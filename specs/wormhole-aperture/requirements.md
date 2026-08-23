# Requirements: WORMHOLE + APERTURE — Resonant Recall, Boundary Delivery, and Node Chains

**Status:** Draft — **BLOCKED on `specs/der-ground-truth/`** · **Supersedes:** `specs/node-chains/` (merged in as Stage C)
**Depends on:** `specs/der-ground-truth/` — gates G0 and G0b below are satisfied THERE, not here.
**Parent concept docs:** `docs/Wormhole-resonant-recall-.md` (physics), `docs/Wormhole-NodeChain-Mailbox.md` (delivery policy), `docs/architecture/FAULTLINE.md` (failure taxonomy)
**Say "WORMHOLE" for the recall topology. Say "APERTURE" for the delivery valve.**

---

## Decisions Locked

Resolved with the user on 2026-08-23. Do not re-litigate.

1. **"Mailbox" is renamed APERTURE.** The component is an opening that admits exactly
   what fits, only while it is open, with a shutter that times it. It sits natively
   beside wormhole / resonance / amplitude / coupling, and it never collides with MCP,
   message queues, or mail infrastructure. Every identifier uses the aperture
   vocabulary: `aperture_open`, `aperture_claim`, `aperture_expired`, `ApertureDecision`,
   `aperture_events`. The parent doc's `mailbox_decision` telemetry event becomes
   `aperture_decision`; its `mailbox_expired` FAULTLINE label becomes `aperture_expired`.
2. **Wormhole state extends the mycelium tables; it does not fork a parallel store.**
   `mycelium_nodes` gains the wormhole columns, `mycelium_edges` remains the coupling /
   posterior substrate. Only genuinely-new concepts (hyperedges, hex bins, aperture
   telemetry) get new tables. This enforces the parent doc's scoping constraint —
   "nothing here is a new subsystem" — against the drift it explicitly warns about.
   Rationale, verified: `mycelium_edges` already carries `hit_count` / `miss_count` /
   `observation_count` with a diminishing-alpha posterior update (`backend/memory/db.py:213-225`,
   `backend/memory/mycelium/scorer.py:91`), which IS a Beta-Bernoulli in all but name;
   `LandmarkIndex.apply_landmark_decay` (`backend/memory/mycelium/landmark.py:571`) and
   `EdgeScorer.apply_decay` (`scorer.py:200`) already implement dormancy-not-deletion.
   Reimplementing either would be the parallel implementation the parent doc forbids.
3. **One merged spec, gated stages.** `specs/node-chains/` is superseded by this
   document. Wormhole is Stage A, Aperture is Stage B, Node Chains is Stage C, the
   FAULTLINE read-side is Stage D. Node Chains is not a peer feature — it is the
   CONSUMER that proves a recall was worth delivering. A single REQ numbering, a single
   task list, gates between stages. The old spec keeps a SUPERSEDED header pointing
   here; its REQ IDs are preserved in the mapping table below so nothing is lost.
4. **Functionality first; empiricism where the answer is genuinely unknown.** The user's
   call: build the thing that works, do not gold-plate a measurement harness around
   decisions that are already obvious. Multi-arm shadow evaluation is therefore scoped
   to APERTURE POLICY ONLY (REQ-13/REQ-14) — the one place the parent doc is honestly
   undecided and where several solutions must be tried to find the best path. Everywhere
   else the gates are structural and cheap: every scored signal names its consumer
   (REQ-36 G2) and no recall path ships without a proven hot-path deadline (REQ-36 G3).
5. **The Beta prior replaces the sigmoid handoff.** Parent doc Q2 ADOPTED: seed coupling
   is expressed as a Beta prior (alpha_0, beta_0) sized to "this structural hunch is
   worth about N observations", and observed co-activations accumulate on top. No
   `crossover`, no steepness `k`. This reuses `observation_count` rather than adding a
   second mechanism for the same job.
6. **Hub scoring is per-destination, never aggregated in storage.** Parent doc Q3
   ADOPTED: store fine, derive coarse. The stored truth is the
   (connector -> destination) pair keyed by the destination's hash; any hub number is a
   VIEW. This means the aggregate formula can change later without migration.
7. **Re-quantization is solved by scheme version + lazy re-file on retrieval.** Parent
   doc Q4 ADOPTED. One integer column, re-hash in place on read. No big-bang migration.
   Nodes that never get used never migrate, and those were heading for dormancy anyway.
8. **Busyness and usefulness are two readings, never one averaged score.** Parent doc Q1
   ADOPTED. The BUSY/NOT-USEFUL quadrant is the failure this split exists to make
   visible. Classification is per coordinate region, consistent with
   `EdgeScorer.record_region_mediator_outcome` (`scorer.py:145`).
9. **The task card is the cross-conversation provenance spine.** `card_id` is already a
   stable, conversation-crossing identifier with a persisted footprint (objective,
   steps, tools_used, files_touched, outcome) retrievable by ID alone
   (`backend/memory/card_footprint.py:37,105`). Wormhole nodes, aperture deliveries, and
   chain provenance all carry `card_id`. This is what makes a chain traceable back to
   the exact task a human can see and address.
10. **No mid-stream token injection, ever.** Parent doc contract lock #4 stands
    unchanged and is elevated to REQ-11 AC7 with a contract test. Delivery happens only
    at DER node / tool-call boundaries.
11. **WORMHOLE REPLACES the existing recall protocol; it does not preserve it.** The
    two-phase `RecallPhases` protocol (Phase R emits `<recall .../>` ops, Phase A answers)
    is front-loaded, synchronous, and — verified below — orphaned. The goal is not to
    revive it. Wormhole IS the recall path: interrupt-driven, boundary-delivered,
    physics-scored. `RecallPhases` MAY be retained as an OPTIONAL fallback behind a
    default-off switch, and only for as long as it costs nothing: the moment it adds a
    hot-path cost, a second source of truth, or a divergent episode shape, it is deleted
    rather than maintained. What IS preserved is the EPISODE CONTRACT — the
    `source_channel='recall'` row shape with its `ops_trace` and `outcome_type`
    (`backend/agent/recall_phases.py:433-480`) — because Node Chains and the C3 test are
    built on that shape. Wormhole becomes its writer. The contract survives; the protocol
    does not have to.
11b. **GROUND TRUTH determinations that change this spec (recorded 2026-08-23).**
    - **Pin table:** `mycelium_pins` IS authoritative (created by
      `backend/memory/db.py:344`). `pins` is MCM build-store contamination — no
      `CREATE` anywhere in `backend/`, columns identical to `.mcm/coordinates.db`.
      REQ-24 AC8 therefore targets `mycelium_pins`, and the earlier draft note
      pointing at `pins` was WRONG. Note the consequence: `ref_status` /
      `last_validated`, which REQ-24 AC9 needs for chain.md staleness, exist only
      on the MCM table — so this spec must ADD them to `mycelium_pins` rather than
      assume them.
    - **Card footprints:** `save_card_footprint` is now wired at the DER card
      terminal state (GROUND TRUTH T6), so REQ-34's data source exists.
    - **Row ordering:** `backend/agent/row_sequence.py` is the backend-owned key.
      Anything this spec adds that produces a card row must stamp it.
    - **Edge substrate (REQ-5) — ANSWERED 2026-08-23, and it weakens Decisions
      Locked 2.** `mycelium_edges` is empty because its population path is
      bootstrap-starved, not because the writer is broken: nodes reach the
      active set only via `navigate_from_task`, whose entry matching is
      KEYWORD-based against **37 nodes spanning 3 of 7 coordinate spaces**
      (labels mostly `tool_*` / `domain_*`). A live read-only probe returned 0
      nodes for an ordinary coding task. So the region-mediator guard rarely
      passes and no edge is written.
      **Consequence for this spec:** extending `mycelium_edges` means building
      on a substrate that is not merely empty but structurally hard to populate
      on the DER path. Stage A must either (a) fix node activation first, or
      (b) name a different substrate — `mycelium_landmark_edges` holds 6,201
      rows and may be the de facto one. **Decide this before Stage A, and treat
      Decisions Locked 2 as UNSETTLED until it is decided.**
      **UPDATE — retargeting to `mycelium_landmark_edges` does NOT resolve it.**
      Those 6,201 rows have `traversal_count = 0` and `hit_count = 0` across the
      board: pure structure from `_auto_connect`, never scored. Neither edge
      layer holds a single scored edge. The option that DOES carry evidence is
      **landmarks + traversals** — `mycelium_traversals` (355 rows with real
      `path_score`/`outcome`) and `mycelium_landmarks` (285 rows, 30 with a live
      `activation_count`).
      **CORRECTED 2026-08-23 — this is better news than first reported.** An
      earlier note here claimed no edge is scored anywhere. Wrong: it was scoped
      to `mycelium_*`. The PHEROMONE layer (`graph_edges`) is alive and learning
      in BOTH instances — MCM 7,638 edges and APP 997,262, every one weighted,
      ~10-15% carrying `last_scored`, weights reinforced from a 0.95 baseline up
      to 3.14. And per `CLAUDE.md` the MCM build store is INHERITED by the
      application at hand-off (same schema, no migration), so the app does not
      start from nothing.
      **So the substrate choice is: pheromone/graph layer (populated, scored,
      decaying, inherited) versus `mycelium_edges` (starved).** Decide it before
      Stage A. Decisions Locked 2 currently names the starved one.

12. **Recorder integrity is `specs/der-ground-truth/`'s job, not this spec's.** A full
    execution/memory audit on 2026-08-23 found that five of the six substrates this spec
    builds on have never been written in production: `der_fan_traces`=0 (emitted only by a
    `DCP` the DER loop never constructs), `mycelium_edges`=0 (a caller exists at
    `agent_kernel.py:11536` but sits behind a guard whose failure logs at DEBUG),
    `semantic_entries`=0 (`card_footprint.py` has zero importers), `mycelium_pins`=0 (while
    354 orphaned links exist), and recall episodes=0. The execution ledger calls
    `persist()` with no storage path and writes nothing (`der_execution_ledger.py:339`).
    And the physics layer records a 0.5% failure rate against the episode layer's 27%.
    **This spec does not fix those** — it declares them a dependency and refuses to begin
    scoring until GROUND TRUTH clears gate GT-G4. A Beta-Bernoulli fed a corpus with no
    negative evidence produces posteriors that all converge to 1.0 and a graph that is
    confidently meaningless.
13. **Empiricism is scoped, not universal.** Shadow multi-arm evaluation applies to
    APERTURE POLICY only (REQ-13/REQ-14), framed as INSTRUMENTED JUDGEMENT rather than
    statistical selection: ~200 DER runs in three months cannot support an A/B across five
    arm families. Shadow logging is nearly free and stays; the bandit / Thompson-sampling
    framing of the parent doc is explicitly deferred until traffic justifies it.
14. **The hex neighborhood layer is deferred behind a corpus-size gate, not deleted.**
    Tier-1a (exact hash) and Tier-2 (bounded walk) work at any scale and ship in Stage A.
    Tier-1b (the six-neighbor ring) buys nothing at 37 mycelium nodes / 207 episodes and
    carries the one decision the parent doc calls expensive-once-data-exists
    (re-quantization). It stays fully specified and ships when the corpus justifies it.

---

## Introduction

IRIS records every action as a node with a mediator, an outcome, and a Caducean RL
signal, and it stores a coordinate graph with scored edges and decaying landmarks. What
it cannot do is (a) find the relevant past state fast enough to use DURING execution,
(b) hand that finding to the running loop without blocking it, or (c) prove afterwards
that the finding was worth having.

This spec builds those three things as one system:

- **WORMHOLE (Stage A)** turns the 4D Caducean confounder state into an addressable
  topology — hash signature, hex bin, hyperedge — so recall is an O(1) lookup with a
  scored fallback walk, not a similarity scan.
- **APERTURE (Stage B)** is the delivery valve: an asynchronous, boundary-aligned
  single-slot hand-off that holds a candidate until the DER loop reaches a safe splice
  point, and drops it rather than ever blocking generation.
- **NODE CHAINS (Stage C)** is the consumer and the proof: successful node paths become
  first-class loadable chains, and a chain that crystallizes out of delivered recalls is
  the empirical evidence that the whole path worked.
- **FAULTLINE READ-SIDE (Stage D)** closes the loop in both directions: a recall that
  causes a typed failure poisons its hyperedge; a recall that prevents one rewards it.

### The finding that reorders everything

`RecallPhases` and `RecallDecoder` are **orphaned**. `docs/architecture/RECALL_AS_COGNITION.md`
claims integration at `agent_kernel.py:set_memory_interface()`, `_respond_direct()`,
`_build_recall_infer_fn()`, and `iris_gateway.py:_handle_chat()`. Verified against the
code: `_respond_direct` exists (`backend/agent/agent_kernel.py:2636`) and
`set_memory_interface` exists (`:565`), but **neither constructs `RecallPhases`**, and
`_build_recall_infer_fn` does not exist at all. A name-scoped grep across
`backend/agent/*.py`, `backend/*.py`, `backend/gateway/*.py` returns only the two
modules themselves; every other reference is a test.

Consequence, and it is load-bearing: `_log_recall_episode` (`recall_phases.py:433`) is
the ONLY writer of `source_channel='recall'` (`:480`), and it is never reached in
production. The parent Aperture doc states "your ultimate boss is `_log_recall_episode`" —
that boss is currently unemployed. No live traffic has ever written a recall episode, so
the C3 test can only ever be satisfied by synthetic rows, and the entire empirical
program of this spec would have no data source.

