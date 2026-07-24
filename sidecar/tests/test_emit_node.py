"""Tests for clinical emit assembly safeguards."""

from __future__ import annotations

from unittest.mock import MagicMock

from sidecar.app.claims import Claim, Locator
from sidecar.app.nodes.emit import emit_node


def _chart_claim(text: str) -> Claim:
    return Claim(
        text=text,
        source_type="chart",
        locator=Locator(table="procedure_result", id="1"),
    )


def test_emit_injects_synthesis_failure_line_when_summary_missing() -> None:
    result = emit_node(
        {
            "route": "labs",
            "message": "Do any of these stand out as abnormal?",
            "verified_claims": [_chart_claim("Creatinine 1.1 mg/dL (2026-01-10)")],
            "refusals": [],
            "tool_results": [],
            "requested_tools": ["labs"],
        }
    )

    assert "I couldn't answer this question" in result["clinical_text"]
    summary_segs = [
        seg for seg in result["clinical_segments"] if seg.get("kind") == "summary"
    ]
    assembly_segs = [
        seg for seg in result["clinical_segments"] if seg.get("kind") == "assembly"
    ]
    assert summary_segs == []
    assert assembly_segs
    assert assembly_segs[0]["text"].startswith("I couldn't answer this question")


def test_emit_keeps_turn_summary_without_failure_line() -> None:
    result = emit_node(
        {
            "route": "labs",
            "message": "What is creatinine?",
            "turn_summary": "Creatinine is 1.1 mg/dL on the most recent lab.",
            "verified_claims": [_chart_claim("Creatinine 1.1 mg/dL (2026-01-10)")],
            "refusals": [],
            "tool_results": [],
            "requested_tools": ["labs"],
        }
    )

    assert result["clinical_text"].startswith("Creatinine is 1.1 mg/dL")
    assert result["clinical_segments"][0]["kind"] == "summary"
    assembly_texts = [
        seg["text"]
        for seg in result["clinical_segments"]
        if seg.get("kind") == "assembly"
    ]
    assert not any(text.startswith("I couldn't answer this question") for text in assembly_texts)


def test_emit_skips_when_clinical_text_already_set() -> None:
    assert emit_node({"clinical_text": "already emitted", "verified_claims": [MagicMock()]}) == {}
