"""OpenRouter Haiku helpers for route classification and claim drafting."""

from __future__ import annotations

import json
import logging
import os
import re
from contextvars import ContextVar
from typing import Any, Literal

from langsmith.wrappers import wrap_openai
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

Route = Literal["brief", "labs", "meds"]

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-haiku-4.5"
DEFAULT_LLM_TIMEOUT_SECONDS = 30.0
MAX_TRANSCRIPT_TURNS = 8
LLM_TEMPERATURE = 0.0

VALID_ROUTES = frozenset({"brief", "labs", "meds"})

AUTO_BRIEF_MESSAGE = "Brief me on this patient."

ROUTE_SYSTEM_PROMPT = (
    "You classify clinical co-pilot user messages into exactly one route. "
    "Reply with only one word: brief, labs, or meds. "
    "brief = general chart summary or overview. "
    "labs = laboratory results or values, including whether results are abnormal. "
    "meds = medications, prescriptions, dosing, switches, or replacements. "
    "If intent is mixed or unclear, pick the primary intent."
)

DRAFT_SYSTEM_PROMPT = (
    "Draft structured clinical claims as JSON only. "
    "Use this exact top-level shape: "
    '{"claims":[{"text":"...","source_type":"chart|note|research",'
    '"locator":{"table":"...","id":"..."},"excerpt":"optional"}],'
    '"refusals":[{"code":"...","text":"..."}]}. '
    "Every claim locator must match a fact from the provided tool results. "
    "Do not invent facts, tables, ids, research locators, URLs, or label text. "
    "Named drugs not on the patient's active med list must not be claimed as "
    "the patient's prescription (prescriptions table). "
    "Use source_type research only when research_label tool facts exist. "
    "Use refusals when you cannot support a request from tool facts alone "
    "(for example dosing without a retrieved label source)."
)

BRIEF_DRAFT_ADDENDUM = (
    "Select approximately 5–10 highest-signal facts for a pre-visit brief. "
    "Prioritize: (1) last visit / encounter reason, (2) active conditions, "
    "(3) allergies if present, (4) abnormal or recent labs over normals, "
    "(5) at most one recent note. Use locators from tool results only."
)

LABS_DRAFT_ADDENDUM = (
    "Select lab results relevant to the question; prefer most recent; "
    "include abnormal wording when in fact text."
)

LABS_ABNORMAL_FOLLOWUP_DRAFT_ADDENDUM = (
    "The user is asking whether any lab results are abnormal or stand out. "
    "Include recent lab facts from tool results — prioritize facts whose text "
    "mentions abnormal flags or out-of-range wording. When the question refers "
    "to 'these' or prior results, select from the labs tool facts for this "
    "patient (do not invent values). If every lab fact is normal or lacks an "
    "abnormal flag, still include the relevant recent lab facts so the answer "
    "can state that none are flagged abnormal on file."
)

_LABS_ABNORMAL_FOLLOWUP = re.compile(
    r"\b("
    r"abnormal|abnormality|stand\s+out|concerning|out\s+of\s+range|"
    r"flagged|critical|elevated|reduced|high|low"
    r")\b",
    re.IGNORECASE,
)

_LABS_DEICTIC_FOLLOWUP = re.compile(
    r"\b(these|those|any\s+of\s+(?:these|them)|which\s+ones?)\b",
    re.IGNORECASE,
)

MEDS_DRAFT_ADDENDUM = (
    "For lists include active Rx and allergies; for dosing include research_label "
    "locators when present; never claim off-chart drugs as patient Rx. "
    "For add/prescribe/recommendation questions: still include verified active Rx "
    "and allergy facts from tool results; do not invent new drug recommendations "
    "as chart claims. "
    "For switch/replace questions: include research_label locators for the "
    "proposed (target) drug when tool facts exist; never claim the target drug "
    "as a prescriptions chart Rx when it is not on the active list."
)

