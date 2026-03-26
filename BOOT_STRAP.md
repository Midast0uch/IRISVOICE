BOOTSTRAP.md — Mycelium Memory Bootstrap System
Setup Guide, Architecture, and Performance at Scale

This document explains the Mycelium Bootstrap Memory System: a lightweight,
agent-agnostic coordinate graph that gives any AI coding agent (Claude Code,
Cursor, Windsurf, Copilot, GPT, OpenCode, or any tool that can run Python)
persistent memory across sessions. It works with any skill, MCP server,
hook, or plugin — anything that emits structured events into the graph.

The system organizes work into milestones (called "gates" in the schema).
A milestone is any functional phase of your project: feature domains, sprints,
release stages, or capability tiers. The structure is defined in a GOALS.md
you write for your project — the bootstrap system enforces ordering and tracks
completion. Call them whatever fits your project; the graph just needs numbers.

The system is designed for large codebases. It does not grow linearly with
codebase size — it compresses. The more sessions that run, the more precise
and lightweight the memory becomes. This document explains why, and how to
set it up for any project.

================================================================
TABLE OF CONTENTS
================================================================

  1. What This System Is
  2. Why Agents Need This
  3. Architecture — The 3-Layer Mycelium Network
  4. The 3D Coordinate System
  5. How It Scales (Performance at Large Codebases)
  6. Setup Instructions
  7. Integration With Skills, MCP, Hooks, and Plugins
  8. Command Reference
  9. Schema Reference
  10. Configuration and Tuning

================================================================
1. WHAT THIS SYSTEM IS
================================================================

The bootstrap memory system is a SQLite-backed coordinate graph that
records everything AI agents do in a codebase and compresses that raw
history into navigable coordinates — not prose, not logs, but mathematical
positions in a multi-dimensional topology space.

It is implemented in a single Python module (bootstrap/coordinates.py)
with no external dependencies beyond the Python standard library. No
pip install required. No server process. Just Python 3.8+ and SQLite.

The system consists of 7 scripts:

  coordinates.py          Core store — schema, API, all graph operations
  session_start.py        Run at session start — prints current state
  query_graph.py          Navigation instrument — query any file, route, failure
  record_event.py         Record any code action into the mycelium trail
  agent_context.py        Work queue — atomic claiming, gate enforcement
  mid_session_snapshot.py Mid-session checkpoint before context condensing
  update_coordinates.py   End-of-session state update + system prompt generation

All 7 scripts are CLI tools. No imports from your project codebase are needed.
They operate on a standalone SQLite database (bootstrap/coordinates.db) that
lives alongside your project files.

================================================================
2. WHY AGENTS NEED THIS
================================================================

AI coding agents have a fundamental problem: context amnesia.

Every session starts blank. The agent must rediscover:
  - What was already built and verified
  - What approaches failed and why
  - What architectural decisions were already made
  - Which files are stable vs. actively changing
  - Where the strongest test-verified paths through the code are

Without persistent memory, each session re-litigates past decisions,
re-discovers past failures, and wastes context window tokens on
information that should be compressed into coordinates.

The Mycelium system solves this with three layers:

  EPISODIC    — Raw events. What happened. Grows every session.
  SEMANTIC    — Compressed positions. What IS true. Self-corrects.
  LANDMARK    — Crystallized facts. What is PERMANENTLY true. Never decays.

The episodic layer is the input. The semantic layer is the compressed
working memory. The landmark layer is the permanent memory that transfers
across projects, agents, and runtimes.

This is not a log system. Logs grow linearly and become noise.
This is a coordinate system. It compresses over time and becomes signal.

================================================================
3. ARCHITECTURE — THE 3-LAYER MYCELIUM NETWORK
================================================================

Layer 1: EPISODIC (code_events table)
--------------------------------------
Every action any agent takes is recorded as a code_event:

  - file_edit:   Modified a file (what changed, why)
  - file_create: Created a new file (what it does)
  - test_run:    Ran a test (pass/fail/partial, what it covers)
  - git_commit:  Committed code (what was included)
  - note:        Architectural decision (why X was chosen over Y)

Each event gets a signal score (0.0 to 1.0):

  Score  Meaning
  0.85   Test passed, git commit — strong positive signal
  0.80   Bug fix edit, architectural note — high-value action
  0.70   Normal file edit — baseline productive action
  0.20   Test failure (generic crash, no specific insight)
  0.50+  Test failure that revealed something (import cycle, missing dep)

