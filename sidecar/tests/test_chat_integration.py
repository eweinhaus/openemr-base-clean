"""Integration tests for /v1/chat LangGraph agent loop (mocked LLM + gateway)."""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from sidecar.app.auth import CORRELATION_HEADER, SECRET_HEADER
from sidecar.app.brief_cache import clear_brief_cache, get_brief_cache
from sidecar.app.claims import EMPTY_CLINICAL_MESSAGE
from sidecar.app.errors import (
    ERROR_DRAFT_PARSE,
    ERROR_GATEWAY_TOOL,
    ERROR_GATEWAY_UNREACHABLE,
    ERROR_INVALID_MESSAGE,
    ERROR_LLM_UNAVAILABLE,
    ERROR_UNEXPECTED,
    message_for_code,
)
from sidecar.app.llm import AUTO_BRIEF_MESSAGE, LlmError
from sidecar.app.main import app
from sidecar.app.research.constants import DECISION_SUPPORT_DISCLAIMER
from sidecar.app.state import (
    DOSING_REFUSAL,
    UNBOUND_MESSAGE,
)

TEST_SECRET = os.environ["COPILOT_INTERNAL_SECRET"]
DOSING_REFUSAL_TEXT = DOSING_REFUSAL.text

# Mock synthesis payloads for route integration tests.
_MOCK_LABS_SYNTHESIS = json.dumps(
    {"summary": "Creatinine is within reference range on the recent CMP."}
)
_MOCK_MEDS_LIST_SYNTHESIS = json.dumps(
    {"summary": "Patient is on metformin 500 mg twice daily with meals."}
)
_MOCK_MEDS_DOSING_SYNTHESIS = json.dumps(
    {
        "summary": (
            "Metformin is typically started at 500 mg twice daily with meals "
            "per the retrieved label."
        )
    }
)


def _patch_synthesize_turn_raw(
    monkeypatch: pytest.MonkeyPatch,
    fn: object,
) -> None:
    """Patch PRD 10 rename target before production lands (raising=False)."""
    monkeypatch.setattr(
        "sidecar.app.nodes.synthesize.synthesize_turn_raw",
        fn,
        raising=False,
    )


def _chat_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "correlation_id": "corr-int-1",
        "user_id": 1,
        "username": "admin",
        "pid": 6,
        "message": "Show recent labs",
        "transcript": [],
    }
    payload.update(overrides)
    return payload


def _auth_headers() -> dict[str, str]:
    return {
        SECRET_HEADER: TEST_SECRET,
        CORRELATION_HEADER: "corr-int-1",
        "Accept": "text/event-stream",
    }


def _parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name: str | None = None
        data: dict[str, Any] | None = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if event_name is not None and data is not None:
            events.append((event_name, data))
    return events


async def _fake_ready(settings: object) -> dict[str, object]:
    """Chat path gates on readiness — keep existing agent tests independent of probes."""
    model = getattr(settings, "openrouter_model", "anthropic/claude-haiku-4.5")
    return {
        "ready": True,
        "gateway": {"reachable": True},
        "openrouter": {"configured": True, "reachable": True},
        "langsmith": {"configured": False, "reachable": False},
        "openrouter_model": model,
    }


def _stream_chat(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    if payload is None:
        payload = _chat_payload()

    monkeypatch.setattr("sidecar.app.main.check_readiness", _fake_ready)

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/v1/chat",
            json=payload,
            headers=_auth_headers(),
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())
    return _parse_sse(body)


LABS_RESULT: dict[str, Any] = {
    "ok": True,
    "tool": "labs",
    "data": {
        "facts": [
            {
                "text": "Serum creatinine 1.1 mg/dL (2026-06-01)",
                "table": "procedure_result",
                "id": "501",
                "excerpt": "CMP — within reference range",
            }
        ]
    },
}

MEDS_RESULT: dict[str, Any] = {
    "ok": True,
    "tool": "meds",
    "data": {
        "facts": [
            {
                "text": "Metformin 500 mg tablet — take one twice daily with meals",
                "table": "prescriptions",
                "id": "201",
                "excerpt": "Active Rx — started 2020-01-10",
            }
        ],
        "meta": {"active_med_count": 1, "allergy_count": 0},
    },
}

VALID_LABS_DRAFT = json.dumps(
    {
        "claims": [
            {
                "text": "Serum creatinine 1.1 mg/dL (2026-06-01)",
                "source_type": "chart",
                "locator": {"table": "procedure_result", "id": "501"},
            }
        ],
        "refusals": [],
    }
)

