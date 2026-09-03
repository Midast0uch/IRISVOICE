# MorphoHDL × IRISVOICE / Caducean Engine — Continuation Brief

**Purpose of this document:** Context handoff so another agent (or the same agent in a new
session) can continue this line of investigation without re-deriving everything from scratch.
This is a design-exploration thread, not a finished spec — treat conclusions below as working
hypotheses, not settled architecture.

---

## 1. Background — what this project is

**IRISVOICE** is Midas's AI-powered application, and the primary implementation environment for
a broader research effort around **physics-based agent loop governance**. The centerpiece is the
**Caducean Engine** — an original system that replaces traditional step-count agent-loop
termination with dynamics governed by a **Duffing oscillator equation**.

Core physics:
- Tracks a 4D state vector **Σ = (x, y, ξ, u)**
- Restoring force **F(u) = 2u − 2u³**, with stable attractors at **u\* = ±1**
- Validated results (Gates 1–5 / D-series / C-series experimental program):
  - Limit cycle R² = 0.9986
  - Twrap prediction at 0.0% error across `c_eff` 1.000–3.000
  - 22.75× efficiency improvement at long-tier vs. counter policy
  - 100% natural exit rate in real LLM trials
- Gates 4 and 5 remain open as of the most recent experimental summary.

Architectural expansions already built on top of the physics core:
- **Governor as Branching Authority** — physics-signal-driven branching via `DirectionSignal`,
  replacing LLM JSON plan-driven branching
- **Cross-Session State Persistence** — warm-starting Σ across sessions
- **Sub-Loop** — nested temporary Caducean sessions that collapse back into the parent as a
  single `COMPRESS` observation
- **Caducean Mixture of Experts (CMoE)** — 4-phase design (environment verification → local
  model hive → multi-model hive with emergent role assignment → swarm execution with
  `Q_swarm` convergence)

Key domain terms in active use: Duffing potential, winding number, `c_eff`, quorum sensing,
`TOPO_VIOLATION`, NBL encoding, pheromone trail, topology primitives
(`CORE`/`ACQUISITION`/`EXPLORATION`/`EVOLUTION`/`ORBIT`), `caducean_update()`, the `(u, ξ)`
phase-plane validation protocol (§11.1), the `speak`/`show` architectural split, `DOCUMENT_RENDER`
trust flag, `DocumentDataStore` keyed by `document_id`, and the DER loop.

A recurring theme in this project: Midas places explicit value on scientific integrity —
notably, correcting a phase-unwrapping postprocessor bug that had falsely suggested a regime
boundary at winding numbers (3,3), rather than fitting theory to the flawed data.

---

## 2. Repository

- **Repo:** https://github.com/Midast0uch/IRISVOICE
- Branches referenced in this thread:
  - `feat/agent-multi-step-tool-execution`
  - `feat/xurorb-spiral-dissolve-winner` (stated by Midas to be functionally the same content as
    the above, just a newer/updated branch)
- Note: at time of this conversation, neither branch URL was reachable via web search/fetch
  (private repo indexing lag, or search-tool visibility limits) — analysis so far is based
  entirely on **files Midas uploaded directly**, not a live clone of the repo. A future agent
  with repo access should verify file paths/imports against the actual tree.

---

## 3. Files reviewed so far (uploaded directly, not fetched from GitHub)

