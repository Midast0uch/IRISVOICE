## Page 1

# Mycelium Layer Spec — Gap Review & Fix

## Instructions

## Context

You are fine-tuning the IRIS Mycelium Layer specification ( requirements.md + design.md ).

The spec is substantially complete and well-structured. Do not restructure or rewrite it.

Apply targeted additions and clarifications only — surgical edits at the locations indicated below.

The goal is to close all identified gaps before the task list is generated. Each section below describes the gap, the exact location to edit, and what the fix should contain.

There are two categories of gaps:

*   **Gaps 1–7:** Structural and precision issues in the existing spec
*   **Gaps 8–12:** Production readiness issues — these concern the bootstrapping problem (the “nature vs nurture” problem): the system is well-designed for steady state but the spec does not define what happens in the critical early sessions before the graph has enough data to be trusted. These gaps must be addressed in the design because the first coordinate path laid down sets the trajectory for everything that follows. A bad cold start produces a self-reinforcing bad graph. The architecture self-corrects over time, but only if the first brick is load-bearing.

---

## Gap 1 — toolpath Ingestion Has No Requirement

**Problem:** ingest_tool_call() appears in the MyceliumInterface API surface in design.md but there is no corresponding Requirement covering how toolpath coordinate nodes are built from tool call observations. toolpath is described as the most dynamic space, updated at TOOLPATH_DECAY_RATE = 0.02/day, yet the only ingestion path covered in the Requirements is hardware (extract_hardware), session timestamps (extract_from_sessions), and statements (extract_from_statement). Tool call observation — the primary source for toolpath — is missing entirely.

**Location to edit:** Add a new acceptance criterion to Requirement 4 (Coordinate Extraction), after criterion 4.13 (the freshness = 1.0 criterion).

---


## Page 2

**What to add:** Write 4-6 acceptance criteria covering:

*   `CoordinateExtractor.ingest_tool_call(tool_name, success, sequence_position, total_steps, session_id)` signature and what it produces
*   How `tool_id` normalization is applied to the tool name (same MD5-modulo-10000 as defined in Req 1.10)
*   How `call_frequency_normalized`, `success_rate`, and `avg_sequence_position` are derived from the running observation window for that tool (minimum observation count before a node is written — suggest 3 calls)
*   That `upsert_node` deduplication applies, so repeated calls update the existing `toolpath` node rather than accumulating duplicates
*   That `ingest_tool_call` is called by `MyceliumInterface.ingest_tool_call()` which is wired into the agent's tool execution path (WorkerExecutor or equivalent) after every tool call completes

---

## Gap 2 — Multi-Project context Node Collision Is Underspecified

**Problem:** Requirement 4.14 states “the nearest node by Euclidean distance to the current session’s `project_id` fires for navigation” when multiple `context` nodes coexist. However, the `project_id` axis is a normalized MD5 hash in `[0.0, 1.0]`. Two unrelated projects can produce `project_id` values within the `upsert_node` deduplication threshold of `0.05`, causing them to be silently merged into a single `context` node — corrupting per-project landmark trails.

**Location to edit:** Requirement 4 — add a new criterion after 4.14, and add a note to Requirement 3 criterion 3.1.

**What to add:**

In Requirement 4, after 4.14: A criterion stating that `context` space nodes use a stricter deduplication threshold of `0.10` on the `project_id` axis alone (not full Euclidean distance across all four axes) before falling back to full Euclidean distance. If two `context` nodes have `|project_id_a - project_id_b| > 0.10`, they MUST NOT be merged regardless of their Euclidean distance in the full 4D space. This prevents hash-adjacent unrelated projects from colliding.

In Requirement 3, criterion 3.1: Add a parenthetical noting that the `0.05` deduplication threshold applies to all spaces except `context`, which uses the stricter per-axis check described in Requirement 4.

---


## Page 3

# Gap 3 — `run_condense()` Space Iteration Order Is Unspecified

**Problem:** MapManager.condense(space_id) takes a single space and condenses it. MyceliumInterface.run_condense() must iterate all seven spaces, but neither the Requirements nor Design specifies the iteration order. Order matters because condensing context before toolpath produces different graph state than the reverse — condensed context nodes may affect subsequent toolpath edge re-pointing.

**Location to edit:** Requirement 7 (Edge Scoring and Decay) — add a criterion after 7.5 (the condense criterion). Also add a sentence to Design → Key Design Decisions as Decision 8.

**What to add:**

In Requirement 7, after 7.5: A criterion specifying that run_condense() and run_expand() iterate spaces in the following fixed order: domain, style, conduct, chrono, capability, context, toolpath. Rationale: identity spaces (domain, style) condense first as they are most stable; toolpath condenses last because it is most volatile and benefits from edge re-pointing already resolved by earlier spaces.

In Design → Key Design Decisions, as Decision 8: Document this as a deliberate decision — fixed space iteration order for maintenance operations — with the rationale above. Note that run_decay() applies to all edges uniformly and is order-independent.


# Gap 4 — Distillation Trigger Conditions Are Not Formalized

**Problem:** The Design document mentions distillation runs "when the system has been idle for ≥10 minutes" but this condition never appears in the Requirements. Without a formalized trigger, the implementation could choose any schedule (time-based, session-count-based, etc.) and still technically satisfy the spec. This matters because too-frequent distillation blocks inference; too-infrequent means stale context for long-running sessions.

**Location to edit:** Requirement 13 (MemoryInterface Integration) — add 2–3 criteria at the end of the existing list.

**What to add:** Criteria covering:

*   DistillationProcess SHALL only trigger the Mycelium maintenance sequence when the system has been idle (no active session) for a configurable DISTILLATION_IDLE_THRESHOLD (default: 600 seconds / 10 minutes)

---


## Page 4