**This is an opportunity, not a blocker.** Because nothing depends on the orphaned
protocol, there is no migration to perform and no live behavior to preserve. Per
Decisions Locked 11, Wormhole does not revive `RecallPhases` — it REPLACES it as the
recall path and INHERITS its episode contract as the writer. The two-phase protocol
survives only as an optional, default-off fallback for as long as it is free.

**Stage 0 (REQ-0) therefore blocks everything, but its target has changed:** what must
exist before any measurement in this spec means anything is a REAL
`source_channel='recall'` episode written from live traffic — written by the wormhole
path, not by resurrecting Phase R/A.

### Success criteria

- A live turn writes a real `source_channel='recall'` episode, produced by the wormhole
  path — the channel is no longer synthetic-only, and the old two-phase protocol was not
  revived to get there.
- A confounder state that has been seen before resolves through Tier-1a (exact hash) or
  Tier-1b (hex neighbors) without a graph walk, and the 1a/1b/2 split is measurable.
- A Tier-2 walk that exceeds its deadline is CANCELLED and logged, and the generation
  stream is measurably unaffected (p95 delta within noise).
- An aperture delivery carries a `recall_trace_id` that survives all the way to a
  FAULTLINE outcome and to a chain's provenance.
- A hyperedge that led to a `walled` tool failure has a measurably lower posterior than
  one that prevented a `transient` retry.
- A landmark that stops earning its keep loses elevation and settles back to ordinary
  wormhole status — demonstrated, not assumed.
