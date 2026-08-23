# Tasks: WORMHOLE + APERTURE

**Supersedes:** `specs/node-chains/tasks.md` (merged in as Stage C)
**Requirements:** `requirements.md` · **Design:** `design.md`
**BLOCKED on:** `specs/der-ground-truth/` — see gate G-DEP below. Do not start Wave 0 here
until that spec's GT-G4 has passed.

> ### 🚦 GATE G-DEP — GROUND TRUTH *(blocks EVERY stage of this spec)*
> The 2026-08-23 audit found five of this spec's six substrates unwritten in production
> (`der_fan_traces`, `mycelium_edges`, `semantic_entries`, `mycelium_pins`, recall
> episodes), an execution ledger that calls `persist()` and writes nothing, and a physics
> failure rate of 0.5% against an episode failure rate of 27%. Scoring against that corpus
> produces posteriors that all converge to 1.0.
> **Evidence:** `specs/der-ground-truth/` GT-G4 passed; its REQ-3 (footprint writer),
> REQ-4 (pin table), REQ-5 (edge substrate) determinations recorded.
> **Record here:** `[ ] PASSED  date: ______  GT-G4 evidence: ______`

> Every task links to a REQ and carries a RIPPLE note naming what it touches or relies on.
> Waves are grouped inside STAGES. A stage may not begin until its gate has PASSED, and a
> gate that cannot be computed is DEAD, not passing — a dead gate blocks (REQ-36 AC-edge,
> `backend/agent/outer_loop.py:27-37`).
> **When a gate passes, record its evidence inline in this file** — the query, the numbers,
> the date (REQ-36 AC8). A later session must be able to audit the claim.

---

## Wave 0 — Green baseline (MANDATORY, before any implementation)

- [ ] **T0** (ALL REQs): Establish and PIN the green baseline. Run and record exact
  pass/fail BEFORE any code change:
  - `backend/agent/tests/test_recall_fixes.py` — **pre-recorded 2026-08-23: `1 failed,
    2 passed`**; `TestC3SkillGenesisSql::test_sql_matches_success_episodes` FAILS with
    "skill genesis did not fire despite 3 successful recall episodes"
    (`test_recall_fixes.py:277`). Classify: **REAL GAP → REQ-20.** Must stay red and
    UNMODIFIED until REQ-20 lands.
  - `backend/tests/test_workflow_capture.py` (REQ-19/20/30 ripple)
  - `backend/tests/test_dag_node_contract.py` + `test_dag_node_behavior.py` (the node
    substrate)
  - `backend/tests/unit/test_tool_errors.py` (17 tests — FAULTLINE, REQ-32/33 ripple)
  - `backend/tests/unit/test_search_loop_bounds.py` (15 tests — wall ledger, REQ-33 AC5)
  - Mycelium scorer/landmark suites (CT-EDGE-1 baseline)
  - Standing CDD harness `scripts/validate_der_*.py`
  - RIPPLE: classify every failure REAL GAP / STALE TEST / ALREADY FIXED /
    BLUEPRINT-DIVERGENT with file:line; `pin_add` the baseline so no later step can claim
    a regression that pre-existed.

- [ ] **T0b** (REQ-0 AC8): Correct `docs/architecture/RECALL_AS_COGNITION.md`. It documents
  four production integration points (`set_memory_interface()`, `_respond_direct()`,
  `_build_recall_infer_fn()`, `iris_gateway._handle_chat()`) — verified: the first two
  exist but never construct `RecallPhases`, the third does not exist at all, and a
  name-scoped grep finds production references nowhere. Replace the integration table with
  what is true and add the Decisions-Locked-11 note (wormhole replaces the protocol,
  inherits the episode contract). — RIPPLE: doc only; prevents the next agent from
  building on a false as-built claim.

- [ ] **T0c** (REQ-36): Add SUPERSEDED headers to `specs/node-chains/requirements.md`,
  `design.md`, `tasks.md` pointing at `specs/wormhole-aperture/` and at the REQ mapping
  table. — RIPPLE: no code; prevents two specs drifting apart.

---

# STAGE 0 — Claim the recall channel

### Wave 1 — The episode contract

- [ ] **T1** (REQ-0 AC2): Extract the recall-episode row shape into an explicit,
  documented writer that BOTH the wormhole path and the legacy `RecallPhases` path call —
  same `source_channel='recall'`, same `ops_trace` in `tool_sequence`, same
  `outcome_type` vocabulary, same `[recall:{ops_key}]` prefix
  (`backend/agent/recall_phases.py:445-480`). — RIPPLE: **CT-RECALL-EPISODE lock**;
  `backend/memory/episodic.py:258` schema is NO-CHANGE (verified — `source_channel` and
  `tool_sequence` columns already exist).

- [ ] **T2** (REQ-0 AC1/AC3/AC5): Wire the wormhole path as the recall-episode writer on a
  live turn; express a wormhole retrieval as an ops_trace entry so it is indistinguishable
  from a legacy entry to the chain layer; stamp `card_id` + `recall_trace_id`. — RIPPLE:
  `backend/agent/agent_kernel.py:2636` `_respond_direct` and `:6932` DER dispatch;
  `_card_context` (`:8017`) gains `recall_trace_id` (additive only).

