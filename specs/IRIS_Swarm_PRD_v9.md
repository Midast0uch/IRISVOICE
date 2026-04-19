IRIS Swarm Orchestrator — Product Requirements Document v9.0
Intelligent Recursive Intelligence System Status: Active Development | Date: March 2026 Audience: Developers and AI agents implementing this system

Changelog from v8.0:

POOL_SIZE changed from 3 (1 brain + 2 parallel workers) to 2 (Leading DER + Trailing DER)
Worker pool geometry replaced with Two-Brain DER Loop architecture
Leading DER Loop: Director A — full speed forward execution
Trailing DER Loop: Director B — crystallization pass, 2–3 steps behind
DER Loop (Director · Explorer · Reviewer) specified in full
Trailing crystallizer fills depth gaps the leading loop left at surface level
Token budget replaces cycle count limit
Mode System added: SPEC / RESEARCH / IMPLEMENT / DEBUG / TEST / REVIEW
Ask User Tool added — structured clarification with Mycelium coordinate ingestion
Spec Engine added — simple doc or full three-doc set based on complexity
Write lock added to MyceliumInterface for concurrent graph access
Mycelium coordinate graph remains the synchronization layer — loops never communicate directly
Parallel mode defined: trailing loop catches up to leading loop only on blocker resolution
Document Purpose
This PRD is written to be consumed directly by an implementing agent or developer. Every section answers one question: what do I build and exactly how does it work? Architecture decisions are stated with their rationale. Code is complete, not pseudocode. Integration points with the existing application are explicit. The Torus network layer is grounded in the published whitepaper — nothing is speculative.

The emphasis of this document is the Two-Brain DER Loop. The application integration layer is a foundation. The Torus network is the destination. The two-brain architecture is the mechanism that produces depth — not just breadth — across any task.

System Context — What Already Exists
IRIS is a running application. It has:

A frontend (Electron/web) sending WebSocket JSON messages
A WebSocket server on 127.0.0.1 receiving those messages
An AgentKernel — a single-model inference loop that currently handles all messages
A ToolBridge connecting to MCP servers and MiniCPM for visual grounding
A SkillsLoader that reads skills/ folder SKILL.md files
Two loaded models: lfm2-8b (brain/reasoning) and lfm2.5-1.2b-instruct (executor)
A MemoryInterface — three-tier memory (working, episodic, semantic) with single access boundary
A Mycelium Layer — coordinate memory graph with landmark crystallization, behavioral contracts, gradient warnings, and five-dimensional context fragmentation (Pacman)
What this PRD builds: The swarm replaces the AgentKernel with a Two-Brain DER Loop. Everything else is untouched. The frontend never changes. The WebSocket protocol never changes.

What this PRD does not touch: Frontend code, WebSocket server protocol, ToolBridge internals, model files.

Table of Contents
Design Principles
Architecture Overview
Model Architecture — Three Roles
TaskMessage — The Atom of Swarm Communication
Permission System
Two-Brain DER Loop — Core Architecture
DER Loop Internals — Director · Explorer · Reviewer
Trailing Crystallizer — Director B
Mode System — Director Intelligence
Mycelium Integration — Shared Graph
SwarmBridge — WebSocket Interface
SkillsLoader Integration
Checkpoint-Based Recovery
Three-Tier Memory Architecture
Safety System
Docker Executor
Voice Pipeline
Torus Network
Channel Gateway
File Structure
Dependencies
Development Roadmap
1. Design Principles
1.1 The Swarm Is the Intelligence, the App Is the Interface
The frontend, WebSocket protocol, and channel integrations are the interface layer.
The swarm is the intelligence layer. Changes to the swarm do not require frontend
changes. These layers are sealed from each other.

1.2 Model-Agnostic From the First Line of Code
No component outside src/model/ references model names. The ModelAdapter interface is the only contract. Swapping models is a change to config/models.json, not source code.

1.3 Skills Are Tools, Tools Are Permissioned
Every capability is registered in the PermissionManager before any worker can call it. A worker without a valid, signed, unexpired token cannot act. No exceptions, no overrides.

1.4 The Swarm Must Be Correct Before It Is Fast
Permission system, checkpoint recovery, and token revocation must be fully implemented
and tested before optimising for throughput. Correct before fast.

1.5 Torus Readiness Is a Day-One Constraint
Every component that will eventually communicate across the Torus network has its
interface defined today. When the network activates, the change is configuration, not code.

1.6 Personal Use Is Always Free, Network Use Is Token-Gated
Your own model, your own devices, your own tasks — always free. Tokens only matter when
consuming compute from other Torus nodes.

1.7 Borrow, Don't Rebuild
Docker sandboxing uses AutoGen's DockerCommandLineCodeExecutor. Vector search uses sqlite-vec. Post-quantum crypto uses NIST-finalised standards. IRIS's contribution is integration and orchestration.

1.8 Brain Thinks Before Executor Acts
Every task produces an explicit ExecutionPlan before any tool is touched. The REASONING model plans. The EXECUTION model follows the plan one step at a time with per-step reflection. This is not optional.

1.9 Depth Over Breadth — The Trailing Crystallizer Principle
New in v9.0. Surface-level completion is not completion. A plan step marked COMPLETED means the leading DER loop's Explorer got a passing result. It does not mean the implementation is coherent with what came before, edge cases are handled, or the detail layers beneath the surface were reached. The trailing crystallizer exists to close this gap. The leading loop covers distance. The trailing loop covers depth. Together they produce work that is both fast and thorough.

1.10 The Mycelium Graph Is the Synchronization Layer
New in v9.0. The two DER loops never communicate directly. There is no message passing between Director A and Director B. Synchronization happens entirely through the shared Mycelium coordinate graph. When Director A's Explorer completes a step and ingest coordinates update the graph, Director B's Director reads those updated coordinates on its next cycle. The graph is the messenger. This is the biological model working correctly.