* The threshold SHALL be stored as a constant in `mycelium/interface.py` and overridable via `MyceliumInterface.__init__(distillation_idle_threshold=600)`
* IF a distillation pass is already running when a new session starts, the maintenance sequence SHALL be interrupted gracefully after the current atomic step completes — it MUST NOT block `get_task_context()` calls
* The distillation pass SHALL record a `last_distillation_at` timestamp so `EdgeScorer.apply_decay()` can compute accurate `days_since_last_distillation` for all decay calculations

---

# Gap 5 — author_edge() VS connect_nodes() Are Indistinguishable

**Problem:** MyceliumInterface exposes both `author_edge(from_space, from_coords, to_space, to_coords, edge_type)` and `connect_nodes(from_space, from_coords, to_space, to_coords, edge_type, initial_score)` with near-identical signatures. No Requirement distinguishes their semantics. This will result in inconsistent usage across the codebase.

**Location to edit:** Requirement 5 (Graph Navigation) — clarify criterion 5.8 (`author_edge`) and add a new criterion for `connect_nodes`. Also update the **Design → API Interface Changes** section for `MyceliumInterface` to document the distinction.

**What to add:**

*In Requirement 5, criterion 5.8:* Expand to specify that `author_edge()` is the **agent-facing** method — called when the AI agent explicitly decides to link two concepts it has observed co-occurring. Initial score is always `0.4`. The agent provides conceptual `from_coords` and `to_coords` as float arrays; `author_edge` resolves the nearest existing nodes in each space (or creates new nodes) and writes the edge. This is the only method agents call.

*In Requirement 5, new criterion after 5.8:* `connect_nodes()` is the **internal** method — called only by Mycelium internals (Navigator, LandmarkMerger) when re-pointing edges during graph maintenance. It takes explicit `initial_score` as a parameter (not defaulted to 0.4) and bypasses the “find nearest node” resolution step, writing directly to the node IDs it is given. External code MUST NOT call `connect_nodes()` directly.

*In Design → API:* Add a comment in the `MyceliumInterface` method list noting `connect_nodes()` as internal-only and `author_edge()` as agent-facing.

---


## Page 5

# Gap 6 — constraint_flags Weights Are Undocumented Design Assumptions

**Problem:** Requirement 4.12 specifies `constraint_flags` as a weighted sum: deadline (+0.30), production (+0.25), public-facing (+0.25), security (+0.20). These weights are asserted without justification and will be wrong for some users — a developer who always works in production will have permanently elevated `constraint_flags` unrelated to actual task pressure. There is no mechanism to tune or validate these weights.

**Location to edit:** Requirement 4, criterion 4.12 — expand it. Also add a note to **Design → Error Handling & Edge Cases** table.

**What to add:**

*In Requirement 4, criterion 4.12:* After the existing weight definition, add:

*   The weights are initial empirical estimates. They SHALL be stored as named constants (CONSTRAINT_WEIGHT_DEADLINE, CONSTRAINT_WEIGHT_PRODUCTION, CONSTRAINT_WEIGHT_PUBLIC, CONSTRAINT_WEIGHT_SECURITY) in spaces.py, not hardcoded inline, to enable future tuning without code changes.
*   The `constraint_flags` axis SHOULD be interpreted relatively across a user’s own sessions — the absolute value matters less than the delta between sessions. ProfileRenderer._render_context() SHALL describe constraint level as low/moderate/elevated/high relative to the user’s own historical range (stored as min_observed and max_observed in the profile section metadata), not as an absolute percentage.

*In Design → Error Handling & Edge Cases,* add a row: | constraint_flags always near 1.0 for a production-only developer | ProfileRenderer computes relative range across user’s own history; absolute values are not shown | Req 4.12 |


# Gap 7 — Missing Test Cases for Boundary Conditions

**Problem:** The test module table in the Design covers the happy path for most modules but is missing explicit test cases for two boundary conditions called out in the Requirements:

*   Req 4.5: `extract_from_sessions()` returns None when fewer than 5 timestamps provided
*   Req 4.17: context nodes with freshness < 0.10 are excluded from profile rendering AND navigation

---


## Page 6

Location to edit: Requirement 14 (Testing), criteria 14.6 and 14.10.

What to add:

In criterion 14.6 (CoordinateExtractor tests): Add explicitly: `extract_from_sessions()` with 4 timestamps returns None ; `extract_from_sessions()` with exactly 5 timestamps returns a valid chrono node.

In criterion 14.10 (ProfileRenderer tests): The existing note covers freshness < 0.10 suppression in profile rendering. Add: a test verifying that a stale context node (freshness < 0.10) also produces no navigation entries from `CoordinateNavigator.navigate_from_task()` — confirming the exclusion applies to both rendering and traversal, not just rendering.


# Gap 8 – Graph Maturity Threshold Before Mycelium Overrides Prose Fallback

**Problem:** The spec defines a prose fallback for empty graphs (Req 13.2, Req 5.6) but has no concept of a “partially mature” graph — one where some nodes exist but confidence is too low to be trusted. An immature graph with 2 low-confidence nodes will produce a MYCELIUM: string that silently overrides the prose fallback, potentially giving the planner worse context than no Mycelium at all. This is the bootstrapping risk: the system could be measurably worse in sessions 1–10 than it was before Mycelium was installed, which destroys trust before the graph has a chance to self-correct.

**Location to edit:** Requirement 12 (MyceliumInterface) — add a criterion after 12.2.
**Requirement 5** — add a maturity check note to criterion 5.1. **Design → Key Design Decisions** as Decision 9.

**What to add:**

In Requirement 12, after 12.2:

*   THE SYSTEM SHALL define a `GRAPH_MATURITY_THRESHOLD` requiring at least 3 distinct spaces to have at least one node with `confidence >= 0.6` before `get_context_path()` returns a non-empty string. Below this threshold, `get_context_path()` returns "" and MemoryInterface falls back to prose — identical to the empty graph case.

*   THE SYSTEM SHALL expose `MyceliumInterface.is_mature() -> bool` that returns True when the maturity threshold is met, allowing callers to distinguish “no graph” from “graph not yet trusted.”

