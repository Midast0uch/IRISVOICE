CLAUDE.md — IRIS Project
Primary instructions for Claude Code.
This file never needs manual updates — hooks fetch live state from the database.
WHAT THIS PROJECT IS
IRIS is a local AI assistant: Python FastAPI backend, Next.js frontend, Tauri desktop.
The agent brain is a two-brain DER Loop (Director · Explorer · Reviewer) with a
trailing crystallizer. Memory is the Mycelium coordinate graph.

Single objective: Build IRIS until it can run a Tauri build without external tools.

STEP 0 — RUN THIS BEFORE ANYTHING ELSE
bash
python bootstrap/session_start.py
Reads the live coordinate database. Tells you current gate, permanent landmarks,
gradient warnings, active contracts, and where the last session left off.
Do not plan, do not write code, do not read files until you have run this.

STEP 1 — CHECK AVAILABLE WORK
bash
python bootstrap/agent_context.py
Shows what's available to build, what other agents are currently working on,
and relevant warnings. Use this to decide what to work on this session.

STEP 1.5 — NAVIGATE THE GRAPH BEFORE TOUCHING ANY FILE
The graph is not a log. It is a navigation instrument with three layers:

  SEMANTIC (what IS true — compressed, always current):
    python bootstrap/query_graph.py --file path/to/file.py
    Shows: topology primitive (CORE/ACQUIRING/EXPLORING/EVOLVING/ORBIT),
           Z-trajectory (direction of travel: ^ rising / v falling / -> stable),
           confidence, pheromone routes (strongest test-reinforced edges),
           and test coverage. Read this before touching the file.

  PHEROMONE ROUTES (where to go):
    python bootstrap/query_graph.py --routes
    Shows the globally strongest edges — paths reinforced by repeated passing tests.
    High weight = high confidence. Follow these first.

  HIGH-SIGNAL FAILURES (what not to repeat):
    python bootstrap/query_graph.py --failures
    Failures scored >= 0.50 are informative — they revealed architectural constraints.
    Read these before approaching an area that has failed before.

  EPISODIC (what happened — secondary):
    python bootstrap/query_graph.py --recent     # last N events
    python bootstrap/query_graph.py --summary    # full graph stats + crystallization
    python bootstrap/query_graph.py --agent X    # specific agent trail

To claim a work item for yourself:

bash
python bootstrap/agent_context.py --claim claude_main
For parallel sub-agents, each gets a unique ID:

bash
python bootstrap/agent_context.py --claim claude_sub_001
python bootstrap/agent_context.py --claim claude_sub_002
PLATFORM — WINDOWS
Use Windows-compatible commands. Never use bash syntax for the user to run.

USE:   python script.py
USE:   python -m pytest backend/tests/ -v
USE:   New-Item file.py -ItemType File          # create empty file
USE:   Get-ChildItem -Recurse -Filter "*.py"    # find files
USE:   Get-Content file.py | Select-Object -First 50
NEVER: touch / ls -la / grep -r / cat | head
THE FOUR GATES — NEVER SKIP
bash
# Always check current gate first:
python bootstrap/session_start.py
Gate 1: DER Loop + Director Mode     ← start here if not cleared
Gate 2: Skill Creator + UI Sync      ← locked until Gate 1 clears
Gate 3: MCP Integrations + Telegram  ← locked until Gate 2 clears
Gate 4: Free Range                   ← earned by clearing Gate 3
Details: bootstrap/GOALS.md Specs: agent_loop_tasks.md, director_mode_system.md, IRIS_Swarm_PRD_v9.md

HOW TO BUILD ANYTHING
READ spec → READ existing file → BUILD → RUN spec test → PASS → RECORD landmark
                                                        → FAIL → fix code → retry
The spec for every Gate 1 item is in agent_loop_tasks.md or director_mode_system.md. Read the relevant section before touching any file. The spec defines exactly what to build, what the acceptance criteria are, and what the test command is.

THE TEST RULE — ABSOLUTE, NON-NEGOTIABLE
Run the spec's requirements test against your implementation. Never write new tests to match your code. Never modify existing tests to make them pass.

The test is the requirement. If it fails, the implementation is incomplete.
Fix the code. The test does not change.

bash
# Example — run spec's test for der_loop:
python -m pytest backend/tests/test_der_loop.py -v

# PASS — record landmark:
python bootstrap/agent_context.py --complete ITEM_ID AGENT_ID success \
  --landmark "der_loop_foundation:DER loop classes built:backend/agent/der_loop.py:python -m pytest backend/tests/test_der_loop.py -v"

# FAIL — record warning, fix code:
python bootstrap/agent_context.py --complete ITEM_ID AGENT_ID failure \
  --warning "domain:ReviewVerdict import failed:circular import:moved to separate enums file"

STEP 2.5 — RECORD EVERY CODE ACTION (this builds the pheromone trail)
After editing a file:
  python bootstrap/record_event.py --type file_edit --file path/to/file.py --desc "what changed and why"

After creating a file:
  python bootstrap/record_event.py --type file_create --file path/to/new_file.py --desc "what this file does"

After a test passes:
  python bootstrap/record_event.py --type test_run --file backend/tests/test_foo.py --result pass --covers backend/foo.py

After a test FAILS but reveals something important (circular dep, missing contract, etc.):
  python bootstrap/record_event.py --type test_run --file backend/tests/test_foo.py --result fail \
    --score 0.70 --desc "what the failure revealed — why the next agent needs to know this"

  --score 0.70 marks this as a high-signal failure (score >= 0.50).
  It appears in --failures. The pheromone trail weakens on this edge, but the
  signal is preserved. This is not a log entry — it is a future-success candidate.

