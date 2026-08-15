# Requirements: Node Chains — Emergent, Composable Skills

## Decisions Locked

Resolved with the user on 2026-08-14. Do not re-litigate.

1. **A skill IS a node chain.** A chain is a compressed, ordered sequence of nodes
   (each node = a mediator/action) that led to a verified outcome. Deterministic
   baseline for repeatable work. This replaces the current "skill = tool-name set"
   capture (`workflow_capture.py`) and the hand-written SKILL.md paradigm.
2. **A pivot is a first-class recorded event, not a silent deviation.** When the agent
   leaves a chain, the pivot carries indicators: where it forked (node index), what
   triggered it (NodeOutcome reason), what alternative was chosen, what the outcome
   was, and the RL signal (u/ξ delta). Future agents can query pivots and decide
   whether to follow the chain or the fork.
3. **The existing RL behavior (Caducean) is part of it.** A pivot IS an RL event: the
   agent took action u ≠ what the chain predicted, and the outcome updates the
   trajectory. A pivot that succeeds repeatedly at the same fork point gets reinforced
   → promoted into a chain variant.
4. **Chain sources: BOTH live DER runs AND recall episodes.** Live runs capture
   immediately; recall episodes (`source_channel='recall'`, `outcome_type='success'`)
   give cross-session emergence. This also fixes the failing C3 test
   (`test_recall_fixes.py::TestC3SkillGenesisSql`).
5. **Chain execution: chain-seeded queue + existing pivot machinery.** When a chain
   matches the task, the Director seeds the queue from the chain (deterministic
   spine), but every node still runs through the existing DAG machinery — NodeOutcome
   reasons, split/fold-back, probe — so pivots are natural, not forbidden.
6. **Pivot promotion: repeated success + RL reinforcement.** A pivot becomes a chain
   variant when it succeeds N times at the same fork point AND the Caducean RL signal
   (u/ξ delta, EML) confirms improvement. Both conditions — no premature forks.
7. **The chain lives in app memory; `chain.md` is a minimal generated projection.**
   `chain.md` is NOT a skill.md. It carries ONLY the context relevant to the chain's
   purpose: name, trigger, the ordered node sequence (mediator → expected outcome),
   and fork points. No tutorial, no phases, no examples. It is generated from the
   memory chain object, never hand-written, and size-bounded so loading a chain never
   costs the agent tokens it doesn't need. This is what makes chains unique to the
   application and prevents skill bloat.
8. **chain.md storage, linking, and upgradability.** chain.md files live in the app
   data directory (`data/chains/<chain_id>.md`). The link between a chain and its
   chain.md is a STABLE reference — the `chain_id` — never a content hash (a content
   hash changes on every regeneration and would break the link). The chain.md
   frontmatter carries `chain_id` (file → chain) and the chain record carries
   `chain_md_path` (chain → file). A `chain_md_hash` on the chain record is used for
   STALENESS DETECTION only: when the chain changes, the hash differs → regenerate the
   file → update the hash (idempotent, same chain_id, new content). Each chain.md is
   ALSO registered as a pin in app memory (`pin_type='chain_md'`) linked to its chain
   via `pin_links`, so future agents can search chains and the pin's `ref_status`
   (alive/stale) + `last_validated` track upgradability: chain changes → pin flips to
   `stale` → regenerated → back to `alive`.
9. **Agent-created nodes are called NODE GRAFTS.** The act of growing a node from a
   chain or script and integrating it into the registry. The node record carries an
   `origin` field: `native` (built-in/MCP/hand-registered — NOT grafts) |
   `chain_graft` (a chain promoted to a composite node, REQ-10) | `script_graft`
   (an agent-authored script, REQ-11). A failed self-test REJECTS the graft without
   touching the registry. "Graft" has DER precedent (`DirectorQueue.graft_attempts`,
   der_loop.py:262).
8. **The goal: no hardcoded workflows, no plugin sprawl.** The agent composes
   pipelines at runtime from the tools already in the app. The backend provides the
   substrate (tools, memory, RL signal, chain runner) — not the workflows.

## Introduction

