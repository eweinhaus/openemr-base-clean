"""Haiku draft + claims parse node."""

from __future__ import annotations

import logging

from ..claims import ClaimsParseError, parse_claims_json
from ..llm import LlmError, draft_claims_raw, set_correlation_id
from ..state import GENERIC_ERROR_MESSAGE, GraphState

logger = logging.getLogger(__name__)


def draft_node(state: GraphState) -> dict[str, object]:
    correlation_id = state.get("correlation_id", "")
    set_correlation_id(correlation_id or None)

    try:
        raw = draft_claims_raw(
            state.get("message", ""),
            state.get("tool_results") or [],
            state.get("transcript"),
        )
        draft = parse_claims_json(raw)
    except (LlmError, ClaimsParseError) as exc:
        logger.warning(
            "Draft claims failed",
            extra={
                "correlation_id": correlation_id,
                "error_type": type(exc).__name__,
            },
        )
        return {"error": GENERIC_ERROR_MESSAGE}

    return {"draft_claims": draft}
