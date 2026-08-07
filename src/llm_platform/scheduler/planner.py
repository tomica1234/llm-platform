from collections.abc import Iterable
from dataclasses import dataclass

from llm_platform.config.schema import DeploymentConfig, GpuProfile


@dataclass(frozen=True, slots=True)
class ProfilePlan:
    profile: str
    start: tuple[str, ...]
    drain: tuple[str, ...]
    keep: tuple[str, ...]
    blocked_by_protected_job: bool = False


class ResourcePlanner:
    def __init__(
        self, deployments: Iterable[DeploymentConfig], profiles: Iterable[GpuProfile]
    ) -> None:
        self.deployments = {item.deployment_id: item for item in deployments}
        self.profiles = {profile.name: profile for profile in profiles}

    def plan(
        self,
        profile_name: str,
        current_deployments: set[str],
        *,
        total_gpus: int = 3,
        protected_gpus: int = 0,
    ) -> ProfilePlan:
        profile = self.profiles[profile_name]
        desired = set(profile.deployments)
        required = sum(self.deployments[item].resources.gpus for item in desired)
        blocked = required > total_gpus - protected_gpus
        if blocked:
            return ProfilePlan(
                profile_name,
                (),
                (),
                tuple(sorted(current_deployments)),
                blocked_by_protected_job=True,
            )
        return ProfilePlan(
            profile_name,
            tuple(sorted(desired - current_deployments)),
            tuple(sorted(current_deployments - desired)),
            tuple(sorted(current_deployments & desired)),
        )


def choose_profile(waiting_models: list[str]) -> str:
    large_count = sum(model == "dvf" for model in waiting_models)
    if large_count >= 2:
        return "strong-shared"
    if any(model == "dvf" for model in waiting_models):
        return "balanced"
    if waiting_models:
        return "implementation-burst"
    return "idle"
