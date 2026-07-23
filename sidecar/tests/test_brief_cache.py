"""Tests for PRD 09 Wave 1 brief in-memory cache."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from sidecar.app.brief_cache import BriefCache, BriefCacheSettings, is_stale


def _sample_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "correlation_id": "corr-abc",
        "clinical_text": "Brief summary text.",
        "clinical_segments": [{"kind": "summary", "text": "Brief summary text."}],
        "citations": [{"id": "c1", "label": "Chart note"}],
    }
    base.update(overrides)
    return base


def test_put_get_hit_within_ttl() -> None:
    cache = BriefCache(BriefCacheSettings(ttl_seconds=60.0, default_schema_version=1))

    cache.put(user_id=10, pid=6, **_sample_payload())
    entry = cache.get(user_id=10, pid=6)

    assert entry is not None
    assert entry["user_id"] == 10
    assert entry["pid"] == 6
    assert entry["schema_version"] == 1
    assert entry["correlation_id"] == "corr-abc"
    assert entry["clinical_text"] == "Brief summary text."
    assert entry["clinical_segments"] == [
        {"kind": "summary", "text": "Brief summary text."}
    ]
    assert entry["citations"] == [{"id": "c1", "label": "Chart note"}]
    assert entry["expires_at"] > entry["created_at"]


def test_get_miss_after_expiry() -> None:
    cache = BriefCache(BriefCacheSettings(ttl_seconds=5.0, default_schema_version=1))
    cache.put(user_id=10, pid=6, **_sample_payload())

    with patch("sidecar.app.brief_cache.time.monotonic", return_value=1000.0):
        cache.put(user_id=10, pid=6, **_sample_payload())

    with patch("sidecar.app.brief_cache.time.monotonic", return_value=1006.0):
        assert cache.get(user_id=10, pid=6) is None


def test_user_id_isolation_same_pid_different_users() -> None:
    cache = BriefCache(BriefCacheSettings(ttl_seconds=60.0, default_schema_version=1))

    cache.put(user_id=10, pid=6, **_sample_payload(correlation_id="user-10"))
    assert cache.get(user_id=11, pid=6) is None
    assert cache.get(user_id=10, pid=6) is not None


def test_schema_version_mismatch_is_miss() -> None:
    cache = BriefCache(BriefCacheSettings(ttl_seconds=60.0, default_schema_version=1))

    cache.put(user_id=10, pid=6, **_sample_payload(), schema_version=1)
    assert cache.get(user_id=10, pid=6, schema_version=2) is None
    assert cache.get(user_id=10, pid=6, schema_version=1) is not None


def test_prune_expired_removes_stale_entries() -> None:
    cache = BriefCache(BriefCacheSettings(ttl_seconds=5.0, default_schema_version=1))

    with patch("sidecar.app.brief_cache.time.monotonic", return_value=1000.0):
        cache.put(user_id=10, pid=6, **_sample_payload())
        cache.put(user_id=10, pid=8, **_sample_payload(correlation_id="corr-8"))

    with patch("sidecar.app.brief_cache.time.monotonic", return_value=1003.0):
        cache.put(user_id=10, pid=2, **_sample_payload(correlation_id="corr-2"))

    with patch("sidecar.app.brief_cache.time.monotonic", return_value=1006.0):
        removed = cache.prune_expired()

    assert removed == 2
    assert cache.get(user_id=10, pid=6) is None
    assert cache.get(user_id=10, pid=8) is None
    assert cache.get(user_id=10, pid=2) is not None


def test_delete_removes_entry() -> None:
    cache = BriefCache(BriefCacheSettings(ttl_seconds=60.0, default_schema_version=1))
    cache.put(user_id=10, pid=6, **_sample_payload())

    assert cache.delete(user_id=10, pid=6) is True
    assert cache.get(user_id=10, pid=6) is None
    assert cache.delete(user_id=10, pid=6) is False


def test_is_stale_when_age_exceeds_soft_seconds() -> None:
    entry = {"created_at": 1000.0}

    with patch("sidecar.app.brief_cache.time.monotonic", return_value=1601.0):
        assert is_stale(entry, soft_seconds=600.0) is True

    with patch("sidecar.app.brief_cache.time.monotonic", return_value=1599.0):
        assert is_stale(entry, soft_seconds=600.0) is False


def test_clear_drops_all_entries() -> None:
    cache = BriefCache(BriefCacheSettings(ttl_seconds=60.0, default_schema_version=1))
    cache.put(user_id=10, pid=6, **_sample_payload())
    cache.put(user_id=10, pid=8, **_sample_payload(correlation_id="corr-8"))

    cache.clear()
    assert cache.get(user_id=10, pid=6) is None
    assert cache.get(user_id=10, pid=8) is None
