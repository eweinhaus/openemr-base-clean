# PRD 03 — LangGraph Sidecar Skeleton (Step 3)

**Roadmap step:** `ARCHITECTURE.md` §7 item 3  
**Goal:** Replace the PRD 02 stub sidecar with a **real LangGraph agent**: refuse → route → gateway stub tools → Haiku draft structured claims → **code** verify → hybrid SSE; OpenRouter Haiku; thin `/health` + `/ready`.  
**Non-goal:** Real chart services (PRD 04), openFDA/DailyMed (PRD 05), citation UI/`citation` SSE (PRD 06), LangSmith (PRD 07), ReAct, durable checkpointer, research-backed dosing.

---

## 1. Problem Statement and Context

### What

Build the **agent loop spine** in a Python sidecar on the same Compose host:

1. Replace `sidecar/stub_app.py` with FastAPI + LangGraph (**one** worker).
2. Graph: refuse-if-unbound → route (`brief`|`labs`|`meds`) → one-shot gather via `tool_proxy` → Haiku draft claims JSON → deterministic verify → emit SSE.
3. OpenRouter Haiku (temp ~0) for **route + draft only** — not verify.
4. Chart tools **only via gateway**; no DB/SQL from Python.
5. Hybrid SSE: `progress` early; **one** `clinical` only after verify; then `done` / `error`.
6. Thin `GET /health` (alive) + `GET /ready` (gateway + OpenRouter reachable).
7. Lock **claim schema** so PRDs 04–06 plug in without rewrite.

### Background

PRD 02 proved session-proxy, correlation ID, secret hop, and tool_proxy fail-closed. Interview trust needs a real draft→verify gate and Haiku path before richer tools. Per `docs/ai-decision-guide.md`: vertical slice over empty skeleton; do not fake spine step 3; never stream clinical text pre-verify.

### Related Work

| Doc | Role |
| --- | --- |
| `ARCHITECTURE.md` §4.4–4.8, §7 item 3 | Graph, claims, hybrid SSE, Haiku, deploy |
| `docs/PRDs/02-session-proxy-gateway.md` | Gateway `/v1/chat`, tool_proxy — **dependency** |
| `docs/PRDs/01-ask-copilot-tab.md` | SSE event names / JS client |
| `docs/ai-decision-guide.md` | Vertical slice; code verify; thin UC-3; DO > local |
| `docs/architecture-overview.md` | Agent loop diagram |

**Depends on:** PRD 02. **Unblocks:** PRDs 04–07.

---

## 2. Technical Context

### Relevant Files/Modules

| Path | Why |
| --- | --- |
| `sidecar/stub_app.py` (PRD 02) | **Replace** with LangGraph app |
| `sidecar/Dockerfile` | Deps: fastapi, uvicorn, langgraph, httpx, OpenAI-compatible client |
| Compose (dev + DO `/opt/openemr`) | Same service; OpenRouter env; one worker; **no public port** |
| `interface/ask_copilot/tool_proxy.php` | Extend stub tool payloads/names if needed |
| `src/ClinicalCopilot/Gateway/*` | Keep contracts stable |
| `interface/ask_copilot/assets/ask_copilot.js` | No event-name changes |

### Similar Implementations

- PRD 02 stub: secret header, SSE frames, `/v1/chat` body.
- OpenRouter OpenAI-compatible API (`https://openrouter.ai/api/v1`).

### Architecture Notes

- Browser → OpenEMR only; sidecar never sees cookies.
- Pid from gateway chat payload; tools echo pid + `correlation_id`; tool_proxy bind-cache enforces match.
- No durable checkpointer; transcript is browser-resent (truncate to last **8** turns).
- Single worker on 2 GB host — one-physician demo limit.
- Research out of scope: `meds` → stub/chart facts + **explicit dosing refuse**.

### Database/API Context

**No schema migrations.**

**Chat (unchanged from PRD 02):**

```
POST /v1/chat
Header: X-Copilot-Internal-Secret, X-Correlation-Id
Accept: text/event-stream
Body: { correlation_id, user_id, username, pid, message, transcript }
```

**Tool proxy (sidecar → gateway):**

```
POST {COPILOT_GATEWAY_TOOL_URL}
Header: X-Copilot-Internal-Secret, X-Correlation-Id
Body: { "tool": "<name>", "args": {}, "pid": <int>, "correlation_id": "<id>" }
```

**SSE (unchanged names):** `progress` `{message}` → `clinical` `{text}` → `done` `{correlation_id}` | `error` `{message}` (generic).  
`citation` events out of scope (PRD 06).

**Claim schema (lock now):**

```json
{
  "claims": [
    {
      "text": "Creatinine 1.4 mg/dL on 2026-06-01",
      "source_type": "chart",
      "locator": { "table": "procedure_result", "id": "42" },
      "excerpt": "optional"
    }
  ],
  "refusals": [
    { "code": "no_research", "text": "No retrieved label source for dosing — I won't guess." }
  ]
}
```

`source_type`: `chart` | `note` | `research`. Verify accepts only locators present in **this turn’s** tool JSON. `research` claims without a research tool result **fail** verify.

---

## 3. Design Decisions (Pre-Made)

### Approach

| Decision | Choice |
| --- | --- |
| Shape | Vertical slice: graph + Haiku + gateway stubs + code verify + hybrid SSE |
| HTTP | FastAPI + uvicorn **`--workers 1`** |
| Graph | `StateGraph`: refuse → route → tools → draft → verify → emit |
| Route | Haiku → `brief`\|`labs`\|`meds`; multi-intent → **primary only**; invalid → **`brief`** |
| Tools | One-shot ≤3 calls via gateway; never bypass |
| Stub tools | `patient_context_stub`; add `labs_stub` / `meds_stub` with fixture locators so verify can pass |
| Draft | Haiku → claims JSON only (temp ~0) |
| Verify | **Deterministic Python** locator ∈ tool results; drop otherwise |
| Prose | **Assemble after verify** (template join); no token-stream clinical |
| Clinical SSE | **Single** `clinical` event after verify |
| Zero claims | Honest empty `clinical` + refusals → `done` (not `error`) |
| Meds / research | Dosing/interaction **refusal** always in PRD 03 |
| Unverified blocks | Not used; omit/refuse |
| Health | `/health` alive; `/ready` tool_proxy + OpenRouter dialable |
| Ready | Soft — do **not** crash-loop Compose on OpenRouter blips |
| LangSmith / checkpointer | Out of scope / none |

### Rationale

Decision guide: spine step 3 real; clinical safety > cleverness; code verify is the interviewable gate; gateway stubs keep pid fail-closed live before PRD 04; thin health/ready for DO smoke (LangSmith stays 07).

### Patterns/Libraries

Python 3.11+: `fastapi`, `uvicorn`, `langgraph`, `httpx`, OpenAI-compatible OpenRouter client. SSE framing identical to PRD 02. Logs carry correlation id; no note-body dumps.

### Code Organization

```
sidecar/
  Dockerfile
  requirements.txt
  app/
    main.py              # /v1/chat, /health, /ready
    auth.py              # secret compare
    sse.py / state.py / graph.py / llm.py / gateway_client.py / claims.py
    nodes/               # refuse, route, tools, draft, verify, emit
  tests/
    test_verify.py
    test_claims_parse.py
```

PHP: only enrich `ToolProxyService` stub payloads if needed; keep fail-closed logic.

### Env (sidecar)

| Variable | Purpose |
| --- | --- |
| `COPILOT_INTERNAL_SECRET` | Shared with OpenEMR |
| `COPILOT_GATEWAY_TOOL_URL` | Full URL to `tool_proxy.php` (Compose DNS) |
| `OPENROUTER_API_KEY` | Required |
| `OPENROUTER_MODEL` | Pin Haiku id at implement time |
| `OPENROUTER_BASE_URL` | Default `https://openrouter.ai/api/v1` |
| `COPILOT_LLM_TIMEOUT_SECONDS` | Default `30` |
| `COPILOT_TOOL_TIMEOUT_SECONDS` | Default `10` |

---

## 4. Implementation Guidance

### Step-by-Step Plan

1. **Confirm PRD 02** works (gateway, secret, tool_proxy, SSE proxy).
2. **Scaffold FastAPI** replacing stub: secret on `/v1/chat`; `/health`; `/ready` probes.
3. **`GatewayClient.call_tool`** — secret + correlation + pid; typed errors on 401/403/5xx/timeout.
4. **Enrich stub payloads** in PHP (preferred) with stable fixture facts/locators, e.g. `data.facts[{text,table,id,excerpt}]` for `patient_context_stub` / `labs_stub` / `meds_stub`.
5. **Graph state:** `correlation_id`, `pid`, `message`, `transcript`, `route`, `tool_results`, `draft_claims`, `verified_claims`, `refusals`, `clinical_text`, `error`.
6. **Nodes:**
   - **refuse:** pid null/≤0 → no tools/LLM clinical path; short refuse clinical → done (defense in depth).
   - **route:** Haiku classifier; emit `progress` (“Routing…”).
   - **tools:** route→tool list; parallel where safe; `progress` (“Fetching chart…”); ≤3 calls.
   - **draft:** truncated transcript + tool JSON → claims JSON; parse fail → SSE `error`.
   - **verify:** locator membership; log drops; append meds dosing refusal.
   - **emit:** assemble prose → one `clinical` → `done`.
7. **SSE writer:** flush progress from nodes; **buffer** clinical until verify completes.
8. **Compose:** rebuild image; OpenRouter env; `--workers 1`; no host port publish.
9. **Smoke local then DO:** Synthea patient → progress → verified/refuse clinical (no `Stub sidecar:`) → done; bad key → generic `error`.

### Key Functions/Methods

| Piece | Responsibility |
| --- | --- |
| `verify_claims(draft, tool_index)` | Locator membership; cite-or-silence |
| `assemble_clinical(verified, refusals)` | Concise prose; no invented facts |
| `route_message` / `draft_claims` | Haiku calls |
| `GatewayClient.call_tool` | Secret + correlation + pid |
| `stream_chat` | Graph → SSE |

### Data Flow

```
Browser → stream.php (session, CSRF, bind, correlation)
  → POST sidecar /v1/chat
       → refuse? → clinical refuse → done
       → route (Haiku) → tools → tool_proxy
       → draft (Haiku) → verify (code) → clinical → done
  → gateway proxies SSE → browser
```

### Complex Logic — Verify

1. Index tool facts into keys `(table, id)`.
2. Each draft claim must match; else **drop** (no fuzzy repair).
3. `source_type == research` with no research tool → drop.
4. Only survivors feed `assemble_clinical`.

```python
def verify_claims(draft, tool_index: set[tuple[str, str]]):
    return [
        c for c in draft.claims
        if c.locator.get("table") and c.locator.get("id")
        and (c.locator["table"], str(c.locator["id"])) in tool_index
    ]
```

Draft parse: JSON mode if available; else first JSON object; failure → `error` SSE.

---

## 5. Edge Cases and Error Handling

### Edge Cases

| Case | Behavior |
| --- | --- |
| Missing/invalid pid | Refuse; no chart tools |
| Empty message | `error` if reached |
| Multi-intent | Primary route only |
| Huge transcript | Truncate to 8 turns |
| All claims fail verify | Honest empty `clinical` + refusals → `done` |
| Stubs without facts | Same as zero claims |
| Meds / dosing ask | Verified stub facts + dosing refusal |
| Patient switch | Gateway `bound_pid`; sidecar never takes pid from transcript/model |
| Concurrent Send | UI disables; document one-worker limit |
| Invented locators / prompt injection | Verify drops; tools use gateway pid only |

### Error Scenarios

| Failure | Handling |
| --- | --- |
| Bad secret | HTTP 401 |
| OpenRouter down/timeout/auth | Log + generic SSE `error` |
| Tool proxy auth failure | Log + SSE `error` |
| Draft JSON parse fail | SSE `error` |
| Gateway ~45s timeout | Keep budgets under it |

### Validation / Messages

- Secret + `correlation_id` required; echo id on `done`.
- Progress copy must stay non-clinical.
- User-facing: `Something went wrong. Try again.` · unbound: `Select a patient before asking about the chart.` · empty verify: `Not enough verified chart data to answer from the record.` · dosing: `No retrieved label source for dosing — I won't guess.`
- Never send tracebacks / OpenRouter raw errors to the browser.

---

## 6. Likely Pitfalls to Avoid

- Streaming Haiku tokens as `clinical` before verify; LLM-as-judge verify.
- SQL from sidecar; trusting model pid; renaming SSE events.
- PHP session held open; proxy not flushing `progress`.
- `/ready` wired to hard Compose restarts on OpenRouter blips.
- Floating model id; unbounded transcript; multiple uvicorn workers.
- 2 GB OOM from fat image; secrets in SSE/JS; public sidecar port.
- `COPILOT_GATEWAY_TOOL_URL` using `localhost` instead of Compose DNS `openemr`.
- Exceeding tool_proxy bind-cache TTL (~10 min from PRD 02) — stay well under.

---

## 7. Testing Requirements

### Scenarios

1. Happy path: progress → clinical from verified stub claims → done.  
2. Invented locator dropped from clinical text.  
3. Meds route includes dosing refusal.  
4. Missing pid → refuse; no tool/LLM clinical path.  
5. Bad secret → 401.  
6. OpenRouter failure → generic `error`.  
7. Invalid draft JSON → `error`.  
8. `/health` 200; `/ready` with mocks.

### Unit / Integration / Manual

- **Unit:** `verify_claims`, `assemble_clinical`, JSON parse, route normalization.  
- **Integration (optional):** TestClient `/v1/chat` with mocked OpenRouter + tool_proxy.  
- **Manual:** Local + **DO** Synthea patient; UI parses SSE; Send re-enables on terminal event.  
- **Data:** Stub fixture locators; any bound Synthea pid.

---

## 8. Acceptance Criteria

### Functional

- [ ] Stub replaced by FastAPI + LangGraph one-worker service.  
- [ ] Graph: refuse → route → tools → draft → verify → emit.  
- [ ] Chart tools only via `tool_proxy` (secret + pid + correlation id).  
- [ ] Haiku for route + draft; verify is code-only.  
- [ ] Hybrid SSE: progress before clinical; clinical only after verify; single clinical event.  
- [ ] Invented locators never appear in `clinical`.  
- [ ] Meds path includes explicit dosing refusal.  
- [ ] `/health` + `/ready` per §3; claim schema used.  
- [ ] Sidecar not public; browser never contacts sidecar.

### User-Facing / Perf / Security

Physician sees non-clinical progress, then concise post-verify answer (or honest empty/refuse), then completion; failures are generic. First `progress` typically &lt; 2s; full turn under ~45s. Secrets stay server-side; pid fail-closed preserved; minimize prompt PHI.

---

## 9. Dependencies and Considerations

### External / Config

- **OpenRouter** (required); gateway tool_proxy (required); no research APIs.  
- Sidecar env: secret, gateway tool URL, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, timeouts.  
- OpenEMR: PRD 02 vars unchanged. Document DO `/opt/openemr` rebuild + env.

### DB / Breaking / Migration

- No migrations.  
- Removes `Stub sidecar:` echo (intentional); may extend stub tool payloads.  
- Steps: land PRD 02 → deploy sidecar + env (local then DO) → smoke Send → update Memory Bank (step 3 done; defer 04–07).

---

## 10. Project Notes from Ticket

### Important Notes

- Spine step 3 must be **real** (graph + Haiku + code verify + hybrid SSE). Stub **chart data** OK until PRD 04.  
- Interview line: “Agent drafts structured claims; verify drops anything without a resolvable source; UI only sees post-verify clinical text.”  
- Live DO is demo source of truth. Distinguish LangGraph (workflow) vs LangSmith (traces — later).

### Assumptions

- PRD 01/02 SSE names and `/v1/chat` body hold; OpenRouter key on local + DO; one concurrent physician OK.

### Deferred

PRD 04 chart services · PRD 05 research · PRD 06 citations · PRD 07 LangSmith · ReAct/checkpointer/chat DB · full domain verify (allergy/RxNorm polish) · SMART/FHIR-primary · per-turn tool tickets.

---

## 11. Attachments and References

- No Jira attachments.  
- Canonical: `ARCHITECTURE.md` · Decisions: `docs/ai-decision-guide.md` + planning chat  
- Prior: `docs/PRDs/01-ask-copilot-tab.md`, `docs/PRDs/02-session-proxy-gateway.md`  
- Diagrams: `docs/architecture-overview.md`
