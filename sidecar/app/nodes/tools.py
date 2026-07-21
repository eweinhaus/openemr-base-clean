"""Gateway stub tool gather node."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from ..gateway_client import (
    GatewayAuthError,
    GatewayClient,
    GatewayForbiddenError,
    GatewayServerError,
    GatewayTimeoutError,
)
from ..llm import Route
from ..state import GENERIC_ERROR_MESSAGE, GraphState

logger = logging.getLogger(__name__)

ROUTE_TOOLS: dict[Route, list[str]] = {
    "brief": ["patient_context_stub"],
    "labs": ["labs_stub"],
    "meds": ["meds_stub"],
}


def make_tools_node(gateway: GatewayClient) -> Callable[[GraphState], dict[str, object]]:
    """Build a tools node bound to a gateway client."""

    def tools_node(state: GraphState) -> dict[str, object]:
        pid = state.get("pid")
        correlation_id = state.get("correlation_id", "")
        route = state.get("route", "brief")
        tool_names = ROUTE_TOOLS.get(route, ["patient_context_stub"])

        if pid is None or pid <= 0:
            return {"error": GENERIC_ERROR_MESSAGE}

        results: list[dict[str, object]] = []
        try:
            with ThreadPoolExecutor(max_workers=min(len(tool_names), 3)) as executor:
                futures = {
                    executor.submit(
                        gateway.call_tool,
                        tool_name,
                        {},
                        pid,
                        correlation_id,
                    ): tool_name
                    for tool_name in tool_names
                }
                for future in as_completed(futures):
                    results.append(future.result())
        except (
            GatewayAuthError,
            GatewayForbiddenError,
            GatewayServerError,
            GatewayTimeoutError,
        ) as exc:
            logger.warning(
                "Gateway tool call failed",
                extra={
                    "correlation_id": correlation_id,
                    "error_type": type(exc).__name__,
                },
            )
            return {"error": GENERIC_ERROR_MESSAGE}

        return {
            "tool_results": results,
            "progress_messages": ["Fetching chart…"],
        }

    return tools_node