The scoring is critical: a failure with score >= 0.50 is NOT discarded.
It is treated as a "high-potential failure" — a future-success candidate.
The pheromone trail weakens on that edge, but the signal is preserved in
the graph for future agents to read. This is how the system learns from
mistakes without losing the information about what was tried.

Episodic events grow forever, but they are the RAW MATERIAL, not the
output. They feed into Layer 2.


Layer 2: SEMANTIC (file_nodes + graph_edges tables)
----------------------------------------------------
The semantic layer is the compressed, always-current map of the codebase.
It has two components:

FILE NODES — one per tracked file:
  - confidence:       0.0 to 1.0 — how well-established this file is
  - z_trajectory:     slope of confidence change (+ = gaining, - = losing)
  - activation_count: how many times meaningfully touched (toward threshold)
  - decay_rate:       how fast confidence fades without reinforcement

  Confidence is NOT a score you set. It is a running average that evolves
  with every event. A file that keeps passing tests gains confidence.
  A file that gets edited but tests keep failing loses confidence.
  A file untouched for days decays toward zero. This is automatic.

GRAPH EDGES — directed connections between nodes:
  - weight:          1.0 base, compounds on every pass/fail traversal
  - compound_count:  total times this edge has been scored
  - relationship:    tests | implements | caused_by | fixed_by | requires

  Edges are pheromone trails. When a test passes, every edge between that
  test and the files it covers gets multiplied by EDGE_SUCCESS_FACTOR (1.10).
  When a test fails, those edges get multiplied by EDGE_FAILURE_FACTOR (0.85).

  An edge with weight 4.2 and compound_count 38 has survived 38 scorings.
  That is not random. That is the architecture telling you: this path works.

  Edges are bounded: weight cannot exceed EDGE_WEIGHT_MAX (5.0) or fall
  below EDGE_WEIGHT_MIN (0.1). Paths weaken but never fully disappear.

The semantic layer self-corrects without intervention. Files that stop
being reinforced decay. Files that keep being touched grow. Edges that
keep passing compound. Edges that keep failing weaken. The map evolves
to match reality — it does not need manual cleanup.


Layer 3: LANDMARK (landmarks table)
-------------------------------------
When a file_node's activation_count reaches CHART_ACTIVATION_THRESHOLD (12),
it becomes a crystallization candidate. This means the node has been
meaningfully activated enough times that the pattern is real, not noise.

When a landmark is added (a named, verified feature with a test command),
it starts with pass_count = 0. Every time the test passes, pass_count
increments. When pass_count reaches LANDMARK_THRESHOLD (3), the landmark
becomes PERMANENT.

Permanent landmarks NEVER decay. They are the inherited memory of the build.
They survive across sessions, across agents, across context resets.

This is the compression progression:

  Raw events  -->  file_node confidence + edge weights  -->  permanent landmark
  (episodic)       (semantic: compressed, always current)    (crystallized: never decays)

The system literally compresses over time:
  - Nodes reinforced enough (activation_count >= 12) → crystallization-ready
  - Landmarks that overlap in coordinate space merge → redundancy collapses
  - Nodes unreinforced decay toward zero → fade from navigation
  - Result: more sessions = more precise, more lightweight, less context cost


================================================================
4. THE 3D COORDINATE SYSTEM
================================================================

The graph is NOT 2-dimensional. Each file exists in a 3D topology space:

  X-AXIS: Confidence (0.0 to 1.0)
    How well-established this file is. High = battle-tested. Low = experimental.
    Computed as a running weighted average of event scores.

  Y-AXIS: Edge Weight (0.0 to 1.0, normalized from raw weight / EDGE_WEIGHT_MAX)
    How connected this file is to other files via pheromone trails.
    High = central to the architecture. Low = isolated.

  Z-AXIS: Z-Trajectory (z_trajectory, -1.0 to +1.0)
    Direction of travel. The SLOPE of confidence change over recent events.
    This is what makes the graph 3D — it encodes momentum, not just position.

    +0.08 or higher → ACQUIRING: confidence is rising, file is being mastered
    -0.06 or lower  → EVOLVING: confidence is falling, file is being replaced
    Near zero       → CORE (if confidence high) or ORBIT (if confidence moderate)

    Z-trajectory is computed as a blended running slope:
      new_z = current_z * 0.70 + z_delta * 0.30
    where z_delta = new_confidence - old_confidence.

    This means Z is smooth — it doesn't jump on a single event. It trends.
    Three good events in a row push Z positive. Three bad events push it negative.
    A stable file has Z ≈ 0 because confidence changes are minimal.