- 3 delivered-and-used recalls sharing an op pattern crystallize a chain, `chain.md`
  lands in `data/chains/`, and `test_recall_fixes.py::TestC3SkillGenesisSql` passes
  UNMODIFIED. (Verified red today: run 2026-08-23 — "skill genesis did not fire despite
  3 successful recall episodes", 1 failed / 2 passed.)
- Every scored quantity introduced by this spec names the dispatch site that reads it.

---

## Requirement ID mapping (from the superseded `specs/node-chains/`)

| Old ID | Old title | New ID |
|---|---|---|
| NC REQ-1 | NodeChain data model | REQ-18 |
| NC REQ-2 | Chain extraction from live DER runs | REQ-19 |
| NC REQ-3 | Chain extraction from recall episodes (C3) | REQ-20 |
| NC REQ-4 | Pivot recording | REQ-21 |
| NC REQ-5 | Pivot promotion to chain variant | REQ-22 |
| NC REQ-6 | Chain-guided execution | REQ-23 |
| NC REQ-7 | chain.md projection | REQ-24 |
| NC REQ-8 | Anti-bloat / token discipline | REQ-25 |
| NC REQ-9 | Observability | folded into REQ-35 |
| NC REQ-10 | Node grafts from chains | REQ-26 |
| NC REQ-11 | Node grafts from scripts | REQ-27 |
| NC REQ-12 | Tool disambiguation / context signatures | REQ-28 |
| NC REQ-13 | Tool evolution | REQ-29 |
| NC REQ-14 | Cross-domain blocker removal | REQ-30 |
| NC REQ-15 | Chain-level permission resolution | REQ-31 |

The full acceptance criteria and edge cases of NC REQ-1..15 are carried forward in
Stage C below unless a Wormhole/Aperture interaction changes them, in which case the
change is called out inline as **[CHANGED FROM NC]**.

---

# STAGE 0 — Claim the recall channel

### REQ-0: The recall episode contract survives; wormhole becomes its writer

**User Story:** As the system I want a real turn to produce a real recall episode so
that every measurement in this spec has a genuine data source instead of test fixtures —
and I want that episode written by the new recall path, not by reviving the old one.

**Verified:** REAL GAP / BLUEPRINT-DIVERGENT. `RecallPhases` (`backend/agent/recall_phases.py:160`)
and `RecallDecoder` (`backend/agent/recall_decoder.py`) are imported by tests only —
`backend/agent/tests/test_recall_fixes.py:25`, `backend/agent/tests/test_pin_store.py:23`.
No production module imports either. `_log_recall_episode` (`recall_phases.py:433`) is
the sole writer of `source_channel='recall'` (`:480`); the only other `source_channel=`
writer in the agent is `agent_kernel.py:870` (`'websocket'`).
`docs/architecture/RECALL_AS_COGNITION.md` asserts four integration points that do not
exist in the code as described.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL write an `episodes` row with `source_channel='recall'` from a
  real inference turn, produced by the wormhole/aperture path.
- AC2: THE SYSTEM SHALL preserve the EXISTING recall-episode row shape — the `ops_trace`
  in `tool_sequence`, the `outcome_type` vocabulary, and the `[recall:{ops_key}]`
  task-summary prefix that keeps distinct op patterns as separate rows
  (`backend/agent/recall_phases.py:445-480`). **This is a contract lock
  (CT-RECALL-EPISODE).** Node Chains (REQ-20) and the C3 test read this shape; changing
  it would silently break genesis.
- AC3: THE SYSTEM SHALL express a wormhole retrieval as an ops_trace entry, so a
  wormhole-sourced episode and a legacy Phase-R episode are indistinguishable to the
  chain-extraction layer.
- AC4: THE SYSTEM SHALL set `outcome_type` from the turn's actual resolved outcome and
  SHALL NOT leave it at the unresolved default when an outcome is known.
- AC5: THE SYSTEM SHALL record the `card_id` and `recall_trace_id` on the recall episode,
  so it is addressable cross-conversation (Decisions Locked 9, REQ-17 AC3).
- AC6: THE SYSTEM SHALL keep `RecallPhases` behind a DEFAULT-OFF switch as an optional
  fallback, and SHALL NOT place it on any hot path while off. WHERE it is enabled it
  SHALL write the same episode shape as AC2.
- AC7: IF the legacy fallback is found to add hot-path cost, a second source of truth, or
  a divergent episode shape THEN THE SYSTEM SHALL remove it rather than maintain it
  (Decisions Locked 11).
- AC8: THE SYSTEM SHALL correct `docs/architecture/RECALL_AS_COGNITION.md` to describe
  what actually exists — including that its four claimed integration points do not — and
  to name wormhole as the recall path.
- AC9: IF the recall path raises or the memory interface is absent THEN THE SYSTEM SHALL
  fall through to the existing direct-response path, log the degradation, and never fail
  the user's turn.
- AC10: THE SYSTEM SHALL expose a switch that disables recall entirely and returns to
  today's behavior exactly (REQ-37 AC1).

**Edge Cases:**
- Memory interface not yet wired at first turn -> path skipped, logged once, retried on
  the next turn; no exception surfaces.
- The turn needs no memory -> an episode is still written recording that zero candidates
  were delivered, so the ignore-rate and the no-op rate are both measurable
  (REQ-15 AC5).
- Both wormhole and the legacy fallback are enabled -> wormhole is authoritative; the
  fallback runs only when wormhole returns nothing, and the episode records which path
  produced it. Two rows for one turn is a contract violation, not a merge.
- Recall latency exceeds its budget -> REQ-12 degraded mode; the turn proceeds without
  recall and the episode records the timeout.

---

# STAGE A — WORMHOLE (topology and physics)

### REQ-1: Confounder state capture and hash signature

**User Story:** As the agent I want the current 4D state flattened into an exact address
so that matching a past state costs a primary-key lookup instead of semantic reasoning.

**Verified:** `CaduceanTrajectoryRecorder.get_latest_coordinate`
(`backend/agent/caducean_trajectory.py:393`) returns `{x, y, xi, u}` for a session
directly from `caducean_trajectories`, which also carries `domain`,
`execution_domain`, and `topic_domain` (`:258`). The 4D state plus domain/capability
that the parent doc's Section 2 Step 1 requires therefore already exists and needs no
new collection.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL compute a `hash_signature` from the quantized 4D confounder
  state (x, y, xi, u) plus `topic_domain` and `execution_domain`.
- AC2: THE SYSTEM SHALL write `hash_signature` onto a node at write time, not compute it
  at query time.
- AC3: THE SYSTEM SHALL treat the hash as an exact-match address and SHALL NOT perform
  any semantic or threshold comparison on it.
- AC4: THE SYSTEM SHALL store the quantization `scheme_version` alongside the hash
  (REQ-10).
- AC5: THE SYSTEM SHALL make hashing deterministic: identical inputs SHALL always
  produce an identical signature, across processes and restarts.

**Edge Cases:**
- No Caducean coordinate exists for the session (cold start) -> no signature is minted;
  the node is written unhashed and hashed lazily on its first retrieval (REQ-10 AC3).
- A coordinate axis is NaN or infinite -> the node is written unhashed and the anomaly
  is logged; a poisoned address is worse than no address.
- Two genuinely different tasks quantize to the same signature -> this is a semantic
  collision, handled by REQ-16, not by tightening the hash.

### REQ-2: Hexagonal binning and neighborhood fallback (Tier 1a / Tier 1b)

**User Story:** As the agent I want an exact-hash miss to fall back to the spatial
neighborhood rather than straight to a graph walk, so that near-matches stay O(1).

**Verified:** NEW. No hex or spatial binning exists today.
`CoordinateNavigator.navigate_from_task` (`backend/memory/mycelium/navigator.py:93`) is
the current entry path and matches by keyword extraction (`:371`), not by coordinate
neighborhood. `ChartRegistry.get_nearest_origins`
(`backend/memory/mycelium/topology.py:161`) is the closest existing analogue and
operates on chart origins, not on confounder state.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL assign every hashed node a `hex_bin_id` derived from the same
  quantized state as its hash signature.
- AC2: WHEN an exact `hash_signature` lookup returns a result THEN THE SYSTEM SHALL
  record the retrieval as `tier='1a'` and SHALL NOT consult neighbor bins.
- AC3: WHEN an exact lookup misses THEN THE SYSTEM SHALL query the six adjacent hex
  cells and SHALL record any retrieval as `tier='1b'`.
- AC4: THE SYSTEM SHALL bound Tier-1b to the immediate neighbor ring; widening beyond
  one ring is a Tier-2 walk, not a Tier-1b lookup.
- AC5: THE SYSTEM SHALL record the 1a / 1b / 2 hit-rate split as a first-class measured
  quantity (REQ-35 AC3) — the parent doc's Q4 instrumentation target.
- AC6 **[DEFERRED — Decisions Locked 14]**: THE SYSTEM SHALL NOT enable Tier-1b until the
  corpus clears gate G7 (REQ-36 AC9). Tier-1a and Tier-2 ship first and are sufficient on
  their own. Rationale: at 37 `mycelium_nodes` and 207 episodes, scanning every candidate
  linearly costs microseconds, so a neighbor-ring index measures as zero improvement while
  committing the system to a quantization scheme that REQ-10 identifies as the one
  expensive-to-change decision. AC1 (bin assignment at write time) still applies from day
  one — bins are MINTED immediately and merely not QUERIED, so no history is lost and the
  scheme-version machinery (REQ-10) is exercised from the start.

**Edge Cases:**
- The bin and all six neighbors are empty -> Tier-2 (REQ-3).
- The state sits exactly on a bin boundary -> assignment is deterministic (a documented
  tie-break rule), never random, so the same state never lands in two bins.
- A neighbor bin holds thousands of nodes -> results are ranked by hyperedge posterior
  and truncated to a bounded candidate count before leaving the lookup.

### REQ-3: Tier-2 weighted walk and signature minting

**User Story:** As the agent I want an unseen confounder combination to still find
something useful, and to become a wormhole for next time.

**Verified:** `CoordinateNavigator.navigate_all_spaces`
(`backend/memory/mycelium/navigator.py:208`) and `record_path_outcome` (`:251`) already
walk and score coordinate paths; `mycelium_traversals` (`backend/memory/db.py:229`)
already persists `path_node_ids` + `path_score` + `outcome`. Tier-2 is a bounded,
deadline-carrying wrapper over this existing walker, not a new walker.

**Acceptance Criteria:**
- AC1: WHEN Tier-1a and Tier-1b both miss THEN THE SYSTEM SHALL run a bounded
  weighted walk from the current coordinate, hopping along edges weighted by posterior
  and recency-resonance.
- AC2: THE SYSTEM SHALL run every Tier-2 walk under a deadline (REQ-12) and off the
  generation path.
- AC3: WHEN a Tier-2 walk succeeds THEN THE SYSTEM SHALL mint a `hash_signature` and
  `hex_bin_id` for the discovered node so the same query resolves at Tier-1 next time.
- AC4: THE SYSTEM SHALL NOT apply a fixed similarity cutoff to decide whether a Tier-2
  result is "close enough"; the acceptance threshold is itself scored (REQ-4 AC6).
- AC5: THE SYSTEM SHALL limit concurrent Tier-2 walks to one per session (single-flight)
  and SHALL drop rather than queue an overlapping request.

**Edge Cases:**
- The walk exceeds its deadline -> cancelled, `recall_timeout` FAULTLINE label emitted,
  no retry within the same DER node (REQ-32).
- The walk returns a node whose mediator no longer exists -> the node is returned with a
  staleness marker; the chain layer treats it per REQ-29.
- The store is locked -> `recall_store_locked` emitted; the walk is dropped, never
  blocked (REQ-12 AC3).

### REQ-4: Hyperedges and the Beta-Bernoulli scorecard

**User Story:** As the agent I want the specific shortcut scored, not the whole
neighborhood, so that one dead end does not blind me to a brilliant memory beside it.

**Verified:** `mycelium_edges` (`backend/memory/db.py:207`) already carries
`hit_count`, `miss_count`, and `observation_count`, and `EdgeScorer.record_outcome`
(`backend/memory/mycelium/scorer.py:91`) already applies a diminishing-alpha posterior
update (`alpha = 1/(1+observation_count)`, documented at `db.py:219-225`) with a
deliberate pessimism prior (`scorer.py:43-48`). What is missing is a THREE-ended edge:
`mycelium_edges` enforces `UNIQUE(from_node_id, to_node_id)` (`db.py:226`), a strict
pair.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define a hyperedge as an ordered triple
  (live_state_hash, landmark_node, target_node) and SHALL store it in a dedicated table.
- AC2: THE SYSTEM SHALL place the Beta-Bernoulli scorecard (alpha, beta,
  observation_count) on the HYPEREDGE, never on the hex bin.
- AC3: WHEN a delivered recall leads to a resolved outcome THEN THE SYSTEM SHALL
  increment the hyperedge's alpha; WHEN it leads to no improvement or a failure THEN
  THE SYSTEM SHALL increment beta.
- AC4: THE SYSTEM SHALL expose the posterior LOWER BOUND, not the raw mean, as the value
  every downstream consumer reads (elevation REQ-7, hub scoring REQ-8, drive REQ-5,
  aperture ranking REQ-11).
- AC5: THE SYSTEM SHALL compose multi-hop path cost as the sum of `-log(posterior)` per
  hop, never as a sum or product of raw posteriors.
- AC6: THE SYSTEM SHALL score the wormhole-match threshold itself as an edge-like
  entity, so loose matches that keep paying off drift it looser and loose matches that
  misfire drift it tighter.
- AC7: THE SYSTEM SHALL score each hyperedge only in the direction it was actually
  travelled; an untravelled direction SHALL be absent, not zero.

**Edge Cases:**
- posterior is exactly 1.0 (beta=0) -> `-log(1)=0` is a legitimate zero cost, but the
  LOWER BOUND at low observation count keeps it out of the maximum-drive regime
  (REQ-5 AC2); the raw mean is never the consumed value.
- posterior is 0.0 -> cost is capped at a finite maximum so a single bad edge cannot
  make a path cost infinite and unrankable.
- The same triple is discovered twice concurrently -> upsert on the triple; counts merge,
  never duplicate.

### REQ-5: Resonance amplitude with coupling-derived damping

**User Story:** As the agent I want nodes that genuinely bridge to stay alive and nodes
that are merely popular to fade, so that the graph converges on what works rather than
on what happened first.

**Verified:** `EdgeScorer.apply_decay` (`backend/memory/mycelium/scorer.py:200`) and
`LandmarkIndex.apply_landmark_decay` (`backend/memory/mycelium/landmark.py:571`) already
implement time-based decay with per-row `decay_rate` (`db.py:216`) and already leave the
record in place. `DCP.prune` (`backend/agent/dcp.py:60`) already prunes the active
working buffer without deleting the underlying record. Dormancy-not-deletion therefore
exists; only the coupling-DERIVED damping coefficient is new.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL model each wormhole node's `amplitude` as a driven-damped
  oscillator consistent with the Caducean engine already in use.
- AC2: THE SYSTEM SHALL inject drive proportional to the resolved variance spike and the
  hyperedge posterior LOWER BOUND, and SHALL bound the spike term with a saturating
  function so no single oscillation can inject unbounded energy.
- AC3: THE SYSTEM SHALL inject drive only when a recall was RECALLED AND USED, never for
  mere retrieval.
- AC4: THE SYSTEM SHALL derive the damping coefficient from coupling to resonant
  neighbors — strongly-coupled nodes decay slower, heavily-used-but-weakly-coupled nodes
  decay faster regardless of their own traffic.
- AC5: THE SYSTEM SHALL NOT subtract amplitude on a failed recall; a failure SHALL raise
  damping for that hyperedge context only.
- AC6: THE SYSTEM SHALL give a new node a birth amplitude sized to survive roughly 30
  days without activation, and SHALL record that constant as a MEASURED target
  (REQ-35 AC4), not a tuned constant.
- AC7: WHEN amplitude decays near zero THEN THE SYSTEM SHALL mark the node dormant and
  prune it from the active working set via the EXISTING DCP mechanism, and SHALL leave
  scorecard, coupling history, and signature untouched.
- AC8: WHEN a dormant node's confounder reappears THEN THE SYSTEM SHALL re-resonate it
  from its retained state, not from a cold start.

**Edge Cases:**
- A node has zero coupling (brand new, no seed matched) -> the seed prior (REQ-6 AC1)
  supplies non-zero coupling so birth does not immediately trigger maximum damping.
- Drive and damping are both extreme -> amplitude is clamped to a documented range; the
  clamp firing is logged as a tuning signal.
- The rich-get-richer loop the parent doc flags (drive ∝ posterior ∝ use ∝ retrieval ∝
  amplitude) -> INSTRUMENTED, not assumed away: REQ-9 makes the BUSY/NOT-USEFUL quadrant
  directly observable, and REQ-35 AC5 reports its population every session.

### REQ-6: Coupling — seed prior plus observed bridge

**User Story:** As the agent I want a new node to start with a structural hunch about
what it relates to, and I want reality to overrule that hunch as evidence accumulates.

**Verified:** `mycelium_edges.observation_count` (`backend/memory/db.py:225`) already
encodes "how much evidence do I have", and `scorer.py:60-67` already documents an
explicit neutral PRIOR (0.5) for an unseen (region, mediator) pair. The Beta-prior
formulation of Decisions Locked 5 is therefore an extension of existing semantics, not a
new one.

**Acceptance Criteria:**
- AC1: WHEN a node is created THEN THE SYSTEM SHALL seed its coupling to existing nodes
  from confounder-signature overlap alone, expressed as a Beta prior (alpha_0, beta_0)
  sized to "worth about N observations".
- AC2: THE SYSTEM SHALL accumulate observed co-activation counts on top of the prior so
  the handoff from seed to observation is automatic.
- AC3: THE SYSTEM SHALL NOT introduce a sigmoid, a crossover point, or a steepness
  constant for this handoff.
- AC4: THE SYSTEM SHALL additionally allow an established `hub_score` (REQ-8) to seed a
  node's coupling to a brand-new landmark above what signature overlap alone would
  justify.
- AC5: THE SYSTEM SHALL surface high-seed / low-observed divergence as a TAGGING signal —
  the reading is "the confounder signature is lumping together things the world treats
  differently", pointing at the tagging, not at the pair.

**Edge Cases:**
- Signature overlap is zero -> the prior is the documented minimum, not zero; a node with
  literally no coupling would be killed by REQ-5 AC4 damping before it could earn any.
- Co-activation count grows very large -> the prior's influence approaches zero
  naturally; no explicit cutoff is needed or permitted.
- Divergence is high for a whole region -> escalated once per region per session, not per
  pair, to keep it off the noise floor.

### REQ-7: Landmark elevation (the resonance axis)

**User Story:** As the agent I want a proven shortcut promoted to a fixed reference
point, and I want that pillar to fall again if it stops earning its keep.

**Verified:** `Landmark` (`backend/memory/mycelium/landmark.py:60`), `LandmarkIndex.save`
(`:329`), `_auto_connect` (`:365`), `apply_landmark_decay` (`:571`), and
`mycelium_landmark_edges` with named decay rates (`landmark.py:34-36`) already implement
a landmark lifecycle with decay and conflict resolution (`resolve_conflict`, `:486`).
Elevation as a CONTINUOUS quantity that can fall is the new part; the crystallization
and decay machinery is not.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL compute `elevation` as a continuous 0..1 function of the
  posterior LOWER BOUND of the node's hyperedges and its coupling to resonant neighbors.
- AC2: THE SYSTEM SHALL weight the coupling term by neighbor RESONANCE, not by raw
  neighbor count.
- AC3: THE SYSTEM SHALL NOT represent elevation as a boolean flag.
- AC4: THE SYSTEM SHALL allow elevation to FALL — when a landmark is contradicted by
  newer high-confidence results, or loses coupling-sustained energy, it SHALL settle back
  to ordinary wormhole status.
- AC5: THE SYSTEM SHALL admit a landmark into path composition only when the composed
  `-log(posterior)` cost through it clears the current threshold (REQ-4 AC5/AC6).
- AC6: THE SYSTEM SHALL log every elevation rise and every fall with its cause
  (REQ-35 AC6).

**Edge Cases:**
- A lucky 2-of-2 success streak -> the lower bound keeps elevation low; promotion does
  not fire. This is the guard AC1 exists for.
- A landmark falls while a chain references it -> the chain is flagged for revalidation
  (REQ-29), never silently rerouted.
- All landmarks in a region fall at once -> the region degrades to Tier-2 walking and
  logs the degradation; it does not error.

### REQ-8: Hub landmarks (the breadth axis), scored per destination

**User Story:** As the agent I want a reliable interchange to count as valuable even when
it is nobody's favourite destination, so that the graph keeps alternate routes.

**Verified:** `LandmarkIndex.add_bridge` (`backend/memory/mycelium/landmark.py:694`),
`get_bridges` (`:736`), `find_bridge` (`:754`), and the `mycelium_landmark_bridges`
table (`backend/memory/db.py`) already model a bridge between landmarks. The per-
destination scorecard is the new part.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL score a connector PER DESTINATION, keyed by the destination's
  hash, and SHALL NOT store an aggregated hub number.
- AC2: THE SYSTEM SHALL derive any hub-level number as a VIEW over the per-destination
  scores, so the aggregation formula can change without migration.
- AC3: THE SYSTEM SHALL apply decay to the per-destination scores, so a connector that
  bridged widely long ago and nothing since does not still rank.
- AC4: THE SYSTEM SHALL treat the hub layer as COMPARATIVE — a connector's standing is
  relative to the other connectors reaching the same destination, never an intrinsic
  quality number.
- AC5: THE SYSTEM SHALL blend hub standing across both directions of travel it has been
  used in, WITHOUT forcing any individual hyperedge to be symmetric (REQ-4 AC7 stands).
- AC6: THE SYSTEM SHALL make hub standing available as a coupling seed source
  (REQ-6 AC4) — this is the named consumer that keeps the signal from being decoration.

**Edge Cases:**
- One bad route among two hundred -> scored badly FOR THAT ROUTE only; the others are
  untouched. This is the whole reason aggregation is refused.
- A connector reaches exactly one destination -> it is scored, and its standing is
  trivially comparative; it is not special-cased.
- Two connectors tie for a destination -> the tie-break is deterministic and logged.

### REQ-9: Busyness and usefulness as two readings

**User Story:** As the tuner I want to see the node that is constantly pulled in and
never helps, because today it is indistinguishable from a genuine highway.

**Verified:** `mycelium_nodes.access_count` (`backend/memory/db.py:203`) already counts
retrieval (busyness). `mycelium_edges.score` with hit/miss counts (`:211-215`) already
carries usefulness. The two exist and are currently never read together.
`EdgeScorer.record_region_mediator_outcome` (`backend/memory/mycelium/scorer.py:145`)
establishes the region-scoped precedent this requirement follows.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL expose busyness (activation frequency) and usefulness (posterior
  lower bound) as TWO separate readings on every wormhole node.
- AC2: THE SYSTEM SHALL NOT collapse the two into a single averaged score anywhere in
  the system.
- AC3: THE SYSTEM SHALL NOT penalize a QUIET node for rarity — a specialist recalled
  twice and right both times is valuable.
- AC4: THE SYSTEM SHALL classify per COORDINATE REGION, not globally; a node may be a
  highway in one region and irrelevant in another.
- AC5: THE SYSTEM SHALL NOT pre-define frequency bands; bands SHALL fall out of the
  observed distribution.
- AC6: THE SYSTEM SHALL report the BUSY/NOT-USEFUL population every session
  (REQ-35 AC5), and the aperture SHALL down-rank candidates in that quadrant
  (REQ-11 AC4) — the named consumer for this signal.

**Edge Cases:**
- A node has high busyness and no scored hyperedges at all -> classified NOT-USEFUL by
  absence of evidence and reported; it is the exact trap case.
- A region has fewer than a handful of nodes -> classification is withheld and reported
  as "insufficient distribution" rather than forced.
- A node moves between quadrants frequently -> the transitions are rate-limited in
  logging (REQ-35 AC7), not smoothed in the data.

### REQ-10: Quantization scheme version and lazy re-file

**User Story:** As the maintainer I want to change the hash quantization after data
exists without a migration or a data loss, so that bin size never becomes a one-way door.

**Verified:** NEW. No hashing or versioning exists today. The migration precedent this
follows is `scripts/migrate_build_store_inheritance.py` (referenced in `CLAUDE.md`) —
which is explicitly an offline, human-run step; this requirement deliberately chooses the
opposite shape (online, incremental, no downtime).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL store a `hash_scheme_version` integer on every hashed node.
- AC2: WHEN a node is retrieved AND its `hash_scheme_version` is older than the current
  scheme THEN THE SYSTEM SHALL re-hash and re-bin it under the current scheme and update
  it in place.
- AC3: THE SYSTEM SHALL hash an unhashed node lazily on its first retrieval.
- AC4: THE SYSTEM SHALL NOT perform a bulk re-hash pass; nodes that are never used never
  migrate.
- AC5: WHEN the scheme version changes THEN THE SYSTEM SHALL require a minimum
  observation count and SHALL bound the step size (hysteresis), so the hit-rate loop
  cannot oscillate between widen and tighten.
- AC6: THE SYSTEM SHALL log every scheme change with the hit-rate evidence that
  justified it.

**Edge Cases:**
- Re-hash moves a node out of the bin the current query is scanning -> the query
  completes against the pre-move snapshot; the move takes effect next query.
- Two sessions re-file the same node concurrently -> the write is idempotent (same input,
  same scheme, same output); last write wins harmlessly.
- The current scheme is unreadable / config is corrupt -> the system keeps using the last
  known-good scheme and logs; it never re-files against an unknown scheme.

---

# STAGE B — APERTURE (delivery)

### REQ-11: The aperture — single-slot, boundary-claimed delivery

**User Story:** As the agent I want a recall candidate handed to me at a point where
taking it is safe, so that memory arrives inside the work instead of interrupting it.

**Verified:** NEW as a component; its boundary already exists.
`DirectorQueue.next_ready` (`backend/agent/der_loop.py:502`) and
`queue.mark_complete` (`backend/agent/agent_kernel.py:12185`) bracket exactly the
node boundary the aperture claims at; `agent_kernel.py:6932` is the live `next_ready`
call site.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL hold at most the configured number of candidates (default one)
  in the aperture at a time.
- AC2: THE SYSTEM SHALL make the aperture DELIVERY ONLY — it SHALL NOT compute any
  relevance score of its own. Candidate quality is owned by Stage A.
- AC3: WHEN the DER loop reaches a node or tool-call boundary AND the aperture holds a
  non-stale candidate THEN THE SYSTEM SHALL claim and inject it.
- AC4: THE SYSTEM SHALL down-rank a candidate whose source node is classified
  BUSY/NOT-USEFUL for the current region (REQ-9 AC6).
- AC5: THE SYSTEM SHALL emit an `aperture_decision` telemetry record for EVERY outcome:
  injected, dropped_stale, dropped_overwritten, expired_unclaimed (REQ-35 AC1).
- AC6: THE SYSTEM SHALL NOT update any Beta-Bernoulli counts at delivery time; counts
  move only after outcome evidence exists (REQ-4 AC3).
- AC7: THE SYSTEM SHALL NEVER splice tokens into an active generation stream. Injection
  happens only at a node / tool-call boundary. **This is a contract lock (CT-APERTURE-1).**

**Edge Cases:**
- The DER run completes with a candidate still held -> `expired_unclaimed` is emitted and
  the candidate is discarded; nothing is carried into the next run implicitly.
- A candidate arrives exactly as a boundary is being crossed -> the boundary check reads
  a consistent snapshot; a candidate is either fully claimable or not claimed at all.
- The aperture is disabled -> Stage A still mints signatures and scores; nothing is
  delivered. Wormhole learning does not depend on delivery being on.

### REQ-12: Hot-path deadline and degraded mode

**User Story:** As the user I want a slow memory lookup to be invisible, because a
missed recall is harmless and a hung generation loop is not.

**Verified:** REAL — this defect shape has already been hit here.
`ToolBridge._record_tool_event` (`backend/agent/tool_bridge.py:1605`) carries a written
post-mortem at `:1618-1629`: the docstring claimed fire-and-forget while the call ran
inline, "a live stack dump caught the DER thread parked here across consecutive samples,
inside ffi_ingest_event -> SQLite, right after a web search returned — so a completed
crawl looked like a hung one". The parent Wormhole doc names mid-stream RECALL mechanics
"UNRESOLVED AND BLOCKING" for precisely this reason. `_DER_TURN_BUDGET_S`
(`backend/agent/agent_kernel.py:125`) is the existing precedent for a last-resort wall
clock.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL run every Tier-2 walk and every aperture fill off the generation
  thread.
- AC2: THE SYSTEM SHALL give every recall operation an explicit deadline with a defined
  behavior on expiry, stated in the code at the call site.
- AC3: WHEN a deadline expires THEN THE SYSTEM SHALL cancel the operation, skip the
  recall, emit the corresponding FAULTLINE label, and SHALL NOT retry within the same
  DER node.
- AC4: THE SYSTEM SHALL NOT allow any recall operation to hold a write lock on the
  memory store while the generation path is active.
- AC5: THE SYSTEM SHALL measure and report the p95 delta between turns with recall
  enabled and disabled (REQ-35 AC8) — this measurement is Gate G3.
- AC6: IF the recall subsystem raises an unexpected exception THEN THE SYSTEM SHALL
  swallow it at the boundary, log it with the session identifier, and continue the turn.

**Edge Cases:**
- The deadline expires after the walk already found a result -> the result is discarded
  for INJECTION but still minted into the topology (REQ-13 arm T2-A); learning survives
  a missed delivery.
- SQLite is locked by an unrelated writer -> `recall_store_locked`; dropped, not queued.
- The system clock jumps -> deadlines use a monotonic clock, never wall time.

### REQ-13: Policy arms are configurable, not hardcoded

**User Story:** As the architect I want the genuinely-undecided aperture policies
implemented as swappable arms, so that evidence rather than a guess selects them.

**Verified:** NEW. The parent doc (`docs/Wormhole-NodeChain-Mailbox.md` §3) defines the
arm matrix. Nothing in the codebase implements any of it.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL implement the aperture's decision points as named ARMS in five
  families: overwrite (OV), staleness (ST), late Tier-2 arrival (T2), cadence (CD), and
  semantic collision (SC).
- AC2: THE SYSTEM SHALL make the active arm per family selectable by configuration
  without a code change.
- AC3: THE SYSTEM SHALL record the arm used per family on every `aperture_decision`
  record (REQ-35 AC1).
- AC4: THE SYSTEM SHALL implement DL-A (degraded mode) as MANDATORY and NOT as an arm —
  there is no alternative to not hanging.
- AC5: THE SYSTEM SHALL ship these defaults for the first live stage: OV-A
  (replace-if-better with a deadband), ST-A (hard TTL), T2-A (mint-only), CD-A
  (bounded-linear), SC-A (physics-only).
- AC6: THE SYSTEM SHALL apply hysteresis to any cadence arm so a variance spike cannot
  produce a polling storm against the store.

**Edge Cases:**
- An unknown arm id is configured -> the system falls back to the documented default,
  logs the rejection, and does not start with an undefined policy.
- Two arms in different families conflict (e.g. a cadence arm starves a staleness arm) ->
  the conflict is logged with both arm ids; the aperture prefers the safer outcome
  (drop over inject).
- All arms are disabled -> the aperture is off, which is a valid configuration (REQ-37).

### REQ-14: Shadow evaluation of alternative arms

**User Story:** As the tuner I want to know what a different policy WOULD have done,
without risking execution stability to find out.

**Verified:** NEW.

**Acceptance Criteria:**
- AC1: WHERE shadow evaluation is enabled THE SYSTEM SHALL compute the decision each
  inactive arm would have made and SHALL record it alongside the active arm's decision.
- AC2: THE SYSTEM SHALL NOT let a shadow arm affect execution in any way.
- AC3: THE SYSTEM SHALL run shadow computation under the same deadline discipline as the
  live path (REQ-12) and SHALL drop a shadow computation before it can delay a real one.
- AC4: THE SYSTEM SHALL make shadow records queryable by arm id and outcome, so the
  question "would ST-B have prevented the stale injections ST-A missed" is answerable
  from data.
- AC5: THE SYSTEM SHALL report, per arm, the rate of `agent_used=true`, the rate of
  `faultline_intersect=prevented_error`, and the rate of `chain_genesis_contrib=true`.
- AC6: THE SYSTEM SHALL NOT auto-promote an arm on the basis of a single metric; arm
  promotion requires the user's review of the per-arm report. **This is the guard the
  parent doc demands** — `bootstrap/GOALS.md` records a live example in this codebase of
  a loop that "accepts ANY proposal that raises natural-exit rate", which is the exact
  single-metric reward-hacking to avoid.
- AC7 **[SCOPED — Decisions Locked 13]**: THE SYSTEM SHALL present the per-arm report as
  INSTRUMENTED JUDGEMENT, not statistical selection, and SHALL state the sample size
  alongside every rate so an underpowered comparison is visibly underpowered. THE SYSTEM
  SHALL NOT implement a bandit, Thompson sampling, or automatic arm weighting at this
  traffic volume — ~200 DER runs in three months cannot separate five arm families. THE
  SYSTEM SHALL record the traffic volume that WOULD justify automatic selection, so the
  deferral has an exit condition rather than being indefinite.

**Edge Cases:**
- Shadow computation is expensive for one arm -> that arm is sampled rather than run on
  every decision, and the sampling rate is recorded so rates stay comparable.
- Shadow and live disagree on nearly every decision -> reported as a finding, not
  silently averaged.
- Shadow logging volume grows unbounded -> bounded retention with aggregate rollups
  (REQ-35 AC7).

### REQ-15: The recall surface is rendered from the schema

**User Story:** As the agent I want recalled memory to arrive in one stable shape every
time, because inconsistently-presented recall gets pattern-matched as noise and ignored.

**Verified:** Partially exists. `ResonanceScorer.format_context`
(`backend/memory/mycelium/resonance.py:256`) and
`Landmark.to_context_string` (`backend/memory/mycelium/landmark.py:86`) already render
memory into context strings from their record shapes. The wormhole surface follows that
precedent with fixed fields and fixed order.

**PRE-EXISTING PARTIAL IMPLEMENTATION (found 2026-08-23):** `lib/cards/memoryRegistry.ts`
already reserves the Wormhole vocabulary on its `recall` kind (`tier`,
`hyperedge_posterior`, `hex_bin_id`, `resonance`, `last_activated`, `elevation`) AND now
carries a `format` function rendering those fields in fixed order — i.e. part of this
requirement's surface exists before the spec that specifies it. It is inert (no emit site
produces those fields yet) and its file comment states the intent plainly: reserve the
vocabulary "WITHOUT implementing any recall mechanics... When that work lands, it edits the
`recall` entry below — it does not touch a card." Treat it as the designated seam: REQ-15
EDITS that entry rather than adding a second surface. `__tests__/cards/memoryRegistry.test.ts`
pins both the fixed order and the graceful-degradation behaviour.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL render the recall surface directly from the node/hyperedge schema
  with fixed fields in a fixed order, never from variable prose.
