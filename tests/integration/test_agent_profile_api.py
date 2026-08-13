from datetime import UTC, datetime
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
from llm_platform.common.enums import SkillName
from llm_platform.gateway.app import create_app
from llm_platform.gateway.service import DeploymentRegistry, GatewayService
from llm_platform.persistence.database import Database
from llm_platform.persistence.models import ModelRow, UserRow
from llm_platform.persistence.skills import ModelSkillRepository
from llm_platform.routing.router import RuleRouter

SHUNTA_KEY = "shunta-profile-api-key-with-entropy"
YUTO_KEY = "yuto-profile-api-key-with-entropy"


async def build_profile_app(model_factory: Any, weights: Any) -> tuple[Any, Database]:
    qwen = model_factory("qwen", family="qwen")
    deepseek = model_factory("deepseek", family="deepseek", enabled=False)
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema_for_tests()
    async with database.session() as session:
        for user_id, permissions in (
            ("shunta", ["qwen"]),
            ("yuto", ["qwen", "deepseek"]),
        ):
            session.add(
                UserRow(
                    id=user_id,
                    linux_username=user_id,
                    display_name=user_id.title(),
                    model_permissions=permissions,
                )
            )
        for model in (qwen, deepseek):
            session.add(
                ModelRow(
                    id=model.model_id,
                    family=model.family,
                    revision=model.revision,
                    capabilities=model.capabilities.model_dump(),
                    license=model.license,
                    enabled=model.enabled,
                )
            )
        await session.commit()
        await ModelSkillRepository(session).record(
            model_id="qwen",
            skill=SkillName.CODING,
            benchmark="global-coding",
            score=0.70,
            sample_count=400,
            confidence=0.95,
        )
    service = GatewayService(
        RuleRouter([qwen, deepseek], [], weights),
        DeploymentRegistry(),
        [qwen, deepseek],
        database_sessions=database.sessions,
    )
    store = InMemoryKeyStore(
        [
            KeyRecord(
                "shunta-key",
                key_prefix(SHUNTA_KEY),
                hash_api_key(SHUNTA_KEY),
                ApiPrincipal("shunta", frozenset({"inference"}), frozenset({"qwen"})),
            ),
            KeyRecord(
                "yuto-key",
                key_prefix(YUTO_KEY),
                hash_api_key(YUTO_KEY),
                ApiPrincipal(
                    "yuto",
                    frozenset({"inference"}),
                    frozenset({"qwen", "deepseek"}),
                ),
            ),
        ]
    )
    return create_app(service, store), database


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def create_profile(client: httpx.AsyncClient, key: str, version: str) -> str:
    response = await client.post(
        "/v1/agent-profiles",
        headers=auth(key),
        json={
            "harness_name": "custom-agent",
            "harness_version": version,
            "config_hash": ("a" if key == SHUNTA_KEY else "b") * 64,
            "toolset_hash": "c" * 64,
            "metadata": {"label": f"version-{version}"},
        },
    )
    assert response.status_code == 201
    assert "metadata" not in response.json()
    return str(response.json()["id"])


async def submit(
    client: httpx.AsyncClient,
    key: str,
    profile_id: str,
    score: float,
    *,
    model_id: str = "qwen",
    idempotency_key: str | None = None,
) -> httpx.Response:
    headers = auth(key)
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return await client.post(
        "/v1/model-skill-evaluations",
        headers=headers,
        json={
            "agent_profile_id": profile_id,
            "model_id": model_id,
            "skill": "coding",
            "benchmark": "agent-bench",
            "score": score,
            "sample_count": 100,
            "confidence": 0.9,
            "raw_metrics": {"passed": int(score * 100)},
            "measured_at": datetime(2026, 8, 13, tzinfo=UTC).isoformat(),
        },
    )


