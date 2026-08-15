# Architectural Blueprint Addendum: Resonant Recall & Wormhole Traversal
Context: IRIS Voice / Caducean Architecture — extends "Architectural Blueprint: Causal DAG & Meta-Learning Framework"
Author: System Architect (User)
Status: Active Exploration / Conceptual Evolution (Updated: Hex Topology Synthesis)

## 0. Executive Summary: Recall as Physics, Not Retrieval

The original blueprint established the DAG as the unifying structure (Section 1), causal topology via Treatment/Mediator/Outcome/Confounder (Section 2), and node lifecycles with Inception for confounder resolution (Section 3). This addendum answers a question that sits underneath all of it: when an agent's streamed thinking hits a point of uncertainty, how does it search its own history for what matters, live, without breaking the stream?

The answer that fell out of the exploration is not a search algorithm bolted onto the graph — it's the same driven-damped oscillator physics the Caducean engine already validated (limit cycle R² 0.9986), applied one layer up. Nodes that get used resonate. Nodes that stop being used decay — but decay means *dormant*, not deleted, per the existing DCP pruning rule (original blueprint Section 1: "prunes the node from the active working buffer but leaves the edge intact"). A wormhole is a shortcut edge between causally distant nodes that share a confounder signature. A landmark is a wormhole whose resonance has held long enough, and whose coupling to other resonant nodes is strong enough, to be promoted into a fixed reference point on the 3D trajectory axis — collapsing multi-hop walks into near-direct triangulation.

**Nothing here is a new subsystem.** It is the existing DAG, the existing Mycelium store, and the existing Caducean physics, reading a signal (timestamps, activation counts, coupling) that was already being collected and previously discarded. This sentence is a SCOPING CONSTRAINT, not a pleasantry: every mechanism below must name the component it reuses, and anything that cannot name one is a new subsystem in disguise and needs justifying on its own terms. It was dropped in an earlier revision of this document and is restored here deliberately — losing it is precisely how a "reuse what is already there" idea becomes a parallel implementation over a few iterations.

*Evolution Note:* The mechanism for this routing has evolved from raw confounder matching to a Hex Topology (Hash Signatures, Hexagonal Binning, and Hyperedges). This unifies the physics of the confounder with the structural math required for "quantum speed" O(1) traversal.

*Resolved during review:* the Hyperedge's Triangle Inequality guarantee does NOT depend on the hex-binned confounder composite being a proper metric space — that was a conflation between two separate layers. The hex bin is only a candidate-generation index (fast lookup of nearby hash cells). The actual distance being composed is the coupling/posterior graph itself, and for any graph where distance is defined as shortest-path-through-weighted-edges, the Triangle Inequality holds by construction — the direct distance is by definition the minimum over all paths, so a candidate path through a landmark can never score better than itself. No geometric assumption required.

The real precision needed is the *composition rule*: Beta-Bernoulli scorecards (Section 6) produce a posterior probability per edge, not a raw distance, so summing two posteriors directly is not meaningful. Convert each edge's cost to `-log(posterior)` before composing — high-confidence edges near-zero cost, low-confidence edges large cost — which is the standard way to turn independent probabilistic hops into a valid additive path cost (equivalent to running Dijkstra/ALT over log-probability weights).

---

## 1. Where This Sits in the Existing DAG

Recall is not a preamble step run once before generation. It is a node state, structurally parallel to SPLIT:

```
RUNNING (streaming tokens)
  → variance spike (|u| crosses threshold mid-thought — a confounder surfaces)
  → RECALL (bounded query against Mycelium)
  → posterior + resonance update on touched edges
  → RUNNING resumes with updated 4D state
```

RECALL is interrupt-driven, not front-loaded. The agent does not decide upfront what history it might need. It asks when the current Treatment→Mediator edge it is reasoning about has no confident prior — exactly the same trigger condition already defined for SPLIT.

---

