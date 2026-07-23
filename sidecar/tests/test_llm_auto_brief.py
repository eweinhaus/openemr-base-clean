"""Tests for is_auto_brief_message helper."""

from __future__ import annotations

import pytest

from sidecar.app.llm import AUTO_BRIEF_MESSAGE, is_auto_brief_message


def test_auto_brief_message_constant() -> None:
    assert AUTO_BRIEF_MESSAGE == "Brief me on this patient."


def test_is_auto_brief_message_exact_match() -> None:
    assert is_auto_brief_message("Brief me on this patient.") is True


@pytest.mark.parametrize(
    "message",
    [
        "  Brief me on this patient.  ",
        "BRIEF ME ON THIS PATIENT.",
        "brief   me   on   this   patient.",
        "Brief  me on  this patient.",
    ],
)
def test_is_auto_brief_message_whitespace_and_case_variants(message: str) -> None:
    assert is_auto_brief_message(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "What's creatinine?",
        "",
        "   ",
        "Brief me on this patient",
        "Brief me on the patient.",
        "Please brief me on this patient.",
    ],
)
def test_is_auto_brief_message_non_matches(message: str) -> None:
    assert is_auto_brief_message(message) is False
