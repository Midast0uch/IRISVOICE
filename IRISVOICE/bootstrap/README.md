Mycelium Bootstrap — Coordinate Memory System
A portable, project-agnostic code memory system for Claude Code agents.
Drop this folder into any project to give agents persistent build memory across sessions.

---

WHAT IT DOES

Agents forget everything between sessions. This system doesn't.

It maintains a SQLite coordinate graph that tracks:
- Every file edited or created (pheromone trail)
- Every test run and its result (landmark crystallization)
- Every failure that revealed something important (high-signal failures)
- Architectural decisions and why they were made (notes)
- Verified features that passed tests N times (permanent landmarks)
- Gradient warnings — where the codebase has failed before and what worked instead

The graph has three layers:
  EPISODIC  — what happened, when, and to which file
  SEMANTIC  — what each file IS in the codebase (rising/stable/falling trajectory, confidence)
  LANDMARK  — verified features (crystallized after 3 passing test runs)

At session start, the agent reads the graph and knows where it left off, what to avoid, and what is already verified. No re-litigating past decisions. No re-discovering old bugs.

---

FILES

  coordinates.py          Core store — SQLite schema, all read/write methods
  coordinates.db          The live database (git-ignored or committed, your choice)
  session_start.py        Load state into context. Also auto-syncs git commits.
  record_event.py         Record a single code action (edit, create, test, note)
  agent_context.py        Work queue — claim items, complete them, run in parallel
  query_graph.py          Query the graph (file state, routes, failures, summary)
  mid_session_snapshot.py Save a progress note mid-session (before context condense)
  update_coordinates.py   Close out a session, record landmarks and warnings
  GOALS.md                Project-specific roadmap (replace with your own)
  signals/                Sub-agent completion signals (for parallel agent coordination)

---

SETUP FOR A NEW PROJECT

1. Copy this bootstrap/ folder into your project root.

2. Replace GOALS.md with your project's roadmap.
   The format is free-form — the agent reads it, not the system.

3. Add these two hooks to .claude/settings.local.json:

   UserPromptSubmit — loads state and auto-syncs git commits on every prompt:
   {
     "hooks": [{
       "type": "command",
       "command": "python -c \"import subprocess,json; r=subprocess.run(['python','bootstrap/session_start.py','--compact'],capture_output=True,text=True,cwd='<YOUR_PROJECT_DIR>',timeout=30); out=(r.stdout or r.stderr)[:2000]; print(json.dumps({'hookSpecificOutput':{'hookEventName':'UserPromptSubmit','additionalContext':out}}))\"",
       "timeout": 35,
       "statusMessage": "Loading coordinate state..."
     }]
   }

   Stop — saves snapshot and closes the session in the graph:
   {
     "hooks": [{
       "type": "command",
       "command": "python -c \"import subprocess; subprocess.run(['python','bootstrap/mid_session_snapshot.py','--progress','auto-snapshot on stop'],capture_output=True,text=True,cwd='<YOUR_PROJECT_DIR>',timeout=30); subprocess.run(['python','bootstrap/update_coordinates.py','--auto','--tasks','auto-session-close'],capture_output=True,text=True,cwd='<YOUR_PROJECT_DIR>',timeout=30)\"",
       "timeout": 70,
       "statusMessage": "Saving snapshot + updating coordinate graph..."
     }]
   }

4. Add CLAUDE.md to your project root (use the one in the project root as a template).
   Point it at bootstrap/GOALS.md and tell the agent its objective.

5. First session — run:
   python bootstrap/session_start.py
   This initializes the database and prints the empty starting state.

---

AUTOMATIC BEHAVIOR (once hooks are wired)

Every prompt:
  - session_start.py runs automatically
  - auto_sync_commits() scans the last 10 git commits
  - Any commit not yet in code_events gets recorded (idempotent — SHA checked)
  - You never need to manually call record_event.py for committed files

Session end:
  - mid_session_snapshot.py saves a progress note
  - update_coordinates.py --auto closes the session in the graph
  - You never need to manually run update_coordinates.py

Manual recording (for uncommitted work, high-signal failures, or notes):
  python bootstrap/record_event.py --type file_edit --file path/to/file --desc "what changed"
  python bootstrap/record_event.py --type test_run --file tests/test_foo --result pass --covers src/foo
  python bootstrap/record_event.py --type test_run --file tests/test_foo --result fail --score 0.70 --desc "what failed revealed"
  python bootstrap/record_event.py --type note --desc "why X was chosen over Y"

---

LANDMARK CRYSTALLIZATION

A landmark forms when a feature's test passes 3 times (default threshold).
Until then it is "developing" — not yet permanent, can still be lost.

  # Record a landmark after a test passes:
  python bootstrap/agent_context.py --complete ITEM_ID AGENT_ID success \
    --landmark "feature_name:short description:path/to/file.py:test command"

  # Check crystallization progress:
  python bootstrap/session_start.py --gate

Permanent landmarks never decay. They appear in session_start output every session.
They are the verified, stable foundation the agent builds on top of.

---

GRADIENT WARNINGS

Warnings record where the codebase has failed before and what worked instead.
They decay after 10 sessions if not reinforced — stale warnings don't pollute context.

  python bootstrap/record_event.py --type note \
    (or via agent_context.py --complete ... --warning "space:what failed:approach:correction")

  Spaces: domain | conduct | context | capability | toolpath

---

PHEROMONE TRAILS

Every time a test passes against a file, the edge between the test and the file
gains weight. High-weight edges are the settled, proven paths through the codebase.

  python bootstrap/query_graph.py --routes    # show strongest paths
  python bootstrap/query_graph.py --file X    # show a file's position in the graph
  python bootstrap/query_graph.py --failures  # show high-signal failures

The agent reads these routes before touching a file. It knows which paths are proven
and which areas carry risk. This is not a log — it is a navigation instrument.

---

PARALLEL AGENTS

The database uses WAL mode — multiple agents can read/write concurrently.
Work claiming is atomic.

  python bootstrap/agent_context.py --claim agent_001
  python bootstrap/agent_context.py --complete ITEM_ID agent_001 success ...
  python bootstrap/agent_context.py --heartbeat agent_001   # every 60s on long tasks
  python bootstrap/agent_context.py --poll                  # orchestrator polls completions

---

PORTABILITY NOTES

- Python 3.8+ required. No dependencies beyond stdlib + sqlite3.
- Works on any OS. All paths use os.path — no hardcoded separators.
- The database schema is stable. It can transfer to a runtime memory store
  when the project reaches production (same schema, no migration needed).
- To use in a new project: copy bootstrap/, update GOALS.md, wire the hooks.