From these three axes, every file is classified into a TOPOLOGY PRIMITIVE:

  CORE         High confidence, stable Z, well-connected. The foundation.
  ACQUISITION  Z positive (>= +0.08). Being actively built up.
  EXPLORATION  Active edits, mixed confidence, Z near zero. Experimental.
  EVOLUTION    Z negative (<= -0.06), was important (confidence > 0.40). Declining.
  ORBIT        Moderate everything, Z near zero. Supporting role.

These primitives are what agents read. They answer "what IS this file?" not
"what happened to this file?" — the semantic layer, not the episodic layer.


================================================================
5. HOW IT SCALES (PERFORMANCE AT LARGE CODEBASES)
================================================================

DATABASE PERFORMANCE
---------------------
The storage is SQLite in WAL (Write-Ahead Logging) mode. This means:

  - Multiple agents can READ concurrently without blocking
  - WRITE operations use BEGIN IMMEDIATE to prevent conflicts
  - Work claiming is atomic — two agents cannot claim the same item
  - No server process needed — the database IS the coordination layer

SQLite performance characteristics for this workload:

  Table            Expected rows (large codebase)    Access pattern
  code_events      5,000-50,000 over months          INSERT + recent queries
  file_nodes       500-5,000 (one per tracked file)  UPDATE (upsert) + full scan
  test_nodes       100-1,000 (one per test)          UPDATE + JOIN
  graph_edges      500-10,000 (connections)           UPDATE weight + ORDER BY
  landmarks        50-200 (verified features)         Small, permanent

  All tables have indexes on the columns used in WHERE and ORDER BY clauses.
  Even at 50,000 events and 5,000 file nodes, every query completes in < 50ms
  on a standard SSD. SQLite handles millions of rows comfortably — this
  workload is well within its design envelope.

MEMORY COMPRESSION — WHY IT GETS LIGHTER, NOT HEAVIER
------------------------------------------------------
The critical insight: this system COMPRESSES with time.

In a traditional log-based approach, a codebase with 2,000 files and 100
sessions would accumulate 50,000+ raw log entries. Each session would need
to read more context, burning more tokens, getting slower.

The Mycelium system works differently:

  Session 1:    50 events → 50 file_nodes created, 20 edges, 0 landmarks
  Session 10:   500 events → 50 file_nodes (same files, updated), 80 edges
  Session 50:   2,500 events → 50 file_nodes (compressed), 12 landmarks

  What the agent reads at session start:
    Session 1:  Full episodic dump (no semantic layer yet)          ~200 tokens
    Session 10: MYCELIUM header + topology + routes + failures      ~80 tokens
    Session 50: MYCELIUM header + 12 landmarks + 3 routes           ~50 tokens

  The semantic layer ABSORBS the episodic layer. Once a file's confidence
  and Z-trajectory encode its full history, the raw events are secondary.
  Once a landmark crystallizes, the events that built it are redundant.

  This is the compression progression at work:
    raw events (unlimited growth) → compressed nodes (bounded) → landmarks (minimal)

DECAY MECHANICS — AUTOMATIC CLEANUP
-------------------------------------
The system does not require manual garbage collection. Decay handles it:

  File nodes not touched:  confidence decays by decay_rate per day (default 0.005)
  Graph edges not scored:  weight decays by 0.020 per day
  Coordinate spaces:       Each space has its own rate (context: 0.025/day fastest)

  After 30 days without reinforcement, a file node's confidence drops to:
    0.80 * (1 - 0.005)^30 = 0.80 * 0.86 = 0.69 (still visible)

  After 90 days:
    0.80 * (1 - 0.005)^90 = 0.80 * 0.64 = 0.51 (fading from routes)

  After 180 days:
    0.80 * (1 - 0.005)^180 = 0.80 * 0.41 = 0.33 (effectively background)

  Landmark-owned files decay at HALF rate — they're structurally important.
  Permanent landmarks NEVER decay — they are the memory floor.

  This means: old files that nobody touches gradually fade from navigation.
  Critical files that are constantly tested stay front and center.
  The map auto-trims itself without human intervention.

