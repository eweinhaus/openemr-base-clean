"""HTTP client for OpenEMR tool_proxy from the LangGraph sidecar."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .auth import CORRELATION_HEADER, SECRET_HEADER

logger = logging.getLogger(__name__)

DEFAULT_GATEWAY_TOOL_URL = "http://openemr/interface/ask_copilot/tool_proxy.php"
DEFAULT_GATEWAY_DISCLOSURE_URL = (
    "http://openemr/interface/ask_copilot/disclosure.php"
)
# Disclosure is best-effort audit — keep the wait short vs chart tools.
DEFAULT_DISCLOSURE_TIMEOUT_SECONDS = 5.0


def derive_disclosure_url(tool_url: str) -> str:
    """Derive disclosure.php URL from the tool_proxy base when possible."""
    if tool_url.endswith("tool_proxy.php"):
        return tool_url[: -len("tool_proxy.php")] + "disclosure.php"
    return DEFAULT_GATEWAY_DISCLOSURE_URL


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
        disclosure_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._secret = secret
        self._tool_url = tool_url
        self._timeout = timeout
        self._disclosure_url = disclosure_url or derive_disclosure_url(tool_url)
        self._disclosure_timeout = min(timeout, DEFAULT_DISCLOSURE_TIMEOUT_SECONDS)
        self._client = client
        self._owns_client = client is None

    def call_tool(
        self,
        tool: str,
        args: dict[str, Any],
        pid: int,
        correlation_id: str,
        user_id: int,
    ) -> dict[str, Any]:
        """POST to tool_proxy with secret, correlation id, and pid/user fail-closed echo."""
        payload = {
            "tool": tool,
            "args": args,
            "pid": pid,
            "user_id": user_id,
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

    def post_verify_disclosure(
        self,
        *,
        correlation_id: str,
        passed: bool,
        reason: str,
    ) -> bool:
        """Best-effort POST of a verify disclosure line. Never raises to callers."""
        payload = {
            "event": "verify",
            "correlation_id": correlation_id,
            "pass": passed,
            "reason": reason,
        }
        headers = {
            SECRET_HEADER: self._secret,
            CORRELATION_HEADER: correlation_id,
        }

        http_client = self._client or httpx.Client(timeout=self._disclosure_timeout)
        try:
            try:
                response = http_client.post(
                    self._disclosure_url,
                    json=payload,
                    headers=headers,
                    timeout=self._disclosure_timeout,
                )
            except httpx.TimeoutException:
                logger.warning(
                    "verify disclosure timed out",
                    extra={"correlation_id": correlation_id},
                )
                return False
            except httpx.RequestError as exc:
                logger.warning(
                    "verify disclosure request failed",
                    extra={
                        "correlation_id": correlation_id,
                        "error_type": type(exc).__name__,
                    },
                )
                return False

            if response.status_code >= 400:
                logger.warning(
                    "verify disclosure rejected",
                    extra={
                        "correlation_id": correlation_id,
                        "status_code": response.status_code,
                    },
                )
                return False
            return True
        except Exception:
            logger.warning(
                "verify disclosure unexpected failure",
                extra={"correlation_id": correlation_id},
                exc_info=True,
            )
            return False
        finally:
            if self._owns_client and self._client is None:
                http_client.close()
