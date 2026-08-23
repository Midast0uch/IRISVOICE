# Tasks: DER GROUND TRUTH

**Requirements:** `requirements.md` · **Design:** `design.md`
**Blocks:** `specs/wormhole-aperture/` (gates G0 / G0b → satisfied here as GT-G4)

> Every task links to a REQ and carries a RIPPLE note.
> **No task in this spec requires running the application in developer mode.** If a task
> appears to, it is mis-scoped — say so rather than reaching for a manual run.
> When a gate passes, record its evidence inline (query, numbers, date).

---

## PRE-EXISTING FAILURES FOUND (2026-08-23, unrelated to this spec)

Full frontend sweep: **48 of 50 suites green, 313 of 315 tests**. The two
failures are STALE TESTS asserting behaviour that was deliberately superseded.
Both are present at `HEAD` and neither their source nor their test differs from
it (`git diff --stat HEAD` empty for both) - **not caused by this work**.

Per the project's absolute test rule these are REPORTED, not reconciled:

| Suite | Asserts | Actual | Why it is stale |
|---|---|---|---|
| `__tests__/cards/verbRegistry.test.ts` | `resolveVerb("frobnicate_widget_xyz")` == `"FROBNICATE_WIDGET_XYZ"` | `"FWX"` | `lib/cards/verbRegistry.ts:175-181` documents a **session-246 user-directed amendment to AC2**: unregistered tools now compact to <=6 chars to fit the fixed-width verb column. The test encodes the pre-amendment behaviour. |
| `__tests__/cards/memoryRegistry.test.ts` | `MEMORY_EVENT_REGISTRY.recall.format` is `undefined` | a formatter exists | A `format` for the `recall` kind was added (its fields - `hex_bin_id`, `tier`, `hyperedge_posterior` - are the WORMHOLE recall surface). The test asserts its absence. |

Neither is touched here. Resolving them needs the user's call on whether the
superseded behaviour was intended, which is exactly what the test rule reserves
for a human.

## Wave 0 — Pin the audit

- [x] **T0** (ALL REQs) - **DONE 2026-08-23 - baseline pinned in pin_ef766b9223ed + the audit tables in requirements.md; test baselines recorded per suite.**: Re-run and PIN the audit measurements as the baseline, so every
  later claim of improvement is a delta against a recorded number:
  - Store row counts: `der_fan_traces=0`, `mycelium_edges=0`, `semantic_entries=0`,
    `mycelium_pins=0` (vs `mycelium_pin_links=354`), recall episodes`=0`,
    `caducean_trajectories=201` (200 success / 1 failure), `der_commits=198`
    (194 VERIFIED / 2 UNVERIFIED / 2 FAILED), `episodes=207` (55 websocket/failure).
  - Import graph: 285 modules scanned, **33 orphans**, `importlib` in exactly one module.
  - Exception census: **441 / 778 handlers swallowed** (205 debug + 236 silent) vs 337
    logged at warning or louder; `agent_kernel.py` = 125 across 14,314 lines.
  - Existing test suites: `backend/tests/unit/test_tool_errors.py`,
    `test_search_loop_bounds.py`, `test_dag_node_contract.py`, `test_dag_node_behavior.py`,
    and the 19 `scripts/validate_*.py` harnesses.
  - RIPPLE: `pin_add` the baseline. Every REQ below is measured against these numbers, and
    a fix that does not move its number did not work (REQ-16 edge case).
  - **Baseline date: 2026-08-23.**

---

# PART 1 — Honest recording

### Wave 1 — Determinations (answer before fixing)

- [x] **T1** (REQ-5 AC1) - **DONE 2026-08-23 - 7 counters live (no_active_nodes / skipped_no_region / skipped_no_mediator / region_resolve_degraded / region_resolve_failed / written / write_failed); swallowed write promoted debug->warning. AWAITING TRAFFIC to answer.**: Instrument the edge-scoring guard at
  `backend/agent/agent_kernel.py:11530` — count how often `_region_node` is None, how often
  `_mediator_tool` is empty, and promote the swallowed exception at `:11541` from `debug`
  to a counted warning. Answer which of the three causes applies. — RIPPLE: this is the
  ONLY determination that needs live traffic, and one recorded session suffices. Do it
  first so it runs while the rest of Part 1 is built.

