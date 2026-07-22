"""Safe user-facing error codes for hybrid SSE (no PHI / no exception dumps)."""

from __future__ import annotations

from typing import Any

from .state import GENERIC_ERROR_MESSAGE

# Short codes stored on GraphState.error and echoed on SSE error frames.
ERROR_LLM_NOT_CONFIGURED = "llm_not_configured"
ERROR_LLM_UNAVAILABLE = "llm_unavailable"
ERROR_LLM_HTTP = "llm_http_error"
ERROR_LLM_EMPTY = "llm_empty_response"
ERROR_DRAFT_PARSE = "draft_parse_failed"
ERROR_INVALID_MESSAGE = "invalid_message"
ERROR_GATEWAY_AUTH = "gateway_auth"
ERROR_GATEWAY_FORBIDDEN = "gateway_forbidden"
ERROR_GATEWAY_TIMEOUT = "gateway_timeout"
ERROR_GATEWAY_UNREACHABLE = "gateway_unreachable"
ERROR_GATEWAY_SERVER = "gateway_server"
ERROR_GATEWAY_TOOL = "gateway_tool_error"
ERROR_SIDECAR_UNREADY = "sidecar_unready"
ERROR_UNEXPECTED = "unexpected"

# Human-readable messages keyed by code. Keep free of stack traces and PHI.
_MESSAGES: dict[str, str] = {
    ERROR_LLM_NOT_CONFIGURED: (
        "Co-Pilot LLM is not configured (missing OPENROUTER_API_KEY)."
    ),
    ERROR_LLM_UNAVAILABLE: "Co-Pilot could not reach the language model. Try again.",
    ERROR_LLM_HTTP: "Language model request was rejected. Try again.",
    ERROR_LLM_EMPTY: "Language model returned an empty response. Try again.",
    ERROR_DRAFT_PARSE: "Co-Pilot could not parse the model draft. Try again.",
    ERROR_INVALID_MESSAGE: "Unable to process that message.",
    ERROR_GATEWAY_AUTH: "Chart tool proxy rejected the internal secret.",
    ERROR_GATEWAY_FORBIDDEN: "Chart tool proxy rejected the patient bind.",
    ERROR_GATEWAY_TIMEOUT: "Chart tool proxy timed out. Try again.",
    ERROR_GATEWAY_UNREACHABLE: "Could not reach the chart tool proxy.",
    ERROR_GATEWAY_SERVER: "Chart tool proxy returned a server error.",
    ERROR_GATEWAY_TOOL: "Chart tool request failed. Try again.",
    ERROR_SIDECAR_UNREADY: "Co-Pilot is temporarily unavailable. Try again.",
    ERROR_UNEXPECTED: GENERIC_ERROR_MESSAGE,
}


def message_for_code(code: str) -> str:
    """Map a stable error code to a safe user-facing message."""
    if not code:
        return GENERIC_ERROR_MESSAGE
    return _MESSAGES.get(code, GENERIC_ERROR_MESSAGE)


def sse_error_payload(
    code: str,
    *,
    correlation_id: str = "",
    detail: str | None = None,
) -> dict[str, Any]:
    """Build an SSE error data object (message + code + optional correlation id)."""
    payload: dict[str, Any] = {
        "message": message_for_code(code),
        "code": code or ERROR_UNEXPECTED,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    # Optional non-PHI detail (e.g. HTTP status) for debugging — never raw exceptions.
    if detail:
        payload["detail"] = detail
    return payload
