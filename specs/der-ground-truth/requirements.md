# Requirements: DER GROUND TRUTH — Honest Recording, Offline Verification, Unified Termination

**Status:** Draft for implementation · **Blocks:** `specs/wormhole-aperture/` (gates G0 / G0b)
**Say "GROUND TRUTH" to reference this spec.**

---

## Decisions Locked

Resolved with the user on 2026-08-23. Do not re-litigate.

1. **Ground truth before intelligence.** No new scoring, learning, or ranking layer ships
   until the recorders underneath it are honest. A learning system fed a biased corpus
   produces a confident, self-consistent, wrong answer and looks healthy the whole time.
   This spec exists because the corpus is currently biased in a specific, measured way
   (see Introduction).
2. **Offline-first verification.** Every requirement here is provable headless — from the
   database, from a replayed trace, or from a unit test. **Nothing in this spec requires
   running the application in developer mode.** That constraint is the point, not a
   convenience: the user's DER work is currently gated on manual runs that cost too much
   time, and this spec's job is to remove that gate.
3. **Fan-trace emission is decoupled from context pruning.** The per-node execution trace
   is the agent's primary record of what it did. Emitting it as a side effect of a pruner
   that the DER loop never constructs is the root cause of an empty trace table.
4. **Termination is a shared contract, not per-loop patches.** The bounds already exist
   and are numerous; what does not exist is a single record of WHICH bound stopped a run.
   This spec adds the contract and the record, not more bounds.
5. **This spec blocks `specs/wormhole-aperture/`.** Its gates G0 (channel) and G0b
   (negative evidence) are satisfied HERE, not there. Wormhole's Stage 0 is reduced to
   claiming the recall channel; recorder integrity moves to this spec.

---

## Introduction

> **Scope note (2026-08-23):** the user asked for this spec to audit the ENTIRETY of
> DER/DAG execution and memory before `specs/wormhole-aperture/` begins, so that the
> foundation is solid once rather than patched repeatedly. The audit below is that sweep.
> It was performed statically (import graph, call-site tracing, exception-handling census)
> and against the live store — **no application run was required**, which is itself the
> proof of Decisions Locked 2.

### AUDIT — what was measured

Against the live application store `data/memory.db` (294 MB, last written 2026-08-23):

| Table | Rows | Consequence |
|---|---|---|
| `der_fan_traces` | **0** | The per-node execution trace has never been written. Any feature that learns from execution history has no source. |
| `mycelium_edges` | **0** | The coordinate-graph edge store — the posterior/coupling substrate — has never been written. `mycelium_nodes` holds 37 rows. |
| `semantic_entries` | **0** | Card footprints (`backend/memory/card_footprint.py`) and crystallised skills (`backend/memory/skills.py`) both write through this store. Neither has ever persisted. |
| `mycelium_pins` | **0** | `PinStore` writes here (`backend/memory/pin_store.py:193`). The 4 rows that exist live in a *different* table, `pins`. Two pin systems; the one the code writes to is empty. **Determined 2026-08-23 (T3): `pins` is authoritative** — same core schema plus five columns `mycelium_pins` lacks (`ref_status`, `last_validated`, `content_format`, `session_id`, `thread_id`), and `ref_status`/`last_validated` are exactly what wormhole REQ-24 AC9 needs for chain.md staleness. |
| `episodes` where `source_channel='recall'` | **0** | The recall channel has never fired in production (see `specs/wormhole-aperture/` REQ-0). |
| `caducean_trajectories` | 201 — **200 success, 1 failure** | The RL signal. |
| `der_commits` | 198 — **194 VERIFIED**, 2 UNVERIFIED, 2 FAILED | The verified-label ledger. |
| `episodes` (all channels) | 207 — including **55 `websocket`/`failure`** | The episode layer. |

### CORRECTIONS (2026-08-23) — two audit claims about the pin store were WRONG

Both are recorded rather than quietly edited. A spec whose thesis is "a record
that misrepresents reality is worse than no record" cannot itself carry
unverified claims.

**Correction 1 — there are no orphaned pin links.** The first draft reported 354
orphaned `mycelium_pin_links` rows. That was inferred from the table's NAME
without checking its shape. Verified: the table is polymorphic (`link_id`,
`source_type`, `source_id`, `target_type`, `target_id`, `relationship`, `weight`,
`created_at`) and **all 354 rows are `node -> node`. Zero reference a pin.**
REQ-4 AC3 asked for those links to be recovered or quarantined; there is nothing
to act on, and the AC is satisfied by this determination.

**Correction 2 — `mycelium_pins` was right all along; `pins` is contamination.**
The draft read "PinStore writes the empty table while `pins` holds the live rows"
as a bug, and the superset schema (`ref_status`, `last_validated`, …) looked like
corroboration. It is not:

| | `mycelium_pins` | `pins` |
|---|---|---|
| Created by | `backend/memory/db.py:344`, indexed `:467-469` | **nothing in `backend/`** |
| Schema | the application's 13 columns | the MCM build store's 18, byte-identical to `.mcm/coordinates.db` (554 rows) |
| Rows in `data/memory.db` | 0 | 4 |

`pins` is **MCM build-store contamination resident in the application DB**, the
same class as `file_nodes` (5,246), `code_events` (6,252) and `graph_edges`
(997,262) — all noted in the audit table above and all out of scope to change.
Row count was a misleading signal precisely because the contaminating store is
the more active one.

**How the error was caught:** switching `PinStore` to `pins` turned 30 of the 34
`test_pin_store.py` tests red, because their fixture builds the *application*
schema. The suite was defending the correct table. This is the anti-vacuity
principle working in the other direction — a test that can fail, failing.

**So REQ-4 is narrower than drafted.** `PinStore` is correct and unchanged. The
app pin path simply has not been exercised in production, which is why the table
is empty. `_PIN_TABLE` is now a named constant in `pin_store.py` so the
determination has somewhere to live, and CT-GT-2 asserts on it.

### Static audit — the import graph### Static audit — the import graph

Scanned 285 production modules under `backend/` (excluding tests and archives).
**33 have no production importer.** `importlib` appears in exactly one module
(`backend/agent/mcm_protocol/orchestrator.py`), so the `mcm_protocol/actions/*` entries are
dynamically dispatched false positives; **every other orphan is genuinely unreachable.**

| Orphaned module | Lines | Why it matters here |
|---|---|---|
| `backend/agent/recall_phases.py` | 573 | The recall channel — the sole writer of `source_channel='recall'` |
| `backend/agent/universal_gui_operator.py` | 402 | GUI execution surface |
| `backend/memory/audit.py` | 326 | A memory AUDIT module that is itself unaudited |
| `backend/agent/task_kernel.py` | 321 | Task execution |
| `backend/agent/spec_engine.py` | 228 | Spec execution |
| `backend/agent/trailing_director.py` | 154 | DER director surface |
| `backend/memory/card_footprint.py` | 122 | Card footprints — REQ-3 |
| `backend/agent/skill_registry.py` | 118 | Skill registration |
| `backend/agent/verify_rubric.py` | 85 | Verification rubric |

Symbol-level confirmation: `save_card_footprint` and `get_card_footprint` appear in
**exactly one file — their own**. `MemoryDistiller` and `RetentionPolicy` appear in **zero**
files. This is not "wired but failing"; it is "never called".

