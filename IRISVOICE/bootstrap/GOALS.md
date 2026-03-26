IRIS Bootstrap Agent — Production Roadmap
This file defines what needs to be built, fixed, or completed to ship IRIS as a production-quality autonomous assistant.
File: IRISVOICE/bootstrap/GOALS.md
Read this at the start of every session.

OBJECTIVE ANCHOR (never changes)
Build IRIS until it can run fully autonomously: receive tasks through its own interface, execute them using its own backend, and improve itself over time without external scaffolding.

HOW TO READ THIS FILE
Each section is a domain. Within each domain, items are ordered by impact.
The graduate condition is the final item in each domain.
Do not work on polish while core functionality is broken.
Use python bootstrap/session_start.py at the start of every session — it tells you
where the graph is, what has been verified, and what failed before.

---

DOMAIN 1 — DER LOOP GAPS (agent brain completeness)
These are architectural features that are defined in code but not yet wired or enforced.
They directly affect the quality of every task the agent executes.

  [1.1] Wire TrailingDirector into _execute_plan_der()
    Status: NOT DONE
    File: backend/agent/agent_kernel.py → _execute_plan_der()
    Gap: TrailingDirector.analyze_gaps() exists in trailing_director.py and is
         fully implemented. It is never called.
    Fix: After each queue.mark_complete(), if len(completed_items) % TRAILING_GAP_MIN == 0,
         call trailing_director.analyze_gaps(item, plan, context_package, is_mature)
         and add returned QueueItems via queue.add_item(). Gap items have critical=False.
    Test: python -m pytest backend/tests/test_trailing_director.py -v
    Landmark: trailing_director_wired

  [1.2] Enforce DER token budgets (replace cycle counting)
    Status: NOT DONE
    File: backend/agent/agent_kernel.py → _execute_plan_der()
          backend/agent/der_constants.py → DER_TOKEN_BUDGETS (already defined)
    Gap: _execute_plan_der() uses max_cycles=40. Token budgets are defined but
         self._der_tokens_used is never incremented or checked.
    Fix: Track tokens used per step. Break loop when _der_tokens_used exceeds
         DER_TOKEN_BUDGETS[mode] (default: 40_000). Pass mode through from
         ModeDetector result.
    Test: python -m pytest backend/tests/test_der_loop.py -v
    Landmark: der_token_budget_enforced

  [1.3] Wire ModeDetector result into _plan_task() and _execute_plan_der()
    Status: PARTIAL
    File: backend/agent/agent_kernel.py
    Gap: ModeDetector.detect() is called but the mode result does not flow into
         _plan_task() to select temperature or into _execute_plan_der() to select
         the correct token budget.
    Fix: Pass mode_result.mode as a parameter to both. Use it to select
         DER_TOKEN_BUDGETS[mode_result.mode.name] in _execute_plan_der().
    Test: python -m pytest backend/tests/test_mode_detector.py -v

  [1.4] Fix record_plan_stats() signature mismatch
    Status: NOT DONE
    Files: backend/memory/interface.py, backend/memory/mycelium/interface.py
    Gap: Call sites pass different fields than the proxy signature expects.
         plan_id and task fields are missing from some call sites.
    Fix: Audit both signatures. Align them. Add missing fields with safe defaults.
    Test: python -m pytest backend/tests/test_mycelium_proxies.py -v

  [1.5] Implement CoordinateInterpreter and BehavioralPredictor
    Status: STUBS ONLY
    File: backend/memory/mycelium/interpreter.py
    Gap: class CoordinateInterpreter: pass — empty body
         class BehavioralPredictor: pass — empty body
         Only ResolutionEncoder is implemented.
    Fix: Implement both classes per their spec roles in agent_loop_design.md.
    Landmark: interpreter_complete

  Graduate condition: agent processes a multi-step task, Reviewer refines at least
  one step, TrailingDirector adds at least one gap item, token budget enforced.

---

