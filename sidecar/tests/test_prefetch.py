"""Tests for PRD 09 Wave 2 prefetch queue and graph shortcut."""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from sidecar.app.auth import SECRET_HEADER
from sidecar.app.brief_cache import clear_brief_cache, get_brief_cache
from sidecar.app.claims import Claim, Locator
from sidecar.app.graph import _after_refuse
from sidecar.app.main import app
from sidecar.app.prefetch import (
    PrefetchJob,
    decrement_chat_active,
    enqueue_prefetch,
    increment_chat_active,
    reset_prefetch_queue,
)

TEST_SECRET = "test-secret"

SAMPLE_CLAIM = Claim(
    text="Creatinine 1.1 mg/dL",
    source_type="chart",
    locator=Locator(table="procedure_result", id="501"),
)


@pytest.fixture(autouse=True)
def _reset_prefetch_state() -> None:
    reset_prefetch_queue()
    clear_brief_cache()
    yield
    reset_prefetch_queue()
    clear_brief_cache()


def _fake_settings() -> MagicMock:
    settings = MagicMock()
    settings.internal_secret = TEST_SECRET
    settings.gateway_tool_url = "http://example.test/tool_proxy.php"
    settings.gateway_disclosure_url = "http://example.test/disclosure.php"
    settings.tool_timeout_seconds = 5.0
    return settings


def _fake_graph_updates(
    *,
    verified_claims: list[Claim] | None = None,
    include_clinical: bool = True,
) -> list[dict[str, dict[str, Any]]]:
    verified = verified_claims if verified_claims is not None else [SAMPLE_CLAIM]
    updates: list[dict[str, dict[str, Any]]] = [
        {
            "tools": {
                "requested_tools": ["patient_context", "labs", "meds", "notes"],
                "tool_results": [],
                "progress_messages": ["Pulling chart…"],
            }
        },
        {"verify": {"verified_claims": verified}},
    ]
    if include_clinical and verified:
        updates.append(
            {
                "emit": {
                    "clinical_text": "Creatinine 1.1 mg/dL",
                    "clinical_segments": [
                        {"kind": "claim", "text": "Creatinine 1.1 mg/dL"}
                    ],
                    "citations": [{"id": "c1", "label": "Lab result"}],
                }
            }
        )
    return updates


class _FakeGraph:
    def __init__(self, updates: list[dict[str, dict[str, Any]]]) -> None:
        self._updates = updates

    def stream(self, *_args: object, **_kwargs: object):
        for update in self._updates:
            yield update


async def _fake_ready(_settings: object) -> dict[str, object]:
    return {
        "ready": True,
        "gateway": {"reachable": True},
        "openrouter": {"configured": True, "reachable": True},
        "langsmith": {"configured": False, "reachable": False},
        "openrouter_model": "anthropic/claude-haiku-4.5",
    }


def test_after_refuse_prefetch_brief_skips_route() -> None:
    assert _after_refuse({"prefetch": True, "route": "brief"}) == "tools"


def test_after_refuse_non_prefetch_still_routes() -> None:
    assert _after_refuse({"prefetch": False, "route": "brief"}) == "route"
    assert _after_refuse({"route": "brief"}) == "route"


def test_prefetch_skips_route_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    route_mock = MagicMock(side_effect=AssertionError("route LLM invoked"))
    monkeypatch.setattr("sidecar.app.nodes.route.route_message", route_mock)
    monkeypatch.setattr(
        "sidecar.app.prefetch.build_graph",
        lambda _gw: _FakeGraph(_fake_graph_updates()),
    )

    job = PrefetchJob(
        user_id=10,
        username="admin",
        pid=6,
        correlation_id="prefetch-route-skip",
    )
    from sidecar.app.prefetch import _run_prefetch_job

    _run_prefetch_job(job, _fake_settings())

    route_mock.assert_not_called()
    entry = get_brief_cache().get(user_id=10, pid=6)
    assert entry is not None
    assert entry["clinical_text"] == "Creatinine 1.1 mg/dL"


def test_zero_verified_claims_does_not_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sidecar.app.prefetch.build_graph",
        lambda _gw: _FakeGraph(_fake_graph_updates(verified_claims=[], include_clinical=False)),
    )

    job = PrefetchJob(user_id=10, username="admin", pid=6, correlation_id="prefetch-zero")
    from sidecar.app.prefetch import _run_prefetch_job

    _run_prefetch_job(job, _fake_settings())

    assert get_brief_cache().get(user_id=10, pid=6) is None


