Design — Agent Loop Upgrade + DER Loop
Mycelium + Kyudo + Pacman Integration into AgentKernel
Director · Explorer · Reviewer
IRISVOICE/backend/agent/agent_kernel.py · March 2026
Overview
This upgrade wires the Mycelium coordinate memory graph, Kyudo task
classification, and Pacman context management into the existing IRIS
agent execution pipeline. All changes are additive. No existing method
is removed. No existing return type is changed.

DER Loop: The existing brain model becomes the Director. The existing tool agent becomes the Explorer. A new lightweight Reviewer is added as a validation membrane between Director broadcasts and Explorer execution. One model. One graph. Three roles.

The one non-negotiable rule: Every Mycelium call is wrapped in its own try/except Exception: pass. No Mycelium failure ever blocks a user response.

File Map
Class / Component	File	Status
AgentKernel	IRISVOICE/backend/agent/agent_kernel.py	EXISTS — modify
ExecutionPlan, PlanStep, StepStatus	IRISVOICE/backend/core_models.py	EXISTS — modify to_context_string() only
MemoryInterface	IRISVOICE/backend/memory/interface.py	EXISTS — add proxy methods
MyceliumInterface	IRISVOICE/backend/memory/mycelium/interface.py	EXISTS — add ContextPackage, _ensure_tables(), record_plan_stats()
TaskClassifier	IRISVOICE/backend/memory/mycelium/kyudo.py	EXISTS — import only
ProfileRenderer	IRISVOICE/backend/memory/mycelium/profile.py	EXISTS — do not modify
ResolutionEncoder	IRISVOICE/backend/memory/mycelium/interpreter.py	CREATE
DirectorQueue, Reviewer, QueueItem	IRISVOICE/backend/agent/der_loop.py	CREATE
mycelium_plan_stats table	IRISVOICE/backend/memory/db.py	EXISTS file — add table
ResolutionEncoder ≠ ProfileRenderer.

ProfileRenderer → Tier 2 profile prose. Do not modify.
ResolutionEncoder → Tier 3 failure + resolution headers. Create in interpreter.py.
Architecture
DER Roles
DIRECTOR  (brain model, _plan_task)
  - Reads Mycelium context package before every broadcast
  - Maintains the DirectorQueue — adds, removes, reorders items
  - Never executes a tool
  - Never reviews a step
  - Only directs

REVIEWER  (same model, Reviewer class)
  - Receives next queue item before Explorer sees it
  - Checks against gradient warnings + active contracts
  - Checks cross-step coherence with completed steps
  - Returns PASS / REFINE / VETO
  - Never executes
  - Falls back to PASS on any failure — never blocks Explorer

EXPLORER  (tool agent, _dispatch_tool)
  - Receives one approved step at a time
  - Executes it
  - Result fed back to Mycelium immediately
  - Never plans
  - Never reviews
Execution Flow
handle()
    │
    ├─ 1. TaskClassifier.classify()           ← FIRST (space_subset needed)
    ├─ 2. get_task_context_package()          ← uses space_subset
    ├─ 3. intent gate
    ├─ 4. Director: _plan_task()              ← initial queue from plan
    ├─ 5. inject plan into task_anchor zone
    │
    └─ 6. _execute_plan_der()                 ← THE DER LOOP
              │
              └─► cycle (max DER_MAX_CYCLES = 40):
                      │
                      ├─ Director re-reads Mycelium graph
                      │      ↳ get_task_context_package() on cycle > 1
                      │      ↳ updated coordinates from previous step
                      │      ↳ re-orients queue based on new graph state
                      │
                      ├─ Director.queue.next_ready()
                      │
                      ├─ Reviewer.review(item, completed, context_package)
                      │      ↳ PASS   → Explorer proceeds
                      │      ↳ REFINE → Explorer uses refined description
                      │      ↳ VETO   → Director re-queues (max 2 vetoes
                      │                 per item then skip)
                      │
                      ├─ Explorer: _dispatch_tool(step)
                      │      ↳ permission gate
                      │      ↳ risk gate
                      │      ↳ execute
                      │      ↳ reflect
                      │
                      ├─ mycelium_ingest_tool_call()   ← live signal
                      │
                      └─ checkpoint → next cycle
Critical sequence: Classification (step 1) MUST precede context assembly (step 2). space_subset from the classifier is an argument to context assembly. Reversing this order causes a NameError.

