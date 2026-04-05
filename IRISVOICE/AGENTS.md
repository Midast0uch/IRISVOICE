AGENTS.md — Universal Agent Guide
Works with Claude Code, Cursor, Windsurf, Copilot, Cline, OpenCode, and any other tool.
This file is self-contained. Read it cold, with no prior context, and you will know
exactly where you are, what to do next, and what not to repeat.

Claude Code users: CLAUDE.md has additional hook-specific detail.

---

THE COORDINATE DATABASE — READ THIS FIRST
==========================================

Location: bootstrap/coordinates.db  (SQLite, WAL mode, concurrent-safe)

This database is NOT a log. It is the only persistent memory this project has.
Every agent that worked here before you wrote into it. You will too.

It does three things:

  1. TELLS YOU WHAT IS TRUE RIGHT NOW
     Current gate, open work, permanent landmarks, active contracts, gradient warnings.
     Run session_start.py and you have the full picture in under 30 seconds.

  2. GUIDES YOU TOWARD WHAT WORKS
     Pheromone trails: graph edges whose weights compound every time a test passes
     across an edge. An edge with weight 4.2 has been reinforced 40+ times.
     These are not random — they encode where the architecture is solid.

     Topology primitives: each file is classified as:
       CORE      — stable, battle-tested, do not break without understanding deps
       ACQUIRING — actively being built up, confidence rising
       EXPLORING — experimental, may be replaced
       EVOLVING  — being refactored, confidence falling — ask why before touching
       ORBIT     — supporting role, rarely changes

     Z-trajectory: momentum of a file's confidence. +0.18 = rising. -0.11 = falling.
     Read it before editing. A falling file is being replaced for a reason.

  3. PRESERVES WHAT YOU LEARN FOR THE NEXT AGENT
     Scored failures (score >= 0.50) are future-success candidates — they revealed
     something real. They surface in --failures so the next agent reads them first.
     Every edit, test, and decision you record makes the map more precise.
     Every event you skip is context the next agent re-discovers from scratch.

THE COMPRESSION PROGRESSION:

  Raw events  -->  file_node confidence + edge weights  -->  permanent landmark
  (episodic)       (semantic: compressed, always current)    (crystallized: never decays)

  Nodes reinforced enough times (activation_count >= 12) become crystallization candidates.
  Landmarks that overlap in coordinate space merge — redundancy collapses.
  Unreinforced nodes decay toward zero and fade from navigation automatically —
  a decay pass runs once per day at session start (no manual action needed).
  The more sessions that run, the more precise and lightweight the map becomes.
  Context cost goes DOWN with time, not up.

---

PLATFORM AUTO-RUN CONFIGURATION
=================================

Configure once. session_start.py then runs automatically at the start of every session.

CLAUDE CODE (hooks already configured):
  .claude/settings.local.json has a UserPromptSubmit hook that auto-runs
  session_start.py --compact and injects the output as additionalContext.
  A Stop hook runs mid_session_snapshot.py + update_coordinates.py --auto at session end.
  Nothing to configure — it is already wired. You will see the state on every prompt.

OPENCODE:
  .opencode/plugins/bootstrap.js fires on session.created using Bun shell API.
  Runs session_start.py and returns output to the session context automatically.
  Requires: opencode >= 0.1, python in PATH.

WINDSURF / CODEIUM:
  Add to .windsurfrules (project root):
    At the start of every session, run: python bootstrap/session_start.py
    Do not skip this. Read the output before any other action.

CURSOR / CLINE / OTHER AGENTS:
  Add to .cursorrules, .clinerules, or equivalent:
    MANDATORY SESSION START: python bootstrap/session_start.py
    This is the only source of truth for milestone status, landmarks, and contracts.

MANUAL (any tool):
  Run python bootstrap/session_start.py before anything else.
  Skipping it means working without the build memory prior agents wrote.

---

STEP 0 — SESSION START
=======================

  python bootstrap/session_start.py

