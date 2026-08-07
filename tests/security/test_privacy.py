import logging

import pytest

from llm_platform.telemetry.logging import redact_metadata, safe_request_log

pytestmark = pytest.mark.security


def test_redaction_and_request_log_omit_prompt_key(caplog: pytest.LogCaptureFixture) -> None:
    assert redact_metadata({"prompt": "private", "request_id": "r1"}) == {
        "prompt": "[REDACTED]",
        "request_id": "r1",
    }
    with caplog.at_level(logging.INFO):
        safe_request_log(
            logging.getLogger("privacy-test"),
            request_id="r1",
            user_id="alice",
            requested_model="auto",
            selected_deployment="fake",
            body_size=100,
        )
    assert "private" not in caplog.text
    assert "prompt" not in caplog.text
