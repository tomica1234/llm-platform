import json
import logging
from collections.abc import Mapping
from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "token",
        "prompt",
        "input",
        "messages",
        "code",
        "diff",
        "secret",
    }
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def redact_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else value
        for key, value in metadata.items()
    }


def safe_request_log(
    logger: logging.Logger,
    *,
    request_id: str,
    user_id: str,
    requested_model: str,
    selected_deployment: str | None,
    body_size: int,
) -> None:
    logger.info(
        "request id=%s user=%s requested_model=%s selected_deployment=%s body_size=%d",
        request_id,
        user_id,
        requested_model,
        selected_deployment or "none",
        body_size,
    )
