import asyncio
import signal
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn

from llm_platform.auth.keys import (
    ApiPrincipal,
    InMemoryKeyStore,
    KeyRecord,
    hash_api_key,
    key_prefix,
)
from llm_platform.config.schema import GpuProfile
from llm_platform.gateway.app import create_app
from llm_platform.gateway.main import GatewayServer
from llm_platform.gateway.service import DeploymentRegistry, GatewayService
from llm_platform.orchestrator.control_plane import ControlPlane
from llm_platform.persistence.database import Database
from llm_platform.persistence.models import InferenceRequestRow
from llm_platform.persistence.repositories import RequestRepository
from llm_platform.routing.router import RuleRouter
from llm_platform.scheduler.planner import ResourcePlanner

API_KEY = "shutdown-integration-key-with-enough-entropy"


class UnavailableReconciler:
    def __init__(self, deployment_id: str) -> None:
        self.deployments = {deployment_id: object()}
        self.instances: dict[str, object] = {}

    async def recover(self) -> tuple[str, ...]:
        return ()

    async def reconcile(self, plan: object) -> None:
        del plan
        await asyncio.Event().wait()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_server_shutdown_terminalizes_backend_wait(
    model_factory: Any,
    deployment_factory: Any,
    weights: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = model_factory("shutdown-model")
    deployment = deployment_factory("shutdown-unavailable", model_id=model.model_id)
    profile = GpuProfile(name="needed", deployments=[deployment.deployment_id])
    idle = GpuProfile(name="idle", deployments=[])
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'server-shutdown.db'}")
    await database.create_schema_for_tests()
    reconciler = UnavailableReconciler(deployment.deployment_id)
    control_plane = ControlPlane(
        reconciler,  # type: ignore[arg-type]
        ResourcePlanner([deployment], [profile, idle]),
        [profile, idle],
        database.sessions,
        interval_seconds=60,
        cleanup_timeout_seconds=1,
    )
    service = GatewayService(
        RuleRouter([model], [deployment], weights),
        DeploymentRegistry(),
        [model],
        request_timeout_seconds=600,
        control_plane=control_plane,
    )
    store = InMemoryKeyStore(
        [
            KeyRecord(
                "shutdown-key",
                key_prefix(API_KEY),
                hash_api_key(API_KEY),
                ApiPrincipal(
                    "shutdown-user",
                    frozenset({"inference"}),
                    frozenset({model.model_id}),
                ),
            )
        ]
    )
    started = asyncio.Event()

    async def startup() -> None:
        await control_plane.start()
        started.set()

    async def shutdown() -> None:
        await control_plane.stop()
        await database.dispose()

    app = create_app(service, store, startup=startup, shutdown=shutdown)
    app.state.control_plane = control_plane
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = GatewayServer(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            timeout_graceful_shutdown=1,
        )
    )
    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    request_id = "request-real-server-shutdown"
    original_transition = RequestRepository.transition

    async def delayed_terminalization(
        repository: RequestRepository,
        actual_request_id: str,
        from_states: set[str],
        target: str,
        **kwargs: Any,
    ) -> bool:
        if actual_request_id == request_id and target == "cancelled":
            await asyncio.sleep(0.2)
        return await original_transition(
            repository, actual_request_id, from_states, target, **kwargs
        )

    monkeypatch.setattr(RequestRepository, "transition", delayed_terminalization)
    request_task: asyncio.Task[httpx.Response] | None = None
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.sleep(0.05)
        async with httpx.AsyncClient(timeout=10) as client:
            request_task = asyncio.create_task(
                client.post(
                    f"http://127.0.0.1:{port}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {API_KEY}",
                        "X-Request-ID": request_id,
                    },
                    json={
                        "model": f"force-deployment/{deployment.deployment_id}",
                        "messages": [],
                    },
                )
            )
            await asyncio.wait_for(control_plane._wake.wait(), timeout=1)
            assert control_plane.queue.position(request_id) == 0

            server.handle_exit(signal.SIGTERM, None)
            server._captured_signals.clear()
            await asyncio.wait_for(server_task, timeout=2)
            await asyncio.wait_for(asyncio.gather(request_task, return_exceptions=True), timeout=1)

        assert request_task.done()
        assert control_plane._task is None
        async with database.session() as session:
            row = await session.get(InferenceRequestRow, request_id)
            assert row is not None
            assert row.state == "cancelled"
            assert row.error_code == "gateway_shutdown"
            assert row.completed_at is not None
    finally:
        if request_task is not None and not request_task.done():
            request_task.cancel()
        if not server_task.done():
            server.should_exit = True
            await server_task
        listener.close()
        await control_plane.stop()
        await database.dispose()
