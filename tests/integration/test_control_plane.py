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
