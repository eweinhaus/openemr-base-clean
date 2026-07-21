---
name: deploy
description: >-
  Deploy Clinical Co-Pilot to the DigitalOcean demo droplet (overlay bind-mounts
  + LangGraph sidecar under /opt/openemr). Use when the user says deploy, /deploy,
  ship to DO, update the live site, or push Co-Pilot to https://142.93.255.212/.
disable-model-invocation: true
---

# Deploy to DigitalOcean

Ship Co-Pilot to the **live demo droplet**. Live DO is interview source of truth (`docs/ai-decision-guide.md`).

## Target (locked)

| | |
| --- | --- |
| URL | https://142.93.255.212/ |
| SSH | `ssh -i ~/.ssh/id_ed25519_openemr root@142.93.255.212` |
| Stack dir | `/opt/openemr` |
| Login | `admin` / `pass` |
| Pattern | Stock `openemr/openemr:latest` + **overlay bind-mounts** + `copilot-sidecar` |

Do **not** switch to fork-built OpenEMR image, Render, or Vercel unless the user explicitly changes the lock.

## Permissions

SSH/`scp`/`docker` against the droplet need unrestricted shell permissions (`required_permissions: ["all"]`). Never print `OPENROUTER_API_KEY` or `COPILOT_INTERNAL_SECRET` values — only report set/missing.

## Choose a path

1. **Update existing Co-Pilot deploy** (default) — overlay already on DO → follow **Redeploy**
2. **First Co-Pilot install** on an OpenEMR-only droplet → follow **First Co-Pilot install**
3. **Empty droplet** → read [reference.md](reference.md) § Bootstrap, then First Co-Pilot install

---

## Redeploy (usual path)

Copy this checklist and track it:

```
Deploy progress:
- [ ] 1. Package overlay + sidecar
- [ ] 2. Backup remote compose; upload; extract (preserve .env)
- [ ] 3. Clean macOS junk; compose up --build
- [ ] 4. Confirm module active
- [ ] 5. Health / mount smoke
- [ ] 6. Browser smoke (and OpenRouter if needed)
- [ ] 7. Update Memory Bank
```

### 1. Package

From repo root:

```bash
bash .cursor/skills/deploy/scripts/package.sh
```

Produces `tmp/do-copilot-deploy.tgz` (gitignored). Contents: `overlay/`, `sidecar/`, `docker-compose.yml`, `.env.example`, `enable_ask_copilot.sql`.

### 2. Upload (preserve secrets)

```bash
KEY="$HOME/.ssh/id_ed25519_openemr"
HOST="root@142.93.255.212"
TGZ="$PWD/tmp/do-copilot-deploy.tgz"

ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$HOST" \
  'cp -a /opt/openemr/docker-compose.yml /opt/openemr/docker-compose.yml.bak.$(date +%Y%m%d%H%M%S)'

scp -i "$KEY" "$TGZ" "$HOST:/opt/openemr/do-copilot-deploy.tgz"

ssh -i "$KEY" "$HOST" 'set -euo pipefail
cd /opt/openemr
# Keep live .env (OPENROUTER / secrets)
if [ -f .env ]; then cp -a .env .env.preserve; fi
tar -xzf do-copilot-deploy.tgz
if [ -f .env.preserve ]; then mv .env.preserve .env; fi
# Only create .env from example if missing
if [ ! -f .env ]; then cp .env.example .env; fi
find overlay sidecar -name "._*" -delete
find overlay sidecar -name ".DS_Store" -delete 2>/dev/null || true
test -f overlay/interface/ask_copilot/index.php
test -f overlay/src/ClinicalCopilot/Gateway/SessionGateway.php
test -f sidecar/Dockerfile
echo EXTRACT_OK
'
```

### 3. Bring stack up

```bash
ssh -i "$KEY" "$HOST" 'set -euo pipefail
cd /opt/openemr
docker compose up -d --build --remove-orphans
docker compose ps
'
```

Wait until OpenEMR login returns HTTP 200 and sidecar is **healthy** (up to ~3 min on 2 GB).

### 4. Module

Idempotent SQL (safe to re-run):

```bash
ssh -i "$KEY" "$HOST" \
  'docker exec -i openemr-mysql-1 mariadb -uopenemr -popenemr openemr < /opt/openemr/enable_ask_copilot.sql'
```

Expect `oe-module-ask-copilot` with `mod_active=1`. Alternate: Modules UI on the live site.

### 5. Automated smoke

