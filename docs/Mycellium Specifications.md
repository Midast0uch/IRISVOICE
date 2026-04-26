## Page 1

# IRIS Mycelium Layer — Implementation Specification v1.6

**Project:** IRIS / Torus Network
**Component:** Mycelium — Coordinate-Graph Memory Navigation Layer
**Date:** March 2026
**Status:** Ready for Implementation
**Depends On:** IRIS Memory Foundation Spec, IRIS Swarm PRD v7.0
**Author:** Architecture Session

---

## Changelog

### v1.0 → v1.1
* Node condensing and expansion via `MapManager`
* Convergence handling via `SessionRegistry`
* `toolpath` as seventh coordinate space
* Agent-authored edges via `author_edge()`

### v1.1 → v1.2
* Landmark Layer — crystallized session fingerprints, permanent map entries
* Cross-session node promotion via landmark activation count
* Coordinate conflict resolution via landmark evidence
* Torus peer sharing via `Landmark.to_remote()`
* Token ID micro-abstracts — model-native compressed encoding
* Toolpath decay parameterized separately
* Developer mode graph dump via `dev_dump()`

### v1.5 → v1.6

---


## Page 2

# What we improved

*   **affect space removed** — weakest of the seven spaces at initialization. Starts almost blind: valence, arousal, and stability derived from tone patterns require dozens of sessions before the coordinates mean anything reliable. More critically, the signal is largely downstream of other spaces – a user with high conduct autonomy and high domain proficiency will naturally exhibit certain tone patterns not because of a stable affect baseline, but because of their operational and intellectual identity. What was genuinely useful in **affect** (communication calibration, tone sensitivity) is absorbed over time into **style** and **conduct** through landmark refinement. The rest was noise. The clinical non-use constraint was also an architectural liability – a space that can never be used for its most obvious inference is a space with a structural weakness.
*   **context space added** — replaces **affect** — the operational environment space. Captures what the user is working on, not who they are or how they work. Project identity, dominant tech stack, active constraints, freshness. This is the space that enables multiple context whiteboards – each active project gets its own context node, its own landmark trail, its own topological geometry in v2.0. The map develops regional density around each project the way a geographic map develops detail around populated areas. Four axes: project_id, stack_id, constraint_flags, freshness. Fastest decay of any profile space – context goes stale faster than tool habits.
*   **Seven spaces now cover three clean categories:** Identity: domain , style Operational: conduct , chrono , capability Environmental: context , toolpath All seven are either behaviorally derived or hardware-detected. None require declaration. None have architectural constraints on their use. The set is complete.
*   **context extractor added to CoordinateExtractor** — project_id and stack_id hashed from session task text, git context if available, and explicit statements. constraint_flags extracted from deadline language, deployment context signals, and privacy-related phrasing. freshness set to 1.0 on extraction, decays daily.
*   **_render_context() added to ProfileRenderer** — renders active project context as a plain-language environment summary. Included in PROFILE_SPACES.
*   **CONTEXT_DECAY_RATE = 0.025** — faster than toolpath (0.02), reflecting that project context switches more abruptly than tool habits.

## Gaps that remain open

*   Landmark naming (cosmetic, low priority)
*   Multi-user landmark aggregation on Torus (privacy design work required)

---


## Page 3

* git integration for automatic project_id and stack_id detection (v1.7 candidate)

---

## v1.4 → v1.5

### What we improved

*   **location space removed** — geographic coordinates were the weakest of the seven spaces. Privacy-compromising (VPN users, privacy-conscious users, anyone who does not want location tracked), unreliable (user moves, coordinate drifts silently), and redundant — the only genuinely useful component was timezone, which is already derivable from the `chrono` space's `peak_activity_hour_utc`. Cultural and geographic context is available to the model from training weights and from what the user says naturally during tasks. No dedicated coordinate space needed.

*   **conduct space added** — replaces **location** — the operational identity space. Captures how the user works with an agent, not who they are as a person. Five axes: autonomy, iteration_style, session_depth, confirmation_threshold, correction_rate. Almost entirely behavioral — derived from observed outcomes, not declarations. The only space that directly shapes plan structure: the Planner reads conduct coordinates to calibrate how many steps to include, where checkpoints go, and how much runway to take before checking in. Decays at 0.008/day — between profile spaces (0.005) and toolpath (0.02), because working habits evolve faster than identity but slower than tool preferences.

*   **Timezone absorbed into chrono** — the `tz_offset_hours` signal that was in the location space is now derived inferentially from chrono's `peak_activity_hour_utc` combined with session timestamps. If a user is consistently most active at 23:00 UTC and their calendar events cluster around evening local time, timezone is implied. No explicit storage required.

*   **conduct extractor added to CoordinateExtractor** — behavioral signals extracted from episodic outcomes. Correction rate observed from `user_corrected` field. Autonomy inferred from how often users let tool calls through versus interrupt. Session depth from average task complexity and episode token counts.

*   `_render_conduct()` added to ProfileRenderer — replaces `_render_location()`. Renders the conduct coordinate as a plain-language operational summary: autonomy level, working style, and checkpoint preferences.

### Gaps that remain open

---


## Page 4

* Landmark naming (cosmetic, low priority)
* Multi-user landmark aggregation on Torus (privacy design work required)

---

**v1.3 → v1.4**

**What we improved**

* **Resonance scoring layer** – the episodic recall mechanism is now Mycelium-aware. Previously `EpisodicStore.retrieve_similar()` scored past episodes by cosine similarity alone — how linguistically close is this task to past tasks? That’s single-axis pattern matching. Resonance is multi-axis: how many coordinate spaces overlap between the current task’s Mycelium fingerprint and the fingerprint of the session that produced each episode? An episode that matches on domain *and* toolpath *and* chrono is far more predictive than one that just shares vocabulary. Each additional resonating space multiplies the confidence score. The final retrieval score is `cosine_similarity × resonance_multiplier`, not cosine alone.
* **Coordinate-aware episodic injection** – `assemble_episodic_context()` now distinguishes between what the coordinate path already covers and what it doesn’t. Success summaries that are already represented in the current landmark or coordinate path are suppressed — the model doesn’t read the same information twice as both numbers and sentences. Failure warnings, corrections, and specific edge cases are always injected as sentences because there is no coordinate representation for “permissions error on Windows.” The two representations work in parallel with different jobs: coordinates carry the stable pattern, sentences carry the specific exceptions.
* **resonance.py module** – a new file that sits between `EpisodicStore` and `MyceliumInterface`. Neither side owns it. It reads the current session’s coordinate path from Mycelium, scores each candidate episode by coordinate overlap, and returns a resonance-augmented ranked list. `EpisodicStore` calls it as an optional scoring pass; if Mycelium has no data yet (fresh install) it falls back to cosine-only ranking transparently.
* **mycelium_episode_index table** – a lightweight bridge table linking episode IDs to the coordinate node IDs that were active during that session. Written at episode store time by the resonance module. Enables O(1) resonance lookup per episode rather than re-navigating the graph on every retrieval call.

**Gaps that remain open**

* Working memory tool result compression — extract stable coordinate facts from tool

---


## Page 5

outputs during execution. Designed but not yet specified in detail.

*   Plan context quality improvement via toolpath priors is already in the spec via the Planner integration point. No further work needed there.

*   **Landmark merge triggered by whiteboard condense** – the two operations are now causally linked. When a whiteboard condenses into a new landmark, `LandmarkIndex` immediately checks whether the new landmark’s coordinate cluster overlaps significantly with any existing landmark of the same task class. If overlap exceeds `MERGE_OVERLAP_THRESHOLD`, the two landmarks merge. The merge is not destructive — it produces a richer unified landmark whose cluster is the weighted union of both, whose score is the confidence-weighted average, and whose micro-abstract is re-derived from the merged cluster. This is the layered transfer: session → whiteboard → landmark → merge → richer landmark. Each layer naturally feeds the next. Understanding accumulates without any manual curation.

*   **Readable Profile Layer** – the missing human face on the coordinate graph.
    `ProfileRenderer` derives a prose profile from the coordinate graph and landmark graph together. It is never manually written. It is always generated from the current state of the map. When coordinates shift — user relocates, domain proficiency changes, new tools become habitual — the profile regenerates automatically during distillation. The profile is the translation of the map into human language. The map is the truth. The profile is the projection.

*   **Profile stratification** – not all coordinate spaces render into the readable profile.
    `toolpath` is operational data — the agent uses it, the user doesn’t read it. `capability` renders as a capability summary, not raw hardware specs. `conduct`, `domain`, `style`, `chrono`, `context` render fully. The profile shows what is meaningful to a human. The rest stays in the machine layer where it belongs.

*   **Profile-coordinate sync** – the profile is always a consequence of the map, never a separate artifact that can drift. Every time `run_condense()`, `run_expand()`, or a landmark merge occurs, a dirty flag is set. Distillation checks the flag and regenerates the profile section for any space that changed. The profile cannot be stale if the distillation cycle runs.

**Gaps that remain open**

*   **Landmark naming** – auto-labels are still `domain_ai:timestamp`. A lightweight naming pass using the merged cluster’s top labels could generate a 3-word human name (e.g. “ai-night-research”). Low priority, cosmetic.

---


## Page 6

*   **Multi-user landmark aggregation on Torus** – sharing anonymized landmark structures between peers for the same task class. Significant privacy design work required. Not safe to implement yet.
*   **Profile narrative voice** – the rendered profile is factual prose. It could be richer — a short paragraph with context and caveats. Future work.

Returns full node/edge/landmark table as structured dict. Exposed via `MyceliumInterface.dev_dump()`. Not available in personal mode.

## Gaps that remain open

*   **Landmark naming** – auto-generated labels use the dominant space ID and a timestamp. No semantic naming yet. A landmark called `domain_ai:1741234567` is correct but not human-readable in developer mode. A lightweight naming pass using the micro-abstract token sequence could generate a 3-word label.
*   **Landmark merging** – two landmarks with highly similar coordinate clusters and task class fingerprints should merge, same as node condensing. Not yet implemented. Duplicate landmarks will accumulate for users who repeatedly do the same class of task.
*   **Multi-user landmark sharing** – on Torus, if two users have compatible (but anonymized) landmark structures for the same task class, those landmarks could be aggregated into a shared navigational prior. Significant privacy design work required before this is safe to implement.

## Purpose

The Mycelium Layer is a coordinate-graph navigation system that sits beneath the existing three-tier memory architecture (working → episodic → semantic) and transforms how agents access context. Instead of agents searching flat vector spaces and reading prose summaries, they navigate a living graph of scored coordinate nodes — following precomputed pathways of least resistance to reach relevant context in the minimum number of tokens possible.

The name is intentional. Mycelium is the underground fungal network through which a forest exchanges nutrients. No single tree knows the network is there. The forest just works – resources flow where they’re needed through paths that have been strengthened by prior successful transfers. Unused paths atrophy. High-traffic paths widen.

---


## Page 7

IRIS's memory system works the same way after this layer is implemented. The swarm, the Planner, the WorkerExecutor — none of them know the Mycelium is there. They ask for context. The Mycelium returns a compact coordinate path instead of a paragraph of prose. The agent reads fewer tokens, activates richer knowledge, burns less KV cache.

---

# The Problem This Solves

## Current state

When a task arrives, the Planner assembles context from three tiers and injects it into the context window as prose:

"User is a developer in New York who prefers concise technical responses, works on AI and blockchain projects, is active late at night, previously failed a task involving file deletion due to missing permissions, has strong preferences for decentralized architecture..."

This is ~60 tokens of semantic context. Multiply by every inference call across every plan step across every parallel worker and the KV cache cost compounds fast. Each token costs KV memory proportional to the number of attention layers — on a 32-layer model, 60 tokens of semantic header occupies the same KV budget as 1,920 attention-layer operations per inference call.

Worse: prose is ambiguous. "Works in New York" costs the model attention operations to disambiguate (city? state?), infer geography, timezone, cultural context. The model derives coordinates from language every single time. You're making it do geography homework on every call.

## What Mycelium does instead

MYCELIUM: loc:[40.712,-74.006,-5.0]@47 | domain:[ai:0.95,crypto:0.87,infra:0.82]@ style:[0.2,0.8,0.9]@156 | chrono:[23.1,2.8,0.91]@89 | path_score:0.94

This is ~18 tokens. It carries more information than the prose version because the model already has the full topographic, cultural, demographic, and relational map of [40.712, -74.006] baked into its weights. You're handing it the address directly rather than making it derive the address from a description.

**The KV cache impact:** Fewer tokens in context = fewer KV entries per layer = more headroom for parallel workers before VRAM pressure becomes a problem. This is the mechanism by which Mycelium eases the multi-agent KV problem — not by solving

---


## Page 8

parallelism directly, but by making each parallel context window so much smaller that more of them fit in the same VRAM budget.

## Why coordinates work mathematically

When a transformer processes the string "New York" it must:

1. Tokenize → [New] [York] = 2 tokens minimum
2. Look up token embeddings for each
3. Run attention across surrounding context to disambiguate meaning
4. Activate geographic/cultural/temporal knowledge from weights

When it processes `[40.712, -74.006]` it:

1. Reads three float tokens
2. Has an unambiguous anchor with no disambiguation needed
3. Activates the same geographic knowledge with less attention overhead

The coordinates are not just shorthand for "New York." They are a precise key into the model's internal knowledge representation that bypasses the language parsing layer entirely. For factual, stable properties of the user (preferences, domain expertise, temporal patterns, operational conduct) this is always the correct primitive.

For dynamic, relational, narrative knowledge (what happened in a conversation, why a task failed, what the user said they wanted) prose and episodic embeddings remain appropriate. Mycelium does not replace those — it adds a faster path for the facts that are stable enough to have coordinates.

---

## Goal

Implement a coordinate-graph memory layer that:

1. Assigns coordinate representations to stable user facts across defined semantic spaces
2. Stores those coordinates as nodes in a scored graph within `data/memory.db`
3. Scores edges between nodes based on co-activation and traversal success
4. Provides a `CoordinateNavigator` interface that returns compact path encodings
5. Integrates into the existing `MemoryInterface` so the Planner and all agents receive

---


## Page 9

coordinate paths in context without any changes to their own code

6. Self-organizes over time – successful paths strengthen, unused paths decay, the graph becomes faster and more accurate with every task

**The single measurable outcome:** Semantic context injected into the planning prompt shrinks from ~60 prose tokens to ~18 coordinate tokens with equal or greater information density, reducing per-inference KV cache cost by approximately 70% for the semantic header zone.

---

# Architecture

## Where Mycelium sits

```mermaid
graph TD
    subgraph Memory Interface
        A[MemoryInterface]
        B[get_task_context()]
        C[assembles all zones]
    end

    D[Working Memory]
    E[Episodic Store]
    F[Semantic Store]

    G[MYCELIUM LAYER]
    H[CoordinateStore]
    I[CoordNavigator]
    J[PathEncoder]
    K[EdgeScorer]

    A --> B
    B --> C
    C --> D
    C --> E
    C --> F

    D --> G
    E --> G
    F --> G

    G --> H
    G --> I
    G --> J
    G --> K
```

Mycelium is called by `MemoryInterface.get_task_context()` when assembling the `semantic_header` zone. It replaces the prose semantic summary with a coordinate path encoding. Everything above it (Planner, WorkerExecutor, PrimaryNode) is unchanged.

## Files to create

<table>
<thead>
<tr>
<th>File</th>
<th>Purpose</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

---


## Page 10

<table>
  <tr>
    <td>backend/memory/mycelium/__init__.py</td>
    <td>Package init</td>
  </tr>
  <tr>
    <td>backend/memory/mycelium/spaces.py</td>
    <td>Coordinate space definitions</td>
  </tr>
  <tr>
    <td>backend/memory/mycelium/store.py</td>
    <td>CoordinateStore – DB read/write</td>
  </tr>
  <tr>
    <td>backend/memory/mycelium/navigator.py</td>
    <td>CoordinateNavigator – graph traversal</td>
  </tr>
  <tr>
    <td>backend/memory/mycelium/encoder.py</td>
    <td>PathEncoder – path → token string</td>
  </tr>
  <tr>
    <td>backend/memory/mycelium/scorer.py</td>
    <td>EdgeScorer – score update and decay</td>
  </tr>
  <tr>
    <td>backend/memory/mycelium/extractor.py</td>
    <td>CoordinateExtractor – facts → coordinates</td>
  </tr>
  <tr>
    <td>backend/memory/mycelium/interface.py</td>
    <td>MyceliumInterface – single access boundary</td>
  </tr>
</table>

## Files to modify

<table>
  <tr>
    <th>File</th>
    <th>Change</th>
  </tr>
  <tr>
    <td>backend/memory/db.py</td>
    <td>Add Mycelium tables to schema</td>
  </tr>
  <tr>
    <td>backend/memory/interface.py</td>
    <td>Call MyceliumInterface in get_task_context()</td>
  </tr>
  <tr>
    <td>backend/memory/distillation.py</td>
    <td>Write coordinate updates during distillation</td>
  </tr>
  <tr>
    <td>backend/memory/semantic.py</td>
    <td>Notify Mycelium when semantic facts update</td>
  </tr>
</table>

## Coordinate Spaces

### Definition

A coordinate space is a named set of axes that together describe a stable property of the user or context. Each axis is a float in a defined range. Together the axes form a point in that space — a coordinate that the model can use as a direct key into its knowledge.

### The seven coordinate spaces

**Space 1:** conduct — NEW v1.5 (replaces location)

The user’s operational identity — how they work with an agent. This is the only space that directly shapes plan structure rather than plan content.

---


## Page 11

Axes: [autonomy, iteration_style, session_depth, confirmation_threshold, correction_rate]
Range: All axes 0.0 to 1.0

autonomy:
*   0.0 = confirm every tool call
*   0.5 = confirm before irreversible actions only
*   1.0 = full agentic execution, report at end

iteration_style:
*   0.0 = heavy iteration, rarely commits to draft on
*   1.0 = decisive, commits quickly and moves on

session_depth:
*   0.0 = always short targeted asks
*   1.0 = long exploratory deep-dives

confirmation_threshold:
*   0.0 = wants confirmation on any consequential act
*   1.0 = never needs confirmation regardless of stak

correction_rate:
*   0.0 = never corrects mid-task
*   1.0 = frequently redirects during execution

Example: `[0.85, 0.7, 0.8, 0.6, 0.2]`
→ high autonomy, mostly decisive, deep sessions, moderate confirmation sensitivity, rarely corrects mid-task

Why: Planner uses conduct to calibrate plan shape before reading a single word of the task. High autonomy + deep session → bold multi-step plan with few gates. Low autonomy + high correction_rate → shorter plan with explicit checkpoints at each consequential action. This is the missing prior – the current six spaces tell the agent who the user is. Conduct tells it how t work with them.

Source: Derived entirely from behavioral observation – episodic outcomes, tool call approval patterns, mid-task redirections, task complexity score NEVER declared by the user. A user who says "just do it" but redirects constantly gets a correction_rate that reflects the behavior, not the wor

Update: At 0.008/day decay – between profile spaces (0.005) and toolpath (0.02). Working habits evolve faster than identity, slower than tool preferences.

Note: confirmation_threshold is a separate axis from autonomy intentionally. A user can be high-autonomy for research tasks but want confirmation befo any file deletion or external API write. The two axes can diverge.

## Space 2: domain

The user's areas of expertise, represented as a sparse vector of domain proficiency scores.
Not all axes need values — unset domains default to 0.0.

Axes: [domain_id, proficiency_0_to_1, recency_0_to_1] per active domain
Domains: ai, crypto, infra, frontend, backend, design, finance, science, writing, operations, hardware, security, data
Example: `[ai:0.95, crypto:0.87, infra:0.82, backend:0.79]`

Why: Planner uses domain scores to select appropriate tools and depth. High proficiency = skip basics. Low proficiency = explain more.

Source: Derived from task history, skill crystallisation scores, explicit stateme
Update: Incrementally – proficiency drifts up/down based on task outcomes

---


## Page 12

# Space 3: style

How the user prefers to communicate and receive information.

Axes: [formality, verbosity, directness]
Range: Each axis 0.0 to 1.0
formality: 0.0 = very casual, 1.0 = formal/professional
verbosity: 0.0 = one word answers, 1.0 = exhaustive detail
directness: 0.0 = diplomatic/softened, 1.0 = blunt/unfiltered
Example: [0.2, 0.6, 0.9] → casual, moderately detailed, direct
Why: Executor uses style coordinates to calibrate response tone and length without parsing preference prose on every call.
Source: Derived from episodic interaction patterns and explicit preferences
Update: Slowly – style coordinates drift toward observed behavior

# Space 4: chrono

The user’s temporal activity patterns.

Axes: [peak_activity_hour_utc, avg_session_length_hours, consistency_score]
Range: peak[0,24], session[0,12], consistency[0,1]
Example: [23.1, 2.8, 0.91] → active around 11pm UTC, ~3hr sessions, consistent
Why: Planner can schedule deferred tasks appropriately.
Tells the agent when the user is likely present vs away.
Consistency score tells it how reliable the pattern is.
Source: Derived from session timestamps in episodic store
Update: Rolling average – recalculated during distillation

# Space 5: context — NEW v1.6 (replaces affect)

The user’s active operational environment – what they are working on right now. Not identity (that is domain, style, conduct) but the external frame: which project, which stack, what constraints are active. Enables multiple context whiteboards – each project node accumulates its own landmark trail and topological geometry. The map develops regional density around each active project over time.

Axes: [project_id, stack_id, constraint_flags, freshness]
Range: project_id[0,1] normalized hash of active project label
stack_id[0,1] normalized hash of dominant tech stack
constraint_flags packed float: deadline pressure, prod vs dev, public vs private, security sensitivity
freshness[0,1] how recently this context was confirmed
1.0 = confirmed this session, decays daily
Example: [0.73, 0.42, 0.60, 0.95]

---


## Page 13

→ Torus project, Python/FastAPI stack, moderate constraints (prod-adjacent, some deadline pressure), confirmed recently

**Why:** Planner uses context to load the right regional map – the landmark trail and topological geometry built up around this specific project. A user switching from their AI infrastructure project to their crypto project gets a completely different prior on tools, depth, and approach even if the task text looks similar. Context is the key that unlocks the right regional cluster.