2. Architecture Overview
2.1 Full System Diagram
┌──────────────────────────────────────────────────────────────────────┐
│                          IRIS APPLICATION                             │
│                                                                       │
│  Frontend (Electron / Web)                                            │
│       │  WebSocket JSON — protocol NEVER changes                      │
│       ▼                                                               │
│  ┌───────────────────────────────────────────────────────────────┐   │
│  │                    SwarmBridge (§11)                          │   │
│  │        Translates WS messages ↔ TaskMessage objects           │   │
│  └──────────────────────────┬────────────────────────────────────┘   │
│                             │                                         │
│              ┌──────────────▼──────────────┐                         │
│              │       PrimaryNode (§6)       │  ← replaces AgentKernel │
│              │   1. mode detection          │  ← NEW v9.0             │
│              │   2. context assembly        │                         │
│              │   3. ask user (if needed)    │  ← NEW v9.0             │
│              │   4. Director A plans        │                         │
│              │   5. Leading DER executes    │  ← NEW v9.0             │
│              │   6. Trailing DER crystallizes│ ← NEW v9.0             │
│              │   7. store episode           │                         │
│              └──────────────┬──────────────┘                         │
│                             │                                         │
│         ┌───────────────────┼───────────────────┐                    │
│         │                   │                   │                    │
│  ┌──────▼──────┐   ┌────────▼────────┐  ┌──────▼──────┐            │
│  │ Leading DER │   │  Trailing DER   │  │  Spec Engine│            │
│  │ Director A  │   │  Director B     │  │  (SPEC mode)│            │
│  │ Explorer A  │   │  Explorer B     │  └─────────────┘            │
│  │ Reviewer A  │   │  Reviewer B     │                              │
│  └──────┬──────┘   └────────┬────────┘                              │
│         │                   │                                         │
│         └─────────┬─────────┘                                        │
│                   │ both read/write                                   │
│         ┌─────────▼─────────┐                                        │
│         │  Mycelium Graph   │  ← shared coordinate memory            │
│         │  (§10)            │  ← synchronization layer               │
│         └───────────────────┘                                        │
│                                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐   │
│  │ SkillsLoader │  │  ToolBridge  │  │     MemoryInterface     │   │
│  │  (§12)       │  │  (unchanged) │  │     (3 tiers — §14)     │   │
│  └──────────────┘  └──────────────┘  └─────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
         │  Tailscale WireGuard mesh (§18) / ZeroMQ
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          TORUS NETWORK                                │
│   NetworkCoordinator — peer registry, routing, credit ledger         │
│   Post-quantum identity — Dilithium3 + Kyber + SPHINCS+              │
└──────────────────────────────────────────────────────────────────────┘
2.2 What the Swarm Replaces vs. What It Keeps
Layer	Status	Notes
Frontend (Electron/web)	UNCHANGED	Protocol never changes
WebSocket message protocol	UNCHANGED	All types handled
ToolBridge (MCP + MiniCPM)	UNCHANGED	Called by Explorer
SkillsLoader	EXTENDED	skills/ → tool registry
AgentKernel inference loop	REPLACED	SwarmBridge → PrimaryNode
Models (lfm2-8b, lfm2.5)	REWIRED	Mapped to adapter roles
MemoryInterface	INTEGRATED	Single access boundary respected
Mycelium Layer	INTEGRATED	Shared graph — synchronization layer
2.3 Pool Geometry Change: v8.0 → v9.0
Version	Pool	Why
v8.0	1 brain + 2 parallel workers (3 total)	Parallel execution of independent steps
v9.0	Leading DER + Trailing DER (2 total)	Depth + breadth across all tasks
The v8.0 geometry produced parallel breadth but left depth gaps — steps that were
surface-complete but lacked the detail layers beneath. The v9.0 geometry trades one
parallel worker for a dedicated crystallization loop that fills those depth gaps. For
tasks that genuinely need more parallelism, Torus dispatch handles it — the local pool
stays small and tight.

3. Model Architecture — Three Roles
(Unchanged from v8.0)

The REASONING model is called by both Directors (plan production) and for synthesis.
The EXECUTION model is called by both Explorers (tool execution) and both Reviewers
(step validation). One model loaded, shared across both loops. Inference calls queue
on the single model — no duplication.

Role	Model	Quantisation	Used For
REASONING	lfm2-8b	Q5_K_M	Plan production, strategy, synthesis, judgment
EXECUTION	lfm2.5-1.2b-instruct	Q4_K_M	Tool calls, step reflection, Reviewer validation
COMPRESSION	lfm2.5-1.2b-instruct	Q3_K_M	Context window summarisation only
Latency note for v9.0: The trailing DER loop adds inference calls but they are offset-timed — the trailing loop is 2–3 steps behind, so its inferences run while the leading loop is executing tool calls (which are I/O-bound, not GPU-bound). Net additional GPU time per task is minimal on RTX 4090. On RTX 3060 budget for ~2–4s additional per trailing pass.

3.2 ModelAdapter Interface
python
# src/model/adapter_base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum

class ModelRole(Enum):
    REASONING   = "reasoning"
    EXECUTION   = "execution"
    COMPRESSION = "compression"

@dataclass
class ModelResponse:
    raw_text:        str
    strategy:        Optional[str]
    tool_calls:      List[Dict[str,Any]]
    subtasks:        List[str]
    external_target: Optional[str]
    confidence:      float
    reasoning:       Optional[str]
    tokens_used:     int
    role_used:       ModelRole

class ModelAdapter(ABC):
    @abstractmethod
    def load(self, model_path: str, n_ctx: int, **kwargs) -> None: ...

    @abstractmethod
    def infer(self, prompt: str, role: ModelRole,
              max_tokens: int = 1000, temperature: float = 0.3) -> ModelResponse: ...

    @abstractmethod
    def get_context_size(self, role: ModelRole) -> int: ...

    @abstractmethod
    def count_tokens(self, text: str) -> int: ...

    @property
    @abstractmethod
    def adapter_id(self) -> str: ...
3.3 config/models.json
(Unchanged from v8.0)

4. TaskMessage
(Unchanged from v8.0)

TaskMessage carries two optional fields added in v7.0: execution_plan and assigned_step. Both remain fully backward compatible.

v9.0 addition: TaskMessage carries a loop_role field for audit purposes:

python
# Add to TaskMessage dataclass
loop_role: str = "primary"  # "leading" | "trailing" | "primary"
This field is set by PrimaryNode when dispatching to either DER loop and appears in all audit log events. It is informational only — it does not change routing or permission behavior.

5. Permission System
(Unchanged from v8.0)

ExecutionPlan.to_remote_plan() must be called by NetworkCoordinator.dispatch_to_peer() before attaching any plan to a remote TaskMessage. Personal data never reaches a Torus peer.

6. Two-Brain DER Loop — Core Architecture
6.1 The Geometry
SHARED: one model, one Mycelium graph, one permission system

LEADING DER LOOP (Director A)
  Role: forward execution
  Speed: full speed — advance the queue
  Graph reads: full context package — directives, contracts,
               gradient warnings, causal context, topology
  Graph writes: tool call signals, step outcomes, landmark crystallization
  Knows about trailing loop: NO — reads graph, that's all

TRAILING DER LOOP (Director B)
  Role: depth crystallization
  Speed: TRAILING_GAP_MIN (2) to TRAILING_GAP_MAX (4) steps behind leading loop
  Graph reads: completed step results, expected vs actual delta,
               low-confidence coordinate regions, ambient signals
  Graph writes: gap-filling tool calls, deepened coordinate signals
  Knows about leading loop: only via the graph — no direct communication

COORDINATION: through Mycelium graph only
  When Director A's Explorer completes step 5 and ingests coordinates,
  Director B's Director reads those coordinates on its next cycle.
  No message passing. No shared state outside the graph.
6.2 Gap Distance
python
# src/core/der_constants.py

# Trailing loop gap — how many steps behind the leading loop
TRAILING_GAP_MIN = 2    # trailing loop never works on steps less than this
                        # far behind the leading loop's current position
TRAILING_GAP_MAX = 4    # if trailing loop falls this far behind, it may
                        # skip non-critical gaps to catch up

# Token budgets per mode (replaces DER_MAX_CYCLES from v8.0)
DER_TOKEN_BUDGETS = {
    "spec":       60_000,
    "research":   80_000,
    "implement":  40_000,
    "debug":      30_000,
    "test":       40_000,
    "review":     20_000,
    "default":    40_000,
}

# Emergency brake — cycle count only, should never be reached
DER_EMERGENCY_STOP    = 200

# Reviewer constraints
DER_MAX_VETO_PER_ITEM = 2

# Parallel mode: trailing loop catches up to leading loop when leading is blocked
DER_PARALLEL_GAP = 0    # when leading loop hits a blocker, trailing loop
                        # advances to leading loop's current position
                        # and both run in parallel until blocker resolved

