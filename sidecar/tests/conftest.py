"""Pytest configuration for sidecar tests."""

from __future__ import annotations

import os

os.environ.setdefault("COPILOT_INTERNAL_SECRET", "test-secret-for-pytest")