### Mycelium memory layer (`backend/memory/mycelium/` — inferred path)
| File | Role |
|---|---|
| `spaces.py` | Root dependency module. Defines the **7 coordinate spaces** (conduct, domain, style, chrono, context, capability, toolpath), domain-ID mapping, decay rate constants, scoring thresholds (`PRUNE_THRESHOLD`, `HIGHWAY_THRESHOLD`, `CONDENSE_THRESHOLD`, `SPLIT_THRESHOLD`, etc.), and `tool_id()` hashing helper. |
| `topology.py` | 3D landmark geometry layer. Builds local charts (X=domain proximity, Y=operational similarity, Z=temporal convergence) around "crystallized" landmarks once `activation_count >= CHART_ACTIVATION_THRESHOLD (12)`. Produces 6 behavioral primitives: CORE, EXPLORATION, TRANSFER, ACQUISITION, EVOLUTION, ORBIT. Contains `ChartRegistry`, `AxisCalculator`, trajectory EWMA tracking, and greedy single-linkage clustering (`_simple_cluster`). |
| `navigator.py` | `CoordinateNavigator` — keyword-matched entry-node selection, hop-limited traversal (`max_hops=4`) along highest-scored outbound edges (`min_score=0.2`). `SessionRegistry` prevents duplicate node traversal within a session. |
| `scorer.py` | `EdgeScorer` — pheromone-style reinforcement. Outcome deltas: hit +0.05, partial +0.02, miss −0.08, highway bonus +0.01 on crossing 0.85 threshold. `MapManager` condenses near-duplicate nodes and splits high-variance nodes. |
| `interpreter.py` | `ResolutionEncoder` (Tier 3 failure/resolution headers), `CoordinateInterpreter` (axis-conflict arbitration cascade: confidence → recency → pheromone strength → average), `BehavioralPredictor` (top-3 next-tool prediction from pheromone edges). |
| `nbl.py` | **Neutral Bayesian Logic** — builds a ≤40-token compact coordinate-state string (`MYCELIUM: context:[...]@gateN | toolpath:[...] | confidence:X`) from the DB. `build_mito_tag()` wraps it in a `<MCM_MITO>` XML tag (≤300 tokens, cacheable base template) that agents treat as "internal biology," not an external tool call. |
| `semantic.py` | `SemanticStore` — versioned user-model entries (preferences, cognitive model, tool proficiency, domain knowledge, named skills) for delta-sync across devices ("Torus-ready"). Fires `ingest_statement()` into Mycelium on every update. |
| `bootstrap_seed.py` | Seeds the runtime Mycelium DB with permanent build landmarks from `bootstrap/coordinates.db` on first launch. |
| `__init__.py` | Three-tier memory architecture entry point (Working / Episodic / Semantic). Single access boundary for all memory operations. |
| `extractor.py`, `landmark.py`, `profile.py`, `resonance.py`, `store.py`, `db.py`, `episodic.py`, `pin_store.py`, `kyudo.py`, `interface.py` | Uploaded but **not yet reviewed in depth**. `kyudo.py` and `interface.py` are the largest files (40KB/44KB) and are suspected to hold the main orchestration/channel-profile logic — flagged as the next place to dig for "always-optimizing" loop behavior. |

### Agent execution core (`backend/agent/` — inferred path)
| File | Role |
|---|---|
| `der_loop.py` | **DER = Director · Explorer · Reviewer.** The Reviewer is explicitly designed as "a membrane, not a gate" — never hard-blocks, falls back to PASS. `DirectorQueue` manages `QueueItem`s with dependency chains, veto counts, and dynamic `ExecutionMode`. |
| `der_constants.py` | `ExecutionMode` enum: **QUICK** (single tool call) → **AGENTIC** (multi-step loop w/ review, default) → **FULL** (multi-cycle exploration/research/synthesis). Escalates/de-escalates dynamically. Token budgets per mode (15k/30k/60k). Safety limits: `DER_EMERGENCY_STOP=200`, `DER_MAX_VETO_PER_ITEM=2`, `DER_MAX_GRAFTS=3`, `DER_MAX_CYCLES=40`. |
| `caducean_trajectory.py` | `CaduceanTrajectoryRecorder` — persists every DER step as a 4D state transition `(x, y, ξ, u, action, outcome, eml_after, recommendation)` to SQLite (WAL mode). Feeds the `TrajectoryController`. Also stores `get_latest_coordinate()` used to place documents on the "Immortus chain" at the agent's actual reasoning-state position. |
| `mcm.py` | **Model Context Memory** — budget-triggered compression (fires at 70% of context budget). Builds an NBL string as the *primary* compression output (the "single biggest token saving in the system," per its own docstring), saves a checkpoint, and on recall runs a fallback ladder: NBL checkpoint → episodic similarity → file-name match. `inject_recovery()` collapses a bloated context down to ~200 tokens. |
| `agent_kernel.py` | `AgentKernel` — central orchestrator for a dual-LLM system (large reasoning model + small execution model), with `TaskContext` carrying state through planning → execution → synthesis. Very large file (7000+ lines); only the top ~150 lines reviewed so far. |
| `memory.py` | Uploaded but not yet reviewed. |

---

## 4. What MorphoHDL is (for reference)

MorphoHDL (Alexander Mordvintsev / Paradigms of Intelligence) is a minimalist HDL for **growing**
combinational (feedforward, stateless, acyclic) boolean circuits via recursive cell division.

- A **cell** is a rewrite rule: given a bus of a certain width, it either (a) splits the bus and
  recursively hands smaller buses to child cells, or (b) hits a **fallback** condition (bus too
  small / out of bounds) and terminates with a base-case circuit component.