- AC0: THE SYSTEM SHALL implement this surface by EDITING the existing
  `memoryRegistry.recall` entry, and SHALL NOT introduce a parallel recall renderer.
- AC2: THE SYSTEM SHALL include at minimum: hex bin id, tier (1a / 1b / 2), hyperedge
  posterior, and last-activated relative time.
- AC3: THE SYSTEM SHALL keep the surface size-bounded.
- AC4: THE SYSTEM SHALL carry the `recall_trace_id` on the surface so downstream
  attribution is possible (REQ-17).
- AC5: THE SYSTEM SHALL measure whether the agent's subsequent reasoning USED what was
  surfaced, and SHALL feed that used/ignored signal into the scorecard of the recall
  mechanism as a whole.
- AC6: THE SYSTEM SHALL treat surface verbosity and default visibility as a TEST, not a
  design decision — the variants and their used/ignored rates are recorded.

**Edge Cases:**
- A field is null (e.g. no last-activated on a fresh node) -> the field is rendered with
  an explicit empty marker, never omitted; a shifting field set defeats AC1.
- The surface would exceed its bound -> it is truncated at a field boundary with an
  explicit truncation marker.
- The agent both uses and contradicts the recall -> recorded as used AND as a beta
  increment; the two signals are not merged.

### REQ-16: Semantic collision guard

**User Story:** As the agent I want two different tasks that happen to share a physics
signature to not be handed each other's memories.

**Verified:** REAL RISK, with an existing analogue. The node-chains analysis already
identified the collision shape: `analyze_video_frames` (video files) vs
`vision.analyze_screen` (live screen) — same domain, different context (carried forward
as REQ-28). `workflow_capture.sequence_similarity` (`backend/agent/workflow_capture.py:52`)
is name-Jaccard and order-insensitive, so it cannot discriminate at all today.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL implement the collision guard as a selectable arm family (SC,
  REQ-13 AC1).
- AC2: THE SYSTEM SHALL record, on every delivery, whether the guard passed, and on what
  evidence.
- AC3: WHERE the objective-fingerprint arm is active THE SYSTEM SHALL require a
  fingerprint match on task keywords or active artifact type in addition to the physics
  match.
- AC4: WHERE the context-signature arm is active THE SYSTEM SHALL reuse the REQ-28
  context signatures rather than defining a second notion of context.
- AC5: WHEN the guard rejects a candidate THEN THE SYSTEM SHALL emit
  `recall_semantic_mismatch` (REQ-32) and SHALL NOT increment beta on the hyperedge — a
  guard rejection is not evidence that the shortcut is bad.

**Edge Cases:**
- The fingerprint extractor is unavailable -> the guard degrades to physics-only and logs
  the degradation; it does not silently pass everything.
- The guard rejects everything in a region -> reported as a tagging finding (REQ-6 AC5),
  because it means the signature is lumping unrelated work together.
- A collision is discovered only after injection -> recorded as
  `faultline_intersect=caused_error` and a beta increment (REQ-33).

### REQ-17: End-to-end attribution via recall_trace_id

**User Story:** As the system I want to prove that a specific delivered memory caused a
specific outcome, because without that proof no chain forms and nothing is learned.

**Verified:** The attribution spine already exists in two halves that are not connected.
`ToolBridge._record_tool_event` (`backend/agent/tool_bridge.py:1605`) threads
`plan_title` into the event payload "so tool executions are recallable by plan context"
(`:1613-1614`), proving the payload is extensible at the tool boundary.
`AgentKernel._card_context` (`backend/agent/agent_kernel.py:8017`) already stamps
`card_id` + `conversation_id` onto every event of a task. The missing piece is a recall
identifier travelling the same route.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL mint a `recall_trace_id` per aperture delivery.
- AC2: THE SYSTEM SHALL carry `recall_trace_id` through the injected surface, into the
  tool-execution event payload, and onto the resulting FAULTLINE outcome.