## 2. The Evolution of the Shortcut Primitive: From Confounder to Hex

It is critical to preserve the understanding of *why* confounders were the starting point, and *why* they had to evolve into Hex primitives. Falling back to singular confounders as routing mechanisms reintroduces binary logic and semantic drift.

### The Origin: The Confounder (The Causal Reality)
A confounder is the *physics* of the system — the hidden variable (like GPU tier or time of day) that influences an outcome. Originally, Tier 1 recall was designed to match nodes based directly on their confounder signature.

The Flaw: A confounder is a continuous, multi-dimensional causal concept. If you use it directly for routing, the agent must perform semantic matching: *"Is the current GPU tier 'close enough' to the historical GPU tier to justify a wormhole?"* This introduces thresholds, binary logic, and drift — too computationally heavy for a live RECALL state. To achieve "quantum speed" traversal, the causal reality of the confounder must be flattened into structural math. This is the Hex Progression:

### Step 1: The Hash Signature (The Exact Address)
The 4D confounder state (x, y, ξ, u, domain, capability) is hashed into a flat string (e.g., `a1b2c3d4`).
Effect: eliminates semantic matching. The hash is a rigid, exact-match coordinate address. If the current state hashes to `a1b2c3d4` and a historical node is tagged with `a1b2c3d4`, the wormhole opens instantly — O(1) lookup, no reasoning required.
Practical note: continuous state rarely hashes to an exact match unless quantization is coarse — in practice, most Tier-1 traffic will land on Step 2, not Step 1. Worth instrumenting the hit-rate split once live.

### Step 2: Hexagonal Spatial Binning (The Neighborhood)
If the exact hash hasn't been minted yet, the 4D state is mapped into a grid of hexagons — the hash represents a *cell*, not a single point.
Effect: if the exact hash misses, the agent checks the 6 adjacent hex cells. Hexagons tile without gaps and have uniform neighbor distance (no diagonal distortion), so the hex bin becomes the spatial neighborhood, pulling the local topology of a confounder region in one jump.

### Step 3: The Hyperedge (The Landmark Tunnel)
A standard DAG edge connects two nodes. A Hyperedge connects three or more at once — e.g., `[Live State Hash, Landmark L, Target Node A]`.
Effect: the Hyperedge is the structural claim that Distance(A→L) + Distance(L→B) approximates the true path distance, bypassing dynamic path calculation — valid to the extent the underlying space is metric (see caveat, Section 0).

### The Unification
The Confounder is the physics causing the variance spike. The Hex/Hash/Hyperedge structure is the math that lets the agent traverse that spike at near-zero computational cost. The Hex Bin provides the speed; the Hyperedge provides the structure; the Beta-Bernoulli score provides the intelligence.

---

## 3. Two-Tier Query (Hex-Updated)

**Tier 1 — Hash & Hex Bin Lookup (The Quantum Hop).**
Every node is tagged with its Hash Signature and placed in a Hex Bin at write time. On a RECALL, hash the current confounder state. If the exact hash exists, pull it directly. If it misses, pull from the adjacent hex cells. All retrieved nodes are connected via Hyperedges to the regional Landmarks. O(1) teleportation.

**Tier 2 — Weighted Graph Walk (Fallback only).**
If the hex bin and its neighbors are empty — a confounder combination nothing has been tagged with yet — fall back to a random-walk-with-restart from the current NBL coordinate, hopping along edges weighted by posterior × recency-resonance. This is how *new* confounders get discovered, per Section 2 of the original blueprint ("confounders are discovered by observing mediator variance"). Every successful Tier 2 walk should mint a new Hash Signature and Hex Bin, so the same query is a wormhole next time.

There is no fixed similarity threshold for "close enough to wormhole." The threshold itself is scored the same way as everything else (Section 6) and drifts based on whether loose matches keep paying off. A hardcoded similarity cutoff here would reintroduce exactly the binary gate this architecture exists to remove.

