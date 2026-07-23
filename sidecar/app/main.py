"""FastAPI shell for the Clinical Co-Pilot LangGraph sidecar (PRD 03 Wave 1)."""

from __future__ import annotations

import os
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from .auth import SECRET_HEADER, verify_secret
from .errors import ERROR_SIDECAR_UNREADY, sse_error_payload
from .gateway_client import (
    DEFAULT_GATEWAY_DISCLOSURE_URL,
    GatewayClient,
    derive_disclosure_url,
)
from .sse import format_sse
from .stream import iter_chat_events
from .tracing import apply_hide_io_policy, langsmith_api_key, probe_langsmith

DEFAULT_GATEWAY_TOOL_URL = "http://openemr/interface/ask_copilot/tool_proxy.php"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-haiku-4.5"
DEFAULT_LANGSMITH_PROJECT = "openemr-copilot-demo"
DEFAULT_READY_CACHE_TTL_SECONDS = 30.0
DEFAULT_BRIEF_CACHE_TTL_SECONDS = 1800.0
DEFAULT_BRIEF_CACHE_SOFT_REFRESH_SECONDS = 600.0
DEFAULT_BRIEF_CACHE_SCHEMA_VERSION = 1

# Process-local readiness cache for /v1/chat (ops /ready always probes fresh).
_ready_cache_body: Dict[str, Any] | None = None
_ready_cache_expires_at: float = 0.0


@dataclass(frozen=True)
class Settings:
    internal_secret: str
    gateway_tool_url: str
    gateway_disclosure_url: str
    openrouter_api_key: str
    openrouter_base_url: str
    openrouter_model: str
    llm_timeout_seconds: float
    tool_timeout_seconds: float
    ready_cache_ttl_seconds: float
    langsmith_api_key: str
    langsmith_tracing: bool
    langsmith_project: str
    brief_cache_ttl_seconds: float
    brief_cache_soft_refresh_seconds: float
    brief_cache_schema_version: int


def load_settings() -> Settings:
    secret = os.environ.get("COPILOT_INTERNAL_SECRET", "")
    tracing_raw = os.environ.get("LANGSMITH_TRACING", "").strip().lower()
    tool_url = os.environ.get("COPILOT_GATEWAY_TOOL_URL", DEFAULT_GATEWAY_TOOL_URL)
    disclosure_raw = os.environ.get("COPILOT_GATEWAY_DISCLOSURE_URL", "").strip()
    disclosure_url = disclosure_raw or derive_disclosure_url(tool_url)
    if not disclosure_url:
        disclosure_url = DEFAULT_GATEWAY_DISCLOSURE_URL
    return Settings(
        internal_secret=secret,
        gateway_tool_url=tool_url,
        gateway_disclosure_url=disclosure_url,
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        openrouter_base_url=os.environ.get(
            "OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL
        ).rstrip("/"),
        openrouter_model=os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
        llm_timeout_seconds=float(
            os.environ.get("COPILOT_LLM_TIMEOUT_SECONDS", "30")
        ),
        tool_timeout_seconds=float(
            os.environ.get("COPILOT_TOOL_TIMEOUT_SECONDS", "10")
        ),
        ready_cache_ttl_seconds=float(
            os.environ.get(
                "COPILOT_READY_CACHE_TTL_SECONDS",
                str(DEFAULT_READY_CACHE_TTL_SECONDS),
            )
        ),
        langsmith_api_key=langsmith_api_key(),
        langsmith_tracing=tracing_raw in ("1", "true", "yes", "on"),
        langsmith_project=os.environ.get(
            "LANGSMITH_PROJECT", DEFAULT_LANGSMITH_PROJECT
        ),
        brief_cache_ttl_seconds=float(
            os.environ.get(
                "COPILOT_BRIEF_CACHE_TTL_SECONDS",
                str(DEFAULT_BRIEF_CACHE_TTL_SECONDS),
            )
        ),
        brief_cache_soft_refresh_seconds=float(
            os.environ.get(
                "COPILOT_BRIEF_CACHE_SOFT_REFRESH_SECONDS",
                str(DEFAULT_BRIEF_CACHE_SOFT_REFRESH_SECONDS),
            )
        ),
        brief_cache_schema_version=int(
            os.environ.get(
                "COPILOT_BRIEF_CACHE_SCHEMA_VERSION",
                str(DEFAULT_BRIEF_CACHE_SCHEMA_VERSION),
            )
        ),
    )