- Circuit topology is never hand-specified — it **emerges** from repeated application of the same
  local rule (e.g. a ripple-carry adder and a Brent-Kung parallel-prefix adder can come from
  nearly the same cell definition with different splitting logic).
- Primitives: `SPLIT`, `CAT`, `HSLICE`/`LSLICE`, LUTs for gates (`Xor3`, `Maj3`, etc.)
- Reference: https://paradigms-of-intelligence.github.io/morpho/

Critical property: **MorphoHDL cells are stateless and history-independent.** Same input always
regrows the same topology. This is the opposite of the Caducean Engine's core design (which is
explicitly stateful — Σ evolves, decisions depend on accumulated trajectory history).

---

## 5. Analysis so far — where the analogy holds and where it breaks

### Holds (real structural parallels already present in the codebase)
1. **Growth-condition-triggered differentiation.** `topology.py`'s `CHART_ACTIVATION_THRESHOLD`
   (a landmark becomes a "chart origin" once `activation_count >= 12`) is structurally the same
   pattern as MorphoHDL's fallback trigger (recursion terminates once a local condition — bus
   width — crosses a threshold).
2. **Condense/expand on variance.** `scorer.py`'s `MapManager` (condense near-duplicate nodes,
   split high-variance nodes) mirrors MorphoHDL's `CONDENSE`/expand-on-demand behavior.
3. **Collapse-to-single-signal.** The **Sub-Loop** (nested Caducean sessions collapsing back to
   parent as one `COMPRESS` observation) and **MCM's `compress()`** (folding a whole bloated
   context into a ≤40-token NBL string) both mirror MorphoHDL's cell finishing and folding its
   result back up to its parent as a single wire.
4. **Coarse-grained "is this too big to do directly" decision already exists**: DER's
   `ExecutionMode` (QUICK/AGENTIC/FULL) is a global, once-per-task version of the same question
   MorphoHDL cells ask locally and repeatedly.

### Breaks (do not import wholesale)
- MorphoHDL is **combinational only** — no state, no feedback, no cycles. The Caducean Engine's
  entire differentiator is a **stateful, feedback-driven dynamical system**. Grafting MorphoHDL's
  pure-rewrite-rule model onto tool execution risks quietly flattening the state-dependent,
  path-history behavior that makes the physics governance layer valuable in the first place.
- Don't try to make the "split or execute" decision a pure/stateless function the way MorphoHDL's
  is. Let it use `u`/`ξ` on purpose — that's the upgrade over MorphoHDL, not a violation of it.

### Working hypothesis proposed for next steps
Reframe `QueueItem` creation in `der_loop.py` as a **repeating local rule** instead of a one-time
plan: each step asks "is this atomic, or still a bundle?" — answered using the live `u` value
from `CaduceanTrajectoryRecorder` (high `|u|`, near an attractor → confident/converged → treat as
atomic and execute; `u` near 0, still oscillating → uncertain → split into child steps via the
existing Sub-Loop mechanism). This would let execution-tree *shape* emerge from physics state
rather than being fixed by the QUICK/AGENTIC/FULL mode chosen up front — the concrete link between
"growing circuits" and "always-optimizing agent loops" that motivated this whole thread.

**Not yet done:** no code changes proposed or written. No verification that `u`/`ξ` are actually
accessible at the point `QueueItem`s are constructed in `der_loop.py`. `kyudo.py`, `interface.py`,
`memory.py`, and the bulk of `agent_kernel.py` (7000+ lines, only ~150 lines read) are unreviewed
and may already contain relevant logic that changes this picture.

---

## 6. Audit findings — Immortus subsystem + `interpreter.py` (answers to §5's open items)

These files were reviewed after the design doc in Section 5 was written, and they directly
answer (and revise) two of that doc's open audit items. Files reviewed:
`backend/agent/immortus/__init__.py`, `brain.py`, `constants.py`, `decisions.py`, `route.py`,
`router.py`, `session.py`, `temporal.py`.

**Finding 1 — `interpreter.py`'s `CoordinateInterpreter.resolve()` is pairwise, not N-way.**
Its signature takes exactly `node_a` and `node_b`. It was built to arbitrate a single two-way
axis conflict (confidence → recency → pheromone-strength → average cascade), not to merge an
arbitrary number of simultaneous signals. Any proposal that treats this cascade as a ready-made
"merge N parallel results" mechanism (relevant to the fan-out/CAT-equivalent idea explored
earlier in this thread) needs a real extension — folding N results two at a time, or rewriting
the cascade to accept a list — not just a usage change.

