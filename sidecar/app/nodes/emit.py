"""Assemble verified clinical text + citation batch node."""

from __future__ import annotations

from ..claims import build_citation_records, build_clinical_payload
from ..nodes.tools import ROUTE_TOOLS
from ..state import GraphState


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

    # Same verified list + tool kwargs so citation_id (c1…n) matches segments (H3).
    payload = build_clinical_payload(
        verified,
        refusals,
        tool_results=tool_results,
        tool_domain_errors=tool_domain_errors,
        requested_tools=requested,
    )
    citations = build_citation_records(verified, tool_results=tool_results)

    return {
        "clinical_text": payload["text"],
        "clinical_segments": payload["segments"],
        "citations": citations,
    }
