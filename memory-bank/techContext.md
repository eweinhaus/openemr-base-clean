# Tech Context

## Local OpenEMR

- Path: `docker/development-easy` → `docker compose up --detach --wait`
- App: http://localhost:8300/ · login `admin` / `pass`
- Tooling: `openemr-cmd` for tests / php-log / Synthea import

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
- Verify FHIR UUIDs; confirm `rxnorm_drugcode` after CCDA import (may need one free-text med for uncertainty demo)

## Agent stack (locked)

| Piece | Choice |
| --- | --- |
| Topology | Hybrid: OpenEMR session-proxy gateway + LangGraph sidecar |
| LLM | OpenRouter · Haiku everywhere (MVP) |
| Framework | LangGraph (Python) |
| Observability | LangSmith (redacted) + correlation IDs + disclosure log |
| Chart access | PHP services via gateway (pid-scoped); FHIR phase 2 |
| Research | openFDA → DailyMed; no PHI in queries |
| Stream | Hybrid SSE (progress → verified clinical) |
| State | Open-tab transcript until closed |
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
- `CLAUDE.md` / `CONTRIBUTING.md` — OpenEMR conventions