New File: IRISVOICE/backend/agent/der_loop.py
python
# CREATE: IRISVOICE/backend/agent/der_loop.py

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import re
import json


class ReviewVerdict(Enum):
    PASS   = "pass"    # step approved as-is
    REFINE = "refine"  # step approved with modification
    VETO   = "veto"    # step rejected — Director must queue alternative


@dataclass
class QueueItem:
    """
    One item in the Director's broadcast queue.
    Richer than PlanStep — carries DER-specific orchestration fields.
    """
    step_id: str
    step_number: int
    description: str
    tool: Optional[str]               = None
    params: Dict[str, Any]            = field(default_factory=dict)
    depends_on: List[str]             = field(default_factory=list)
    critical: bool                    = True
    objective_anchor: str             = ""   # overall task goal — never changes
    coordinate_signal: str            = ""   # Mycelium coordinate region targeted
    veto_count: int                   = 0
    refined_description: Optional[str] = None  # set by Reviewer on REFINE


@dataclass
class DirectorQueue:
    """
    The Director's live broadcast queue.
    Initialized from ExecutionPlan.steps, updated as Explorer feeds back.

    The Director re-reads the Mycelium graph before every cycle and can:
    - Update item descriptions based on new coordinates
    - Add new items when the graph reveals gaps
    - Remove items when the graph shows they're no longer needed
    """
    objective: str
    items: List[QueueItem]  = field(default_factory=list)
    completed_ids: List[str] = field(default_factory=list)
    vetoed_ids: List[str]    = field(default_factory=list)
    cycle_count: int         = 0
    max_cycles: int          = 40    # DER_MAX_CYCLES
    max_veto_per_item: int   = 2     # DER_MAX_VETO_PER_ITEM

    def next_ready(self) -> Optional["QueueItem"]:
        """Next item whose dependencies are all completed. None if none ready."""
        completed = set(self.completed_ids)
        for item in self.items:
            if item.step_id in self.completed_ids:
                continue
            if item.step_id in self.vetoed_ids:
                continue
            if all(dep in completed for dep in item.depends_on):
                return item
        return None

    def mark_complete(self, step_id: str) -> None:
        if step_id not in self.completed_ids:
            self.completed_ids.append(step_id)

    def mark_vetoed(self, step_id: str) -> None:
        if step_id not in self.vetoed_ids:
            self.vetoed_ids.append(step_id)

    def add_item(self, item: "QueueItem") -> None:
        self.items.append(item)

    def is_complete(self) -> bool:
        active = [i for i in self.items if i.step_id not in self.vetoed_ids]
        return all(i.step_id in self.completed_ids for i in active)

    def hit_cycle_limit(self) -> bool:
        return self.cycle_count >= self.max_cycles