---

## 4. Per-Node State (Minimum Fields)

```
Node {
  id                      # NBL coordinate, e.g. CORE:473
  hash_signature          # Flattened 4D confounder state for O(1) Tier 1 matching
  hex_bin_id              # Spatial bin ID for topological neighborhood fallback
  created_ts
  last_activated_ts
  activation_log          # timestamped list or decayed count, NOT a fixed window
  amplitude               # current resonance energy (see Section 5)
  scorecard: { alpha, beta }   # Beta-Bernoulli on Hyperedges (see Section 6)
  hyperedges              # List of multi-node connections [Live_State, Landmark, Target]
  hub_score                # Rolling aggregate: how often this node is a useful bridge across DISTINCT hex bins, blended across both directions of travel (see Section 5a, 7a)
  elevation               # continuous 0..1, landmark-ness (see Section 7)
}
```

No `window_size` field. Recency is read directly off `last_activated_ts` vs `created_ts` — the oscillator math uses the gap, not a configured lookback range.

---

## 5. Resonance (Amplitude) Update

Model each node/wormhole as a driven-damped oscillator, consistent with the Caducean engine already in use:

- **Drive:** each activation (this node was recalled AND used) injects energy proportional to how useful that recall turned out to be — a positive scorecard outcome drives harder than a neutral or failed one. A recall that resolves a large |u| oscillation injects more energy than a minor clarification. Note the qualifier: recalled-and-used, not merely returned by a query. Energy for being retrieved rather than for being useful is how a popularity loop starts.
- **Damping:** NOT a fixed per-node coefficient. Damping is *derived* from coupling — a node strongly coupled to other resonant neighbors decays slower (energy is sustained by transfer); a node with heavy usage but weak/no coupling to useful neighbors decays faster regardless of its own traffic. **This is the non-bias correction: raw usage frequency is not trustworthy on its own; throughput to other useful nodes is what should be rewarded.** Without this the graph converges on whatever was popular early rather than on what actually bridges.
- **Birth energy:** the one deliberately arbitrary constant in the system. New nodes get a flat starting amplitude sized to survive roughly 30 days without any activation before decaying toward dormancy — an initial condition, not a behavioral rule, giving new nodes room to prove themselves before coupling-derived damping dominates. It is called out as arbitrary so it stays a measured target (Section 10) rather than quietly becoming a tuned constant nobody revisits.
- **Dormancy, not deletion:** when amplitude decays near zero, the node is pruned from the active working set (**the same DCP mechanism as Section 1 of the original blueprint — not a new pruner**) but the record — scorecard, coupling history, signature — persists untouched. If a matching confounder reappears later, the node re-resonates from where it left off rather than starting cold.

---

## 5a. Coupling Strength: Seed Prior + Observed Bridge

Coupling between nodes is not purely derived nor purely assigned — it needs both:

- **Seed value (the "why," assigned at birth):** when a node is created, its initial coupling to existing nodes is set from confounder-signature overlap alone — a structural prior, before either node has been used together in practice. This lets a brand-new node start with *some* coupling rather than isolation, **which matters given Section 5's damping rule: coupling-starved nodes decay fast regardless of usage.** Without a seed, every new node would be born into the exact condition that kills it fastest.
- **Observed bridge (the "why," earned over time):** actual co-activation frequency — how often the two are genuinely pulled together in real recalls — accumulates independently and gradually outweighs the seed as evidence builds. Same prior-to-posterior shape as the scorecard in Section 6, applied to coupling strength instead of node success.

```
coupling(a, b) = blend(seed_coupling(a, b), observed_co_activation(a, b), weighted by observation count)
```

