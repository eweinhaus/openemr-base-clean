"""Server-Sent Events framing (PRD 02 contract)."""

from __future__ import annotations

import json
from typing import Any


def format_sse(event: str, data: dict[str, Any]) -> str:
    """Format one SSE frame: event line + JSON data line + blank line."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"