IRIS already records every action as a node with a mediator, an outcome, and an RL
signal (`der_fan_traces`, `caducean_trajectories`, `mycelium_traversals`). What it
does not do is read those traces back as *executable plans*. The current skill
genesis (`workflow_capture.py`) captures only an order-insensitive set of tool names
from the live run — it throws away order, outcomes, params, and forks — and the
recall-episode genesis path was designed but never wired (the failing C3 test).

Node chains close that gap: successful node paths become first-class, loadable,
RL-scored chains that seed future execution, with pivots recorded as queryable
events. The agent curates its own pipelines from its own successful runs — no
workflow is ever hardcoded into the backend again.

### Success criteria

- A successful DER run produces a chain that a later, similar task can load and
  follow.
- 3 successful recall episodes sharing a pattern produce a chain (the C3 test
  passes).
- A deviation from a chain is recorded as a PivotEvent with indicators (node,
  trigger reason, alternative, outcome, u/ξ delta) and is queryable by future
  agents.
- A pivot that succeeds N times at the same fork point with RL confirmation becomes
  a chain variant.
- `chain.md` files are generated, minimal, and size-bounded — never hand-written,
  never bloated.
- No workflow is hardcoded into the backend; all pipelines emerge from execution.

## Requirements

### REQ-1: NodeChain data model

**User Story:** As the agent I want a successful node path to be stored as a
first-class, loadable object so that I can reuse it as a deterministic baseline.

**Verified:** `mycelium_traversals` already stores `path_node_ids` + `path_score` +
`outcome` via `log_traversal` (`backend/memory/mycelium/store.py:546`). `NodeRecord`
carries `mediator` (the tool/action + args hash) at `backend/agent/der_loop.py:120`.
What is missing is a first-class chain object with fork points and stats.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define a NodeChain record carrying at minimum: chain_id,
  name, trigger, an ordered list of chain nodes, stats (uses, success_rate,
  avg_score), provenance (which run/episode created it), and confidence.
- AC2: THE SYSTEM SHALL define a chain node as a reference to a mediator (tool +
  args schema) with its expected outcome and verified_fraction.
- AC3: THE SYSTEM SHALL store chains in app memory (`data/memory.db`), not in MCM
  coordinates.
- AC4: THE SYSTEM SHALL persist chains durably so they survive process restarts.

**Edge Cases:**
- A chain with zero nodes → never created; extraction requires >= 2 nodes.
- Duplicate chain (same mediator sequence) → deduplicated by sequence hash, not
  duplicated.

### REQ-2: Chain extraction from live DER runs

**User Story:** As the agent I want a successful run to become a chain immediately so
that the next similar task starts from the proven path.

**Verified:** `_maybe_trigger_skill_creation` is called after DER completes
(`backend/agent/agent_kernel.py:7021`) with `_tool_seq` built from `completed_items`
(`:6999-7007`). `der_fan_traces` records per-node `(step_id, tool, args_hash,
outcome, u, xi)` (`backend/agent/caducean_trajectory.py:63`).

**Acceptance Criteria:**
- AC1: WHEN a DER run completes with outcome success THEN THE SYSTEM SHALL extract a
  chain from the run's node records (mediator sequence + outcomes).
- AC2: THE SYSTEM SHALL extract the chain from the node records / fan traces, not
  from the current tool-name-set heuristic.
- AC3: THE SYSTEM SHALL record the chain's provenance (session_id, task_summary,
  timestamp).
- AC4: THE SYSTEM SHALL NOT extract a chain from a run with fewer than 2 successful
  nodes.

**Edge Cases:**
- Run completes with partial outcome → chain extraction is deferred until a success
  exists; partial runs are recorded as evidence, not chains.
- Run fails → no chain; the failure is recorded for the pivot/failure vocabulary.

### REQ-3: Chain extraction from recall episodes

**User Story:** As the agent I want repeated successful recall episodes to crystallize
into a chain so that cross-session patterns emerge without a live run.

