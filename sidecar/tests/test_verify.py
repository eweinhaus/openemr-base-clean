"""Tests for verify_claims, build_tool_fact_map, filter_refusals, and assemble_clinical."""

from __future__ import annotations

from sidecar.app.claims import (
    Claim,
    DraftClaims,
    Locator,
    Refusal,
    assemble_clinical,
    build_tool_fact_map,
    build_tool_index,
    filter_refusals,
    verify_claims,
)
from sidecar.app.state import DOSING_REFUSAL

DOSING_REFUSAL_TEXT = DOSING_REFUSAL.text
EMPTY_MESSAGE = "Not enough verified chart data to answer from the record."


def _tool_results_with_fact(table: str, fact_id: str, text: str = "stub") -> list[dict]:
    return [
        {
            "ok": True,
            "data": {
                "facts": [
                    {
                        "text": text,
                        "table": table,
                        "id": fact_id,
                        "excerpt": "excerpt",
                    }
                ]
            },
        }
    ]


def test_invented_locator_dropped() -> None:
    draft = DraftClaims(
        claims=[
            Claim(
                text="Creatinine 1.4 mg/dL",
                source_type="chart",
                locator=Locator(table="procedure_result", id="999"),
            )
        ],
        refusals=[],
    )
    fact_map = build_tool_fact_map(
        _tool_results_with_fact("procedure_result", "42")
    )

    verified = verify_claims(draft, fact_map)

    assert verified == []


def test_matching_locator_uses_tool_fact_text_not_model_prose() -> None:
    draft = DraftClaims(
        claims=[
            Claim(
                text="Creatinine 9.9 mg/dL — invented by model",
                source_type="chart",
                locator=Locator(table="procedure_result", id="42"),
            )
        ],
        refusals=[],
    )
    fact_map = build_tool_fact_map(
        _tool_results_with_fact("procedure_result", "42", "Creatinine 1.4 mg/dL")
    )

    verified = verify_claims(draft, fact_map)

    assert len(verified) == 1
    assert verified[0].text == "Creatinine 1.4 mg/dL"
    assert "9.9" not in verified[0].text
    assert verified[0].locator.table == "procedure_result"
    assert verified[0].locator.id == "42"
    assert verified[0].excerpt == "excerpt"


def test_research_claim_dropped() -> None:
    draft = DraftClaims(
        claims=[
            Claim(
                text="Metformin 500 mg BID per label",
                source_type="research",
                locator=Locator(table="dailymed", id="123"),
            )
        ],
        refusals=[],
    )
    fact_map = build_tool_fact_map(
        _tool_results_with_fact("dailymed", "123")
    )

    verified = verify_claims(draft, fact_map)

    assert verified == []


def test_all_fail_verify_assemble_returns_honest_empty_message() -> None:
    draft = DraftClaims(
        claims=[
            Claim(
                text="Invented fact",
                source_type="chart",
                locator=Locator(table="procedure_result", id="999"),
            )
        ],
        refusals=[],
    )
    fact_map = build_tool_fact_map(
        _tool_results_with_fact("procedure_result", "42")
    )
    verified = verify_claims(draft, fact_map)

    text = assemble_clinical(verified, draft.refusals)

    assert EMPTY_MESSAGE in text
    assert "Invented fact" not in text


def test_filter_refusals_drops_unknown_codes_and_canonicalizes() -> None:
    refusals = [
        Refusal(code="no_research", text="Model-authored dosing prose that looks clinical"),
        Refusal(code="sneaky", text="Creatinine is 99 mg/dL"),
        Refusal(code="no_research", text="duplicate"),
    ]

    filtered = filter_refusals(
        refusals,
        canonical={DOSING_REFUSAL.code: DOSING_REFUSAL},
    )

    assert len(filtered) == 1
    assert filtered[0].code == "no_research"
    assert filtered[0].text == DOSING_REFUSAL_TEXT
    assert "99 mg/dL" not in filtered[0].text


def test_meds_dosing_refusal_appears_in_assembled_text() -> None:
    refusals = [
        Refusal(code="no_research", text=DOSING_REFUSAL_TEXT),
    ]
    verified = [
        Claim(
            text="Patient on metformin 500 mg",
            source_type="chart",
            locator=Locator(table="prescriptions", id="10"),
        )
    ]

    text = assemble_clinical(verified, refusals)

    assert "Patient on metformin 500 mg" in text
    assert DOSING_REFUSAL_TEXT in text


