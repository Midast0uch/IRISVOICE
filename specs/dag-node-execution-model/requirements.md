# Requirements: DAG Node Execution Model

## Decisions Locked

Resolved with the user on 2026-08-10. Do not re-litigate.

1. **Every action in the application is a node.** Existing pipelines and new ones alike.
   Not a websearch-specific mechanism — websearch is simply the first place the absence
   was felt.
2. **The brain model directs; it is not funnelled.** A fixed string of tool calls is not
   acceptable as the execution model. The planner composes and re-routes a graph.
3. **Pivots are first-class, not error handling.** When a node fails in a way another node
   can address, re-routing is a normal traversal — the same way `crawl → vision → crawl`
   is normal in the websearch spec, generalised to every capability.
4. **Existing tools must keep working untouched.** Adoption is strangler-fig. A tool that
   never declares node metadata behaves exactly as it does today.
5. **MCP-backed and multi-modal actions are first-class nodes**, not special cases. The
   user is building pipelines over MCP servers, and audio (parakeet) + vision pipelines
   for video clipping/editing from ChatView or YouTube. These must compose with each
   other without new bespoke plumbing per pipeline.
6. **This does not replace DER.** DER remains the execution loop. This spec gives DER the
   seams it currently lacks.

## Introduction

IRIS already has a tool registry, a DER execution loop, node records, and edges. What it
does not have is a way for the planner to see *inside* an action or to re-route when one
fails. Every tool is a leaf that returns a result; composite tools hide entire pipelines
with their own decision points; and recovery must be hand-written as an `if` branch inside
whichever module owns the pipeline.

The websearch feature demonstrated the cost concretely: `fetch.crawl` and `fetch.vision`
were built as interchangeable capabilities, then invoked from inside a hardcoded funnel.
DER saw one tool call (`crawler_query`) with one outcome, so it could not escalate a
fresh bot-challenge to vision, could not switch acquisition channel when the URL planner
returned nothing, and its only loop-back re-ran the same planner and failed identically.
Three separate hand-written branches were required to fix three symptoms of one structural
gap.

This spec makes actions composable nodes with routable outcomes, so the planner can pivot
without anyone writing the branch in advance.

### Success criteria

- A node that fails for a reason another node advertises can be re-routed **without any
  code change in the failing node's module**.
- `crawler_query` — today one opaque tool wrapping a full pipeline — is expressible as a
  sub-graph whose decision points DER can see and re-route.
- A new pipeline (e.g. audio-transcribe → segment-select → clip → render) is added by
  registering nodes, with no new dispatch or orchestration code.
- An MCP tool and an in-process tool are indistinguishable to the planner.
- Every existing tool continues to work with no changes to its definition.

## Requirements

### REQ-1: Typed, routable node outcomes

**User Story:** As the planner I want an action's failure to carry a machine-routable
reason so that I can choose a different node instead of failing the task.

**Verified:** Today tools return free-form results. `backend/agent/tool_decision.py`
records success/error_type, but the reason is not a routable value the planner branches
on. The websearch path had to invent its own vocabulary — `backend/crawler/usability.py`
`UsabilityReason` (OK / EMPTY / TOO_SHORT / CHALLENGE / TRANSPORT_ERROR) — which is
consumed only inside the crawler. That enum is the working prototype of what this
requirement generalises.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define one node-outcome type carrying at minimum: terminal status,
  a typed reason, a human-readable detail, and the produced artifact when successful.
- AC2: THE SYSTEM SHALL require every node to return that outcome type and SHALL NOT allow
  a node to signal failure by raising into the planner.
- AC3: THE SYSTEM SHALL make the typed reason a closed, enumerated vocabulary so routing
  decisions are decidable rather than string-matched.
- AC4: WHEN a node produces a partial result THEN THE SYSTEM SHALL represent it as a
  distinct status from both success and failure, so the planner can decide whether partial
  is sufficient.
