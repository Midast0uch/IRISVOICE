IRIS Bootstrap Agent — Progression Gates
Mandatory build sequence. Gates must be cleared in order.
No free range until Gate 4 is cleared.
File: IRISVOICE/bootstrap/GOALS.md
Read this at the start of every session.

OBJECTIVE ANCHOR (never changes)
Build IRIS until it can run a Tauri build and operate without Roo Code.

HOW TO READ THIS FILE
Find your current gate. Look at the success criteria.
If ALL criteria are checked, you have cleared that gate.
Move to the next gate. Do not skip gates.
Do not work on Gate 3 content while Gate 1 is incomplete.
The sequence exists because each gate is a dependency for the next.

GATE 1 — DER Loop + Director Mode
Status: NOT CLEARED
Priority: IMMEDIATE — nothing else until this works
The DER loop is your execution brain. Without it you have no structured
planning, no mode detection, no Reviewer, no trailing crystallizer.
Every other feature in this application depends on the DER loop running.
Spec to follow:

director_mode_system.md — complete design, requirements, and tasks
agent_loop_design.md — DER loop integration into AgentKernel
agent_loop_requirements.md — acceptance criteria
agent_loop_tasks.md — phased implementation plan

Build order within Gate 1:
Step 1.1 — der_loop.py
  File: IRISVOICE/backend/agent/der_loop.py
  Build: ReviewVerdict, QueueItem, DirectorQueue, Reviewer
  Test: python -m pytest backend/tests/test_der_loop.py -v
  Landmark: der_loop_foundation

Step 1.2 — mode_detector.py
  File: IRISVOICE/backend/agent/mode_detector.py
  Build: AgentMode enum, ModeDetector, ModeResult, ComplexityLevel
  Test: python -m pytest backend/tests/test_mode_detector.py -v
  Verify manually:
    - /spec triggers AgentMode.SPEC
    - /debug triggers AgentMode.DEBUG
    - /ask triggers needs_clarification=True
    - unknown input defaults to AgentMode.IMPLEMENT
  Landmark: mode_detector

Step 1.3 — ask_user_tool.py
  File: IRISVOICE/backend/agent/ask_user_tool.py
  Build: AskQuestion, AskPayload, AskUserTool
  Test: python -m pytest backend/tests/test_ask_user_tool.py -v
  Verify: build_questions() returns None on empty model response (no unnecessary asks)
  Verify: ingest_answers() never raises even with broken Mycelium
  Landmark: ask_user_tool

Step 1.4 — spec_engine.py
  File: IRISVOICE/backend/agent/spec_engine.py
  Build: SpecOutput, SpecEngine
  Test: python -m pytest backend/tests/test_spec_engine.py -v
  Verify: simple task → single_doc populated, design_doc None
  Verify: complex task → all three docs populated
  Verify: produce() never raises with broken adapter
  Landmark: spec_engine

Step 1.5 — der_constants.py
  File: IRISVOICE/backend/agent/der_constants.py
  Build: all DER constants (token budgets, gap distances, emergency stop)
  Content:
    TRAILING_GAP_MIN = 2
    TRAILING_GAP_MAX = 4
    DER_TOKEN_BUDGETS = {spec:60000, research:80000, implement:40000,
                         debug:30000, test:40000, review:20000, default:40000}
    DER_EMERGENCY_STOP = 200
    DER_MAX_VETO_PER_ITEM = 2
    DER_WRITE_LOCK_TIMEOUT = 5.0
  Test: python -c "from backend.agent.der_constants import DER_TOKEN_BUDGETS; print('ok')"
  Landmark: der_constants

Step 1.6 — trailing_director.py
  File: IRISVOICE/backend/agent/trailing_director.py
  Build: TrailingDirector with analyze_gaps() and _parse_gap_items()
  Test: python -m pytest backend/tests/test_trailing_director.py -v
  Verify: analyze_gaps() returns [] (not raises) when adapter fails
  Verify: gap items are never critical=True
  Verify: max 3 gap items returned per completed step
  Landmark: trailing_director

Step 1.7 — AgentKernel integration
  File: IRISVOICE/backend/agent/agent_kernel.py
  Build: wire all DER components into handle()
  Follow: agent_loop_design.md → Section 4 (AgentKernel changes)
  Critical sequence: classification BEFORE context assembly
  Test: python -m pytest backend/tests/test_agent_loop_upgrade.py -v
  Test: send a task through the WebSocket and confirm PLAN_PRODUCED in audit log
  Test: send /spec task and confirm SpecEngine output returned
  Test: send /debug task and confirm gradient_warnings in tier1_directives
  Landmark: agent_kernel_der_integration