- [ ] **T3** (REQ-0 AC6/AC7, REQ-37): Put `RecallPhases` behind a DEFAULT-OFF switch. It
  runs only when wormhole returns nothing, and writes through T1's shared writer. Add the
  full switch set: recall path, wormhole minting, aperture delivery, chain-guided
  execution, script grafts, shadow evaluation. Unparseable value → OFF + log. — RIPPLE:
  precedent `IRIS_DER_TURN_BUDGET_S` (`agent_kernel.py:125`). **Two rows for one turn is a
  contract violation, not a merge** — assert it.

- [ ] **T4** (REQ-35 AC1/AC2/AC9): `aperture_events` table + the off-critical-path emitter.
  Daemon thread, bounded ring buffer, size-capped fields, large payloads by reference.
  — RIPPLE: copy the discipline (and read the post-mortem) at
  `backend/agent/tool_bridge.py:1618-1629`. This lands FIRST because everything downstream
  is measured through it.

> ### 🚦 GATE G0 — CHANNEL
> **Blocks:** Stage A scoring.
> **Evidence:** a live turn wrote a real `source_channel='recall'` episode in the locked
> shape, produced by the wormhole path. Enabling the legacy fallback does NOT satisfy this.
> **Record here:** `[ ] PASSED  date: ______  query: ______  episode id: ______`

---

# STAGE A — WORMHOLE

### Wave 2 — Addressing (schema + hashing)

- [ ] **T5** (REQ-1, REQ-2, REQ-10): Additive ALTERs on `mycelium_nodes` — `hash_signature`,
  `hex_bin_id`, `hash_scheme_version`, `amplitude`, `elevation`, `dormant`, `card_id` +
  indexes. — RIPPLE: `backend/memory/db.py:195`; guard like the existing ALTER path at
  `:539`; **CT-EDGE-1: `mycelium_edges` is NOT touched.**

- [ ] **T6** (REQ-1): `wormhole/signature.py` — deterministic quantize + hash of
  (x, y, ξ, u, topic_domain, execution_domain) reading
  `caducean_trajectory.get_latest_coordinate` (`:393`). NaN/inf → unhashed + log. —
  RIPPLE: unit tests only; no I/O; determinism across processes is the assertion.

- [ ] **T7** (REQ-2 AC1): Hex bin ASSIGNMENT at write time, with a DOCUMENTED
  deterministic boundary tie-break (the same state must never land in two bins). Bins are
  minted from day one so no history is lost and REQ-10's scheme-version machinery is
  exercised. — RIPPLE: pure math; `topology.py:161` `get_nearest_origins` is the nearest
  analogue, deliberately not reused (it bins chart origins, not confounder state).

- [ ] **T7b** (REQ-2 AC3/AC6) — **DEFERRED behind gate G7**: Tier-1b six-neighbor QUERY
  path. Candidates ranked by posterior and truncated to a bounded count, **with the
  truncation logged** (no silent cap). **Do not enable at current corpus size** — 37
  `mycelium_nodes` / 207 episodes, where a linear candidate scan costs microseconds and a
  neighbor index measures as zero improvement while committing to the one quantization
  decision REQ-10 calls expensive-to-change. Fully specified, shipped when G7's scan-cost
  curve justifies it. — RIPPLE: Tier-1a (T14) and Tier-2 (T15) are sufficient without it.

- [ ] **T8** (REQ-10): Scheme version + lazy re-file on retrieval; hysteresis on scheme
  change (minimum observation count + bounded step). NO bulk pass. — RIPPLE: every read
  path through T5's columns; BT-REFILE-1.

### Wave 3 — Scoring (hyperedges, resonance, coupling)

- [ ] **T9** (REQ-4): `wormhole_hyperedges` table + `alpha`/`beta` update API + derived
  `posterior_lower_bound` and `-log(posterior)` edge cost with a finite cap. Directional:
  score only the direction travelled; an untravelled direction is ABSENT, not zero. —
  RIPPLE: new table (the existing edge table is a strict pair, `db.py:226`); **every
  downstream consumer reads the LOWER BOUND, never the mean** (design decision 3).

- [ ] **T10** (REQ-6): Coupling as a Beta prior — seed from signature overlap by SEEDING
  `observation_count` + score on edge creation, then let `EdgeScorer.record_outcome`
  (`scorer.py:91`) accumulate. NO sigmoid, NO crossover, NO `k`. — RIPPLE: **CT-EDGE-1** —
  reuse the existing update, do not add a second one.

- [ ] **T11** (REQ-5): Amplitude as a driven-damped oscillator. Drive = bounded/saturated
  |u_spike| × posterior LOWER BOUND, injected only on recalled-AND-used. Damping DERIVED
  from coupling. Failure raises damping for that hyperedge context only — it never
  subtracts amplitude. Birth energy ≈ 30 days, recorded as a MEASURED target. — RIPPLE:
  physics-aware test (equal usage + unequal coupling → the weakly-coupled node decays
  faster). This is the anti-popularity guarantee.

