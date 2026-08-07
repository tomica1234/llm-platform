from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from llm_platform.common.errors import PlatformError


class RuntimeHttpClient:
    def __init__(self, timeout_seconds: float = 600) -> None:
        self._timeout = httpx.Timeout(timeout_seconds)

    async def get_health(self, base_url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{base_url}/health")
                return response.is_success
        except httpx.HTTPError:
            return False

    async def get_metrics(self, base_url: str) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{base_url}/metrics")
            response.raise_for_status()
            return response.text

    async def post_json(
        self,
        base_url: str,
        path: str,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> Mapping[str, Any]:
        headers = {"X-Request-ID": request_id}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.post(f"{base_url}{path}", json=payload, headers=headers)
                response.raise_for_status()
                value = response.json()
            except httpx.TimeoutException as exc:
                raise PlatformError(
                    "backend_timeout", "backend request timed out", 504, True
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise PlatformError(
                    "backend_error",
                    f"backend returned HTTP {exc.response.status_code}",
                    502,
                    exc.response.status_code >= 500,
                ) from exc
        if not isinstance(value, dict):
            raise PlatformError("invalid_backend_response", "backend returned non-object JSON", 502)
        return value

    async def stream_bytes(
        self,
        base_url: str,
        path: str,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> AsyncIterator[bytes]:
        headers = {"X-Request-ID": request_id, "Accept": "text/event-stream"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST", f"{base_url}{path}", json=payload, headers=headers
            ) as response:
                if not response.is_success:
                    await response.aread()
                    raise PlatformError(
                        "backend_error",
                        f"backend returned HTTP {response.status_code}",
                        502,
                        response.status_code >= 500,
                    )
                async for chunk in response.aiter_bytes():
                    yield chunk
