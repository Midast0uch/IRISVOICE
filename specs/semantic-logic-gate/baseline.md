# Baseline: Pre-Existing Failures at Wave 0 (Semantic Logic Gate)

> **Produced 2026-08-14** as part of W0.1 (green baseline) / W0.2 (routing-contract
> snapshot) of `tasks.md`. Purpose: record the before-state so the after-state can
> be diffed honestly, and flag which pre-existing failures sit on the gate's
> contract surface so they are never misattributed to (or silently masked by) the
> gate work.
>
> **Method**: full `pytest` run split by suite (unit / contract / behavioral /
> flat+agent) with `-q --tb=line`, plus `npx tsc --noEmit` and `jest --silent`.
> Spec-relevant failures were then **re-run in isolation** to distinguish REAL
> code drift from order-dependent (suite-state) failures — a failure that passes
> isolated is not the same class as one that fails everywhere (see
> pin_6fd9df8517e0: "a green suite is not evidence").

---

## 1. Totals

### Backend (`pytest`, venv Python 3.13.12, pytest 9.1.0)

| Suite | Passed | Failed | Skipped | Errors | Notes |
|---|---|---|---|---|---|
| `backend/tests/unit` | 964 | 12 | 0 | 9 | 9 errors = `test_iris_core_smoke.py` (C++ DLL) |
| `backend/tests/contract` | 1049 | 22 | 8 | 0 | `test_exa_provider.py` excluded (collection error, see B4) |
| `backend/tests/behavioral` | 496 | 27 | 0 | 3 | 3 errors = `test_der_chain_landing.py` |
| `backend/tests/` flat + `backend/agent/tests` | 994 | 103 | 33 | 22 | 22 errors = barge_in (14) + parakeet (8) |
| **Total** | **3503** | **164** | **41** | **34** | + 1 collection error (`test_exa_provider.py`) |

### Frontend

| Check | Result |
|---|---|
| `npx tsc --noEmit` | **CLEAN** (exit 0) |
| `jest --silent` | **156 passed, 12 failed** (6 suites of 35) |

---

## 2. Failure Groups, Classified & Prioritized

Priority is **relevance to the semantic-gate spec**, not severity of the failure:

- **P0** — sits on the gate's contract surface (REQ-3/5/7/8). Must be understood
  before the corresponding task; the gate must not be blamed for them, and must
  not silently paper over them.
- **P1** — on files the gate will edit (design.md Ripple-Effect Map) or on the
  DER loop the gate's `requires_der_kernel` feeds. Watch for interaction.
- **P2** — adjacent, non-blocking.
- **P3** — environment / harness only, unrelated to the gate.

---

### P0 — Gate contract surface

#### P0-1. `test_latency_metrics.py` — REAL code drift (REQ-5 touchpoint)
- **Failures**: `TestSTTLatencyLogLine` (2), `TestFlowLatencyLogLine` (1),
  `TestLiveLatencyMetricsDemo` (1) in unit; same 4 again in flat. 8 total.
- **Root cause (verified isolated)**: `iris_gateway._on_voice_result` line 2572
  calls `self._active_conversation_id.get(session_id)` but `IRISGateway` has **no
  `_active_conversation_id` attribute** → `AttributeError` → the `[STT_LATENCY]`
  line never emits. The `[LAYERS]`-adjacent flow-latency tests fail the same way.
