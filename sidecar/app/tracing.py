"""LangSmith redaction policy + soft readiness helpers (PRD 07).

LangGraph = agent workflow. LangSmith = optional redacted traces of that
workflow. Tracing is env-gated and silent when off/missing keys.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

DEFAULT_LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"
HIDE_INPUTS_ENV = "LANGSMITH_HIDE_INPUTS"
HIDE_OUTPUTS_ENV = "LANGSMITH_HIDE_OUTPUTS"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def tracing_flag_enabled() -> bool:
    """True when LANGSMITH_TRACING (or legacy LANGCHAIN_TRACING_V2) is on."""
    if _env_truthy("LANGSMITH_TRACING"):
        return True
    return _env_truthy("LANGCHAIN_TRACING_V2")


def langsmith_api_key() -> str:
    return (
        os.environ.get("LANGSMITH_API_KEY", "").strip()
        or os.environ.get("LANGCHAIN_API_KEY", "").strip()
    )


def is_langsmith_configured() -> bool:
    return bool(langsmith_api_key())


def langsmith_endpoint() -> str:
    raw = (
        os.environ.get("LANGSMITH_ENDPOINT", "").strip()
        or os.environ.get("LANGCHAIN_ENDPOINT", "").strip()
        or DEFAULT_LANGSMITH_ENDPOINT
    )
    return raw.rstrip("/")


def apply_hide_io_policy() -> None:
    """Force hide inputs/outputs whenever tracing is enabled.

    GraphState is a PHI firehose — never rely on operators remembering hide env.
    """
    if not tracing_flag_enabled():
        return
    os.environ[HIDE_INPUTS_ENV] = "true"
    os.environ[HIDE_OUTPUTS_ENV] = "true"


async def probe_langsmith(
    client: httpx.AsyncClient,
    *,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Soft LangSmith status for /ready. Never gates clinical readiness alone.

    When unconfigured, skips network. When configured, GETs ``/info`` with
    ``x-api-key`` (same budget as other readiness probes via the shared client).
    """
    key = langsmith_api_key() if api_key is None else api_key.strip()
    if not key:
        return {"configured": False, "reachable": False}

    url = f"{langsmith_endpoint()}/info"
    try:
        response = await client.get(url, headers={"x-api-key": key})
        return {
            "configured": True,
            "reachable": response.status_code < 500,
            "status_code": response.status_code,
        }
    except httpx.HTTPError as exc:
        return {
            "configured": True,
            "reachable": False,
            "error": type(exc).__name__,
        }
