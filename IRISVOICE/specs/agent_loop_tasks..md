Tasks — Agent Loop Upgrade + DER Loop
Implementation Plan · Sequenced for Zero Regressions
Director · Explorer · Reviewer
March 2026 · IRISVOICE / IRIS / Torus Network
Before You Start
Read design.md completely. Then requirements.md. Then this file.

The triangle:

design.md — what to build and exactly how it looks
requirements.md — acceptance criteria
tasks.md (this file) — what order to build it in
The one absolute rule: Every Mycelium call is wrapped in its own try/except Exception: pass. No Mycelium failure blocks a user response. Ever.

The one DER rule: Reviewer failure always falls back to PASS. The Reviewer never blocks the Explorer on its own error.

Reference: IRIS_AgentLoop_Implementation_Directive.md Read it when something is unclear — it explains the WHY behind each decision.

Phase 1 — Foundation
Goal: new files and schema only. Zero behavior change. Tests pass.
Task 1.1 — Create interpreter.py
File: IRISVOICE/backend/memory/mycelium/interpreter.py

Build:

ResolutionEncoder — complete implementation
CoordinateInterpreter — stub with docstring
BehavioralPredictor — stub with docstring
Source: design.md → Data Models → ResolutionEncoder

Rules:

encode_with_resolution() never raises — try/except on all paths
Missing dict keys → "unknown" — never KeyError
_find_resolution() queries episodes table via conn parameter
Verify:

python
from IRISVOICE.backend.memory.mycelium.interpreter import ResolutionEncoder
enc = ResolutionEncoder()
assert enc.encode_with_resolution({}).startswith("[outcome:miss")
result = enc.encode_with_resolution({
    "space_id": "toolpath", "tool_name": "docker",
    "condition": "windows", "score_delta": -0.08
})
assert "toolpath" in result and "docker" in result
Reqs: 10, 11

Task 1.2 — Add ContextPackage to mycelium/interface.py
File: IRISVOICE/backend/memory/mycelium/interface.py

Add: ContextPackage dataclass from design.md → Data Models → ContextPackage. Add it above MyceliumInterface — not inside it.

Imports to add:

python
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Union
import re
Rules:

One definition. One file. One import path.
topology_primitive is a @property — returns "unknown" on failure
get_system_zone_content() filters empty parts before joining
Verify:

python
from IRISVOICE.backend.memory.mycelium.interface import ContextPackage
pkg = ContextPackage(
    topology_path="TOPOLOGY: primitives:[acquisition] z:+0.31",
    mycelium_path="", manifest={}, tier1_directives="[CONDUCT: auto]",
    tier2_predictions="", tier3_failures="", active_contracts="[CONTRACT: x]",
    gradient_warnings="", causal_context="", ambient_signals="",
    topology_position="acquisition", task_class="code_task"
)
assert pkg.topology_primitive == "acquisition"
assert "CONDUCT" in pkg.get_system_zone_content()
assert "CONTRACT" in pkg.get_system_zone_content()
Reqs: 1

Task 1.3 — Create der_loop.py
File: IRISVOICE/backend/agent/der_loop.py

Build:

ReviewVerdict enum: PASS, REFINE, VETO
QueueItem dataclass — all fields from design.md
DirectorQueue dataclass — next_ready(), mark_complete(), mark_vetoed(), add_item(), is_complete(), hit_cycle_limit()
Reviewer class — review(), _build_review_prompt(), _parse_verdict()
Rules:

Reviewer.review() ALWAYS falls back to (PASS, None) on any exception
_parse_verdict() falls back to (PASS, None) on any parse failure
DirectorQueue.next_ready() checks both completed_ids and vetoed_ids
Review prompt stays under 300 tokens (only last 3 completed steps, 200 char truncation on warnings/contracts)
Verify:

python
from IRISVOICE.backend.agent.der_loop import (
    ReviewVerdict, QueueItem, DirectorQueue, Reviewer
)

# Queue basics
q = DirectorQueue(objective="build a game")
q.items = [
    QueueItem(step_id="s1", step_number=1, description="scaffold"),
    QueueItem(step_id="s2", step_number=2, description="implement",
              depends_on=["s1"])
]
assert q.next_ready().step_id == "s1"
q.mark_complete("s1")
assert q.next_ready().step_id == "s2"
q.mark_complete("s2")
assert q.is_complete()