class Reviewer:
    """
    Validates Director queue items before Explorer executes them.
    Uses the same model as Director and Explorer — one model, three roles.
    Reads from Mycelium graph. Never writes to it.

    The Reviewer is a membrane, not a gate.
    It never blocks on failure — always falls back to PASS.

    Verdicts:
        PASS   — step is clean, Explorer proceeds as-is
        REFINE — step has an issue but is fixable,
                 refined_description provided
        VETO   — step conflicts with known gradient danger or contract,
                 Director must replace this item

    Unknown territory (no gradient data) → PASS with no penalty.
    Only known danger (gradient warnings) or rule violations (contracts)
    produce VETO.
    """

    REVIEWER_MAX_TOKENS = 200
    REVIEWER_TEMPERATURE = 0.0  # deterministic — reviewer must be consistent

    def __init__(self, adapter, memory_interface):
        self.adapter = adapter
        self.memory  = memory_interface

    def review(
        self,
        item: QueueItem,
        completed_steps: List[QueueItem],
        context_package,
        is_mature: bool
    ) -> tuple:
        """
        Returns (ReviewVerdict, output: str | None)
        Never raises. Falls back to (PASS, None) on any error.
        """
        try:
            # Fast path: no Mycelium data → skip review
            if not is_mature or not hasattr(context_package, 'gradient_warnings'):
                return ReviewVerdict.PASS, None

            prompt = self._build_review_prompt(
                item=item,
                completed_steps=completed_steps,
                gradient_warnings=context_package.gradient_warnings or "",
                active_contracts=context_package.active_contracts or "",
            )

            response = self.adapter.infer(
                prompt,
                role="EXECUTION",
                max_tokens=self.REVIEWER_MAX_TOKENS,
                temperature=self.REVIEWER_TEMPERATURE
            )

            return self._parse_verdict(response.raw_text)

        except Exception:
            return ReviewVerdict.PASS, None

    def _build_review_prompt(
        self,
        item: QueueItem,
        completed_steps: List[QueueItem],
        gradient_warnings: str,
        active_contracts: str,
    ) -> str:
        """
        Compact review prompt — stays under 300 tokens.
        Only needs: current step, last 3 completed, dangers, contracts.
        """
        completed_summary = "\n".join(
            f"- Step {s.step_number}: {s.description} [done]"
            for s in completed_steps[-3:]
        ) or "None"

        return (
            f"OBJECTIVE: {item.objective_anchor}\n\n"
            f"COMPLETED STEPS (last 3):\n{completed_summary}\n\n"
            f"GRADIENT WARNINGS:\n{gradient_warnings[:200] or 'None'}\n\n"
            f"ACTIVE CONTRACTS:\n{active_contracts[:200] or 'None'}\n\n"
            f"NEXT STEP TO REVIEW:\n"
            f"  Step {item.step_number}: {item.description}\n"
            f"  Tool: {item.tool or 'none'}\n\n"
            "Does this step conflict with a gradient warning or contract?\n"
            "Does it contradict what was already completed?\n\n"
            "Respond with JSON only:\n"
            '{"verdict":"pass|refine|veto",'
            '"reason":"one sentence or empty string",'
            '"refined":"improved step description or empty string"}'
        )

    def _parse_verdict(self, raw: str) -> tuple:
        """Parse model response. Falls back to PASS on any parse failure."""
        try:
            m = re.search(r'\{[\s\S]+?\}', raw)
            if not m:
                return ReviewVerdict.PASS, None
            data = json.loads(m.group())
            v    = data.get("verdict", "pass").lower()
            reason  = data.get("reason", "") or None
            refined = data.get("refined", "") or None

            if v == "veto":
                return ReviewVerdict.VETO, reason
            if v == "refine" and refined:
                return ReviewVerdict.REFINE, refined
            return ReviewVerdict.PASS, None
        except Exception:
            return ReviewVerdict.PASS, None
Data Models
ContextPackage
python
# IRISVOICE/backend/memory/mycelium/interface.py
# ADD BEFORE MyceliumInterface class

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Union
import re

@dataclass
class ContextPackage:
    mycelium_path: str
    topology_path: str
    manifest: Dict[str, Any]
    tier1_directives: str
    tier2_predictions: str
    tier3_failures: str
    active_contracts: str
    gradient_warnings: str
    causal_context: str
    ambient_signals: str
    topology_position: str
    task_class: str
    _registered_addresses: List[str] = field(default_factory=list)

    def get_system_zone_content(self) -> str:
        parts = [
            self.active_contracts, self.gradient_warnings,
            self.causal_context, self.tier1_directives,
            self.mycelium_path, self.topology_path, self.ambient_signals,
        ]
        return "\n".join(p for p in parts if p)

    def get_tier2_predictions(self) -> str:
        return self.tier2_predictions or ""

    def get_tier3_failures(self) -> str:
        return self.tier3_failures or ""

    def register_address(self, url: str, token_count: int, summary: str) -> None:
        self.manifest[url] = {"token_count": token_count, "summary": summary}
        self._registered_addresses.append(url)

    @property
    def topology_primitive(self) -> str:
        if not self.topology_path:
            return "unknown"
        m = re.search(r'primitives:\[([a-z_]+)\]', self.topology_path)
        return m.group(1) if m else "unknown"
ResolutionEncoder
python
# CREATE: IRISVOICE/backend/memory/mycelium/interpreter.py

from typing import Dict, Optional
import json


