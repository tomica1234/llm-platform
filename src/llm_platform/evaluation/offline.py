from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Outcome:
    deployment_id: str
    success: bool
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    count: int
    success_rate: float
    mean_elapsed_seconds: float
    deployment_counts: Mapping[str, int]
    collapse_detected: bool


def evaluate(outcomes: Iterable[Outcome], *, collapse_threshold: float = 0.95) -> EvaluationReport:
    values = list(outcomes)
    if not values:
        return EvaluationReport(0, 0, 0, {}, False)
    counts: dict[str, int] = {}
    for outcome in values:
        counts[outcome.deployment_id] = counts.get(outcome.deployment_id, 0) + 1
    largest_share = max(counts.values()) / len(values)
    return EvaluationReport(
        len(values),
        sum(outcome.success for outcome in values) / len(values),
        sum(outcome.elapsed_seconds for outcome in values) / len(values),
        counts,
        largest_share >= collapse_threshold and len(counts) > 1,
    )
