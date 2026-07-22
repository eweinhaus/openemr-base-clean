"""Unit tests for research query-term scrubbing (PRD 05 H3)."""

from __future__ import annotations

from sidecar.app.research import scrub_query_term


def test_scrub_accepts_simvastatin() -> None:
    assert scrub_query_term("simvastatin") == "simvastatin"


def test_scrub_rejects_empty() -> None:
    assert scrub_query_term("") is None
    assert scrub_query_term("   ") is None


def test_scrub_rejects_oversized() -> None:
    oversized = "a" * 65
    assert scrub_query_term(oversized) is None


def test_scrub_rejects_at_sign() -> None:
    assert scrub_query_term("drug@example") is None


def test_scrub_rejects_message_like_commas_and_emails() -> None:
    assert scrub_query_term("Smith, Jane") is None
    assert scrub_query_term("ask doctor@clinic.org about dose") is None
