"""Assemble verified clinical text + citation batch node."""

from __future__ import annotations

from ..claims import build_citation_records, build_clinical_payload
from ..nodes.synthesize import format_synthesis_failure_line
from ..nodes.tools import ROUTE_TOOLS
from ..state import GraphState


def _resolve_synthesis_failure_line(state: GraphState, *, verified_count: int) -> str | None:
    """Ensure verified turns never emit claims-only with no visible narrative."""
    raw = state.get("synthesis_failure_line")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()

    turn_summary = state.get("turn_summary")
    if isinstance(turn_summary, str) and turn_summary.strip():
        return None

    if verified_count <= 0:
        return None

    return format_synthesis_failure_line("parse_failed")


def emit_node(state: GraphState) -> dict[str, object]:
    if state.get("error") or state.get("clinical_text"):
        return {}

    verified = state.get("verified_claims") or []
    refusals = state.get("refusals") or []
    tool_results = state.get("tool_results") or []
    tool_domain_errors = state.get("tool_domain_errors") or {}
    requested = state.get("requested_tools")
    if not requested:
        route = state.get("route", "brief")
        requested = list(ROUTE_TOOLS.get(route, ["patient_context"]))

    synthesis_failure_line = _resolve_synthesis_failure_line(
        state,
        verified_count=len(verified),
    )

    # Same verified list + tool kwargs so citation_id (c1…n) matches segments (H3).
    payload = build_clinical_payload(
        verified,
        refusals,
        tool_results=tool_results,
        tool_domain_errors=tool_domain_errors,
        requested_tools=requested,
        message=state.get("message", "") or "",
        turn_summary=state.get("turn_summary"),
        synthesis_failure_line=synthesis_failure_line,
    )
    citations = build_citation_records(verified, tool_results=tool_results)

    return {
        "clinical_text": payload["text"],
        "clinical_segments": payload["segments"],
        "citations": citations,
    }
