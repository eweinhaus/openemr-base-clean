"""Gateway chart tool gather node."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Mapping, Sequence

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
from ..progress import chart_progress_for_route
from ..research import (
    RESEARCH_PROGRESS_MESSAGE,
    ResolveStatus,
    build_research_tool_result,
    extract_dailymed_facts,
    extract_openfda_facts,
    fetch_label,
    is_dosing_like,
    reconcile_on_chart_after_hit,
    resolve_drug_query,
)
from ..state import GraphState

logger = logging.getLogger(__name__)

ROUTE_TOOLS: dict[Route, list[str]] = {
    "brief": ["patient_context", "labs", "meds", "notes"],
    "labs": ["labs"],
    # UC-3: meds + allergies (from meds tool) + conditions (patient_context).
    "meds": ["meds", "patient_context"],
}

_FORM_HINT_RE = re.compile(r"\b(ER|XR|SA)\b", re.IGNORECASE)


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


def _meds_facts_from_results(
    results: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Extract ``data.facts`` from the meds chart tool payload, if present."""
    for payload in results:
        if payload.get("tool") != "meds":
            continue
        data = payload.get("data")
        if not isinstance(data, Mapping):
            return []
        facts = data.get("facts")
        if isinstance(facts, list):
            return [f for f in facts if isinstance(f, Mapping)]
        return []
    return []


def _form_hint_from_message(message: str) -> str | None:
    match = _FORM_HINT_RE.search(message)
    if match is None:
        return None
    return match.group(1).upper()


def _active_rx_texts(meds_facts: Sequence[Mapping[str, Any]]) -> list[str]:
    texts: list[str] = []
    for fact in meds_facts:
        text = fact.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text)
    return texts


def _maybe_append_research(
    *,
    route: Route | str,
    message: str,
    correlation_id: str,
    results: list[dict[str, object]],
    progress_messages: list[str],
) -> None:
    """Gate openFDA/DailyMed research onto meds+dosing turns (H8/H11).

    Mutates ``results`` / ``progress_messages`` in place. Never sets graph error.
    """
    # H11: research only on meds route — never brief/labs.
    if route != "meds":
        return
    if not is_dosing_like(message):
        return

    meds_facts = _meds_facts_from_results(results)
    resolved = resolve_drug_query(message, meds_facts)
    if resolved is None:
        return
    if resolved.status is not ResolveStatus.OK or resolved.query is None:
        # BLOCKED / NONE → no HTTP, no research progress (verify may refuse).
        return

    # Progress only when HTTP will actually run.
    progress_messages.append(RESEARCH_PROGRESS_MESSAGE)

    try:
        label = fetch_label(resolved.query, correlation_id=correlation_id)
        if not label.ok or not label.source or not label.set_id:
            return

        form_hint = _form_hint_from_message(message)
        if label.source == "openfda" and label.openfda_result is not None:
            facts = extract_openfda_facts(
                label.openfda_result,
                form_hint=form_hint,
            )
        elif label.source == "dailymed" and label.dailymed_xml is not None:
            facts = extract_dailymed_facts(
                label.dailymed_xml,
                set_id=label.set_id,
                form_hint=form_hint,
            )
        else:
            facts = []

        on_chart = reconcile_on_chart_after_hit(
            resolved.query.on_chart,
            label.generic_names,
            label.brand_names,
            _active_rx_texts(meds_facts),
        )
        results.append(
            build_research_tool_result(
                facts,
                on_chart=on_chart,
                query_term=resolved.query.term,
                source=label.source,
                set_id=label.set_id,
            )
        )
    except Exception:
        # H8: research failure never sets graph error — skip research facts.
        logger.warning(
            "Research label fetch failed; skipping research facts",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )


def make_tools_node(gateway: GatewayClient) -> Callable[[GraphState], dict[str, object]]:
    """Build a tools node bound to a gateway client."""

    def tools_node(state: GraphState) -> dict[str, object]:
        pid = state.get("pid")
        user_id = state.get("user_id")
        correlation_id = state.get("correlation_id", "")
        route = state.get("route", "brief")
        message = state.get("message", "") or ""
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

        progress_messages = [chart_progress_for_route(route)]
        _maybe_append_research(
            route=route,
            message=message,
            correlation_id=correlation_id,
            results=results,
            progress_messages=progress_messages,
        )

        return {
            "tool_results": results,
            "tool_domain_errors": domain_errors,
            "requested_tools": tool_names,
            "progress_messages": progress_messages,
        }

    return tools_node