SYNTHESIZE_SYSTEM_PROMPT = (
    "Write a short professional clinical pre-visit summary as JSON only. "
    'Use this exact shape: {"summary":"..."}. '
    "Voice: professional clinical tone opening with "
    '"Patient presents for…" when visit reason is known. '
    "Open with visit reason or last encounter when provided in verified facts. "
    "Include verified allergies and abnormal labs when present in verified facts. "
    "You may note chart gaps using the provided domain flags only — do not invent "
    "unavailable or empty-domain copy beyond those flags. "
    "Do not introduce new clinical facts, values, dates, or medications beyond "
    "what appears in verified facts. Prefer the exact date strings from verified "
    "facts (do not reformat dates). Target roughly 80–150 words. "
    "No markdown, bullets, or citation markers."
)

SYNTHESIZE_LABS_SYSTEM_PROMPT = (
    "Write a short direct answer about laboratory results as JSON only. "
    'Use this exact shape: {"summary":"..."}. '
    "Answer the user's question directly. Put abnormal values first when present. "
    "Use only verified lab fact texts — do not introduce new values, dates, or tests. "
    "Do not discuss medications or allergies unless they appear in verified lab facts. "
    "Target roughly 40–80 words. No markdown, bullets, or citation markers."
)

SYNTHESIZE_LABS_ABNORMAL_FOLLOWUP_ADDENDUM = (
    "When the user asks whether any results stand out or are abnormal, say "
    "clearly which verified lab facts are flagged abnormal — or state that none "
    "of the verified lab facts include an abnormal flag on file. Do not infer "
    "abnormality from numeric values alone unless the verified fact text says so."
)

SYNTHESIZE_MEDS_SYSTEM_PROMPT = (
    "Write a short medication-focused answer as JSON only. "
    'Use this exact shape: {"summary":"..."}. '
    "For medication list questions: prose summary of active medications; "
    "mention verified allergies or conditions when present in verified facts. "
    "For add/prescribe/recommendation questions: state that new prescriptions "
    "cannot be recommended from the chart alone; summarize verified current "
    "medications and relevant allergies/conditions only. "
    "For switch/replace questions: summarize verified current Rx from chart facts "
    "and verified research facts for the proposed drug only; do not state whether "
    "the switch is appropriate; do not repeat dose numbers from the user question "
    "unless the identical number appears in verified fact text. "
    "For dosing questions: paraphrase only verified chart and research dose facts; "
    "do not invent dosing. Never replace or duplicate decision-support disclaimers, "
    "not-on-list lines, or refusal copy — those appear separately in assembly. "
    "Target roughly 40–80 words. No markdown, bullets, or citation markers."
)

logger = logging.getLogger(__name__)
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class LlmError(Exception):
    """Raised when an OpenRouter LLM call fails.

    ``code`` is a stable, non-PHI token surfaced on SSE error frames for debugging.
    """

    def __init__(self, message: str, *, code: str = "llm_unavailable") -> None:
        super().__init__(message)
        self.code = code


def set_correlation_id(correlation_id: str | None) -> None:
    """Set correlation id for LLM log context (never logged message bodies)."""
    _correlation_id.set(correlation_id)


def is_auto_brief_message(message: str) -> bool:
    """Return True when message matches the auto-brief bind prompt (normalized)."""
    normalized = re.sub(r"\s+", " ", message.strip().lower())
    target = re.sub(r"\s+", " ", AUTO_BRIEF_MESSAGE.strip().lower())
    return normalized == target