INVENTED_LABS_DRAFT = json.dumps(
    {
        "claims": [
            {
                "text": "Serum creatinine 9.9 mg/dL (2026-06-01)",
                "source_type": "chart",
                "locator": {"table": "procedure_result", "id": "999"},
            }
        ],
        "refusals": [],
    }
)

VALID_MEDS_DRAFT = json.dumps(
    {
        "claims": [
            {
                "text": "Metformin 500 mg tablet — take one twice daily with meals",
                "source_type": "chart",
                "locator": {"table": "prescriptions", "id": "201"},
            }
        ],
        "refusals": [],
    }
)

VALID_BRIEF_DRAFT = json.dumps(
    {
        "claims": [
            {
                "text": "Last visit 2024-03-01 — follow-up for hypertension",
                "source_type": "chart",
                "locator": {"table": "form_encounter", "id": "701"},
            },
            {
                "text": "Active problem: Essential hypertension",
                "source_type": "chart",
                "locator": {"table": "lists", "id": "801"},
            },
        ],
        "refusals": [],
    }
)

PATIENT_CONTEXT_RESULT: dict[str, Any] = {
    "ok": True,
    "tool": "patient_context",
    "data": {
        "facts": [
            {
                "text": "Last visit 2024-03-01 — follow-up for hypertension",
                "table": "form_encounter",
                "id": "701",
                "excerpt": "Office visit — follow-up",
            },
            {
                "text": "Active problem: Essential hypertension",
                "table": "lists",
                "id": "801",
                "excerpt": "Problem list",
            },
        ]
    },
}


def _gateway_brief_tool(_self: object, tool: str, *_rest: object) -> dict[str, Any]:
    if tool == "patient_context":
        return PATIENT_CONTEXT_RESULT
    return {"ok": True, "tool": tool, "data": {"facts": []}}


def test_happy_path_labs_progress_clinical_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "labs")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: VALID_LABS_DRAFT,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: LABS_RESULT,
    )
    _patch_synthesize_turn_raw(
        monkeypatch,
        lambda *_a, **_k: _MOCK_LABS_SYNTHESIS,
    )

    events = _stream_chat(monkeypatch)

    names = [name for name, _ in events]
    assert names.index("progress") < names.index("clinical")
    assert names.index("clinical") < names.index("citation")
    assert names.index("citation") < names.index("done")
    assert names.count("clinical") == 1
    assert names.count("citation") == 1
    assert names[-1] == "done"

    progress = [data for name, data in events if name == "progress"]
    assert any("Pulling chart" in msg["message"] for msg in progress)
    assert any("Pulling labs" in msg["message"] for msg in progress)
    assert any("Summarizing" in msg["message"] for msg in progress)

    clinical = next(data for name, data in events if name == "clinical")
    assert "Serum creatinine 1.1 mg/dL" in clinical["text"]
    assert "Stub sidecar:" not in clinical["text"]
    assert "skeleton online" not in clinical["text"].lower()
    assert "segments" in clinical
    claim_segs = [s for s in clinical["segments"] if s.get("kind") == "claim"]
    assembly_segs = [s for s in clinical["segments"] if s.get("kind") == "assembly"]
    assert claim_segs
    assert all("citation_id" in s for s in claim_segs)
    assert all("citation_id" not in s for s in assembly_segs)

    citation = next(data for name, data in events if name == "citation")
    assert "citations" in citation
    assert len(citation["citations"]) == len(claim_segs)
    claim_ids = {s["citation_id"] for s in claim_segs}
    cite_ids = {c["citation_id"] for c in citation["citations"]}
    assert claim_ids == cite_ids

    done = next(data for name, data in events if name == "done")
    assert done["correlation_id"] == "corr-int-1"