**Finding 2 — Immortus is not "3D coordinates + literal time."** `ImmortusBrain` is an
*activation-gated speculative router*, not a passive time-indexed log. It only runs when a
plan's dependency depth ≥ `IMMORTUS_DEPTH_THRESHOLD` (3); otherwise standard DER runs untouched.
When active, it picks a `CoordinateRoute` (an ordered list of `step_id`s with a score) between an
`entry_coords` and `objective_coords` pulled from the Mycelium coordinate space — so it *is*
grounded in the same 3D graph. But the "4th dimension" it tracks per session
(`TemporalCoordinate`: `momentum`, `drift`, `velocity`, `identifier_depth`) is **not** wall-clock
time and **not** the Caducean physics state (`u`, `ξ`). It's a separate, parallel bookkeeping
system — closer to a dashboard for the currently-committed route (how much energy is left, how
far off-plan things have drifted, how many steps completed) than a stored history of past
coordinate-to-coordinate transitions. Nothing in these files persists `TemporalCoordinate` for
later cross-session lookup — it lives and dies with one `ImmortusSession`.

**Consequence for the earlier design doc (§6/§7 of the other agent's document, referenced in
this thread):** the proposal to expose `u`/`ξ` as coordinate-pair history "via Immortus" doesn't
have an existing home to slot into — `TemporalCoordinate` would need `u`/`ξ` fields added, or the
pair-tracing would need to be new infrastructure built alongside Immortus rather than inside it.

**Open tension worth deciding explicitly:** Immortus's own activation gates
(`IMMORTUS_DEPTH_THRESHOLD`, `IMMORTUS_CLARITY_THRESHOLD = 0.70`,
`IMMORTUS_NOVELTY_THRESHOLD = 0.50`) are hard cutoffs with no blending — the same kind of binary
cliff the growth-width proposal (Section 5) was designed to avoid at the per-step level. It's not
necessarily wrong for a coarse "should the heavier routing machinery even turn on" decision to be
a cliff while a fine-grained per-step decision is continuous — but the two mechanisms currently
make overlapping "how much should this fan out" judgments from two uncoordinated signals
(`drift`/`route_score` in Immortus vs. `u`/`ξ` in the growth-width proposal) and nothing here
confirms they were meant to compose. Confirmed working: `router.py`'s `_pheromone_walk()` does
genuinely read live edge scores out of `mycelium_edges` (or via `graph.pheromone_walk()`), so the
claim that Immortus and Mycelium's edge-scoring are already bridged is correct — just at the
whole-route level, not the parallel-merge level `interpreter.py` would need for that.

---

## 7. Open questions for the next agent

1. Where exactly in `der_loop.py` are `QueueItem`s constructed, and is `u`/`ξ` state available at
   that point (or would it need to be threaded in from `caducean_trajectory.py`)?
2. What does `kyudo.py` actually do? (Largest unreviewed file, name suggests it may be central —
   possibly the channel-profile / orchestration logic referenced in `navigator.py`'s
   `_get_profile_readable_spaces()`.)
3. Does `interface.py` (44KB, `MyceliumInterface`) already contain a splitting/differentiation
   mechanism that would make the proposed change redundant?
4. Is there an existing `caducean_update()` implementation to review, to confirm how `F(u) = 2u -
   2u³` and the attractor dynamics are actually computed per DER cycle?
5. Should the "split or execute" decision threshold be a new named constant (alongside
   `CONVERGENCE_THRESHOLD = 0.08` / `DIVERGENCE_THRESHOLD = -0.06` already in `topology.py`), or
   reuse those directly?
