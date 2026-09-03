AGENTS.md
Primary instructions for OPENCODE.
MCM SDK keeps the coordinate graph current automatically — no manual DB updates needed.

---

WHAT THIS PROJECT IS

You are working on **IRIS Voice**, a voice-controlled desktop assistant.

- **Frontend**: Next.js 15, React, Tailwind CSS v4, Tauri API
- **Backend**: Python FastAPI, WebSockets, async architecture
- **Desktop**: Tauri (Rust) — borderless widget, system tray, global shortcuts
- **Audio**: Porcupine wake word, WebRTC/STT pipeline, WebSocket streaming
- **Auth**: OAuth handlers, OS keyring for secure credential storage
- **Database**: MCM SDK coordinate graph at `.mcm/coordinates.db` (project-local; set `MCM_DB_PATH=C:\dev\IRISVOICE\.mcm\coordinates.db`)

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
  get_session() → check pos 15 (work items available)
NOTE: there is no claim_work() tool on the MCM MCP server. Work items are
visible through get_session() only; claiming is not exposed.
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
  PASS -> record_test(file=..., result='pass') + pin_add(title=..., type='decision')
  FAIL -> fix code, return to QUALITY CHECK. The test does not change.

THE SCOPE BOUND — HOW MUCH TO BUILD (read BEFORE writing code)
Two ladders decide the SHAPE of a change. Two lines decide its EDGES.
The ladders alone are not enough: they tell you how small each piece should be
and say nothing about how far the change should reach. An agent obeying only the
ladders will still write three files when the task needed one, because every
individual piece passed the "is this minimal?" test.

MINIMALITY LADDER — how small (stop at the first rung that works):
  1. Does this need to exist at all?
  2. Is it already in the codebase? (search before writing — duplicates are the
     most common over-build in this repo)
  3. Standard library?
  4. Platform-native (OS, framework, browser API)?
  5. A dependency already installed?
  6. Can it be one line?
  7. The minimum that actually works.

DEPTH LADDER — how sure (all rungs, always, no early exit):
  a. Read the code the change touches before writing.
  b. Trace the real flow — not the flow you assume.
  c. Enumerate the edge cases and say which are handled.
  d. Verify with the project's own tests.
  e. Optimize only measured hot paths.

THE RUNGS RUN AFTER UNDERSTANDING, NEVER INSTEAD OF IT.
Minimalism applies to CODE. It never applies to UNDERSTANDING, VERIFICATION,
ERROR HANDLING, SECURITY, or ACCESSIBILITY. Those are not rungs to skip.

EVERY TASK CARRIES TWO LINES — they are the contract, not commentary:
  DONE =     the single observable condition that ends the task. When it is
             true, STOP. Not "when it feels complete."
  NOT THIS = the specific over-builds this task invites. Producing any of them
             is a task FAILURE even if the code works.

You are measured against those two lines, never against your own sense of
completeness. If a task has no DONE/NOT THIS lines, write them and state them
back before starting — an unbounded task is an unstarted task.

THE OVER-BUILD LIST — what NOT THIS almost always means here:
  - An abstraction over a set of size one (a "pluggable backend" for one backend,
    an interface with one implementer, a registry with one entry).
  - A framework where a function was asked for — a scheduler, a policy engine, a
    template system, a plugin layer, a DSL.
  - Configuration for something nobody asked to configure.
  - A compatibility shim or deprecation path for code you were told to delete.
  - Helper/utility modules created to hold code used exactly once.
  - Defensive handling for states the type system or call site already excludes.
  - Refactoring adjacent code you were not asked to touch, "while you're in there."
  - New tests written to describe what you built, instead of running the tests
    that already define the requirement (see THE TEST RULE — ABSOLUTE).

WHEN THE BOUND AND THE WORK CONFLICT — REPORT, DO NOT WIDEN.
If DONE = is unreachable without producing something on the NOT THIS = list,
that is a FINDING. Stop, name the specific conflict, propose the smallest change
to the bound that resolves it, and wait. Quietly widening the bound destroys the
evidence that the task was scoped wrong — the same failure mode as quietly
weakening a test.