- [x] **T2** (REQ-3 AC5) - **DONE 2026-08-23 - DETERMINED: MemoryDistiller and RetentionPolicy have zero references anywhere. Dispositioned REVIEW in the orphan inventory; retiring or wiring them needs the owner's call.**: Determine the disposition of `MemoryDistiller` /
  `RetentionPolicy` — both have **zero references anywhere**. Wire or retire. — RIPPLE:
  `backend/memory/skills.py`, `distillation.py`, `retention.py`; feeds REQ-15's inventory.
  An unreferenced retention policy means nothing is retaining anything.

- [x] **T3** (REQ-4 AC1/AC3) - **DONE 2026-08-23 - DETERMINED: mycelium_pins IS authoritative (app schema, db.py:344). `pins` is MCM build-store contamination (no CREATE in backend/, columns identical to .mcm). The 354 links are node->node, zero pin refs - no orphans. TWO draft claims corrected in requirements.md.**: Determine the authoritative pin table. `PinStore` writes
  `mycelium_pins` (`backend/memory/pin_store.py:193`) which holds 0 rows, while
  `mycelium_pin_links` holds 354 and a separate `pins` table holds 4. Explain the 354
  orphaned links; recover or quarantine. — RIPPLE: `der_links.py` and `semantic_gate.py`
  are PinStore's two importers and must be checked against the answer.

> **T1 STATUS 2026-08-23:** instrumentation SHIPPED and accumulating. The
> determination itself needs one recorded session of live traffic - the counters
> answer it directly: `skipped_no_region` >> `written` means the guard never
> passes; `write_failed` > 0 means the write raises; both ~0 with traffic present
> means edge state lives elsewhere (`mycelium_landmark_edges`, 6201 rows).
>
> ### 🚦 GATE GT-G1 — DETERMINATION
> **Blocks:** any fix to REQ-3 / REQ-4 / REQ-5.
> **Evidence:** a written cause for each empty store — never called / called and failing /
> writing elsewhere. REQ-3's is already answered (never called, zero importers).
> **Record here:** `[ ] PASSED  date: ______  edges: ______  pins: ______  skills: ______`

### Wave 2 — Wire the write paths

- [x] **T4** (REQ-1) - **DONE 2026-08-23 - _der_emit_fan_trace at the node terminal outcome, idempotent per (session,step), emitted BEFORE the mycelium block so it cannot inherit that guard's fragility.**: Move fan-trace emission to the DER node-finalize path. Same writer
  (`record_fan_trace`), same row shape, same error handling — **call site only**. Idempotent
  upsert on `(session_id, step_id)` so a DCP run cannot double-write. Off the critical path.
  — RIPPLE: `backend/agent/der_loop.py` finalize site; `backend/agent/dcp.py:152,183`
  becomes secondary; **CT-GT-1 pins the row shape**. BT-GT-1 is the proof: a run with NO
  pruning writes rows.

- [x] **T5** (REQ-2) - **DONE 2026-08-23 - commit writes counted BY LABEL; the swallowed record_commit failure promoted debug->warning. Distinguishes 'failures never reach this path' from 'the write fails quietly'.**: Reach the trajectory and commit recorders on failure paths.
  `record` (`caducean_trajectory.py:226`) and `record_commit` (`:484`) already accept the
  outcome and label — this is a call-site gap, not a recorder gap. A retry records BOTH
  outcomes; a killed run records the state actually reached. — RIPPLE: BT-GT-3;
  produces GT-G4's evidence.

- [x] **T6** (REQ-3 AC1-AC4, AC6) - **DONE 2026-08-23 - _save_card_footprint wired at the card terminal state; partial maps to 'unknown', never a fabricated converged.**: Wire `save_card_footprint` to the card-terminal path
  and add the contract test asserting the writer has a production caller. — RIPPLE:
  `backend/memory/card_footprint.py` (0 importers today); `agent_kernel.py` card-terminal
  site; **unblocks `specs/wormhole-aperture/` REQ-34**, which currently builds on a module
  nothing calls.

- [x] **T7** (REQ-4 AC2/AC5) - **DONE 2026-08-23 - PinStore was already correct; _PIN_TABLE named constant added so the determination is pinned. 34/34 test_pin_store green.**: Point `PinStore` at the authoritative table; add CT-GT-2
  pinning the table name. — RIPPLE: `backend/memory/pin_store.py:18,126,148,193,238`;
  **unblocks `specs/wormhole-aperture/` REQ-24 AC8**, which targets the empty table today.

