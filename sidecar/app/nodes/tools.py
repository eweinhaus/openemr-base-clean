"""Gateway stub tool gather node."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from ..errors import (
    ERROR_GATEWAY_AUTH,
    ERROR_GATEWAY_FORBIDDEN,
    ERROR_GATEWAY_SERVER,
    ERROR_GATEWAY_TIMEOUT,
    ERROR_GATEWAY_TOOL,
    ERROR_GATEWAY_UNREACHABLE,
    ERROR_UNEXPECTED,
)
from ..gateway_client import (
    GatewayAuthError,
    GatewayClient,
    GatewayError,
    GatewayForbiddenError,
    GatewayNetworkError,
    GatewayServerError,
    GatewayTimeoutError,
)
from ..llm import Route
from ..state import GraphState

logger = logging.getLogger(__name__)

ROUTE_TOOLS: dict[Route, list[str]] = {
    "brief": ["patient_context_stub"],
    "labs": ["labs_stub"],
    "meds": ["meds_stub"],
}


def _gateway_error_code(exc: GatewayError) -> str:
    if isinstance(exc, GatewayAuthError):
        return ERROR_GATEWAY_AUTH
    if isinstance(exc, GatewayForbiddenError):
        return ERROR_GATEWAY_FORBIDDEN
    if isinstance(exc, GatewayTimeoutError):
        return ERROR_GATEWAY_TIMEOUT
    if isinstance(exc, GatewayNetworkError):
        return ERROR_GATEWAY_UNREACHABLE
    if isinstance(exc, GatewayServerError):
        return ERROR_GATEWAY_SERVER
    return ERROR_GATEWAY_TOOL


def make_tools_node(gateway: GatewayClient) -> Callable[[GraphState], dict[str, object]]:
    """Build a tools node bound to a gateway client."""

    def tools_node(state: GraphState) -> dict[str, object]:
        pid = state.get("pid")
        user_id = state.get("user_id")
        correlation_id = state.get("correlation_id", "")
        route = state.get("route", "brief")
        tool_names = ROUTE_TOOLS.get(route, ["patient_context_stub"])

        if pid is None or pid <= 0:
            return {"error": ERROR_UNEXPECTED}
        if user_id is None or user_id <= 0:
            return {"error": ERROR_UNEXPECTED}

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
                        user_id,
                    ): tool_name
                    for tool_name in tool_names
                }
                for future in as_completed(futures):
                    results.append(future.result())
        except GatewayError as exc:
            # Catch base GatewayError so 4xx (invalid_request / not_implemented)
            # becomes a clean SSE error instead of aborting the stream.
            code = _gateway_error_code(exc)
            logger.warning(
                "Gateway tool call failed",
                extra={
                    "correlation_id": correlation_id,
                    "error_type": type(exc).__name__,
                    "error_code": code,
                },
            )
            return {"error": code}

        return {
            "tool_results": results,
            "progress_messages": ["Fetching chart…"],
        }

    return tools_node
