"""String-contains checks for DRAFT_SYSTEM_PROMPT (H6 research drafting rules)."""

from __future__ import annotations

from sidecar.app.llm import DRAFT_SYSTEM_PROMPT


def test_draft_system_prompt_forbids_invented_research() -> None:
    lower = DRAFT_SYSTEM_PROMPT.lower()
    assert "not invent" in lower
    assert "research" in lower
    assert "url" in lower or "urls" in lower


def test_draft_system_prompt_off_chart_not_prescription() -> None:
    lower = DRAFT_SYSTEM_PROMPT.lower()
    assert "active med list" in lower or "active list" in lower
    assert "prescription" in lower
    assert "prescriptions" in lower
