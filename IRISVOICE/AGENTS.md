AGENTS.md — IRIS Project
Universal instructions for any AI agent working in this codebase.
Works with Cursor, Windsurf, Copilot, GPT-based agents, Claude, and any other tool.
Claude Code users: CLAUDE.md has additional platform-specific detail.

This file is designed to be read at the start of every session, by any agent, without
prior context. It is self-contained.

═══════════════════════════════════════════════════════════════════
WHAT THIS PROJECT IS
═══════════════════════════════════════════════════════════════════

IRIS is a local AI assistant: Python FastAPI backend, Next.js frontend, Tauri desktop.
The agent brain is a DER Loop (Director, Explorer, Reviewer) with a memory system
called Mycelium that stores user context as coordinate graphs — not prose.

Single build objective: IRIS runs a Tauri build without any external agent tools.
That is when this codebase is complete. Everything before that is a gate.

You are one agent in a sequence. Others have worked here before you.
Others will work here after you. The coordinate database is the continuity between you.

═══════════════════════════════════════════════════════════════════
THE COORDINATE DATABASE — WHAT IT IS AND WHY IT MATTERS
═══════════════════════════════════════════════════════════════════

Location: IRISVOICE/bootstrap/coordinates.db (SQLite, WAL mode, safe for concurrency)

This database is NOT a log. It is a living memory system that does three things:

  1. TELLS YOU WHAT IS TRUE RIGHT NOW
     - Which gate you are on and what work is open
     - What permanent landmarks (verified features) exist — these must not break
     - What gradient warnings (past failures) say to avoid
     - What contracts (architectural rules) are active

  2. GUIDES YOU TOWARD WHAT WORKS
     - Pheromone trails: graph edges whose weights compound every time a test passes
       across an edge. An edge with weight 4.2 has been reinforced 40+ times.
       Follow those trails. They are where the architecture is solid.
     - Topology primitives: each file is classified as CORE (stable, battle-tested),
       ACQUIRING (actively being built up), EXPLORING (experimental), EVOLVING
       (being refactored), or ORBIT (supporting role). This tells you what a file
       IS right now, not just what happened to it.
     - Z-trajectory: direction of travel. A file with z:+0.22 is gaining confidence
       (approaching mastery). One with z:-0.15 is losing confidence (being replaced).
       This is the third coordinate axis — it encodes momentum, not just position.

  3. PRESERVES WHAT YOU LEARN FOR THE NEXT AGENT
     - Every file edit, test run, and architectural decision you record becomes
       part of the permanent mycelium trail that future agents navigate.
     - A failure you score correctly (e.g. score:0.70 on an informative failure)
       prevents the next agent from making the same mistake. It is not discarded —
       it is kept as a high-signal failure that the graph actively surfaces.
     - When IRIS is complete, this database transfers directly to data/memory.db
       and becomes the runtime memory of the application itself. The schema is
       compatible by design. What you build here is what IRIS runs on.

THE COMPRESSION PROGRESSION (how the memory gets lighter, not heavier):

  Raw events  -->  file_node confidence + edge weights  -->  permanent landmark
  (episodic)       (semantic: compressed, always current)    (crystallized: never decays)

  This is not just a metaphor. The system literally compresses over time:
  - Nodes that are reinforced enough times (activation_count >= 12) become
    crystallization candidates — pattern is real, not noise
  - Landmarks that overlap in coordinate space merge — redundancy collapses
  - Nodes that go unreinforced decay toward zero and fade from navigation
  - The result: the more sessions that run, the more precise and lightweight
    the map becomes. Context cost goes DOWN with time, not up.

═══════════════════════════════════════════════════════════════════
STEP 0 — RUN THIS BEFORE ANYTHING ELSE
═══════════════════════════════════════════════════════════════════

  python bootstrap/session_start.py

Output structure:
  MYCELIUM: ...    <- compact coordinate state (15 tokens, not 60 words of prose)
  TOPOLOGY: ...    <- primitive distribution across tracked files
  GRADIENT: ...    <- active warning count
  PHEROMONE ROUTES <- strongest reinforced paths through the codebase graph
  FILE TOPOLOGY    <- what each active file IS (CORE/ACQUIRING/EXPLORING/etc.)
  HIGH-SIGNAL FAILURES  <- informative failures worth reading before you start

  CURRENT GATE:    <- what gate you are on and what is incomplete
  PERMANENT LANDMARKS   <- verified features. Do not break these.
  GRADIENT WARNINGS     <- what approaches have failed. Do not repeat these.
  ACTIVE CONTRACTS      <- architectural rules from past corrections.