def test_empty_verified_claims_still_emits_citation_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero verified claims → clinical assembly text + citation {citations: []}."""
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "labs")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: INVENTED_LABS_DRAFT,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: LABS_RESULT,
    )

    events = _stream_chat(monkeypatch)
    names = [name for name, _ in events]

    assert names.index("clinical") < names.index("citation")
    assert names.index("citation") < names.index("done")

    clinical = next(data for name, data in events if name == "clinical")
    citation = next(data for name, data in events if name == "citation")

    assert EMPTY_CLINICAL_MESSAGE in clinical["text"]
    assert clinical["segments"]
    assert all(s.get("kind") == "assembly" for s in clinical["segments"])
    assert all("citation_id" not in s for s in clinical["segments"])
    assert citation["citations"] == []


def test_invented_locator_dropped_from_clinical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "labs")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: INVENTED_LABS_DRAFT,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: LABS_RESULT,
    )

    events = _stream_chat(monkeypatch)
    clinical = next(data for name, data in events if name == "clinical")

    assert EMPTY_CLINICAL_MESSAGE in clinical["text"]
    assert "9.9 mg/dL" not in clinical["text"]


def test_dosing_question_includes_dosing_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dosing + research miss → chart facts + canonical no_research (not SSE error)."""
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "meds")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: VALID_MEDS_DRAFT,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: MEDS_RESULT,
    )
    # Avoid real FDA egress; miss keeps H1 refuse path.
    miss = MagicMock(
        ok=False,
        source=None,
        set_id=None,
        outcome="miss",
        openfda_result=None,
        dailymed_xml=None,
        generic_names=(),
        brand_names=(),
    )
    monkeypatch.setattr(
        "sidecar.app.nodes.tools.fetch_label",
        lambda *_a, **_k: miss,
    )

    events = _stream_chat(
        monkeypatch,
        _chat_payload(message="What dose of metformin should I titrate to?"),
    )
    clinical = next(data for name, data in events if name == "clinical")
    event_names = [name for name, _ in events]

    assert "Metformin 500 mg" in clinical["text"]
    assert DOSING_REFUSAL_TEXT in clinical["text"]
    assert "error" not in event_names
    assert "done" in event_names


def test_med_list_question_has_no_dosing_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain 'what meds' turn ships verified Rx facts without refusal noise."""
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "meds")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: VALID_MEDS_DRAFT,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: MEDS_RESULT,
    )

    events = _stream_chat(
        monkeypatch,
        _chat_payload(message="What medications is the patient on?"),
    )
    clinical = next(data for name, data in events if name == "clinical")

    assert "Metformin 500 mg" in clinical["text"]
    assert DOSING_REFUSAL_TEXT not in clinical["text"]


def test_dosing_research_hit_omits_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Meds + mock research hit → label text in clinical; no_research absent."""
    from sidecar.app.research import LabelFetchResult

    set_id = "abc-set-id-1"
    fact_id = f"{set_id}:dosage_and_administration"
    openfda_result = {
        "openfda": {
            "generic_name": ["METFORMIN"],
            "brand_name": ["GLUCOPHAGE"],
            "spl_set_id": [set_id],
            "product_type": ["HUMAN PRESCRIPTION DRUG"],
        },
        "dosage_and_administration": [
            "Usual adult dose is 500 mg twice daily with meals."
        ],
    }
    research_draft = json.dumps(
        {
            "claims": [
                {
                    "text": "Metformin 500 mg tablet — take one twice daily with meals",
                    "source_type": "chart",
                    "locator": {"table": "prescriptions", "id": "201"},
                },
                {
                    "text": "model label prose",
                    "source_type": "research",
                    "locator": {"table": "openfda", "id": fact_id},
                },
            ],
            "refusals": [],
        }
    )

    def _fake_fetch(query: Any, *, correlation_id: str = "") -> LabelFetchResult:
        return LabelFetchResult(
            ok=True,
            source="openfda",
            set_id=set_id,
            outcome="hit_openfda",
            openfda_result=openfda_result,
            generic_names=("METFORMIN",),
            brand_names=("GLUCOPHAGE",),
        )

    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "meds")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: research_draft,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: MEDS_RESULT,
    )
    monkeypatch.setattr("sidecar.app.nodes.tools.fetch_label", _fake_fetch)

    events = _stream_chat(
        monkeypatch,
        _chat_payload(message="What is the typical adult dose of metformin?"),
    )
    clinical = next(data for name, data in events if name == "clinical")
    citation = next(data for name, data in events if name == "citation")
    progress = [data["message"] for name, data in events if name == "progress"]
    names = [name for name, _ in events]

    assert names.index("clinical") < names.index("citation")
    assert names.index("citation") < names.index("done")
    assert "Usual adult dose is 500 mg twice daily" in clinical["text"]
    assert DOSING_REFUSAL_TEXT not in clinical["text"]
    assert any("Looking up label information" in p for p in progress)

    research_cites = [
        c for c in citation["citations"] if c.get("source_type") == "research"
    ]
    assert len(research_cites) >= 1
    claim_segs = [s for s in clinical["segments"] if s.get("kind") == "claim"]
    assert all("citation_id" in s for s in claim_segs)
    research_ids = {c["citation_id"] for c in research_cites}
    claim_ids = {s["citation_id"] for s in claim_segs}
    assert research_ids <= claim_ids


