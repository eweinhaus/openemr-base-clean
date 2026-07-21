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

Bring up the local OpenEMR webapp via `docker/development-easy`.

## Do this

1. Run the helper (preferred — handles Docker Desktop, waits, verifies):

```bash
bash .cursor/skills/start-openemr/scripts/start.sh
```

2. Shell tool **must** use unrestricted permissions (`required_permissions: ["all"]`). Docker socket calls fail in the sandbox.

3. Tell the user:
   - App: http://localhost:8300/ (HTTPS: https://localhost:9300/)
   - Login: `admin` / `pass`
   - phpMyAdmin: http://localhost:8310/

## If the script is unavailable

```bash
# 1) Docker daemon
docker info >/dev/null 2>&1 || open -a Docker
# poll until ready (macOS): up to ~2 minutes
until docker info >/dev/null 2>&1; do sleep 2; done

# 2) Start stack (from repo root)
cd docker/development-easy
docker compose up --detach --wait
```

Prefer `openemr-cmd up` from that directory only if `openemr-cmd` is on `PATH`.

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
```

Expect `openemr` **healthy** and HTTP `200` or `302`.

## Stop (only if asked)

```bash
cd docker/development-easy && docker compose down
# wipe volumes (slow next start): docker compose down -v
```