The two are allowed to diverge, **and the divergence is itself a signal worth watching**. A high seed / low observed pair means two nodes look structurally related but rarely turn out to matter together in practice — **usually an indicator that the confounder tagging is coarser than the real causal relationship**. That reading is the actionable part: the divergence does not just say "these drifted", it says *the signature is lumping together things the world treats differently*, which points at the tagging rather than at the pair. Exactly the kind of drift Level 3 (Meta-Learning) should surface and correct over time, the same way it already owns the wormhole-match threshold.

A third seed source: when a node has an established `hub_score` (Section 7a) from bridging well elsewhere, that general connector reputation can seed its coupling to a brand-new landmark higher than confounder-overlap alone would justify — a node that's reliably good at bridging tends to stay good at bridging, independent of the specific pair.

---

## 6. Scorecard (Beta-Bernoulli) on Hyperedges

*Critical Update:* previously, the scorecard was applied to individual confounder strings or hex bins. Scoring the entire Hex Bin creates a "Blind Trust" issue — if a bin contains 100 nodes and 1 is brilliant but 99 are useless, a string of failures tanks the bin's score and blinds the agent to the one brilliant memory trapped inside.

**The Solution:** the Beta-Bernoulli score is placed directly on the Hyperedge connecting the Live State Hash, the Landmark, and the Target Node.

- Recall leads to a COMPLETED outcome that resolved the confounder → `alpha += 1` on the Hyperedge.
- Recall leads to no improvement or a FAILED outcome → `beta += 1` on the Hyperedge.
- Posterior confidence = `alpha / (alpha + beta)`, **naturally humble on low sample counts — a node used twice at 100% is not trusted the way a node used 40 times at 90% is.** That humility is the whole reason for a Beta-Bernoulli rather than a running average, and it is what Section 7's lower-bound elevation test depends on.
- Edge cost for path composition (Hyperedge chaining, Section 7) = `-log(posterior)`, not the raw posterior — additive along a path, and consistent with standard shortest-path math over probabilistic edges.

The Hex Bin is just the spatial container. The Hyperedge is the actual structural wormhole, and *that* is what gets scored — this lets the system learn which specific wormholes inside a spatial neighborhood are the real shortcuts, without discarding the whole neighborhood when one wormhole is a dead end.

The wormhole-match threshold (how loose a Hex Bin boundary is allowed to be) uses this identical mechanism, scored as its own edge-like entity: **loose matches that keep paying off drift the threshold looser; loose matches that keep misfiring drift it tighter.** This is the existing Level 3 Meta-Learning loop from the original blueprint (Section 4) pointed at this specific threshold — **not a new mechanism**.

---

## 7. Landmark Elevation via Triangle Inequality

A wormhole is promoted to landmark status — moved from the transient edge-weight layer onto the fixed 3D (X, Y, Z) trajectory axis as a pillar — when:

```
elevation = f(posterior_lower_bound_of_hyperedges, coupling_to_resonant_neighbors)
```

- Uses the *lower* confidence bound, not the raw mean, so a lucky small sample doesn't get promoted.
- Coupling term is weighted by neighbor resonance, not raw neighbor count — **being coupled to two thriving landmarks counts for more than being coupled to ten dormant nodes.**
- Elevation is continuous, **not a flag**, and can fall as well as rise. **A landmark that stops earning its keep — contradicted by newer high-confidence results, or simply unused long enough to lose coupling-sustained energy — settles back down to ordinary wormhole status rather than persisting as a stale fixed truth.** A pillar that cannot fall is an assumption, not a measurement.

With Hyperedges, this is mathematically rigorous by construction (see Section 0) — the Triangle Inequality holds for the coupling graph regardless of hex geometry, as long as edge costs are composed as `-log(posterior)` rather than summed as raw probabilities. A Landmark only gets elevated if the composed cost of all Hyperedges passing through it clears the threshold.

