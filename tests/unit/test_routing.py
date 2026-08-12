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


@pytest.mark.parametrize(
    ("value", "policy"),
    [
        ("auto", "balanced"),
        ("fast", "fast"),
        ("balanced", "balanced"),
        ("strong", "strong"),
        ("max", "max"),
        ("auto/fast", "fast"),
        ("auto/balanced", "balanced"),
        ("auto/strong", "strong"),
        ("auto/max", "max"),
        ("quality", "strong"),
        ("auto/quality", "strong"),
    ],
)
def test_parse_automatic_selectors(value: str, policy: str) -> None:
    selector = parse_selector(value)
    assert selector.mode is RouteMode.AUTO
    assert selector.policy == policy
    assert selector.model_id is None


@pytest.mark.parametrize(
    "value",
    [
        "prefer/model-a",
        "force/model-a",
        "force/model-a@vllm",
        "force-deployment/model-a-vllm",
    ],
)
def test_parse_explicit_selectors(value: str) -> None:
    assert parse_selector(value).mode is not RouteMode.AUTO


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
            parse_selector("fast"),
            frozenset({"fast", "strong"}),
            failure_count=2,
            high_risk=True,
            review_family="qwen",
        )
    )
    assert result.model.model_id == "strong"
    assert ReasonCode.ESCALATED_AFTER_TEST_FAILURE in result.reasons
    assert ReasonCode.HIGH_RISK_FINAL_REVIEW in result.reasons


def test_four_policies_select_distinct_real_deployments(
    model_factory: Any, deployment_factory: Any, weights: Any
) -> None:
    models = [
        model_factory("swift-model", quality=0.55),
        model_factory("general-model", quality=0.8),
        model_factory("expert-model", quality=0.92),
        model_factory("frontier-model", quality=1.0),
    ]
    specifications = [
        ("swift-vllm", "swift-model", 1, 2, 100),
        ("general-vllm", "general-model", 1, 15, 50),
        ("expert-vllm", "expert-model", 2, 60, 25),
        ("frontier-vllm", "frontier-model", 3, 300, 10),
    ]
    deployments = []
    for index, (deployment_id, model_id, gpus, startup, generation_tps) in enumerate(
        specifications
    ):
        deployment = deployment_factory(
            deployment_id, model_id=model_id, gpus=gpus, port=8300 + index
        )
        assert deployment.benchmark is not None
        deployment = deployment.model_copy(
            update={
                "benchmark": deployment.benchmark.model_copy(
                    update={"startup_seconds": startup, "generation_tps": generation_tps}
                )
            }
        )
        deployments.append(deployment)
    router = RuleRouter(models, deployments, weights)
    permitted = frozenset(model.model_id for model in models)
    expected = {
        "fast": "swift-vllm",
        "balanced": "general-vllm",
        "strong": "expert-vllm",
        "max": "frontier-vllm",
    }
    for policy, deployment_id in expected.items():
        result = router.route(
            RouteRequest(
                parse_selector(policy),
                permitted,
                loaded_deployments=frozenset({"swift-vllm"}),
            )
        )
        assert result.deployment.deployment_id == deployment_id
        assert result.model.model_id not in {"fast", "balanced", "strong", "max"}

    forced = router.route(RouteRequest(parse_selector("force/swift-model"), permitted))
    assert forced.deployment.deployment_id == "swift-vllm"


def test_context_and_permission_are_hard_filters(
    model_factory: Any, deployment_factory: Any, weights: Any
) -> None:
    router = build_router(model_factory, deployment_factory, weights)
    with pytest.raises(RouteUnavailableError):
        router.route(
            RouteRequest(parse_selector("auto"), frozenset({"fast"}), context_tokens=100_000)
        )


@pytest.mark.parametrize(
    "request_changes",
    [
        {"permitted_models": frozenset()},
        {"require_multimodal": True},
        {"context_tokens": 100_000},
        {"available_gpus": 0},
    ],
)
def test_policy_never_bypasses_hard_filters(
    model_factory: Any,
    deployment_factory: Any,
    weights: Any,
    request_changes: dict[str, Any],
) -> None:
    router = RuleRouter(
        [model_factory("real-model")],
        [deployment_factory("real-deployment", model_id="real-model")],
        weights,
    )
    arguments: dict[str, Any] = {
        "selector": parse_selector("max"),
        "permitted_models": frozenset({"real-model"}),
    }
    arguments.update(request_changes)
    with pytest.raises(RouteUnavailableError, match="constraints"):
        router.route(RouteRequest(**arguments))