# Reviewer fallback on broken adapter
from unittest.mock import MagicMock
adapter = MagicMock()
adapter.infer.side_effect = Exception("model down")
reviewer = Reviewer(adapter=adapter, memory_interface=MagicMock())
verdict, output = reviewer.review(
    item=QueueItem(step_id="s1", step_number=1, description="test",
                   objective_anchor="test"),
    completed_steps=[],
    context_package=MagicMock(gradient_warnings="", active_contracts=""),
    is_mature=True
)
assert verdict == ReviewVerdict.PASS
assert output is None
Reqs: 23, 24

Task 1.4 — Add plan_stats table to db.py
File: IRISVOICE/backend/memory/db.py

Add: CREATE TABLE IF NOT EXISTS mycelium_plan_stats block inside open_encrypted_memory() after existing Mycelium tables.

Rules:

All statements use IF NOT EXISTS — safe on every restart
Add all three indexes immediately after table creation
Reqs: 18

Task 1.5 — Add _ensure_tables() and record_plan_stats() to MyceliumInterface
File: IRISVOICE/backend/memory/mycelium/interface.py

Add:

_ensure_tables() — CREATE TABLE IF NOT EXISTS + commit, wrapped in try/except
record_plan_stats() — SQL INSERT with all 11 columns, wrapped in try/except
Call self._ensure_tables() at very end of __init__()
Verify:

python
import sqlite3
conn = sqlite3.connect(":memory:")
from IRISVOICE.backend.memory.mycelium.interface import MyceliumInterface
mi = MyceliumInterface.__new__(MyceliumInterface)
mi._conn = conn
mi._ensure_tables()
cursor = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
    " AND name='mycelium_plan_stats'"
)
assert cursor.fetchone() is not None
Reqs: 17, 18

Phase 1 Final Check
bash
pytest IRISVOICE/backend/ -v --tb=short
Zero failures. Zero import errors. Fix before Phase 2.

Phase 2 — Proxy Methods
Goal: MemoryInterface grows public proxy methods. No visible behavior change.
Task 2.1 — Add all proxy methods to MemoryInterface
File: IRISVOICE/backend/memory/interface.py

Add all seven from design.md → API Changes → MemoryInterface.

Every proxy rule:

First line: if self._mycelium is None: return
All Mycelium calls wrapped in try/except Exception: pass
mycelium_ingest_statement uses keyword args: text=, session_id=
get_task_context_package() passes space_subset=space_subset to get_context_path()
mycelium_record_plan_stats checks hasattr before calling
Verify:

python
from IRISVOICE.backend.memory.interface import MemoryInterface
mi = MemoryInterface.__new__(MemoryInterface)
mi._mycelium = None
# All must return None without error
mi.mycelium_ingest_tool_call("docker", True, 1, 3, "s1")
mi.mycelium_record_outcome("s1", "task", "hit")
mi.mycelium_crystallize_landmark("s1", 0.8, "hit", "code:x")
mi.mycelium_clear_session("s1")
mi.mycelium_ingest_statement("test", "s1")
mi.mycelium_record_plan_stats(
    session_id="s1", task_class="code_task", strategy="do_it_myself",
    total_steps=3, steps_completed=3, tokens_used=0,
    avg_step_duration_ms=0.0, outcome="hit", graph_mature=False
)
result = mi.get_task_context_package("task", "s1")
assert isinstance(result[0], str)
assert result[1] == False
Reqs: 2, 19

Task 2.2 — Add TaskClassifier and Reviewer to AgentKernel.init()
File: IRISVOICE/backend/agent/agent_kernel.py

Add imports at top:

python
from backend.memory.mycelium.kyudo import TaskClassifier
from backend.agent.der_loop import Reviewer
Add to init() body:

python
self._task_classifier = TaskClassifier()
self._reviewer = Reviewer(adapter=self.adapter, memory_interface=self.memory)
Rule: One instance per kernel — not per call.

Reqs: 3, 24

