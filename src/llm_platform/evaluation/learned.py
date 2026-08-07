from collections.abc import Mapping
from typing import Protocol


class LearnedRouter(Protocol):
    """A scorer only; hard constraints and manual force are applied before this hook."""

    def scores(
        self, features: Mapping[str, float], deployment_ids: tuple[str, ...]
    ) -> Mapping[str, float]: ...


class BaselineLearnedRouter:
    def scores(
        self, features: Mapping[str, float], deployment_ids: tuple[str, ...]
    ) -> Mapping[str, float]:
        del features
        return {deployment_id: 0.0 for deployment_id in deployment_ids}


def assignment_bucket(task_id: str, experiment: str, buckets: int = 100) -> int:
    import hashlib

    digest = hashlib.sha256(f"{experiment}:{task_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % buckets
