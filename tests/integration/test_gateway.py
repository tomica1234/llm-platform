from typing import Any

import httpx
import pytest

from llm_platform.auth.keys import (
    ApiPrincipal,
    InMemoryKeyStore,
    KeyRecord,
    hash_api_key,
    key_prefix,
)
from llm_platform.common.enums import BackendState
from llm_platform.common.errors import PlatformError
from llm_platform.gateway.app import create_app
from llm_platform.gateway.service import ConcurrencyLimiter, DeploymentRegistry, GatewayService
from llm_platform.routing.router import RuleRouter
from llm_platform.runtimes.base import RuntimeInstance
from llm_platform.runtimes.fake import FakeRuntimeAdapter

API_KEY = "integration-key-with-enough-entropy"
ADMIN_KEY = "integration-admin-key-with-enough-entropy"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_per_user_concurrency_limit() -> None:
    limiter = ConcurrencyLimiter()
    principal = ApiPrincipal(
        "alice", frozenset({"inference"}), frozenset({"qwen"}), max_concurrency=1
    )
    async with limiter.slot(principal):
        with pytest.raises(PlatformError) as error:
            async with limiter.slot(principal):
                pass
    assert error.value.status_code == 429


def make_app(model_factory: Any, deployment_factory: Any, weights: Any) -> Any:
    llama_model = model_factory("example-model-a", family="deepseek", quality=0.9)
    vllm_model = model_factory("qwen", family="qwen", quality=0.7)
    from llm_platform.common.enums import RuntimeKind

    llama = deployment_factory(
        "example-model-a-llama",
        model_id="example-model-a",
        runtime=RuntimeKind.LLAMA_CPP,
        gpus=2,
        port=8101,
    )
    vllm = deployment_factory("qwen-vllm", model_id="qwen", port=8201)
    router = RuleRouter([llama_model, vllm_model], [llama, vllm], weights)
    registry = DeploymentRegistry()
    for deployment in (llama, vllm):
        adapter = FakeRuntimeAdapter()
        instance = RuntimeInstance(
            f"instance-{deployment.deployment_id}",
            deployment.deployment_id,
            f"http://127.0.0.1:{deployment.serving.port}",
            BackendState.READY,
        )
        registry.register(deployment.deployment_id, adapter, instance)
    service = GatewayService(router, registry, [llama_model, vllm_model])
    principal = ApiPrincipal(
        "alice", frozenset({"inference"}), frozenset({"example-model-a", "qwen"}), 1
    )
    store = InMemoryKeyStore(
        [
            KeyRecord("key", key_prefix(API_KEY), hash_api_key(API_KEY), principal),
            KeyRecord(
                "admin-key",
                key_prefix(ADMIN_KEY),
                hash_api_key(ADMIN_KEY),
                ApiPrincipal(
                    "admin",
                    frozenset({"inference", "admin"}),
                    frozenset({"example-model-a", "qwen"}),
                ),
            ),
        ]
    )
    return create_app(service, store)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_responses_and_force_runtime(
    model_factory: Any, deployment_factory: Any, weights: Any
) -> None:
    app = make_app(model_factory, deployment_factory, weights)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "model": "force/example-model-a@llama_cpp",
                "input": "hello",
                "benign_future_field": {"preserved": True},
            },
        )
    assert response.status_code == 200
    assert response.json()["object"] == "response"
    assert response.headers["x-selected-runtime"] == "llama_cpp"
    assert response.headers["x-selected-deployment"] == "example-model-a-llama"
    assert response.headers["x-request-id"].startswith("req-")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_streaming_and_models(
    model_factory: Any, deployment_factory: Any, weights: Any
) -> None:
    app = make_app(model_factory, deployment_factory, weights)
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        models = await client.get("/v1/models", headers=headers)
        response = await client.post(
            "/v1/chat/completions",
            headers=headers,
            json={"model": "force-deployment/qwen-vllm", "messages": [], "stream": True},
        )
    assert models.status_code == 200
    assert {item["id"] for item in models.json()["data"]} == {"example-model-a", "qwen"}
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.content.endswith(b"data: [DONE]\n\n")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auth_admin_and_unavailable_errors(
    model_factory: Any, deployment_factory: Any, weights: Any
) -> None:
    app = make_app(model_factory, deployment_factory, weights)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthenticated = await client.get("/v1/models")
        admin = await client.get("/admin/status", headers={"Authorization": f"Bearer {API_KEY}"})
        unavailable = await client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"model": "force/missing", "input": "x"},
        )
    assert unauthenticated.status_code == 401
    assert admin.status_code == 403
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["retryable"] is True
    assert "fallback" in unavailable.json()["error"]["message"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_can_explain_route(
    model_factory: Any, deployment_factory: Any, weights: Any
) -> None:
    app = make_app(model_factory, deployment_factory, weights)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        inference = await client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"model": "force-deployment/qwen-vllm", "input": "hello"},
        )
        explained = await client.get(
            f"/admin/routes/{inference.headers['x-request-id']}",
            headers={"Authorization": f"Bearer {ADMIN_KEY}"},
        )
    assert explained.status_code == 200
    assert explained.json()["deployment"] == "qwen-vllm"
    assert "MANUAL_FORCE" in explained.json()["reason_codes"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_ready_metrics(
    model_factory: Any, deployment_factory: Any, weights: Any
) -> None:
    app = make_app(model_factory, deployment_factory, weights)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/ready")).status_code == 200
        metrics = await client.get("/metrics")
    assert metrics.status_code == 200
    assert "llm_platform_requests_total" in metrics.text
