from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(slots=True)
class SwitchGuard:
    minimum_dwell_seconds: float
    max_switches_per_window: int
    window_seconds: float = 600
    clock: Callable[[], float] = field(default=lambda: 0.0)
    last_switch_at: float | None = None
    _switches: deque[float] = field(default_factory=deque)

    def allow(self, *, expected_savings_seconds: float, load_cost_seconds: float) -> bool:
        now = self.clock()
        while self._switches and self._switches[0] <= now - self.window_seconds:
            self._switches.popleft()
        if expected_savings_seconds <= load_cost_seconds:
            return False
        if (
            self.last_switch_at is not None
            and now - self.last_switch_at < self.minimum_dwell_seconds
        ):
            return False
        return len(self._switches) < self.max_switches_per_window

    def record(self) -> None:
        now = self.clock()
        self.last_switch_at = now
        self._switches.append(now)


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_seconds: float = 300
    clock: Callable[[], float] = field(default=lambda: 0.0)
    _failures: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _opened_at: dict[str, float] = field(default_factory=dict)

    def record_failure(self, deployment_id: str) -> bool:
        self._failures[deployment_id] += 1
        if self._failures[deployment_id] >= self.failure_threshold:
            self._opened_at[deployment_id] = self.clock()
            return True
        return False

    def record_success(self, deployment_id: str) -> None:
        self._failures.pop(deployment_id, None)
        self._opened_at.pop(deployment_id, None)

    def allow_attempt(self, deployment_id: str) -> bool:
        opened_at = self._opened_at.get(deployment_id)
        if opened_at is None:
            return True
        return self.clock() - opened_at >= self.cooldown_seconds

    def failures(self, deployment_id: str) -> int:
        return self._failures.get(deployment_id, 0)