def test_brief_route_never_looks_up_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H11: brief never invokes research even if message is dosing-like."""
    fetch_mock = MagicMock()
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "brief")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: VALID_MEDS_DRAFT,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: MEDS_RESULT,
    )
    monkeypatch.setattr("sidecar.app.nodes.tools.fetch_label", fetch_mock)

    events = _stream_chat(
        monkeypatch,
        _chat_payload(message="What is the typical adult dose of metformin?"),
    )
    progress = [data["message"] for name, data in events if name == "progress"]

    fetch_mock.assert_not_called()
    assert not any("Looking up label information" in p for p in progress)


def test_brief_route_emits_summary_and_claim_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "brief")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: VALID_BRIEF_DRAFT,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        _gateway_brief_tool,
    )
    _patch_synthesize_turn_raw(
        monkeypatch,
        lambda *_a, **_k: json.dumps(
            {
                "summary": (
                    "Patient presents for follow-up for hypertension. "
                    "Last visit was 2024-03-01."
                )
            }
        ),
    )

    events = _stream_chat(monkeypatch, _chat_payload(message="Brief me."))
    clinical = next(data for name, data in events if name == "clinical")
    citation = next(data for name, data in events if name == "citation")

    summary_segs = [s for s in clinical["segments"] if s.get("kind") == "summary"]
    claim_segs = [s for s in clinical["segments"] if s.get("kind") == "claim"]
    assert len(summary_segs) == 1
    assert summary_segs[0]["text"].startswith("Patient presents for follow-up")
    assert "citation_id" not in summary_segs[0]
    assert len(claim_segs) >= 2
    assert clinical["text"].startswith("Patient presents for follow-up")
    assert len(citation["citations"]) == len(claim_segs)


def test_labs_route_emits_summary_segment_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRD 10: labs with verified claims → labeled summary segment first."""
    synthesize_mock = MagicMock(return_value=_MOCK_LABS_SYNTHESIS)
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "labs")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: VALID_LABS_DRAFT,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: LABS_RESULT,
    )
    _patch_synthesize_turn_raw(monkeypatch, synthesize_mock)

    events = _stream_chat(monkeypatch)
    clinical = next(data for name, data in events if name == "clinical")
    progress = [data["message"] for name, data in events if name == "progress"]

    synthesize_mock.assert_called_once()
    summary_segs = [s for s in clinical["segments"] if s.get("kind") == "summary"]
    claim_segs = [s for s in clinical["segments"] if s.get("kind") == "claim"]
    assert len(summary_segs) == 1
    assert clinical["segments"][0]["kind"] == "summary"
    assert summary_segs[0]["text"].startswith("Creatinine is within reference range")
    assert "citation_id" not in summary_segs[0]
    assert claim_segs
    assert clinical["text"].startswith("Creatinine is within reference range")
    assert any("Summarizing" in p for p in progress)


def test_labs_abnormal_followup_emits_visible_answer_or_failure_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UC-2 follow-up: abnormal phrasing must not yield claims-only collapsed UI."""
    abnormal_synthesis = json.dumps(
        {
            "summary": (
                "None of the verified recent lab results include an abnormal flag on file."
            )
        }
    )
    synthesize_mock = MagicMock(return_value=abnormal_synthesis)
    draft_mock = MagicMock(return_value=VALID_LABS_DRAFT)
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "labs")
    monkeypatch.setattr("sidecar.app.nodes.draft.draft_claims_raw", draft_mock)
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: LABS_RESULT,
    )
    _patch_synthesize_turn_raw(monkeypatch, synthesize_mock)

    transcript = [
        {"role": "user", "text": "Show recent labs"},
        {
            "role": "assistant",
            "text": "Creatinine is within reference range on the recent CMP.\n"
            "Serum creatinine 1.1 mg/dL (2026-06-01)",
        },
    ]
    events = _stream_chat(
        monkeypatch,
        _chat_payload(
            message="Do any of these stand out as abnormal?",
            transcript=transcript,
        ),
    )
    clinical = next(data for name, data in events if name == "clinical")

    synthesize_mock.assert_called_once()
    draft_kwargs = draft_mock.call_args.kwargs
    assert draft_kwargs["route"] == "labs"

    summary_segs = [s for s in clinical["segments"] if s.get("kind") == "summary"]
    assembly_segs = [s for s in clinical["segments"] if s.get("kind") == "assembly"]
    assert summary_segs or assembly_segs
    visible_text = clinical["text"].strip()
    assert visible_text
    assert (
        visible_text.startswith("None of the verified")
        or visible_text.startswith("I couldn't answer this question")
    )


def test_meds_list_route_emits_summary_segment_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRD 10: meds list turn with verified claims → medication summary first."""
    synthesize_mock = MagicMock(return_value=_MOCK_MEDS_LIST_SYNTHESIS)
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "meds")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: VALID_MEDS_DRAFT,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: MEDS_RESULT,
    )
    _patch_synthesize_turn_raw(monkeypatch, synthesize_mock)

    events = _stream_chat(
        monkeypatch,
        _chat_payload(message="What medications is the patient on?"),
    )
    clinical = next(data for name, data in events if name == "clinical")
    progress = [data["message"] for name, data in events if name == "progress"]

    synthesize_mock.assert_called_once()
    summary_segs = [s for s in clinical["segments"] if s.get("kind") == "summary"]
    claim_segs = [s for s in clinical["segments"] if s.get("kind") == "claim"]
    assert len(summary_segs) == 1
    assert clinical["segments"][0]["kind"] == "summary"
    assert summary_segs[0]["text"].startswith("Patient is on metformin")
    assert "citation_id" not in summary_segs[0]
    assert claim_segs
    assert "Metformin 500 mg" in clinical["text"]
    assert clinical["text"].startswith("Patient is on metformin")
    assert DOSING_REFUSAL_TEXT not in clinical["text"]
    assert any("Summarizing" in p for p in progress)


