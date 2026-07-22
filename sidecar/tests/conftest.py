"""Pytest configuration for sidecar tests."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("COPILOT_INTERNAL_SECRET", "test-secret-for-pytest")


@pytest.fixture(autouse=True)
def _clear_ready_cache() -> None:
    """Avoid readiness cache leaking across TestClient chat/ready cases."""
    from sidecar.app.main import clear_ready_cache

    clear_ready_cache()
    yield
    clear_ready_cache()
