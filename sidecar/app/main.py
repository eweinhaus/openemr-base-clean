"""FastAPI shell for the Clinical Co-Pilot LangGraph sidecar (PRD 03 Wave 1)."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from .auth import SECRET_HEADER, verify_secret
from .gateway_client import GatewayClient
from .sse import format_sse
from .stream import iter_chat_events

DEFAULT_GATEWAY_TOOL_URL = "http://openemr/interface/ask_copilot/tool_proxy.php"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-haiku-4.5"


@dataclass(frozen=True)
class Settings:
    internal_secret: str
    gateway_tool_url: str
    openrouter_api_key: str
    openrouter_base_url: str
    openrouter_model: str
    llm_timeout_seconds: float
    tool_timeout_seconds: float


def load_settings() -> Settings:
    secret = os.environ.get("COPILOT_INTERNAL_SECRET", "")
    return Settings(
        internal_secret=secret,
        gateway_tool_url=os.environ.get(
            "COPILOT_GATEWAY_TOOL_URL", DEFAULT_GATEWAY_TOOL_URL
        ),
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
    )


class ChatRequest(BaseModel):
    correlation_id: str = ""
    user_id: Optional[int] = None
    username: str = ""
    pid: Optional[int] = None
    message: str = ""
    transcript: List[Any] = Field(default_factory=list)


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
    yield


app = FastAPI(title="Clinical Co-Pilot Sidecar", lifespan=lifespan)


def get_settings() -> Settings:
    return load_settings()


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

    openrouter["configured"] = bool(settings.openrouter_api_key)
    # A missing OpenRouter key means clinical turns will fail — report unready
    # so a health probe catches the misconfiguration instead of masking it.
    # H10 (PRD 05): do not probe openFDA / DailyMed here — research is
    # best-effort at tool time and must not gate readiness.
    ready = (
        gateway.get("reachable") is True
        and bool(settings.openrouter_api_key)
        and openrouter.get("reachable") is True
    )
    return {
        "ready": ready,
        "gateway": gateway,
        "openrouter": openrouter,
        "openrouter_model": settings.openrouter_model,
    }


def _chat_event_iterator(
    settings: Settings,
    *,
    correlation_id: str,
    pid: Optional[int],
    user_id: Optional[int],
    message: str,
    transcript: List[Any],
) -> Iterator[str]:
    gateway = GatewayClient(
        secret=settings.internal_secret,
        tool_url=settings.gateway_tool_url,
        timeout=settings.tool_timeout_seconds,
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


@app.get("/health")
async def health() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/ready")
async def ready() -> JSONResponse:
    settings = get_settings()
    body = await check_readiness(settings)
    return JSONResponse(content=body)


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
