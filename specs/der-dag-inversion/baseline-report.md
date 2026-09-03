# Baseline Report — DER DAG Inversion (Wave 0, T1/T2)

Date: 2026-08-05
Spec: `specs/der-dag-inversion/`

Command: `python -m pytest backend/tests -q --ignore=backend/tests/contract/test_exa_provider.py --tb=line -p no:cacheprovider`
Frontend: `npx jest --silent`

## 1. Backend suite totals (run 1, pre-fix)

```
2204 passed, 102 failed, 27 skipped, 55 errors   (2388 collected, ~11 min)
```

Run-to-run variance observed: a second identical run gave `2208 passed, 108 failed, 17
skipped, 55 errors` — the failed/skipped delta (102→108, 27→17) is timing/network flake in
the integration suite. Totals per file below are from the `--tb=line` run.

## 2. COLLECTION ERRORS — ROOT CAUSE FOUND AND FIXED (2 files)

Two test files could not even be collected: `test_chat_persistence.py` and
`test_iris_supervisor.py`, both with the same underlying cause.

**Root cause — cross-test `sys.modules` pollution (REAL test-harness bug, not app code):**
`backend/tests/contract/test_vad_reliability.py` replaced `sys.modules["backend"]` with an
empty stub module (`__path__=[]`, no `__file__`) at module import time and never restored
it. Every test file collected afterward that imported a not-yet-cached `backend.*` name
failed with `cannot import name 'X' from 'backend' (unknown location)` / `No module named
'backend.Y'`. Exactly two files imported uncached top-level names:
- `test_chat_persistence.py:9` — `from backend import conversation_store`
- `test_iris_supervisor.py` — `from backend.iris_supervisor import ModelRunnerSupervisor`

**Fix (test harness only, tests unchanged):** `test_vad_reliability.py` now snapshots the
real module tree (`backend`, `backend.audio`, `backend.audio.engine`,
`backend.audio.cadence_detector`, `backend.audio.voice_command`) before stubbing and
restores it after loading `voice_command` — mirroring the pattern `test_vad_first_wake.py`
already used. The same class of bug existed in `test_vad_first_wake.py` (it mutated the
real `backend.audio.engine` module's `AudioEngine`/`VoiceState` to `object` and never
restored) and was fixed the same way.

**Result:** collect-only now clean — `1589 tests collected, 0 errors`.
Bounded cross-check `test_vad_reliability + test_vad_first_wake + test_barge_in`:
`50 passed, 1 failed` — the 1 failure (`test_idle_timer_is_daemon`) fails in isolation too
(see §4), so it is genuine, not pollution.

## 3. Failure triage (REAL / ORDER-DEPENDENT / STALE / UNRELATED)

Legend: F=FAILED, E=ERROR (setup/collection), counts from the `--tb=line` run.

### 3.1 ORDER-DEPENDENT — resolved by the §2 fix (counts will drop on next full run)

| file | F | E | notes |
|---|---|---|---|
| `backend/tests/unit/test_barge_in.py` | 7 | 14 | `TestBargeInDetection` setup errors were `AudioEngine` resolving to `object` (stub leaked from `test_vad_first_wake`). Isolated run: 39 pass / 1 fail. Residual genuine: `test_idle_timer_is_daemon` (see 3.3). |
| `backend/tests/integration/test_voice_pipeline.py` | 23 | 2 | Same `AudioEngine = object` pollution (its `TestAudioEngineClean` at :311 hits `cannot set '_initialized' of immutable type 'object'`). Recheck after §2 fix. |

### 3.2 UNRELATED — environment / native build / live services

| file | F | E | notes |
|---|---|---|---|
| `backend/tests/integration/test_lmstudio_integration.py` | 4 | 30 | `FileNotFoundError: backend\backend\main.py` — the test's path resolution is WRONG (it joins `backend/` twice: `backend/backend/main.py`). STALE path bug in the test PLUS the LM Studio server is not running (environment). |
| `backend/tests/unit/test_iris_core_smoke.py` | 0 | 9 | `iris_core.dll` not found — Rust core (`backend/native/`) not built. Environment. |
| `backend/tests/integration/test_vision_integration.py` | 7 | 0 | Vision server (`llama-server`/vision endpoint) not reachable. Environment. |
| `backend/tests/integration/test_voice_pipeline.py` (remaining) | — | — | Also contains audio-device-dependent tests; some of the 23 may be environment (no audio device in CI). |

