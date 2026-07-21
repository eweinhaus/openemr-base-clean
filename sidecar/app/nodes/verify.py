"""Deterministic claim verification node."""

from __future__ import annotations

import logging
import re

from ..claims import Refusal, build_tool_index, verify_claims
from ..state import DOSING_REFUSAL, GraphState

logger = logging.getLogger(__name__)

_DOSING_PATTERN = re.compile(
    r"\b(dose|dosing|dosage|titrat(?:e|ion)|how\s+much|mg\s*/?\s*kg)\b",
    re.IGNORECASE,
)


def _message_looks_like_dosing(message: str) -> bool:
    return bool(_DOSING_PATTERN.search(message))


def verify_node(state: GraphState) -> dict[str, object]:
    draft = state.get("draft_claims")
    tool_results = state.get("tool_results") or []
    correlation_id = state.get("correlation_id", "")

    if draft is None:
        return {}

    tool_index = build_tool_index(tool_results)
    verified = verify_claims(draft, tool_index)

    dropped = len(draft.claims) - len(verified)
    if dropped > 0:
        logger.info(
            "Claims dropped during verify",
            extra={
                "correlation_id": correlation_id,
                "dropped_count": dropped,
            },
        )

    refusals: list[Refusal] = list(draft.refusals)
    route = state.get("route")
    message = state.get("message", "")
    if route == "meds" or _message_looks_like_dosing(message):
        if not any(r.code == DOSING_REFUSAL.code for r in refusals):
            refusals.append(DOSING_REFUSAL)

    return {
        "verified_claims": verified,
        "refusals": refusals,
    }
