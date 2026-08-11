import asyncio
from pathlib import Path
from typing import Any

import pytest

from llm_platform.common.enums import BackendState, RuntimeKind
from llm_platform.config.schema import GpuProfile
from llm_platform.gateway.service import DeploymentRegistry
from llm_platform.orchestrator.control_plane import ControlPlane
from llm_platform.orchestrator.reconciler import Reconciler
from llm_platform.persistence.database import Database
from llm_platform.persistence.models import ControlPlaneStateRow, InferenceRequestRow
from llm_platform.runtimes.llama_cpp import LlamaCppAdapter
from llm_platform.scheduler.planner import ResourcePlanner
from llm_platform.slurm.fake import FakeSlurmAdapter


class HealthyHttpClient:
    async def get_health(self, base_url: str) -> bool:
        del base_url
        return True


class UnavailableReconciler:
    def __init__(self, deployment_id: str) -> None:
        self.deployments = {deployment_id: object()}
        self.instances: dict[str, object] = {}
        self.reconcile_started = asyncio.Event()

    async def recover(self) -> tuple[str, ...]:
        return ()

    async def reconcile(self, plan: object) -> None:
        del plan
        self.reconcile_started.set()
        await asyncio.Event().wait()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_queued_request_starts_slurm_managed_backend_and_persists_metadata(
    deployment_factory: Any, tmp_path: Path
) -> None:
    deployment = deployment_factory(
        "llama-one", model_id="dvf", runtime=RuntimeKind.LLAMA_CPP, port=8111
    )
    profile = GpuProfile(name="balanced", deployments=[deployment.deployment_id])
    registry = DeploymentRegistry()
    slurm = FakeSlurmAdapter()
    adapter = LlamaCppAdapter(http_client=HealthyHttpClient())  # type: ignore[arg-type]
    reconciler = Reconciler(
        {deployment.deployment_id: deployment},
        {deployment.deployment_id: adapter},
        slurm,
        registry=registry,
        slurm_managed_runtime=True,
        health_timeout=1,
        script_directory=tmp_path,
    )
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema_for_tests()
    controller = ControlPlane(
        reconciler,
        ResourcePlanner([deployment], [profile, GpuProfile(name="idle", deployments=[])]),
        [profile, GpuProfile(name="idle", deployments=[])],
        database.sessions,
        interval_seconds=0.01,
    )
    await controller.start()
    try:
        await controller.wait_for_deployment(
            deployment.deployment_id,
            "request-1",
            "user-1",
            "force/dvf",
            {"model": "force/dvf", "input": "not persisted"},
            timeout_seconds=2,
        )
        instance = registry.instances[deployment.deployment_id]
        assert instance.state is BackendState.READY
        assert instance.process_id is None
        await controller.request_started("request-1", deployment.deployment_id)
        await controller.request_finished("request-1")
        async with database.session() as session:
            row = await session.get(InferenceRequestRow, "request-1")
            assert row is not None
            assert row.state == "completed"
            assert "not persisted" not in repr(row.__dict__)
            state = await session.get(ControlPlaneStateRow, "singleton")
            assert state is not None
            assert state.desired_profile == "balanced"
    finally:
        await controller.stop()
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_shutdown_cancels_backend_wait_and_terminalizes_request(
    deployment_factory: Any, tmp_path: Path
) -> None:
    deployment = deployment_factory("unavailable", model_id="dvf")
    profile = GpuProfile(name="needed", deployments=[deployment.deployment_id])
    idle = GpuProfile(name="idle", deployments=[])
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'shutdown.db'}")
    await database.create_schema_for_tests()
    reconciler = UnavailableReconciler(deployment.deployment_id)
    controller = ControlPlane(
        reconciler,  # type: ignore[arg-type]
        ResourcePlanner([deployment], [profile, idle]),
        [profile, idle],
        database.sessions,
        interval_seconds=60,
    )
    await controller.start()
    request = asyncio.create_task(
        controller.wait_for_deployment(
            deployment.deployment_id,
            "request-shutdown",
            "user-1",
            "force/unavailable",
            {"model": "force/unavailable"},
            timeout_seconds=600,
        )
    )
    try:
        await asyncio.wait_for(reconciler.reconcile_started.wait(), timeout=1)
        await asyncio.wait_for(controller._wake.wait(), timeout=1)
        assert controller.queue.position("request-shutdown") == 0

        await asyncio.wait_for(controller.stop(), timeout=1)

        assert request.cancelled()
        assert controller._task is None
        async with database.session() as session:
            row = await session.get(InferenceRequestRow, "request-shutdown")
            assert row is not None
            assert row.state == "cancelled"
            assert row.error_code == "gateway_shutdown"
            assert row.completed_at is not None

        await asyncio.wait_for(controller.stop(), timeout=1)
    finally:
        if not request.done():
            request.cancel()
        await controller.stop()
        await database.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_startup_recovery_attaches_healthy_existing_job(
    deployment_factory: Any, tmp_path: Path
) -> None:
    deployment = deployment_factory(
        "llama-recovered", model_id="dvf", runtime=RuntimeKind.LLAMA_CPP, port=8112
    )
    slurm = FakeSlurmAdapter()
    job = await slurm.submit_backend(deployment, "existing-instance", tmp_path / "unused")
    registry = DeploymentRegistry()
    adapter = LlamaCppAdapter(http_client=HealthyHttpClient())  # type: ignore[arg-type]
    reconciler = Reconciler(
        {deployment.deployment_id: deployment},
        {deployment.deployment_id: adapter},
        slurm,
        registry=registry,
        slurm_managed_runtime=True,
        health_timeout=1,
    )

    assert await reconciler.recover() == ()
    instance = registry.instances[deployment.deployment_id]
    assert instance.instance_id == "existing-instance"
    assert instance.allocation_id == job.job_id
    assert instance.state is BackendState.READY
