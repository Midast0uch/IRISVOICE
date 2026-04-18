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
  record_event.py         Record a single code action (edit, create, test, note, pin)
  agent_context.py        Work queue — claim items, complete them, run in parallel
  query_graph.py          Query the graph (file state, routes, failures, summary)
  mid_session_snapshot.py Save a progress note mid-session (before context condense)
  update_coordinates.py   Close out a session, record landmarks and warnings
  pin.py                  PiN CLI — anchor/search/link Primordial Information Nodes
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
  - Decay pass runs once per day — non-landmark node confidence fades without
    reinforcement. Stale context self-corrects. Permanent landmarks never decay.
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

PiNs (Primordial Information Nodes — anchor any knowledge artifact into the graph):
  python bootstrap/record_event.py --type pin --title "TTS Pipeline" --content "F5-TTS is primary..." --tags tts voice
  python bootstrap/record_event.py --type pin --pin-type image --title "Arch Diagram" --image-refs docs/arch.png
  python bootstrap/record_event.py --type pin --pin-type decision --title "Chose SQLite over Postgres" --permanent

  # Or use the dedicated PiN CLI for more control:
  python bootstrap/pin.py --add "Design: TTS pipeline" --type decision --content "..." --permanent
  python bootstrap/pin.py --search "tts"
  python bootstrap/pin.py --link pin:PIN_ID landmark:lm_foo documents
  python bootstrap/pin.py --list --type decision

Cross-project landmark bridging (register equivalent landmarks across projects):
  python bootstrap/pin.py --bridge lm_g1_backend_health \
    --remote-name "g1_api_healthy" --remote-project "other-project" --confidence 0.95
  python bootstrap/pin.py --bridges   # list all bridges

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

PiN LAYER (Primordial Information Nodes)

A PiN is any meaningful unit of knowledge anchored to this project's memory graph.
The name is intentional — "primordia" are the first growth points of a fungal network.
PiNs are the attachment points IRIS memory crystallises around.

PiN types:
  note       — freeform note or observation
  file       — a specific file or set of files
  folder     — a directory / subtree
  image      — diagram, screenshot, visual reference
  doc        — document, spec, README, design brief
  url        — external link, API reference, library docs
  decision   — architectural or technical decision record
  fragment   — code snippet, prompt fragment, reusable pattern

  # Anchor a design decision permanently:
  python bootstrap/pin.py --add "Decision: TTS primary = F5-TTS" --type decision \
    --content "F5-TTS over Piper: voice cloning is core to IRIS identity." \
    --tags tts voice decision --permanent

  # Link an architecture diagram to the file it describes:
  python bootstrap/pin.py --add "Arch: DER Loop" --type image \
    --image-refs docs/der_loop.png --file-refs backend/agent/der_loop.py
  python bootstrap/pin.py --link pin:PIN_ID file:backend/agent/der_loop.py documents

  # Search all PiNs:
  python bootstrap/pin.py --search "tts"
  python bootstrap/pin.py --list --type decision   # only decision PiNs

PiNs appear in compact output so agents arriving mid-project know what knowledge
already exists without reading random files.

---

CROSS-PROJECT LANDMARK BRIDGING

Each IRIS installation has a unique instance_id (UUID, auto-created on first init).
Permanent landmarks and PiNs carry an origin_id — provenance is always known.

A landmark bridge maps a local landmark to an equivalent landmark in another project.
Projects don't have to be code or the same domain — they just need the same 7-space
coordinate map. IRIS uses bridges to bootstrap faster on new projects: familiar
patterns activate from prior traversals rather than re-crystallising from scratch.

Bridge types:
  equivalent — same pattern, different codebase / domain / instance
  similar    — overlapping pattern, partial activation expected
  inverse    — opposite pattern — activates as a warning, not a boost

  python bootstrap/pin.py --bridge lm_g1_backend_health \
    --remote-name "g1_api_healthy" --remote-project "other-project" \
    --confidence 0.95 --bridge-type equivalent
  python bootstrap/pin.py --bridges                  # list all
  python bootstrap/pin.py --bridges lm_g1_backend_health   # one landmark

Federation (full DB merge between IRIS instances) is built into the IRIS application
layer — not the bootstrap. The application will expose a federation interface once
Gate 3 is complete.

---

PORTABILITY NOTES

- Python 3.8+ required. No dependencies beyond stdlib + sqlite3.
- Works on any OS. All paths use os.path — no hardcoded separators.
- The database schema is stable. It transfers to data/memory.db at production.
  (same coordinate map schema — no migration needed).
- To use in a new project: copy bootstrap/, update GOALS.md, wire the hooks.
- Instance identity: instance_registry auto-created on first init. No config needed.
