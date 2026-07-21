"""Structured claim schema, parse, verify, and clinical assembly."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

EMPTY_CLINICAL_MESSAGE = (
    "Not enough verified chart data to answer from the record."
)

VALID_SOURCE_TYPES = frozenset({"chart", "note", "research"})


class ClaimsParseError(ValueError):
    """Raised when draft claims JSON cannot be parsed."""


@dataclass(frozen=True)
class Locator:
    table: str
    id: str


@dataclass(frozen=True)
class Claim:
    text: str
    source_type: str
    locator: Locator
    excerpt: str | None = None


@dataclass(frozen=True)
class Refusal:
    code: str
    text: str


@dataclass
class DraftClaims:
    claims: list[Claim] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)


def parse_claims_json(raw: str) -> DraftClaims:
    """Parse draft claims from JSON text, optionally embedded in prose."""
    payload = _load_json_object(raw)
    return _draft_from_payload(payload)


# Canonical refusal codes the verify node may surface (model text is discarded).
ALLOWED_REFUSAL_CODES: frozenset[str] = frozenset({"no_research"})


def build_tool_fact_map(
    tool_results: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, str]]:
    """Map (table, id) → {text, excerpt?} from this turn's tool facts."""
    fact_map: dict[tuple[str, str], dict[str, str]] = {}
    for result in tool_results:
        if not result.get("ok"):
            continue
        data = result.get("data")
        if not isinstance(data, dict):
            continue
        facts = data.get("facts")
        if not isinstance(facts, list):
            continue
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            table = fact.get("table")
            fact_id = fact.get("id")
            text = fact.get("text")
            if not table or fact_id is None or not isinstance(text, str) or not text.strip():
                continue
            entry: dict[str, str] = {"text": text.strip()}
            excerpt = fact.get("excerpt")
            if isinstance(excerpt, str) and excerpt.strip():
                entry["excerpt"] = excerpt.strip()
            fact_map[(str(table), str(fact_id))] = entry
    return fact_map


def build_tool_index(tool_results: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Index tool facts as (table, id) keys for locator verification."""
    return set(build_tool_fact_map(tool_results).keys())


def verify_claims(
    draft: DraftClaims,
    fact_map: dict[tuple[str, str], dict[str, str]],
) -> list[Claim]:
    """Keep chart claims with known locators; replace text with tool fact prose.

    Cite-or-silence: never ship model-authored clinical text for a chart locator.
    Research claims are dropped until a research verify path exists (PRD 05).
    """
    verified: list[Claim] = []
    seen_locators: set[tuple[str, str]] = set()
    for claim in draft.claims:
        if claim.source_type == "research":
            continue
        key = (claim.locator.table, claim.locator.id)
        if key in seen_locators:
            continue
        fact = fact_map.get(key)
        if fact is None:
            continue
        seen_locators.add(key)
        fact_text = fact.get("text", "").strip()
        if not fact_text:
            continue
        verified.append(
            Claim(
                text=fact_text,
                source_type="chart",
                locator=claim.locator,
                excerpt=fact.get("excerpt") or claim.excerpt,
            )
        )
    return verified


def filter_refusals(
    refusals: list[Refusal],
    *,
    allowed_codes: frozenset[str] | None = None,
    canonical: dict[str, Refusal] | None = None,
) -> list[Refusal]:
    """Keep only allowlisted refusal codes; replace text with canonical copy."""
    codes = allowed_codes if allowed_codes is not None else ALLOWED_REFUSAL_CODES
    canon = canonical or {}
    filtered: list[Refusal] = []
    seen: set[str] = set()
    for refusal in refusals:
        if refusal.code not in codes or refusal.code in seen:
            continue
        seen.add(refusal.code)
        filtered.append(canon.get(refusal.code, refusal))
    return filtered


def assemble_clinical(verified: list[Claim], refusals: list[Refusal]) -> str:
    """Join verified claim text and refusal messages into concise clinical prose."""
    parts: list[str] = []
    if verified:
        parts.extend(claim.text for claim in verified)
    else:
        parts.append(EMPTY_CLINICAL_MESSAGE)
    parts.extend(refusal.text for refusal in refusals if refusal.text)
    return " ".join(parts)


def _load_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise ClaimsParseError("Empty claims JSON")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        extracted = _extract_first_json_object(text)
        if extracted is None:
            raise ClaimsParseError("Invalid claims JSON") from None
        try:
            parsed = json.loads(extracted)
        except json.JSONDecodeError as exc:
            raise ClaimsParseError("Invalid claims JSON") from exc

    if not isinstance(parsed, dict):
        raise ClaimsParseError("Claims JSON must be an object")
    return parsed


def _extract_first_json_object(text: str) -> str | None:
    match = re.search(r"\{", text)
    if match is None:
        return None

    start = match.start()
    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    return None


def _draft_from_payload(payload: dict[str, Any]) -> DraftClaims:
    raw_claims = payload.get("claims", [])
    raw_refusals = payload.get("refusals", [])

    if not isinstance(raw_claims, list):
        raise ClaimsParseError("claims must be a list")
    if not isinstance(raw_refusals, list):
        raise ClaimsParseError("refusals must be a list")

    claims = [_claim_from_dict(item, index) for index, item in enumerate(raw_claims)]
    refusals = [
        _refusal_from_dict(item, index) for index, item in enumerate(raw_refusals)
    ]
    return DraftClaims(claims=claims, refusals=refusals)


def _claim_from_dict(item: Any, index: int) -> Claim:
    if not isinstance(item, dict):
        raise ClaimsParseError(f"claims[{index}] must be an object")

    text = item.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ClaimsParseError(f"claims[{index}].text must be a non-empty string")

    source_type = item.get("source_type")
    if not isinstance(source_type, str) or source_type not in VALID_SOURCE_TYPES:
        raise ClaimsParseError(
            f"claims[{index}].source_type must be one of: chart, note, research"
        )

    locator_raw = item.get("locator")
    if not isinstance(locator_raw, dict):
        raise ClaimsParseError(f"claims[{index}].locator must be an object")

    table = locator_raw.get("table")
    fact_id = locator_raw.get("id")
    if not isinstance(table, str) or not table.strip():
        raise ClaimsParseError(f"claims[{index}].locator.table must be a non-empty string")
    if fact_id is None or str(fact_id).strip() == "":
        raise ClaimsParseError(f"claims[{index}].locator.id must be present")

    excerpt = item.get("excerpt")
    if excerpt is not None and not isinstance(excerpt, str):
        raise ClaimsParseError(f"claims[{index}].excerpt must be a string when present")

    return Claim(
        text=text.strip(),
        source_type=source_type,
        locator=Locator(table=table.strip(), id=str(fact_id)),
        excerpt=excerpt,
    )


def _refusal_from_dict(item: Any, index: int) -> Refusal:
    if not isinstance(item, dict):
        raise ClaimsParseError(f"refusals[{index}] must be an object")

    code = item.get("code")
    text = item.get("text")
    if not isinstance(code, str) or not code.strip():
        raise ClaimsParseError(f"refusals[{index}].code must be a non-empty string")
    if not isinstance(text, str) or not text.strip():
        raise ClaimsParseError(f"refusals[{index}].text must be a non-empty string")

    return Refusal(code=code.strip(), text=text.strip())