6. Should Immortus's route-level decisions (`drift`, `route_score`, `PIVOT`) and the per-step
   growth-width decision (`u`, `ξ`) be explicitly composed (e.g., growth-width operates *within*
   whichever step Immortus's committed route currently points to), or kept deliberately separate?
   Nothing currently confirms either intent — this should be a decision, not a discovery.
7. If `u`/`ξ` history-by-coordinate-pair is still wanted (Section 6 of the earlier design doc),
   does it make more sense as new fields on `TemporalCoordinate`, or as an entirely separate
   table alongside `caducean_trajectories`?

---

## 8. Suggested next step

Share `kyudo.py`, `interface.py`, and the section of `der_loop.py` where `QueueItem` objects are
actually created and consumed (not just the dataclass definition), plus whichever file contains
the live `caducean_update()` implementation. That will let the next agent confirm or revise the
hypothesis in Section 5 against real control flow instead of static analysis of definitions.

---

## 9. Inner loop / outer loop — combining the MorphoHDL sub-loop rule with a self-tuning
    outer loop (AIDE2-inspired)

**Source:** Weco AI, "AIDE²: The First Evidence of Recursive Self-Improvement"
(https://www.weco.ai/blog/first-evidence-of-recursive-self-improvement), published 2026-07-14.
Summarized in plain terms below — see the source for full detail; do not treat the summary as a
verbatim reproduction.

### 9.1 What AIDE² actually did

Weco built a two-loop system for autonomously improving their own research agent:
- **Inner loop** — an ordinary autoresearch agent that optimizes code against an evaluation
  metric for one task (draft → debug → improve, operating over a solution tree).
- **Outer loop** — a separate agent that rewrites the *inner loop's own code* (its search policy,
  its context-handling logic, its guardrails), evaluates the rewritten inner-loop agent across a
  batch of held-out tasks, and keeps the rewrite only if it beats the previous best.

Run for 100 unattended outer-loop steps over eight days, this discovered seven successively
better versions of the inner-loop agent (AIDE0 → AIDE85), which then beat two years of
Weco's own hand-tuning on tasks it was never optimized against. It also self-discovered defenses
against reward hacking (gaming its own success metric) that Weco hadn't explicitly asked for.
Three design choices did most of the work and are the parts worth reusing:
1. **Public/private split** — the inner loop only ever sees a "public" score to steer itself;
   whether a change survives is decided on a "private" held-out score it never sees. This is what
   stopped the system from just learning to look good on its own metric.
2. **Fixed cost budget per evaluation** — proposed changes can't win by just spending more
   compute; they have to be genuine efficiency gains. This is what forced real algorithmic
   improvement instead of brute force.
3. **Task heterogeneity** — every proposed change is tested across a deliberately varied task
   set, which is what forced generalizable improvements instead of narrow overfitting.

Weco is explicit that this is "Level 1" (net positive) self-improvement — the loop got
efficiently better than manual tuning — not "Level 2" (ignition, where the improved system
becomes a *better improver*) or "Level 3." They also report a real cost: the final evolved agent
became noticeably harder for its own creators to understand and maintain.

### 9.2 The mapping onto IRISVOICE

This maps onto the Caducean Engine's existing structure more directly than it might first
appear, because the two-loop shape is already half-built:

| AIDE² concept | IRISVOICE equivalent (existing) | IRISVOICE equivalent (proposed) |
|---|---|---|
| Inner loop (executes one task against an eval) | DER loop / Sub-Loop, governed live by `u`/`ξ` via `caducean_update()`, plus the growth-width split-or-execute rule from Section 5 | — already exists as a hypothesis, not yet confirmed against real control flow |
| Outer loop (rewrites the inner loop's own code/policy) | *nothing currently plays this role* | A new, slower-running process that reads completed session trajectories and proposes small changes to the **governing constants** themselves (`CONVERGENCE_THRESHOLD`, `DIVERGENCE_THRESHOLD`, `PRUNE_THRESHOLD`, `HIGHWAY_THRESHOLD`, the growth-width curve's shape, edge-scoring deltas in `scorer.py`, etc.) |
| Raw material the outer loop trains on | — | Already being recorded, unused for this purpose: `caducean_trajectories` (per-step `x, y, ξ, u, action, outcome, eml_after`), `mycelium_traversals`, episodic memory |
| Public/private split | — | Don't let the outer loop judge a proposed constant change using the *same* live pheromone/confidence score that the constant itself feeds into — that's circular and will reward-hack itself. Judge it on something the inner loop doesn't directly optimize: natural exit rate, whether `DER_EMERGENCY_STOP` was hit, wall-clock/token efficiency, or downstream task success. |
| Fixed cost budget | — | Cap how much replay/evaluation compute the outer loop gets per proposed change, so tuning can't just become "run more sessions." |
| Task heterogeneity | — | Evaluate each proposed constant change across a mix of task/domain types already distinguished in Mycelium's `domain` coordinate space — not just the domain that inspired the proposal. |
| Keep-only-if-better gate | — | Adopt a new constant value only if it beats the incumbent on the held-out metric; log every accepted *and* rejected proposal (AIDE² rejected ~90% of its own proposals — that ratio is a feature, not a failure). |

**In plain terms:** the growth-width rule from Section 5 is the *athlete* — deciding, live,
whether to break a step down further based on how resolved the current physics state feels. What
AIDE² adds is a *coach* — a separate, slower loop that doesn't run the task itself, but watches
tape from many past sessions and nudges the athlete's own decision-making rules (the thresholds
that decide "this feels resolved enough to stop splitting") toward whatever has actually worked
best, without ever letting the athlete grade its own performance.

