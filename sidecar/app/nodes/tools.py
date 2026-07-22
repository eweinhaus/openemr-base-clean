"""Gateway chart tool gather node."""

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
    "brief": ["patient_context", "labs", "meds", "notes"],
    "labs": ["labs"],
    "meds": ["meds"],
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
        tool_names = ROUTE_TOOLS.get(route, ["patient_context"])

        if pid is None or pid <= 0:
            return {"error": ERROR_UNEXPECTED}
        if user_id is None or user_id <= 0:
            return {"error": ERROR_UNEXPECTED}

        results: list[dict[str, object]] = []
        domain_errors: dict[str, str] = {}
        fail_closed_code: str | None = None

        with ThreadPoolExecutor(max_workers=min(len(tool_names), 4)) as executor:
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
                tool_name = futures[future]
                try:
                    payload = future.result()
                except (GatewayAuthError, GatewayForbiddenError) as exc:
                    code = _gateway_error_code(exc)
                    logger.warning(
                        "Gateway tool call fail-closed",
                        extra={
                            "correlation_id": correlation_id,
                            "tool": tool_name,
                            "error_type": type(exc).__name__,
                            "error_code": code,
                        },
                    )
                    fail_closed_code = code
                    # Drain remaining futures so the pool shuts down cleanly.
                    continue
                except GatewayError as exc:
                    code = _gateway_error_code(exc)
                    logger.warning(
                        "Gateway tool call failed (domain unavailable)",
                        extra={
                            "correlation_id": correlation_id,
                            "tool": tool_name,
                            "error_type": type(exc).__name__,
                            "error_code": code,
                        },
                    )
                    domain_errors[tool_name] = code
                    continue

                if not isinstance(payload, dict) or not payload.get("ok"):
                    logger.warning(
                        "Gateway tool returned ok=false",
                        extra={
                            "correlation_id": correlation_id,
                            "tool": tool_name,
                            "error_code": ERROR_GATEWAY_TOOL,
                        },
                    )
                    domain_errors[tool_name] = ERROR_GATEWAY_TOOL
                    continue

                # Ensure tool name is present for assemble empty/unavailable detection.
                if "tool" not in payload:
                    payload = {**payload, "tool": tool_name}
                results.append(payload)

        if fail_closed_code is not None:
            return {"error": fail_closed_code}

        if not results:
            unique_codes = set(domain_errors.values())
            code = (
                next(iter(unique_codes))
                if len(unique_codes) == 1
                else ERROR_GATEWAY_TOOL
            )
            return {
                "error": code,
                "tool_results": [],
                "tool_domain_errors": domain_errors,
                "requested_tools": tool_names,
            }

        return {
            "tool_results": results,
            "tool_domain_errors": domain_errors,
            "requested_tools": tool_names,
            "progress_messages": ["Fetching chart…"],
        }

    return tools_node
