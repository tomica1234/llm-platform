import asyncio
from typing import Any

import pytest

from llm_platform.common.enums import RuntimeKind
from llm_platform.config.schema import GpuProfile
from llm_platform.orchestrator.reconciler import Reconciler
from llm_platform.runtimes.fake import FakeRuntimeAdapter
from llm_platform.scheduler.planner import ResourcePlanner
from llm_platform.slurm.fake import FakeSlurmAdapter


@pytest.mark.integration
@pytest.mark.asyncio
async def test_balanced_to_three_gpu_shared_after_drain(deployment_factory: Any) -> None:
    large_two = deployment_factory(
        "large-two", model_id="dvf", runtime=RuntimeKind.LLAMA_CPP, gpus=2, port=8101
    )
    small = deployment_factory("small", model_id="qwen", gpus=1, port=8201)
    shared = deployment_factory(
        "large-shared", model_id="dvf", runtime=RuntimeKind.LLAMA_CPP, gpus=3, port=8102
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
async def test_non_preemptible_job_blocks_transition(deployment_factory: Any) -> None:
    shared = deployment_factory(
        "large-shared", model_id="dvf", runtime=RuntimeKind.LLAMA_CPP, gpus=3, port=8102
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
