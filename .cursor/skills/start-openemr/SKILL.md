---
name: start-openemr
description: >-
  Start the OpenEMR development-easy Docker webapp (ensure Docker Desktop is
  running, bring up compose, verify health). Use when explicitly invoked as
  start-OpenEMR / start-openemr, or when the user asks to start/run/boot the
  OpenEMR local webapp stack.
disable-model-invocation: true
---

# Start OpenEMR

Bring up the local OpenEMR webapp via `docker/development-easy`. This includes
the **Clinical Co-Pilot `copilot-sidecar`** service — Ask Co-Pilot fails closed
("Something went wrong. Try again.") if the gateway can't reach it, so the
sidecar must be up whenever the app is.

## Do this

1. Run the helper (preferred — handles Docker Desktop, waits, verifies openemr
   **and** the sidecar):

```bash
bash .cursor/skills/start-openemr/scripts/start.sh
```

2. Shell tool **must** use unrestricted permissions (`required_permissions: ["all"]`). Docker socket calls fail in the sandbox.

3. Tell the user:
   - App: http://localhost:8300/ (HTTPS: https://localhost:9300/)
   - Login: `admin` / `pass`
   - phpMyAdmin: http://localhost:8310/
   - Co-Pilot sidecar status (the script prints whether `OPENROUTER_API_KEY`
     is configured; without it Ask Co-Pilot turns still error at the LLM call).

## If the script is unavailable

```bash
# 1) Docker daemon
docker info >/dev/null 2>&1 || open -a Docker
# poll until ready (macOS): up to ~2 minutes
until docker info >/dev/null 2>&1; do sleep 2; done

# 2) Start stack (from repo root) — brings up openemr AND copilot-sidecar
cd docker/development-easy
docker compose up --detach --wait
```

Prefer `openemr-cmd up` from that directory only if `openemr-cmd` is on `PATH`.

The `copilot-sidecar` service is defined in the same compose file (no host
ports — reachable only from `openemr` at `http://copilot-sidecar:8080`). `up`
builds it on first run. For live Ask Co-Pilot turns it needs
`OPENROUTER_API_KEY`; set it in `docker/development-easy/.env` (git-ignored):

```bash
echo 'OPENROUTER_API_KEY=sk-or-...' >> docker/development-easy/.env
docker compose -f docker/development-easy/docker-compose.yml up -d --wait copilot-sidecar
```

Do **not** export `COPILOT_SIDECAR_URL` in your shell before `up` — it bakes a
stale value into the openemr container (symptom: gateway logs
`Connection refused for URI http://<something>:8080/v1/chat`). The compose
default `http://copilot-sidecar:8080` is correct for local.

## Pitfalls (avoid)

| Issue | Fix |
|-------|-----|
| `Cannot connect to the Docker daemon` | Docker Desktop not running — `open -a Docker`, then poll `docker info` |
| Compose exits before app is usable | Always use `--wait` (or wait for `openemr` healthy) |
| Wrong directory | Compose file is only in `docker/development-easy/` |
| Sandbox / EACCES on docker.sock | Re-run shell with `required_permissions: ["all"]` |
| Inside `*/openemr-wt-<slug>/` worktree | Use `openemr-cmd worktree start <branch>` / `worktree up` — do **not** raw-compose the primary stack |

## Verify

```bash
docker compose -f docker/development-easy/docker-compose.yml ps
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8300/
# gateway → sidecar reachability + OpenRouter readiness (from inside openemr):
docker compose -f docker/development-easy/docker-compose.yml exec -T openemr \
  curl -s http://copilot-sidecar:8080/ready
```

Expect `openemr` **and** `copilot-sidecar` **healthy**, HTTP `200`/`302`, and a
`/ready` JSON body. `"configured":true` means OpenRouter is wired; `false` means
the sidecar is reachable but `OPENROUTER_API_KEY` is missing.

## Stop (only if asked)

```bash
cd docker/development-easy && docker compose down
# wipe volumes (slow next start): docker compose down -v
```