FINISHING IS NOT EXPANDING.
Deliver the whole task. Do not narrow it either — the requested scope IS the
deliverable. "Minimal" means no code beyond what DONE = requires; it never means
a partial implementation, a stub, or a TODO left where work belongs.

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

WHAT "MODIFYING A TEST" MEANS — the whole test, not just its assertions.
A test is its ASSERTIONS *and* the INPUTS that reach them. Weakening either
weakens the test. Every item below counts as modifying it, and none of them may
be used to turn a red run green:
  - Reducing the LOAD or scale the test drives (10 barge-ins -> 5, 200 cycles ->
    40, 8 concurrent steps -> 2). This is the most common evasion and the hardest
    to catch in review, because the assertion still READS as strict while the
    input no longer reaches it.
  - Loosening a tolerance (abs=1e-6 -> 1e-2) or widening an accepted range.
  - Narrowing scope: dropping a parametrize case, an asserted field, or one of
    several asserted parameters (asserting `s` but quietly not `a`).
  - Swapping a real dependency for a stub or mock that cannot fail.
  - Renaming or re-scoping a test so its name no longer describes what it checks.
  - Marking xfail/skip, or moving an assertion behind a condition that is false
    in practice.

WHEN A TEST AND THE SPEC GENUINELY CONFLICT — REPORT, DO NOT RECONCILE.
Stop and surface the conflict. Name the spec line and the test line that
disagree, show the arithmetic or trace that proves it, and propose a fix. A
spec-internal inconsistency is a FINDING to be raised, not an obstacle to be
engineered around. Adjusting either side to force green destroys the evidence
that the spec was wrong.

A TOLERANCE MAY ONLY BE WIDENED FOR A PHYSICAL REASON, STATED IN A COMMENT.
"theta advances by omega*dt between the two reads, so a 1e-6 bound asserts
scheduler timing rather than the reset itself" is a reason. "It was flaky" is
not. Write the reason next to the number.

IF A TEST'S INPUTS MUST CHANGE, SAY SO OUT LOUD.
Changing inputs is sometimes correct — a setup that encoded the OLD behavior, or
a shared literal id that collides with another test through a global singleton.
When it is correct: the test's name and docstring MUST still describe the load it
actually drives, and the change MUST be called out in your report. Never leave it
for a reviewer to discover in the diff.

  # After a test passes, anchor the outcome (inline recording is already done above):
  pin_add(title='feature_name', type='decision')
  # Stamp the feature onto the event chain BEFORE crystallizing (this produces feature_id):
  define_feature(name='feature_name', seed_files=['file1.py', 'file2.py'], thread_id='<session-id>')
  # Crystallize a verified feature into a permanent landmark (>=1 edit + >=1 test pass + >=1 file):
  crystallize_landmark(feature_id=..., name=..., description=...)
  # Checkpoint + trigger on-demand pruning:
  mcm_compress(active_task='what was just completed', active_files=['file1.py', 'file2.py'])

  # Record a failure that revealed something:
  record_test(file=..., result='fail', description='what the failure revealed')
  # NOTE: there is no health.add_warning() tool. Record the lesson as a PiN instead:
  pin_add(title='Warning: <what failed>', type='decision', content='approach tried / what worked')

---

