import sys
from pathlib import Path

import pytest

from llm_platform.agent_harness.features import extract_features
from llm_platform.agent_harness.state import AgentTaskState, TaskStateStore
from llm_platform.agent_harness.workflow import AgentWorkflow
from llm_platform.agent_harness.workspace import SafeWorkspace
from llm_platform.common.enums import AgentPhase


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discover_to_finalize_and_restart_state(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    source = repository / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    state_store = TaskStateStore(tmp_path / "state")
    state = AgentTaskState("task-1", str(repository), "implement and review example")
    state_store.save(state)
    workflow = AgentWorkflow(state, state_store)
    workspace = SafeWorkspace(repository, allow_in_place=True)

    assert workspace.list_files() == ["example.py"]
    workflow.transition(AgentPhase.PLAN)
    state.plan = ["change example", "test", "review"]
    workflow.transition(AgentPhase.IMPLEMENT)
    import hashlib

    old = workspace.read_text("example.py")
    workspace.apply_replacement(
        "example.py",
        expected_sha256=hashlib.sha256(old.encode()).hexdigest(),
        old="value = 1",
        new="value = 2",
    )
    workflow.transition(AgentPhase.TEST)
    result = await workspace.run([sys.executable, "-m", "py_compile", "example.py"])
    assert workflow.record_test(list(result.argv), result.returncode, result.stderr)
    workflow.transition(AgentPhase.REVIEW)
    features = extract_features(repository, state, ["example.py"])
    assert features.languages == ("python",)
    workflow.transition(AgentPhase.FINALIZE)

    restored = state_store.load("task-1")
    assert restored.phase is AgentPhase.FINALIZE
    assert restored.status == "complete"
    assert restored.test_history


@pytest.mark.integration
def test_repeated_failure_escalates(tmp_path: Path) -> None:
    store = TaskStateStore(tmp_path / "state")
    state = AgentTaskState("task-2", str(tmp_path), "fix")
    workflow = AgentWorkflow(state, store)
    for _ in range(3):
        workflow.record_test(["pytest"], 1, "same failure")
    assert state.model == "auto/quality"
    assert "ESCALATED_AFTER_TEST_FAILURE" in state.route_reasons
