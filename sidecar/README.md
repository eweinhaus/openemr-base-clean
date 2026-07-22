# Copilot LangGraph sidecar (PRD 03–07)

FastAPI + uvicorn service running the Clinical Co-Pilot agent graph
(refuse → route → tools → draft → verify → emit). Validates
`COPILOT_INTERNAL_SECRET`, exposes `/health`, soft `/ready`, and `/v1/chat`
which streams hybrid SSE (`progress` → verified `clinical` → `citation` →
`done` | `error`).

Route classification and claim drafting call OpenRouter (Haiku, temperature 0).
Chart facts come from the OpenEMR gateway `tool_proxy.php` (PRD 04). On
`meds` + dosing-like turns, the tools node may append sidecar-only label
research (openFDA → DailyMed; PRD 05) — never via `tool_proxy`. Verification
is deterministic: claims must cite a locator from this turn's tools, and the
shipped text is the tool fact prose. `source_type` stays `chart` / `note` /
`research`. Canonical `no_research` is appended only when the ask is
dosing-like and no verified research dosing fact survived.

Optional **LangSmith** (PRD 07): env-gated redacted traces of the LangGraph
run. **LangGraph ≠ LangSmith** — Graph is the agent workflow; Smith is the
tracer. When `LANGSMITH_TRACING` is on, the process forces
`LANGSMITH_HIDE_INPUTS` / `LANGSMITH_HIDE_OUTPUTS` so GraphState PHI is not
shipped. Run metadata carries `correlation_id` only (no `pid` / message).
Missing or unreachable LangSmith does **not** flip `/ready` to false; when
hard deps fail, `/v1/chat` immediately SSE-errors with `sidecar_unready`
(no graph / LLM).

## Layout

```
sidecar/
  Dockerfile
  requirements.txt
  app/
    main.py            # FastAPI routes: /health, /ready, /v1/chat
    auth.py            # shared-secret compare
    sse.py             # SSE framing
    stream.py          # run graph → yield SSE events
    tracing.py         # LangSmith hide policy + soft /ready probe
    graph.py           # LangGraph assembly
    state.py           # GraphState + shared messages/limits
    llm.py             # OpenRouter Haiku route/draft helpers
    claims.py          # claim schema, parse, verify, assemble
    gateway_client.py  # HTTP client → tool_proxy.php
    research/          # openFDA → DailyMed (PRD 05; scrubbed DrugQuery only)
    nodes/             # refuse, route, tools, draft, verify, emit
  tests/
```

## Run locally

From repo root (install deps once):

```bash
cd sidecar
pip install -r requirements.txt
export COPILOT_INTERNAL_SECRET=dev-secret-change-me
export OPENROUTER_API_KEY=sk-or-...   # required for live route/draft turns
uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1
```

Or from `sidecar/` with module path:

```bash
export COPILOT_INTERNAL_SECRET=dev-secret-change-me
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1
```

Health:

```bash
curl -s http://127.0.0.1:8080/health
```

Ready (soft — always HTTP 200; `ready: false` when the gateway is unreachable
**or `OPENROUTER_API_KEY` is missing**). OpenRouter `/models` reachability and
LangSmith appear as soft fields (`openrouter.reachable`, `langsmith`) and never
alone flip `ready`. `/ready` does **not** probe openFDA/DailyMed. `/v1/chat`
reuses a short TTL readiness cache (`COPILOT_READY_CACHE_TTL_SECONDS`, default
30s); `/ready` always probes fresh.

```bash
curl -s http://127.0.0.1:8080/ready
```

Chat (SSE):

```bash
curl -N -X POST http://127.0.0.1:8080/v1/chat \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-Copilot-Internal-Secret: dev-secret-change-me" \
  -H "X-Correlation-Id: abc123" \
  -d '{
    "correlation_id": "abc123",
    "user_id": 1,
    "username": "admin",
    "pid": 6,
    "message": "Show recent labs",
    "transcript": []
  }'
```

Wrong secret → `401` with `{"error":"unauthorized"}`. Unbound pid → clinical
refusal text. Empty or >4000-char message → SSE `error` frame. When
`ready=false` → SSE `error` with `code=sidecar_unready` (no clinical).

## Docker

```bash
docker build -t copilot-sidecar sidecar/
docker run --rm -e COPILOT_INTERNAL_SECRET=dev-secret-change-me -p 8080:8080 copilot-sidecar
```

Compose service `copilot-sidecar` in `docker/development-easy/docker-compose.yml`
and `docker/production/docker-compose.yml` (**no host ports** in compose; both
pass the full env below). Healthcheck stays on **`/health` only** (never
`/ready`) so OpenRouter blips do not restart the sidecar.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `COPILOT_INTERNAL_SECRET` | *(required)* | Shared with OpenEMR gateway |
| `COPILOT_GATEWAY_TOOL_URL` | `http://openemr/interface/ask_copilot/tool_proxy.php` | Chart tool proxy |
| `COPILOT_GATEWAY_DISCLOSURE_URL` | `http://openemr/interface/ask_copilot/disclosure.php` (or derived from tool URL) | Best-effort verify disclosure callback |
| `OPENROUTER_API_KEY` | empty | Required for live route/draft (missing → `/ready` false, turns error) |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API base |
| `OPENROUTER_MODEL` | `anthropic/claude-haiku-4.5` | Pinned Haiku id |
| `OPENFDA_API_KEY` | empty | Optional openFDA key (higher rate limits); `/ready` does **not** probe FDA |
| `COPILOT_LLM_TIMEOUT_SECONDS` | `30` | Per-LLM-call budget (route and draft each) |
| `COPILOT_TOOL_TIMEOUT_SECONDS` | `10` | Gateway tool / probe budget |
| `COPILOT_READY_CACHE_TTL_SECONDS` | `30` | Cache `/v1/chat` readiness probes; `/ready` always fresh |
| `LANGSMITH_TRACING` | `false` | Enable LangSmith tracing when key is set |
| `LANGSMITH_API_KEY` | empty | Optional; chat works without it (silent disable) |
| `LANGSMITH_PROJECT` | `openemr-copilot-demo` | LangSmith project name |
| `LANGSMITH_HIDE_INPUTS` | `true` | Redact trace inputs (forced at startup if tracing on) |
| `LANGSMITH_HIDE_OUTPUTS` | `true` | Redact trace outputs (forced at startup if tracing on) |

OpenEMR container (not sidecar): `COPILOT_SIDECAR_URL`,
`COPILOT_GATEWAY_TIMEOUT_SECONDS` (default 120 — must cover route + draft +
tools for one turn).

## Observability join (interview)

Same `correlation_id` joins the app disclosure JSONL (`ask_start` /
`tool_proxy` / `verify`) to a redacted LangSmith run. The EHR boundary audit
is **not** outsourced to the tracer — LangSmith does not replace
`DisclosureLog`.

### Alert definition stubs (not wired)

| Alert | Meaning | On-call response (demo) |
| --- | --- | --- |
| p95 latency > threshold | Physician waits too long | Check OpenRouter/gateway; reduce brief tool work; note single-worker limit |
| Error rate > threshold | Elevated SSE `error` | Check `/ready`, keys, disclosure/tool_proxy logs by `correlation_id` |
| Tool failure rate > threshold | Chart proxy / bind failures | Check secret, bind TTL, pid mismatch lines in disclosure JSONL |

## Tests

From repo root (host Python 3.11+):

```bash
pip install -r sidecar/requirements.txt pytest
export COPILOT_INTERNAL_SECRET=test-secret
pytest sidecar/tests/ -q
```