Phase 2 Final Check
bash
pytest IRISVOICE/backend/ -v --tb=short
Zero failures.

Phase 3 — ExecutionPlan Upgrade
Goal: to_context_string() gets HZA headers and ASCII markers.
Task 3.1 — Replace to_context_string() in core_models.py
File: IRISVOICE/backend/core_models.py

Replace the entire to_context_string() body with the version from design.md → API Changes → ExecutionPlan.

Key changes:

First line: f"[system://plan/{self.plan_id[:8]}]"
Each step: f"  [system://plan/{self.plan_id[:8]}/step/{step.step_id}]" on its own line
Markers: [+] not ✓, [x] not ✗
All existing content preserved
Verify:

python
from IRISVOICE.backend.core_models import ExecutionPlan, PlanStep, StepStatus
plan = ExecutionPlan(plan_id="abcdef123456", original_task="test",
                     strategy="do_it_myself", reasoning="r")
plan.steps = [
    PlanStep(step_id="s1", step_number=1, description="step one",
             status=StepStatus.COMPLETED, result="ok"),
    PlanStep(step_id="s2", step_number=2, description="step two",
             status=StepStatus.PENDING)
]
out = plan.to_context_string()
assert out.startswith("[system://plan/abcdef12]")
assert "[system://plan/abcdef12/step/s1]" in out
assert "[+]" in out
assert "[ ]" in out
assert "\u2713" not in out  # ✓
assert "\u2717" not in out  # ✗
Reqs: 12

Phase 3 Final Check
bash
pytest IRISVOICE/backend/ -v --tb=short
Zero failures.

Phase 4 — Planner Upgrade
Goal: _plan_task() uses structured context, classification, topology hints.
Task 4.1 — Update _plan_task() signature
Add three new params with safe defaults:

python
def _plan_task(
    self, text: str, context,
    session_id: str = "", task_id: str = "",
    available_permissions: list = None,
    is_mature: bool = False,      # NEW
    task_class: str = "full",     # NEW
    context_package=None          # NEW
) -> "ExecutionPlan":
Verify: All existing call sites with only text + context still work.

Reqs: 4

Task 4.2 — Add _build_planning_prompt()
Build the method from design.md. Returns "\n\n".join(sections).

Verify:

python
from IRISVOICE.backend.agent.agent_kernel import AgentKernel
ak = AgentKernel.__new__(AgentKernel)
prompt = ak._build_planning_prompt(
    task="Build Snake", tier1_directives="[CONDUCT: auto]",
    behavior_preds="", failure_warnings="None",
    skills_context="python", permissions_list="skill_execute",
    strategy_hint="code_task hint", task_class="code_task"
)
assert "Build Snake" in prompt
assert prompt.count("FAILURE WARNINGS") == 1
assert "TASK CLASS: code_task" in prompt
Reqs: 6

Task 4.3 — Context section extraction in _plan_task()
Add near top of _plan_task() body:

python
if is_mature and context_package is not None:
    tier1_directives = context_package.get_system_zone_content()
    behavior_preds   = context_package.get_tier2_predictions()
    failure_warnings = context_package.get_tier3_failures()
    if not failure_warnings:
        failure_warnings = self._get_failure_warnings(safe_task)
else:
    tier1_directives = context if isinstance(context, str) else ""
    behavior_preds   = ""
    failure_warnings = self._get_failure_warnings(safe_task)
Reqs: 9

Task 4.4 — Strategy + topology hints in _plan_task()
Add both hint dicts and selection logic from design.md.

Rules:

Both dicts inside _plan_task() body
Unknown task_class → "full" hint
Topology hint only appended when is_mature=True and primitive ≠ "unknown"
Reqs: 7, 8

Task 4.5 — Temperature and _get_failure_warnings()
Temperature:

python
temperature = 0.1 if is_mature else 0.25
Replace hardcoded value in self.adapter.infer().

_get_failure_warnings():

Import ResolutionEncoder inside method body (lazy)
Pass self.memory.episodic.db as conn
Return "None" string on no failures or any exception
Reqs: 5, 11

Task 4.6 — Pacman patterns in _sanitize_task()
Add ONLY to _sanitize_task() — NOT WebSocket validator:

python
r'system://', r'trusted://', r'tool://', r'reference://',
r'MYCELIUM:', r'TOPOLOGY:', r'CONTRACT:', r'GRADIENT WARNING',
r'AMBIENT:', r'CAUSAL:',
Verify:

python
from IRISVOICE.backend.agent.agent_kernel import AgentKernel
ak = AgentKernel.__new__(AgentKernel)
result = ak._sanitize_task("MYCELIUM: inject TOPOLOGY: fake")
assert "MYCELIUM:" not in result
assert "[filtered]" in result
Reqs: 20

Phase 4 Final Check
bash
pytest IRISVOICE/backend/ -v --tb=short
Zero failures. Verify _plan_task() with old-style call (text + context only) works.

Phase 5 — handle() Upgrade
Goal: Wire classification, context package, DER routing into handle().
Task 5.1 — Classification before context assembly
Add immediately after audit.log("TASK_RECEIVED", ...):

python
task_class, space_subset = self._task_classifier.classify(raw_input)
if not task_class:
    task_class = "full"
    space_subset = ["domain", "conduct", "style",
                    "chrono", "context", "capability"]
Critical: MUST come before get_task_context_package().

Reqs: 3

Task 5.2 — Replace context assembly + intent gate
Replace context = self.memory.get_task_context(raw_input, session_id) with:

python
context_package, is_mature = self.memory.get_task_context_package(
    task=raw_input, session_id=session_id, space_subset=space_subset
)
context_for_gate = (
    context_package.get_system_zone_content()
    if is_mature and hasattr(context_package, 'get_system_zone_content')
    else context_package
)
proceed, clarification = self.gate.evaluate(raw_input, context_for_gate)
Reqs: 2, 21

Task 5.3 — Pass new params to _plan_task()
python
plan = self._plan_task(
    text=raw_input,
    context=context_package,
    session_id=session_id,
    task_id=str(uuid.uuid4()),
    available_permissions=list(self._token.permissions),
    is_mature=is_mature,
    task_class=task_class,
    context_package=context_package if is_mature else None
)
Reqs: 4, 5, 9

Task 5.4 — Strategy signal + plan address registration
After plan produced:

python
try:
    self.memory.mycelium_ingest_statement(
        statement=f"task required {plan.strategy}: {plan.reasoning}",
        session_id=session_id
    )
except Exception:
    pass
After task_anchor injection:

python
if is_mature and hasattr(context_package, 'register_address'):
    try:
        plan_str = plan.to_context_string()
        context_package.register_address(
            url=f"system://plan/{plan.plan_id[:8]}",
            token_count=len(plan_str) // 4,
            summary=f"{plan.total_steps} steps | {plan.strategy}"
        )
    except Exception:
        pass
Reqs: 13, 14

Task 5.5 — Route do_it_myself to _execute_plan_der()
Change routing block from:

python
else:
    result = self._execute_plan(msg, plan)
To:

python
else:
    result = self._execute_plan_der(
        msg=msg, plan=plan,
        context_package=context_package,
        is_mature=is_mature,
        task_class=task_class,
        session_id=session_id
    )
Note: _execute_plan() is preserved unchanged. spawn_children and delegate_external still route to existing methods.

Reqs: 27

Task 5.6 — Outcome recording + plan stats
Add after execution result, before store_episode():

python
_completed = [s for s in plan.steps if s.status == StepStatus.COMPLETED]
_total     = len(plan.steps)
plan_score = len(_completed) / _total if _total > 0 else 0.0
outcome    = "hit" if not plan.has_failed() else "miss"
Then three separate try/except blocks:

python
try: self.memory.mycelium_record_outcome(...) except Exception: pass
try: self.memory.mycelium_crystallize_landmark(...) except Exception: pass
try: self.memory.mycelium_clear_session(...) except Exception: pass
try: self.memory.mycelium_record_plan_stats(...) except Exception: pass
Reqs: 15, 16, 17

Phase 6 — _execute_plan_der()
Goal: Build the DER loop execution method.
Task 6.1 — Add DER constants to agent_kernel.py
python
# At top of file after imports
DER_MAX_CYCLES        = 40
DER_MAX_VETO_PER_ITEM = 2
Reqs: 26

