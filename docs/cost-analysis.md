# Clinical Co-Pilot — AI cost analysis (A9 / L5)

**Date:** 2026-07-22  
**Topology:** hybrid OpenEMR session-proxy gateway + LangGraph sidecar, **single worker** on the same **DigitalOcean 2 GB** droplet (~**$12/mo**), model pin **OpenRouter** `anthropic/claude-haiku-4.5`, research **openFDA → DailyMed** (sidecar-only), cite-or-silence verify, hybrid SSE.  
**Tone:** interview-honest estimates — not audited invoices.

---

## 1. Actual / estimated spend to date (build + demo)

| Line item | Amount | Notes |
| --- | --- | --- |
| DigitalOcean droplet (2 GB, NYC1) | **$12 / month** | OpenEMR + MariaDB + one sidecar worker; swap already in play for MVP |
| OpenRouter (Haiku prototyping) | **~$5–30** (estimate) | Route + draft calls during build/demo; **not** a measured invoice export — treat as order-of-magnitude |
| LangSmith | **$0** (optional free tier) | Redacted traces when keys set; silent disable if missing — does not gate `/ready` alone |
| openFDA / DailyMed | **$0** | Public APIs; optional `OPENFDA_API_KEY` only raises rate limits |

**Dev-time LLM note:** Co-Pilot uses two Haiku calls per successful turn (route + draft) when the graph runs. Unbound-pid refuses and auth failures do **not** burn tokens. Failures after route still may have spent the route call.

---

## 2. Haiku pricing ballpark (caveat: prices change)

As of mid-2026 public list / aggregator ballparks for Claude Haiku 4.5-class models (OpenRouter / Anthropic-adjacent):

| | Approx. |
| --- | --- |
| Input | **~$1.00 / 1M tokens** |
| Output | **~$5.00 / 1M tokens** |

**Caveat:** OpenRouter and upstream list prices move. Re-check https://openrouter.ai/ before any budget commitment. Caching / batch discounts may apply on some providers; MVP does not assume prompt-cache savings.

### Rough $/user/month (token-only sketch)

Assumptions for a **single active physician** using Co-Pilot between rooms (not concurrent clinic-wide load):

- ~20 turns / physician / day × 20 workdays ≈ **400 turns / month**
- ~2 LLM calls / turn (route + draft)
- ~3–6k input + ~0.4–1k output tokens **per call** (brief with chart facts is the heavy case) → order **~$0.01–0.05 / turn** at Haiku list rates
- → ballpark **~$4–20 / active physician / month** in LLM tokens alone at that usage

This is **not** “users × tokens” at scale — concurrency, chart fan-in, and hosting dominate after ~1K concurrent-capable users (below).

---

## 3. Projections by user tier (architecture must change)

“Users” here means **physicians (or seats) who could hit the agent**, not page views. Costs are **order-of-magnitude**; the important part is **what breaks** on the current single-worker 2 GB box.

### ~100 users

| | |
| --- | --- |
| **Architecture** | Keep current: one OpenEMR + MariaDB + **one** LangGraph worker on 2 GB; Haiku everywhere; **no** pre-ask brief cache |
| **Cost drivers** | $12 droplet + Haiku tokens for sparse concurrency (often one physician at a time in demo) |
| **Rough monthly** | Hosting **~$12** + LLM **tens of dollars** if lightly used; still demo-shaped |
| **Honest limit** | Concurrent SSE turns will queue/saturate the single worker — acceptable for interview MVP |

### ~1K users

| | |
| --- | --- |
| **Architecture** | Add **brief TTL cache** (pre-ask / short-lived chart fact cache); **rate limits** per user/session; likely **2 workers** or **separate small sidecar host** so OpenEMR PHP and agent CPU do not fight on one 2 GB box |
| **Cost drivers** | Extra ~$12–40 host for sidecar; LLM grows with active seats; openFDA rate limits matter for UC-3 |
| **Rough monthly** | Hosting **~$25–60** + LLM **low hundreds** if hundreds of active physicians ask daily |
| **Why not tokens×users** | Without cache + rate limits, chart tool fan-in (brief = 4 parallel tools) and dual LLM calls amplify cost and latency faster than seat count |

### ~10K users

| | |
| --- | --- |
| **Architecture** | **Split** OpenEMR vs agent hosts; **queue** in front of LangGraph; **multi-worker** agent pool; **Redis** (or equivalent) checkpointer / bind store; stronger monitoring (metrics + the three alert stubs wired) |
| **Cost drivers** | Agent cluster VMs; Redis; LLM; chart DB read load; research egress |
| **Rough monthly** | Hosting **hundreds–low thousands** + LLM **thousands** depending on engagement |
| **Product shifts** | Still read-only chart for Co-Pilot; interaction APIs remain out of MVP; SMART/FHIR chart path becomes attractive to reduce custom tool_proxy fan-in |

### ~100K users

| | |
| --- | --- |
| **Architecture** | Dedicated **agent cluster**; **FHIR/SMART** (or equivalent) for chart access; **multi-region**; durable transcript policy revisited; interaction APIs still a **separate** product surface if ever added |
| **Cost drivers** | **LLM tokens** + **chart fan-in** + **research** (FDA/DailyMed or licensed label corpus) + multi-region ops |
| **Rough monthly** | Dominated by LLM and EHR integration infra — budget as a platform line item, not a $12 droplet |
| **Honesty** | Current compose-on-one-droplet design is **explicitly** not this tier |

---

## 4. What we are *not* counting (yet)

- Physician time saved (product value, not cloud bill)
- OpenEMR core hosting if Co-Pilot were bolted onto an existing large install (marginal agent cost only)
- Compliance/BAA legal spend (OpenRouter treated as BAA-covered / no-training for demo policy — contract reality is org-specific)
- Dual-source conflict UX / interaction APIs (deferred) — those would add research and possibly higher-tier model spend

---

## 5. Interview one-liner

> We run Haiku on a **$12/mo 2 GB** single-worker hybrid stack for the demo; build-time OpenRouter was roughly **tens of dollars**. Scaling is **not** “multiply tokens by users” — at 1K we add cache and separate the sidecar; at 10K we queue and multi-worker with Redis; at 100K we need an agent cluster and FHIR/SMART. Cost drivers become **LLM + chart fan-in + research**, not the droplet.
