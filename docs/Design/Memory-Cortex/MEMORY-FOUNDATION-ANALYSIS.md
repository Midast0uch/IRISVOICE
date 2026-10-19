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
| W4 | **Decay**: incremental from a `last_decayed_at`; maintenance receives the latest settled u | two passes on an idle edge subtract once per elapsed span, not twice (guard); the u multiplier varies in production | no change to decay rates or prune threshold |
| W5 | **Why 0 routing edges** (Wormhole spec U3 / S54): find where the region-mediator write goes and fix it | a DER node step writes a `mycelium_edges` row on the live app (measured) | no new edge model (Beta posteriors are Stage A) |
| W6 | **The graph walks**: confidence grows with repeated observation; entry matching reaches the nodes that exist; spaces that are never fed get their feed | live traversals return nodes; access counts vary; maturity measured honestly | no lowered thresholds as the fix; no fake nodes |
| W7 | **Episode index records nodes** (follows W6) | new index rows carry node ids | — |
| W8 | **Caducean `domain` constant**: the trajectory row takes the node's real sector | trajectories show more than one sector on new rows | — |
| W9 | **Sectors, shadow mode**: `mycelium_sectors` + `mycelium_landmark_sectors`; landmark sector at creation (rule, then cluster, then `general`); idempotent backfill; lifecycle (birth / closure / split / merge / dissolve) computed and LOGGED, consumed by nothing | every live landmark has ≥ 1 sector; lifecycle decisions measured over real sessions | no consumer reads sectors yet (shadow); no auto-created space |
| W10 | **Spaces registry** as the source of truth; Kyudo fails closed | an 8th test space works end to end in a test store | no new real space |