- AC3: THE SYSTEM SHALL carry `recall_trace_id` and `card_id` onto the recall episode
  written for the turn (REQ-0 AC3).
- AC4: THE SYSTEM SHALL make the chain-genesis path able to answer "which deliveries
  contributed to this chain" from stored data alone.
- AC5: IF attribution cannot be established for a delivery THEN THE SYSTEM SHALL record
  the delivery with `agent_used=unknown` rather than defaulting it to false — an
  unmeasured outcome must not be scored as a negative.

**Edge Cases:**
- The tool boundary is bypassed (an internal action with no tool call) -> attribution
  falls back to the node boundary; the coarser scope is recorded.
- Two deliveries are live for one node (bounded-queue arm OV-B) -> each carries its own
  trace id and each is attributed separately.
- A delivery contributes to a success many turns later -> attribution window is bounded
  and the bound is recorded; late credit is dropped, not guessed.

---

# STAGE C — NODE CHAINS (the consumer and the proof)

> Carried forward from `specs/node-chains/`. The Decisions Locked of that spec remain in
> force: a skill IS a node chain; a pivot is a first-class recorded event; the Caducean
> RL signal is the reinforcement signal; chains live in app memory and `chain.md` is a
> minimal generated projection; agent-created nodes are NODE GRAFTS; no workflow is ever
> hardcoded into the backend.

### REQ-18: NodeChain data model
**(was NC REQ-1)**

**User Story:** As the agent I want a successful node path stored as a first-class,
loadable object so that I can reuse it as a deterministic baseline.

**Verified:** `mycelium_traversals` already stores `path_node_ids` + `path_score` +
`outcome` (`backend/memory/db.py:229`, `backend/memory/mycelium/store.py:546`).
`NodeRecord` carries `mediator` (`backend/agent/der_loop.py:120`). Missing: a first-class
chain object with fork points and stats.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define a NodeChain record carrying at minimum chain_id, name,
  trigger, an ordered list of chain nodes, stats (uses, success_rate, avg_score),
  provenance, and confidence.
- AC2: THE SYSTEM SHALL define a chain node as a reference to a mediator (tool + args
  schema) with its expected outcome and verified_fraction.
- AC3: THE SYSTEM SHALL store chains in app memory (`data/memory.db`), not in MCM
  coordinates.
- AC4: THE SYSTEM SHALL persist chains durably so they survive process restarts.
- AC5 **[CHANGED FROM NC]**: THE SYSTEM SHALL record on the chain's provenance the
  `card_id` of the task card that produced it and the `recall_trace_id`s that
  contributed, so a chain is addressable from the card the user can see
  (Decisions Locked 9, REQ-17 AC4).

**Edge Cases:**
- A chain with zero nodes -> never created; extraction requires >= 2 nodes.
- Duplicate chain (same mediator sequence) -> deduplicated by sequence hash.

### REQ-19: Chain extraction from live DER runs
**(was NC REQ-2)**

**User Story:** As the agent I want a successful run to become a chain immediately so
that the next similar task starts from the proven path.

**Verified:** `_maybe_trigger_skill_creation` is called after DER completes
(`backend/agent/agent_kernel.py:7021`, defined `:1535`) with `_tool_seq` built from
`completed_items`. `record_fan_trace` records per-node `(step_id, tool, args_hash,
outcome, u, xi)` (`backend/agent/caducean_trajectory.py:293`).

**Acceptance Criteria:**
- AC1: WHEN a DER run completes with outcome success THEN THE SYSTEM SHALL extract a
  chain from the run's node records (mediator sequence + outcomes).
- AC2: THE SYSTEM SHALL extract from node records / fan traces, not from the tool-name-set
  heuristic.
- AC3: THE SYSTEM SHALL record provenance (session_id, task_summary, timestamp, card_id).
- AC4: THE SYSTEM SHALL NOT extract a chain from a run with fewer than 2 successful nodes.

**Edge Cases:**
- Run completes partially -> extraction deferred; the partial run is recorded as
  evidence, not a chain.
- Run fails -> no chain; the failure feeds the pivot/failure vocabulary.

### REQ-20: Chain extraction from recall episodes (the C3 requirement)
**(was NC REQ-3)**

**User Story:** As the agent I want repeated successful recall episodes to crystallize
into a chain so that cross-session patterns emerge without a live run.

**Verified:** `_log_recall_episode` (`backend/agent/recall_phases.py:433`) persists
recall traces with `ops_trace` and `outcome_type` (default `"partial"`, `:438`),
`source_channel="recall"` (`:480`). `_maybe_trigger_skill_creation` returns early on an
empty tool_sequence (`backend/agent/agent_kernel.py:1561`) — the recall path was never
wired. **Baseline run 2026-08-23:** `test_recall_fixes.py::TestC3SkillGenesisSql` FAILS
("skill genesis did not fire despite 3 successful recall episodes"), 1 failed / 2 passed.
**And per REQ-0, the writer itself is unreachable in production** — so this requirement
depends on Stage 0.

**Acceptance Criteria:**
- AC1: WHEN >= 3 recall episodes with `source_channel='recall'` AND
  `outcome_type='success'` share a tool/op pattern THEN THE SYSTEM SHALL extract a chain.
- AC2: THE SYSTEM SHALL NOT trigger extraction for `outcome_type='hit'` or
  `outcome_type='partial'`.
- AC3: THE SYSTEM SHALL make `test_recall_fixes.py::TestC3SkillGenesisSql::test_sql_matches_success_episodes`
  pass WITHOUT weakening its assertions or its inputs.
- AC4: THE SYSTEM SHALL deduplicate recall-extracted chains against live-run chains
  (same sequence hash -> one chain).
- AC5 **[CHANGED FROM NC]**: THE SYSTEM SHALL count an episode toward the threshold only
  when its attribution is established (REQ-17); episodes with `agent_used=unknown` SHALL
  NOT count toward genesis, and the excluded count SHALL be logged.

**Edge Cases:**
- Fewer than 3 matching episodes -> no chain; the count is configurable.
- The pattern is already a chain -> no new chain.
- All three episodes came from one delivery replayed -> deduplicated by
  `recall_trace_id`; three deliveries are required, not three rows.

### REQ-21: Pivot recording
**(was NC REQ-4)**

**User Story:** As a future agent I want every deviation from a chain with its
indicators, so that I can judge whether the fork is relevant to my task.

**Verified:** `NodeOutcome.Reason` is a closed vocabulary
(`backend/agent/nodes/outcome.py:40`). `record_fan_trace` carries u/xi per node
(`backend/agent/caducean_trajectory.py:293`). `NodeRecord` carries `folded_back`,
`probe`, `chosen_branch` (`backend/agent/der_loop.py:141,149,157`).

**Acceptance Criteria:**
- AC1: WHEN the agent deviates from a chain's predicted next node THEN THE SYSTEM SHALL
  record a PivotEvent.
- AC2: THE SYSTEM SHALL record chain_id, node_index, trigger (NodeOutcome reason),
  alternative_taken, outcome (OK/PARTIAL/FAILED), u_before/u_after, xi_before/xi_after.
- AC3: THE SYSTEM SHALL tag the PivotEvent with topic_domain and execution_domain.
- AC4: THE SYSTEM SHALL make PivotEvents queryable by chain_id, node_index, trigger, and
  outcome.
- AC5: THE SYSTEM SHALL record pivots even when the deviation ultimately fails.
- AC6 **[CHANGED FROM NC]**: WHEN a pivot was taken while a recall was live in the
  aperture THEN THE SYSTEM SHALL record the `recall_trace_id` on the PivotEvent, so a
  recall that CAUSED a pivot is distinguishable from one that merely coincided with it.

**Edge Cases:**
- Deviation with no chain active -> no PivotEvent; pivots are relative to a chain.
- No Caducean state -> u/xi recorded as null; the pivot is still recorded.

### REQ-22: Pivot promotion to chain variant
**(was NC REQ-5)**

**User Story:** As the agent I want a proven fork to become a first-class alternative so
that the chain grows branches rather than being replaced.

**Verified:** `caducean_trajectories` + `der_commits` carry the RL signal
(`backend/agent/caducean_trajectory.py:258,484`). `mycelium_landmark_merges` exists as
the merge precedent. No fork/variant concept exists today.

**Acceptance Criteria:**
- AC1: WHEN a pivot at the same chain_id + node_index succeeds N times (default 2) AND
  the RL signal confirms improvement THEN THE SYSTEM SHALL promote it to a variant.
- AC2: THE SYSTEM SHALL record the promotion with the pivot events that justified it.
- AC3: THE SYSTEM SHALL make variants selectable at execution time.
- AC4: THE SYSTEM SHALL NOT promote a pivot that succeeded once without RL confirmation.
- AC5: THE SYSTEM SHALL bound variants per fork point (default 3); overflow merges or
  archives the weakest.

**Edge Cases:**
- RL neutral -> no promotion; the pivot stays recorded.
- A variant outperforms the main chain -> it may become the main chain; the old main
  becomes a variant. Auto, with logging.

### REQ-23: Chain-guided execution
**(was NC REQ-6)**

**User Story:** As the agent I want to start from a proven chain but keep the freedom to
pivot when the world differs.

**Verified:** `DirectorQueue` (`backend/agent/der_loop.py:243`) is seeded from
`ExecutionPlan.steps` and manages mode; `next_ready` (`:502`) is the dispatch point;
`NodeRecord` carries the pivot mechanics.

**Acceptance Criteria:**
- AC1: WHEN a chain matches the incoming task THEN THE SYSTEM SHALL seed the
  DirectorQueue from the chain's node sequence.
- AC2: THE SYSTEM SHALL run every chain node through the existing node execution
  machinery — chain nodes are NOT exempt from pivot mechanics.
- AC3: WHEN a chain node fails with a routable reason THEN THE SYSTEM SHALL apply
  outcome-driven routing and record a PivotEvent.
- AC4: THE SYSTEM SHALL match chains by trigger + topic/execution domain, not exact text.
- AC5: THE SYSTEM SHALL allow chain-guided execution to be disabled entirely.

**Edge Cases:**
- No chain matches -> free planning, exactly as today.
- Every chain node fails -> degrade to free planning; failures count against the chain's
  confidence.
- A mediator is unavailable -> node skipped with a recorded reason; chain flagged for
  revalidation.

### REQ-24: chain.md projection
**(was NC REQ-7)**

**User Story:** As the agent I want a lean, loadable view of a chain so that I can
discover and trigger it without loading an instruction manual.

**Verified:** `mycelium_pins` / `mycelium_pin_links` exist (`backend/memory/db.py`), and
`PinStore` (`backend/memory/pin_store.py`) is the registration surface.
`data/chains/` does not exist yet (verified: directory absent).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL generate `chain.md` containing ONLY name, trigger, the ordered
  node sequence (mediator -> expected outcome), and fork points.
- AC2: THE SYSTEM SHALL NOT include tutorial text, phases, examples, or prose beyond the
  chain's purpose.
- AC3: THE SYSTEM SHALL regenerate on chain change (promotion, variant addition,
  confidence update).
- AC4: THE SYSTEM SHALL NOT accept hand-written `chain.md` files as chain sources.
- AC5: THE SYSTEM SHALL name the projection `chain.md`, not `skill.md`.
- AC6: THE SYSTEM SHALL store projections at `data/chains/<chain_id>.md`.
- AC7: THE SYSTEM SHALL embed `chain_id` in frontmatter AND store `chain_md_path` on the
  chain record — a stable bidirectional link that survives regeneration.
- AC8 **[CHANGED FROM NC]**: THE SYSTEM SHALL register each `chain.md` as a pin
  (`pin_type='chain_md'`) linked via pin links, **in the table `specs/der-ground-truth/`
  REQ-4 determines to be authoritative** — NOT `mycelium_pins` by assumption. The audit
  found `mycelium_pins` holds 0 rows (while `PinStore` writes to it,
  `backend/memory/pin_store.py:193`) and `mycelium_pin_links` holds 354 orphaned links.
  Registering chain projections into the empty table would make every chain unfindable.
- AC9: WHEN a chain changes THEN THE SYSTEM SHALL mark the pin `ref_status='stale'`,
  regenerate, and restore `ref_status='alive'` with `last_validated` updated.
- AC10: THE SYSTEM SHALL store `chain_md_hash` for STALENESS DETECTION only; the hash
  SHALL NEVER serve as the link.

**Edge Cases:**
- Many nodes -> truncated to the REQ-25 bound; the full chain stays in memory.
- Directory unwritable -> chain stays in memory; generation retried, never fatal.
- Pin registration fails -> the file still exists; registration retried, never fatal.
- File deleted but chain exists -> regenerated on demand; the record is the truth.

### REQ-25: Anti-bloat and token discipline
**(was NC REQ-8)**

**User Story:** As the user I want chains to never bloat the system or cost tokens the
agent does not need.

**Verified:** Current SKILL.md files carry long instruction bodies; loading them costs
tokens. `MIN_DISTINCT_TOOLS = 3` and `SIMILARITY_THRESHOLD = 0.85`
(`backend/agent/workflow_capture.py:29-30`) are the current capture bounds.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL bound each `chain.md` by a configurable hard token/byte cap.
- AC2: THE SYSTEM SHALL bound total chains and variants; on overflow the weakest
  (confidence x usage) are ARCHIVED, never silently deleted.