async def coding_score(
    client: httpx.AsyncClient, key: str, profile_id: str | None = None
) -> tuple[float | None, str]:
    headers = auth(key)
    if profile_id is not None:
        headers["X-Agent-Profile-Id"] = profile_id
    response = await client.get("/v1/model-capabilities", headers=headers)
    assert response.status_code == 200
    qwen = next(model for model in response.json()["models"] if model["id"] == "qwen")
    return qwen["skills"]["coding"]["score"], qwen["skills"]["coding"]["source"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_user_scoped_dynamic_profiles_without_gateway_restart(
    model_factory: Any, weights: Any
) -> None:
    app, database = await build_profile_app(model_factory, weights)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        shunta_v1 = await create_profile(client, SHUNTA_KEY, "1")
        shunta_v2 = await create_profile(client, SHUNTA_KEY, "2")
        yuto_v1 = await create_profile(client, YUTO_KEY, "1")
        assert (await submit(client, SHUNTA_KEY, shunta_v1, 0.82)).status_code == 201
        assert (await submit(client, YUTO_KEY, yuto_v1, 0.61)).status_code == 201

        score, source = await coding_score(client, SHUNTA_KEY, shunta_v1)
        assert score == pytest.approx(0.82)
        assert source == "agent_profile"
        score, source = await coding_score(client, YUTO_KEY, yuto_v1)
        assert score == pytest.approx(0.61)
        assert source == "agent_profile"
        score, source = await coding_score(client, SHUNTA_KEY)
        assert score == pytest.approx(0.70)
        assert source == "global"
        score, source = await coding_score(client, SHUNTA_KEY, shunta_v2)
        assert score == pytest.approx(0.70)
        assert source == "global"

        first = await submit(client, SHUNTA_KEY, shunta_v2, 0.90, idempotency_key="shunta-v2-run")
        retry = await submit(client, SHUNTA_KEY, shunta_v2, 0.90, idempotency_key="shunta-v2-run")
        assert first.status_code == 201
        assert retry.status_code == 200
        assert retry.json()["id"] == first.json()["id"]
        score, source = await coding_score(client, SHUNTA_KEY, shunta_v2)
        assert score == pytest.approx(0.90)
        assert source == "agent_profile"

    async with database.session() as session:
        history = await ModelSkillRepository(session).history("qwen", agent_profile_id=shunta_v1)
        assert len(history) == 1
        assert history[0].score == pytest.approx(0.82)
    await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_profile_api_enforces_ownership_and_model_permissions(
    model_factory: Any, weights: Any
) -> None:
    app, database = await build_profile_app(model_factory, weights)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        shunta_profile = await create_profile(client, SHUNTA_KEY, "1")
        yuto_profile = await create_profile(client, YUTO_KEY, "1")
        await submit(client, YUTO_KEY, yuto_profile, 0.61)

        cross_read = await client.get(
            f"/v1/agent-profiles/{yuto_profile}", headers=auth(SHUNTA_KEY)
        )
        cross_write = await submit(client, SHUNTA_KEY, yuto_profile, 0.99)
        cross_capability = await client.get(
            "/v1/model-capabilities",
            headers={**auth(SHUNTA_KEY), "X-Agent-Profile-Id": yuto_profile},
        )
        missing = await client.get(
            "/v1/model-capabilities",
            headers={**auth(SHUNTA_KEY), "X-Agent-Profile-Id": "ap-missing"},
        )
        forbidden_model = await submit(client, SHUNTA_KEY, shunta_profile, 0.8, model_id="deepseek")
        global_write = await client.post(
            "/v1/model-skill-evaluations",
            headers=auth(SHUNTA_KEY),
            json={
                "model_id": "qwen",
                "skill": "coding",
                "benchmark": "forbidden-global",
                "score": 1,
                "sample_count": 1,
                "confidence": 1,
                "measured_at": datetime.now(UTC).isoformat(),
            },
        )
        listed = await client.get("/v1/agent-profiles", headers=auth(SHUNTA_KEY))
        catalog = await client.get("/v1/model-capabilities", headers=auth(SHUNTA_KEY))

    assert cross_read.status_code == 403
    assert cross_write.status_code == 403
    assert cross_capability.status_code == 403
    assert missing.status_code == 404
    assert forbidden_model.status_code == 403
    assert global_write.status_code == 422
    assert [profile["id"] for profile in listed.json()["profiles"]] == [shunta_profile]
    assert [model["id"] for model in catalog.json()["models"]] == ["qwen"]
    assert "deepseek" not in catalog.text.lower()
    assert "0.61" not in catalog.text
    await database.dispose()
