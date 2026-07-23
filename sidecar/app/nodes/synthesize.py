"""Turn narrative synthesis node (PRD 08/10 — post-verify, all chart routes)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from ..claims import ClaimsParseError, _load_json_object, build_domain_status_lines
from ..llm import (
    LlmError,
    set_correlation_id,
    synthesize_turn_raw,
)
from ..nodes.tools import ROUTE_TOOLS
from ..progress import PROGRESS_SUMMARIZING
from ..state import GraphState

logger = logging.getLogger(__name__)

# Function / narrative words ignored when listing novel vocab for diagnostics.
# Word-vocabulary is NOT a hard guard (PRD 08 §4 step 4 is optional); Haiku
# paraphrase will always invent ordinary English that cannot be allowlisted.
_DIAGNOSTIC_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "patient",
        "presents",
        "presenting",
        "for",
        "with",
        "chart",
        "summary",
        "verify",
        "sources",
        "below",
        "file",
        "none",
        "recent",
        "active",
        "from",
        "that",
        "this",
        "have",
        "has",
        "been",
        "were",
        "will",
        "also",
        "not",
        "are",
        "was",
        "their",
        "they",
        "last",
        "visit",
        "follow",
        "followup",
        "history",
        "medical",
        "clinical",
        "record",
        "information",
        "available",
        "noted",
        "noting",
        "including",
        "include",
        "includes",
        "included",
        "without",
        "into",
        "about",
        "there",
        "when",
        "where",
        "which",
        "while",
        "during",
        "after",
        "before",
        "over",
        "under",
        "more",
        "most",
        "some",
        "such",
        "than",
        "then",
        "these",
        "those",
        "other",
        "others",
        "only",
        "well",
        "being",
        "does",
        "did",
        "may",
        "might",
        "could",
        "would",
        "should",
        "must",
        "need",
        "needs",
        "needed",
        "seen",
        "known",
        "currently",
        "current",
        "ongoing",
        "stable",
        "monitor",
        "monitoring",
        "management",
        "care",
        "plan",
        "plans",
        "today",
        "here",
        "present",
        "presentation",
        "since",
        "until",
        "through",
        "between",
        "within",
        "around",
        "onto",
        "upon",
        "both",
        "each",
        "every",
        "either",
        "neither",
        "same",
        "much",
        "many",
        "very",
        "just",
        "even",
        "still",
        "already",
        "again",
        "because",
        "although",
        "though",
        "unless",
        "whether",
        "medications",
        "medication",
        "meds",
        "problems",
        "problem",
        "conditions",
        "condition",
        "allergies",
        "allergy",
        "notes",
        "listed",
        "several",
        "multiple",
        "among",
        "prior",
        "plus",
        "absence",
        "absent",
        "documented",
        "encounter",
        "check",
        "procedure",
        "disorder",
        "situation",
        "stage",
        "essential",
        "chronic",
        "continues",
        "continuing",
        "reports",
        "findings",
        "routine",
        "managed",
        "daily",
        "review",
        "return",
        "returns",
        "labs",
        "laboratory",
        "laboratories",
        "results",
        "result",
        "show",
        "shows",
        "showed",
        "showing",
        "dated",
        "date",
        "dates",
        "level",
        "levels",
        "value",
        "values",
        "normal",
        "abnormal",
        "elevated",
        "reduced",
        "increased",
        "taking",
        "treated",
        "treatment",
        "therapy",
        "related",
        "associated",
        "consistent",
        "concerning",
        "latest",
        "remains",
        "remain",
        "reflects",
        "reflect",
        "indicates",
        "indicate",
        "suggesting",
        "suggests",
        "suggest",
        "overall",
        "general",
        "status",
        "profile",
        "charted",
        "injection",
        "tablet",
        "oral",
        "dose",
        "dosing",
        "january",
        "february",
        "march",
        "april",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
    }
)

_NUMERIC_TOKEN = re.compile(r"\d+(?:\.\d+)?")
_WORD_TOKEN = re.compile(r"[a-z]{4,}")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTH_DAY_YEAR = re.compile(
    r"\b("
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
    r")\s+(\d{1,2}),?\s+(\d{4})\b",
    re.IGNORECASE,
)
_MONTH_NAME_TO_NUM = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


@dataclass(frozen=True)
class GuardReport:
    """Deterministic synthesis guard outcome (PRD 08)."""

    ok: bool
    reason: str
    rejected_numerics: tuple[str, ...] = ()
    novel_tokens: tuple[str, ...] = ()
    summary_len: int = 0


def _int_token_variants(value: int) -> set[str]:
    """String forms Haiku may use for a calendar day/month/year component."""
    if value < 0:
        return set()
    raw = str(value)
    return {raw, raw.zfill(2)}


def _date_component_tokens(verified_texts: list[str]) -> set[str]:
    """Allow day/month/year digits implied by dates already in verified facts.

    Haiku often rewrites ``2026-01-18`` / ``Jan 18, 2026`` as ``18-01-2026``.
    A naive substring check then rejects ``01`` even though the date is grounded.
    """
    allowed: set[str] = set()
    for text in verified_texts:
        for match in _ISO_DATE.finditer(text):
            year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            allowed.update(_int_token_variants(year))
            allowed.update(_int_token_variants(month))
            allowed.update(_int_token_variants(day))
        for match in _MONTH_DAY_YEAR.finditer(text):
            month = _MONTH_NAME_TO_NUM.get(match.group(1).lower())
            if month is None:
                continue
            day = int(match.group(2))
            year = int(match.group(3))
            allowed.update(_int_token_variants(year))
            allowed.update(_int_token_variants(month))
            allowed.update(_int_token_variants(day))
    return allowed


def _verified_numeric_values(verified_union: str) -> list[float]:
    values: list[float] = []
    for match in _NUMERIC_TOKEN.finditer(verified_union):
        try:
            values.append(float(match.group(0)))
        except ValueError:
            continue
    return values


def _numeric_token_grounded(
    token: str,
    *,
    verified_union: str,
    verified_values: list[float],
    date_components: set[str],
) -> bool:
    if token in verified_union or token in date_components:
        return True
    try:
        value = float(token)
    except ValueError:
        return False
    return any(value == verified for verified in verified_values)


def rejected_summary_tokens(text: str, verified_texts: list[str]) -> list[str]:
    """Content words in summary that are not in verified facts or diagnostic stopwords.

    Used for logging / tests only — not a hard fail criterion.
    """
    verified_union = " ".join(verified_texts).lower()
    allowed = set(_DIAGNOSTIC_STOPWORDS)
    for match in _WORD_TOKEN.finditer(verified_union):
        allowed.add(match.group(0))
    return [
        match.group(0)
        for match in _WORD_TOKEN.finditer(text.lower())
        if match.group(0) not in allowed
    ]


def diagnose_guard_summary(text: str, verified_texts: list[str]) -> GuardReport:
    """Explain whether summary is safe to emit (numeric + length hard rules)."""
    summary = text.strip()
    if not summary:
        return GuardReport(ok=False, reason="empty", summary_len=0)

    summary_len = len(summary)
    if summary_len > 1200:
        return GuardReport(
            ok=False,
            reason="too_long",
            novel_tokens=tuple(rejected_summary_tokens(summary, verified_texts)[:12]),
            summary_len=summary_len,
        )

    verified_union = " ".join(verified_texts).lower()
    if not verified_union.strip():
        return GuardReport(
            ok=False,
            reason="no_verified_texts",
            summary_len=summary_len,
        )

    verified_values = _verified_numeric_values(verified_union)
    date_components = _date_component_tokens(verified_texts)
    rejected_numerics = [
        match.group(0)
        for match in _NUMERIC_TOKEN.finditer(summary)
        if not _numeric_token_grounded(
            match.group(0),
            verified_union=verified_union,
            verified_values=verified_values,
            date_components=date_components,
        )
    ]
    novel = rejected_summary_tokens(summary, verified_texts)
    novel_tuple = tuple(dict.fromkeys(novel))[:12]

    if rejected_numerics:
        return GuardReport(
            ok=False,
            reason="novel_numeric",
            rejected_numerics=tuple(dict.fromkeys(rejected_numerics)),
            novel_tokens=novel_tuple,
            summary_len=summary_len,
        )

    # Vocabulary mismatches are logged for observability but do not drop the
    # summary. PRD 08 marks drug/clinical word checks as optional; a closed
    # English allowlist cannot keep up with Haiku paraphrase on rich charts.
    return GuardReport(
        ok=True,
        reason="ok",
        novel_tokens=novel_tuple,
        summary_len=summary_len,
    )


def guard_summary(text: str, verified_texts: list[str]) -> bool:
    """Return True when summary text is unlikely to introduce novel clinical values."""
    return diagnose_guard_summary(text, verified_texts).ok


def build_domain_context_for_synthesis(
    *,
    tool_results: list[dict[str, Any]],
    tool_domain_errors: dict[str, str],
    requested_tools: list[str],
) -> dict[str, Any]:
    """Compact empty/unavailable domain flags for synthesis prompts (no raw facts)."""
    status_lines = build_domain_status_lines(
        tool_results=tool_results,
        tool_domain_errors=tool_domain_errors,
        requested_tools=requested_tools,
    )
    empty_domains: list[str] = []
    unavailable_domains: list[str] = []

    empty_map = {
        "No active conditions on file.": "conditions",
        "No recent labs on file.": "labs",
        "No active medications on file.": "medications",
        "No allergies on file.": "allergies",
        "No recent notes on file.": "notes",
    }
    unavailable_map = {
        "Chart summary unavailable — try again.": "patient_context",
        "Labs unavailable — try again.": "labs",
        "Medications unavailable — try again.": "medications",
        "Notes unavailable — try again.": "notes",
    }

    for line in status_lines:
        if line in empty_map:
            empty_domains.append(empty_map[line])
        elif line in unavailable_map:
            unavailable_domains.append(unavailable_map[line])

    return {
        "empty_domains": empty_domains,
        "unavailable_domains": unavailable_domains,
    }


def _parse_summary_json(raw: str) -> str | None:
    try:
        payload = _load_json_object(raw)
    except ClaimsParseError:
        return None
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    return summary.strip()


def _preview(text: str, limit: int = 180) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


_SYNTHESIS_FAILURE_MESSAGES: dict[str, str] = {
    "novel_numeric": (
        "doing so would require doses or numbers that aren't documented in the "
        "chart or drug labels below"
    ),
    "too_long": (
        "the answer was too long to display safely; review the chart facts below"
    ),
    "empty": (
        "there wasn't enough on the chart to write a reply; review the sources below"
    ),
    "no_verified_texts": (
        "there wasn't enough chart information to answer; review what's below"
    ),
    "parse_failed": (
        "I wasn't able to put together a readable reply from the chart; expand "
        "the sources below to review what's on file"
    ),
    "llm_unavailable": (
        "the service is temporarily unavailable; try again shortly, or review "
        "the chart facts below"
    ),
    "llm_http_error": (
        "the service is temporarily unavailable; try again shortly, or review "
        "the chart facts below"
    ),
    "llm_not_configured": (
        "answer generation isn't available right now; review the chart facts below"
    ),
    "llm_empty_response": (
        "I couldn't generate a reply for this question; review the chart facts below"
    ),
}


def format_synthesis_failure_line(reason_code: str) -> str:
    """Build a visible assembly line when post-verify synthesis fails."""
    detail = _SYNTHESIS_FAILURE_MESSAGES.get(
        reason_code,
        "I couldn't produce a safe answer from the chart; review the sources below",
    )
    return f"I couldn't answer this question — {detail}."


def synthesize_node(state: GraphState) -> dict[str, object]:
    correlation_id = state.get("correlation_id", "")
    set_correlation_id(correlation_id or None)

    if state.get("error"):
        return {}
    verified = state.get("verified_claims") or []
    if not verified:
        return {}

    route = state.get("route", "brief")

    verified_facts = [
        {"text": claim.text, "source_type": claim.source_type} for claim in verified
    ]
    verified_texts = [claim.text for claim in verified]

    tool_results = state.get("tool_results") or []
    tool_domain_errors = state.get("tool_domain_errors") or {}
    requested = state.get("requested_tools")
    if not requested:
        requested = list(ROUTE_TOOLS.get(route, ["patient_context"]))

    domain_context = build_domain_context_for_synthesis(
        tool_results=tool_results,
        tool_domain_errors=tool_domain_errors,
        requested_tools=requested,
    )

    try:
        raw = synthesize_turn_raw(
            route,
            state.get("message", ""),
            verified_facts,
            domain_context,
            state.get("transcript"),
        )
        summary = _parse_summary_json(raw)
        if summary is None:
            logger.warning(
                "Turn synthesis JSON parse failed route=%s correlation_id=%s raw_preview=%r",
                route,
                correlation_id,
                _preview(raw or ""),
            )
            return {
                "synthesis_failure_line": format_synthesis_failure_line("parse_failed"),
            }

        report = diagnose_guard_summary(summary, verified_texts)
        if not report.ok:
            # Put diagnostics in the message body — uvicorn's default formatter
            # ignores logger `extra` keys, which hid prior rejected_tokens.
            logger.warning(
                "Turn synthesis guard failed route=%s reason=%s rejected_numerics=%s "
                "novel_tokens=%s summary_len=%d verified_fact_count=%d "
                "summary_preview=%r correlation_id=%s",
                route,
                report.reason,
                list(report.rejected_numerics),
                list(report.novel_tokens),
                report.summary_len,
                len(verified_texts),
                _preview(summary),
                correlation_id,
            )
            return {
                "synthesis_failure_line": format_synthesis_failure_line(report.reason),
            }

        if report.novel_tokens:
            logger.info(
                "Turn synthesis guard passed with novel_tokens=%s "
                "summary_len=%d route=%s correlation_id=%s",
                list(report.novel_tokens),
                report.summary_len,
                route,
                correlation_id,
            )
    except LlmError as exc:
        error_code = getattr(exc, "code", "llm_unavailable")
        logger.warning(
            "Turn synthesis LLM failed route=%s error_type=%s error_code=%s correlation_id=%s",
            route,
            type(exc).__name__,
            error_code,
            correlation_id,
        )
        return {
            "synthesis_failure_line": format_synthesis_failure_line(str(error_code)),
        }

    return {
        "progress_messages": [PROGRESS_SUMMARIZING],
        "turn_summary": summary,
    }