Output you will see:
  CURRENT GATE    — what gate you are on and what work is open
  PERMANENT LANDMARKS  — verified features. Do not break these.
  GRADIENT WARNINGS    — what approaches have failed. Do not repeat these.
  ACTIVE CONTRACTS     — architectural rules from past corrections.
  PHEROMONE ROUTES     — strongest reinforced paths through the codebase graph
  FILE TOPOLOGY        — what each active file IS right now
  HIGH-SIGNAL FAILURES — informative failures worth reading before you start

Do not plan. Do not read files. Do not write code. Read this output first.
The graph tells you more in 30 seconds than reading random files for 10 minutes.

---

STEP 1 — CHECK AVAILABLE WORK
==============================

  python bootstrap/agent_context.py

Shows work available to claim, what other agents are building, what is done.

To claim a work item:
  python bootstrap/agent_context.py --claim your_agent_id

Use a unique ID that identifies your tool and session:
  cursor_001  windsurf_main  copilot_sub_1  claude_main  opencode_001

The database is atomic — two agents cannot claim the same item simultaneously.
Gate locks are enforced. You cannot claim Gate 2 work while Gate 1 has open items.

---

STEP 1.5 — NAVIGATE THE GRAPH BEFORE TOUCHING ANY FILE
========================================================

This step is not optional. Agents that skip it cause regressions.

Before editing any file:
  python bootstrap/query_graph.py --file path/to/file.py

Returns:
  - Topology primitive (what this file IS)
  - Z-trajectory (direction of confidence: rising, stable, or falling)
  - Confidence score
  - Pheromone routes (which files it connects to, and how strongly)
  - Test coverage (which tests cover it — run them before and after any change)

Examples:
  CORE      -> [0.84] backend/agent/agent_kernel.py      (stable, high coverage)
  ACQUIRING  ^ [0.61] backend/channels/telegram_bridge.py (actively building up)
  EVOLVING   v [0.43] backend/mcp/server_manager.py       (losing confidence — ask why)

Strongest paths across the whole codebase:
  python bootstrap/query_graph.py --routes

Informative failures before entering a risky area:
  python bootstrap/query_graph.py --failures

Overall graph state:
  python bootstrap/query_graph.py --summary

---

HOW TO BUILD ANYTHING
======================

  READ spec  -->  NAVIGATE graph  -->  READ file  -->  BUILD
    -->  QUALITY CHECK  -->  RUN TEST  -->  PASS -> RECORD
                                        -->  FAIL -> fix, repeat

THE QUALITY CHECK — REQUIRED BEFORE RUNNING THE SPEC TEST

A feature that passes a test but is unoptimized is not done.
Before running the test, verify all of the following:

  [ ] No unnecessary work in hot paths — loops, I/O, and DB calls are as few as needed
  [ ] Heavy imports are lazy — no ML model, GPU init, or large lib loaded at module level
  [ ] Error handling is complete — every exception path has an explicit outcome
  [ ] Resources are cleaned up — file handles, DB connections, subprocess handles closed
  [ ] No shared mutable state across sessions or concurrent requests
  [ ] Memory footprint is bounded — no unbounded caches, no infinite queues
  [ ] Async/sync boundary is correct — blocking calls not in async hot paths
  [ ] Logging is structured — session_id or context identifier in every log line
  [ ] The implementation matches the spec's intent — not just its literal words
  [ ] Nothing in this file could cause a crash that would block a user response

If any item fails the check, fix it before running the test.
A passing test on unoptimized code is a time bomb, not a landmark.

THE TEST RULE — NON-NEGOTIABLE:
  Run the spec's test against your implementation.
  Never write new tests to match your code.
  Never modify existing tests to make them pass.
  The test is the requirement. Fix the code. The test does not change.

On test PASS (after quality check passes):
  python bootstrap/agent_context.py --complete ITEM_ID YOUR_AGENT_ID success \
    --landmark "name:description:file.py:test_command"

On test FAIL:
  python bootstrap/agent_context.py --complete ITEM_ID YOUR_AGENT_ID failure \
    --warning "space:what failed:approach tried:what to try instead"

LANDMARK CRYSTALLIZATION:
  A landmark becomes PERMANENT after 3 passing test runs (default threshold).
  Permanent landmarks never decay. They are the verified foundation.
  Do not mark anything permanent until it has passed 3 times.

---