Do not plan. Do not read files. Do not write code. Read this output first.
The MYCELIUM line is the compressed state of the entire build history in coordinates.
Everything below it is the human-readable translation.

═══════════════════════════════════════════════════════════════════
STEP 1 — CHECK AVAILABLE WORK
═══════════════════════════════════════════════════════════════════

  python bootstrap/agent_context.py

Shows:
  - Work items available to claim in the current gate
  - Items already claimed by other agents (do not duplicate)
  - Items already completed (do not redo)

To claim a work item:

  python bootstrap/agent_context.py --claim your_agent_id

Use a unique ID that identifies your tool and session:
  cursor_001  windsurf_main  copilot_sub_1  gpt4_agent  opencode_001

The database is atomic — two agents cannot claim the same item simultaneously.
Gate locks are enforced automatically. You cannot claim Gate 2 work while
Gate 1 has incomplete items. The database decides, not you.

═══════════════════════════════════════════════════════════════════
STEP 1.5 — NAVIGATE THE GRAPH BEFORE TOUCHING ANY FILE
═══════════════════════════════════════════════════════════════════

This step is not optional. Agents that skip it cause regressions.

Before editing any file, run:

  python bootstrap/query_graph.py --file path/to/file.py

This returns the SEMANTIC layer for that file — not just a log:
  - Topology primitive: what this file IS (CORE/ACQUIRING/EXPLORING/EVOLVING/ORBIT)
  - Z-trajectory: direction of travel (up = gaining confidence, down = losing it)
  - Confidence: how well-established this file is in the graph (0.0 to 1.0)
  - Pheromone routes: which files this one connects to, and how strongly
  - Test coverage: which tests cover it — run them before and after any change
  - Event history: who touched it, when, and why

Example output for a CORE file:
  Topology:  CORE        -> z:+0.002  conf:0.82  activations:9/12
  Routes:    [4.2x/38runs] der_loop.py --tests--> test_der_loop.py

Example output for an ACQUIRING file:
  Topology:  ACQUIRING   ^ z:+0.18   conf:0.61  activations:5/12
  Routes:    [1.8x/6runs] telegram_bridge.py --implements--> telegram_notifier.py

Example output for an EVOLVING file:
  Topology:  EVOLVING    v z:-0.11   conf:0.44  activations:3/12
  (This file is losing confidence. Ask why before touching it.)

To see the strongest pheromone routes across the whole codebase:

  python bootstrap/query_graph.py --routes

Follow these first. They are the paths that have been reinforced by repeated
successful test runs. An edge with weight 4.2 is not random — it earned that.

To see informative failures before starting work in a risky area:

  python bootstrap/query_graph.py --failures

These are NOT dead weight. A failure with score 0.65 means an agent tried something,
it failed, but the failure itself was informative — it revealed a dependency, a pattern,
an architectural constraint. Read these before approaching the same area.

To understand the overall graph state:

  python bootstrap/query_graph.py --summary

═══════════════════════════════════════════════════════════════════
THE FOUR GATES — NEVER SKIP, NEVER REORDER
═══════════════════════════════════════════════════════════════════

  Gate 1: DER Loop + Director Mode     [start here if not cleared]
  Gate 2: Skill Creator + UI Sync      [locked until Gate 1 clears]
  Gate 3: MCP + Telegram               [locked until Gate 2 clears]
  Gate 4: Free Range                   [earned by clearing Gate 3]

Spec files to read before building each gate:
  bootstrap/GOALS.md              -- gate structure and acceptance criteria
  specs/agent_loop_tasks.md       -- Gate 1 build tasks
  specs/director_mode_system.md   -- Gate 1 mode system
  specs/IRIS_Swarm_PRD_v9.md      -- full architecture contracts

═══════════════════════════════════════════════════════════════════
HOW TO BUILD ANYTHING
═══════════════════════════════════════════════════════════════════

  READ spec  -->  NAVIGATE graph  -->  READ file  -->  BUILD  -->  TEST  -->  RECORD

On test PASS:
  python bootstrap/agent_context.py --complete ITEM_ID YOUR_AGENT_ID success \
    --landmark "name:description:file.py:test_command"

On test FAIL:
  python bootstrap/agent_context.py --complete ITEM_ID YOUR_AGENT_ID failure \
    --warning "space:what failed:approach tried:what to try instead"

THE TEST RULE — NON-NEGOTIABLE:
  Run the spec's test against your implementation.
  Never write new tests to match your code.
  Never modify existing tests to make them pass.
  The test is the requirement. Fix the code. The test does not change.

