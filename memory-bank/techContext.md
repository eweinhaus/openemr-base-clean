# Tech Context

## Local OpenEMR

- Path: `docker/development-easy` → `docker compose up --detach --wait`
- App: http://localhost:8300/ · login `admin` / `pass`
- Tooling: `openemr-cmd` for tests / php-log / Synthea import
- **Co-Pilot bootstrap:** `scripts/copilot/setup-local-demo.sh` (module enable + demo seeds); auto via start-openemr skill unless `COPILOT_SKIP_SETUP=1`
- **Sidecar QA (dev):** `curl http://127.0.0.1:8080/health` / `/ready` (loopback-only port; override `WT_COPILOT_SIDECAR_PORT`)

## Public deploy (live)

| | |
| --- | --- |
| URL | https://142.93.255.212/ |
| Host | DigitalOcean Droplet `openemr`, NYC1 |
| Size | Basic Regular, 1 vCPU / **2 GB** / 50 GB SSD (~$12/mo) |
| OS | Ubuntu 24.04 |
| Stack | Docker Compose @ `/opt/openemr` |
| Images | `openemr/openemr:latest` + `mariadb:11.8` (fork-built when agent lands) |
| Login | `admin` / `pass` (Gauntlet demo; documented in AUDIT) |
| SSH | `ssh -i ~/.ssh/id_ed25519_openemr root@142.93.255.212` |
| Key | `openemr-do` on DO |

HTTPS self-signed on bare IP. No DB TLS / MFA on public demo (documented gaps).

## Demo clinical data

- Example SQL = demographics only — **insufficient**
- Synthea: `openemr-cmd import-random-patients` ≈ **5–10** on **local and DO**
- Verify FHIR UUIDs; confirm `rxnorm_drugcode` after CCDA import
- **Local seeds:** `scripts/copilot/setup-local-demo.sh` — picker appts (pids 6/8/2) + Lisinopril empty RxNorm on Susan Underwood/pid 2; re-run `--seed-only` after calendar day roll

## Agent stack (locked)

| Piece | Choice |
| --- | --- |
| Topology | Hybrid: OpenEMR session-proxy gateway + LangGraph sidecar |
| LLM | OpenRouter · Haiku everywhere (MVP); pin `anthropic/claude-haiku-4.5` (not retired `claude-3.5-haiku`) |
| Framework | LangGraph (Python) |
| Observability | Correlation ID + JSONL disclosure (`verify` callback); LangSmith redacted env-gated (PRD 07 thin; no dashboard polish) |
| Chart access | PHP services via gateway (pid-scoped); FHIR phase 2 |
| Research | openFDA → DailyMed fallback; no PHI; `sidecar/app/research/` (PRD 05 landed); optional `OPENFDA_API_KEY` |
| Stream | Hybrid SSE (progress → clinical `{text,segments}` → citation batch → done) |
| State | Open-tab transcript until closed (plain text resend; citations display-only) |
| Deploy | Same 2 GB host; single sidecar worker |

## Git

| Remote | URL |
| --- | --- |
| `origin` | https://github.com/eweinhaus/openemr-base-clean |
| `upstream` | https://github.com/Gauntlet-HQ/openemr-base-clean |

Branch: `main` → `origin/main`.

## Explicitly not used for EHR runtime

- Vercel / Firebase — wrong for PHP+MySQL EHR
- Render — costlier two-service + disk pattern for this stage

## Important docs

- `docs/directions.md` — case study
- `AUDIT.md` — Stage 3
- `USERS.md` / `USER.md` — Stage 4 (USERS canonical)
- `ARCHITECTURE.md` — Stage 5 plan (canonical locks)
- `docs/ai-decision-guide.md` — how agents choose under ambiguity (under ARCHITECTURE; local/untracked for now)
- `docs/architecture-overview.md` — diagrams companion
- `docs/architecture-tech-primer.md` — study guide (decisions now locked)
- `docs/PRDs/01`–`08` — vertical-slice PRDs (`07-observability-langsmith.md` coded; `08-brief-narrative-synthesis.md` coded)
- `docs/local-demo-success-criteria.md` — local QA sign-off checklist
- `CLAUDE.md` / `CONTRIBUTING.md` — OpenEMR conventions
