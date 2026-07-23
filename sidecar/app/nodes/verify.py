"""Deterministic claim verification node."""

from __future__ import annotations

import logging
from typing import Callable

from ..claims import (
    DraftClaims,
    Refusal,
    apply_allergy_contradiction,
    build_tool_fact_map,
    filter_refusals,
    verify_claims,
)
from ..gateway_client import GatewayClient
from ..research import RESEARCH_TABLES, is_dosing_like
from ..state import ALLERGY_CONTRADICTION_REFUSAL, DOSING_REFUSAL, GraphState

logger = logging.getLogger(__name__)

_CANONICAL_REFUSALS: dict[str, Refusal] = {
    DOSING_REFUSAL.code: DOSING_REFUSAL,
    ALLERGY_CONTRADICTION_REFUSAL.code: ALLERGY_CONTRADICTION_REFUSAL,
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


def disclosure_pass_reason(
    verified: list,
    draft: DraftClaims,
    refusals: list[Refusal],
) -> tuple[bool, str]:
    """Map verify outcome to disclosure pass + short allowlisted reason code."""
    if len(verified) > 0:
        return True, "ok"
    dropped = len(draft.claims) - len(verified)
    if dropped > 0:
        return False, "claims_dropped"
    if refusals and not draft.claims:
        return False, "all_refused"
    return False, "empty_verified"


def _run_verify(
    state: GraphState,
    gateway: GatewayClient | None,
) -> dict[str, object]:
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

    verified, allergy_hit = apply_allergy_contradiction(verified, tool_results)

    refusals = filter_refusals(
        list(draft.refusals),
        canonical=_CANONICAL_REFUSALS,
    )
    if allergy_hit and not any(
        r.code == ALLERGY_CONTRADICTION_REFUSAL.code for r in refusals
    ):
        refusals.append(ALLERGY_CONTRADICTION_REFUSAL)

    # H1: append no_research only when dosing-like AND no verified research dosing fact.
    message = state.get("message", "")
    if is_dosing_like(message) and not _has_verified_research_dosing(verified):
        if not any(r.code == DOSING_REFUSAL.code for r in refusals):
            refusals.append(DOSING_REFUSAL)

    if gateway is not None:
        passed, reason = disclosure_pass_reason(verified, draft, refusals)
        try:
            gateway.post_verify_disclosure(
                correlation_id=correlation_id,
                passed=passed,
                reason=reason,
            )
        except Exception:
            # Best-effort: never fail the clinical turn on disclosure errors.
            logger.warning(
                "verify disclosure callback failed",
                extra={"correlation_id": correlation_id},
                exc_info=True,
            )

    return {
        "verified_claims": verified,
        "refusals": refusals,
    }


def make_verify_node(
    gateway: GatewayClient,
) -> Callable[[GraphState], dict[str, object]]:
    """Build a verify node that POSTs a best-effort disclosure callback."""

    def verify_node(state: GraphState) -> dict[str, object]:
        return _run_verify(state, gateway)

    return verify_node


def verify_node(state: GraphState) -> dict[str, object]:
    """Verify without disclosure callback (unit tests / no gateway)."""
    return _run_verify(state, None)