**Verified:** `_log_recall_episode` (`backend/agent/recall_phases.py:433`) persists
recall traces with `ops_trace` and `outcome_type` (default "partial"), prefixed
`[recall:{ops_key}]` so unique op patterns store as separate rows (`:445` documents
"Skill genesis therefore sees every unique op pattern"). The C3 test
(`backend/agent/tests/test_recall_fixes.py:253`) expects genesis from 3 successful
recall episodes, but `_maybe_trigger_skill_creation` returns early on empty
tool_sequence (`backend/agent/agent_kernel.py:1561`) — the recall path was never
wired.

**Acceptance Criteria:**
- AC1: WHEN >= 3 recall episodes with `source_channel='recall'` AND
  `outcome_type='success'` share a tool/op pattern THEN THE SYSTEM SHALL extract a
  chain from that pattern.
- AC2: THE SYSTEM SHALL NOT trigger chain extraction for `outcome_type='hit'` (never
  written) or `outcome_type='partial'` (the unresolved default).
- AC3: THE SYSTEM SHALL make the C3 test
  (`test_recall_fixes.py::TestC3SkillGenesisSql::test_sql_matches_success_episodes`)
  pass without weakening its assertions.
- AC4: THE SYSTEM SHALL deduplicate chains extracted from recall against chains
  extracted from live runs (same sequence hash → one chain).

**Edge Cases:**
- Fewer than 3 matching episodes → no chain; the count is configurable.
- Episodes share a pattern but the pattern is already a chain → no new chain.

### REQ-4: Pivot recording

**User Story:** As a future agent I want to see every deviation from a chain with its
indicators so that I can judge whether the fork is relevant to my task.

**Verified:** `NodeOutcome` carries a closed `Reason` vocabulary
(`backend/agent/nodes/outcome.py:40`) — the pivot trigger vocabulary. `der_fan_traces`
carries `u`/`xi` per node (`caducean_trajectory.py:63`). `NodeRecord` carries
`folded_back`, `probe`, `chosen_branch` (`der_loop.py:141,149,157`) — the pivot
mechanics.

**Acceptance Criteria:**
- AC1: WHEN the agent deviates from a chain's predicted next node THEN THE SYSTEM
  SHALL record a PivotEvent.
- AC2: THE SYSTEM SHALL record in the PivotEvent at minimum: chain_id, node_index
  (where it forked), trigger (the NodeOutcome reason), alternative_taken (mediator
  chosen instead), outcome (OK/PARTIAL/FAILED), u_before/u_after, xi_before/xi_after.
- AC3: THE SYSTEM SHALL tag the PivotEvent with task-relevance signals (topic_domain,
  execution_domain) so other agents can match it to their task.
- AC4: THE SYSTEM SHALL make PivotEvents queryable by chain_id, node_index, trigger
  reason, and outcome.
- AC5: THE SYSTEM SHALL record pivots even when the deviation ultimately fails — a
  failed pivot is evidence, not noise.

**Edge Cases:**
- Deviation happens but the chain is not being followed (no chain active) → no
  PivotEvent; pivots are defined relative to a chain.
- The RL signal is unavailable (no Caducean state) → u/xi recorded as null, pivot
  still recorded.

### REQ-5: Pivot promotion to chain variant

**User Story:** As the agent I want a proven fork to become a first-class alternative
so that the chain grows branches rather than being replaced.

**Verified:** `caducean_trajectories` + `der_commits` carry the RL signal
(`caducean_trajectory.py:41,80`). `mycelium_landmark_merges` exists for merging
(`backend/memory/db.py` schema). The current system has no fork/variant concept.

**Acceptance Criteria:**
- AC1: WHEN a pivot at the same chain_id + node_index succeeds N times (N
  configurable, default 2) AND the RL signal confirms improvement THEN THE SYSTEM
  SHALL promote it to a chain variant.
- AC2: THE SYSTEM SHALL record the promotion with the pivot events that justified it.
- AC3: THE SYSTEM SHALL make variants selectable at execution time — the agent may
  choose the main chain or a variant.
- AC4: THE SYSTEM SHALL NOT promote a pivot that succeeded once without RL
  confirmation.
- AC5: THE SYSTEM SHALL bound the number of variants per fork point (configurable);
  exceeding the bound merges or archives the weakest variant.