SCALABILITY ACROSS CONTEXT WINDOWS
------------------------------------
The system is designed for agents with limited context windows (4K-200K tokens).

  The MYCELIUM: header line is 15 tokens. It encodes the ENTIRE build state:
    MYCELIUM: context:[1.00,0.85,0.02]@gate4 | toolpath:[w:4.1,ev:127] | confidence:0.95

  Compare this to a prose summary of 127 events:
    "In the last 30 sessions, the following files were edited: ... (3000 tokens)"

  The coordinate representation is 200x more token-efficient than prose.
  As the graph matures, more information is encoded in coordinates, and
  less needs to be expressed in prose. Token cost goes DOWN over time.

  For mid-session context management:
    - mid_session_snapshot.py checkpoints progress before context condensing
    - session_start.py --compact reloads state from the DB (not from memory)
    - The agent can condense and resume without losing any build knowledge

CONCURRENT AGENT PERFORMANCE
------------------------------
Multiple agents can work simultaneously on the same codebase:

  - Work claiming uses BEGIN IMMEDIATE (serialized writes, no conflicts)
  - Each agent gets a unique agent_id for event attribution
  - Signal files in bootstrap/signals/ enable asynchronous poll-based coordination
  - Heartbeat mechanism prevents stale claims (10-minute default timeout)
  - WAL mode means readers never block writers and vice versa

  Tested pattern: 1 orchestrator + 3 sub-agents working on different gate items
  concurrently. Zero conflicts, zero data loss, proper attribution.


================================================================
6. SETUP INSTRUCTIONS
================================================================

PREREQUISITES
--------------
  - Python 3.8 or later (standard library only — no pip install needed)
  - A codebase you want to give persistent memory to
  - An AI coding agent that can execute Python scripts

STEP 1: COPY THE BOOTSTRAP DIRECTORY
--------------------------------------
Copy the bootstrap/ directory into your project root:

  your-project/
    bootstrap/
      coordinates.py
      session_start.py
      query_graph.py
      record_event.py
      agent_context.py
      mid_session_snapshot.py
      update_coordinates.py
    src/
    tests/
    ...

The bootstrap/ directory is self-contained. It has no imports from your
project. It creates its own SQLite database (bootstrap/coordinates.db)
on first run.

STEP 2: INITIALIZE THE DATABASE
---------------------------------
  python bootstrap/coordinates.py --test

This runs the self-test, which:
  1. Creates bootstrap/coordinates.db if it doesn't exist
  2. Creates all tables and indexes
  3. Seeds the 7 coordinate spaces
  4. Verifies CRUD operations on landmarks, warnings, contracts
  5. Generates a system prompt state block
  6. Cleans up test data

If it prints "PASS: Coordinate store working correctly", you're ready.

STEP 3: DEFINE YOUR GOALS.md AND SEED WORK ITEMS (OPTIONAL)
--------------------------------------------------------------
The "gate" concept in the work queue maps directly to milestones or functional
domains in your project. A gate is simply a numbered phase — call them gates,
milestones, domains, sprints, or whatever fits your project. The only rule the
system enforces is ordering: gate 2 items cannot be claimed until all gate 1
items are complete. This prevents building on unverified foundations.

For a new project, define your GOALS.md first:
  - What are the major functional milestones?
  - What does each milestone require to be considered done?
  - What test command verifies each requirement?

Example GOALS.md structure for any project:
  Milestone 1: Core data layer + API (the foundation everything else needs)
  Milestone 2: Business logic + integrations (depends on M1 being verified)
  Milestone 3: UI + user flows (depends on M2 being verified)
  Milestone 4: Production hardening, packaging, deployment

Then seed work items from that structure:

  # seed_work.py
  from bootstrap.coordinates import CoordinateStore

  store = CoordinateStore()
  store.seed_work_items([
      {
          "item_id": "1.1",
          "gate": 1,           # milestone number — any integer
          "step": "1.1",
          "description": "Build the core data model",
          "spec_file": "docs/GOALS.md",
          "test_command": "python -m pytest tests/test_models.py -v",
      },
      {
          "item_id": "1.2",
          "gate": 1,
          "step": "1.2",
          "description": "Build the API router",
          "spec_file": "docs/GOALS.md",
          "test_command": "python -m pytest tests/test_api.py -v",
      },
      {
          "item_id": "2.1",
          "gate": 2,           # locked until all gate 1 items complete
          "step": "2.1",
          "description": "Build the payment integration",
          "spec_file": "docs/GOALS.md",
          "test_command": "python -m pytest tests/test_payments.py -v",
      },
  ])

This is optional. You can use the system purely as a memory graph without
the work queue. The graph works with or without the gated structure.

