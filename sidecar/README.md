# Copilot FastAPI sidecar (PRD 03 Wave 1)

FastAPI + uvicorn shell replacing the PRD 02 stdlib stub. Validates `COPILOT_INTERNAL_SECRET`, exposes `/health`, soft `/ready`, and a placeholder `/v1/chat` that emits hybrid SSE (`progress` → `clinical` → `done`).

Wave 3 wires the LangGraph agent; Wave 1 chat returns a short skeleton clinical line (no `Stub sidecar:` watermark).

## Layout

```
sidecar/
  Dockerfile
  requirements.txt
  app/
    main.py       # routes
    auth.py       # secret compare
    sse.py        # SSE framing
    claims.py     # claim schema (T1; used by Wave 2+ verify)
  tests/
```

`stub_app.py` was removed; use this FastAPI app instead.

## Run locally

From repo root (install deps once):

```bash
cd sidecar
pip install -r requirements.txt
export COPILOT_INTERNAL_SECRET=dev-secret-change-me
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

Ready (soft — always HTTP 200; body may show `ready: false`):

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
    "message": "Hello",
    "transcript": []
  }'
```

Wrong secret → `401` with `{"error":"unauthorized"}`.

## Docker

```bash
docker build -t copilot-sidecar sidecar/
docker run --rm -e COPILOT_INTERNAL_SECRET=dev-secret-change-me -p 8080:8080 copilot-sidecar
```

Compose service `copilot-sidecar` in `docker/development-easy/docker-compose.yml` and `docker/production/docker-compose.yml` (**no host ports** in compose).

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `COPILOT_INTERNAL_SECRET` | *(required)* | Shared with OpenEMR gateway |
| `COPILOT_GATEWAY_TOOL_URL` | `http://openemr/interface/ask_copilot/tool_proxy.php` | Tool proxy for `/ready` probe |
| `OPENROUTER_API_KEY` | empty | Optional in Wave 1; required for full agent later |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API base |
| `OPENROUTER_MODEL` | `anthropic/claude-3.5-haiku` | Pinned Haiku id |
| `COPILOT_LLM_TIMEOUT_SECONDS` | `30` | LLM call budget |
| `COPILOT_TOOL_TIMEOUT_SECONDS` | `10` | Gateway tool / probe budget |

OpenEMR container (not sidecar): `COPILOT_SIDECAR_URL`, `COPILOT_GATEWAY_TIMEOUT_SECONDS`.

**Wave 4 compose gap:** `docker-compose.yml` currently sets only `COPILOT_INTERNAL_SECRET` on `copilot-sidecar`. Add `COPILOT_GATEWAY_TOOL_URL`, `OPENROUTER_*`, and timeout vars when wiring the full agent.

## Tests

From repo root (host Python 3.11+):

```bash
pip install -r sidecar/requirements.txt pytest
export COPILOT_INTERNAL_SECRET=test-secret
pytest sidecar/tests/ -q
```
