CLAUDE.md
Primary instructions for Claude Code.
Hooks keep the coordinate graph current automatically — no manual DB updates needed.

---

WHAT THIS PROJECT IS
Read bootstrap/GOALS.md for the full roadmap, current gate, and domain breakdown.

---

STEP 0 — SESSION START (automatic via hook)
The UserPromptSubmit hook runs bootstrap/session_start.py on every prompt.
It loads current gate, landmarks, warnings, contracts, and auto-syncs any
git commits not yet in the coordinate graph.

You do not need to run session_start.py manually. The hook handles it.

If you need a fresh read mid-session:
  python bootstrap/session_start.py --compact

---

STEP 1 — CHECK AVAILABLE WORK
  python bootstrap/agent_context.py
Shows what is available to build, what is in progress, and relevant warnings.
Use this to decide what to work on this session.

---

STEP 1.5 — NAVIGATE THE GRAPH BEFORE TOUCHING ANY FILE
The graph is a navigation instrument with three layers:

  SEMANTIC (what IS true — compressed, always current):
    python bootstrap/query_graph.py --file path/to/file.py
    Shows: topology primitive (CORE/ACQUIRING/EXPLORING/EVOLVING/ORBIT),
           Z-trajectory (direction of travel: rising / falling / stable),
           confidence, pheromone routes, and test coverage.
    Read this before touching a file.

  PHEROMONE ROUTES (where to go next):
    python bootstrap/query_graph.py --routes
    Globally strongest edges — reinforced by repeated passing tests.
    High weight = high confidence. Follow these first.

  HIGH-SIGNAL FAILURES (what not to repeat):
    python bootstrap/query_graph.py --failures
    Failures scored >= 0.50 revealed architectural constraints.
    Read these before approaching an area that has failed before.

  EPISODIC (what happened — secondary):
    python bootstrap/query_graph.py --recent
    python bootstrap/query_graph.py --summary
    python bootstrap/query_graph.py --agent X

---

HOW TO BUILD ANYTHING
READ spec -> NAVIGATE graph -> READ file -> BUILD -> QUALITY CHECK -> RUN spec test
  PASS -> record landmark
  FAIL -> fix code, return to QUALITY CHECK. The test does not change.

THE QUALITY CHECK — REQUIRED BEFORE EVERY TEST RUN
Verify ALL of these before running the spec test:
  [ ] No unnecessary work in hot paths — loops, I/O, DB calls as few as needed
  [ ] Heavy imports are lazy — no ML model or GPU init at module level
  [ ] Error handling complete — every exception path has an explicit outcome
  [ ] Resources cleaned up — file handles, connections, subprocesses closed
  [ ] No shared mutable state across sessions or concurrent requests
  [ ] Memory footprint bounded — no unbounded caches or infinite queues
  [ ] Async/sync boundary correct — blocking calls not in async hot paths
  [ ] Logging structured — context identifier in every log line
  [ ] Nothing in this file can crash and block a user response

A passing test on unoptimized code is not done. Quality check is not optional.

THE TEST RULE — ABSOLUTE
Run the spec's test against your implementation.
Never write new tests to match your code.
Never modify existing tests to make them pass.
The test is the requirement.

  # Complete a work item after passing:
  python bootstrap/agent_context.py --complete ITEM_ID AGENT_ID success \
    --landmark "name:description:file/path.py:test command"

  # Record a failure that revealed something:
  python bootstrap/agent_context.py --complete ITEM_ID AGENT_ID failure \
    --warning "space:what failed:approach tried:what worked instead"

---

RECORDING CODE ACTIONS (builds the pheromone trail)

Git commits are auto-recorded by session_start.py on every prompt.
You only need to manually record events that are NOT part of a commit:

  # After editing a file (if not yet committed):
  python bootstrap/record_event.py --type file_edit --file path/to/file.py --desc "what changed and why"

  # After creating a file:
  python bootstrap/record_event.py --type file_create --file path/to/file.py --desc "what this file does"

  # After a test passes:
  python bootstrap/record_event.py --type test_run --file tests/test_foo.py --result pass --covers src/foo.py

  # After a test fails but reveals something important:
  python bootstrap/record_event.py --type test_run --file tests/test_foo.py --result fail \
    --score 0.70 --desc "what the failure revealed"
  # --score 0.70 = high-signal failure (>= 0.50). Appears in --failures.
  # Pheromone trail weakens on this edge but the signal is preserved.

  # After an architectural decision:
  python bootstrap/record_event.py --type note --desc "why you chose X over Y"
  # Notes encode WHY. The semantic layer compresses these over time.

---

PARALLEL SUB-AGENT PROTOCOL
The database is WAL-mode SQLite — safe for concurrent processes.
Work claiming is atomic — two agents cannot take the same item.

  # Orchestrator: see what is available and in progress
  python bootstrap/agent_context.py
  python bootstrap/agent_context.py --poll   # check sub-agent completions

  # Sub-agent workflow:
  python bootstrap/agent_context.py --claim agent_001
  # ... build the feature ...
  python bootstrap/agent_context.py --complete ITEM_ID agent_001 success \
    --landmark "name:desc:file:test_command"
  python bootstrap/agent_context.py --heartbeat agent_001  # every 60s on long tasks

---

CONTEXT WINDOW MANAGEMENT

At ~50k tokens used:
  python bootstrap/mid_session_snapshot.py --progress "what was just completed"
Then condense. After condensing, the hook re-runs session_start automatically.

Loop prevention — same error twice in a row = change approach:
  python bootstrap/mid_session_snapshot.py \
    --warn "space:what is looping:approach being repeated:what to try instead"

Session end is handled automatically by the Stop hook:
  - Saves mid-session snapshot
  - Runs update_coordinates.py --auto to close the session in the graph
You do not need to run update_coordinates.py manually.

---

SAFETY RAILS
Never delete or overwrite files without reading them first.
Never git push or git reset --hard without explicit user confirmation.
Never pip install or npm install without checking first.
Never hardcode credentials — environment variables only.
Prefix risky commands with SAFE-CHECK: and wait for confirmation.

---

WHAT DONE LOOKS LIKE

The coordinate graph is complete when:
  python bootstrap/query_graph.py --summary shows:
    - Events recorded for every file touched
    - Pheromone edges with weight > 1.0 on major test connections
    - Near-crystallization candidates on the most-used files
  python bootstrap/session_start.py shows confidence >= 0.85
  python bootstrap/query_graph.py --routes shows the architecture's settled paths

The three layers should all be present:
  EPISODIC:  code_events for every build action
  SEMANTIC:  file_node confidence + Z-trajectory + edge weights
  LANDMARK:  permanent landmarks for every verified feature

When the project reaches its completion condition (defined in GOALS.md),
bootstrap/coordinates.db transfers to the application's runtime memory store.
Same schema. No migration. The build memory becomes the app memory.

---

SPEC / DOMAIN QUICK REFERENCE
Production roadmap:     bootstrap/GOALS.md
Graph queries:          python bootstrap/query_graph.py --help
Work queue:             python bootstrap/agent_context.py --help
Event recording:        python bootstrap/record_event.py --help
Session update:         python bootstrap/update_coordinates.py --help
PiN (Primordial Info Nodes): python bootstrap/pin.py --help
Landmark bridges:            python bootstrap/pin.py --bridges
