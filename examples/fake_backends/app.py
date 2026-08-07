import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="Fake OpenAI-compatible backend")
cancelled: set[str] = set()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> str:
    return "fake_backend_up 1\n"


async def stream_events(request_id: str, kind: str) -> AsyncIterator[bytes]:
    for token in ("fake", " response"):
        if request_id in cancelled:
            break
        event = {"type": kind, "delta": token}
        yield f"data: {json.dumps(event)}\n\n".encode()
        await asyncio.sleep(0)
    yield b"data: [DONE]\n\n"


@app.post("/v1/responses")
async def responses(request: Request) -> Any:
    body = await request.json()
    request_id = request.headers.get("x-request-id", f"fake-{uuid.uuid4().hex}")
    if body.get("stream"):
        return StreamingResponse(
            stream_events(request_id, "response.output_text.delta"),
            media_type="text/event-stream",
        )
    return {
        "id": request_id,
        "object": "response",
        "model": body.get("model", "fake"),
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "fake response"}],
            }
        ],
        "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    }


@app.post("/v1/chat/completions")
async def chat(request: Request) -> Any:
    body = await request.json()
    request_id = request.headers.get("x-request-id", f"fake-{uuid.uuid4().hex}")
    if body.get("stream"):
        return StreamingResponse(
            stream_events(request_id, "chat.completion.chunk"), media_type="text/event-stream"
        )
    return {
        "id": request_id,
        "object": "chat.completion",
        "model": body.get("model", "fake"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "fake response"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }


@app.post("/internal/cancel/{request_id}")
async def cancel(request_id: str) -> dict[str, bool]:
    cancelled.add(request_id)
    return {"cancelled": True}