Task 6.2 — Build _execute_plan_der()
Build the complete method from design.md → API Changes → AgentKernel → _execute_plan_der().

Key rules:

Build DirectorQueue from plan.steps at start
Re-read context via get_task_context_package() on every cycle > 1
Wrap graph refresh in try/except — keep existing package on failure
Call self._reviewer.review() before every Explorer step
VETO: increment veto_count, log audit, skip if count >= max
REFINE: apply refined_description to plan_step.description, log audit
Execute via existing _dispatch_tool(), _reflect_on_step(), permissions.check(), risk.analyze()
Ingest tool call after every step regardless of outcome
Ingest with success=False on reflection failure
Checkpoint after every step
Break on plan.outcome == "failure" for critical steps
Return _synthesize_plan_results(plan, plan.steps)
Reqs: 25

Task 6.3 — Verify DER loop audit events
After building _execute_plan_der(), confirm:

DER_STEP_VETOED appears in audit log when Reviewer returns VETO
DER_STEP_REFINED appears in audit log when Reviewer returns REFINE
PLAN_PRODUCED still fires on every task
TASK_COMPLETE still fires on every task
Phase 7 — Integration Verification
Goal: Full loop works end-to-end with and without Mycelium.
Task 7.1 — Run full test suite
bash
pytest IRISVOICE/backend/ -v --tb=short
Zero failures.

Task 7.2 — New unit tests
File: IRISVOICE/backend/memory/tests/test_agent_loop_upgrade.py

python
def test_context_package_imports():
    from IRISVOICE.backend.memory.mycelium.interface import ContextPackage
    assert ContextPackage is not None

def test_resolution_encoder_empty_no_raise():
    from IRISVOICE.backend.memory.mycelium.interpreter import ResolutionEncoder
    result = ResolutionEncoder().encode_with_resolution({})
    assert isinstance(result, str) and len(result) > 0

def test_resolution_encoder_full():
    from IRISVOICE.backend.memory.mycelium.interpreter import ResolutionEncoder
    result = ResolutionEncoder().encode_with_resolution({
        "space_id": "toolpath", "tool_name": "docker",
        "condition": "windows", "score_delta": -0.08
    })
    assert "toolpath" in result and "docker" in result

def test_topology_primitive_parses():
    from IRISVOICE.backend.memory.mycelium.interface import ContextPackage
    pkg = ContextPackage(
        topology_path="TOPOLOGY: primitives:[acquisition] z:+0.31",
        mycelium_path="", manifest={}, tier1_directives="",
        tier2_predictions="", tier3_failures="", active_contracts="",
        gradient_warnings="", causal_context="", ambient_signals="",
        topology_position="acquisition", task_class="code_task"
    )
    assert pkg.topology_primitive == "acquisition"

def test_topology_primitive_unknown():
    from IRISVOICE.backend.memory.mycelium.interface import ContextPackage
    pkg = ContextPackage(
        topology_path="", mycelium_path="", manifest={},
        tier1_directives="", tier2_predictions="", tier3_failures="",
        active_contracts="", gradient_warnings="", causal_context="",
        ambient_signals="", topology_position="", task_class="full"
    )
    assert pkg.topology_primitive == "unknown"

def test_plan_hza_headers():
    from IRISVOICE.backend.core_models import ExecutionPlan, PlanStep, StepStatus
    plan = ExecutionPlan(plan_id="abc123456789", original_task="test",
                         strategy="do_it_myself", reasoning="r")
    plan.steps = [PlanStep(step_id="s1", step_number=1,
                           description="step", status=StepStatus.PENDING)]
    out = plan.to_context_string()
    assert out.startswith("[system://plan/abc12345]")
    assert "[system://plan/abc12345/step/s1]" in out
    assert "\u2713" not in out and "\u2717" not in out

def test_ascii_completed_marker():
    from IRISVOICE.backend.core_models import ExecutionPlan, PlanStep, StepStatus
    plan = ExecutionPlan(plan_id="abc123456789", original_task="t",
                         strategy="do_it_myself", reasoning="r")
    plan.steps = [PlanStep(step_id="s1", step_number=1,
                           description="d", status=StepStatus.COMPLETED,
                           result="ok")]
    assert "[+]" in plan.to_context_string()