CONTRACT-DRIVEN + BEHAVIORAL TESTING — REQUIRED FOR RECURSIVE SYSTEMS
This project's core loops (DER execution, Sub-Loop fold-back, context pruning, outer
self-tuning) are ONE recursive operator at four scales. Bugs live in the SEAMS between
parts, not inside them. A green unit suite that misses a phantom UI card, a success spoken
after a failure, or a self-tuning constant that cheats its own metric is WORSE than honest —
it hides the real break. Therefore testing is layered and cross-cutting, never unit-only:

  1. CONTRACT TESTS — pin every boundary with an explicit contract:
     - backend → frontend event shape (IRISStreamEvent.TOOL_CALL / result / VALIDATION_FAILED)
     - agent → TTS text shape (speak vs display split; speak never internal narration)
     - loop → ledger record shape (state, action, verified_label for ALL outcomes)
     A contract break is caught at the interface, BEFORE behavior.
  2. BEHAVIORAL TESTS — drive a FULL task through the real loop (plan → execute → verify →
     commit → narrate → display) and assert EMERGENT properties: no phantom card, spoken ⊆
     visible, failure recorded AND shown, self-tuning REJECTS the hack. Run the system as it
     actually runs.
  3. INTERTWINED — contract and behavioral share fixtures and assertions. Every behavioral
     gap found DECOMPOSES into the contract test that would have caught it, so the gap becomes
     a permanent guard. Contract tests are derived from real behavioral traces, not invented.
  4. PHYSICS-AWARE — inject Caducean u/ξ trajectory states and assert system-level outcome
     (split when oscillating, silence when converged, narration fires on band crossing).
  5. STANDING CDD HARNESS — a replay harness (scripts/validate_der_*.py family) replays
     recorded trajectories through the FULL stack and asserts contracts + behaviors on EVERY
     run. This is the gap-finding instrument: if we test correctly, we find the gaps and errors.
     Organize tests as: tests/contract/ (boundary pins) + tests/behavioral/ (full-loop) +
     tests/unit/ (pure logic only). The harness wires them together.

A passing unit test on unoptimized code is not done. A green suite that misses a cross-layer
failure is not done. Quality check is not optional.

---

RECORDING CODE ACTIONS (builds the pheromone trail)

Git commits are auto-recorded by the MCM plugin on every prompt.
You only need to manually record events that are NOT part of a commit:

  # After editing a file (if not yet committed):
  record_edit(file='path/to/file.py', description='what changed', thread_id='<session-id>')

  # After creating a file:
  record_create(file='path/to/file.py', description='what it is', thread_id='<session-id>')

  # After a test passes:
  record_test(file='tests/test_foo.py', result='pass', description='what it verified', thread_id='<session-id>')

  # After a test fails but reveals something important:
  record_test(file='tests/test_foo.py', result='fail', description='what the failure revealed')

  # After an architectural decision:
  pin_add(title='Decision: chose X over Y', type='decision', content='why', tags=['domain'])
  # Notes encode WHY. The semantic layer compresses these over time.

---

PARALLEL SUB-AGENT PROTOCOL
The database is WAL-mode SQLite — safe for concurrent processes.
Work claiming is atomic — two agents cannot take the same item.

  # Orchestrator: see what is available and in progress
  get_session() → check work_items in state

  # Sub-agent workflow:
  # NOTE: claim_work() and complete_task() are NOT exposed on the MCM MCP
  # server. Atomic claiming is described in the SDK docs but has no tool
  # binding here. Until one exists, coordinate work assignment OUTSIDE the
  # graph and record outcomes with record_edit / record_test / pin_add.
  # ... build the feature ...
  record_test(file=..., result='pass', description=..., thread_id='<session-id>')

---


## _CTX GOVERNANCE

Every tool response includes `_ctx`:

| Field | Meaning | When to act |
|-------|---------|-------------|
| `gov` | OK / LOOP / RAPID / TIMEOUT / OVERLOAD / EXIT | OVERLOAD/EXIT -> compress immediately |
| `bal` | Balance 0.5-2.5+ | >2.0 -> compress soon |
| `fail` | Consecutive failures | >=2 -> check approach |
| `ferr` | Last error type | e.g. "ImportError" |
| `lock` | Pattern lock | Same error >=4x -> force compress |
| `stuck` | Work assessment | Engine thinks you are stuck |

**gov="OVERLOAD"**: Pattern lock - 4x same error, edits blocked. Call mcm_compress() to reset.

## BREAKING OUT OF FAILURE SPIRALS

