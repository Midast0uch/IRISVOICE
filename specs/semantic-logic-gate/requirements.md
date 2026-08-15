# Requirements: Semantic Logic Gate Architecture (DAG-Routed & Ontology-Grounded)

> **Curation pass 2 (2026-08-14).** The original draft of this spec cited APIs and
> line numbers that did not exist, undercounted the lane set, and invented a
> parallel telemetry record and a parallel ontology walk that the codebase
> already provides. Every "Verified:" annotation below was re-checked against
> live source. Where the code already does the work, the requirement is to
> **reuse**, not reinvent.

## Decisions Locked
- **DAG Capability Lanes**: The semantic logic gate classifies user requests into **DAG-composable capability lanes** (`IntentDomain` → `CapabilityLane`). There are **16 lanes** across 5 domains (3 + 4 + 2 + 4 + 3), not 15. Execution plans are DAG graphs whose capability nodes co-mingle, branch, and route to each other.
- **Ontology-Grounded, Registry-Backed Memory**: Factual memory recall is grounded in the **IRIS Cognitive Ontology** (`specs/der-dag-inversion/ontology.md`, `backend/agent/ontology_recall.py`). Both ontology axes are **registry-backed** — `topic_domain` from the 13-value `DOMAIN_IDS` registry (`backend/memory/mycelium/spaces.py:89`) and `execution_domain` from `{voice, der, research}`. The gate **never invents domain values**; a registry miss resolves to `general` and is logged.
- **Reuse, Don't Reinvent**: The kernel already performs ontology recall (`AgentKernel._der_recall_neighborhood`, `agent_kernel.py:4241`) and widening telemetry (`record_widening_telemetry`, `ontology_recall.py:304`), and already has per-turn metrics (`TurnMetrics`, `observability.py:95`). The gate extends and shares these; it does not create a second ontology walk or a second telemetry record.
- **LFM2.5 Encoder Integration (provenance-gated)**: Lane assignment uses the in-process **LFM2.5-Encoder-350M** (`embedding:lfm25-emb-350m`, 1024-dim) via the existing `EmbeddingService`. Centroid projection is **only** run when the active backend is neural; if the service has degraded to the `hash` backend, Tier 1 is skipped entirely (hash vectors carry no semantic signal — cosine similarity over them is noise).
- **Co-Mingling & Multi-Lane DAG Emission**: A prompt spanning multiple lanes emits a multi-node DAG, never a forced single path.
- **Fluid, non-binary routing (user-resolved)**: The gate does NOT force a single label. A turn produces a *ranked lane distribution*; chit-chat is just one lane among several and is **not mutually exclusive** with task lanes ("hey, and also fix the reconnect test" → banter + code_inspection + test_validation co-occur). The only boolean is a *derived efficiency flag* (`requires_der_kernel` = "do I spin up the expensive task engine?"), not a content judgment.
- **Web-mode gate composes, not replaced (user-resolved)**: the gate works *alongside* the existing `_should_skip_der` web-mode check (REQ-1 AC6).
- **Centroid artifact is a checked-in file (user-resolved)**: committed JSON with backend provenance, re-tunable without a code deploy.
- **Thresholds are initial values, tuned in the benchmark (user-resolved)**: `τ_co-mingle=0.62`, follow-up `sim≥0.65`, margin `0.15` are starting points; T13's 50-utterance benchmark tunes them.
- **Wave 0 = green baseline first (user-resolved)**: before any gate code, run the full backend suite to green so implementation starts from a known-good state.
- **Bidirectional Caducean memory (user-resolved)**: the gate reads the existing coordinate-recall path *and* writes its routing decision back to `memory_chain` (REQ-7).
- **Shim is temporary (user-resolved)**: keep a `_needs_planning` compatibility shim through the migration; the benchmark phase (T13) must prove the gate's default matches *and* improves on the legacy outcomes, and only then is the shim retired.
- **Planning is extensible, not closed (user-resolved)**: the planning decision is exposed as structured output and overridable per-task by skills/plugins/MCPs (REQ-8). `_needs_planning` as a private boolean is **not** the long-term answer — it is replaced by an extensible policy hook whose default is the gate.

---

