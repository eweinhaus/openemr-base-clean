"""Tests for ROUTE_TOOLS, parallel gather, and per-tool partial failure."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from sidecar.app.errors import (
    ERROR_GATEWAY_AUTH,
    ERROR_GATEWAY_SERVER,
    ERROR_GATEWAY_TOOL,
)
from sidecar.app.gateway_client import (
    GatewayAuthError,
    GatewayServerError,
)
from sidecar.app.nodes.tools import ROUTE_TOOLS, make_tools_node


def test_route_tools_names_and_brief_has_four() -> None:
    assert ROUTE_TOOLS == {
        "brief": ["patient_context", "labs", "meds", "notes"],
        "labs": ["labs"],
        "meds": ["meds"],
    }
    assert all("_stub" not in name for names in ROUTE_TOOLS.values() for name in names)


def test_brief_max_workers_capped_at_four(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeExecutor:
        def __init__(self, max_workers: int) -> None:
            captured["max_workers"] = max_workers

        def __enter__(self) -> "_FakeExecutor":
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def submit(self, fn: Any, *args: Any, **kwargs: Any) -> MagicMock:
            future = MagicMock()
            tool_name = args[0] if args else kwargs.get("tool")
            future.result.return_value = {
                "ok": True,
                "tool": tool_name,
                "data": {"facts": []},
            }
            return future

    monkeypatch.setattr(
        "sidecar.app.nodes.tools.ThreadPoolExecutor",
        _FakeExecutor,
    )
    monkeypatch.setattr(
        "sidecar.app.nodes.tools.as_completed",
        lambda futures: list(futures),
    )

    gateway = MagicMock()
    node = make_tools_node(gateway)
    result = node(
        {
            "pid": 6,
            "user_id": 1,
            "correlation_id": "corr-1",
            "route": "brief",
        }
    )

    assert captured["max_workers"] == 4
    assert "error" not in result
    assert len(result["tool_results"]) == 4


def test_partial_merge_three_succeed_one_server_error() -> None:
    gateway = MagicMock()

    def _call(
        tool: str,
        _args: dict,
        _pid: int,
        _corr: str,
        _user_id: int,
    ) -> dict[str, Any]:
        if tool == "notes":
            raise GatewayServerError("tool_proxy server error (500)")
        return {
            "ok": True,
            "tool": tool,
            "data": {
                "facts": [
                    {
                        "text": f"{tool} fact",
                        "table": "lists" if tool == "patient_context" else "procedure_result",
                        "id": "1",
                    }
                ]
            },
        }

    gateway.call_tool.side_effect = _call
    node = make_tools_node(gateway)
    result = node(
        {
            "pid": 6,
            "user_id": 1,
            "correlation_id": "corr-partial",
            "route": "brief",
        }
    )

    assert "error" not in result
    assert len(result["tool_results"]) == 3
    assert result["tool_domain_errors"] == {"notes": ERROR_GATEWAY_SERVER}
    tools_ok = {r["tool"] for r in result["tool_results"]}
    assert tools_ok == {"patient_context", "labs", "meds"}


def test_all_tools_fail_sets_graph_error() -> None:
    gateway = MagicMock()
    gateway.call_tool.side_effect = GatewayServerError("tool_proxy server error (500)")
    node = make_tools_node(gateway)
    result = node(
        {
            "pid": 6,
            "user_id": 1,
            "correlation_id": "corr-all-fail",
            "route": "labs",
        }
    )

    assert result["error"] == ERROR_GATEWAY_SERVER
    assert result.get("tool_results", []) == [] or "tool_results" not in result


def test_auth_error_on_any_tool_fails_closed() -> None:
    gateway = MagicMock()

    def _call(
        tool: str,
        _args: dict,
        _pid: int,
        _corr: str,
        _user_id: int,
    ) -> dict[str, Any]:
        if tool == "labs":
            raise GatewayAuthError("tool_proxy unauthorized")
        return {"ok": True, "tool": tool, "data": {"facts": []}}

    gateway.call_tool.side_effect = _call
    node = make_tools_node(gateway)
    result = node(
        {
            "pid": 6,
            "user_id": 1,
            "correlation_id": "corr-auth",
            "route": "brief",
        }
    )

    assert result["error"] == ERROR_GATEWAY_AUTH


def test_empty_facts_is_success_not_error() -> None:
    gateway = MagicMock()
    gateway.call_tool.return_value = {
        "ok": True,
        "tool": "labs",
        "data": {"facts": []},
    }
    node = make_tools_node(gateway)
    result = node(
        {
            "pid": 6,
            "user_id": 1,
            "correlation_id": "corr-empty",
            "route": "labs",
        }
    )

    assert "error" not in result
    assert result["tool_results"] == [
        {"ok": True, "tool": "labs", "data": {"facts": []}}
    ]
    assert result.get("tool_domain_errors", {}) == {}


def test_ok_false_body_counts_as_domain_error_not_success() -> None:
    gateway = MagicMock()
    gateway.call_tool.return_value = {
        "ok": False,
        "tool": "labs",
        "error": "chart_error",
    }
    node = make_tools_node(gateway)
    result = node(
        {
            "pid": 6,
            "user_id": 1,
            "correlation_id": "corr-ok-false",
            "route": "labs",
        }
    )

    assert result["error"] == ERROR_GATEWAY_TOOL
    assert result.get("tool_domain_errors", {}).get("labs") == ERROR_GATEWAY_TOOL