1. Same error keeps repeating -> gov="LOOP" / "OVERLOAD" at 4x
2. mcm_compress() - saves failure state, clears lock, force-prunes context
3. mcm_recall("ErrorName") - see clustered failures with error types and files
4. navigate(file) - check region_failures and failure_trails
5. Do NOT edit the same file again - investigate the topology first

## CONTEXT PRUNING (AUTOMATIC + ON-DEMAND)

Pruning is handled by the `mcm-pruning` OpenCode plugin (register it in this project's
`opencode.json` with `MCM_DB_PATH=C:\dev\IRISVOICE\.mcm\coordinates.db`). You do NOT call a
prune tool manually — the plugin hooks OpenCode's `messages.transform`.

- **Automatic**: when context hits the nudge threshold (55% of the model window, ~70k/128k
  tokens) the plugin prunes older, low-value messages in place. At the hard threshold (65%)
  it prunes more aggressively. The model window is auto-detected from `chat.params`
  (`Model.limit.context`).
- **On-demand**: call `mcm_compress()` to checkpoint AND force-prune immediately. It writes a
  `.mcm_prune_pending.json` marker in the worktree; the plugin consumes and deletes it next turn.
- **What is kept**: the last `recencyWindowTurns` (4) turns, tool calls/results for
  HIGH_KEEP_TOOLS (`task`), and high-salience messages. Everything else is summarized or dropped
  to free tokens.
- **DB isolation**: pruning reads/writes ONLY this project's `.mcm/coordinates.db`. It never
  touches other projects' databases.

---

CONTEXT WINDOW MANAGEMENT


Automatic pruning triggers at 55% (nudge) / 65% (threshold) of the model window (128k tokens
by default; auto-detected from `chat.params` -> `Model.limit.context`). For an explicit
checkpoint + immediate force-prune: `mcm_compress(active_task='...', active_files=[...])`.
After condensing, call mcm_recall(query) to recover knowledge.

Loop prevention — same error twice in a row = change approach:
  pin_add(title='Loop detected: <error>', type='decision', content='approach repeated; correction: try a different approach')

Session end is handled automatically by the MCM lifecycle protocol.
You do not need to run session cleanup manually.

---

## IRIS Voice-Specific Architecture Rules

### Frontend (Next.js)
- **Tests**: `npm test` or `npx jest`
- **Type check**: `npx tsc --noEmit`
- **Lint**: `npm run lint`
- **Component structure**: Use React Server Components where possible
- **Styling**: Tailwind CSS v4 — use `@theme` and `@import "tailwindcss"`
- **State**: React hooks, avoid global state for UI-only data

### Backend (Python FastAPI)
- **Tests**: `pytest` in backend/ or root tests/
- **Type check**: `mypy` or rely on Pydantic models
- **Async**: All I/O must be async — no blocking calls in endpoint handlers
- **WebSockets**: Use FastAPI WebSocket for real-time audio streaming
- **Auth**: OAuth via `auth_handlers/`, credentials in OS keyring only
- **Audio**: Porcupine wake word detection, streaming via WebSocket

### Desktop (Tauri/Rust)
- **Build**: `cargo build` in src-tauri/
- **Tests**: `cargo test` in src-tauri/
- **Window**: Borderless widget, system tray integration
- **Shortcuts**: Global shortcuts registered via Tauri API
- **Bridge**: Frontend ↔ Rust via Tauri commands and events

### Quality Check — Required Before Every Test Run
Verify ALL of these before running tests:
- [ ] No unnecessary work in hot paths — loops, I/O, DB calls as few as needed
- [ ] Heavy imports are lazy — no ML model or GPU init at module level
- [ ] Error handling complete — every exception path has an explicit outcome
- [ ] Resources cleaned up — file handles, connections, subprocesses closed
- [ ] No shared mutable state across sessions or concurrent requests
- [ ] Memory footprint bounded — no unbounded caches or infinite queues
- [ ] Async/sync boundary correct — blocking calls not in async hot paths
- [ ] Logging structured — context identifier in every log line
- [ ] Nothing in this file can crash and block a user response

A passing test on unoptimized code is not done. Quality check is not optional.

