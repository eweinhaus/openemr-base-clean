"""Integration tests for /v1/chat LangGraph agent loop (mocked LLM + gateway)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from sidecar.app.auth import CORRELATION_HEADER, SECRET_HEADER
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
from sidecar.app.llm import LlmError
from sidecar.app.main import app
from sidecar.app.state import (
    DOSING_REFUSAL,
    UNBOUND_MESSAGE,
)

TEST_SECRET = "test-secret-for-pytest"
DOSING_REFUSAL_TEXT = DOSING_REFUSAL.text


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


def _stream_chat(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    if payload is None:
        payload = _chat_payload()

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


LABS_STUB_RESULT: dict[str, Any] = {
    "ok": True,
    "tool": "labs_stub",
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

MEDS_STUB_RESULT: dict[str, Any] = {
    "ok": True,
    "tool": "meds_stub",
    "data": {
        "facts": [
            {
                "text": "Metformin 500 mg tablet — take one twice daily with meals",
                "table": "prescriptions",
                "id": "201",
                "excerpt": "Active Rx — started 2020-01-10",
            }
        ]
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
        lambda *_a, **_k: LABS_STUB_RESULT,
    )

    events = _stream_chat(monkeypatch)

    names = [name for name, _ in events]
    assert names.index("progress") < names.index("clinical")
    assert names.count("clinical") == 1
    assert names[-1] == "done"

    progress = [data for name, data in events if name == "progress"]
    assert any("Routing" in msg["message"] for msg in progress)
    assert any("Fetching chart" in msg["message"] for msg in progress)

    clinical = next(data for name, data in events if name == "clinical")
    assert "Serum creatinine 1.1 mg/dL" in clinical["text"]
    assert "Stub sidecar:" not in clinical["text"]
    assert "skeleton online" not in clinical["text"].lower()

    done = next(data for name, data in events if name == "done")
    assert done["correlation_id"] == "corr-int-1"


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
        lambda *_a, **_k: LABS_STUB_RESULT,
    )

    events = _stream_chat(monkeypatch)
    clinical = next(data for name, data in events if name == "clinical")

    assert EMPTY_CLINICAL_MESSAGE in clinical["text"]
    assert "9.9 mg/dL" not in clinical["text"]


def test_dosing_question_includes_dosing_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", lambda *_a, **_k: "meds")
    monkeypatch.setattr(
        "sidecar.app.nodes.draft.draft_claims_raw",
        lambda *_a, **_k: VALID_MEDS_DRAFT,
    )
    monkeypatch.setattr(
        "sidecar.app.gateway_client.GatewayClient.call_tool",
        lambda *_a, **_k: MEDS_STUB_RESULT,
    )

    events = _stream_chat(
        monkeypatch,
        _chat_payload(message="What dose of metformin should I titrate to?"),
    )
    clinical = next(data for name, data in events if name == "clinical")

    assert "Metformin 500 mg" in clinical["text"]
    assert DOSING_REFUSAL_TEXT in clinical["text"]


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
        lambda *_a, **_k: MEDS_STUB_RESULT,
    )

    events = _stream_chat(
        monkeypatch,
        _chat_payload(message="What medications is the patient on?"),
    )
    clinical = next(data for name, data in events if name == "clinical")

    assert "Metformin 500 mg" in clinical["text"]
    assert DOSING_REFUSAL_TEXT not in clinical["text"]


def test_oversized_message_yields_error_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Messages beyond the gateway cap are refused before any LLM/tool work."""
    route_mock = MagicMock(return_value="labs")
    gateway_mock = MagicMock(return_value=LABS_STUB_RESULT)
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
    gateway_mock = MagicMock(return_value=LABS_STUB_RESULT)
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
        lambda *_a, **_k: LABS_STUB_RESULT,
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
    gateway_mock = MagicMock(return_value=LABS_STUB_RESULT)
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
        lambda *_a, **_k: LABS_STUB_RESULT,
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
        lambda *_a, **_k: LABS_STUB_RESULT,
    )

    events = _stream_chat(monkeypatch)

    error = next(data for name, data in events if name == "error")
    assert error["code"] == ERROR_DRAFT_PARSE
    assert error["message"] == message_for_code(ERROR_DRAFT_PARSE)
    assert not any(name == "clinical" for name, _ in events)
