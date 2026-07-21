"""Route classification node."""

from __future__ import annotations

import logging

from ..errors import ERROR_LLM_UNAVAILABLE
from ..llm import LlmError, Route, route_message, set_correlation_id
from ..state import GraphState

logger = logging.getLogger(__name__)


def route_node(state: GraphState) -> dict[str, object]:
    correlation_id = state.get("correlation_id", "")
    set_correlation_id(correlation_id or None)

    try:
        route: Route = route_message(
            state.get("message", ""),
            state.get("transcript"),
        )
    except LlmError as exc:
        logger.warning(
            "Route classification failed",
            extra={
                "correlation_id": correlation_id,
                "error_type": type(exc).__name__,
                "error_code": getattr(exc, "code", ERROR_LLM_UNAVAILABLE),
            },
        )
        return {"error": getattr(exc, "code", ERROR_LLM_UNAVAILABLE)}

    return {
        "route": route,
        "progress_messages": ["Routing…"],
    }