class ResolutionEncoder:
    def encode_with_resolution(self, failure: Dict, conn=None) -> str:
        try:
            space_id   = failure.get("space_id", "unknown")
            tool       = failure.get("tool_name", "unknown")
            condition  = failure.get("condition", "unknown")
            delta      = failure.get("score_delta", -0.05)
            resolution = failure.get("resolution", None)
            if resolution is None and conn is not None:
                resolution = self._find_resolution(failure, conn)
            if resolution:
                return (
                    f"[space:{space_id} | outcome:miss | tool:{tool} | "
                    f"condition:{condition} | delta:{delta:.2f} | "
                    f"resolution:{resolution} \u2192 hit]"
                )
            return (
                f"[space:{space_id} | outcome:miss | tool:{tool} | "
                f"condition:{condition} | delta:{delta:.2f}]"
            )
        except Exception:
            summary = failure.get("task_summary", "unknown failure")
            reason  = failure.get("failure_reason", "")
            return f"[outcome:miss | {summary[:80]} | {reason[:40]}]"

    def _find_resolution(self, failure: Dict, conn) -> Optional[str]:
        try:
            session_id = failure.get("session_id")
            if not session_id:
                return None
            cursor = conn.execute(
                """SELECT tool_sequence FROM episodes
                   WHERE session_id != ? AND outcome_type = 'success'
                   AND task_summary LIKE ? ORDER BY created_at DESC LIMIT 1""",
                (session_id, f"%{failure.get('tool_name', '')}%")
            )
            row = cursor.fetchone()
            if not row:
                return None
            seq = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            if seq and isinstance(seq, list) and len(seq) > 0:
                first = seq[0]
                name = first.get("tool", "") if isinstance(first, dict) else str(first)
                return name[:40] if name else None
            return None
        except Exception:
            return None


class CoordinateInterpreter:
    """Stub — implement in later phase."""
    pass

class BehavioralPredictor:
    """Stub — implement in later phase."""
    pass
API Changes
MemoryInterface — New Methods Only
(Identical to original upgrade spec. All proxy methods unchanged.)

python
def get_task_context_package(self, task, session_id, space_subset=None):
    try:
        if self._mycelium is None or not self._mycelium.is_mature():
            return self.get_task_context(task, session_id), False
        pkg = self._mycelium.get_context_path(
            task_text=task, session_id=session_id, space_subset=space_subset
        )
        if not pkg or isinstance(pkg, str):
            return self.get_task_context(task, session_id), False
        return pkg, True
    except Exception:
        return self.get_task_context(task, session_id), False

def mycelium_ingest_tool_call(self, tool_name, success,
                               sequence_position, total_steps, session_id):
    if self._mycelium is None: return
    try:
        self._mycelium.ingest_tool_call(
            tool_name=tool_name, success=success,
            sequence_position=sequence_position,
            total_steps=total_steps, session_id=session_id
        )
    except Exception: pass

def mycelium_record_outcome(self, session_id, task_text, outcome):
    if self._mycelium is None: return
    try:
        self._mycelium.record_outcome(
            session_id=session_id, task_text=task_text, outcome=outcome
        )
    except Exception: pass

def mycelium_crystallize_landmark(self, session_id, cumulative_score,
                                   outcome, task_entry_label):
    if self._mycelium is None: return
    try:
        self._mycelium.crystallize_landmark(
            session_id=session_id, cumulative_score=cumulative_score,
            outcome=outcome, task_entry_label=task_entry_label
        )
    except Exception: pass

def mycelium_clear_session(self, session_id):
    if self._mycelium is None: return
    try: self._mycelium.clear_session(session_id)
    except Exception: pass

def mycelium_ingest_statement(self, statement, session_id):
    if self._mycelium is None: return
    try:
        self._mycelium.ingest_statement(text=statement, session_id=session_id)
    except Exception: pass

def mycelium_record_plan_stats(self, **kwargs):
    if self._mycelium is None: return
    if hasattr(self._mycelium, "record_plan_stats"):
        try: self._mycelium.record_plan_stats(**kwargs)
        except Exception: pass
MyceliumInterface — _ensure_tables() + record_plan_stats()
python
def __init__(self, ...):
    # ... existing body ...
    self._ensure_tables()   # ADD at very end

def _ensure_tables(self) -> None:
    try:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS mycelium_plan_stats (
                stat_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                task_class TEXT NOT NULL, strategy TEXT NOT NULL,
                total_steps INTEGER NOT NULL, steps_completed INTEGER NOT NULL,
                tokens_used INTEGER DEFAULT 0, avg_step_duration_ms REAL DEFAULT 0.0,
                outcome TEXT NOT NULL, graph_mature INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            )
        """)
        self._conn.commit()
    except Exception: pass

def record_plan_stats(self, session_id, task_class, strategy, total_steps,
                      steps_completed, tokens_used, avg_step_duration_ms,
                      outcome, graph_mature) -> None:
    try:
        import uuid, time
        self._conn.execute(
            """INSERT INTO mycelium_plan_stats VALUES
               (?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4())[:12], session_id, task_class, strategy,
             total_steps, steps_completed, tokens_used, avg_step_duration_ms,
             outcome, 1 if graph_mature else 0, time.time())
        )
        self._conn.commit()
    except Exception: pass