# Write lock timeout
DER_WRITE_LOCK_TIMEOUT = 5.0  # seconds
6.3 When Parallel Mode Activates
The trailing loop runs at GAP distance by default. It enters parallel mode (catches up to the leading loop) in exactly one condition: the leading loop has hit a blocker it cannot resolve within DER_MAX_VETO_PER_ITEM cycles.

Normal operation:
  Leading loop: step 8 (current)
  Trailing loop: step 5-6 (GAP_MIN to GAP_MAX behind)

Blocker condition (leading loop on step 8, vetoed twice):
  Leading loop: step 8 (stuck)
  Trailing loop: advances to step 7 (one step behind)
  → Both work in parallel:
      Leading loop: retries step 8 with alternative approach
      Trailing loop: deepens steps 6-7 to enrich graph context
        for leading loop's retry
  → Once step 8 resolves:
      Trailing loop returns to GAP_MIN distance
The parallel mode is brief and purposeful. It does not persist. The
trailing loop returns to its gap distance immediately after the blocker clears.

6.4 Write Lock for Graph Safety
Both loops write to the Mycelium graph. Writes must be serialized to prevent corruption. A threading lock on the MyceliumInterface connection handles this. Reads are concurrent — only writes are serialized.

python
# In MyceliumInterface.__init__():
import threading
self._write_lock = threading.Lock()
self._write_lock_timeout = DER_WRITE_LOCK_TIMEOUT

# Wrap all _conn.execute() + _conn.commit() pairs:
def _safe_write(self, sql: str, params: tuple = ()) -> None:
    """Thread-safe graph write. Never raises — logs on timeout."""
    acquired = self._write_lock.acquire(timeout=self._write_lock_timeout)
    if not acquired:
        # Log timeout but don't block execution
        return
    try:
        self._conn.execute(sql, params)
        self._conn.commit()
    except Exception:
        pass
    finally:
        self._write_lock.release()
All ingest_tool_call(), record_outcome(), crystallize_landmark(), and record_plan_stats() calls go through _safe_write(). Read methods (get_context_path(), is_mature(), etc.) continue to use _conn directly — no lock needed for reads.

7. DER Loop Internals — Director · Explorer · Reviewer
7.1 Three Roles, One Model
DIRECTOR  (REASONING model, _plan_task / _crystallize_task)
  Leading:  "What's next in the plan?"
  Trailing: "What's incomplete in what was just built?"
  Both:     Re-reads Mycelium graph before every broadcast
  Neither:  Executes a tool. Reviews a step.

REVIEWER  (EXECUTION model, Reviewer class)
  Validates next queue item before Explorer sees it
  Checks: gradient warnings, active contracts, cross-step coherence
  Returns: PASS / REFINE / VETO
  Falls back to PASS on any failure — never blocks Explorer
  Temperature: 0.0 — deterministic

EXPLORER  (EXECUTION model, _dispatch_tool)
  Executes one approved step
  Returns result to Mycelium immediately via ingest_tool_call()
  Never plans. Never reviews.
7.2 DirectorQueue and QueueItem
python
# src/core/der_loop.py
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set
from enum import Enum
import threading


class ReviewVerdict(Enum):
    PASS   = "pass"
    REFINE = "refine"
    VETO   = "veto"


class LoopRole(Enum):
    LEADING  = "leading"
    TRAILING = "trailing"


@dataclass
class QueueItem:
    step_id: str
    step_number: int
    description: str
    tool: Optional[str]                = None
    params: Dict[str, Any]             = field(default_factory=dict)
    depends_on: List[str]              = field(default_factory=list)
    critical: bool                     = True
    objective_anchor: str              = ""
    coordinate_signal: str             = ""
    veto_count: int                    = 0
    refined_description: Optional[str] = None
    # Trailing loop fields
    gap_analysis: Optional[str]        = None   # what trailing Director found missing
    depth_layer: int                   = 0      # 0=surface, 1=first layer, 2=deeper


@dataclass
class DirectorQueue:
    """
    The Director's live broadcast queue.
    Leading queue: initialized from ExecutionPlan.steps, updated as Explorer feeds back.
    Trailing queue: initialized from completed steps, populated by gap analysis.
    """
    objective: str
    loop_role: LoopRole
    items: List[QueueItem]             = field(default_factory=list)
    completed_ids: List[str]           = field(default_factory=list)
    vetoed_ids: List[str]              = field(default_factory=list)
    cycle_count: int                   = 0
    max_cycles: int                    = 200    # DER_EMERGENCY_STOP
    max_veto_per_item: int             = 2
    # Trailing loop state
    leading_position: int              = 0      # step number leading loop is on
    gap_min: int                       = 2      # TRAILING_GAP_MIN
    gap_max: int                       = 4      # TRAILING_GAP_MAX

    def next_ready(self) -> Optional[QueueItem]:
        completed = set(self.completed_ids)
        for item in self.items:
            if item.step_id in self.completed_ids: continue
            if item.step_id in self.vetoed_ids: continue
            if all(dep in completed for dep in item.depends_on):
                return item
        return None

    def mark_complete(self, step_id: str) -> None:
        if step_id not in self.completed_ids:
            self.completed_ids.append(step_id)

    def mark_vetoed(self, step_id: str) -> None:
        if step_id not in self.vetoed_ids:
            self.vetoed_ids.append(step_id)

    def add_item(self, item: QueueItem) -> None:
        self.items.append(item)

    def is_complete(self) -> bool:
        active = [i for i in self.items if i.step_id not in self.vetoed_ids]
        return all(i.step_id in self.completed_ids for i in active)

    def hit_cycle_limit(self) -> bool:
        return self.cycle_count >= self.max_cycles

    def within_gap(self, step_number: int) -> bool:
        """
        Trailing loop: is this step within the allowed gap distance?
        Returns True if the step is safe to work on (not too close to leading loop).
        """
        if self.loop_role == LoopRole.LEADING:
            return True  # leading loop has no gap constraint
        distance = self.leading_position - step_number
        return distance >= self.gap_min
7.3 Reviewer
python
# src/core/der_loop.py (continued)

