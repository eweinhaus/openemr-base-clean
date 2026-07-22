"""Resolve scrubbed DrugQuery from dosing message + chart meds facts (PRD 05)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from .constants import UNCERTAIN_RXNORM_SUFFIX
from .dosing import is_dosing_like
from .scrub import scrub_query_term

# Capture off-chart named drug after dosing phrasing (message only).
_DOSE_OF_CAPTURE = re.compile(
    r"(?:dose|dosing|dosage)\s+(?:of|for)\s+([A-Za-z][A-Za-z0-9\-/ ]{1,40})",
    re.IGNORECASE,
)

# Labeled RxCUI / RxNorm digits in fact text (never invent from bare ids).
_RXCUI_LABELED = re.compile(
    r"(?i)\b(?:rxnorm|rxcui)\s*[:#]?\s*(\d{4,})\b",
)

# Strength / form / salt tokens stripped before display-name matching.
_FORM_STRENGTH_TOKENS = frozenset(
    {
        "mg",
        "mcg",
        "ug",
        "g",
        "ml",
        "l",
        "iu",
        "meq",
        "mmol",
        "oral",
        "tablet",
        "tablets",
        "tab",
        "tabs",
        "capsule",
        "capsules",
        "cap",
        "caps",
        "er",
        "xr",
        "xl",
        "sr",
        "cr",
        "ir",
        "sa",
        "dr",
        "hcl",
        "hbr",
        "hydrochloride",
        "sodium",
        "potassium",
        "calcium",
        "solution",
        "suspension",
        "syrup",
        "cream",
        "ointment",
        "gel",
        "patch",
        "injection",
        "injectable",
        "inhaler",
        "spray",
        "drops",
        "chewable",
        "extended",
        "release",
        "delayed",
        "immediate",
    }
)

_PRESCRIPTIONS_TABLE = "prescriptions"
_TOKEN_SPLIT = re.compile(r"[\s,;/]+")
_TRAILING_PUNCT = re.compile(r"[.,;:!?]+$")


class ResolveStatus(str, Enum):
    """Outcome of drug resolve for a dosing-like message."""

    OK = "ok"
    BLOCKED = "blocked"
    NONE = "none"


@dataclass(frozen=True)
class DrugQuery:
    """Scrubbed outbound research identity — never raw user message / PHI."""

    term: str
    rxcui: str | None
    on_chart: bool
    blocked: bool
    display_name: str
    matched_fact_id: str | None = None


@dataclass(frozen=True)
class ResolveResult:
    """Resolve outcome; ``query`` is set for OK and BLOCKED."""

    status: ResolveStatus
    query: DrugQuery | None


def resolve_drug_query(
    message: str,
    meds_facts: Sequence[Mapping[str, Any]],
) -> ResolveResult | None:
    """Resolve a scrubbed ``DrugQuery`` from message + meds chart facts.

    Returns ``None`` when the message is not dosing-like (no research).
    Never performs HTTP; callers must skip the research client when status is
    ``BLOCKED`` or ``NONE``.
    """
    if not is_dosing_like(message):
        return None

    chart_match = _match_prescription_in_message(message, meds_facts)
    if chart_match is not None:
        fact, display_name, uncertain = chart_match
        fact_id = _as_str(fact.get("id")) or None
        if uncertain:
            return ResolveResult(
                status=ResolveStatus.BLOCKED,
                query=DrugQuery(
                    term=display_name,
                    rxcui=None,
                    on_chart=True,
                    blocked=True,
                    display_name=display_name,
                    matched_fact_id=fact_id,
                ),
            )

        rxcui = _extract_rxcui(fact)
        scrubbed = scrub_query_term(display_name) or display_name
        return ResolveResult(
            status=ResolveStatus.OK,
            query=DrugQuery(
                term=scrubbed,
                rxcui=rxcui,
                on_chart=True,
                blocked=False,
                display_name=display_name,
                matched_fact_id=fact_id,
            ),
        )

    captured = _capture_dose_of_term(message)
    if captured is None:
        return ResolveResult(status=ResolveStatus.NONE, query=None)

    scrubbed = scrub_query_term(captured)
    if scrubbed is None:
        return ResolveResult(status=ResolveStatus.NONE, query=None)

    return ResolveResult(
        status=ResolveStatus.OK,
        query=DrugQuery(
            term=scrubbed,
            rxcui=None,
            on_chart=False,
            blocked=False,
            display_name=scrubbed,
            matched_fact_id=None,
        ),
    )


def reconcile_on_chart_after_hit(
    on_chart: bool,
    label_generic_names: Sequence[str],
    label_brand_names: Sequence[str],
    active_rx_texts: Sequence[str],
) -> bool:
    """H15: after a label hit, flip ``on_chart`` if brand/generic matches Rx text.

    Any openFDA generic or brand token that appears as a case-insensitive
    substring of an active prescription fact text counts as on-chart.
    """
    if on_chart:
        return True

    tokens: list[str] = []
    for name in (*label_generic_names, *label_brand_names):
        cleaned = name.strip()
        if cleaned:
            tokens.append(cleaned.lower())
    if not tokens:
        return False

    haystacks = [text.lower() for text in active_rx_texts if text and text.strip()]
    for token in tokens:
        for hay in haystacks:
            if token in hay:
                return True
    return False


def _match_prescription_in_message(
    message: str,
    meds_facts: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], str, bool] | None:
    """Return best prescriptions-table match: (fact, display_name, uncertain)."""
    message_l = message.lower()
    best: tuple[Mapping[str, Any], str, bool] | None = None
    best_len = 0

    for fact in meds_facts:
        if _as_str(fact.get("table")) != _PRESCRIPTIONS_TABLE:
            continue
        text = _as_str(fact.get("text"))
        if not text:
            continue
        uncertain = text.endswith(UNCERTAIN_RXNORM_SUFFIX)
        core = text[: -len(UNCERTAIN_RXNORM_SUFFIX)] if uncertain else text
        display = _display_name_from_fact_text(core)
        if not display:
            continue
        if display.lower() not in message_l:
            continue
        if len(display) > best_len:
            best = (fact, display, uncertain)
            best_len = len(display)

    return best


def _display_name_from_fact_text(text: str) -> str:
    """Strip dosage/instructions/form tokens → human drug name for matching."""
    # Instructions after em dash are not part of the display name.
    head = text.split("—", 1)[0].strip()
    head = head.split(" - ", 1)[0].strip()
    # Drop trailing parenthetical labels (e.g. RxNorm mention).
    head = re.sub(r"\s*\([^)]*\)\s*$", "", head).strip()

    kept: list[str] = []
    for raw in _TOKEN_SPLIT.split(head):
        token = _TRAILING_PUNCT.sub("", raw.strip())
        if not token:
            continue
        lower = token.lower().rstrip(".")
        if lower in _FORM_STRENGTH_TOKENS:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?(?:mg|mcg|g|ml|iu|meq)", lower):
            continue
        kept.append(token)

    return " ".join(kept).strip()


def _capture_dose_of_term(message: str) -> str | None:
    match = _DOSE_OF_CAPTURE.search(message)
    if match is None:
        return None
    raw = match.group(1).strip()
    raw = _TRAILING_PUNCT.sub("", raw).strip()
    # Prefer leading drug tokens; drop trailing strength/form noise.
    display = _display_name_from_fact_text(raw)
    return display or None


def _extract_rxcui(fact: Mapping[str, Any]) -> str | None:
    """Digits-only RxCUI from labeled text or fact/meta fields — never bare id."""
    text = _as_str(fact.get("text"))
    labeled = _RXCUI_LABELED.search(text)
    if labeled is not None:
        return labeled.group(1)

    for key in ("rxcui", "rxnorm", "rxnorm_drugcode"):
        direct = _digits_only(fact.get(key))
        if direct is not None:
            return direct

    meta = fact.get("meta")
    if isinstance(meta, Mapping):
        for key in ("rxcui", "rxnorm", "rxnorm_drugcode"):
            from_meta = _digits_only(meta.get(key))
            if from_meta is not None:
                return from_meta

    return None


def _digits_only(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.isdigit() and len(text) >= 4:
        return text
    return None


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)
