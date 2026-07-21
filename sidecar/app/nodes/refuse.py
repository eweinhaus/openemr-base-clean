"""Refuse-if-unbound and message guard node."""

from __future__ import annotations

from ..errors import ERROR_INVALID_MESSAGE
from ..state import MAX_MESSAGE_LENGTH, UNBOUND_MESSAGE, GraphState


def refuse_node(state: GraphState) -> dict[str, object]:
    pid = state.get("pid")
    message = (state.get("message") or "").strip()

    if pid is None or pid <= 0:
        return {"clinical_text": UNBOUND_MESSAGE}

    # The gateway caps messages at 4000 chars; enforce the same bound here so a
    # caller with the internal secret cannot push oversized prompts to the LLM.
    if not message or len(message) > MAX_MESSAGE_LENGTH:
        return {"error": ERROR_INVALID_MESSAGE}

    return {}