class Reviewer:
    """
    Validates Director queue items before Explorer executes them.
    One model, one Reviewer class — used by both leading and trailing loops.
    Temperature 0.0 — deterministic validation.
    Falls back to PASS on any failure — never blocks Explorer.
    """
    REVIEWER_MAX_TOKENS  = 200
    REVIEWER_TEMPERATURE = 0.0

    def __init__(self, adapter, memory_interface):
        self.adapter = adapter
        self.memory  = memory_interface

    def review(
        self,
        item: QueueItem,
        completed_steps: List[QueueItem],
        context_package,
        is_mature: bool,
        loop_role: LoopRole = LoopRole.LEADING
    ) -> tuple:
        """
        Returns (ReviewVerdict, output: str | None).
        Never raises. Falls back to (PASS, None) on any error.
        """
        try:
            if not is_mature or not hasattr(context_package, 'gradient_warnings'):
                return ReviewVerdict.PASS, None

            prompt = self._build_review_prompt(
                item=item,
                completed_steps=completed_steps,
                gradient_warnings=context_package.gradient_warnings or "",
                active_contracts=context_package.active_contracts or "",
                loop_role=loop_role
            )

            response = self.adapter.infer(
                prompt, role=ModelRole.EXECUTION,
                max_tokens=self.REVIEWER_MAX_TOKENS,
                temperature=self.REVIEWER_TEMPERATURE
            )
            return self._parse_verdict(response.raw_text)

        except Exception:
            return ReviewVerdict.PASS, None

    def _build_review_prompt(
        self, item, completed_steps, gradient_warnings,
        active_contracts, loop_role
    ) -> str:
        completed_summary = "\n".join(
            f"- Step {s.step_number}: {s.description} [done]"
            for s in completed_steps[-3:]
        ) or "None"

        role_context = (
            "You are reviewing a crystallization step. Focus on depth gaps "
            "and missing detail layers, not forward progress."
            if loop_role == LoopRole.TRAILING
            else
            "You are reviewing an execution step. Focus on safety and coherence."
        )

        return (
            f"OBJECTIVE: {item.objective_anchor}\n\n"
            f"ROLE: {role_context}\n\n"
            f"COMPLETED STEPS (last 3):\n{completed_summary}\n\n"
            f"GRADIENT WARNINGS:\n{gradient_warnings[:200] or 'None'}\n\n"
            f"ACTIVE CONTRACTS:\n{active_contracts[:200] or 'None'}\n\n"
            f"STEP TO REVIEW:\n"
            f"  Step {item.step_number}: {item.description}\n"
            f"  Tool: {item.tool or 'none'}\n\n"
            "Does this step conflict with a gradient warning or contract?\n"
            "Does it contradict what was already completed?\n\n"
            "JSON only:\n"
            '{"verdict":"pass|refine|veto","reason":"","refined":""}'
        )

    def _parse_verdict(self, raw: str) -> tuple:
        import re, json
        try:
            m = re.search(r'\{[\s\S]+?\}', raw)
            if not m: return ReviewVerdict.PASS, None
            data    = json.loads(m.group())
            v       = data.get("verdict", "pass").lower()
            reason  = data.get("reason", "") or None
            refined = data.get("refined", "") or None
            if v == "veto":   return ReviewVerdict.VETO, reason
            if v == "refine" and refined: return ReviewVerdict.REFINE, refined
            return ReviewVerdict.PASS, None
        except Exception:
            return ReviewVerdict.PASS, None
7.4 ExecutionPlan and PlanStep
(Unchanged from v8.0 with one addition to to_context_string())

Add HZA address headers and ASCII-safe markers:

python
def to_context_string(self) -> str:
    """
    Injected into task_anchor zone of the context window.
    HZA addresses make each step directly navigable.
    ASCII-safe markers prevent encoding errors.
    """
    markers = {
        StepStatus.PENDING:   "[ ]",
        StepStatus.RUNNING:   "[~]",
        StepStatus.COMPLETED: "[+]",   # ASCII safe — not Unicode
        StepStatus.FAILED:    "[x]",
        StepStatus.SKIPPED:   "[s]",
        StepStatus.BLOCKED:   "[b]",
    }
    lines = [
        f"[system://plan/{self.plan_id[:8]}]",   # HZA address
        f"EXECUTION PLAN [{self.plan_id[:8]}]",
        f"Task: {self.original_task}",
        f"Strategy: {self.strategy}",
        f"Reasoning: {self.reasoning}", "", "Steps:"
    ]
    for step in self.steps:
        dep_str = (f" (after: {', '.join(step.depends_on)})"
                   if step.depends_on else "")
        lines.append(
            f"  [system://plan/{self.plan_id[:8]}/step/{step.step_id}]"
        )
        lines.append(
            f"  {markers.get(step.status,'[ ]')} "
            f"Step {step.step_number}: {step.description}{dep_str}"
        )
        if step.status == StepStatus.COMPLETED and step.result:
            lines.append(f"      Result: {str(step.result)[:100]}")
        if step.status == StepStatus.FAILED:
            lines.append(f"      Failed: {step.failure_reason}")
    return "\n".join(lines)
8. Trailing Crystallizer — Director B
8.1 What It Does
The trailing crystallizer is Director B's DER loop. It follows Director A's leading loop at a gap of TRAILING_GAP_MIN to TRAILING_GAP_MAX steps.

For each completed step in the leading loop's wake, Director B asks: "Is this actually done to the depth it needs to be?"

If yes — advance to the next completed step.
If no — build a gap-filling queue and execute it before advancing.

8.2 Gap Analysis
The trailing Director receives a different context package than the leading Director:

python
# src/core/trailing_director.py

class TrailingDirector:
    """
    Director B for the trailing crystallizer DER loop.
    Reads completed step results and finds depth gaps.
    Never races with the leading loop — always stays at gap distance.
    """

    GAP_ANALYSIS_PROMPT = """
OBJECTIVE: {objective}

COMPLETED STEP:
  Step {step_number}: {description}
  Expected output: {expected_output}
  Actual result: {actual_result}

GRAPH STATE (coordinate confidence after this step):
{graph_state}

KNOWN FAILURE PATTERNS:
{gradient_warnings}

DEPTH ANALYSIS:
Look at the gap between what was planned and what was actually built.
What detail layers exist beneath the surface that were not addressed?
Consider: edge cases, error handling, integration coherence with adjacent steps,
missing validation, incomplete state management, untested paths.

If nothing is missing: return empty gap_items list.
If gaps exist: return specific, actionable gap-filling steps.
Maximum 3 gap-filling steps per completed step — focus on highest impact.

JSON only:
{
  "has_gaps": true|false,
  "confidence": 0.0-1.0,
  "gap_items": [
    {
      "description": "specific gap-filling action",
      "tool": "tool_name or null",
      "params": {},
      "depth_layer": 1
    }
  ]
}
"""

    def __init__(self, adapter, memory_interface):
        self.adapter = adapter
        self.memory  = memory_interface

    def analyze_gaps(
        self,
        completed_step,      # PlanStep that leading loop just completed
        plan,                # full ExecutionPlan for context
        context_package,     # current Mycelium context package
        is_mature: bool
    ) -> List[QueueItem]:
        """
        Analyze a completed step for depth gaps.
        Returns list of gap-filling QueueItems (may be empty).
        Never raises.
        """
        try:
            graph_state = ""
            gradient_warnings = ""
            if is_mature and context_package is not None:
                try:
                    graph_state = context_package.mycelium_path or ""
                    gradient_warnings = context_package.gradient_warnings or ""
                except Exception:
                    pass

            prompt = self.GAP_ANALYSIS_PROMPT.format(
                objective=plan.original_task,
                step_number=completed_step.step_number,
                description=completed_step.description,
                expected_output=completed_step.expected_output or "not specified",
                actual_result=str(completed_step.result)[:300] if completed_step.result else "no result",
                graph_state=graph_state[:300],
                gradient_warnings=gradient_warnings[:200] or "None"
            )

            response = self.adapter.infer(
                prompt,
                role=ModelRole.REASONING,
                max_tokens=800,
                temperature=0.1
            )

            return self._parse_gap_items(
                response.raw_text,
                completed_step,
                plan.original_task
            )

        except Exception:
            return []   # empty gap list — trailing loop advances without action

    def _parse_gap_items(
        self, raw: str, step, objective: str
    ) -> List[QueueItem]:
        import re, json
        try:
            m = re.search(r'\{[\s\S]+\}', raw)
            if not m: return []
            data = json.loads(m.group())
            if not data.get("has_gaps", False): return []

            items = []
            for i, g in enumerate(data.get("gap_items", [])[:3]):
                items.append(QueueItem(
                    step_id=f"gap-{step.step_id}-{i}",
                    step_number=step.step_number,
                    description=g.get("description", ""),
                    tool=g.get("tool"),
                    params=g.get("params", {}),
                    critical=False,         # gap items are never critical
                    objective_anchor=objective,
                    depth_layer=g.get("depth_layer", 1),
                    gap_analysis=f"Gap in step {step.step_number}"
                ))
            return items
        except Exception:
            return []