**Edge Cases:**
- RL signal is neutral (no improvement, no regression) → no promotion; the pivot
  stays recorded.
- A variant becomes the dominant path (outperforms the main chain) → the variant may
  become the main chain; the old main becomes a variant.

### REQ-6: Chain-guided execution

**User Story:** As the agent I want to start a task from a proven chain but keep the
freedom to pivot when the world differs, so that determinism and discretion coexist.

**Verified:** `DirectorQueue` (`backend/agent/der_loop.py:243`) is seeded from
`ExecutionPlan.steps` and manages mode (QUICK/AGENTIC/FULL). `NodeRecord` carries the
pivot mechanics (`folded_back`, `probe`, `chosen_branch`). The dag-node-execution-model
spec (REQ-4, REQ-5) established outcome-driven routing and mid-execution re-planning.

**Acceptance Criteria:**
- AC1: WHEN a chain matches the incoming task THEN THE SYSTEM SHALL seed the
  DirectorQueue from the chain's node sequence.
- AC2: THE SYSTEM SHALL run every chain node through the existing node execution
  machinery (NodeOutcome, split/fold-back, probe) — chain nodes are NOT exempt from
  pivot mechanics.
- AC3: WHEN a chain node fails with a routable reason THEN THE SYSTEM SHALL apply
  outcome-driven routing (dag-node-execution-model REQ-4) and record a PivotEvent
  (REQ-4).
- AC4: THE SYSTEM SHALL match chains to tasks by trigger + task-relevance signals
  (topic_domain, execution_domain), not by exact task text.
- AC5: THE SYSTEM SHALL allow chain-guided execution to be disabled entirely,
  returning to today's free-planning path.

**Edge Cases:**
- No chain matches → free planning, exactly as today.
- Chain matches but every node fails → the run degrades to free planning; the
  failures are recorded as evidence against the chain's confidence.
- A chain node's mediator is unavailable (tool removed) → the node is skipped with a
  recorded reason; the chain is flagged for re-validation.

### REQ-7: chain.md projection

**User Story:** As the agent I want a lean, loadable view of a chain so that I can
discover and trigger it without loading a full instruction manual.

**Verified:** Current skills are SKILL.md files with frontmatter (name, description,
triggers) and long bodies (`.opencode/skills/*/SKILL.md`). The user's decision: chains
project to `chain.md` — minimal, purpose-relevant only, never hand-written.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL generate a `chain.md` from each chain object containing ONLY:
  name, trigger, the ordered node sequence (mediator → expected outcome), and fork
  points.
- AC2: THE SYSTEM SHALL NOT include tutorial text, phases, examples, or prose beyond
  the chain's purpose in `chain.md`.
- AC3: THE SYSTEM SHALL regenerate `chain.md` when the chain changes (promotion,
  variant addition, confidence update).
- AC4: THE SYSTEM SHALL NOT accept hand-written `chain.md` files as chain sources —
  chains come from memory, the md is a projection.
- AC5: THE SYSTEM SHALL name the projection `chain.md` (not `skill.md`) to keep the
  concept distinct from hand-authored skills.
- AC6: THE SYSTEM SHALL store `chain.md` files in the app data directory
  (`data/chains/<chain_id>.md`).
- AC7: THE SYSTEM SHALL embed `chain_id` in the `chain.md` frontmatter AND store
  `chain_md_path` on the chain record — a stable bidirectional link that survives
  regeneration.
- AC8: THE SYSTEM SHALL register each `chain.md` as a pin in app memory
  (`pin_type='chain_md'`) and link it to its chain via `pin_links` (relationship
  `chain_md`), so chains are searchable by future agents.
- AC9: WHEN a chain changes THEN THE SYSTEM SHALL mark the chain's pin
  `ref_status='stale'`, regenerate the `chain.md`, and restore `ref_status='alive'`
  with `last_validated` updated.
- AC10: THE SYSTEM SHALL store `chain_md_hash` (hash of the last generated content)
  on the chain record and regenerate the file WHEN the hash differs from the current
  chain state — the hash detects staleness, it never serves as the link.