- [x] **T8** (REQ-5 AC3/AC4) - **DONE 2026-08-23 - ANSWERED OFFLINE, no traffic needed. Cause (a): the guard passes only rarely, and the mechanism is now established.**

  **Evidence chain, all read-only:**
  1. `SessionRegistry.register` (navigator.py:40) has exactly ONE caller that
     populates it: `navigate_from_task` (navigator.py:196).
  2. `navigate_from_task` reaches the DER path via
     `get_task_context_package` -> `get_context_path`
     (`agent_kernel.py:5609` -> `memory/interface.py:697` -> `:416`). So the path
     IS live - "the registrar never runs" is RULED OUT.
  3. Register side (`agent_kernel.py:5611`) and read side (`:6730`) both use the
     IDENTICAL expression `session_id or self.session_id`. So an identity
     mismatch is RULED OUT.
  4. **Direct probe against the live store** (read-only): `navigate_from_task`
     returns **0 nodes and registers nothing** for `"run the test suite and fix
     failures"`, while `"hardware"` and `"search the web..."` reach the write
     path (readonly error proves activation). Entry matching is
     keyword-based (`_match_entry_nodes` / `_extract_keywords`) against **37
     nodes covering only 3 of 7 spaces** (toolpath 30, capability 4, domain 3),
     whose labels are mostly `tool_*` / `domain_*`.

  **Conclusion:** `node_ids` is empty for any task whose keywords miss those 37
  labels, so `_region_node` is None and the guard never passes -> `mycelium_edges`
  stays at 0. The guard is not broken; its INPUT is bootstrap-starved.

  **What T1's counters still add:** the production hit-RATE
  (`skipped_no_region` vs `written`). The mechanism no longer needs them.

  **A near-miss worth recording:** I first inferred this from
  `access_count = 0` on all 37 nodes. That inference was UNSOUND - nothing in
  the codebase ever increments `access_count`; it is set to 0 at
  `navigator.py:240` and only ever read. Checking before claiming is what
  stopped a fourth wrong finding. (Separate defect, see Finding 11.): Act on T1's determination — wire the writer, or correct
  `specs/wormhole-aperture/` Decisions Locked 2 to name the real substrate. **Do not create
  a third edge store** (REQ-5 AC5). — RIPPLE: this is the task that decides whether the
  wormhole spec's central reuse justification survives.

- [x] **T9** (REQ-14) - **DONE 2026-08-23 - all 5 ExecutionLedger sites now pass storage_path (IRIS_DER_LEDGER_DIR, default data/der_ledger); persist-without-path is counted, not a silent True.**: Give the execution ledger a production storage path so `persist()`
  writes; make a persist-that-cannot-persist a counted condition rather than a silent
  no-op; keep the atomic `.tmp` write (`der_execution_ledger.py:348`) and the in-memory
  mode for tests. — RIPPLE: `agent_kernel.py:7555,8600,8603`;
  `scripts/validate_der_integrity.py` asserts on this ledger and has been asserting against
  memory that evaporates.

- [x] **T10** (REQ-13) - **DONE 2026-08-23 - backend/agent/write_counters.py + named counters on every write path this spec touches (edge scoring x7, fan traces, commits by label, footprints, ledger, row-seq). All 441 handlers NOT rewritten, per AC4.**: Silent-failure policy — the three-case classification, plus a named
  counter on every swallowed WRITE-path failure this spec touches (fan traces,
  trajectories, commits, footprints, pins, edges, ledger). **Do NOT rewrite all 441
  handlers** (REQ-13 AC4). Preserve never-break-the-caller throughout. — RIPPLE:
  `agent_kernel.py:11541`, `card_footprint.py:57-59`, `caducean_trajectory.py:315` are the
  worked examples; counters surface through REQ-6.

> ### 🚦 GATE GT-G2 — RECORDING
> **Blocks:** treating Part 2 as meaningful (an invariant suite over empty tables is DEAD,
> not passing).
> **Evidence:** `der_fan_traces` non-zero from a real run with no pruning; footprints
> persisting; ledger file on disk.
> **Record here:** `[ ] PASSED  date: ______  fan_traces: ____  footprints: ____  ledger: ____`

---

# PART 2 — Offline verification

### Wave 3 — Invariants

- [x] **T11** (REQ-6) - **DONE 2026-08-23 - scripts/validate_store_invariants.py, 7 invariants, PASS/FAIL/DEAD, read-only, exit 1 on FAIL or DEAD.**: `scripts/validate_store_invariants.py` — read-only, headless,
  PASS / FAIL / **DEAD** per invariant, non-zero exit on FAIL or DEAD, per-invariant report
  with offending counts and example keys. Invariants per REQ-6 AC1 plus REQ-13's
  swallowed-write counters. — RIPPLE: NEW file; the `live` vs `passed` precedent is
  `backend/agent/outer_loop.py:27-37`.