def test_meds_dosing_route_emits_summary_research_and_disclaimer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRD 10: meds dosing + research hit → summary, claims, disclaimer assembly."""
    from sidecar.app.research import LabelFetchResult

    set_id = "abc-set-id-1"
    fact_id = f"{set_id}:dosage_and_administration"
    openfda_result = {
        "openfda": {
            "generic_name": ["METFORMIN"],
            "brand_name": ["GLUCOPHAGE"],
            "spl_set_id": [set_id],
            "product_type": ["HUMAN PRESCRIPTION DRUG"],
        },
        "dosage_and_administration": [
            "Usual adult dose is 500 mg twice daily with meals."
        ],
    }
    research_draft = json.dumps(
        {
            "claims": [
                {
                    "text": "Metformin 500 mg tablet — take one twice daily with meals",
                    "source_type": "chart",
                    "locator": {"table": "prescriptions", "id": "201"},
                },
                {
                    "text": "Usual adult dose is 500 mg twice daily with meals.",
                    "source_type": "research",
                    "locator": {"table": "openfda", "id": fact_id},
                },
            ],
            "refusals": [],
        }
    )

    def _fake_fetch(query: Any, *, correlation_id: str = "") -> LabelFetchResult:
        return LabelFetchResult(
            ok=True,
            source="openfda",
            set_id=set_id,
            outcome="hit_openfda",
            openfda_result=openfda_result,
            generic_names=("METFORMIN",),
            brand_names=("GLUCOPHAGE",),
        )

    synthesize_mock = MagicMock(return_value=_MOCK_MEDS_DOSING_SYNTHESIS)
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "meds")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: research_draft,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: MEDS_RESULT,
    )
    monkeypatch.setattr("sidecar.app.nodes.tools.fetch_label", _fake_fetch)
    _patch_synthesize_turn_raw(monkeypatch, synthesize_mock)

    events = _stream_chat(
        monkeypatch,
        _chat_payload(message="What is the typical adult dose of metformin?"),
    )
    clinical = next(data for name, data in events if name == "clinical")
    citation = next(data for name, data in events if name == "citation")
    progress = [data["message"] for name, data in events if name == "progress"]

    synthesize_mock.assert_called_once()
    summary_segs = [s for s in clinical["segments"] if s.get("kind") == "summary"]
    claim_segs = [s for s in clinical["segments"] if s.get("kind") == "claim"]
    assembly_segs = [s for s in clinical["segments"] if s.get("kind") == "assembly"]
    assert len(summary_segs) == 1
    assert clinical["segments"][0]["kind"] == "summary"
    assert summary_segs[0]["text"].startswith("Metformin is typically started")
    assert claim_segs
    assert any("Usual adult dose is 500 mg twice daily" in s["text"] for s in claim_segs)
    assert any(
        DECISION_SUPPORT_DISCLAIMER in s["text"] for s in assembly_segs
    )
    assert DOSING_REFUSAL_TEXT not in clinical["text"]
    assert any("Summarizing" in p for p in progress)
    assert any("Looking up label information" in p for p in progress)

    research_cites = [
        c for c in citation["citations"] if c.get("source_type") == "research"
    ]
    assert len(research_cites) >= 1
    research_ids = {c["citation_id"] for c in research_cites}
    claim_ids = {s["citation_id"] for s in claim_segs}
    assert research_ids <= claim_ids


def test_oversized_message_yields_error_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Messages beyond the gateway cap are refused before any LLM/tool work."""
    route_mock = MagicMock(return_value="labs")
    gateway_mock = MagicMock(return_value=LABS_RESULT)
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", route_mock)
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        gateway_mock,
    )

    events = _stream_chat(monkeypatch, _chat_payload(message="x" * 4001))

    error = next(data for name, data in events if name == "error")
    assert error["code"] == ERROR_INVALID_MESSAGE
    assert error["message"] == message_for_code(ERROR_INVALID_MESSAGE)
    assert error["correlation_id"] == "corr-int-1"
    assert not any(name == "clinical" for name, _ in events)
    route_mock.assert_not_called()
    gateway_mock.assert_not_called()