## Introduction
The Semantic Logic Gate replaces the legacy rule-based router in `backend/agent/agent_kernel.py` — `_classify_intent` (`agent_kernel.py:1885-1927`, returns `"chat" | "action" | "followup" | "question"`) and `_needs_planning` (`agent_kernel.py:1928-1955`). It provides a multi-dimensional semantic routing engine powered by the local **LFM2.5-Encoder-350M**, grounded in the **IRIS Cognitive Ontology**, and routed into composable **DAG Capability Lanes** across Chit-Chat, Ontology Memory QA, Desktop Actions, Task Execution, and Research Swarms.

### Success Criteria
- **Latency**: Gate classification ≤ **20 ms** warm (Tier 0 < 1 ms, Tier 1 ≈ 10–15 ms, Tier 2 ≈ 2 ms), after a one-time lazy, bounded model warm-up. A classification over **35 ms** emits a performance warning. (The original spec cited three conflicting numbers — 15 ms, 20 ms, 35 ms; this is the reconciled budget.)
- **Ontology Precision**: 100% of memory-seeking turns resolve through `ontology_recall.filtered_chain_recall` with progressive widen-order and registry-backed axes — no free-text domain invention.
- **DAG Composability**: Multi-concern prompts compile into a DAG with typed dependency edges (`depends_on`, `derives_from`, `handoff_to`).
- **Precision / No Phantom Cards**: Zero chit-chat turns trigger DER task planning or a UI task-progress card (i.e., zero `TASK_START` events).

---

## Requirements

### REQ-1: Hierarchical Intent Domains & DAG Capability Lanes
**User Story:** As the IRIS kernel, I want incoming prompts decomposed into capability lanes within intent domains so execution can construct a dynamic DAG where sub-intents co-mingle and route to each other.

**Verified:** Replaces `_classify_intent` (`agent_kernel.py:1885-1927`) and `_needs_planning` (`agent_kernel.py:1928-1955`). The legacy 4-class result (`chat|action|followup|question`) is superseded by `(IntentDomain, set[CapabilityLane])`.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL classify every incoming turn into a primary `IntentDomain` and one or more `CapabilityLane` nodes — **16 lanes, counted exactly**:
  1. **`CONVERSATIONAL_SURFACE`** (3): `lane:chitchat_banter`, `lane:clarification_probe`, `lane:explanation_synthesis`.
  2. **`ONTOLOGY_MEMORY_QA`** (4): `lane:preference_lookup`, `lane:skill_landmark_query`, `lane:episodic_trajectory_walk`, `lane:domain_concept_retrieval`.
  3. **`VOICE_DESKTOP_ACTION`** (2): `lane:immediate_os_control`, `lane:system_state_query`.
  4. **`TASK_EXECUTION_DAG`** (4): `lane:code_inspection`, `lane:mutation_patch`, `lane:test_validation`, `lane:shell_command`.
  5. **`RESEARCH_SWARM_DAG`** (3): `lane:web_crawler_query`, `lane:source_triangulation`, `lane:deep_synthesis`.
- AC2: WHEN a prompt spans multiple concerns (e.g. "Look up our WebSocket reconnect pattern from last session and test it in ws_client.rs") THEN THE SYSTEM SHALL emit a DAG linking `ONTOLOGY_MEMORY_QA(lane:skill_landmark_query)` `--derives_from-->` `TASK_EXECUTION_DAG(lane:code_inspection)` `--depends_on-->` `TASK_EXECUTION_DAG(lane:test_validation)`.
- AC3: WHEN a prompt is purely `CONVERSATIONAL_SURFACE(lane:chitchat_banter)` THEN THE SYSTEM SHALL bypass the DER planner, emit **zero** `IRISStreamEvent.TASK_START` events, and dispatch to `AgentKernel._respond_direct` (`agent_kernel.py:2251`).
- AC4: IF the input prompt is empty or whitespace-only THEN THE SYSTEM SHALL classify it as `CONVERSATIONAL_SURFACE(lane:chitchat_banter)` (matching the legacy `_classify_intent` empty-string behavior).
- AC5 (NEW — preserve `_tool_mode` contract): THE SYSTEM SHALL respect `AgentKernel._tool_mode` (`agent_kernel.py:275`, `auto | ask_first | disabled`) exactly as `_needs_planning` does today:
  - `disabled` → never plan, always direct path (gate still classifies for telemetry, but `requires_der_kernel=False`).
  - `ask_first` → DER only when the prompt starts with an explicit tool prefix (`tool:`, `run:`, `execute:`, `plan:`).
  - `auto` → DER for action + follow-up lanes.