- AC5: THE SYSTEM SHALL preserve the outcome's reason through to the existing node record
  and edge machinery, so the graph records WHY a traversal happened.

**Edge Cases:**
- A node raises despite AC2 → the runner converts it to a failure outcome with a reserved
  reason; the task must not die.
- A reason with no registered handler → treated as terminal for that branch, recorded, and
  surfaced (never silently swallowed).
- Legacy tools that return today's free-form result → mapped to a default outcome by the
  adapter (REQ-7), never blocked.

### REQ-2: One node registry covering every action

**User Story:** As a developer I want to register a new action once and have the planner
able to use it, so that adding a pipeline does not mean writing dispatch code.

**Verified:** A registry already exists and is most of the way there.
`backend/agent/tool_registry.py:45 ToolSpec` carries `name`, `description`, `parameters`,
`category`, `permission_tier`, `executor` (`internal | mcp | dev | crawler | research |
memory`), `mcp_server` / `mcp_tool`, `parallel_safe`, `long_running`, `critical`, with
`register_tool` at `:99` and `register_builtin_tools` at `:250`. A second, parallel
registry exists for fetch capabilities at `backend/crawler/capabilities.py` (`CAPABILITIES`,
`register_capability`, `get_capability`) — evidence that the pattern is already being
reinvented per-feature.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL extend the existing tool registry rather than introducing a third
  registry.
- AC2: THE SYSTEM SHALL allow a registered node to declare its typed inputs, its produced
  artifact type, and the failure reasons it can emit.
- AC3: THE SYSTEM SHALL treat MCP-backed nodes, in-process nodes, and subprocess-backed
  nodes identically at the planner interface.
- AC4: THE SYSTEM SHALL allow the fetch-capability registry to be expressed through the
  unified registry so the parallel mechanism can be retired.
- AC5: THE SYSTEM SHALL NOT require a node to declare node metadata; an undeclared tool
  remains callable exactly as today (REQ-7).

**Edge Cases:**
- Two nodes registering the same name → last-write-wins is forbidden; registration must
  fail loudly at startup rather than silently shadow.
- MCP server unavailable at registration time → the node registers as unavailable and the
  planner routes around it, rather than the registration failing.

### REQ-3: Composite actions decompose into sub-graphs

**User Story:** As the planner I want to see the decision points inside a multi-step
action so that I can re-route within it instead of only around it.

**Verified:** `crawler_query` is one tool wrapping the entire funnel — plan → fetch →
passage-split → credibility → rerank → extract+cite — in
`backend/crawler/orchestrator.py research()`. Its internal recovery paths
(`dispatch_urls`, `_race_url`, `_park_source`, the broaden-and-retry) are invisible to
DER, which is why each required a hand-written branch.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL allow a node to be defined as a composition of other nodes.
- AC2: WHEN a composite node runs THEN THE SYSTEM SHALL record its sub-node outcomes
  individually, not only the composite's terminal outcome.
- AC3: THE SYSTEM SHALL allow the planner to re-route at a sub-node boundary without
  restarting the composite from the beginning.
- AC4: THE SYSTEM SHALL keep the composite callable as a single unit, so existing callers
  and the existing UI card behaviour are unchanged.
- AC5: THE SYSTEM SHALL express the websearch acquisition path as the reference composite,
  since its decision points are already specified and tested.

**Edge Cases:**
- A sub-node fails in a composite whose caller only understands the composite's result →
  the composite still returns one outcome (AC4) while the sub-outcomes are recorded (AC2).
- Deeply nested composites → depth is bounded and the bound is configurable; exceeding it
  is a recorded failure, not a hang.

### REQ-4: Outcome-driven routing

**User Story:** As the planner I want to pick a different node based on how the last one
failed, so that recovery is a graph decision rather than code someone remembered to write.

**Verified:** NEW. The absence is demonstrated: `backend/crawler/orchestrator.py`
`_dispatch_one` routes to vision ONLY on prior recorded domain-failure history, so a bot
challenge encountered in the moment never escalated — a branch that had to be added by
hand after the fact.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL allow a node to advertise which failure reasons it can plausibly
  recover from.