class ChatRequest(BaseModel):
    correlation_id: str = ""
    user_id: Optional[int] = None
    username: str = ""
    pid: Optional[int] = None
    message: str = ""
    transcript: List[Any] = Field(default_factory=list)


class PrefetchBriefRequest(BaseModel):
    user_id: int
    username: str = ""
    pid: int
    correlation_id: str = ""
    prefetch: bool = True


def _require_secret_at_startup() -> None:
    secret = os.environ.get("COPILOT_INTERNAL_SECRET", "")
    if not secret:
        print("COPILOT_INTERNAL_SECRET is required", file=sys.stderr)
        sys.exit(1)
    if secret == "dev-copilot-secret-change-me":
        print(
            "WARNING: COPILOT_INTERNAL_SECRET is the weak default; "
            "rotate before any public deploy",
            file=sys.stderr,
        )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _require_secret_at_startup()
    # When tracing is on, force hide I/O so GraphState PHI never leaves the box.
    apply_hide_io_policy()
    yield


app = FastAPI(title="Clinical Co-Pilot Sidecar", lifespan=lifespan)


def get_settings() -> Settings:
    return load_settings()


def clear_ready_cache() -> None:
    """Test helper — drop the process-local readiness cache."""
    global _ready_cache_body, _ready_cache_expires_at
    _ready_cache_body = None
    _ready_cache_expires_at = 0.0