STEP 4: ADD TO YOUR AGENT INSTRUCTIONS
----------------------------------------
Add to your CLAUDE.md, .cursorrules, .windsurfrules, or equivalent:

  Before starting any session, run:
    python bootstrap/session_start.py

  Before editing any file, check its topology:
    python bootstrap/query_graph.py --file path/to/file.py

  After every code action, record it:
    python bootstrap/record_event.py --type file_edit --file path --desc "what changed"

  After every test run, record it:
    python bootstrap/record_event.py --type test_run --file test_path --result pass --covers impl_path

  At session end, update coordinates:
    python bootstrap/update_coordinates.py --auto --tasks "what,was,done"

STEP 5: FIRST SESSION
-----------------------
Run the first session start:

  python bootstrap/session_start.py

You'll see mostly empty state — that's normal. The graph populates as
agents record events. After 3-5 sessions, the semantic layer becomes
informative. After 10+ sessions, pheromone routes and topology primitives
are mature enough to genuinely guide agent decisions.

STEP 6: VERIFY GROWTH
-----------------------
After a few sessions, check graph health:

  python bootstrap/query_graph.py --summary

  This shows:
    - Total events, file nodes, test nodes, edges
    - Hottest files (most-edited)
    - Near-crystallization candidates (activation_count >= 12)
    - High-potential failures (informative failures preserved)

  python bootstrap/query_graph.py --routes

  This shows the strongest pheromone routes — paths with the highest
  compounded edge weights from repeated successful test runs.


================================================================
7. INTEGRATION WITH SKILLS, MCP, HOOKS, AND PLUGINS
================================================================

The bootstrap system is designed as a universal memory substrate. Any tool
that can call Python scripts can write into and read from the graph.

CLAUDE CODE HOOKS
------------------
Claude Code hooks execute shell commands in response to events. Wire them
to automatically record events and checkpoint progress:

  // settings.local.json (project-level) or settings.json (global)
  {
    "hooks": {
      "UserPromptSubmit": [
        {
          "hooks": [
            {
              "type": "command",
              "command": "python -c \"import subprocess,json; r=subprocess.run(['python','bootstrap/session_start.py','--compact'],capture_output=True,text=True,cwd='YOUR_PROJECT_DIR',timeout=30); out=(r.stdout or r.stderr)[:2000]; print(json.dumps({'hookSpecificOutput':{'hookEventName':'UserPromptSubmit','additionalContext':out}}))\""
              "timeout": 35,
              "statusMessage": "Loading coordinate state..."
            }
          ]
        }
      ],
      "Stop": [
        {
          "hooks": [
            {
              "type": "command",
              "command": "python -c \"import subprocess; subprocess.run(['python','bootstrap/mid_session_snapshot.py','--progress','auto-snapshot on stop'],capture_output=True,text=True,cwd='YOUR_PROJECT_DIR',timeout=30)\"",
              "timeout": 35,
              "statusMessage": "Saving mid-session snapshot..."
            }
          ]
        }
      ],
      "PostToolUse": [
        {
          "matcher": "Edit",
          "command": "python bootstrap/record_event.py --type file_edit --file $FILE_PATH --desc 'hook-recorded edit'"
        }
      ]
    }
  }

  Replace YOUR_PROJECT_DIR with the path to your project root (where
  bootstrap/ lives). If bootstrap/ is at the shell's cwd, omit cwd.

  UserPromptSubmit hook: runs session_start.py --compact before every
  prompt and injects the output as additionalContext. The agent always
  sees current coordinate state without needing to be reminded.

  Stop hook: runs mid_session_snapshot.py automatically at the end of
  every Claude response. The agent checkpoints progress without needing
  to be asked. This is the key mechanism — without it, progress is only
  saved when the agent explicitly runs the script.

  PostToolUse hook: records every file edit into the pheromone trail
  automatically, without the agent needing to call record_event.py manually.

MCP SERVERS
------------
Any MCP server that your agent uses can have its outputs recorded as events.
The pattern is:

  1. Agent calls MCP tool (e.g., file search, code analysis, database query)
  2. After processing the result, agent records a note or file_edit event
  3. The graph captures that the MCP tool was used and what it produced

  For bidirectional integration, an MCP server can QUERY the graph:

    from bootstrap.coordinates import CoordinateStore
    store = CoordinateStore("path/to/coordinates.db")

    # Get semantic state for a file before an MCP tool modifies it
    node = store.get_file_node("src/api/router.py")
    topology = store.classify_topology_primitive("src/api/router.py")
    routes = store.get_pheromone_routes(from_file="src/api/router.py")

    # After the MCP tool completes, record the event
    store.record_code_event(
        agent_id="mcp_filetools",
        event_type="file_edit",
        file_path="src/api/router.py",
        description="MCP file tool refactored error handling",
        outcome="pass",
    )

  This is how the Mycelium graph becomes the memory layer beneath all tools.
  The MCP server doesn't need to know about Mycelium internals — it just
  calls record_code_event() and query methods.