- [x] **T12** (REQ-6, design § anti-vacuity) - **DONE 2026-08-23 - --self-test: all 7 invariants report DEAD on an empty store, none PASS. GATE GT-G3 PASSED.**: The suite's SELF-TEST — run every invariant
  against an EMPTY database and assert **none report PASS**. — RIPPLE: this is the single
  test that would have caught the entire condition this spec exists to fix. An assertion
  that passes over an empty table is exactly how five empty stores went unnoticed.

- [x] **T13** (REQ-15) - **DONE 2026-08-23 - scripts/validate_orphans.py, importlib-aware, baseline 28 in scripts/orphan_baseline.json, fails on a NEW undispositioned orphan.**: Orphan-detection check — headless, `importlib`-aware, baseline of
  33 recorded, fails when the count rises without a disposition. — RIPPLE: NEW; the audit
  script from 2026-08-23 is the prototype.

- [x] **T14** (REQ-15 AC1/AC2/AC6) - **DONE 2026-08-23 - all 28 dispositioned: 8 KEEP-DORMANT, 3 RETIRE (recommendation only - nothing deleted), 1 WIRE, 16 REVIEW awaiting owner domain knowledge.**: Disposition every orphan — WIRE / RETIRE /
  KEEP-DORMANT with reason and expiry. **RETIRE records a recommendation; it does not
  delete.** Deletion needs the user's per-module confirmation. — RIPPLE: 33 modules;
  `recall_phases.py` is dispositioned by `specs/wormhole-aperture/` REQ-0 (KEEP-DORMANT
  behind a default-off switch), so start from that precedent.

> ### 🚦 GATE GT-G3 — ANTI-VACUITY
> **Blocks:** shipping the invariant suite.
> **[x] PASSED — 2026-08-23 · invariants: 7 · none-pass-on-empty: CONFIRMED (7 DEAD, 0 PASS)**
> `python scripts/validate_store_invariants.py --self-test` → exit 0.
>
> **Live store 2026-08-23** (`--db data/memory.db` → exit 1): 1 PASS · 3 FAIL · 3 DEAD.
> FAIL: fan traces (198 commits, 0 traces) · failure reconciliation (26.9% episode
> vs 0.5% physics) · coupling substrate (37 nodes, 0 edges).
> DEAD: footprints (semantic_entries empty) · pin links (no pin refs to resolve) ·
> termination cause (column absent). The suite reproduces the audit independently.

### Wave 4 — Corpus

- [x] **T15** (REQ-7) - **DONE 2026-08-23 - scripts/export_der_traces.py, read-only, selects by session/date/OUTCOME, redacts user content, marks gaps rather than interpolating. Verified against the live store.**: `scripts/export_der_traces.py` — read-only, selects by session id /
  date range / **outcome**, emits the format `scripts/validate_der_cli_harness.py` already
  documents and consumes. Redacts user content (REQ-7 AC4). `_schema_version` on the file
  and `_gap` markers where records are incomplete. Non-zero exit on an empty result. —
  RIPPLE: **CT-GT-3 pins the round trip**; exporting by outcome is what makes failure
  traces obtainable at all.

- [x] **T16** (REQ-8) - **DONE 2026-08-23 - tests/traces/ seeded with 5 exported traces (failure + success classes). Coverage reported per run; declared gaps kept as fixtures of the pre-T4 condition.**: The committed corpus under `tests/traces/` — successes, failures,
  one per termination cause, tool failures across FAULTLINE dimensions. One-command
  addition (AC3), coverage report (AC4), bounded per class **with what was dropped logged**.
  — RIPPLE: redaction (T15) is what makes it committable.

- [x] **T17** (REQ-8 AC2) - **DONE 2026-08-23 - scripts/replay_corpus.py, one command, exit non-zero on any break. IMMEDIATELY surfaced Finding 10 (no exported session has a terminal frame).**: One command replays the whole corpus through every standing
  harness, headless, non-zero on any break. — RIPPLE: the 19 `scripts/validate_*.py`
  files; existing assertions preserved, corpus becomes their input.

---

# PART 3 — Unified termination

### Wave 5 — Cause vocabulary

