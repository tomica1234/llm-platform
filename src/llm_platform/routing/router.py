from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from llm_platform.common.enums import RuntimeKind
from llm_platform.common.errors import RouteUnavailableError
from llm_platform.config.schema import DeploymentConfig, ModelConfig, ScoreWeights


class RouteMode(StrEnum):
    AUTO = "auto"
    PREFER = "prefer"
    FORCE = "force"
    FORCE_DEPLOYMENT = "force-deployment"


class ReasonCode(StrEnum):
    MANUAL_FORCE = "MANUAL_FORCE"
    MANUAL_PREFER = "MANUAL_PREFER"
    MODEL_ALREADY_LOADED = "MODEL_ALREADY_LOADED"
    BEST_PREDICTED_SUCCESS = "BEST_PREDICTED_SUCCESS"
    LOWEST_EXPECTED_COMPLETION_TIME = "LOWEST_EXPECTED_COMPLETION_TIME"
    BATCH_WITH_EXISTING_REQUEST = "BATCH_WITH_EXISTING_REQUEST"
    ESCALATED_AFTER_TEST_FAILURE = "ESCALATED_AFTER_TEST_FAILURE"
    HIGH_RISK_FINAL_REVIEW = "HIGH_RISK_FINAL_REVIEW"
    UNBENCHMARKED = "UNBENCHMARKED"
    CONTEXT_TOO_LONG = "CONTEXT_TOO_LONG"
    RUNTIME_INCOMPATIBLE = "RUNTIME_INCOMPATIBLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NO_CAPACITY = "NO_CAPACITY"


@dataclass(frozen=True, slots=True)
class Selector:
    mode: RouteMode
    policy: str = "balanced"
    model_id: str | None = None
    runtime: RuntimeKind | None = None
    deployment_id: str | None = None


def parse_selector(value: str) -> Selector:
    if value == "auto":
        return Selector(RouteMode.AUTO)
    if value in {"auto/fast", "auto/balanced", "auto/quality"}:
        return Selector(RouteMode.AUTO, value.split("/", 1)[1])
    if value.startswith("prefer/"):
        model_id = value.removeprefix("prefer/")
        if model_id:
            return Selector(RouteMode.PREFER, model_id=model_id)
    if value.startswith("force-deployment/"):
        deployment_id = value.removeprefix("force-deployment/")
        if deployment_id:
            return Selector(RouteMode.FORCE_DEPLOYMENT, deployment_id=deployment_id)
    if value.startswith("force/"):
        target = value.removeprefix("force/")
        model_id, separator, runtime_name = target.partition("@")
        if model_id:
            runtime = None
            if separator:
                try:
                    runtime = RuntimeKind(runtime_name)
                except ValueError as exc:
                    raise RouteUnavailableError("forced runtime is not supported") from exc
            return Selector(RouteMode.FORCE, model_id=model_id, runtime=runtime)
    raise RouteUnavailableError(f"invalid virtual model selector: {value}")


@dataclass(frozen=True, slots=True)
class RouteRequest:
    selector: Selector
    permitted_models: frozenset[str]
    context_tokens: int = 0
    require_tools: bool = False
    require_structured_output: bool = False
    require_multimodal: bool = False
    available_gpus: int = 3
    loaded_deployments: frozenset[str] = frozenset()
    deployment_queue_wait: Mapping[str, float] = field(default_factory=dict)
    same_model_waiters: Mapping[str, int] = field(default_factory=dict)
    previous_model: str | None = None
    failure_count: int = 0
    high_risk: bool = False
    review_family: str | None = None


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    deployment_id: str
    model_id: str
    score: float
    reasons: tuple[ReasonCode, ...]


@dataclass(frozen=True, slots=True)
class RouteResult:
    model: ModelConfig
    deployment: DeploymentConfig
    mode: RouteMode
    score: float
    reasons: tuple[ReasonCode, ...]
    candidates: tuple[ScoredCandidate, ...]