- AC2: WHEN a node returns a failure reason THEN THE SYSTEM SHALL select candidate
  recovery nodes by matching that reason against advertised capabilities.
- AC3: THE SYSTEM SHALL bound recovery attempts per originating step, and the bound SHALL
  be configurable.
- AC4: THE SYSTEM SHALL NOT re-route a failure reason that represents a deliberate refusal
  (for example a robots.txt refusal or a denied permission); such reasons are terminal.
- AC5: THE SYSTEM SHALL record every routing decision with the reason that triggered it
  and the node selected.
- AC6: WHEN no candidate node advertises the reason THEN THE SYSTEM SHALL report the
  failure honestly rather than retrying the same node.

**Edge Cases:**
- Two nodes advertise the same reason → selection is deterministic and logged; cost or
  declared preference breaks the tie.
- A recovery node fails with the same reason → the bound in AC3 prevents a loop; the
  second identical failure is terminal for that branch.
- Cyclic advertisement (A recovers B, B recovers A) → the attempt bound is the guard.

### REQ-5: Mid-execution re-planning

**User Story:** As the brain model I want to change the plan while it is running when the
world turns out differently, so that a task is not locked into the shape I guessed at the
start.

**Verified:** DER plans steps up front. `_execute_plan_der`
(`backend/agent/agent_kernel.py:5908`) executes a planned step list; the only loop-back in
the websearch path re-runs the *same* planner with a broadened query, which is why a
planner failure re-failed identically.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL allow the executing graph to be extended or amended between steps
  based on outcomes already observed.
- AC2: THE SYSTEM SHALL preserve already-completed work when the graph is amended; an
  amendment SHALL NOT re-execute satisfied nodes.
- AC3: THE SYSTEM SHALL bound amendments per task and SHALL record each one.
- AC4: THE SYSTEM SHALL keep the existing step budget and token accounting authoritative;
  an amendment cannot exceed the task's budget.
- AC5: IF an amendment would exceed a bound THEN THE SYSTEM SHALL proceed with the existing
  graph and record that the amendment was refused.

**Edge Cases:**
- Amendment arrives while a parallel branch is in flight → the in-flight branch completes;
  amendments apply to scheduling decisions not yet made.
- Amendment that removes a node whose output a later node consumes → rejected as invalid,
  recorded, execution continues unchanged.

### REQ-6: Multi-modal and MCP nodes are first-class

**User Story:** As a builder I want to compose vision, audio, MCP and in-process actions in
one graph so that pipelines like "clip this YouTube video" are assembled, not hand-built.

**Verified:** The pieces exist and are unconnected. MCP: `backend/mcp/builtin_servers.py`
`BuiltinServer` with `_setup_tools`, `backend/mcp/protocol.py` `MCPTool`, and
`backend/tools/vision_mcp_server.py` exposing five `vision.*` tools. Vision browser
actions: `backend/vision/browser_session.py`. `ToolSpec` already carries `executor="mcp"`
plus `mcp_server`/`mcp_tool`, so the routing hook exists.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL let a node consume the artifact produced by a node of a different
  modality without bespoke conversion code at the call site.
- AC2: THE SYSTEM SHALL declare artifact types so the planner can tell which nodes can
  legally follow which.
- AC3: THE SYSTEM SHALL support long-running nodes without blocking the graph, reusing the
  existing `long_running` heartbeat behaviour.
- AC4: THE SYSTEM SHALL allow a node to be backed by an external MCP server with no change
  to how the planner selects or sequences it.
- AC5: WHERE a modality's backing service is unavailable THE SYSTEM SHALL mark its nodes
  unavailable and route around them (REQ-4 AC6 applies when no alternative exists).

**Edge Cases:**
- Artifact too large to pass by value (video, audio) → passed by reference/handle; the
  contract must not force materialisation into the graph.