Multiple context nodes coexist – one per active project. The nearest one to the current session fires. The whiteboard is seeded from that project's landmark history.

**Source:** project_id and stack_id: hashed from task text, git context if available, explicit statements ("working on Torus today", "this is for the frontend" constraint_flags: deadline language, deployment signals, privacy phrasing freshness: set to 1.0 on extraction, decays at CONTEXT_DECAY_RATE.

**Update:** CONTEXT_DECAY_RATE = 0.025/day – faster than toolpath (0.02).

Context switches more abruptly than tool habits. A stale context node is actively misleading, not just imprecise. Freshness axis amplifies the decay signal – low freshness = low confidence in the whole node.

**Note:** Replaces affect, which started blind (needed dozens of sessions before coordinates were reliable) and was largely downstream of conduct and domain. What was genuinely useful in affect absorbs into style and conduct through landmark refinement over time.

## Space 6: capability

What the user’s local environment can actually do — hardware and tooling reality.

**Axes:** [gpu_tier, ram_gb_normalized, has_docker, has_tailscale, os_id]

**Range:** gpu_tier[0,5] (0=none,1=integrated,2=low,3=mid,4=high,5=datacenter)
ram_gb_normalized = ram_gb / 128 → [0,1]
has_docker, has_tailscale → 0.0 or 1.0
os_id: 0=linux, 0.5=mac, 1.0=windows

**Example:** [4.0, 0.5, 1.0, 0.0, 1.0] → high-end GPU, 64GB RAM, Docker yes, Tailscale no, Windows

**Why:** Planner uses this to decide whether to spawn local workers, use Docker, or delegate to Torus. Prevents planning steps the hardware can't execute.

**Source:** System detection at startup, explicit configuration

**Update:** At startup and when hardware changes

## Space 7: toolpath — NEW v1.1

The user’s tool usage signature — which tools get called, in what sequences, and with what success rate. This is behavioral data derived entirely from episodic tool_sequence records. It is the most reliable coordinate space because it reflects what the user actually does, not what they say or how the hardware is configured.

---


## Page 14

Axes: [tool_id, call_frequency_normalized, success_rate, avg_sequence_position]
Range:
*   tool_id[0, 1] (normalized hash of tool name)
*   call_frequency_normalized: calls_per_session / max_calls_observed → [0, 1]
*   success_rate: successful_calls / total_calls → [0, 1]
*   avg_sequence_position: avg position in plan step sequence → [0, 1]

Example: [0.42, 0.87, 0.94, 0.15] → web_search, called frequently, 94% success, tends to be an early step

Why: Planner receives pre-scored tool sequence suggestions from this space rather than reasoning about tool selection from scratch every time.
The highest-scored toolpath edges are the highways – sequences that have worked for tasks like this one, in this order, with these success rates.
Reduces plan production inference cost significantly for recurring task t

Source: Derived from tool_sequence field of episodic store during distillation
Update: Incrementally after every task – most dynamic of all coordinate spaces
Note: Toolpath edges decay faster than user-profile edges (decay_rate=0.02 vs 0 because tool availability and task patterns change more often than identi See EdgeScorer – toolpath edges use TOOLPATH_DECAY_RATE constant.

## Toolpath coordinate → Planner integration:

When the Planner calls get_context_path(task_text), toolpath nodes relevant to the task are included in the returned path. The Planner prompt receives a tool suggestion line derived from the highest-scored toolpath edges:

MYCELIUM: ... | toolpath: [web_search→0.94, file_read→0.87, skill:summarize→0.81]

This tells the Planner: for tasks like this one, these tools in this order have the highest historical success rate. The Planner can follow the highway or deviate with explicit reasoning. Either way the starting point is earned knowledge, not a guess.

---

# Database Schema

Add these tables to data/memory.db inside open_encrypted_memory() in backend/memory/db.py. All existing tables are unchanged. These are additive.

-- Coordinate nodes
-- Each row is one coordinate point in one space for this user
CREATE TABLE IF NOT EXISTS mycelium_nodes (
    node_id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    coordinates BLOB NOT NULL, -- struct-packed float array
    label TEXT, -- human-readable, optional, for debuggin

---


## Page 15

sql
confidence REAL DEFAULT 0.5,    -- how certain we are about this coordina
created_at REAL NOT NULL,
updated_at REAL NOT NULL,
access_count INTEGER DEFAULT 0,
last_accessed REAL
);
```

-- Scored edges between nodes
-- An edge means: when node A is relevant, node B is also likely relevant
-- Score is the strength of that association, learned from traversal outcomes

CREATE TABLE IF NOT EXISTS mycelium_edges (
    edge_id TEXT PRIMARY KEY,
    from_node_id TEXT NOT NULL,
    to_node_id TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.5,    -- 0.0 to 1.0
    edge_type TEXT NOT NULL,            -- "coactivation" | "causal"
    traversal_count INTEGER DEFAULT 0,
    hit_count INTEGER DEFAULT 0,        -- traversals that led to usefu
    miss_count INTEGER DEFAULT 0,       -- traversals that led to wrong
    decay_rate REAL DEFAULT 0.005,      -- score lost per day unused
    created_at REAL NOT NULL,
    last_traversed REAL,
    FOREIGN KEY (from_node_id) REFERENCES mycelium_nodes (node_id),
    FOREIGN KEY (to_node_id) REFERENCES mycelium_nodes (node_id),
    UNIQUE(from_node_id, to_node_id)
);
```

-- Navigation log
-- Records every path traversal for score learning and debugging

CREATE TABLE IF NOT EXISTS mycelium_traversals (
    traversal_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_summary TEXT,
    path_node_ids TEXT NOT NULL,     -- JSON array of node_ids in traversal orde
    path_score REAL,
    outcome TEXT,                    -- "hit" | "miss" | "partial"
    tokens_saved INTEGER,           -- prose tokens replaced by this path
    created_at REAL NOT NULL
);
```

-- Space registry
-- Defines what coordinate spaces exist and their axis metadata

CREATE TABLE IF NOT EXISTS mycelium_spaces (
    space_id TEXT PRIMARY KEY,
    axes TEXT NOT NULL,              -- JSON array of axis names
    dtype TEXT NOT NULL,
    value_range TEXT NOT NULL,      -- JSON [min, max]

---


## Page 16

sql
description TEXT,
active INTEGER DEFAULT 1
);
```

CREATE INDEX IF NOT EXISTS idx_nodes_space ON mycelium_nodes(space_id);
CREATE INDEX IF NOT EXISTS idx_edges_from ON mycelium_edges(from_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_score ON mycelium_edges(score DESC);
CREATE INDEX IF NOT EXISTS idx_traversals_session ON mycelium_traversals(session_

---

## Landmark Layer (NEW v1.2)

-- Landmarks - crystallized navigational patterns from completed sessions
-- The card catalogue entry, not the book.
-- Survives conversation deletion. Belongs to the map, not the content.

CREATE TABLE IF NOT EXISTS mycelium_landmarks (
    landmark_id TEXT PRIMARY KEY,
    label TEXT, -- auto-generated, human-readable in
    task_class TEXT NOT NULL, -- loose fingerprint: dominant spac
    coordinate_cluster TEXT NOT NULL, -- JSON: ordered list of {node_id,
    traversal_sequence TEXT NOT NULL, -- JSON: node_ids in activation ord
    cumulative_score REAL NOT NULL, -- weighted avg of all edge scores
    micro_abstract BLOB, -- packed int32 array of raw token
    micro_abstract_text TEXT, -- decoded version, dev mode only,
    activation_count INTEGER DEFAULT 0, -- times future sessions snapped to
    is_permanent INTEGER DEFAULT 0, -- 1 = constituent nodes bypass dec
    conversation_ref TEXT, -- originating session_id, nullable
    created_at REAL NOT NULL,
    last_activated REAL
);

-- Landmark edges - scored relations between landmarks
-- Navigable the same way node edges are. Self-organizing by traversal outcome.

CREATE TABLE IF NOT EXISTS mycelium_landmark_edges (
    edge_id TEXT PRIMARY KEY,
    from_landmark_id TEXT NOT NULL,
    to_landmark_id TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.5,
    edge_type TEXT NOT NULL, -- "sequential" | "domain" | "toolp
    traversal_count INTEGER DEFAULT 0,
    hit_count INTEGER DEFAULT 0,
    miss_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    last_traversed REAL,
    FOREIGN KEY (from_landmark_id) REFERENCES mycelium_landmarks(landmark_id),
    FOREIGN KEY (to_landmark_id) REFERENCES mycelium_landmarks(landmark_id),
    UNIQUE(from_landmark_id, to_landmark_id)
);

---


## Page 17

-- Conflict resolution log
-- Records which coordinate won a conflict and why (landmark evidence vs confidence)
CREATE TABLE IF NOT EXISTS mycelium_conflicts (
    conflict_id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    axis TEXT NOT NULL,
    value_a REAL NOT NULL,
    source_a TEXT NOT NULL, -- "statement" | "behavioral" | "handwritten"
    value_b REAL NOT NULL,
    source_b TEXT NOT NULL,
    resolved_value REAL NOT NULL,
    resolution_basis TEXT NOT NULL, -- "landmark_score" | "confidence"
    landmark_ref TEXT, -- landmark that provided evidence, if any
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_landmarks_task_class ON mycelium_landmarks(task_class);
CREATE INDEX IF NOT EXISTS idx_landmarks_score ON mycelium_landmarks(cumulative_score);
CREATE INDEX IF NOT EXISTS idx_landmark_edges_from ON mycelium_landmark_edges(from_lm_id);
CREATE INDEX IF NOT EXISTS idx_conflicts_space ON mycelium_conflicts(space_id);

--- --- Readable Profile Layer (NEW v1.3) ---
--- The human face of the coordinate graph.
--- Never manually written. Always derived from coordinates + landmarks during disassembly.
--- One row per rendered profile section (one per rendered coordinate space).
--- The full profile is assembled by reading all sections ordered by render_order.

CREATE TABLE IF NOT EXISTS mycelium_profile (
    section_id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL, -- which coordinate space this section belongs to
    render_order INTEGER NOT NULL, -- display order in assembled profile
    prose TEXT NOT NULL, -- the human-readable rendered text
    source_node_ids TEXT NOT NULL, -- JSON: node_ids that produced this section
    source_lm_ids TEXT, -- JSON: landmark_ids that influenced this section
    dirty INTEGER DEFAULT 0, -- 1 = needs regeneration on next disassembly
    last_rendered REAL NOT NULL,
    word_count INTEGER
);

-- Landmark merge log - records every merge event for auditability
CREATE TABLE IF NOT EXISTS mycelium_landmark_merges (
    merge_id TEXT PRIMARY KEY,
    survivor_id TEXT NOT NULL, -- landmark that absorbed the other
    absorbed_id TEXT NOT NULL, -- landmark that was merged in
    overlap_score REAL NOT NULL, -- cluster overlap that triggered merge
    pre_merge_score_s REAL NOT NULL, -- survivor score before merge
    post_merge_score_s REAL NOT NULL, -- survivor score after merge
    created_at REAL NOT NULL
);

---


## Page 18

sql
pre_merge_score_a REAL NOT NULL, -- absorbed score before merge
post_merge_score REAL NOT NULL, -- merged landmark score after
created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_profile_space ON mycelium_profile(space_id);
CREATE INDEX IF NOT EXISTS idx_profile_dirty ON mycelium_profile(dirty);
CREATE INDEX IF NOT EXISTS idx_merges_survivor ON mycelium_landmark_merges(surviv
```

--- Resonance Layer (NEW v1.4) ---

--- Bridge table: links episode IDs to the coordinate node IDs active in that sess
--- Written at episode store time. Enables O(1) resonance lookup per episode.
--- Without this table, resonance would require re-navigating the full graph
--- for every candidate episode on every retrieval call - too expensive.

CREATE TABLE IF NOT EXISTS mycelium_episode_index (
    idx_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL, -- FK to episodes.id in memory.db
    session_id TEXT NOT NULL,
    node_ids TEXT NOT NULL, -- JSON array of node_ids active in ses
    space_ids TEXT NOT NULL, -- JSON array of space_ids (derived, fo
    landmark_id TEXT, -- landmark crystallized from this sess
    coordinate_hash TEXT NOT NULL, -- short hash of node_ids for dedup / f
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_epindex_episode ON mycelium_episode_index(episode
CREATE INDEX IF NOT EXISTS idx_epindex_session ON mycelium_episode_index(session
CREATE INDEX IF NOT EXISTS idx_epindex_landmark ON mycelium_episode_index(landma
CREATE INDEX IF NOT EXISTS idx_epindex_hash ON mycelium_episode_index(coordin


File 1: backend/memory/mycelium/spaces.py

```python
# backend/memory/mycelium/spaces.py
# Coordinate space definitions - the axes that describe the user

from dataclasses import dataclass, field
from typing import List, Tuple, Dict

@dataclass
class CoordinateSpace:
    space_id: str
    axes: List[str]

---


## Page 19

dtype: str # "float" | "int" | "binary"
value_range: Tuple[float, float] # (min, max) for normalization
description: str = ""

def normalize(self, values: List[float]) -> List[float]:
    """Normalize values to [0, 1] range for cross-space comparison."""
    lo, hi = self.value_range
    span = hi - lo
    if span == 0:
        return [0.0] * len(values)
    return [(v - lo) / span for v in values]

def dimension_count(self) -> int:
    return len(self.axes)

# The seven canonical spaces
SPACES: Dict[str, CoordinateSpace] = {

    # NEW v1.5 - replaces location
    "conduct": CoordinateSpace(
        space_id="conduct",
        axes=["autonomy", "iteration_style", "session_depth",
              "confirmation_threshold", "correction_rate"],
        dtype="float",
        value_range=(0.0, 1.0),
        description="Operational identity - how the user works with an agent. "
                    "Planner uses these to calibrate plan shape: checkpoint densi "
                    "step count, autonomy budget. Derived from behavioral observa "
                    "only - never declared. Decays at 0.008/day."
    ),

    "domain": CoordinateSpace(
        space_id="domain",
        axes=["domain_id", "proficiency", "recency"],
        dtype="float",
        value_range=(0.0, 1.0),
        description="User expertise areas as proficiency scores. Sparse - only "
                    "active domains are stored. Planner uses these to calibrate d "
    ),

    "style": CoordinateSpace(
        space_id="style",
        axes=["formality", "verbosity", "directness"],
        dtype="float",
        value_range=(0.0, 1.0),
        description="Communication preference coordinates. Executor uses these to "
    ),

---


## Page 20

"calibrate response tone and length without prose parsing."

),

"chrono": CoordinateSpace(
    space_id="chrono",
    axes=["peak_activity_hour_utc", "avg_session_length_hours", "consistency",
    dtype="float",
    value_range=(0.0, 24.0),
    description="Temporal activity signature. Used for task scheduling and "
    "estimating user availability."
),

# NEW v1.6 - replaces affect
"context": CoordinateSpace(
    space_id="context",
    axes=["project_id", "stack_id", "constraint_flags", "freshness"],
    dtype="float",
    value_range=(0.0, 1.0),
    description="Active operational environment - what project, what stack, "
    "what constraints. Multiple nodes coexist (one per active pro "
    "Nearest fires. Enables per-project landmark trails and topol "
    "Decays fastest of any profile space - stale context misleads
),

"capability": CoordinateSpace(
    space_id="capability",
    axes=["gpu_tier", "ram_normalized", "has_docker",
    "has_tailscale", "os_id"],
    dtype="float",
    value_range=(0.0, 5.0),
    description="Hardware and tooling reality. Planner uses this to decide "
    "whether to spawn local workers, use Docker, or delegate to T
),

# NEW v1.1
"toolpath": CoordinateSpace(
    space_id="toolpath",
    axes=["tool_id", "call_frequency_normalized",
    "success_rate", "avg_sequence_position"],
    dtype="float",
    value_range=(0.0, 1.0),
    description="Tool usage signature. Derived from episodic tool_sequence re
    "Planner uses highest-scored toolpath edges to get pre-scored
    "sequence suggestions rather than reasoning from scratch. "
    "Decay rate is 4x higher than user-profile spaces - tools cha
),

}

---


## Page 21

# The six canonical spaces comment was stale - there are seven spaces
# Decay rates by space category:

TOOLPATH_DECAY_RATE = 0.02 # tool habits change faster than identity
CONTEXT_DECAY_RATE = 0.025 # context switches most abruptly - fastest profile d
CONDUCT_DECAY_RATE = 0.008 # working habits: between identity (0.005) and tools

# All other profile spaces (domain, style, chrono, capability): 0.005/day

# Domain name to float ID mapping for the domain space
DOMAIN_IDS: Dict[str, float] = {
    "ai": 0.10,
    "crypto": 0.20,
    "infra": 0.30,
    "frontend": 0.40,
    "backend": 0.50,
    "design": 0.60,
    "finance": 0.70,
    "science": 0.80,
    "writing": 0.90,
    "operations": 0.91,
    "hardware": 0.92,
    "security": 0.93,
    "data": 0.94,
}

# Tool name to normalized float ID - NEW v1.1
# Hashed deterministically so the same tool always maps to the same ID
def tool_id(tool_name: str) -> float:
    """Convert a tool name to a normalized float ID in [0, 1]."""
    import hashlib
    h = int(hashlib.md5(tool_name.encode()).hexdigest(), 16)
    return (h % 10000) / 10000.0

def get_space(space_id: str) -> CoordinateSpace:
    if space_id not in SPACES:
        raise ValueError(f"Unknown coordinate space: '{space_id}'. "
                         f"Valid spaces: {list(SPACES.keys())}")
    return SPACES[space_id]

def is_toolpath_space(space_id: str) -> bool:
    """Toolpath edges use a different decay rate - callers check this."""
    return space_id == "toolpath"

---


## Page 22

# File 2: backend/memory/mycelium/store.py

```python
# backend/memory/mycelium/store.py
# CoordinateStore - all reads and writes to mycelium tables

import struct
import uuid
import time
import json
import math
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass, field

from backend.memory.mycelium.spaces import CoordinateSpace, get_space

@dataclass
class CoordNode:
    node_id: str
    space_id: str
    coordinates: List[float]
    label: Optional[str]
    confidence: float
    created_at: float
    updated_at: float
    access_count: int
    last_accessed: Optional[float]

    def distance_to(self, other_coords: List[float]) -> float:
        """Euclidean distance in coordinate space - lower is more similar."""
        if len(self.coordinates) != len(other_coords):
            return float('inf')
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(self.coordinates, other_coords)))

@dataclass
class CoordEdge:
    edge_id: str
    from_node_id: str
    to_node_id: str
    score: float
    edge_type: str
    traversal_count: int
    hit_count: int

---


## Page 23

python
miss_count: int
decay_rate: float
created_at: float
last_traversed: Optional[float]

@dataclass
class MemoryPath:
    nodes: List[CoordNode]
    cumulative_score: float
    token_encoding: str  # compact string for context injection
    spaces_covered: List[str]
    traversal_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

def is_empty(self) -> bool:
    return len(self.nodes) == 0

def _pack_coords(coords: List[float]) -> bytes:
    return struct.pack(f'{len(coords)}f', *coords)

def _unpack_coords(blob: bytes) -> List[float]:
    n = len(blob) // 4
    return list(struct.unpack(f'{n}f', blob))

class CoordinateStore:
    """
    All reads and writes to mycelium_nodes and mycelium_edges.
    Never called directly - always through MyceliumInterface.
    """

    def __init__(self, conn):
        self.conn = conn

    # — Node operations —

    def upsert_node(self, space_id: str, coordinates: List[float],
                    label: str = None, confidence: float = 0.5) -> CoordNode:
        """
        Insert or update a coordinate node.
        If a node in the same space with coordinates within distance 0.05 already exists,
        update it rather than creating a duplicate.
        """
        existing = self._find_near_node(space_id, coordinates, threshold=0.05)
        now = time.time()

---


## Page 24

python
if existing:
    self.conn.execute("""
        UPDATE mycelium_nodes
        SET coordinates=?, confidence=?, updated_at=?, label=COALESCE(? , label)
        WHERE node_id=?
    """, (_pack_coords(coordinates), confidence, now, label, existing.node_id))
    existing.coordinates = coordinates
    existing.confidence = confidence
    existing.updated_at = now
    return existing

node_id = str(uuid.uuid4())[:12]
self.conn.execute("""
    INSERT INTO mycelium_nodes
    (node_id, space_id, coordinates, label, confidence, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
""", (node_id, space_id, _pack_coords(coordinates), label, confidence, now, now))
self.conn.commit()
return CoordNode(
    node_id=node_id, space_id=space_id, coordinates=coordinates,
    label=label, confidence=confidence, created_at=now,
    updated_at=now, access_count=0, last_accessed=None
)
```

def get_node(self, node_id: str) -> Optional[CoordNode]:
    row = self.conn.execute(
        "SELECT * FROM mycelium_nodes WHERE node_id=?", (node_id,))
    ).fetchone()
    if not row: return None
    return self._row_to_node(row)

def get_nodes_by_space(self, space_id: str) -> List[CoordNode]:
    rows = self.conn.execute(
        "SELECT * FROM mycelium_nodes WHERE space_id=? ORDER BY access_count DESC",
        (space_id,)
    ).fetchall()
    return [self._row_to_node(r) for r in rows]

def nearest_node(self, space_id: str, coordinates: List[float]) -> Optional[CoordNode]:
    """Find the node in the given space closest to the given coordinates."""
    nodes = self.get_nodes_by_space(space_id)
    if not nodes: return None
    return min(nodes, key=lambda n: n.distance_to(coordinates))

def record_access(self, node_id: str):

---


## Page 25

python
self.conn.execute("""
    UPDATE mycelium_nodes
    SET access_count = access_count + 1, last_accessed = ?
    WHERE node_id = ?
""", (time.time(), node_id))
self.conn.commit()

def _find_near_node(self, space_id: str, coords: List[float],
                    threshold: float) -> Optional[CoordNode]:
    nodes = self.get_nodes_by_space(space_id)
    for node in nodes:
        if node.distance_to(coords) <= threshold:
            return node
    return None

def _row_to_node(self, row) -> CoordNode:
    return CoordNode(
        node_id=row[0], space_id=row[1],
        coordinates=_unpack_coords(row[2]),
        label=row[3], confidence=row[4],
        created_at=row[5], updated_at=row[6],
        access_count=row[7], last_accessed=row[8]
    )
```

# — Edge operations —

```python
def upsert_edge(self, from_node_id: str, to_node_id: str,
                edge_type: str = "coactivation",
                initial_score: float = 0.5) -> CoordEdge:
    existing = self.get_edge(from_node_id, to_node_id)
    now = time.time()
    if existing:
        return existing

    edge_id = str(uuid.uuid4())[:12]
    self.conn.execute("""
        INSERT OR IGNORE INTO mycelium_edges
        (edge_id, from_node_id, to_node_id, score, edge_type,
         traversal_count, hit_count, miss_count, decay_rate, created_at)
        VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0.005, ?)
    """, (edge_id, from_node_id, to_node_id, initial_score, edge_type, now))
    self.conn.commit()
    return CoordEdge(
        edge_id=edge_id, from_node_id=from_node_id, to_node_id=to_node_id,
        score=initial_score, edge_type=edge_type, traversal_count=0,
        hit_count=0, miss_count=0, decay_rate=0.005,
        created_at=now, last_traversed=None
    )

---


## Page 26

)
```python
def get_edge(self, from_node_id: str, to_node_id: str) -> Optional[CoordEdge]:
    row = self.conn.execute("""
        SELECT * FROM mycelium_edges
        WHERE from_node_id=? AND to_node_id=?
    """, (from_node_id, to_node_id)).fetchone()
    if not row: return None
    return self._row_to_edge(row)

def get_outbound_edges(self, node_id: str,
                       min_score: float = 0.1) -> List[CoordEdge]:
    """Get all edges from a node, ordered by score descending."""
    rows = self.conn.execute("""
        SELECT * FROM mycelium_edges
        WHERE from_node_id=? AND score >= ?
        ORDER BY score DESC
    """, (node_id, min_score)).fetchall()
    return [self._row_to_edge(r) for r in rows]

def update_edge_score(self, edge_id: str, delta: float):
    """Apply a score delta, clamping result to [0.0, 1.0]."""
    self.conn.execute("""
        UPDATE mycelium_edges
        SET score = MAX(0.0, MIN(1.0, score + ?)),
            last_traversed = ?
        WHERE edge_id = ?
    """, (delta, time.time(), edge_id))
    self.conn.commit()

def increment_edge_traversal(self, edge_id: str, outcome: str):
    col = "hit_count" if outcome == "hit" else "miss_count"
    self.conn.execute(f"""
        UPDATE mycelium_edges
        SET traversal_count = traversal_count + 1,
            {col} = {col} + 1,
            last_traversed = ?
        WHERE edge_id = ?
    """, (time.time(), edge_id))
    self.conn.commit()

def _row_to_edge(self, row) -> CoordEdge:
    return CoordEdge(
        edge_id=row[0], from_node_id=row[1], to_node_id=row[2],
        score=row[3], edge_type=row[4], traversal_count=row[5],
        hit_count=row[6], miss_count=row[7], decay_rate=row[8],
        created_at=row[9], last_traversed=row[10]
    )

---


## Page 27

)
# — Traversal log —

def log_traversal(self, session_id: str, path: "MemoryPath",
                 task_summary: str, outcome: str, tokens_saved: int):
    self.conn.execute("""
        INSERT INTO mycelium_traversals
        (traversal_id, session_id, task_summary, path_node_ids,
         path_score, outcome, tokens_saved, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        path.traversal_id, session_id, task_summary[:200],
        json.dumps([n.node_id for n in path.nodes]),
        path.cumulative_score, outcome, tokens_saved, time.time()
    ))
    self.conn.commit()


File 3: backend/memory/mycelium/scorer.py

# backend/memory/mycelium/scorer.py
# EdgeScorer and MapManager - score updates, decay, condense, expand

import time
from backend.memory.mycelium.store import CoordinateStore
from backend.memory.mycelium.spaces import TOOLPATH_DECAY_RATE

# Score deltas for each outcome type
SCORE_DELTAS = {
    "hit": +0.05,  # traversal led to context that was used by the agent
    "partial": +0.02,  # traversal led to context that was partially useful
    "miss": -0.08,  # traversal led to context that was wrong or irrelevant
}

# Edges below this score are candidates for pruning
PRUNE_THRESHOLD = 0.08

# Edges above this score are considered highways - given a small bonus
HIGHWAY_THRESHOLD = 0.85
HIGHWAY_BONUS = 0.01

# Nodes closer than this are candidates for condensing (merging)
CONDENSE_THRESHOLD = 0.04

---


## Page 28

# Nodes with confidence spread > this within same space are candidates for split
SPLIT_THRESHOLD = 0.40

class EdgeScorer:
    """
    Manages edge score updates and decay.
    Called by CoordinateNavigator after each traversal.
    Called by DistillationProcess background daemon for decay.
    """

    def __init__(self, store: CoordinateStore):
        self.store = store

    def record_outcome(self, edge_ids: list, outcome: str):
        """
        Update scores for all edges in a traversal path based on outcome.
        outcome: "hit" | "partial" | "miss"
        """
        delta = SCORE_DELTAS.get(outcome, 0.0)
        for edge_id in edge_ids:
            self.store.update_edge_score(edge_id, delta)
            self.store.increment_edge_traversal(edge_id, outcome)

    def apply_decay(self, self, conn):
        """
        Apply time-based score decay to all edges.
        Called by DistillationProcess every 4 hours.
        Toolpath edges use TOOLPATH_DECAY_RATE (4x faster than profile edges).
        Edges below PRUNE_THRESHOLD are removed. Graph stays lean.
        """
        now = time.time()
        # Join with nodes to get space_id for per-space decay rate
        edges = conn.execute("""
            SELECT e.edge_id, e.score, e.decay_rate, e.last_traversed, n.space_id
            FROM mycelium_edges e
            JOIN mycelium_nodes n ON e.from_node_id = n.node_id
        """).fetchall()

        pruned = 0
        for edge_id, score, decay_rate, last_traversed, space_id in edges:
            # Toolpath decays faster
            effective_decay = (TOOLPATH_DECAY_RATE if space_id == "toolpath" else decay_rate)
            days_idle = ((now - last_traversed) / 86400.0) if last_traversed else 1.0)

---


## Page 29

python
new_score = max(0.0, score - effective_decay * days_idle)

if new_score < PRUNE_THRESHOLD:
    conn.execute("DELETE FROM mycelium_edges WHERE edge_id=?",
                 (edge_id,))
    pruned += 1
else:
    conn.execute("UPDATE mycelium_edges SET score=? WHERE edge_id=?",
                 (new_score, edge_id))

conn.commit()
return pruned
```

```python
def reinforce_highway(self, edge_id: str):
    """
    Edges exceeding HIGHWAY_THRESHOLD get a small bonus on successful travers
    Prevents regression of the most reliable paths.
    """
    edge = self.store.get_edge_by_id(edge_id)
    if edge and edge.score >= HIGHWAY_THRESHOLD:
        self.store.update_edge_score(edge_id, HIGHWAY_BONUS)
```

class MapManager:
"""
Intentional graph operations - condense and expand.
NEW v1.1.

Condense: merge two nodes in the same space that have converged so close together that they carry essentially the same information. Eliminates duplicate context injection and frees KV budget.

Expand: split a node that is being used for contradictory purposes - detected when the node's edges show high variance in outcome (some paths from this node are consistent hits, others are consistent misses).

Both operations are called by DistillationProcess, not at inference time.
"""

def __init__(self, store: CoordinateStore):
    self.store = store

def condense(self, space_id: str) -> int:
    """
    Find pairs of nodes in the same space closer than CONDENSE_THRESHOLD and merge the weaker into the stronger.
    Returns number of nodes merged.
    """

---


## Page 30

Merge rules:
- Surviving node: higher access_count (more load-bearing)
- Merged coordinates: weighted average by confidence
- All edges from the merged node are re-pointed to the survivor
- Merged node is deleted

```python
nodes = self.store.get_nodes_by_space(space_id)
merged_count = 0
merged_ids   = set()

for i, node_a in enumerate(nodes):
    if node_a.node_id in merged_ids:
        continue
    for node_b in nodes[i+1:]:
        if node_b.node_id in merged_ids:
            continue
        if node_a.distance_to(node_b.coordinates) <= CONDENSE_THRESHOLD:
            # Determine survivor (higher access count wins)
            survivor, casualty = (
                (node_a, node_b) if node_a.access_count >= node_b.access_
                else (node_b, node_a)
            )
            # Weighted average coordinates
            w_s = survivor.confidence
            w_c = casualty.confidence
            total = w_s + w_c
            new_coords = [
                (a * w_s + b * w_c) / total
                for a, b in zip(survivor.coordinates, casualty.coordinate
            ]
            # Update survivor with merged coordinates
            self.store.upsert_node(
                space_id=survivor.space_id,
                coordinates=new_coords,
                label=survivor.label,
                confidence=min(1.0, (w_s + w_c) / 2 + 0.05)
            )
            # Re-point casualty's edges to survivor
            self.store.conn.execute("""
                UPDATE mycelium_edges
                SET from_node_id=?
                WHERE from_node_id=?
            """, (survivor.node_id, casualty.node_id))
            self.store.conn.execute("""
                UPDATE mycelium_edges
                SET to_node_id=?
            """, (survivor.node_id,))
            merged_ids.add(node_b.node_id)
            merged_count += 1

---


## Page 31

WHERE to_node_id=?
"""
(survivor.node_id, casualty.node_id)
# Delete casualty
self.store.conn.execute(
    "DELETE FROM mycelium_nodes WHERE node_id=?",
    (casualty.node_id,)
)
self.store.conn.commit()
merged_ids.add(casualty.node_id)
merged_count += 1

return merged_count

def expand(self, space_id: str) -> int:
"""
Find nodes whose outbound edges show high outcome variance
(some edges are consistent hits, others consistent misses from the same n
This signals the node is carrying contradictory meanings - split it.

Split creates two new nodes:
- Node A: coordinates shifted slightly toward the hit-edge targets
- Node B: coordinates shifted slightly toward the miss-edge targets
- Original node deleted, edges redistributed

Returns number of nodes split.
"""
nodes = self.store.get_nodes_by_space(space_id)
split_count = 0

for node in nodes:
    edges = self.store.get_outbound_edges(node.node_id, min_score=0.0)
    if len(edges) < 4:
        continue

    hit_edges = [e for e in edges if e.hit_count > e.miss_count * 2]
    miss_edges = [e for e in edges if e.miss_count > e.hit_count * 2]

    # Only split if there's clear divergence
    if not hit_edges or not miss_edges:
        continue
    variance = abs(len(hit_edges) - len(miss_edges)) / len(edges)
    if variance < SPLIT_THRESHOLD:
        continue

    # Get target coordinates for hit and miss clusters
    hit_targets = [self.store.get_node(e.to_node_id) for e in hit_edges
                   if self.store.get_node(e.to_node_id)]

---


## Page 32

python
miss_targets = [self.store.get_node(e.to_node_id) for e in miss_edges
                if self.store.get_node(e.to_node_id)]

if not hit_targets or not miss_targets:
    continue

# Shift node coordinates toward hit cluster center
n_dims = len(node.coordinates)
hit_center = [
    sum(t.coordinates[d] for t in hit_targets) / len(hit_targets)
    for d in range(min(n_dims, len(hit_targets[0].coordinates)))
]
miss_center = [
    sum(t.coordinates[d] for t in miss_targets) / len(miss_targets)
    for d in range(min(n_dims, len(miss_targets[0].coordinates)))
]

# Interpolate 20% toward each cluster center
node_a_coords = [
    node.coordinates[d] * 0.8 + hit_center[d] * 0.2
    for d in range(len(node.coordinates))
]
node_b_coords = [
    node.coordinates[d] * 0.8 + miss_center[d] * 0.2
    for d in range(len(node.coordinates))
]

# Create the two new nodes
node_a = self.store.upsert_node(space_id, node_a_coords,
                                 f"{node.label}:hit", node.confidence
                                 )
node_b = self.store.upsert_node(space_id, node_b_coords,
                                 f"{node.label}:miss", node.confidenc

# Redistribute edges
for e in hit_edges:
    self.store.upsert_edge(node_a.node_id, e.to_node_id,
                           e.edge_type, e.score)
for e in miss_edges:
    self.store.upsert_edge(node_b.node_id, e.to_node_id,
                           e.edge_type, e.score)

# Delete original
self.store.conn.execute(
    "DELETE FROM mycelium_nodes WHERE node_id=?", (node.node_id,)
)
self.store.conn.execute(
    "DELETE FROM mycelium_edges WHERE from_node_id=? OR to_node_id=?"

---


## Page 33

python
(node.node_id, node.node_id)
)
self.store.conn.commit()
split_count += 1

return split_count
```

File 4: backend/memory/mycelium/navigator.py

# backend/memory/mycelium/navigator.py
# SessionRegistry + CoordinateNavigator - convergence handling and graph traversa

import time
from typing import List, Optional, Set, Dict
from backend.memory.mycelium.store import CoordinateStore, CoordNode, MemoryPath
from backend.memory.mycelium.scorer import EdgeScorer
from backend.memory.mycelium.encoder import PathEncoder

class SessionRegistry:
    """
    Session-level awareness layer. NEW v1.1.

    Tracks which coordinate node IDs have already been injected into the context window for the current task session. This is the shared whiteboard check - if a node is already on the whiteboard, no worker re-injects it.

    The brain agent's context window for one task is the whiteboard.
    Any child worker spawned from that session reads the plan's context string, which already contains the coordinate path the brain assembled. Workers do not navigate back to nodes already present in that string.

    One SessionRegistry instance per PrimaryNode. Cleared after every task.
    """

    def __init__(self):
        self._active: Dict[str, Set[str]] = {} # session_id -> set of node_ids

    def is_active(self, session_id: str, node_id: str) -> bool:
        """Return True if this node is already in the session's context window."""
        return node_id in self._active.get(session_id, set())

    def register(self, session_id: str, node_ids: List[str]):
        """Mark these node IDs as active in the session context window."""

---


## Page 34

python
if session_id not in self._active:
    self._active[session_id] = set()
self._active[session_id].update(node_ids)

def clear(self, session_id: str):
    """Called by PrimaryNode.handle() after task completes - wipes the whiteb
    self._active.pop(session_id, None)

def delta_nodes(self, session_id: str,
                nodes: List[CoordNode]) -> List[CoordNode]:
    """
    Given a list of nodes a worker wants to inject, return only the ones
    not already present in the session's context window.
    Workers call this before encoding their path - they only inject deltas.
    """
    active = self._active.get(session_id, set())
    return [n for n in nodes if n.node_id not in active]

# Singleton registry - shared across all navigators in a process
_session_registry = SessionRegistry()

class CoordinateNavigator:
    """
    Navigates the mycelium graph by score gradient.
    Entry point: a task embedding or known coordinates in a space.
    Returns: a MemoryPath - ordered nodes with a compact token encoding.

    Uses SessionRegistry to avoid re-injecting nodes already on the whiteboard.
    The first worker to traverse a node owns it for the session. Subsequent
    workers receive only their delta - new nodes not yet in the context window.
    """
    def __init__(self, store: CoordinateStore, scorer: EdgeScorer,
                 encoder: PathEncoder):
        self.store = store
        self.scorer = scorer
        self.encoder = encoder
        self.registry = _session_registry

    def navigate_from_task(self, task_text: str, session_id: str,
                           max_hops: int = 4,
                           min_score: float = 0.5) -> MemoryPath:
        """
        Primary entry point. Given a task string, find the best entry node
        and traverse the graph to assemble a context path.
        """

---


## Page 35

Convergence handling: nodes already active in this session are skipped during traversal. Workers get delta paths only - no redundant injection.

"""
```python
entry_nodes = self._find_entry_nodes(task_text)
if not entry_nodes:
    return MemoryPath(nodes=[], cumulative_score=0.0,
                      token_encoding="", spaces_covered=[])

best_entry = max(entry_nodes, key=lambda n: n.confidence)
path = self._traverse(best_entry, max_hops, min_score, session_id)

# Register all nodes in this path as active in the session
self.registry.register(session_id, [n.node_id for n in path.nodes])
return path
```
```

def navigate_from_coordinates(self, space_id: str,
                              coordinates: List[float],
                              session_id: str,
                              max_hops: int = 4,
                              min_score: float = 0.5) -> MemoryPath:

    entry = self.store.nearest_node(space_id, coordinates)
    if not entry:
        return MemoryPath(nodes=[], cumulative_score=0.0,
                          token_encoding="", spaces_covered=[])

    return self._traverse(entry, max_hops, min_score, session_id)


def navigate_all_spaces(self, session_id: str) -> MemoryPath:

    """
    Return the highest-confidence node from each space.
    Used for semantic_header assembly when no specific task anchor exists
    - gives a full profile snapshot at minimum token cost.
    """

    nodes = []
    for space_id in ["capability", "conduct", "domain",
                     "style", "chrono", "context"]:
        space_nodes = self.store.get_nodes_by_space(space_id)
        if space_nodes:
            # Pick highest confidence node per space
            best = max(space_nodes, key=lambda n: n.confidence)
            nodes.append(best)
            self.store.record_access(best.node_id)

    if not nodes:
        return MemoryPath(nodes=[], cumulative_score=0.0,
                          token_encoding="", spaces_covered=[])

---


## Page 36

path = MemoryPath(
    nodes=nodes,
    cumulative_score=sum(n.confidence for n in nodes) / len(nodes),
    token_encoding=self.encoder.encode(nodes),
    spaces_covered=[n.space_id for n in nodes]
)
return path

# — Internal traversal —

def _traverse(self, entry: CoordNode, max_hops: int,
             min_score: float, session_id: str) -> MemoryPath:
"""
Traverses the graph from entry node following highest-scored edges.

Convergence rule (NEW v1.1): nodes already registered as active in this session are skipped. They are already on the whiteboard – the context window of the brain agent or the plan's context string carried by child workers. Re-injecting them wastes KV budget.
"""

path_nodes = [entry]
path_edges = []
# visited combines local traversal history AND session-active nodes
visited = {entry.node_id} | self.registry._active.get(session_id, set)
current = entry
total_score = entry.confidence

self.store.record_access(entry.node_id)

for _ in range(max_hops):
    edges = self.store.get_outbound_edges(current.node_id,
                                          min_score=min_score)
    if not edges:
        break

    # Follow highest-scored edge whose target is not already on whiteboar
    next_edge = None
    for edge in edges:
        if edge.to_node_id not in visited:
            next_edge = edge
            break

    if not next_edge:
        break

    next_node = self.store.get_node(next_edge.to_node_id)
    if not next_node:

---


## Page 37

break

path_nodes.append(next_node)
path_edges.append(next_edge)
visited.add(next_node.node_id)
total_score += next_edge.score
current = next_node
self.store.record_access(next_node.node_id)

avg_score = total_score / len(path_nodes) if path_nodes else 0.0
encoding = self.encoder.encode(path_nodes)

return MemoryPath(
    nodes=path_nodes,
    cumulative_score=avg_score,
    token_encoding=encoding,
    spaces_covered=list({n.space_id for n in path_nodes}),
)

def record_path_outcome(self, path: MemoryPath,
                        outcome: str, session_id: str,
                        task_summary: str = ""):

    """
    Called after task completion to update edge scores.
    outcome: "hit" | "partial" | "miss"
    This is the learning signal that makes Mycelium smarter over time.
    """

    if len(path.nodes) < 2:
        return

    # Reconstruct edges from path node sequence
    edge_ids = []
    for i in range(len(path.nodes) - 1):
        edge = self.store.get_edge(path.nodes[i].node_id,
                                   path.nodes[i+1].node_id)
        if edge:
            edge_ids.append(edge.edge_id)

    self.scorer.record_outcome(edge_ids, outcome)
    self.store.log_traversal(
        session_id=session_id,
        path=path,
        task_summary=task_summary,
        outcome=outcome,
        tokens_saved=self._estimate_tokens_saved(path)
    )

---


## Page 38

python
def _find_entry_nodes(self, task_text: str) -> List[CoordNode]:
    """
    Find candidate entry nodes by matching task keywords to node labels.
    Returns all nodes whose label has meaningful overlap with the task.
    """
    task_lower = task_text.lower()
    candidates = []

    # Check each space for relevant nodes - include toolpath in entry search
    for space_id in ["domain", "capability", "conduct", "chrono", "toolpath"]:
        nodes = self.store.get_nodes_by_space(space_id)
        for node in nodes:
            if node.label and any(
                kw in task_lower for kw in (node.label.lower().split())
            ):
                candidates.append(node)

    # If no label matches, return all high-confidence nodes
    if not candidates:
        for space_id in ["domain", "style"]:
            nodes = self.store.get_nodes_by_space(space_id)
            candidates.extend([n for n in nodes if n.confidence > 0.7])

    return candidates


def _estimate_tokens_saved(self, path: MemoryPath) -> int:
    """Rough estimate: each node in path replaces ~12 prose tokens."""
    return len(path.nodes) * 12


def author_edge(self, from_space: str, from_coords: List[float],
               to_space: str, to_coords: List[float],
               edge_type: str = "coactivation",
               initial_score: float = 0.4):
    """
    Agent-authored edge creation. NEW v1.1.

    Called by WorkerExecutor when it observes a reliable co-occurrence during execution -
    e.g., 'every time I call web_search on a crypto task, the use finds it useful.' The agent creates the edge directly rather than waiting for distillation to detect the pattern.

    Initial score is intentionally low (0.4) - the edge must prove itself through traversal before becoming a highway. Agents can suggest paths but the scoring system validates them.

    Called via MyceliumInterface.author_edge() - never directly.
    """

---


## Page 39

python
from_node = self.store.nearest_node(from_space, from_coords)
to_node = self.store.nearest_node(to_space, to_coords)
if from_node and to_node and from_node.node_id != to_node.node_id:
    self.store.upsert_edge(
        from_node.node_id, to_node.node_id,
        edge_type, initial_score
    )
```

```python
def clear_session(self, session_id: str):
    """Wipe the session whiteboard. Called by PrimaryNode after task complete"""
    self.registry.clear(session_id)
```

# File 5: backend/memory/mycelium/encoder.py

```python
# backend/memory/mycelium/encoder.py
# PathEncoder - converts a list of CoordNodes into a compact token string

from typing import List
from backend.memory.mycelium.store import CoordNode

class PathEncoder:
    """
    Encodes a MemoryPath into a compact string for injection into context.

    The encoding must be:
    - As short as possible (minimize token count)
    - Information-dense (maximize what the model can infer per token)
    - Consistent format (model learns to parse it after a few interactions)
    - Human-debuggable (should be readable by a developer inspecting context)

    Format per node:
    {space_id}:{[coord1], [coord2], ...}@access_count}

    Full path:
    MYCELIUM: {node1} | {node2} | ... | path_score:{score:.2f}
    """

    def encode(self, nodes: List[CoordNode]) -> str:
        if not nodes:
            return ""

        parts = []
        for node in nodes:
```
```python
from typing import List
from backend.memory.mycelium.store import CoordNode

class PathEncoder:
    """
    Encodes a MemoryPath into a compact string for injection into context.

    The encoding must be:
    - As short as possible (minimize token count)
    - Information-dense (maximize what the model can infer per token)
    - Consistent format (model learns to parse it after a few interactions)
    - Human-debuggable (should be readable by a developer inspecting context)

    Format per node:
    {space_id}:{[coord1], [coord2], ...}@access_count}

    Full path:
    MYCELIUM: {node1} | {node2} | ... | path_score:{score:.2f}
    """

    def encode(self, nodes: List[CoordNode]) -> str:
        if not nodes:
            return ""

        parts = []
        for node in nodes:

---


## Page 40

python
coord_str = ",".join(f"{c:.3f}" for c in node.coordinates)
label_str = f"({node.label})" if node.label else ""
parts.append(f"{node.space_id}{label_str}:{coord_str}@{node.access_"

avg_confidence = sum(n.confidence for n in nodes) / len(nodes)
parts.append(f"confidence:{avg_confidence:.2f}")

return "MYCELIUM: " + "".join(parts)

def encode_minimal(self, nodes: List[CoordNode]) -> str:
    """
    Ultra-compact encoding for sub-agent workers where KV pressure is highest
    Drops labels and access counts. Coordinates only.
    Used by WorkerExecutor when context budget is tight.
    """
    if not nodes:
        return ""
    parts = [
        f"{n.space_id}:[{', '.join(f'{c:.2f}' for c in n.coordinates)}]"
        for n in nodes
    ]
    return "MC: " + "".join(parts)

def decode_space_hints(self, encoding: str) -> List[str]:
    """
    Extract space IDs from an encoding string.
    Used by Planner to know which spaces are represented in context.
    """
    if not encoding.startswith("MYCELIUM:") and not encoding.startswith("MC:"):
        return []
    spaces = []
    for part in encoding.split("|"):
        part = part.strip()
        if ":[" in part:
            space_id = part.split(":[")[0].split("(")[0].strip()
            if space_id not in ("MYCELIUM", "MC", "confidence"):
                spaces.append(space_id)
    return spaces
```

File 6: backend/memory/mycelium/extractor.py

# backend/memory/mycelium/extractor.py
# CoordinateExtractor - derives coordinates from text and behavior data

---


## Page 41

import re
import time
from typing import Optional, List, Tuple, Dict
from backend.memory.mycelium.spaces import SPACES, DOMAIN_IDS

class CoordinateExtractor:
    """
    Extracts coordinate values from:
    1. Explicit user statements ("I live in New York", "I prefer concise answers"
    2. Behavioral patterns from episodic store (session timestamps, tool usage)
    3. System detection (hardware capability at startup)

    Returns (space_id, coordinates, confidence, label) tuples ready for CoordinateStore.upsert_node().

    This is the bridge between language/behavior and the coordinate graph.
    The extractor runs during distillation - not at inference time.
    """

    def extract_from_statement(self, text: str) -> List[Tuple]:
        """
        Parse an explicit user statement and return coordinate tuples.
        Returns list of (space_id, coordinates, confidence, label).
        """
        results = []

        conduct = self._extract_conduct_signals(text)
        if conduct: results.append(conduct)

        style = self._extract_style(text)
        if style: results.append(style)

        domains = self._extract_domains(text)
        results.extend(domains)

        return results

    def extract_from_sessions(self, session_timestamps: List[float]) -> Optional[
    """
    Derive chrono coordinates from a list of session start timestamps.
    Returns (space_id, coordinates, confidence, label) or None if insufficient
    """
    if len(session_timestamps) < 5:
        return None

    import math

---


## Page 42

hours = [(t % 86400) / 3600 for t in session_timestamps]

# Circular mean for peak hour (hours wrap at 24)
sin_mean = sum(math.sin(2 * math.pi * h / 24) for h in hours) / len(hours)
cos_mean = sum(math.cos(2 * math.pi * h / 24) for h in hours) / len(hours)
peak_hour = (math.atan2(sin_mean, cos_mean) * 24 / (2 * math.pi)) % 24

# Estimate average session length from consecutive timestamps
gaps = sorted(session_timestamps)
session_gaps = [gaps[i+1] - gaps[i] for i in range(len(gaps)-1)]
    if gaps[i+1] - gaps[i] < 14400] # < 4 hours = same sessi
avg_session_hours = (sum(session_gaps) / len(session_gaps)) / 3600
    if session_gaps else 1.0)

# Consistency: circular variance (lower = more consistent)
r = math.sqrt(sin_mean**2 + cos_mean**2)
consistency = r # 0 = random, 1 = perfectly consistent

confidence = min(0.9, 0.3 + len(session_timestamps) * 0.05)
label = f"peak~{peak_hour:.0f}h"

return ("chrono", [peak_hour, avg_session_hours, consistency],
    confidence, label)

def extract_hardware(self) -> Optional[Tuple]:
"""
Detect hardware capability and return capability coordinates.
Runs once at startup.
"""

try:
    gpu_tier = self._detect_gpu_tier()
    ram_norm = self._detect_ram_normalized()
    has_docker = self._check_command("docker --version")
    has_ts = self._check_command("tailscale version")
    os_id = self._detect_os_id()

    coords = [gpu_tier, ram_norm,
        1.0 if has_docker else 0.0,
        1.0 if has_ts else 0.0,
        os_id]
    label = f"gpu:{gpu_tier:.0f} ram:{ram_norm*128:.0f}gb"
    return ("capability", coords, 0.95, label)
except Exception:
    return None

# — Private extractors

---


## Page 43

python
def _extract_conduct_signals(self, text: str) -> Optional[Tuple]:
    """
    Extract weak conduct signals from explicit user preference statements.

    Note: conduct coordinates are primarily built from behavioral observation (episodic outcomes, tool approval patterns) during distillation.
    This method handles the rare case where a user states a preference explicitly - e.g. "just do it without asking me" or "always confirm before running code." These statements bootstrap the conduct coordinate before enough behavioral history exists.

    The behavioral extractor in distillation.py is the authoritative source.
    This method provides early signal only.
    """

    text_lower = text.lower()

    autonomy = None
    confirmation_threshold = None

    # Autonomy signals - explicit permission statements
    if any(p in text_lower for p in [
        "just do it", "don't ask", "don't confirm", "without asking",
        "full autonomy", "handle it", "i trust you"
    ]):
        autonomy = 0.9

    elif any(p in text_lower for p in [
        "always confirm", "ask before", "check with me", "let me approve",
        "don't run anything", "show me first"
    ]):
        autonomy = 0.2
        confirmation_threshold = 0.1

    if autonomy is not None:
        # Only bootstrap - confidence is low, behavioral data will refine
        coords = [
            autonomy,
            0.5,  # iteration_style - unknown, default mid
            0.5,  # session_depth - unknown, default mid
            confirmation_threshold if confirmation_threshold else (1.0 - autonomy),
            0.3,  # correction_rate - unknown, default low-moderate
        ]
        label = f"autonomy:{autonomy:.1f}_stated"
        return ("conduct", coords, 0.4, label)  # low confidence - stated not

    return None

---


## Page 44

python
def _extract_style(self, text: str) -> Optional[Tuple]:
    """Infer style coordinates from preference statements."""
    text_lower = text.lower()

    # Verbosity signals
    verbosity = 0.5
    if any(w in text_lower for w in ["concise", "brief", "short", "quick", "tight"]):
        verbosity = 0.2
    elif any(w in text_lower for w in ["detailed", "thorough", "comprehensive", "in-depth"]):
        verbosity = 0.8

    # Directness signals
    directness = 0.5
    if any(w in text_lower for w in ["direct", "blunt", "straight", "honest", "bold"]):
        directness = 0.9
    elif any(w in text_lower for w in ["gentle", "careful", "diplomatic"]):
        directness = 0.2

    # Only return if we detected at least one signal
    if verbosity != 0.5 or directness != 0.5:
        return ("style", [0.3, verbosity, directness], 0.6, "extracted")
    return None


def _extract_domains(self, text: str) -> List[Tuple]:
    """Extract domain expertise mentions and assign proficiency estimates."""
    results = []
    text_lower = text.lower()

    domain_signals = {
        "ai": ["ai", "machine learning", "llm", "neural", "model", "inference"],
        "crypto": ["crypto", "blockchain", "web3", "defi", "solidity", "avalanche"],
        "infra": ["infrastructure", "devops", "kubernetes", "docker", "ci/cd"],
        "backend": ["backend", "api", "fastapi", "django", "server", "database"],
        "frontend": ["frontend", "react", "next.js", "ui", "css", "tailwind"],
        "security": ["security", "auth", "encryption", "zero trust", "vulnerability"],
    }

    for domain, keywords in domain_signals.items():
        if any(kw in text_lower for kw in keywords):
            domain_id = DOMAIN_IDS.get(domain, 0.5)
            results.append(
                (f"domain_{domain}"),
                [domain_id, 0.7, 1.0],  # moderate proficiency, recent
                0.6,
                f"{domain}:0.7"
            )
    return results

---


## Page 45

python
def _detect_gpu_tier(self) -> float:
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            name = result.stdout.lower()
            if any(x in name for x in ["4090", "a100", "h100"]): return 5.0
            if any(x in name for x in ["4080", "4070", "3090"]): return 4.0
            if any(x in name for x in ["4060", "3080", "3070"]): return 3.0
            if any(x in name for x in ["3060", "2080", "2070"]): return 3.0
        return 2.0
    except Exception:
        pass

try:
    import torch
    if torch.backends.mps.is_available(): return 3.0
except Exception:
    pass
return 0.0

def _detect_ram_normalized(self) -> float:
    try:
        import psutil
        return min(1.0, psutil.virtual_memory().total / (128 * 1024**3))
    except Exception:
        return 0.25

def _check_command(self, cmd: str) -> bool:
    try:
        import subprocess
        r = subprocess.run(cmd.split(), capture_output=True, timeout=2)
        return r.returncode == 0
    except Exception:
        return False

def _detect_os_id(self) -> float:
    import platform
    s = platform.system().lower()
    if s == "linux": return 0.0
    if s == "darwin": return 0.5
    return 1.0

---


## Page 46

# File 7: backend/memory/mycelium/interface.py

```python
# backend/memory/mycelium/interface.py
# MyceliumInterface - single access boundary for all Mycelium operations
# This is the ONLY file that should be imported by code outside the mycelium/ pac

from typing import Optional, List
from backend.memory.mycelium.store import CoordinateStore, MemoryPath
from backend.memory.mycelium.navigator import CoordinateNavigator
from backend.memory.mycelium.encoder import PathEncoder
from backend.memory.mycelium.scorer import EdgeScorer, MapManager
from backend.memory.mycelium.extractor import CoordinateExtractor
from backend.memory.mycelium.landmark import LandmarkCondenser, LandmarkIndex
from backend.memory.mycelium.profile import LandmarkMerger, ProfileRenderer
from backend.memory.mycelium.spaces import SPACES, tool_id as make_tool_id

class MyceliumInterface:
    """
    Single access boundary for the Mycelium layer.
    All callers - MemoryInterface, DistillationProcess, SemanticStore,
    WorkerExecutor - interact with Mycelium through this class only.

    Responsibilities:

    1. get_context_path() - coordinate path for context injection
    2. get_landmark_context() - landmark prior for Planner
    3. get_readable_profile() - full human-readable profile (NEW v1.3)
    4. get_profile_section() - single space section of profile (NEW v1.3)
    5. ingest_statement() - coordinates from user text
    6. ingest_sessions() - chrono coordinates from session data
    7. ingest_hardware() - capability coordinates at startup
    8. ingest_tool_call() - toolpath coordinates from execution
    9. record_outcome() - learning signal after task completion
    10. crystallize_landmark() - condense whiteboard -> landmark -> try merge
    11. run_decay() - edge decay every 4 hours
    12. run_condense() - merge over-close nodes
    13. run_expand() - split contradictory nodes
    14. run_profile_render() - regenerate dirty profile sections (NEW v1.3)
    15. author_edge() - agent-authored edge
    16. connect_nodes() - explicit node connection
    17. clear_session() - wipe whiteboard after task
    18. nullify_conversation() - handle conversation deletion
    19. resolve_conflict() - coordinate conflict resolution
    20. run_landmark_decay() - landmark edge decay
    21. dev_dump() - developer mode graph inspection
    """

---


## Page 47

python
def __init__(self, conn, tokenizer=None, dev_mode: bool = False):
    self.conn = conn
    self.dev_mode = dev_mode
    self.store = CoordinateStore(conn)
    self.encoder = PathEncoder()
    self.scorer = EdgeScorer(self.store)
    self.map_mgr = MapManager(self.store)
    self.navigator = CoordinateNavigator(self.store, self.scorer, self.encoder)
    self.extractor = CoordinateExtractor()
    self.lm_index = LandmarkIndex(conn, self.store)
    self.lm_condenser = LandmarkCondenser(
        self.store, self.navigator.registry, tokenizer
    )
    self.lm_merger = LandmarkMerger(conn, self.store, self.lm_index)
    self.profile = ProfileRenderer(conn, self.store, self.lm_index)
    self._ensure_spaces_registered()

def get_context_path(self, task_text: str = "",
                     session_id: str = "",
                     minimal: bool = False) -> str:
    """
    Primary output of Mycelium. Returns a compact coordinate path string ready for injection into the semantic_header zone.

    If task_text is provided, navigates from the most relevant entry node.
    If no task_text, returns full profile snapshot (one node per space).
    minimal=True returns ultra-compact encoding for KV-pressured workers.
    """
    if task_text:
        path = self.navigator.navigate_from_task(
            task_text, session_id, max_hops=4, min_score=0.5
        )
    else:
        path = self.navigator.navigate_all_spaces(session_id)

    if path.is_empty():
        return ""

    if minimal:
        return self.encoder.encode_minimal(path.nodes)
    return path.token_encoding

def ingest_statement(self, text: str, session_id: str = "") -> int:
    """
    Extract coordinate facts from a user statement and store them.
    Returns the number of nodes created or updated.
    """

---


## Page 48

Called by DistillationProcess when processing episodic content.

```python
facts = self.extractor.extract_from_statement(text)
count = 0
for space_id, coords, confidence, label in facts:
    # Normalize space_id - domain extractions prefix with "domain_"
    actual_space = space_id.split("_")[0] if "_" in space_id else space_i
    if actual_space not in SPACES:
        continue
    node = self.store.upsert_node(
        space_id=actual_space,
        coordinates=coords,
        label=label,
        confidence=confidence
    )
    # Auto-connect new node to existing nodes in same space
    self._auto_connect(node)
    count += 1
return count
```

def ingest_sessions(self, session_timestamps: List[float]) -> bool:

"""
Update chrono coordinates from session timestamp history.
Called by DistillationProcess every 4 hours.
Returns True if coordinates were updated.
"""

result = self.extractor.extract_from_sessions(session_timestamps)
if not result:
    return False
space_id, coords, confidence, label = result
self.store.upsert_node(space_id, coords, label, confidence)
return True

def ingest_hardware(self) -> bool:

"""
Detect and store capability coordinates.
Called once at application startup.
Returns True if detection succeeded.
"""

result = self.extractor.extract_hardware()
if not result:
    return False
space_id, coords, confidence, label = result
self.store.upsert_node(space_id, coords, label, confidence)
return True

def record_outcome(self, session_id: str, task_text: str, outcome: str):

---


## Page 49

"""
Learning signal. Call after every task completes.
outcome: "hit" | "partial" | "miss"
Mycelium uses this to strengthen or weaken traversal edges.
Over time, reliable paths become faster and unreliable ones decay.
"""

path = self.navigator.navigate_from_task(task_text, session_id)
if not path.is_empty():
    self.navigator.record_path_outcome(
        path, outcome, session_id, task_text[:200]
    )

def run_decay(self):
    """
    Apply time-based score decay to all edges.
    Called by DistillationProcess background daemon every 4 hours.
    Toolpath edges decay 4x faster than user-profile edges.
    Edges below prune threshold are removed. Graph stays lean.
    """

pruned = self.scorer.apply_decay(self.conn)
return pruned

def run_condense(self) -> dict:
    """
    Merge over-close nodes in each space. NEW v1.1.
    Called by DistillationProcess after decay - keeps graph lean.
    Returns counts per space for monitoring.
    """

results = {}
for space_id in SPACES:
    merged = self.map_mgr.condense(space_id)
    if merged > 0:
        results[space_id] = merged
return results

def run_expand(self) -> dict:
    """
    Split contradictory nodes in each space. NEW v1.1.
    Called by DistillationProcess after condense.
    A node showing high outcome variance is split into hit-cluster
    and miss-cluster nodes so traversal can route around failures.
    Returns counts per space for monitoring.
    """

results = {}
for space_id in SPACES:
    split = self.map_mgr.expand(space_id)
    if split > 0:

---


## Page 50

results[space_id] = split
return results

def ingest_tool_call(self, tool_name: str, success: bool,
                     sequence_position: int, total_steps: int,
                     session_id: str = ""):

"""
Update toolpath coordinates from a single tool call execution. NEW v1.1.
Called by WorkerExecutor after each tool call via PrimaryNode.

Derives toolpath node coordinates:
- tool_id: deterministic float from tool name hash
- call_frequency: updated as rolling average in store
- success_rate: updated incrementally
- avg_sequence_position: normalized position in plan

Over time this builds a toolpath map of which tools work, when,
and in what order for this user's task patterns.
"""

tid = make_tool_id(tool_name)
pos_norm = sequence_position / max(total_steps, 1)
# Upsert with incremental confidence - first call is low confidence
existing = self.store.nearest_node("toolpath", [tid, 0, 0, 0])
if existing and existing.distance_to([tid, 0, 0, 0]) < 0.01:
    # Update existing node - blend new outcome into success_rate axis
    old_coords = existing.coordinates
    old_sr = old_coords[2] if len(old_coords) > 2 else 0.5
    new_sr = old_sr * 0.9 + (1.0 if success else 0.0) * 0.1
    new_freq = min(1.0, (old_coords[1] if len(old_coords) > 1 else 0))
    new_pos = (old_coords[3] * 0.8 + pos_norm * 0.2
               if len(old_coords) > 3 else pos_norm)
    new_coords = [tid, new_freq, new_sr, new_pos]
    new_conf = min(0.95, existing.confidence + 0.01)
    self.store.upsert_node("toolpath", new_coords,
                           tool_name, new_conf)
else:
    # First call for this tool
    self.store.upsert_node(
        "toolpath",
        [tid, 0.1, 1.0 if success else 0.0, pos_norm],
        tool_name, 0.3
    )

def ingest_conduct_outcomes(self, episodes: List[Dict]) -> int:

"""
Derive and update conduct coordinates from a batch of episodic outcomes.
NEW v1.5. Called by DistillationProcess during the maintenance pass.
"""

---


## Page 51

This is the authoritative conduct extractor. Unlike _extract_conduct_sign (which handles rare explicit preference statements), this method builds t conduct coordinate from actual behavioral history - what the user did, no what they said.

episodes: list of dicts with keys:
- outcome_type: "success" | "failure" | "partial"
- user_corrected: bool - did user redirect mid-task?
- tool_calls_approved: int - how many tool calls went through uninter
- tool_calls_interrupted: int - how many the user stopped or changed
- task_complexity: float [0,1] - estimated complexity of the task
- session_token_count: int - size of session (proxy for depth)
- outcome_score: float [0,1]

Returns: 1 if conduct node updated, 0 if insufficient data.

"""
if len(episodes) < 3:
    return 0 # Need at least 3 episodes for a reliable signal

# Correction rate
corrected = sum(1 for e in episodes if e.get("user_corrected", False))
correction_rate = corrected / len(episodes)

# Autonomy - ratio of tool calls that went through uninterrupted
total_approved = sum(e.get("tool_calls_approved", 0) for e in episodes)
total_interrupted = sum(e.get("tool_calls_interrupted", 0) for e in episo
total_calls = total_approved + total_interrupted
autonomy = total_approved / total_calls if total_calls > 0 else 0.7

# Confirmation threshold - interruption rate on complex tasks specificall
complex_eps = [e for e in episodes if e.get("task_complexity", 0) > 0.6]
complex_interrupted = sum(e.get("tool_calls_interrupted", 0) for e in com
complex_calls = sum(e.get("tool_calls_approved", 0) + e.get("tool_c
for e in complex_eps)
confirmation_threshold = 1.0 - (complex_interrupted / complex_calls
if complex_calls > 0 else 0.3)

# Session depth - average complexity + token volume
avg_complexity = sum(e.get("task_complexity", 0.5) for e in episodes)
avg_tokens = sum(e.get("session_token_count", 1000) for e in episo
depth_from_tokens = min(1.0, avg_tokens / 10000)
session_depth = (avg_complexity + depth_from_tokens) / 2

# Iteration style - avg outcome score on successes: high = decisive, low
success_eps = [e for e in episodes if e.get("outcome_type") == "succes
iteration_style = (sum(e.get("outcome_score", 1.0) for e in success_eps)

---


## Page 52

python
if success_eps else 0.5)

confidence = min(0.92, 0.4 + len(episodes) * 0.02)

coords = [
    round(autonomy, 3),
    round(iteration_style, 3),
    round(session_depth, 3),
    round(confimation_threshold, 3),
    round(correction_rate, 3),
]

label = f"auto:{autonomy:.2f} corr:{correction_rate:.2f}"
self.store.upsert_node("conduct", coords, label, confidence)
return 1
```

```python
def author_edge(self, from_space: str, from_coords: List[float],
                to_space: str, to_coords: List[float],
                edge_type: str = "coactivation"):

"""
Agent-authored edge. NEW v1.1.
Called by WorkerExecutor when it observes a reliable co-occurrence.
Initial score is low (0.4) - must earn its score through traversal.
"""

self.navigator.author_edge(
    from_space, from_coords, to_space, to_coords,
    edge_type, initial_score=0.4
)
```

```python
def clear_session(self, session_id: str):

"""
Wipe the session whiteboard. NEW v1.1.
Called by PrimaryNode.handle() after every task completes,
immediately after clear_session() on working memory.
Ensures the next task starts with a clean convergence check.
"""

self.navigator.clear_session(session_id)
```

```python
def connect_nodes(self, from_space: str, from_coords: List[float],
                   to_space: str, to_coords: List[float],
                   edge_type: str = "coactivation",
                   initial_score: float = 0.5):

"""
Explicitly connect two coordinate nodes.
Called by DistillationProcess when it detects a reliable co-occurrence
pattern across spaces.
"""

from_node = self.store.nearest_node(from_space, from_coords)
to_node   = self.store.nearest_node(to_space, to_coords)

---


## Page 53

python
if from_node and to_node:
    self.store.upsert_edge(
        from_node.node_id, to_node.node_id,
        edge_type, initial_score
    )
```

def get_stats(self) -> dict:
    """
    Return graph statistics for debugging and monitoring.
    """
    nodes = self.conn.execute(
        "SELECT COUNT(*), AVG(confidence), AVG(access_count) "
        "FROM mycelium_nodes"
    ).fetchone()
    edges = self.conn.execute(
        "SELECT COUNT(*), AVG(score), MAX(score), MIN(score) "
        "FROM mycelium_edges"
    ).fetchone()
    by_space = {}
    for space_id in SPACES:
        count = self.conn.execute(
            "SELECT COUNT(*) FROM mycelium_nodes WHERE space_id=?",
            (space_id,)
        ).fetchone()[0]
        by_space[space_id] = count
    return {
        "nodes": {"count": nodes[0], "avg_confidence": nodes[1],
                  "avg_access": nodes[2], "by_space": by_space},
        "edges": {"count": edges[0], "avg_score": edges[1],
                  "max_score": edges[2], "min_score": edges[3]},
    }

def crystallize_landmark(self, session_id: str, cumulative_score: float,
                         outcome: str, task_entry_label: str = ""):
    """
    Condense the completed session whiteboard into a Landmark, then immediately try to merge it with any similar existing landmark.

    This is the layered transfer (NEW v1.3 - merge now triggered here):
    whiteboard condenses -> new landmark saved
    -> LandmarkMerger.try_merge() fires
    -> if overlap >= MERGE_OVERLAP_THRESHOLD: landmarks merge
    -> merged cluster is richer than either alone
    -> dirty flag set on affected profile sections
    -> ProfileRenderer regenerates on next distillation pass

    Called by PrimaryNode after record_outcome(), before clear_session().
    Only produces a landmark if score >= LANDMARK_MIN_SCORE and outcome != "m"
    """

---


## Page 54

python
landmark = self.lm_condenser.condense(
    session_id=session_id,
    cumulative_score=cumulative_score,
    outcome=outcome,
    task_entry_label=task_entry_label
)
if landmark:
    self.lm_index.save(landmark)
    # Immediately try merge - this is the causal link (NEW v1.3)
    self.lm_merger.try_merge(landmark)
```

```python
def get_readable_profile(self) -> str:
    """
    Return the full assembled human-readable profile. NEW v1.3.
    The profile is derived from the coordinate graph and landmark graph.
    Never manually written - always generated.

    Format: A short paragraph of natural language covering domain expertise, operational conduct, activity patterns, communication style, capabilities and active project context. toolpath is excluded (operational, agent-only

    Used for:
    - Developer mode settings panel
    - High-personalization agent contexts (injected selectively, not on every
    """
    return self.profile.get_full_profile()
```

```python
def get_profile_section(self, space_id: str) -> str:
    """
    Return a single rendered profile section for a coordinate space. NEW v1.3
    Returns empty string if section not yet rendered or space not in PROFILE_
    """
    return self.profile.get_profile_section(space_id)
```

```python
def run_profile_render(self) -> int:
    """
    Regenerate all dirty profile sections. NEW v1.3.
    Called by DistillationProcess as the final step of the maintenance pass, after run_landmark_decay().
    Returns number of sections regenerated.
    """
    return self.profile.render_dirty_sections()
```

```python
def get_landmark_context(self, task_class: str) -> str:
    """
    Return a compact landmark prior string for the Planner. NEW v1.2.
    ~40 tokens regardless of original conversation size.
    """

---


## Page 55

Returns "" if no matching landmark with sufficient score exists.
"""
return self.lm_index.get_context_for_task(task_class)

def nullify_conversation(self, session_id: str):
    """
    Handle conversation deletion. NEW v1.2.
    Sets conversation_ref = NULL on all landmarks from this session.
    The landmarks themselves are never deleted - they belong to the map.
    """
    self.lm_index.nullify_conversation(session_id)

def resolve_conflict(self, space_id: str, axis: str,
                     value_a: float, source_a: str,
                     value_b: float, source_b: str) -> float:
    """
    Resolve a coordinate conflict using landmark evidence. NEW v1.2.
    Checks which coordinate value appears in higher-scored landmarks.
    Falls back to source priority heuristic if no landmark evidence.
    Logs the resolution to mycelium_conflicts table.
    Returns the resolved coordinate value.
    """
    resolved, _ = self.lm_index.resolve_conflict(
        space_id, axis, value_a, source_a, value_b, source_b
    )
    return resolved

def run_landmark_decay(self) -> int:
    """
    Decay landmark edge scores. NEW v1.2.
    Called by DistillationProcess after run_expand().
    Permanent landmark edges decay at half rate.
    Returns number of edges pruned.
    """
    return self.lm_index.apply_landmark_decay()

def dev_dump(self) -> dict:
    """
    Developer mode only - full graph state dump. NEW v1.2.
    Returns node/edge/landmark tables as structured dict.
    Raises PermissionError if dev_mode=False.
    """
    if not self.dev_mode:
        raise PermissionError("dev_dump() is only available in developer mode")
    return self.lm_index.dump_graph()

# --- Private ---

---


## Page 56

python
def _auto_connect(self, new_node):
    """
    When a new node is added, connect it to existing nodes in the same space with an initial low-score edge.
    """
    existing = self.store.get_nodes_by_space(new_node.space_id)
    for node in existing:
        if node.node_id != new_node.node_id:
            self.store.upsert_edge(
                new_node.node_id, node.node_id,
                "coactivation", initial_score=0.3
            )

def _ensure_spaces_registered(self):
    """Register all coordinate spaces in the mycelium_spaces table on init."""
    import json
    for space_id, space in SPACES.items():
        self.conn.execute("""
            INSERT OR IGNORE INTO mycelium_spaces
            (space_id, axes, dtype, value_range, description)
            VALUES (?, ?, ?, ?, ?)
        """, (
            space_id,
            json.dumps(space.axes),
            space.dtype,
            json.dumps(list(space.value_range)),
            space.description
        ))
    self.conn.commit()
```

# File 8: backend/memory/mycelium/landmark.py

The Landmark Layer. Three classes in one file: Landmark (the data structure), LandmarkCondenser (crystallizes a whiteboard into a landmark on session end), and LandmarkIndex (stores, retrieves, and navigates between landmarks).

```python
# backend/memory/mycelium/landmark.py
# Landmark Layer - crystallized navigational patterns from completed sessions
# NEW v1.2

import struct
import uuid

---


## Page 57

python
import time
import json
import math

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

from backend.memory.mycelium.store import CoordinateStore, CoordNode, MemoryPath
from backend.memory.mycelium.navigator import SessionRegistry


# How many sessions must activate a landmark before its nodes go permanent
PERMANENCE_THRESHOLD = 8

# Minimum cumulative score for a session to produce a landmark at all
LANDMARK_MIN_SCORE = 0.45

# Maximum nodes in a coordinate cluster - keeps landmarks lean
CLUSTER_MAX_NODES = 6

# Landmark edges below this score are pruned (same rhythm as node edges)
LANDMARK_PRUNE_THRESHOLD = 0.08


# — Data structure —

@dataclass
class Landmark:
    """
    A crystallized navigational pattern from a completed session.

    The landmark is the card catalogue entry, not the book.
    It carries enough to find the knowledge and know if it's worth opening - not the knowledge itself.

    Conversation can be deleted. Landmark survives.
    The landmark belongs to the map, not the content.
    """

    landmark_id: str
    label: Optional[str]
    task_class: str # e.g. "domain_ai:research" or "toolp
    coordinate_cluster: List[Dict] # [{node_id, activation_count}, ...]
    traversal_sequence: List[str] # node_ids in activation order
    cumulative_score: float
    micro_abstract: Optional[bytes] # packed int32 token IDs - model's na
    micro_abstract_text: Optional[str] # decoded, dev mode only
    activation_count: int
    is_permanent: bool

---


## Page 58

conversation_ref: Optional[str] # session_id of origin, null if delet
created_at: float
last_activated: Optional[float]

def to_context_string(self) -> str:
    """
    Compact encoding for context injection.
    ~40 tokens regardless of original conversation length.
    Format: LANDMARK:{id}|class:{task_class}|score:{score:.2f}|nodes:{n}|act:
    """
    n = len(self.coordinate_cluster)
    top_nodes = self.coordinate_cluster[:3] # top 3 by activation count
    node_str = ",".join(c["node_id"][:8] for c in top_nodes)
    return (f"LANDMARK:{self.landmark_id[:8]}"
            f"|class:{self.task_class}"
            f"|score:{self.cumulative_score:.2f}"
            f"|nodes:{n}:{node_str}"
            f"|act:{self.activation_count}")

def to_remote(self) -> Dict:
    """
    Torus-safe representation. Strips labels, micro-abstract text,
    and conversation reference. Sends only coordinate structure and scores.
    A peer receives navigational shape without any personal content.
    """
    return {
        "landmark_id": self.landmark_id,
        "task_class": self.task_class,
        "cumulative_score": self.cumulative_score,
        "cluster_size": len(self.coordinate_cluster),
        "traversal_length": len(self.traversal_sequence),
        "activation_count": self.activation_count,
        # No label, no micro_abstract_text, no conversation_ref
    }

def nullify_conversation(self):
    """
    Called when the originating conversation is deleted.
    Landmark itself is untouched - only the pointer goes null.
    """
    self.conversation_ref = None

def _pack_token_ids(token_ids: List[int]) -> bytes:
    """
    Pack token ID list as int32 array - the numbering system.
    """
    return struct.pack(f'{len(token_ids)}i', *token_ids)

---


## Page 59

python
def _unpack_token_ids(blob: bytes) -> List[int]:
    n = len(blob) // 4
    return list(struct.unpack(f'{n}i', blob))
```

# — Condenser —

class LandmarkCondenser:

"""
Crystallizes a completed session whiteboard into a Landmark.

Called by PrimaryNode.handle() after record_outcome() and before clear_sessio
Only produces a landmark if the session score meets LANDMARK_MIN_SCORE -
failed or shallow sessions don't become landmarks.

The condenser answers three questions about the whiteboard:
1. Which nodes were activated most? (coordinate cluster)
2. Which activation path scored highest? (traversal sequence)
3. What was the navigational essence? (micro-abstract token IDs)

It does NOT read the conversation content. It reads only the
SessionRegistry traversal log and the node access counts for this session.
The landmark contains no user words, no task description text.
"""

def __init__(self, store: CoordinateStore, registry: SessionRegistry,
             tokenizer=None):
    self.store = store
    self.registry = registry
    self.tokenizer = tokenizer  # optional - if None, micro_abstract is None

def condense(self, session_id: str, cumulative_score: float,
             outcome: str, task_entry_label: str = "") -> Optional["Landmark"]:
    """
    Produce a Landmark from the completed session, or None if score too low.

    session_id: the just-completed session
    cumulative_score: average edge score across all traversals this session
    outcome: "hit" | "partial" | "miss"
    task_entry_label: label of the entry node that started navigation
    """

    if cumulative_score < LANDMARK_MIN_SCORE:
        return None
    if outcome == "miss":
        return None  # Failed sessions don't become landmarks

---


## Page 60

active_nodes = self.registry._active.get(session_id, set())
if not active_nodes:
    return None

# Fetch node objects and rank by access count in this session
nodes = []
for node_id in active_nodes:
    node = self.store.get_node(node_id)
    if node:
        nodes.append(node)

if not nodes:
    return None

# Build coordinate cluster - top N by access count, capped at CLUSTER_MAX
nodes.sort(key=lambda n: n.access_count, reverse=True)
cluster_nodes = nodes[:CLUSTER_MAX_NODES]
coordinate_cluster = [
    {"node_id": n.node_id, "activation_count": n.access_count,
     "space_id": n.space_id}
    for n in cluster_nodes
]

# Traversal sequence - order of first activation (use registry order prox
# Registry stores as a set, so we reconstruct order from access timestamp
# by sorting cluster nodes by last_accessed ascending
ordered = sorted(
    cluster_nodes,
    key=lambda n: n.last_accessed or n.created_at
)
traversal_sequence = [n.node_id for n in ordered]

# Task class fingerprint - dominant space of entry node
dominant_space = cluster_nodes[0].space_id if cluster_nodes else "unknown"
entry_hint = task_entry_label[:20] if task_entry_label else "session"
task_class = f"{dominant_space}:{entry_hint}"

# Micro-abstract - pack as token IDs if tokenizer available
micro_abstract = None
micro_abstract_text = None
if self.tokenizer:
    # Build a minimal text description from coordinate cluster
    abstract_text = self._build_abstract_text(cluster_nodes, cumulative_s
    token_ids = self.tokenizer.encode(abstract_text)[:30]  # cap at 3
    micro_abstract = _pack_token_ids(token_ids)
    micro_abstract_text = abstract_text  # stored separately, dev mode on

---


## Page 61

python
label = f"{dominant_space}:{int(time.time())}"

return Landmark(
    landmark_id = str(uuid.uuid4()),
    label = label,
    task_class = task_class,
    coordinate_cluster = coordinate_cluster,
    traversal_sequence = traversal_sequence,
    cumulative_score = cumulative_score,
    micro_abstract = micro_abstract,
    micro_abstract_text = micro_abstract_text,
    activation_count = 0,
    is_permanent = False,
    conversation_ref = session_id,
    created_at = time.time(),
    last_activated = None,
)
```

```python
def _build_abstract_text(self, nodes: List[CoordNode],
                         score: float) -> str:

    """
    Build a compact text description of the session for tokenization.
    This is the only prose in the landmark - and it becomes token IDs
    immediately. The text itself is not stored in production mode.
    Maximum 30 tokens when encoded.
    """

    spaces = list({n.space_id for n in nodes})
    labels = [n.label for n in nodes if n.label][:3]
    label_str = " ".join(labels) if labels else "unlabeled"
    return f"{' '.join(spaces)} {label_str} score:{score:.2f}"
```

# — Index —

class LandmarkIndex:
"""
Stores, retrieves, and navigates between Landmarks.

The landmark graph is a higher-order layer on top of the coordinate graph.
Landmarks are connected by scored edges just like nodes are.
The navigator can traverse landmark edges the same way it traverses node edge
following score gradient to find the most relevant prior session pattern.

Also handles:
- Node promotion to permanent tier based on landmark activation counts
- Conflict resolution using landmark evidence
- Conversation deletion (nullify_conversation)

---


## Page 62

- Torus-safe remote export

```python
def __init__(self, conn, store: CoordinateStore):
    self.conn = conn
    self.store = store

def save(self, landmark: Landmark):
    """Persist a new landmark to the database."""
    self.conn.execute("""
        INSERT INTO mycelium_landmarks
        (landmark_id, label, task_class, coordinate_cluster, traversal_sequence,
         cumulative_score, micro_abstract, micro_abstract_text, activation_count,
         is_permanent, conversation_ref, created_at, last_activated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        landmark.landmark_id,
        landmark.label,
        landmark.task_class,
        json.dumps(landmark.coordinate_cluster),
        json.dumps(landmark.traversal_sequence),
        landmark.cumulative_score,
        landmark.micro_abstract,
        landmark.micro_abstract_text,
        landmark.activation_count,
        1 if landmark.is_permanent else 0,
        landmark.conversation_ref,
        landmark.created_at,
        landmark.last_activated,
    ))
    self.conn.commit()

# Auto-connect to similar landmarks
self._auto_connect_landmark(landmark)

def find_matching(self, task_class: str,
                  min_score: float = 0.4) -> List[Landmark]:
    """
    Find landmarks matching a task class fingerprint.
    Used by Planner to snap to a prior navigational pattern
    before even beginning graph traversal.
    """
    rows = self.conn.execute("""
        SELECT * FROM mycelium_landmarks
        WHERE task_class LIKE ? AND cumulative_score >= ?
        ORDER BY activation_count DESC, cumulative_score DESC
        LIMIT 5
    """, (task_class, min_score))
    return [Landmark(*row) for row in rows]
```

```mermaid
classDiagram
    Class Landmark {
        - landmark_id: int
        - label: str
        - task_class: str
        - coordinate_cluster: dict
        - traversal_sequence: list
        - cumulative_score: float
        - micro_abstract: str
        - micro_abstract_text: str
        - activation_count: int
        - is_permanent: bool
        - conversation_ref: str
        - created_at: datetime
        - last_activated: datetime
    }
    Class CoordinateStore {
        - conn: Connection
    }
    Class MyceliumDatabase {
        - conn: Connection
        - store: CoordinateStore
        - _auto_connect_landmark(Landmark): None
        - find_matching(task_class: str, min_score: float = 0.4): List[Landmark]
    }
    Landmark --> CoordinateStore : store
    MyceliumDatabase --> CoordinateStore : store

---


## Page 63

"""
(f"{task_class.split(': ')[0]}%", min_score)).fetchall()
return [self._row_to_landmark(r) for r in rows]

def activate(self, landmark_id: str):
"""
Record that a future session snapped to this landmark.
Increments activation_count. Checks for permanence promotion.
"""
self.conn.execute("""
UPDATE mycelium_landmarks
SET activation_count = activation_count + 1,
    last_activated = ?
WHERE landmark_id = ?
""")
(self.time.time(), landmark_id))
self.conn.commit()

# Check promotion threshold
row = self.conn.execute(
    "SELECT activation_count FROM mycelium_landmarks WHERE landmark_id=?"
)(landmark_id,)
).fetchone()
if row and row[0] >= PERMANENCE_THRESHOLD:
    self._promote_to_permanent(landmark_id)

def nullify_conversation(self, session_id: str):
"""
Called when a conversation is deleted.
Sets conversation_ref to NULL for all landmarks from that session.
The landmark itself is completely untouched - only the pointer goes null.
"""
self.conn.execute("""
UPDATE mycelium_landmarks
SET conversation_ref = NULL
WHERE conversation_ref = ?
""")
(session_id,))
self.conn.commit()

def resolve_conflict(self, space_id: str, axis: str,
                     value_a: float, source_a: str,
                     value_b: float, source_b: str) -> Tuple[float, str]:
"""
Resolve a coordinate conflict using landmark evidence.

Strategy:
1. Find all landmarks whose coordinate cluster contains nodes from this s
2. For each landmark, check which value (a or b) was closer to the node's
   coordinate on the conflicted axis

---


## Page 64

3. Sum the cumulative scores of landmarks supporting each value
4. The value with higher landmark-weighted support wins
5. Log the resolution

Falls back to confidence comparison if no landmark evidence exists.
Returns (resolved_value, resolution_basis).

"""
# Get all landmarks with nodes in this space
landmarks = self._get_landmarks_for_space(space_id)

score_a = 0.0
score_b = 0.0

for lm in landmarks:
    for cluster_entry in lm.coordinate_cluster:
        node = self.store.get_node(cluster_entry["node_id"])
        if not node or node.space_id != space_id:
            continue
        # Find the axis index in this space
        from backend.memory.mycelium.spaces import get_space
        try:
            space = get_space(space_id)
            axis_idx = space.axes.index(axis)
            if axis_idx >= len(node.coordinates):
                continue
            node_val = node.coordinates[axis_idx]
            # This landmark's score supports whichever value is closer
            dist_a = abs(node_val - value_a)
            dist_b = abs(node_val - value_b)
            if dist_a < dist_b:
                score_a += lm.cumulative_score
            else:
                score_b += lm.cumulative_score
        except (ValueError, IndexError):
            continue

if score_a == 0.0 and score_b == 0.0:
    # No landmark evidence - fall back to source confidence heuristic
    # behavioral > statement > hardware for dynamic axes
    priority = {"behavioral": 3, "hardware": 2, "statement": 1}
    pa, pb = priority.get(source_a, 0), priority.get(source_b, 0)
    resolved = value_a if pa >= pb else value_b
    basis = "confidence"
else:
    resolved = value_a if score_a >= score_b else value_b
    basis = "landmark_score"

---


## Page 65

# Log the resolution

```python
self.conn.execute("""
    INSERT INTO mycelium_conflicts
    (conflict_id, space_id, axis, value_a, source_a, value_b, source_b,
     resolved_value, resolution_basis, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (str(uuid.uuid4())[:12], space_id, axis,
      value_a, source_a, value_b, source_b,
      resolved, basis, time.time()))
self.conn.commit()
```

return resolved, basis

```python
def get_context_for_task(self, task_class: str) -> str:
    """
    Returns the to_context_string() of the best matching landmark for this
    task class. Used by Planner as a navigational prior before traversal.
    ~40 tokens. Returns empty string if no match.
    """
    matches = self.find_matching(task_class, min_score=0.5)
    if not matches:
        return ""
    best = matches[0]
    self.activate(best.landmark_id)
    return best.to_context_string()
```

```python
def connect_landmarks(self, from_id: str, to_id: str,
                      edge_type: str = "sequential",
                      initial_score: float = 0.5):
    """
    Create a scored edge between two landmarks.
    """
    edge_id = str(uuid.uuid4())[:12]
    self.conn.execute("""
        INSERT OR IGNORE INTO mycelium_landmark_edges
        (edge_id, from_landmark_id, to_landmark_id, score, edge_type,
         traversal_count, hit_count, miss_count, created_at)
        VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?)
    """, (edge_id, from_id, to_id, initial_score, edge_type, time.time()))
    self.conn.commit()
```

```python
def apply_landmark_decay(self):
    """
    Decay landmark edge scores. Landmarks themselves don't decay -
    only their edges do. A landmark with no strong edges becomes
    unreachable but persists as a record.
    Landmarks with is_permanent=1 have their edges decay at half rate.
    """
    now = time.time()

---


## Page 66

edges = self.conn.execute("""

    SELECT le.edge_id, le.score, le.last_traversed, lm.is_permanent
    FROM mycelium_landmark_edges le
    JOIN mycelium_landmarks lm ON le.from_landmark_id = lm.landmark_id

""").fetchall()

pruned = 0
for edge_id, score, last_traversed, is_permanent in edges:
    days_idle = ((now - last_traversed) / 86400.0) if last_traversed else 0
    decay_rate = 0.002 if is_permanent else 0.005
    new_score = max(0.0, score - decay_rate * days_idle)
    if new_score < LANDMARK_PRUNE_THRESHOLD:
        self.conn.execute(
            "DELETE FROM mycelium_landmark_edges WHERE edge_id=?", (edge_id,)
        )
        pruned += 1
    else:
        self.conn.execute(
            "UPDATE mycelium_landmark_edges SET score=? WHERE edge_id=?", (new_score, edge_id)
        )

self.conn.commit()
return pruned


def dump_graph(self) -> Dict:

    """
    Developer mode only. Full structured dump of landmark graph state.
    Exposed via MyceliumInterface.dev_dump(). Never called in personal mode.
    """

    landmarks = self.conn.execute(
        "SELECT landmark_id, label, task_class, cumulative_score, "
        "activation_count, is_permanent, conversation_ref FROM mycelium_landm"
    ).fetchall()
    edges = self.conn.execute(
        "SELECT from_landmark_id, to_landmark_id, score, edge_type "
        "FROM mycelium_landmark_edges ORDER BY score DESC"
    ).fetchall()
    return {
        "landmarks": [
            {"id": r[0], "label": r[1], "task_class": r[2],
             "score": r[3], "activations": r[4],
             "permanent": bool(r[5]), "has_conversation": r[6] is not None}
            for r in landmarks
        ],
        "edges": [
            {"from": r[0][:8], "to": r[1][:8], "score": r[2], "type": r[3]}
            for r in edges
        ]
    }

---


## Page 67

l,
}

# — Private —

def _promote_to_permanent(self, landmark_id: str):
"""
Mark a landmark as permanent and make all its constituent nodes immune to decay. Called when activation_count >= PERMANENCE_THRESHOLD.
"""

self.conn.execute("""
    UPDATE mycelium_landmarks SET is_permanent=1 WHERE landmark_id=?
""", (landmark_id,))

# Fetch cluster and mark each node permanent via a label flag
row = self.conn.execute(
    "SELECT coordinate_cluster FROM mycelium_landmarks WHERE landmark_id=?
    (landmark_id,)
).fetchone()
if row:
    cluster = json.loads(row[0])
    for entry in cluster:
        # Set a permanent flag on the node by giving it max confidence
        # The decay system checks confidence - nodes at 1.0 are treated a
        self.conn.execute("""
            UPDATE mycelium_nodes SET confidence=1.0 WHERE node_id=?
        """, (entry["node_id"],))
self.conn.commit()

def _auto_connect_landmark(self, new_landmark: Landmark):
"""
Connect a new landmark to existing landmarks with similar task_class. Initial score 0.4 - must earn its weight through traversal.
"""

dominant = new_landmark.task_class.split(":")[0]
similar = self.conn.execute("""
    SELECT landmark_id FROM mycelium_landmarks
    WHERE task_class LIKE ? AND landmark_id != ?
    ORDER BY cumulative_score DESC LIMIT 5
""", (f"{dominant}%", new_landmark.landmark_id)).fetchall()

for (existing_id,) in similar:
    self.connect_landmarks(
        new_landmark.landmark_id, existing_id,
        edge_type="domain", initial_score=0.4
    )

---


## Page 68

python
def _get_landmarks_for_space(self, space_id: str) -> List[Landmark]:
    """Get all landmarks containing at least one node from the given space."""
    rows = self.conn.execute(
        "SELECT * FROM mycelium_landmarks"
    ).fetchall()
    result = []
    for row in rows:
        lm = self._row_to_landmark(row)
        spaces = {c.get("space_id") for c in lm.coordinate_cluster}
        if space_id in spaces:
            result.append(lm)
    return result

def _row_to_landmark(self, row) -> Landmark:
    return Landmark(
        landmark_id = row[0],
        label = row[1],
        task_class = row[2],
        coordinate_cluster = json.loads(row[3]),
        traversal_sequence = json.loads(row[4]),
        cumulative_score = row[5],
        micro_abstract = row[6],
        micro_abstract_text = row[7],
        activation_count = row[8],
        is_permanent = bool(row[9]),
        conversation_ref = row[10],
        created_at = row[11],
        last_activated = row[12],
    )
```

File 9: backend/memory/mycelium/profile.py

Two classes: LandmarkMerger (triggered by whiteboard condense, produces richer unified landmarks) and ProfileRenderer (derives human-readable prose from the coordinate and landmark graphs). These are the layered transfer and the human face.

# backend/memory/mycelium/profile.py
# LandmarkMerger + ProfileRenderer - layered transfer and readable profile
# NEW v1.3

import uuid
import time
import json
import math

---


## Page 69

from typing import List, Optional, Dict, Tuple

from backend.memory.mycelium.store import CoordinateStore, CoordNode
from backend.memory.mycelium.landmark import (
    Landmark, LandmarkIndex, PERMANENCE_THRESHOLD
)
from backend.memory.mycelium.spaces import SPACES, get_space

# Cluster overlap ratio that triggers a landmark merge
# 0.5 = at least half the smaller cluster's nodes must appear in the larger
MERGE_OVERLAP_THRESHOLD = 0.50

# Spaces that render into the readable profile - ordered by display priority
# context replaces affect as of v1.6 - affect absorbed into style/conduct via lan
PROFILE_SPACES = ["domain", "conduct", "chrono", "style", "capability", "context"]

# Spaces deliberately excluded from the readable profile
# toolpath: operational, agent-only
# affect: removed v1.6 - replaced by context
PROFILE_EXCLUDED = {"toolpath"}

# — Landmark Merger —

class LandmarkMerger:
    """
    Triggered automatically when a whiteboard condenses into a new landmark.
    Checks whether the new landmark overlaps significantly with any existing
    landmark of the same task class. If so, merges them.

    This is the layered transfer:
        session ends
        -> whiteboard condenses -> new landmark
        -> LandmarkMerger fires
        -> new landmark merges with similar existing landmark
        -> merged landmark has richer coordinate cluster
        -> ProfileRenderer detects dirty flag
        -> profile regenerates from enriched state

    The merge is not destructive. The absorbed landmark is soft-deleted
    (marked absorbed=True) but kept for audit purposes in the merge log.
    All edges pointing to the absorbed landmark are re-pointed to the survivor.

    The survivor is whichever landmark has higher activation_count.
    If equal, the one with higher cumulative_score survives.
    """

---


## Page 70

python
def __init__(self, conn, store: CoordinateStore, lm_index: LandmarkIndex):
    self.conn = conn
    self.store = store
    self.lm_index = lm_index

def try_merge(self, new_landmark: Landmark) -> Optional[Landmark]:
    """
    Called immediately after a new landmark is saved.
    Returns the merged landmark if a merge occurred, None otherwise.

    The profile dirty flag is set on the affected spaces if a merge happens.
    """
    candidates = self._find_merge_candidates(new_landmark)
    if not candidates:
        return None

    # Take the highest-overlap candidate
    best_candidate, overlap_score = candidates[0]
    if overlap_score < MERGE_OVERLAP_THRESHOLD:
        return None

    merged = self._merge(new_landmark, best_candidate, overlap_score)
    return merged

def _find_merge_candidates(
    self, landmark: Landmark
) -> List[Tuple[Landmark, float]]:
    """
    Find existing landmarks of the same task class whose coordinate cluster overlaps with the new landmark's cluster.
    Returns list of (candidate, overlap_ratio) sorted by overlap desc.
    """
    dominant = landmark.task_class.split(":") [0]
    rows = self.conn.execute("""
        SELECT * FROM mycelium_landmarks
        WHERE task_class LIKE ?
        AND landmark_id != ?
        AND (absorbed IS NULL OR absorbed = 0)
        ORDER BY activation_count DESC, cumulative_score DESC
        LIMIT 10
    """, (f"{dominant}%", landmark.landmark_id)).fetchall()

    candidates = []
    new_node_ids = {c["node_id"] for c in landmark.coordinate_cluster}

    for row in rows:
        candidate = Landmark(row)
        if candidate.landmark_id == landmark.landmark_id:
            continue
        if candidate.task_class != landmark.task_class:
            continue
        if candidate.coordinate_cluster & new_node_ids:
            candidates.append((candidate, row["overlap_ratio"]))
```
```python
def _find_merge_candidates(
    self, landmark: Landmark
) -> List[Tuple[Landmark, float]]:
    """
    Find existing landmarks of the same task class whose coordinate cluster overlaps with the new landmark's cluster.
    Returns list of (candidate, overlap_ratio) sorted by overlap desc.
    """
    dominant = landmark.task_class.split(":") [0]
    rows = self.conn.execute("""
        SELECT * FROM mycelium_landmarks
        WHERE task_class LIKE ?
        AND landmark_id != ?
        AND (absorbed IS NULL OR absorbed = 0)
        ORDER BY activation_count DESC, cumulative_score DESC
        LIMIT 10
    """, (f"{dominant}%", landmark.landmark_id)).fetchall()

    candidates = []
    new_node_ids = {c["node_id"] for c in landmark.coordinate_cluster}

    for row in rows:
        candidate = Landmark(row)
        if candidate.landmark_id == landmark.landmark_id:
            continue
        if candidate.task_class != landmark.task_class:
            continue
        if candidate.coordinate_cluster & new_node_ids:
            candidates.append((candidate, row["overlap_ratio"]))

---


## Page 71

candidate = self.lm_index._row_to_landmark(row)
cand_ids = {c["node_id"] for c in candidate.coordinate_cluster}
# Overlap ratio = intersection / smaller cluster
intersection = len(new_node_ids & cand_ids)
smaller = min(len(new_node_ids), len(cand_ids))
if smaller == 0:
    continue
overlap = intersection / smaller
if overlap > 0:
    candidates.append((candidate, overlap))

candidates.sort(key=lambda x: x[1], reverse=True)
return candidates

def _merge(self, new_lm: Landmark, existing_lm: Landmark,
           overlap_score: float) -> Landmark:

"""
Merge two landmarks. Survivor = higher activation_count (or score if tied
Produces a richer unified landmark with a merged coordinate cluster.
"""

# Determine survivor and absorbed
if existing_lm.activation_count > new_lm.activation_count:
    survivor, absorbed = existing_lm, new_lm
elif new_lm.activation_count > existing_lm.activation_count:
    survivor, absorbed = new_lm, existing_lm
else:
    # Equal activations - higher score survives
    if existing_lm.cumulative_score >= new_lm.cumulative_score:
        survivor, absorbed = existing_lm, new_lm
    else:
        survivor, absorbed = new_lm, existing_lm

# Merge coordinate clusters - weighted union
# Nodes in both: keep the one with higher activation_count
# Nodes in only one: include if from survivor, include if activation >= 2
merged_cluster = self._merge_clusters(
    survivor.coordinate_cluster, absorbed.coordinate_cluster
)

# Merged score - confidence-weighted average
w_s = survivor.activation_count + 1
w_a = absorbed.activation_count + 1
merged_score = (
    (survivor.cumulative_score * w_s + absorbed.cumulative_score * w_a)
    / (w_s + w_a)
)

---


## Page 72

# Merged traversal - survivor's sequence with absorbed nodes appended if
survivor_seq = survivor.traversal_sequence
absorbed_novel = [
    n for n in absorbed.traversal_sequence
    if n not in set(survivor_seq)
]
merged_sequence = survivor_seq + absorbed_novel

# Update survivor in DB with merged data
self.conn.execute("""
    UPDATE mycelium_landmarks
    SET coordinate_cluster = ?,
        traversal_sequence = ?,
        cumulative_score = ?,
        micro_abstract = NULL,
        micro_abstract_text = NULL
    WHERE landmark_id = ?
""", (
    json.dumps(merged_cluster),
    json.dumps(merged_sequence),
    merged_score,
    survivor.landmark_id
)))

# Mark absorbed as absorbed (soft delete)
self.conn.execute("""
    UPDATE mycelium_landmarks
    SET absorbed = 1
    WHERE landmark_id = ?
""", (absorbed.landmark_id,))

# Re-point all edges from absorbed -> survivor
self.conn.execute("""
    UPDATE mycelium_landmark_edges
    SET from_landmark_id = ?
    WHERE from_landmark_id = ?
""", (survivor.landmark_id, absorbed.landmark_id))
self.conn.execute("""
    UPDATE mycelium_landmark_edges
    SET to_landmark_id = ?
    WHERE to_landmark_id = ?
""", (survivor.landmark_id, absorbed.landmark_id))

# Log the merge
self.conn.execute("""
    INSERT INTO mycelium_landmark_merges
    (merge_id, survivor_id, absorbed_id, overlap_score,
    """, (merge_id, survivor.landmark_id, absorbed.landmark_id, overlap_score))

---


## Page 73

python
pre_merge_score_s, pre_merge_score_a, post_merge_score, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
(
str(uuid.uuid4())[:12],
survivor.landmark_id, absorbed.landmark_id, overlap_score,
survivor.cumulative_score, absorbed.cumulative_score,
merged_score, time.time()
)
self.conn.commit()

# Mark profile dirty for all spaces covered by merged cluster
self._mark_profile_dirty(merged_cluster)

# Return updated survivor
survivor.coordinate_cluster = merged_cluster
survivor.traversal_sequence = merged_sequence
survivor.cumulative_score = merged_score
return survivor

def _merge_clusters(self, cluster_s: List[Dict],
                    cluster_a: List[Dict]) -> List[Dict]:
    """
    Weighted union of two coordinate clusters.
    If a node appears in both, keep whichever has higher activation_count.
    Include nodes from absorbed cluster if activation_count >= 2 (earned presence)
    Cap at CLUSTER_MAX_NODES (imported from landmark.py) - keep highest-activated nodes
    """
    from backend.memory.mycelium.landmark import CLUSTER_MAX_NODES

    by_id: Dict[str, Dict] = {}

    for entry in cluster_s:
        by_id[entry["node_id"]] = entry

    for entry in cluster_a:
        nid = entry["node_id"]
        if nid in by_id:
            # Keep higher activation
            if entry["activation_count"] > by_id[nid]["activation_count"]:
                by_id[nid] = entry
        elif entry["activation_count"] >= 2:
            # Only include absorbed-only nodes if they've earned presence
            by_id[nid] = entry

    merged = sorted(by_id.values(), key=lambda e: e["activation_count"], reverse=True)
    return merged[:CLUSTER_MAX_NODES]

---


## Page 74

python
def _mark_profile_dirty(self, cluster: List[Dict]):
    """
    Set dirty=1 on profile sections for all spaces covered by this cluster.
    ProfileRenderer will regenerate those sections on next distillation pass.
    """
    spaces_affected = {entry.get("space_id") for entry in cluster
                       if entry.get("space_id") in PROFILE_SPACES}
    for space_id in spaces_affected:
        self.conn.execute("""
            UPDATE mycelium_profile SET dirty = 1 WHERE space_id = ?
        """, (space_id,))
    self.conn.commit()
```

# — Profile Renderer —

class ProfileRenderer:

"""
Derives a human-readable prose profile from the coordinate graph and landmark graph. Called by DistillationProcess when profile sections are dirty

The profile is the translation of the map into human language. The map is the truth. The profile is the projection.

It is never manually written or edited. It is always re-derived. When coordinates shift, the profile regenerates to match.

Structure:
Each rendered space produces one profile section - a short prose paragraph or sentence. The full profile is the sections assembled in render_order.

Stratification rules:
- domain -> renders fully: expertise areas with proficiency language
- conduct -> renders fully: operational identity - autonomy, working sty
- chrono -> renders fully: activity pattern description
- style -> renders fully: communication preference summary
- capability -> renders as capability summary, not raw specs
- context -> renders fully: active project and environment summary (v1.6
- toolpath -> NOT rendered (operational, agent-only)
- affect -> REMOVED v1.6 (replaced by context, absorbed into style/cond

The rendered profile is stored in mycelium_profile and surfaced in two places
1. Developer mode - full profile visible in settings/debug panel
2. Agent context - an optional `user_profile` zone in MemoryInterface, injected only when the task requires high personalization and the coordinate path alone is insufficient. NOT injected on every call.
"""

---


## Page 75

python
def __init__(self, conn, store: CoordinateStore, lm_index: LandmarkIndex):
    self.conn = conn
    self.store = store
    self.lm_index = lm_index

def render_dirty_sections(self) -> int:
    """
    Find all dirty profile sections and re-render them.
    Called by DistillationProcess after maintenance pass.
    Returns number of sections regenerated.
    """
    dirty_rows = self.conn.execute(
        "SELECT section_id, space_id FROM mycelium_profile WHERE dirty = 1"
    ).fetchall()

    # Also render any spaces that have nodes but no profile section yet
    existing_spaces = {r[1] for r in dirty_rows}
    for space_id in PROFILE_SPACES:
        if space_id not in existing_spaces:
            nodes = self.store.get_nodes_by_space(space_id)
            if nodes:
                dirty_rows.append((None, space_id))

    count = 0
    for section_id, space_id in dirty_rows:
        prose = self._render_space(space_id)
        if not prose:
            continue
        nodes = self.store.get_nodes_by_space(space_id)
        node_ids = [n.node_id for n in nodes]
        lm_ids = self._get_landmark_ids_for_space(space_id)

        if section_id:
            self.conn.execute("""
                UPDATE mycelium_profile
                SET prose=?, source_node_ids=?, source_lm_ids=?,
                    dirty=0, last_rendered=?, word_count=?
                WHERE section_id=?
            """, (prose, json.dumps(node_ids), json.dumps(lm_ids),
                  time.time(), len(prose.split()), section_id))
        else:
            self.conn.execute("""
                INSERT INTO mycelium_profile
                (section_id, space_id, render_order, prose, source_node_ids,
                 source_lm_ids, dirty, last_rendered, word_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (None, space_id, 0, prose, json.dumps(node_ids), json.dumps(lm_ids),
                  time.time(), len(prose.split())))

---


## Page 76

"""
(
    str(uuid.uuid4())[:12],
    space_id,
    PROFILE_SPACES.index(space_id),
    prose,
    json.dumps(node_ids),
    json.dumps(lm_ids),
    time.time(),
    len(prose.split())
)
"""

count += 1

self.conn.commit()
return count


def get_full_profile(self) -> str:
    """
    Assemble and return the full readable profile as a single prose string.
    Sections joined in render_order. Used for developer mode display and
    high-personalization agent contexts.
    """
    rows = self.conn.execute("""
        SELECT prose FROM mycelium_profile
        WHERE dirty = 0
        ORDER BY render_order ASC
    """).fetchall()
    if not rows:
        return ""
    return "".join(r[0] for r in rows if r[0])


def get_profile_section(self, space_id: str) -> str:
    """
    Return a single rendered section for a given space.
    """
    row = self.conn.execute(
        "SELECT prose FROM mycelium_profile WHERE space_id=? AND dirty=0",
        (space_id,)
    ).fetchone()
    return row[0] if row else ""


# — Space renderers —

def _render_space(self, space_id: str) -> str:
    """
    Dispatch to the appropriate space renderer.
    """
    renderers = {
        "domain": self._render_domain,
        "conduct": self._render_conduct,  # v1.5 - replaces location
        "chrono": self._render_chrono,
        "style": self._render_style,
        "location": self._render_location,
        "context": self._render_context,
        "content": self._render_content,
        "footer": self._render_footer,
    }

---


## Page 77

json
"capability": self._render_capability,
"context": self._render_context,  # v1.6 - replaces affect
}
```

renderer = renderers.get(space_id)
if not renderer:
    return ""
nodes = self.store.get_nodes_by_space(space_id)
if not nodes:
    return ""
return renderer(nodes)

def _render_domain(self, nodes: List[CoordNode]) -> str:
"""
Renders domain expertise as a natural sentence.
e.g. "Deep expertise in AI and crypto, strong background in infrastructure and backend systems."
"""

# domain nodes: [domain_id, proficiency, recency]
from backend.memory.mycelium.spaces import DOMAIN_IDS
id_to_name = {v: k for k, v in DOMAIN_IDS.items() }

expertise = []
familiar = []
for node in nodes:
    if len(node.coordinates) < 2:
        continue
    domain_id = node.coordinates[0]
    proficiency = node.coordinates[1]
    # Map domain_id back to name (nearest match)
    name = min(id_to_name.keys(),
               key=lambda k: abs(k - domain_id))
    name = id_to_name[name]
    if proficiency >= 0.8:
        expertise.append(name)
    elif proficiency >= 0.5:
        familiar.append(name)

parts = []
if expertise:
    parts.append(f"Deep expertise in {self._join_list(expertise)}")
if familiar:
    parts.append(f"working knowledge of {self._join_list(familiar)}")
return ".".join(parts) + "." if parts else ""

def _render_conduct(self, nodes: List[CoordNode]) -> str:
"""
Renders operational identity as a plain-language summary.

---


## Page 78

e.g. "Works with high agent autonomy - prefers full execution with end-of-task reports. Deep-dive sessions. Commits quickly to outputs. Wants confirmation before irreversible operations."

NEW v1.5 - replaces _render_location.

"""
for node in nodes:
    if len(node.coordinates) < 5:
        continue
    autonomy = node.coordinates[0]
    iteration = node.coordinates[1]
    depth = node.coordinates[2]
    confirm_thresh = node.coordinates[3]
    correction = node.coordinates[4]

# Autonomy description
if autonomy >= 0.80:
    auto_desc = "high agent autonomy - prefers full execution with en
elif autonomy >= 0.50:
    auto_desc = "moderate autonomy - confirm before irreversible acti
else:
    auto_desc = "low autonomy - prefers step-by-step confirmation"

# Session depth
depth_desc = ("Deep-dive sessions." if depth >= 0.70
              else "Mixed session lengths." if depth >= 0.40
              else "Prefers short, targeted tasks.")

# Iteration style
iter_desc = ("Commits quickly to outputs." if iteration >= 0.70
             else "Iterates moderately." if iteration >= 0.40
             else "Heavy iteration - rarely satisfied with first draf

# Confirmation threshold (only surface if meaningfully different from
confirm_parts = []
if confirm_thresh <= 0.40:
    confirm_parts.append("wants confirmation before consequential act
elif confirm_thresh <= 0.20:
    confirm_parts.append("wants confirmation before any external writ

# Correction rate (only surface if notably high)
if correction >= 0.60:
    confirm_parts.append("frequently redirects mid-task")
elif correction >= 0.40:
    confirm_parts.append("occasionally redirects mid-task")

confirm_desc = (f" {' '.join(c.capitalize() for c in confirm_parts)}")

---


## Page 79

if confirm_parts else "")

return (f"Works with {auto_desc}. "
f"{depth_desc} {iter_desc}{confirm_desc}").strip()
return ""

def _render_chrono(self, nodes: List[CoordNode]) -> str:
"""
Renders activity pattern as natural language.
e.g. "Most active late at night (~11pm), with ~3-hour sessions. Consistent"
"""

for node in nodes:
    if len(node.coordinates) < 3:
        continue
    peak_h = node.coordinates[0]
    session_h = node.coordinates[1]
    consist = node.coordinates[2]

    # Time-of-day description
    if 5 <= peak_h < 12:
        time_desc = f"morning (~{self._fmt_hour(peak_h)})"
    elif 12 <= peak_h < 17:
        time_desc = f"afternoon (~{self._fmt_hour(peak_h)})"
    elif 17 <= peak_h < 21:
        time_desc = f"evening (~{self._fmt_hour(peak_h)})"
    else:
        time_desc = f"late at night (~{self._fmt_hour(peak_h)})"

    session_desc = f"~{session_h:.1f}-hour sessions"
    consist_desc = ("Very consistent schedule." if consist > 0.8
                    else "Moderate schedule consistency." if consist > 0.
                    else "Variable schedule.")

    return (f"Most active {time_desc}, with {session_desc}. "
            f"{consist_desc}")
return ""

def _render_style(self, nodes: List[CoordNode]) -> str:
"""
Renders communication style as preference description.
e.g. "Prefers direct, moderately detailed technical communication.
Casual tone."
"""

for node in nodes:
    if len(node.coordinates) < 3:
        continue
    formality = node.coordinates[0]

---


## Page 80

python
verbosity  = node.coordinates[1]
directness = node.coordinates[2]

tone = ("formal" if formality > 0.7
        else "casual" if formality < 0.3
        else "professional")
detail = ("exhaustive detail" if verbosity > 0.8
          else "moderate detail" if verbosity > 0.4
          else "concise responses")
direct = ("very direct" if directness > 0.8
         else "balanced" if directness > 0.4
         else "diplomatic")

return (f"Prefers {direct}, {detail}. {tone.capitalize()} tone.")
return ""
```

def _render_capability(self, nodes: List[CoordNode]) -> str:
"""
Renders hardware capability as a summary sentence.
Does NOT expose raw specs - just capability level.
e.g. "High-end local GPU available. Docker enabled. Windows environment."
"""

for node in nodes:
    if len(node.coordinates) < 5:
        continue
    gpu_tier, ram_norm, has_docker, has_ts, os_id = node.coordinates[:5]

    gpu_desc = (
        "Datacenter GPU" if gpu_tier >= 5 else
        "High-end local GPU" if gpu_tier >= 4 else
        "Mid-range GPU" if gpu_tier >= 3 else
        "Low-end GPU" if gpu_tier >= 1 else
        "No dedicated GPU"
    )
    ram_gb = ram_norm * 128
    ram_desc = f"~{ram_gb:.0f}GB RAM"
    tools = []
    if has_docker >= 0.5: tools.append("Docker")
    if has_ts >= 0.5: tools.append("Tailscale")
    tools_desc = (f"{', '.join(tools)} enabled." if tools else "")
    os_desc = ("Linux" if os_id < 0.3
               else "macOS" if os_id < 0.7
               else "Windows")

    return (f"{gpu_desc} available. {ram_desc}. "
            f"{tools_desc} {os_desc} environment.").strip()
return ""

---


## Page 81

python
def _render_context(self, nodes: List[CoordNode]) -> str:
    """
    Renders active project context as a plain-language environment summary.
    Handles multiple context nodes - renders all active projects.
    e.g. "Currently working on Torus (Python/FastAPI stack, production-adjace constraints). Secondary context: Iris frontend."

    NEW v1.6 - replaces _render_affect.
    """

    # Reverse-hash approximations for common project/stack IDs
    # In production, the extractor stores the original label alongside the ha
    # Here we fall back to a generic description when no label is available.

    summaries = []
    for node in nodes:
        if len(node.coordinates) < 4:
            continue

        freshness = node.coordinates[3]
        if freshness < 0.10:
            continue  # too stale to surface

        # Constraint flags interpretation
        constraint = node.coordinates[2]
        constraint_parts = []
        if constraint >= 0.70:
            constraint_parts.append("high-constraint environment")
        elif constraint >= 0.40:
            constraint_parts.append("moderate constraints")

        label = getattr(node, 'label', None) or "active project"
        freshness_desc = ("current session" if freshness > 0.90
                          else "recently confirmed" if freshness > 0.60
                          else "carry-over context")

        constraint_str = (f", {''.join(constraint_parts)}" if constraint_pa
        summaries.append(f"{label} {freshness_desc}{constraint_str}")

    if not summaries:
        return ""
    if len(summaries) == 1:
        return f"Active context: {summaries[0]}"

    primary = summaries[0]
    secondary = "; ".join(summaries[1:])
    return f"Active context: {primary}. Secondary: {secondary}."

# — Helpers

---


## Page 82

python
def _join_list(self, items: List[str]) -> str:
    if not items: return ""
    if len(items) == 1: return items[0]
    if len(items) == 2: return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"

def _fmt_hour(self, h: float) -> str:
    """Format a float hour as 12h time string."""
    h_int = int(h) % 24
    ampm = "am" if h_int < 12 else "pm"
    h12 = h_int % 12 or 12
    return f"{h12}{ampm}"

def _get_landmark_ids_for_space(self, space_id: str) -> List[str]:
    rows = self.conn.execute(
        "SELECT landmark_id FROM mycelium_landmarks "
        "WHERE coordinate_cluster LIKE ? AND (absorbed IS NULL OR absorbed=0)",
        (f'%"{space_id}"%',)
    ).fetchall()
    return [r[0] for r in rows]
```

# Updated Files to Modify Table (v1.6)

<table>
<thead>
<tr>
<th>File</th>
<th>Change</th>
</tr>
</thead>
<tbody>
<tr>
<td>backend/memory/db.py</td>
<td>Add all Mycelium tables including profile, landmark merges, episode index</td>
</tr>
<tr>
<td>backend/memory/interface.py</td>
<td>Call MyceliumInterface in get_task_context()</td>
</tr>
<tr>
<td>backend/memory/distillation.py</td>
<td>Full maintenance pass incl. profile render</td>
</tr>
<tr>
<td>backend/memory/semantic.py</td>
<td>Notify Mycelium when semantic facts update</td>
</tr>
<tr>
<td>backend/memory/mycelium/landmark.py</td>
<td>Add absorbed column handling</td>
</tr>
<tr>
<td>backend/memory/mycelium/spaces.py</td>
<td>Remove affect space, add context space, add CONTEXT_DECAY_RATE</td>
</tr>
<tr>
<td>backend/memory/mycelium/extractor.py</td>
<td>Remove _extract_affect(), add _extract_context_signals()</td>
</tr>
</tbody>
</table>

---


## Page 83

<table>
  <tr>
    <td>backend/memory/mycelium/profile.py</td>
    <td>Remove _render_affect() (was excluded anyway), add _render_context(), update PROFILE_SPACES</td>
  </tr>
  <tr>
    <td>backend/memory/mycelium/resonance.py</td>
    <td>Update RESONANCE_SPACES — context replaces affect</td>
  </tr>
  <tr>
    <td>backend/memory/episodic.py</td>
    <td>Call ResonanceScorer.index_episode() on store, augment_retrieval() on retrieve</td>
  </tr>
</table>

# File 10: backend/memory/mycelium/resonance.py

Sits between EpisodicStore and MyceliumInterface. Neither side owns it. Two classes: EpisodeIndexer (writes the bridge table at episode store time) and ResonanceScorer (augments cosine similarity with coordinate overlap on retrieval).

```python
# backend/memory/mycelium/resonance.py
# Resonance Layer - coordinate-aware episodic retrieval
# NEW v1.4
#
# The episodic store knows about task similarity in language space (cosine).
# Mycelium knows about task similarity in coordinate space (graph proximity).
# This module bridges the two.
#
# Core idea:
# An episode that resonates across many coordinate spaces is more relevant
# than one that merely sounds similar. Each additional resonating space
# multiplies the confidence that this past episode is genuinely predictive
# of the current task - not just linguistically adjacent to it.
#
# Two representations, two jobs:
# Coordinates -> carry the stable pattern (who, what domain, what tools, when)
# Sentences -> carry the specific exceptions (failures, corrections, surprise
# Both are injected. Coordinates via Mycelium path. Sentences via episodic reca
# But success sentences that duplicate what coordinates already say are suppres

import hashlib
import json
import time
import uuid
import logging
from typing import List, Dict, Optional, Set, Tuple, Any

---


## Page 84

logger = logging.getLogger(__name__)

# How much each resonating space multiplies the base cosine score.
# Tuned so that 3+ resonating spaces doubles the effective retrieval score,
# but a single-space match barely moves it.
RESONANCE_WEIGHT_PER_SPACE = 0.15

# Spaces that carry meaningful resonance signal for episode retrieval.
# context included - a past episode in the same project context is highly relevan
# affect removed v1.6 - replaced by context.
RESONANCE_SPACES = {"domain", "toolpath", "chrono", "conduct", "style", "capabili

# How much coordinate overlap (ratio) is needed to count a space as resonating.
# 0.6 = at least 60% of the space's active nodes must overlap.
RESONANCE_OVERLAP_THRESHOLD = 0.60

# When the landmark of a past episode exactly matches the current landmark,
# apply a strong bonus - this is the highest-confidence retrieval signal.
LANDMARK_MATCH_BONUS = 0.40

# Success episodes whose coordinate coverage already exceeds this ratio
# relative to the current coordinate path are suppressed from sentence injection.
# The model already has this information via coordinates.
SUPPRESSION_COVERAGE_THRESHOLD = 0.70

# — Episode Indexer —

class EpisodeIndexer:
    """
    Writes the mycelium_episode_index bridge table at episode store time.

    Called by EpisodicStore.store() after the episode is persisted.
    Reads the current session's active nodes from SessionRegistry and
    writes a lightweight index record linking the episode to its coordinate
    fingerprint.

    This happens once per episode. Retrieval then uses the index table
    directly instead of re-navigating the graph on every lookup.
    """

    def __init__(self, conn, registry):
        """
        conn: the mycelium DB connection (same memory.db)
        registry: SessionRegistry instance from CoordinateNavigator
        """

---


## Page 85

python
self.conn = conn
self.registry = registry

def index_episode(self, episode_id: str, session_id: str,
                   landmark_id: Optional[str] = None):
    """
    Index a newly stored episode against the current session's coordinate state.

    :param episode_id: the episode just written to episodes table
    :param session_id: the session that produced the episode
    :param landmark_id: the landmark crystallized from this session (may be None
                        if called before crystallize_landmark fires - that's fine,
                        the landmark_id can be back-filled by crystallize_landmark)
    """
    active_nodes = self.registry._active.get(session_id, set())
    if not active_nodes:
        # No Mycelium data for this session yet - index with empty nodes.
        # Resonance will score this episode as 0 until it's back-filled.
        active_nodes = set()

    node_ids = sorted(list(active_nodes))
    space_ids = self._get_space_ids(node_ids)
    coord_hash = self._hash_nodes(node_ids)

    # Upsert - if the episode was already indexed (duplicate update path),
    # refresh the node set and landmark reference
    existing = self.conn.execute(
        "SELECT idx_id FROM mycelium_episode_index WHERE episode_id=?",
        (episode_id,)
    ).fetchone()

    if existing:
        self.conn.execute("""
            UPDATE mycelium_episode_index
            SET node_ids=?, space_ids=?, landmark_id=?, coordinate_hash=?
            WHERE episode_id=?
        """, (json.dumps(node_ids), json.dumps(space_ids),
              landmark_id, coord_hash, episode_id))
    else:
        self.conn.execute("""
            INSERT INTO mycelium_episode_index
            (idx_id, episode_id, session_id, node_ids, space_ids,
             landmark_id, coordinate_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4())[:12],
            episode_id, session_id,

---


## Page 86

python
json.dumps(node_ids), json.dumps(space_ids),
landmark_id, coord_hash, time.time()
))
self.conn.commit()
```

def backfill_landmark(self, session_id: str, landmark_id: str):
    """
    Called by crystallize_landmark() after the landmark is saved.
    Updates any episode index records for this session to point to the landma
    """
    self.conn.execute("""
        UPDATE mycelium_episode_index
        SET landmark_id = ?
        WHERE session_id = ? AND (landmark_id IS NULL OR landmark_id = '')
    """, (landmark_id, session_id))
    self.conn.commit()

def _get_space_ids(self, node_ids: List[str]) -> List[str]:
    """Look up space_id for each node in the list."""
    if not node_ids:
        return []
    placeholders = ",".join("?" * len(node_ids))
    rows = self.conn.execute(
        f"SELECT DISTINCT space_id FROM mycelium_nodes WHERE node_id IN ({placeholders})",
        node_ids
    ).fetchall()
    return [r[0] for r in rows]

def _hash_nodes(self, node_ids: List[str]) -> str:
    """Short hash of sorted node list for fast dedup comparison."""
    raw = "|".join(node_ids)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# --- Resonance Scorer ---
class ResonanceScorer:
    """
    Augments cosine similarity scores with coordinate space resonance.

    Called by EpisodicStore.retrieve_similar() and retrieve_failures()
    after the initial cosine ranking is produced.

    The resonance calculation:
    For each candidate episode, look up its mycelium_episode_index record.
    Compare its active node set against the current session's active node set
    For each coordinate space where overlap >= RESONANCE_OVERLAP_THRESHOLD,
    """

---


## Page 87

that space "resonates." Each resonating space adds RESONANCE_WEIGHT_PER_S to a multiplier. If the episode's landmark matches the current landmark, add LANDMARK_MATCH_BONUS.

```python
final_score = cosine_similarity * (1.0 + resonance_multiplier)
```

The suppression calculation:
For success episodes, measure what fraction of the episode's coordinate coverage is already present in the current coordinate path. If coverage exceeds SUPPRESSION_COVERAGE_THRESHOLD, the episode's sentence summary would duplicate information the model already has from coordinates. Mark it suppressed - score is retained for ranking but the sentence is not injected into the context window.

Graceful degradation:
If Mycelium has no data (fresh install, no index records), resonance multiplier is 0 for all episodes. The ranking falls back to pure cosine. EpisodicStore behaviour is unchanged from pre-Mycelium.

```python
def __init__(self, conn, registry):
    self.conn = conn
    self.registry = registry

def augment_retrieval(
    self,
    session_id: str,
    candidates: List[Dict[str, Any]],
    current_landmark_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Take the cosine-ranked candidate list from EpisodicStore and re-rank it using resonance scores. Also mark suppressed episodes.

    candidates: list of episode dicts, each must have 'id' and 'similarity'
    Returns: same list, re-sorted by final_score, with added fields:
        - resonance_score: float (0.0 if no index data)
        - final_score: cosine x (1 + resonance)
        - suppressed: bool (True = don't inject as sentence)
        - resonating_spaces: list of space_ids that resonated
    """
    current_nodes = self._get_current_nodes(session_id)
    current_spaces = self._nodes_to_space_map(current_nodes)

    for ep in candidates:
        ep_id = ep.get("id", "")
        index = self._get_index(ep_id)

        # Calculate resonance score
        resonance_score = 0.0
        if index is not None:
            resonance_score = self._calculate_resonance_score(index, current_spaces)

        # Calculate final score
        final_score = cosine_similarity * (1.0 + resonance_score)

        # Mark suppressed if necessary
        suppressed = False
        if index is not None and self._is_suppressed(index, current_spaces):
            suppressed = True

        # Update episode dict with new fields
        ep["resonance_score"] = resonance_score
        ep["final_score"] = final_score
        ep["suppressed"] = suppressed
        ep["resonating_spaces"] = [space.id for space in current_spaces if self._is_resonating_space(space, index)]
```
```python
current_nodes = self._get_current_nodes(session_id)
current_spaces = self._nodes_to_space_map(current_nodes)

for ep in candidates:
    ep_id = ep.get("id", "")
    index = self._get_index(ep_id)

    # Calculate resonance score
    resonance_score = 0.0
    if index is not None:
        resonance_score = self._calculate_resonance_score(index, current_spaces)

    # Calculate final score
    final_score = cosine_similarity * (1.0 + resonance_score)

    # Mark suppressed if necessary
    suppressed = False
    if index is not None and self._is_suppressed(index, current_spaces):
        suppressed = True

    # Update episode dict with new fields
    ep["resonance_score"] = resonance_score
    ep["final_score"] = final_score
    ep["suppressed"] = suppressed
    ep["resonating_spaces"] = [space.id for space in current_spaces if self._is_resonating_space(space, index)]

---


## Page 88

python
if not index:
    # No Mycelium data - resonance is 0, not suppressed
    ep["resonance_score"] = 0.0
    ep["final_score"] = ep.get("similarity", 0.0)
    ep["suppressed"] = False
    ep["resonating_spaces"] = []
    continue

ep_nodes = set(json.loads(index["node_ids"]))
ep_spaces = json.loads(index["space_ids"])
ep_lm = index.get("landmark_id")

# Calculate resonance multiplier
resonating, multiplier = self._calculate_resonance(
    current_nodes, current_spaces, ep_nodes, ep_spaces
)

# Landmark match bonus
if (current_landmark_id and ep_lm
    and current_landmark_id == ep_lm):
    multiplier += LANDMARK_MATCH_BONUS

cosine = ep.get("similarity", 0.0)
final_score = cosine * (1.0 + multiplier)
resonance_score = multiplier

# Suppression: is this success episode already covered by coordinates
suppressed = False
if ep.get("outcome_score", 0) >= 0.6:  # success episodes only
    coverage = self._coverage_ratio(ep_nodes, current_nodes)
    if coverage >= SUPPRESSION_COVERAGE_THRESHOLD:
        suppressed = True

ep["resonance_score"] = round(resonance_score, 3)
ep["final_score"] = round(final_score, 3)
ep["suppressed"] = suppressed
ep["resonating_spaces"] = resonating

# Re-sort by final_score descending
candidates.sort(key=lambda e: e.get("final_score", 0.0), reverse=True)
return candidates


def format_context(
    self,
    successes: List[Dict[str, Any]],
    failures: List[Dict[str, Any]]

---


## Page 89

) -> str:
"""
Assemble the episodic context string for injection.

Successes: inject only if NOT suppressed (not already covered by coordina
Failures: always inject - specific exceptions have no coordinate represe

Returns a compact string, or empty string if nothing to inject.
"""
parts = []

# Unsuppressed successes only
active_successes = [ep for ep in successes if not ep.get("suppressed", False)]
if active_successes:
    parts.append("RELEVANT PAST SUCCESSES:")
    for ep in active_successes:
        spaces_str = ""
        if ep.get("resonating_spaces"):
            spaces_str = f" [{', '.join(ep['resonating_spaces'])}]"
        parts.append(
            f"  - {ep['task_summary']} "
            f"(score: {ep['outcome_score']}{spaces_str})"
        )

# Failures always injected - they are the specific exceptions
if failures:
    parts.append("WARNINGS FROM PAST FAILURES:")
    for ep in failures:
        reason = ep.get("failure_reason", "unknown reason")
        parts.append(f"  - {ep['task_summary']}: {reason}")

return "\n".join(parts)

# — Private —

def _calculate_resonance(
    self,
    current_nodes: Set[str],
    current_spaces: Dict[str, Set[str]],
    ep_nodes: Set[str],
    ep_space_ids: List[str]
) -> Tuple[List[str], float]:
    """
    For each coordinate space, check whether the episode's nodes overlap
    sufficiently with the current session's nodes in that space.
    Returns (list_of_resonating_space_ids, total_multiplier).
    """

---


## Page 90

python
resonating  = []
multiplier  = 0.0

for space_id in RESONANCE_SPACES:
    if space_id not in ep_space_ids:
        continue
    current_in_space = current_spaces.get(space_id, set())
    if not current_in_space:
        continue

    # Get episode's nodes in this space
    ep_in_space = self._get_nodes_in_space(ep_nodes, space_id)
    if not ep_in_space:
        continue

    # Overlap ratio = intersection / smaller set
    intersection = len(current_in_space & ep_in_space)
    smaller      = min(len(current_in_space), len(ep_in_space))
    if smaller == 0:
        continue
    overlap = intersection / smaller

    if overlap >= RESONANCE_OVERLAP_THRESHOLD:
        resonating.append(space_id)
        multiplier += RESONANCE_WEIGHT_PER_SPACE

return resonating, multiplier
```

```python
def _coverage_ratio(self, ep_nodes: Set[str],
                     current_nodes: Set[str]) -> float:

    """
    What fraction of the episode's coordinate nodes are already present
    in the current session's active nodes?
    1.0 = episode is fully covered by current coordinates.
    0.0 = episode introduces entirely new coordinate territory.
    """

    if not ep_nodes:
        return 0.0
    covered = len(ep_nodes & current_nodes)
    return covered / len(ep_nodes)
```

```python
def _get_current_nodes(self, session_id: str) -> Set[str]:
    """Get the current session's active node set from the registry."""
    return self.registry._active.get(session_id, set())
```

```python
def _nodes_to_space_map(self, node_ids: Set[str]) -> Dict[str, Set[str]]:
    """Map each space_id to the set of node_ids in that space."""

---


## Page 91

python
if not node_ids:
    return {}
placeholders = ",".join("?" * len(node_ids))
rows = self.conn.execute(
    f"SELECT node_id, space_id FROM mycelium_nodes "
    f"WHERE node_id IN ({placeholders})",
    list(node_ids)
).fetchall()
result: Dict[str, Set[str]] = {}
for node_id, space_id in rows:
    result.setdefault(space_id, set()).add(node_id)
return result

def _get_nodes_in_space(self, node_ids: Set[str],
                        space_id: str) -> Set[str]:
    """Filter a node set to only those in a given space."""
    if not node_ids:
        return set()
    placeholders = ",".join("?" * len(node_ids))
    rows = self.conn.execute(
        f"SELECT node_id FROM mycelium_nodes "
        f"WHERE node_id IN ({placeholders}) AND space_id=?",
        list(node_ids) + [space_id]
    ).fetchall()
    return {r[0] for r in rows}

def _get_index(self, episode_id: str) -> Optional[Dict]:
    """Look up the episode index record for a given episode."""
    row = self.conn.execute(
        "SELECT node_ids, space_ids, landmark_id "
        "FROM mycelium_episode_index WHERE episode_id=?",
        (episode_id,)
    ).fetchone()
    if not row:
        return None
    return {
        "node_ids": row[0],
        "space_ids": row[1],
        "landmark_id": row[2]
    }
```

# Integration Points

## 1. MemoryInterface — get_task_context()

---


## Page 92

Primary integration point. Mycelium replaces prose semantic_header.

```python
# In MemoryInterface.__init__, add:
from backend.memory.mycelium.interface import MyceliumInterface
self.mycelium = MyceliumInterface(self._conn)

# In get_task_context(), replace prose semantic_header assembly with:
mycelium_path = self.mycelium.get_context_path(
    task_text=task, session_id=session_id, minimal=False
)
if mycelium_path:
    self.working.append(session_id, mycelium_path, zone="semantic_header")
else:
    # Fallback to prose if Mycelium graph is empty (fresh install)
    prose = self.semantic.get_user_header()
    if prose:
        self.working.append(session_id, prose, zone="semantic_header")
```

## 2. DistillationProcess — coordinate extraction and graph maintenance

Add to `backend/memory/distillation.py` in `_run_distillation()`:

```python
for episode in episodes_to_distill:
    self._distill_episode_to_semantic(episode)
    # Extract coordinates from episode content
    self.memory.mycelium.ingest_statement(
        episode.full_content, session_id=episode.session_id
    )

# Chrono update
timestamps = self._get_session_timestamps(limit=100)
self.memory.mycelium.ingest_sessions(timestamps)

# Conduct update - derive operational identity from behavioral history (NEW v1.5)
# Pass recent episodes as structured dicts for behavioral signal extraction
conduct_episodes = self._get_conduct_episode_batch(limit=50)
self.memory.mycelium.ingest_conduct_outcomes(conduct_episodes)

# Graph maintenance - order matters: decay -> condense -> expand
pruned = self.memory.mycelium.run_decay()
merged = self.memory.mycelium.run_condense()  # NEW v1.1
split = self.memory.mycelium.run_expand()     # NEW v1.1
```

## 3. PrimaryNode — outcome signal, landmark crystallization, session cleanup

---


## Page 93

Add to `PrimaryNode.handle()` after `store_episode()` — ORDER MATTERS:

```python
outcome = "hit" if not plan.has_failed() else "miss"

# 1. Learning signal to node/edge graph
self.memory.mycelium.record_outcome(
    session_id=session_id, task_text=raw_input, outcome=outcome
)

# 2. Crystallize whiteboard into landmark (NEW v1.2)
# Must happen before clear_session - registry is still populated
self.memory.mycelium.crystallize_landmark(
    session_id=session_id,
    cumulative_score=plan.avg_step_score(),  # or track separately
    outcome=outcome,
    task_entry_label=plan.entry_label or ""
)

# 3. Wipe whiteboard - must be last
self.memory.mycelium.clear_session(session_id)
```

## 4. Conversation deletion — nullify landmark conversation references

When a user deletes a conversation, call this in the conversation deletion handler. The landmark itself is never deleted — only its pointer to the conversation goes null.

```python
# In whatever handler processes conversation deletion:
self.memory.mycelium.nullify_conversation(deleted_session_id)
```

## 5. Application startup — hardware detection and landmark index init

```python
# main.py lifespan startup, after memory init:
self.memory.mycelium.ingest_hardware()
# No landmark init needed - LandmarkIndex reads existing table on first query
```

## 6. Planner — landmark prior before graph traversal (NEW v1.2)

The Planner now checks for a matching landmark before navigating the coordinate graph. If a landmark matches, it gets a pre-scored navigational prior at ~40 tokens, and the graph traversal is guided by the landmark's coordinate cluster rather than starting from scratch.

```python
# In Planner.produce_plan(), before get_context_path():
task_class_hint = self._infer_task_class(raw_input)  # e.g. "domain_ai"

---


## Page 94

python
landmark_context = self.memory.mycelium.get_landmark_context(task_class_hint)
# landmark_context is "" if no match, or a LANDMARK:... string if found

# Assemble planning prompt
prompt_parts = []
if landmark_context:
    prompt_parts.append(landmark_context)  # landmark prior first
coord_path = self.memory.mycelium.get_context_path(
    task_text=raw_input, session_id=session_id
)
if coord_path:
    prompt_parts.append(coord_path)  # then coordinate path
prompt_parts.append(plan_instructions)
```

7. **WorkerExecutor — tool call ingestion and agent edge authoring**

**Tool call ingestion:** After every tool call in `_execute()` and `_execute_assigned_step()`:

```python
try:
    self.mycelium.ingest_tool_call(
        tool_name=tc["tool"],
        success=(result.get("status") == "success"),
        sequence_position=step.step_number,
        total_steps=plan.total_steps,
        session_id=msg.session_id
    )
except Exception:
    pass  # Mycelium ingestion never blocks execution
```

**Agent edge authoring:** When a worker observes a reliable co-occurrence:

```python
self.mycelium.author_edge(
    from_space="toolpath", from_coords=[tool_id("web_search"), 0, 0, 0],
    to_space="domain", to_coords=[0.20, 0, 0],
    edge_type="causal"
)
```

**Convergence-aware context:** Handled automatically by `SessionRegistry`. Workers call `get_context_path(minimal=True)` and receive delta-only paths.

```python
mycelium_minimal = self.memory.mycelium.get_context_path(
    task_text=step.description,
    session_id=msg.session_id,
    minimal=True

---


## Page 95

python
)
child_msg.context = mycelium_minimal + "\n" + plan.to_context_string()
```

# 2. EpisodicStore — resonance wiring (NEW v1.4)

Two changes to `backend/memory/episodic.py`. Neither is invasive — both wrap existing behaviour rather than replacing it.

## On episode store — index the episode:

```python
# In EpisodicStore.store(), after self.db.commit():
try:
    from backend.memory.mycelium.resonance import EpisodeIndexer
    # mycelium_conn and registry passed in at EpisodicStore init,
    # or accessed via shared MemoryInterface reference
    self._indexer.index_episode(
        episode_id=episode_id,
        session_id=episode.session_id,
        landmark_id=None  # backfilled later by crystallize_landmark()
    )
except Exception:
    pass  # Resonance indexing never blocks episode storage
```

## On retrieval — augment with resonance scores:

```python
# In EpisodicStore.retrieve_similar(), after scoring episodes by cosine:
try:
    from backend.memory.mycelium.resonance import ResonanceScorer
    current_lm = self._mycelium.get_current_landmark_id(session_id)
    scored_episodes = self._scorer.augment_retrieval(
        session_id=session_id,
        candidates=[ep for _, ep in scored_episodes],
        current_landmark_id=current_lm
    )
    # scored_episodes is now re-sorted by final_score, with suppressed flags
except Exception:
    pass  # Falls back to cosine-only ranking transparently

# In assemble_episodic_context(), replace the format block:
successes = self.retrieve_similar(task, session_id=session_id, limit=5, min_score
failures = self.retrieve_failures(task, session_id=session_id, limit=3)
return self._scorer.format_context(successes, failures)
# format_context() handles suppression - success sentences not injected
# if their coordinate coverage is already in the current Mycelium path

---


## Page 96

EpisodicStore init — add indexer and scorer:

```python
def __init__(self, db_path, biometric_key, mycelium_conn=None, registry=None):
    # ... existing init ...
    self._mycelium = mycelium_conn  # None on fresh install - resonance degrades
    if mycelium_conn and registry:
        from backend.memory.mycelium.resonance import EpisodeIndexer, ResonanceScorer
        self._indexer = EpisodeIndexer(mycelium_conn, registry)
        self._scorer = ResonanceScorer(mycelium_conn, registry)
    else:
        self._indexer = None
        self._scorer = None
```

crystallize_landmark() — backfill the episode index:

```python
# In MyceliumInterface.crystallize_landmark(), after lm_merger.try_merge():
if landmark and hasattr(self, '_indexer') and self._indexer:
    self._indexer.backfill_landmark(
        session_id=session_id,
        landmark_id=landmark.landmark_id
    )
```

3. DistillationProcess — full maintenance pass

```python
for episode in episodes_to_distill:
    self._distill_episode_to_semantic(episode)
    self.memory.mycelium.ingest_statement(
        episode.full_content, session_id=episode.session_id
    )

timestamps = self._get_session_timestamps(limit=100)
self.memory.mycelium.ingest_sessions(timestamps)

# Maintenance order matters - each step feeds the next
pruned = self.memory.mycelium.run_decay()  # edges decay
merged = self.memory.mycelium.run_condense()  # nodes merge -> dirty
split = self.memory.mycelium.run_expand()  # nodes split -> dirty
lm_pruned = self.memory.mycelium.run_landmark_decay()  # landmark edges decay
rendered = self.memory.mycelium.run_profile_render()  # regenerate dirty sec
```

Lifecycle of a Coordinate and Landmark

Day 1 — User says: “I’m working on AI infrastructure, just run it, I’ll review at the end”

---


## Page 97

1. Episode stored → `EpisodeIndexer.index_episode()` fires
2. Session has no Mycelium nodes yet — index record written with empty node set
3. Distillation: coordinates extracted → `domain_ai`, `domain_infra` nodes created
4. Conduct extractor catches "just run it, I'll review at the end" → weak autonomy signal (0.4 confidence — stated, not observed)
5. Profile dirty → renders: "Deep expertise in AI and infrastructure. Works with high agent autonomy — prefers full execution with end-of-task reports."

**Day 3 — 5 successful AI tasks, each calling web_search**

1. Each episode stored → indexed with active node set (domain_ai, toolpath:web_search, chrono:late)
2. 5 landmarks crystallized → `backfill_landmark()` updates each index record with landmark_id
3. Next task comes in. `retrieve_similar()` runs cosine scoring → 5 candidates
4. `augment_retrieval()` fires — compares current session nodes against each episode's index
5. All 5 episodes resonate on domain_ai + toolpath + chrono → high resonance multiplier
6. All 5 are also suppressed — their coordinate coverage is already in the Mycelium path
7. `format_context()` produces: no success sentences (all suppressed), no failures
8. The model gets the coordinate path. Clean. No redundant sentences.

**Day 5 — New task: user asks about something in a different domain (crypto)**

1. Current session nodes: domain_crypto, toolpath:web_search
2. `retrieve_similar()` returns 5 candidates, mix of AI and crypto episodes
3. `augment_retrieval()` fires — AI episodes resonate on toolpath but not domain
4. Crypto episode from day 2 resonates on domain_crypto + toolpath — higher final_score
5. AI success episodes: suppressed (domain doesn't match, but toolpath does — partial coverage)
6. Crypto episode: not suppressed (domain_crypto is new territory in this session)
7. `format_context()` injects the crypto success episode as a sentence

---


## Page 98

8. The model reads: coordinate path + one targeted sentence about the relevant crypto success

**Week 2 – A task fails with a Docker permissions error**

1. Failure episode stored and indexed with active nodes: domain_ai, capability:docker, toolpath
2. Next similar task: `retrieve_failures()` returns this episode
3. `augment_retrieval()` — resonates on domain_ai + capability:docker
4. `format_context()` injects: “WARNINGS: User ran Docker AI task: permissions error on Windows”
5. Failures are never suppressed. This sentence is always injected regardless of coordinate coverage.
6. The model reads: coordinate path (stable pattern) + failure warning (specific exception)

**Month 2 – Full maturity**

Episodic recall is now surgical. On familiar tasks the context window contains:

* Coordinate path: ~15 tokens (the map, the stable pattern)
* Landmark prior: ~40 tokens on familiar task classes
* Failure warnings: 1-2 targeted sentences on known risk patterns
* Success summaries: zero — all suppressed, already covered by coordinates

On novel tasks or new domains, 1-2 success sentences surface to provide territory the coordinates don’t yet cover. As those sessions accumulate and their coordinates mature, those sentences gradually disappear too. The episodic recall zone self-compresses over time as the coordinate graph fills in.

---

## Testing Checklist

Before marking this implementation complete:

### Coordinate graph (v1.0)

* `CoordinateStore.upsert_node()` deduplicates within distance threshold 0.05
* `CoordinateNavigator.navigate_all_spaces()` returns one node per space

---


## Page 99

* PathEncoder.encode() output contains "MYCELIUM:" prefix
* EdgeScorer.apply_decay() removes edges below PRUNE_THRESHOLD
* EdgeScorer.record_outcome("hit") increases edge score
* EdgeScorer.record_outcome("miss") decreases edge score
* CoordinateExtractor.extract_from_statement("just run it, report at the end") returns conduct node with low confidence
* CoordinateExtractor does NOT extract conduct from neutral statements
* conduct coordinate observed autonomy overrides declared autonomy after enough sessions
* MyceliumInterface.get_context_path() returns empty string when graph is empty
* MyceliumInterface.get_context_path() returns valid MYCELIUM: string after ingest
* MemoryInterface.get_task_context() injects Mycelium path into semantic_header zone
* Mycelium path is shorter in tokens than equivalent prose semantic header
* data/identity.db is never referenced anywhere in mycelium/ package

**Session registry and convergence (v1.1)**

* EdgeScorer.apply_decay() uses TOOLPATH_DECAY_RATE for toolpath space edges
* MapManager.condense() merges two nodes within threshold — survivor has higher access_count
* MapManager.condense() re-points all edges from merged node to survivor
* MapManager.expand() splits a node with clear hit/miss edge divergence
* SessionRegistry.clear() resets correctly — next session starts clean
* Second worker navigating same session returns shorter or empty path
* MyceliumInterface.ingest_tool_call() creates toolpath node on first call
* MyceliumInterface.author_edge() creates an edge with initial score 0.4
* MyceliumInterface.clear_session() wipes the registry for that session only

**Landmark layer (v1.2)**

---


## Page 100

*   LandmarkCondenser.condense() returns None when score < LANDMARK_MIN_SCORE
*   LandmarkCondenser.condense() returns None when outcome == "miss"
*   Landmark.to_context_string() output is ≤ 50 tokens
*   Landmark.to_remote() contains no label, no micro_abstract_text, no conversation_ref
*   LandmarkIndex.activate() promotes to permanent at PERMANENCE_THRESHOLD
*   Nodes with confidence=1.0 survive decay pass unchanged
*   LandmarkIndex.nullify_conversation() sets conversation_ref=NULL
*   Nullified landmark still returned by find_matching()
*   LandmarkIndex.resolve_conflict() returns landmark-validated value when evidence exists
*   LandmarkIndex.resolve_conflict() logs to mycelium_conflicts table
*   MyceliumInterface.dev_dump() raises PermissionError when dev_mode=False

**Landmark merge and readable profile (v1.3)**

*   LandmarkMerger.try_merge() returns None when overlap < MERGE_OVERLAP_THRESHOLD
*   LandmarkMerger.try_merge() returns merged landmark when overlap sufficient
*   Absorbed landmark is marked absorbed=1 — not deleted
*   All edges from absorbed landmark re-pointed to survivor
*   Merge sets dirty=1 on profile sections for affected spaces
*   crystallize_landmark() calls lm_merger.try_merge() after saving landmark
*   ProfileRenderer._render_domain() produces natural language expertise sentence
*   ProfileRenderer._render_conduct() produces autonomy + working style sentence
*   ProfileRenderer._render_conduct() does NOT expose raw float coordinates
*   high correction_rate conduct node produces "frequently redirects mid-task" in profile
*   location space produces no profile section (removed v1.5)
*   ProfileRenderer._render_chrono() produces time-of-day + session length sentence
*   ProfileRenderer._render_style() produces tone + detail + directness sentence

---


## Page 101

*   ProfileRenderer._render_capability() renders capability level not raw specs
*   toolpath space produces no profile section
*   affect space produces no profile section (removed v1.6, no nodes should exist)
*   context space produces environment summary in profile
*   ProfileRenderer._render_context() handles multiple context nodes (one per project)
*   ProfileRenderer._render_context() suppresses nodes with freshness < 0.10
*   get_full_profile() assembles sections in render_order
*   Profile reads as coherent natural language prose

**Conduct space (v1.5)**

*   CoordinateExtractor._extract_conduct_signals("just run it without asking") returns conduct node, autonomy >= 0.8, confidence == 0.4
*   CoordinateExtractor._extract_conduct_signals("always confirm before running") returns conduct node, autonomy <= 0.3
*   CoordinateExtractor._extract_conduct_signals("search for restaurants") returns None — no location, no stated conduct
*   MyceliumInterface.ingest_conduct_outcomes([]) returns 0 — insufficient data
*   MyceliumInterface.ingest_conduct_outcomes([2 episodes]) returns 0 — below threshold
*   MyceliumInterface.ingest_conduct_outcomes([5 episodes, all approved]) returns 1, autonomy near 1.0
*   MyceliumInterface.ingest_conduct_outcomes([5 episodes, all corrected]) returns 1, correction_rate near 1.0
*   Conduct node confidence grows with more episodes — 3 episodes < 10 episodes
*   Stated autonomy (confidence 0.4) is superseded by observed autonomy (confidence > 0.4) after 3+ behavioral episodes
*   CONDUCT_DECAY_RATE = 0.008 — faster than profile (0.005), slower than toolpath (0.02)
*   conduct edges decay at CONDUCT_DECAY_RATE, not TOOLPATH_DECAY_RATE
*   ProfileRenderer._render_conduct() produces autonomy + depth + iteration sentence

---


## Page 102

*   ProfileRenderer._render_conduct() does NOT expose raw float values in output
*   High correction_rate (>= 0.6) surfaces "frequently redirects mid-task" in profile
*   Low confirmation_threshold (<= 0.4) surfaces confirmation preference in profile
*   Conduct node included in RESONANCE_SPACES — episodes with matching conduct resonate
*   navigate_all_spaces() includes conduct space node when present
*   Distillation calls ingest_conduct_outcomes() with recent episodic batch
*   EpisodeIndexer.index_episode() writes record with empty node set when session has no Mycelium data
*   EpisodeIndexer.index_episode() writes correct node_ids and space_ids when session is active
*   EpisodeIndexer.backfill_landmark() updates index records for a session with landmark_id
*   EpisodeIndexer upserts correctly — second call for same episode updates rather than duplicates
*   ResonanceScorer.augment_retrieval() returns same-length list as input
*   ResonanceScorer.augment_retrieval() re-sorts list by final_score descending
*   Episode with 0 resonating spaces: final_score == cosine_similarity
*   Episode with 3 resonating spaces: final_score > cosine_similarity
*   Landmark match bonus applied when current_landmark_id matches episode's landmark_id
*   Success episode with coverage >= threshold: suppressed=True
*   Success episode with coverage < threshold: suppressed=False
*   Failure episode: suppressed=False regardless of coverage
*   ResonanceScorer.format_context() omits suppressed success sentences
*   ResonanceScorer.format_context() always includes failure sentences
*   ResonanceScorer.format_context() includes resonating_spaces in success sentence when present

---


## Page 103

*   ResonanceScorer.augment_retrieval() with no index data: resonance_score=0, suppressed=False
*   Fresh install (no Mycelium data): EpisodicStore behaviour identical to pre-Mycelium
*   EpisodicStore.store() exception in indexer does not block episode storage
*   EpisodicStore.retrieve_similar() exception in scorer falls back to cosine ranking
*   Distillation maintenance order: decay → condense → expand → landmark decay → profile render

## What This Does Not Do

*   **Does not replace episodic memory.** Narrative and failure-context stays in the episodic store. Resonance augments retrieval – it does not replace storage.
*   **Does not suppress failure warnings.** Failure sentences are always injected. They carry specific exceptions that have no coordinate representation.
*   **Does not replace semantic prose entirely.** Fresh install falls back to prose and cosine-only retrieval.
*   **Does not delete landmarks when conversations are deleted.**
    *   `nullify_conversation()` nulls the pointer; the landmark remains fully navigable.
*   **Does not expose toolpath in the readable profile.** Toolpath is agent-only operational data.
*   **Does not make clinical inferences.** Affect was removed precisely because its most obvious inference was architecturally off-limits. The seven remaining spaces have no such constraint.
*   **Does not touch data/identity.db.** Dilithium keys and Torus identity are completely separate.
*   **Does not require the swarm.** Single-agent mode works fully. Improves when swarm activates.
*   **Does not expose graph state to personal mode users.** `dev_dump()` is gated behind `dev_mode=True`.
*   **Does not manually curate the profile.** The profile is always derived, never edited. If the underlying coordinates are wrong, fixing the coordinates fixes the profile.

---


## Page 104

IRIS Mycelium Layer — Specification v1.6 The library without every word. The map without the territory. The path that outlasts the conversation. Coordinates are the stable pattern. Landmarks are the inheritance. The profile is the translation. Resonance is the retrieval signal. What sounds similar isn’t always what matters. What resonates across spaces always does. Seven spaces. The right seven. Identity, operational, environmental. Prime, complete, and designed to grow.