Directionality is worth deciding explicitly: coupling A→L is not guaranteed equal to L→A (usefulness need not be symmetric). This does not require a separate design mechanism — it falls out naturally from scoring each Hyperedge only in the direction it was actually traveled. A→L only accrues a tally when the agent stands near A and reaches L; L→A only accrues one on the reverse trip. An untraveled direction is not missing data, it's simply an unasked question — and if that direction is ever needed later, it falls through to the Tier 2 walk (Section 3) the same as any unscored path, discovering and scoring it for the first time.

---

## 7a. Hub Landmarks: A Second Elevation Axis

Section 7's elevation criteria rewards *depth* — a node that is a highly reliable destination for one specific target. There is a second, distinct way a node earns permanent-pillar status: *breadth* — being a consistently useful bridge across many different hex-bin neighborhoods, even when no single connection is the strongest available. A node can be the weaker half of any given coupling pair and still be structurally valuable, the same way a highway interchange doesn't need to be anyone's destination to be indispensable.

This is tracked via `hub_score` (Section 4) — a rolling aggregate of how often a node functions as a useful waypoint across *distinct* bins, blended across both directions of travel it has been used in. Because it is an aggregate over many separately-directional edges, `hub_score` naturally behaves as a bidirectional summary signal without requiring any individual Hyperedge to be forced symmetric — that resolution from Section 5a/6 stays intact; this is a coarser signal built on top of it, not a reversal of it.

**Why this matters operationally:** a graph that only ever elevates and routes through Resonance Landmarks (Section 7) is brittle — one dominant path per region, no alternates. Hub Landmarks give the system secondary, moderate-but-well-connected routes that remain available even when the top-scored path is unavailable, contested, or hasn't been discovered yet for a given query. They also feed back into Section 5a as a third seed source for brand-new coupling relationships (a node with a strong hub reputation elsewhere gets seeded higher on a fresh pairing than confounder-overlap alone would justify). Once elevated, other walks reach that region of the graph by hopping to the nearest landmark first, then triangulating from there — shrinking the effective search diameter (the ALT / landmark-pathfinding pattern).

---

## 8. Why This Matters Beyond Performance

Even absent a measured speed or accuracy gain immediately, this is a structurally different way for an agent to search its own memory during live generation — not a vector-similarity lookup run once before the response, but a continuously-updating, physics-governed resonance field that the agent's own streamed reasoning perturbs and reads from in real time. The recall step becomes part of the thought, not a preamble to it.

---

## 9. Recall Surface Format: Ontology-Consistent, Empirically Tuned

A RECALL that surfaces useful history but presents it inconsistently gets pattern-matched as noise and ignored by the agent's own downstream reasoning — **regardless of retrieval quality**. Perfect recall rendered inconsistently is indistinguishable from no recall. The fix is not choosing a good format; it is rendering the surface **directly from the node schema (Section 4) every time, so the agent learns to recognize a stable shape rather than parse variable prose.** Fixed fields, fixed order:

```
[RECALL @ hex_bin_id]
  tier: hash | walk
  hyperedge_posterior: alpha/(alpha+beta)
  last_activated: <relative time>
```

What's genuinely open — and should be treated as a test, not a design decision — is verbosity and default visibility. This is measurable directly: does the agent's subsequent reasoning actually use what was surfaced, or does it proceed as if the block weren't there. That usage/ignore signal is itself a candidate input to the scorecard on the RECALL mechanism as a whole.

---

## 10. Open Questions for Future Exploration

*(Note to the next AI agent: continue using the vocabulary established in the original blueprint and this addendum — DAG, fan_trace, Treatment/Mediator/Outcome/Confounder, Hex/Hash/Hyperedge topology, wormhole, landmark, resonance/amplitude, coupling-derived damping. Areas still open:)*

Each question below now carries a PROPOSED answer with its known problems attached. These are
candidates, NOT settled: three of the four still contain constants this document itself says must be
measured, and the telemetry that would set them does not exist yet. Recorded so the reasoning is not
lost — not so it can be implemented as-is.