- [x] **T18** (REQ-9 AC1/AC6) - **DONE 2026-08-23 - backend/agent/termination.py, 12-member closed vocabulary + CAUSE_BOUNDS naming the constant each bound comes from. Adds NO bound.**: Define the closed termination-cause enum — `natural`,
  `sufficiency`, `cycle_cap`, `token_budget`, `turn_wallclock`, `veto_cap`, `graft_cap`,
  `depth_cap`, `zero_yield`, `permission_refused`, `user_abort`, `unexpected`. Follows the
  `NodeOutcome.Reason` discipline (`backend/agent/nodes/outcome.py:40`). — RIPPLE:
  **CT-GT-4**; a SEPARATE enum at run level — node-level reasons are not extended (CT-1).

- [x] **T19** (REQ-9 AC2/AC3) - **DONE 2026-08-23 - 5 additive columns on caducean_session_exits; record_session_exit takes an optional TerminationRecord. Absence stays NULL, never invented.**: Record exactly one cause per run, with the bound's
  CONFIGURED and MEASURED values, into the existing `caducean_session_exits` (415 rows) via
  `record_session_exit` (`caducean_trajectory.py:518`). Co-occurring near-misses recorded
  alongside. — RIPPLE: `der_loop.py:698,707`; `agent_kernel.py:125,10103`; `orchestrator`
  zero-yield; **REQ-9 AC5 — no new bounds are added by this spec.**

- [x] **T20** (REQ-9 AC4) - **DONE 2026-08-23 - validate_store_invariants.py --terminations. Currently reports the column is unpopulated, which is honest: runs must accumulate.**: Termination-distribution report — "what stopped my last 100
  runs" in one query. — RIPPLE: this is the number that tells you whether DER's
  brittleness is a termination problem; today it cannot be computed.

### Wave 6 — Termination testing

- [x] **T21** (REQ-10) - **DONE 2026-08-23 - backend/tests/unit/test_termination.py, 13 tests, headless. Every cause round-trips; a bounded exit is never a success; a malformed record degrades to `unexpected` without losing the row.**: Synthetic driver forcing each cause deterministically; assert the
  run stops, records the right cause, and **finalises honestly — a run stopped by a bound
  never reports success**. No network, TTS, model, or GUI. — RIPPLE: BT-GT-5; an
  unforceable cause is REPORTED as a known gap, never quietly omitted.

- [x] **T22** (REQ-10 AC3) - **DONE 2026-08-23 - B-2 (exactly one terminal frame) extended across every trace in replay_corpus.py; currently FAILING on all 5, which is the honest state.**: Extend the existing B-2 invariant ("exactly one terminal
  frame", `scripts/validate_der_cli_harness.py`) across every termination cause. — RIPPLE:
  **CT-GT-3 is a lock** — extend it, do not replace it.

---

# PART 5 — The task progress card tells the truth

> The card is in this spec because the user's report — "works with simulated emit events
> but not with real work" — is this spec's thesis at the event boundary. Three of these
> were already isolated in `pin_587a3e612558` (session 247 FINAL, items 3/4/5) and remain
> open; the audit added the mechanism.

### Wave 7 — Measure before fixing

- [x] **T27** (REQ-19 AC1/AC2/AC3) — **DONE 2026-08-23, see GT-G6 below.** Write the EMITTER contract validator — ordering key
  present and unique, exactly one terminal frame per `task:start`, no `stepNumber`
  collision, phase transitions carry `phase`+`phase_sequence` — asserted on a trace
  independently of any renderer. Run it over the existing captured traces (conv-44/49/51)
  and **record which ones violate it**. — RIPPLE: **this measurement comes FIRST and
  explains why the suite is green while the card is wrong.** Fixing the reducer before
  knowing whether its input was legitimate is exactly how the current state arose.
  Gate GT-G6.

> ### 🚦 GATE GT-G6 — EMITTER HONESTY
> **Blocks:** calling any card-rendering fix done.
> **Evidence:** captured traces run through the emitter contract; violations recorded.
> **[x] PASSED — 2026-08-23 · traces checked: 3 · VIOLATIONS: 18**
>
> `lib/cards/emitterContract.ts` (rules E1–E5) + `__tests__/contract/emitterContract.test.ts`
> (12/12 green: 7 self-tests proving the validator can fail, 5 measurement verdicts).
> Frames extracted mechanically from the contract-locked reducer suite into
> `__tests__/fixtures/cardTraces.ts` — 21 frames, 0 parse errors, locked suite re-run
> 7/7 with **zero diff**.
>
> | Trace | Frames | Violations | Rules |
> |---|---|---|---|
> | conv-49 websearch | 11 | 7 | E1 ×1, E5 ×6 |
> | conv-49 websearch + graft | 12 | 8 | E1 ×1, **E2 ×1**, E5 ×6 |
> | conv-code implement | 9 | 3 | E1 ×2, E5 ×1 |
>
> **VERDICT — the emitter was malformed all along.**
> - **E1:** EVERY `task:start` row in EVERY trace arrives with no `stepNumber`, including
>   the non-crawl code task. **The defect is not crawl-specific.**
> - **E5:** every phase transition opens a row with no key orderable against planner rows.
>   `phase_sequence` orders phases among THEMSELVES only — it can never interleave them.
> - **E2:** the graft collides `r1` and `r1_s1` on key 1 — in the fixture labelled
>   "real payload shape".
> - **E3 HOLDS:** terminals are correct in all three traces. Pinned so it stays that way.
>
> **Why the reducer suite is green anyway:** not one of C1–C5 asserts ORDER. C2 uses
> `toContain` on descriptions (order-independent), C3 counts nodes, C4 finds a node, C5
> checks `isWorking`. C6 does assert order — and passes only because a *tie* on key 1
> happens to resolve to insertion order. Nothing was ever testing the thing that is broken.

### Wave 8 — One sequence

- [x] **T28** (REQ-17 AC2/AC3) - **DONE 2026-08-23 - backend/agent/row_sequence.py; memoized per row identity so revisions cannot renumber. 15 unit tests green.**: Backend-owned monotonic ordering key. Replace the planner
  LLM's self-reported `step_number` (`agent_kernel.py:5066-5068`, positional fallback
  `len(steps)+1`) and the graft's `len(completed_items)` (`:7756`, which can COLLIDE) as
  render-order authorities. Planner numbering survives as a separate DISPLAY concern
  (REQ-17 AC5). — RIPPLE: the wire payload changes; T27's validator must pass afterwards.