- AC6 (web-mode coordination — NEW): THE SYSTEM SHALL compose with the existing web-mode DER gate — `_should_skip_der` (`agent_kernel.py:4602`), `_is_web_search_request` (`4540`), `_looks_informational` (`4571`), `get_global_internet_access` — rather than replace it. The gate sets the lane and the `question vs action` boundary; `_should_skip_der` remains the final DER-skip authority against the web toggle (T36 contract). `lane:web_crawler_query` is only emitted when web mode is ON.
- AC7 (fluid, non-binary classification — NEW): THE SYSTEM SHALL produce a **ranked lane distribution**, never a single forced label. `chitchat_banter` is one lane among many and may co-occur with task/research lanes in the same turn; the banter portion routes to `_respond_direct`, the task portion routes to DER. The only binary output is the derived `requires_der_kernel` flag (True iff any task/research/desktop lane clears threshold OR a follow-up extends an active task), which is a pure efficiency guard, not a content classification.

**Edge Cases:**
- *Prompt requires code inspection before knowing if mutation is needed*: emit a conditional node branching `code_inspection` → `mutation_patch`.
- *Web mode OFF + search intent*: the existing `_should_skip_der`/`_is_web_search_request` path already advises toggling internet access (`agent_kernel.py:4657-4658`); the gate must not emit `lane:web_crawler_query` in this state.
- *`ModeDetector` overlap*: `backend/agent/mode_detector.py` already resolves `AgentMode` (`spec|research|implement|debug|test|review`) and `ModeResult.needs_clarification`. The gate does **not** re-implement mode detection — it consumes the mode result to seed `lane:clarification_probe` and to set `execution_domain` (`research` mode → `research` winding, per `_der_execution_domain`, `agent_kernel.py:10339`).

---

### REQ-2: Ontology-Grounded Semantic Memory Gate
**User Story:** As an agent navigating memory, I want factual queries mapped to the IRIS Cognitive Ontology so lookups query structured neighborhoods rather than unstructured text.

**Verified:** Traced against `backend/agent/ontology_recall.py:43-315`, `backend/memory/mycelium/spaces.py:89`, `specs/der-dag-inversion/ontology.md` §1–§4. The kernel already exercises this path via `AgentKernel._der_recall_neighborhood` (`agent_kernel.py:4241`) — the gate **shares** that helper rather than re-querying.

**Acceptance Criteria:**
- AC1: WHEN a prompt maps to `ONTOLOGY_MEMORY_QA` THEN THE SYSTEM SHALL extract the two **registry-backed** axes:
  - `topic_domain` ∈ the 13 canonical domains from `DOMAIN_IDS` (`spaces.py:89`): `ai, web, data, devops, mobile, systems, security, finance, science, design, hardware, gaming, general`. Resolution reuses `resolve_topic_domain(text)` (`backend/memory/mycelium/extractor.py:496`); a miss → `general` + logged.
  - `execution_domain` ∈ `{voice, der, research}` (ontology.md §2b; `AgentKernel._der_execution_domain`).