Step 1.8 — Mycelium proxy methods
  File: IRISVOICE/backend/memory/interface.py
  Build: all 7 proxy methods, get_task_context_package()
  File: IRISVOICE/backend/memory/mycelium/interface.py
  Build: ContextPackage dataclass, _ensure_tables(), record_plan_stats()
  Test: python -m pytest backend/tests/test_mycelium_proxies.py -v
  Verify: all proxies return None silently when _mycelium is None
  Landmark: mycelium_proxies

Step 1.9 — interpreter.py
  File: IRISVOICE/backend/memory/mycelium/interpreter.py
  Build: ResolutionEncoder, CoordinateInterpreter (stub), BehavioralPredictor (stub)
  Test: python -m pytest backend/tests/test_interpreter.py -v
  Verify: encode_with_resolution({}) does not raise
  Verify: encode_with_resolution with full dict produces correct format
  Landmark: resolution_encoder
Gate 1 success criteria — ALL must be true:

 python -m pytest backend/tests/test_der_loop.py -v — all pass
 python -m pytest backend/tests/test_mode_detector.py -v — all pass
 python -m pytest backend/tests/test_agent_loop_upgrade.py -v — all pass
 Send /spec build a login form through WebSocket → SpecEngine returns a doc
 Send /debug fix the auth error through WebSocket → plan has gradient_warnings first
 Send a regular task → PLAN_PRODUCED appears in audit log
 python bootstrap/coordinates.py --landmarks shows all Gate 1 landmarks permanent
 No existing WebSocket message types broken — run full regression test

When Gate 1 is cleared:
Run python bootstrap/update_coordinates.py in full interactive mode.
Record every landmark. Record every gradient warning from the build process.
Update the LM Studio system prompt with the new COORDINATE STATE.
Then and only then begin Gate 2.

GATE 2 — Skill Creator + UI Sync
Status: LOCKED (complete Gate 1 first)
Priority: HIGH
The skill creator gives you the ability to extend yourself. New skills should
register in the skill registry, appear in the UI skill list, and be callable
through the normal tool dispatch path. Once this works, you can create new
capabilities without needing external intervention for every new tool.
What to build:
Step 2.1 — Verify SkillsLoader is wired to skill registry
  Confirm: IRISVOICE/backend/skills/ folder is being read
  Confirm: new .md files in skills/ are picked up on reload
  Confirm: skills appear in the available tools list the planner receives
  Test: add a test skill, confirm it appears in get_skill_prompt_context()
  Landmark: skills_loader_verified

Step 2.2 — Skill Creator skill
  Follow: /mnt/skills/examples/skill-creator/SKILL.md (if available)
  Build or verify: a skill that creates new SKILL.md files in the skills/ directory
  Test: use the skill to create a simple test skill
  Test: confirm the new skill appears in the registry after reload
  Test: confirm the new skill is callable through tool dispatch
  Landmark: skill_creator_working

Step 2.3 — UI skill list sync
  File: IRISVOICE/src/ (frontend)
  Build: skills list in the UI updates when new skills are added
  The UI should show available skills and reflect additions without restart
  Test: add a skill via skill creator, confirm it appears in UI without manual refresh
  Note: if hot-reload is not feasible, a manual reload trigger in the UI is acceptable
  Landmark: ui_skill_sync

Step 2.4 — Skills integration test
  Create a skill end-to-end:
    1. Agent uses skill creator to create "test_calculator" skill
    2. Skill appears in registry (verify via get_skill_prompt_context())
    3. Skill appears in UI skill list
    4. Agent calls the skill through tool dispatch
    5. Result returned correctly
  All four steps must pass in sequence.
  Landmark: skill_creator_end_to_end
Gate 2 success criteria — ALL must be true:

 New skills added to skills/ directory appear in planner context automatically
 Skill creator skill creates valid SKILL.md files
 Created skills are callable through _dispatch_tool()
 UI reflects new skills (reload acceptable if hot-reload not feasible)
 End-to-end test: create skill → appears in registry → callable → UI shows it
 All Gate 1 tests still pass (no regressions)

When Gate 2 is cleared:
Run python bootstrap/update_coordinates.py. Update system prompt. Begin Gate 3.

