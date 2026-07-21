"""Shared-secret authentication for internal gateway → sidecar hops."""

from __future__ import annotations

import hmac

SECRET_HEADER = "X-Copilot-Internal-Secret"
CORRELATION_HEADER = "X-Correlation-Id"


def verify_secret(provided: str | None, expected: str) -> bool:
    """Constant-time compare of the internal secret header value."""
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)