- AC2: THE SYSTEM SHALL formulate recall via `RecallFilters` (`ontology_recall.py:62`) using `node_type` ∈ `{task, step, sub_loop}` (3 values — **not** the 5 the original spec claimed) and a `relationship` from the link vocabulary. The full write vocabulary is **10 predicates** (`LINK_VOCABULARY`, `pin_store.py:61`; ontology.md §3a); only the **7 DER-resolvable subset** (`_DER_PREDICATES`, `ontology_recall.py:50`) — `part_of, depends_on, derives_from, relevant_to, failed_like, contains, related_to` — is resolved by recall; an out-of-vocabulary relationship widens to the type+domains scope (`unknown_relationship_widens`, `ontology_recall.py:77`).
- AC3: THE SYSTEM SHALL execute recall via `filtered_chain_recall(conn, filters)` with the mandatory widen-order: `relationship+type+domains` → `type+domains` → `domains` → `unfiltered-all` (`SCOPE_*`, `ontology_recall.py:43-46`).
- AC4 (route to the right store — NEW): The gate SHALL dispatch by lane to the store that actually owns the data:
  - `lane:preference_lookup` → `backend/memory/semantic.py` (`user_preferences`, `cognitive_model`, `tool_proficiency`, `domain_knowledge` categories) via `MemoryInterface.get_preference`/`set_preference` (`backend/memory/interface.py:439-482`). Preferences do **not** live in the DER `memory_chain`.
  - `lane:skill_landmark_query` → `ontology_recall.filtered_chain_recall` + the pin/landmark store. `skill_landmark` is a landmark concept, **not** a `node_type` value — it must never be passed as `RecallFilters.node_type`.
  - `lane:episodic_trajectory_walk` → `ontology_recall.filtered_chain_recall` over `memory_chain`, and `recall_failed_like` (`ontology_recall.py:280`) for the AVOID walk.
  - `lane:domain_concept_retrieval` → ontology doc concepts / `DOMAIN_IDS` registry.
- AC5: IF an ontology walk returns zero matches at the narrowest scope THEN THE SYSTEM SHALL log the winning widened scope via the existing `record_widening_telemetry` (`ontology_recall.py:304`) and return surviving nodes without raising.

**Edge Cases:**
- *Unknown relationship predicate*: widens to `type+domains` without error (existing behavior, `ontology_recall.py:209`).
- *Cross-session query*: `thread_id` is a recency **ranking** input, never a hard filter (ontology.md §4).

---

### REQ-3: LFM2.5 Neural Centroid Projector (provenance-gated)
**User Story:** As the semantic gate, I want to use the 1024-dimensional LFM2.5 Encoder to project utterances into capability-lane embeddings with negligible cost, so subtle voice phrasing is categorized correctly — without ever trusting a hash-vector cosine.

**Verified:** `EmbeddingService` (`backend/memory/embedding.py`): `EMBEDDING_DIM = 1024` (line 343), `BACKEND_LFM = "lfm25-emb-350m"` (line 47), `encode_with_backend(text, backend)` (line 742), `encode(text)` with 256-entry LRU (lines 366-367, 698), `backend` property (line 658), `compare_embeddings(a, backend_a, b, backend_b)` which **refuses cross-backend comparison** (line 262), `_window_for(LFM) == 512` (line 400), and lazy, latched, bounded model load (lines 410-466). Construction never loads the model (Defect 1, line 380).

**Acceptance Criteria:**
- AC1 (lazy centroids, not pre-computed — CORRECTED): THE SYSTEM SHALL compute and cache **16 normalized 1024-dim centroid vectors** (one per lane) lazily on first gate use, encoded via `encode_with_backend(text, BACKEND_LFM)`. Centroids are **data, not code**: stored in a versioned calibration artifact (e.g. `backend/agent/semantic_gate_centroids.json`) with recorded `backend` provenance, so they can be re-calibrated without a code deploy.
- AC2: WHEN evaluating a turn THEN THE SYSTEM SHALL compute cosine similarity of the prompt embedding against the lane centroids and produce a ranked distribution, using `compare_embeddings` (or `_cosine` on same-backend vectors only) — never a bare cross-backend dot product.
- AC3 (provenance gate — NEW): BEFORE Tier 1, THE SYSTEM SHALL check `EmbeddingService.backend == BACKEND_LFM` (i.e., a neural backend is active). IF the service has degraded to `BACKEND_HASH` (or any non-neural backend) THEN THE SYSTEM SHALL skip Tier 1 entirely and fall through to Tier 0 / Tier 2, logging a warning once per process. Hash-vector cosine is not a router input.
- AC4: WHERE multiple lanes exceed the co-mingling threshold ($\tau_{\text{co-mingle}} \ge 0.62$) THEN THE SYSTEM SHALL construct a multi-node DAG of all qualifying lanes.
- AC5 (early-exit — NEW): THE SYSTEM SHALL short-circuit the 16-way comparison when the top-2 centroid margin is decisive: compute centroids in descending prior-frequency order, and stop once the top score exceeds the second by a configured margin ($\Delta_{\text{margin}}$, default 0.15). Centroid vectors are L2-normalized once, so each comparison is an $O(d)$ dot product, not a full cosine (no per-lane norm).
- AC6: IF the LFM backend raises OR degrades THEN THE SYSTEM SHALL fail-safe to Tier 0 rule-based classification and log a warning without interrupting the request.