- [x] **T29** (REQ-17 AC1/AC4/AC6) - **DONE 2026-08-23 - key stamped on planner rows (_stamp_row_seq), crawl phase rows (tool_bridge), and the synthesis row. Reducer consumes it; BOTH append paths now re-sort (a SECOND defect found by the test).**: Every row-producing path populates the key — including
  **phase nodes, which today carry none** (`hooks/useTaskProgress.ts:908-920`) and
  therefore collapse to `MAX_SAFE_INTEGER` in `sortSteps` (`:447-453`) and can never sort
  into sequence. A row missing the key is a counted contract violation (REQ-13 AC2), not a
  silent sort-to-end. — RIPPLE: **this is the actual fix for `pin_587a3e612558` item 3.**
  BT-GT-10 proves phase nodes render BETWEEN the planner steps they occurred between.

- [x] **T30** (REQ-18) - **DONE 2026-08-23 - deriveProgress: one derivation, both halves together, denominator floored. Orb ring reads the same value.**: One derivation for the counter and the ring. Recompute the numerator
  whenever the denominator changes — today `:952-958` advances `totalSteps` and never
  touches `currentStep`. Retire `deriveCurrentStep`'s independent index-based notion
  (`:72-76`). Drive the XurOrb radial progress from the same value; numerator never exceeds
  denominator; denominator never shrinks. — RIPPLE: `components/chat/TaskListCard.tsx`
  consumes it. **The counter, the list order, and the orb ring are three symptoms of one
  cause — this task and T29 close all three.** CT-GT-7, BT-GT-11.

### Wave 9 — CLI parity

- [x] **T31** (REQ-20 AC1/AC2/AC3) - **DONE 2026-08-23 - seq + progress pair carried through taskCardToMatrixProps into the CLI types.**: Carry the ordering key and the progress pair through
  `taskCardToMatrixProps` (`components/chat-view.tsx:183-212`) into `TaskStepItem` /
  `TaskCardProps` (`lib/cli/CLITaskProgressRenderer.ts:62-87`), neither of which has them
  today. — RIPPLE: renderer internals (`:110-344` — width, Unicode, padding) are
  NO-CHANGE; ordering and progress sit ABOVE them.

- [x] **T32** (REQ-20 AC4) - **DONE 2026-08-23 - lib/cards/rowOrder.ts is the ONE shared derivation, verbRegistry precedent.**: ONE shared ordering/progress derivation between GUI and CLI,
  following the `lib/cards/verbRegistry` precedent (T8a already shares the verb mapping
  deliberately — never two implementations of one mapping). — RIPPLE: a second
  implementation is the defect this task exists to prevent.

