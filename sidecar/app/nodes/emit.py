"""Assemble verified clinical text node."""

from __future__ import annotations

from ..claims import assemble_clinical
from ..state import GraphState


def emit_node(state: GraphState) -> dict[str, object]:
    if state.get("error") or state.get("clinical_text"):
        return {}

    verified = state.get("verified_claims") or []
    refusals = state.get("refusals") or []
    return {"clinical_text": assemble_clinical(verified, refusals)}