**Edge Cases:**
- A chain with many nodes → the projection is truncated to the size bound (REQ-8);
  the full chain stays in memory.
- The projection directory is unwritable → the chain stays in memory; generation is
  retried, never fatal.
- The pin registration fails (pin store unavailable) → the chain.md file still
  exists; pin registration is retried, never fatal.
- The chain.md file is deleted but the chain exists → regenerated on next chain
  change or on demand; the chain record is the source of truth.

### REQ-8: Anti-bloat / token discipline

**User Story:** As the user I want chains to never bloat the system or cost the agent
tokens it doesn't need, so that the application stays lean as chains accumulate.

**Verified:** The concern is real: current SKILL.md files carry long instruction
bodies; loading them costs tokens. The user's explicit requirement: chains must not
cause bloat.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL bound the size of each `chain.md` (hard token/byte cap,
  configurable).
- AC2: THE SYSTEM SHALL bound the total number of chains and variants (configurable);
  when the bound is exceeded, the weakest chains (lowest confidence × usage) are
  archived, never deleted silently.
- AC3: THE SYSTEM SHALL merge chains that share a prefix and outcome (reuse the
  mycelium landmark-merge pattern) to prevent near-duplicate chains.
- AC4: THE SYSTEM SHALL NOT load a chain's full memory record when only the `chain.md`
  projection is needed.
- AC5: THE SYSTEM SHALL record chain size and load cost in the chain's stats so the
  next iteration can measure and tune the bounds.

**Edge Cases:**
- Archive threshold reached mid-session → archiving is deferred to a maintenance
  pass, never on the critical path.
- A chain is referenced by an active PivotEvent → it is not archived while referenced.

### REQ-9: Observability

**User Story:** As the tuner I want to see chain creation, pivots, and promotions so
that I can tune thresholds from data.

**Verified:** The codebase's history shows silent selection hides defects (documented
in dag-node-execution-model REQ-9). Unlogged chain behavior would be unanswerable.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log every chain creation with its source (live run / recall),
  sequence hash, and provenance.
- AC2: THE SYSTEM SHALL log every PivotEvent with its indicators (REQ-4 AC2).
- AC3: THE SYSTEM SHALL log every promotion and every refused promotion with cause.
- AC4: THE SYSTEM SHALL scope every log line with a context identifier (session_id /
  thread_id).
- AC5: THE SYSTEM SHALL keep instrumentation off the critical path.

**Edge Cases:**
- High-frequency pivot logging → rate-limited summaries rather than per-event lines.

### REQ-10: Node grafts from chains (composite nodes)

**User Story:** As the agent I want a proven chain to become a callable node so that I
can compose pipelines without anyone writing dispatch code.

**Verified:** `dag-node-execution-model` REQ-3 established that composite actions
decompose into sub-graphs; `NodeSpec` carries `composite_of` metadata
(`tool_registry.py:180-181` note). `register_tool` (`tool_registry.py:99`) and
`register_node` are programmatic and idempotent — a runtime registration is possible
today. The media pipeline tools already exist as registered nodes: `transcribe_media`
(`tool_registry.py:876`), `analyze_video_frames` (`:891`), `clip_video` (`:909`), all
with artifact kinds (`audio_ref`/`video_ref`) and failure reasons (`UPSTREAM_ERROR`,
`NO_CANDIDATES`) declared (`:190-192`, `:207-209`).

**Acceptance Criteria:**
- AC1: WHEN a chain reaches a verified state THEN THE SYSTEM SHALL allow it to be
  grafted as a composite node (a `NodeSpec` with `composite_of` = the chain's node
  sequence, `origin='chain_graft'`), with its own name, input parameters, artifact
  kind, and failure reasons.
- AC2: THE SYSTEM SHALL make a grafted chain-node callable exactly like any other
  node — inside the DER loop, inside another chain, or by the agent directly.
- AC3: THE SYSTEM SHALL allow a grafted chain-node to be nested inside a higher-order
  chain (chains compose into chains).
- AC4: THE SYSTEM SHALL self-test a graft before acceptance — every node in the
  composite is already registered and verified (reuse the `self_test_skill` structural
  discipline, `workflow_capture.py:85`). A failed self-test REJECTS the graft without
  touching the registry.
