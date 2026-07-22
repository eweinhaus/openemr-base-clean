"""Unit tests for research SPL/label extract → facts (PRD 05 H7)."""

from __future__ import annotations

from sidecar.app.research.constants import (
    DOSAGE_SECTION_ID_SUFFIX,
    RESEARCH_TOOL_NAME,
    TABLE_DAILYMED,
    TABLE_OPENFDA,
    TEXT_MAX_CHARS,
)
from sidecar.app.research.extract import (
    build_research_tool_result,
    extract_dailymed_facts,
    extract_openfda_facts,
)

_SET_ID = "abc-123-setid"


def _rx_openfda(**overrides: object) -> dict:
    base: dict = {
        "openfda": {
            "product_type": ["HUMAN PRESCRIPTION DRUG"],
            "spl_set_id": [_SET_ID],
            "brand_name": ["Zocor"],
            "generic_name": ["simvastatin"],
        },
        "dosage_and_administration": [
            "The usual adult dosage is 20 to 40 mg once daily."
        ],
    }
    for key, value in overrides.items():
        if key == "openfda" and isinstance(value, dict):
            merged = dict(base["openfda"])
            merged.update(value)
            base["openfda"] = merged
        else:
            base[key] = value
    return base


_MINIMAL_SPL_RX = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<document xmlns="urn:hl7-org:v3">
  <code code="34391-3" displayName="HUMAN PRESCRIPTION DRUG LABEL"/>
  <title>Simvastatin Tablets</title>
  <component>
    <structuredBody>
      <component>
        <section>
          <code code="34068-7" codeSystem="2.16.840.1.113883.6.1"
                displayName="DOSAGE &amp; ADMINISTRATION SECTION"/>
          <title>Dosage and Administration</title>
          <text>
            <paragraph>Take 20 mg orally once daily in the evening.</paragraph>
          </text>
        </section>
      </component>
    </structuredBody>
  </component>
</document>
"""

_MINIMAL_SPL_OTC = """\
<?xml version="1.0" encoding="UTF-8"?>
<document xmlns="urn:hl7-org:v3">
  <code code="34390-5" displayName="HUMAN OTC DRUG LABEL"/>
  <title>Acetaminophen Tablets</title>
  <component>
    <structuredBody>
      <component>
        <section>
          <code code="34068-7" codeSystem="2.16.840.1.113883.6.1"
                displayName="DOSAGE &amp; ADMINISTRATION SECTION"/>
          <text><paragraph>Take 2 tablets every 6 hours.</paragraph></text>
        </section>
      </component>
    </structuredBody>
  </component>
</document>
"""


def test_otc_only_yields_no_facts() -> None:
    result = _rx_openfda(openfda={"product_type": ["HUMAN OTC DRUG"]})
    assert extract_openfda_facts(result) == []


def test_empty_dosage_yields_no_facts() -> None:
    result = _rx_openfda(dosage_and_administration=[])
    assert extract_openfda_facts(result) == []
    result2 = _rx_openfda(dosage_and_administration=["", "  "])
    assert extract_openfda_facts(result2) == []


def test_dose_truncated_at_1500() -> None:
    long_dose = "A" * (TEXT_MAX_CHARS + 200)
    result = _rx_openfda(dosage_and_administration=[long_dose])
    facts = extract_openfda_facts(result)
    assert len(facts) == 1
    assert len(facts[0]["text"]) == TEXT_MAX_CHARS
    assert facts[0]["text"] == "A" * TEXT_MAX_CHARS


def test_happy_prescription_one_fact() -> None:
    facts = extract_openfda_facts(_rx_openfda())
    assert len(facts) == 1
    fact = facts[0]
    assert fact["table"] == TABLE_OPENFDA
    assert fact["id"] == f"{_SET_ID}{DOSAGE_SECTION_ID_SUFFIX}"
    assert "20 to 40 mg" in fact["text"]
    assert _SET_ID in fact["excerpt"]
    assert "Zocor" in fact["excerpt"]


def test_ambiguous_forms_flag_miss() -> None:
    assert extract_openfda_facts(_rx_openfda(), ambiguous_forms=True) == []


def test_mixed_ir_er_names_without_hint_miss() -> None:
    result = _rx_openfda(
        openfda={
            "brand_name": ["Metformin", "Metformin ER"],
            "generic_name": ["metformin"],
        }
    )
    assert extract_openfda_facts(result) == []


def test_mixed_ir_er_names_with_hint_accept() -> None:
    result = _rx_openfda(
        openfda={
            "brand_name": ["Metformin", "Metformin ER"],
            "generic_name": ["metformin"],
        }
    )
    facts = extract_openfda_facts(result, form_hint="ER")
    assert len(facts) == 1


def test_single_er_name_without_hint_still_accepts() -> None:
    """Single ER product name without hint is not mixed-family ambiguity."""
    result = _rx_openfda(
        openfda={
            "brand_name": ["Metformin ER"],
            "generic_name": ["metformin hydrochloride"],
        }
    )
    facts = extract_openfda_facts(result)
    assert len(facts) == 1


def test_dailymed_xml_fixture_yields_fact() -> None:
    facts = extract_dailymed_facts(_MINIMAL_SPL_RX, set_id=_SET_ID)
    assert len(facts) == 1
    fact = facts[0]
    assert fact["table"] == TABLE_DAILYMED
    assert fact["id"] == f"{_SET_ID}{DOSAGE_SECTION_ID_SUFFIX}"
    assert "20 mg" in fact["text"]
    assert _SET_ID in fact["excerpt"]
    assert "Simvastatin" in fact["excerpt"]


def test_dailymed_otc_yields_no_facts() -> None:
    assert extract_dailymed_facts(_MINIMAL_SPL_OTC, set_id=_SET_ID) == []


def test_bad_xml_yields_empty() -> None:
    assert extract_dailymed_facts("<not><valid", set_id=_SET_ID) == []
    assert extract_dailymed_facts("definitely not xml", set_id=_SET_ID) == []


def test_build_research_tool_result_meta_shape() -> None:
    facts = extract_openfda_facts(_rx_openfda())
    payload = build_research_tool_result(
        facts,
        on_chart=True,
        query_term="simvastatin",
        source="openfda",
        set_id=_SET_ID,
    )
    assert payload["ok"] is True
    assert payload["tool"] == RESEARCH_TOOL_NAME
    assert payload["data"]["facts"] == facts
    meta = payload["data"]["meta"]
    assert meta == {
        "on_chart": True,
        "query_term": "simvastatin",
        "source": "openfda",
        "set_id": _SET_ID,
    }
