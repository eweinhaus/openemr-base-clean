# Deploy reference — DigitalOcean Clinical Co-Pilot

## Overlay layout on droplet

```
/opt/openemr/
  docker-compose.yml          # DO-tuned (overlay mounts + sidecar)
  .env                        # secrets — never overwrite blindly
  .env.example                # template from package
  enable_ask_copilot.sql
  overlay/
    interface/ask_copilot/
    interface/modules/custom_modules/oe-module-ask-copilot/
    src/ClinicalCopilot/
  sidecar/                    # build context for copilot-sidecar
  docker-compose.yml.bak.*    # backups
```

Bind mounts into `openemr` container:

| Host | Container |
| --- | --- |
| `./overlay/interface/ask_copilot` | `.../interface/ask_copilot` |
| `./overlay/interface/modules/custom_modules/oe-module-ask-copilot` | `.../interface/modules/custom_modules/oe-module-ask-copilot` |
| `./overlay/src/ClinicalCopilot` | `.../src/ClinicalCopilot` |

## Env vars

| Var | Where | Notes |
| --- | --- | --- |
| `COPILOT_INTERNAL_SECRET` | openemr + sidecar | Shared; required for gateway ↔ sidecar |
| `COPILOT_SIDECAR_URL` | openemr | Default `http://copilot-sidecar:8080` |
| `COPILOT_GATEWAY_TIMEOUT_SECONDS` | openemr | Default **120** (covers route+draft LLM budgets) |
| `COPILOT_GATEWAY_TOOL_URL` | sidecar | `http://openemr/interface/ask_copilot/tool_proxy.php` |
| `OPENROUTER_API_KEY` | sidecar | Required for live Haiku route/draft |
| `OPENROUTER_BASE_URL` | sidecar | `https://openrouter.ai/api/v1` |
| `OPENROUTER_MODEL` | sidecar | `anthropic/claude-haiku-4.5` |
| `COPILOT_LLM_TIMEOUT_SECONDS` | sidecar | Default `30` |
| `COPILOT_TOOL_TIMEOUT_SECONDS` | sidecar | Default `10` |

Repo `docker/production/docker-compose.yml` uses `${COPILOT_INTERNAL_SECRET:?...}` (fail if unset). The **DO** compose shipped by `package.sh` currently allows a weak default for demo continuity — rotate before any non-demo use; note debt in Memory Bank if still weak.

## DO compose (canonical shape)

Embedded in `scripts/package.sh`. Key differences from stock production template:

- `mariadb:11.8` with `--innodb-buffer-pool-size=256M` (2 GB host)
- Three Co-Pilot bind mounts on `openemr`
- `copilot-sidecar` build `context: ./sidecar` (no host ports)
- Named volumes preserved: `databasevolume`, `sitevolume`, `logvolume01`

Container names on this droplet are typically:

- `openemr-openemr-1`
- `openemr-mysql-1`
- `openemr-copilot-sidecar-1`

If names differ, resolve via `docker compose ps` / `docker ps`.

## Bootstrap (empty Ubuntu droplet)

Only when `/opt/openemr` does not exist yet:

1. Droplet: Ubuntu 24.04, NYC1, **2 GB** RAM, SSH key `openemr-do` / local `~/.ssh/id_ed25519_openemr`
2. Install Docker Engine + Compose plugin
3. Add **2G swap** (OpenEMR install + image pulls need it on 2 GB)
4. `mkdir -p /opt/openemr` and start from production-style compose (mysql + openemr) **or** run First Co-Pilot install packaging immediately
5. Open ports 80/443; HTTPS will be self-signed on bare IP
6. Wait for OpenEMR first-boot health; login `admin`/`pass`
7. Import Synthea (~5–10 patients) with `--isDev=true` path — `importRandomPatients … false` only stores CCDA docs (known caveat)
8. Then enable Co-Pilot overlay as in SKILL.md

Do not recreate the droplet casually — demo Synthea + missing-RxNorm seed live in volumes.

## Synthea / demo data (DO)

- Prefer existing patients; re-import only if DB wiped
- Known missing-RxNorm seed historically: **Vincenzo126 Kemmer137** (pid **6**, Turmeric free-text)
- Local counterpart differs (Susan Underwood pid 2) — do not assume identical pids

## What is intentionally not deployed this way

- Fork-built `openemr/openemr` image with Co-Pilot baked in (deferred)
- LangSmith keys (optional later)
- Production credential rotation / DB TLS / MFA
- Multi-worker sidecar

## Related docs

- `memory-bank/techContext.md` — host facts
- `memory-bank/activeContext.md` — current DO gap / last deploy notes
- `docker/production/docker-compose.yml` — repo production template (+ sidecar)
- `sidecar/README.md` — sidecar env and health
- `AUDIT.md` — demo security posture