async def _probe_url(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    try:
        response = await client.request("HEAD", url, headers=headers)
        if response.status_code >= 400:
            response = await client.get(url, headers=headers)
        return {
            "reachable": response.status_code < 500,
            "status_code": response.status_code,
        }
    except httpx.HTTPError as exc:
        return {"reachable": False, "error": type(exc).__name__}


async def check_readiness(settings: Settings) -> Dict[str, Any]:
    timeout = httpx.Timeout(settings.tool_timeout_seconds)
    gateway: Dict[str, Any]
    openrouter: Dict[str, Any]
    langsmith: Dict[str, Any]

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        gateway = await _probe_url(
            client,
            settings.gateway_tool_url,
            headers={SECRET_HEADER: settings.internal_secret},
        )

        openrouter_headers: Dict[str, str] = {}
        if settings.openrouter_api_key:
            openrouter_headers["Authorization"] = (
                f"Bearer {settings.openrouter_api_key}"
            )
        openrouter = await _probe_url(
            client,
            f"{settings.openrouter_base_url}/models",
            headers=openrouter_headers or None,
        )

        # Soft field only — never alone flips ready=false; never probes FDA.
        langsmith = await probe_langsmith(
            client, api_key=settings.langsmith_api_key
        )

    openrouter["configured"] = bool(settings.openrouter_api_key)
    # Hard ready = gateway reachable + OpenRouter key present.
    # openrouter.reachable is soft (like langsmith): a transient /models 5xx
    # must not fail-close clinical turns — live LLM errors surface as llm_*.
    # H10 (PRD 05): do not probe openFDA / DailyMed here.
    ready = gateway.get("reachable") is True and bool(settings.openrouter_api_key)
    return {
        "ready": ready,
        "gateway": gateway,
        "openrouter": openrouter,
        "langsmith": langsmith,
        "openrouter_model": settings.openrouter_model,
    }


async def get_readiness(
    settings: Settings,
    *,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Return readiness; cache for chat hot path, fresh for ops /ready."""
    global _ready_cache_body, _ready_cache_expires_at

    now = time.monotonic()
    ttl = max(0.0, float(settings.ready_cache_ttl_seconds))
    if (
        not force_refresh
        and ttl > 0
        and _ready_cache_body is not None
        and now < _ready_cache_expires_at
    ):
        return _ready_cache_body

    body = await check_readiness(settings)
    _ready_cache_body = body
    _ready_cache_expires_at = now + ttl
    return body


def _chat_event_iterator(
    settings: Settings,
    *,
    correlation_id: str,
    pid: Optional[int],
    user_id: Optional[int],
    message: str,
    transcript: List[Any],
) -> Iterator[str]:
    from .prefetch import decrement_chat_active, increment_chat_active

    increment_chat_active()
    try:
        gateway = GatewayClient(
            secret=settings.internal_secret,
            tool_url=settings.gateway_tool_url,
            timeout=settings.tool_timeout_seconds,
            disclosure_url=settings.gateway_disclosure_url,
        )
        for event_name, payload in iter_chat_events(
            gateway=gateway,
            correlation_id=correlation_id,
            pid=pid,
            user_id=user_id,
            message=message,
            transcript=transcript,
        ):
            yield format_sse(event_name, payload)
    finally:
        decrement_chat_active()


def _unready_event_iterator(*, correlation_id: str) -> Iterator[str]:
    """Fail-closed SSE: one error frame, no graph / LLM / clinical."""
    yield format_sse(
        "error",
        sse_error_payload(ERROR_SIDECAR_UNREADY, correlation_id=correlation_id),
    )


@app.get("/health")
async def health() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/ready")
async def ready() -> JSONResponse:
    settings = get_settings()
    # Ops probe always fresh — do not serve a stale cache here.
    body = await get_readiness(settings, force_refresh=True)
    # Orchestrators that key off HTTP status alone must see 503 when not ready.
    status_code = 200 if body.get("ready") else 503
    return JSONResponse(content=body, status_code=status_code)


@app.post("/v1/chat", response_model=None)
async def chat(
    request: Request,
    body: ChatRequest,
    x_copilot_internal_secret: Optional[str] = Header(default=None),
    x_correlation_id: Optional[str] = Header(default=None),
) -> Union[StreamingResponse, JSONResponse]:
    settings = get_settings()
    provided_secret = x_copilot_internal_secret or request.headers.get(SECRET_HEADER)
    if not verify_secret(provided_secret, settings.internal_secret):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})

    correlation_id = body.correlation_id or x_correlation_id or ""

    readiness = await get_readiness(settings, force_refresh=False)
    if not readiness.get("ready"):
        return StreamingResponse(
            _unready_event_iterator(correlation_id=correlation_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "close",
            },
        )

    return StreamingResponse(
        _chat_event_iterator(
            settings,
            correlation_id=correlation_id,
            pid=body.pid,
            user_id=body.user_id,
            message=body.message,
            transcript=body.transcript,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "close",
        },
    )


@app.post("/v1/prefetch-brief")
async def prefetch_brief(
    request: Request,
    body: PrefetchBriefRequest,
    x_copilot_internal_secret: Optional[str] = Header(default=None),
) -> JSONResponse:
    settings = get_settings()
    provided_secret = x_copilot_internal_secret or request.headers.get(SECRET_HEADER)
    if not verify_secret(provided_secret, settings.internal_secret):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})

    readiness = await get_readiness(settings, force_refresh=False)
    if not readiness.get("ready"):
        return JSONResponse(status_code=200, content={"ok": False, "error": "unready"})

    from .prefetch import enqueue_prefetch

    queued = enqueue_prefetch(
        user_id=body.user_id,
        username=body.username,
        pid=body.pid,
        correlation_id=body.correlation_id,
    )
    return JSONResponse(status_code=200, content={"ok": True, "queued": queued})
