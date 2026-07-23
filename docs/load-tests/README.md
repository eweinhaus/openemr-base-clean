# Clinical Co-Pilot — Load tests (L2 / L3)

**Purpose:** Scripts and a place to record CPU / memory / latency / error-rate under concurrent chat load.  
**Honest expectation:** MVP is **one LangGraph worker** on a **2 GB** droplet shared with OpenEMR + MariaDB. Saturation (rising p95/p99, timeouts, elevated errors) at moderate concurrency is the **expected** result — not a surprise failure.

Do **not** invent baseline numbers. Fill the table below only after a real run.

## Prerequisites

- [k6](https://k6.io/) installed locally
- Sidecar reachable (`BASE_URL`) **or** gateway stream URL if you extend the script
- Matching `COPILOT_INTERNAL_SECRET` as `SECRET`
- Prefer hitting **sidecar `/v1/chat`** from a host that can reach the Docker network (or a published port). Browser→gateway SSE needs session+CSRF and is harder to drive from k6 without cookie setup.

## Env vars

| Variable | Meaning | Example |
| --- | --- | --- |
| `BASE_URL` | Sidecar origin (no trailing slash) | `http://127.0.0.1:8080` |
| `SECRET` | `X-Copilot-Internal-Secret` | same as compose |
| `VUS` | Virtual users (concurrent) | `10` or `50` |
| `DURATION` | Optional hold time | `30s` (script defaults scenarios) |
| `PID` | Bound patient id in payload | `6` (demo) — unbound refuses without LLM |

## Scenarios (≥10 and ≥50 concurrent)

```bash
# ≥10 concurrent
BASE_URL=http://127.0.0.1:8080 SECRET=dev-secret-change-me VUS=10 \
  k6 run docs/load-tests/k6-chat.js

# ≥50 concurrent — expect single-worker saturation on 2 GB
BASE_URL=http://127.0.0.1:8080 SECRET=dev-secret-change-me VUS=50 \
  k6 run docs/load-tests/k6-chat.js
```

Optional: `k6 run --out json=docs/load-tests/run.json ...` then extract http metrics.

## What to record

From k6 summary (and `docker stats` / `top` on the droplet during the run):

| Metric | Where |
| --- | --- |
| p50 / p95 / p99 latency | k6 `http_req_duration` |
| Error rate | non-200, SSE `error` frames, timeouts |
| CPU / memory | host or `copilot-sidecar` + `openemr` containers |
| Throughput | successful iterations / s |

Wrong secret should stay **401** (auth path); do not count intentional 401 probes as clinical errors.

## Baseline placeholder (L2) — fill after run

| Scenario | VUs | p50 | p95 | p99 | Error rate | CPU (sidecar) | Mem (sidecar) | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| warm idle | 1 | — | — | — | — | — | — | fill after run |
| concurrent | 10 | — | — | — | — | — | — | fill after run |
| stress | 50 | — | — | — | — | — | — | fill after run; **expect saturation** |

**Interview line:** Single-worker saturation under ≥10–50 concurrent SSE turns is consistent with ARCHITECTURE §4.7 / §8 — we document the limit instead of claiming multi-tenant capacity.
