from typing import Any

import pytest

from llm_platform.common.enums import BackendState, RuntimeKind
from llm_platform.config.schema import GpuProfile
from llm_platform.scheduler.planner import ResourcePlanner, choose_profile
from llm_platform.scheduler.state_machine import BackendStateMachine


def test_state_machine_happy_path_and_invalid_transition() -> None:
    state = BackendState.STOPPED
    for target in (
        BackendState.ALLOCATING,
        BackendState.STARTING,
        BackendState.WARMING,
        BackendState.READY,
        BackendState.DRAINING,
        BackendState.STOPPING,
        BackendState.STOPPED,
    ):
        state = BackendStateMachine.transition(state, target)
    with pytest.raises(ValueError):
        BackendStateMachine.transition(BackendState.READY, BackendState.STOPPED)


def test_profile_planner_protects_non_preemptible_job(deployment_factory: Any) -> None:
    large = deployment_factory(
        "large", model_id="dvf", runtime=RuntimeKind.LLAMA_CPP, gpus=3, port=8101
    )
    profiles = [GpuProfile(name="strong-shared", deployments=["large"])]
    planner = ResourcePlanner([large], profiles)
    blocked = planner.plan("strong-shared", set(), total_gpus=3, protected_gpus=1)
    assert blocked.blocked_by_protected_job
    assert not blocked.start


def test_profile_selection_coalesces_large_model() -> None:
    assert choose_profile(["dvf", "dvf"]) == "strong-shared"
    assert choose_profile(["dvf", "qwen"]) == "balanced"
    assert choose_profile(["qwen"]) == "implementation-burst"
    assert choose_profile([]) == "idle"