```bash
ssh -i "$KEY" "$HOST" 'set -e
cd /opt/openemr
docker exec openemr-openemr-1 sh -c "
  test -f /var/www/localhost/htdocs/openemr/interface/ask_copilot/index.php &&
  test -f /var/www/localhost/htdocs/openemr/src/ClinicalCopilot/Gateway/SessionGateway.php &&
  echo MOUNTS_OK
"
docker exec openemr-openemr-1 sh -c "curl -sS --max-time 5 \$COPILOT_SIDECAR_URL/health; echo"
docker exec openemr-copilot-sidecar-1 sh -c "curl -sS http://127.0.0.1:8080/health; echo"
if grep -q "^OPENROUTER_API_KEY=.\+" /opt/openemr/.env; then echo OPENROUTER=set; else echo OPENROUTER=missing; fi
'
```

### 6. Browser smoke

1. https://142.93.255.212/ → accept self-signed warning → `admin` / `pass`
2. Select a Synthea patient (e.g. pid **6** Vincenzo126 Kemmer137 if still present)
3. **Ask Co-Pilot** tab (`acp0`) → Send a short message
4. Expect hybrid SSE: `progress` → clinical/refuse → `done` (not a 404 / gateway crash)

If `OPENROUTER=missing`, clinical Haiku turns fail — set key (below) before claiming chat works.

### 7. Memory Bank

After a successful deploy, update `memory-bank/activeContext.md` + `progress.md` (what landed, OpenRouter status, leftover debt).

---

## First Co-Pilot install

Same as Redeploy, but:

1. Confirm stock stack already runs at `/opt/openemr` (`docker compose ps` shows mysql + openemr).
2. Packaging **replaces** remote `docker-compose.yml` with overlay mounts + sidecar (script embeds the DO compose). Backup first (step 2).
3. Always run enable-module SQL.
4. Volumes (`databasevolume`, `sitevolume`) must be **kept** — never `docker compose down -v` on DO.

---

## Set / rotate OpenRouter key

Ask the user for the key if missing. Write without echoing:

```bash
ssh -i "$KEY" "$HOST" 'set -euo pipefail
cd /opt/openemr
# KEY value supplied out-of-band — do not log it
grep -q "^OPENROUTER_API_KEY=" .env \
  && sed -i "s/^OPENROUTER_API_KEY=.*/OPENROUTER_API_KEY=${OPENROUTER_API_KEY}/" .env \
  || echo "OPENROUTER_API_KEY=${OPENROUTER_API_KEY}" >> .env
docker compose up -d --force-recreate copilot-sidecar
'
```

Prefer passing the value via an env var on the remote command the user approved — never commit keys; never paste into Memory Bank.

---

## PHP-only hot patch (fast)

When only overlay PHP/JS changed (no sidecar/compose):

```bash
# package.sh still OK, or rsync overlay dirs then:
ssh -i "$KEY" "$HOST" 'cd /opt/openemr && docker compose restart openemr'
```

Sidecar Python changes require `docker compose up -d --build copilot-sidecar`.

---

## Hard rules

- **Preserve** `/opt/openemr/.env` on every upload.
- **Never** `docker compose down -v` on DO (wipes Synthea + sites).
- Sidecar stays **Compose-internal** (no host port publish).
- Single uvicorn worker; 2 GB host — one-physician demo concurrency only.
- Demo posture: self-signed HTTPS, `admin`/`pass`, no DB TLS — document, don’t “fix” into production hardening mid-demo.
- Prefer overlay sync over rebuilding a custom OpenEMR image (current debt; intentional).

## Pitfalls

| Symptom | Fix |
| --- | --- |
| `._*` / weird PHP parse errors after scp | `find overlay sidecar -name '._*' -delete` |
| Ask Co-Pilot missing from menu | Re-run `enable_ask_copilot.sql`; hard refresh / re-login |
| Mounts missing inside container | Confirm compose volume lines; `compose up -d` recreate openemr |
| Sidecar unhealthy / OOM | `free -h`; avoid extra services; rebuild sidecar only |
| Send fails / route error | `OPENROUTER_API_KEY` missing or sidecar not reachable from openemr |
| Local Docker Hub hang | Build sidecar **on the droplet** (`compose build`), not via local Desktop creds |
| Wrong module SQL columns | Use packaged `enable_ask_copilot.sql` (not a minimal invent-columns INSERT) |

## Additional resources

- Compose template, env vars, bootstrap, Synthea notes: [reference.md](reference.md)
- Packaging script: [scripts/package.sh](scripts/package.sh)
- Module SQL: [scripts/enable-module.sql](scripts/enable-module.sql)
