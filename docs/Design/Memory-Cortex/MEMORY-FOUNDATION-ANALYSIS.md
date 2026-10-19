# IRIS Memory Foundation — analysis and growth design

Status: ANALYSIS + PROPOSAL for owner review, 2026-10-18. Read-only throughout: code read, live
`data/memory.db` queried with `mode=ro`, nothing written. Every number below was measured on the
live store on 2026-10-18 unless marked *code-read* (found by reading code, not run) or
*UNVERIFIED*. Companion: `MEMORY-DASHBOARD-DESIGN.md` (this folder) §16.

Sources: `docs/CADUCEAN_ARCHITECTURE.md`, `docs/CADUCEAN_TECHNICAL_OVERVIEW.md`,
`docs/Design/EVENT_TAXONOMY.md`, `docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md`,
`specs/wormhole-aperture/`, `specs/der-dag-inversion/ontology.md`,
`backend/memory/mycelium/*.py`, `backend/memory/event_alphabet.py`,
`backend/agent/caducean_trajectory.py`, `backend/gateway/iris_ffi.py`.

---

## 0. In one paragraph

The design is organic and coherent: one operator — *expand where outcomes disagree, compress
where they agree* — already shapes execution (split width), the session (context compression),
cross-session tuning, and the Mycelium graph (condense / expand). Growth of sectors (topic
domains) and of coordinate spaces should be that same operator, not a hand-edited list. **But the
seed is not yet alive.** On live data the coordinate graph has never been walked: 116 nodes, every
access count 0, every traversal empty, 0 routing edges, a closed maturity gate, inert resonance,
merges that zero their own scores. One closed gate near the root starves everything downstream.
So the foundation work is, in order: make the seed breathe, make the registries data-driven, then
let sectors and spaces grow by the operator — in shadow first, as the Oracle does.

---

## 1. The one idea, applied to memory

> "Compress everything that happened into one honest current position, then let moment-to-moment
> behavior be a pure, memory-free reaction to that position." (CADUCEAN_ARCHITECTURE §1)

The Caducean state Σ = (x, y, ξ, u) — expansion accumulator, compression accumulator, phase angle,
attentional velocity — is that position for the *work*. Mycelium does the same for *memory*:
thousands of outcomes become one edge score; routing reads the score, never the history. And the
graph "reshapes itself — condense merges near-duplicate nodes, expand splits a node when its
outbound hit/miss variance exceeds 0.40. That is the Caducean duality at graph scale"
(CADUCEAN_ARCHITECTURE §8).

The physics adds two rules that matter for growth:

- **Wall-pair closure.** The topological charge Q = (x − y)/(x + y + 1) must return toward 0 for a
  natural exit; "a lone kink — a session that only expands, never compresses — is topologically
  forbidden" (OVERVIEW §5). Measured: natural exits |Q| 0.53, budget exits 0.91.
- **Windings give identity.** ξ = l·x − m·y (mod 2π); each execution domain has its own winding
  (der (1,1), voice (2,1), research (3,3)) and therefore its own cycle speed
  c_eff = c·√(l² + m²). "The physics is universal; the interpretation is local."

**The organic rule for this foundation:** anything that grows (a sector, a landmark, a chain) is
born by expansion and survives only by closure through compression — outside evidence that it
holds. Anything that only expands and never closes folds back into its parent. This is the
landmark rule (candidate → proven by ≥ 2 outside-evidence sessions) generalized, and it is Q → 0
applied to structure.

---

## 2. What the memory is made of (map)

### 2.1 Seven layers of meaning, and how fast each may grow

| Layer | What it is | Today | How it should grow |
|---|---|---|---|
| **Alphabet** | closed lattices: family 9, valence 3, actor 5, evidence 8, cause 27, outcome 27, trigger (EVENT_TAXONOMY §3) | code `event_alphabet.py`, schema_version 1 | **never** — only an owner-approved schema_version bump |
| **Vocabulary** | open words: labels, tools, bars | seed labels in code, Layer 3 counts unknowns | data edits from evidence (exists) |
| **Coordinate spaces** | the profile of the user and the machine: conduct, domain, style, chrono, context, capability, toolpath — each in a Kyudo trust zone | `SPACES` dict in code + a `mycelium_spaces` table | **deliberately**: a reviewed registry row, never auto-minted (a space is a new dimension of meaning) |
| **Sectors** (topic domains) | what a thing is ABOUT: 13 registry keys (ai, web, data, devops, mobile, systems, security, finance, science, design, hardware, gaming, general) | `DOMAIN_IDS` constant; keyword classifier | **organically**, evidence-gated (§5) |
| **Modes** (execution domains) | HOW a thing runs: der, voice, research — each with its own windings | derived from the path, not text | when a new execution path exists (rare, code) |
| **Landmarks** | a claim proven true by outside evidence, anchored to a cluster of coordinate nodes | candidate → landmark → permanent; merge at Jaccard ≥ 0.5 | organically (exists, but starved — §3) |
| **Time** | Immortus chain (transitions + references), trajectories, episodes, events | append-only | by work (exists) |

The physics Σ sits across all of them: it is the *position of the work* when anything happens.

### 2.2 The word "domain" means six things

