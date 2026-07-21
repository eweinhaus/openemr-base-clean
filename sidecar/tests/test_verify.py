"""Tests for verify_claims, build_tool_index, and assemble_clinical."""

from __future__ import annotations

from sidecar.app.claims import (
    Claim,
    DraftClaims,
    Locator,
    Refusal,
    assemble_clinical,
    build_tool_index,
    verify_claims,
)

DOSING_REFUSAL = (
    "No retrieved label source for dosing — I won't guess."
)
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
    tool_index = build_tool_index(
        _tool_results_with_fact("procedure_result", "42")
    )

    verified = verify_claims(draft, tool_index)

    assert verified == []


def test_matching_locator_kept() -> None:
    draft = DraftClaims(
        claims=[
            Claim(
                text="Creatinine 1.4 mg/dL on 2026-06-01",
                source_type="chart",
                locator=Locator(table="procedure_result", id="42"),
            )
        ],
        refusals=[],
    )
    tool_index = build_tool_index(
        _tool_results_with_fact("procedure_result", "42", "Creatinine 1.4")
    )

    verified = verify_claims(draft, tool_index)

    assert len(verified) == 1
    assert verified[0].text == "Creatinine 1.4 mg/dL on 2026-06-01"
    assert verified[0].locator.table == "procedure_result"
    assert verified[0].locator.id == "42"


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
    tool_index = build_tool_index(
        _tool_results_with_fact("dailymed", "123")
    )

    verified = verify_claims(draft, tool_index)

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
    tool_index = build_tool_index(
        _tool_results_with_fact("procedure_result", "42")
    )
    verified = verify_claims(draft, tool_index)

    text = assemble_clinical(verified, draft.refusals)

    assert EMPTY_MESSAGE in text
    assert "Invented fact" not in text


def test_meds_dosing_refusal_appears_in_assembled_text() -> None:
    refusals = [
        Refusal(code="no_research", text=DOSING_REFUSAL),
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
    assert DOSING_REFUSAL in text