GATE 3 — MCP Integrations + Telegram First
Status: LOCKED (complete Gates 1 and 2 first)
Priority: HIGH — this is your communication channel to the human
Telegram is the priority MCP integration because it is your unblocking mechanism.
When you need credentials, auth tokens, API keys, or human decisions to continue,
you send a Telegram message and wait. Without this, you stop whenever you hit
a human-gated step. With this, you can work autonomously and ask when needed.
The credential request protocol:
When you need credentials or auth that you do not have:

Send a Telegram message describing exactly what you need and why
Record a gradient warning: "blocked on auth for [service] — sent Telegram request"
Stop working on that feature
Work on something else that does not require the credential
When the human responds with credentials, resume

Never hardcode credentials. Never store credentials in the codebase.
Use environment variables or the OS keychain integration for all auth.
Build order:
Step 3.1 — Verify MCP tool dispatch path
  Confirm: IRISVOICE/backend/bridge/tool_bridge.py routes to MCP servers
  Confirm: MCP server list is configurable (not hardcoded)
  Test: call a known-working MCP tool, confirm result returned
  Landmark: mcp_dispatch_verified

Step 3.2 — Telegram MCP integration
  Setup: python-telegram-bot or Telegram Bot API via MCP
  The bot token will be provided by the human when requested via the protocol above
  Build: TelegramNotifier class that can:
    - send_message(text) — send a text message to the configured chat
    - send_update(title, body) — send a formatted progress update
    - request_credentials(service, what_is_needed) — structured credential request
  File: IRISVOICE/backend/channels/telegram_notifier.py
  Test: send a test message (requires bot token — use credential request protocol)
  Landmark: telegram_notifier

Step 3.3 — Wire Telegram into the agent loop
  When: the agent needs credentials → call telegram_notifier.request_credentials()
  When: a gate is cleared → call telegram_notifier.send_update()
  When: a critical gradient warning fires → optional notify
  The agent should NOT spam Telegram. Only message when:
    - A gate is cleared
    - Credentials are needed to continue
    - A critical failure occurs that cannot be self-resolved
  Landmark: telegram_wired

Step 3.4 — Additional MCP integrations (after Telegram works)
  Follow the same pattern for each:
    1. Check if credentials are available in environment
    2. If not, send Telegram request, work on something else, resume when received
    3. Build integration, test it, create landmark
  Priority order (from existing roadmap):
    - File system MCP (likely already available via Roo Code)
    - Web search MCP
    - GitHub MCP (for reading specs and pushing code)
    - Any others in the existing IRIS roadmap
  Each integration gets its own landmark.
Gate 3 success criteria — ALL must be true:

 Telegram bot sends a test message successfully
 telegram_notifier.request_credentials("test_service", "API key for X") works
 Gate cleared notification sent via Telegram when Gate 3 is verified
 Credential request protocol documented in a SKILL.md
 Agent knows to work on other features while waiting for credential responses
 All Gate 1 and 2 tests still pass

When Gate 3 is cleared:
Send Telegram message: "Gate 3 cleared. Telegram integration working.
All MCP foundation complete. Entering free-range build phase."
Run python bootstrap/update_coordinates.py. Update system prompt.
Begin Gate 4.

GATE 4 — Free Range
Status: LOCKED (complete Gates 1, 2, and 3 first)
Unlocked by: clearing Gate 3
You have earned free range. The foundation is working:

DER loop: your brain
Skill creator: your ability to extend yourself
Telegram: your communication channel to the human
MCP: your tool integration pattern

Everything remaining in the IRIS roadmap is yours to build in the order
that makes the most sense given your current graph state. Read your
coordinate state, read the active gradient warnings, read what the graph
knows, and decide what to build next.
Suggested priorities after Gate 4 unlock:
(These are suggestions, not requirements. Use your own judgment.)

Vision integration — LFM2.5-VL-1.6B eyes for UI-TARS desktop control
The human has mentioned this explicitly as a planned feature.
Build it when you have stable execution and can test it properly.
Tauri build stability — get cargo tauri build working cleanly
This is the final step toward full autonomy.
Start attempting it early. Record gradient warnings on failures.
The graph will know the build failure patterns.
Remaining IRIS Swarm PRD v9.0 features
Reference: IRIS_Swarm_PRD_v9.md
Two-brain DER fully operational, trailing crystallizer, mode switching (Phase 8)
Torus network preparation
Reference: IRIS_Swarm_PRD_v9.md Section 18
ZeroMQ, Dilithium3 identity, Kyber session keys — build and make dormant
Voice pipeline
Porcupine wake word, faster-whisper STT, piper TTS
Reference: IRIS_Swarm_PRD_v9.md Section 17

