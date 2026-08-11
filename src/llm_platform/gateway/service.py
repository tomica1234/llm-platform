import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from llm_platform.auth.keys import ApiPrincipal
from llm_platform.common.enums import BackendState
from llm_platform.common.errors import AuthorizationError, PlatformError, RouteUnavailableError
from llm_platform.config.schema import ModelConfig
from llm_platform.routing.router import RouteRequest, RouteResult, RuleRouter, parse_selector
from llm_platform.runtimes.base import RuntimeAdapter, RuntimeInstance
from llm_platform.telemetry.logging import safe_request_log
from llm_platform.telemetry.metrics import METRICS

if TYPE_CHECKING:
    from llm_platform.orchestrator.control_plane import ControlPlane

LOGGER = logging.getLogger(__name__)
BLOCKED_EXTENSION_FIELDS = frozenset(
    {"backend_url", "runtime_command", "artifact_path", "model_path", "environment"}
)


@dataclass(frozen=True, slots=True)
class SelectedBackend:
    route: RouteResult
    adapter: RuntimeAdapter
    instance: RuntimeInstance


class DeploymentRegistry:
    def __init__(self) -> None:
        self.adapters: dict[str, RuntimeAdapter] = {}
        self.instances: dict[str, RuntimeInstance] = {}

    def register(
        self, deployment_id: str, adapter: RuntimeAdapter, instance: RuntimeInstance
    ) -> None:
        self.adapters[deployment_id] = adapter
        self.instances[deployment_id] = instance

    def unregister(self, deployment_id: str) -> None:
        self.adapters.pop(deployment_id, None)
        self.instances.pop(deployment_id, None)

    def ready_ids(self) -> frozenset[str]:
        return frozenset(
            deployment_id
            for deployment_id, instance in self.instances.items()
            if instance.state is BackendState.READY
        )

    def resolve(self, route: RouteResult) -> SelectedBackend:
        deployment_id = route.deployment.deployment_id
        adapter = self.adapters.get(deployment_id)
        instance = self.instances.get(deployment_id)
        if adapter is None or instance is None or instance.state is not BackendState.READY:
            raise RouteUnavailableError("selected backend is not ready")
        return SelectedBackend(route, adapter, instance)


@dataclass(frozen=True, slots=True)
class GatewayResult:
    body: Mapping[str, Any]
    selected: SelectedBackend


class ConcurrencyLimiter:
    def __init__(self) -> None:
        self._active: dict[str, int] = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def slot(self, principal: ApiPrincipal) -> AsyncIterator[None]:
        async with self._lock:
            active = self._active.get(principal.user_id, 0)
            if active >= principal.max_concurrency:
                raise PlatformError(
                    "concurrency_limit",
                    "per-user concurrency limit reached",
                    429,
                    True,
                )
            self._active[principal.user_id] = active + 1
        try:
            yield
        finally:
            async with self._lock:
                remaining = self._active.get(principal.user_id, 1) - 1
                if remaining:
                    self._active[principal.user_id] = remaining
                else:
                    self._active.pop(principal.user_id, None)


