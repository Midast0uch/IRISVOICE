# The Learned Scoreboard and Live Reasoning State

**What this is.** A design-thinking document, written to be turned into a spec *after*
[`caducean-phase-scheduler`](../specs/caducean-phase-scheduler/) and
[`caducean-kernel-unification`](../specs/caducean-kernel-unification/) land. It answers three
questions:

1. What is the actual boundary between the *learned scoreboard* (safe for scheduling to read) and
   *live reasoning state* (not safe), and why?
2. Is the scoreboard a lightweight recursive learning path that works with memory? — **Mostly yes.
   One part of that framing is wrong, and the wrong part matters.**
3. The three physics↔memory couplings — NBL/MCM compression, coordinate-addressed recall, and
   EML→retrieval breadth — how each can be improved with what already exists.

**Status of claims.** Every claim about the code carries a file:line citation and was traced on
2026-07-27. Claims without a citation are proposals, and say so. This discipline exists because
`CADUCEAN_TECHNICAL_OVERVIEW.md` §11 was stale in both directions long enough for three bugs to
accumulate behind it (see that document's §13).

---

## 1. The boundary, stated correctly

I originally framed this as *"learned prior, yes; live reasoning state, no."* That framing is a
useful shorthand but it is **not the real rule**, and if you hold it literally you will reject
something that already works and is correct.

Here is the actual rule:

> **A component must not consume a signal that is correlated across the very things that component
> exists to keep apart.**

Everything follows from that, including which couplings are fine:

| Component | Its job | May it read live `u`/`ξ`? | Why |
|---|---|---|---|
| **Phase scheduler** | *De-correlate* work in time so it never arrives as a burst | **No** | `u` is correlated across sessions doing similar work — that is the entire premise of `coupled_registry`. Feeding a de-correlator a correlated signal makes sessions that *think* alike get *scheduled* alike. It would look like it was working right up until the two busiest sessions synchronized. |
| **Memory decay / retention** | Keep what matters, drop what doesn't | **Yes** | Retention has no de-correlation requirement. Correlated retention is *desirable* — if the agent is exploring, preserve exploratory trails. |
| **Retrieval breadth** | Match search width to cognitive need | **Yes** | Same: no separation requirement. |
| **Split / growth width** | Decide execution-tree shape | **Yes** | It is *supposed* to be a function of resolution state. |

This is why **memory reading live `u` is already live in production and is correct**, while
scheduling reading it would be a defect. The distinction is not about staleness or provenance. It
is about whether correlation is your enemy.

The scoreboard is safe for the scheduler for a reason that survives this sharper test: **an edge
score is a per-path summary of many past outcomes across many sessions.** Two concurrent sessions
reading the same scoreboard get the same *prior*, but that prior does not tell them to act at the
same *moment* — it only says "this kind of work tends to pay off." Timing stays free for the
scheduler to spread. The signal is orthogonal to the axis the scheduler controls, which is exactly
what makes it admissible.

---

## 2. Verified inventory — what already exists

The scoreboard is real, and richer than I described in conversation. Nothing below needs to be
built.

| Mechanism | Where | What it does |
|---|---|---|
| **Outcome scoring** | [`scorer.py:70-102`](../backend/memory/mycelium/scorer.py) | `record_outcome(edge_ids, outcome)` — `hit +0.05`, `partial +0.02`, `miss −0.08`. Plus a `HIGHWAY_BONUS` (+0.01) when a hit crosses `HIGHWAY_THRESHOLD` (0.85). |
| **Per-edge hit statistics** | `mycelium_edges.hit_count` / `miss_count` / `traversal_count` | A real hit-rate per path is already queryable. |
| **Time decay + pruning** | [`scorer.py:104-184`](../backend/memory/mycelium/scorer.py) | `score −= rate × multiplier × days_idle`; edges below `PRUNE_THRESHOLD` (0.08) are **deleted**. |
| **Decay is wired** | [`main.py:684`](../backend/main.py), [`interface.py:595`](../backend/memory/interface.py), [`distillation.py:428`](../backend/memory/distillation.py) | `run_maintenance()` fires at startup, every N completed tasks, and from the distillation process. **Not dormant** — unlike `coupled_registry`. |
| **Decay is already `u`-modulated** | [`scorer.py:132-146`](../backend/memory/mycelium/scorer.py) | `u > 0` (explore) → multiplier **0.5** (preserve learning); `u < 0` (compress) → **1.8** (prune faster). A live physics→memory coupling, in production, correct. |
| **Structural learning** | [`scorer.py:233-425`](../backend/memory/mycelium/scorer.py) | `condense` merges near-duplicate nodes; `expand` **splits a node when its outbound hit/miss variance exceeds 0.40**. The graph reshapes itself around where outcomes disagree. |
| **A scoreboard reader already influences behavior** | [`interpreter.py:204-260`](../backend/memory/mycelium/interpreter.py) | `BehavioralPredictor.predict` ranks candidate next tools by `(hit_count / traversal_count) × target_confidence` and feeds `ContextPackage.tier2_predictions`. |
| **EML → retrieval breadth** | [`agent_kernel.py:5496-5504`](../backend/agent/agent_kernel.py) | High EML + x-dominant → retrieve **more, looser** (limit 5, min-score 0.40). Low EML + y-dominant → **fewer, stricter** (limit 3, 0.65). |

Two things worth pausing on.

**`condense`/`expand` is the Caducean duality at the graph scale.** Merge near-duplicates
(compress) and split high-variance nodes (expand), driven by outcome disagreement. That is the
same operator the DER loop applies to execution shape via `_growth_width`, applied to memory
topology instead. Nobody appears to have written that parallel down, and it is a stronger claim
for the architecture's coherence than anything in the overview's §8.

**Decay is the restoring force the Duffing parameters lack.** Finding F1 in the overview's §13 is
that `(a, b, s)` ratchets one way with nothing pulling back. The scoreboard does not have that
problem — reinforcement pushes up, decay pulls down, and both are wired. My instinct in
conversation was that the scoreboard would need a homeostat added; it already has one. That
correction matters for §3, because it changes which risk is real.

---

## 3. Your intuition: where it holds, and the one place it breaks

### Where you are right

**It is genuinely lightweight.** Reading an edge score is one indexed SQL read against
`.mcm/coordinates.db`. No model call, no new learner, no training loop, no new storage. The
`BehavioralPredictor` query ([`interpreter.py:243-256`](../backend/memory/mycelium/interpreter.py))
is the shape of the whole thing: a single `SELECT … ORDER BY (hit_count/traversal_count) *
confidence DESC LIMIT 10`.

**It genuinely works with memory rather than beside it.** The score accumulates as a *side effect*
of work succeeding or failing. Nothing has to be instrumented for scheduling's benefit. And the
read path already has a production precedent that does exactly this kind of consumption.

**The two-timescale structure is already the house style.** Fast stateless reaction to a slow
stateful accumulation is the §9 principle from your own concept doc, and it is what NBL and the
Duffing law both do. A scheduler reading a slowly-learned score is that pattern again, not a new
idea bolted on.

### Where the framing breaks: "recursive learning path"

**The loop closes, but the reward does not measure what you would be trying to learn.**

Trace it honestly:

```
scheduling decides when work runs
   → which work actually runs
   → outcomes (hit / partial / miss)
   → edge scores change
   → scheduling changes
```

That is a closed loop. But look at what the reward signal is actually reporting. `hit` means *the
work was worth doing*. It says nothing about whether the **timing** was right. A step that would
have hit at 10:00 also hits at 10:04. So the loop learns *which work is valuable* — and scheduling
free-rides on that.

**So this is not a recursive learner for scheduling. It is a scheduler consuming a value prior
learned elsewhere.** That distinction is not pedantic. If you treat it as reinforcement learning
for scheduling, you will go looking for a credit-assignment story that does not exist, and you may
build feedback machinery on top of a reward that cannot see the variable you are adjusting.

**And there is a real timing reward available — just not this one.** The phase scheduler's own
instrumentation (`caducean-phase-scheduler` REQ-20) produces exactly the signals that *do* vary
with timing: `429` events per provider, gate wait durations, and inter-request gap distribution.
If you ever want genuine recursive learning about *scheduling*, that telemetry is the reward, not
the edge score. Two learners, two rewards, two timescales:

| Learner | Reward | Learns | Timescale |
|---|---|---|---|
| Existing Mycelium scoring | hit / partial / miss | which work is valuable | tasks → days |
| *(hypothetical)* scheduling tuner | 429 rate, wait time, gap variance | which cadence is better | calls → minutes |

My recommendation is to build the first coupling only — read the prior, no learning — and add a
timing learner only if REQ-20's data shows the fixed rules leaving real value on the table.
Shipping one closed loop is a lot easier to reason about than two interacting ones.

### The risk that is actually sharp: irreversible pruning

This is the part I would not have caught without reading `apply_decay`, and it is the strongest
argument for caution.

Decay is driven by `days_idle = (now − last_traversed) / 86400`
([`scorer.py:162`](../backend/memory/mycelium/scorer.py)), and edges below 0.08 are **deleted**,
not merely lowered ([`scorer.py:172-174`](../backend/memory/mycelium/scorer.py)).

Now add scheduling that favors high-scoring paths:

- Favored paths get more turns → traversed more often → `last_traversed` refreshes → **decay
  never bites them.**
- Starved paths get fewer turns → idle accumulates → score falls → crosses 0.08 → **the edge is
  deleted.**

The path is then gone. Not down-weighted — gone. And it was starved because scheduling
de-prioritized it, which scheduling did because its score was lower, which it was partly because
it got fewer turns. **A path can be permanently deleted for having been under-scheduled rather
than for being bad**, and once deleted there is no signal left to recover it from.

The existing decay is a fine counterweight to *reinforcement*. It is not a counterweight to
*scheduling-induced starvation*, because starvation and decay push the same direction. That is
the same structural shape as overview finding F1 — two forces, one direction, no restoring term —
just relocated from engine parameters to graph edges.

Three plausible mitigations, all cheap, none yet designed:

1. **Floor the scheduling share.** Never let a registrant's derived rhythm fall below some
   fraction of the even split. Guarantees every path keeps getting traversed, so decay measures
   genuine staleness rather than scheduling neglect.
2. **Separate "not scheduled" from "not useful."** Decay on `days_idle` conflates them. If the
   scheduler recorded *offered-but-deferred* turns, decay could exempt paths that were ready and
   passed over.
3. **Make the coupling read-only with respect to prune eligibility.** Let the score influence
   *rhythm* but explicitly exclude scheduling-derived traversals from refreshing
   `last_traversed`, so favored paths do not get free decay immunity either. This is the most
   symmetric fix and probably the right one.

### Two smaller gaps

**Value is not urgency.** An edge score measures whether work pays off, not whether it must happen
soon. Memory compression *must* run before context overflows regardless of how unremarkable its
outcomes are. If rhythm is derived purely from value, low-value-but-deadline-bound work starves.
The phase manager's `natural_period_s` currently encodes urgency implicitly; deriving it purely
from the scoreboard would erase that. Any design needs both terms.

**Exploration decays by construction.** A brand-new path has no hits, so it scores low, so it gets
fewer turns, so it accrues hits slowly. Standard explore/exploit. The system already holds the
right signal for the counterweight — EML is literally an exploration/memory-load balance, and it
already widens retrieval when exploration is called for
([`agent_kernel.py:5499-5501`](../backend/agent/agent_kernel.py)). The same signal should widen
*scheduling* generosity toward unproven paths. Note this is EML (a balance ratio), not `u` — and
EML is not correlated across sessions the way `u` is, so §1's test permits it. Worth confirming
that carefully during design rather than assuming it.

### Net verdict

You are right that this is a lightweight coupling that works with the memory you already have,
and right that the pieces are largely built. You are wrong that it is a *recursive learning path*
for scheduling — it is a value prior with a closed loop whose reward cannot see timing. And the
recursion, such as it is, has one genuinely dangerous property: it can cause permanent deletion of
paths it starved. That is designable around, but it must be designed, not assumed.

---

## 4. The three memory couplings, and how to improve each

### A. NBL / MCM compression — make it fire on a boundary, not a threshold

**Current state.** MCM compresses when the context hits a budget fraction (0.70 default,
[`mcm_check_compress.py`](../backend/agent/mcm_protocol/actions/mcm_check_compress.py)). NBL builds
a compact string carrying a **3-tuple** `[gate_prog, landmark_density, session_depth]`
([`nbl.py:90`](../backend/memory/nbl.py)) — a Mycelium *context* coordinate, **not** the Caducean
4D `(x, y, ξ, u)`.

**Two improvements, both using what exists:**

1. **Compress at a convergence boundary rather than a token threshold.** A 70% trigger fires
   wherever the token count happens to land — frequently mid-thought. The system already knows
   when a thought is *finished*: `|u| >= U_CONVERGED`
   ([`der_constants.py:142`](../backend/agent/der_constants.py)). Compressing at that crossing
   folds a completed unit of reasoning instead of cutting one in half, so the NBL summary is a
   summary of something coherent. Concretely: treat 0.70 as the point where compression becomes
   *eligible* and the next convergence crossing as the point where it *fires*, with a hard
   ceiling (0.85, say) that forces compression regardless. Same shape as the phase gate — eligible
   window plus a hard rail. Same lesson as unification REQ-12: prefer the band signal over the raw
   threshold.

2. **Carry the 4D coordinate in the NBL string.** Today NBL's 3-tuple and the Immortus chain's
   4-tuple are different coordinate systems, so an NBL summary cannot be located in the same space
   as the documents and steps it summarizes. Adding the Caducean 4-tuple — using the single
   `format_coords` helper that unification REQ-5 introduces — makes NBL summaries *addressable by
   the same proximity query* as everything else. That is the point where "compress history into a
   position" stops being a metaphor and becomes literally true: the compressed artifact would sit
   at the position it compressed.

**Dependency:** improvement 2 needs unification REQ-5 (one coordinate format) first.

### B. Coordinate-addressed recall — fix it, then rank by two signals

**Current state.** Broken three ways (overview §13 finding F6): lookup key mismatch, prose in a
coordinate field, split chain identity. Unification REQ-4/5/6 repairs all three.

**The improvement worth designing *after* the repair:** the proximity query
([`agent_kernel.py:3755`](../backend/agent/agent_kernel.py)) ranks purely by coordinate distance.
It answers *"what did I gather while thinking like this?"* — which is the novel primitive, and it
is genuinely something embeddings cannot do.

But the scoreboard knows something the coordinate does not: **whether it worked.** Ranking by
`distance × edge_score` (or distance gated on a minimum score) answers the strictly better
question: *"what did I gather while thinking like this, that actually paid off?"* Both inputs
already exist; nothing new is stored. This is the point where the two memory layers — the
coordinate chain and the pheromone graph — finally talk to each other, and as far as I can tell
they never have.

Two smaller additions once the plumbing works: the trajectory table already carries `domain` and
`recommendation` columns ([`caducean_trajectory.py:37-38`](../backend/agent/caducean_trajectory.py)),
so proximity queries can be domain-scoped, and can exclude entries recorded during a
TOPO_VIOLATION (`recommendation == 3`) — you probably do not want to recall what you were doing
while the topology was breaking.

**Dependency:** hard-blocked on unification REQ-4/5/6. There is nothing to improve until the
query returns non-empty.

### C. EML → retrieval breadth — the coupling that works, and its three rough edges

**Current state.** Works correctly ([`agent_kernel.py:5496-5504`](../backend/agent/agent_kernel.py)).
This is the best existing example of the physics paying off, and it is undocumented.

**Three improvements, in ascending order of effort:**

1. **Stop making an FFI call per step.** The retrieval path calls `ffi_calculate_eml(_session)`
   inside the DER loop ([`agent_kernel.py:5498`](../backend/agent/agent_kernel.py)), while
   `CaduceanTrajectoryRecorder.get_cached_eml()`
   ([`caducean_trajectory.py:266-269`](../backend/agent/caducean_trajectory.py)) exists precisely
   to avoid that and is currently used only by AutoResearch
   ([`auto_research.py:343`](../backend/agent/auto_research.py)). This is a hot-path fix worth a
   couple of lines, and the `CLAUDE.md` quality check explicitly asks for it ("no unnecessary work
   in hot paths").

2. **Make the modulation continuous.** It is currently a three-branch `if/elif` with hardcoded
   pairs (2/0.55, 5/0.40, 3/0.65). Interpolating limit and min-score continuously in EML gives
   graded behavior instead of three cliffs — the same correction the scheduler spec applies to
   amplitude and the unification spec applies to registry coupling. Three specs converging on
   "replace the threshold with a continuous function" is a pattern worth naming as a house rule.

3. **Extend the modulation to the third consumer.** EML/`u` already modulate retrieval breadth
   (`agent_kernel`) and decay rate (`scorer.py:132-146`). The coordinate-proximity *threshold* is
   the one comparable knob that is still a constant. An exploring agent should accept looser
   coordinate matches; a consolidating one should demand tighter. That would make all three memory
   read/retain paths physics-aware, from two of three today.

---

## 5. Where should this go — unify spec, or its own?

**Recommendation: its own spec, after both current ones land.** Reasoning:

- **Hard dependency.** §4B cannot be built until unification REQ-4/5/6 makes coordinate recall
  return anything. §4A improvement 2 needs REQ-5's shared formatter. §3's coupling needs the phase
  manager to exist.
- **Scope integrity.** `caducean-kernel-unification` has a clean thesis — *repair what exists and
  factor out shared math*. These are *enhancements*, a different kind of work. Mixing them would
  make a 15-REQ spec into a 25-REQ one and blur what "done" means.
- **The scoreboard coupling deserves its own risk treatment.** The irreversible-pruning problem in
  §3 needs a real design decision, its own flag, and its own behavioral tests. Appending it to a
  spec whose Wave 4 already carries the highest-risk change in the project is asking for the two
  risks to be evaluated as one.

**✅ Two candidates were pulled forward into `caducean-kernel-unification` (2026-07-27)** as
**REQ-16** and **REQ-17**, with tasks T3.8–T3.12 in that spec's Wave 3:

| Candidate | Landed as | Note |
|---|---|---|
| §4C.1 — use the cached EML instead of a per-step FFI call | **REQ-16** | Turned out **not** to be a ~2-line change. `_eml_cache` is a **class attribute** ([`caducean_trajectory.py:107`](../backend/agent/caducean_trajectory.py)) written unconditionally by every `record()` ([`:195`](../backend/agent/caducean_trajectory.py)), so it is shared across sessions — swapping the call naively would trade a small cost for cross-session contamination. REQ-16 makes the cache per-session first. Still small, but it is a correctness fix, not just a perf one. |
| §4C.2 — continuous EML modulation | **REQ-17** | Also had a trap: **`limit` is V-shaped** across the three anchors (explore 5 → neutral 2 → consolidate 3) while `min_score` is monotone. The obvious single interpolation would put `limit ≈ 4` at neutral, silently doubling the common case's retrieval work, with no existing test catching it. REQ-17 AC3 anchors on today's exact values as the non-regression property. |

Cross-spec safety for both was checked against the phase scheduler on four surfaces and recorded as
**C9** in [`specs/CADUCEAN_SPEC_RECONCILIATION.md`](../specs/CADUCEAN_SPEC_RECONCILIATION.md) — no
conflict. The interesting one: scheduler throttling *cannot* stale a step-indexed EML cache, which is
the exact inverse of why relaxation needed a wall-clock floor (C5). Same system, two caches, opposite
correct answers.

§4A (NBL/compression), §4B (two-signal proximity ranking), and §3 (the scoreboard coupling itself)
remain for the follow-on spec.

Everything else — the scoreboard coupling, NBL coordinate carry, boundary-triggered compression,
two-signal proximity ranking — belongs in the follow-on spec. Suggested name:
`specs/memory-physics-coupling/`.

---

## 6. Open questions for the follow-on spec

- **Q1 — Which mitigation for irreversible pruning?** §3 offers three. The third (exclude
  scheduling-derived traversals from refreshing `last_traversed`) is the most symmetric, since it
  denies favored paths free decay immunity as well as protecting starved ones. Needs verification
  that `last_traversed` has exactly one write path before relying on that.
- **Q2 — Is EML admissible to the scheduler under §1's test?** The exploration counterweight needs
  a signal, and EML is the natural one. EML is a *ratio* derived from `(x, y)` accumulation, so it
  is less obviously correlated across sessions than `u` — but "less obviously" is not "verified."
  This needs an actual correlation check against recorded trajectories before any scheduler reads
  it. **Do not assume; measure.**
- **Q3 — How is urgency represented alongside value?** Two terms, or one term with a floor? A
  floor is simpler and doubles as the Q1 starvation guard, which is an argument for it.
- **Q4 — Does the `condense`/`expand` duality want to be unified with `_growth_width`?** Both
  split on outcome disagreement; both merge on similarity. They may be the same operator at two
  scales, which would be a genuine finding rather than a coincidence — or the resemblance may be
  superficial. Worth an hour of comparison before either claiming or dismissing it, and worth
  resisting the urge to unify them just because they rhyme.
- **Q5 — Should the timing learner (§3) ever be built?** Deliberately deferred. Decide from
  REQ-20's measured gap-variance data, not in advance.

---

## 7. One-paragraph summary

The learned scoreboard is real, wired, and already has a reader that influences behavior — so
coupling it to scheduling is a small change to an existing system rather than a new subsystem. It
is safe for the scheduler to read for a precise reason: an edge score is orthogonal to the timing
axis the scheduler controls, whereas live `u` is correlated across exactly the sessions the
scheduler must keep apart. That correlation test, not any distinction about staleness, is the real
boundary — and it correctly permits the physics→memory couplings that already exist and work. The
one thing to design carefully is that reinforcement plus scheduling plus idle-decay all push the
same direction, so a path can be permanently deleted for having been under-scheduled rather than
for being bad; that is the same one-way-ratchet shape as the Duffing-parameter defect, relocated to
graph edges. And the loop should be understood as a scheduler consuming a value prior, not as
reinforcement learning about scheduling — the reward reports whether *work* was worth doing and
cannot see *when* it ran. If timing ever needs to be learned, the reward for that lives in the
scheduler's own rate telemetry, and that is a second learner to be added deliberately or not at
all.