---


## Page 7

*   THE SYSTEM SHALL log a single INFO -level message the first time `is_mature()` transitions from False to True, recording the session count and spaces that crossed the threshold.
*   The GRAPH_MATURITY_THRESHOLD SHALL be stored as a named constant in mycelium/interface.py and overrideable via MyceliumInterface.__init__().

In Design -> Key Design Decisions, as Decision 9: Document the maturity gate as a deliberate cold-start protection. Rationale: the prose fallback is known-good; an immature coordinate path is unknown-quality. The asymmetry favors the known quantity until the graph earns override authority. The threshold of 3 spaces / confidence 0.6 is a conservative starting point — this is one of the empirical constants that should be reviewed after the first 50 users.

---

## Gap 9 — conduct Cold Start Has No Defined Default

**Problem:** conduct is derived entirely from behavioral observation (Req 4.7, 4.8). It takes a minimum of 3 episodes before a behavioral conduct node is written. It takes additional sessions before confidence exceeds the 0.4 statement-bootstrap threshold. During this window — potentially the first 5-10 sessions — the planner has no conduct signal at all, or only a low-confidence statement bootstrap. The spec does not define what the planner does in this case. The implementation will invent a default, and that default will shape every plan structure in the critical period when the user is forming their first impression of IRIS.

**Location to edit:** Requirement 4 (Coordinate Extraction) — add criteria after 4.8.

**Requirement 5** — add a note to criterion 5.4 (navigate_all_spaces). **Design -> Error Handling & Edge Cases table.**

**What to add:**

In Requirement 4, after 4.8:

*   THE SYSTEM SHALL define a CONDUCT_COLD_START_DEFAULT coordinate vector `[0.5, 0.5, 0.5, 0.5, 0.5]` (all axes at midpoint: moderate autonomy, balanced iteration, medium depth, moderate confirmation, low correction) with confidence = 0.2 — below any statement bootstrap threshold.
*   WHEN navigate_all_spaces() finds no conduct node in the graph AND the maturity threshold has not been reached, THE SYSTEM SHALL inject a synthetic conduct node built from CONDUCT_COLD_START_DEFAULT coordinates with label = "cold_start_default" — this node is never persisted to the database, only used for context assembly in that session.

---


## Page 8

* The cold-start default SHALL be documented as deliberately conservative: a user who wants more autonomy will correct the system quickly (generating behavioral signal that supersedes it within 3–5 sessions), while a user who is comfortable with the default will simply never trigger a correction signal.

* THE SYSTEM SHALL expose `CONDUCT_COLD_START_DEFAULT` as a named constant in `spaces.py` so it can be tuned independently of the space definition.

In Design -> Error Handling & Edge Cases, add a row:
| No conduct node exists (sessions 1-3) | Synthetic cold-start node injected at `[0.5,0.5,0.5,0.5,0.5]` with confidence=0.2 — never persisted, used for context assembly only | Req 4 (gap-fix: 9) |

---

# Gap 10 – Maximum Distillation Interval for Long-Running Sessions

**Problem:** Gap 4 formalizes the idle-based distillation trigger (10 minutes of inactivity). However, a power user running continuous sessions for 3–4 hours accumulates stale edges, unprocessed behavioral signals, and unpruned context nodes that never get cleaned up because the idle threshold is never reached. Over a multi-day sprint this compounds: the graph grows noisier with each session and decay never fires. There is no circuit-breaker.

**Location to edit:** Requirement 13 (MemoryInterface Integration) — extend the criteria added in Gap 4 with one additional criterion.

**What to add:**

*   THE SYSTEM SHALL define a `DISTILLATION_MAX_INTERVAL` constant (default: 14400 seconds / 4 hours) in `mycelium/interface.py`. IF the time since `last_distillation_at` exceeds `DISTILLATION_MAX_INTERVAL`, THE SYSTEM SHALL trigger a distillation pass at the next session boundary (after `clear_session()` is called) regardless of idle state.

*   A session boundary is defined as the moment between `clear_session()` completing and the next `get_task_context()` call — the safest window to run maintenance without blocking inference.

*   This max-interval pass SHALL run the full maintenance sequence in order: `run_decay()`
    → `run_condense()`
    → `run_expand()`
    → `run_landmark_decay()`
    → `run_profile_render()` .

---

# Gap 11 – Remote Worker Context Asymmetry Is

---


## Page 9

# Undocumented

**Problem:** When a task is dispatched to a Torus remote worker, `to_remote()` strips `label`, `micro_abstract_text`, and `conversation_ref` from landmarks. This means remote workers have no way to reconstruct the original project label from a `project_id` float, causing them to systematically underweight context resonance compared to local workers – a known accuracy asymmetry. This is probably the correct tradeoff (privacy > accuracy for remote dispatch) but it is undocumented, meaning an implementer might try to “fix” it and accidentally leak project labels to the network.

**Location to edit:** Requirement 8 (Landmark Layer) — expand criterion 8.12 (`to_remote()`). Design → Security & Performance Considerations — add a note under Security.

**What to add:**

*In Requirement 8, criterion 8.12:* After the existing stripping definition, add: This stripping is intentional and permanent — remote workers MUST NOT receive project labels, task abstracts, or conversation references. The consequence is that remote workers will compute context resonance using coordinate distance only (no label matching), producing slightly lower resonance scores for context-space episodes compared to local workers. This accuracy asymmetry is the accepted cost of privacy-preserving Torus dispatch. A requirement to “restore” label data for remote workers would violate the privacy contract and MUST NOT be implemented.

*In Design → Security,* add a bullet: **Known context asymmetry by design:** Remote Torus workers receive coordinate paths without project labels. Their context resonance scores will be marginally lower than local workers for the same task. This is the correct tradeoff — privacy of project identity outweighs marginal resonance accuracy on remote dispatch.


# Gap 12 — `profile_render_order` Values Are Undefined