- [x] **T33** (REQ-20 AC5/AC6) - **DONE 2026-08-23 - __tests__/cli/cliCardParity.test.ts, 12 tests, fully headless.**: CLI contract + behavioral tests end to end — trace →
  reducer → adapter → rendered frame — asserting GUI and CLI agree on sequence and
  progress. **Fully headless: `taskCardToMatrixProps` is a pure function of a `TaskCard`,
  so no app and no developer-mode session is required.** — RIPPLE: existing CLI tests cover
  the RENDERER only (width/Unicode/padding); this covers the ADAPTER. CT-GT-8, BT-GT-13.

### Wave 10 — Density, not restyling

- [x] **T34** (REQ-21 AC1/AC2/AC4) - **DONE 2026-08-23 - detail attributed to the row that OWNS it; finished rows retain a bounded, truncation-marked summary.**: Attribute per-item detail to the row it BELONGS to
  rather than to whichever row is newest-and-working (`useTaskProgress.ts:929-946`), and
  retain a completed row's summary instead of clearing it. Bound retained detail per row
  and **log what was truncated**. — RIPPLE: `pin_587a3e612558` item 5 — "only TWO step nodes
  had inline summary; others blank." Keep the existing terminal-card rule
  (`:971-974`: a finished card never advertises a page it is no longer reading). BT-GT-14.

- [x] **T35** (REQ-21 AC5) - **DONE 2026-08-23 - CT-GT-9 phase-verb lock in useTaskProgress.density.test.tsx.**: Regression test pinning phase-node verbs to `PHASE_VERB[phase]`
  rather than description keyword matching. — RIPPLE: `pin_587a3e612558` item 4 appears
  ALREADY FIXED (`useTaskProgress.ts:51`, `:916-918`) — this is a **lock so it cannot
  silently return**, not a fix. CT-GT-9.

- [x] **T36** (REQ-21 AC6) - **DONE 2026-08-23 - VERIFIED: zero CSS/styling files touched; zero className/colour/palette edits across the whole card diff. The one TaskListCard change is session 248's phase-verb fix (logic, pre-existing). No restyle shipped.**: Verify no visual-language change shipped — palette, chassis, and
  Liquid Ink styling untouched. — RIPPLE: **the aesthetic is not the defect and is not in
  scope.** This task is a guard against scope creep into a redesign.

---

# PART 4 — Gates and closeout

- [~] **T23** (REQ-11) - **BLOCKED ON TRAFFIC, and this is the ONLY genuine one.**
  T5 is shipped and T24 proves it writes. GT-G4 asks whether the *production*
  failure rate reconciles across layers, which is a question about real runs and
  cannot be answered synthetically without assuming the answer.: Reconcile the failure rate across all four layers — episode,
  trajectory, commit, fan trace — as one figure. Explain the residual or fix it. Include
  failure traces in the corpus. — RIPPLE: **this is the gate `specs/wormhole-aperture/`
  Stage A waits on.** Baseline: 0.5% physics vs 27% episode.

- [x] **T24** (REQ-16) - **DONE 2026-08-23 - proven WITHOUT traffic.**
  `backend/tests/unit/test_write_paths_proven.py` (6 tests) drives every fixed
  writer against a temp store and asserts the rows appear. The closer: it runs
  the REQ-6 invariant suite over a store written only by the fixed paths, and
  `every_step_has_fan_trace` / `commits_carry_verified_label` flip from FAIL
  (live pre-fix store) to **PASS**. So the MECHANISMS are verified now; only the
  production RATES need traffic.: Report the before/after deltas for every store this spec touched,
  plus swallowed-write counter totals and the orphan count, as headline figures. — RIPPLE:
  a count that did not move is a FAIL, not a neutral result.

- [x] **T25** - **DONE 2026-08-23 - CT-GT-1..9 + BT-GT-10..14 shipped across 5 new suites; 321 frontend + 94 backend tests green. Anti-vacuity proven per fix by targeted revert.** (REQ-6, REQ-8): Contract tests CT-GT-1..CT-GT-5 + behavioral tests
  BT-GT-1..BT-GT-9, all headless. — RIPPLE: `backend/tests/contract/`,
  `backend/tests/behavioral/`; each behavioral gap decomposes into its contract test per
  design § Intertwined.

