"""Background prefetch queue for UC-1 brief cache (PRD 09 Wave 2)."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Optional, Set, Tuple

from .brief_cache import get_brief_cache
from .gateway_client import GatewayClient
from .graph import build_graph
from .llm import AUTO_BRIEF_MESSAGE
from .stream import build_initial_state, build_stream_config
from .state import GraphState

logger = logging.getLogger(__name__)

JobKey = Tuple[int, int]


@dataclass(frozen=True)
class PrefetchJob:
    user_id: int
    username: str
    pid: int
    correlation_id: str


_lock = threading.Lock()
_pending: Deque[PrefetchJob] = deque()
_pending_keys: Set[JobKey] = set()
_worker_thread: threading.Thread | None = None
_worker_running = False

_chat_active = 0
_chat_active_lock = threading.Lock()

_DEFER_POLL_SECONDS = 0.05


def increment_chat_active() -> None:
    """Signal an interactive /v1/chat SSE stream is active."""
    global _chat_active
    with _chat_active_lock:
        _chat_active += 1


def decrement_chat_active() -> None:
    """Clear one active /v1/chat SSE stream."""
    global _chat_active
    with _chat_active_lock:
        _chat_active = max(0, _chat_active - 1)


def get_chat_active() -> int:
    with _chat_active_lock:
        return _chat_active


def reset_prefetch_queue() -> None:
    """Test helper — drain queue state and stop the worker."""
    global _worker_thread, _worker_running, _chat_active
    with _lock:
        _pending.clear()
        _pending_keys.clear()
        _worker_running = False
        _worker_thread = None
    with _chat_active_lock:
        _chat_active = 0


def enqueue_prefetch(
    user_id: int,
    username: str,
    pid: int,
    correlation_id: str,
    *,
    settings_loader: Callable[[], Any] | None = None,
) -> bool:
    """Queue a prefetch job. Returns True when a new job was added."""
    key = (user_id, pid)
    with _lock:
        if key in _pending_keys:
            return False
        _pending.append(
            PrefetchJob(
                user_id=user_id,
                username=username,
                pid=pid,
                correlation_id=correlation_id,
            )
        )
        _pending_keys.add(key)
        _start_worker_locked(settings_loader)
    return True


def _start_worker_locked(
    settings_loader: Callable[[], Any] | None,
) -> None:
    global _worker_thread, _worker_running
    if _worker_running and _worker_thread is not None and _worker_thread.is_alive():
        return
    _worker_running = True
    _worker_thread = threading.Thread(
        target=_worker_loop,
        args=(settings_loader,),
        daemon=True,
        name="copilot-prefetch-worker",
    )
    _worker_thread.start()


def _worker_loop(settings_loader: Callable[[], Any] | None) -> None:
    from .main import load_settings

    loader = settings_loader or load_settings

    while True:
        while get_chat_active() > 0:
            time.sleep(_DEFER_POLL_SECONDS)

        job: PrefetchJob | None = None
        with _lock:
            if not _pending:
                global _worker_thread, _worker_running
                _worker_running = False
                _worker_thread = None
                return
            job = _pending.popleft()
            _pending_keys.discard((job.user_id, job.pid))

        try:
            settings = loader()
            _run_prefetch_job(job, settings)
        except Exception:
            logger.exception(
                "Prefetch job failed",
                extra={"correlation_id": job.correlation_id, "pid": job.pid},
            )


def _run_prefetch_job(job: PrefetchJob, settings: Any) -> None:
    gateway = GatewayClient(
        secret=settings.internal_secret,
        tool_url=settings.gateway_tool_url,
        timeout=settings.tool_timeout_seconds,
        disclosure_url=settings.gateway_disclosure_url,
    )
    graph = build_graph(gateway)

    initial = build_initial_state(
        correlation_id=job.correlation_id,
        pid=job.pid,
        user_id=job.user_id,
        message=AUTO_BRIEF_MESSAGE,
        transcript=[],
    )
    initial["route"] = "brief"
    initial["prefetch"] = True

    final_state: GraphState = dict(initial)
    config = build_stream_config(job.correlation_id)

    for update in graph.stream(initial, config=config, stream_mode="updates"):
        for _node_name, node_update in update.items():
            if isinstance(node_update, dict):
                final_state.update(node_update)

    if final_state.get("error"):
        logger.warning(
            "Prefetch graph ended with error",
            extra={
                "correlation_id": job.correlation_id,
                "pid": job.pid,
                "error": final_state.get("error"),
            },
        )
        return

    verified = final_state.get("verified_claims") or []
    if len(verified) < 1:
        logger.warning(
            "Prefetch produced zero verified claims — not caching",
            extra={"correlation_id": job.correlation_id, "pid": job.pid},
        )
        return

    clinical_text = final_state.get("clinical_text", "")
    clinical_segments = final_state.get("clinical_segments") or []
    citations = final_state.get("citations") or []

    get_brief_cache().put(
        user_id=job.user_id,
        pid=job.pid,
        correlation_id=job.correlation_id,
        clinical_text=clinical_text,
        clinical_segments=clinical_segments,
        citations=citations,
    )
    logger.info(
        "Prefetch cached brief payload",
        extra={
            "correlation_id": job.correlation_id,
            "pid": job.pid,
            "user_id": job.user_id,
        },
    )
