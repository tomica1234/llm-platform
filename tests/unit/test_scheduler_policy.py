from dataclasses import dataclass

from llm_platform.scheduler.policy import CircuitBreaker, SwitchGuard


@dataclass
class FakeClock:
    now: float = 0

    def __call__(self) -> float:
        return self.now


def test_switch_guard_dwell_cost_and_rate_without_sleep() -> None:
    clock = FakeClock()
    guard = SwitchGuard(120, 2, clock=clock)
    assert not guard.allow(expected_savings_seconds=10, load_cost_seconds=10)
    assert guard.allow(expected_savings_seconds=20, load_cost_seconds=10)
    guard.record()
    clock.now = 100
    assert not guard.allow(expected_savings_seconds=20, load_cost_seconds=10)
    clock.now = 120
    assert guard.allow(expected_savings_seconds=20, load_cost_seconds=10)
    guard.record()
    clock.now = 300
    assert not guard.allow(expected_savings_seconds=20, load_cost_seconds=10)
    clock.now = 601
    assert guard.allow(expected_savings_seconds=20, load_cost_seconds=10)


def test_circuit_breaker_stops_restart_loop_and_recovers_after_cooldown() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(3, 60, clock)
    assert not breaker.record_failure("bad")
    assert not breaker.record_failure("bad")
    assert breaker.record_failure("bad")
    assert not breaker.allow_attempt("bad")
    clock.now = 60
    assert breaker.allow_attempt("bad")
    breaker.record_success("bad")
    assert breaker.failures("bad") == 0