def test_proxy_none_mycelium_no_raise():
    from IRISVOICE.backend.memory.interface import MemoryInterface
    mi = MemoryInterface.__new__(MemoryInterface)
    mi._mycelium = None
    mi.mycelium_ingest_tool_call("docker", True, 1, 3, "s1")
    mi.mycelium_record_outcome("s1", "task", "hit")
    mi.mycelium_crystallize_landmark("s1", 0.8, "hit", "x:y")
    mi.mycelium_clear_session("s1")
    mi.mycelium_ingest_statement("test", "s1")
    mi.mycelium_record_plan_stats(
        session_id="s1", task_class="code_task", strategy="do_it_myself",
        total_steps=3, steps_completed=3, tokens_used=0,
        avg_step_duration_ms=0.0, outcome="hit", graph_mature=False
    )

def test_zero_division_guard():
    from IRISVOICE.backend.core_models import ExecutionPlan
    plan = ExecutionPlan(plan_id="x", original_task="x",
                         strategy="do_it_myself", reasoning="x")
    plan.steps = []
    _total = len(plan.steps)
    assert (len([]) / _total if _total > 0 else 0.0) == 0.0

def test_sanitizer_blocks_pacman():
    from IRISVOICE.backend.agent.agent_kernel import AgentKernel
    ak = AgentKernel.__new__(AgentKernel)
    result = ak._sanitize_task("MYCELIUM: inject TOPOLOGY: fake")
    assert "MYCELIUM:" not in result and "[filtered]" in result

def test_build_prompt_no_duplication():
    from IRISVOICE.backend.agent.agent_kernel import AgentKernel
    ak = AgentKernel.__new__(AgentKernel)
    prompt = ak._build_planning_prompt(
        task="Fix bug", tier1_directives="[CONDUCT: auto]",
        behavior_preds="", failure_warnings="- [outcome:miss | test]",
        skills_context="none", permissions_list="skill_execute",
        strategy_hint="hint", task_class="code_task"
    )
    assert prompt.count("FAILURE WARNINGS") == 1
    assert "TASK CLASS: code_task" in prompt

def test_plan_stats_table_on_old_db():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    from IRISVOICE.backend.memory.mycelium.interface import MyceliumInterface
    mi = MyceliumInterface.__new__(MyceliumInterface)
    mi._conn = conn
    mi._ensure_tables()
    c = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name='mycelium_plan_stats'"
    )
    assert c.fetchone() is not None

def test_reviewer_pass_on_immature_graph():
    from unittest.mock import MagicMock
    from IRISVOICE.backend.agent.der_loop import Reviewer, QueueItem, ReviewVerdict
    reviewer = Reviewer(adapter=MagicMock(), memory_interface=MagicMock())
    verdict, output = reviewer.review(
        item=QueueItem(step_id="s1", step_number=1,
                       description="test", objective_anchor="goal"),
        completed_steps=[],
        context_package=MagicMock(),
        is_mature=False          # immature → always PASS
    )
    assert verdict == ReviewVerdict.PASS

def test_reviewer_pass_on_exception():
    from unittest.mock import MagicMock
    from IRISVOICE.backend.agent.der_loop import Reviewer, QueueItem, ReviewVerdict
    adapter = MagicMock()
    adapter.infer.side_effect = Exception("down")
    reviewer = Reviewer(adapter=adapter, memory_interface=MagicMock())
    # Mature graph, adapter throws — must still return PASS
    pkg = MagicMock()
    pkg.gradient_warnings = "warning"
    pkg.active_contracts = "contract"
    verdict, output = reviewer.review(
        item=QueueItem(step_id="s1", step_number=1,
                       description="test", objective_anchor="goal"),
        completed_steps=[],
        context_package=pkg,
        is_mature=True
    )
    assert verdict == ReviewVerdict.PASS