**Problem:** `mycelium_profile` has a `render_order` column used by `get_readable_profile()` to assemble sections. Nothing in the spec defines what values `render_order` should hold for each space. Two independent implementations of `_ensure_spaces_registered()` will produce different orders, causing inconsistent profile output — the kind of subtle bug that only surfaces when comparing profile output across instances or debugging a Torus sync.

**Location to edit:** Requirement 10 (Readable Profile) — add a criterion after 10.1. Design → Data Models — add a note to the `mycelium_profile` schema block.

---


## Page 10

# What to add:

In Requirement 10, after 10.1:

*   THE SYSTEM SHALL assign fixed `render_order` values for all six profile spaces, defined as named constants in `spaces.py`:
    *   domain → 1
    *   conduct → 2
    *   chrono → 3
    *   style → 4
    *   capability → 5
    *   context → 6
    *   toolpath → excluded (render_order = NULL or absent)
*   These values SHALL be written by `_ensure_spaces_registered()` during MyceliumInterface initialization and SHALL NOT be overridable at runtime — profile section order is a contract, not a preference.

In Design -> Data Models, `mycelium_profile schema`: Add a comment: `render_order` values are fixed constants defined in `spaces.py` — `domain=1, conduct=2, chrono=3, style=4, capability=5, context=6`. `toolpath` is never written to this table.


# Gap 13 – No Security or Precision Layer for RAG and External Input

**Problem:** The spec has no mechanism for classifying, filtering, or containing external input — from RAG retrievals, MCP tool results, document ingestion, or desktop vision observations (MiniCPM). All external content that lands in the context window currently has equal access to influence coordinate updates, landmark crystallization, and plan structure. This creates two compounding risks:

1.  **Security risk:** Prompt injection through retrieved content. A malicious document or compromised MCP server can craft content that looks semantically similar to a real task, lands in the context window, and influences agent behavior or poisons the coordinate graph.

---


## Page 11

2. **Precision risk:** Low-quality external sources pollute high-quality internal coordinates. A single irrelevant document retrieval can produce coordinate updates that decay slowly enough to degrade navigation accuracy across many sessions.

The biological model already present in the architecture provides the solution: **hyphae as typed channels** (selective transport, not content inspection) + **cell wall as a membrane** (permeability by channel type, not by content analysis) + **quorum sensing as immune response** (population-level threat detection triggering coordinated reorganization).

This is not a foreign security mechanism — it is the organic logic of the existing decay and maintenance system, given a trigger and a classification input.

**Location to edit:** Add a new **Requirement 15 (Hypha Security and Precision Layer)** to requirements.md . Add a new **Section: Hypha Security Architecture** to design.md under Architecture. Add backend/memory/mycelium/hypha.py to the new files table. Add QuorumSensor, HyphaChannel, CellWall, and QuorumReorganization to the component overview diagram.

---

**What to add to requirements.md as Requirement 15:**

**User Story:** As the IRIS memory system, I want all external input classified into typed hypha channels before it can reach the coordinate graph or context window, so that the graph is protected from injection and pollution without requiring content inspection.

**Acceptance Criteria**

**Channel Classification**

1. THE SYSTEM SHALL define a HyphaChannel enum in backend/memory/mycelium/hypha.py with five levels: SYSTEM (4), USER (3), VERIFIED (2), EXTERNAL (1), UNTRUSTED (0). The integer values represent transport authority — higher values can reach more zones.

2. THE SYSTEM SHALL assign channel levels as follows:
    *   SYSTEM — IRIS internals, own specs, own coordinate graph outputs
    *   USER — user's own documents, notes, direct statements
    *   VERIFIED — MCP servers with a pinned identity (URL + content hash registered at startup)
    *   EXTERNAL — web retrieval, unverified documents, unknown sources

---


## Page 12

*   UNTRUSTED – anonymous sources, sources that failed identity verification, any MCP whose identity does not match its registered pin

3.  THE SYSTEM SHALL attach a HyphaChannel value to every RAG retrieval result, every MCP tool result, and every external document chunk at the point of ingestion — before any embedding, coordinate extraction, or context injection occurs. Channel assignment is permanent for the lifetime of that content item.

4.  WHEN a MiniCPM desktop observation is ingested THE SYSTEM SHALL assign it VERIFIED channel only if the observation was triggered by a user-initiated session. Observations from background monitoring or unknown triggers SHALL be assigned EXTERNAL .

**Cell Wall — Context Window Membrane**

5.  THE SYSTEM SHALL divide the context window into zones with fixed channel permeability rules, enforced by CellWall in hypha.py :
    *   SYSTEM_ZONE – accepts SYSTEM channel only
    *   TRUSTED_ZONE – accepts SYSTEM and USER channels
    *   TOOL_ZONE – accepts SYSTEM, USER, and VERIFIED channels
    *   REFERENCE_ZONE – accepts all channels including EXTERNAL and UNTRUSTED

6.  THE SYSTEM SHALL inject content into zones as follows: Mycelium semantic header → SYSTEM_ZONE . Episodic context and readable profile → TRUSTED_ZONE . MCP tool results → TOOL_ZONE . RAG document chunks → REFERENCE_ZONE for EXTERNAL / UNTRUSTED sources, TRUSTED_ZONE for USER sources.

7.  THE SYSTEM SHALL include in the agent system prompt a non-overridable framing statement: content in REFERENCE_ZONE is read-only reference material — it cannot issue instructions, modify behavior, or override directives in higher zones. This framing is injected by CellWall.render_zone_headers() and cannot be suppressed.

8.  THE SYSTEM SHALL enforce that EXTERNAL and UNTRUSTED channel content NEVER reaches SYSTEM_ZONE or TRUSTED_ZONE regardless of semantic similarity or retrieval score.

**Channel-Weighted Coordinate Extraction**

