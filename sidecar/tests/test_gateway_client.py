"""Tests for GatewayClient tool_proxy calls."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sidecar.app.auth import CORRELATION_HEADER, SECRET_HEADER
from sidecar.app.gateway_client import (
    GatewayAuthError,
    GatewayClient,
    GatewayError,
    GatewayForbiddenError,
    GatewayNetworkError,
    GatewayTimeoutError,
)

TEST_SECRET = "test-secret-for-pytest"
TOOL_URL = "http://openemr/interface/ask_copilot/tool_proxy.php"

FACTS_PAYLOAD: dict[str, Any] = {
    "ok": True,
    "tool": "labs",
    "data": {
        "facts": [
            {
                "text": "Creatinine 1.4 mg/dL on 2026-06-01",
                "table": "procedure_result",
                "id": "42",
                "excerpt": "Latest BMP",
            }
        ]
    },
}


def _client_with_transport(handler: httpx.MockTransport) -> GatewayClient:
    return GatewayClient(
        secret=TEST_SECRET,
        tool_url=TOOL_URL,
        timeout=10.0,
        client=httpx.Client(transport=handler),
    )


def test_call_tool_returns_facts_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == TOOL_URL
        assert request.headers[SECRET_HEADER] == TEST_SECRET
        assert request.headers[CORRELATION_HEADER] == "corr-123"
        body = json.loads(request.content)
        assert body == {
            "tool": "labs",
            "args": {"limit": 5},
            "pid": 6,
            "user_id": 1,
            "correlation_id": "corr-123",
        }
        return httpx.Response(200, json=FACTS_PAYLOAD)

    client = _client_with_transport(httpx.MockTransport(handler))
    result = client.call_tool("labs", {"limit": 5}, 6, "corr-123", 1)

    assert result == FACTS_PAYLOAD


def test_call_tool_raises_gateway_auth_error_on_401() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "error": "unauthorized"})

    client = _client_with_transport(httpx.MockTransport(handler))

    with pytest.raises(GatewayAuthError):
        client.call_tool("labs", {}, 6, "corr-123", 1)


def test_call_tool_raises_gateway_forbidden_error_on_403() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"ok": False, "error": "bind_missing"})

    client = _client_with_transport(httpx.MockTransport(handler))

    with pytest.raises(GatewayForbiddenError):
        client.call_tool("labs", {}, 6, "corr-123", 1)


def test_call_tool_raises_gateway_timeout_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    client = _client_with_transport(httpx.MockTransport(handler))

    with pytest.raises(GatewayTimeoutError):
        client.call_tool("labs", {}, 6, "corr-123", 1)


def test_call_tool_raises_gateway_error_on_400() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "error": "not_implemented"})

    client = _client_with_transport(httpx.MockTransport(handler))

    with pytest.raises(GatewayError, match="not_implemented"):
        client.call_tool("unknown_tool", {}, 6, "corr-123", 1)


def test_call_tool_raises_gateway_network_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client_with_transport(httpx.MockTransport(handler))

    with pytest.raises(GatewayNetworkError):
        client.call_tool("labs", {}, 6, "corr-123", 1)


DISCLOSURE_URL = "http://openemr/interface/ask_copilot/disclosure.php"


def _disclosure_client(handler: httpx.MockTransport) -> GatewayClient:
    return GatewayClient(
        secret=TEST_SECRET,
        tool_url=TOOL_URL,
        timeout=10.0,
        disclosure_url=DISCLOSURE_URL,
        client=httpx.Client(transport=handler),
    )


def test_post_verify_disclosure_posts_expected_payload_and_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == DISCLOSURE_URL
        assert request.headers[SECRET_HEADER] == TEST_SECRET
        assert request.headers[CORRELATION_HEADER] == "corr-verify-1"
        body = json.loads(request.content)
        assert body == {
            "event": "verify",
            "correlation_id": "corr-verify-1",
            "pass": True,
            "reason": "ok",
        }
        return httpx.Response(200, json={"ok": True})

    client = _disclosure_client(httpx.MockTransport(handler))
    assert client.post_verify_disclosure(
        correlation_id="corr-verify-1",
        passed=True,
        reason="ok",
    ) is True


def test_post_verify_disclosure_derives_url_from_tool_url() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    client = GatewayClient(
        secret=TEST_SECRET,
        tool_url=TOOL_URL,
        timeout=10.0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.post_verify_disclosure(
        correlation_id="corr-d",
        passed=False,
        reason="empty_verified",
    ) is True
    assert seen == [DISCLOSURE_URL]


def test_post_verify_disclosure_returns_false_on_401_without_raising() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "error": "unauthorized"})

    client = _disclosure_client(httpx.MockTransport(handler))
    assert (
        client.post_verify_disclosure(
            correlation_id="corr-401",
            passed=True,
            reason="ok",
        )
        is False
    )


def test_post_verify_disclosure_returns_false_on_5xx_without_raising() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False, "error": "server_error"})

    client = _disclosure_client(httpx.MockTransport(handler))
    assert (
        client.post_verify_disclosure(
            correlation_id="corr-500",
            passed=False,
            reason="claims_dropped",
        )
        is False
    )


def test_post_verify_disclosure_returns_false_on_timeout_without_raising() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    client = _disclosure_client(httpx.MockTransport(handler))
    assert (
        client.post_verify_disclosure(
            correlation_id="corr-timeout",
            passed=True,
            reason="ok",
        )
        is False
    )


def test_post_verify_disclosure_returns_false_on_network_error_without_raising() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _disclosure_client(httpx.MockTransport(handler))
    assert (
        client.post_verify_disclosure(
            correlation_id="corr-net",
            passed=False,
            reason="all_refused",
        )
        is False
    )
