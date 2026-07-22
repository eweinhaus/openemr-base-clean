"""Unit tests for openFDA → DailyMed research client (PRD 05 H3/H8/H9/H13)."""

from __future__ import annotations

import inspect
from typing import Any

import httpx
import pytest

from sidecar.app.research.client import LabelFetchResult, fetch_label
from sidecar.app.research.resolve import DrugQuery


def _query(
    *,
    term: str = "simvastatin",
    rxcui: str | None = None,
    blocked: bool = False,
    on_chart: bool = True,
) -> DrugQuery:
    return DrugQuery(
        term=term,
        rxcui=rxcui,
        on_chart=on_chart,
        blocked=blocked,
        display_name=term,
        matched_fact_id=None,
    )


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _openfda_hit_body() -> dict[str, Any]:
    return {
        "results": [
            {
                "openfda": {
                    "generic_name": ["SIMVASTATIN"],
                    "brand_name": ["ZOCOR"],
                    "spl_set_id": ["abc-set-id-1"],
                    "rxcui": ["312961"],
                },
                "dosage_and_administration": [
                    "The usual dosage range is 5 to 40 mg/day."
                ],
            }
        ]
    }


def test_fetch_label_signature_has_no_message_parameter() -> None:
    params = inspect.signature(fetch_label).parameters
    assert "message" not in params
    assert "query" in params


def test_blocked_query_makes_zero_http_calls() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500, json={"error": "should not be called"})

    result = fetch_label(
        _query(blocked=True),
        client=_client(handler),
        correlation_id="corr-blocked",
    )
    assert result.ok is False
    assert result.outcome == "miss"
    assert result.source is None
    assert calls == []


def test_openfda_404_miss_single_call_no_retry() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        host = request.url.host or ""
        if "api.fda.gov" in host:
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
        # DailyMed also misses — focus is openFDA not retried.
        return httpx.Response(404, json={"data": []})

    result = fetch_label(
        _query(term="simvastatin", rxcui=None),
        client=_client(handler),
    )
    assert result.ok is False
    assert result.outcome == "miss"
    openfda_calls = [c for c in calls if "api.fda.gov" in (c.url.host or "")]
    assert len(openfda_calls) == 1


def test_openfda_timeout_miss_no_retry() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("timed out")

    result = fetch_label(
        _query(term="simvastatin", rxcui=None),
        client=_client(handler),
        deadline_seconds=1.0,
    )
    assert result.ok is False
    assert result.outcome == "timeout"
    openfda_calls = [c for c in calls if "api.fda.gov" in (c.url.host or "")]
    assert len(openfda_calls) == 1


def test_openfda_429_miss_single_call_no_retry() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        host = request.url.host or ""
        if "api.fda.gov" in host:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(404, json={"data": []})

    result = fetch_label(
        _query(term="simvastatin", rxcui=None),
        client=_client(handler),
    )
    assert result.ok is False
    assert result.outcome == "miss"
    openfda_calls = [c for c in calls if "api.fda.gov" in (c.url.host or "")]
    assert len(openfda_calls) == 1


def test_openfda_5xx_miss_single_call_no_retry() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        host = request.url.host or ""
        if "api.fda.gov" in host:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(404, json={"data": []})

    result = fetch_label(
        _query(term="simvastatin", rxcui=None),
        client=_client(handler),
    )
    assert result.ok is False
    openfda_calls = [c for c in calls if "api.fda.gov" in (c.url.host or "")]
    assert len(openfda_calls) == 1


def test_openfda_happy_path_extracts_names_and_set_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.fda.gov" in (request.url.host or "")
        assert "sort=effective_time%3Adesc" in str(request.url) or (
            request.url.params.get("sort") == "effective_time:desc"
        )
        assert request.url.params.get("limit") == "1"
        search = request.url.params.get("search", "")
        assert "simvastatin" in search.lower() or "312961" in search
        return httpx.Response(200, json=_openfda_hit_body())

    result = fetch_label(
        _query(term="simvastatin", rxcui="312961"),
        client=_client(handler),
        correlation_id="corr-hit",
    )
    assert result.ok is True
    assert result.source == "openfda"
    assert result.outcome == "hit_openfda"
    assert result.set_id == "abc-set-id-1"
    assert result.generic_names == ("SIMVASTATIN",)
    assert result.brand_names == ("ZOCOR",)
    assert result.openfda_result is not None
    assert "dosage_and_administration" in result.openfda_result
    assert result.dailymed_xml is None


def test_openfda_miss_then_dailymed_hit() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        host = request.url.host or ""
        path = request.url.path

        if "api.fda.gov" in host:
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})

        if path.endswith("/spls.json"):
            return httpx.Response(
                200,
                json={"data": [{"setid": "dm-set-99", "title": "SIMVASTATIN"}]},
            )

        if "/spls/" in path and path.endswith(".xml"):
            assert "dm-set-99" in path
            return httpx.Response(
                200,
                text="<document><title>SIMVASTATIN</title></document>",
            )

        return httpx.Response(500, text="unexpected")

    result = fetch_label(
        _query(term="simvastatin", rxcui=None),
        client=_client(handler),
    )
    assert result.ok is True
    assert result.source == "dailymed"
    assert result.outcome == "hit_dailymed"
    assert result.set_id == "dm-set-99"
    assert result.dailymed_xml is not None
    assert "SIMVASTATIN" in result.dailymed_xml
    assert result.openfda_result is None

    openfda_calls = [u for u in calls if "api.fda.gov" in u]
    dailymed_json = [u for u in calls if "spls.json" in u]
    dailymed_xml = [u for u in calls if ".xml" in u]
    assert len(openfda_calls) == 1
    assert len(dailymed_json) == 1
    assert len(dailymed_xml) == 1


def test_rxcui_404_falls_back_to_generic_term_on_openfda() -> None:
    searches: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.fda.gov" not in (request.url.host or ""):
            return httpx.Response(404, json={"data": []})
        search = request.url.params.get("search", "")
        searches.append(search)
        if "rxcui" in search:
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
        return httpx.Response(200, json=_openfda_hit_body())

    result = fetch_label(
        _query(term="simvastatin", rxcui="312961"),
        client=_client(handler),
    )
    assert result.ok is True
    assert result.source == "openfda"
    assert len(searches) == 2
    assert "312961" in searches[0]
    assert "simvastatin" in searches[1].lower()


def test_exceptions_become_miss_never_raise() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = fetch_label(
        _query(term="simvastatin", rxcui=None),
        client=_client(handler),
    )
    assert isinstance(result, LabelFetchResult)
    assert result.ok is False
    assert result.outcome in {"miss", "timeout"}
