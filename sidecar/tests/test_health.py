"""Tests for /health and soft /ready endpoints."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from sidecar.app.auth import CORRELATION_HEADER, SECRET_HEADER
from sidecar.app.errors import ERROR_SIDECAR_UNREADY, message_for_code
from sidecar.app.main import app

TEST_SECRET = "test-secret-for-pytest"


def test_health_returns_200_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.text == "ok"


def test_ready_returns_200_with_degraded_body_when_deps_unreachable() -> None:
    async def fake_probe(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"reachable": False, "error": "ConnectError"}

    with patch("sidecar.app.main._probe_url", new=AsyncMock(side_effect=fake_probe)):
        with patch(
            "sidecar.app.tracing.probe_langsmith",
            new=AsyncMock(
                return_value={"configured": False, "reachable": False}
            ),
        ):
            with TestClient(app) as client:
                response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["gateway"]["reachable"] is False
    assert body["openrouter"]["configured"] is False
    assert "langsmith" in body
    assert body["langsmith"]["configured"] is False


def test_ready_reports_unready_when_api_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clinical turns need OpenRouter — a missing key must not look ready."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    async def fake_probe(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"reachable": True, "status_code": 200}

    with patch("sidecar.app.main._probe_url", new=AsyncMock(side_effect=fake_probe)):
        with TestClient(app) as client:
            response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["gateway"]["reachable"] is True
    assert body["openrouter"]["configured"] is False
    assert body["langsmith"]["configured"] is False


def test_ready_reports_ready_when_probes_succeed_with_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    async def fake_probe(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"reachable": True, "status_code": 200}

    with patch("sidecar.app.main._probe_url", new=AsyncMock(side_effect=fake_probe)):
        with TestClient(app) as client:
            response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["gateway"]["reachable"] is True
    assert body["openrouter"]["reachable"] is True
    assert body["openrouter"]["configured"] is True
    assert body["langsmith"]["configured"] is False


def test_ready_soft_langsmith_unreachable_does_not_flip_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H3: missing/unreachable LangSmith must not alone set ready=false."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test-key")

    async def fake_probe(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"reachable": True, "status_code": 200}

    async def fake_langsmith(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"configured": True, "reachable": False, "error": "ConnectError"}

    with patch("sidecar.app.main._probe_url", new=AsyncMock(side_effect=fake_probe)):
        with patch(
            "sidecar.app.main.probe_langsmith",
            new=AsyncMock(side_effect=fake_langsmith),
        ):
            with TestClient(app) as client:
                response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["langsmith"]["configured"] is True
    assert body["langsmith"]["reachable"] is False


def test_ready_does_not_probe_research_apis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H10: /ready must not call openFDA / DailyMed (or fetch_label)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    fetch_mock = AsyncMock()

    async def fake_probe(client: object, url: str, **_kwargs: object) -> dict[str, object]:
        assert "fda.gov" not in url
        assert "dailymed" not in url
        return {"reachable": True, "status_code": 200}

    with patch("sidecar.app.main._probe_url", new=AsyncMock(side_effect=fake_probe)):
        with patch("sidecar.app.research.client.fetch_label", fetch_mock):
            with TestClient(app) as client:
                response = client.get("/ready")

    assert response.status_code == 200
    fetch_mock.assert_not_called()
    assert "langsmith" in response.json()


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


def test_chat_unready_yields_sidecar_unready_without_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H9: ready=false → one SSE error; no graph / LLM / clinical."""
    monkeypatch.setenv("COPILOT_INTERNAL_SECRET", TEST_SECRET)

    async def unready(_settings: object) -> dict[str, object]:
        return {
            "ready": False,
            "gateway": {"reachable": False},
            "openrouter": {"configured": True, "reachable": True},
            "langsmith": {"configured": False, "reachable": False},
            "openrouter_model": "anthropic/claude-haiku-4.5",
        }

    build_graph = MagicMock()
    iter_events = MagicMock()
    monkeypatch.setattr("sidecar.app.main.check_readiness", unready)
    monkeypatch.setattr("sidecar.app.stream.build_graph", build_graph)
    monkeypatch.setattr("sidecar.app.main.iter_chat_events", iter_events)

    headers = {
        SECRET_HEADER: TEST_SECRET,
        CORRELATION_HEADER: "corr-unready-1",
        "Accept": "text/event-stream",
    }
    payload = {
        "correlation_id": "corr-unready-1",
        "user_id": 1,
        "username": "admin",
        "pid": 6,
        "message": "Show recent labs",
        "transcript": [],
    }

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/v1/chat",
            json=payload,
            headers=headers,
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert len(events) == 1
    name, data = events[0]
    assert name == "error"
    assert data["code"] == ERROR_SIDECAR_UNREADY
    assert data["message"] == message_for_code(ERROR_SIDECAR_UNREADY)
    assert data["message"] == "Co-Pilot is temporarily unavailable. Try again."
    assert data["correlation_id"] == "corr-unready-1"
    assert "OpenRouter" not in data["message"]
    assert "LangSmith" not in data["message"]
    build_graph.assert_not_called()
    iter_events.assert_not_called()