class RuleRouter:
    def __init__(
        self,
        models: Iterable[ModelConfig],
        deployments: Iterable[DeploymentConfig],
        weights: Mapping[str, ScoreWeights],
    ) -> None:
        self.models = {model.model_id: model for model in models}
        self.deployments = {item.deployment_id: item for item in deployments}
        self.weights = dict(weights)

    def _filter_reason(
        self, model: ModelConfig, deployment: DeploymentConfig, request: RouteRequest
    ) -> ReasonCode | None:
        selector = request.selector
        if not model.enabled or not deployment.enabled:
            return ReasonCode.RUNTIME_INCOMPATIBLE
        if model.model_id not in request.permitted_models:
            return ReasonCode.PERMISSION_DENIED
        if selector.mode is RouteMode.FORCE_DEPLOYMENT:
            if deployment.deployment_id != selector.deployment_id:
                return ReasonCode.RUNTIME_INCOMPATIBLE
        elif selector.mode is RouteMode.FORCE:
            if model.model_id != selector.model_id:
                return ReasonCode.RUNTIME_INCOMPATIBLE
            if selector.runtime is not None and deployment.runtime is not selector.runtime:
                return ReasonCode.RUNTIME_INCOMPATIBLE
        if request.context_tokens > deployment.capabilities.max_context:
            return ReasonCode.CONTEXT_TOO_LONG
        if request.require_tools and not deployment.capabilities.tool_calling:
            return ReasonCode.RUNTIME_INCOMPATIBLE
        if request.require_structured_output and not deployment.capabilities.structured_output:
            return ReasonCode.RUNTIME_INCOMPATIBLE
        if request.require_multimodal and not deployment.capabilities.multimodal:
            return ReasonCode.RUNTIME_INCOMPATIBLE
        if deployment.resources.gpus > request.available_gpus:
            return ReasonCode.NO_CAPACITY
        if selector.mode in {RouteMode.AUTO, RouteMode.PREFER} and not deployment.auto_eligible:
            return ReasonCode.UNBENCHMARKED
        return None

    def route(self, request: RouteRequest) -> RouteResult:
        weights = self.weights.get(request.selector.policy, self.weights["balanced"])
        scored: list[tuple[ModelConfig, DeploymentConfig, ScoredCandidate]] = []
        for deployment in self.deployments.values():
            model = self.models.get(deployment.model_id)
            if model is None or self._filter_reason(model, deployment, request) is not None:
                continue
            benchmark = deployment.benchmark
            latency = 1.0
            switch_cost = 0.0
            if benchmark is not None:
                throughput = max(benchmark.generation_tps, 0.001)
                latency = 1 / throughput
                switch_cost = benchmark.startup_seconds / 600
            queue_wait = request.deployment_queue_wait.get(deployment.deployment_id, 0) / 600
            loaded = deployment.deployment_id in request.loaded_deployments
            same_waiters = request.same_model_waiters.get(model.model_id, 0)
            score = (
                weights.quality_weight * model.quality_score
                - weights.latency_weight * latency
                - weights.wait_weight * queue_wait
                - weights.switch_weight * (0 if loaded else switch_cost)
                - weights.resource_weight * (deployment.resources.gpus / 3)
                + weights.loaded_bonus * int(loaded)
                + weights.batching_bonus * min(same_waiters, 3)
                + weights.continuity_bonus * int(request.previous_model == model.model_id)
            )
            reasons: list[ReasonCode] = [ReasonCode.BEST_PREDICTED_SUCCESS]
            if loaded:
                reasons.append(ReasonCode.MODEL_ALREADY_LOADED)
            if same_waiters:
                reasons.append(ReasonCode.BATCH_WITH_EXISTING_REQUEST)
            if (
                request.selector.mode is RouteMode.PREFER
                and model.model_id == request.selector.model_id
            ):
                score += 100
                reasons.append(ReasonCode.MANUAL_PREFER)
            if request.selector.mode in {RouteMode.FORCE, RouteMode.FORCE_DEPLOYMENT}:
                reasons.insert(0, ReasonCode.MANUAL_FORCE)
            if request.failure_count >= 2:
                score += weights.quality_weight * model.quality_score
                reasons.append(ReasonCode.ESCALATED_AFTER_TEST_FAILURE)
            if request.high_risk:
                score += weights.quality_weight * model.quality_score
                reasons.append(ReasonCode.HIGH_RISK_FINAL_REVIEW)
                if request.review_family is not None and model.family != request.review_family:
                    score += weights.diversity_bonus
            candidate = ScoredCandidate(
                deployment.deployment_id, model.model_id, score, tuple(reasons)
            )
            scored.append((model, deployment, candidate))
        if not scored:
            forced = request.selector.mode in {RouteMode.FORCE, RouteMode.FORCE_DEPLOYMENT}
            message = (
                "forced model/runtime/deployment is unavailable; no fallback was attempted"
                if forced
                else "no deployment satisfies routing constraints"
            )
            raise RouteUnavailableError(message)
        scored.sort(key=lambda item: (-item[2].score, item[1].deployment_id))
        selected_model, selected_deployment, selected = scored[0]
        return RouteResult(
            selected_model,
            selected_deployment,
            request.selector.mode,
            selected.score,
            selected.reasons,
            tuple(item[2] for item in scored),
        )
