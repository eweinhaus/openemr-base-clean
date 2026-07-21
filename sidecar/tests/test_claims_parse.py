"""Tests for parse_claims_json."""

from __future__ import annotations

import pytest

from sidecar.app.claims import ClaimsParseError, parse_claims_json


def test_valid_json_parses() -> None:
    raw = """
    {
      "claims": [
        {
          "text": "Creatinine 1.4 mg/dL on 2026-06-01",
          "source_type": "chart",
          "locator": { "table": "procedure_result", "id": "42" },
          "excerpt": "Cr 1.4"
        }
      ],
      "refusals": [
        {
          "code": "no_research",
          "text": "No retrieved label source for dosing — I won't guess."
        }
      ]
    }
    """
    draft = parse_claims_json(raw)

    assert len(draft.claims) == 1
    claim = draft.claims[0]
    assert claim.text == "Creatinine 1.4 mg/dL on 2026-06-01"
    assert claim.source_type == "chart"
    assert claim.locator.table == "procedure_result"
    assert claim.locator.id == "42"
    assert claim.excerpt == "Cr 1.4"

    assert len(draft.refusals) == 1
    assert draft.refusals[0].code == "no_research"
    assert (
        draft.refusals[0].text
        == "No retrieved label source for dosing — I won't guess."
    )


def test_invalid_json_raises() -> None:
    with pytest.raises(ClaimsParseError):
        parse_claims_json("not json at all")


def test_first_json_object_extraction_from_prose() -> None:
    raw = """
    Here is the structured output you asked for:

    {
      "claims": [
        {
          "text": "HbA1c 7.2%",
          "source_type": "chart",
          "locator": { "table": "procedure_result", "id": "7" }
        }
      ],
      "refusals": []
    }

    Let me know if you need anything else.
    """
    draft = parse_claims_json(raw)

    assert len(draft.claims) == 1
    assert draft.claims[0].text == "HbA1c 7.2%"
    assert draft.claims[0].locator.table == "procedure_result"
    assert draft.claims[0].locator.id == "7"
    assert draft.refusals == []
