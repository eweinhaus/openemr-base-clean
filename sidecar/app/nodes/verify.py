"""Deterministic claim verification node."""

from __future__ import annotations

import logging

from ..claims import (
    Refusal,
    build_tool_fact_map,
    filter_refusals,
    verify_claims,
)
from ..research import RESEARCH_TABLES, is_dosing_like
from ..state import DOSING_REFUSAL, GraphState

logger = logging.getLogger(__name__)

_CANONICAL_REFUSALS: dict[str, Refusal] = {
    DOSING_REFUSAL.code: DOSING_REFUSAL,
}


def _has_verified_research_dosing(verified: list) -> bool:
    """True when a verified claim cites an openFDA/DailyMed dosage locator (H1)."""
    for claim in verified:
        if getattr(claim, "source_type", None) != "research":
            continue
        locator = getattr(claim, "locator", None)
        if locator is None:
            continue
        if locator.table in RESEARCH_TABLES:
            return True
    return False


def verify_node(state: GraphState) -> dict[str, object]:
    draft = state.get("draft_claims")
    tool_results = state.get("tool_results") or []
    correlation_id = state.get("correlation_id", "")

    if draft is None:
        return {}

    fact_map = build_tool_fact_map(tool_results)
    verified = verify_claims(draft, fact_map)

    dropped = len(draft.claims) - len(verified)
    if dropped > 0:
        logger.info(
            "Claims dropped during verify",
            extra={
                "correlation_id": correlation_id,
                "dropped_count": dropped,
            },
        )

    refusals = filter_refusals(
        list(draft.refusals),
        canonical=_CANONICAL_REFUSALS,
    )
    # H1: append no_research only when dosing-like AND no verified research dosing fact.
    message = state.get("message", "")
    if is_dosing_like(message) and not _has_verified_research_dosing(verified):
        if not any(r.code == DOSING_REFUSAL.code for r in refusals):
            refusals.append(DOSING_REFUSAL)

    return {
        "verified_claims": verified,
        "refusals": refusals,
    }