STEP 2.5 — RECORD EVERY CODE ACTION
=====================================

Git commits are auto-recorded by session_start.py on every prompt (Claude Code).
For other agents, or for uncommitted work, record manually:

After editing a file:
  python bootstrap/record_event.py --type file_edit \
    --file path/to/file.py \
    --desc "what changed and why — enough for the next agent to understand"

After creating a file:
  python bootstrap/record_event.py --type file_create \
    --file path/to/new_file.py \
    --desc "what this file does and why it exists"

After a test passes:
  python bootstrap/record_event.py --type test_run \
    --file tests/test_foo.py --result pass \
    --covers src/foo.py

After a test fails — but the failure revealed something real:
  python bootstrap/record_event.py --type test_run \
    --file tests/test_foo.py --result fail \
    --score 0.70 \
    --desc "what the failure revealed — why the next agent needs to know this"

  score >= 0.50 = high-signal failure. Appears in --failures.
  Save high scores for failures that revealed real architectural constraints.
  Do not give high scores to crashes with no useful information.

After an architectural decision:
  python bootstrap/record_event.py --type note \
    --desc "chose X over Y because — full reasoning"

  Notes encode WHY. The next agent reads them and does not re-litigate
  decisions that were already reasoned through.

---

UNDERSTANDING WHAT THE GRAPH IS TELLING YOU
=============================================

The MYCELIUM line in session_start output:

  MYCELIUM: context:[0.62,0.55,0.01]@gate1 | toolpath:[w:4.1,ev:127] | confidence:0.75

  context:[0.62,0.55,0.01]  — gate completion, landmark density, session depth
  @gate1                    — current gate (DEVELOPER MODE)
  toolpath:[w:4.1,ev:127]   — strongest edge weight, total events recorded
  confidence:0.95           — overall graph confidence

PHEROMONE ROUTES section:

  [4.2x / 38 runs] src/agent/core.py --tests--> tests/test_core.py

  Weight 4.2 across 38 runs = proven path. Start here when the area is unclear.

FILE TOPOLOGY section:

  ACQUIRING  ^ [0.61] src/channels/notifier.py    <- actively being built up
  CORE      -> [0.84] src/agent/kernel.py         <- stable, do not break
  EVOLVING   v [0.43] src/mcp/server_manager.py   <- losing confidence, ask why

---

PARALLEL AGENT PROTOCOL
========================

The database is WAL-mode SQLite — safe for concurrent reads and writes.
Work claiming is atomic — two agents cannot take the same item.

  # Orchestrator — see state and poll completions:
  python bootstrap/agent_context.py
  python bootstrap/agent_context.py --poll

  # Sub-agent workflow:
  python bootstrap/agent_context.py --claim agent_001
  # ... build the feature, run quality check, run the test ...
  python bootstrap/agent_context.py --complete ITEM_ID agent_001 success \
    --landmark "name:desc:file:test_command"

  # Heartbeat for long tasks (every 60s prevents claim expiry):
  python bootstrap/agent_context.py --heartbeat agent_001

---

CONTEXT WINDOW MANAGEMENT
===========================

At ~50k tokens (before window fills):
  python bootstrap/mid_session_snapshot.py --progress "what just completed"
  [condense context in your tool]
  python bootstrap/session_start.py --compact

Loop prevention — same failure twice in a row:
  python bootstrap/mid_session_snapshot.py \
    --warn "space:what is looping:approach tried:what to try instead"
  Then change approach. Never retry the same thing a third time.

Session end (Claude Code: automated by Stop hook):
  python bootstrap/update_coordinates.py --auto \
    --tasks "comma,separated,completed,tasks" \
    [--landmark "name:desc:file:test_command"] \
    [--warning "space:failure:approach:correction"]

Other agents: run this manually at the end of every session.

---

CRITICAL ARCHITECTURE RULES
==============================

These come from the spec. Violating them breaks things that are already verified.

  1. Every memory system call wrapped in try/except — never blocks user response
  2. Classification BEFORE context assembly — order matters
  3. Reviewer always falls back to PASS on exception — never blocks Explorer
  4. Safe defaults on all new parameters — never rely on implicit None
  5. SPEC mode routes directly — not through the DER loop
  6. Token budget terminates loops — not cycle count
  7. Write lock on all shared graph writes — concurrent loops share one graph

