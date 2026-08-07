from llm_platform.common.enums import BackendState


class BackendStateMachine:
    ALLOWED: dict[BackendState, frozenset[BackendState]] = {
        BackendState.STOPPED: frozenset({BackendState.ALLOCATING}),
        BackendState.ALLOCATING: frozenset({BackendState.STARTING, BackendState.FAILED}),
        BackendState.STARTING: frozenset({BackendState.WARMING, BackendState.FAILED}),
        BackendState.WARMING: frozenset({BackendState.READY, BackendState.FAILED}),
        BackendState.READY: frozenset(
            {BackendState.DRAINING, BackendState.DEGRADED, BackendState.FAILED}
        ),
        BackendState.DRAINING: frozenset(
            {BackendState.SLEEPING, BackendState.STOPPING, BackendState.READY, BackendState.TIMEOUT}
        ),
        BackendState.SLEEPING: frozenset(
            {BackendState.WARMING, BackendState.STOPPING, BackendState.FAILED}
        ),
        BackendState.STOPPING: frozenset({BackendState.STOPPED, BackendState.FAILED}),
        BackendState.DEGRADED: frozenset({BackendState.DRAINING, BackendState.STOPPING}),
        BackendState.FAILED: frozenset({BackendState.STOPPING, BackendState.ALLOCATING}),
        BackendState.ORPHANED: frozenset({BackendState.STOPPING}),
        BackendState.TIMEOUT: frozenset({BackendState.READY, BackendState.STOPPING}),
    }

    @classmethod
    def transition(cls, current: BackendState, target: BackendState) -> BackendState:
        if target is current:
            return current
        if target not in cls.ALLOWED.get(current, frozenset()):
            raise ValueError(f"invalid backend transition: {current} -> {target}")
        return target