ExecutionPlan.to_context_string()
python
def to_context_string(self) -> str:
    status_markers = {
        StepStatus.PENDING:   "[ ]",
        StepStatus.RUNNING:   "[~]",
        StepStatus.COMPLETED: "[+]",
        StepStatus.FAILED:    "[x]",
        StepStatus.SKIPPED:   "[s]",
        StepStatus.BLOCKED:   "[b]",
    }
    lines = [
        f"[system://plan/{self.plan_id[:8]}]",
        f"EXECUTION PLAN [{self.plan_id[:8]}]",
        f"Task: {self.original_task}",
        f"Strategy: {self.strategy}",
        f"Reasoning: {self.reasoning}",
        "", "Steps:"
    ]
    for step in self.steps:
        marker  = status_markers.get(step.status, "[ ]")
        dep_str = (
            f" (after: {', '.join(step.depends_on)})" if step.depends_on else ""
        )
        lines.append(f"  [system://plan/{self.plan_id[:8]}/step/{step.step_id}]")
        lines.append(f"  {marker} Step {step.step_number}: {step.description}{dep_str}")
        if step.status == StepStatus.COMPLETED and step.result:
            lines.append(f"      Result: {str(step.result)[:100]}")
        if step.status == StepStatus.FAILED:
            lines.append(f"      Failed: {step.failure_reason}")
    return "\n".join(lines)
AgentKernel.init() additions
python
from backend.memory.mycelium.kyudo import TaskClassifier
from backend.agent.der_loop import Reviewer

# In __init__() body:
self._task_classifier = TaskClassifier()
self._reviewer = Reviewer(adapter=self.adapter, memory_interface=self.memory)
AgentKernel._execute_plan_der() — New Method
python
# DER loop constants — add at top of agent_kernel.py
DER_MAX_CYCLES        = 40
DER_MAX_VETO_PER_ITEM = 2