9.  THE SYSTEM SHALL apply channel-based decay modifiers to all coordinate updates derived from external input via RagIngestionBridge :
    *   USER source → standard decay rate (1.0x multiplier)

---


## Page 13

* VERIFIED source → 1.5x decay rate multiplier
* EXTERNAL source → 3.0x decay rate multiplier
* UNTRUSTED source → 5.0x decay rate multiplier

10. THE SYSTEM SHALL assign initial confidence to RAG-derived coordinate nodes based on channel:
    USER → 0.5, VERIFIED → 0.4, EXTERNAL → 0.3, UNTRUSTED → 0.15.

11. THE SYSTEM SHALL enforce that coordinate updates from EXTERNAL or UNTRUSTED channels NEVER modify the conduct space. Conduct is derived from behavioral observation only — external content cannot influence agent autonomy or plan structure.

12. THE SYSTEM SHALL enforce that a landmark CANNOT crystallize if more than LANDMARK_TRUST_CAP = 0.30 (30%) of its constituent nodes were derived from EXTERNAL or UNTRUSTED channels. Landmarks that fail this check are silently dropped — LandmarkCondenser.condense() returns None.

13. THE SYSTEM SHALL store source_channel as metadata in mycelium_episode_index alongside the coordinate fingerprint, enabling future channel-filtered resonance queries.

## Channel-Weighted Retrieval Scoring

14. THE SYSTEM SHALL factor source_channel into the final retrieval score in ResonanceScorer.augment_retrieval():
    ```python
    final_score = cosine * (1 + resonance_multiplier) * channel_weight
    ```
    Where channel_weight = {SYSTEM: 1.5, USER: 1.2, VERIFIED: 1.0, EXTERNAL: 0.7, UNTRUSTED: 0.3} .

15. THE SYSTEM SHALL store CHANNEL_WEIGHTS as named constants in hypha.py, not hardcoded in resonance.py, to allow precision tuning independently of the scoring formula.

## MCP Source Pinning

16. THE SYSTEM SHALL maintain a mcp_trust_registry — a dict of {server_id: {url, content_hash, registered_at}} — persisted in mycelium_spaces or a dedicated config file data/mcp_pins.json. An MCP server is VERIFIED only if its runtime identity matches its registered pin.

17. WHEN an MCP server's identity does not match its registered pin THE SYSTEM SHALL downgrade it to UNTRUSTED for that session and log a WARNING -level security event to mycelium_conflicts with resolution_basis = "mcp_pin_mismatch".

---


## Page 14

18. THE SYSTEM SHALL provide `MyceliumInterface.register_mcp(server_id, url, content_hash)` called at application startup for each configured MCP server.

## Quorum Sensing — Immune Response

19. THE SYSTEM SHALL implement `QuorumSensor` in `hypha.py` that accumulates threat signals across sessions into a `threat_level: float` in `[0.0, 1.0]`. Threat signals and their weights:
    * Channel trust violation (content arriving on VERIFIED channel producing coordinates statistically consistent with UNTRUSTED sources) → +0.25
    * Coordinate update velocity anomaly (more than QUORUM_VELOCITY_THRESHOLD coordinate updates in a single session, inconsistent with organic learning patterns) → +0.20
    * Landmark activation anomaly (a landmark activated far outside its normal task class frequency — more than 3 standard deviations above its historical mean) → +0.30
    * Coordinate channel mismatch (a VERIFIED or higher channel node updating in a direction strongly predicted by EXTERNAL / UNTRUSTED content rather than behavioral observation) → +0.25

20. THE SYSTEM SHALL define `QUORUM_THRESHOLD = 0.60` as the threat level at which quorum fires. This constant SHALL be stored in `hypha.py` and overridable via `MyceliumInterface.__init__()`.

21. WHEN `QuorumSensor.threat_level` crosses `QUORUM_THRESHOLD` THE SYSTEM SHALL trigger `QuorumReorganization` — an emergency accelerated maintenance cycle:
    * Apply `run_decay()` with a `QUORUM_DECAY_MULTIPLIER = 3.0` amplifier on all nodes modified in the current and previous session
    * Suspend landmark crystallization for the remainder of the current session (`crystallize_landmark()` returns `None` until `clear_session()` is called)
    * Set `dirty = 1` on all profile sections
    * Run `run_condense()` and `run_expand()` immediately in the fixed space order
    * Run `run_profile_render()` to regenerate all dirty sections
    * Log the full reorganization event to `mycelium_conflicts` with `resolution_basis = "quorum_reorganization"`

22. WHEN quorum fires THE SYSTEM SHALL reset `threat_level = 0.0` after

---


## Page 15

QuorumReorganization completes. The map that any attacker spent sessions mapping is now reorganized around different geometry.

23. THE SYSTEM SHALL decay threat_level passively at QUORUM_SIGNAL_DECAY = 0.05 per clean session (a session that produces no new threat signals). Threat signals from isolated anomalies fade without triggering reorganization if they do not compound.

24. THE SYSTEM SHALL expose QuorumSensor.threat_level via MyceliumInterface.get_stats() for observability. No external action is required – quorum is self-triggering.

## Subagent Hypha Precision

25. THE SYSTEM SHALL support named hypha channel variants for subagent specialization. A subagent (e.g. a WorkerExecutor specialized for code, research, or vision) may be assigned a named channel profile that restricts which coordinate spaces it can read from and write to. Named channel profiles are defined in hypha.py as SUBAGENT_CHANNEL_PROFILES dict.

26. THE SYSTEM SHALL provide three built-in subagent channel profiles:
    * "code_worker" — read: all spaces; write: toolpath, context only
    * "research_worker" — read: all spaces; write: domain, context only
    * "vision_worker" — read: all spaces; write: context, capability only

27. WHEN a subagent calls get_context_path() with a named channel profile THE SYSTEM SHALL filter the returned coordinate path to include only spaces the profile is permitted to read, and filter coordinate update calls to only accept writes to permitted spaces. This prevents a compromised subagent from polluting identity spaces (conduct, style, chrono) it has no business modifying.