- [ ] **T12** (REQ-5 AC7/AC8): Dormancy through the EXISTING pruner — `DCP.prune`
  (`backend/agent/dcp.py:60`) and `EdgeScorer.apply_decay` (`scorer.py:200`). Record,
  scorecard, coupling, and signature survive; re-resonate from retained state on
  reappearance. — RIPPLE: **NO new pruner** (parent doc's explicit scoping rule); BT-DORMANT-1.

- [ ] **T13** (REQ-9): Busy/Useful as TWO readings. Busyness reuses
  `mycelium_nodes.access_count` (`db.py:203`); usefulness is the posterior lower bound.
  Per coordinate REGION (`scorer.py:145` precedent). Bands fall out of the observed
  distribution — none are pre-defined. — RIPPLE: **G2 named consumer = the aperture's
  ranking (T20).** Without that consumer this task is refused at review.

### Wave 4 — Retrieval tiers

- [ ] **T14** (REQ-2 AC2): Tier-1a exact-hash lookup; record the tier on every retrieval.
  Tier-1b is T7b, deferred behind G7 — until then a Tier-1a miss falls straight through to
  Tier-2 (T15). — RIPPLE: read-only; feeds the G1 split, which reports 1a/1b/2 with 1b at
  zero by design until G7 passes.

- [ ] **T15** (REQ-3, REQ-12): Tier-2 as a DEADLINE-BOUNDED, SINGLE-FLIGHT wrapper over
  `CoordinateNavigator.navigate_all_spaces` (`navigator.py:208`), running off the
  generation thread, holding no write lock, using a MONOTONIC clock. Overlap → DROP, never
  queue. On success, mint signature + bin (`record_path_outcome` `:251`). — RIPPLE: **this
  is the parent doc's UNRESOLVED AND BLOCKING item**; the defect shape is documented at
  `tool_bridge.py:1618-1629`. BT-HOT-1 / BT-HOT-2 are its proof.

- [ ] **T16** (REQ-7): Elevation as a continuous 0..1 quantity that RISES AND FALLS, from
  the posterior lower bound + resonance-weighted coupling. Falls ride the EXISTING
  `apply_landmark_decay` pass (`landmark.py:571`). Log every rise and fall with cause. —
  RIPPLE: `LandmarkIndex.save`/`activate`; BT-FALL-1. **A pillar that cannot fall is an
  assumption, not a measurement.**

- [ ] **T17** (REQ-8): `wormhole_hub_scores` — PER DESTINATION, keyed by destination hash.
  No aggregate column. Hub standing is a VIEW. Decay applies to the per-destination rows. —
  RIPPLE: `LandmarkIndex.add_bridge` (`:694`); **G2 named consumer = coupling seed source
  (T10 / REQ-6 AC4).**

- [ ] **T18** (REQ-35 AC3/AC4/AC5/AC6): Wormhole observability — Tier-1a/1b/2 split,
  birth-amplitude survival, BUSY/NOT-USEFUL population per region, elevation rise/fall log.
  Rate-limited rollups, bounded retention. — RIPPLE: T4's emitter; produces G1's evidence.

> ### 🚦 GATE G1 — TOPOLOGY
> **Blocks:** Stage B.
> **Evidence:** Tier-1a/1b/2 split reported from real traffic; ≥1 hyperedge posterior moved
> by real outcome evidence.
> **Record here:** `[ ] PASSED  date: ______  1a/1b/2 = __/__/__  hyperedge id: ______`

---

# STAGE B — APERTURE

### Wave 5 — The valve

- [ ] **T19** (REQ-11 AC1/AC2/AC7): `wormhole/aperture.py` — single-slot hold, claim at
  boundary only, delivery-only (no scoring of its own). — RIPPLE: `DirectorQueue.next_ready`
  (`der_loop.py:502`) and the live call site (`agent_kernel.py:6932`); **CT-APERTURE-1 is
  the single most important test in this spec** — assert zero mid-stream splices.

- [ ] **T20** (REQ-11 AC3/AC4, REQ-33 AC5): Claim path — rank by hyperedge posterior lower
  bound, DOWN-RANK BUSY/NOT-USEFUL candidates (T13's consumer), consult `is_walled`
  (`tool_errors.py:190`) before ranking a candidate whose mediator targets a walled domain.
  — RIPPLE: closes G2 for T13 and for the wall ledger; BT-TRAP-1.

- [ ] **T21** (REQ-11 AC5, REQ-35 AC1): Emit `aperture_decision` for ALL FOUR actions.
  `agent_used` is TRI-STATE — `unknown` is never coerced to `false`. — RIPPLE:
  **CT-APERTURE-2**; a silent drop is a contract break.

- [ ] **T22** (REQ-12): Degraded mode (DL-A, MANDATORY, not an arm) — cancel on deadline,
  skip, emit the FAULTLINE label, no retry inside the same DER node. Swallow unexpected
  exceptions at the boundary. — RIPPLE: every recall entry point; REQ-12 AC6.

- [ ] **T23** (REQ-15): Recall surface rendered from the schema — fixed fields, fixed order,
  explicit empty markers, size-bounded with an explicit truncation marker, carrying
  `recall_trace_id`. — RIPPLE: follows `resonance.py:256` / `landmark.py:86`
  (**CT-SURFACE-1: do not reshape those**); AC5's used/ignored signal feeds the recall
  mechanism's own scorecard.

### Wave 6 — Attribution (the actual deliverable)

- [ ] **T24** (REQ-17 AC1/AC2): Mint `recall_trace_id` per delivery; thread it through the
  surface into `_record_tool_event` — the same additive pattern as the existing
  `plan_title` threading (`tool_bridge.py:1613-1614`) — and onto the FAULTLINE outcome.
  **Keep it on the daemon thread.** — RIPPLE: **CT-FAULTLINE-1** (idempotence + extra-key
  preservation); BT-ATTR-1.

- [ ] **T25** (REQ-17 AC3/AC4/AC5): Attribution join — trace id recoverable from the tool
  event, the FAULTLINE outcome, the episode, and the chain provenance, from stored data
  alone. Unmeasured → `agent_used=unknown`. Bounded late-credit window, recorded. —
  RIPPLE: T1's episode writer; Stage C REQ-20 AC5 depends on this.

- [ ] **T26** (REQ-34): Task-card provenance bridge — read card footprints
  (`card_footprint.py:37,105`) as a chain-extraction source; stamp `card_id` on wormhole
  nodes, aperture decisions, and chain provenance; resolve a user-referenced card id to its
  footprint as recall context. Only `outcome='converged'` footprints yield chains. —
  RIPPLE: **CT-CARD-1** — `_resolve_card_identity` (`agent_kernel.py:7948`) is a lock, do
  not touch it. `@card:` addressing UX stays OUT of scope.

### Wave 7 — Policy arms

- [ ] **T27** (REQ-13): Arm registry across five families (OV / ST / T2 / CD / SC),
  config-selectable, recorded per decision. Ship defaults OV-A, ST-A, T2-A, CD-A, SC-A.
  Unknown arm id → documented default + logged rejection. Hysteresis on any cadence arm. —
  RIPPLE: DL-A is NOT an arm (REQ-13 AC4) — there is no alternative to not hanging.

- [ ] **T28** (REQ-16): SC guard as an arm family. A guard rejection emits
  `recall_semantic_mismatch` and **does NOT increment beta** — the shortcut was never
  tried. SC-C reuses REQ-28 context signatures rather than defining a second notion of
  context. — RIPPLE: BT-GUARD-1; couples to T39 (context signatures).

- [ ] **T29** (REQ-14): Shadow evaluation — compute what inactive arms WOULD have done,
  record alongside, zero execution effect, same deadline discipline, sampled if expensive
  **with the sampling rate recorded** so rates stay comparable. Per-arm report:
  `agent_used`, `faultline_intersect=prevented_error`, `chain_genesis_contrib`. —
  RIPPLE: **no auto-promotion** (REQ-14 AC6 / G6). The anti-reward-hacking test lives here.

> ### 🚦 GATE G3 — HOT PATH *(applies to every stage; verified here first)*
> **Evidence:** BT-HOT-1 p95 delta with recall enabled vs disabled, measured under real
> injected store latency (not a mock that cannot fail), within the stated bound.
> **Record here:** `[ ] PASSED  date: ______  p95 on/off = ____ / ____ ms  bound: ____`

> ### 🚦 GATE G4 — DELIVERY
> **Blocks:** Stage C recall extraction (REQ-20).
> **Evidence:** ≥1 delivery attributed end-to-end with `agent_used=true`.
> **Record here:** `[ ] PASSED  date: ______  recall_trace_id: ______`

---

# STAGE C — NODE CHAINS

### Wave 8 — Foundation

- [ ] **T30** (REQ-18): `NodeChain` / `PivotEvent` / `ChainVariant` dataclasses in
  `backend/agent/node_chain.py` (NEW — verified absent). Provenance carries `card_id`,
  `recall_trace_ids[]`, `landmark_refs[]`. — RIPPLE: consumed by extraction, runner,
  projection; CT-3/CT-4 pin the shapes.

- [ ] **T31** (REQ-18): `node_chains`, `pivot_events`, `chain_variants` tables following the
  `mycelium_traversals` pattern (`backend/memory/db.py:229`); idempotent
  `CREATE TABLE IF NOT EXISTS`, no migration. `pivot_events` carries `recall_trace_id`. —
  RIPPLE: app memory schema only.

- [ ] **T32** (REQ-18, REQ-30 AC2): Order-sensitive sequence-hash dedupe helper. — RIPPLE:
  used by BOTH extraction paths (T33, T34); replaces name-Jaccard.

### Wave 9 — Extraction

- [ ] **T33** (REQ-19): Live-run extraction from node records / fan traces; wire into the
  `_maybe_trigger_skill_creation` call site (`agent_kernel.py:7021`), replacing the
  tool-name heuristic. — RIPPLE: `workflow_capture.py` superseded;
  `caducean_trajectory.record_fan_trace` (`:293`) is the read source.

- [ ] **T34** (REQ-20): Recall-episode extraction — group `source_channel='recall'` AND
  `outcome_type='success'` by op pattern, count ≥ 3 → chain. Fix the early-return on empty
  tool_sequence (`agent_kernel.py:1561`) that is the direct cause of C3 being red. Count an
  episode ONLY when attribution is established; log the excluded count. Dedupe by
  `recall_trace_id` — three deliveries, not three rows. — RIPPLE: **the C3 test MUST pass
  UNMODIFIED — same assertions, same inputs, same 3-episode load** (`test_recall_fixes.py:253`).
  `recall_phases.py` control flow is NO-CHANGE.

- [ ] **T35** (REQ-19, REQ-20, REQ-30): Refactor `workflow_capture.py` — keep
  `register_verified_skill` shape for CT-2 backward compat; remove `MIN_DISTINCT_TOOLS`
  (`:29`); replace `sequence_similarity` (`:52`) with T32's order-sensitive hash; validate
  against `tool_registry.resolve_tool` (`:99`). — RIPPLE:
  `backend/tests/test_workflow_capture.py` assertions preserved where behavior is
  preserved; `auto_research.py` consumer.

### Wave 10 — Pivots and promotion

- [ ] **T36** (REQ-21): `record_pivot(...)` reading u/ξ from Caducean, writing
  `pivot_events` with topic/execution domain tags and `recall_trace_id` when a recall was
  live. — RIPPLE: `der_loop.py` NodeRecord finalize site; CT-4.

- [ ] **T37** (REQ-22): Promotion — same fork point succeeds N times (default 2) AND RL
  confirms improvement → `chain_variants` row + regenerate chain.md. — RIPPLE:
  `mycelium_landmark_merges` pattern; **physics-aware test: neutral RL → NO promotion.**

- [ ] **T38** (REQ-22 AC3/AC5): Variant selection at execution; bound variants per fork
  (default 3); archive the weakest on overflow. — RIPPLE: chain runner (T40).

### Wave 11 — Execution, projection, lifecycle

- [ ] **T39** (REQ-28): Context signatures on every node (domain, artifact contract, intent
  keywords); recorded on chain nodes at capture; fit validation at replay — a mismatch is a
  PIVOT, never a wrong-tool fire; semantic similarity index for selection and graft
  near-duplicate refusal; selection rationale recorded. Exposed to the aperture's SC-C arm
  (T28). — RIPPLE: `tool_registry.py`; `der_loop.py` replay path; CT-7.

- [ ] **T40** (REQ-23): Chain-seeded `DirectorQueue` — every chain node still runs through
  NodeOutcome + routing + fold-back. Disable switch (REQ-23 AC5). — RIPPLE:
  `der_loop.py:243`; **chain nodes are NOT exempt from pivot mechanics.**

- [ ] **T41** (REQ-24, REQ-25): `chain.md` generation, storage, and linking — minimal
  projection to `data/chains/<chain_id>.md` (NEW directory), size-bounded, regenerated on
  change; frontmatter `chain_id` is the LINK, `chain_md_hash` is a staleness DETECTOR only;
  register as a pin (`pin_type='chain_md'`) with `ref_status` alive/stale **into the table
  `specs/der-ground-truth/` REQ-4 determined authoritative — NOT `mycelium_pins` by
  assumption** (0 rows in production, while 354 orphaned links exist). — RIPPLE: registering
  into the empty table would make every chain unfindable; CT-5.

- [ ] **T41b** (REQ-38): Chain specificity — score how much each chain constrains the next
  run beyond free planning, derived from argument schemas, context signatures (T39), and
  fork points, NOT from mediator-name sequence. Record in chain stats; report the
  distribution. Low specificity is an ARCHIVE-first signal (T42) — its named consumer under
  G2. **Never blocks chain creation**: a low-specificity chain is recorded and allowed to
  decay, because refusing to create it would hide the measurement. — RIPPLE: **AC6's
  aggregate — what fraction of chains constrain more than free planning would — is the
  honest test of whether Node Chains earns its complexity, and it must be reportable before
  Stage C is called successful.**

- [ ] **T42** (REQ-25): Lifecycle bounds — max chains (default 200), archive weakest
  (confidence × usage) on overflow DEFERRED to a maintenance pass, merge near-duplicates by
  prefix + outcome. Never delete silently; never archive a chain referenced by an active
  PivotEvent. — RIPPLE: landmark-merge pattern; REQ-25 AC5 stats.

- [ ] **T43** (REQ-31): Chain-level permission resolution — tier = MAX of node tiers;
  chain-as-unit approval; approved tier recorded; re-checked on tool evolution.
  **A delivered recall can NEVER raise the effective tier.** — RIPPLE: **CT-PERM-1**;
  `permissions.py`; `der_loop.py` execution gate.

> ### 🚦 GATE G5 — PROOF
> **Blocks:** Stage C completion (and any claim that this spec works).
> **Evidence:** `TestC3SkillGenesisSql` GREEN and UNMODIFIED + a `chain.md` in
> `data/chains/` produced from attributed deliveries.
> **Record here:** `[ ] PASSED  date: ______  chain.md path: ______  test output: ______`

---

# STAGE D — FAULTLINE integration

### Wave 12 — Bidirectional loop

- [ ] **T44** (REQ-32): Register the five recall labels through the EXISTING
  `register_error_label` API (`tool_errors.py:92`) — a DATA edit, never a loop rewrite:
  `recall_timeout`, `recall_store_locked`, `aperture_expired`, `recall_candidate_stale`,
  `recall_semantic_mismatch`. **Name each label's reading dispatch site** (G2). — RIPPLE:
  CT-FAULTLINE-2 — an invalid registration is refused, not coerced (`:106-108`).

- [ ] **T45** (REQ-33 AC1/AC2/AC3): FAULTLINE → hyperedge posterior. A `retryable:no`
  failure under a live trace id → beta++. A recorded counterfactual (recalled workaround
  applied, previously-typed failure did not recur) → alpha++. `faultline_intersect`
  recorded on every decision. **AC2 fires ONLY on an explicit counterfactual, never on the
  mere absence of a failure.** — RIPPLE: BT-POISON-1 (both directions, one test).

- [ ] **T46** (REQ-33 AC4): Guard rejections do not increment beta — wire the exception
  through from T28. — RIPPLE: BT-GUARD-1.

---

# STAGE E — Grafts and evolution

### Wave 13 — Grafts

- [ ] **T47** (REQ-26): Chain grafts — verified chain → composite `NodeSpec`
  (`composite_of`, `origin='chain_graft'`); self-test BEFORE acceptance, a failure REJECTS
  without touching the registry; nestable; synced on chain change. No user approval needed
  (composition of already-approved nodes). — RIPPLE: `tool_registry.register_node`
  duplicate guard; `self_test_skill` (`workflow_capture.py:85`) is the structural precedent.

- [ ] **T48** (REQ-27): Script grafts — new `executor="script"` on `ToolSpec`
  (`tool_registry.py:58` has no script type today) + `script_sandbox.py`: subprocess,
  timeout, no shell expansion, bounded args, no network by default. `read_only` default;
  explicit user approval to escalate. Structural self-test before first use. Disable switch
  (composition-only mode). — RIPPLE: `tool_bridge.py` dispatch; `permissions.py` tiers.

- [ ] **T49** (REQ-30 AC4): Artifact CONSUME contract on `NodeSpec` (`_consume` map beside
  the existing `_produce`, `tool_registry.py:183`); validate compatibility at COMPOSITION
  time, before execution. — RIPPLE: `der_loop.py` composition check.

- [ ] **T50** (REQ-27, UC-2): Self-created MCP server pattern — a script graft that speaks
  JSON-RPC, runtime registration into `mycelium_mcp_registry` with a trust level and a
  network approval path. — RIPPLE: `tool_registry.py` MCP executor path; `script_sandbox.py`.

### Wave 14 — Evolution

- [ ] **T51** (REQ-29): Tool version / signature hash on chain nodes and fan traces
  (`caducean_trajectory.py:293`); signature change → flag referencing chains stale +
  revalidate (adapted / re-captured / archived); improvement → confidence bump as RL
  reinforcement; applies to grafts. Storms batch to a maintenance pass. — RIPPLE:
  `tool_evolution.py` (NEW); CT-8.

- [ ] **T52** (REQ-29 AC7): A landmark falling below elevation (T16) flags chains that
  reference it (`landmark_refs[]`) on the SAME revalidation path as a tool change. — RIPPLE:
  couples Stage A back into Stage C; this is the reason `landmark_refs[]` exists on the
  chain record.

---

# STAGE F — Verification

### Wave 15 — Tests and harness

- [ ] **T53**: Contract tests — CT-APERTURE-1/2, CT-RECALL-EPISODE, CT-EDGE-1,
  CT-FAULTLINE-1/2, CT-CARD-1, CT-SURFACE-1, CT-PERM-1, CT-1, CT-2, CT-3/4/5, CT-7/8/9. —
  RIPPLE: `backend/tests/contract/`.

- [ ] **T54**: Behavioral tests — BT-HOT-1/2, BT-ATTR-1, BT-FALL-1, BT-TRAP-1, BT-POISON-1,
  BT-GUARD-1, BT-C3, BT-CHAIN-1, BT-DORMANT-1, BT-REFILE-1, BT-6/7. — RIPPLE:
  `backend/tests/behavioral/`; BT-HOT-1 uses REAL injected latency, never a mock that
  cannot fail.

- [ ] **T55**: Physics-aware tests — oscillating |u| fires a fill / converged does not;
  neutral RL refuses promotion; a large spike is capped AND the cap firing is logged; equal
  usage + unequal coupling → the weakly-coupled node decays faster. — RIPPLE: the
  anti-popularity guarantee is asserted directly, not inferred.

- [ ] **T56**: Anti-reward-hacking tests — an arm that maximizes `agent_used` by injecting
  on every boundary is NOT promoted (its other metrics fall); a gate whose input is
  uncomputable BLOCKS rather than passes; every coverage cap LOGS what it dropped. —
  RIPPLE: this is the load-bearing half of the scoring principle
  (`backend/agent/outer_loop.py:27-37`; `bootstrap/GOALS.md`).

- [ ] **T57**: Extend the standing CDD harness (`scripts/validate_der_*.py`) to replay
  recorded trajectories and assert on EVERY run: no mid-stream injection, every aperture
  decision emitted, attribution recoverable end-to-end, chains + pivots emerge, elevation
  rises AND falls. — RIPPLE: runs on every validation.

- [ ] **T58** (REQ-35): Full observability sweep — every chain creation, pivot,
  promotion/refusal, graft accept/reject logged and session-scoped; rate-limited rollups;
  bounded retention; nothing inline. — RIPPLE: T4's emitter.

- [ ] **T68** (REQ-46): Cause-based retrieval keyed on the FAULTLINE dimension triple
  `(retryable, blame, info_state)`, with nearest-neighbour lookup inside that 3x3x3
  lattice, and the triple folded into hyperedge region scoping. - RIPPLE:
  **FAULTLINE section 5 names THIS SPEC as the consumer** ("the fixed-field recall shape
  Wormhole/memoryRegistry expect") and the spec had no cause axis at all. Layer 1 is a
  declared INVARIANT - address by dimensions, never re-model them. **At current corpus
  size a closed 27-cell lattice is a far better exact-match key than the continuous 4D
  state** (which is why REQ-2 AC6 defers hex querying); record which axis produced each
  candidate so their relative value is measurable.

- [ ] **T69** (REQ-47): Wire a delivered recall into the reviewer's branch decision
  (retry / diversify / ask / report) and record which branch was taken. - RIPPLE:
  **this is what the whole thing is FOR.** FAULTLINE section 1: an uninformed reviewer
  "does the only thing it can: re-plan. Same query -> same results -> same wall" - the
  14-minute blind-retry loop. A delivery that never changes a branch is decoration,
  however good its posterior. Add NO recall-specific branches (CT-1). Treat FAULTLINE as
  GROWING: never block on its open roadmap, and raise improvements there rather than
  building a parallel classifier here.

- [ ] **T65** (REQ-13 AC1/AC5b): BC backing-store arm family - BC-A (WAL + single-flight,
  default) and BC-B (Tier-2 reads an in-memory topology SNAPSHOT refreshed at safe
  boundaries). Snapshot age recorded on every candidate served from it. - RIPPLE: the
  spec had HARD-CODED BC-A's single-flight rule (REQ-3 AC5) as settled, which is the
  "refuse to fix the value, score it instead" violation the governing principle warns
  about. Six arm families now, not five.

- [ ] **T66** (REQ-44): Minimum-evidence gate + high-risk context definition. A
  zero-evidence hyperedge must not reach a `permission_tier` above `read_only` or a step
  with a TERMINAL failure reason on its first appearance. Emit `new_candidate_trial`;
  record withheld deliveries as withheld, never as absent. - RIPPLE: **today nothing
  stops a brand-new candidate being delivered into a destructive-tier step.** Unknown
  tier counts as high-risk.

- [ ] **T67** (REQ-45): Contract-test the stage boundary - the aperture module imports no
  scorer and writes no score column. - RIPPLE: **merging the two docs dissolved the
  boundary that Mailbox section 7 lock 5 was protecting.** With both stages in one file
  nothing structural stops a delivery change editing Stage A's math.

- [ ] **T62** (REQ-41): Model RECALL as a node STATE parallel to SPLIT, entered from
  RUNNING on the SAME trigger SPLIT already uses (no confident prior on the
  Treatment->Mediator edge), reusing `U_SPLIT` (`der_constants.py:233`) rather than a
  second threshold. Posterior + resonance update happens on EXIT, then RUNNING resumes
  with the updated 4D state. - RIPPLE: **this is parent doc section 1 and the spec had
  captured NONE of it** - every "split" here meant the tier hit-rate. A new threshold
  would be the "new subsystem in disguise" section 0 forbids. Still bounded and off the
  critical path (REQ-12): a node state is not synchronous work.

- [ ] **T63** (REQ-42): `activation_log` per node (timestamped list or decayed count),
  bounded, truncation logged. **NO `window_size`, no configured lookback, anywhere.**
  Recency derives from the `last_accessed` - `created_at` gap on the existing
  `mycelium_nodes` columns. - RIPPLE: DEPENDS on GROUND TRUTH Finding 11 - nothing
  currently writes `access_count`/`last_accessed`, so the recency term is meaningless
  until that is fixed and must report un-computable rather than be silently used.

- [ ] **T64** (REQ-43): Vocabulary lock - the scoring act is POLLING/VOTING in code,
  comments and telemetry; Treatment/Mediator/Outcome/Confounder stay causal. - RIPPLE:
  parent doc Q2a; cheap now, expensive to unpick once the terms are in code.

- [ ] **T60** (REQ-39): Name and wire the Level 3 adjustment path for every value this
  spec declines to hardcode - match threshold, coupling blend, elevation, quantization,
  arm weights - through the EXISTING `backend/agent/outer_loop.py`, never a second
  self-tuning mechanism. Subject each to that loop's compound gate INCLUDING the
  `live` vs `passed` distinction. - RIPPLE: **`outer_loop.py` currently accepts any
  proposal that raises natural-exit rate (`bootstrap/GOALS.md`); pointing it at wormhole
  values without fixing that would propagate the reward-hack into the memory topology.**
  Fix the single-metric gate FIRST or do not wire it.

- [ ] **T61** (REQ-40): Prove the existing pheromone layer still works as the fallback
  after every stage - measure its write/score rate before and after, and treat a drop as
  a regression in THIS spec. Keep its writes off every new component (AC3) so a defect
  here cannot take the old path down. Verify the MCM inheritance path stays readable. -
  RIPPLE: `graph_edges` is alive (MCM 7,638 / APP 997,262, weighted, ~10-15% scored);
  `mycelium_*` is starved. "Fall back to today" means falling back to the pheromone
  layer, so its health is a PRECONDITION, not an afterthought.

- [ ] **T59** (REQ-14 AC5/AC6/AC7, G6): Produce the per-arm multi-metric report — **with
  the sample size stated beside every rate**, so an underpowered comparison is visibly
  underpowered — and review it WITH the user before any arm becomes a default.
  **No bandit, no Thompson sampling, no automatic weighting at this traffic** (~200 DER
  runs in three months cannot separate five arm families). Record the traffic volume that
  WOULD justify automatic selection, so the deferral has an exit condition. — RIPPLE:
  instrumented judgement, not statistical selection; a human gate on purpose.

> ### 🚦 GATE G7 — CORPUS SIZE
> **Blocks:** T7b (Tier-1b hex neighbor ring).
> **Evidence:** measured scan-cost curve showing the neighbor index beats a linear
> candidate scan. Baseline 2026-08-23: 37 `mycelium_nodes`, 207 episodes, 201 trajectories.
> **Record here:** `[ ] PASSED  date: ______  nodes: ____  scan vs index: ____ / ____ µs`

> ### 🚦 GATE G6 — POLICY
> **Blocks:** promoting any aperture arm to default.
> **Evidence:** multi-metric per-arm report (agent_used, faultline_intersect,
> chain_genesis_contrib) reviewed by the user. A single metric is never sufficient.
> **Record here:** `[ ] PASSED  date: ______  arms promoted: ______  report: ______`

> ### 🚦 GATE G2 — NAMED CONSUMER *(standing, every stage, every review)*
> No new scored quantity ships without naming the dispatch/planning site that READS it.
> Current bindings: amplitude → damping + dormancy (T11/T12) · busy/useful → aperture
> ranking (T20) · hub standing → coupling seed (T10) · elevation → path admission (T16) +
> chain revalidation (T52) · hex bin → Tier-1b (T14) · recall labels → degraded mode (T22)
> + ranking (T20).

---

## Dependency / parallelization notes

- **T0 / T0b / T0c are mandatory and land first.** No implementation task may claim a
  regression that pre-existed the pinned baseline.
- **Stage 0 (T1–T4) blocks everything.** Without a real recall episode from the wormhole
  path, every downstream measurement is synthetic. T4 (telemetry) lands FIRST inside the
  stage because every later gate is read through it.
- **Wave 2 (T5–T8) must land before Waves 3 and 4** — the columns are prerequisites.
  T6 and T7 are pure math and can be written in parallel with T5's schema work.
- **Wave 3 (T9–T13) is largely parallel.** T9 (hyperedges) blocks T11 (drive reads the
  posterior); T10, T12, T13 are independent of each other.
- **Wave 4: T14 depends on T5/T7; T15 depends on nothing in Wave 3** and can start early —
  it is the highest-risk task in the spec and benefits from the longest runway.
  T16 depends on T9; T17 depends on T9 and feeds back into T10.
- **Stage B (T19–T29) is gated on G1, but T19/T22/T23 are structurally independent** of
  Stage A scoring and can be built and contract-tested against a stubbed candidate source.
- **T24/T25 (attribution) are the spec's actual deliverable.** If everything else lands and
  these do not, the system retrieves and delivers and learns nothing.
- **Stage C Wave 8 (T30–T32) depends only on Stage 0** and can run in parallel with
  Stage A. T33 (live extraction) needs no recall at all and can land early; **T34 (recall
  extraction) is gated on G4.**
- **Stage E (T47–T52) depends on Wave 8 + T39**; T48 (script sandbox) is independent of
  the chain layer and can run in parallel.
- **Stage F is continuous, not terminal.** Contract tests land WITH the task they pin, not
  at the end. T57 (harness) extends as each stage lands.

### NO-CHANGE-verified areas (contract test only, no code)

`recall_phases.py:433-480` row shape · `mycelium/store.py:546` traversal recording ·
`mycelium/scorer.py:91,200` posterior + decay · `mycelium/landmark.py:571` decay pass ·
`dcp.py:60` pruner · `caducean_trajectory.py:393` coordinate read ·
`tool_errors.py:92,178,190,309` registry + wall ledger + normalizer ·
`card_footprint.py:37,105` footprint accessors · `tool_bridge.py:237` unfiltered tool list ·
`pin_store.py` + `mycelium_pins`/`pin_links` · `outer_loop.py` (deliberately not extended) ·
frontend `TaskListCard.tsx` / `useTaskProgress.ts` (no new stream event).

### CONTRACT LOCK areas (pin, never modify)

`nodes/outcome.py` `Reason` (CT-1) · `named_skills` shape (CT-2) · the C3 test itself ·
`mycelium_edges` posterior semantics (CT-EDGE-1) · `normalize_failure` idempotence
(CT-FAULTLINE-1) · `_resolve_card_identity` card stability (CT-CARD-1) ·
`ToolSpec.permission_tier` vocabulary (CT-PERM-1) · `resonance.format_context` /
`Landmark.to_context_string` (CT-SURFACE-1) · the recall episode row shape
(CT-RECALL-EPISODE) · no-mid-stream-injection (CT-APERTURE-1).