After an architectural decision:
  python bootstrap/record_event.py --type note --desc "why you chose X over Y — full reasoning"

  Notes encode WHY. The semantic layer compresses these into coordinates over time.
  The next agent reads this and does not re-litigate already-reasoned decisions.

PARALLEL SUB-AGENT PROTOCOL
Claude Code sub-agents can work on different Gate 1 items simultaneously.
The database is WAL-mode SQLite — safe for multiple concurrent processes.
Work claiming is atomic — two agents cannot take the same item.

Orchestrator (main agent) workflow:

bash
# See what's available and in progress:
python bootstrap/agent_context.py

# Poll for sub-agent completions:
python bootstrap/agent_context.py --poll

# After polling, check if gate advanced:
python bootstrap/session_start.py --gate
Sub-agent workflow:

bash
# Claim work:
python bootstrap/agent_context.py --claim claude_sub_001

# Read the spec file and test command printed by claim
# Build the feature
# Run the test
# Complete:
python bootstrap/agent_context.py --complete ITEM_ID claude_sub_001 success \
  --landmark "name:desc:file:test_command"

# Heartbeat for long tasks (every 60s prevents claim expiry):
python bootstrap/agent_context.py --heartbeat claude_sub_001
Gate constraint: No agent can claim Gate 2 items while Gate 1 has incomplete items. The database enforces this automatically. Agents self-organize through the work queue.

CRITICAL IMPLEMENTATION RULES
These come from the spec. Violating them breaks the architecture.

python
# 1. Every Mycelium call wrapped in try/except
try:
    self.memory.mycelium_ingest_tool_call(...)
except Exception:
    pass  # never blocks user response

# 2. Classification BEFORE context assembly (fixed order)
task_class, space_subset = self._task_classifier.classify(raw_input)  # FIRST
context_package, is_mature = self.memory.get_task_context_package(...) # SECOND

# 3. Reviewer always falls back to PASS on failure
except Exception:
    return ReviewVerdict.PASS, None  # never blocks Explorer

# 4. Safe defaults on all new _plan_task() parameters
def _plan_task(self, text, context,
               is_mature: bool = False,
               task_class: str = "full",
               context_package=None):

# 5. ASCII markers only — no Unicode (encoding errors on Windows)
"[+]"  "[x]"  "[~]"  "[ ]"  — never ✓ ✗

# 6. SPEC mode bypasses DER loop — routes to SpecEngine directly

# 7. Token budget not cycle count
DER_TOKEN_BUDGETS = {"implement":40000,"debug":30000,...}
DER_EMERGENCY_STOP = 200  # last resort only

# 8. Write lock on all Mycelium writes (two loops share one graph)
conn.execute("BEGIN IMMEDIATE")  # in _safe_write()
LOOP PREVENTION
Same error appearing twice in a row = change approach before the third attempt.

bash
# Before third attempt, record what's failing:
python bootstrap/mid_session_snapshot.py \
  --warn "space:what is looping:approach being repeated:what to try instead"
CONTEXT WINDOW MANAGEMENT
At ~50k tokens used:

bash
python bootstrap/mid_session_snapshot.py --progress "what was just completed"
Then condense. After condensing:

bash
python bootstrap/session_start.py --compact
At session end:

bash
python bootstrap/update_coordinates.py --auto \
  --tasks "comma,separated,tasks" \
  [--landmark "name:desc:file:test"] \
  [--warning "space:failure:approach:correction"]
SPEC FILE QUICK REFERENCE
DER loop classes/design:   agent_loop_design.md
DER loop requirements:     agent_loop_requirements.md → Req 23-27
DER loop build tasks:      agent_loop_tasks.md → Phases 1-6
Mode system (all):         director_mode_system.md → Parts 1-3
Mycelium ContextPackage:   agent_loop_design.md → Data Models
Proxy methods:             agent_loop_design.md → API Changes §1
Trailing crystallizer:     IRIS_Swarm_PRD_v9.md → Section 8
Write lock / WAL:          IRIS_Swarm_PRD_v9.md → Section 6.4
Token budget constants:    director_mode_system.md → Req 35
Gate sequence:             bootstrap/GOALS.md
SAFETY RAILS
Never delete/overwrite files without reading them first
Never git push, git reset --hard without explicit confirmation
Never pip install or npm install without checking first
Never hardcode credentials — environment variables only
Never access paths outside IRISVOICE/
Prefix risky commands with SAFE-CHECK: and wait for confirmation.

WHAT DONE LOOKS LIKE
cargo tauri build completes without errors
Built app launches
Task received through app's own interface
Response from IRIS backend — not Claude Code
Coordinate store transferred to IRISVOICE/data/memory.db (same schema, no migration)

The coordinate graph is complete when:
  python bootstrap/query_graph.py --summary shows:
    - Events recorded for every file touched
    - Pheromone edges with weight > 1.0 on all major test connections
    - Near-crystallization candidates on the most-used files
  python bootstrap/session_start.py shows MYCELIUM: confidence >= 0.85
  python bootstrap/query_graph.py --routes shows the architecture's settled paths

The three layers should all be present at completion:
  EPISODIC: code_events for every build action taken
  SEMANTIC: file_node confidence + Z-trajectory + edge weights across the graph
  LANDMARK: 17+ permanent landmarks — verified features that never decay

At that point, bootstrap/coordinates.db transfers to data/memory.db.
The application's Mycelium runtime reads the same graph the build agents wrote.
The build memory IS the app memory. Same schema. Same coordinate system. Always was.
IRIS — CLAUDE.md Hooks keep this file current. Database keeps the memory. Read spec. Build. Run spec test. Record what passes.