class GatewayService:
    def __init__(
        self,
        router: RuleRouter,
        registry: DeploymentRegistry,
        models: list[ModelConfig],
        *,
        request_timeout_seconds: float = 600,
        config_revision: str = "development",
        control_plane: "ControlPlane | None" = None,
    ) -> None:
        self.router = router
        self.registry = registry
        self.models = models
        self.request_timeout_seconds = request_timeout_seconds
        self.config_revision = config_revision
        self.control_plane = control_plane
        self.limiter = ConcurrencyLimiter()
        self.route_history: dict[str, dict[str, Any]] = {}

    def record_route(self, request_id: str, selected: SelectedBackend) -> None:
        self.route_history[request_id] = {
            "request_id": request_id,
            "model": selected.route.model.model_id,
            "runtime": selected.route.deployment.runtime,
            "deployment": selected.route.deployment.deployment_id,
            "mode": selected.route.mode,
            "reason_codes": [reason.value for reason in selected.route.reasons],
            "config_revision": self.config_revision,
        }

    def list_models(self, principal: ApiPrincipal) -> list[dict[str, Any]]:
        return [
            {
                "id": model.model_id,
                "object": "model",
                "owned_by": "local-llm-platform",
                "capabilities": model.capabilities.model_dump(),
            }
            for model in self.models
            if model.enabled and model.model_id in principal.model_permissions
        ]

    def route(
        self,
        payload: Mapping[str, Any],
        principal: ApiPrincipal,
        headers: Mapping[str, str],
    ) -> RouteResult:
        principal.require_scope("inference")
        blocked = BLOCKED_EXTENSION_FIELDS.intersection(payload)
        if blocked:
            raise RouteUnavailableError(
                f"unsafe gateway extension fields are not accepted: {', '.join(sorted(blocked))}"
            )
        model_value = payload.get("model", "auto")
        if not isinstance(model_value, str):
            raise RouteUnavailableError("model must be a string")
        try:
            context_tokens = int(headers.get("x-agent-context-tokens", "0"))
            failure_count = int(headers.get("x-agent-failure-count", "0"))
        except ValueError as exc:
            raise PlatformError(
                "invalid_agent_metadata", "agent numeric headers must be integers", 400
            ) from exc
        if context_tokens < 0 or failure_count < 0:
            raise PlatformError(
                "invalid_agent_metadata", "agent numeric headers may not be negative", 400
            )
        high_risk = headers.get("x-agent-risk", "").lower() in {"high", "critical"}
        request = RouteRequest(
            selector=parse_selector(model_value),
            permitted_models=principal.model_permissions,
            context_tokens=context_tokens,
            require_tools=bool(payload.get("tools")),
            require_structured_output=payload.get("response_format") is not None,
            available_gpus=3,
            loaded_deployments=self.registry.ready_ids(),
            previous_model=headers.get("x-agent-previous-model"),
            failure_count=failure_count,
            high_risk=high_risk,
        )
        started = time.monotonic()
        route = self.router.route(request)
        METRICS.route_seconds.observe(time.monotonic() - started)
        if route.deployment.model_id not in principal.model_permissions:
            raise AuthorizationError("selected model is not permitted")
        return route

    def select(
        self,
        payload: Mapping[str, Any],
        principal: ApiPrincipal,
        headers: Mapping[str, str],
    ) -> SelectedBackend:
        return self.registry.resolve(self.route(payload, principal, headers))

    async def _select_ready(
        self,
        payload: Mapping[str, Any],
        principal: ApiPrincipal,
        headers: Mapping[str, str],
        request_id: str,
    ) -> SelectedBackend:
        route = self.route(payload, principal, headers)
        if self.control_plane is not None:
            await self.control_plane.wait_for_deployment(
                route.deployment.deployment_id,
                request_id,
                principal.user_id,
                str(payload.get("model", "auto")),
                dict(payload),
                timeout_seconds=self.request_timeout_seconds,
            )
        return self.registry.resolve(route)

    async def complete(
        self,
        path: str,
        payload: Mapping[str, Any],
        principal: ApiPrincipal,
        headers: Mapping[str, str],
        request_id: str,
    ) -> GatewayResult:
        selected = await self._select_ready(payload, principal, headers, request_id)
        self.record_route(request_id, selected)
        forwarded = dict(payload)
        forwarded["model"] = selected.route.model.model_id
        started = time.monotonic()
        try:
            if self.control_plane is not None:
                await self.control_plane.request_started(
                    request_id, selected.route.deployment.deployment_id
                )
            async with self.limiter.slot(principal):
                async with asyncio.timeout(self.request_timeout_seconds):
                    body = await selected.adapter.proxy(
                        selected.instance, path, forwarded, request_id
                    )
        except TimeoutError:
            await selected.adapter.cancel(selected.instance, request_id)
            if self.control_plane is not None:
                await self.control_plane.request_finished(request_id, failed=True)
            raise
        except BaseException:
            if self.control_plane is not None:
                await self.control_plane.request_finished(request_id, failed=True)
            raise
        else:
            if self.control_plane is not None:
                await self.control_plane.request_finished(request_id)
        finally:
            METRICS.request_seconds.labels(
                deployment=selected.route.deployment.deployment_id
            ).observe(time.monotonic() - started)
        safe_request_log(
            LOGGER,
            request_id=request_id,
            user_id=principal.user_id,
            requested_model=str(payload.get("model", "auto")),
            selected_deployment=selected.route.deployment.deployment_id,
            body_size=len(str(payload)),
        )
        return GatewayResult(body, selected)

    async def stream(
        self,
        path: str,
        payload: Mapping[str, Any],
        principal: ApiPrincipal,
        headers: Mapping[str, str],
        request_id: str,
    ) -> tuple[SelectedBackend, AsyncIterator[bytes]]:
        selected = await self._select_ready(payload, principal, headers, request_id)
        self.record_route(request_id, selected)
        forwarded = dict(payload)
        forwarded["model"] = selected.route.model.model_id

        async def generate() -> AsyncIterator[bytes]:
            failed = True
            async with self.limiter.slot(principal):
                try:
                    if self.control_plane is not None:
                        await self.control_plane.request_started(
                            request_id, selected.route.deployment.deployment_id
                        )
                    async for chunk in selected.adapter.stream(
                        selected.instance, path, forwarded, request_id
                    ):
                        yield chunk
                    failed = False
                except asyncio.CancelledError:
                    METRICS.cancellations.inc()
                    await selected.adapter.cancel(selected.instance, request_id)
                    raise
                finally:
                    if self.control_plane is not None:
                        await self.control_plane.request_finished(request_id, failed=failed)

        return selected, generate()


def routing_headers(selected: SelectedBackend, request_id: str) -> dict[str, str]:
    return {
        "X-Selected-Logical-Model": selected.route.model.model_id,
        "X-Selected-Runtime": selected.route.deployment.runtime,
        "X-Selected-Deployment": selected.route.deployment.deployment_id,
        "X-Route-Mode": selected.route.mode,
        "X-Queue-Wait-Ms": "0",
        "X-Backend-Load-Ms": "0",
        "X-Request-ID": request_id,
        "X-Config-Revision": "configured",
    }