- AC3: THE SYSTEM SHALL merge chains sharing a prefix and outcome, reusing the
  landmark-merge pattern.
- AC4: THE SYSTEM SHALL NOT load a chain's full memory record when only the projection
  is needed.
- AC5: THE SYSTEM SHALL record chain size and load cost in stats so bounds are tunable
  from data.

**Edge Cases:**
- Archive threshold reached mid-session -> archiving deferred to a maintenance pass,
  never on the critical path.
- A chain referenced by an active PivotEvent -> not archived while referenced.

### REQ-26: Node grafts from chains (composite nodes)
**(was NC REQ-10)**

**User Story:** As the agent I want a proven chain to become a callable node so that I
can compose pipelines without anyone writing dispatch code.

**Verified:** `register_tool` (`backend/agent/tool_registry.py:99`) and `register_node`
are programmatic and idempotent; media pipeline nodes (`transcribe_media` `:876`,
`analyze_video_frames` `:891`, `clip_video` `:909`) already declare artifact kinds and
failure reasons. `self_test_skill` (`backend/agent/workflow_capture.py:85`) is the
structural-self-test precedent.

**Acceptance Criteria:**
- AC1: WHEN a chain reaches a verified state THEN THE SYSTEM SHALL allow it to be grafted
  as a composite node (`composite_of` = the chain's sequence, `origin='chain_graft'`)
  with its own name, inputs, artifact kind, and failure reasons.
- AC2: THE SYSTEM SHALL make a grafted chain-node callable exactly like any other node.
- AC3: THE SYSTEM SHALL allow grafts to nest inside higher-order chains.
- AC4: THE SYSTEM SHALL self-test a graft before acceptance; a failed self-test REJECTS
  the graft WITHOUT touching the registry.
- AC5: THE SYSTEM SHALL NOT require user approval for chain grafts.
- AC6: THE SYSTEM SHALL keep chain and graft in sync — a chain change re-grafts or marks
  stale.

**Edge Cases:**
- An inner node is removed -> graft marked stale, refused until revalidated.
- Two chains graft the same node name -> the duplicate guard refuses the second.

### REQ-27: Node grafts from scripts (sandboxed, approval-gated)
**(was NC REQ-11)**

**User Story:** As the agent I want to grow a genuinely new leaf capability by writing a
small script, so that the pipeline is not blocked on a developer.

**Verified:** `ToolSpec.executor` (`backend/agent/tool_registry.py:58`) supports
`internal | mcp | dev | crawler | research | memory | gui` — there is NO script executor
today. `create_skill` (`:492`) is the runtime-node-creation precedent.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL allow the agent to author a script or parameterized command
  template and graft it with `executor="script"`, `origin='script_graft'`.
- AC2: THE SYSTEM SHALL run script grafts in a sandbox: subprocess with timeout, no shell
  expansion, bounded arguments, no network by default.
- AC3: THE SYSTEM SHALL default script grafts to `permission_tier="read_only"` and SHALL
  require explicit user approval before any escalation.
- AC4: THE SYSTEM SHALL structurally self-test before first use; failure REJECTS.
- AC5: THE SYSTEM SHALL record the graft's source and approval state.
- AC6: THE SYSTEM SHALL allow accepted script grafts to compose into chains.
- AC7: THE SYSTEM SHALL allow script grafts to be disabled entirely (composition-only
  mode).

**Edge Cases:**
- Script hangs -> subprocess timeout; typed failure reason returned.
- Script writes outside its sandbox -> denied and recorded.
- User denies escalation -> graft stays at its tier; the agent pivots.
- Script graft fails in a chain -> outcome-driven routing applies.

### REQ-28: Context signatures and tool fit validation
**(was NC REQ-12)**

**User Story:** As the agent I want to pick the right tool when several similar tools
exist, so that a chain node never fires the wrong tool for the task context.

**Verified:** Tools are differentiated only by name + description + category
(`backend/agent/tool_registry.py:44-70`). `sequence_similarity`
(`backend/agent/workflow_capture.py:52`) is name-Jaccard, order-insensitive. The
collision is real: `analyze_video_frames` (video files) vs `vision.analyze_screen` (live
screen).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL give every node a context signature: domain, artifact contract
  (in/out kinds), and intent keywords.
- AC2: THE SYSTEM SHALL record the context signature on each chain node at capture time.
- AC3: WHEN a chain is replayed THEN THE SYSTEM SHALL validate each node's mediator
  against the current task context; IF fit is below threshold THEN THE SYSTEM SHALL treat
  it as a pivot rather than firing the wrong tool.
- AC4: WHEN a graft is created THEN THE SYSTEM SHALL require a distinguishing context
  signature; a near-duplicate SHALL be refused or require explicit differentiation.
- AC5: THE SYSTEM SHALL maintain a semantic (not name-Jaccard) tool similarity index used
  by both selection and graft dedupe.
- AC6: THE SYSTEM SHALL record the selection rationale on the node record.
- AC7 **[CHANGED FROM NC]**: THE SYSTEM SHALL expose the context signature to the
  aperture's SC-C arm (REQ-16 AC4) rather than letting the aperture define its own notion
  of context.

**Edge Cases:**
- Two tools truly interchangeable -> high similarity reported; selection deterministic and
  logged.
- Recorded context stale -> fit validation fails -> pivot -> possibly a new variant.
- Graft declares an identical context -> refused.
- Index unavailable -> exact-name fallback, degradation logged.

### REQ-29: Tool evolution — versioning and revalidation
**(was NC REQ-13)**

**User Story:** As the agent I want chains to stay correct when the tools they use change,
so that a chain never silently runs against a stale tool.

**Verified:** `NodeRecord.mediator` records tool + args hash
(`backend/agent/der_loop.py:120`); `record_fan_trace` records `args_hash`
(`backend/agent/caducean_trajectory.py:293`). Neither records a tool VERSION. No
tool-change revalidation exists.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL record a tool version/signature hash on each chain node at
  capture time.
- AC2: WHEN a tool's signature changes THEN THE SYSTEM SHALL flag referencing chains stale
  and revalidate them.
- AC3: WHEN a tool is removed THEN THE SYSTEM SHALL flag referencing chains and pivot to
  an alternative or mark for re-capture.
- AC4: WHEN a tool is improved THEN THE SYSTEM SHALL re-verify chains using it and reflect
  the improvement as RL reinforcement.
- AC5: THE SYSTEM SHALL record the tool-change event and each chain's revalidation outcome.
- AC6: THE SYSTEM SHALL apply tool evolution to grafts.
- AC7 **[CHANGED FROM NC]**: WHEN a landmark referenced by a chain falls below elevation
  (REQ-7 AC4) THEN THE SYSTEM SHALL flag that chain for revalidation on the same path as a
  tool change — a fallen landmark is a changed dependency.

**Edge Cases:**
- Tool changes but the chain still works -> revalidation confirms; version bumped.
- Incompatible change -> fit validation fails -> pivot.
- Tool removed with no alternative -> chain archived, never silently deleted.
- Tool-change storm -> revalidation batched to a maintenance pass.

### REQ-30: Cross-domain pipeline creation — remove capture blockers
**(was NC REQ-14)**

**User Story:** As the agent I want to create a pipeline for ANY domain or across domains,
so that no structural threshold silently prevents a valid pipeline from becoming a chain.

**Verified:** Three blockers confirmed: (1) `MIN_DISTINCT_TOOLS = 3`
(`backend/agent/workflow_capture.py:29`); (2) `sequence_similarity` (`:52`) is
order-insensitive name-Jaccard; (3) nodes declare what they PRODUCE
(`backend/agent/tool_registry.py:183`) but not what they CONSUME. Verified NON-blockers:
`domain_windings` (`backend/agent/coupled_registry.py:83`) maps domains to physics
numbers, not tool filters; `get_available_tools` (`backend/agent/tool_bridge.py:237`)
returns all tools with no domain filter.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL capture a chain from ANY successful run regardless of
  distinct-tool count — a 2-node chain is valid.
- AC2: THE SYSTEM SHALL dedupe by ORDER-SENSITIVE sequence hash, not name-Jaccard.
- AC3: THE SYSTEM SHALL extract from BOTH episode channels (`websocket` and `recall`).
- AC4: THE SYSTEM SHALL validate artifact compatibility at composition time, BEFORE
  execution.
- AC5: THE SYSTEM SHALL NOT restrict composition by domain.

**Edge Cases:**
- A 2-node chain never reused -> decays/archives via REQ-25, not by a capture threshold.
- Same tool set, different order -> both captured, distinct hashes.
- Artifact mismatch -> pivot to a compatible node or graft an adapter.

### REQ-31: Chain-level permission resolution
**(was NC REQ-15)**

**User Story:** As the user I want to approve a cross-domain chain once, not per node, so
that legitimate pipelines are not silently blocked while security is preserved.

**Verified:** `ToolSpec.permission_tier` (`backend/agent/tool_registry.py:56`) is
`read_only | side_effect | destructive`. No chain-level resolution exists.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL compute a chain's required tier as the MAX of its nodes' tiers.
- AC2: WHEN a chain requires a tier above the current session THEN THE SYSTEM SHALL
  request approval for the CHAIN as a unit and SHALL NOT execute until approved.
- AC3: THE SYSTEM SHALL record the approved tier on the chain record.
- AC4: THE SYSTEM SHALL NOT allow a chain to exceed its approved tier even if a node's
  tier changes later.
- AC5: THE SYSTEM SHALL apply the same resolution to grafts.
- AC6 **[CHANGED FROM NC]**: THE SYSTEM SHALL NEVER let a delivered recall raise the
  effective permission tier of a running chain. A recall is information; it is not
  authorization.

**Edge Cases:**
- User denies -> chain not executed; the agent pivots lower or narrows the task.
- A node's tier rises after approval -> chain flagged for re-approval, never silently
  executed at the higher tier.
- Entirely read_only chain -> no approval needed.

### REQ-41: RECALL is a node state, structurally parallel to SPLIT

**User Story:** As the agent I want recall to be a state my execution enters and
leaves, not a step run before I start, so that the recall becomes part of the
thought instead of a preamble to it.

**Verified:** GAP IN THIS SPEC, found on a re-read of the parent doc 2026-08-23.
`docs/Wormhole-resonant-recall-.md` §1 is unambiguous and this spec had captured
none of it — every occurrence of "split" here referred to the Tier-1a/1b/2 hit-rate
split, never to the DAG's SPLIT state. The doc specifies:

```
RUNNING (streaming tokens)
  -> variance spike (|u| crosses threshold mid-thought - a confounder surfaces)
  -> RECALL (bounded query against Mycelium)
  -> posterior + resonance update on touched edges
  -> RUNNING resumes with updated 4D state
```

and states the trigger explicitly: the agent "asks when the current
Treatment->Mediator edge it is reasoning about has no confident prior — **exactly
the same trigger condition already defined for SPLIT**." `U_SPLIT = 0.5`
(`backend/agent/der_constants.py:233`) is that threshold, with bands documented at
`:403-406`.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL model RECALL as a node STATE in the existing DAG,
  structurally parallel to SPLIT — entered from RUNNING, exited back to RUNNING.
- AC2: THE SYSTEM SHALL trigger RECALL from the SAME condition SPLIT already uses
  — no confident prior on the Treatment->Mediator edge under consideration — and
  SHALL reuse `U_SPLIT` rather than introducing a second threshold. A new
  threshold here would be the "new subsystem in disguise" the parent doc's §0
  scoping constraint forbids.
- AC3: WHEN RECALL exits THEN THE SYSTEM SHALL apply the posterior and resonance
  update to the edges the query touched, and RUNNING SHALL resume with the
  updated 4D state — the update is part of leaving the state, not a later pass.
- AC4: THE SYSTEM SHALL NOT front-load recall. The agent SHALL NOT decide upfront
  what history it might need (this is what makes REQ-0's replacement of the
  two-phase protocol a design consequence rather than a preference).
- AC5: THE SYSTEM SHALL keep RECALL bounded and off the critical path per REQ-12;
  being a node state does NOT make it synchronous work on the stream.
- AC6: THE SYSTEM SHALL record RECALL state entries and exits like any other node
  state, so the recall's own frequency and cost are visible (REQ-35).

**Edge Cases:**
- The spike condition fires but the aperture has nothing -> RECALL is entered and
  exits immediately with no update; the empty visit is still recorded, because
  "how often do we look and find nothing" is a tuning signal.
- SPLIT and RECALL both qualify on the same spike -> the existing DAG decides;
  this spec adds a state, it does not re-order the state machine.
- Caducean state unavailable -> no spike can be computed, so RECALL never
  triggers; recorded as a degradation, never as "no recall needed".

### REQ-42: Per-node state completeness and the no-window rule

**User Story:** As the maintainer I want recency derived from timestamps rather
than a configured lookback, so that nobody has to guess a window size.

**Verified:** GAP IN THIS SPEC. `docs/Wormhole-resonant-recall-.md` §4 specifies
`activation_log` — "timestamped list or decayed count, **NOT a fixed window**" —
and closes with: "**No `window_size` field.** Recency is read directly off
`last_activated_ts` vs `created_ts` — the oscillator math uses the gap, not a
configured lookback range." This spec's data model carried neither the field nor
the prohibition. `mycelium_nodes` already has `created_at` and `last_accessed`
(`backend/memory/db.py:195-204`), so the timestamps exist; the activation history
does not.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL carry an `activation_log` per wormhole node — a
  timestamped list or a decayed count.
- AC2: THE SYSTEM SHALL NOT introduce a `window_size` field, a configured
  lookback, or any fixed-N recency window anywhere in the wormhole layer.
- AC3: THE SYSTEM SHALL derive recency from the gap between `last_activated` and
  `created`, which is what the oscillator math (REQ-5) consumes.
- AC4: THE SYSTEM SHALL bound `activation_log` so a long-lived node cannot grow
  it without limit, and SHALL prefer a decayed count over truncating history
  silently — if it does truncate, it SHALL record that it did.
- AC5: THE SYSTEM SHALL reuse `mycelium_nodes.created_at` / `last_accessed` for
  the timestamps rather than adding parallel columns.
- AC6 **[REQ-9 interaction]**: THE SYSTEM SHALL treat `activation_log` as the
  BUSYNESS reading's source, keeping it separate from the posterior that carries
  usefulness — the two are never averaged.

**Edge Cases:**
- A node is activated many times in one run -> recorded per activation; burst
  behaviour is signal, not noise to be collapsed.
- `last_accessed` is never written (the `access_count` defect, GROUND TRUTH
  Finding 11) -> this requirement DEPENDS on that being fixed; if the timestamp
  is stale the recency term is meaningless and SHALL be reported as un-computable
  rather than silently used.

### REQ-43: Vocabulary lock — the scoring act is POLLING, never "treatment"

**User Story:** As a future agent reading this system I want its terms to mean one
thing each, so that the causal vocabulary does not collide with the scoring
vocabulary.

**Verified:** GAP IN THIS SPEC. `docs/Wormhole-resonant-recall-.md` Q2a states it
directly: "call this act POLLING or VOTING — never 'treatment'. Treatment is
already taken in the causal vocabulary (the objective handed to a node, per the
original blueprint §2). Reusing it for the act of scoring would collide with the
DAG's own terms, the same class of drift as `related_to` vs `relevant_to`."

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL name the act of accumulating votes and deriving a
  measurement from the tally POLLING or VOTING, in code, comments, and telemetry.
- AC2: THE SYSTEM SHALL reserve Treatment, Mediator, Outcome and Confounder for
  their causal meanings from the original blueprint, and SHALL NOT reuse any of
  them for a scoring mechanism.
- AC3: THE SYSTEM SHALL preserve the established vocabulary generally — DAG,
  fan_trace, Hex/Hash/Hyperedge, wormhole, landmark, resonance/amplitude,
  coupling-derived damping — since the parent doc's §10 note to future agents
  asks for continuity of terms, and this spec is what those agents will read.

**Edge Cases:**
- A new mechanism genuinely needs a name -> it takes a new one; it does not borrow
  a causal term.
- Existing code already misuses a term -> recorded as a finding; renaming live
  code is out of scope here unless it is the wormhole's own.

### REQ-39: Level 3 meta-learning is named, not assumed

**User Story:** As the architect I want the loop that DOES the scoring to be a
named, existing mechanism, because the parent doc's governing principle is
"refuse to hardcode, score it instead" — and a scoring principle with no scorer
is a hardcoded value wearing a different label.

**Verified:** GAP IN THIS SPEC, raised by the user 2026-08-23. The parent doc
(`docs/Wormhole-resonant-recall-.md` §6) is explicit that the wormhole-match
threshold uses "the existing Level 3 Meta-Learning loop from the original
blueprint (Section 4) pointed at this specific threshold — **not a new
mechanism**." §5a says the same for coupling divergence; Q4 says it for hex
quantization; Q2a generalises it into the governing principle. This spec applied
that principle in five places (threshold, coupling, elevation, quantization,
arms) but never named the loop that actually adjusts them — it only referenced
`backend/agent/outer_loop.py` as a CAUTIONARY example, and put the meta-learner
in Non-Requirements. That leaves the values scored but never re-tuned.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL name, for every value this spec declines to hardcode, the
  existing loop that adjusts it — wormhole-match threshold (REQ-4 AC6), coupling
  seed/observed blend (REQ-6), elevation thresholds (REQ-7), hex quantization
  (REQ-10 AC5), and aperture arm weights (REQ-14).
- AC2: THE SYSTEM SHALL route those adjustments through the EXISTING Level 3
  loop (`backend/agent/outer_loop.py`) rather than adding a second self-tuning
  mechanism — the parent doc's "not a new mechanism" constraint.
- AC3: THE SYSTEM SHALL subject every wormhole value it feeds to that loop to the
  loop's existing compound gate, including the `live` vs `passed` distinction
  (`outer_loop.py:27-37`), so a value whose evidence cannot be computed is not
  adjusted on a dead signal.
- AC4: THE SYSTEM SHALL NOT let the outer loop tune a wormhole value on a single
  metric. `bootstrap/GOALS.md` records that this loop already "accepts ANY
  proposal that raises natural-exit rate" — pointing it at wormhole values
  without fixing that would propagate the reward-hack into the memory topology.
- AC5: IF the outer loop is unavailable or disabled THEN THE SYSTEM SHALL hold
  every scored value at its last known-good setting and SHALL record that it is
  no longer adapting — never silently revert to a compiled-in default.
- AC6: THE SYSTEM SHALL record each adjustment with the evidence that justified
  it, so a drifting threshold is auditable after the fact.

**Edge Cases:**
- The loop proposes an adjustment the compound gate rejects -> recorded as a
  refused promotion with cause (REQ-35 AC6), not discarded.
- Two wormhole values are coupled (threshold and quantization) -> adjusted one at
  a time, per the loop's existing one-change-per-run discipline.
- No evidence has accumulated yet -> the value holds at its seed and is reported
  as un-tuned, which is honest; an un-tuned value is not a failure.

### REQ-40: The existing learning layer must keep working as the fallback

**User Story:** As the user I want the memory that works today to still work after
this ships, so that an error in node chains or wormhole degrades the system to
"as good as before" rather than to "no learning at all".

**Verified:** GAP IN THIS SPEC, raised by the user 2026-08-23. REQ-37 provides
kill switches that return to "today's behavior" — but that phrase was never
audited. What today's behavior actually is, measured: the PHEROMONE layer
(`graph_edges`) is alive and learning in both store instances; the application
`mycelium_*` coordinate layer is starved (37 nodes, 0 edges). So "fall back to
today" means falling back to the pheromone layer, and that layer's health is a
PRECONDITION of this spec, not an afterthought.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL treat the existing pheromone/graph learning layer as a
  first-class fallback, and SHALL verify it still functions after every stage of
  this spec — not only that the new layer works.
- AC2: WHEN wormhole retrieval, aperture delivery, or chain-guided execution is
  disabled or failing THEN THE SYSTEM SHALL continue recording and scoring
  through the existing layer, at no less than its pre-spec rate.
- AC3: THE SYSTEM SHALL NOT route the existing layer's writes through any new
  component this spec adds, so a defect in the new path cannot take the old one
  down with it.
- AC4: THE SYSTEM SHALL measure the existing layer's write and score rates before
  and after each stage, and SHALL treat a drop as a regression in this spec.
- AC5: THE SYSTEM SHALL preserve the MCM build-store inheritance path
  (`CLAUDE.md`: same schema, no migration) — nothing added here may make the
  inherited graph unreadable by the application.
- AC6: THE SYSTEM SHALL make the fallback exercisable on demand, so "it would
  still work" is demonstrated rather than assumed.

**Edge Cases:**
- The new layer and the fallback disagree about a value -> the fallback is
  authoritative while the new layer is disabled; the disagreement is recorded.
- The fallback itself is found to be degraded -> that is a `specs/der-ground-truth/`
  finding and BLOCKS this spec, because a fallback that does not work is not one.
- Inheritance lands mid-flight -> the new layer treats inherited rows as ordinary
  evidence; it may not require them to carry fields this spec introduced.

### REQ-38: Chain specificity — a chain must constrain more than free planning would

**User Story:** As the user I want to know whether a chain is actually telling the agent
something, because a chain that encodes what the agent would have done anyway is bloat
wearing the costume of a skill.

**Verified:** NEW — and the risk is concrete. `sequence_similarity`
(`backend/agent/workflow_capture.py:52`) is name-Jaccard and order-insensitive, so today
nothing distinguishes a meaningful pipeline from a generic one. Most research tasks in this
system run through the same small mediator set (`web_search`, `crawler_query`, synthesise),
so a chain of those names is close to content-free as a plan: it predicts nothing that
free planning would not have produced. The value of a chain lives in its ARGUMENTS, its
context signature, and its fork points — not in its tool order.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL compute a specificity score per chain — how much the chain
  constrains the next run beyond what free planning would have produced for the same task
  class.
- AC2: THE SYSTEM SHALL derive specificity from what the chain actually pins: argument
  schemas, context signatures (REQ-28), and fork points — NOT from mediator-name sequence
  alone.
- AC3: THE SYSTEM SHALL record specificity in the chain's stats (REQ-25 AC5) and report its
  distribution (REQ-35).
- AC4: THE SYSTEM SHALL treat a low-specificity chain as an ARCHIVE candidate ahead of a
  high-specificity one when the chain bound is exceeded (REQ-25 AC2) — this is
  specificity's named consumer (G2).
- AC5: THE SYSTEM SHALL NOT block chain creation on specificity; a low-specificity chain is
  recorded, measured, and allowed to decay. Refusing to create it would hide the
  measurement that proves the concept works or does not.
- AC6: THE SYSTEM SHALL make the aggregate answerable: across all chains, what fraction
  constrain the next run more than free planning. **That fraction is the honest test of
  whether Node Chains is worth its complexity**, and it must be reportable before Stage C
  is called successful.

**Edge Cases:**
- No free-planning baseline exists for a task class -> specificity is reported as
  `unknown`, never as zero. An unmeasured chain is not a bad chain.
- A chain is highly specific but never matches anything -> that is REQ-25's decay problem,
  not a specificity problem; the two signals stay separate.
- Every chain scores low -> that is a finding about the concept, to be reported plainly,
  not a threshold to be loosened until chains look good.

---

# STAGE D — FAULTLINE integration (bidirectional)

### REQ-32: Recall failures are FAULTLINE labels

**User Story:** As the reviewer I want a recall failure to arrive with its cause and
dimensions intact, like every other failure in the system.

**Verified:** `register_error_label(label, retryable, blame, info_state, description)`
(`backend/agent/tool_errors.py:92`) is the Layer-2 growth API and REFUSES invalid
dimension values (`:106-108`). `tool_error` (`:247`) and `normalize_failure` (`:309`)
are the canonical construction and boundary-normalization functions. Seeded vocabulary
today: `transient`, `walled`, `rate_limited`, `empty`, `invalid_params`,
`capability_missing`, `crashed` (`docs/architecture/FAULTLINE.md` §7).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL register the recall failure labels through the EXISTING
  `register_error_label` API — a data edit, never a loop rewrite:
  `recall_timeout` (maybe/self/unknown), `recall_store_locked` (maybe/world/blocked),
  `aperture_expired` (yes/self/missing), `recall_candidate_stale` (yes/query/unknown),
  `recall_semantic_mismatch` (no/query/unknown).
- AC2: THE SYSTEM SHALL name, for each label, the dispatch or planning site that READS it.
  **A label with no named consumer SHALL be refused at review** (FAULTLINE §11 design
  rule, generalized as Gate G2).
- AC3: THE SYSTEM SHALL preserve the original message in `details["raw"]` for every
  recall failure, per the canonical outcome shape.
- AC4: THE SYSTEM SHALL let unrecognized recall failures land in Layer 3 (stored raw +
  counted), never discarded.

**Edge Cases:**
- A recall failure occurs outside a tool boundary -> it is still constructed via
  `tool_error()` so the shape is identical; only the emission site differs.
- The label registry is not yet seeded when the first failure occurs -> Layer 3 catches
  it and it is promotable via `promote_unknown` (`backend/agent/tool_errors.py:235`).

### REQ-33: FAULTLINE outcomes feed hyperedge posteriors

**User Story:** As the agent I want a recall that caused a wall to be trusted less next
time, and a recall that prevented a retry loop to be trusted more.

**Verified:** The read side already exists and has a live proof of value.
`record_wall` / `is_walled` (`backend/agent/tool_errors.py:178,190`) form a domain-keyed
TTL ledger consulted by `dispatch_urls` before spending a round trip
(`docs/architecture/FAULTLINE.md` §11), added because spacedaily.com parked as `walled`
at 14:56 and was re-dispatched at 15:13 — 18 dispatch rounds of churn. This requirement
applies the same read-side discipline to hyperedges.

**Acceptance Criteria:**
- AC1: WHEN a tool executed under a live `recall_trace_id` fails with a `retryable:no`
  label THEN THE SYSTEM SHALL increment beta on the hyperedge that delivered it.
- AC2: WHEN a delivered recall demonstrably prevents a FAULTLINE error THEN THE SYSTEM
  SHALL increment alpha on that hyperedge.
- AC3: THE SYSTEM SHALL record `faultline_intersect` as one of
  `null | prevented_error | caused_error` on every `aperture_decision`.
- AC4: THE SYSTEM SHALL NOT increment beta when the aperture's own guard rejected the
  candidate (REQ-16 AC5) — the shortcut was never tried.
- AC5: THE SYSTEM SHALL consult the wall ledger BEFORE ranking a candidate whose mediator
  targets a walled domain, and SHALL down-rank rather than deliver it.

**Edge Cases:**
- The failure is attributable to two live deliveries -> both are penalized; splitting
  blame by guesswork is worse than penalizing both.
- "Prevented an error" cannot be proven, only inferred -> AC2 fires only on an explicit
  recorded counterfactual (the recalled workaround was applied and the previously-typed
  failure did not recur), never on the absence of a failure alone.
- The tool succeeded but produced a wrong result -> that is the reviewer's
  `verified_label`, not a FAULTLINE label; it feeds REQ-4 AC3, not this requirement.

---

# CROSS-CUTTING

### REQ-34: Task-card provenance bridge

**User Story:** As the user I want to reference a past task by the ID on its card and
have the agent recover what actually happened, across conversations.

**Verified:** ALREADY EXISTS, unexploited. `save_card_footprint` / `get_card_footprint`
(`backend/memory/card_footprint.py:37,105`) persist objective, steps, tools_used,
files_touched, and terminal outcome keyed by `card_id`, retrievable by primary key
without loading the conversation (`card_footprint.py:16-19`). `_resolve_card_identity`
(`backend/agent/agent_kernel.py:7948`) keeps `card_id` stable across every event of a
task, and `_card_context` (`:8017`) stamps `card_id` + `conversation_id` on each event.
The task-card spec explicitly deferred `@card:<id>` addressing UX
(`specs/task-card-v2-liquid-ink/requirements.md` REQ-11, "Foundation only").

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL treat a card footprint as a first-class chain-extraction source
  alongside live DER runs and recall episodes — its `steps` and `tools_used` ARE an
  ordered mediator sequence with a terminal outcome.
- AC2: THE SYSTEM SHALL record `card_id` on wormhole nodes minted during that card's
  execution, on every `aperture_decision`, and on every chain's provenance.
- AC3: WHEN the user references a card ID from a previous conversation THEN THE SYSTEM
  SHALL resolve it to its footprint and make that footprint available as recall context.
- AC4: THE SYSTEM SHALL NOT extract a chain from a footprint whose outcome is not
  `converged` — a card that failed or was abandoned is evidence, not a chain
  (consistent with REQ-19 AC4).
- AC5: THE SYSTEM SHALL keep the `@card:` addressing UX out of scope here; this
  requirement is the DATA bridge only.

**Edge Cases:**
- The referenced card_id does not exist -> the agent says so plainly; it does not
  fabricate a footprint.
- The footprint exists but its conversation was deleted -> the footprint is still
  readable; it is keyed by card_id, not by conversation (`card_footprint.py:16-19`).
- A card's footprint and its live DER trace disagree -> the DER trace wins for chain
  extraction; the disagreement is logged as an observability finding.

### REQ-35: Telemetry contract and observability

**User Story:** As the tuner I want every decision this system makes to be visible, so
that the next iteration is set by evidence rather than by argument.

**Verified:** The pattern to follow is established. `_record_tool_event`
(`backend/agent/tool_bridge.py:1605`) demonstrates BOTH the required discipline (a daemon
thread, off the critical path — `:1618-1629`) and the failure to avoid (it previously
serialized entire crawl results through FFI into SQLite). `unknown_label_counts`
(`backend/agent/tool_errors.py:224`) is the existing evidence-accumulation precedent.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL emit one `aperture_decision` record per aperture outcome carrying
  at minimum: trace_id, session_id, card_id, der_node_id, the arm used per family, the
  candidate (hyperedge_id, tier, posterior lower bound, trigger hex, claim hex), the
  action taken, and the outcome (agent_used, faultline_intersect, chain_genesis_contrib).
- AC2: THE SYSTEM SHALL scope every log line with a session or thread identifier.
- AC3: THE SYSTEM SHALL report the Tier-1a / Tier-1b / Tier-2 hit-rate split per session.
- AC4: THE SYSTEM SHALL report birth-amplitude survival — how long new nodes actually last
  without activation — so the 30-day constant is measured, not assumed (REQ-5 AC6).
- AC5: THE SYSTEM SHALL report the BUSY/NOT-USEFUL population per coordinate region
  (REQ-9 AC6).
- AC6: THE SYSTEM SHALL log every elevation rise and fall with its cause (REQ-7 AC6), and
  every chain creation, pivot, promotion, refused promotion, and graft accept/reject.
- AC7: THE SYSTEM SHALL rate-limit high-frequency events into aggregate rollups rather
  than per-event lines, and SHALL bound telemetry retention.
- AC8: THE SYSTEM SHALL measure the p95 turn-latency delta with recall enabled vs disabled
  (REQ-12 AC5).
- AC9: THE SYSTEM SHALL keep ALL instrumentation off the critical path — never inline,
  never holding a lock the generation path needs, never serializing a full result payload.

**Edge Cases:**
- Telemetry write fails -> swallowed and counted; the observed operation proceeds.
- A record would exceed a size bound -> fields are truncated with an explicit marker, and
  large payloads (full results) are referenced by id, never embedded.
- The telemetry store is unavailable at startup -> records buffer in a bounded in-memory
  ring and are dropped oldest-first, never queued unboundedly.

### REQ-36: Stage gates

**User Story:** As the architect I want a stage to be structurally unable to proceed until
its predecessor is proven, so that a plausible-but-wrong layer cannot be built upon.

**Verified:** NEW as a requirement; the failure it prevents is documented in this
codebase. `bootstrap/GOALS.md` records that the DER outer loop "currently accepts ANY
proposal that raises natural-exit rate — precisely the single-metric reward-hacking the
gate was written to prevent", and `backend/agent/outer_loop.py:27-37` documents guards
that report `live=False` when their input cannot be computed, because "conflating 'no
signal' with 'no objection' is exactly what let a three-metric gate accept on one metric
for months".

**Acceptance Criteria:**
- AC0 (G-DEP — GROUND TRUTH): THE SYSTEM SHALL NOT begin ANY stage of this spec until
  `specs/der-ground-truth/` has cleared its gate **GT-G4 (negative evidence)** and its
  determinations for the edge substrate (GROUND TRUTH REQ-5), the pin table (REQ-4), and
  the footprint writer (REQ-3) are recorded. Five of this spec's six substrates are
  currently unwritten; scoring against them would produce confident nonsense. **This gate
  subsumes what an earlier draft called G0b.**
- AC1 (G0 — CHANNEL): THE SYSTEM SHALL NOT begin Stage A scoring until a live turn has
  written a real `source_channel='recall'` episode in the locked shape (REQ-0 AC1/AC2).
  Until then every downstream measurement is synthetic. Passing G0 by enabling the legacy
  fallback SHALL NOT count — the gate is about the wormhole path producing evidence.
- AC2 (G1 — TOPOLOGY): THE SYSTEM SHALL NOT begin Stage B until the Tier-1a/1b/2 split is
  being reported from real traffic (REQ-35 AC3) and at least one hyperedge has a posterior
  moved by real outcome evidence.
- AC3 (G2 — NAMED CONSUMER): THE SYSTEM SHALL refuse, at review, any new scored quantity
  (amplitude, hub standing, elevation, hex bin, error label) that does not name the
  dispatch or planning site reading it. This gate applies to EVERY stage, always.
- AC4 (G3 — HOT PATH): THE SYSTEM SHALL NOT enable any recall path that touches
  generation until the p95 delta (REQ-12 AC5) is measured and within the stated bound.
  This gate applies to EVERY stage, always.
- AC5 (G4 — DELIVERY): THE SYSTEM SHALL NOT begin Stage C chain extraction from recall
  until at least one delivery has been attributed end-to-end (REQ-17) with
  `agent_used=true`.
- AC6 (G5 — PROOF): THE SYSTEM SHALL treat Stage C complete only when
  `TestC3SkillGenesisSql` passes UNMODIFIED and a `chain.md` exists in `data/chains/`
  produced from attributed deliveries.
- AC7 (G6 — POLICY): THE SYSTEM SHALL NOT promote an aperture arm to default on a single
  metric; promotion requires the multi-metric per-arm report (REQ-14 AC5) reviewed by the
  user (REQ-14 AC6).
- AC8: THE SYSTEM SHALL record each gate's evidence (the query, the numbers, the date) in
  the spec's task list as it is passed, so a later session can audit the claim.
- AC9 (G7 — CORPUS SIZE): THE SYSTEM SHALL NOT enable Tier-1b (REQ-2 AC6) until the
  wormhole node corpus is large enough that a neighbor-ring index measurably beats a linear
  candidate scan. THE SYSTEM SHALL derive that threshold from a measured scan-cost curve,
  not from a guessed node count, and SHALL record the measurement. Baseline at spec time:
  37 `mycelium_nodes`, 207 episodes, 201 trajectories — orders of magnitude below where the
  index pays for itself.

**Edge Cases:**
- A gate's input cannot be computed -> the gate is DEAD, not passing (the `outer_loop`
  `live` vs `passed` distinction, `backend/agent/outer_loop.py:27-37`). A dead gate blocks.
