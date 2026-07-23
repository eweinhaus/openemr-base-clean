# Clinical Co-Pilot — Eval results

**Date:** 2026-07-22  
**Catalog:** [`catalog.md`](./catalog.md)  
**Harness:** `pytest sidecar/tests/` (mocked LLM + gateway) — cases **E-\*** map 1:1 to the catalog table.

## How this run is defined

There is no separate golden-file clinical eval corpus. The defensible MVP record is the sidecar regression suite: each catalog ID names the failure mode and points at the pytest that encodes expected behavior.

**E-CONFLICT** is **deferred** (openFDA→DailyMed fallback-only). It is listed in the catalog for honesty and is **not** expected to pass as a conflict-surface test.

## Re-run (authoritative)

From repo root:

```bash
pip install -r sidecar/requirements.txt pytest
export COPILOT_INTERNAL_SECRET=test-secret
pytest sidecar/tests/ -q
```

Paste the pytest summary below after a clean run on the commit you are grading. Do **not** invent pass counts.

## Recorded run — 2026-07-22

**Command:** `unset COPILOT_INTERNAL_SECRET; pytest sidecar/tests/ -q`  
(conftest sets `COPILOT_INTERNAL_SECRET=test-secret-for-pytest`)

**Representative summary:**

```text
164 passed, 2 warnings in 0.74s
```

| Case ID | Mapped? | Notes |
| --- | --- | --- |
| E-UNBOUND | yes | pytest |
| E-EMPTY | yes | pytest |
| E-RXNORM | yes | pytest |
| E-MISS | yes | pytest |
| E-AMBIG | yes | pytest |
| E-HALLUC | yes | pytest |
| E-UC1 | yes | pytest |
| E-UC2 | yes | pytest |
| E-UC3 | yes | pytest |
| E-CITE | yes | pytest |
| E-XPID | yes | pytest |
| E-ALLERGY | yes | `test_verify_node_allergy_contradiction_drops_research` |
| E-CONFLICT | deferred | No test; MVP does not surface dual-source conflicts |

## Interpretation

- **Pass** means the named failure mode is enforced under mock boundaries (auth, empty facts, research miss, hallucinated locators, citation pairing, etc.).
- **Not** a substitute for live physician demo smoke on https://142.93.255.212/ (session + OpenRouter).
- Single-worker / 2 GB limits are load concerns (`docs/load-tests/`), not eval catalog outcomes.
