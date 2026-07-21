"""Route classification node."""

from __future__ import annotations

from ..llm import Route, route_message, set_correlation_id
from ..state import GraphState


def route_node(state: GraphState) -> dict[str, object]:
    correlation_id = state.get("correlation_id", "")
    set_correlation_id(correlation_id or None)

    route: Route = route_message(
        state.get("message", ""),
        state.get("transcript"),
    )
    return {
        "route": route,
        "progress_messages": ["Routing…"],
    }