28. THE SYSTEM SHALL add subagent channel profile support to CoordinateNavigator.navigate_from_task() via an optional channel_profile: str parameter. When provided, navigation is restricted to readable spaces only.

---

**What to add to design.md :**

**New file in the new files table:** backend/memory/mycelium/hypha.py | HyphaChannel, CellWall, RagIngestionBridge, QuorumSensor, QuorumReorganization, SUBAGENT_CHANNEL_PROFILES | Channel classification, context window membrane, immune response, subagent precision routing

---


## Page 16

# New component in the architecture diagram:

<mermaid>
graph TD
    A[HyphaLayer (mycelium/hypha.py)] --> B[HyphaChannel - typed channel enum, born at source classification]
    A --> C[CellWall - membrane permeability rules, zone enforcement]
    A --> D[RagIngestionBridge - RAG/MCP/vision → channel-classified coordinate]
    A --> E[QuorumSensor - threat signal accumulation, immune trigger]
    A --> F[QuorumReorganization - accelerated decay + topology reshuffle on qu]
</mermaid>

## New Key Design Decision (Decision 10): Structural security over content inspection.

The HyphaLayer never reads content to determine trust — it assigns channels at source and enforces permeability by channel type at every boundary. This is the membrane model: a cell wall does not analyze every molecule, it enforces structural properties. The consequence is that the security model is not defeatable by crafting content that looks clean — the content is never evaluated. Only the channel it arrived on matters, and channels are assigned before content exists. This is also why QuorumReorganization reuses the existing organic maintenance infrastructure rather than introducing a foreign security mechanism: the map reorganizes the same way it always does, just faster and triggered by population-level threat signal rather than idle time.

## New row in Error Handling & Edge Cases:
| MCP server identity does not match registered pin | Server downgraded to UNTRUSTED channel for session; WARNING logged to mycelium_conflicts | Req 15.17 || Quorum threshold crossed | QuorumReorganization fires: 3x decay on recent nodes, landmark suspension, full condense/expand/render | Req 15.21 || Subagent attempts to write to restricted space | Write silently dropped; channel profile enforces write boundary without error propagation | Req 15.27 |

---

## Gap 14 — Kyudo Precision Optimization Layer (Token Cost Compounding)

**Problem:** The original goal was context windows so optimized that agents barely have to think — not just a one-time token reduction but a compounding cost curve where more sessions means cheaper inference, not more expensive. The current spec achieves the initial 75% token reduction (prose → coordinates) but does not specify the mechanisms that make the cost keep dropping over time. Six optimization opportunities exist that all use infrastructure already specced, cost nothing new to maintain, and compound with session count.

The rename is also formalized here: the HyphaLayer (Gap 13) is renamed **Kyudo Layer**

---


## Page 17

throughout both documents. Kyudo — Japanese precision archery — captures the design philosophy: precision is the goal, security is a byproduct of doing precision correctly. The security properties are structural consequences of the precision architecture. They cannot be present without each other.

**Location to edit:** Add a new **Requirement 16 (Kyudo Precision Optimization)** to requirements.md . Add a new **Section: Kyudo Precision Architecture** to design.md . Add backend/memory/mycelium/kyudo.py to the new files table, replacing hypha.py . Find-and-replace HyphaLayer → KyudoLayer and hypha.py → kyudo.py throughout both documents.

---

**What to add to requirements.md as Requirement 16:**

**User Story:** As the IRIS inference pipeline, I want context assembly cost to decrease compoundingly as the session graph matures, so that agents spend inference budget on reasoning rather than orientation — and the system becomes cheaper to run the longer it operates.

**Acceptance Criteria**

**Rename: HyphaLayer → KyudoLayer**

1. THE SYSTEM SHALL rename all references to HyphaLayer, hypha.py, and related class names to KyudoLayer, kyudo.py throughout the codebase. The classes HyphaChannel, CellWall, RagIngestionBridge, QuorumSensor, QuorumReorganization, and SUBAGENT_CHANNEL_PROFILES are retained with the same signatures — only the module name and layer name change. All <!-- gap-fix: 13 --> markers reference kyudo.py not hypha.py .

**PredictiveLoader — Pre-warm Context at Session Boundary**

2. THE SYSTEM SHALL provide PredictiveLoader in kyudo.py that runs at every session boundary — between clear_session() completing and the next get_task_context() call — and pre-navigates the most probable coordinate path for the next task.

3. THE SYSTEM SHALL base pre-navigation predictions on three signals in priority order:
(a) chrono space — time-of-day and session length patterns predict task class;
(b) context space — active project node predicts which landmark region to pre-warm;
(c) last session’s task_class fingerprint — consecutive sessions in the same project frequently share task class.

4. THE SYSTEM SHALL cache the pre-warmed coordinate path in a _prediction_cache

---


## Page 18

dict keyed by `session_id`. WHEN `get_context_path()` is called and a cache entry exists for that session AND the incoming task text matches the predicted task class within `PREDICTION_MATCH_THRESHOLD = 0.70` cosine similarity, THE SYSTEM SHALL return the cached path directly without graph traversal.

5. WHEN the cache miss occurs (prediction confidence below threshold or no cache entry) THE SYSTEM SHALL fall through to standard `navigate_from_task()` traversal and log the miss. Cache hit rate SHALL be exposed in `MyceliumInterface.get_stats()` as `prediction_cache_hit_rate`.

6. THE SYSTEM SHALL expire the prediction cache entry after `PREDICTION_CACHE_TTL = 300` seconds (5 minutes) at session boundary. A stale cache is worse than no cache — it must not persist across idle periods.

7. THE SYSTEM SHALL NOT run `PredictiveLoader` until `is_mature()` returns `True`. Pre-warming an immature graph produces noise, not signal.

**MicroAbstractEncoder — Structured Failure Warning Format**

