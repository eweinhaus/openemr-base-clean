"""Refuse-if-unbound and empty-message guard node."""

from __future__ import annotations

from ..state import GENERIC_ERROR_MESSAGE, UNBOUND_MESSAGE, GraphState


def refuse_node(state: GraphState) -> dict[str, object]:
    pid = state.get("pid")
    message = (state.get("message") or "").strip()

    if pid is None or pid <= 0:
        return {"clinical_text": UNBOUND_MESSAGE}

    if not message:
        return {"error": GENERIC_ERROR_MESSAGE}

    return {}
