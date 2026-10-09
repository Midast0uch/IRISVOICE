# Ripple Map: every file this spec touches

Produced in review, 2026-10-08 (session 392). Line numbers drift; search by the
function or symbol named. **This is the coverage list — a change to a file not
listed here is a spec violation, and a file listed here that a wave does not
touch must be said to be untouched, not silently skipped.**

## The chokepoints (a change here is felt everywhere)

| File / symbol | What changes | Waves | Ripple if wrong |
|---|---|---|---|
| `backend/agent/decision_engine.py` `CONSUMERS` | +`depth_route`, +`call_closing` (AC9.1 ex. 2, 3) | 1 | CT-DE-7 asserts EXACT set equality — it **must** change in the same commit |
| `decision_engine.py` `CONSUMER_JOBS` | −`browser_next`, −`web_depth` (AC9.1 ex. 1); +`call_closing` | 1 | 19 → 17 + 1. `oracle_job()` falls back to `general` for unknowns, so an unremoved dead entry silently routes |
| `decision_engine.py` `ORACLE_JOBS` | `guard` gains an image declaration (AC9.1 ex. 4). Text fields unchanged | 4 | `job_input()` builds the state; AC3.5 field-presence test keys off this |
| `decision_engine.py` `ConsumerSpec` | `criteria: bool` → typed criteria; `decision_type` required (REQ-4) | 1 | Every registration site must pass a type. A missing one scores nothing (AC1.6) — fail-closed, but silent |
| `decision_engine.py` `decide()` / `noul()` | transports to the batched path (REQ-7); letter scoring removed (AC1.4) | 2, 6 | The engine lock is taken once per pass, so batching **reduces** contention (design §8) |
| `decision_engine.py` `_current_backend_identity()` | key becomes `model_id\|readout_mode\|criteria_hash` (AC2.1) | 3 | Feeds `threshold_for()` and `oracle_calibration.threshold()`. Wrong key = stale flips stand |
| `decision_engine.py` `job_input()` | returns a structured `OracleState`, renders ALL declared fields (AC3.1) | 4 | 4 of 8 jobs currently send byte-identical input; the fix changes what the model sees, so it is a behaviour change, not a refactor |
| `decision_backend_d1.py` `decide()` | route → `/v1/chat/completions`; named-criteria + noul + score renderers; BOTH logprob shapes (AC1.1-1.3, AC0.3) | 2 | `bytes[0]` as a token id = character code = silent void. The single most dangerous line in the spec |
| `decision_backend_d1.py:360` | stops reading only `frame["goal"]` (AC3.2) | 4 | The budget cap moves with it (AC3.4) |
| `decision_backend_d1.py:376-379` | the `len(opts)==2` noul heuristic is **deleted** (AC4.3) | 1 | Must come AFTER every consumer is declared, or an undeclared consumer scores nothing |
| `decision_backend_d1.py` `_ensure_letter_ids` | vocabulary extends from letters/yes-no to criterion NAMES and level tokens | 2 | A name that is not single-token silently drops that option from the readout |

## Row production and the store (where the truth has to survive)

| File / symbol | What changes | Waves | Ripple if wrong |
|---|---|---|---|
| `tool_bridge.py:2649-2657` dedup key | scope added, OR dedup moved after labelling (**AC6.3a-1**) | 5 | **Do nothing and every JOIN is a biased subset.** This is the spec's central measurement |
| `tool_bridge.py` `record_decision` | row payload gains `turn_id`, `step_id`, call ordinal (AC6.3a) | 5 | The join has no key without it |
| `surface_shadow.py` `shadow_row()` / `_submit_shadow()` | add scope to the row; count excluded rows (AC10.2, AC10.5) | 1, 5 | An excluded row must be COUNTED, never silently dropped (repo standard) |
| `monitor_shadow.py` (done, sufficient) | same, plus **the lane→ledger path that still drops rows** (T5.11) | 5 | `agent_kernel.py:20945-20949` records the bare-`pass` bug as FIXED, yet `done` still reads 0 rows. The fix did not restore the path |
| `surface_shadow.py` `register_surface_consumers()` | pass a declared type (REQ-4) | 1 | Idempotence (`get_consumer_spec(cid) is not None`) means an already-registered consumer is **never upgraded** — a stale spec persists across the change |
| `event_oracle.py` `register_consumers()` | dynamic `event_type:*` consumers need a type rule (**REQ-13.5**) | 1 | They are not in `CONSUMERS`; no declared criteria exists for them |

## The DAG and the node loop (must not move)