8.3 _execute_plan_trailing()
python
# In PrimaryNode (src/core/primary_node.py)

def _execute_plan_trailing(
    self,
    plan: ExecutionPlan,
    leading_queue: DirectorQueue,
    context_package,
    is_mature: bool,
    session_id: str,
    agent_mode: str
) -> None:
    """
    Trailing DER loop — runs in a background thread alongside the leading loop.
    Never blocks the leading loop. Never raises beyond this method.
    Finds and fills depth gaps in completed steps.
    Returns when leading loop is complete or token budget exhausted.
    """
    import time
    from backend.agent.der_loop import DirectorQueue, QueueItem, ReviewVerdict, LoopRole

    trailing_director = TrailingDirector(
        adapter=self.adapter,
        memory_interface=self.memory
    )
    reviewer = Reviewer(
        adapter=self.adapter,
        memory_interface=self.memory
    )

    trailing_queue = DirectorQueue(
        objective=plan.original_task,
        loop_role=LoopRole.TRAILING,
        gap_min=TRAILING_GAP_MIN,
        gap_max=TRAILING_GAP_MAX
    )

    current_token_budget = DER_TOKEN_BUDGETS.get(agent_mode, DER_TOKEN_BUDGETS["default"])
    tokens_used = 0
    processed_step_ids: Set[str] = set()

    while (
        not leading_queue.is_complete()
        and trailing_queue.cycle_count < DER_EMERGENCY_STOP
        and tokens_used < current_token_budget
    ):
        trailing_queue.cycle_count += 1
        time.sleep(0.05)  # brief yield — don't starve leading loop

        # Find completed steps that trailing loop hasn't processed yet
        for plan_step in plan.steps:
            if plan_step.step_id in processed_step_ids:
                continue
            if plan_step.status != StepStatus.COMPLETED:
                continue
            # Check gap constraint — only work on steps far enough behind leading
            if not trailing_queue.within_gap(plan_step.step_number):
                continue

            # Mark as being processed
            processed_step_ids.add(plan_step.step_id)

            # Re-read graph — trailing Director always has fresh coordinates
            try:
                updated_pkg, updated_mature = \
                    self.memory.get_task_context_package(
                        task=plan.original_task, session_id=session_id
                    )
                if updated_mature:
                    context_package = updated_pkg
                    is_mature = True
            except Exception:
                pass

            # Gap analysis
            gap_items = trailing_director.analyze_gaps(
                completed_step=plan_step,
                plan=plan,
                context_package=context_package,
                is_mature=is_mature
            )

            if not gap_items:
                continue  # nothing missing — advance

            # Execute gap-filling items through Reviewer → Explorer
            for gap_item in gap_items:
                verdict, reviewer_output = reviewer.review(
                    item=gap_item,
                    completed_steps=[],
                    context_package=context_package,
                    is_mature=is_mature,
                    loop_role=LoopRole.TRAILING
                )

                if verdict == ReviewVerdict.VETO:
                    continue  # skip vetoed gap items — they're non-critical

                if verdict == ReviewVerdict.REFINE and reviewer_output:
                    gap_item.refined_description = reviewer_output

                # Explorer executes gap fill
                if gap_item.tool:
                    try:
                        description = gap_item.refined_description or gap_item.description
                        result = self._dispatch_tool(
                            {"tool": gap_item.tool, "params": gap_item.params},
                            self._token
                        )

                        # Ingest into Mycelium — this is the crystallization
                        try:
                            self.memory.mycelium_ingest_tool_call(
                                tool_name=gap_item.tool,
                                success=result.get("status") == "success",
                                sequence_position=gap_item.step_number,
                                total_steps=len(plan.steps),
                                session_id=session_id
                            )
                        except Exception:
                            pass

                        tokens_used += 50  # approximate — gap fills are small

                        self.audit.log("TRAILING_GAP_FILLED", {
                            "step_id": plan_step.step_id,
                            "gap_description": description[:100],
                            "depth_layer": gap_item.depth_layer,
                            "tool": gap_item.tool
                        })

                    except Exception:
                        pass  # trailing loop never blocks on its own errors

        tokens_used = sum(s.tokens_used for s in plan.steps)

    self.audit.log("TRAILING_LOOP_COMPLETE", {
        "plan_id": plan.plan_id,
        "cycles": trailing_queue.cycle_count,
        "steps_processed": len(processed_step_ids)
    })
8.4 Running Both Loops
python
# In PrimaryNode._execute_plan_der() — the main execution method

import threading

def _execute_plan_der(
    self, msg, plan, context_package, is_mature, task_class, session_id, agent_mode
) -> dict:
    """
    Leading DER loop runs in the main thread.
    Trailing DER loop runs in a background thread — never blocks leading.
    Both feed the same Mycelium graph.
    """
    # Start trailing loop in background thread
    trailing_thread = threading.Thread(
        target=self._execute_plan_trailing,
        args=(plan, leading_queue, context_package,
              is_mature, session_id, agent_mode),
        daemon=True    # daemon — trailing loop exits if main thread exits
    )
    trailing_thread.start()

    # Leading loop runs in main thread (full DER loop logic)
    result = self._run_leading_loop(
        msg=msg, plan=plan,
        context_package=context_package,
        is_mature=is_mature,
        session_id=session_id,
        agent_mode=agent_mode
    )

    # Wait for trailing loop to finish (with timeout)
    trailing_thread.join(timeout=30)  # trailing loop gets 30s after leading completes

    return result
9. Mode System — Director Intelligence
9.1 Six Modes
The Director detects operating mode before planning. Slash commands are deterministic
overrides. Inference is keyword-based with Mycelium context weighting.

Mode	Triggers	Token Budget	Graph Priority
/spec	design, plan, architect	60,000	topology → contracts
/research	find out, compare, explore	80,000	ambient signals → concentration field
/implement	build, code, create	40,000	full context package
/debug	fix, broken, error	30,000	gradient warnings FIRST
/test	write tests, verify	40,000	contracts + causal context
/review	review, check, critique	20,000	gradient warnings + failures
9.2 ModeDetector
python
# src/core/mode_detector.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class AgentMode(Enum):
    SPEC      = "spec"
    RESEARCH  = "research"
    IMPLEMENT = "implement"
    DEBUG     = "debug"
    TEST      = "test"
    REVIEW    = "review"


class ComplexityLevel(Enum):
    SIMPLE  = "simple"
    COMPLEX = "complex"
    UNKNOWN = "unknown"


@dataclass
class ModeResult:
    mode: AgentMode
    complexity: ComplexityLevel
    needs_clarification: bool
    trigger: str        # "slash_command" | "inference" | "default"
    confidence: float