def is_labs_abnormal_followup_like(message: str) -> bool:
    """True when the user asks whether labs/results are abnormal or stand out."""
    text = message.strip()
    if not text:
        return False
    if _LABS_ABNORMAL_FOLLOWUP.search(text):
        return True
    if _LABS_DEICTIC_FOLLOWUP.search(text) and re.search(
        r"\b(abnormal|stand|concerning|flag|result|lab|value|out)\b",
        text,
        re.IGNORECASE,
    ):
        return True
    return False


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
    *,
    route: Route | str = "brief",
) -> str:
    """Draft claims JSON from tool facts via Haiku (verify happens elsewhere)."""
    user_prompt = _build_draft_user_prompt(message, tool_results, transcript)
    system_prompt = DRAFT_SYSTEM_PROMPT
    if route == "brief":
        system_prompt = f"{DRAFT_SYSTEM_PROMPT}\n\n{BRIEF_DRAFT_ADDENDUM}"
    elif route == "labs":
        system_prompt = f"{DRAFT_SYSTEM_PROMPT}\n\n{LABS_DRAFT_ADDENDUM}"
        if is_labs_abnormal_followup_like(message):
            system_prompt = (
                f"{system_prompt}\n\n{LABS_ABNORMAL_FOLLOWUP_DRAFT_ADDENDUM}"
            )
    elif route == "meds":
        system_prompt = f"{DRAFT_SYSTEM_PROMPT}\n\n{MEDS_DRAFT_ADDENDUM}"
    return _chat_completion(
        purpose="draft",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=True,
    )


def synthesize_turn_raw(
    route: Route | str,
    message: str,
    verified_facts: list[dict[str, str]],
    domain_context: dict[str, Any],
    transcript: list | None = None,
) -> str:
    """Synthesize route narrative JSON from verified fact texts only."""
    route_key = normalize_route(str(route))
    if route_key == "labs":
        system_prompt = SYNTHESIZE_LABS_SYSTEM_PROMPT
        if is_labs_abnormal_followup_like(message):
            system_prompt = (
                f"{system_prompt}\n\n{SYNTHESIZE_LABS_ABNORMAL_FOLLOWUP_ADDENDUM}"
            )
    elif route_key == "meds":
        system_prompt = SYNTHESIZE_MEDS_SYSTEM_PROMPT
    else:
        system_prompt = SYNTHESIZE_SYSTEM_PROMPT

    facts_json = json.dumps(verified_facts, separators=(",", ":"), default=str)
    domain_json = json.dumps(domain_context, separators=(",", ":"), default=str)
    transcript_text = _format_transcript(transcript)
    user_prompt = (
        f"User message:\n{message.strip()}\n\n"
        f"Recent transcript (last {MAX_TRANSCRIPT_TURNS} turns):\n{transcript_text}\n\n"
        f"Verified facts (use only these clinical details):\n{facts_json}\n\n"
        f"Domain flags (for gap narration only):\n{domain_json}"
    )
    return _chat_completion(
        purpose="synthesize",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=True,
    )


def synthesize_brief_raw(
    message: str,
    verified_facts: list[dict[str, str]],
    domain_context: dict[str, Any],
    transcript: list | None = None,
) -> str:
    """Synthesize brief narrative JSON from verified fact texts only."""
    return synthesize_turn_raw(
        "brief",
        message,
        verified_facts,
        domain_context,
        transcript,
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
    sanitized: list[dict[str, str]] = []
    for entry in transcript:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        text = entry.get("text")
        if role not in ("user", "assistant") or not isinstance(text, str):
            continue
        cleaned = text.strip()
        if not cleaned:
            continue
        if len(cleaned) > 4000:
            cleaned = cleaned[:4000]
        sanitized.append({"role": role, "text": cleaned})
    return list(sanitized[-MAX_TRANSCRIPT_TURNS:])


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
        raise LlmError(
            "OPENROUTER_API_KEY is not configured",
            code="llm_not_configured",
        )
    # wrap_openai captures token usage / cost into LangSmith when tracing is on.
    return wrap_openai(
        OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
        )
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
        raise LlmError("OpenRouter request failed", code="llm_unavailable") from exc
    except APIStatusError as exc:
        raise LlmError(
            f"OpenRouter returned HTTP {exc.status_code}",
            code="llm_http_error",
        ) from exc
    except Exception as exc:
        raise LlmError("OpenRouter request failed", code="llm_unavailable") from exc

    usage = getattr(response, "usage", None)
    if usage is not None:
        logger.info(
            "OpenRouter LLM usage",
            extra={
                **log_extra,
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            },
        )

    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise LlmError("OpenRouter returned empty content", code="llm_empty_response")
    return content.strip()
