"""Tests for draft_claims_raw and integration with parse_claims_json."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sidecar.app.claims import parse_claims_json
from sidecar.app.llm import LlmError, draft_claims_raw


DRAFT_JSON = """
{
  "claims": [
    {
      "text": "Creatinine 1.4 mg/dL on 2026-06-01",
      "source_type": "chart",
      "locator": { "table": "procedure_result", "id": "42" }
    }
  ],
  "refusals": []
}
"""


@patch("sidecar.app.llm._get_client")
def test_draft_claims_raw_returns_json_string(mock_get_client: MagicMock) -> None:
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=DRAFT_JSON))]
    )
    tool_results = [
        {
            "ok": True,
            "data": {
                "facts": [
                    {
                        "text": "Creatinine 1.4 mg/dL on 2026-06-01",
                        "table": "procedure_result",
                        "id": "42",
                    }
                ]
            },
        }
    ]

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}, clear=False):
        raw = draft_claims_raw("Summarize labs", tool_results, transcript=[])

    assert raw.strip().startswith("{")
    draft = parse_claims_json(raw)
    assert len(draft.claims) == 1
    assert draft.claims[0].locator.table == "procedure_result"
    assert draft.claims[0].locator.id == "42"

    create_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert create_kwargs["temperature"] == 0.0
    assert create_kwargs["response_format"] == {"type": "json_object"}
    assert "procedure_result" in create_kwargs["messages"][1]["content"]


def test_draft_claims_raw_missing_api_key_raises_llm_error() -> None:
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False):
        with pytest.raises(LlmError, match="OPENROUTER_API_KEY"):
            draft_claims_raw("Summarize labs", [], transcript=[])