- **Relevance**: design.md says the `[LAYERS]` line "is already asserted by
  `test_latency_metrics.py`" and T8 (REQ-5) extends `TurnMetrics`/`[LAYERS]`.
  The gate fields must be added **additively** (design.md Ripple: "appended,
  never reordered/removed") and these failures must stay attributed to the
  `_active_conversation_id` drift, not to T8.
- **Action**: do NOT fix as part of the gate (out of scope); note in T8 report.

#### P0-2. `test_embedding_contract.py::test_encode_with_meta_backend_is_hash` — REAL drift, provenance risk (REQ-3 touchpoint)
- **Failure**: asserts `meta.backend == BACKEND_HASH`; got `'lfm25-emb-350m'`.
- **Root cause (verified isolated)**: with the GGUF missing
  ("LFM2.5-Embedding-350M GGUF not found in config.embedding.model_path"), the
  service does **not** degrade to hash — it loads the model from the HuggingFace
  cache via transformers, and the load report shows **UNEXPECTED/MISSING weights**
  (random-init tensors). So `EmbeddingService.backend` reports `lfm25-emb-350m`
  while the loaded model is semantically broken.
- **Relevance**: T3's provenance gate (REQ-3 AC3) checks
  `EmbeddingService.backend == BACKEND_LFM` to decide whether Tier 1 is safe.
  This failure proves "backend == LFM" is **not sufficient** evidence the neural
  path is sound — the gate must also tolerate a broken-but-reported-LFM backend
  (its AC6 fail-safe already covers "LFM raises OR degrades"; this is a third
  state: *reports LFM, produces garbage*). **Candidate FINDING to surface at T3**
  (per AGENTS.md: report, do not reconcile).

#### P0-3. `test_chain_coordinate_store_contract.py` (3) + `test_der_chain_landing.py` (3 errors) — REQ-7 touchpoint
- **Failures**: `TestCTN1RowShape::test_chain_row_carries_coords_outcome_insight`,
  `TestCTN2AlterIdempotence` (2); `test_der_chain_landing` (3 errors).
- **Root cause (verified isolated)**: `_PythonFallbackEngine(db_path, key_hex="00"*32)`
  → `_run_migrations` → `MemoryError`; sqlcipher logs "hmac check failed for
  pgno=1" — the test DB is encrypted with a key that does not match `"00"*32`.
- **Relevance**: REQ-7 (T6) reads/writes `memory_chain` via
  `ffi_immortus_chain_append` / `ffi_immortus_chain_query_by_coordinate`, and T12
  pins the `memory_chain` row shape. The Python fallback engine's key handling is
  the exact surface T6/T12 will exercise. The gate's REQ-7 edge case ("engine not
  loaded → no-op") is currently the *normal* state (see P1-3).

#### P0-4. `test_recall_fixes.py` (2) — REAL drift on the direct-response path (REQ-1/REQ-8 touchpoint)
- **Failures**: `TestC3SkillGenesisSql::test_sql_matches_success_episodes`
  ("skill genesis did not fire despite 3 successful recall episodes");
  `TestC5ChunkCallbackDirectPath::test_chunk_callback_forwarded_to_respond_direct`
  → `'AgentKernel' object has no attribute 'conversation_id'`.
- **Relevance**: `test_recall_fixes.py:457` is one of the 5+ `_needs_planning`
  MagicMock sites W0.2 must pin (design.md Ripple). The `conversation_id`
  AttributeError sits on `process_text_message` → `_respond_direct` — the exact
  path REQ-1 AC3 dispatches pure conversation to. The T7 shim must keep the mock
  site green; the `conversation_id` drift is pre-existing and out of scope.

#### P0-5. `test_universal_planning.py` — **GREEN (9/9)** — the routing-contract anchor
- **Status**: passes at baseline. This is the W0.2 reference outcome set the gate
  must reproduce (chit-chat→direct, action→DER, question→direct, followup→DER,
  `ask_first` prefix-only). **Do not let T7 regress it.** If the gate's
  `requires_der_kernel` diverges on any pinned case, that is a spec-vs-code
  conflict to surface, not to engineer around.

---

### P1 — Files the gate will edit / DER loop the gate feeds

#### P1-1. `test_der_phase1.py::test_single_authority` + `test_der_single_authority_regression.py` — on `explorer.py` (design.md DEDUPE)
- **Failure**: asserts `"from backend.agent.explorer import propose" in src` —
  the resolver is no longer wired via `explorer.propose`.
- **Relevance**: design.md Ripple marks `explorer.py` as **DEDUPE** — T2
  centralizes the web-intent heuristic and `explorer.py` imports the shared
  predicate. This test asserts the *old* wiring. At T2 time, decide (with user if
  needed) whether the test is stale or the wiring regressed — do not silently
  "fix" either side.

#### P1-2. DER behavioral group — `test_der_phase0` (6), `test_der_invariants` (1), `test_der_concurrent` (3), `test_der_a1_a2_a3_memory_bridge` (1), `test_der_c1_error_propagation` (1), `test_der_integration_smoke` (1), `test_plan_grafting` (1), `test_recovery_escalation_gap` (2), `test_shallow_verified_flagged` (1)
- **Root cause**: mixed. `test_der_phase0::test_stub_is_failed` **passes in
  isolation** (order-dependent); others assert the G1 "stub must be FAILED"
  invariant and fail on `'UNVERIFIED' == 'FAILED'` — a real DER-loop behavior
  drift at HEAD (pre-existing, known from prior rounds).
- **Relevance**: the gate's `requires_der_kernel` flag is the DER planner's
  entry gate (REQ-1 AC7). T7 must not change DER-loop behavior; these failures
  are the baseline the gate inherits. Do not attribute to T7.

#### P1-3. C++ core DLL not loaded — `test_iris_core_smoke.py` (9 errors), `test_caducean_*` (partial), swig deprecation warnings
- **Root cause**: `iris_core` DLL / swig bindings unavailable in this environment
  (`builtin type swigvarlink has no __module__`).
- **Relevance**: REQ-7's edge case — "engine not loaded: all `ffi_*` calls no-op
  (return `-1`/`[]`/`{}`); the gate degrades to ontology recall only, never
  raises" — is the **current runtime state**. T6 must be implemented and tested
  against the no-op path first; the C++ path is untestable here.

---

### P2 — Adjacent, non-blocking

| Group | Tests | Cause class | Relevance |
|---|---|---|---|
| `test_context_engineering` (4+4) | chunk assembly / token budget | real drift (chunk path) | Tier 2 uses ontology recall, not context chunks — LOW |
| `test_crawler_task_progress` (contract + flat) | progress/listening-state events | real drift | not gate-related |
| `test_speak_tool::test_resolves_active_kernel_without_creating_one` | kernel resolution | real drift | kernel wiring only |
| `test_tool_bridge_gates::test_desktop_gate_dispatches_when_on` | desktop gate | real drift | adjacent to `VOICE_DESKTOP_ACTION` domain but not the gate |
| `test_chat_immortus` (2) | ffi degradation | **order-dependent** (passes isolated) | REQ-7 surface; re-check in T12 isolation |
| `test_document_rehydration_wave0` (2) | orchestrator penalty / learn-from-crawl | real drift | unrelated |
| `test_skill_creator` (3) + `test_ui_skill_sync` (2) | skill file ops | env (filesystem) | unrelated |
| `test_local_model_load` (2) | binary fallback | env | unrelated |
| `test_graded_fallback_scorer` (6) | band thresholds | real drift | unrelated |
| `test_dispatch_contract` (2), `test_cross_space_refusal` (2), `test_event_bus` (1), `test_resolver_fallback` (1), `test_browser_session_contract` (1) | misc contract | mixed (state/env) | spot-check only if a gate test touches the same module |

---

### P3 — Environment / harness only (NOT code, NOT gate-related)

| Group | Tests | Cause |
|---|---|---|
| Audio/voice native deps | `test_barge_in` (20 + 14 errors), `test_voice_pipeline` (15), `test_parakeet_service` (8 + 8 errors), `test_lmstudio_integration` (2, "SpeechRecognition not installed"), `test_porcupine_regression` (3+3), `test_voice_tool_calling` (4+4) | missing `speech_recognition` module, native audio models, Porcupine access keys, parakeet decoder |
| Telegram | `test_telegram_notifier` (16), `test_telegram_wired` (14) | import / credentials |
| Collection | `test_exa_provider.py` | `pytest_httpx` not installed |
| Frontend harness | `__tests__/InputRow.test.tsx` (7) | renders `ChatWing` without `<CrawlProvider>` (known pre-existing) |
| Frontend ESM transform | `DashboardWing`, `IntegrationListPanel`, 3× `tests/bugfix/*-exploration` (5) | `SyntaxError: Cannot use 'import.meta' outside a module` / `require is not defined` — jest transform gap, not product code |

---

## 3. Watch List — tests the gate MUST keep green

| Test | Why | Gate task |
|---|---|---|
| `test_universal_planning.py` (9) | W0.2 routing-contract anchor; gate default must be equivalent | T7, T13 |
| `test_latency_metrics.py` `[LAYERS]` assertions | T8 extends the line additively | T8 |
| `test_recall_fixes.py:457` `_needs_planning` mock site | shim must keep it green | T7 |
| `test_voice_command_start_contract.py:157`, `test_per_thread_context_behavior.py:95,108`, `test_context_usage_on_direct_reply.py:59`, `test_chunk_callback_nonstreaming.py:7` | remaining `_needs_planning` mock sites (W0.2) | T7 |
| `test_der_t18_governance_contract.py`, `test_der_t11_step_count_contract.py` | assert existing `[LAYERS]` fields survive | T8 |

## 4. Findings surfaced (not reconciled)

1. **P0-2**: `EmbeddingService.backend == BACKEND_LFM` can be true while the loaded
   model is broken (transformers fallback, random-init weights). T3's provenance
   gate must treat "reports LFM" as necessary-but-not-sufficient. (REQ-3 AC3/AC6)
2. **P1-1**: `test_der_phase1::test_single_authority` asserts `explorer.propose`
   wiring that no longer exists at HEAD — decide stale-vs-regressed at T2, when
   `explorer.py` is edited for DEDUPE.
3. **P0-1**: `IRISGateway._active_conversation_id` missing — pre-existing drift on
   the voice-result path; out of gate scope but blocks `[STT_LATENCY]`/flow-latency
   telemetry assertions.

## 5. W0.2 — Routing-Contract Snapshot (the before-state the gate must reproduce)

> Task W0.2 (REQ-1): pin the legacy `_needs_planning` / `_classify_intent`
> outcomes as the reference the gate's `requires_der_kernel` must match, and
> confirm the `_needs_planning` shim's dependent mock sites. **No code changes.**

### 5.1 Pinned outcomes — `test_universal_planning.py` (flat + behavioral twin, identical, 9/9 GREEN at baseline)

| Test | Inputs | Pinned outcome |
|---|---|---|
| `test_chitchat_bypasses_planning` | 17 msgs: hi, hello, hey there, how are you?, how's it going, thanks, thank you, ok, yes, no, bye, good night, lol, what's up, who are you, nice, cool, great | `_needs_planning == False` |
| `test_action_messages_route_to_planner` | 7 msgs: search for the latest news on AI, create a file called notes.txt, open chrome, remind me to call mom at 5pm, send an email to bob, download the report, list files in the project folder | `_needs_planning == True` |
| `test_standalone_questions_take_direct_path` | 5 msgs: what time is it in Tokyo?, explain how recursion works, what is the capital of France?, who wrote Romeo and Juliet?, how does a carburetor work? | `_needs_planning == False` |
| `test_followup_to_task_routes_to_planner` | task_ctx = [reminder user/assistant pair]; msgs: yes do it, change that to 6pm, what about the other one, ok proceed | `_needs_planning(msg, task_ctx) == True` |
| `test_disabled_mode_never_plans` | `_tool_mode="disabled"`; msgs: search for cats, hi | always `False` |
| `test_ask_first_mode_only_prefix` | `_tool_mode="ask_first"`; msgs: tool: search for cats / search for cats / hi | `True` / `False` / `False` |
| `test_is_chitchat_detects_acknowledgements` | 6 msgs: got it, sure thing, sounds good, agreed, of course, alright | `_is_chitchat == True` |

**Gate equivalence target (T13)**: `compile_dag(prompt, ctx, tool_mode).requires_der_kernel`
must equal the legacy `_needs_planning` outcome for every row above.

### 5.2 `_needs_planning` shim-dependent sites (7 sites / 6 files, confirmed by grep)

| File:line | How it depends |
|---|---|
| `backend/agent/tests/test_recall_fixes.py:457` | mocks `kernel._needs_planning` |
| `backend/tests/test_chunk_callback_nonstreaming.py:7` | mocks `kernel._needs_planning` |
| `backend/tests/unit/test_chunk_callback_nonstreaming.py:7` | twin of above |
| `backend/tests/behavioral/test_context_usage_on_direct_reply.py:59` | mocks `kernel._needs_planning` |
| `backend/tests/behavioral/test_per_thread_context_behavior.py:95,108` | mocks `kernel._needs_planning` |
| `backend/tests/contract/test_voice_command_start_contract.py:157` | mocks `kernel._needs_planning` |
| `backend/tests/test_universal_planning.py` + behavioral twin | call `k._needs_planning(msg[, task_ctx])` directly (no mock) |

**Shim requirement (T7)**: `_needs_planning(text, context) -> bool` must remain a
callable on `AgentKernel` delegating to `compile_dag().requires_der_kernel` until
T13's gate-proof retires it. The mock sites patch the method by name — the shim
keeps them green without modification.

---

## 6. How to re-run

```powershell
# backend (split to avoid the 20-min full-suite timeout)
.venv\Scripts\python.exe -m pytest backend/tests/unit -q --tb=line -p no:cacheprovider
.venv\Scripts\python.exe -m pytest backend/tests/contract -q --tb=line -p no:cacheprovider --ignore=backend/tests/contract/test_exa_provider.py
.venv\Scripts\python.exe -m pytest backend/tests/behavioral -q --tb=line -p no:cacheprovider
.venv\Scripts\python.exe -m pytest backend/tests backend/agent/tests -q --tb=line -p no:cacheprovider --ignore=backend/tests/unit --ignore=backend/tests/contract --ignore=backend/tests/behavioral --ignore=backend/tests/integration --ignore=backend/tests/archive --ignore=backend/tests/contracts --ignore=backend/tests/data

# frontend
npx tsc --noEmit
node --experimental-vm-modules node_modules/jest/bin/jest.js --silent
```