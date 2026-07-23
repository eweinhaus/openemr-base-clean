"""Structured claim schema, parse, verify, and clinical assembly."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .research.constants import (
    DECISION_SUPPORT_DISCLAIMER,
    RESEARCH_TABLES,
    RESEARCH_TOOL_NAME,
    format_not_on_list,
)
from .research.extract import derive_research_title_and_url

EMPTY_CLINICAL_MESSAGE = (
    "Not enough verified chart data to answer from the record."
)

# Physician-facing assembly copy (not verified claims — no fake locators).
EMPTY_CONDITIONS = "No active conditions on file."
EMPTY_LABS = "No recent labs on file."
EMPTY_MEDS = "No active medications on file."
EMPTY_ALLERGIES = "No allergies on file."
EMPTY_NOTES = "No recent notes on file."

UNAVAILABLE_PATIENT_CONTEXT = "Chart summary unavailable — try again."
UNAVAILABLE_LABS = "Labs unavailable — try again."
UNAVAILABLE_MEDS = "Medications unavailable — try again."
UNAVAILABLE_NOTES = "Notes unavailable — try again."

VALID_SOURCE_TYPES = frozenset({"chart", "note", "research"})

# Short human labels for chart/note citation titles when excerpt is empty.
_TABLE_FRIENDLY_TITLES: dict[str, str] = {
    "procedure_result": "Lab result",
    "prescriptions": "Active medication",
    "form_clinical_notes": "Clinical note",
    "form_encounter": "Encounter",
    "lists": "Problem or allergy",
    "openfda": "Drug label",
    "dailymed": "Drug label",
}


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
ALLOWED_REFUSAL_CODES: frozenset[str] = frozenset(
    {"no_research", "allergy_contradiction"}
)

_ALLERGY_PREFIX = "Allergy: "


def build_tool_fact_map(
    tool_results: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, str]]:
    """Map (table, id) → {text, excerpt?, fhir_uuid?, retrieved_at?} from tool facts."""
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
            fhir_uuid = fact.get("fhir_uuid")
            if isinstance(fhir_uuid, str) and fhir_uuid.strip():
                entry["fhir_uuid"] = fhir_uuid.strip()
            retrieved_at = fact.get("retrieved_at")
            if isinstance(retrieved_at, str) and retrieved_at.strip():
                entry["retrieved_at"] = retrieved_at.strip()
            fact_map[(str(table), str(fact_id))] = entry
    return fact_map


def allergy_titles_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> list[str]:
    """Extract allergy titles from chart facts (``Allergy: …`` text prefix)."""
    titles: list[str] = []
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
            text = fact.get("text")
            if not isinstance(text, str) or not text.startswith(_ALLERGY_PREFIX):
                continue
            title = text[len(_ALLERGY_PREFIX) :].strip()
            # Drop optional reaction suffix (" — anaphylaxis").
            if " — " in title:
                title = title.split(" — ", 1)[0].strip()
            if title:
                titles.append(title)
    return titles


def research_query_terms_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> list[str]:
    """Drug query terms from research_label meta (and chart Rx display names)."""
    terms: list[str] = []
    for result in tool_results:
        if not result.get("ok"):
            continue
        tool = result.get("tool")
        data = result.get("data")
        if not isinstance(data, dict):
            continue
        if tool == RESEARCH_TOOL_NAME:
            meta = data.get("meta")
            if isinstance(meta, dict):
                query_term = meta.get("query_term")
                if isinstance(query_term, str) and query_term.strip():
                    terms.append(query_term.strip())
        facts = data.get("facts")
        if not isinstance(facts, list):
            continue
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            if fact.get("table") != "prescriptions":
                continue
            text = fact.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            # Display name is leading token(s) before dosage / uncertain suffix.
            name = text.strip()
            if " (RxNorm not on file" in name:
                name = name.split(" (RxNorm not on file", 1)[0].strip()
            if " — " in name:
                name = name.split(" — ", 1)[0].strip()
            # Keep first word cluster that looks like a drug name (drop trailing dose nums).
            parts = name.split()
            drug_parts: list[str] = []
            for part in parts:
                if any(ch.isdigit() for ch in part):
                    break
                drug_parts.append(part)
            if drug_parts:
                terms.append(" ".join(drug_parts))
            elif name:
                terms.append(name)
    return terms


def _tokens_overlap(a: str, b: str) -> bool:
    """Case-insensitive whole-token or substring match for drug ↔ allergy titles."""
    left = a.strip().lower()
    right = b.strip().lower()
    if not left or not right:
        return False
    if left == right:
        return True
    if left in right or right in left:
        return True
    left_tokens = {t for t in re.split(r"[^a-z0-9]+", left) if len(t) >= 3}
    right_tokens = {t for t in re.split(r"[^a-z0-9]+", right) if len(t) >= 3}
    return bool(left_tokens & right_tokens)


def apply_allergy_contradiction(
    verified: list[Claim],
    tool_results: list[dict[str, Any]],
) -> tuple[list[Claim], bool]:
    """Drop dosing/med claims that contradict an allergy on this turn's facts.

    Returns ``(filtered_claims, contradiction_found)``. When a researched or
    prescription claim's drug overlaps an allergy title, drop research claims
    and matching prescription claims so verify does not recommend that drug.
    """
    allergies = allergy_titles_from_tool_results(tool_results)
    if not allergies:
        return verified, False

    drug_terms = research_query_terms_from_tool_results(tool_results)
    conflicting_terms = [
        term
        for term in drug_terms
        if any(_tokens_overlap(term, allergy) for allergy in allergies)
    ]
    if not conflicting_terms:
        return verified, False

    filtered: list[Claim] = []
    for claim in verified:
        if claim.source_type == "research" or claim.locator.table in RESEARCH_TABLES:
            # Any research claim on a turn where the queried drug conflicts.
            continue
        if claim.locator.table == "prescriptions":
            text = claim.text or ""
            if any(_tokens_overlap(term, text) for term in conflicting_terms):
                continue
        filtered.append(claim)
    return filtered, True


def build_tool_index(tool_results: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Index tool facts as (table, id) keys for locator verification."""
    return set(build_tool_fact_map(tool_results).keys())