**Edge Cases:**
- *Prompt exceeds 512 tokens*: windowed via `EmbeddingService._window_for(BACKEND_LFM) == 512` (`embedding.py:400-402`).
- *Cold first call*: the model load is lazy + latched + bounded by `IRIS_EMBEDDING_LOAD_TIMEOUT_S`; the gate relies on a startup warm-up (REQ-6) so the first user turn never pays the load.

---

### REQ-4: Contextual Continuation & Active DAG Extension (a lens over the existing execution graph)
**User Story:** As a user conversing with IRIS during a task, I want follow-up remarks to extend or morph the work that is already underway without the assistant starting over.

**Verified:** The "active DAG" **already exists** in the system — the original spec invented a new parallel object it did not need. The real homes are:
- `AgentKernel._der_ledger` → `ExecutionLedger` → `TaskLifecycle` per `task_id` (`der_execution_ledger.py:177,209`; wired at `agent_kernel.py:6871-6884`), holding `required_step_ids` / `completed_step_ids` / `pending_step_ids` / `next_action` / `lifecycle` — documented as "resumable task state" (REQ-9).
- `DirectorQueue` (`der_loop.py:243`) — the live queue: `items` (each `QueueItem.depends_on` is already a DAG edge, `der_loop.py:210`), `completed_ids`, `vetoed_ids`, `failed_ids`, `graft_attempts`.
- `NodeRecord` (`der_loop.py:70`) — `parent_step_id`, `node_type`, `folded_back`, `blocker`, `outcome`.
- `PausedDERState` / `ConversationContext` (`conversation_context_store.py:56,76`) — cross-turn persistence of a paused loop.
- The durable link store (`part_of` / `depends_on` / `derives_from` / `failed_like`).