- A stage must ship partially for an unrelated reason -> the ungated part ships behind its
  kill switch (REQ-37) in the OFF position, and the gate still blocks enabling it.
- Evidence is gathered but ambiguous -> the gate does not pass on a tie; ambiguity is a
  finding to report, not an obstacle to route around.

### REQ-37: Kill switches and degraded operation

**User Story:** As the user I want to turn any part of this off and get today's behavior
back, because an experimental memory layer must never be able to hold my assistant hostage.

**Verified:** The precedent exists: `IRIS_DER_TURN_BUDGET_S`
(`backend/agent/agent_kernel.py:125`) and `IRIS_CRAWL_ARUN_TOTAL_S`
(`docs/architecture/FAULTLINE.md` §6) are existing environment-driven bounds.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide an independent switch for each of: the recall path
  (REQ-0 AC6), wormhole minting, aperture delivery, chain-guided execution
  (REQ-23 AC5), script grafts (REQ-27 AC7), and shadow evaluation (REQ-14).
- AC2: WHEN every switch is off THEN THE SYSTEM SHALL behave exactly as it does today.
- AC3: THE SYSTEM SHALL allow wormhole LEARNING to continue while aperture DELIVERY is
  off, so the topology can be built and inspected before it is trusted.
- AC4: THE SYSTEM SHALL log the switch state at startup, once, with the session
  identifier.