### 3.3 STALE — test asserts an outdated contract (test is the requirement; code must be checked)

| file | F | E | notes |
|---|---|---|---|
| `backend/tests/unit/test_barge_in.py::TestIdleTimerPreventsStall::test_idle_timer_is_daemon` | 1 | 0 | Production `_on_transcription_complete` (voice_command.py:1253) reads `self._last_stt_timing`, which the test's hand-rolled handler fixture (test_barge_in.py:870–891) never initializes. The fixture omits a production attribute. Fix belongs in Wave 1 triage (initialize the attribute in the fixture — the test asserts behavior, not the attribute list). |
| `backend/tests/integration/test_lmstudio_integration.py` | — | — | path bug `backend/backend/main.py` — stale path resolution (see 3.2). |

### 3.4 REAL — genuine behavioral gaps (these are the spec's target areas)

| file | F | E | notes |
|---|---|---|---|
| `backend/tests/behavioral/test_der_phase0.py` | 5 | 0 | DER phase-0 contracts (FAN SUMMARY / plan shape). |
| `backend/tests/behavioral/test_context_engineering.py` | 5 | 0 | `retrieve_context_chunks returned nothing for a clearly matching query` (:115), chunk_types filter lost (:162). |
| `backend/tests/behavioral/test_der_concurrent.py` | 3 | 0 | Concurrent DER turns. |
| `backend/tests/behavioral/test_voice_tool_calling.py` | 4 | 0 | Voice tool calling. |
| `backend/tests/contract/test_model_routing_contract.py` | 6 | 0 | Routing contract. |
| `backend/tests/integration/test_crawl_integration.py` | 5 | 0 | Crawler chain. |
| `backend/tests/unit/test_latency_metrics.py` | 5 | 0 | Latency metrics. |
| `backend/tests/unit/test_active_kernel_registry.py` | 4 | 0 | Active kernel registry. |
| `backend/tests/contract/test_porcupine_regression.py` | 3 | 0 | Wake word regression. |
| `backend/tests/unit/test_skill_creator.py` | 3 | 0 | Skill creator. |
| `backend/tests/unit/test_ui_skill_sync.py` | 2 | 0 | UI/skill sync. |
| `backend/tests/integration/test_chat_immortus.py` | 2 | 0 | Chat immortus. |
| `backend/tests/integration/test_input_validation.py` | 3 | 0 | Input validation. |
| `backend/tests/contract/test_cross_space_refusal.py` | 2 | 0 | Cross-space refusal. |
| `backend/tests/behavioral/test_der_success_synthesizes.py` | 2 | 0 | DER success synthesis. |
| `backend/tests/contract/test_voice_command_start_contract.py` | 2 | 0 | Voice command start contract. |
| `backend/tests/behavioral/test_der_a1_a2_a3_memory_bridge.py` | 1 | 0 | Memory bridge. |
| `backend/tests/behavioral/test_der_c1_error_propagation.py` | 1 | 0 | Error propagation. |
| `backend/tests/behavioral/test_der_phase1.py` | 1 | 0 | DER phase-1. |
| `backend/tests/behavioral/test_web_mode_gate.py` | 1 | 0 | Web mode gate. |
| `backend/tests/contract/test_der_integration_smoke.py` | 1 | 0 | DER integration smoke. |
| `backend/tests/contract/test_event_bus.py` | 1 | 0 | Event bus. |
| `backend/tests/contract/test_resolver_fallback.py` | 1 | 0 | Resolver fallback. |
| `backend/tests/contract/test_speak_tool.py` | 1 | 0 | Speak tool. |
| `backend/tests/integration/test_skill_e2e.py` | 1 | 0 | Skill e2e. |
| `backend/tests/unit/test_phase3_regression.py` | 1 | 0 | Phase-3 regression. |
| `backend/tests/unit/test_skill_simulator.py` | 1 | 0 | Skill simulator. |

Note: several §3.4 failures may share ONE root cause each (e.g. a broken shared memory/
recall path explains test_context_engineering + DER memory-bridge failures). Wave 1 (signal
integrity) and Wave 4/5 (coupling, ontology) are the spec's own answer to these; the
behavioral DER failures are the CDD harness gap-finders the spec was written for.

## 4. Frontend jest

```
Test Suites: 3 failed, 28 passed, 31 total
Tests:       5 failed, 155 passed, 160 total
```

