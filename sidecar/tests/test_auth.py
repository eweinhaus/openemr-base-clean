"""Tests for internal-secret auth and refuse-path chat SSE."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sidecar.app.auth import CORRELATION_HEADER, SECRET_HEADER
from sidecar.app.main import app
from sidecar.app.state import UNBOUND_MESSAGE

TEST_SECRET = "test-secret-for-pytest"


def _chat_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "correlation_id": "corr-123",
        "user_id": 1,
        "username": "admin",
        "pid": 6,
        "message": "Hello",
        "transcript": [],
    }
    payload.update(overrides)
    return payload


def test_chat_rejects_missing_secret() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/chat", json=_chat_payload())

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_chat_rejects_wrong_secret() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat",
            json=_chat_payload(),
            headers={SECRET_HEADER: "wrong-secret"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_chat_refuses_unbound_pid_without_placeholder_clinical() -> None:
    headers = {
        SECRET_HEADER: TEST_SECRET,
        CORRELATION_HEADER: "corr-123",
        "Accept": "text/event-stream",
    }
    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/v1/chat",
            json=_chat_payload(pid=None),
            headers=headers,
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = "".join(response.iter_text())

    assert (
        f'event: clinical\ndata: {{"text": "{UNBOUND_MESSAGE}", "segments": []}}'
        in body
    )
    assert 'event: citation\ndata: {"citations": []}' in body
    assert 'event: done\ndata: {"correlation_id": "corr-123"}' in body
    assert "Stub sidecar:" not in body
    assert "skeleton online" not in body.lower()