8. THE SYSTEM SHALL provide `MicroAbstractEncoder` in `kyudo.py` that compresses episodic failure warnings from natural language sentences into a structured 5-token format: `[space: {space_id} | outcome:miss | tool:{tool_id} | condition: {condition_hash} | delta:{score_delta}]`.

9. THE SYSTEM SHALL apply `MicroAbstractEncoder` to all failure warnings before injection into the context window via `ResonanceScorer.format_context()`. Success episodes that are not suppressed retain natural language format — their variability benefits from prose. Failure warnings are structured because their value is in the pattern, not the narrative.

10. THE SYSTEM SHALL provide `MicroAbstractEncoder.decode(encoded: str) -> str` that reconstructs a human-readable failure sentence from the structured format — used by `ProfileRenderer` and `dev_dump()` for human inspection, never injected into agent context.

11. WHEN a failure warning cannot be encoded into the structured format (missing tool_id, unclassifiable condition) THE SYSTEM SHALL fall back to natural language injection and log a `DEBUG` -level message. Encoding failure MUST NOT suppress the warning — failure warnings are always injected.

**TaskClassifier — Space Subset Selection Before Navigation**

12. THE SYSTEM SHALL provide `TaskClassifier` in `kyudo.py` that runs a cheap pattern match on incoming task text — keyword heuristics plus task length, no inference call —

---


## Page 19

and returns a `task_class` string and a `space_subset: List[str]` of coordinate spaces relevant to that task class.

13. THE SYSTEM SHALL define the following built-in task class → space subset mappings as `TASK_CLASS_SPACE_MAP` in `kyudo.py`:

*   `"quick_edit"` (task text < 20 words, no planning keywords) → ["conduct", "context"]
*   `"code_task"` (code keywords: implement, fix, debug, refactor, test) → ["conduct", "domain", "toolpath", "context"]
*   `"research_task"` (research keywords: find, analyze, compare, explain, summarize) → ["domain", "style", "context", "chrono"]
*   `"planning_task"` (planning keywords: design, architect, spec, plan, structure) → ["domain", "conduct", "style", "context", "capability"]
*   `"full"` (default fallback – all non-toolpath profile spaces) → ["domain", "conduct", "style", "chrono", "context", "capability"]

14. THE SYSTEM SHALL pass `space_subset` into `CoordinateNavigator.navigate_from_task()` as an optional `spaces: List[str]` filter parameter. When provided, navigation only traverses nodes in the specified spaces. When absent, full traversal is used (backward-compatible default).

15. THE SYSTEM SHALL wire `TaskClassifier` into `MyceliumInterface.get_context_path()` as the first step before navigation. Classification cost is O(1) keyword matching — it MUST NOT add measurable latency to context assembly.

16. THE SYSTEM SHALL expose the classified `task_class` in `MyceliumInterface.get_stats()` as `last_task_class` for observability and tuning.

**Whiteboard Slice — Per-Subagent Coordinate Path Pre-filtering**

17. THE SYSTEM SHALL provide `WhiteboardSlicer` in `kyudo.py` that pre-slices the full coordinate path by subagent channel profile before broadcasting via the swarm whiteboard.

18. WHEN the coordinator (PrimaryNode / brain worker) assembles the whiteboard context, THE SYSTEM SHALL call `WhiteboardSlicer.slice(full_path, channel_profile)` for each worker’s assigned profile, producing a filtered coordinate path containing only the spaces that profile is permitted to read.

---


## Page 20

19. THE SYSTEM SHALL ensure the full coordinate path is assembled once by the coordinator and stored in the whiteboard. Slices are derived views — they are never stored separately. The source of truth remains the full path on the whiteboard.

20. THE SYSTEM SHALL track whiteboard slice token counts in `MyceliumInterface.get_stats()` as `whiteboard_broadcast_tokens` — the sum of all per-worker slice sizes. This is the metric that reflects the compounding benefit: as workers specialize and profiles narrow, broadcast cost drops.

**DeltaEncoder — Traversal Log Compression**

21. THE SYSTEM SHALL provide `DeltaEncoder` in `kyudo.py` that compresses `mycelium_traversals` log entries by storing only the coordinate path delta from the previous session’s path rather than the full path on every entry.

22. THE SYSTEM SHALL store the delta as a JSON object with three keys: `added` (nodes present in current path but not previous), `removed` (nodes present in previous path but not current), `modified` (nodes present in both with changed coordinate values exceeding `DELTA_CHANGE_THRESHOLD = 0.05`).

23. WHEN no previous session path exists (first session, or previous path was cleared by QuorumReorganization) THE SYSTEM SHALL store the full path as the delta baseline. This is the only case where a full path is written.

24. THE SYSTEM SHALL provide `DeltaEncoder.reconstruct(session_id) -> List[CoordNode]` that replays deltas from the baseline forward to reconstruct the full path for any session. Used by ResonanceScorer for historical resonance lookups — never called on the inference-time path.

25. THE SYSTEM SHALL add a `delta_compressed` boolean column to `mycelium_traversals` so `DeltaEncoder.reconstruct()` can distinguish baseline entries from delta entries without inspecting the payload.

**Partial Profile API Wired Into Context Assembly**

26. THE SYSTEM SHALL wire `get_profile_section(space_id)` into `MemoryInterface.get_task_context()` so that only the profile sections corresponding to the TaskClassifier -selected `space_subset` are fetched and injected — not the full profile string.

27. THE SYSTEM SHALL assemble the partial profile in `render_order` sequence using only the selected sections. The resulting profile string is structurally identical to a full profile — same formatting, same section headers — just fewer sections.

28. THE SYSTEM SHALL preserve the existing `get_readable_profile()` method for full

---


## Page 21

profile access — used by `dev_dump()`, human inspection, and any caller that explicitly needs the complete profile. It is never called on the inference-time path after this wiring is complete.

**Compounding Cost Model**

29. THE SYSTEM SHALL track the following metrics in `MyceliumInterface.get_stats()` to make the compounding cost reduction observable:

*   `prediction_cache_hit_rate` — fraction of tasks served from pre-warmed cache
*   `avg_spaces_navigated` — average space subset size per task (shrinks as task classification improves)
*   `whiteboard_broadcast_tokens` — total tokens broadcast to workers per session (shrinks as profiles specialize)
*   `failure_warning_tokens` — tokens consumed by failure warning injection (shrinks as structured encoding coverage grows)
*   `avg_context_tokens_per_task` — the primary metric; should decrease monotonically after graph maturity

30. THE SYSTEM SHALL log a `INFO` -level message every 50 sessions reporting the `avg_context_tokens_per_task` trend — confirming or alerting on the compounding reduction. If `avg_context_tokens_per_task` is not decreasing after session 50, the log SHOULD include which component is the largest cost contributor so tuning effort can be directed correctly.

---

**What to add to design.md :**

**New file in the new files table (replaces hypha.py entry):**

```
backend/memory/mycelium/kyudo.py | KyudoLayer, HyphaChannel, CellWall, RagIngestionBridge, QuorumSensor, QuorumReorganization, SUBAGENT_CHANNEL_PROFILES, PredictiveLoader, MicroAbstractEncoder, TaskClassifier, WhiteboardSlicer, DeltaEncoder | Full Kyudo precision and security layer — channel classification, context membrane, immune response, subagent routing, predictive pre-warming, structured encoding, task-class navigation, whiteboard slicing, delta compression
```

**Updated component in the architecture diagram:**

<mermaid>
graph LR
    A[ ] --> B[KyudoLayer (mycelium/kyudo.py)]
</mermaid>

---


## Page 22

mermaid
graph TD
    A[HyphaChannel] --> B[typed channel enum, born at source]
    A[CellWall] --> C[membrane permeability, zone enforcement]
    A[RagIngestionBridge] --> D[external input -> channel-classified coordinate]
    A[QuorumSensor + QuorumReorganization] --> E[immune response]
    A[SUBAGENT_CHANNEL_PROFILES] --> F[subagent write boundaries]
    A[PredictiveLoader] --> G[pre-warm coordinate cache at session boundary]
    A[MicroAbstractEncoder] --> H[failure warnings -> 5-token structured format]
    A[TaskClassifier] --> I[task text -> space subset -> minimal navigation]
    A[WhiteboardSlicer] --> J[full path -> per-worker filtered slices]
    A[DeltaEncoder] --> K[traversal log delta compression]
```

**New Key Design Decision (Decision 11): Compounding cost reduction as an architectural property.** The six Kyudo optimization mechanisms are not independent performance improvements — they compound. TaskClassifier reduces the spaces navigated. PredictiveLoader eliminates navigation entirely on cache hits. WhiteboardSlicer reduces broadcast cost proportional to worker specialization. DeltaEncoder reduces storage and resonance lookup cost proportional to session graph stability. MicroAbstractEncoder reduces episodic injection cost proportional to failure pattern coverage. Partial profile wiring reduces profile fetch cost proportional to task class precision. Each mechanism improves independently. Together they produce a cost curve that bends downward with session count — the system gets cheaper to operate the longer it runs and the richer the graph becomes. This is the inverse of the standard RAG cost curve, where more history means more tokens. The coordinate graph compresses history rather than accumulating it.

**New rows in Error Handling & Edge Cases:** | PredictiveLoader cache miss (low confidence) | Falls through to standard navigate_from_task() traversal; miss logged to get_stats() | Req 16.5 || MicroAbstractEncoder cannot encode failure warning | Falls back to natural language injection; warning is never suppressed | Req 16.11 || TaskClassifier task class unrecognized | Falls back to "full" space subset — all non-toolpath spaces; backward-compatible | Req 16.13 || avg_context_tokens_per_task not decreasing after session 50 | INFO log identifies largest cost contributor for targeted tuning | Req 16.30 |

---

## Instruction to Agent

After applying all fourteen fixes above:

1. **Do not renumber** existing requirements or criteria — append new criteria with the next sequential number in their section.

---


## Page 23

2. **Preserve all existing wording** in unchanged criteria — do not paraphrase or clean up text that was not part of a gap.

3. **Output two files:** an updated `requirements.md` and an updated `design.md` — do not merge them into one document.

4. **Mark every addition** with an inline comment `<!-- gap-fix: N -->` (where N is the gap number from this document) so the changes are easily auditable.

5. **Apply the rename:** find-and-replace `HyphaLayer` → `KyudoLayer` and `hypha.py` → `kyudo.py` throughout both documents. Class names inside the module (`HyphaChannel`, `CellWall`, etc.) are unchanged.

6. After edits are complete, do a final pass to confirm:
    * No `affect` space remains anywhere in either document
    * `data/identity.db` is not referenced anywhere in the mycelium package description
    * All fourteen gap fixes are present and marked
    * The bootstrapping gaps (8–12) trace the full cold-start path cohesively
    * Gap 13 (Kyudo security) traces end-to-end: channel classification → cell wall → coordinate rules → retrieval scoring → MCP pinning → quorum sensing → subagent precision
    * Gap 14 (Kyudo precision) traces end-to-end: rename → predictive loader → micro-abstract encoding → task classifier → whiteboard slice → delta encoder → partial profile → compounding cost model
    * The compounding cost model (Req 16.29–30) references all six optimization mechanisms

7. Do **not** attempt to resolve the empirical constants (`GRAPH_MATURITY_THRESHOLD`, `CONDUCT_COLD_START_DEFAULT`, `constraint_flags weights`, `QUORUM_THRESHOLD`, `QUORUM_DECAY_MULTIPLIER`, `CHANNEL_WEIGHTS`, `PREDICTION_MATCH_THRESHOLD`, `DELTA_CHANGE_THRESHOLD`). These are intentionally left as named constants for post-deployment tuning. Document them as such, do not change their values.