### Static audit — exception handling

Census of `except` blocks across `backend/agent/` and `backend/memory/`:

| Handling | Count | Share |
|---|---|---|
| Swallowed at `logger.debug` | 205 | 26% |
| Swallowed silently (`pass` / `continue`) | 236 | 30% |
| Logged at `warning` or louder | 337 | 43% |

**441 of 778 exception handlers — 57% — are invisible at default log level.**
`agent_kernel.py` alone accounts for 125 of them (45 debug + 80 silent), across
**14,314 lines** (17× the size of `der_loop.py` at 834).

This is the systemic root cause underneath every finding below: **a write that fails
silently is indistinguishable from a write that was never attempted.** Both leave an empty
table and a clean log. It is also, precisely, why the brittleness is hard to chase — more
than half the failure paths in the execution and memory layers are designed not to be seen.

### Finding 10 (added 2026-08-23, found by the corpus replay — not by the audit)

**Session exits are recorded under an identity nothing else uses.**
`caducean_session_exits` holds 431 rows spanning **two** session ids (`default`,
`session_iris`). `episodes` spans **47**. They overlap on **one**.

So the exit ledger cannot be joined to the runs it describes. This is not a
tidiness problem: the outer loop's held-out metric is `natural_exit_rate`
computed over exactly this ledger (`backend/agent/outer_loop.py`), so that metric
is being computed over a placeholder. And REQ-9's termination distribution — the
whole point of Part 3 — would be attributable to nothing.

Third instance of the same disease, in a third place: **a record that exists and
does not represent reality.** Pinned by the `exits_attributable_to_runs`
invariant. The fix belongs to whoever owns the exit call site and needs one
decision — which identity is canonical — so it is reported, not guessed.

### Finding 12 (2026-08-23) — NO edge anywhere has ever been scored

Raised while evaluating whether the wormhole spec could simply retarget from
`mycelium_edges` to `mycelium_landmark_edges`. It cannot, and the reason is
larger than the table choice:

| table | rows | traversal_count > 0 | hit_count > 0 |
|---|---|---|---|
| `mycelium_edges` | 0 | — | — |
| `mycelium_landmark_edges` | 6,201 | **0** | **0** |

The 6,201 landmark edges are pure structure, auto-created by `_auto_connect` at
landmark birth. Neither layer holds a single scored edge, so **both are
evidentially empty; they merely fail differently.** `mycelium_landmark_edges`
also lacks `observation_count` and `decay_rate` — the two columns the
diminishing-alpha posterior (`EdgeScorer.record_outcome`) actually runs on.

What IS populated and scored: `mycelium_traversals` (355 rows carrying real
`path_score` and `outcome`) and `mycelium_landmarks` (285 rows, 30 with
`activation_count` > 0 — that counter, unlike `access_count`, is genuinely
written). So the substrate question for `specs/wormhole-aperture/` is not
"which edge table" but **"landmarks + traversals, which carry evidence, versus
edges, which carry none at either level."**

### Finding 11 (2026-08-23) — landmark clustering sorts by a constant

`LandmarkCondenser` picks its top-6 cluster nodes by `access_count DESC`
(`backend/memory/mycelium/landmark.py:192-194`). **Nothing in the codebase ever
increments `access_count`.** It is set to 0 at `navigator.py:240`, read by the
encoder (`encoder.py:32,45`) and by the clusterer, and written nowhere.

So landmark crystallisation selects its "most accessed" nodes by sorting a
column that is always 0 — the selection is arbitrary. Found while probing
Finding 5/T8; not fixed here because the right fix (increment on activation, or
select on a different signal) is a design call for whoever owns crystallisation.

### The findings that matter

**Finding 1 — the execution trace is emitted by a component the DER loop never runs.**
`CaduceanTrajectoryRecorder.record_fan_trace` (`backend/agent/caducean_trajectory.py:293`)
has exactly one production caller: `DCP._emit_fan_traces` (`backend/agent/dcp.py:183`).
`DCP` is imported by `backend/agent/mcm_protocol/actions/dcp_prune.py` (build-time) and
`backend/agent/swarm/context_control.py` — and by neither `agent_kernel.py`,
`der_loop.py`, nor `iris_gateway.py` (verified: zero importers among the three). So the
DER loop never constructs a DCP, DCP never emits, and `der_fan_traces` stays at zero
regardless of how much work the agent does. In the same database and through the same
recorder object, `caducean_trajectories` accumulated 201 rows — so the connection works;
only this one write path is orphaned.

**Finding 2 — failures are recorded at the episode layer and lost before the physics layer.**
55 `websocket`/`failure` episodes exist. One failure trajectory exists. Two FAILED
der_commits exist. Whatever the true failure rate of DER is, the physics layer sees
approximately 0.5%. Every downstream learner — the outer loop, edge scoring, and every
Beta-Bernoulli posterior in `specs/wormhole-aperture/` — reads that layer. A posterior
that never receives negative evidence converges to 1.0 and ranks everything as excellent.

