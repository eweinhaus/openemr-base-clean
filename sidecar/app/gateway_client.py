"""HTTP client for OpenEMR tool_proxy from the LangGraph sidecar."""

from __future__ import annotations

from typing import Any

import httpx

from .auth import CORRELATION_HEADER, SECRET_HEADER

DEFAULT_GATEWAY_TOOL_URL = "http://openemr/interface/ask_copilot/tool_proxy.php"


class GatewayError(Exception):
    """Base class for gateway client failures."""


class GatewayAuthError(GatewayError):
    """tool_proxy rejected the internal secret (HTTP 401)."""


class GatewayForbiddenError(GatewayError):
    """tool_proxy rejected pid/correlation bind (HTTP 403)."""


class GatewayServerError(GatewayError):
    """tool_proxy or upstream gateway returned HTTP 5xx."""


class GatewayTimeoutError(GatewayError):
    """tool_proxy request exceeded the configured timeout."""


class GatewayNetworkError(GatewayError):
    """tool_proxy could not be reached (connection/DNS/TLS failure)."""


class GatewayClient:
    """Calls OpenEMR chart tools via the internal tool_proxy endpoint."""

    def __init__(
        self,
        *,
        secret: str,
        tool_url: str,
        timeout: float,
        client: httpx.Client | None = None,
    ) -> None:
        self._secret = secret
        self._tool_url = tool_url
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    def call_tool(
        self,
        tool: str,
        args: dict[str, Any],
        pid: int,
        correlation_id: str,
    ) -> dict[str, Any]:
        """POST to tool_proxy with secret, correlation id, and pid fail-closed echo."""
        payload = {
            "tool": tool,
            "args": args,
            "pid": pid,
            "correlation_id": correlation_id,
        }
        headers = {
            SECRET_HEADER: self._secret,
            CORRELATION_HEADER: correlation_id,
        }

        http_client = self._client or httpx.Client(timeout=self._timeout)
        try:
            response = http_client.post(
                self._tool_url,
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise GatewayTimeoutError("tool_proxy request timed out") from exc
        except httpx.RequestError as exc:
            raise GatewayNetworkError("tool_proxy request failed") from exc
        finally:
            if self._owns_client and self._client is None:
                http_client.close()

        if response.status_code == 401:
            raise GatewayAuthError("tool_proxy unauthorized")
        if response.status_code == 403:
            raise GatewayForbiddenError("tool_proxy forbidden")
        if response.status_code >= 500:
            raise GatewayServerError(
                f"tool_proxy server error ({response.status_code})"
            )

        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise GatewayServerError("tool_proxy returned invalid JSON") from exc

        if response.status_code >= 400:
            error = body.get("error", "tool_proxy request failed")
            raise GatewayError(f"tool_proxy error: {error}")

        return body
