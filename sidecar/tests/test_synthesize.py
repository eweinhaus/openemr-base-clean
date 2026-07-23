"""Unit tests for PRD 08 brief narrative synthesis and PRD 10 all-route synthesis."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from sidecar.app.llm import LlmError
from sidecar.app.nodes.synthesize import (
    build_domain_context_for_synthesis,
    diagnose_guard_summary,
    guard_summary,
    rejected_summary_tokens,
    synthesize_node,
)


def test_guard_summary_passes_when_summary_only_uses_verified_numbers() -> None:
    verified = [
        "Last visit 2024-03-01 — follow-up",
        "Creatinine 1.4 mg/dL",
    ]
    summary = (
        "Patient presents for follow-up. Last visit was 2024-03-01 with "
        "creatinine 1.4 mg/dL noted."
    )
    assert guard_summary(summary, verified) is True


def test_guard_summary_fails_when_summary_introduces_novel_numeric_value() -> None:
    verified = ["Last visit 2024-03-01 — follow-up"]
    summary = "Patient presents for follow-up. Creatinine is 9.9 mg/dL."
    report = diagnose_guard_summary(summary, verified)
    assert report.ok is False
    assert report.reason == "novel_numeric"
    assert "9.9" in report.rejected_numerics


def test_guard_summary_fails_on_runaway_length() -> None:
    verified = ["Last visit 2024-03-01 — follow-up"]
    summary = "Patient presents for follow-up. " + ("detail " * 300)
    report = diagnose_guard_summary(summary, verified)
    assert report.ok is False
    assert report.reason == "too_long"


def test_guard_summary_passes_for_rich_brief_paraphrase() -> None:
    verified = [
        "Alteplase 100 MG Injection 1.00",
        "Simvastatin 20 MG Oral Tablet 1.00",
        "Active problem: Essential hypertension (disorder)",
        "Last visit 2026-01-18 — Encounter for check up (procedure)",
    ]
    summary = (
        "Patient presents for check up. Last visit was 2026-01-18 for an encounter "
        "for check up. Active problems include essential hypertension. Medications "
        "include simvastatin and alteplase. No allergies on file; no recent notes on file."
    )
    assert guard_summary(summary, verified) is True


def test_guard_summary_passes_for_spelled_out_month_from_iso_date() -> None:
    verified = [
        "Last visit 2026-01-18 — Encounter for check up (procedure)",
        "Creatinine 1.4 mg/dL (2026-01-10)",
    ]
    summary = (
        "Patient presents for check up. Last visit was January 18, 2026. "
        "Recent labs from January 10, 2026 show creatinine 1.4 mg/dL."
    )
    assert guard_summary(summary, verified) is True


def test_guard_summary_passes_when_haiku_reformats_chart_date() -> None:
    """Live failure mode: chart 'Jan 18, 2026' → summary '18-01-2026' (token 01)."""
    verified = [
        "Last visit Jan 18, 2026 — Encounter for check up (procedure)",
        "Active problem: History of myocardial infarction (situation)",
        "Simvastatin 20 MG Oral Tablet 1.00",
    ]
    summary = (
        "Patient presents for follow-up care. Last encounter was 18-01-2026 for "
        "routine check-up. Active cardiac history includes prior myocardial "
        "infarction. Medications include simvastatin 20 MG."
    )
    report = diagnose_guard_summary(summary, verified)
    assert report.ok is True, report
    assert report.rejected_numerics == ()


def test_guard_summary_still_rejects_invented_lab_value() -> None:
    verified = ["Last visit Jan 18, 2026 — follow-up", "Creatinine 1.4 mg/dL"]
    summary = "Patient presents for follow-up. Creatinine is 9.9 mg/dL on 18-01-2026."
    report = diagnose_guard_summary(summary, verified)
    assert report.ok is False
    assert report.reason == "novel_numeric"
    assert "9.9" in report.rejected_numerics


def test_guard_summary_passes_for_labs_narrative_glue() -> None:
    verified = [
        "Last visit 2026-01-18 — Encounter for check up (procedure)",
        "Creatinine 1.4 mg/dL (2026-01-10)",
        "Glucose 110 mg/dL (2026-01-10)",
    ]
    summary = (
        "Patient presents for check up. Last visit 2026-01-18. "
        "Recent laboratory results from 2026-01-10 show creatinine 1.4 mg/dL "
        "and glucose 110 mg/dL."
    )
    assert guard_summary(summary, verified) is True


def test_guard_summary_allows_paraphrase_vocabulary_when_numbers_grounded() -> None:
    """Ordinary English paraphrase must not drop the summary (allowlist trap)."""
    verified = [
        "Last visit 2026-01-18 — Encounter for check up (procedure)",
        "Active problem: Essential hypertension (disorder)",
        "Simvastatin 20 MG Oral Tablet 1.00",
        "Creatinine 1.4 mg/dL (2026-01-10)",
    ]
    summary = (
        "Patient arrives today for a wellness checkup after the 2026-01-18 encounter. "
        "Hypertension remains the primary concern. He continues simvastatin 20 MG. "
        "The most recent creatinine reading was 1.4 mg/dL on 2026-01-10."
    )
    report = diagnose_guard_summary(summary, verified)
    assert report.ok is True
    assert report.reason == "ok"


def test_rejected_summary_tokens_lists_novel_vocabulary() -> None:
    verified = ["Last visit 2026-01-18 — follow-up"]
    summary = "Patient presents for follow-up. Potassium is 6.2 mEq/L."
    rejected = rejected_summary_tokens(summary, verified)
    assert "potassium" in rejected


def test_parse_summary_json_accepts_markdown_fenced_payload() -> None:
    from sidecar.app.nodes.synthesize import _parse_summary_json

    raw = (
        '```json\n{"summary":"Patient presents for check up. Last visit 2026-01-18."}\n```'
    )
    assert _parse_summary_json(raw) == (
        "Patient presents for check up. Last visit 2026-01-18."
    )


def test_synthesize_node_skips_when_route_is_labs_and_zero_verified_claims() -> None:
    result = synthesize_node({"route": "labs", "verified_claims": []})
    assert result == {}


def test_synthesize_node_skips_when_zero_verified_claims() -> None:
    result = synthesize_node({"route": "brief", "verified_claims": []})
    assert result == {}


def test_synthesize_node_sets_turn_summary_on_mocked_brief_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = MagicMock()
    claim.text = "Last visit 2024-03-01 — follow-up for hypertension"
    claim.source_type = "chart"

    monkeypatch.setattr(
        "sidecar.app.nodes.synthesize.synthesize_turn_raw",
        lambda *_a, **_k: json.dumps(
            {
                "summary": (
                    "Patient presents for follow-up for hypertension. "
                    "Last visit was 2024-03-01."
                )
            }
        ),
    )

    result = synthesize_node(
        {
            "route": "brief",
            "message": "Brief me.",
            "verified_claims": [claim],
            "tool_results": [],
            "requested_tools": ["patient_context", "labs", "meds", "notes"],
        }
    )

    assert "turn_summary" in result
    assert result["turn_summary"].startswith("Patient presents for follow-up")
    assert "Last visit was 2024-03-01" in result["turn_summary"]


def test_synthesize_node_runs_for_labs_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = MagicMock()
    claim.text = "Creatinine 1.4 mg/dL (2026-01-10)"
    claim.source_type = "chart"

    monkeypatch.setattr(
        "sidecar.app.nodes.synthesize.synthesize_turn_raw",
        lambda *_a, **_k: json.dumps(
            {
                "summary": (
                    "Recent laboratory results from 2026-01-10 show creatinine "
                    "1.4 mg/dL."
                )
            }
        ),
        raising=False,
    )

    result = synthesize_node(
        {
            "route": "labs",
            "message": "What is creatinine?",
            "verified_claims": [claim],
            "tool_results": [],
            "requested_tools": ["labs"],
        }
    )

    assert "turn_summary" in result
    assert result["turn_summary"].startswith("Recent laboratory results")
    assert "creatinine 1.4 mg/dL" in result["turn_summary"]


def test_synthesize_node_runs_for_meds_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = MagicMock()
    claim.text = "Simvastatin 20 MG Oral Tablet 1.00"
    claim.source_type = "chart"

    monkeypatch.setattr(
        "sidecar.app.nodes.synthesize.synthesize_turn_raw",
        lambda *_a, **_k: json.dumps(
            {
                "summary": (
                    "Active medications include simvastatin 20 MG oral tablet."
                )
            }
        ),
        raising=False,
    )

    result = synthesize_node(
        {
            "route": "meds",
            "message": "What medications do they take?",
            "verified_claims": [claim],
            "tool_results": [],
            "requested_tools": ["meds", "patient_context"],
        }
    )

    assert "turn_summary" in result
    assert result["turn_summary"].startswith("Active medications include simvastatin")
    assert "simvastatin 20 MG" in result["turn_summary"]


def test_synthesize_node_omits_turn_summary_on_labs_guard_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = MagicMock()
    claim.text = "Creatinine 1.4 mg/dL (2026-01-10)"
    claim.source_type = "chart"

    monkeypatch.setattr(
        "sidecar.app.nodes.synthesize.synthesize_turn_raw",
        lambda *_a, **_k: json.dumps(
            {"summary": "Recent labs show creatinine 9.9 mg/dL on 2026-01-10."}
        ),
        raising=False,
    )

    result = synthesize_node(
        {
            "route": "labs",
            "message": "What is creatinine?",
            "verified_claims": [claim],
            "tool_results": [],
            "requested_tools": ["labs"],
        }
    )

    assert "turn_summary" not in result
    assert result == {}


def test_synthesize_node_omits_summary_on_guard_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = MagicMock()
    claim.text = "Last visit 2024-03-01 — follow-up"
    claim.source_type = "chart"

    monkeypatch.setattr(
        "sidecar.app.nodes.synthesize.synthesize_turn_raw",
        lambda *_a, **_k: json.dumps(
            {"summary": "Patient presents for follow-up. Potassium is 6.2 mEq/L."}
        ),
    )

    result = synthesize_node(
        {
            "route": "brief",
            "message": "Brief me.",
            "verified_claims": [claim],
            "tool_results": [],
            "requested_tools": ["patient_context", "labs", "meds", "notes"],
        }
    )
    assert result == {}


def test_synthesize_node_omits_summary_on_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = MagicMock()
    claim.text = "Last visit 2024-03-01 — follow-up"
    claim.source_type = "chart"

    def _raise(*_a: object, **_k: object) -> str:
        raise LlmError("OpenRouter request failed")

    monkeypatch.setattr("sidecar.app.nodes.synthesize.synthesize_turn_raw", _raise)

    result = synthesize_node(
        {
            "route": "brief",
            "message": "Brief me.",
            "verified_claims": [claim],
            "tool_results": [],
            "requested_tools": ["patient_context", "labs", "meds", "notes"],
        }
    )
    assert result == {}


def test_build_domain_context_for_synthesis_flags_empty_notes() -> None:
    context = build_domain_context_for_synthesis(
        tool_results=[
            {
                "ok": True,
                "tool": "notes",
                "data": {"facts": []},
            }
        ],
        tool_domain_errors={},
        requested_tools=["notes"],
    )
    assert "notes" in context["empty_domains"]
    assert context["unavailable_domains"] == []


def test_build_domain_context_for_synthesis_flags_unavailable_domain() -> None:
    context = build_domain_context_for_synthesis(
        tool_results=[],
        tool_domain_errors={"notes": "gateway_timeout"},
        requested_tools=["notes"],
    )
    assert "notes" in context["unavailable_domains"]