---

SAFETY RAILS
=============

Never delete or overwrite files without reading them first.
Never git push or git reset --hard without explicit user confirmation.
Never install packages without checking existing requirements/lockfiles first.
Never hardcode credentials — environment variables only.
Prefix risky commands with SAFE-CHECK: and wait for confirmation.

---

WHAT DONE LOOKS LIKE
=====================

A feature is done when ALL of the following are true:
  [ ] The spec's test passes
  [ ] The quality check (above) passes
  [ ] A landmark is recorded via agent_context.py --complete
  [ ] The landmark has passed tests 3 times (permanent)
  [ ] No existing landmark was broken by this change

The build is complete when:
  All production domains in bootstrap/GOALS.md have green status
  The application receives input through its own interface and responds
  No external scaffolding (Claude Code, Cursor, etc.) is involved in the response
  Coordinate store transferred to the application's runtime memory location (same schema)

The coordinate database is complete when:
  python bootstrap/query_graph.py --summary shows:
    - Events recorded for every file that was touched
    - Pheromone routes with weight > 1.0 on all major test connections
    - Near-crystallization candidates on the most-used files
  python bootstrap/session_start.py shows confidence >= 0.85

---

QUICK REFERENCE
================

SESSION:
  python bootstrap/session_start.py               # full state
  python bootstrap/session_start.py --compact     # short state after condense
  python bootstrap/session_start.py --gate        # current gate only

NAVIGATION:
  python bootstrap/query_graph.py --file path/to/file.py    # what a file IS
  python bootstrap/query_graph.py --routes                  # strongest paths
  python bootstrap/query_graph.py --failures                # informative failures
  python bootstrap/query_graph.py --summary                 # full graph stats
  python bootstrap/query_graph.py --recent                  # last N events

WORK QUEUE:
  python bootstrap/agent_context.py                          # see available work
  python bootstrap/agent_context.py --claim your_agent_id   # claim an item
  python bootstrap/agent_context.py --complete ID AGENT success --landmark "..."
  python bootstrap/agent_context.py --complete ID AGENT failure --warning "..."
  python bootstrap/agent_context.py --heartbeat your_agent_id
  python bootstrap/agent_context.py --poll                   # orchestrator poll

RECORDING:
  python bootstrap/record_event.py --type file_edit   --file path --desc "why"
  python bootstrap/record_event.py --type file_create --file path --desc "what"
  python bootstrap/record_event.py --type test_run    --file path --result pass --covers impl
  python bootstrap/record_event.py --type test_run    --file path --result fail --score 0.70 --desc "..."
  python bootstrap/record_event.py --type note        --desc "decision and reasoning"
  python bootstrap/record_event.py --type wiki_entry  --title "..." --content "..." --tags t1 t2
  python bootstrap/record_event.py --type image_ref   --title "..." --image-refs path/to/img.png
  python bootstrap/record_event.py --type project_ref --project-name "..." --project-path /path

WIKI (knowledge nodes — docs, images, design decisions):
  python bootstrap/wiki.py --add "Title" --content "body" --tags tag1 tag2
  python bootstrap/wiki.py --add "Image: Diagram" --image-refs docs/arch.png --permanent
  python bootstrap/wiki.py --search "query"
  python bootstrap/wiki.py --list
  python bootstrap/wiki.py --link wiki:ENTRY_ID landmark:lm_foo documents
  python bootstrap/wiki.py --projects
  python bootstrap/wiki.py --ensure-project "name" --path /path

FEDERATION (share permanent knowledge between IRIS instances):
  python bootstrap/merge_db.py --source /path/to/coordinates.db
  python bootstrap/merge_db.py --dry-run --source /path/to/coordinates.db
  python bootstrap/merge_db.py --log

SESSION BOUNDARIES:
  python bootstrap/mid_session_snapshot.py --progress "..."    # before condense
  python bootstrap/mid_session_snapshot.py --warn "space:..."  # loop prevention
  python bootstrap/update_coordinates.py --auto --tasks "..."  # end of session