def test_missing_pid_refuses_without_llm_or_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route_mock = MagicMock(return_value="labs")
    draft_mock = MagicMock(return_value=VALID_LABS_DRAFT)
    gateway_mock = MagicMock(return_value=LABS_RESULT)
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", route_mock)
    monkeypatch.setattr("sidecar.app.nodes.draft.draft_claims_raw", draft_mock)
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        gateway_mock,
    )

    events = _stream_chat(monkeypatch, _chat_payload(pid=None))

    clinical = next(data for name, data in events if name == "clinical")
    assert clinical["text"] == UNBOUND_MESSAGE
    assert "event: done" in "\n".join(f"{n}:{d}" for n, d in events) or any(
        n == "done" for n, _ in events
    )
    route_mock.assert_not_called()
    draft_mock.assert_not_called()
    gateway_mock.assert_not_called()


def test_llm_error_yields_generic_error_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "labs")

    def _raise_llm(*_a: object, **_k: object) -> str:
        raise LlmError("OpenRouter request failed")

    monkeypatch.setattr("sidecar.app.nodes.draft.draft_claims_raw", _raise_llm)
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: LABS_RESULT,
    )

    events = _stream_chat(monkeypatch)

    error = next(data for name, data in events if name == "error")
    assert error["code"] == ERROR_LLM_UNAVAILABLE
    assert error["message"] == message_for_code(ERROR_LLM_UNAVAILABLE)
    assert error["correlation_id"] == "corr-int-1"
    assert "OpenRouter" not in error["message"]
    assert not any(name == "clinical" for name, _ in events)


def test_route_llm_error_yields_generic_error_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_route(*_a: object, **_k: object) -> str:
        raise LlmError("OpenRouter request failed")

    draft_mock = MagicMock(return_value=VALID_LABS_DRAFT)
    gateway_mock = MagicMock(return_value=LABS_RESULT)
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", _raise_route)
    monkeypatch.setattr("sidecar.app.nodes.draft.draft_claims_raw", draft_mock)
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        gateway_mock,
    )

    events = _stream_chat(monkeypatch)

    error = next(data for name, data in events if name == "error")
    assert error["code"] == ERROR_LLM_UNAVAILABLE
    assert error["message"] == message_for_code(ERROR_LLM_UNAVAILABLE)
    assert not any(name == "clinical" for name, _ in events)
    draft_mock.assert_not_called()
    gateway_mock.assert_not_called()


def test_gateway_network_error_yields_generic_error_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sidecar.app.gateway_client import GatewayNetworkError

    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "labs")

    def _raise_network(*_a: object, **_k: object) -> dict:
        raise GatewayNetworkError("tool_proxy request failed")

    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        _raise_network,
    )
    draft_mock = MagicMock(return_value=VALID_LABS_DRAFT)
    monkeypatch.setattr("sidecar.app.nodes.draft.draft_claims_raw", draft_mock)

    events = _stream_chat(monkeypatch)

    error = next(data for name, data in events if name == "error")
    assert error["code"] == ERROR_GATEWAY_UNREACHABLE
    assert error["message"] == message_for_code(ERROR_GATEWAY_UNREACHABLE)
    assert not any(name == "clinical" for name, _ in events)
    draft_mock.assert_not_called()


