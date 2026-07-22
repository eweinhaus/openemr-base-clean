"""Unit tests for safe SSE error code mapping."""

from __future__ import annotations

from sidecar.app.errors import (
    ERROR_LLM_NOT_CONFIGURED,
    ERROR_SIDECAR_UNREADY,
    ERROR_UNEXPECTED,
    message_for_code,
    sse_error_payload,
)
from sidecar.app.state import GENERIC_ERROR_MESSAGE


def test_message_for_known_code() -> None:
    msg = message_for_code(ERROR_LLM_NOT_CONFIGURED)
    assert "OPENROUTER_API_KEY" in msg


def test_message_for_sidecar_unready() -> None:
    msg = message_for_code(ERROR_SIDECAR_UNREADY)
    assert msg == "Co-Pilot is temporarily unavailable. Try again."
    assert "OpenRouter" not in msg
    assert "LangSmith" not in msg


def test_message_for_unknown_code_falls_back() -> None:
    assert message_for_code("not_a_real_code") == GENERIC_ERROR_MESSAGE


def test_sse_error_payload_shape() -> None:
    payload = sse_error_payload(
        ERROR_LLM_NOT_CONFIGURED,
        correlation_id="corr-9",
        detail="optional",
    )
    assert payload["code"] == ERROR_LLM_NOT_CONFIGURED
    assert payload["correlation_id"] == "corr-9"
    assert payload["detail"] == "optional"
    assert "OPENROUTER_API_KEY" in payload["message"]


def test_sse_error_payload_omits_empty_optional_fields() -> None:
    payload = sse_error_payload(ERROR_UNEXPECTED)
    assert payload["code"] == ERROR_UNEXPECTED
    assert "correlation_id" not in payload
    assert "detail" not in payload
