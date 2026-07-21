"""Run the agent graph and yield SSE event payloads."""

from __future__ import annotations

from typing import Any, Iterator, Optional

from .gateway_client import GatewayClient
from .graph import build_graph
from .llm import MAX_TRANSCRIPT_TURNS
from .state import GENERIC_ERROR_MESSAGE, GraphState


def build_initial_state(
    *,
    correlation_id: str,
    pid: Optional[int],
    message: str,
    transcript: list[Any],
) -> GraphState:
    truncated = list(transcript[-MAX_TRANSCRIPT_TURNS:]) if transcript else []
    return GraphState(
        correlation_id=correlation_id,
        pid=pid,
        message=message,
        transcript=truncated,
        tool_results=[],
        verified_claims=[],
        refusals=[],
        progress_messages=[],
    )


def iter_chat_events(
    *,
    gateway: GatewayClient,
    correlation_id: str,
    pid: Optional[int],
    message: str,
    transcript: list[Any],
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Sync generator: progress during graph stream, then clinical/error + done."""
    graph = build_graph(gateway)
    initial = build_initial_state(
        correlation_id=correlation_id,
        pid=pid,
        message=message,
        transcript=transcript,
    )

    final_state: GraphState = dict(initial)

    for update in graph.stream(initial, stream_mode="updates"):
        for _node_name, node_update in update.items():
            if not isinstance(node_update, dict):
                continue
            for progress in node_update.get("progress_messages", []):
                if isinstance(progress, str) and progress:
                    yield ("progress", {"message": progress})
            final_state.update(node_update)

    if final_state.get("error"):
        yield ("error", {"message": GENERIC_ERROR_MESSAGE})
        return

    clinical_text = final_state.get("clinical_text", "")
    yield ("clinical", {"text": clinical_text})
    yield ("done", {"correlation_id": correlation_id})