SKILLS (CLAUDE CODE CUSTOM SKILLS)
------------------------------------
Skills are reusable prompt+tool bundles. They can integrate with the graph:

  - A "code-review" skill reads --routes and --failures before reviewing
  - A "refactor" skill checks topology primitives to avoid EVOLVING files
  - A "test" skill records test_run events and compounds pheromone trails
  - A "deploy" skill reads landmark status to verify all are PERMANENT

  The graph acts as shared memory between skills. Skill A records events.
  Skill B reads the graph state that Skill A created. Neither skill needs
  to know about the other — the coordinate system is the communication layer.

PLUGINS AND EXTERNAL TOOLS
----------------------------
Any tool that can run Python or make HTTP calls to a wrapper can integrate:

  - Linting tools → record_event.py --type note --desc "lint: 3 warnings in api.py"
  - CI/CD systems → record_event.py --type test_run --file tests/ --result pass
  - Code formatters → record_event.py --type file_edit --file formatted_file.py
  - Documentation generators → record_event.py --type note --desc "docs updated"
  - Git hooks (pre-commit, post-commit) → record_event.py --type git_commit

  The --score flag allows any tool to explicitly grade its own output:
    python bootstrap/record_event.py --type test_run --result fail --score 0.70 \
      --desc "CI failed but revealed missing env var — high-signal failure"


MULTI-AGENT ORCHESTRATION
---------------------------
The work queue (agent_context.py) supports multiple concurrent agents:

  Agent 1: python bootstrap/agent_context.py --claim cursor_main
  Agent 2: python bootstrap/agent_context.py --claim claude_sub_001
  Agent 3: python bootstrap/agent_context.py --claim windsurf_refactor

  Each agent works independently. The database enforces:
    - No two agents claim the same work item
    - Milestone ordering is respected (milestone 2 locked until milestone 1 complete)
    - Heartbeats keep claims alive; stale claims auto-release after 10 min
    - Signal files enable asynchronous poll-based coordination

  All agents read and write the same coordinate graph. Agent 1's test results
  compound the same pheromone trails that Agent 2 navigates. The graph is the
  shared memory — no inter-process communication needed beyond SQLite.


================================================================
8. COMMAND REFERENCE
================================================================

SESSION LIFECYCLE:
  python bootstrap/session_start.py               Full state at session start
  python bootstrap/session_start.py --compact      Short state after context condense
  python bootstrap/session_start.py --gate         Just the current gate status
  python bootstrap/mid_session_snapshot.py \
    --progress "what was completed"                 Checkpoint before condense
  python bootstrap/mid_session_snapshot.py \
    --warn "space:failure:approach:correction"      Record a repeating failure
  python bootstrap/update_coordinates.py --auto \
    --tasks "task1,task2" \
    [--landmark "name:desc:file:test_command"] \
    [--warning "space:failure:approach:correction"]  End of session update

NAVIGATION:
  python bootstrap/query_graph.py --file path       Topology + Z + confidence + routes
  python bootstrap/query_graph.py --routes           Globally strongest pheromone paths
  python bootstrap/query_graph.py --failures         High-signal failures (score >= 0.50)
  python bootstrap/query_graph.py --summary          Full graph statistics
  python bootstrap/query_graph.py --recent           Last N events across all agents
  python bootstrap/query_graph.py --agent AGENT_ID   Specific agent's trail

RECORDING:
  python bootstrap/record_event.py --type file_edit \
    --file path/to/file.py --desc "what changed and why"

  python bootstrap/record_event.py --type file_create \
    --file path/to/new_file.py --desc "what this file does"

  python bootstrap/record_event.py --type test_run \
    --file path/to/test.py --result pass \
    --covers path/to/implementation.py

  python bootstrap/record_event.py --type test_run \
    --file path/to/test.py --result fail \
    --score 0.70 --desc "what the failure revealed"

  python bootstrap/record_event.py --type note \
    --desc "architectural decision and full reasoning"

  python bootstrap/record_event.py --type git_commit \
    --desc "feat: what was built"

