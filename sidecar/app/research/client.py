"""openFDA → DailyMed label HTTP client (PRD 05 H3/H8/H9/H13)."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .constants import (
    DAILYMED_BASE_URL,
    HTTP_DEADLINE_SECONDS,
    OPENFDA_LABEL_URL,
    TABLE_DAILYMED,
    TABLE_OPENFDA,
)
from .resolve import DrugQuery
from .scrub import scrub_query_term

logger = logging.getLogger(__name__)

_OUTCOME_HIT_OPENFDA = "hit_openfda"
_OUTCOME_HIT_DAILYMED = "hit_dailymed"
_OUTCOME_MISS = "miss"
_OUTCOME_TIMEOUT = "timeout"


@dataclass(frozen=True)
class LabelFetchResult:
    """Raw-ish label payload for extract; never raises to the caller."""

    ok: bool
    source: str | None  # "openfda" | "dailymed"
    set_id: str | None
    outcome: str  # hit_openfda | hit_dailymed | miss | timeout
    openfda_result: dict[str, Any] | None = None
    dailymed_xml: str | None = None
    generic_names: tuple[str, ...] = ()
    brand_names: tuple[str, ...] = ()


def fetch_label(
    query: DrugQuery,
    *,
    correlation_id: str = "",
    client: httpx.Client | None = None,
    api_key: str | None = None,
    deadline_seconds: float | None = None,
) -> LabelFetchResult:
    """Fetch one label via openFDA then DailyMed fallback.

    Builds the outbound query from ``DrugQuery`` only (H3). Network/HTTP
    failures become a miss result — never raised (H8). Zero retries on
    429/5xx (H9). Logs correlation_id + outcome + set_id only (H13).
    """
    if query.blocked:
        return _finish(
            LabelFetchResult(
                ok=False,
                source=None,
                set_id=None,
                outcome=_OUTCOME_MISS,
            ),
            correlation_id=correlation_id,
        )

    deadline = (
        HTTP_DEADLINE_SECONDS if deadline_seconds is None else float(deadline_seconds)
    )
    key = api_key if api_key is not None else os.environ.get("OPENFDA_API_KEY")
    start = time.monotonic()
    owns_client = client is None
    http = client or httpx.Client()

    try:
        openfda = _try_openfda(
            http,
            query,
            api_key=key,
            start=start,
            deadline=deadline,
        )
        if openfda is not None and openfda.ok:
            return _finish(openfda, correlation_id=correlation_id)

        if openfda is not None and openfda.outcome == _OUTCOME_TIMEOUT:
            remaining = _remaining(start, deadline)
            if remaining <= 0:
                return _finish(openfda, correlation_id=correlation_id)

        dailymed = _try_dailymed(
            http,
            query,
            start=start,
            deadline=deadline,
        )
        if dailymed is not None:
            return _finish(dailymed, correlation_id=correlation_id)

        # Prefer timeout outcome when the shared deadline was the cause.
        if openfda is not None and openfda.outcome == _OUTCOME_TIMEOUT:
            return _finish(openfda, correlation_id=correlation_id)
        if _remaining(start, deadline) <= 0:
            return _finish(
                LabelFetchResult(
                    ok=False,
                    source=None,
                    set_id=None,
                    outcome=_OUTCOME_TIMEOUT,
                ),
                correlation_id=correlation_id,
            )
        return _finish(
            LabelFetchResult(
                ok=False,
                source=None,
                set_id=None,
                outcome=_OUTCOME_MISS,
            ),
            correlation_id=correlation_id,
        )
    except Exception:
        # Belt-and-suspenders: never raise to caller (H8).
        return _finish(
            LabelFetchResult(
                ok=False,
                source=None,
                set_id=None,
                outcome=_OUTCOME_MISS,
            ),
            correlation_id=correlation_id,
        )
    finally:
        if owns_client:
            http.close()


def _try_openfda(
    http: httpx.Client,
    query: DrugQuery,
    *,
    api_key: str | None,
    start: float,
    deadline: float,
) -> LabelFetchResult | None:
    """Attempt openFDA: rxcui first (if any), then scrubbed term on 404/miss."""
    searches: list[str] = []
    if query.rxcui and query.rxcui.isdigit():
        searches.append(f'openfda.rxcui:"{query.rxcui}"')

    term = scrub_query_term(query.term) if query.term else None
    if term:
        searches.append(f'openfda.generic_name:"{term}"')

    if not searches:
        return None

    last_timeout = False
    for search in searches:
        remaining = _remaining(start, deadline)
        if remaining <= 0:
            last_timeout = True
            break

        status, payload, timed_out = _get_json(
            http,
            OPENFDA_LABEL_URL,
            params=_openfda_params(search, api_key),
            timeout=remaining,
        )
        if timed_out:
            last_timeout = True
            break

        if status is None:
            # Network error — treat as miss for this query; try next / DailyMed.
            continue

        # 404 / empty → try next search (rxcui then term). No retry of same URL (H9).
        if status == 404 or (status == 200 and _empty_openfda(payload)):
            continue

        # 400 / 429 / 5xx → stop openFDA entirely; DailyMed may still run.
        if status in (400, 429) or (status is not None and status >= 500):
            return None

        if status != 200 or not isinstance(payload, dict):
            continue

        result = _first_openfda_result(payload)
        if result is None:
            continue

        set_id = _openfda_set_id(result)
        generics, brands = _openfda_names(result)
        return LabelFetchResult(
            ok=True,
            source=TABLE_OPENFDA,
            set_id=set_id,
            outcome=_OUTCOME_HIT_OPENFDA,
            openfda_result=result,
            generic_names=generics,
            brand_names=brands,
        )

    if last_timeout:
        return LabelFetchResult(
            ok=False,
            source=None,
            set_id=None,
            outcome=_OUTCOME_TIMEOUT,
        )
    return None


def _try_dailymed(
    http: httpx.Client,
    query: DrugQuery,
    *,
    start: float,
    deadline: float,
) -> LabelFetchResult | None:
    """One DailyMed search + one XML fetch (single source attempt, H9)."""
    term = scrub_query_term(query.term) if query.term else None
    if not term:
        return None

    remaining = _remaining(start, deadline)
    if remaining <= 0:
        return LabelFetchResult(
            ok=False,
            source=None,
            set_id=None,
            outcome=_OUTCOME_TIMEOUT,
        )

    search_url = f"{DAILYMED_BASE_URL}/spls.json"
    status, payload, timed_out = _get_json(
        http,
        search_url,
        params={"drug_name": term},
        timeout=remaining,
    )
    if timed_out:
        return LabelFetchResult(
            ok=False,
            source=None,
            set_id=None,
            outcome=_OUTCOME_TIMEOUT,
        )
    if status != 200 or not isinstance(payload, dict):
        return None

    set_id = _first_dailymed_setid(payload)
    if not set_id:
        return None

    remaining = _remaining(start, deadline)
    if remaining <= 0:
        return LabelFetchResult(
            ok=False,
            source=None,
            set_id=None,
            outcome=_OUTCOME_TIMEOUT,
        )

    xml_url = f"{DAILYMED_BASE_URL}/spls/{quote(set_id, safe='')}.xml"
    xml_status, xml_text, xml_timed_out = _get_text(
        http,
        xml_url,
        timeout=remaining,
    )
    if xml_timed_out:
        return LabelFetchResult(
            ok=False,
            source=None,
            set_id=None,
            outcome=_OUTCOME_TIMEOUT,
        )
    if xml_status != 200 or not xml_text:
        return None

    return LabelFetchResult(
        ok=True,
        source=TABLE_DAILYMED,
        set_id=set_id,
        outcome=_OUTCOME_HIT_DAILYMED,
        dailymed_xml=xml_text,
    )


def _openfda_params(search: str, api_key: str | None) -> dict[str, str]:
    params: dict[str, str] = {
        "search": search,
        "sort": "effective_time:desc",
        "limit": "1",
    }
    if api_key:
        params["api_key"] = api_key
    return params


def _get_json(
    http: httpx.Client,
    url: str,
    *,
    params: dict[str, str],
    timeout: float,
) -> tuple[int | None, Any, bool]:
    """Return (status, json_or_None, timed_out). Never raises."""
    try:
        response = http.get(url, params=params, timeout=timeout)
    except httpx.TimeoutException:
        return None, None, True
    except httpx.HTTPError:
        return None, None, False

    try:
        payload: Any = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload, False


def _get_text(
    http: httpx.Client,
    url: str,
    *,
    timeout: float,
) -> tuple[int | None, str | None, bool]:
    """Return (status, text_or_None, timed_out). Never raises."""
    try:
        response = http.get(url, timeout=timeout)
    except httpx.TimeoutException:
        return None, None, True
    except httpx.HTTPError:
        return None, None, False

    text = response.text
    return response.status_code, text if text else None, False


def _first_openfda_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    return first if isinstance(first, dict) else None


def _empty_openfda(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return True
    return _first_openfda_result(payload) is None


def _openfda_set_id(result: dict[str, Any]) -> str | None:
    openfda = result.get("openfda")
    if not isinstance(openfda, dict):
        return None
    set_ids = openfda.get("spl_set_id")
    if isinstance(set_ids, list) and set_ids:
        value = set_ids[0]
        return str(value) if value is not None else None
    if isinstance(set_ids, str) and set_ids:
        return set_ids
    return None


def _openfda_names(result: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    openfda = result.get("openfda")
    if not isinstance(openfda, dict):
        return (), ()
    return (
        _as_name_tuple(openfda.get("generic_name")),
        _as_name_tuple(openfda.get("brand_name")),
    )


def _as_name_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                names.append(item.strip())
        return tuple(names)
    return ()


def _first_dailymed_setid(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    if not isinstance(data, list):
        return None
    for item in data:
        if not isinstance(item, dict):
            continue
        set_id = item.get("setid") or item.get("set_id")
        if isinstance(set_id, str) and set_id.strip():
            return set_id.strip()
    return None


def _remaining(start: float, deadline: float) -> float:
    return max(0.0, deadline - (time.monotonic() - start))


def _finish(result: LabelFetchResult, *, correlation_id: str) -> LabelFetchResult:
    logger.info(
        "research_label",
        extra={
            "correlation_id": correlation_id,
            "outcome": result.outcome,
            "set_id": result.set_id,
        },
    )
    return result
