"""LangGraph agent state for the Clinical Co-Pilot sidecar."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional, TypedDict

from .claims import Claim, DraftClaims, Refusal

Route = Literal["brief", "labs", "meds"]

UNBOUND_MESSAGE = "Select a patient before asking about the chart."
GENERIC_ERROR_MESSAGE = "Something went wrong. Try again."

DOSING_REFUSAL = Refusal(
    code="no_research",
    text="No retrieved label source for dosing — I won't guess.",
)


class GraphState(TypedDict, total=False):
    correlation_id: str
    pid: Optional[int]
    message: str
    transcript: list[Any]
    route: Route
    tool_results: list[dict[str, Any]]
    draft_claims: Optional[DraftClaims]
    verified_claims: list[Claim]
    refusals: Annotated[list[Refusal], operator.add]
    clinical_text: str
    error: str
    progress_messages: Annotated[list[str], operator.add]
