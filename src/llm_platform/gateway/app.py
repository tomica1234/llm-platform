import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import RequestResponseEndpoint

from llm_platform.auth.keys import ApiPrincipal, KeyStore, authenticate
from llm_platform.common.errors import PlatformError, RouteUnavailableError
from llm_platform.gateway.service import GatewayService, routing_headers


def error_body(error: PlatformError, request_id: str) -> dict[str, Any]:
    return {
        "error": {
            "message": error.message,
            "type": error.code,
            "code": error.code,
            "request_id": request_id,
            "retryable": error.retryable,
        }
    }


def create_app(
    service: GatewayService,
    key_store: KeyStore,
    shutdown: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if shutdown is not None:
            await shutdown()

    app = FastAPI(title="Local GPU LLM Platform", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        incoming = request.headers.get("x-request-id")
        request_id = incoming if incoming and len(incoming) <= 128 else f"req-{uuid.uuid4().hex}"
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(PlatformError)
    async def platform_error(request: Request, error: PlatformError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(error_body(error, request_id), status_code=error.status_code)

    async def principal(
        request: Request, authorization: str | None = Header(default=None)
    ) -> ApiPrincipal:
        if authorization is None or not authorization.startswith("Bearer "):
            from llm_platform.common.errors import AuthenticationError

            raise AuthenticationError()
        token = authorization.removeprefix("Bearer ")
        if not token:
            from llm_platform.common.errors import AuthenticationError

            raise AuthenticationError()
        return await authenticate(token, key_store)

    Principal = Annotated[ApiPrincipal, Depends(principal)]

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        is_ready = bool(service.registry.ready_ids())
        return JSONResponse(
            {"status": "ready" if is_ready else "not_ready"},
            status_code=200 if is_ready else 503,
        )

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/v1/models")
    async def models(user: Principal) -> dict[str, Any]:
        return {"object": "list", "data": service.list_models(user)}

    async def proxy_request(
        path: str,
        request: Request,
        user: ApiPrincipal,
    ) -> Response:
        try:
            payload = await request.json()
        except ValueError as exc:
            raise RouteUnavailableError("request body must be a JSON object") from exc
        if not isinstance(payload, dict):
            raise RouteUnavailableError("request body must be a JSON object")
        request_id = request.state.request_id
        normalized_headers: Mapping[str, str] = {
            key.lower(): value for key, value in request.headers.items()
        }
        if payload.get("stream") is True:
            selected, iterator = await service.stream(
                path, payload, user, normalized_headers, request_id
            )

            async def disconnect_aware() -> AsyncIterator[bytes]:
                async for chunk in iterator:
                    if await request.is_disconnected():
                        await selected.adapter.cancel(selected.instance, request_id)
                        break
                    yield chunk

            return StreamingResponse(
                disconnect_aware(),
                media_type="text/event-stream",
                headers=routing_headers(selected, request_id),
            )
        try:
            result = await service.complete(path, payload, user, normalized_headers, request_id)
        except TimeoutError as exc:
            raise PlatformError("request_timeout", "request timed out", 504, True) from exc
        return JSONResponse(dict(result.body), headers=routing_headers(result.selected, request_id))

    @app.post("/v1/responses")
    async def responses(request: Request, user: Principal) -> Response:
        return await proxy_request("/v1/responses", request, user)

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request, user: Principal) -> Response:
        return await proxy_request("/v1/chat/completions", request, user)

    @app.get("/admin/status")
    async def admin_status(user: Principal) -> dict[str, Any]:
        user.require_scope("admin")
        return {
            "ready_deployments": sorted(service.registry.ready_ids()),
            "config_revision": service.config_revision,
        }

    @app.get("/admin/routes/{request_id}")
    async def admin_route(request_id: str, user: Principal) -> dict[str, Any]:
        user.require_scope("admin")
        route = service.route_history.get(request_id)
        if route is None:
            raise PlatformError("route_not_found", "route decision was not found", 404)
        return route

    return app
