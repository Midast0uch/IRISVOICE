CLAUDE.md
Primary instructions for Claude Code.
MCM SDK keeps the coordinate graph current automatically — no manual DB updates needed.

---

WHAT THIS PROJECT IS
Read bootstrap/GOALS.md for the full roadmap, current gate, and domain breakdown.

---

STEP 0 — SESSION START (automatic via MCM SDK)
The MCM plugin runs get_session() automatically on every prompt.
It loads current gate, landmarks, warnings, contracts, and NBL state.

You do not need to run get_session() manually unless you want a fresh read.

If you need a fresh read mid-session:
  get_session()

---

STEP 1 — CHECK AVAILABLE WORK
  claim_work()
or
  get_session() → check pos 15 (work items available)
Shows what is available to build, what is in progress, and relevant warnings.
Use this to decide what to work on this session.

---

STEP 1.5 — NAVIGATE THE GRAPH BEFORE TOUCHING ANY FILE
The graph is a navigation instrument with three layers:

  SEMANTIC (what IS true — compressed, always current):
    navigate(file_path)
    Shows: topology primitive (CORE/ACQUISITION/EXPLORATION/EVOLUTION/ORBIT),
           Z-trajectory (direction of travel: rising / falling / stable),
           confidence, pheromone routes, and test coverage.
    Read this before touching a file.

  PHEROMONE ROUTES (where to go next):
    get_session() → check topology in state
    Globally strongest edges — reinforced by repeated passing tests.
    High weight = high confidence. Follow these first.

  HIGH-SIGNAL FAILURES (what not to repeat):
    get_session() → check warnings
    Failures scored >= 0.50 revealed architectural constraints.
    Read these before approaching an area that has failed before.

  EPISODIC (what happened — secondary):
    pin_search(query)
    mcm_recall(query)

---

HOW TO BUILD ANYTHING
READ spec -> NAVIGATE graph -> READ file -> BUILD -> QUALITY CHECK -> RUN spec test
  PASS -> record_test(file, 'pass') + pin_add(title, 'decision')
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
  complete_task(item_id, agent_id, 'success')
  # Then add landmark:
  pin_add(title='feature_name', pin_type='decision', file_refs=['file.py'])

  # Record a failure that revealed something:
  complete_task(item_id, agent_id, 'failure')
  # Then add warning:
  health.add_warning(space='domain', description='what failed', approach='tried', correction='what worked')

---

RECORDING CODE ACTIONS (builds the pheromone trail)

Git commits are auto-recorded by the MCM plugin on every prompt.
You only need to manually record events that are NOT part of a commit:

  # After editing a file (if not yet committed):
  record_edit(file_path)

  # After creating a file:
  record_create(file_path)

  # After a test passes:
  record_test(test_file, test_name, outcome='pass', covers=['src/foo.py'])

  # After a test fails but reveals something important:
  record_test(test_file, test_name, outcome='fail', description='what the failure revealed')

  # After an architectural decision:
  pin_add(title='Decision: chose X over Y', pin_type='decision', content='why')
  # Notes encode WHY. The semantic layer compresses these over time.

---

PARALLEL SUB-AGENT PROTOCOL
The database is WAL-mode SQLite — safe for concurrent processes.
Work claiming is atomic — two agents cannot take the same item.

  # Orchestrator: see what is available and in progress
  get_session() → check work_items in state

  # Sub-agent workflow:
  claim_work(agent_id='agent_001')
  # ... build the feature ...
  complete_task(item_id, agent_id='agent_001', status='success')
  # heartbeat is handled automatically by the SDK

---

CONTEXT WINDOW MANAGEMENT

At ~50k tokens used or when NBL pos 28 > 800:
  mcm_compress(active_task='what was just completed', active_files=['file1.py', 'file2.py'])
Then condense. After condensing, call mcm_recall(query) to recover knowledge.

Loop prevention — same error twice in a row = change approach:
  health.add_warning(space='conduct', description='loop detected', approach='repeated', correction='try different approach')

Session end is handled automatically by the MCM lifecycle protocol.
You do not need to run session cleanup manually.

---

SAFETY RAILS
Never delete or overwrite files without reading them first.
Never git push or git reset --hard without explicit user confirmation.
Never pip install or npm install without checking first.
Never hardcode credentials — environment variables or OS keyring only.
Prefix risky commands with SAFE-CHECK: and wait for confirmation.

---

WHAT DONE LOOKS LIKE

The coordinate graph is complete when:
  get_session() shows:
    - Events recorded for every file touched
    - Pheromone edges with weight > 1.0 on major test connections
    - Near-crystallization candidates on the most-used files
  NBL pos 18-24 (coordinates) show confidence >= 0.85
  Topology shows CORE files with stable Z-trajectory

The three layers should all be present:
  EPISODIC:  code_events for every build action
  SEMANTIC:  file_node confidence + Z-trajectory + edge weights
  LANDMARK:  permanent landmarks for every verified feature

When the project reaches its completion condition (defined in GOALS.md),
data/databases/coordinates.db transfers to the application's runtime memory store.
Same schema. No migration. The build memory becomes the app memory.

---

SPEC / DOMAIN QUICK REFERENCE
Production roadmap:     bootstrap/GOALS.md
Graph queries:          get_session() or navigate(file)
Work queue:             claim_work() / get_session()
Event recording:        record_edit(), record_test(), record_create()
Session update:         handled automatically by SDK lifecycle
PiN (Primordial Info Nodes): pin_add(), pin_search(), pin_list()
Landmark bridges:            pin_link()
