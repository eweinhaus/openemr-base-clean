"""Tests for /health and soft /ready endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from sidecar.app.main import app


def test_health_returns_200_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.text == "ok"


def test_ready_returns_200_with_degraded_body_when_deps_unreachable() -> None:
    async def fake_probe(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"reachable": False, "error": "ConnectError"}

    with patch("sidecar.app.main._probe_url", new=AsyncMock(side_effect=fake_probe)):
        with TestClient(app) as client:
            response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["gateway"]["reachable"] is False
    assert body["openrouter"]["configured"] is False


def test_ready_reports_ready_when_probes_succeed_without_api_key() -> None:
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