**Acceptance Criteria:**
- AC1 (read, don't own): WHEN a turn arrives AND a non-terminal `TaskLifecycle` exists with non-empty `pending_step_ids` THEN THE SYSTEM SHALL treat that lifecycle + the active `DirectorQueue` as the "active DAG" for follow-up evaluation. The gate is a **read-only lens**; it adds no second persistence layer.
- AC2 (extension → reuse the graft path): WHEN a short follow-up ($\le 12$ words, reusing `_is_followup_to_task`'s rules) aligns with the active task ($\text{sim} \ge 0.65$) THEN THE SYSTEM SHALL emit an *extend* directive that **appends** new `QueueItem` steps to the open lifecycle's pending set — the same mechanism the graft handler already uses mid-task (`agent_kernel.py:7810`), now triggered across turns.
- AC3 (morph → edge changes, not a fresh plan): WHEN the follow-up re-targets or reorders work THEN THE SYSTEM SHALL express it as edge changes on existing nodes (add/remove `depends_on`), and deeper rework as the existing sub-loop split (`_split_step`) + fold-back (`NodeRecord.folded_back`), **never** a new graph.
- AC4 (close/switch): WHEN the prompt explicitly aborts or switches topic THEN THE SYSTEM SHALL transition the `TaskLifecycle` to terminal and open a new `task_id` (mirroring the frontend reset on terminal task events / `iris:conversation_switched`, `hooks/useTaskProgress.ts:203-211`).
- AC5 (AVOID integration): WHEN extending from a failed step THEN THE SYSTEM SHALL consult `recall_failed_like` (`ontology_recall.py:280`) so a known-failure class is avoided rather than re-attempted.

**Edge Cases:**
- *Ambiguous continuation*: emits `lane:clarification_probe` before destructive actions.
- *Lifecycle is terminal but user still says "do the same again"*: treated as a NEW task (fresh plan), not an extension of a closed one.

---

### REQ-5: Observability, Metrics & Telemetry (extend `TurnMetrics`, don't fork it)
**User Story:** As a systems engineer, I want gate latency, centroid distances, ontology widen-scopes, and lane assignments surfaced through the existing `[LAYERS]` telemetry line, not a parallel record.

**Verified:** `TurnMetrics` (`backend/utils/observability.py:95-182`) already emits the `[LAYERS]` summary per turn and is asserted by `test_latency_metrics.py`. `get_turn_id()` (`observability.py:189`) mints the turn id. `record_widening_telemetry` (`ontology_recall.py:304`) already logs the winning widen scope. The original spec's bespoke `SemanticGateTelemetry` dataclass is **dropped**.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL add gate fields to `TurnMetrics` — `gate_domain`, `gate_lanes` (comma-joined), `gate_latency_ms`, `gate_widen_scope`, `gate_centroid_top1`, `gate_centroid_margin` — and emit them on the existing `[LAYERS]` line. Turn id comes from `get_turn_id()`.
- AC2: THE SYSTEM SHALL reuse `record_widening_telemetry` for the ontology widen-scope (no new scope logger).
- AC3: IF total gate classification + DAG compilation exceeds 35 ms THEN THE SYSTEM SHALL emit a performance warning (dev-loud via `loud_error`/`safe_call`, `observability.py:38-88`), and degrade to a single-node fallback.
- AC4: Telemetry SHALL be off the hot path (fire-and-forget, never block the response — same discipline as `broadcast_inference_event`, `observability.py:194`).

---

### REQ-6 (NEW): Reuse, Provenance & Warm-Up Discipline
**User Story:** As a maintainer, I want the gate to import ontology constants and reuse shared helpers so it cannot drift from the CI-pinned schema, and I want the model warm so no user turn pays the load.

**Acceptance Criteria:**
- AC1 (import, don't hardcode): THE SYSTEM SHALL import `DOMAIN_IDS` (`spaces.py:89`), `LINK_VOCABULARY` (`pin_store.py:61`), and node-type values from their source modules. The ontology schema is CI-pinned by `scripts/validate_ontology_schema.py` (REQ-22) — a hardcoded copy fails loudly on drift.
- AC2 (warm-up): THE SYSTEM SHALL pre-warm the LFM backend during kernel/startup initialization as a background task (bounded + latched, relying on `EmbeddingService`'s existing `_load_active_backend` semantics), so the first user turn runs at warm latency. The warm-up must never block startup.
- AC3 (shared recall helper): THE SYSTEM SHALL refactor the `RecallFilters` construction in `AgentKernel._der_recall_neighborhood` (`agent_kernel.py:4241`) into a shared helper the gate also calls, so ontology recall has exactly one code path.
- AC4 (quality gates): The gate module SHALL satisfy the AGENTS.md quality check — heavy imports lazy (no transformers/torch at module level; load via `EmbeddingService`, which already bounds it), blocking calls kept out of async hot paths, structured logs with `turn_id` in every line, and no shared mutable state across sessions.

---

### REQ-7 (NEW): Bidirectional Caducean Memory — coordinate recall + routing write-back
**User Story:** As the semantic gate, I want my memory reads and my routing decisions to flow through the same fast Caducean memory engine the rest of the system uses, so recall gets a reasoning-state dimension and routing improves itself over time.

**Verified:** `backend/gateway/iris_ffi.py`:
- Writes: `ffi_immortus_chain_append` (`1585`) routes through the **Python engine first** (`1310-1390`) because the C++ core's fixed 8-arg struct cannot carry `node_type`/`topic_domain`/`execution_domain`/`mediator` (dual-engine design, `1050-1108`). This is a background durability write (`durability_queue`), not a hot path.
- Fast native read: `ffi_immortus_chain_query_by_coordinate` (`1639`, C++ core primary at `1424-1432`) returns chain rows whose `coords_from` is within a Euclidean threshold of the current reasoning-state coordinates — distinct from embedding cosine similarity.
- Physics state: `ffi_caducean_get_state` (`1555`) returns `{x, y, xi, u, a, b, s, c_eff}` in-memory, O(1).

**Acceptance Criteria:**
- AC1 (reasoning-state recall): WHEN evaluating a turn THEN THE SYSTEM SHALL, in addition to ontology recall (REQ-2) and centroid projection (REQ-3), query `ffi_immortus_chain_query_by_coordinate` with the current `ffi_caducean_get_state` coordinates (via `coords_from`/`coords_to` of the `memory_chain` row) to surface "data gathered while thinking like this" as a complementary recall dimension. The ontology axes and the coordinate proximity are **different axes of the same `memory_chain` table** — not two stores.
- AC2 (routing write-back): AFTER classifying a turn, THE SYSTEM SHALL append a `memory_chain` row via `ffi_immortus_chain_append` recording the routing decision — `result` = lane distribution + `requires_der_kernel`, `node_type` = `task`/`step` as appropriate, `topic_domain`/`execution_domain` = the resolved registry axes, `coords_from`/`coords_to` = the Caducean state at classification time. This makes routing decisions first-class, recallable memory.
- AC3 (outcome closure): WHEN the routed turn's DER task reaches a terminal outcome THEN THE SYSTEM SHALL record that outcome on the routing row (e.g. via `ffi_immortus_chain_append`'s `nbl_outcome`/`insight`), so "how was this routed, and did it work" is answerable from memory (closing the loop the mediator causal-triple already supports).
- AC4 (never on the hot path): THE SYSTEM SHALL perform AC2/AC3 write-backs off the hot path (background/durability queue), so a memory write can never block or fail a user response.

**Edge Cases:**
- *Engine not loaded*: all `ffi_*` calls no-op (return `-1`/`[]`/`{}`); the gate degrades to ontology recall only, never raises.
- *No coordinates available* (empty `ffi_caducean_get_state`): skip the coordinate recall and the write-back coordinate fields; ontology recall still runs.

### REQ-8 (NEW): Extensible Planning Policy (per-task, overridable)
**User Story:** As an integrator (a skill, plugin, or MCP author), I want to influence how the agent plans for a specific task without editing the kernel, so a specialized workflow can change routing without breaking the default.

**Verified:** Tool *choice* is already extensible — `register_tool` (`tool_registry.py:99`), `register_capability` (`crawler/capabilities.py:149`), `set_capability_providers` (`tool_registry.py:87`). But planning *intent* is closed: `_needs_planning` (`agent_kernel.py:1928`) reads only `_tool_mode` (`275`, `auto|ask_first|disabled`, set via `iris_gateway.py:1419`). There is no hook for an external actor to change whether/how a task is planned.

**Acceptance Criteria:**
- AC1 (structured decision): THE SYSTEM SHALL expose the planning decision as structured output — `DAGPlanGraph` + `requires_der_kernel` + the lane distribution + a `why`/provenance field — never a bare bool from a private method.
- AC2 (contribution/override hook): THE SYSTEM SHALL provide a planning-policy hook where registered contributors (skills/plugins/MCPs) receive the turn and the gate's draft `DAGPlanGraph`, and may adjust it — add/remove lanes, override `requires_der_kernel`, or delegate to a custom planner. The gate's classification is the **default**, not the authority; an override is explicit and logged.
- AC3 (`_tool_mode` becomes a policy): THE SYSTEM SHALL re-express `_tool_mode` as a registered policy (`auto` = default, `ask_first` = prefix-only, `disabled` = never plan), not a special-cased branch inside the decision function.
- AC4 (default equivalence): WHEN no contributor overrides THEN THE SYSTEM SHALL behave exactly as the gate's default — equivalent to the legacy outcomes for the simple cases the benchmark pins.

**Edge Cases:**
- *Contributor returns nothing / fails*: the gate's draft stands; the failure is logged, never a crash.
- *Conflicting overrides*: last-registered wins; the conflict is logged (deterministic, reviewable).

## Open Questions (resolve WITH user → move to Decisions Locked)
All open questions are now **resolved** (see Decisions Locked). The routing-contract migration decision is finalized as: keep the `_needs_planning` **shim** during migration; the benchmark phase (T13) must prove the gate's default is equivalent for the simple cases AND superior for co-mingled/multi-lane prompts the legacy classifier could not express; only then is the shim retired and call sites point directly at the gate (REQ-8). No open items remain.

## Non-Requirements (Out of Scope)
- Training or fine-tuning custom LLM checkpoints.
- Re-architecting the low-level SQLite schema of `pin_store.py` or `memory_chain` (the gate queries existing tables).
- Modifying audio STT / Porcupine wake-word acoustic models.
- Re-implementing `ModeDetector` (`backend/agent/mode_detector.py`) — the gate consumes its result.
- Replacing `EmbeddingService` — the gate is a client of it, including its LRU cache and hash fallback.