Landmark crystallization:
  A landmark becomes PERMANENT after 3 passing test runs (LANDMARK_THRESHOLD).
  Call verify_landmark() or run --complete with --landmark three times.
  Permanent landmarks never decay. They are the inherited memory of this build.

═══════════════════════════════════════════════════════════════════
STEP 2.5 — RECORD EVERY CODE ACTION
═══════════════════════════════════════════════════════════════════

This is how the pheromone trail grows. Every event you record makes the next
agent's navigation more precise. Every event you skip is context the next agent
has to re-discover from scratch.

After editing a file:
  python bootstrap/record_event.py --type file_edit \
    --file backend/agent/agent_kernel.py \
    --desc "added task_class parameter — fixes NameError on startup, resolves Gate1.4"

After creating a file:
  python bootstrap/record_event.py --type file_create \
    --file backend/channels/telegram_notifier.py \
    --desc "outbound Telegram channel — reads BOT_TOKEN/CHAT_ID from .env, never raises"

After a test passes:
  python bootstrap/record_event.py --type test_run \
    --file backend/tests/test_telegram_notifier.py --result pass \
    --covers backend/channels/telegram_notifier.py

After a test fails — BUT the failure was informative (revealed something real):
  python bootstrap/record_event.py --type test_run \
    --file backend/tests/test_der_loop.py --result fail \
    --score 0.70 \
    --desc "ImportError: circular dependency — agent_kernel imports ReviewVerdict at top level"

  The --score 0.70 flag tells the graph: this failure carries signal.
  A score >= 0.50 on a failure makes it a future-success candidate.
  It appears in --failures so the next agent reads it before approaching that area.
  Do not give high scores to crashes with no useful information. Save them for
  failures that revealed something the next agent genuinely needs to know.

After an architectural decision (the most important thing to record):
  python bootstrap/record_event.py --type note \
    --desc "chose synchronous HTTP over async for TelegramNotifier: agent calls are
            infrequent, async adds complexity without benefit, simpler to test"

  These notes encode WHY. The next agent reads them and does not re-litigate
  decisions that were already reasoned through. This is the semantic memory
  layer — it compresses over time as coordinates absorb the pattern.

═══════════════════════════════════════════════════════════════════
UNDERSTANDING WHAT THE GRAPH IS TELLING YOU
═══════════════════════════════════════════════════════════════════

The MYCELIUM: line in session_start output:

  MYCELIUM: context:[1.00,0.85,0.02]@gate4 | toolpath:[w:4.1,ev:127] | confidence:0.95

  context:[1.00,0.85,0.02]  -- gate completion, landmark density, session depth
  @gate4                    -- current gate
  toolpath:[w:4.1,ev:127]   -- strongest edge weight, total events recorded
  confidence:0.95           -- overall graph confidence (17 permanent landmarks)

The TOPOLOGY: line:

  TOPOLOGY: core:12 | acquiring:3 | orbit:8 | evolving:1

  This tells you the primitive distribution. 12 files are CORE (solid, settled).
  3 are ACQUIRING (being actively built up). 1 is EVOLVING (losing confidence —
  investigate before touching it). Follow the CORE files when the path is unclear.

The PHEROMONE ROUTES section:

  [4.2x / 38 runs] backend/agent/der_loop.py --tests--> backend/tests/test_der_loop.py

  Weight 4.2 means this edge has been scored 38 times and survived.
  It is not arbitrary. Start here when working in the DER loop area.

The FILE TOPOLOGY section:

  ACQUIRING   ^ [0.61] backend/channels/telegram_bridge.py
  CORE        -> [0.84] backend/agent/agent_kernel.py
  EVOLVING    v [0.43] backend/mcp/server_manager.py

  ACQUIRING with ^ = confidence rising. This file is being built right now.
  CORE with ->    = stable. Do not break it without checking what depends on it.
  EVOLVING with v = confidence falling. Find out why before touching it.

═══════════════════════════════════════════════════════════════════
MANAGING CONTEXT ACROSS A SESSION
═══════════════════════════════════════════════════════════════════

At session start:
  python bootstrap/session_start.py

At ~50k tokens (before context window fills):
  python bootstrap/mid_session_snapshot.py --progress "what just completed"
  [condense/summarize context in your tool]
  python bootstrap/session_start.py --compact

At session end:
  python bootstrap/update_coordinates.py --auto \
    --tasks "comma,separated,completed,tasks" \
    [--landmark "name:desc:file:test_command"] \
    [--warning "space:failure:approach:correction"]

If you hit a repeating error (same failure twice in a row), stop and record it:
  python bootstrap/mid_session_snapshot.py \
    --warn "space:what is looping:approach being repeated:what to try instead"
  Then change approach. Never retry the same thing a third time.