DOMAIN 2 — VOICE PIPELINE (sensory input)
IRIS is a voice assistant. Without a working voice pipeline, users cannot
interact naturally. This is the primary input modality.

  [2.1] Wake word detection (Porcupine)
    Status: PARTIAL — detector code exists, activation untested end-to-end
    Files: backend/voice/porcupine_detector.py
    Gap: Wake word detection may work but is not integrated into a live audio loop
         that feeds into the agent's prompt pipeline.
    Fix: Verify PorcupineWakeWordDetector activates, feeds "wake detected" signal
         to the frontend orb animation and to the STT pipeline.
    Test: Manual — say wake word, orb activates, STT begins

  [2.2] Speech-to-text (faster-whisper)
    Status: UNKNOWN — check if faster-whisper is installed and configured
    Files: backend/voice/ (check for whisper integration)
    Fix: Wire faster-whisper to produce transcript text that feeds
         process_text_message() as if the user typed it.
    Test: Speak a sentence, verify transcript appears in chat

  [2.3] Text-to-speech (CosyVoice or piper)
    Status: CosyVoice directory exists (backend/voice/CosyVoice/)
    Gap: Whether TTS is wired to the response pipeline is unknown.
    Fix: Verify TTS is called with agent response text and plays audio output.
    Test: Agent responds, audio plays

  [2.4] Voice-first DER loop mode
    Status: NOT STARTED
    Gap: DER_TOKEN_BUDGETS has "voice_first" as an inference profile label
         but no DER mode maps to it.
    Fix: When voice pipeline is active, use tighter token budget (under 20k)
         and prefer single-step responses over multi-step plans.
    Landmark: voice_pipeline_end_to_end

  Graduate condition: wake word → STT → agent response → TTS plays — full cycle
  without any manual keyboard input.

---

DOMAIN 3 — VISION SYSTEM (desktop perception)
IRIS needs to see the screen to act as a desktop automation agent.
The vision layer is defined in code but may not be operational.

  [3.1] Verify LFM2.5-VL MCP server is operational
    Status: DEVELOPING (1/3 passes for vision_layer landmark)
    Files: backend/tools/vision_mcp_server.py, backend/tools/lfm_vl_provider.py
    Test: python -m pytest backend/tests/test_vision_mcp.py -v
    Gap: Server may not start cleanly or model may not load.
    Fix: Get the test passing 2 more times to crystallize vision_layer as permanent.
    Landmark: vision_layer (needs 2 more passes)

  [3.2] UniversalGUIOperator — perception-action-verify loop
    Status: DEVELOPING (1/3 passes for paint_iris_demo)
    Files: backend/agent/universal_gui_operator.py, scripts/paint_iris_demo.py
    Test: python scripts/paint_iris_demo.py
    Gap: Demo script has high-signal failures (score 0.68-0.72). Root cause unknown.
    Fix: Run the demo script, read the failure, fix the underlying issue.
    Landmark: paint_iris_demo (needs 2 more passes)

  [3.3] Wire vision into agent tool dispatch
    Status: NOT DONE
    Files: backend/bridge/tool_bridge.py
    Gap: Vision capture and analysis are not available as tools the DER loop can call.
    Fix: Register vision tools (capture_screen, analyze_region, find_element) in
         the tool registry so the Explorer can invoke them as item.tool values.
    Landmark: vision_wired_to_der

  Graduate condition: Agent can describe what is on screen when asked, and can
  click a UI element identified by vision — verified with paint_iris_demo passing.

---

DOMAIN 4 — SKILLS SYSTEM (self-extension)
The skill creator works end-to-end. The skill library is minimal.
This domain is about building a useful library of skills the agent can actually use.

  [4.1] Credential request skill
    Status: NOT DONE
    Gap: Telegram is wired but has no bot token. The credential request protocol
         (send Telegram → wait → resume) is documented in GOALS.md but no SKILL.md
         exists for it.
    Fix: Create SKILL.md for credential_request. When agent needs auth:
         1. Call telegram_notifier.request_credentials(service, what_needed)
         2. Record gradient warning: "blocked on auth for [service]"
         3. Stop working on that feature, pick something else
         When credential arrives: resume.
    Landmark: credential_request_skill

  [4.2] File read / write skills
    Status: UNKNOWN — check if filesystem MCP is available
    Gap: Agent may not be able to read/write files through the skill dispatch path.
    Fix: Verify filesystem MCP is available and register file read/write/search
         as dispatchable skills.

  [4.3] Web search skill
    Status: UNKNOWN
    Fix: Wire web search MCP (or implement direct HTTP search) as a skill.
         Agent should be able to research before implementing.

  [4.4] GitHub MCP skill
    Status: NOT DONE
    Fix: Wire GitHub MCP for reading specs, creating PRs, reading issues.
         Requires bot token from Telegram credential request protocol.

  [4.5] Self-improvement skill
    Status: PARTIAL — skill creator works but agent does not use it proactively
    Gap: The agent does not create new skills when it identifies a repeated pattern.
    Fix: After any task where the same tool sequence appears 3+ times, trigger
         skill creator to codify that pattern into a SKILL.md.

  Graduate condition: Agent creates a new skill mid-task without being asked,
  the skill appears in the registry and is callable in a subsequent session.

---