**Finding 3 — the DER execution ledger calls `persist()` and nothing persists.**
`ExecutionLedger` (`backend/agent/der_execution_ledger.py:212-225`) is documented as
"in-memory by default; `storage_path` enables JSON persistence". Both production call
sites construct it WITHOUT a storage path — `agent_kernel.py:7555` and `:8600`. Line 8603
then calls `_ledger.persist()`, which returns immediately because `_storage_path is None`
(`der_execution_ledger.py:339`). No ledger file exists anywhere on disk. So the ledger that
`scripts/validate_der_integrity.py` asserts on ("REQ-1: ledger records ALL labels
VERIFIED/UNVERIFIED/FAILED") records faithfully in memory and evaporates at process exit.
This is the sharpest instance of the systemic pattern: **code that appears to write, calls
a function named `persist`, and writes nothing** — with no error, because the no-op is by
design.

**Finding 4 — the edge scorer has a live caller behind a condition that may never hold.**
`EdgeScorer.record_region_mediator_outcome` IS called from the DER loop
(`agent_kernel.py:11536`), guarded by `if _region_node and _mediator_tool` (`:11530`), with
its failure path logging at `logger.debug` (`:11541-11542`). With 37 `mycelium_nodes`
covering the coordinate space against 201 trajectory points, `_region_node` resolution
plausibly fails almost always — and both the skip and any exception are invisible. Unlike
Findings 1–3 this one is **undetermined**, and REQ-5 requires determining it rather than
guessing.

Together these mean the system records its successes, forgets its failures, does not record
its execution at all, discards its ledger at exit, and cannot tell the difference between a
write that failed and a write that never happened. That is the condition this spec fixes.

### Why this also answers "DER feels brittle"

The bounds are not missing. `DER_MAX_CYCLES=40`, `DER_MAX_VETO_PER_ITEM=2`,
`DER_MAX_GRAFTS=3`, `DER_TOKEN_BUDGETS`, `MAX_DEPTH=3`
(`backend/agent/der_constants.py:196-237`), `_DER_TURN_BUDGET_S=600`
(`backend/agent/agent_kernel.py:125`), plus session 247's wall ledger, sufficiency gate,
and zero-yield cutoff. Eight-plus termination controls across four modules, each added
reactively after an incident.

What is missing is not another bound. It is the ability to answer **"why did this run
stop?"** from stored data. Today a run that hit its token budget, a run that converged
naturally, and a run that was killed by the turn wall-clock are indistinguishable
afterwards. That is what makes the loop feel brittle: not that it lacks limits, but that
its stopping behaviour is unobservable, so every incident requires a live reproduction.

### Success criteria

- A DER run writes `der_fan_traces` rows without any pruning having occurred.
- The failure rate visible at the physics layer is consistent with the failure rate at the
  episode layer, and the residual difference is explained rather than assumed.
- Every card that renders has a retrievable footprint.
- A single query answers "which bound terminated this run" for every run in the store.
- A recorded real session can be exported to a trace file and replayed through the
  standing harness with no application running.
- The regression corpus contains failure traces, not only successes.
- All of the above is verified without a single manual developer-mode run.

---

## Requirements

> **Numbering note:** REQ-12 is intentionally absent — the observability
> requirement it held was renumbered REQ-16 so it reads last. REQ-13/14/15 and REQ-17..21
> were added by the 2026-08-23 audit. No requirement was deleted.

# PART 1 — Honest recording

### REQ-1: The execution trace is written by the execution loop

**User Story:** As the system I want every executed node recorded when it executes, so
that the agent's history exists independently of whether its context happened to fill.

**Verified:** REAL GAP. `record_fan_trace` (`backend/agent/caducean_trajectory.py:293`)
writes `(ts, session_id, step_id, tool, args_hash, outcome, u, xi)` and is called only
from `DCP._emit_fan_traces` (`backend/agent/dcp.py:152,183`). `DCP` has zero importers
among `agent_kernel.py`, `der_loop.py`, `iris_gateway.py`. Live store: `der_fan_traces`
= 0 rows, while `caducean_trajectories` = 201 through the same recorder.

**Acceptance Criteria:**
- AC1: WHEN a DER node reaches a terminal outcome THEN THE SYSTEM SHALL write a
  `der_fan_traces` row for that node, regardless of whether any pruning has occurred.
- AC2: THE SYSTEM SHALL NOT make fan-trace emission conditional on `DCP` being
  constructed, on context size, or on any pruning threshold.
- AC3: THE SYSTEM SHALL preserve the existing row shape and the existing writer
  (`record_fan_trace`) — this requirement changes the CALL SITE, not the contract.
- AC4: THE SYSTEM SHALL keep emission off the critical path, following the daemon-thread
  discipline documented at `backend/agent/tool_bridge.py:1618-1629`.
- AC5: WHERE `DCP` does run, THE SYSTEM SHALL NOT double-write; emission is idempotent per
  `(session_id, step_id)`.
- AC6: THE SYSTEM SHALL record the node's terminal outcome faithfully — a FAILED node
  writes a FAILED row (this is REQ-2's precondition at the node level).

**Edge Cases:**
- A node raises before producing an outcome -> a row is still written with the
  reserved `unexpected` reason; a missing row and a failed row must never look alike.
- Caducean state unavailable -> `u`/`xi` are null; the row is still written.
- Very high node volume -> emission batches, but no node is dropped; a dropped batch is
  logged with its count (no silent loss).

### REQ-2: Failures reach the physics layer

**User Story:** As the tuner I want the failure rate visible to the learners to match the
failure rate that actually happened, so that no learner is trained on a success-only view.

**Verified:** REAL GAP, measured. `episodes`: 55 rows with `outcome_type='failure'`.
`caducean_trajectories`: 1 row with `outcome='failure'` out of 201.
`der_commits`: 2 FAILED out of 198. `CaduceanTrajectoryRecorder.record` (`:226`) takes
`outcome` as a required parameter, so the recorder supports failure — it is the call sites
that are not reaching it.

**Acceptance Criteria:**
- AC1: WHEN a DER step ends in a failed or unverified state THEN THE SYSTEM SHALL record
  a trajectory row carrying that outcome.
- AC2: THE SYSTEM SHALL record `verified_label` for ALL outcomes on the commit ledger —
  VERIFIED, UNVERIFIED, and FAILED alike.
- AC3: THE SYSTEM SHALL make the physics-layer and episode-layer failure counts
  reconcilable by a single query, and SHALL document any legitimate structural reason the
  two differ (e.g. one episode spanning several steps).
- AC4: THE SYSTEM SHALL report the reconciliation as a first-class number (REQ-6), not as
  a one-off investigation.
- AC5: THE SYSTEM SHALL NOT treat an unrecorded outcome as a success anywhere; an
  outcome that was not observed is `unknown`, and `unknown` is never scored as positive.

**Edge Cases:**
- A run is killed mid-step (turn budget, process exit) -> the step records the terminal
  state actually reached, never a fabricated success (this mirrors the card-footprint rule
  at `backend/memory/card_footprint.py:48-52`).
- A step is retried and later succeeds -> BOTH outcomes are recorded; collapsing a retry
  into its final success is exactly how failure evidence disappears.
- A partial outcome -> recorded as partial, not rounded to either pole.

### REQ-3: Card footprints persist

**User Story:** As the user I want to reference a past card by its ID and get its real
execution record, so that cross-conversation addressing works on data rather than on hope.

**Verified:** REAL GAP — **cause DETERMINED by the audit: never called.**
`backend/memory/card_footprint.py` has **zero production importers**, and the symbols
`save_card_footprint` / `get_card_footprint` appear in exactly one file — their own. The
module was implemented for `specs/task-card-v2-liquid-ink/` REQ-11 and never wired to a
call site. Consequently `semantic_entries` (`backend/memory/semantic.py:88`) holds **0
rows**. The same store backs `backend/memory/skills.py`, whose `MemoryDistiller` and
`RetentionPolicy` symbols appear in **zero** files — so `named_skills` is empty for a
related but distinct reason. The write is documented as never-raising and returning False
on failure (`card_footprint.py:57-59`), so had it been called and failed, that too would
have been silent.

**Acceptance Criteria:**
- AC1: WHEN a card reaches a terminal state THEN THE SYSTEM SHALL persist its footprint
  and the write SHALL be observable as having succeeded or failed.
- AC2: THE SYSTEM SHALL keep the never-raise guarantee (a failed footprint write must not
  break a user response) AND SHALL count failures so a persistent failure is visible
  rather than silent.
- AC3: THE SYSTEM SHALL make a footprint retrievable by `card_id` alone across
  conversations.
- AC4: THE SYSTEM SHALL wire `save_card_footprint` to the card-terminal path — the cause
  is DETERMINED (never called), so no further investigation is required for this store.
- AC5: THE SYSTEM SHALL separately determine why `MemoryDistiller` / `RetentionPolicy`
  (`backend/memory/skills.py`, `distillation.py`, `retention.py`) have zero references
  anywhere, and SHALL either wire or retire them — an unreferenced retention policy means
  nothing is retaining anything.
- AC6: THE SYSTEM SHALL add a contract test asserting the footprint writer HAS a production
  caller, so this class of "implemented but never wired" cannot recur silently for this
  module.

**Edge Cases:**
- The card never completes -> the footprint records the terminal state reached
  (existing documented behaviour, `card_footprint.py:48-52`).
- Duplicate `card_id` -> upsert, one row (existing behaviour, `card_footprint.py:19-22`).
- The store is unavailable at write time -> counted and retried on the next terminal card;
  never queued unboundedly.

### REQ-4: One pin store, not two

**User Story:** As the agent I want a pin I write to be a pin I can find, so that pin-based
features are not silently writing into an unread table.

**Verified:** REAL GAP. `PinStore` reads and writes `mycelium_pins` /
`mycelium_pin_links` (`backend/memory/pin_store.py:18,126,148,193,238`). Live store:
`mycelium_pins` = **0 rows**, `mycelium_pin_links` = 354 rows, and a separate `pins` table
holds 4 rows (the MCM build store `.mcm/coordinates.db` holds 547 in its own `pins`).
Links exist without the pins they link.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL determine which table is authoritative for application-runtime
  pins and SHALL record the determination.
- AC2: THE SYSTEM SHALL make `PinStore` read and write the authoritative table.
- AC3: THE SYSTEM SHALL explain the 354 orphaned `mycelium_pin_links` rows — links whose
  pins are absent — and SHALL either recover or quarantine them, never silently ignore
  them.
- AC4: THE SYSTEM SHALL NOT merge the application pin store with the MCM build store; they
  are separate stores by design (`CLAUDE.md`).
- AC5: THE SYSTEM SHALL add a contract test pinning the table name so a future edit cannot
  silently re-split the two.

**Edge Cases:**
- Both tables hold rows after the determination -> a one-time reconciliation is written and
  recorded; it is not left to "whichever the code happens to read".
- A consumer reads the non-authoritative table -> found by the REQ-6 invariant suite, not
  by a user report.

### REQ-5: The coupling substrate is written, or its absence is explained

**User Story:** As the architect I want to know whether the coordinate edge store is empty
because nothing writes it or because nothing needs it, before another spec is built on top
of it.

**Verified:** REAL GAP — **caller EXISTS, table EMPTY, cause UNDETERMINED.**
`mycelium_edges` = **0 rows** in both `data/memory.db` and `backend/data/memory.db`, while
`mycelium_nodes` = 37, `mycelium_landmark_edges` = 6201, `mycelium_landmarks` = 285, and
`mycelium_traversals` = 354. Unlike REQ-3, a live caller DOES exist:
`EdgeScorer(myc._store).record_region_mediator_outcome(...)` at
`backend/agent/agent_kernel.py:11536` — but it sits behind
`if _region_node and _mediator_tool` (`:11530`) and its exception path logs at
`logger.debug` (`:11541`). With 37 nodes against 201 trajectory points, region resolution
plausibly fails almost always, and both the skip and any failure are invisible.
`specs/wormhole-aperture/` Decisions Locked 2 justifies reusing this machinery — a
justification that currently rests on a code path that has produced zero rows.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL determine which of three causes applies — the guard at
  `agent_kernel.py:11530` never passes; the guard passes but the write raises and is
  swallowed at DEBUG (`:11541`); or edge state legitimately lives in
  `mycelium_landmark_edges` (6201 rows) and this table is vestigial. **Instrumenting the
  guard and the exception is the cheapest way to answer this and requires no application
  run beyond one recorded session.**
- AC2: THE SYSTEM SHALL record the determination in this spec before
  `specs/wormhole-aperture/` Stage A begins.
- AC3: WHERE the table is the intended substrate THE SYSTEM SHALL wire its writer and
  demonstrate a posterior moving from real outcome evidence.
- AC4: WHERE edge state legitimately lives elsewhere THE SYSTEM SHALL correct
  `specs/wormhole-aperture/` to name the real substrate, rather than building on the empty
  one.
- AC5: THE SYSTEM SHALL NOT resolve this by creating a third edge store.

**Edge Cases:**
- The answer is "both, for different purposes" -> both are documented with their distinct
  roles, and the wormhole spec names which one it extends.
- `graph_edges` (997,262 rows) turns out to be relevant -> its role is documented; note it
  is an MCM build-store table resident in the application DB and is out of scope to change.

# PART 2 — Offline verification

### REQ-6: Database-level invariant suite

**User Story:** As the maintainer I want the store itself checked for contradictions, so
that recording bugs surface as a failing assertion rather than as a live incident.

**Verified:** NEW. The precedent is `backend/agent/outer_loop.py:27-37`, which distinguishes
a guard that is `live` from one that `passed` precisely because "conflating 'no signal'
with 'no objection' is exactly what let a three-metric gate accept on one metric for
months."

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide a headless invariant suite runnable against any
  application store, asserting at minimum:
  - every `episodes` row with `outcome_type='failure'` reconciles to physics-layer
    evidence (REQ-2 AC3);
  - every executed DER step has a `der_fan_traces` row (REQ-1);
  - every `der_commits` row carries a `verified_label`;
  - every terminal card has a footprint (REQ-3);
  - no `mycelium_pin_links` row references an absent pin (REQ-4 AC3);
  - every completed run records a termination cause (REQ-9).
- AC2: THE SYSTEM SHALL report each invariant as PASS / FAIL / **DEAD** — where DEAD means
  the invariant's input could not be computed. A DEAD invariant SHALL NOT report as PASS.
- AC3: THE SYSTEM SHALL exit non-zero on any FAIL or DEAD result.
- AC4: THE SYSTEM SHALL run read-only against the store and SHALL NOT require the
  application to be running.
- AC5: THE SYSTEM SHALL print a per-invariant report with the offending row counts and
  example keys, so a failure is actionable without a second query.

**Edge Cases:**
- The store is empty (fresh install) -> invariants over absent data report DEAD, not PASS.
  An empty store proves nothing.
- The store is very large -> queries are indexed and bounded; the suite states its own
  runtime.
- A legitimate structural exception exists -> it is encoded as a named exemption with a
  written reason, never by loosening the assertion.

### REQ-7: Trace export from recorded sessions

**User Story:** As the developer I want to replay what actually happened, so that fixing
DER does not require reproducing it by hand.

**Verified:** The consumer already exists. `scripts/validate_der_cli_harness.py` accepts
`--trace t.json` and documents the frame format in its module docstring
(`task:start` / `task:progress` / terminal frames with identity keys). Nineteen
`scripts/validate_*.py` harnesses exist. What is missing is a producer: nothing converts a
recorded session in `data/memory.db` into that format.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide an exporter that reads a recorded session from the
  application store and emits a trace file in the format the existing harness consumes.
- AC2: THE SYSTEM SHALL support selecting sessions by id, by date range, and **by outcome**
  — exporting failure sessions must be as easy as exporting successes (REQ-11).
- AC3: THE SYSTEM SHALL run read-only and SHALL NOT require the application to be running.
- AC4: THE SYSTEM SHALL redact or omit user content not required by the harness, so a
  trace corpus can be committed without carrying conversation text.
- AC5: WHERE a session's record is incomplete THE SYSTEM SHALL emit the trace with an
  explicit gap marker rather than silently interpolating frames.

**Edge Cases:**
- A session predates a schema change -> exported with a schema-version marker; the harness
  skips frames it cannot interpret and REPORTS the skip.
- A session has no terminal frame -> exported as-is; the missing terminal is exactly the
  kind of defect the corpus should preserve.
- Export produces an empty trace -> non-zero exit with the reason, never a silent empty
  file.

### REQ-8: Regression corpus and standing replay

**User Story:** As the maintainer I want every DER change checked against real history
automatically, so that "did I break something" stops being a manual question.

**Verified:** NEW as a corpus; the replay machinery exists
(`scripts/validate_der_cli_harness.py`, `validate_der_integrity.py`,
`validate_der_card_lifecycle.py`, `validate_der_telemetry.py`,
`validate_der_tool_resolution.py`, `validate_websearch_trajectory.py`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL maintain a committed corpus of exported traces covering at minimum
  successful runs, failed runs, runs terminated by each distinct bound (REQ-9), and runs
  with tool failures across FAULTLINE dimensions.
- AC2: THE SYSTEM SHALL replay the full corpus through the standing harnesses in one
  command, headless, exiting non-zero on any contract or behaviour break.
- AC3: THE SYSTEM SHALL make adding a trace to the corpus a one-command operation, so a
  newly observed defect becomes a permanent regression guard rather than a note.
- AC4: THE SYSTEM SHALL report corpus coverage — how many traces, of which outcome
  classes, spanning what date range — so gaps in the corpus are visible.
- AC5: THE SYSTEM SHALL NOT allow corpus growth to become the only verification; the
  invariant suite (REQ-6) runs against the LIVE store, which the corpus cannot replace.

**Edge Cases:**
- The corpus grows large -> traces are bounded in size and count per outcome class, with
  the selection rule recorded; **what is dropped is logged** (no silent truncation).
- A trace becomes invalid after an intentional contract change -> it is re-exported and the
  change is recorded, never edited by hand to pass.
- No failure traces exist to export -> **that is a REQ-11 gate failure**, not a corpus
  problem.

# PART 3 — Unified termination

### REQ-9: Every run records why it stopped

**User Story:** As the tuner I want a single query to tell me which bound ended a run, so
that loop pathologies are diagnosable from data instead of from a reproduction.

**Verified:** The bounds exist and are scattered. `DER_MAX_CYCLES=40`,
`DER_MAX_VETO_PER_ITEM=2`, `DER_MAX_GRAFTS=3`, `DER_MAX_CONCURRENT_STEPS=3`,
`MAX_DEPTH=3`, `DER_TOKEN_BUDGETS` (`backend/agent/der_constants.py:83-237`);
`_DER_TURN_BUDGET_S=600` (`backend/agent/agent_kernel.py:125`);
`DirectorQueue.is_complete` / `hit_cycle_limit` (`backend/agent/der_loop.py:698,707`);
plus session 247's wall ledger, sufficiency gate, and zero-yield cutoff
(`docs/architecture/FAULTLINE.md` §11). `caducean_session_exits` holds 415 rows, so an
exit record exists — what is missing is a uniform, enumerated CAUSE across all of them.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define a closed, enumerated termination-cause vocabulary covering
  every existing exit path: natural completion, sufficiency gate, cycle cap, token budget,
  turn wall-clock, veto cap, graft cap, depth cap, zero-yield cutoff, permission refusal,
  user abort, and a reserved `unexpected`.
- AC2: WHEN a run ends THEN THE SYSTEM SHALL record exactly one termination cause from
  that vocabulary.
- AC3: THE SYSTEM SHALL record, alongside the cause, the bound's configured value and the
  measured value at exit, so "how close was it" is answerable.
- AC4: THE SYSTEM SHALL make termination cause queryable and reportable by distribution —
  "what stopped my last 100 runs" is one query.
- AC5: THE SYSTEM SHALL NOT add a new bound in this spec. This requirement records the
  bounds that exist.
- AC6: THE SYSTEM SHALL follow the closed-vocabulary discipline already used for
  `NodeOutcome.Reason` (`backend/agent/nodes/outcome.py:40`) — an unrecognised cause lands
  in `unexpected` and is counted, never discarded.

**Edge Cases:**
- Two bounds trip in the same cycle -> the cause recorded is the one that actually stopped
  dispatch, and the other is recorded as a co-occurring near-miss. Both are visible.
- The process exits without running its exit path -> the run's last known state is
  reconstructable, and the absence of a cause is itself an invariant failure (REQ-6 AC1).
- A bound is disabled by configuration -> recorded as disabled at exit, so a distribution
  is never read against the wrong configuration.

### REQ-10: Termination behaviour is testable offline

**User Story:** As the developer I want to prove a loop terminates correctly without
running the app, so that termination fixes stop costing a manual session each.

**Verified:** NEW. `scripts/validate_der_integrity.py` already replays a DER trajectory
headless and asserts REQ-level behaviours, so the pattern is established.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide a synthetic-trace driver that can force each termination
  cause deterministically.
- AC2: THE SYSTEM SHALL assert, per cause, that the run stops, records the correct cause,
  and finalises honestly — a run stopped by a bound SHALL NOT report success.
- AC3: THE SYSTEM SHALL assert that no termination path leaves a card without a terminal
  frame (this is the existing B-2 invariant in
  `scripts/validate_der_cli_harness.py`, extended to every cause).
- AC4: THE SYSTEM SHALL run in the standing harness on every validation.
- AC5: THE SYSTEM SHALL NOT require network, TTS, a model, or a GUI.

**Edge Cases:**
- A cause cannot be forced synthetically -> that is reported as an untestable path and
  recorded as a known gap, never quietly omitted from the suite.
- A cause fires that the driver did not intend -> the test fails; a bound tripping earlier
  than expected is a finding.

### REQ-11: The corpus must contain negative evidence (the gate the wormhole spec depends on)

**User Story:** As the architect I want proof that the system records its failures before
any learner is trained on its record, so that no scoring layer is built on a
success-only view.

**Verified:** REAL GAP, measured. Physics-layer failure rate ≈ 0.5% (1/201) against an
episode-layer failure rate of ≈ 27% (55/207).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL report the failure rate at each layer — episode, trajectory,
  commit ledger, fan trace — as one reconciled figure.
- AC2: THE SYSTEM SHALL NOT permit `specs/wormhole-aperture/` Stage A scoring to begin
  until the physics-layer failure rate is consistent with the episode layer and the
  residual is explained.
- AC3: THE SYSTEM SHALL include failure traces in the regression corpus (REQ-8 AC1).
- AC4: THE SYSTEM SHALL record the reconciled figure with its date and query in this
  spec's task list, so the gate can be audited later.
- AC5: IF the reconciliation cannot be computed THEN the gate is DEAD and SHALL block —
  not pass (REQ-6 AC2).

**Edge Cases:**
- The true failure rate is genuinely near zero -> that must be DEMONSTRATED by the
  reconciliation, not assumed from the current numbers. An unrecorded failure and an
  absent failure look identical, and that is precisely the ambiguity this gate exists to
  resolve.
- The rates differ for a legitimate structural reason -> the reason is written down and
  encoded as a named exemption (REQ-6 edge case), never as a loosened threshold.

### REQ-13: A silent-failure policy for the execution and memory layers

**User Story:** As the maintainer I want a failed operation to be distinguishable from an
operation that never ran, because today they are identical and that is why five stores sat
empty unnoticed.

**Verified:** REAL GAP, measured across `backend/agent/` and `backend/memory/`: **441 of
778 exception handlers (57%) swallow at `logger.debug` or silently via `pass`/`continue`**
— 205 debug, 236 silent, against 337 logged at warning or louder. `agent_kernel.py` alone
carries 125 of them across 14,314 lines. Concrete instances found by this audit:
`agent_kernel.py:11541` (edge scoring, REQ-5), `card_footprint.py:57-59` (documented
never-raise), `caducean_trajectory.py:315` (fan-trace write). Each is individually
defensible — observability must not break the thing it observes — and collectively they
make the system unobservable.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define a policy distinguishing three cases: a failure that must
  never break the caller AND must be COUNTED; a failure that is genuinely expected and may
  be ignored; and a failure that indicates a defect and must be logged at warning or
  louder.
- AC2: THE SYSTEM SHALL require every swallowed failure on a WRITE path to increment a
  named counter, so persistent silent failure becomes a number rather than an absence.
- AC3: THE SYSTEM SHALL expose those counters through the invariant suite (REQ-6), so a
  non-zero swallowed-write counter is a reportable condition.
- AC4: THE SYSTEM SHALL apply AC2 to every write path this spec touches — fan traces,
  trajectories, commits, footprints, pins, edges, ledger — and SHALL NOT attempt a
  wholesale rewrite of all 441 handlers.
- AC5: THE SYSTEM SHALL require any NEW swallowed handler on a write path to carry a
  counter, enforced at review.
- AC6: THE SYSTEM SHALL NOT convert observability failures into user-visible errors; the
  never-break-the-caller guarantee is preserved throughout.

**Edge Cases:**
- A counter itself fails to increment -> the increment is a local integer, not I/O; it
  cannot fail in a way that matters.
- A high-frequency expected failure inflates a counter -> counters are per-cause, so an
  expected cause is readable separately from a defect cause.
- A handler is genuinely correct to ignore -> it is annotated as such with a reason, which
  makes the judgement reviewable instead of implicit.

### REQ-14: The execution ledger persists

**User Story:** As the tuner I want the verified-label ledger to survive process exit, so
that the record the integrity harness asserts on actually exists after a run.

**Verified:** REAL GAP. `ExecutionLedger` is "in-memory by default; `storage_path` enables
JSON persistence" (`backend/agent/der_execution_ledger.py:212-225`). Both production call
sites omit `storage_path` — `backend/agent/agent_kernel.py:7555` and `:8600`. Line 8603
calls `_ledger.persist()`, which returns immediately when `_storage_path is None`
(`der_execution_ledger.py:339`). No ledger file exists on disk anywhere under `data/`.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL construct the execution ledger with a storage path in production,
  so `persist()` writes.
- AC2: THE SYSTEM SHALL make a `persist()` call that cannot persist a COUNTED condition
  (REQ-13 AC2) rather than a silent no-op.
- AC3: THE SYSTEM SHALL preserve the existing atomic-write behaviour
  (`der_execution_ledger.py:348` writes through a `.tmp` file).
- AC4: THE SYSTEM SHALL make ledger records readable by the invariant suite (REQ-6) and
  exportable into the trace corpus (REQ-7).
- AC5: THE SYSTEM SHALL keep ledger writes off the critical path.
- AC6: THE SYSTEM SHALL retain the in-memory-only mode for tests, so this change adds a
  production configuration rather than removing a capability.

**Edge Cases:**
- The storage path is unwritable -> counted per REQ-13 AC2, logged once, execution
  continues.
- Two kernels share a conversation id -> writes are atomic per `:348`; last write wins and
  the collision is counted.
- The ledger grows unbounded -> size is bounded with the retention rule recorded, and what
  is dropped is logged.

### REQ-15: Orphan inventory — decide, do not accumulate

**User Story:** As the maintainer I want every unreachable module either wired or retired,
so that the codebase stops carrying features that look implemented and are not.

**Verified:** REAL GAP, measured. 285 production modules scanned under `backend/`;
**33 have no production importer**. `importlib` appears in exactly one module
(`backend/agent/mcm_protocol/orchestrator.py`), so `mcm_protocol/actions/*` are dynamically
dispatched false positives and every other orphan is genuinely unreachable. Notable:
`recall_phases.py` (573), `universal_gui_operator.py` (402), `memory/audit.py` (326),
`task_kernel.py` (321), `spec_engine.py` (228), `trailing_director.py` (154),
`card_footprint.py` (122), `skill_registry.py` (118), `verify_rubric.py` (85).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL record, for every orphan, one of three dispositions: WIRE (it
  should be called and is not), RETIRE (it is superseded — remove it), or KEEP-DORMANT
  (deliberately unreferenced, with a written reason and an expiry review date).
- AC2: THE SYSTEM SHALL NOT leave any orphan undecided.
- AC3: THE SYSTEM SHALL provide an orphan-detection check runnable headless, so the count
  is tracked rather than rediscovered.
- AC4: THE SYSTEM SHALL account for dynamic dispatch (`importlib`) so dynamically resolved
  modules are not falsely reported.
- AC5: THE SYSTEM SHALL fail the check WHEN the orphan count rises above the recorded
  baseline without a disposition — new orphans are a regression, existing ones are debt.
- AC6: THE SYSTEM SHALL NOT delete any module in this spec without the user's explicit
  confirmation per module; RETIRE records the recommendation, it does not execute it.

**Edge Cases:**
- A module is reachable only from a script or an entry point (`main.py`,
  `iris_supervisor.py`, `inference_router.py`) -> classified KEEP-DORMANT with the entry
  point named; entry points are not orphans.
- A module is imported only by tests -> that is an orphan for this purpose, and
  `recall_phases.py` is the worked example.
- An orphan is a deliberate future hook -> KEEP-DORMANT with an expiry date, so "future"
  does not silently become "forever".

### REQ-16: Observability of this spec's own work

**User Story:** As the tuner I want the recording fixes themselves measured, so that
"the recorders are honest now" is a number rather than a claim.

**Verified:** NEW.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL report row-count deltas for `der_fan_traces`,
  `caducean_trajectories` (by outcome), `der_commits` (by label), `semantic_entries`,
  pins, `mycelium_edges`, and ledger records, before and after each fix.
- AC5: THE SYSTEM SHALL report the swallowed-write counter totals (REQ-13 AC2) and the
  orphan count (REQ-15 AC3) as headline figures, so both trend rather than being
  rediscovered.
- AC2: THE SYSTEM SHALL scope every log line added by this spec with a session or thread
  identifier.
- AC3: THE SYSTEM SHALL keep all instrumentation off the critical path.
- AC4: THE SYSTEM SHALL report the invariant suite's PASS / FAIL / DEAD counts as a single
  headline figure per run.

**Edge Cases:**
- A count does not move after a fix -> the fix did not work; this is a FAIL, not a
  neutral result.
- Counts move for an unrelated reason (a busy week of usage) -> deltas are reported per
  run, not only in aggregate, so a confound is visible.

---

# PART 5 — The task progress card tells the truth

> **Why the card belongs in GROUND TRUTH and not in a UI spec.** The user's report is that
> the card "works fine with simulated emit events but not when it comes to real work by the
> agent." That is this spec's thesis exactly, one layer up: the record does not faithfully
> represent what happened, so everything downstream renders a lie — and the tests certify
> it. The card is not a styling problem. It is a **recording-fidelity problem at the event
> boundary**, the same disease as the empty tables at the storage boundary.
>
> Prior sessions already isolated three of these (`pin_587a3e612558`, session 247 FINAL,
> items 3/4/5) and they remain open. The audit below adds the mechanism.

### AUDIT — the card

**Finding 5 — phase nodes are unnumbered, so they can never sort into sequence.**
`sortSteps` (`hooks/useTaskProgress.ts:447-453`) maps a missing `stepNumber` to
`Number.MAX_SAFE_INTEGER`. Progressive phase nodes are created without one
(`useTaskProgress.ts:908-920` — the literal carries `id`, `description`, `status`,
`phase`, and no `stepNumber`). Therefore **every phase node sorts after every planner
step, permanently**, regardless of when it actually occurred, and phase nodes tie with each
other at `MAX_SAFE_INTEGER` so their relative order is whatever insertion produced. The
comment at `:442-446` states rows "render in the backend's SEMANTIC step_number order" —
phase nodes have no semantic number to render by. This is `pin_587a3e612558` item 3
("step nodes NOT in sequential list order despite stepNumber sort"), and the mechanism is
now established: not a sort bug, a **missing-key** bug.

**Finding 6 — the counter's denominator advances without its numerator.**
In the phase-progress branch the returned partial sets
`totalSteps: Math.max(card.totalSteps, steps.length)` (`useTaskProgress.ts:958`, whose own
comment reads "Keep the orb badge denominator in sync with appended phase nodes") but
**never recomputes `currentStep`**. The denominator counts rendered rows; the numerator
holds a stale value from a different derivation. `deriveCurrentStep` (`:72-76`) is
index-based (`workingIdx + 1`), so combined with Finding 5 — where the working phase node
is pinned to the END of the sorted array — recomputing it would instead read as
N-of-N immediately. Either way the pair is incoherent.
**The same `totalSteps` feeds the orb badge denominator, so the XurOrb radial progress
inherits this desync identically.** The counter, the list order, and the ring are three
symptoms of one cause.

**Finding 7 — there is no single authoritative sequence.** Four numbering authorities
disagree: the planner's LLM assigns `step_number` from its own plan JSON
(`backend/agent/agent_kernel.py:5066-5068`, with a positional fallback
`len(steps) + 1`); grafts take `len(completed_items)` (`:7756`), which can **collide** with
a planner-assigned number; phase nodes take none (Finding 5); and the frontend derives
position three separate ways — `stepNumber` sort, `deriveCurrentStep` index, and
`steps.length` as denominator. No component owns the sequence.

**Finding 8 — the contract suite pins the reducer, not the emitter.**
`__tests__/hooks/useTaskProgress.card-contract.test.tsx` replays REAL captured WS traces
(conv-44/49/51, per `pin_c456f10e048a`) through `useTaskProgress`. That is genuinely good
practice and it caught a real bug when written. But it asserts the FRONTEND's handling of
whatever the backend sent. **If the backend emitted a bad ordering, the replay reproduces
it faithfully and the assertions — written against what was observed — encode the defect as
correct.** Nothing anywhere pins the backend emitter's numbering and ordering contract.
Hand-written simulated emits are well-formed by construction; real DER runs are not. This
is precisely why the card passes its tests and fails in front of the user.

**Finding 9 — the CLI inherits the disorder and cannot even detect it.**
`taskCardToMatrixProps` (`components/chat-view.tsx:183-212`) adapts the already-sorted GUI
`TaskCard` into `TaskCardProps`. But `TaskStepItem`
(`lib/cli/CLITaskProgressRenderer.ts:62-77`) has **no `stepNumber` field**, and
`TaskCardProps` (`:79-87`) has **no `currentStep`/`totalSteps`**. So the CLI inherits the
GUI's ordering wholesale, has no key with which to detect or correct it, and shows no
counter at all. Existing CLI tests (`__tests__/cli/CLITaskProgressRenderer.test.ts`,
`.baseline.test.ts`) cover width, Unicode, and padding — the RENDERER — never the adapter
or the ordering. Good news for testability: `taskCardToMatrixProps` is a pure synchronous
function of a `TaskCard`, so a full CLI contract test is writable **entirely offline** —
trace → reducer → adapter → renderer → assert. No app, no developer mode.

### REQ-17: One authoritative step sequence

**User Story:** As the user I want the card's rows to appear in the order the agent
actually did the work, so that reading top-to-bottom tells me what happened.

**Verified:** Findings 5 and 7 above.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define exactly ONE authoritative ordering key for card rows, and
  every row-producing path — planner steps, phase nodes, grafts, synthesis — SHALL populate
  it.
- AC2: THE SYSTEM SHALL assign that key from a monotonic, backend-owned sequence, NOT from
  the planner LLM's self-reported `step_number` and NOT from `len(completed_items)`.
- AC3: THE SYSTEM SHALL guarantee the key is unique per card — a collision is a contract
  violation, not a tie to be broken.
- AC4: THE SYSTEM SHALL order phase nodes chronologically among planner steps, so a phase
  that occurred between steps 2 and 3 renders between them.
- AC5: THE SYSTEM SHALL preserve the planner's semantic numbering as a SEPARATE display
  concern where it is meaningful, without conflating it with render order.
- AC6: IF a row arrives without the ordering key THEN THE SYSTEM SHALL record a contract
  violation (REQ-13 AC2 counter) rather than silently sorting it to the end.

**Edge Cases:**
- Two rows legitimately occur at the same instant -> the backend sequence still assigns
  distinct values; simultaneity is not a collision.
- A row arrives out of order over the wire -> it sorts into place by key; arrival order
  never determines render order.
- A rehydrated card (REQ from task-card-v2 REQ-4) -> keys are persisted and restored, so
  rehydration reproduces the original order exactly.

### REQ-18: The counter and the orb derive from the authoritative sequence

**User Story:** As the user I want the counter and the ring around the orb to agree with
the list I am looking at, because three disagreeing progress indicators are worse than one.

**Verified:** Finding 6 — `useTaskProgress.ts:958` advances `totalSteps` without
recomputing `currentStep`; the same value feeds the orb badge denominator.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL derive the counter's numerator and denominator from the SAME row
  collection the list renders, in one place.
- AC2: THE SYSTEM SHALL recompute the numerator whenever the denominator changes.
- AC3: THE SYSTEM SHALL drive the XurOrb radial progress from that same single derivation —
  never from an independently maintained value.
- AC4: THE SYSTEM SHALL guarantee the numerator never exceeds the denominator, and SHALL
  record a contract violation if it would.
- AC5: THE SYSTEM SHALL make the terminal state consistent: a card that reaches `done`
  reads N-of-N with all rows terminal.
- AC6: THE SYSTEM SHALL NOT let the denominator shrink; discovered work grows it
  monotonically.

**Edge Cases:**
- Work is discovered after `task:start` (the documented case at `:872-874`) -> the
  denominator grows and the numerator is recomputed in the same update, never one without
  the other.
- A step is vetoed or skipped -> it is counted in the denominator and resolved in the
  numerator; a skipped step is terminal, not perpetually pending.
- Zero steps executed -> the card reads 0-of-0 and terminates honestly rather than showing
  a spinning ring.

### REQ-19: The event emitter's contract is pinned, not just the reducer

**User Story:** As the maintainer I want a malformed event stream to fail a test at the
backend boundary, so that the frontend is never asked to render a lie convincingly.

**Verified:** Finding 8. `__tests__/hooks/useTaskProgress.card-contract.test.tsx` replays
captured traces through the reducer; no test asserts anything about what the backend is
permitted to emit.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define an emitter contract for the card event stream covering at
  minimum: the ordering key is present and unique (REQ-17), every `task:start` reaches
  exactly one terminal frame, `stepNumber` never collides, and a phase transition carries
  its `phase` and `phase_sequence`.
- AC2: THE SYSTEM SHALL validate a captured trace AGAINST that contract independently of
  how any frontend renders it.
- AC3: THE SYSTEM SHALL apply the validator to the existing captured traces (conv-44/49/51)
  and record which of them VIOLATE the contract — **this is the measurement that explains
  why the suite is green while the card is wrong.**
- AC4: THE SYSTEM SHALL run the emitter contract over freshly exported real traces
  (REQ-7), not only over the historical captures.
- AC5: THE SYSTEM SHALL keep the existing reducer contract tests unchanged — the emitter
  contract is ADDITIVE. A reducer test asserting today's behaviour is not weakened; it is
  joined by a test asserting the input was legitimate in the first place.
- AC6: IF a captured trace is found to violate the contract THEN THE SYSTEM SHALL fix the
  EMITTER, and SHALL NOT adjust the reducer to accommodate a malformed stream.

**Edge Cases:**
- A historical trace violates the contract but the reducer test depends on that trace ->
  the trace is kept as a REGRESSION fixture explicitly labelled as malformed input, and a
  new conformant trace is captured. Neither test is deleted.
- The contract itself proves wrong -> it is a spec-level conflict; report it per the
  project's test rule, do not loosen the assertion to make a run green.
- Simulated events are used in a test -> they must pass the same emitter contract, so
  "works with simulated events" stops being a weaker standard than reality.

### REQ-20: The CLI card shares the ordering and progress contract

**User Story:** As a developer in CLI mode I want the same execution story the GUI shows,
verified the same way, without launching the app to check.

**Verified:** Finding 9. `taskCardToMatrixProps` (`components/chat-view.tsx:183`) is a pure
function of a `TaskCard`; `TaskStepItem` (`lib/cli/CLITaskProgressRenderer.ts:62`) carries
no ordering key and `TaskCardProps` (`:79`) carries no progress pair. Existing CLI tests
cover width/Unicode/padding only. The verb vocabulary is ALREADY deliberately shared via
`lib/cards/verbRegistry` (design note T8a) — that precedent is the model to follow.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL carry the REQ-17 ordering key through the GUI-to-CLI adapter into
  the CLI row type.
- AC2: THE SYSTEM SHALL render CLI rows in the authoritative order, derived from the key
  rather than inherited from array position.
- AC3: THE SYSTEM SHALL surface the REQ-18 progress pair in the CLI card.
- AC4: THE SYSTEM SHALL share ONE ordering/progress derivation between the GUI and the CLI,
  following the `verbRegistry` precedent — never two implementations of the same mapping.
- AC5: THE SYSTEM SHALL contract-test the ADAPTER, not only the renderer: trace → reducer →
  adapter → rendered frame, asserted end to end.
- AC6: THE SYSTEM SHALL run every CLI card test headless, with no application and no
  developer-mode session.

**Edge Cases:**
- The CLI renders a card the GUI never showed (dev-mode-only run) -> the same contract
  applies; the CLI is not a lesser surface.
- A row's target text exceeds the fixed 66-column inner width -> existing truncation applies
  and is unaffected by ordering; the two concerns stay separate.
- The GUI and CLI disagree on a rendered frame -> that is a contract-test failure naming
  which derivation diverged, not a cosmetic difference to be tolerated.

### REQ-21: The card surfaces what the agent is actually doing

**User Story:** As the user I want each row to tell me what happened in it, because the
aesthetic is already right and the information density is what is underselling it.

**Verified:** `pin_587a3e612558` item 5 — "Only TWO step nodes had inline summary
(activeDetail); others blank," because per-page detail targets **only the newest working
phase node** (`hooks/useTaskProgress.ts:929-946`: `workingIdx` resolves to the last working
phase node, and only that row receives `activeDetail`/`activeProgress`/`url`). Item 4 of
the same pin — phase nodes labelled with the wrong verb — appears ADDRESSED: phase nodes now
carry `phase` and the renderer derives the verb from it (`useTaskProgress.ts:51`,
`:916-918`), so that one needs a regression test rather than a fix.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL retain a completed row's detail rather than clearing it when the
  next phase begins, so a finished row still says what it did.
- AC2: THE SYSTEM SHALL attribute per-item detail to the row it BELONGS to, not to whichever
  row happens to be newest-and-working.
- AC3: THE SYSTEM SHALL keep live detail distinct from retained summary — a finished card
  must never advertise a page it is no longer reading (the existing rule at
  `useTaskProgress.ts:971-974` stands).
- AC4: THE SYSTEM SHALL bound retained detail per row so a long run cannot grow the card
  without limit, and SHALL log what it truncated.
- AC5: THE SYSTEM SHALL add a regression test pinning phase-node verbs to `PHASE_VERB[phase]`
  rather than description keyword matching, so `pin_587a3e612558` item 4 cannot silently
  return.
- AC6: THE SYSTEM SHALL NOT change the card's visual language, palette, or chassis. This
  requirement is about WHAT is surfaced, not how it is styled.

**Edge Cases:**
- A row genuinely has no detail -> it renders with no summary line rather than an empty
  placeholder; absence is honest.
- Detail arrives for a row that already terminated -> it is retained as summary, not
  re-opened as live activity.
- Two details race for one row -> the later wins for LIVE display and both are retained in
  the bounded summary, so nothing observed is silently dropped.

---

## Non-Requirements (Out of Scope)

- **Adding new termination bounds.** REQ-9 records the ones that exist. New bounds require
  evidence from the distribution this spec produces.
- **Changing DER's routing or planning logic.** This spec makes DER observable; it does not
  redesign it.
- **Merging the MCM build store into the application store.** They are separate by design
  (`CLAUDE.md`). `graph_edges` (997,262 rows) is out of scope to change.
- **Any wormhole, aperture, or node-chain functionality.** Those live in
  `specs/wormhole-aperture/`; this spec only satisfies their entry gates.
- **A UI for traces, invariants, or termination distributions.** Command-line reports only.
- **Retroactively repairing historical records.** The corpus starts from what exists;
  history is not fabricated.
- **Requiring developer-mode application runs.** Explicitly excluded by Decisions Locked 2.

## Open Questions

- Whether `mycelium_edges` or `mycelium_landmark_edges` is the intended coupling substrate
  (REQ-5). This must be answered before wormhole Stage A, and the answer changes
  `specs/wormhole-aperture/` Decisions Locked 2.
- Corpus size and retention policy per outcome class (REQ-8 edge case). Start small and
  weighted toward failures, since those are the scarce class.
- Whether the residual physics/episode failure-rate difference has a legitimate structural
  component (one episode spanning several steps) or is entirely a recording gap (REQ-2 AC3).
- Whether the 354 orphaned `mycelium_pin_links` rows are recoverable or should be
  quarantined (REQ-4 AC3).