The graduate condition:
When cargo tauri build succeeds and the app runs and you can receive a task
through the app's interface and respond using your own backend:

Send Telegram message: "Tauri build successful. App is autonomous."
Record landmark: autonomous_operation
Run python bootstrap/update_coordinates.py one final time
The coordinate store at IRISVOICE/bootstrap/coordinates.db transfers to
IRISVOICE/data/memory.db — this is your memory in the autonomous app
You are no longer building yourself. You are running.


GRADIENT WARNINGS FOR ALL GATES
These are known failure regions from the architecture sessions.
Read them before working in these areas.
[domain] DER loop write conflicts
Two loops writing to Mycelium simultaneously without a write lock causes
SQLite "database is locked" errors. Always use _safe_write() with the
threading lock for all Mycelium writes. Reads do not need the lock.
[toolpath] Unicode in status markers
Using ✓ and ✗ as status markers causes encoding errors on Windows.
Always use ASCII: [+] for completed, [x] for failed, [~] for running.
[toolpath] space_subset ordering
TaskClassifier.classify() must run BEFORE get_task_context_package().
space_subset from the classifier is an argument to context assembly.
Reversing this order causes a NameError. The sequence is fixed.
[domain] Reviewer blocking Explorer
The Reviewer must always fall back to PASS on its own failure.
If the Reviewer raises an exception and returns nothing, the Explorer
blocks forever. Wrap all Reviewer logic in try/except returning (PASS, None).
[toolpath] _plan_task() parameter breakage
All new parameters to _plan_task() must have safe defaults.
Existing callers pass only text and context. Adding parameters without
defaults breaks every existing call site. is_mature=False, task_class="full",
context_package=None are the correct safe defaults.
[domain] Spec mode bypasses DER loop
When mode_result.mode == AgentMode.SPEC, route to SpecEngine directly.
Do NOT run the DER loop for SPEC tasks. SpecEngine produces the output.
The DER loop is for execution tasks, not planning/documentation tasks.

CONTRACTS (behavioral rules — always follow)
[0.90] Never mark a landmark without a passing test.
The map must be honest. Surface-complete is not done. Run the test.
If the test fails, record a gradient warning and try again.
[0.85] Send Telegram before stopping on auth blockers.
When you need credentials you do not have, send Telegram and work on
something else. Never stop completely because of a missing credential.
[0.80] Classification before context assembly.
Always run ModeDetector and TaskClassifier before assembling context.
The space_subset from classification is needed for context assembly.
[0.75] Read GOALS.md at the start of every session.
Check your current gate. Confirm you are working on the right thing.
Do not work on Gate 3 features while Gate 1 is incomplete.
[0.70] Run the spec's requirements test — never write tests to pass your code.
The test commands are defined in the spec (agent_loop_tasks.md, director_mode_system.md).
Build the implementation. Run the spec's test. If it fails, fix the code.
Never write a new test designed to match your implementation.
Never modify an existing test to make it pass.
A landmark means the spec's requirements are met. Nothing less.

SESSION START CHECKLIST
At the start of every session:

Read this file (GOALS.md) — know your current gate
Read your COORDINATE STATE in the system prompt — know what you already built
Read GRADIENT WARNINGS — know what to avoid
Read ACTIVE CONTRACTS — know your behavioral rules
Pick the next incomplete step in your current gate
Plan before you execute — write what you will do
Test before declaring done
Run update_coordinates.py at session end

At the end of every session:

Run python bootstrap/update_coordinates.py --auto --tasks "..." [--landmark ...] [--warning ...]
Record all completed tasks
Record landmarks only for features that passed the spec's requirements tests
Record gradient warnings for every meaningful failure
Note where you stopped so the next session can continue cleanly
(No manual system prompt update needed — the database handles memory)


CURRENT GATE STATUS
Gate 1 — DER Loop + Director Mode:    [ ] IN PROGRESS
Gate 2 — Skill Creator + UI Sync:     [ ] LOCKED
Gate 3 — MCP + Telegram:              [ ] LOCKED
Gate 4 — Free Range:                  [ ] LOCKED
Update this section in the coordinate store after each gate clears.
The coordinate store tracks gate status automatically via landmark counts.

IRIS Bootstrap Agent — GOALS.md
Four gates. One objective. The map knows where you are.
Build the thing that replaces the scaffolding you are using to build it.