def verify_claims(
    draft: DraftClaims,
    fact_map: dict[tuple[str, str], dict[str, str]],
) -> list[Claim]:
    """Keep chart/note/research claims with known locators; use tool fact prose.

    Cite-or-silence: never ship model-authored clinical text for a known locator.
    Research claims are verified when their locator is in ``fact_map``; surviving
    claims keep their original ``source_type`` (never forced to ``chart``).
    """
    verified: list[Claim] = []
    seen_locators: set[tuple[str, str]] = set()
    for claim in draft.claims:
        if claim.source_type not in ("chart", "note", "research"):
            continue
        key = (claim.locator.table, claim.locator.id)
        if key in seen_locators:
            continue
        fact = fact_map.get(key)
        if not fact:
            continue
        seen_locators.add(key)
        fact_text = fact.get("text", "").strip()
        if not fact_text:
            continue
        # Excerpt is source-derived only — never fall back to model-authored text.
        verified.append(
            Claim(
                text=fact_text,
                source_type=claim.source_type,
                locator=claim.locator,
                excerpt=fact.get("excerpt"),
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


def assemble_clinical(
    verified: list[Claim],
    refusals: list[Refusal],
    *,
    tool_results: list[dict[str, Any]] | None = None,
    tool_domain_errors: dict[str, str] | None = None,
    requested_tools: list[str] | None = None,
) -> str:
    """Join claims → not-on-list → disclaimer? → refusals → domain lines."""
    return build_clinical_payload(
        verified,
        refusals,
        tool_results=tool_results,
        tool_domain_errors=tool_domain_errors,
        requested_tools=requested_tools,
    )["text"]


def build_clinical_payload(
    verified: list[Claim],
    refusals: list[Refusal],
    *,
    tool_results: list[dict[str, Any]] | None = None,
    tool_domain_errors: dict[str, str] | None = None,
    requested_tools: list[str] | None = None,
) -> dict[str, Any]:
    """Build flat clinical ``text`` plus ordered ``segments`` (PRD 06).

    Claim segments carry ``citation_id`` (``c1``…``cN``). Assembly / refusal /
    disclaimer / empty-domain / ``EMPTY_CLINICAL`` lines are ``kind: assembly``
    without ``citation_id`` (H1–H2, H9).
    """
    results = tool_results or []
    assembly_lines = _assembly_lines(
        refusals=refusals,
        tool_results=results,
        tool_domain_errors=tool_domain_errors or {},
        requested_tools=requested_tools or [],
    )

    segments: list[dict[str, Any]] = []
    for index, claim in enumerate(verified, start=1):
        segments.append(
            {
                "kind": "claim",
                "text": claim.text,
                "citation_id": f"c{index}",
            }
        )
    for line in assembly_lines:
        segments.append({"kind": "assembly", "text": line})

    if not segments:
        segments = [{"kind": "assembly", "text": EMPTY_CLINICAL_MESSAGE}]

    text_parts = [claim.text for claim in verified] + assembly_lines
    if not text_parts:
        text_parts = [EMPTY_CLINICAL_MESSAGE]

    return {
        "text": "\n".join(text_parts),
        "segments": segments,
    }


def build_citation_records(
    verified: list[Claim],
    tool_results: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """One citation record per verified claim; ids match clinical segments (H3).

    Emits ``fhir_uuid`` / ``retrieved_at`` only when present on the source fact.
    Keeps claim ``source_type`` (H10). Research title/url from excerpt ``" — "``
    split or DailyMed set_id.
    """
    results = tool_results or []
    set_ids = _research_set_ids_by_locator(results)
    fact_map = build_tool_fact_map(results)
    # Research tool meta may carry a turn-level retrieved_at for all research facts.
    research_retrieved_at = _research_retrieved_at(results)
    citations: list[dict[str, Any]] = []
    for index, claim in enumerate(verified, start=1):
        excerpt = claim.excerpt if isinstance(claim.excerpt, str) else ""
        excerpt = excerpt.strip() if excerpt else ""
        title, url = _citation_title_and_url(claim, excerpt, set_ids)
        key = (claim.locator.table, claim.locator.id)
        fact = fact_map.get(key, {})
        locator: dict[str, Any] = {
            "table": claim.locator.table,
            "id": claim.locator.id,
            "url": url,
        }
        fhir_uuid = fact.get("fhir_uuid")
        if fhir_uuid:
            locator["fhir_uuid"] = fhir_uuid
        citation: dict[str, Any] = {
            "citation_id": f"c{index}",
            "source_type": claim.source_type,
            "title": title,
            "excerpt": excerpt,
            "locator": locator,
        }
        retrieved_at = fact.get("retrieved_at") or (
            research_retrieved_at
            if claim.source_type == "research" or claim.locator.table in RESEARCH_TABLES
            else None
        )
        if retrieved_at:
            citation["retrieved_at"] = retrieved_at
        citations.append(citation)
    return citations


def _research_retrieved_at(tool_results: list[dict[str, Any]]) -> str | None:
    for result in tool_results:
        if result.get("tool") != RESEARCH_TOOL_NAME:
            continue
        data = result.get("data")
        if not isinstance(data, dict):
            continue
        meta = data.get("meta")
        if not isinstance(meta, dict):
            continue
        retrieved_at = meta.get("retrieved_at")
        if isinstance(retrieved_at, str) and retrieved_at.strip():
            return retrieved_at.strip()
    return None


def _assembly_lines(
    *,
    refusals: list[Refusal],
    tool_results: list[dict[str, Any]],
    tool_domain_errors: dict[str, str],
    requested_tools: list[str],
) -> list[str]:
    """Physician-facing assembly copy (never cited)."""
    domain_lines = build_domain_status_lines(
        tool_results=tool_results,
        tool_domain_errors=tool_domain_errors,
        requested_tools=requested_tools,
    )
    not_on_list_lines = _not_on_list_lines(tool_results)
    refusal_texts = [refusal.text for refusal in refusals if refusal.text]

    parts: list[str] = []
    parts.extend(not_on_list_lines)
    if _should_include_disclaimer(tool_results, refusals):
        parts.append(DECISION_SUPPORT_DISCLAIMER)
    parts.extend(refusal_texts)
    parts.extend(domain_lines)
    return parts


def _citation_title_and_url(
    claim: Claim,
    excerpt: str,
    set_ids: dict[tuple[str, str], str],
) -> tuple[str, str | None]:
    if claim.source_type == "research" or claim.locator.table in RESEARCH_TABLES:
        set_id = set_ids.get((claim.locator.table, claim.locator.id))
        title, url = derive_research_title_and_url(excerpt or None, set_id=set_id)
        if not title:
            title = _TABLE_FRIENDLY_TITLES.get(claim.locator.table, "Drug label")
        return title, url

    if excerpt:
        first_line = excerpt.split("\n", 1)[0].strip()
        if first_line:
            return first_line, None
    title = _TABLE_FRIENDLY_TITLES.get(claim.locator.table, "Chart source")
    return title, None


def _research_set_ids_by_locator(
    tool_results: list[dict[str, Any]],
) -> dict[tuple[str, str], str]:
    """Map research fact (table, id) → meta.set_id when present."""
    mapping: dict[tuple[str, str], str] = {}
    for result in tool_results:
        if not isinstance(result, dict) or not result.get("ok"):
            continue
        if result.get("tool") != RESEARCH_TOOL_NAME:
            continue
        data = result.get("data")
        if not isinstance(data, dict):
            continue
        meta = data.get("meta")
        set_id: str | None = None
        if isinstance(meta, dict):
            raw = meta.get("set_id")
            if isinstance(raw, str) and raw.strip():
                set_id = raw.strip()
        if not set_id:
            continue
        facts = data.get("facts")
        if not isinstance(facts, list):
            continue
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            table = fact.get("table")
            fact_id = fact.get("id")
            if not table or fact_id is None:
                continue
            mapping[(str(table), str(fact_id))] = set_id
    return mapping


def _not_on_list_lines(tool_results: list[dict[str, Any]]) -> list[str]:
    """Emit not-on-list when any research_label meta has on_chart is False."""
    lines: list[str] = []
    seen_drugs: set[str] = set()
    for result in tool_results:
        if not isinstance(result, dict) or not result.get("ok"):
            continue
        if result.get("tool") != RESEARCH_TOOL_NAME:
            continue
        data = result.get("data")
        if not isinstance(data, dict):
            continue
        meta = data.get("meta")
        if not isinstance(meta, dict) or meta.get("on_chart") is not False:
            continue
        drug = meta.get("query_term") or meta.get("display")
        if not isinstance(drug, str) or not drug.strip():
            continue
        drug = drug.strip()
        if drug in seen_drugs:
            continue
        seen_drugs.add(drug)
        lines.append(format_not_on_list(drug))
    return lines


def _should_include_disclaimer(
    tool_results: list[dict[str, Any]],
    refusals: list[Refusal],
) -> bool:
    """Disclaimer once when research facts exist or a no_research refusal is present."""
    if any(refusal.code == "no_research" for refusal in refusals):
        return True
    for result in tool_results:
        if not isinstance(result, dict) or not result.get("ok"):
            continue
        if result.get("tool") != RESEARCH_TOOL_NAME:
            continue
        data = result.get("data")
        if not isinstance(data, dict):
            continue
        facts = data.get("facts")
        if isinstance(facts, list) and facts:
            return True
    return False


def build_domain_status_lines(
    *,
    tool_results: list[dict[str, Any]],
    tool_domain_errors: dict[str, str],
    requested_tools: list[str],
) -> list[str]:
    """Allowlisted empty/unavailable one-liners for requested chart domains."""
    if not requested_tools:
        return []

    by_tool = _index_successful_tool_results(tool_results)
    lines: list[str] = []
    for tool_name in requested_tools:
        if tool_name in tool_domain_errors:
            unavailable = _unavailable_line(tool_name)
            if unavailable:
                lines.append(unavailable)
            continue
        result = by_tool.get(tool_name)
        if result is None:
            continue
        lines.extend(_empty_lines_for_tool(tool_name, result))
    return lines


def _index_successful_tool_results(
    tool_results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for result in tool_results:
        if not isinstance(result, dict) or not result.get("ok"):
            continue
        tool = result.get("tool")
        if isinstance(tool, str) and tool:
            indexed[tool] = result
    return indexed


def _unavailable_line(tool_name: str) -> str | None:
    if tool_name == "patient_context":
        return UNAVAILABLE_PATIENT_CONTEXT
    if tool_name == "labs":
        return UNAVAILABLE_LABS
    if tool_name == "meds":
        return UNAVAILABLE_MEDS
    if tool_name == "notes":
        return UNAVAILABLE_NOTES
    return None


def _empty_lines_for_tool(tool_name: str, result: dict[str, Any]) -> list[str]:
    data = result.get("data")
    if not isinstance(data, dict):
        data = {}
    facts = data.get("facts")
    if not isinstance(facts, list):
        facts = []

    if tool_name == "patient_context":
        has_problem = any(
            isinstance(fact, dict) and fact.get("table") == "lists" for fact in facts
        )
        return [] if has_problem else [EMPTY_CONDITIONS]

    if tool_name == "labs":
        has_lab = any(
            isinstance(fact, dict) and fact.get("table") == "procedure_result"
            for fact in facts
        )
        return [] if has_lab else [EMPTY_LABS]

    if tool_name == "notes":
        has_note = any(
            isinstance(fact, dict) and fact.get("table") == "form_clinical_notes"
            for fact in facts
        )
        return [] if has_note else [EMPTY_NOTES]

    if tool_name == "meds":
        return _meds_empty_lines(data, facts)

    return []


def _meds_empty_lines(data: dict[str, Any], facts: list[Any]) -> list[str]:
    meta = data.get("meta")
    lines: list[str] = []
    if isinstance(meta, dict) and (
        "active_med_count" in meta and "allergy_count" in meta
    ):
        try:
            active_med_count = int(meta["active_med_count"])
            allergy_count = int(meta["allergy_count"])
        except (TypeError, ValueError):
            active_med_count = 0
            allergy_count = 0
        if active_med_count == 0:
            lines.append(EMPTY_MEDS)
        if allergy_count == 0:
            lines.append(EMPTY_ALLERGIES)
        return lines

    has_rx = any(
        isinstance(fact, dict) and fact.get("table") == "prescriptions" for fact in facts
    )
    has_allergy = any(
        isinstance(fact, dict) and fact.get("table") == "lists" for fact in facts
    )
    if not has_rx:
        lines.append(EMPTY_MEDS)
    if not has_allergy:
        lines.append(EMPTY_ALLERGIES)
    return lines


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