class ModeDetector:
    SLASH_COMMANDS = {
        "/spec":       AgentMode.SPEC,
        "/research":   AgentMode.RESEARCH,
        "/implement":  AgentMode.IMPLEMENT,
        "/debug":      AgentMode.DEBUG,
        "/test":       AgentMode.TEST,
        "/review":     AgentMode.REVIEW,
        "/ask":        None,
    }

    MODE_KEYWORDS = {
        AgentMode.SPEC:      ["design", "plan", "architect", "spec", "blueprint", "structure"],
        AgentMode.RESEARCH:  ["research", "find out", "compare", "investigate", "explore options"],
        AgentMode.DEBUG:     ["fix", "broken", "error", "not working", "failing", "exception"],
        AgentMode.TEST:      ["write tests", "test coverage", "verify", "add tests"],
        AgentMode.REVIEW:    ["review", "check my", "is this correct", "critique"],
        AgentMode.IMPLEMENT: ["build", "code", "create", "write", "add", "implement"],
    }

    COMPLEXITY_SIMPLE  = ["small", "quick", "minor", "simple", "just", "tweak"]
    COMPLEXITY_COMPLEX = ["system", "architecture", "full", "from scratch", "redesign"]

    def detect(self, task: str, context_package=None, is_mature: bool = False) -> ModeResult:
        try:
            task_lower = task.lower().strip()

            # Slash command — deterministic
            for cmd, mode in self.SLASH_COMMANDS.items():
                if task_lower.startswith(cmd):
                    if cmd == "/ask":
                        return ModeResult(AgentMode.IMPLEMENT, ComplexityLevel.UNKNOWN,
                                         True, "slash_command", 1.0)
                    return ModeResult(mode, self._detect_complexity(task_lower),
                                     False, "slash_command", 1.0)

            mode, conf = self._infer_mode(task_lower)
            complexity  = self._detect_complexity(task_lower)
            needs_ask   = (
                (mode == AgentMode.SPEC and complexity == ComplexityLevel.UNKNOWN)
                or (conf < 0.5 and len(task.split()) > 15)
            )

            # Suppress ask if graph already knows
            if needs_ask and is_mature and context_package is not None:
                try:
                    if (context_package.topology_primitive not in ("unknown", "")
                            or context_package.tier1_directives):
                        needs_ask = False
                except Exception:
                    pass

            return ModeResult(mode, complexity, needs_ask, "inference", conf)

        except Exception:
            return ModeResult(AgentMode.IMPLEMENT, ComplexityLevel.UNKNOWN, False, "default", 0.0)

    def strip_command(self, task: str) -> str:
        """Remove slash command prefix from task string."""
        for cmd in self.SLASH_COMMANDS:
            if task.lower().strip().startswith(cmd):
                return task.strip()[len(cmd):].strip()
        return task

    def _infer_mode(self, task_lower: str) -> Tuple[AgentMode, float]:
        scores = {mode: 0 for mode in AgentMode}
        for mode, keywords in self.MODE_KEYWORDS.items():
            for kw in keywords:
                if kw in task_lower:
                    scores[mode] += 1
        total = sum(scores.values())
        if total == 0:
            return AgentMode.IMPLEMENT, 0.3
        best = max(scores, key=scores.get)
        conf = min(scores[best] / max(total, 1) + 0.3, 1.0)
        return best, conf

    def _detect_complexity(self, task_lower: str) -> ComplexityLevel:
        s = sum(1 for kw in self.COMPLEXITY_SIMPLE if kw in task_lower)
        c = sum(1 for kw in self.COMPLEXITY_COMPLEX if kw in task_lower)
        if c > s: return ComplexityLevel.COMPLEX
        if s > c: return ComplexityLevel.SIMPLE
        return ComplexityLevel.UNKNOWN
9.3 Ask User Tool
When the Director needs context that the Mycelium graph doesn't have, it surfaces structured questions to the user. All questions at once. One round trip. Every answer ingested as a Mycelium coordinate signal at confidence=0.6.

python
# src/core/ask_user_tool.py

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import json, re


@dataclass
class AskQuestion:
    id: str
    text: str
    type: str           # "single_select" | "multi_select" | "free_text"
    options: List[str]  = field(default_factory=list)
    required: bool      = True


@dataclass
class AskPayload:
    questions: List[AskQuestion]
    context: str