- AC5: THE SYSTEM SHALL NOT require user approval for chain grafts — they are
  composition of already-approved nodes, no new capability.
- AC6: THE SYSTEM SHALL keep the chain and its graft in sync — a chain change
  re-grafts the node or marks it stale.

**Edge Cases:**
- A graft's inner node is removed → the graft is marked stale and refused until
  re-validated.
- Two chains graft the same node name → the duplicate guard refuses the second
  (`register_node` duplicate guard, CT-8 in dag-node-execution-model).

### REQ-11: Node grafts from scripts (sandboxed, approval-gated)

**User Story:** As the agent I want to grow a genuinely new leaf capability (e.g.
add captions, add music to a video) by writing a small script, so that the pipeline is
not blocked on a developer hand-building the node.

**Verified:** `ToolSpec.executor` (`tool_registry.py:58`) supports
`internal | mcp | dev | crawler | research | memory | gui` — there is NO script
executor today. The `create_skill` internal MCP tool (`tool_registry.py:492`) is the
precedent for runtime node creation. The user's decision: sandboxed execution +
approval for escalation.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL allow the agent to author a script (Python or a parameterized
  command template) and graft it as a node with a new `executor="script"` type and
  `origin='script_graft'`.
- AC2: THE SYSTEM SHALL run script grafts in a sandbox: subprocess with timeout, no
  shell expansion, bounded arguments, no network by default.
- AC3: THE SYSTEM SHALL default script grafts to `permission_tier="read_only"` and
  SHALL require explicit user approval before any escalation to `side_effect` or
  `destructive` (dag-node-execution-model REQ-8 AC2 — a route can never exceed the
  user-approved tier).
- AC4: THE SYSTEM SHALL structurally self-test a script graft before first use — the
  script is well-formed, references only known binaries, and declares its artifact
  kind + failure reasons. A failed self-test REJECTS the graft.
- AC5: THE SYSTEM SHALL record the graft's source (agent-authored, chain_id that
  motivated it) and its approval state in the node record.
- AC6: THE SYSTEM SHALL allow script grafts to be composed into chains like any other
  node once accepted.
- AC7: THE SYSTEM SHALL allow the user to disable script grafts entirely
  (composition-only mode — chain grafts, REQ-10, still work).

**Edge Cases:**
- The script hangs → the subprocess timeout kills it; the node returns a typed
  failure reason.
- The script writes outside its sandbox → denied by the sandbox; recorded.
- The user denies an escalation → the graft stays at its current tier; the agent
  pivots to an alternative.
- A script graft fails in a chain → outcome-driven routing applies (REQ-6 AC3).

### REQ-12: Tool disambiguation — context signatures and fit validation

**User Story:** As the agent I want to pick the right tool when several similar tools
exist, so that a chain node never fires the wrong tool for the task context.

**Verified:** Tools today are differentiated only by name + description + category
(`ToolSpec`, `tool_registry.py:44-70`). `sequence_similarity` (`workflow_capture.py:52`)
is name-Jaccard, order-insensitive — no context dimension. The dag-node-execution-model
declares artifact kinds (`_produce`) and failure reasons (`_emits`) but no task-context
dimension. The collision risk is already real: `analyze_video_frames` (video files) vs
`vision.analyze_screen` (live screen) — both vision, different context.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL give every node a context signature: domain (video | audio |
  screen | web | memory | system), artifact contract (in/out kinds), and intent
  keywords.
- AC2: THE SYSTEM SHALL record the context signature on each chain node at capture
  time — the tool AND the context it was used in.
- AC3: WHEN a chain is replayed THEN THE SYSTEM SHALL validate each node's mediator
  against the current task context; IF the fit is below threshold THEN THE SYSTEM
  SHALL treat the deviation as a pivot (recorded per REQ-4) rather than firing the
  wrong tool.
- AC4: WHEN a graft is created THEN THE SYSTEM SHALL require it to declare its
  distinguishing context signature; IF a near-duplicate exists (same domain + artifact
  contract + similar intent) THEN THE SYSTEM SHALL refuse the graft or require
  explicit differentiation.