- An MCP server disconnects mid-graph → in-flight node fails with a typed reason; routing
  applies.

### REQ-7: Strangler-fig adoption

**User Story:** As a maintainer I want this to land incrementally so that a partially
migrated system is fully working at every point.

**Verified:** 12,291-line `agent_kernel.py` with 117 test files reaching into internals
(pin `pin_1bb97f28e137`). A big-bang conversion is not viable.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL execute an undeclared legacy tool exactly as it does today.
- AC2: THE SYSTEM SHALL allow nodes to be adopted one at a time, with declared and
  undeclared nodes coexisting in one graph.
- AC3: THE SYSTEM SHALL keep every existing tool name, signature, and result shape
  unchanged for existing callers.
- AC4: THE SYSTEM SHALL provide a switch that disables outcome-driven routing entirely,
  returning behaviour to today's path.
- AC5: WHEN routing is disabled THEN THE SYSTEM SHALL be behaviourally identical to the
  pre-change system.

**Edge Cases:**
- A declared node calls an undeclared one → allowed; the undeclared result is adapted.
- Rollback mid-migration → AC4's switch is the rollback.

### REQ-8: Safety and permission preserved through routing

**User Story:** As the user I want re-routing never to become a way around a refusal or a
permission gate.

**Verified:** `ToolSpec.permission_tier` (`read_only | side_effect | destructive`) already
exists and gates execution. The websearch spec established the precedent that a robots.txt
refusal must never be routed around, and that a CAPTCHA is parked rather than solved.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL evaluate the permission tier of a recovery node exactly as it does
  for a planned node.
- AC2: THE SYSTEM SHALL NOT allow a recovery route to reach a higher permission tier than
  the step the user approved.
- AC3: THE SYSTEM SHALL treat deliberate refusals as terminal reasons (REQ-4 AC4).
- AC4: THE SYSTEM SHALL record any routing decision that was blocked by permission.

**Edge Cases:**
- A recovery node needs a permission the original did not → the route is offered to the
  user, not taken silently.

### REQ-9: Observability of the graph

**User Story:** As the tuner I want to see the graph that actually executed, so routing
policy can be set from data.

**Verified:** The need is proven by this codebase's history: silent provider selection and
silent capability selection each hid a defect for months, and 19 mechanisms were found
built-but-never-called. Unlogged selection is unanswerable.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log every node execution with its node name, typed outcome reason,
  duration, and task identifier.
- AC2: THE SYSTEM SHALL log every routing decision including the reason, the candidates
  considered, and the selection.
- AC3: THE SYSTEM SHALL log every graph amendment and every refused amendment with cause.
- AC4: THE SYSTEM SHALL make the executed graph reconstructable from the log alone.
- AC5: THE SYSTEM SHALL keep instrumentation off the critical path.

**Edge Cases:**
- High-fan-out graphs → log rate-limited summaries rather than per-item lines.

## Non-Requirements (Out of Scope)

- **Replacing DER.** DER stays the execution loop; this adds seams to it.
- **Decomposing `agent_kernel.py`.** Tracked separately in `pin_1bb97f28e137`.
- **A visual graph editor or any UI for authoring graphs.**
- **Distributed or cross-machine node execution.**
- **Changing existing tool names, signatures, or result shapes** (REQ-7 AC3).
- **Autonomous permission escalation** (REQ-8 AC2).
- **Building the video-clipping or other new pipelines themselves.** This spec makes them
  expressible; each pipeline is its own spec.

## Open Questions

- Whether artifact types should be a closed enum or structurally typed — start closed and
  widen from measured need.
- Selection policy when several nodes advertise the same reason: declared preference,
  measured cost, or measured success rate. Start with declared preference and revisit from
  REQ-9 AC2 data.
- Whether graph amendment should be planner-driven only, or whether a node may propose a
  successor. Start planner-only; a node proposing its own successor reintroduces hidden
  control flow.