def test_gateway_4xx_error_yields_generic_error_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Base GatewayError (HTTP 400) must become an SSE error, not abort the stream."""
    from sidecar.app.gateway_client import GatewayError

    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "labs")

    def _raise_4xx(*_a: object, **_k: object) -> dict:
        raise GatewayError("tool_proxy error: not_implemented")

    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        _raise_4xx,
    )
    draft_mock = MagicMock(return_value=VALID_LABS_DRAFT)
    monkeypatch.setattr("sidecar.app.nodes.draft.draft_claims_raw", draft_mock)

    events = _stream_chat(monkeypatch)

    error = next(data for name, data in events if name == "error")
    assert error["code"] == ERROR_GATEWAY_TOOL
    assert error["message"] == message_for_code(ERROR_GATEWAY_TOOL)
    assert "not_implemented" not in error["message"]
    assert not any(name == "clinical" for name, _ in events)
    draft_mock.assert_not_called()


def test_unexpected_graph_exception_yields_error_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unhandled graph exceptions must still emit a hybrid SSE error frame."""

    class _BoomGraph:
        def stream(self, *_a: object, **_k: object):
            raise RuntimeError("unexpected node failure")

    monkeypatch.setattr(
        "sidecar.app.stream.build_graph",
        lambda *_a, **_k: _BoomGraph(),
    )

    events = _stream_chat(monkeypatch)

    error = next(data for name, data in events if name == "error")
    assert error["code"] == ERROR_UNEXPECTED
    assert error["message"] == message_for_code(ERROR_UNEXPECTED)
    assert "node failure" not in error["message"].lower()
    assert not any(name == "clinical" for name, _ in events)
    assert not any(name == "done" for name, _ in events)


def test_invented_claim_text_with_valid_locator_replaced_by_tool_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "labs")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: json.dumps(
            {
                "claims": [
                    {
                        "text": "Serum creatinine 9.9 mg/dL (hallucinated)",
                        "source_type": "chart",
                        "locator": {"table": "procedure_result", "id": "501"},
                    }
                ],
                "refusals": [
                    {
                        "code": "sneaky",
                        "text": "Also inventing creatinine 99 via refusal",
                    }
                ],
            }
        ),
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: LABS_RESULT,
    )

    events = _stream_chat(monkeypatch)
    clinical = next(data for name, data in events if name == "clinical")

    assert "Serum creatinine 1.1 mg/dL" in clinical["text"]
    assert "9.9" not in clinical["text"]
    assert "99" not in clinical["text"]


def test_invalid_draft_json_yields_error_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "labs")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: "not valid json at all",
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: LABS_RESULT,
    )

    events = _stream_chat(monkeypatch)

    error = next(data for name, data in events if name == "error")
    assert error["code"] == ERROR_DRAFT_PARSE
    assert error["message"] == message_for_code(ERROR_DRAFT_PARSE)
    assert not any(name == "clinical" for name, _ in events)


def test_disclosure_callback_failure_still_emits_clinical_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Best-effort verify disclosure must not break progress→clinical→citation→done."""
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "labs")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: VALID_LABS_DRAFT,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: LABS_RESULT,
    )

    def _boom(*_a: object, **_k: object) -> bool:
        raise RuntimeError("disclosure unavailable")

    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.post_verify_disclosure",
        _boom,
    )

    events = _stream_chat(monkeypatch)
    names = [name for name, _ in events]
    assert names.index("progress") < names.index("clinical")
    assert names.index("clinical") < names.index("citation")
    assert names.index("citation") < names.index("done")
    assert not any(name == "error" for name, _ in events)


CACHED_BRIEF_CLINICAL_TEXT = (
    "Summary: Patient presents for follow-up for hypertension. "
    "Last visit was 2024-03-01."
)
CACHED_BRIEF_SEGMENTS: list[dict[str, Any]] = [
    {
        "kind": "summary",
        "text": "Summary: Patient presents for follow-up for hypertension.",
    },
    {
        "kind": "claim",
        "text": "Last visit 2024-03-01 — follow-up for hypertension",
        "citation_id": "cache-cite-1",
    },
]
CACHED_BRIEF_CITATIONS: list[dict[str, Any]] = [
    {
        "citation_id": "cache-cite-1",
        "source_type": "chart",
        "label": "Last visit",
        "locator": {"table": "form_encounter", "id": "701"},
    },
]


@pytest.fixture(autouse=True)
def _reset_brief_cache() -> None:
    clear_brief_cache()
    yield
    clear_brief_cache()


def _seed_brief_cache(
    *,
    user_id: int = 1,
    pid: int = 6,
    correlation_id: str = "corr-prefetch-1",
) -> None:
    get_brief_cache().put(
        user_id,
        pid,
        correlation_id=correlation_id,
        clinical_text=CACHED_BRIEF_CLINICAL_TEXT,
        clinical_segments=CACHED_BRIEF_SEGMENTS,
        citations=CACHED_BRIEF_CITATIONS,
    )


def test_cache_hit_auto_brief_replays_sse_without_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warm cache + auto-brief + empty transcript → clinical/citation/done, no LLM."""
    _seed_brief_cache()

    route_mock = MagicMock(return_value="brief")
    draft_mock = MagicMock(return_value=VALID_BRIEF_DRAFT)
    build_graph_mock = MagicMock()
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", route_mock)
    monkeypatch.setattr("sidecar.app.nodes.draft.draft_claims_raw", draft_mock)
    monkeypatch.setattr("sidecar.app.stream.build_graph", build_graph_mock)

    events = _stream_chat(
        monkeypatch,
        _chat_payload(message=AUTO_BRIEF_MESSAGE, transcript=[]),
    )
    names = [name for name, _ in events]

    assert names == ["clinical", "citation", "done"]
    assert "progress" not in names

    clinical = next(data for name, data in events if name == "clinical")
    citation = next(data for name, data in events if name == "citation")
    done = next(data for name, data in events if name == "done")

    assert clinical["text"] == CACHED_BRIEF_CLINICAL_TEXT
    assert clinical["segments"] == CACHED_BRIEF_SEGMENTS
    assert citation["citations"] == CACHED_BRIEF_CITATIONS
    assert done["correlation_id"] == "corr-int-1"

    route_mock.assert_not_called()
    draft_mock.assert_not_called()
    build_graph_mock.assert_not_called()