def test_successful_prefetch_puts_cache_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sidecar.app.prefetch.build_graph",
        lambda _gw: _FakeGraph(_fake_graph_updates()),
    )

    job = PrefetchJob(
        user_id=10,
        username="admin",
        pid=8,
        correlation_id="prefetch-hit",
    )
    from sidecar.app.prefetch import _run_prefetch_job

    _run_prefetch_job(job, _fake_settings())

    entry = get_brief_cache().get(user_id=10, pid=8)
    assert entry is not None
    assert entry["correlation_id"] == "prefetch-hit"
    assert entry["clinical_text"] == "Creatinine 1.1 mg/dL"
    assert entry["citations"] == [{"id": "c1", "label": "Lab result"}]


def test_synthesize_guard_fail_still_caches_claims_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard fail skips summary but emit still produces claims-only payload."""
    updates = _fake_graph_updates()
    updates.insert(1, {"synthesize": {}})
    monkeypatch.setattr(
        "sidecar.app.prefetch.build_graph",
        lambda _gw: _FakeGraph(updates),
    )

    job = PrefetchJob(
        user_id=10,
        username="admin",
        pid=2,
        correlation_id="prefetch-guard-fail",
    )
    from sidecar.app.prefetch import _run_prefetch_job

    _run_prefetch_job(job, _fake_settings())

    entry = get_brief_cache().get(user_id=10, pid=2)
    assert entry is not None
    assert entry["clinical_text"] == "Creatinine 1.1 mg/dL"
    assert all(seg.get("kind") != "summary" for seg in entry["clinical_segments"])


def test_queue_serializes_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    lock = threading.Lock()
    active = 0
    max_active = 0
    order: list[int] = []
    release = threading.Event()

    def _slow_job(job: PrefetchJob, _settings: object) -> None:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            order.append(job.pid)
        try:
            time.sleep(0.05)
        finally:
            with lock:
                active -= 1
            if len(order) == 2:
                release.set()

    monkeypatch.setattr("sidecar.app.prefetch._run_prefetch_job", _slow_job)

    loader = _fake_settings
    assert enqueue_prefetch(10, "admin", 6, "c1", settings_loader=loader) is True
    assert enqueue_prefetch(10, "admin", 8, "c2", settings_loader=loader) is True
    assert enqueue_prefetch(10, "admin", 6, "c3", settings_loader=loader) is False

    assert release.wait(timeout=3.0)
    assert order == [6, 8]
    assert max_active == 1


def test_chat_active_defers_prefetch(monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()
    allow_finish = threading.Event()

    def _blocking_job(job: PrefetchJob, _settings: object) -> None:
        started.set()
        assert allow_finish.wait(timeout=2.0)
        get_brief_cache().put(
            user_id=job.user_id,
            pid=job.pid,
            correlation_id=job.correlation_id,
            clinical_text="deferred",
            clinical_segments=[],
            citations=[],
        )

    monkeypatch.setattr("sidecar.app.prefetch._run_prefetch_job", _blocking_job)

    increment_chat_active()
    enqueue_prefetch(10, "admin", 6, "defer-test", settings_loader=_fake_settings)

    time.sleep(0.15)
    assert not started.is_set()

    decrement_chat_active()
    assert started.wait(timeout=2.0)
    allow_finish.set()

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if get_brief_cache().get(user_id=10, pid=6) is not None:
            break
        time.sleep(0.05)
    assert get_brief_cache().get(user_id=10, pid=6) is not None


def test_prefetch_brief_endpoint_queues_when_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sidecar.app.main.check_readiness", _fake_ready)
    enqueue_mock = MagicMock(return_value=True)
    monkeypatch.setattr("sidecar.app.prefetch.enqueue_prefetch", enqueue_mock)

    with TestClient(app) as client:
        response = client.post(
            "/v1/prefetch-brief",
            json={
                "user_id": 10,
                "username": "admin",
                "pid": 6,
                "correlation_id": "api-prefetch",
                "prefetch": True,
            },
            headers={SECRET_HEADER: TEST_SECRET},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "queued": True}
    enqueue_mock.assert_called_once_with(
        user_id=10,
        username="admin",
        pid=6,
        correlation_id="api-prefetch",
    )


def test_prefetch_brief_endpoint_unready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unready(_settings: object) -> dict[str, object]:
        return {"ready": False}

    monkeypatch.setattr("sidecar.app.main.check_readiness", _unready)

    with TestClient(app) as client:
        response = client.post(
            "/v1/prefetch-brief",
            json={"user_id": 10, "username": "admin", "pid": 6, "correlation_id": "x"},
            headers={SECRET_HEADER: TEST_SECRET},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": "unready"}


def test_prefetch_brief_endpoint_unauthorized() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/prefetch-brief",
            json={"user_id": 10, "username": "admin", "pid": 6, "correlation_id": "x"},
            headers={SECRET_HEADER: "wrong-secret"},
        )

    assert response.status_code == 401
