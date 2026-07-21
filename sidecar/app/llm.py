"""OpenRouter Haiku helpers for route classification and claim drafting."""

from __future__ import annotations

import json
import logging
import os
import re
from contextvars import ContextVar
from typing import Any, Literal

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

Route = Literal["brief", "labs", "meds"]

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-3.5-haiku"
DEFAULT_LLM_TIMEOUT_SECONDS = 30.0
MAX_TRANSCRIPT_TURNS = 8
LLM_TEMPERATURE = 0.0

VALID_ROUTES = frozenset({"brief", "labs", "meds"})

ROUTE_SYSTEM_PROMPT = (
    "You classify clinical co-pilot user messages into exactly one route. "
    "Reply with only one word: brief, labs, or meds. "
    "brief = general chart summary or overview. "
    "labs = laboratory results or values. "
    "meds = medications or prescriptions. "
    "If intent is mixed or unclear, pick the primary intent."
)

DRAFT_SYSTEM_PROMPT = (
    "Draft structured clinical claims as JSON only. "
    "Use this exact top-level shape: "
    '{"claims":[{"text":"...","source_type":"chart|note|research",'
    '"locator":{"table":"...","id":"..."},"excerpt":"optional"}],'
    '"refusals":[{"code":"...","text":"..."}]}. '
    "Every claim locator must match a fact from the provided tool results. "
    "Do not invent facts, tables, ids, or research sources. "
    "Use refusals when you cannot support a request from tool facts alone "
    "(for example dosing without a retrieved label source)."
)

logger = logging.getLogger(__name__)
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class LlmError(Exception):
    """Raised when an OpenRouter LLM call fails."""


def set_correlation_id(correlation_id: str | None) -> None:
    """Set correlation id for LLM log context (never logged message bodies)."""
    _correlation_id.set(correlation_id)


def normalize_route(raw: str) -> Route:
    """Normalize a route label; invalid or empty values default to brief."""
    text = raw.strip()
    if not text:
        return "brief"

    primary = text.split()[0].lower()
    primary = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", primary)
    if primary in VALID_ROUTES:
        return primary  # type: ignore[return-value]
    return "brief"


def route_message(message: str, transcript: list | None = None) -> str:
    """Classify the user message into brief, labs, or meds via Haiku."""
    user_prompt = _build_route_user_prompt(message, transcript)
    raw = _chat_completion(
        purpose="route",
        system_prompt=ROUTE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )
    return normalize_route(raw)


def draft_claims_raw(
    message: str,
    tool_results: list[Any],
    transcript: list | None = None,
) -> str:
    """Draft claims JSON from tool facts via Haiku (verify happens elsewhere)."""
    user_prompt = _build_draft_user_prompt(message, tool_results, transcript)
    return _chat_completion(
        purpose="draft",
        system_prompt=DRAFT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        json_mode=True,
    )


def _build_route_user_prompt(message: str, transcript: list | None) -> str:
    transcript_text = _format_transcript(transcript)
    return (
        f"User message:\n{message.strip()}\n\n"
        f"Recent transcript (last {MAX_TRANSCRIPT_TURNS} turns):\n{transcript_text}"
    )


def _build_draft_user_prompt(
    message: str,
    tool_results: list[Any],
    transcript: list | None,
) -> str:
    tool_json = json.dumps(tool_results, separators=(",", ":"), default=str)
    transcript_text = _format_transcript(transcript)
    return (
        f"User message:\n{message.strip()}\n\n"
        f"Recent transcript (last {MAX_TRANSCRIPT_TURNS} turns):\n{transcript_text}\n\n"
        f"Tool results (use only these facts for locators):\n{tool_json}"
    )


def _truncate_transcript(transcript: list | None) -> list[Any]:
    if not transcript:
        return []
    return list(transcript[-MAX_TRANSCRIPT_TURNS:])


def _format_transcript(transcript: list | None) -> str:
    turns = _truncate_transcript(transcript)
    if not turns:
        return "(none)"
    return json.dumps(turns, separators=(",", ":"), default=str)


def _load_llm_config() -> tuple[str, str, str, float]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    base_url = os.environ.get(
        "OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL
    ).rstrip("/")
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
    timeout = float(
        os.environ.get("COPILOT_LLM_TIMEOUT_SECONDS", str(DEFAULT_LLM_TIMEOUT_SECONDS))
    )
    return api_key, base_url, model, timeout


def _get_client() -> OpenAI:
    api_key, base_url, _, timeout = _load_llm_config()
    if not api_key:
        raise LlmError("OPENROUTER_API_KEY is not configured")
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=0,
    )


def _chat_completion(
    *,
    purpose: str,
    system_prompt: str,
    user_prompt: str,
    json_mode: bool = False,
) -> str:
    _, _, model, _ = _load_llm_config()
    correlation_id = _correlation_id.get()
    log_extra: dict[str, Any] = {"purpose": purpose, "model": model}
    if correlation_id:
        log_extra["correlation_id"] = correlation_id
    logger.info("OpenRouter LLM request", extra=log_extra)

    client = _get_client()
    request_kwargs: dict[str, Any] = {
        "model": model,
        "temperature": LLM_TEMPERATURE,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if json_mode:
        request_kwargs["response_format"] = {"type": "json_object"}

    try:
        response = client.chat.completions.create(**request_kwargs)
    except (APIConnectionError, APITimeoutError) as exc:
        raise LlmError("OpenRouter request failed") from exc
    except APIStatusError as exc:
        raise LlmError(f"OpenRouter returned HTTP {exc.status_code}") from exc
    except Exception as exc:
        raise LlmError("OpenRouter request failed") from exc

    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise LlmError("OpenRouter returned empty content")
    return content.strip()
