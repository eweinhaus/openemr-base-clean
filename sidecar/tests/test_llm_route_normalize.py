"""Tests for route normalization and route_message LLM helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sidecar.app.llm import (
    DEFAULT_OPENROUTER_MODEL,
    LlmError,
    normalize_route,
    route_message,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("brief", "brief"),
        ("labs", "labs"),
        ("meds", "meds"),
        ("BRIEF", "brief"),
        ("  Labs  ", "labs"),
        ("MEDS.", "meds"),
        ("labs and meds", "labs"),
        ("unknown", "brief"),
        ("", "brief"),
        ("   ", "brief"),
    ],
)
def test_normalize_route(raw: str, expected: str) -> None:
    assert normalize_route(raw) == expected


@patch("sidecar.app.llm._get_client")
def test_route_message_returns_normalized_route(mock_get_client: MagicMock) -> None:
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="  LABS  "))]
    )

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}, clear=False):
        route = route_message("Show recent creatinine", transcript=[])

    assert route == "labs"
    create_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert create_kwargs["model"] == DEFAULT_OPENROUTER_MODEL
    assert create_kwargs["temperature"] == 0.0
    assert "Show recent creatinine" in create_kwargs["messages"][1]["content"]


@patch("sidecar.app.llm._get_client")
def test_route_message_invalid_model_output_defaults_to_brief(
    mock_get_client: MagicMock,
) -> None:
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="pharmacy"))]
    )

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}, clear=False):
        route = route_message("What is going on?")

    assert route == "brief"


@patch("sidecar.app.llm._get_client")
def test_route_message_truncates_transcript_to_last_eight_turns(
    mock_get_client: MagicMock,
) -> None:
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="meds"))]
    )
    transcript = [{"role": "user", "content": f"turn-{index}"} for index in range(10)]

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}, clear=False):
        route_message("Refill lisinopril", transcript=transcript)

    user_prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][1][
        "content"
    ]
    assert '"turn-2"' in user_prompt
    assert '"turn-9"' in user_prompt
    assert '"turn-0"' not in user_prompt
    assert '"turn-1"' not in user_prompt


def test_route_message_missing_api_key_raises_llm_error() -> None:
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False):
        with pytest.raises(LlmError, match="OPENROUTER_API_KEY"):
            route_message("Hello")