### Test Rules — Absolute
Run the spec's test against your implementation.
Never write new tests to match your code.
Never modify existing tests to make them pass.
The test is the requirement.

"Modifying a test" covers its INPUTS as well as its assertions — reducing the
load it drives, loosening a tolerance, dropping a parametrize case, or stubbing a
dependency that could fail are all modifications. See "THE TEST RULE — ABSOLUTE"
above for the full list and for what to do when a test and the spec genuinely
conflict (report it; never reconcile it yourself).

---

### Manual Live Testing & Verification (Web App)
When a feature needs manual live UI testing or visual verification (beyond unit/integration tests), use the **mcp-browser-ui** skill (`~/.opencode/skills/mcp-browser-ui/SKILL.md`). It covers browser control via Playwright/Chrome DevTools MCP, screenshot capture, and vision-subagent verification. Rules to follow from that skill:
- Save ALL screenshots to the canonical `<workspace>/screenshots/` folder (gitignored) with descriptive, timestamped filenames — never scatter them in the repo root or temp dirs.
- The main model cannot see images inline — delegate visual verification to the `vision-minimax` sub-agent.
- Capture a baseline (idle) state plus one screenshot per trigger; verify each trigger at least twice and confirm the backend reacts (e.g., WebSocket messages), not just that a screenshot changed.

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
.mcm/coordinates.db transfers to the application's runtime memory store.
Same schema. No migration. The build memory becomes the app memory.

---

---

MCM TOOL SIGNATURES — VERIFIED 2026-08-25 AGAINST THE LIVE SERVER
Calling an MCM tool with the wrong parameter names does NOT return a validation
error from the server — it HANGS until the 120s client timeout. A hung call may
still have committed its write (verified: one pin_add timed out at the client
and its row was present in the DB afterwards). So a timeout tells you NOTHING
about whether the write landed. Check with db_query before retrying, or you
will create duplicates.

Tools that EXIST on the mcm-cad server:
  get_session, navigate, read_file, mcm_grep, mcm_glob, db_query, query_events,
  health_check, record_edit, record_create, record_test, pin_add, pin_search,
  pin_list, define_feature, crystallize_landmark, mcm_compress, mcm_recall,
  run_command, submit_plan

Tools this document used to reference that DO NOT EXIST:
  claim_work, complete_task, pin_link, health.add_warning
  (also: crystallize_landmark and define_feature carry NO 'mcm_' prefix)

Exact signatures (required args in CAPS):
  record_edit(FILE, description, thread_id)
  record_create(FILE, description, thread_id)
  record_test(FILE, RESULT, description, thread_id)      # result: 'pass'|'fail'
  pin_add(TITLE, content, tags, type)                     # 'type', not 'pin_type'
  define_feature(NAME, SEED_FILES, THREAD_ID, description, since_turn)
  crystallize_landmark(FEATURE_ID, NAME, DESCRIPTION, session_number)
  navigate(FILE)
  db_query(SQL, params, limit)                            # SELECT only
  mcm_grep(PATTERN, directory, include)
  mcm_glob(PATTERN, directory)
  mcm_compress(active_task, active_files, retention)

SPEC / DOMAIN QUICK REFERENCE
Production roadmap:     bootstrap/GOALS.md
Graph queries:          get_session() or navigate(file)
Work queue:             get_session()   (no claim_work tool exists)
Event recording:        record_edit(file=), record_test(file=,result=), record_create(file=)
Session update:         handled automatically by SDK lifecycle
PiN (Primordial Info Nodes): pin_add(title=,content=,type=,tags=), pin_search(query=), pin_list()
Landmarks:                   define_feature() -> crystallize_landmark()
                             (NOTE: no pin_link() tool exists)
Search the repo:             mcm_grep(pattern=,directory=), mcm_glob(pattern=)
                             WARNING: both walk unbounded and have timed out
                             (>120s) at the repo root. Scope to a subdirectory.
Inspect the graph:           db_query(sql=) [read-only, fast], query_events(),
                             health_check(), read_file(file=)