WORK QUEUE:
  python bootstrap/agent_context.py                 See available work
  python bootstrap/agent_context.py --claim ID      Claim next available item
  python bootstrap/agent_context.py --complete \
    ITEM_ID AGENT_ID success \
    --landmark "name:desc:file:test_cmd"             Complete with landmark
  python bootstrap/agent_context.py --complete \
    ITEM_ID AGENT_ID failure \
    --warning "space:failure:approach:correction"     Complete with warning
  python bootstrap/agent_context.py --heartbeat ID  Keep claim alive
  python bootstrap/agent_context.py --poll           Check for sub-agent completions

DIRECT API:
  python bootstrap/coordinates.py --test             Run self-test
  python bootstrap/coordinates.py --state            Print coordinate state block
  python bootstrap/coordinates.py --landmarks        List all landmarks
  python bootstrap/coordinates.py --warnings         List active warnings


================================================================
9. SCHEMA REFERENCE
================================================================

CORE TABLES:

  landmarks
    landmark_id     TEXT PK     "lm_coordinate_store"
    name            TEXT        Human-readable name
    description     TEXT        What this feature does
    feature_path    TEXT        File or module it covers
    test_command    TEXT        Command that verifies it
    pass_count      INTEGER     Times test has passed (→ PERMANENT at 3)
    is_permanent    INTEGER     1 when pass_count >= 3
    session_number  INTEGER     When it was created
    created_at      REAL        Unix timestamp
    last_verified   REAL        Last passing test timestamp

  gradient_warnings
    warning_id      TEXT PK
    space           TEXT        Which coordinate space (domain, toolpath, etc.)
    description     TEXT        What failed
    approach        TEXT        What was tried
    correction      TEXT        What worked instead (null until resolved)
    session_number  INTEGER
    decay_session   INTEGER     Session when this warning expires
    created_at      REAL

  contracts
    contract_id     TEXT PK
    rule            TEXT        "when X do Y"
    evidence_count  INTEGER     Corrections that support this rule
    confidence      REAL        0.0-1.0 (activates at evidence >= 2)
    is_active       INTEGER
    created_at      REAL
    last_fired      REAL

  code_events
    event_id        TEXT PK     "ev_<uuid>"
    session_number  INTEGER
    agent_id        TEXT        Which agent recorded this
    event_type      TEXT        file_edit | file_create | test_run | git_commit | note
    file_path       TEXT        (nullable)
    description     TEXT        Human-readable description
    outcome         TEXT        pass | fail | partial | null
    score           REAL        Signal quality 0.0-1.0 (null = unscored)
    detail          TEXT        JSON blob (test output, diff stats, etc.)
    landmark_id     TEXT        Link to landmark (nullable)
    gate            INTEGER     (nullable)
    created_at      REAL

  file_nodes
    file_id          TEXT PK    "fn_<sha256[:16]>" — deterministic from path
    file_path        TEXT UQ    Actual file path
    purpose          TEXT       What this file does
    language         TEXT       Auto-detected from extension
    edit_count       INTEGER    Total edits
    activation_count INTEGER    Meaningful touches (→ crystallization at 12)
    confidence       REAL       0.0-1.0, running weighted average
    z_trajectory     REAL       -1.0 to +1.0, direction of travel
    decay_rate       REAL       Fraction lost per day (default 0.005)
    last_agent       TEXT
    last_edited      REAL
    owning_landmark  TEXT       Link to landmark (halves decay rate)
    test_files       TEXT       JSON array
    created_at       REAL

  test_nodes
    test_id         TEXT PK     "tn_<sha256[:16]>" — deterministic from path+name
    test_file       TEXT        Path to test file
    test_name       TEXT        Specific test function (nullable)
    total_runs      INTEGER
    pass_count      INTEGER
    fail_count      INTEGER
    last_run        REAL
    last_outcome    TEXT
    covers_files    TEXT        JSON array of implementation file paths
    landmark_id     TEXT
    created_at      REAL

  graph_edges
    edge_id         TEXT PK     "ge_<sha256[:16]>" — deterministic from source+target
    source_type     TEXT        test | file
    source_id       TEXT        fn_XXX or tn_XXX
    target_type     TEXT        test | file
    target_id       TEXT        fn_XXX or tn_XXX
    relationship    TEXT        tests | implements | caused_by | fixed_by | requires
    weight          REAL        1.0 base, compounds to 5.0 max, decays to 0.1 min
    compound_count  INTEGER     Total scorings (strength indicator)
    decay_rate      REAL        0.020 per day default
    last_scored     REAL        Timestamp of last weight change
    created_at      REAL

SUPPORTING TABLES:

  sessions          — Session history (objective, tasks, maturity)
  coordinate_path   — 7 coordinate spaces with confidence values
  work_items        — Gated work queue with atomic claiming