DOMAIN 5 — MYCELIUM MEMORY MATURATION
The graph is mature (confidence 0.95) but several components are stubs.
These limit the quality of context packages the Reviewer receives.

  [5.1] CoordinateInterpreter — resolve coordinate conflicts
    Status: STUB (class pass)
    File: backend/memory/mycelium/interpreter.py
    Fix: Implement coordinate conflict resolution. When two nodes have overlapping
         coordinate claims, CoordinateInterpreter should arbitrate.

  [5.2] BehavioralPredictor — predict likely next agent actions
    Status: STUB (class pass)
    File: backend/memory/mycelium/interpreter.py
    Fix: Implement prediction based on pheromone edge weights. Given current task
         class and topology position, predict the 3 most likely next steps.
         These predictions should populate ContextPackage.tier2_predictions.

  [5.3] Memory transfer — bootstrap DB to runtime DB
    Status: NOT DONE
    Gap: The graduate condition in the original GOALS.md said:
         "bootstrap/coordinates.db transfers to data/memory.db"
         This has not been done. The build memory and app memory are still separate.
    Fix: When app launches and data/memory.db does not exist, copy
         bootstrap/coordinates.db to data/memory.db. Same schema, no migration.
    Landmark: memory_transfer_complete

  [5.4] Mycelium maintenance schedule
    Status: UNKNOWN — run_maintenance() exists but unclear when it's called
    File: backend/memory/mycelium/interface.py → run_maintenance()
    Fix: Schedule run_maintenance() to run every N sessions (not every request).
         Five-step sequence: edge decay → condense → expand → landmark decay → render dirty.

  Graduate condition: python bootstrap/query_graph.py --summary shows
  BehavioralPredictor returning non-empty tier2_predictions for a real task.

---

DOMAIN 6 — FRONTEND PRODUCTION QUALITY
The UI works but has missing features, rough edges, and unfinished panels.

  [6.1] InferenceConsolePanel — local model status
    Status: FILE EXISTS (components/dashboard/InferenceConsolePanel.tsx) but
            integration state unknown
    Gap: The inference console should show: active GGUF model, hardware profile,
         context length, GPU layers, tokens/sec.
    Fix: Wire InferenceConsolePanel to the backend's hardware_info endpoint
         and the local_model_manager state.

  [6.2] ModelsScreen — GGUF model management
    Status: PARTIAL — HF search wired, local scan wired
    Gap: Loading a model and switching the active model may not work end-to-end.
    Fix: Verify load_model WS message triggers LFM local inference. Verify
         the active model persists across sessions.

  [6.3] Orb animation → voice pipeline sync
    Status: PARTIAL — orb animates but may not be tied to actual audio levels
    Fix: Wire the orb's animation state to: (a) microphone input level during
         STT, (b) TTS playback state during response.

  [6.4] Chat history persistence
    Status: UNKNOWN — conversations exist in React state but may not persist
    Gap: Closing and reopening the app likely clears conversation history.
    Fix: Persist conversation history to a local SQLite DB (or use the Mycelium
         episodic layer as the backing store).

  [6.5] Settings panel — field save/load
    Status: PARTIAL — fields render via SidePanel but persistence unclear
    Gap: User changes to voice settings, model settings, etc. may not save.
    Fix: Verify field values are saved to backend state and restored on app open.

  [6.6] Tab bar state persistence
    Status: UNKNOWN
    Fix: Active tab (voice/agent/automate/etc.) should restore after restart.

  Graduate condition: App opens, loads previous conversation, last active model
  is loaded, settings are as the user left them — no configuration required.

---

DOMAIN 7 — BACKEND PRODUCTION QUALITY
Core backend correctness issues that affect reliability under real use.

  [7.1] AgentKernel — der_kernel_full_integration (1/3 passes)
    Status: DEVELOPING
    Test: python -m pytest backend/tests/test_agent_loop_upgrade.py -v
    Fix: Get the test passing 2 more times with real backend running.
    Landmark: der_kernel_full_integration (needs 2 more passes)

  [7.2] Error handling — WebSocket disconnect during DER loop
    Status: UNKNOWN
    Gap: If client disconnects mid-execution, the DER loop may continue
         consuming resources with no way to deliver the result.
    Fix: Check client connection status before each DER cycle. If disconnected,
         record partial outcome to Mycelium and exit cleanly.

  [7.3] Session management — multiple simultaneous users
    Status: UNKNOWN
    Gap: AgentKernel is created per session_id. Check that two concurrent
         sessions do not share state (Reviewer, memory write lock, etc.).

  [7.4] Backend startup sequence
    Status: PARTIAL — backend starts but sequence timing is fragile
    Gap: If backend starts before all models are loaded, WebSocket connections
         may arrive before the agent is ready.
    Fix: Add readiness probe. WebSocket connections should queue or return
         "not ready" until all critical services are initialized.

  [7.5] Logging — structured, queryable
    Status: PARTIAL — print() and logger.info() mixed throughout
    Fix: Standardize on Python logging. Add session_id to all log records.
         Route agent execution logs to a file that can be tailed in InferenceConsolePanel.

  Graduate condition: 100 sequential requests processed without error or memory leak.
  Test by sending 100 text messages through the WebSocket and checking outcomes.

