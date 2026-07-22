"""Unit tests for LangSmith hide policy and stream metadata (PRD 07 P2)."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest

from sidecar.app import tracing
from sidecar.app.stream import build_stream_config, iter_chat_events


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def test_apply_hide_io_policy_forces_hide_when_tracing_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_HIDE_INPUTS", raising=False)
    monkeypatch.delenv("LANGSMITH_HIDE_OUTPUTS", raising=False)

    tracing.apply_hide_io_policy()

    assert _env_truthy("LANGSMITH_HIDE_INPUTS")
    assert _env_truthy("LANGSMITH_HIDE_OUTPUTS")


def test_apply_hide_io_policy_noop_when_tracing_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGSMITH_HIDE_INPUTS", raising=False)
    monkeypatch.delenv("LANGSMITH_HIDE_OUTPUTS", raising=False)

    tracing.apply_hide_io_policy()

    assert "LANGSMITH_HIDE_INPUTS" not in os.environ
    assert "LANGSMITH_HIDE_OUTPUTS" not in os.environ


def test_build_stream_config_has_correlation_id_only() -> None:
    config = build_stream_config("corr-meta-1")
    assert config["metadata"] == {"correlation_id": "corr-meta-1"}
    assert config["tags"] == ["clinical-copilot"]
    assert "pid" not in config["metadata"]
    assert "message" not in config["metadata"]


def test_iter_chat_events_passes_stream_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeGraph:
        def stream(self, *_args: object, **kwargs: object):
            captured["config"] = kwargs.get("config")
            return iter(())

    monkeypatch.setattr(
        "sidecar.app.stream.build_graph",
        lambda *_a, **_k: _FakeGraph(),
    )

    gateway = MagicMock()
    list(
        iter_chat_events(
            gateway=gateway,
            correlation_id="corr-stream-9",
            pid=6,
            user_id=1,
            message="secret clinical text",
            transcript=[],
        )
    )

    config = captured["config"]
    assert config is not None
    assert config["metadata"] == {"correlation_id": "corr-stream-9"}
    assert config["tags"] == ["clinical-copilot"]
    assert "pid" not in config["metadata"]
    assert "message" not in config["metadata"]
    assert "secret clinical text" not in str(config)