class AskUserTool:
    """
    Structured clarification tool for the Director.
    Maximum 3 questions per ask. One round trip per session.
    Every answer ingested into Mycelium at confidence 0.6.
    Returns None when model has enough context — no unnecessary asks.
    Never raises.
    """

    def __init__(self, adapter, memory_interface):
        self.adapter = adapter
        self.memory  = memory_interface

    def build_questions(self, task, mode, context_package, is_mature) -> Optional[AskPayload]:
        try:
            known = ""
            if is_mature and context_package is not None:
                try:
                    known = (
                        f"KNOWN: topology={context_package.topology_primitive}, "
                        f"directives={context_package.tier1_directives[:100]}"
                    )
                except Exception:
                    pass

            prompt = (
                f"TASK: {task}\nMODE: {mode}\n{known}\n\n"
                "What information is missing that would significantly change your plan?\n"
                "Max 3 questions. Don't ask what is already known.\n"
                "Return empty list if you have enough.\n"
                '{"context":"why","questions":[{"id":"q1","text":"?","type":"single_select","options":["a","b"]}]}'
            )

            r = self.adapter.infer(prompt, role=ModelRole.REASONING,
                                   max_tokens=400, temperature=0.1)
            return self._parse(r.raw_text)
        except Exception:
            return None

    def ingest_answers(self, answers: Dict[str, str],
                       questions: List[AskQuestion], session_id: str) -> None:
        try:
            for q in questions:
                answer = answers.get(q.id)
                if not answer: continue
                try:
                    self.memory.mycelium_ingest_statement(
                        statement=f"{q.text}: {answer}",
                        session_id=session_id
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def _parse(self, raw: str) -> Optional[AskPayload]:
        try:
            m = re.search(r'\{[\s\S]+\}', raw)
            if not m: return None
            data = json.loads(m.group())
            qs = data.get("questions", [])
            if not qs: return None
            return AskPayload(
                questions=[
                    AskQuestion(
                        id=q.get("id", f"q{i}"), text=q.get("text", ""),
                        type=q.get("type", "single_select"),
                        options=q.get("options", [])
                    )
                    for i, q in enumerate(qs[:3])
                ],
                context=data.get("context", "")
            )
        except Exception:
            return None
9.4 Spec Engine
When mode is SPEC, the Spec Engine produces output instead of the DER loop executing.

python
# src/core/spec_engine.py

from dataclasses import dataclass
from typing import Optional


@dataclass
class SpecOutput:
    title: str
    is_complex: bool
    single_doc: Optional[str]       = None
    design_doc: Optional[str]       = None
    requirements_doc: Optional[str] = None
    tasks_doc: Optional[str]        = None


class SpecEngine:
    """
    Produces spec documents for SPEC mode tasks.
    Simple tasks → single lightweight doc.
    Complex tasks → full three-doc set (design + requirements + tasks).
    Depth calibrated to topology_primitive from Mycelium.
    Never raises.
    """

    DEPTH_BY_TOPOLOGY = {
        "core":        "lean",
        "acquisition": "detailed",
        "exploration": "bridged",
        "orbit":       "detailed",
        "transfer":    "standard",
        "evolution":   "lean",
        "unknown":     "standard",
    }

    def __init__(self, adapter, memory_interface):
        self.adapter = adapter
        self.memory  = memory_interface

    def produce(self, task, is_complex, context_package, is_mature, session_id) -> SpecOutput:
        try:
            topology = "unknown"
            if is_mature and context_package is not None:
                try: topology = context_package.topology_primitive
                except Exception: pass

            depth = self.DEPTH_BY_TOPOLOGY.get(topology, "standard")
            title = " ".join(task.strip().split()[:6]).title()
            ctx   = ""
            if is_mature and context_package is not None:
                try: ctx = f"CONTEXT:\n{context_package.get_system_zone_content()[:400]}\n\n"
                except Exception: pass

            if is_complex:
                return self._complex(task, title, depth, ctx)
            return self._simple(task, title, depth, ctx)
        except Exception:
            return SpecOutput(title=task[:60], is_complex=is_complex)

    def _simple(self, task, title, depth, ctx) -> SpecOutput:
        depth_inst = {"lean": "Expert audience. Be concise.",
                      "detailed": "Include reasoning and alternatives.",
                      "bridged": "Connect theory to practice.",
                      "standard": "Clear and complete."}[depth]
        r = self.adapter.infer(
            f"{ctx}TASK: {task}\n{depth_inst}\n"
            "Produce a concise feature spec:\n"
            f"# Feature: {title}\n## What it does\n"
            "## How it fits existing system\n## Implementation steps\n## What NOT to change",
            role=ModelRole.REASONING, max_tokens=2000, temperature=0.1
        )
        return SpecOutput(title=title, is_complex=False, single_doc=r.raw_text)

    def _complex(self, task, title, depth, ctx) -> SpecOutput:
        base = f"{ctx}TASK: {task}\nAudience depth: {depth}.\n"
        design = self.adapter.infer(
            base + f"Produce design.md for: {title}. "
            "Include: overview, file map, architecture, data models, API changes, "
            "sequence diagrams, error handling, what does NOT change. "
            "Follow IRIS spec format.",
            role=ModelRole.REASONING, max_tokens=3000, temperature=0.1
        ).raw_text
        reqs = self.adapter.infer(
            base + f"Produce requirements.md for: {title}. "
            "User stories + THE SYSTEM SHALL acceptance criteria. "
            "Include non-requirements section.",
            role=ModelRole.REASONING, max_tokens=3000, temperature=0.1
        ).raw_text
        tasks = self.adapter.infer(
            base + f"Produce tasks.md for: {title}. "
            "Phased implementation plan. Each task: file, what to add, "
            "key rules, verification snippet. Final checklist.",
            role=ModelRole.REASONING, max_tokens=3000, temperature=0.1
        ).raw_text
        return SpecOutput(title=title, is_complex=True,
                         design_doc=design, requirements_doc=reqs, tasks_doc=tasks)
10. Mycelium Integration — Shared Graph
10.1 The Shared Graph Contract
Both DER loops share one Mycelium graph. This is the synchronization layer.
The following rules govern all Mycelium access in the two-brain architecture:

Reads are concurrent. Both loops may call get_context_path(), is_mature(), and all read methods simultaneously. No lock needed for reads.
Writes are serialized. All ingest_*, record_*, crystallize_*, and clear_* calls go through _safe_write() with the write lock. No exceptions.
Leading loop writes take priority. If both loops attempt to write simultaneously, the write lock serializes them FIFO. The leading loop's writes are not prioritized programmatically — the operating system schedules them. This is correct.
Trailing loop writes are always non-critical. All trailing loop write calls are wrapped in try/except pass. A trailing write that fails silently is acceptable. A leading write that fails is also wrapped — neither loop blocks on Mycelium failure.
The graph is the only shared state. No shared queues, no shared step registries, no direct communication between Director A and Director B. Only the graph.
10.2 Context Package Assembly
When the Director re-reads the graph on each cycle, it receives a ContextPackage containing the five Pacman fragmentation dimensions:

Dimension 1: ZONE        — which membrane delivered this content
Dimension 2: TIER        — how deep it's metabolized
Dimension 3: ADDRESS     — HZA navigable location
Dimension 4: PRIORITY    — biological reasoning order
Dimension 5: CONCENTRATION — ambient field awareness
The leading Director reads the full package. The trailing Director's package is
enriched with the completed step's actual result and the delta between expected
and actual — this is the gap analysis input.

10.3 Pacman Cost Curve in Two-Brain Context
The trailing loop doubles the number of Mycelium read cycles per session.
This is intentional and beneficial. More cycles means more coordinate signals,
faster landmark crystallization, and a richer graph for the next session.

Session 1-10:   graph immature — trailing loop analyzes gaps but graph has less to offer
Session 50+:    gradient warnings start catching trailing loop's gap attempts
                 (known failures prevent redundant gap analysis)
Session 100+:   behavioral contracts guide both loops simultaneously
                 trailing loop gap rate drops as leading loop improves from
                 richer context — the compounding cost curve applies to both
The trailing loop accelerates Mycelium maturation. Twice the signals per session
means the graph reaches the 90%+ confidence threshold faster.

11. SwarmBridge
(Unchanged from v8.0)

SwarmBridge translates WebSocket messages to TaskMessages. Nothing in SwarmBridge
changes for the two-brain architecture. The bridge hands tasks to PrimaryNode.
PrimaryNode handles loop routing internally.

12–17. Unchanged Sections
(SkillsLoader Integration, Checkpoint-Based Recovery, Three-Tier Memory, Safety System, Docker Executor, Voice Pipeline — all unchanged from v8.0)

Checkpoint note for v9.0: CheckpointManager.add_step() distinguishes leading vs trailing loop steps via the loop_role field in the step dict:

python
self.checkpoint.add_step(
    msg.task_id,
    {"step_id": step.step_id, "tool": step.tool,
     "params": step.params, "loop_role": "leading"},  # or "trailing"
    step.result
)
On recovery, leading loop steps are replayed first. Trailing loop gap-fills
are replayed only if the leading step they were filling is also in the
checkpoint. This prevents ghost gap-fills for steps that were re-executed.

18. Torus Network
(Unchanged from v8.0 with one addition)

Two-brain Torus dispatch: When a task exceeds local capacity and delegate_external is chosen, the Planner dispatches to a Torus peer. The remote node runs a single DER loop (leading only — no trailing crystallizer for remote dispatch). The remote worker receives the coordinate path from Mycelium — not the full prose context. When the remote result comes back, the local trailing loop analyses the remote step for gaps just as it would a local step.

plan.to_remote_plan() must still be called before any remote dispatch. Context_snapshot is stripped. Sensitive param keys are stripped. Personal data never reaches a Torus peer.

19. File Structure
iris/
├── config/
│   ├── models.json
│   ├── permissions.json
│   ├── memory.json
│   ├── settings.json
│   ├── channels.json
│   └── external_models.json
│
├── models/
│   ├── lfm2-8b-Q5_K_M.gguf
│   ├── lfm2.5-1.2b-instruct-Q4_K_M.gguf
│   └── lfm2.5-1.2b-instruct-Q3_K_M.gguf
│
├── skills/
│   └── skill-name/SKILL.md
│
├── src/
│   ├── model/
│   │   ├── adapter_base.py
│   │   ├── registry.py
│   │   └── adapters/lfm_adapter.py
│   │
│   ├── core/
│   │   ├── primary_node.py           # Updated v9.0 — two-brain routing
│   │   ├── worker_pool.py            # Simplified — no preloaded workers
│   │   ├── worker_executor.py        # Preserved — Torus remote execution
│   │   ├── docker_worker.py
│   │   ├── task_message.py           # Updated v9.0 — loop_role field added
│   │   ├── message_bus.py
│   │   ├── intent_gate.py
│   │   ├── checkpoint.py             # Updated v9.0 — loop_role in step dict
│   │   ├── recovery_monitor.py
│   │   ├── execution_plan.py         # Updated v9.0 — HZA headers, ASCII markers
│   │   ├── planner.py                # Updated v9.0 — mode-aware planning
│   │   ├── der_loop.py               # NEW v9.0 — DirectorQueue, Reviewer, QueueItem
│   │   ├── der_constants.py          # NEW v9.0 — all DER constants
│   │   ├── trailing_director.py      # NEW v9.0 — Director B, gap analysis
│   │   ├── mode_detector.py          # NEW v9.0 — AgentMode, ModeDetector
│   │   ├── ask_user_tool.py          # NEW v9.0 — AskUserTool
│   │   └── spec_engine.py            # NEW v9.0 — SpecEngine
│   │
│   ├── bridge/
│   │   ├── swarm_bridge.py
│   │   ├── skills_swarm_bridge.py
│   │   └── tool_bridge.py
│   │
│   ├── network/
│   │   ├── coordinator.py            # to_remote_plan() required before dispatch
│   │   ├── peer_client.py
│   │   └── peer_server.py
│   │
│   ├── channels/
│   │   ├── base.py
│   │   ├── telegram.py
│   │   ├── discord_chat.py
│   │   └── whatsapp.py
│   │
│   ├── permissions/
│   │   ├── token.py
│   │   └── manager.py
│   │
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── interface.py              # Updated v9.0 — write lock, proxy methods
│   │   ├── working.py
│   │   ├── episodic.py
│   │   ├── semantic.py
│   │   ├── embedding.py
│   │   ├── db.py                     # Updated v9.0 — mycelium_plan_stats table
│   │   ├── distillation.py
│   │   └── skills.py
│   │
│   ├── memory/mycelium/
│   │   ├── interface.py              # Updated v9.0 — write lock, ContextPackage,
│   │   │                             #   _ensure_tables(), record_plan_stats()
│   │   ├── kyudo.py                  # TaskClassifier — do not modify
│   │   ├── profile.py                # ProfileRenderer — do not modify
│   │   ├── interpreter.py            # NEW — ResolutionEncoder, stubs
│   │   └── [all existing Mycelium files unchanged]
│   │
│   ├── safety/
│   │   ├── risk_analyzer.py
│   │   ├── notifier.py
│   │   └── approval.py
│   │
│   ├── voice/
│   ├── vision/
│   ├── identity/
│   └── audit/
│       └── logger.py
│
├── data/
│   ├── memory.db
│   ├── checkpoints.db
│   ├── identity.db
│   ├── network_ledger.db
│   └── audit_log.jsonl
│
├── docker/iris-worker/Dockerfile
│
├── tests/
│   ├── test_adapter.py
│   ├── test_task_message.py
│   ├── test_permissions.py
│   ├── test_pool.py
│   ├── test_checkpoint.py
│   ├── test_swarm.py
│   ├── test_skills.py
│   ├── test_memory.py
│   ├── test_safety.py
│   ├── test_bridge.py
│   ├── test_network.py
│   ├── test_execution_plan.py
│   ├── test_planner.py
│   ├── test_der_loop.py              # NEW v9.0
│   ├── test_trailing_director.py     # NEW v9.0
│   ├── test_mode_detector.py         # NEW v9.0
│   └── test_two_brain_integration.py # NEW v9.0
│
├── main.py
└── requirements.txt
20. Dependencies
(Unchanged from v8.0)

21. Development Roadmap
Phase 0 — App Integration (Weeks 1–2) ← START HERE
Goal: SwarmBridge wired in. Single DER loop (leading only). Zero regressions.

 Write SwarmBridge
 Write SkillsSwarmBridge
 Wire into existing WebSocket server
 PrimaryNode in do_it_myself mode, single leading DER loop
 ModeDetector — all slash commands working
 AskUserTool — questions surface to user, answers ingest to Mycelium
 Verify all message types pass through unchanged
 der_constants.py — all constants defined
Success criteria: Frontend works identically. /spec, /debug, /research commands detected correctly. Ask tool surfaces questions and ingests answers.

Phase 1 — Message Foundation (Weeks 3–4)
Goal: TaskMessage, PermissionToken, MessageBus, AuditLogger complete.

(Same as v8.0 plus:)

 TaskMessage includes loop_role field
 Audit log shows loop_role in all DER events
Success criteria: PLAN_PRODUCED in audit log. loop_role present.

Phase 2 — Leading DER Loop Complete (Weeks 5–6)
Goal: Full single leading DER loop with Reviewer, mode-aware planning, Mycelium integration, token budget.

 src/core/der_loop.py — DirectorQueue, QueueItem, Reviewer
 _execute_plan_der() — leading loop with Reviewer gate
 DER_TOKEN_BUDGETS — token budget check replaces cycle limit
 DER_EMERGENCY_STOP — backup cycle brake
 Mode-aware graph reads in _plan_task()
 SpecEngine — simple and complex output paths
 All Mycelium proxy methods wired into leading loop
 mycelium_plan_stats table populated after every task
 DER_STEP_VETOED and DER_STEP_REFINED in audit log
Success criteria:

PLAN_PRODUCED in audit log for every task
Token budget check fires before cycle limit
SPEC mode produces docs, not DER execution
Reviewer VETO logged, Director advances to next item
Phase 3 — Trailing Crystallizer (Weeks 7–8)
Goal: Trailing DER loop running in background thread, gap analysis producing depth fills, Mycelium write lock preventing corruption.

 src/core/trailing_director.py — TrailingDirector, gap analysis
 _execute_plan_trailing() — background thread execution
 threading.Thread(daemon=True) — trailing loop never outlives main thread
 Write lock on MyceliumInterface._safe_write()
 Gap distance enforced: within_gap() check before processing
 Parallel mode: trailing loop catches up on leading loop blocker
 TRAILING_GAP_FILLED in audit log
 TRAILING_LOOP_COMPLETE in audit log
 Checkpoint: loop_role in step dict for recovery
Success criteria:

Trailing loop audit events appear after leading loop events for same step
Trailing loop never processes steps within TRAILING_GAP_MIN of leading loop
No SQLite write conflicts — both loops complete without database is locked errors
Graph maturity reached faster with trailing loop than without (compare 50 sessions)
Phase 4 — Memory and Learning (Weeks 9–10)
(Same as v8.0 Phase 3)

Phase 5 — Safety, Docker, External Models (Weeks 11–12)
(Same as v8.0 Phase 4)

Phase 6 — Voice, Vision, Hardening (Weeks 13–14)
(Same as v8.0 Phase 5)

Phase 7 — Torus Network (Weeks 15–18)
(Same as v8.0 Phase 6, plus:)

 Remote dispatch uses single DER loop (leading only — no trailing for remote)
 Local trailing loop processes remote-completed steps for gap analysis
 to_remote_plan() called before any remote dispatch — unchanged constraint
Phase 8 — Mode Switching (After Phase 7)
Goal: Director can switch modes within a session. Mode nesting for sub-tasks.

 ModeStack added to DirectorQueue
 Sub-mode detection at top of each DER cycle
 DEBUG sub-mode triggers when Explorer step fails
 TEST sub-mode triggers on coherence gap detection
 Sub-mode budget: max 3 steps per sub-mode invocation
 Automatic return to primary mode after sub-mode resolves
Note: Implement after Phase 7 is verified. Mode switching is one new field and one new check per cycle. The architecture supports it — implement it when the foundation is proven.

Phase 9 — External Channels (Weeks 19–20, Optional)
(Same as v8.0 Phase 7)

IRIS / Torus Network — PRD v9.0 | Confidential Two brains. One graph. Leading loop covers distance. Trailing loop covers depth. The metabolism never stops.