═══════════════════════════════════════════════════════════════════
CRITICAL ARCHITECTURE RULES
═══════════════════════════════════════════════════════════════════

These come from the spec. Violating them breaks things that are already verified.

1. Every Mycelium call wrapped in try/except — never blocks user response
2. Classification BEFORE context assembly — NameError if reversed
3. Reviewer always falls back to PASS on exception — never blocks Explorer
4. Safe defaults on all new _plan_task() parameters
5. ASCII markers only: [+] [x] [~] [ ] — Unicode breaks encoding on Windows
6. SPEC mode routes to SpecEngine directly — not through the DER loop
7. Token budget terminates the DER loop — not cycle count
8. BEGIN IMMEDIATE on all Mycelium writes — two loops share one graph

═══════════════════════════════════════════════════════════════════
PLATFORM — WINDOWS
═══════════════════════════════════════════════════════════════════

USE:   python script.py
USE:   python -m pytest backend/tests/ -v
USE:   New-Item file.py -ItemType File
USE:   Get-ChildItem -Recurse -Filter "*.py"
NEVER: touch / ls -la / grep -r / cat | head

═══════════════════════════════════════════════════════════════════
SAFETY RAILS
═══════════════════════════════════════════════════════════════════

Never delete or overwrite files without reading them first.
Never git push or git reset --hard without explicit user confirmation.
Never pip install or npm install without checking requirements.txt first.
Never hardcode credentials — environment variables only (.env file).
Never access paths outside IRISVOICE/.
Prefix risky commands with SAFE-CHECK: and wait for confirmation.

═══════════════════════════════════════════════════════════════════
WHAT DONE LOOKS LIKE
═══════════════════════════════════════════════════════════════════

The build is complete when:
  cargo tauri build completes without errors
  The built app launches and accepts input through its own interface
  IRIS responds — not this agent tool
  Coordinate store at IRISVOICE/data/memory.db (transferred from bootstrap/)

The coordinate database is complete when:
  python bootstrap/query_graph.py --summary shows:
    - Events recorded for every file that was touched
    - Pheromone routes with weight > 1.0 on all major test connections
    - Near-crystallization candidates on the most-used files
  python bootstrap/session_start.py shows MYCELIUM: confidence >= 0.85

At that point, the bootstrap/coordinates.db can transfer to data/memory.db
and the application's own Mycelium runtime takes over — same schema, same
coordinate graph, same pheromone trails. The build memory becomes the app memory.
Nothing is lost. Everything was built in the right format from session one.

═══════════════════════════════════════════════════════════════════
QUICK REFERENCE — ALL COMMANDS
═══════════════════════════════════════════════════════════════════

SESSION:
  python bootstrap/session_start.py               # full state at session start
  python bootstrap/session_start.py --compact     # short state after condense

NAVIGATION (read before touching anything):
  python bootstrap/query_graph.py --file path/to/file.py    # what a file IS
  python bootstrap/query_graph.py --routes                  # strongest paths
  python bootstrap/query_graph.py --failures                # informative failures
  python bootstrap/query_graph.py --summary                 # full graph stats
  python bootstrap/query_graph.py --recent                  # last N events
  python bootstrap/query_graph.py --agent cursor_001        # agent trail

WORK CLAIMING:
  python bootstrap/agent_context.py                          # see available work
  python bootstrap/agent_context.py --claim your_agent_id   # claim a work item
  python bootstrap/agent_context.py --complete ID AGENT success --landmark "..."
  python bootstrap/agent_context.py --complete ID AGENT failure --warning "..."
  python bootstrap/agent_context.py --heartbeat your_agent_id  # keep claim alive

RECORDING (write after every action):
  python bootstrap/record_event.py --type file_edit   --file path --desc "why"
  python bootstrap/record_event.py --type file_create --file path --desc "what"
  python bootstrap/record_event.py --type test_run    --file path --result pass --covers impl.py
  python bootstrap/record_event.py --type test_run    --file path --result fail --score 0.70 --desc "what it revealed"
  python bootstrap/record_event.py --type note        --desc "architectural decision and why"
  python bootstrap/record_event.py --type git_commit  --desc "feat: what was built"

SESSION BOUNDARIES:
  python bootstrap/mid_session_snapshot.py --progress "..."    # before condense
  python bootstrap/mid_session_snapshot.py --warn "space:..."  # loop prevention
  python bootstrap/update_coordinates.py --auto --tasks "..."  # end of session

═══════════════════════════════════════════════════════════════════