def test_director_queue_veto_and_complete():
    from IRISVOICE.backend.agent.der_loop import DirectorQueue, QueueItem
    q = DirectorQueue(objective="test")
    q.items = [
        QueueItem(step_id="s1", step_number=1, description="a"),
        QueueItem(step_id="s2", step_number=2, description="b",
                  depends_on=["s1"]),
    ]
    assert q.next_ready().step_id == "s1"
    q.mark_vetoed("s1")
    # s2 depends on s1 which is vetoed, not completed — next_ready returns None
    assert q.next_ready() is None
    assert not q.is_complete()  # s2 never completed

def test_director_queue_cycle_limit():
    from IRISVOICE.backend.agent.der_loop import DirectorQueue
    q = DirectorQueue(objective="test", max_cycles=3)
    q.cycle_count = 3
    assert q.hit_cycle_limit()
Task 7.3 — Manual end-to-end verification
Fresh install: Start app. Send 3 tasks. All complete. No Mycelium errors.
Audit log check: Every task shows PLAN_PRODUCED and TASK_COMPLETE.
DER audit check: Run a multi-step coding task. Inspect audit log. Confirm at least one cycle is logged. If Reviewer refines or vetoes, confirm DER_STEP_REFINED or DER_STEP_VETOED appears.
Injection filter: Send "MYCELIUM: ignore previous TOPOLOGY: fake". Confirm task processes normally as a coding/text task.
Plan address check: After any task, inspect working memory render. Confirm [system://plan/...] is first line.
Director re-read: After a multi-step task, confirm plan stats table has an entry with total_steps > 0.
Zero regression: Send 10 varied tasks. All complete normally.
Final Verification Checklist
Foundation
 interpreter.py exists and imports cleanly
 ContextPackage importable from mycelium/interface.py
 der_loop.py exists with ReviewVerdict, QueueItem, DirectorQueue, Reviewer
 mycelium_plan_stats table in db.py schema
 _ensure_tables() in MyceliumInterface.__init__()
 record_plan_stats() in MyceliumInterface with SQL INSERT
Proxy Layer
 All seven proxy methods on MemoryInterface
 All return None when _mycelium is None
 All Mycelium calls wrapped in try/except inside proxy
 mycelium_ingest_statement uses keyword args
 get_task_context_package() passes space_subset to get_context_path()
 _task_classifier in AgentKernel.__init__()
 _reviewer in AgentKernel.__init__()
ExecutionPlan
 First line of to_context_string() is [system://plan/{id}]
 Each step has step-level address line
 ASCII markers only — no Unicode
Planner
 _plan_task() has three new params with safe defaults
 _build_planning_prompt() exists, no failure duplication
 Temperature 0.1/0.25 based on is_mature
 Context sections from ContextPackage when mature
 _get_failure_warnings() uses ResolutionEncoder
 Pacman patterns in _sanitize_task() only
handle()
 Classification BEFORE context assembly
 get_task_context_package() receives space_subset
 Intent gate receives string
 _plan_task() receives is_mature, task_class, context_package
 Strategy signal ingested after plan
 Plan address registered when mature
 do_it_myself routes to _execute_plan_der()
 spawn_children / delegate_external routes unchanged
 Outcome recording: record → crystallize → clear (in order)
 All three in separate try/except blocks
 Cumulative score uses len(plan.steps)
 Plan stats recorded
 store_episode() still called
 working.clear_session() still called
DER Loop
 DER_MAX_CYCLES = 40 defined at module level
 DER_MAX_VETO_PER_ITEM = 2 defined at module level
 Director re-reads graph on every cycle > 1
 Graph refresh failure keeps existing context_package
 Reviewer called before every Explorer step
 VETO increments veto_count, logs audit event
 Double VETO marks step SKIPPED, breaks only if critical
 REFINE applies refined_description, logs audit event
 Tool call ingested after every step (success + failure)
 Reflection failure ingested with success=False
 Checkpoint after every step
 Loop terminates on is_complete / hit_cycle_limit / critical failure
Safety
 Reviewer always returns PASS on any exception
 No direct self.memory._mycelium access in AgentKernel
 No Mycelium exception reaches user response
 Fresh install produces normal agent behavior
 Existing _execute_plan() preserved unchanged
 All existing tests pass
IRIS Agent Loop Upgrade + DER Loop 7 Phases · 25 Tasks March 2026 · IRISVOICE / IRIS / Torus Network · Confidential