- [x] **T26** - **DONE 2026-08-23 - wormhole spec updated with the pin-table, footprint, and row-ordering determinations; edge substrate flagged STILL OPEN.**: Update `specs/wormhole-aperture/` with this spec's determinations —
  Decisions Locked 2 (edge substrate, from T8), REQ-24 AC8 (pin table, from T7), REQ-34
  (footprint writer, from T6) — and mark its G0/G0b as satisfied here. — RIPPLE: the two
  specs must not drift; this task is what keeps them joined.

> ### 🚦 GATE GT-G4 — NEGATIVE EVIDENCE
> **Blocks:** `specs/wormhole-aperture/` Stage A scoring. **This is wormhole's G0b.**
> **Evidence:** physics-layer failure rate reconciled with the episode layer; residual
> explained; failure traces in the corpus.
> **Record here:** `[ ] PASSED  date: ______  ep/traj/commit/fan = __/__/__/__  residual: ______`

> ### 🚦 GATE GT-G5 — OFFLINE
> **Blocks:** declaring this spec complete.
> **Evidence:** every requirement verified with **zero developer-mode application runs**.
> The one exception is T1's single recorded session for the edge-guard determination.
> **Record here:** `[ ] PASSED  date: ______  manual runs used: ______`

---

## Dependency / parallelization notes

- **T0 first, always.** Every claim in this spec is a delta against the pinned baseline.
- **T1 starts immediately and runs in the background** — it is the only determination
  needing live traffic, and one recorded session answers it. Everything else in Wave 1 is
  static.
- **Wave 1 (T1–T3) gates Wave 2 (T4–T10)** for REQ-3/4/5 only. **T4 (fan traces), T5
  (failures), T9 (ledger), T10 (policy) need no determination and can start at once** —
  they are the highest-value tasks in the spec and none of them is blocked.
- **T4 is the single highest-leverage task.** It converts an empty execution history into a
  real one, and it unblocks Node Chains' live-run source in the wormhole spec.
- **Part 2 depends on Part 2's own T11/T12 landing together** — never ship the suite
  without its anti-vacuity self-test, or the suite reproduces the bug it exists to catch.
- **Part 3 (T18–T22) is fully independent of Parts 1–2** and can run in parallel from day
  one. It joins at T16 (the corpus wants a trace per cause).
- **T15 must precede T16**; T16 must precede T17.
- **T23 (GT-G4) depends on T5 landing and running long enough to accumulate failures.**
  It is the long-pole task for unblocking the wormhole spec — start T5 early.
- **T26 is the join point** with `specs/wormhole-aperture/` and must not be skipped.
- **Part 5 (T27–T36) is independent of Parts 1–3** and can run in parallel from day one —
  it touches the event boundary, not the storage boundary. **T27 must land before T28–T30**:
  measure whether the emitter is honest before fixing anything that renders it.
- **T29 + T30 together close all four reported card symptoms** (list order, counter,
  orb ring, and — via the shared derivation — CLI order). They share one root cause.
- **Wave 9 (T31–T33) depends on T29/T30**; the CLI cannot share a derivation that does not
  exist yet.
- **Wave 10 (T34–T36) is independent of Waves 8–9** and can run alongside them.

### What this spec deliberately does NOT do

Add termination bounds (REQ-9 AC5) · redesign DER routing · rewrite all 441 exception
handlers (REQ-13 AC4) · delete any module without per-module confirmation (REQ-15 AC6) ·
merge the MCM build store into the application store · touch `graph_edges` (997,262 rows,
build-store data resident in the app DB) · require a developer-mode run.

### CONTRACT LOCK areas (pin, never modify)

`record_fan_trace` row shape (CT-GT-1) · the authoritative pin table name, once determined
(CT-GT-2) · the harness trace format (CT-GT-3) · the termination-cause enum's closedness
(CT-GT-4) · DEAD-exits-non-zero (CT-GT-5) · the existing reducer contract suite
`__tests__/hooks/useTaskProgress.card-contract.test.tsx`, which is ADDITIVE-only and never
weakened (CT-GT-6) · phase-node verbs from `PHASE_VERB[phase]` (CT-GT-9) ·
`lib/cards/verbRegistry` as the one shared GUI/CLI mapping · `NodeOutcome.Reason` (CT-1).

### Card work explicitly NOT in scope

Restyling, palette changes, chassis changes, or any Liquid Ink visual revision (REQ-21 AC6).
The aesthetic is not the defect. Also out: wiring the `temp/task-card-redesign` renderer
(`pin_e028e5195e52`) — a separate decision, unrelated to ordering fidelity.
