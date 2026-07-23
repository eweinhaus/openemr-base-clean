"""Haiku draft + claims parse node."""

from __future__ import annotations

import logging

from ..claims import ClaimsParseError, parse_claims_json
from ..errors import ERROR_DRAFT_PARSE, ERROR_LLM_UNAVAILABLE
from ..llm import LlmError, draft_claims_raw, set_correlation_id
from ..state import GraphState

logger = logging.getLogger(__name__)


def draft_node(state: GraphState) -> dict[str, object]:
    correlation_id = state.get("correlation_id", "")
    set_correlation_id(correlation_id or None)

    try:
        raw = draft_claims_raw(
            state.get("message", ""),
            state.get("tool_results") or [],
            state.get("transcript"),
            route=state.get("route", "brief"),
        )
        draft = parse_claims_json(raw)
    except LlmError as exc:
        code = getattr(exc, "code", ERROR_LLM_UNAVAILABLE)
        logger.warning(
            "Draft claims failed",
            extra={
                "correlation_id": correlation_id,
                "error_type": type(exc).__name__,
                "error_code": code,
            },
        )
        return {"error": code}
    except ClaimsParseError:
        logger.warning(
            "Draft claims failed",
            extra={
                "correlation_id": correlation_id,
                "error_type": "ClaimsParseError",
                "error_code": ERROR_DRAFT_PARSE,
            },
        )
        return {"error": ERROR_DRAFT_PARSE}

    return {"draft_claims": draft}
