# Copilot stub sidecar (PRD 02 Wave 1)

Minimal stdlib Python service that validates `COPILOT_INTERNAL_SECRET` and emits hybrid SSE (`progress` → `clinical` → `done`). Replaced by the LangGraph sidecar in PRD 03.

## Run locally

```bash
export COPILOT_INTERNAL_SECRET=dev-secret-change-me
python3 sidecar/stub_app.py
```

Health check:

```bash
curl -s http://127.0.0.1:8080/health
```

Chat (SSE):

```bash
curl -N -X POST http://127.0.0.1:8080/v1/chat \
  -H "Content-Type: application/json" \
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

Wrong secret returns `401` with `{"error":"unauthorized"}`.

## Docker Compose

Wired in `docker/development-easy/docker-compose.yml` and `docker/production/docker-compose.yml` as service `copilot-sidecar` (**no host ports**).

Shared env (openemr + sidecar):

| Variable | Purpose |
| --- | --- |
| `COPILOT_INTERNAL_SECRET` | Shared secret (required; default only for local easy-dev) |
| `COPILOT_SIDECAR_URL` | OpenEMR → sidecar, e.g. `http://copilot-sidecar:8080` |
| `COPILOT_GATEWAY_TIMEOUT_SECONDS` | Default `45` |

On DigitalOcean `/opt/openemr`, set the same variables and rebuild/restart so openemr can reach the sidecar on the Compose network. Do not publish sidecar ports on the public interface.
