# Copilot LangGraph sidecar (PRD 03)

FastAPI + uvicorn service running the Clinical Co-Pilot agent graph
(refuse → route → tools → draft → verify → emit). Validates
`COPILOT_INTERNAL_SECRET`, exposes `/health`, soft `/ready`, and `/v1/chat`
which streams hybrid SSE (`progress` → verified `clinical` → `done` | `error`).

Route classification and claim drafting call OpenRouter (Haiku, temperature 0).
Chart facts come from the OpenEMR gateway `tool_proxy.php` (stub tools until
PRD 04). Verification is deterministic: chart claims must cite a locator
returned by this turn's tools, and the shipped text is the tool fact prose —
never model-authored clinical text. Refusal codes are allowlisted
(`no_research`) and canonicalized.

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
    graph.py           # LangGraph assembly
    state.py           # GraphState + shared messages/limits
    llm.py             # OpenRouter Haiku route/draft helpers
    claims.py          # claim schema, parse, verify, assemble
    gateway_client.py  # HTTP client → tool_proxy.php
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
**or `OPENROUTER_API_KEY` is missing/unreachable**):

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
refusal text. Empty or >4000-char message → SSE `error` frame.

## Docker

```bash
docker build -t copilot-sidecar sidecar/
docker run --rm -e COPILOT_INTERNAL_SECRET=dev-secret-change-me -p 8080:8080 copilot-sidecar
```

Compose service `copilot-sidecar` in `docker/development-easy/docker-compose.yml`
and `docker/production/docker-compose.yml` (**no host ports** in compose; both
pass the full env below).

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `COPILOT_INTERNAL_SECRET` | *(required)* | Shared with OpenEMR gateway |
| `COPILOT_GATEWAY_TOOL_URL` | `http://openemr/interface/ask_copilot/tool_proxy.php` | Chart tool proxy |
| `OPENROUTER_API_KEY` | empty | Required for live route/draft (missing → `/ready` false, turns error) |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API base |
| `OPENROUTER_MODEL` | `anthropic/claude-haiku-4.5` | Pinned Haiku id |
| `COPILOT_LLM_TIMEOUT_SECONDS` | `30` | Per-LLM-call budget (route and draft each) |
| `COPILOT_TOOL_TIMEOUT_SECONDS` | `10` | Gateway tool / probe budget |

OpenEMR container (not sidecar): `COPILOT_SIDECAR_URL`,
`COPILOT_GATEWAY_TIMEOUT_SECONDS` (default 120 — must cover route + draft +
tools for one turn).

## Tests

From repo root (host Python 3.11+):

```bash
pip install -r sidecar/requirements.txt pytest
export COPILOT_INTERNAL_SECRET=test-secret
pytest sidecar/tests/ -q
```
