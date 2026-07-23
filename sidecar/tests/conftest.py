"""Pytest configuration for sidecar tests."""

from __future__ import annotations

import os

import pytest

# Align with docs/local-demo-success-criteria.md §9 (T-1): same env var as runtime.
os.environ.setdefault("COPILOT_INTERNAL_SECRET", "test-secret")

TEST_SECRET = os.environ["COPILOT_INTERNAL_SECRET"]


@pytest.fixture(autouse=True)
def _clear_ready_cache() -> None:
    """Avoid readiness cache leaking across TestClient chat/ready cases."""
    from sidecar.app.main import clear_ready_cache

    clear_ready_cache()
    yield
    clear_ready_cache()