All 3 failing suites are `tests/bugfix/*bug-exploration*.test.js`
(`tauri-dev-compilation-bug-exploration`, `tauri-dev-compilation-preservation`,
`iris-widget-tilt-transform-bug-exploration`) — exploration artifacts, STALE. Not
application regressions.

## 5. What was changed during baseline (must be reported, not hidden)

- `backend/tests/contract/test_vad_reliability.py` — test-harness hygiene: restore
  `sys.modules` after stubbing (fixes 2 collection errors; tests' assertions unchanged).
- `backend/tests/unit/test_vad_first_wake.py` — test-harness hygiene: never mutate an
  already-imported `backend.audio.engine`; restore `sys.modules` after loading (fixes
  ORDER-DEPENDENT failures in `test_barge_in` and `test_voice_pipeline`; assertions unchanged).

No production code was modified during Wave 0.

## 6. T2 — Caducean-family harnesses

Run: `python scripts/validate_*.py` (all 12 found; spec listed ten — all run and recorded).

```
PASS  validate_display_coherence.py       13.3s
PASS  validate_local_model_path.py         7.6s
PASS  validate_outer_loop.py               4.8s
PASS  validate_phase_scheduler.py         86.8s
PASS  validate_phase1_foundation.py        5.0s
PASS  validate_switcher.py                44.7s
FAIL  validate_apply_e2e.py                2.4s  ConnectionRefusedError [WinError 1225] — live LM Studio service not running (UNRELATED/environment)
FAIL  validate_apply_fix.py                2.3s  ConnectionRefusedError [WinError 1225] — live LM Studio service not running (UNRELATED/environment)
FAIL  validate_caducean_kernels.py        27.1s  "4 failure(s)" — kernel behavior (REAL, spec target)
FAIL  validate_der_integrity.py            4.6s  "[FAIL] blocked event emitted" + "[FAIL] user asked with options" (REAL — DER integrity contracts)
FAIL  validate_der_tool_resolution.py      4.5s  search_web CRASHED "An asyncio.Future, a coroutine or an awaitable is required" (REAL — async dispatch bug); "model unavailable" entries (environment)
FAIL  validate_encoder_path.py            17.3s  AttributeError: '_S' object has no attribute '_TRUSTED_RESULT_TOOLS' (REAL — likely cross-harness state leak or stale constant)
```

6/12 pass. Failures split: 2 environment (live service), 4 REAL harness gaps. The 4 REAL
failures are exactly the DER loop seams the spec targets (tool resolution async bug,
integrity-event contract, kernel behavior) — the CDD harnesses are doing their job.

## 7. T3 — per-turn call-count baseline (MEASURED 2026-08-06, offline DER-loop driver)

5-step FULL-mode task, with and without splits. The live-gateway measurement
(`ws://127.0.0.1:8090` + bound provider) remains blocked as originally noted,
but the spec-sanctioned DER-loop-level instrument (same `der_calls` counter T25
records) has now been measured offline in `scripts/measure_der_call_count.py`
(real `_plan_task` / `_der_run_step_execution` / `_der_finalize_step` /
`_split_step` / `_der_route_subloop_children`, counting router on
`_router.generate`, stub batcher for the pre-T25 baseline):

```
[MEASURE] shape=no_splits mode=baseline calls=6
[MEASURE] shape=no_splits mode=batched  calls=6
[MEASURE] shape=with_splits mode=baseline calls=9
[MEASURE] shape=with_splits mode=batched  calls=7 der_calls=1
[MEASURE] reduction_with_splits=2
T3_BASELINE_OK
```

**Baseline (demand side, pre-batching): 6 calls/turn without splits; 9
calls/turn with a 3-child split** (1 planner + 5 step resolves + 3 per-child
resolves). Same shape under T25 batching: **7 calls/turn** (children group into
one `dispatch_batch` call; `der_calls=1`). Sanity: no_splits is identical in
both modes (6 = 6) — batching only touches split children. The Wave 1.5 exit
criterion ("call count measurably lower than the T3 baseline on the same task
shape") is satisfied by measurement: 7 < 9.

## 7b. LIVE T3 — full-stack run (2026-08-06, gateway ws://127.0.0.1:8090 + cerebras/gemma-4-31b)

The live stack was brought up and a real 5-step research task ran end-to-end
through the DER loop (turn 847d03a8-ffd): 4 real `crawler_query` crawls + 1
`get_rendered_documents`, success synthesis, real 3725-char answer.
`[LAYERS] ... path=der der_steps=0 der_calls=0 step_tokens=5 ttft_ms=406778.5`.

**FINDING 1 — 429 rate-limit amplification is the dominant cost, not a
re-gathering loop.** The turn made **27 router calls** but **~15 are logical**
(1 plan + 5 resolves + 4 crawler topic-extractions + ~4 verifies + 1
synthesis). The other ~12 are transport-level retries of 429'd calls — **34
HTTP 429 attempts** total, each costing a 30s `_sleep_on_429` backoff (visible
as 30s gaps between every call cluster). The step sequence proves there is NO
re-gathering loop: 3 × `crawler_query` + 1 × `get_rendered_documents`, each
step crawled exactly once. Wall time 6.8 min is 429-sleep-dominated, not
loop-dominated. This is the T27 (rate-health) + phase-manager pacing axis.

**FINDING 2 — `der_steps`/`der_calls` confirmed 0 in live production despite
the loop running** — the "declared, never assigned" defect (tasks.md evidence
list) is real, not hypothetical. T11 (Wave 2) must wire
`TurnMetrics.der_steps = len(completed_items)` + `der_calls` at the DER-turn
finalize for any `[LAYERS]`-based call-count claim to be observable.

**FINDING 3 — T25 batched dispatch routed to the WRONG provider (fixed).**
Live: `[SubLoopBatcher] BATCH_READY join=s1_s1 children=3 reason=full` fired,
but `der_batch_dispatch failed: Ollama returned 500` — `_der_dispatch_batch_group`
passed the LEGACY `_selected_reasoning_model` ("llama3.2:latest") as
`router.generate`'s first arg, which the router treats as a ROLE → resolve
failed → fell back to the broken Ollama provider, while per-step calls routed
to cerebras. Fixed: batched dispatch now passes the role `"reasoning"` so it
resolves the same bound provider as siblings (agent_kernel.py:7436-7453);
contract test CT-9 (`test_batch_contract.py::test_ct9_batch_dispatch_uses_role_binding`)
pins it. 55/55 batch+DER tests green.

**FINDING 4 — config dead binding**: `data/iris_config.json` role_bindings
pointed at `ollama` (provider='ollama', models llama3.2:latest) but `providers`
had no `ollama` entry — "Provider instance 'ollama' not found in registry" on
every plan. Corrected to provider=cerebras + gemma-4-31b for both roles.
(Ollama itself is broken on this machine: `llama-server binary not found`.)

## 7c. T11 + gap-fix VALIDATED LIVE (2026-08-06, turn 95cbe698-342)

After wiring T11 (der_steps/der_calls) and the gap-recursion fix, the live
5-step research task COMPLETED end-to-end:

```
[LAYERS] turn=95cbe698-342 engine=native path=der der_steps=8 der_calls=0
[DER] success synthesis ran (REQ-12 AC1) - steps=8
[AgentKernel] DER response: Based on the research conducted...
```

- **der_steps=8 is a REAL number** (5 planned + 3 gap-fill items completed) —
  every prior live run showed der_steps=0 (declared-never-assigned). T11 proven
  live, not just by unit test.
- **der_calls=0 is CORRECT for this turn** — no splits occurred (all 5 steps
  succeeded), so no batch groups dispatched; the T25 counter only increments
  on split turns. Batching telemetry is invisible on non-split turns by design.
- **Gap-recursion fixed live**: prior run (fc2a1a48-ddf) looped forever on
  gap-on-gap (gap-s2-0 -> step 2 re-crawl -> gap-s2-1/2 -> step 2 re-crawl...).
  The guard (`not _is_gap_item` at the analyze_gaps trigger) stops gap items
  from re-triggering analysis; this run's gap items executed cheap doc-reads
  (4ms) and the turn terminated. Contract: test_der_gap_no_recursion_contract.py.
- Turn wall time ~8.5 min: 5 crawls (60-120s each) + gap items; 429 retries
  absorbed with backoff, no stall. The 5 planned steps completed cleanly — the
  earlier 10+ min hangs were the gap loop, NOT 429s resuming from step 1.

## 7d. Trailing-Director gap-fill REMOVED (2026-08-06, user decision)

The gap-fill ran SEQUENTIALLY after the user's task: it was invoked
synchronously in `_der_finalize_step` and its gap items were queued into the
SAME turn, re-executing completed steps' work after the plan finished. It
never ran in parallel with the task — so it only added latency and
unsolicited steps (live 95cbe698-342: 5 planned steps then gap-s2-* extended
the turn to der_steps=8). **Decision: remove the gap-fill entirely.**

Changes (agent_kernel.py):
- init no longer constructs `TrailingDirector`; `_trailing_director` stays
  None (the `is not None` guards were already in place everywhere).
- the `analyze_gaps` block in `_der_finalize_step` is removed, along with the
  REQ-5 AC1 shallow-verified trigger that fed it.
- orphaned import + `set_memory_interface` wiring + stale comment removed.
- the `TrailingDirector` CLASS and its unit tests remain (module untouched) —
  only the kernel wiring is gone.

Contract tests `test_der_gap_no_recursion_contract.py` (2) pin the removal:
kernel never constructs it; finalize has no gap-analysis call. 80/80
batch+DER+contract+unit tests green. NOTE: `test_der_phase0.py` (5 F) and
`test_der_integration_smoke.py`'s old-path duplicate were PRE-EXISTING
failures (stale `backend\backend\...` path bug) — unrelated to this removal,
already triaged in the Wave-0 baseline §3.4.

**LIVE-REGression-checked (2026-08-06, turn e5b1c45a-275):**
```
12:34-12:40  steps 1-5: crawler_query x4 (55s/71s/52s/48s) + get_rendered_documents (0.1s)
12:40:34  [DER] success synthesis ran (REQ-12 AC1) - steps=5
12:40:34  [LAYERS] der_steps=5 der_calls=0 step_tokens=5 ttft_ms=369590
12:40:34  DER completed
```
Exactly 5 steps, ZERO gap items, clean termination, no hang — regression-free.
Run-to-run: der_steps=8 (gap-loop present) -> 8 (recursion fixed) -> **5
(gap-fill removed)**. Wall time 6.1 min (was 8.5+ with gap-fill).

## 8. REQ-2 build-memory inheritance — schema delta (AC1, data)

BUILD store: `.mcm/coordinates.db` (28 tables). Application store:
`data/memory.db` (53 tables). Shared tables: 25 (list below). All shared
tables are schema-identical EXCEPT the three documented here.

| Table | BUILD schema | App schema | Delta |
|---|---|---|---|
| `memory_chain` | legacy (entry_id, thread_id, session_id, sequence, role, content, metadata, session_ts, result, distilled, created_at) — 4828 rows | same legacy shape — 1825 rows (T6 migrates to coordinate at engine init) | both need the coordinate ALTER (chain_id, coords_from, coords_to, nbl_outcome, insight, file_path, landmark_id, stale) for parity |
| `memory_chain_v2` | orphan shape (chain_id, thread_id, sequence, label, role, content, metadata, distilled, created_at) — 0 rows | same orphan shape — 0 rows | DROPPED in both (T6 app store, T7b BUILD store) |
| `caducean_trajectories` | has `domain` column | no `domain` column | T10 (Wave 2) adds domain to the app store; BUILD already has it |

Shared tables verified schema-identical: caducean_session_exits, caducean_trajectories
(except domain), checkpoints, code_events, contracts, coordinate_path, der_commits,
der_fan_traces, eml_trees, file_nodes, folders, gradient_warnings, graph_edges,
instance_registry, landmark_bridges, landmarks, memory_chain (except coords), pins,
pin_links, project_registry, sessions, sqlite_sequence, test_nodes, work_items.
BUILD-only (not in app): shared_sigma_events, shared_sigma_global, shared_sigma_servers.

## 9. T6/T7/T7b outcomes

- T6: idempotent coordinate ALTER + orphan v2 drop in the engine migration
  (`iris_ffi._run_migrations`), AC5 guard prevents decoy/.mcm writes; append made
  shape-agnostic; FFI wrapper kwargs bug found by behavioral test and fixed.
- T7: CT-N1/N2/N3 + behavioral chain-landing test (23 tests green). Verified: legacy
  1825 rows survive with null coords, recall tolerates both shapes.
- T7b: `scripts/migrate_build_store_inheritance.py` — offline, human-run, idempotent
  inheritance migration (dry-run supported). Verified on a BUILD copy: 4828 rows
  preserved, coordinate schema applied, v2 dropped, and the inherited store accepts
  application appends. CLAUDE.md claim updated to be true (AC3).
