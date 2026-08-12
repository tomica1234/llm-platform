from llm_platform.agent_harness.state import AgentTaskState, TaskStateStore
from llm_platform.common.enums import AgentPhase


class AgentWorkflow:
    ORDER = (
        AgentPhase.DISCOVER,
        AgentPhase.PLAN,
        AgentPhase.IMPLEMENT,
        AgentPhase.TEST,
        AgentPhase.DEBUG,
        AgentPhase.REVIEW,
        AgentPhase.FINALIZE,
    )

    def __init__(self, state: AgentTaskState, store: TaskStateStore) -> None:
        self.state = state
        self.store = store

    def transition(self, target: AgentPhase) -> None:
        current = self.state.phase
        allowed = {
            AgentPhase.DISCOVER: {AgentPhase.PLAN},
            AgentPhase.PLAN: {AgentPhase.IMPLEMENT},
            AgentPhase.IMPLEMENT: {AgentPhase.TEST},
            AgentPhase.TEST: {AgentPhase.DEBUG, AgentPhase.REVIEW},
            AgentPhase.DEBUG: {AgentPhase.IMPLEMENT, AgentPhase.REVIEW},
            AgentPhase.REVIEW: {AgentPhase.IMPLEMENT, AgentPhase.FINALIZE},
            AgentPhase.FINALIZE: set(),
        }
        if target not in allowed[current]:
            raise ValueError(f"invalid agent phase transition: {current} -> {target}")
        self.state.phase = target
        if target is AgentPhase.FINALIZE:
            self.state.status = "complete"
        self.store.save(self.state)

    def record_test(self, command: list[str], returncode: int, output_summary: str) -> bool:
        previous = self.state.test_history[-1] if self.state.test_history else None
        failure_signature = (tuple(command), output_summary)
        previous_signature = None
        if previous is not None:
            previous_signature = (tuple(previous["command"]), previous["output_summary"])
        if returncode != 0 and failure_signature == previous_signature:
            self.state.repeated_failures += 1
        elif returncode == 0:
            self.state.repeated_failures = 0
        self.state.test_history.append(
            {"command": command, "returncode": returncode, "output_summary": output_summary}
        )
        if self.state.repeated_failures >= 2 and not self.state.model.startswith("force/"):
            self.state.model = "auto/strong"
            self.state.route_reasons.append("ESCALATED_AFTER_TEST_FAILURE")
        self.store.save(self.state)
        return returncode == 0