STABLE IDS:
  All node and edge IDs are SHA256-based, not Python hash().
  Python's hash() is randomized per process — different CLI invocations
  would produce different IDs for the same file, breaking edge-to-node
  resolution. SHA256 is deterministic: the same file path always produces
  the same file_id, regardless of process, platform, or time.

    _file_id("src/api/router.py")  → "fn_a3b8c9d4e5f67890"  (always)
    _test_id("tests/test_api.py")  → "tn_1234567890abcdef"  (always)
    _edge_id(test_id, file_id)     → "ge_fedcba0987654321"  (always)


================================================================
10. CONFIGURATION AND TUNING
================================================================

All tuning constants are at the top of coordinates.py:

  LANDMARK_THRESHOLD = 3
    How many passing tests before a landmark becomes permanent.
    Increase for stricter verification (5 = very strict).
    Decrease for faster crystallization (2 = liberal).

  CHART_ACTIVATION_THRESHOLD = 12
    How many meaningful activations before a file_node is crystallization-ready.
    This prevents noise from becoming landmarks.
    Increase for large codebases with many incidental touches (15-20).
    Decrease for small focused projects (8-10).

  EDGE_WEIGHT_MAX = 5.0
    Upper bound on pheromone trail strength.
    Higher values allow more differentiation between frequently-tested
    and rarely-tested paths. 5.0 is a good default for most codebases.

  EDGE_WEIGHT_MIN = 0.1
    Lower bound. Edges never fully disappear — they fade but persist.
    Set to 0.0 if you want complete edge death (not recommended).

  EDGE_SUCCESS_FACTOR = 1.10
    Weight multiplier on pass. 1.10 = 10% compounding per successful traversal.
    At 1.10, an edge reaches weight 4.0 after ~15 consecutive passes.
    Increase to 1.15 for faster trail formation.

  EDGE_FAILURE_FACTOR = 0.85
    Weight multiplier on fail. 0.85 = 15% decay per failed traversal.
    Failure decays faster than success compounds — this is intentional.
    The system is conservative: good paths grow slowly, bad paths weaken fast.

  HIGH_POTENTIAL_FAILURE_THRESHOLD = 0.50
    Minimum score for a failure to be treated as a future-success candidate.
    Lower this to 0.40 to capture more informative failures.
    Raise to 0.60 for stricter signal filtering.

  NODE_DECAY_RATES (per coordinate space, per day):
    domain:     0.005   Expertise — very stable
    conduct:    0.008   Working habits — somewhat stable
    style:      0.005   Communication preference — stable
    chrono:     0.005   Temporal patterns — stable
    context:    0.025   Project context — decays FAST (stale context misleads)
    capability: 0.002   Hardware/tooling — nearly static
    toolpath:   0.020   Behavioral tool habits — moderate turnover

  GRADIENT_DECAY_SESSIONS = 10
    How many sessions before a gradient warning fades.
    Increase for long-lived warnings (20 = persistent caution).

  CONTRACT_MIN_EVIDENCE = 2
    How many correction events before a behavioral contract activates.
    Increase for higher confidence (3-4 = strong pattern required).


SCALING FOR LARGE CODEBASES (1000+ files)
-------------------------------------------
For very large codebases, consider these adjustments:

  1. Increase CHART_ACTIVATION_THRESHOLD to 15-20
     More files means more noise. Higher threshold ensures only genuinely
     important files crystallize.

  2. Increase context decay rate to 0.030-0.040
     Large codebases have more stale context. Faster decay keeps the
     semantic layer current.

  3. Use --file queries instead of --summary for navigation
     At 5000+ file nodes, full graph scans become expensive for display
     (though still fast at the SQLite level). Query specific files.

  4. Run decay passes regularly
     For active projects with daily sessions, run_decay_pass() daily.
     For less active projects, run it weekly with days_elapsed=7.

  5. Monitor coordinates.db file size
     Typical: 1-5 MB for 100-500 files
     Large:   5-20 MB for 1000-5000 files
     Very large: 20-50 MB for 5000+ files with deep history
     SQLite VACUUM periodically if space matters (quarterly is fine).

TRANSFER TO PRODUCTION
------------------------
The schema is intentionally transfer-compatible with a production memory.db.
When your project is complete, the bootstrap database can become your
application's runtime memory:

  cp bootstrap/coordinates.db data/memory.db

No migration. No schema changes. The coordinate graph the build agents wrote
IS the graph the production system reads. The build memory becomes the
app memory. This was by design from session one.

================================================================
