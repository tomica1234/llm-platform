from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx


class GatewayClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 600) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def response(
        self, payload: Mapping[str, Any], headers: Mapping[str, str]
    ) -> Mapping[str, Any]:
        request_headers = {"Authorization": f"Bearer {self.api_key}", **headers}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/v1/responses", json=dict(payload), headers=request_headers
            )
            response.raise_for_status()
            value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError("gateway returned invalid JSON")
        return value

    async def stream(
        self, payload: Mapping[str, Any], headers: Mapping[str, str]
    ) -> AsyncIterator[bytes]:
        body = dict(payload)
        body["stream"] = True
        request_headers = {"Authorization": f"Bearer {self.api_key}", **headers}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/v1/responses", json=body, headers=request_headers
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk
