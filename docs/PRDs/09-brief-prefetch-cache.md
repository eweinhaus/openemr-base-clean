# PRD 09 — Brief Prefetch Cache (UC-1 Pre-Ask)

**Roadmap step:** Post–PRD 08 enhancement to UC-1 pre-visit brief latency  
**Goal:** Background-prefetch verified brief payloads for the **top three patients on today's schedule picker**, so auto-brief on patient bind returns **instantly** (SSE replay) instead of running the full graph.  
**Non-goal:** Redis/durable cache, multi-worker queue, auto-brief UX change (already shipped), cache on `labs`/`meds` routes, new SSE event types, weakening interactive pid bind, prefetch for off-schedule Finder patients.

---

## 1. Problem Statement and Context

### What

Today, selecting a patient from the Ask Co-Pilot picker **auto-sends** `"Brief me on this patient."` and runs the full LangGraph path: route → four chart tools → draft → verify → synthesize → emit. Tool fan-in plus three Haiku calls can exceed the physician's ~30–90s between-rooms budget on first touch.

PRD 04 deliberately gathers **all four chart tools on brief** because a TTL cache was planned. PRD 08 added synthesize (+1 Haiku). This PRD implements **pre-ask prefetch + serve-from-cache** so the rich brief shape stays intact while bind → auto-brief feels instant when prefetch completed.

### Background

- **UC-1 job** (`USER.md`): pre-visit synthesis in seconds.
- **Physician UX** (`docs/ai-decision-guide.md` §2, §5, §6): keep rich parallel gather; accept uncached latency only as fallback; post-cache must fit the ~90s window.
- **Auto-brief on bind** is already coded: `selectPatient()` → `sendMessage(autoBriefMessage)` in `interface/ask_copilot/assets/ask_copilot.js`.
- **Schedule picker** exposes `next_pid` + chronological `appointments` via `ProviderDayScheduleService` / `schedule.php`.
- **Single worker / 2 GB** — prefetch must be sequential and deferrable; no new infra.

### Related Work

| Doc / code | Role |
| --- | --- |
| `docs/PRDs/04-chart-tools.md` | Brief four-tool bundle = cache unit (deferred impl) |
| `docs/PRDs/06-citations-hybrid-sse.md` | Serve hits via existing `clinical` → `citation` → `done` |
| `docs/PRDs/08-brief-narrative-synthesis.md` | Cache stores post-synthesize payload (`kind:summary` + claims) |
| `docs/ai-decision-guide.md` §8 | Auth/pid locks — schedule-scoped prefetch only |
| `sidecar/app/main.py` | Readiness TTL cache pattern (~30s) to mirror |
| `src/ClinicalCopilot/Gateway/FileCorrelationBindStore.php` | Per-correlation pid bind for tool_proxy |

**Depends on:** PRDs 04, 06, 08 (landed). **Does not block:** PRD 07 observability extensions.

### Project Notes (planning session 2026-07-23)

- **Trigger:** Ask Co-Pilot tab open (after schedule load) **and** re-prefetch after each successful patient bind.
- **Prefetch set:** First **3 unique pids** in picker display order — Next card, then remaining appointments (skip duplicate next row in list).
- **TTL:** 30 minutes hard expire; soft re-prefetch if tab re-opened and entry age > 10 minutes.
- **Cache tier:** Full emit payload (not tool snapshot only).
- **Miss behavior:** Uncached full graph (unchanged).
- Demo smoke: local admin schedule seeds pids **6, 8, 2**; rich brief on **pid 6**.

---

## 2. Technical Context

### Relevant Files/Modules

| Path | Change |
| --- | --- |
| `src/ClinicalCopilot/Schedule/SchedulePrefetchSelector.php` | **New** — top-3 pid list (picker parity) |
| `tests/Tests/Isolated/ClinicalCopilot/Schedule/SchedulePrefetchSelectorTest.php` | **New** |
| `interface/ask_copilot/prefetch.php` | **New** — session auth → kick sidecar prefetch |
| `interface/ask_copilot/assets/ask_copilot.js` | Fire prefetch after schedule load + after bind auto-brief completes |
| `interface/ask_copilot/index.php` | `prefetchUrl` config |
| `src/ClinicalCopilot/Gateway/PrefetchBriefService.php` | **New** — validate schedule scope, mint binds, call sidecar |
| `src/ClinicalCopilot/Gateway/SidecarClient.php` | `postPrefetch()` (non-SSE JSON) |
| `src/ClinicalCopilot/Gateway/FileCorrelationBindStore.php` | Used for prefetch correlation binds |
| `sidecar/app/brief_cache.py` | **New** — in-memory store + TTL |
| `sidecar/app/prefetch.py` | **New** — queue, run brief graph, store payload |
| `sidecar/app/main.py` | `POST /v1/prefetch-brief`, cache check hook in chat path |
| `sidecar/app/stream.py` | Cache hit → replay SSE without graph |
| `sidecar/app/llm.py` | `is_auto_brief_message()` helper (normalized match) |
| `sidecar/tests/test_brief_cache.py` | **New** |
| `sidecar/tests/test_prefetch.py` | **New** |
| `sidecar/tests/test_chat_integration.py` | Cache hit regression |
| `tests/js/ask-copilot-patient-picker.test.js` | Prefetch fetch after schedule |
| `memory-bank/activeContext.md` | Record prefetch locks |
| `docs/ai-decision-guide.md` | Note post-cache UC-1 latency expectation met |

### Similar Implementations

- **Readiness cache** (`sidecar/app/main.py` `_ready_cache_*`) — process-local TTL dict pattern.
- **Schedule builder** (`ProviderDayScheduleBuilder` + `NextAppointmentSelector`) — reuse for next index.
- **Picker render order** (`ask_copilot.js` `renderSchedule`) — prefetch selector must mirror display order.
- **Graph brief path** (`graph.py` verify → synthesize → emit) — prefetch runs same graph with fixed message.

### Architecture Notes

- **Interactive bind unchanged:** `stream.php` still binds correlation to **session pid** only.
- **Prefetch bind:** Gateway creates a **separate correlation id** per prefetch job with `(user_id, target_pid)`; sidecar tool calls use that correlation. Target pid must appear on provider's today schedule (server-computed).
- **Verify at prefetch time:** Cache stores only post-verify + post-synthesize emit output. Serve path does **not** re-run verify or LLM.
- **Hybrid SSE unchanged on serve:** replay `clinical` `{text, segments}` → `citation` `{citations}` → `done` (PRD 06). Optional single progress or typing indicator only — no fake multi-step progress.
- **Research:** Prefetch brief never calls openFDA (H11 — brief route only).

### Database/API Context

**No schema migrations.**

**New internal endpoints:**

```http
POST /interface/ask_copilot/prefetch.php
  Session cookie + CSRF POST
  Body: (empty — server computes pids from schedule)
  Response: 202 JSON { "queued": [pid...], "skipped": "reason?" }

POST /v1/prefetch-brief  (sidecar, internal secret)
  { "user_id": int, "username": str, "pid": int, "correlation_id": str, "prefetch": true }
  Response: 200 JSON { "ok": true, "cached": true } | { "ok": false, "error": "..." }
```

**Cache entry shape (sidecar in-memory):**

```python
{
  "user_id": int,
  "pid": int,
  "schema_version": 1,
  "created_at": float,
  "expires_at": float,
  "correlation_id": str,  # prefetch verify/disclosure join
  "clinical_text": str,
  "clinical_segments": list,
  "citations": list,
}
```

**Cache key:** `(user_id, pid, schema_version=1)` — never `correlation_id`.

---

## 3. Design Decisions (Pre-Made)

### Approach

**Schedule-scoped background prefetch + full-payload sidecar cache + SSE replay on auto-brief cache hit.**

| Decision | Choice | Rationale |
| --- | --- | --- |
| Trigger | Tab open after `loadSchedule()` success; **re-prefetch after each bind** auto-brief completes | Warms next patients as day progresses |
| Prefetch set | Top 3 unique pids in **picker display order** | Matches physician mental model |
| Who computes pids | **PHP server only** | Client cannot request arbitrary pids |
| Cache contents | Full emit payload post-synthesize | Instant auto-brief; PRD 08 shape preserved |
| Cache location | Sidecar process memory | MVP single-worker; no Redis |
| TTL | **30 min** hard; **10 min** soft refresh on tab re-open | Login/tab-open prefetch useless at 60s |
| Prefetch concurrency | **Sequential** queue, max 1 active prefetch | 2 GB single worker |
| Prefetch vs chat | Defer prefetch if `/v1/chat` SSE active | Don't starve interactive turns |
| Auth | Schedule membership + `patients/demo` ACL | Fail-closed; no weakening session bind |
| Brief detection on serve | Normalized message matches auto-brief string **and** empty/single-turn transcript | Avoid serving cache on follow-ups |
| Partial prefetch failure | Do not cache failed turns; miss on serve | No stale/error payloads as hits |
| Feature flag | None | Demo path always on when sidecar ready |
| New SSE events | None | Replay PRD 06 contract |

### Patterns/Libraries

- PHP: `SchedulePrefetchSelector` isolated tests (no BaseService DB bootstrap).
- Sidecar: reuse `build_graph()`, `iter_chat_events` internals or shared `run_brief_to_emit()` helper.
- JS: fire-and-forget `fetch(prefetchUrl, { method: 'POST' })` — no await blocking picker.
- Env: `COPILOT_BRIEF_CACHE_TTL_SECONDS` default `1800`; `COPILOT_BRIEF_CACHE_SOFT_REFRESH_SECONDS` default `600`.

### Code Organization

```
src/ClinicalCopilot/Schedule/SchedulePrefetchSelector.php
src/ClinicalCopilot/Gateway/PrefetchBriefService.php
interface/ask_copilot/prefetch.php
sidecar/app/brief_cache.py
sidecar/app/prefetch.py
```

---

## 4. Implementation Guidance

### Step-by-Step Plan

1. **`SchedulePrefetchSelector`** — Input: `ProviderDaySchedule`. Output: `list<int>` max 3 unique pids:
   - Find `nextIndex` where `appointments[i].pid === nextPid` (same as `renderSchedule`).
   - If `nextIndex >= 0`, append that pid.
   - Iterate `appointments` in order; append pid if not already in list; stop at 3.
2. **`prefetch.php`** — POST + CSRF + ACL; `session_write_close()` early; call `PrefetchBriefService::queueTodayTopThree($authUserId)`.
3. **`PrefetchBriefService`** — Load schedule via `ProviderDayScheduleService`; if empty, return `{ queued: [] }`. For each pid: mint correlation id, `bindStore->put(correlationId, pid, userId)`, POST sidecar `/v1/prefetch-brief` (async fire-and-forget from PHP — use short timeout, sidecar queues internally).
4. **`brief_cache.py`** — Thread-safe dict; `get(user_id, pid)`, `put(...)`, `prune_expired()`, TTL from settings.
5. **`prefetch.py`** — Module-level queue + lock; worker runs one job at a time; skip if chat active flag set; on job: run brief graph with `message="Brief me on this patient."`, `route` forced to `brief` (skip route LLM — set state directly), store emit fields on success (≥1 verified claim per verify heuristic).
6. **`main.py`** — Add `/v1/prefetch-brief`; increment queue; return 202 immediately.
7. **`stream.py` / chat path** — Before graph: if `is_auto_brief_message(message)` and transcript empty-ish and cache hit for `(user_id, pid)`: yield cached clinical + citation + done; log `cached_serve`. Else existing graph.
8. **`ask_copilot.js`** — After successful `loadSchedule()`: call `triggerPrefetch()`. After `sendMessage(autoBrief)` resolves (stream done): call `triggerPrefetch()` again.
9. **Disclosure** — Prefetch graph runs normal verify callback. On cache serve, append disclosure stub `event=ask_start` with `cached: true` or extend JSONL with `event=brief_cache_serve` (pick one; document in Memory Bank).
10. **Tests + docs** — PHPUnit selector; pytest cache/prefetch/integration; Jest prefetch fetch; update Memory Bank.

### Key Functions/Methods

| Function | Location | Purpose |
| --- | --- | --- |
| `SchedulePrefetchSelector::topPids(ProviderDaySchedule, int $limit = 3)` | PHP | Picker-parity pid list |
| `PrefetchBriefService::queueTodayTopThree(int $providerUserId)` | PHP | Auth + schedule scope + sidecar kick |
| `BriefCache.get / put / delete` | `brief_cache.py` | TTL store |
| `enqueue_prefetch(...)` / `_run_prefetch_job(...)` | `prefetch.py` | Sequential worker |
| `is_auto_brief_message(message: str) -> bool` | `llm.py` | Normalized brief intent |
| `try_cached_brief_response(...)` | `stream.py` | SSE replay |

### Data Flow

```
Tab open → schedule.php → JS renderSchedule → POST prefetch.php
  → PHP: top 3 pids → bindStore per pid → sidecar /v1/prefetch-brief (×3 queued)
  → sidecar: brief graph (tools→draft→verify→synthesize→emit) → brief_cache.put

Physician selects patient → bind → auto sendMessage("Brief me...")
  → stream.php → sidecar /v1/chat
  → cache hit? replay clinical+citation+done : full graph

Auto-brief done → JS triggerPrefetch() → refresh top 3 for rolling queue
```

### Complex Logic: `SchedulePrefetchSelector`

**Must match `renderSchedule` in JS:**

```php
// Pseudocode
$pids = [];
$nextPid = $schedule->nextPid;
$nextIndex = -1;
foreach ($schedule->appointments as $i => $appt) {
    if ($nextPid !== null && $appt->pid === $nextPid) {
        $nextIndex = $i;
        break;
    }
}
if ($nextIndex >= 0) {
    $pids[] = $schedule->appointments[$nextIndex]->pid;
}
foreach ($schedule->appointments as $j => $appt) {
    if ($j === $nextIndex) {
        continue;
    }
    if (!in_array($appt->pid, $pids, true)) {
        $pids[] = $appt->pid;
    }
    if (count($pids) >= 3) {
        break;
    }
}
return $pids;
```

**Schedule scope check for prefetch:** `in_array($pid, $allSchedulePids, true)` where `$allSchedulePids` = unique pids from today's non-terminal appointments.

### Complex Logic: Prefetch graph shortcut

- Set initial state: `route="brief"`; **skip `route_node` LLM** via graph entry or conditional edge from START when `prefetch=true` flag in state.
- Message fixed: `"Brief me on this patient."`
- Transcript: `[]`
- On zero verified claims after verify: **do not cache** (log warning).
- On synthesize guard fail: cache **claims-only** payload (no summary segment) — still valid partial win.

---

## 5. Edge Cases and Error Handling

| Scenario | Behavior |
| --- | --- |
| Empty schedule | `prefetch.php` returns `{ queued: [] }`; no sidecar calls |
| Fewer than 3 appointments | Prefetch 1–2 pids only |
| Duplicate pid on schedule | Dedupe — one brief per pid |
| Prefetch not finished before bind | Cache miss → uncached graph (existing UX) |
| Sidecar `/ready` false | Skip prefetch; log; auto-brief uses uncached path |
| Prefetch tool partial failure | Same as normal brief — cache if ≥1 verified claim |
| Finder / off-schedule patient | Never prefetched; always full graph |
| Follow-up after brief ("What's creatinine?") | Never cache serve — route labs/meds |
| User change-patient mid-stream | Don't prefetch while `streaming === true` |
| Session user mismatch | Cache key includes `user_id` — no cross-user hits |
| Tab re-open after 10+ min | Soft re-prefetch replaces stale entries |
| TTL expired | Miss; background prefetch may repopulate |

### Error Messages

No new physician-facing error codes. Prefetch failure is silent; interactive path unchanged.

---

## 6. Likely Pitfalls to Avoid

1. **Weakening interactive pid bind** — prefetch correlation binds are separate; `stream.php` session bind unchanged.
2. **Client-supplied pid list** — always server-compute from schedule.
3. **Caching draft or unverified text** — only post-verify emit payload.
4. **Parallel prefetch jobs** — sequential only on 2 GB worker.
5. **Blocking picker on prefetch** — fire-and-forget POST.
6. **Serving cache on labs/meds follow-ups** — brief message + empty transcript gate only.
7. **Keying cache by correlation_id** — use `(user_id, pid, schema_version)`.
8. **Caching failed verify turns** — omit from cache.
9. **Skipping dedupe** — same pid twice on schedule must not double queue.
10. **New SSE event types** — replay existing events only.
11. **Thinning brief to one tool** — breaks PRD 04 cache bundle (ai-decision-guide §12).
12. **Prefetch during active SSE** — defer queue.
13. **Missing disclosure on prefetch** — tool_proxy + verify must still log.
14. **Deploy PHP without sidecar** — ship together; cache empty until sidecar up.

---

## 7. Testing Requirements

### Unit Tests

**PHP `SchedulePrefetchSelectorTest`:**
- Next card + two list rows → 3 pids in display order.
- `next_pid` first in list — not duplicated.
- Duplicate pid on schedule → one entry.
- One appointment → one pid.
- Empty appointments → `[]`.

**Python `test_brief_cache.py`:**
- put/get hit within TTL.
- miss after expiry.
- user_id isolation.
- schema_version mismatch → miss.

**Python `test_prefetch.py`:**
- queue serializes jobs.
- skip cache on zero verified claims.
- prefetch flag skips route LLM (mock).

### Integration (`test_chat_integration.py`)

- Seed cache → `/v1/chat` with auto-brief message → SSE has clinical+citation without mock LLM.
- Labs message with warm cache → full graph (no cache serve).

### Jest

- After mock schedule fetch, `prefetch.php` POST called once.
- After mock bind + stream complete, prefetch POST called again.