| File / symbol | What changes | Waves | Ripple if wrong |
|---|---|---|---|
| `node_executor.py:629` / `:648` closing return | **READ ONLY by this spec** — it is the truth source for `call_closing` (AC10.4) | 5 | If it changes, every historical `call_closing` label silently changes meaning |
| `node_executor.py:629` batch_changed | the changed-file exclusion reads this (AC10.5) | 5 | |
| `node_executor.py` the loop (`:453`), `_CLOSE_ARGS`, `step_done` | candidate detection — asks only about calls that CLAIMED done (AC10.2) | 5 | Asking about every call is 12x the cost and measures the uninteresting subset |
| `node_executor.py` `repeats` / `last_key` | untouched by this spec; the basis of the deferred step-layer usefulness idea (REQ-11) | — | Recorded so it is not "cleaned up" mid-spec |
| `agent_kernel.py:20950-20970` the `done` consult | **fenced**: `done` already has a live `enforced=` path and writes `data["done"]`. Not touched by this spec | — | The reason `call_closing` is measurement-only (AC10.0) |
| `agent_kernel.py:20983-20989` goal-contract veto | **READ ONLY** — the backstop `call_closing` sits beneath | — | |
| `agent_kernel.py` `_current_turn_id` | the scope source (AC6.3a) | 5 | |
| `agent_kernel.py` row-sink install | the suspect for the 5 zero-row consumers (T5.11) | 5 | |

## The bar and its instruments

| File / symbol | What changes | Waves | Ripple if wrong |
|---|---|---|---|
| `consumer_bar.py` `ConsumerBar.status` / `derive_status` | `sampled` added; `superseded_flips` gains readout+criteria (AC2.3, AC6.1) | 3, 5 | Additive — no clause removed (AC9.4) |
| `consumer_bar.py` `superseded_flips()` | compares `readout_mode`, `criteria_hash` | 3 | It only checks `status == "enforced"`, so a `sampled` consumer is never flagged superseded — acceptable, but state it |
| `scripts/consumer_enforcement_report.py` `load_rows` | joins on `turn_id`; reports `label_sources` per consumer | 5 | Its query is the definition of "a labelled row". If it does not change, the report keeps measuring parity |
| `scripts/fit_oracle_calibration.py` | banded accuracy (REQ-13.6); the stability probe (REQ-13.7) | 5 | A single AUROC is what hid 0.52. The band curve is the diagnostic that replaces it |
| `benchmarks/oracle_calibration.json` | keyed by the new identity; old entries stop resolving | 3 | Correct fail-closed behaviour, but the file must be migrated, not left to rot |

## Vision and capture

| File / symbol | What changes | Waves | Ripple if wrong |
|---|---|---|---|
| `vision/screen_capture.py` `capture_base64()` | scale factor must be obtainable (**REQ-13.1** — the tuple return is NOT additive) | 4 | 3 callers unpack a 2-tuple. A naive 3-tuple breaks all of them |
| `tools/vision_provider.py` `screenshot_to_bytes` | unchanged; the session rule stays absolute (AC5.3) | — | |
| `click_safety.py` / `browser_tools.py` / `click_safety_shadow.py` | first image consumer; rules → judge → escalation and the row sink unchanged (AC5.2) | 4 | The noul readout broke with an image in the probe — this is where that shows up |

## The phase domain

| File / symbol | What changes | Waves | Ripple if wrong |
|---|---|---|---|
| `phase_domain.py` Decision instance `load_fn` | **counts QUESTIONS, not runs** (AC7.3) | 6 | Without it a 3-question run is admitted 3x too often. The most important line in REQ-7 |
| `phase_domain.py` `enter` / `exit`, capacity | untouched | — | Exit-driven admission is measured behaviour |
| Bench P3 / live gate P4 harnesses | **re-taken**; the old numbers are invalidated (AC7.7) | 6 | Citing the old numbers as evidence is a spec violation |

## Tests that MUST change in the same commit as the code they pin

| Test | Why | Wave |
|---|---|---|
| `contract/test_decision_engine_contract.py` CT-DE-7 `test_consumers_and_counters` | exact set equality on `CONSUMERS` | 1 |
| CT-DE-7 second enumeration | same | 1 |
| `contract/test_oracle_jobs_contract.py` | job field lists; the `guard` image declaration | 1, 4 |
| `contract/test_bar_record_enforcement.py` | `status` gains `sampled` | 5 |
| `contract/test_click_safety_contract.py` | image in state; row sink unchanged | 4 |
| **NEW** criteria-isolation test (AC7.5) | A's criteria must not appear in B's question | 6 |
| **NEW** failure-isolation test (AC7.5) | one malformed consumer must not fail the batch | 6 |
| **NEW** field-presence test per job (AC3.5) | every declared field in the state, no reference field | 4 |
| **NEW** load-counts-questions test (AC7.3) | pins the most important line in REQ-7 | 6 |
| **NEW** `node_executor` non-consumption test (AC10.0 fence 2) | the fence that matters | 1 |
| **NEW** dedup-scope test (AC6.3a-1) | rows survive long enough to be joined | 5 |
| **NEW** logprob `id`-not-`bytes[0]` test (AC0.3) | pins the probe bug that voided two runs | 0 |

## Files deliberately NOT touched

`universal_gui_operator.py` (zero importers — flagged by
`scripts/validate_orphans.py:64`; unrelated to this spec, and REQ-5 explicitly
builds no click path), `screen_monitor.py` (a `ScreenCapture` caller, unaffected
if REQ-13.1 is additive), the DER planner and Brain (the Oracle advises; the
planner stays the gate, oracle.md §15), and every retired Parakeet / GLiNER
artefact.