def test_assemble_empty_labs_line_without_fake_citation() -> None:
    text = assemble_clinical(
        [],
        [],
        tool_results=[
            {"ok": True, "tool": "labs", "data": {"facts": []}},
        ],
        tool_domain_errors={},
        requested_tools=["labs"],
    )

    assert "No recent labs on file." in text
    assert EMPTY_MESSAGE not in text
    assert "procedure_result" not in text
    assert "locator" not in text.lower()


def test_assemble_unavailable_notes_line() -> None:
    verified = [
        Claim(
            text="Creatinine 1.4 mg/dL",
            source_type="chart",
            locator=Locator(table="procedure_result", id="42"),
        )
    ]
    text = assemble_clinical(
        verified,
        [],
        tool_results=[
            {
                "ok": True,
                "tool": "labs",
                "data": {
                    "facts": [
                        {
                            "text": "Creatinine 1.4 mg/dL",
                            "table": "procedure_result",
                            "id": "42",
                        }
                    ]
                },
            }
        ],
        tool_domain_errors={"notes": "gateway_server"},
        requested_tools=["labs", "notes"],
    )

    assert "Creatinine 1.4 mg/dL" in text
    assert "Notes unavailable — try again." in text


def test_assemble_conditions_empty_when_only_visit_fact() -> None:
    text = assemble_clinical(
        [
            Claim(
                text="Last visit 2026-01-18 — check up",
                source_type="chart",
                locator=Locator(table="form_encounter", id="9"),
            )
        ],
        [],
        tool_results=[
            {
                "ok": True,
                "tool": "patient_context",
                "data": {
                    "facts": [
                        {
                            "text": "Last visit 2026-01-18 — check up",
                            "table": "form_encounter",
                            "id": "9",
                        }
                    ]
                },
            }
        ],
        tool_domain_errors={},
        requested_tools=["patient_context"],
    )

    assert "Last visit 2026-01-18" in text
    assert "No active conditions on file." in text


def test_assemble_meds_meta_only_allergies_empty() -> None:
    text = assemble_clinical(
        [
            Claim(
                text="Metformin 500 mg",
                source_type="chart",
                locator=Locator(table="prescriptions", id="1"),
            )
        ],
        [],
        tool_results=[
            {
                "ok": True,
                "tool": "meds",
                "data": {
                    "facts": [
                        {
                            "text": "Metformin 500 mg",
                            "table": "prescriptions",
                            "id": "1",
                        }
                    ],
                    "meta": {"active_med_count": 1, "allergy_count": 0},
                },
            }
        ],
        tool_domain_errors={},
        requested_tools=["meds"],
    )

    assert "Metformin 500 mg" in text
    assert "No allergies on file." in text
    assert "No active medications on file." not in text


def test_assemble_meds_empty_facts_no_meta_both_one_liners() -> None:
    text = assemble_clinical(
        [],
        [],
        tool_results=[
            {"ok": True, "tool": "meds", "data": {"facts": []}},
        ],
        tool_domain_errors={},
        requested_tools=["meds"],
    )

    assert "No active medications on file." in text
    assert "No allergies on file." in text
    assert "Medications unavailable" not in text


def test_assemble_chart_summary_unavailable() -> None:
    text = assemble_clinical(
        [],
        [],
        tool_results=[],
        tool_domain_errors={"patient_context": "gateway_server"},
        requested_tools=["patient_context"],
    )

    assert "Chart summary unavailable — try again." in text
    assert "No active conditions on file." not in text


def test_duplicate_locators_verified_once() -> None:
    draft = DraftClaims(
        claims=[
            Claim(
                text="Creatinine mention one",
                source_type="chart",
                locator=Locator(table="procedure_result", id="42"),
            ),
            Claim(
                text="Creatinine mention two",
                source_type="chart",
                locator=Locator(table="procedure_result", id="42"),
            ),
        ],
        refusals=[],
    )
    fact_map = build_tool_fact_map(
        _tool_results_with_fact("procedure_result", "42", "Creatinine 1.4 mg/dL")
    )

    verified = verify_claims(draft, fact_map)

    assert len(verified) == 1
    assert verified[0].text == "Creatinine 1.4 mg/dL"


def test_build_tool_index_matches_fact_map_keys() -> None:
    tools = _tool_results_with_fact("lists", "101", "Diabetes")
    assert build_tool_index(tools) == set(build_tool_fact_map(tools).keys())