### Manual Testing

| Step | Action | Expected |
| --- | --- | --- |
| M1 | Open tab; wait ~60s; bind pid 6 | Auto-brief appears quickly (cache hit) |
| M2 | Bind before prefetch completes | Brief still appears (uncached, slower) |
| M3 | After pid 6, bind pid 8 | Second bind faster if prefetch finished |
| M4 | Finder off-schedule patient | Slower uncached brief |
| M5 | Follow-up "What's creatinine?" | No cache; labs shape |

---

## 8. Acceptance Criteria

### Functional

- [ ] Tab open triggers background prefetch for ≤3 schedule pids (server-computed).
- [ ] Re-prefetch fires after each auto-brief stream completes.
- [ ] Cache stores full PRD 08 brief payload (summary + claims + citations when synthesis succeeded).
- [ ] Auto-brief cache hit replays `clinical` → `citation` → `done` without LLM/graph.
- [ ] Cache miss runs unchanged full graph.
- [ ] Off-schedule / Finder patients never hit prefetch cache.
- [ ] Labs/meds follow-ups never serve brief cache.
- [ ] Prefetch uses schedule-scoped auth; arbitrary pid rejected.
- [ ] TTL 30 minutes; entries soft-refresh after 10 minutes on tab re-open prefetch.

### User-Facing

- [ ] Physician selects next patient → brief appears without multi-step wait when prefetch completed.
- [ ] Sources still work on cached brief (citation batch replayed).

### Performance

- [ ] Prefetch does not block picker or composer.
- [ ] At most one prefetch graph runs at a time.
- [ ] Cache hit auto-brief p95 **≤ 2s** (network + SSE replay).

### Security

- [ ] Cache keyed by `user_id` + `pid`.
- [ ] Prefetch pid ⊆ provider today schedule.
- [ ] No browser calls to sidecar directly.

---

## 9. Dependencies and Considerations

### External Services

- OpenRouter Haiku (prefetch burns up to 3× route+draft+synthesize per prefetch cycle — acceptable for demo).
- Existing gateway tool_proxy + disclosure paths.

### Configuration

| Env | Default | Purpose |
| --- | --- | --- |
| `COPILOT_BRIEF_CACHE_TTL_SECONDS` | `1800` | Hard cache expiry |
| `COPILOT_BRIEF_CACHE_SOFT_REFRESH_SECONDS` | `600` | Re-prefetch stale entries |
| `COPILOT_BRIEF_CACHE_SCHEMA_VERSION` | `1` | Bump to invalidate all entries |

### Breaking Changes

None for API consumers. Auto-brief latency improves when cache warm.

### Migration

Deploy PHP + sidecar together. No data migration.

### Deferred

- Redis/shared cache for multi-worker.
- Visible "Prepared at …" staleness UI.
- Invalidate on chart write webhooks.
- Prefetch on global OpenEMR login (tab open only for MVP).

---

## 10. Hard Invariants

| # | Invariant | Enforcement |
| --- | --- | --- |
| H1 | Cache serve only for auto-brief message + non-follow-up transcript | `stream.py` + tests |
| H2 | Cached payload = post-verify (+ synthesize when present) | prefetch store path |
| H3 | Prefetch pid ∈ today provider schedule | PHP gate |
| H4 | Interactive session bind unchanged | stream.php review |
| H5 | SSE order on serve: clinical → citation → done | integration test |
| H6 | Brief prefetch never calls research | tools_node H11 |
| H7 | Sequential prefetch worker | prefetch queue |
| H8 | No cache entry without ≥1 verified claim | prefetch store guard |

---

## 11. Attachments and References

- Planning conversation: brief prefetch architecture (2026-07-23).
- Code anchors: `ask_copilot.js` `renderSchedule`, `selectPatient`, `loadSchedule`; `ProviderDayScheduleBuilder`; `sidecar/app/main.py` readiness cache; PRD 04 § deferred cache note.
- No Jira ticket attachments.

---

## 12. Acceptance Checklist (PR)

- [ ] `SchedulePrefetchSelector` + tests
- [ ] `prefetch.php` + `PrefetchBriefService` + `SidecarClient::postPrefetch`
- [ ] Sidecar cache + prefetch queue + `/v1/prefetch-brief`
- [ ] Chat cache serve path + tests
- [ ] JS trigger on schedule load + post auto-brief
- [ ] Memory Bank + ai-decision-guide note
- [ ] Manual M1–M3 on local demo schedule (pids 6/8/2)