1. **Topic domain** — what a node is about (registry, 13 keys). → call it a **sector** (the
   owner's word) in docs and UI.
2. **Execution domain** — how it runs (der / voice / research, with windings). → a **mode**.
3. The **`domain` coordinate space** — the user's expertise: (domain_id, proficiency, recency).
4. The **phase domain** of the scheduler (`decision.oracle_cpu`, `execution.der_nodes`).
5. A **web domain** (a site, REQ-33).
6. The **`caducean_trajectories.domain`** column — constant `general` on all 7,089 rows (a bug, §3).

Keeping one word for six meanings is how "domains" stayed half-built: each writer meant a
different one. The registries below use *sector* and *mode*; "domain" stays only as the name of the
coordinate space.

### 2.3 How they interweave

```
event  = said in the ALPHABET, with a LABEL, about a SECTOR, run in a MODE, at a Σ position
  └ touches coordinate NODES in SPACES (through Kyudo: trust channel → zone → allowed spaces)
       └ LANDMARKS condense clusters of those nodes (≤ 6 nodes, across spaces) once proven
            └ a SECTOR is (a) a region of the domain space and (b) the set of landmarks it holds
                 └ the other SPACES describe how work in that sector happens (its profile:
                   which tools, what time, which style, which project)
```

Landmarks are the **knots** that tie sectors and spaces together: each landmark belongs to one or
more sectors (weighted) and carries a cluster across spaces. A sector's *profile* is the centroid,
per space, of its landmarks' clusters. That is the interweave, and it is what the 3D cortex draws:
territories (sectors) on the skin, neurons (landmarks) inside, tracts between them, and the
spaces as the layers a neuron's cluster spans.

---

## 3. Measured state: the seed is not yet alive

| Value | Live (2026-10-18) | Effect |
|---|---|---|
| Coordinate nodes | 116: toolpath 101, domain 7, capability 4, style 3, conduct 1, **chrono 0, context 0** | the profile barely exists |
| Node access_count | **0 on all 116** | every "most-used" choice is insertion order |
| Spaces with a node at confidence ≥ 0.6 | 2 (capability, toolpath); maturity needs 3 (`interface.py:339-356`) | **gate closed** → `get_context_path` returns "" |
| Traversals | 3,025, **path empty on all 3,025**; outcomes partial 2,649, miss 354, success 22, hit 0 | navigation never returns a node |
| Routing edges (`mycelium_edges`) | **0** | expand cannot run; decay has nothing to act on |
| Episode index | 2,841 rows, **node_ids empty on all** | resonance is inert |
| Toolpath success_rate | **one value on every node** | zero variance |
| Landmarks | 2,701 rows; max activation 3; **cumulative_score 0 on 2,581** | permanence (8) and topology origin (12) unreachable |
| Merges | 2,480; merged score = activation-weighted mean, and both activations are 0 → score 0 (`profile.py:105-111`) | every merge erases the score |
| Landmark edges | 6,628, all `similarity`, score 0.4, last_traversed NULL | never decay, never learn |
| Landmarks with a sector | 0 (no column) | the cortex cannot place them |
| Event addresses | 11,887 events → **291 distinct** addresses | address ≈ "how many steps in", not the state |
| Σ inside an event | `sigma_from = sigma_to` on all 11,887 | no event records a transition |
| Trajectory rows that never compressed | **4,068 of 7,089 have y = 0** | balance pins at its 3.0 ceiling in those sessions (formula, *code-read*) |
| u | spread −1…1, mean 0.17, 335 distinct values | u is a real signal now (good) |
| `caducean_trajectories.domain` | `general` on all 7,089 | the per-domain physics has one bucket |
| `memory_chain.coords_from` | filled on 14,318 of 29,773 | the documented "honest gap" is half closed (good) |
| Sector values | `memory_chain.topic_domain` 12 real values on ~23% of rows; `memory_events.topic_domain` NULL ~90% | sectors exist, mostly unwritten |

### 3.1 The cause chain (why it is inert)

One closed gate near the root starves everything below it:

1. **Spaces are barely fed.** Extractors are keyword-only; domain, style and conduct nodes get
   confidence 0.4; chrono and context are never written (*code-read*: `extractor.py`).
2. **Maturity gate stays closed** (2 of 3 spaces) → the context path is empty.
3. **Navigation finds no entry**: keyword-in-label fails, and the fallback wants confidence > 0.7
   but nodes have 0.4 (`navigator.py:138-145`, *code-read* line 414).
4. → **access_count never rises** → condense survivors, landmark top-6 clusters and merge
   survivors are chosen by insertion order.
5. → **landmark activations stay 0** → **merges zero the score** → permanence and topology origins
   are unreachable → charts, Z-trajectory and staleness are dormant.
6. Separately: **0 routing edges** (likely the compounding decay below, *UNVERIFIED cause*) →
   expand never runs, so the graph cannot grow by the operator at all.

### 3.2 The physics → memory couplings

- **u → decay is inert in production.** `apply_decay` modulates only when given a session; all
  three production callers of `run_maintenance()` pass none, so the multiplier is always 1.0
  (`scorer.py:236-249`; `memory/interface.py:611`, `main.py:1166`). CADUCEAN_ARCHITECTURE §8
  still marks it PROVEN.
- **Decay compounds.** Each pass subtracts `rate × days_idle` measured from `last_traversed`, and
  never moves `last_traversed` (`scorer.py:268-289`) — every pass re-subtracts the whole idle span.
- **EML → recall breadth** works (PROVEN), but balance pins at 3.0 whenever min(x, y) = 0, which
  is true for 57% of trajectory rows.
- **Σ → document address** is now half populated (coords_from 48%).

---

## 4. Contradictions to resolve first

1. **Are sectors hashed?** EVENT_TAXONOMY:54 says not; `event_alphabet.py:203` and Wormhole REQ-1
   hash them.
2. **Two sector registries**: `spaces.py:89-103` vs `docs/Mycellium Specifications.md:889-903`
   (different keys). The code list is the live one; the spec is stale.
3. **"Landmark" has three definitions** (activation-12 "never decays" in the Mycelium guide; a
   proven claim in the taxonomy; demotable/stale in CLM). The proven-claim definition is the one
   the code enforces.
4. **"Beta-Bernoulli" edges** (Wormhole REQ Decisions 2) vs the additive delta in `scorer.py:55-59`.
5. **NaN ξ or u crashes the address writer**: `int(nan)` raises outside the `try`
   (`event_alphabet.py:201-203`); the spec says "write unhashed".
6. **"hash_signature" names three different hashes** (state, event address, chain sequence).
7. `RECALL_AS_COGNITION.md` claims live integration; RecallPhases has no production caller.

---

## 5. Growth design (proposal)

### 5.1 Sectors as a living registry

**Shape (data, not code):**

- `mycelium_sectors(sector_key PK, parent_key, label, status, born_at, born_from, alias_of,
  members, outside_evidence, last_activity)` — `sector_key` is a stable text path
  (`systems/memory/recall`), **never** a number. `status ∈ {candidate, proven, dissolved}`.
- `mycelium_landmark_sectors(landmark_id, sector_key, weight, source)` — a landmark belongs to one
  or more sectors with a weight; `source ∈ {rule, cluster, user, oracle}` (only rule and user are
  evidence — EVENT_TAXONOMY §6).
- Seeded with the 13 registry keys as proven roots. The `domain` space's `domain_id` axis stops
  being `id/12` (which breaks at the 14th key); it stores a stable ordinal from the registry, and
  the 3D layout reads territories from the registry, never from that float.

**Lifecycle — the one operator:**

| Step | Operator | Rule (start values; tune by measurement) |
|---|---|---|
| **Birth** | expand | items that land in `general` (or a parent) and share terms recur in ≥ 3 sessions → a *candidate* child sector, in shadow |
| **Closure** | compress | a candidate becomes *proven* when it holds ≥ 2 landmarks with outside evidence from ≥ 2 sessions — the same gate as landmark promotion; the wall-pair closes |
| **Split** | expand | a proven sector whose landmarks' outcomes disagree (variance > 0.40, the node-expand threshold) splits into children |
| **Merge** | compress | two sectors whose landmark sets overlap ≥ 0.5 (the landmark-merge threshold) merge; the absorbed key becomes an **alias** so old addresses still resolve |
| **Dissolve** | fold-back | a candidate that only expands for a set time without closure folds back into its parent — a lone kink is forbidden |

**Bounds (growth has a budget):** depth ≤ 3, a cap on children per parent, candidates expire,
every transition is a `memory` event (`LANDMARK_*`-style labels: `SECTOR_BORN`, `SECTOR_PROVEN`,
`SECTOR_SPLIT`, `SECTOR_MERGED`, `SECTOR_DISSOLVED` — new *labels*, no new alphabet values).

**Trust (Kyudo):** only channels admitted to the TOOL zone may create a candidate; untrusted web
content may propose but never close a sector; the 30% untrusted cap applies to a sector's
evidence as it does to a landmark cluster.

**Shadow first:** sector assignment runs in shadow and is measured (precision of membership,
churn, false births) before any consumer reads it — the Oracle's own discipline.

**Landmark sector at creation (the immediate fix):** at `LandmarkCondenser.condense`, assign from
(1) `resolve_topic_domain(task_entry_label)` (the rule path research memory already uses), else
(2) the `domain` nodes in the landmark's own cluster (weighted), else `general`; backfill the live
landmarks with the same rule once, idempotently.

### 5.2 Coordinate spaces as an open registry

- The `mycelium_spaces` table becomes the source of truth. Each row declares: axes, ranges, decay,
  **Kyudo zone (required)**, render order, resonance participation, extractor, schema version.
- Everything hard-coded today is derived from it (each is a silent blocker for an 8th space —
  *code-read*): `_SPACE_ORDER` (`scorer.py:31-39`, a new space would never condense or expand),
  `RENDER_ORDER` and the renderer map (`profile.py:399-406`), `RESONANCE_SPACES`
  (`spaces.py:188-190`), `TASK_CLASS_SPACE_MAP` (`kyudo.py:525-532`), literal space names in
  `navigator.py` and `topology.py`.
- **Kyudo fails closed**: a space with no zone is refused, not filed in the REFERENCE zone
  (`kyudo.py:139` is fail-open today).
- **Per-space distance scale**: dedup 0.05 and condense 0.04 are global, so chrono (0–24) and
  capability (0–5) dominate distance; normalize each axis by its declared range.
- **A new space is added deliberately**, by a reviewed proposal, never minted — it is a new
  dimension of meaning. Sectors grow organically *inside* the spaces.

### 5.3 Addresses that survive growth

- Hash a sector's **root** plus the scheme version, and carry the refined path as a separate
  field; refining `systems → systems/memory` must not move an address.
- Do not hash raw step counts. Hash the *state*: e.g. the charge Q (binned), log-binned work
  volume, ξ and u bins. Decide this before Wormhole Stage A, with a lazy re-file (REQ-10).
- Make the NaN path return "unhashed", as the spec says.

---

## 6. Caducean Σ as the visual expression of the cortex

Each visual must be driven by the real value (a computed signal must change behaviour, and must
have a sane value — CLAUDE.md "hidden failures").

| Physics | Meaning | In the cortex | In the timeline (synapse view) |
|---|---|---|---|
| **x** expansion accumulator | generative work | the organism inhales: tissue extends, buds (candidate neurons / candidate sectors) appear | fibres fan out, the passage widens |
| **y** compression accumulator | validation / consolidation | exhale: tissue tightens, merges and absorptions are visible | fibres bundle tighter, the passage narrows |
| **ξ** phase angle | position in the cognitive cycle | the rotation phase of the inner shells and of the skin's pulse bands | the twist phase of the fibre bundles |
| **u** attentional velocity | momentum, explore (+) / compress (−) | flow direction (outward / inward); trails persist longer at u > 0, fade faster at u < 0 (the decay coupling, once live) | pulse speed along the fibres |
| \|u\| bands (0.5 / 0.85) | split zone / converged | a fan-out of sparks when \|u\| < 0.5 | the fibre bundle splits and folds back |
| **Q** charge | wall-pair balance | the two serpents of the caduceus: equal = closed, one dominant = strain | the closing of the passage at a natural exit |
| **balance / EML** | phase advance rate | breathing rate | travel rhythm |
| **c_eff** (windings per mode) | cycle speed of der / voice / research | — | each mode's threads twist at their own rate |
| band crossing | "settling" / "re-opening" | one pulse across the lattice | a synaptic release |
| TOPO violation | topological drift | an immune response: the quorum reorganization (Kyudo) | the passage tightens and flickers |

**Precondition:** the values must be honest first — events must record Σ transitions
(`sigma_from ≠ sigma_to`), and the 57% of sessions that never compress must be explained (are
those steps really all expansion, or is the classifier missing consolidating calls?).

---

## 7. What we have not yet considered (prioritised)

1. **The graph has never been walked** (§3.1). Nothing grows on it until the maturity gate, entry
   matching and access counting work. Highest priority.
2. **Merges erase scores** — fix: plain mean when both activations are 0.
3. **Decay**: pass the session's u (or the last settled position) into maintenance; decay
   incrementally from a `last_decayed_at`, not from `last_traversed`. Then measure why there are
   0 edges.
4. **Events carry no Σ transition**: write the before and after positions.
5. **The address is a step counter**: change what is hashed before Wormhole is built on it.
6. **"Domain" × 6**: adopt *sector* / *mode* in docs, specs and UI.
7. **Registries are code**: move sectors and spaces into tables (§5.1, §5.2).
8. **Zero-variance values**: toolpath success_rate, domain proficiency 0.5 / recency 1.0, landmark
   edge score 0.4 — each needs a real input or must stop being drawn.
9. **Episode index never records nodes** — resonance cannot work until it does.
10. **Growth budgets**: `caducean_trajectories` has no retention; sector minting needs bounds
    (§5.1); toolpath windows per session are unbounded (*code-read*).
11. **Kyudo zone default is fail-open** (§5.2).
12. **The hive network** (GOALS §7b): sector keys must be stable, versioned text so peers can read
    them; a remote sector enters only as a candidate and closes only on local evidence.
13. **Docs out of date**: CADUCEAN_ARCHITECTURE §8 (decay PROVEN), RECALL_AS_COGNITION, the stale
    sector list in the Mycelium specification, the "five" topology primitives (there are six).

---

## 8. Order of work (foundation first)

| Phase | Goal | Done when (measured) |
|---|---|---|
| **0 Measure & guard** | a curation/liveness report over the live store (the numbers in §3) | the report runs and each value has a guard that fails on today's state |
| **1 Make the seed breathe** | maturity, entry matching, access counts, merge score, decay, Σ transitions, episode-index nodes | traversals return nodes; access counts vary; merged scores ≠ 0; events record transitions |
| **2 Registries as data** | `mycelium_sectors` + landmark membership; spaces table as source of truth; Kyudo fail-closed; landmark sector at creation + backfill | every live landmark has ≥ 1 sector; an 8th test space works end to end in a test store |
| **3 Organic sectors, in shadow** | birth / closure / split / merge / dissolve running in shadow | precision and churn measured over real sessions |
| **4 Visuals on real values** | the cortex reads registries and Σ, not synthetic layout | every visual in §6 varies with its value on real data |
| **5 Hive-ready keys** | versioned, shareable sector keys; remote = candidate | — (later, GOALS §7b) |

## 9. Decisions (owner, 2026-10-18)

1. **Sector** (topic domain) and **mode** (execution domain): ADOPTED.
2. Sector registry + weighted membership + lifecycle: APPROVED, **in shadow mode** until its
   structure and place in the system are verified.
3. Growth speeds (alphabet never, spaces deliberately, sectors organically, labels as data): AGREED.
4. Make the seed live first: AGREED.
5. Change the event address, and build whatever else makes `specs/wormhole-aperture` easier to
   implement later: APPROVED.

## 10. Work order (approved 2026-10-18) — each item carries its scope bound

Method: CLAUDE.md "BUILD + VERIFY IRIS — THE MEASURED LOOP". Targeted tests only; a guard that
fails on the old state for every measured fix; values checked on the live store read-only.

| # | Item | DONE = | NOT THIS = |
|---|---|---|---|
| W1 | **State address v2** (`event_alphabet.hash_signature`, scheme 2): x, y enter as the charge Q (5 bins) and the work volume (log2, 6 bins), not raw counts; ξ and u bins kept; the sector ROOT and the mode; NaN or inf → no address (logged, counted); a `hex_bin_id` minted from the same quantized state (Wormhole REQ-2 AC1; Tier-1b querying stays deferred) | new events carry scheme 2 + a hex bin; addresses no longer grow with step count (guard); NaN cannot raise | no bulk re-hash of old rows (REQ-10 AC4); no Tier-1b lookup; no hyperedges |
| W2 | **Σ transitions on events**: every writer passes the position before AND after the step | `sigma_from ≠ sigma_to` where the step moved Σ (guard) | no new Σ source; reuse the DER lane's before/after |
| W3 | **Merge keeps the score** (`profile.py`): plain mean when both activations are 0 | a merge of two unactivated landmarks keeps a non-zero score (guard) | no backfill of the 2,480 historical merges in this item |
| W4 | **Decay = the counterpart of growth (§11)**: incremental from a `last_decayed_at`; the evidence weight a(n) on decay as on growth; Kyudo channel and Caducean phase multipliers; node confidence decays to the stated floor; landmark edges on the same law; the reorganization is the law at m_quorum | two passes subtract once (guard); young and old beliefs cross at the same use frequency (guard); the phase multiplier varies on live data (measured 0.68-1.37 per day) | no change to the base rates or the prune threshold |
| W5 | **Why 0 routing edges** (Wormhole spec U3 / S54): find where the region-mediator write goes and fix it | a DER node step writes a `mycelium_edges` row on the live app (measured) | no new edge model (Beta posteriors are Stage A) |
| W6 | **The graph walks**: confidence grows with repeated observation; entry matching reaches the nodes that exist; spaces that are never fed get their feed | live traversals return nodes; access counts vary; maturity measured honestly | no lowered thresholds as the fix; no fake nodes |
| W7 | **Episode index records nodes** (follows W6) | new index rows carry node ids | — |
| W8 | **Caducean `domain` constant**: the trajectory row takes the node's real sector | trajectories show more than one sector on new rows | — |
| W9 | **Sectors, shadow mode**: `mycelium_sectors` + `mycelium_landmark_sectors`; landmark sector at creation (rule, then cluster, then `general`); idempotent backfill; lifecycle (birth / closure / split / merge / dissolve) computed and LOGGED, consumed by nothing | every live landmark has ≥ 1 sector; lifecycle decisions measured over real sessions | no consumer reads sectors yet (shadow); no auto-created space |
| W10 | **Spaces registry** as the source of truth. Each row declares its Kyudo terms (§12.3): write lock (the lowest channel that may write), render zone, subagent write owners, task classes, decay rate, confidence floor. An unknown space or channel fails closed | an 8th test space works end to end in a test store, including its Kyudo terms | no new real space |
| W11 | **Kyudo repairs (§12)**, built with W4: node channel + confidence caps + trust cap on the cluster; reorganization (scope, nodes, re-render, conflict log); threat fades per clean session; the suspension ends with the session | each has a guard that fails on the old code | the §12.2 items stay proposals until measured |

### 10.1 Status (2026-10-19)

W1, W2, W3, W8 committed (`04b8f858`). W5/W6/W7 committed (`7cd434e9`): the session region,
confidence that grows on recurrence, the chrono feed. W4 + W11 committed (`14e3452b`); the
active-day clock (§11.4) follows. Open: W9, W10, the live gate.


---

## 11. Growth and decay as one law (owner, 2026-10-19)

> "make sure there's an algo that is in alignment with the speed growth of the memory and decay
> together" — and "don't forget about the reorganization as well with the decay".

### 11.1 What was wrong (code-read; live values read-only)

- **Growth was weighted by evidence, decay was not.** An edge observation moves the score by
  `delta / (1 + n)` (REQ-26), so belief converges. Decay took `rate × days` whatever n was. A
  route with 100 proofs that was used once a day gained 0.05/101 and lost 0.02: it shrank while
  in use. The two halves ran at different speeds.
- **Decay compounded.** Each pass subtracted the whole time since the last traversal again.
- **Node confidence had growth and no decay** (after W6): repetition could only ratchet it up.
- **The physics coupling never ran.** The scorer asked the *store* for `get_latest_u`; only the
  interface has it, so the u multiplier was 1.0 on every pass, even when a session was passed.
- **Landmark edges are inert**: 6,628 rows, all score 0.4, traversal count 0, never traversed —
  nothing makes them grow. (A writer is still needed; the law is ready for it.)

### 11.2 The law (`backend/memory/mycelium/decay.py`)

For every learned strength s with evidence n (edge score; landmark-edge score with n = traversal
count):

```
growth  (an observation):  s += delta · a(n)            a(n) = 1 / (1 + n)
decay   (an idle span):    s -= rate · m · days · a(n)
m = m_channel (weaker endpoint, Kyudo Part 3) · m_phase (Caducean, over the span) · m_quorum
```

The net drift per day is `a(n) · (delta · f − rate · m)`, where f is the use frequency. **Its
sign does not depend on n**: a young and an old belief cross at the same frequency
`f* = rate · m / delta`; a belief with more evidence only moves more slowly — in both
directions. That is the alignment: one speed, set by the evidence, for growth and for decay.
Examples: toolpath (0.02/day, hit +0.05) needs a hit every 2.5 days; a default edge (0.01) one
every 5 days; a weak (EXTERNAL) source needs 3x the reconfirmation.

**Node confidence** is the same pair in multiplicative form (a node has no count): growth
shrinks doubt, `c → 1 − (1 − c)(1 − 0.25·w)` (W6); decay shrinks only what repetition earned,
`c → floor + (c − floor)·exp(−rate · m · days)`, floor = the stated value 0.4 (Req 4.4).
Each moves in proportion to its distance from its bound, so they meet at an equilibrium set by
f. What was stated stays; what was earned must keep being earned.

**The phase** is the time-mean of the per-step multipliers over the span (expand 0.5,
compress 1.8, neutral 1.0). The multiplier of the *mean u* was 0.5 on every span of the live
store (72% of steps expand) — a constant, so a failure by §3's rule. The step mean varies with
the work: 0.68–1.37 per day (measured 2026-10-19). Compression phases prune; expansion phases
preserve.

**Incremental**: each span counts once, from `max(last touch, last_decayed_at)`.

### 11.3 The reorganization is the same law, faster

The quorum reorganization runs this law with `m_quorum = 3.0` for one day-span, on what the
**current and previous day touched** (edges by `last_traversed`, nodes by `updated_at`). It no
longer decays every edge by a separate rule, and it now reaches node confidence, where poisoned
coordinates live. Because a(n) is in the law, it strips **new, unproven growth** (the shape of
an injection) while well-proven memory barely moves — the immune response targets what is new,
by construction. Measured in the guard: a fresh edge loses 0.03, a 50-proof edge less than a
tenth of that, an edge outside the window nothing.

### 11.4 The clock: active days (owner decision, 2026-10-19)

The law counts **active days** — UTC dates with at least one episode (`decay.ActivityClock`;
52 of the last 90 calendar days on the live store). Decay follows the speed at which the memory
grows: an away month forgets nothing; a busy week fades unreinforced memory per use, not per
calendar day. One query per pass on the covering index `idx_ep_timestamp`. A span counts the
active dates strictly after the date of its last touch, up to today. An empty episode table
means no activity, so nothing decays.

Req 7.2 ("score −= rate × days idle") now reads *active* days. A store with no episode
**table** (a Mycelium-only store: test fixtures, a partial schema) has no activity record; it
counts calendar days, logged at WARNING — the existing Req 7.2 test runs on such a store and is
unchanged. Replay on the live store (read-only): active idle 0–52 days against 0–99 calendar;
node confidence after one pass 0.42–0.95; three spaces keep a node ≥ 0.6, so the maturity gate
opens honestly.

---

## 12. Kyudo — the self-cleaning security of the memory (analysis, 2026-10-19)

Source: `Mycellium Kyudo Layer Guide.md` (v1.0, March 2026; partly stale, the concepts hold).
Kyudo is **one mechanism with two names**: the channel a source arrives on sets how much it may
write, how fast its signal fades, which context zone it reaches, and whether it can become
permanent. Precision and security are the same property; the decay system *is* the security
system; the reorganization is the decay system with an emergency multiplier.

### 12.1 Guide against code (measured / code-read)

| Guide | Code (before 2026-10-19) | Now |
|---|---|---|
| Channel per content item, permanent | channel only on episode-index rows — **0 of 2,850 rows carry one**; nodes carry none | nodes record `source_channel` (the highest channel that ever observed them: reconfirmation earns trust) |
| Initial confidence by channel (EXTERNAL 0.30) | the document bridge wrote EXTERNAL content at **0.8**, above every stated value | capped per channel at the store |
| Decay multiplier by channel (EXTERNAL 3x) | absent | in the law (§11.2) |
| Rule 2: landmark trust cap, 30% of constituent nodes | checked a *session* channel argument that **no caller passes** — never ran | measured on the cluster's own nodes on every condense |
| Rule 1: conduct is behavioural only | CellWall `can_write_space` blocks it on the RAG/document paths | unchanged (holds) |
| Quorum signals (4 kinds) | **1 of 4 emitted**, and it is a physics TOPO_VIOLATION filed as `update_velocity_anomaly` | unchanged — §12.2 |
| Threat fades per clean session | `decay_clean_session` had **no caller**: anomalies piled up for the life of the process | fades at session end when the session raised no signal |
| Reorganization: decay what the suspect sessions touched | decayed **every** edge, never nodes | §11.3 |
| … re-render the profile | read `_profile_renderer`; the attribute is `_renderer` — **skipped** | fixed |
| … log to `mycelium_conflicts` | wrote columns `resolution`, `resolved_at` that do not exist — **0 rows ever** | fixed |
| … suspend crystallisation until `clear_session` | never lifted — one reorganization blocked landmarks until restart | lifted at session end |
| MCP pin mismatch → UNTRUSTED | registry loaded, **never compared** | open — §12.2 |
| RAG ingestion bridge at the boundary | `ingest_rag_content` has **no production caller**: web retrieval enters memory with no channel | open — §12.2 |
| Subagent write profiles | read slicing exists; **writes are not checked** | open — §12.2 |
| Precision half (whiteboard slicer, micro-abstract, delta encoder) | **no production caller** | open — measure, then wire or remove |

### 12.2 Proposals (not built; each needs its measurement first)

1. **The immune signals, from places that already know.** Velocity: count node upserts per
   session and fire above the live p99 (`QUORUM_VELOCITY_THRESHOLD` is "TBD post-deployment" —
   measure it from the store). Landmark activation anomaly: an activation above mean + 3σ for
   its task class. Channel mismatch: a VERIFIED source whose coordinates move where EXTERNAL
   content predicted. Give the physics violation its own label instead of borrowing "velocity".
   Run in shadow first and measure the false-alarm rate, as the Oracle does.
2. **A durable immune memory**: persist the threat level and the signals (the docstring's
   `quorum_log` table does not exist). In memory only, a restart erases the evidence, and an
   attacker who spreads across restarts never reaches quorum.
3. **Every external write through the bridge**: research memory and web results enter with a
   channel (EXTERNAL), or none of §12.1 applies to them.
4. **MCP pin check at call time**: compare the server's identity with its pin; downgrade to
   UNTRUSTED and raise `channel_trust_violation` on drift.
5. **Enforce subagent write profiles on writes** (silent drop, as the guide says — no threat
   signal for a normal boundary).
6. **Separate the write lock from the render zone** (W10). The code reuses the guide's
   *context-window* zones as *write* permissions per space, so `toolpath` sits in REFERENCE and
   any channel may write it — the document bridge files untrusted documents into toolpath, a
   behavioural space. Each space declares both in the registry; unknown fails closed.
7. **A landmark-edge writer** (co-activation), so landmark edges grow under the law.

### 12.3 What a space declares (for W10)

`space_id`, axes and ranges, base decay rate, confidence floor, **write lock** (the lowest
channel that may write it), **render zone** (where its profile section enters the context),
subagent **write owners**, the **task classes** that navigate it, resonance participation,
extractor, schema version. A new space is added deliberately (a reviewed row), and inherits the
law and the immune response with no new code.


---

## 13. Findings while building §12 (2026-10-19)

### 13.1 The memory never reaches the agent's step prompts (largest gap)

The DER loop expects a `ContextPackage` object (`memory/mycelium/interface.py:48`: tier-1
directives, tier-2 predictions, tier-3 failures, gradient warnings, the Mycelium path, the
topology path) and reads it at `agent_kernel.py:8191-8198`, `:10653`, `:16736`, and through
`LiveContextPackage` (`memory/live_context.py`). **Nothing in production constructs a
`ContextPackage`.** `MemoryInterface.get_task_context_package` always returns a plain string
(its direct `get_context_path(..., space_subset=...)` call raises `TypeError` — the parameter does
not exist — and the fallback returns the prose/coordinate string), so every attribute read is
empty. The coordinate graph, landmarks, failure warnings and predictions are computed and
**never shown to the agent**. This is not a Kyudo item; it is the connection from memory to
answers, and it changes every prompt — so it needs the measured loop (CLAUDE.md "BUILD + VERIFY
IRIS"): build the package, run the eval tasks before/after, keep it only if pass and reply_s do
not regress, with an off switch.

### 13.2 The precision half (proposal from §12.1, measured)

| Component | Live? | Finding |
|---|---|---|
| TaskClassifier | live (keyword path) | its labels (`research_task` …) never match the kernel's `research/explore/investigate` check (`agent_kernel.py:18688`) |
| PredictiveLoader | half-wired | `pre_warm` calls `navigator.navigate_subgraph`, which does not exist (error swallowed at debug); the cached hint text is `""`, so the Jaccard check is 0 and every lookup misses; `hit_rate` is never logged |
| MicroAbstractEncoder | dead | no production caller; the 30 `micro_abstract` rows are bootstrap seeds |
| WhiteboardSlicer | dead | no caller; `whiteboard_broadcast_tokens` hard-coded 0 |
| DeltaEncoder / PathDelta | dead | no caller; `mycelium_path_deltas` table never created |

Decision: the dead three stay dormant (their tests pin them; deleting them is an owner call);
each is wired only together with a consumer that changes behaviour. PredictiveLoader and the
TaskClassifier labels are fixed as part of §13.1, because they only matter once the package
reaches the prompt.

### 13.3 Pins in the application memory

Pins are a port of the MCM PiN into the app store (`backend/memory/pin_store.py`: types note,
file, folder, image, doc, url, decision, fragment, checkpoint).

- `mycelium_pins`: **0 rows**. `PinStore.add/update/checkpoint` have no production caller; the
  two raw inserts (`agent/swarm/coordinator.py:162`, `agent/swarm/context_control.py:104`) run
  only with swarm on (default off).
- The recall path for pins (`recall_decoder._resolve_pin`) is unreachable: nothing imports
  `recall_phases` / `recall_decoder` in production.
- `mito_inject.py:50` counts permanent pins from table `pins` / column `permanent` (the build
  store's shape) every turn; the error is swallowed, so the count is always 0.
- `mycelium_pin_links`: 16,578 rows — not pins. They are DER step links (`relevant_to` 12,757,
  `depends_on` 3,535, `part_of` 279, `failed_like` 7). Their ids are `node:<step_id>` with plan-
  local step ids (`s1`, `s2` …), so **every plan's `s1` is the same node**: 16,569 of the links
  resolve to `der_fan_traces.step_id`, but without a session scope the lineage graph collapses
  onto ~64 ids. `weight` is 1.0 on every row.
- `docs/Design/Memory-Cortex/MEMORY-DASHBOARD-DESIGN.md:712` lists a "Keep this in mind: pin into
  the context window" action; nothing implements it, and the mockup draws no pins.

**What a pin is in IRIS (proposal).** Learned memory grows (neurons, edges, landmarks); a pin is
**explicit** memory — something the user or IRIS chose to hold: a file, a URL, a decision, a
note, a checkpoint. It does not decay by the §11 law (it is held, not earned), it carries the
channel of whoever pinned it (user = USER), and it is either *resting* or *held in context*
(the dashboard action).

**How pins look in the cortex (proposal).**
- **Cortex level:** a pin is a small **faceted crystal set into the inner wall**, in the territory
  (sector) of its topic — still, not pulsing, which is what separates held memory from living
  neurons. Its facets take the pin-type colour; its size follows its link count. Fine, taut
  **tethers** run from it to what it references (an artifact in the format layers, a landmark
  cluster, a thread) — straight and tense, unlike the soft fibre tissue.
- **Held in context:** the crystal gets a thin bright ring and its tethers brighten — "IRIS is
  holding this right now".
- **Timeline:** a pin sits on its thread at the moment it was made, as a fixed bead the fibres
  part around; scrolling past it shows its tethers to later threads that used it.
- **Checkpoint pins** (session checkpoints) mark doorways: the tunnel's doorway to a thread can
  carry the checkpoint crystal of where that thread was paused.

Work to make pins real (not built): a session-scoped id for DER links (`node:<session>:<step>`)
so the lineage stops collapsing; a production writer for user pins (the "keep this in mind"
action and an agent tool), routed through Kyudo with the pinner's channel; fix the `mito_inject`
count; then the cortex reads `mycelium_pins` + `mycelium_pin_links`.


---

## 14. §12.2 proposals — status (2026-10-19)

| # | Proposal | Status | Commit | Measured / open |
|---|---|---|---|---|
| 3 | Every write through the trust bridge | **built** | `588036cd` | one vocabulary (zones, document labels → HyphaChannel; unknown = UNTRUSTED); bookkeeping (2,775 card rows, skills) no longer filed as the user's words; episode-index rows carry a channel (backfill 387 + 2,349); channel-weighted retrieval in SHADOW (`kyudo.trust_rank.*` counters). Open: a failed web-tool step still fragments into the `tool` zone (`agent_kernel.py` der_failure). |
| 7 | Landmark edges grow | **built** | `bcb6c8ea`, `d1f255e1` | landmarks activate when the session's region overlaps their cluster (≤ 6), and their edges take one observation per turn by the §11 law. Found: the region was cleared before the turn-end job, so every episode-index row had `'[]'` — fixed. Open: 91 live landmarks share 7 clusters (duplicates that never merged — W9). |
| 1+2 | Immune signals in shadow + durable immune memory | **built** | `526a6d03` | `mycelium_quorum_log`, threat level restored on start, retention 2,000 rows; TOPO violation has its own label. Velocity shadow (> 11 upserts) fires on 5 of 2,365 sessions — all honest long sessions: it does not separate an attack. Activation shadow: 0 fires (no activation history until now). `channel_mismatch` not built. |
| 6 | Write lock separate from the render zone (W10) | **built** | `c209f33a` | `mycelium_spaces` is the registry; locks: conduct/style/chrono ≥ USER, capability/toolpath = SYSTEM, context ≥ VERIFIED, domain ≥ EXTERNAL; fails closed; an 8th test space works end to end; untrusted documents no longer write toolpath. |
| 4 | MCP pin check | **built, dormant** | `0c9341ca` | identity hash over endpoint + serverInfo + tools (with descriptions); drift → UNTRUSTED + conflict row + signal. Nothing in production connects an external MCP server yet. Pin creation is an owner decision. |
| 5 | Subagent write limits | **closed** | — | no production path writes nodes under a worker identity; the profiles are read-only (evidence in `0c9341ca`). |
| — | Precision half | **measured** | — | §13.2: three components dead, the predictive loader half-wired; tied to §13.1. |

The largest open item is not in §12: **§13.1, the memory never reaches the agent's step
prompts.**


---

## 15. The next three, and the live gate (2026-10-19)

| Item | Commit | State |
|---|---|---|
| The memory reaches the step prompts (§13.1) | `a0b0924c` | ContextPackage built from existing producers (path, topology, predictions, failures, task class); capped 1,600 chars, 150 ms budget; off switch `IRIS_MEMORY_CONTEXT_PACKAGE=0`. ON by default. |
| Landmark duplicates + sectors in shadow (W9) | `c8852bb5` | merge-all at Jaccard ≥ 0.5, region clusters, uuid merge ids, specificity tie-break; sectors table, roots, sector at save + backfill (91: rule 19, cluster 51, general 21), lifecycle logged only. A session with no region crystallizes no landmark. `collapse_duplicates()` is NOT in maintenance (decision below). |
| Cortex visual | `c198f97a` | timeline = fibre tissue; the doorway is a tall soft arch with no rim; pins, trust membranes, fading, landmark tracts, immune response, sectors, spaces; MEMORY-DASHBOARD-DESIGN §17. |
| First-turn stall found by the gate | `d706941c` | 73 s in the chart-origin query (cold SCAN) → 196 ms with an index. Standard S113. |

**Live gate (coding group, 15 tasks, real backend).**

| Run | Pass | Sum of reply_s | Note |
|---|---|---|---|
| ON #1 | 14/15 | 685 s | includes the 12.8 s cold first turn (the S113 stall) |
| OFF | 13/15 | 643 s | `IRIS_MEMORY_CONTEXT_PACKAGE=0`, same build |
| ON #2 (after S113) | 13/15 | 816 s | 8 packages built; 22 extra model calls (below) |

Run-to-run noise is large (the two ON runs differ by 19%; failures move between tasks:
ON#1 c14, OFF c04+c06, ON#2 c05+c11). Pass does not regress. The reply time is higher in
ON#2, and the measured cause is **the step reviewer's model branch** (`der_loop.py` ~1167):
it runs when the graph is mature and a package exists — which never happened before today —
and in ON#2 it made 22 extra calls (role EXECUTION). It judges a step against the package's
gradient warnings and active contracts, and **no producer fills either field**, so it reviews
with no memory signal. Gating it on non-empty warnings/contracts conflicts with five existing
tests (`tests/unit/test_reviewer_split.py`, `tests/contract/test_verdict_consumer_shape.py`)
that pin "mature + package → model review" — reported, not changed (owner decision below).

**Live values after the gate (read-only):** 48 `mycelium_edges` (was 0; scores 0.5–1.0,
evidence up to 12); 23 landmarks activated by use (max 14 — one is now a chart origin); 55
landmark edges grown (0.42–0.45, up to 8 traversals); 5 landmarks permanent through use
(tier `landmark` + 8 activations — the rule that was always there, now reachable); new nodes
carry their channel (21 SYSTEM, 1 USER); 13 proven sector roots; quorum log empty (no signal).
**Not exercised:** the episode index — every eval task is a repeat, the episode store dedups
it (UPDATE, early return) before the index step, so no new index row formed; check with a new
task.

**Decisions for the owner.**
1. The reviewer's model branch: keep it live (the tests' contract; +~22 calls/run, no memory
   signal to judge), or require a warning/contract first (change the five tests' contract).
2. `collapse_duplicates()` on the live store: it would absorb 88 of 91 landmarks into 3, but
   they look alike only because of the old global-top-6 cluster bug — their claims differ.
3. Permanence through use: a `landmark`-tier claim becomes permanent at 8 activations; the
   activations are now real (one landmark reached 14 in ~46 turns — hub concentration).

**Visual check (in-app browser):** demo + `?real` load with no console errors; `?real` reads 7
spaces, 120 nodes, 0 pins. The orb renders as a bright white core in the in-app browser — the
same for the version before this work (software rendering, ~17 fps); check brightness in your
own browser.
