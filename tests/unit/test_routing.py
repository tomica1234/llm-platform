from typing import Any

import pytest

from llm_platform.common.enums import RuntimeKind
from llm_platform.common.errors import RouteUnavailableError
from llm_platform.routing.router import (
    ReasonCode,
    RouteMode,
    RouteRequest,
    RuleRouter,
    parse_selector,
)


def build_router(model_factory: Any, deployment_factory: Any, weights: Any) -> RuleRouter:
    models = [
        model_factory("fast", family="qwen", quality=0.6),
        model_factory("strong", family="deepseek", quality=0.95),
    ]
    deployments = [
        deployment_factory("fast-vllm", model_id="fast", port=8201),
        deployment_factory(
            "strong-llama",
            model_id="strong",
            runtime=RuntimeKind.LLAMA_CPP,
            gpus=2,
            port=8101,
        ),
    ]
    return RuleRouter(models, deployments, weights)


def test_manual_force_runtime_is_absolute_priority(
    model_factory: Any, deployment_factory: Any, weights: Any
) -> None:
    router = build_router(model_factory, deployment_factory, weights)
    result = router.route(
        RouteRequest(parse_selector("force/strong@llama_cpp"), frozenset({"fast", "strong"}))
    )
    assert result.deployment.deployment_id == "strong-llama"
    assert result.mode is RouteMode.FORCE
    assert result.reasons[0] is ReasonCode.MANUAL_FORCE


def test_force_does_not_fallback(model_factory: Any, deployment_factory: Any, weights: Any) -> None:
    router = build_router(model_factory, deployment_factory, weights)
    with pytest.raises(RouteUnavailableError, match="no fallback"):
        router.route(RouteRequest(parse_selector("force/missing"), frozenset({"fast", "strong"})))


def test_unbenchmarked_excluded_from_auto(
    model_factory: Any, deployment_factory: Any, weights: Any
) -> None:
    model = model_factory("only")
    deployment = deployment_factory("only-vllm", model_id="only", benchmarked=False)
    router = RuleRouter([model], [deployment], weights)
    with pytest.raises(RouteUnavailableError):
        router.route(RouteRequest(parse_selector("auto"), frozenset({"only"})))
    forced = router.route(
        RouteRequest(parse_selector("force-deployment/only-vllm"), frozenset({"only"}))
    )
    assert forced.deployment.deployment_id == "only-vllm"


def test_failure_escalation_and_high_risk_reason(
    model_factory: Any, deployment_factory: Any, weights: Any
) -> None:
    router = build_router(model_factory, deployment_factory, weights)
    result = router.route(
        RouteRequest(
            parse_selector("auto/quality"),
            frozenset({"fast", "strong"}),
            failure_count=2,
            high_risk=True,
            review_family="qwen",
        )
    )
    assert result.model.model_id == "strong"
    assert ReasonCode.ESCALATED_AFTER_TEST_FAILURE in result.reasons
    assert ReasonCode.HIGH_RISK_FINAL_REVIEW in result.reasons


def test_context_and_permission_are_hard_filters(
    model_factory: Any, deployment_factory: Any, weights: Any
) -> None:
    router = build_router(model_factory, deployment_factory, weights)
    with pytest.raises(RouteUnavailableError):
        router.route(
            RouteRequest(parse_selector("auto"), frozenset({"fast"}), context_tokens=100_000)
        )