def _execute_plan_der(self, msg, plan, context_package,
                      is_mature, task_class, session_id) -> dict:
    """
    DER Loop. Director re-reads graph each cycle. Reviewer gates each step.
    Explorer executes one approved step. Signals feed back to Mycelium.
    Falls back to _synthesize_plan_results() on completion or limit.
    """
    import time
    from backend.agent.der_loop import DirectorQueue, QueueItem, ReviewVerdict

    queue = DirectorQueue(
        objective=plan.original_task,
        items=[
            QueueItem(
                step_id=s.step_id, step_number=s.step_number,
                description=s.description, tool=s.tool, params=s.params,
                depends_on=s.depends_on, critical=s.critical,
                objective_anchor=plan.original_task,
            )
            for s in plan.steps
        ],
        max_cycles=DER_MAX_CYCLES,
        max_veto_per_item=DER_MAX_VETO_PER_ITEM
    )
    completed_items = []

    while not queue.is_complete() and not queue.hit_cycle_limit():
        queue.cycle_count += 1

        # Director re-reads graph on every cycle after the first
        if queue.cycle_count > 1:
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

        item = queue.next_ready()
        if item is None:
            break

        # Reviewer gate
        verdict, reviewer_output = self._reviewer.review(
            item=item, completed_steps=completed_items,
            context_package=context_package, is_mature=is_mature
        )

        if verdict == ReviewVerdict.VETO:
            item.veto_count += 1
            self.audit.log("DER_STEP_VETOED", {
                "step_id": item.step_id, "reason": reviewer_output,
                "veto_count": item.veto_count
            })
            if item.veto_count >= queue.max_veto_per_item:
                queue.mark_vetoed(item.step_id)
                for s in plan.steps:
                    if s.step_id == item.step_id:
                        s.status = StepStatus.SKIPPED
                        s.failure_reason = f"Vetoed: {reviewer_output}"
                        break
                if item.critical:
                    plan.outcome = "failure"
                    break
            continue

        if verdict == ReviewVerdict.REFINE and reviewer_output:
            item.refined_description = reviewer_output
            self.audit.log("DER_STEP_REFINED", {
                "step_id": item.step_id, "refined": reviewer_output
            })

        # Explorer executes
        plan_step = next(
            (s for s in plan.steps if s.step_id == item.step_id), None
        )
        if plan_step is None:
            continue

        if item.refined_description:
            plan_step.description = item.refined_description

        plan_step.status = StepStatus.RUNNING
        t0 = time.time()

        try:
            if plan_step.required_permission:
                if not self.permissions.check(
                    self.node_id, plan_step.required_permission,
                    plan_step.tool or ""
                ):
                    plan_step.status = StepStatus.BLOCKED
                    plan_step.failure_reason = "Permission denied at execution"
                    if plan_step.critical:
                        plan.outcome = "failure"
                    continue

            risk = self.risk.analyze(
                plan_step.required_permission or "skill_execute",
                {"tool": plan_step.tool, "params": plan_step.params}
            )
            if risk.get("auto_block"):
                plan_step.status = StepStatus.BLOCKED
                plan_step.failure_reason = "Auto-blocked by risk analyzer"
                if plan_step.critical:
                    plan.outcome = "failure"
                continue

            raw_result = self._dispatch_tool(
                {"tool": plan_step.tool, "params": plan_step.params},
                self._token
            )
            plan_step.duration_ms = int((time.time() - t0) * 1000)

            reflection = self._reflect_on_step(plan_step, raw_result)

            if reflection["success"]:
                plan_step.status = StepStatus.COMPLETED
                plan_step.result = raw_result
                queue.mark_complete(item.step_id)
                completed_items.append(item)
                self.memory.working.append(
                    session_id,
                    f"Step {plan_step.step_number} completed: "
                    f"{str(raw_result)[:300]}",
                    zone="active_tool_state"
                )
            else:
                plan_step.failure_reason = reflection["reason"]
                if plan_step.critical:
                    plan_step.status = StepStatus.FAILED
                    plan.outcome = "failure"
                else:
                    plan_step.status = StepStatus.SKIPPED
                try:
                    self.memory.mycelium_ingest_tool_call(
                        tool_name=plan_step.tool or "inference",
                        success=False,
                        sequence_position=plan_step.step_number,
                        total_steps=len(plan.steps),
                        session_id=session_id
                    )
                except Exception:
                    pass

        except Exception as e:
            plan_step.status = StepStatus.FAILED
            plan_step.failure_reason = str(e)
            plan_step.duration_ms = int((time.time() - t0) * 1000)
            if plan_step.critical:
                plan.outcome = "failure"

        if plan_step.tool:
            try:
                self.memory.mycelium_ingest_tool_call(
                    tool_name=plan_step.tool,
                    success=(plan_step.status == StepStatus.COMPLETED),
                    sequence_position=plan_step.step_number,
                    total_steps=len(plan.steps),
                    session_id=session_id
                )
            except Exception:
                pass

        self.checkpoint.add_step(
            msg.task_id,
            {"step_id": plan_step.step_id, "tool": plan_step.tool,
             "params": plan_step.params},
            plan_step.result
        )

        if plan.outcome == "failure":
            break

    return self._synthesize_plan_results(plan, plan.steps)
handle() — Route to DER loop for do_it_myself
In handle(), change the execution routing block from:

python
else:
    result = self._execute_plan(msg, plan)
To:

python
else:
    result = self._execute_plan_der(
        msg=msg,
        plan=plan,
        context_package=context_package,
        is_mature=is_mature,
        task_class=task_class,
        session_id=session_id
    )
Everything else in handle() is unchanged from the original upgrade spec.

Error Handling Reference
Scenario	Correct behavior
Reviewer throws	(PASS, None) via outer try/except — Explorer proceeds
Reviewer parse fails	(PASS, None) — Explorer proceeds
Step vetoed twice	Marked SKIPPED, Director continues with remaining items
Cycle limit hit (40)	_synthesize_plan_results() on whatever completed
Graph refresh fails mid-loop	Keeps existing context_package — loop continues
Mycelium unavailable	All proxy methods no-op — DER loop runs without graph
Zero plan steps	len(plan.steps) with > 0 guard — no ZeroDivisionError
Unicode in markers	[+] [x] [~] — not ✓ ✗
What Does Not Change
get_task_context() — signature and behavior identical
_execute_plan() — preserved, used by spawn_children fallback
_validate_permissions() — unchanged
_parse_plan() — unchanged
to_remote_plan() — unchanged
store_episode() — called unchanged after every task
working.clear_session() — called unchanged
All WebSocket message handling — unchanged
All existing audit log events — unchanged
WorkerExecutor — unchanged
IRIS Agent Loop Upgrade + DER Loop Director · Explorer · Reviewer March 2026 · IRISVOICE / IRIS / Torus Network · Confidential