### 9.3 A concrete algorithm (single-variable, guarded)

Proposed as a first, deliberately conservative version — not the AIDE² system in miniature, just
its three safety properties applied to constant-tuning rather than full code rewriting:

1. **Trigger.** On a schedule (e.g. every N completed sessions, or reusing MCM's existing
   70%-budget trigger cadence as a model), pull a batch of recent `caducean_trajectories` +
   outcome records.
2. **Propose one change.** Identify a single named constant (from `spaces.py`, `der_constants.py`,
   `scorer.py`, or the growth-width curve's parameters) and propose one small, bounded nudge to
   it — not a rewrite of the rule's logic. Keeping changes to one variable at a time is the direct
   countermeasure to AIDE²'s own reported downside (§3.2 of the source: the evolved agent became
   hard to understand) — legibility should be a constraint on this system from day one, not an
   afterthought.
3. **Evaluate on held-out sessions, not the sessions that inspired the proposal.** Replay the
   candidate value against a separate batch of recorded trajectories (or flag a small number of
   upcoming live sessions as evaluation-only), and score using a metric independent of the
   internal pheromone/confidence score being tuned (natural exit rate, emergency-stop rate,
   steps-to-convergence, token cost) — this is the public/private split, adapted.
4. **Budget-cap the evaluation.** Fixed number of replay sessions or fixed compute per proposal —
   this is what stops the outer loop from just brute-forcing its way to an apparent win.
5. **Test across task types, not one.** Pull the held-out batch from more than one `domain`
   coordinate value.
6. **Keep only if it wins; log everything either way.** Adopt the new constant value only if it
   beats the incumbent on the held-out metric under the fixed budget. Log rejected proposals too
   — that record is itself useful signal about which constants are already near-optimal versus
   still worth probing.
7. **Do not extend to rewriting the growth-width function's logic itself until step-tuning is
   stable and well-understood.** AIDE² found that of ~95 more ambitious proposals it tried, only
   about 10% survived; the simplest lever (tuning existing named constants) is where almost all of
   the safe, legible value is, and is the natural first target given how many named constants
   this codebase already exposes (`spaces.py` alone defines a dozen).

### 9.4 How this ties back into the rest of this document

- It gives the growth-width hypothesis (Section 5) a reason to exist beyond one session — instead
  of Midas hand-tuning `CONVERGENCE_THRESHOLD`/`DIVERGENCE_THRESHOLD` by feel (the way Weco spent
  two years hand-tuning AIDEhuman), the outer loop does that tuning continuously from data the
  system is already recording.
- `interpreter.py`'s pairwise `resolve()` cascade (Section 6, Finding 1) is a good *first target*
  for this algorithm: its confidence-diff (0.05) and recency-diff (1.0) cutoffs are exactly the
  kind of single named constants Step 2 above would probe, before attempting the harder N-way
  extension.
- The Immortus finding in Section 6 is a direct caution for Step 3: `TemporalCoordinate`'s
  `drift`/`momentum` is a separate scoring system from `u`/`ξ` — the outer loop must not
  accidentally validate a proposed change by checking "did drift go down," since drift is
  computed from the very step-success signal a change might be gaming. The held-out metric needs
  to be genuinely external to whichever system is being tuned.
- `nbl.py`/`mcm.py`'s existing compact-encoding philosophy is a natural fit for how the outer
  loop would log its own history cheaply — an NBL-style ledger of "constant X: was V1, tried V2,
  held-out result R, kept/rejected" costs almost nothing to keep around indefinitely.
- **Calibration, not hype:** per Weco's own framing, this class of system — even when it works —
  is "Level 1" (net positive vs. manual tuning), not a system that improves its own ability to
  improve itself. The honest framing for IRISVOICE is "a disciplined auto-tuner for existing
  named constants," not "recursive self-improvement" in the strong sense. Keep that distinction
  explicit in any future write-up so expectations don't run ahead of what Section 9.3's algorithm
  actually does.

**Not yet done:** no code written, no confirmation that trajectory data currently recorded is
sufficient to compute the proposed held-out metrics, no design for where this outer-loop process
would actually run (background job? triggered by `DistillationProcess`? a new module entirely?).