---

DOMAIN 8 — DISTRIBUTION & INSTALLATION
Getting IRIS into the user's hands without requiring developer setup.

  [8.1] MSI installer — verify it installs and runs
    Status: MSI built (cargo tauri build succeeded)
    Gap: The installer has not been run on a clean machine.
    Fix: Install from MSI on a machine without the dev environment.
         Verify the app launches and connects to the bundled backend.

  [8.2] Backend bundling in Tauri
    Status: iris-backend.exe is listed in externalBin but may not exist
    File: src-tauri/tauri.conf.json → "externalBin": ["binaries/iris-backend"]
    Gap: The binaries/ directory does not exist. The Tauri build currently works
         because it builds without the bundled binary. In production, the backend
         must be bundled or auto-started.
    Fix: Either (a) compile a standalone iris-backend.exe and add to binaries/,
         or (b) update the Tauri app to spawn python start-backend.py on launch.

  [8.3] First-run setup
    Status: NOT DONE
    Gap: A new user has no Mycelium database, no API keys, no model loaded.
         The app needs to guide them through first-run configuration.
    Fix: Detect first run (no data/memory.db). Show setup wizard:
         1. Select inference mode (cloud API / local GGUF / LM Studio)
         2. Enter API key if cloud (Telegram credential request protocol)
         3. Download or select GGUF model if local
         4. Test voice input
    Landmark: first_run_wizard

  Graduate condition: Person who has never used IRIS installs from MSI, runs the
  app, and sends their first message to the agent — no terminal required.

---

DOMAIN 9 — ADVANCED FEATURES (after core is solid)
Do not start these until Domains 1-5 are complete.

  [9.1] Torus network preparation
    Reference: IRIS_Swarm_PRD_v9.md Section 18
    Build and make dormant: ZeroMQ messaging, Dilithium3 identity, Kyber session keys.
    Agent instances should be able to discover and communicate when activated.

  [9.2] Two-brain DER — second instance with different context
    Reference: IRIS_Swarm_PRD_v9.md Phase 8
    Run two AgentKernel instances on the same task. Instance B sees what Instance A
    vetoed. Shared Mycelium write lock coordinates them.

  [9.3] Trailing crystallizer — full crystallization cycle
    The trailing Director (Domain 1.1) + landmark crystallization (already working)
    together form the trailing crystallizer. Once Domain 1.1 is done, verify
    crystallization fires correctly for gap-filled items.

---

SESSION START CHECKLIST
At the start of every session:

  1. python bootstrap/session_start.py          (full state)
  2. python bootstrap/agent_context.py          (available work)
  3. Read this file — pick the highest-priority incomplete item
  4. Read the spec for that item before touching any file
  5. Build → test → record → repeat

At the end of every session:

  python bootstrap/update_coordinates.py --auto --tasks "..." [--landmark ...] [--warning ...]
  python bootstrap/mid_session_snapshot.py --progress "what was just completed"

MID-SESSION (at ~50k tokens):

  python bootstrap/mid_session_snapshot.py --progress "current progress"
  Then ask Claude Code to condense context.
  After condensing: python bootstrap/session_start.py --compact

PRIORITY ORDER FOR NEW SESSIONS
  1. Domain 1 — DER loop gaps (every task depends on this)
  2. Domain 3 — Vision (paint_iris_demo, vision_layer — already developing)
  3. Domain 2 — Voice pipeline (primary input modality)
  4. Domain 5 — Mycelium stubs (improves Reviewer quality)
  5. Domain 7 — Backend reliability (needed before distribution)
  6. Domain 4 — Skills library (self-extension)
  7. Domain 6 — Frontend polish (quality of life)
  8. Domain 8 — Distribution (needed to ship)
  9. Domain 9 — Advanced features (after everything else)

CONTRACTS (behavioral rules — always follow)
  [1.00] Never mark a landmark without a passing test.
  [0.90] Run session_start.py before any code changes.
  [0.85] Send Telegram before stopping on auth blockers.
  [0.80] Classification before context assembly (Step 2 before Step 3).
  [0.75] Read the spec for an area before touching its files.
  [0.70] Run the spec's requirements test — never write tests to pass your code.

IRIS Production Roadmap — bootstrap/GOALS.md
Nine domains. One objective. Ship a working autonomous assistant.