- AC5: THE SYSTEM SHALL maintain a tool similarity index (semantic, not name-Jaccard)
  used by both selection (AC3) and graft dedupe (AC4).
- AC6: THE SYSTEM SHALL record the selection rationale (which similar tools were
  considered, why this one won) on the node record.

**Edge Cases:**
- Two tools are truly interchangeable → the index reports high similarity; selection
  is deterministic and logged.
- The chain's recorded context is stale (task changed) → fit validation fails →
  pivot → possibly a new variant.
- A graft declares a context identical to an existing tool → refused; the agent must
  differentiate or use the existing tool.
- The similarity index is unavailable → selection falls back to exact-name match and
  logs the degradation.

### REQ-13: Tool evolution — versioning, re-validation, improvement feedback

**User Story:** As the agent I want chains to stay correct when the tools they use are
improved or changed, so that a chain never silently runs against a stale tool.

**Verified:** `NodeRecord.mediator` records the tool + args hash (`der_loop.py:120`)
but no tool version. `der_fan_traces` records `args_hash` (`caducean_trajectory.py:63`)
but no tool version. There is no tool-version or tool-change re-validation mechanism
today. REQ-6 edge covers mediator-unavailable but not mediator-changed. Tool
improvement is the "improve on the process" loop of the grand vision.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL record a tool version/hash on each chain node at capture time
  — which version of the tool the chain was built against.
- AC2: WHEN a tool's signature changes (parameters, artifact contract, failure
  reasons) THEN THE SYSTEM SHALL flag all chains referencing it as stale and
  re-validate them.
- AC3: WHEN a tool is removed THEN THE SYSTEM SHALL flag referencing chains and pivot
  them to an alternative (REQ-6 edge) or mark them for re-capture.
- AC4: WHEN a tool is improved THEN THE SYSTEM SHALL re-verify chains using it and
  reflect the improvement (confidence bump, re-validated outcome) — tool improvement
  is RL reinforcement for the chain.
- AC5: THE SYSTEM SHALL record the tool-change event and each chain's re-validation
  outcome (adapted / re-captured / archived).
- AC6: THE SYSTEM SHALL apply tool evolution to grafts too — a chain graft re-validates
  when its inner nodes change; a script graft updates when its script is improved.

**Edge Cases:**
- A tool changes but the chain still works → re-validation confirms; chain stays,
  version bumped.
- A tool changes incompatibly → the chain's node fails fit validation (REQ-12 AC3) →
  pivot → possibly a new variant.
- A tool is removed and no alternative exists → the chain is archived (never deleted
  silently, REQ-8 AC2).
- Tool-change storms (many tools change at once) → re-validation is batched/deferred
  to a maintenance pass, never on the critical path.

### REQ-14: Cross-domain pipeline creation — remove capture blockers

**User Story:** As the agent I want to create a pipeline for ANY domain or across
domains, so that no structural threshold or dedupe rule silently prevents a valid
pipeline from becoming a chain.

**Verified:** Three verified blockers exist today: (1) `MIN_DISTINCT_TOOLS = 3`
(`workflow_capture.py:29`) — a 2-node pipeline is never captured; (2)
`sequence_similarity` (`workflow_capture.py:52`) is order-insensitive name-Jaccard —
`transcribe → clip` and `clip → transcribe` collide as identical; (3) nodes declare
what they PRODUCE (`_produce` map, `tool_registry.py:183`) but not what they CONSUME,
so cross-domain composition cannot validate artifact compatibility before execution.
Verified NON-blockers: `domain_windings` (`coupled_registry.py:83`) maps domains to
Caducean physics numbers, not tool filters; `get_available_tools` (`tool_bridge.py:237`)
returns all tools with no domain filter — cross-domain composition is structurally open.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL capture a chain from ANY successful run regardless of
  distinct-tool count — a 2-node chain is valid (removes `MIN_DISTINCT_TOOLS`).
- AC2: THE SYSTEM SHALL dedupe chains by ORDER-SENSITIVE sequence hash, not
  name-Jaccard — distinct pipelines sharing a tool set are distinct chains.