### Q1 — The Drive Function (energy injection)
**Proposed:** do not subtract amplitude on a failed recall. Let the beta increment raise the damping
coefficient for that specific hyperedge context only, and make the drive a function of the variance
spike being resolved: `Drive = k · |u_spike| · posterior`. High posterior + large spike → large
energy; failed context → drive approaches zero while baseline amplitude is untouched elsewhere.

**Structure is sound. Two corrections and one tension:**
- **Use the posterior LOWER BOUND, not the raw mean `α/(α+β)`.** As written, a node at α=1, β=0
  scores 1.0 and receives MAXIMUM drive on its very first success. That is precisely the lucky-small-
  sample failure Section 7 guards against when promoting landmarks — so the document would be
  cautious about promotion while being maximally generous about energy, on the same evidence. Make
  both use the lower bound or neither.
- **Bound `|u_spike|`.** It is unbounded in principle, and drive is linear in it, so a single extreme
  oscillation can inject arbitrarily large energy and permanently distort the field. Cap it or pass
  it through a saturating function.
- **TENSION TO INSTRUMENT, not to resolve on paper:** drive ∝ posterior, posterior grows with
  successful use, use requires retrieval, retrieval favours amplitude. That is a rich-get-richer
  loop. Section 5's coupling-derived damping exists *specifically* because "raw usage frequency is
  not trustworthy on its own" — and this drive function partially reintroduces usage-proportional
  reward. Whether damping dominates is an empirical question. Measure it; do not assume it.

**ADOPTED DIRECTION — separate BUSYNESS from USEFULNESS; do not average them.**
The rich-get-richer tension exists because activation frequency and recall quality are currently
tangled into one number, which makes a popular-but-useless node indistinguishable from a genuine
highway. Keep them as TWO readings on the node:
```
             |  USEFUL (high posterior)   |  NOT USEFUL (low posterior)
  BUSY       |  genuine highway           |  TRAP — pulled in constantly, never helps
  QUIET      |  specialist — rare, good   |  dormant, let it decay
```
The BUSY/NOT-USEFUL quadrant is the one that cannot be seen today and is the one that actively costs
the agent — it looks identical to a highway because both are busy.
- **Do NOT collapse the two into a single averaged score.** Averaging re-merges exactly what the
  split was for: a very busy useless node and a rarely-used excellent one can land on the same mean.
  The policy reads both axes; the two are not summed. (Heart rate and blood pressure are kept
  separate for the same reason.)
- **A QUIET node must not be penalised for rarity.** A specialist recalled twice a year and right
  both times is valuable; the split is what makes that expressible.
- **Bounded/ranged, per Q1's correction above** — this also fixes the unbounded `|u_spike|`.
- **Classification is PER COORDINATE REGION, not global.** A node can be a highway in one region and
  irrelevant in another. This is deliberately the same principle as DER spec REQ-26 (a mediator's
  score is region-scoped because a tool that works in one place may fail in another) applied one
  layer up. Keep the two consistent.