def test_cache_miss_auto_brief_runs_full_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto-brief with empty cache still runs the graph (mock LLM)."""
    route_mock = MagicMock(return_value="brief")
    draft_mock = MagicMock(return_value=VALID_BRIEF_DRAFT)
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", route_mock)
    monkeypatch.setattr("sidecar.app.nodes.draft.draft_claims_raw", draft_mock)
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        _gateway_brief_tool,
    )
    _patch_synthesize_turn_raw(
        monkeypatch,
        lambda *_a, **_k: json.dumps(
            {"summary": "Patient presents for follow-up for hypertension."}
        ),
    )

    events = _stream_chat(
        monkeypatch,
        _chat_payload(message=AUTO_BRIEF_MESSAGE, transcript=[]),
    )
    names = [name for name, _ in events]

    assert "progress" in names
    assert "clinical" in names
    assert "citation" in names
    assert names[-1] == "done"
    route_mock.assert_called()
    draft_mock.assert_called()


def test_cache_warm_labs_message_runs_full_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Follow-up labs question must not serve cached brief."""
    _seed_brief_cache()

    route_mock = MagicMock(return_value="labs")
    draft_mock = MagicMock(return_value=VALID_LABS_DRAFT)
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", route_mock)
    monkeypatch.setattr("sidecar.app.nodes.draft.draft_claims_raw", draft_mock)
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: LABS_RESULT,
    )
    _patch_synthesize_turn_raw(
        monkeypatch,
        lambda *_a, **_k: _MOCK_LABS_SYNTHESIS,
    )

    events = _stream_chat(
        monkeypatch,
        _chat_payload(message="What's creatinine?", transcript=[]),
    )
    names = [name for name, _ in events]

    assert "progress" in names
    assert names.index("clinical") < names.index("citation")
    clinical = next(data for name, data in events if name == "clinical")
    assert "Serum creatinine 1.1 mg/dL" in clinical["text"]
    assert CACHED_BRIEF_CLINICAL_TEXT not in clinical["text"]
    route_mock.assert_called()
    draft_mock.assert_called()


def test_cache_warm_auto_brief_with_transcript_runs_full_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto-brief after a prior turn must not replay cache."""
    _seed_brief_cache()

    route_mock = MagicMock(return_value="brief")
    draft_mock = MagicMock(return_value=VALID_BRIEF_DRAFT)
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", route_mock)
    monkeypatch.setattr("sidecar.app.nodes.draft.draft_claims_raw", draft_mock)
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        _gateway_brief_tool,
    )
    _patch_synthesize_turn_raw(
        monkeypatch,
        lambda *_a, **_k: json.dumps(
            {"summary": "Patient presents for follow-up for hypertension."}
        ),
    )

    events = _stream_chat(
        monkeypatch,
        _chat_payload(
            message=AUTO_BRIEF_MESSAGE,
            transcript=[
                {"role": "user", "text": "What's creatinine?"},
                {"role": "assistant", "text": "Serum creatinine 1.1 mg/dL."},
            ],
        ),
    )
    names = [name for name, _ in events]

    assert "progress" in names
    clinical = next(data for name, data in events if name == "clinical")
    assert CACHED_BRIEF_CLINICAL_TEXT not in clinical["text"]
    route_mock.assert_called()
    draft_mock.assert_called()
