"""SPL / openFDA label → research facts (deterministic; no LLM)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Mapping
from xml.etree.ElementTree import Element

from .constants import (
    DAILYMED_DOSAGE_LOINC,
    DOSAGE_SECTION_ID_SUFFIX,
    RESEARCH_TOOL_NAME,
    TABLE_DAILYMED,
    TABLE_OPENFDA,
    TEXT_MAX_CHARS,
)

# openFDA product_type / DailyMed document code displayName substring.
_RX_PRODUCT_MARKER = "HUMAN PRESCRIPTION DRUG"
_OTC_PRODUCT_MARKER = "HUMAN OTC DRUG"

# Extended / delayed release tokens (IR is immediate-release).
_ER_TOKEN = re.compile(r"\b(?:ER|XR|SA)\b", re.IGNORECASE)

_DAILYMED_SETID_URL = (
    "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"
)


def extract_openfda_facts(
    result: Mapping[str, Any],
    *,
    form_hint: str | None = None,
    ambiguous_forms: bool = False,
) -> list[dict[str, str]]:
    """Build research facts from one openFDA ``results[0]`` object.

    Misses (empty list) for OTC-only, empty dosage, or form ambiguity.
    Never raises for those cases.
    """
    if ambiguous_forms:
        return []

    openfda = result.get("openfda")
    if not isinstance(openfda, Mapping):
        openfda = {}

    if not _is_rx_product_types(openfda.get("product_type")):
        return []

    if _is_mixed_ir_er_without_hint(openfda, form_hint):
        return []

    dosage_text = _join_dosage_field(result.get("dosage_and_administration"))
    dosage_text = _truncate(dosage_text)
    if not dosage_text:
        return []

    set_id = _first_str(openfda.get("spl_set_id"))
    if not set_id:
        return []

    title = _first_str(openfda.get("brand_name")) or _first_str(
        openfda.get("generic_name")
    )
    return [
        {
            "text": dosage_text,
            "table": TABLE_OPENFDA,
            "id": f"{set_id}{DOSAGE_SECTION_ID_SUFFIX}",
            "excerpt": _build_excerpt(set_id, title),
        }
    ]


def extract_dailymed_facts(
    xml_text: str,
    *,
    set_id: str,
    form_hint: str | None = None,
    ambiguous_forms: bool = False,
) -> list[dict[str, str]]:
    """Parse DailyMed SPL XML; dosage section LOINC ``34068-7``.

    Misses on parse failure, non-Rx, empty dosage, or form ambiguity.
    """
    if ambiguous_forms or not set_id or not xml_text.strip():
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    if not _dailymed_is_rx(root):
        return []

    title = _dailymed_title(root)
    # Single-title payloads cannot mix IR+ER families; form_hint reserved for
    # callers that already filtered candidates. Ambiguity for DailyMed is via
    # ``ambiguous_forms`` (handled above).
    _ = form_hint

    dosage_text = _dailymed_dosage_text(root)
    dosage_text = _truncate(dosage_text)
    if not dosage_text:
        return []

    return [
        {
            "text": dosage_text,
            "table": TABLE_DAILYMED,
            "id": f"{set_id}{DOSAGE_SECTION_ID_SUFFIX}",
            "excerpt": _build_excerpt(set_id, title),
        }
    ]


def build_research_tool_result(
    facts: list[dict[str, str]],
    *,
    on_chart: bool,
    query_term: str,
    source: str,
    set_id: str,
) -> dict[str, Any]:
    """Assemble the ``research_label`` tool_results payload for tools_node."""
    return {
        "ok": True,
        "tool": RESEARCH_TOOL_NAME,
        "data": {
            "facts": facts,
            "meta": {
                "on_chart": on_chart,
                "query_term": query_term,
                "source": source,
                "set_id": set_id,
            },
        },
    }


# --- helpers -----------------------------------------------------------------


def _truncate(text: str) -> str:
    if len(text) <= TEXT_MAX_CHARS:
        return text
    return text[:TEXT_MAX_CHARS]


def _join_dosage_field(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        parts = [p.strip() for p in raw if isinstance(p, str) and p.strip()]
        return "\n".join(parts)
    return ""


def _first_str(raw: Any) -> str:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return ""


def _is_rx_product_types(product_type: Any) -> bool:
    types = _as_str_list(product_type)
    return any(_RX_PRODUCT_MARKER in t.upper() for t in types)


def _as_str_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, str)]
    return []


def _normalize_hint(form_hint: str | None) -> str | None:
    if form_hint is None:
        return None
    hint = form_hint.strip()
    return hint or None


def _list_has_er_and_non_er(names: list[str]) -> bool:
    """True when a single name list clearly mixes ER/XR/SA and non-ER labels."""
    if len(names) < 2:
        return False
    has_er = any(_ER_TOKEN.search(n) for n in names)
    has_non_er = any(not _ER_TOKEN.search(n) for n in names)
    return has_er and has_non_er


def _openfda_implies_mixed_forms(openfda: Mapping[str, Any]) -> bool:
    """Detect IR+ER family mix within brand_name or generic_name lists.

    Brand ER + plain generic (typical single SPL) is *not* mixed.
    """
    if _list_has_er_and_non_er(_as_str_list(openfda.get("brand_name"))):
        return True
    if _list_has_er_and_non_er(_as_str_list(openfda.get("generic_name"))):
        return True
    return False


def _is_mixed_ir_er_without_hint(
    openfda: Mapping[str, Any],
    form_hint: str | None,
) -> bool:
    if not _openfda_implies_mixed_forms(openfda):
        return False
    # With a form hint, resolve already disambiguated — accept.
    if _normalize_hint(form_hint) is not None:
        return False
    return True


def dailymed_setid_url(set_id: str) -> str:
    """Public DailyMed drugInfo URL for a SPL set id (citation Open label)."""
    return _DAILYMED_SETID_URL.format(set_id=set_id)


def derive_research_title_and_url(
    excerpt: str | None,
    *,
    set_id: str | None = None,
) -> tuple[str, str | None]:
    """Derive popup title + https URL from research excerpt and/or set_id.

    Prefer ``"{title} — {https://…}"`` in the excerpt; otherwise fall back to
    a DailyMed URL built from ``set_id`` when present.
    """
    text = (excerpt or "").strip()
    title = ""
    url: str | None = None

    if " — " in text:
        left, right = text.split(" — ", 1)
        right = right.strip()
        if right.startswith("https://"):
            title = left.strip()
            url = right
        else:
            title = text
    elif text.startswith("https://"):
        url = text
    else:
        title = text

    if url is None and isinstance(set_id, str) and set_id.strip():
        url = dailymed_setid_url(set_id.strip())

    return title, url


def _build_excerpt(set_id: str, title: str) -> str:
    url = dailymed_setid_url(set_id)
    if title:
        return f"{title} — {url}"
    return url


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _parent_map(root: Element) -> dict[Element, Element]:
    parents: dict[Element, Element] = {}
    for parent in root.iter():
        for child in list(parent):
            parents[child] = parent
    return parents


def _dailymed_is_rx(root: Element) -> bool:
    """True when SPL looks like HUMAN PRESCRIPTION DRUG (not OTC-only)."""
    saw_rx = False
    saw_otc = False
    for el in root.iter():
        if _local_tag(el.tag) != "code":
            continue
        display = (el.get("displayName") or "").upper()
        code = el.get("code") or ""
        if _RX_PRODUCT_MARKER in display or code == "34391-3":
            saw_rx = True
        if _OTC_PRODUCT_MARKER in display or code == "34390-5":
            saw_otc = True
    if saw_rx:
        return True
    if saw_otc:
        return False
    return False


def _dailymed_title(root: Element) -> str:
    for el in root.iter():
        if _local_tag(el.tag) == "title":
            text = "".join(el.itertext()).strip()
            if text:
                return text
    return ""


def _dailymed_dosage_text(root: Element) -> str:
    parents = _parent_map(root)
    for el in root.iter():
        if _local_tag(el.tag) != "code":
            continue
        if el.get("code") != DAILYMED_DOSAGE_LOINC:
            continue
        section = _nearest_section(el, parents)
        if section is None:
            continue
        text = " ".join(section.itertext())
        text = re.sub(r"\s+", " ", text).strip()
        return text
    return ""


def _nearest_section(
    el: Element,
    parents: Mapping[Element, Element],
) -> Element | None:
    node: Element | None = el
    while node is not None:
        if _local_tag(node.tag) == "section":
            return node
        node = parents.get(node)
    return None