- AC5: IF a switch's value is unparseable THEN THE SYSTEM SHALL default to OFF and log
  the rejection.

**Edge Cases:**
- A switch is flipped mid-session -> takes effect at the next DER node boundary, never
  mid-node.
- Delivery is off but a chain was already seeded from a delivered recall -> the chain
  continues; switches gate new activity, not in-flight work.

---

## Non-Requirements (Out of Scope)

- **Replacing DER.** DER stays the execution loop; chains seed it, the aperture feeds it.
- **Replacing the dag-node-execution-model.** This builds on typed outcomes and
  outcome-driven routing; it does not replace them.
- **Mid-stream token injection.** Explicitly and permanently excluded (Decisions Locked 10).
- **Reviving the two-phase `RecallPhases` protocol as the primary recall path.** Wormhole
  replaces it (Decisions Locked 11). Keeping it as a default-off fallback is in scope;
  investing in it is not. Its EPISODE CONTRACT is preserved; its control flow is not.
- **A new relevance/search engine in the aperture.** Delivery only (REQ-11 AC2).
- **The `@card:<id>` addressing UX.** REQ-34 is the data bridge; the UX stays deferred to
  the task-card spec.
- **A visual editor or UI for authoring chains, wormholes, or landmarks.**
- **Cross-machine sharing of chains, wormholes, or landmarks.** All app-local.
- **Autonomous permission escalation.** REQ-31 AC6 forbids recall from raising a tier.
- **Hand-coded media leaf tools.** Chains compose registered nodes; the agent may graft
  script nodes (REQ-27).
- **Decomposing `agent_kernel.py`.** Tracked separately.
- **A full multi-armed bandit / Thompson sampling meta-learner.** REQ-14 delivers the
  per-arm evidence; automatic ARM selection is deferred until the evidence exists and
  REQ-36 AC7 is satisfiable. **This exclusion covers the bandit only — it does NOT
  exclude Level 3 meta-learning, which REQ-39 requires and routes through the existing
  `outer_loop.py` rather than a new mechanism.** An earlier draft of this list read as
  if it excluded meta-learning entirely; that was wrong, and it would have left every
  value in this spec scored but never re-tuned.
- **A second self-tuning mechanism.** REQ-39 AC2 forbids one; adjustments go through the
  loop that already exists.
- **Repairing the existing pheromone learning layer.** REQ-40 requires it to keep
  WORKING and measures that it does, but defects found in it belong to
  `specs/der-ground-truth/`, not here.

## Open Questions

- **Elevation thresholds.** What makes a node a Hub Landmark vs a Resonance Landmark vs
  both at once (REQ-7 vs REQ-8) is unresolved. Deliberately left to fall out of the
  REQ-35 AC5/AC6 distribution rather than being pre-defined.
- **Initial hex quantization coarseness.** Start coarse enough that Tier-1a hits occur at
  all, then let REQ-10 AC5 hysteresis move it. The starting value is a first guess, not a
  design decision.
- **The attribution window for late credit** (REQ-17 edge case). Start bounded at one DER
  run; revisit from REQ-35 data.
- **Default bounds carried from node-chains:** chain.md cap ~2KB, max chains 200, max
  variants 3 per fork, promotion N=2. Revisit from REQ-25 AC5 / REQ-35 data.
- **Whether chain matching should use the embedding service** or stay lexical. Start
  lexical (trigger + domain tags); revisit from data.
- **Whether a dominant variant auto-promotes to main chain.** Start auto with logging.
