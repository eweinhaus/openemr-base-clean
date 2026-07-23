"""Process-local TTL cache for prefetched UC-1 brief payloads (PRD 09)."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_BRIEF_CACHE_TTL_SECONDS = 1800.0
DEFAULT_BRIEF_CACHE_SCHEMA_VERSION = 1

CacheKey = Tuple[int, int, int]


@dataclass(frozen=True)
class BriefCacheSettings:
    ttl_seconds: float
    default_schema_version: int


def load_brief_cache_settings() -> BriefCacheSettings:
    ttl_raw = os.environ.get(
        "COPILOT_BRIEF_CACHE_TTL_SECONDS",
        str(DEFAULT_BRIEF_CACHE_TTL_SECONDS),
    )
    schema_raw = os.environ.get(
        "COPILOT_BRIEF_CACHE_SCHEMA_VERSION",
        str(DEFAULT_BRIEF_CACHE_SCHEMA_VERSION),
    )
    return BriefCacheSettings(
        ttl_seconds=max(0.0, float(ttl_raw)),
        default_schema_version=int(schema_raw),
    )


def _cache_key(user_id: int, pid: int, schema_version: int) -> CacheKey:
    return (user_id, pid, schema_version)


def is_stale(entry: Dict[str, Any], soft_seconds: float) -> bool:
    """Return True when entry age exceeds soft refresh threshold."""
    created_at = float(entry["created_at"])
    age = time.monotonic() - created_at
    return age > max(0.0, float(soft_seconds))


class BriefCache:
    """Thread-safe in-memory brief cache keyed by (user_id, pid, schema_version)."""

    def __init__(
        self,
        settings: BriefCacheSettings | None = None,
    ) -> None:
        self._settings = settings or load_brief_cache_settings()
        self._entries: Dict[CacheKey, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    @property
    def default_schema_version(self) -> int:
        return self._settings.default_schema_version

    def get(
        self,
        user_id: int,
        pid: int,
        schema_version: int | None = None,
    ) -> Optional[Dict[str, Any]]:
        version = (
            self._settings.default_schema_version
            if schema_version is None
            else schema_version
        )
        key = _cache_key(user_id, pid, version)
        now = time.monotonic()

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if now >= float(entry["expires_at"]):
                del self._entries[key]
                return None
            return dict(entry)

    def put(
        self,
        user_id: int,
        pid: int,
        *,
        correlation_id: str,
        clinical_text: str,
        clinical_segments: List[Any],
        citations: List[Any],
        schema_version: int | None = None,
    ) -> Dict[str, Any]:
        version = (
            self._settings.default_schema_version
            if schema_version is None
            else schema_version
        )
        now = time.monotonic()
        ttl = max(0.0, float(self._settings.ttl_seconds))
        entry: Dict[str, Any] = {
            "user_id": user_id,
            "pid": pid,
            "schema_version": version,
            "created_at": now,
            "expires_at": now + ttl,
            "correlation_id": correlation_id,
            "clinical_text": clinical_text,
            "clinical_segments": list(clinical_segments),
            "citations": list(citations),
        }
        key = _cache_key(user_id, pid, version)

        with self._lock:
            self._entries[key] = entry

        return dict(entry)

    def delete(
        self,
        user_id: int,
        pid: int,
        schema_version: int | None = None,
    ) -> bool:
        version = (
            self._settings.default_schema_version
            if schema_version is None
            else schema_version
        )
        key = _cache_key(user_id, pid, version)

        with self._lock:
            if key not in self._entries:
                return False
            del self._entries[key]
            return True

    def prune_expired(self) -> int:
        now = time.monotonic()
        removed = 0

        with self._lock:
            stale_keys = [
                key
                for key, entry in self._entries.items()
                if now >= float(entry["expires_at"])
            ]
            for key in stale_keys:
                del self._entries[key]
                removed += 1

        return removed

    def clear(self) -> None:
        """Test helper — drop all cached brief entries."""
        with self._lock:
            self._entries.clear()


_brief_cache: BriefCache | None = None
_brief_cache_lock = threading.Lock()


def get_brief_cache() -> BriefCache:
    """Return the process-local brief cache singleton."""
    global _brief_cache
    if _brief_cache is not None:
        return _brief_cache

    with _brief_cache_lock:
        if _brief_cache is None:
            _brief_cache = BriefCache()
        return _brief_cache


def clear_brief_cache() -> None:
    """Test helper — reset the process-local brief cache singleton."""
    global _brief_cache
    with _brief_cache_lock:
        if _brief_cache is not None:
            _brief_cache.clear()
        _brief_cache = None