- **DO NOT pre-define the frequency bands or their classifications.** The quadrant above costs
  nothing and is self-evident. "N bands, each classified per plane" is a large structure invented
  before any data exists — let the bands fall out of the observed distribution (Q4's discipline).

### Q2 — The Blending Curve (seed vs observed coupling)
**Proposed:** sigmoid handoff, `weight_observed = 1 / (1 + exp(-k · (n − crossover)))`, crossover
around n=5, so the seed dominates early and observed reality takes over sharply once evidence exists.
Reasoning: linear blending lets the seed bias the system for too long.

**The reasoning against linear is correct, but there is a better answer that removes both constants.**
A Beta-Bernoulli posterior ALREADY encodes "how much evidence do I have" in its pseudo-counts.
Express the seed coupling as a Beta PRIOR (α₀, β₀) sized to how much the signature overlap is worth,
then let observed co-activations accumulate on top. The handoff becomes automatic — the prior
dominates while counts are low and is naturally swamped as they grow. No sigmoid, no crossover point,
no steepness parameter `k`, and it reuses the exact conjugate machinery already used everywhere else
in this document rather than introducing a second mechanism for the same job.
KEEP THE SIGMOID ONLY IF a deliberately SHARP cutover is wanted rather than a gradual one — that is
the one behaviour the prior formulation cannot express. Otherwise it is two tuned constants
(`crossover`, `k`) doing work one prior already does.

**ADOPTED: prior-weighted, not switched.** The seed is expressed as "this structural hunch is worth
about N observations of evidence"; real co-activations accumulate on top and naturally outweigh it.
Nothing schedules when to stop trusting the seed.

### Q2a — THE GOVERNING PRINCIPLE: scoring/polling instead of constraints
This is a PRINCIPLE, not a mechanism detail, and it governs the whole document.

**Statement:** wherever the system needs a value — a threshold, a weight, a ranking, a cutover point
— do NOT hardcode it and do NOT constrain it in advance. Apply the scoring/polling mechanism to it
and let the correct measurement REVEAL ITSELF from evidence. That revelation is the emergence. The
principle is not "add feedback and emergence happens"; it is "refuse to fix the value, score it
instead, and the system tells you what the value actually is."
Everything in this document is already an instance of it: the wormhole-match threshold is scored
rather than set (Section 6); coupling is seed-then-observed rather than assigned (Section 5a); the
hex quantization is instrumented rather than engineered (Q4); landmark elevation is a continuous
measured quantity rather than a flag (Section 7). Same move, applied five times.

**THE ONE GUARD — and it is not optional.** A scoring loop faithfully optimises whatever it is
pointed at. If the scored signal is not the thing that actually matters, the loop will produce a
confident, self-consistent, wrong answer — and it will look healthy the whole time. This project has
a live example of exactly that in its own code (bootstrap/GOALS.md, DER outer loop):
> *the outer loop currently accepts ANY proposal that raises natural-exit rate — precisely the
> single-metric reward-hacking the gate was written to prevent*
That is feedback working perfectly and yielding garbage, because the measured signal was a proxy.
So the principle in full: **refuse to hardcode, score it instead, AND verify that what you are
scoring is the real thing.** The verification is the load-bearing half. Three known failure shapes
when it is missing — oscillation (no deadband, see Q4 hysteresis), runaway (rich-get-richer, see Q1),
and lock-in (converging early and never exploring).

**VOCABULARY:** call this act POLLING or VOTING — never "treatment". Treatment is already taken in
the causal vocabulary (the objective handed to a node, per the original blueprint Section 2). Reusing
it for the act of scoring would collide with the DAG's own terms, the same class of drift as
`related_to` vs `relevant_to`. What is being described here is a repeated FORMULA inside the DAG:
accumulate votes on an outcome, derive the measurement from the tally.

### Q3 — Hub Score Formula
**Proposed:** `hub_score = count(distinct_hex_bins_bridged) · min(posterior_lower_bound across those
bridges)`, so a node bridging 10 bins on terrible posteriors is correctly scored as a connector to
nowhere. Using the lower bound is consistent with Section 7 — good.

**The intent is right; the `min` is brittle.** One weak bridge among twenty strong ones drags the
whole score down to that weak bridge's value. A node that bridges twenty territories excellently and
one poorly then scores as though it were uniformly poor — which is not "reliably useful across
diverse territories", it is "judged entirely by its single worst connection", and it lets one bad
bridge permanently suppress an otherwise excellent hub.
**ADOPTED — do not aggregate at all; score PER DESTINATION.** Both the `min` and the alternatives
first considered (a low quantile, or counting bridges above a floor) are still trying to squash many
bridges into one number, and every such collapse is fragile in some direction. The correct move is
that **a connector is only good relative to a particular destination**, so the score lives on the
(connector → destination) pair, keyed by that destination's hash. Heathrow's one bad route is scored
badly FOR THAT ROUTE and never touches the other two hundred. No aggregation, nothing to be dragged
down by.

**The hub layer is COMPARATIVE, not absolute.** Its purpose is not to assign a connector an intrinsic
quality number; it is to establish, relative to other connectors, which ones are reliably good across
the destinations they actually reach — a network of good connectors as its own layer. An interchange
is never "good" in the abstract, only good compared with the alternatives.

**STORE FINE, DERIVE COARSE.** The per-destination scores are the stored truth; any hub number is a
VIEW computed from them. A summary can always be re-derived from detail; detail can never be
recovered from a summary. This also means the aggregate formula can be changed later (average,
count-above-floor, quantile) without losing or migrating anything.
Decay still applies to the per-destination scores — a connector that bridged widely two years ago and
nothing since should not still rank in the hub layer.

### Q4 — Tier-1a / Tier-1b Hit-Rate Split
**Proposed — and this is the strongest of the four, because it refuses to guess:** do not engineer
the hash quantization upfront. Start coarse (e.g. 4D floats rounded to 1 decimal) so Tier-1a exact
hits occur at all, instrument the ratio, and adjust: below ~5% Tier-1a, widen; above ~80%, the space
is too coarse (noise) so tighten. The band is an instrumentation target, not a law.

**Two additions it needs:**
- **Hysteresis.** As written the loop oscillates: tighten → hit-rate falls below 5% → widen →
  hit-rate jumps above 80% → tighten. Require a minimum observation count before any adjustment and
  bound the step size.
- **RE-QUANTIZATION INVALIDATES EVERY EXISTING HASH — and this is the load-bearing one.** Change the
  quantization after history accumulates and previously minted signatures point at bins that no
  longer correspond to anything. So bin size is NOT freely tunable once the graph has data: it is
  cheap to change now and expensive later. Decide the migration story before the first bin is
  written — either accept a one-time re-binning pass, or version the hash so old and new coexist.
  This is the reason Q4's empirical loop cannot be deferred indefinitely: the loop needs data, but
  the data makes the loop costly to act on.

**ADOPTED SOLUTION — scheme version + lazy re-file on retrieval.** Timestamps alone are NOT
sufficient: knowing WHEN a node was filed tells you WHICH scheme minted its hash, but it does not
make that node findable under a new scheme. The timestamp supplies the information to fix things; it
is not itself the fix. The minimal complete answer is one extra field:
- Store the **quantization scheme version** on each node alongside its hash signature (one integer).
- On retrieval, if a node's scheme version is older than the current one, **re-hash it under the
  current scheme and update it in place**.
Nodes that get used migrate themselves; nodes that never get used never migrate — and those were
heading for dormancy anyway (Section 5), so nothing is spent on memory that does not earn it. No
big-bang migration, no downtime, no data loss, and re-binning stops being a one-way door.
This is the postal-code problem solved by re-labelling each file the next time it is pulled from the
cabinet, rather than closing the office to re-label everything at once. It composes with dormancy
rather than fighting it, and it is the version to prefer on the "simple, and will not cause future
problems" test.

### Still genuinely open (no proposed answer yet)
- **Instrumentation:** minimum logging to validate the 30-day birth-energy constant, the
  Tier-1a/1b hit-rate split, and recall-surface verbosity against actual downstream usage.
- **Elevation thresholds:** what makes a node a Hub Landmark versus a Resonance Landmark versus both
  at once (Section 7 vs 7a).
- **Mid-stream RECALL mechanics:** how the bounded query in Section 1 runs without becoming
  synchronous work on the critical path. UNRESOLVED AND BLOCKING — this is the exact defect shape
  already fixed three times in this codebase (a blocking write on a hot path making completed work
  look hung). Needs a stated deadline and a defined behaviour on expiry before any implementation.
