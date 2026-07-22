"""Run the agent graph and yield SSE event payloads."""

from __future__ import annotations

import logging
from typing import Any, Iterator, Optional

from .errors import ERROR_UNEXPECTED, sse_error_payload
from .gateway_client import GatewayClient
from .graph import build_graph
from .llm import MAX_TRANSCRIPT_TURNS
from .state import GraphState

logger = logging.getLogger(__name__)


def build_stream_config(correlation_id: str) -> dict[str, Any]:
    """RunnableConfig for graph.stream — correlation join only (no pid / message)."""
    return {
        "metadata": {"correlation_id": correlation_id},
        "tags": ["clinical-copilot"],
    }


def build_initial_state(
    *,
    correlation_id: str,
    pid: Optional[int],
    user_id: Optional[int],
    message: str,
    transcript: list[Any],
) -> GraphState:
    truncated: list[Any] = []
    if transcript:
        for entry in transcript[-MAX_TRANSCRIPT_TURNS:]:
            if not isinstance(entry, dict):
                continue
            role = entry.get("role")
            text = entry.get("text")
            if role not in ("user", "assistant") or not isinstance(text, str):
                continue
            cleaned = text.strip()
            if not cleaned:
                continue
            truncated.append({"role": role, "text": cleaned[:4000]})
    return GraphState(
        correlation_id=correlation_id,
        pid=pid,
        user_id=user_id,
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
    user_id: Optional[int],
    message: str,
    transcript: list[Any],
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Sync generator: progress during graph stream, then clinical/error + done."""
    try:
        graph = build_graph(gateway)
        initial = build_initial_state(
            correlation_id=correlation_id,
            pid=pid,
            user_id=user_id,
            message=message,
            transcript=transcript,
        )

        final_state: GraphState = dict(initial)
        config = build_stream_config(correlation_id)

        for update in graph.stream(initial, config=config, stream_mode="updates"):
            for _node_name, node_update in update.items():
                if not isinstance(node_update, dict):
                    continue
                for progress in node_update.get("progress_messages", []):
                    if isinstance(progress, str) and progress:
                        yield ("progress", {"message": progress})
                final_state.update(node_update)

        error_code = final_state.get("error")
        if error_code:
            yield (
                "error",
                sse_error_payload(str(error_code), correlation_id=correlation_id),
            )
            return

        clinical_text = final_state.get("clinical_text", "")
        segments = final_state.get("clinical_segments") or []
        citations = final_state.get("citations") or []
        yield ("clinical", {"text": clinical_text, "segments": segments})
        # Always emit citation after successful clinical (even citations: []).
        yield ("citation", {"citations": citations})
        yield ("done", {"correlation_id": correlation_id})
    except Exception:
        # Never abort mid-stream without an error frame (keeps hybrid SSE contract).
        logger.exception(
            "Chat graph failed unexpectedly",
            extra={"correlation_id": correlation_id},
        )
        yield (
            "error",
            sse_error_payload(ERROR_UNEXPECTED, correlation_id=correlation_id),
        )