- AC3: THE SYSTEM SHALL extract chains from BOTH episode channels — DER-run episodes
  (`source_channel='websocket'`, `agent_kernel.py:747`) AND recall episodes
  (`source_channel='recall'`).
- AC4: THE SYSTEM SHALL validate artifact compatibility (node A's output kind
  consumable by node B's input kind) at composition time, BEFORE execution — a
  mismatch is a routable failure, not a runtime surprise.
- AC5: THE SYSTEM SHALL NOT restrict chain composition by domain — any registered
  node composes with any other (verified: no domain filter exists).

**Edge Cases:**
- A 2-node chain is captured but never reused → it decays/archives via the RL layer
  (REQ-8), not by a capture threshold.
- Two pipelines share a tool set but differ in order → both captured, distinct
  sequence hashes.
- Artifact mismatch at composition → the agent pivots to a compatible node (REQ-12
  AC3) or grafts an adapter (REQ-11).

### REQ-15: Chain-level permission resolution (security-preserving)

**User Story:** As the user I want to approve a cross-domain chain once, not per node,
so that legitimate pipelines are not silently blocked while security is preserved.

**Verified:** `ToolSpec.permission_tier` (`tool_registry.py:56`) is
`read_only | side_effect | destructive`. A cross-domain chain mixes tiers; today
there is no chain-level resolution — a chain needing `side_effect` in a `read_only`
session is blocked with no approval path.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL compute a chain's required permission tier as the MAX of its
  nodes' tiers.
- AC2: WHEN a chain requires a tier above the current session THEN THE SYSTEM SHALL
  request user approval for the CHAIN as a unit (not per node) and SHALL NOT execute
  until approved.
- AC3: THE SYSTEM SHALL record the approved tier on the chain record.
- AC4: THE SYSTEM SHALL NOT allow a chain to exceed its approved tier even if a
  node's tier changes later (REQ-13 interaction — re-validation re-checks the tier).
- AC5: THE SYSTEM SHALL apply the same resolution to grafts — a script graft's tier
  is its own (REQ-11 AC3); a chain graft's tier is the max of its inner nodes.

**Edge Cases:**
- The user denies chain approval → the chain is not executed; the agent pivots to a
  lower-tier alternative or asks for a narrower task.
- A node's tier rises after approval (tool evolution) → the chain is flagged for
  re-approval, never silently executed at the higher tier.
- A chain is entirely read_only → no approval needed; executes normally.

## Non-Requirements (Out of Scope)

- **Replacing DER.** DER stays the execution loop; chains seed it (REQ-6).
- **Replacing the dag-node-execution-model.** Node chains build on it; they do not
  replace typed outcomes or outcome-driven routing.
- **A visual chain editor or any UI for authoring chains.**
- **Hand-written skills.** Hand-authored SKILL.md files remain usable as today, but
  they are not chain sources (REQ-7 AC4).
- **Decomposing `agent_kernel.py`.** Tracked separately.
- **Autonomous permission escalation.** Pivots respect the existing permission tiers
  (dag-node-execution-model REQ-8). Script grafts default to `read_only` and require
  user approval to escalate (REQ-11 AC3).
- **Cross-machine chain sharing.** Chains are app-local.
- **Building the missing media leaf nodes** (e.g. `add_music`, `add_captions`) as
  hand-written backend tools. Chains compose registered nodes (REQ-10); the agent may
  graft them as script nodes (REQ-11) — but no hand-coded media tools are added to
  the backend by this spec.

## Open Questions

- Default values for the configurable bounds (chain.md size cap, max chains, max
  variants, promotion N). Start: size cap ~2KB, max chains 200, max variants 3 per
  fork, N=2 — revisit from REQ-8 AC5 / REQ-9 data.
- Whether chain matching should also use the embedding service (semantic similarity)
  or stay lexical (trigger + domain tags). Start lexical; revisit from REQ-9 data.
- Whether a chain variant that becomes dominant should auto-promote to main chain
  (REQ-5 edge case) or require user confirmation. Start auto with logging.