"""LangGraph agent state for the Clinical Co-Pilot sidecar."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional, TypedDict

from .claims import Claim, DraftClaims, Refusal

Route = Literal["brief", "labs", "meds"]

UNBOUND_MESSAGE = "Select a patient before asking about the chart."
# Fallback UI text when an error code has no mapped message (see errors.py).
GENERIC_ERROR_MESSAGE = "Something went wrong. Try again."
# Mirrors the gateway's ASK_COPILOT_MESSAGE_MAX_LENGTH cap.
MAX_MESSAGE_LENGTH = 4000

DOSING_REFUSAL = Refusal(
    code="no_research",
    text="No retrieved label source for dosing — I won't guess.",
)

ALLERGY_CONTRADICTION_REFUSAL = Refusal(
    code="allergy_contradiction",
    text="This medication appears on the allergy list — I won't suggest dosing.",
)


class GraphState(TypedDict, total=False):
    correlation_id: str
    pid: Optional[int]
    user_id: Optional[int]
    message: str
    transcript: list[Any]
    route: Route
    tool_results: list[dict[str, Any]]
    # tool_name → stable gateway error code for per-domain unavailable assembly.
    tool_domain_errors: dict[str, str]
    # Tool names requested for this route (for empty/unavailable assembly).
    requested_tools: list[str]
    draft_claims: Optional[DraftClaims]
    verified_claims: list[Claim]
    refusals: Annotated[list[Refusal], operator.add]
    clinical_text: str
    # Ordered clinical segments (claim + assembly) for SSE; paired with citations (PRD 06).
    clinical_segments: list[dict[str, Any]]
    # Citation batch for SSE; citation_id values match claim segments (H3).
    citations: list[dict[str, Any]]
    # Stable non-PHI error code (see errors.py); truthy short-circuits the graph to emit.
    error: str
    progress_messages: Annotated[list[str], operator.add]
