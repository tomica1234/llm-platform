import asyncio
from typing import Any

import pytest

from llm_platform.common.enums import RuntimeKind
from llm_platform.config.schema import GpuProfile
from llm_platform.orchestrator.reconciler import Reconciler
from llm_platform.runtimes.fake import FakeRuntimeAdapter
from llm_platform.runtimes.llama_cpp import LlamaCppAdapter
from llm_platform.scheduler.planner import ProfilePlan, ResourcePlanner
from llm_platform.slurm.base import SlurmJob, SlurmJobState
from llm_platform.slurm.fake import FakeSlurmAdapter


class FailingSlurmAdapter(FakeSlurmAdapter):
    async def submit_backend(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise RuntimeError("sbatch failed: Invalid qos specification")


class ImmediatelyFailingSlurmAdapter(FakeSlurmAdapter):
    async def submit_backend(self, *args: Any, **kwargs: Any) -> SlurmJob:
        job = await super().submit_backend(*args, **kwargs)
        job.state = SlurmJobState.FAILED
        job.exit_code = 1
        return job


class DelayedCancellationSlurmAdapter(FakeSlurmAdapter):
    def __init__(self, inspections_before_gone: int) -> None:
        super().__init__()
        self.inspections_before_gone = inspections_before_gone
        self.cancel_requested = False

    async def cancel(self, job_id: str) -> None:
        if job_id in self.jobs:
            self.cancel_requested = True

    async def inspect(self, job_id: str) -> SlurmJob | None:
        job = self.jobs.get(job_id)
        if job is not None and self.cancel_requested:
            if self.inspections_before_gone == 0:
                self.jobs.pop(job_id)
                return None
            self.inspections_before_gone -= 1
        return job


class UnhealthyHttpClient:
    async def get_health(self, base_url: str) -> bool:
        del base_url
        return False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_balanced_to_three_gpu_shared_after_drain(deployment_factory: Any) -> None:
    large_two = deployment_factory(
        "large-two", model_id="example-model-a", runtime=RuntimeKind.LLAMA_CPP, gpus=2, port=8101
    )
    small = deployment_factory("small", model_id="qwen", gpus=1, port=8201)
    shared = deployment_factory(
        "large-shared", model_id="example-model-a", runtime=RuntimeKind.LLAMA_CPP, gpus=3, port=8102
    )
    deployments = {item.deployment_id: item for item in (large_two, small, shared)}
    profiles = [
        GpuProfile(name="balanced", deployments=["large-two", "small"]),
        GpuProfile(name="strong-shared", deployments=["large-shared"]),
    ]
    planner = ResourcePlanner(deployments.values(), profiles)
    slurm = FakeSlurmAdapter()
    adapters = {deployment_id: FakeRuntimeAdapter() for deployment_id in deployments}
    reconciler = Reconciler(deployments, adapters, slurm, drain_timeout=1)
    first = await reconciler.reconcile(planner.plan("balanced", set()))
    assert set(first.started) == {"large-two", "small"}
    assert slurm.available_gpus() == 0

    active = reconciler.instances["large-two"]
    active.active_requests.add("stream-1")

    async def complete_stream() -> None:
        await asyncio.sleep(0)
        active.active_requests.remove("stream-1")

    completion = asyncio.create_task(complete_stream())
    second = await reconciler.reconcile(planner.plan("strong-shared", set(reconciler.instances)))
    await completion
    assert second.started == ("large-shared",)
    assert set(second.stopped) == {"large-two", "small"}
    assert set(reconciler.instances) == {"large-shared"}
    assert slurm.available_gpus() == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stop_waits_for_cancelled_running_job_to_leave_slurm(
    deployment_factory: Any,
) -> None:
    deployment = deployment_factory("delayed-stop")
    slurm = DelayedCancellationSlurmAdapter(inspections_before_gone=2)
    reconciler = Reconciler(
        {deployment.deployment_id: deployment},
        {deployment.deployment_id: FakeRuntimeAdapter()},
        slurm,
        termination_timeout=1,
        termination_poll_interval=0.001,
    )
    planner = ResourcePlanner(
        [deployment], [GpuProfile(name="running", deployments=[deployment.deployment_id])]
    )
    await reconciler.reconcile(planner.plan("running", set()))

    stopped = await reconciler.reconcile(ProfilePlan("idle", (), (deployment.deployment_id,), ()))

    assert stopped.stopped == (deployment.deployment_id,)
    assert stopped.failures == ()
    assert slurm.jobs == {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stop_timeout_is_reported_and_deployment_is_not_stopped(
    deployment_factory: Any,
) -> None:
    deployment = deployment_factory("stuck-stop")
    slurm = DelayedCancellationSlurmAdapter(inspections_before_gone=100)
    reconciler = Reconciler(
        {deployment.deployment_id: deployment},
        {deployment.deployment_id: FakeRuntimeAdapter()},
        slurm,
        termination_timeout=0.001,
        termination_poll_interval=0.001,
    )
    planner = ResourcePlanner(
        [deployment], [GpuProfile(name="running", deployments=[deployment.deployment_id])]
    )
    await reconciler.reconcile(planner.plan("running", set()))

    stopped = await reconciler.reconcile(ProfilePlan("idle", (), (deployment.deployment_id,), ()))

    assert stopped.stopped == ()
    assert stopped.failures[0].operation == "stop"
    assert "did not release before timeout" in stopped.failures[0].reason
    assert deployment.deployment_id in reconciler.instances


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stop_of_already_gone_slurm_job_is_idempotently_successful(
    deployment_factory: Any,
) -> None:
    deployment = deployment_factory("already-gone")
    slurm = FakeSlurmAdapter()
    reconciler = Reconciler(
        {deployment.deployment_id: deployment},
        {deployment.deployment_id: FakeRuntimeAdapter()},
        slurm,
    )
    planner = ResourcePlanner(
        [deployment], [GpuProfile(name="running", deployments=[deployment.deployment_id])]
    )
    started = await reconciler.reconcile(planner.plan("running", set()))
    job_id = reconciler.instances[deployment.deployment_id].allocation_id
    assert job_id is not None
    slurm.jobs.pop(job_id)

    stopped = await reconciler.reconcile(ProfilePlan("idle", (), (deployment.deployment_id,), ()))

    assert started.started == (deployment.deployment_id,)
    assert stopped.stopped == (deployment.deployment_id,)
    assert stopped.failures == ()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_preemptible_job_blocks_transition(deployment_factory: Any) -> None:
    shared = deployment_factory(
        "large-shared", model_id="example-model-a", runtime=RuntimeKind.LLAMA_CPP, gpus=3, port=8102
    )
    planner = ResourcePlanner(
        [shared], [GpuProfile(name="strong-shared", deployments=["large-shared"])]
    )
    plan = planner.plan("strong-shared", set(), protected_gpus=1)
    slurm = FakeSlurmAdapter()
    reconciler = Reconciler({"large-shared": shared}, {"large-shared": FakeRuntimeAdapter()}, slurm)
    result = await reconciler.reconcile(plan)
    assert result.blocked
    assert not slurm.jobs


@pytest.mark.integration
@pytest.mark.asyncio
async def test_submit_failure_is_reported_by_reconciliation(deployment_factory: Any) -> None:
    deployment = deployment_factory("failed-submit")
    reconciler = Reconciler(
        {deployment.deployment_id: deployment},
        {deployment.deployment_id: FakeRuntimeAdapter()},
        FailingSlurmAdapter(),
    )
    result = await reconciler.reconcile(
        ResourcePlanner(
            [deployment], [GpuProfile(name="failed", deployments=[deployment.deployment_id])]
        ).plan("failed", set())
    )
    assert result.started == ()
    assert result.failures[0].operation == "submit"
    assert "Invalid qos specification" in result.failures[0].reason


@pytest.mark.integration
@pytest.mark.asyncio
async def test_immediate_slurm_job_failure_is_reported_by_reconciliation(
    deployment_factory: Any, tmp_path: Any
) -> None:
    deployment = deployment_factory(
        "failed-start", model_id="example-model-a", runtime=RuntimeKind.LLAMA_CPP
    )
    adapter = LlamaCppAdapter(http_client=UnhealthyHttpClient())  # type: ignore[arg-type]
    slurm = ImmediatelyFailingSlurmAdapter()
    reconciler = Reconciler(
        {deployment.deployment_id: deployment},
        {deployment.deployment_id: adapter},
        slurm,
        slurm_managed_runtime=True,
        script_directory=tmp_path,
    )

    result = await reconciler.reconcile(
        ResourcePlanner(
            [deployment], [GpuProfile(name="failed", deployments=[deployment.deployment_id])]
        ).plan("failed", set())
    )

    assert result.started == ()
    assert result.failures[0].operation == "start"
    assert "terminal state failed" in result.failures[0].reason
    assert reconciler.breaker.failures(deployment.deployment_id) == 1
    assert next(iter(slurm.jobs.values())).state is SlurmJobState.FAILED
