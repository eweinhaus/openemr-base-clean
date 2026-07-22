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
from sidecar.app.research.client import LabelFetchResult
from sidecar.app.research.constants import (
    RESEARCH_PROGRESS_MESSAGE,
    RESEARCH_TOOL_NAME,
    UNCERTAIN_RXNORM_SUFFIX,
)


def _ok_meds_gateway(
    facts: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Gateway that returns a successful meds chart payload."""
    gateway = MagicMock()
    gateway.call_tool.return_value = {
        "ok": True,
        "tool": "meds",
        "data": {
            "facts": facts
            if facts is not None
            else [
                {
                    "text": "Simvastatin 20 MG Oral Tablet (RxNorm 312961)",
                    "table": "prescriptions",
                    "id": "12",
                }
            ]
        },
    }
    return gateway


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


# --- PRD 05 research gate (H8 / H11) -----------------------------------------


def test_brief_route_never_calls_research_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H11: research only on meds — brief never invokes fetch_label."""
    calls: list[Any] = []

    def _fake_fetch(*_a: Any, **_kw: Any) -> LabelFetchResult:
        calls.append(1)
        return LabelFetchResult(
            ok=False, source=None, set_id=None, outcome="miss"
        )

    monkeypatch.setattr("sidecar.app.nodes.tools.fetch_label", _fake_fetch)

    gateway = MagicMock()

    def _call(
        tool: str,
        _args: dict,
        _pid: int,
        _corr: str,
        _user_id: int,
    ) -> dict[str, Any]:
        return {"ok": True, "tool": tool, "data": {"facts": []}}

    gateway.call_tool.side_effect = _call
    node = make_tools_node(gateway)
    result = node(
        {
            "pid": 6,
            "user_id": 1,
            "correlation_id": "corr-brief-research",
            "route": "brief",
            "message": "What is the typical adult dose of simvastatin?",
        }
    )

    assert "error" not in result
    assert calls == []
    assert RESEARCH_PROGRESS_MESSAGE not in result.get("progress_messages", [])
    tools = {r["tool"] for r in result["tool_results"]}
    assert RESEARCH_TOOL_NAME not in tools


def test_meds_non_dosing_skips_research(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-dosing meds list ask → no HTTP, no Looking up label progress."""
    calls: list[Any] = []

    def _fake_fetch(*_a: Any, **_kw: Any) -> LabelFetchResult:
        calls.append(1)
        return LabelFetchResult(
            ok=False, source=None, set_id=None, outcome="miss"
        )

    monkeypatch.setattr("sidecar.app.nodes.tools.fetch_label", _fake_fetch)

    node = make_tools_node(_ok_meds_gateway())
    result = node(
        {
            "pid": 6,
            "user_id": 1,
            "correlation_id": "corr-meds-list",
            "route": "meds",
            "message": "what meds is the patient on?",
        }
    )

    assert "error" not in result
    assert calls == []
    assert result["progress_messages"] == ["Fetching chart…"]
    assert RESEARCH_PROGRESS_MESSAGE not in result["progress_messages"]
    assert all(r["tool"] != RESEARCH_TOOL_NAME for r in result["tool_results"])


def test_meds_dosing_blocked_uncertain_skips_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uncertain RxNorm (BLOCKED) → no HTTP, no research progress."""
    calls: list[Any] = []

    def _fake_fetch(*_a: Any, **_kw: Any) -> LabelFetchResult:
        calls.append(1)
        return LabelFetchResult(
            ok=False, source=None, set_id=None, outcome="miss"
        )

    monkeypatch.setattr("sidecar.app.nodes.tools.fetch_label", _fake_fetch)

    facts = [
        {
            "text": f"Lisinopril 10 mg — daily{UNCERTAIN_RXNORM_SUFFIX}",
            "table": "prescriptions",
            "id": "55",
        }
    ]
    node = make_tools_node(_ok_meds_gateway(facts))
    result = node(
        {
            "pid": 2,
            "user_id": 1,
            "correlation_id": "corr-blocked",
            "route": "meds",
            "message": "What is the typical adult dose of lisinopril?",
        }
    )

    assert "error" not in result
    assert calls == []
    assert RESEARCH_PROGRESS_MESSAGE not in result.get("progress_messages", [])
    assert all(r["tool"] != RESEARCH_TOOL_NAME for r in result["tool_results"])


def test_meds_dosing_fetch_hit_appends_research_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dosing + resolve OK + mock hit → research_label + Looking up label."""
    openfda_result = {
        "openfda": {
            "generic_name": ["SIMVASTATIN"],
            "brand_name": ["ZOCOR"],
            "spl_set_id": ["abc-set-id-1"],
            "product_type": ["HUMAN PRESCRIPTION DRUG"],
        },
        "dosage_and_administration": [
            "The usual dosage range is 5 to 40 mg/day."
        ],
    }

    def _fake_fetch(query: Any, *, correlation_id: str = "") -> LabelFetchResult:
        assert query.term.lower() == "simvastatin"
        assert correlation_id == "corr-hit"
        return LabelFetchResult(
            ok=True,
            source="openfda",
            set_id="abc-set-id-1",
            outcome="hit_openfda",
            openfda_result=openfda_result,
            generic_names=("SIMVASTATIN",),
            brand_names=("ZOCOR",),
        )

    monkeypatch.setattr("sidecar.app.nodes.tools.fetch_label", _fake_fetch)

    node = make_tools_node(_ok_meds_gateway())
    result = node(
        {
            "pid": 6,
            "user_id": 1,
            "correlation_id": "corr-hit",
            "route": "meds",
            "message": "What is the typical adult dose of simvastatin?",
        }
    )

    assert "error" not in result
    assert RESEARCH_PROGRESS_MESSAGE in result["progress_messages"]
    assert result["progress_messages"][0] == "Fetching chart…"
    research = [r for r in result["tool_results"] if r["tool"] == RESEARCH_TOOL_NAME]
    assert len(research) == 1
    assert research[0]["ok"] is True
    assert research[0]["data"]["facts"]
    assert research[0]["data"]["meta"]["source"] == "openfda"
    assert research[0]["data"]["meta"]["on_chart"] is True
    chart_meds = [r for r in result["tool_results"] if r["tool"] == "meds"]
    assert len(chart_meds) == 1


def test_meds_dosing_fetch_raises_keeps_chart_no_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H8: fetch exception → chart meds kept; research never sets error."""

    def _boom(*_a: Any, **_kw: Any) -> LabelFetchResult:
        raise RuntimeError("simulated research failure")

    monkeypatch.setattr("sidecar.app.nodes.tools.fetch_label", _boom)

    node = make_tools_node(_ok_meds_gateway())
    result = node(
        {
            "pid": 6,
            "user_id": 1,
            "correlation_id": "corr-raise",
            "route": "meds",
            "message": "What is the typical adult dose of simvastatin?",
        }
    )

    assert "error" not in result
    # Progress was added before HTTP; exception skips research facts only.
    assert RESEARCH_PROGRESS_MESSAGE in result["progress_messages"]
    tools = [r["tool"] for r in result["tool_results"]]
    assert "meds" in tools
    assert RESEARCH_TOOL_NAME not in tools
