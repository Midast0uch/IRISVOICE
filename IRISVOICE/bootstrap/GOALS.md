IRIS Bootstrap Agent — Production Roadmap
This file defines what needs to be built, fixed, or completed to ship IRIS as a production-quality autonomous assistant.
File: IRISVOICE/bootstrap/GOALS.md
Read this at the start of every session.

OBJECTIVE ANCHOR (never changes)
Build IRIS until it can run fully autonomously: receive tasks through its own interface, execute them using its own backend, and improve itself over time without external scaffolding.

---

GATED MILESTONES (current priority track — gates are sequential)
These gates supersede the domain priority order below for new sessions.
Do not begin a gate's spec work until the previous gate is verified.
Specs for Gates 2-4 will be provided after each gate is confirmed working.

  GATE 1 — DEVELOPER MODE (CURRENT GATE)
  Goal: Frontend + backend running together. Load a 4B or 8B GGUF model from
        C:\Users\midas\.lmstudio\models and chat with it through IRIS.
        Inference must be stable — no RAM spikes, other apps remain usable.

  Inference constraints:
    - Target models: 4B or 8B parameter, Q4_K_M or Q5_K_M quantization
    - Safe defaults: n_ctx=32768, n_batch=1536, n_gpu_layers=-1
    - Backend: ik_llama.cpp (llama-server binary) when installed, else llama-cpp-python
    - ik_llama.cpp handles memory management automatically — install it, then
      remove manual parameter tuning from profiles
    - KV cache compressed (q8_0) to minimize VRAM usage for long contexts
    - Never exceed 85% of available VRAM on model load

  Inference requirements (BOTH must work — not CPU-only):
    - CPU+GPU together: n_gpu_layers=-1 offloads all layers to RTX 3070
    - Requires: Windows SDK installed (rc.exe + mt.exe) → then rebuild llama-cpp-python
      with: CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --upgrade --force-reinstall
    - After rebuild: llama_cpp.llama_supports_gpu_offload() must return True
    - ik_llama.cpp binary preferred when available (auto-detected by _find_llama_server_binary)

  9B TPS benchmark (verified 2026-03-31):
    Qwen3.5-9B-Q3_K_S on RTX 3070 8GB:
      4k ctx  / q8_0 KV: 49 tok/s   (balanced profile)
      32k ctx / q8_0 KV: 50.8 tok/s (balanced profile — IRIS standard)
      100k ctx/ q4_0 KV: 44.1 tok/s (research profile)
      Prompt processing:  1095 tok/s
    All above 25 tok/s target. Balanced profile is the IRIS standard.

  Gate 1 checklist:
    [G1.1] Backend starts cleanly, /health returns 200
    [G1.2] Frontend loads at port 3000, orb connects (green)
    [G1.3] ModelsScreen lists GGUFs from C:\Users\midas\.lmstudio\models
    [G1.4] DONE — llama_cpp 0.3.19 rebuilt with CUDA. llama_supports_gpu_offload()=True.
            RTX 3070 8191MB VRAM, compute capability 8.6. Verified 2026-03-31.
    [G1.5] Load a 9B model with balanced profile (32k ctx, n_batch=2048, full GPU)
            Verified: Qwen3.5-9B-Q3_K_S loads in ~55s, 50.8 tok/s at 32k.
    [G1.6] Send chat through IRIS — response from local GGUF confirmed
    [G1.7] No memory spike on startup — backend starts clean, CUDA only inits
            when user explicitly loads a model (not at startup)
    [G1.8] Tool calling works with iris_local model — skills can be created and
            recalled within the same session (DER loop + episodic memory active)

  G1.4 unblocked. Remaining: start backend + frontend, load model via ModelsScreen,
  send chat, confirm reply from local GGUF with GPU active.
  Do NOT verify Gate 1 on CPU-only. CPU+GPU together is the requirement.

  Verify by: Start both servers, open the app, load a model via ModelsScreen,
  type a message in chat, confirm reply comes from the local GGUF with GPU active.

  GATE 2 — CHAT/TERMINAL HYBRID (spec pending — provided after Gate 1 verified)
  Goal: chat-view.tsx becomes a chat/terminal hybrid by embedding an existing
        open-source terminal interface (xterm.js or equivalent) rather than
        building a CLI renderer from scratch. The terminal is the driver for
        the IRIS agent — input/output flows through the embedded terminal,
        the agent backend remains unchanged. Works in tandem with
        dashboard-wing.tsx. Spec to be given once Gate 1 is confirmed.

  Design intent:
    - Embed xterm.js (or similar) inside chat-view.tsx as a React component
    - Terminal receives agent streaming output and renders it natively
    - User input goes through the terminal → WebSocket → agent kernel
    - Existing open-source CLI platforms/tools can be wired as alternate
      drivers (e.g. pipe output from another CLI tool into the terminal view)
    - No custom CLI rendering code — leverage the open-source ecosystem

  GATE 3 — AGENT KERNEL UPGRADE (spec pending — provided after Gate 2 verified)
  Goal: Agent kernel handles deep multi-step tasks with no loss of direction
        or context. Full DER loop enforcement with token budgets and
        TrailingDirector wired. Spec to be given once Gate 2 is confirmed.

  GATE 4 — MEMORY VISUALIZATION (spec pending — provided after Gate 3 verified)
  Goal: Dashboard becomes a visual Mycelium memory decoder. Users can see and
        interact with IRIS's local memory graph. Spec provided after Gate 3.

---

HOW TO READ THIS FILE
Each section is a domain. Within each domain, items are ordered by impact.
The graduate condition is the final item in each domain.
Do not work on polish while core functionality is broken.
session_start.py runs automatically on every prompt (Claude Code hook) — it tells you
where the graph is, what has been verified, and what failed before.

BUILD SEQUENCE — EVERY FEATURE FOLLOWS THIS ORDER:

  1. Read the domain spec here
  2. Run query_graph.py --file on every file you plan to touch
  3. Read the file — the full function, not just the area you plan to change
  4. Build the feature
  5. Run the quality check (ALL items below must pass before running the test):
       [ ] No unnecessary work in hot paths — loops, I/O, DB calls minimized
       [ ] Heavy imports are lazy — no ML model or GPU init at module level
       [ ] Error handling complete — every exception path has an explicit outcome
       [ ] Resources cleaned up — file handles, connections, subprocesses closed
       [ ] No shared mutable state across sessions or concurrent requests
       [ ] Memory footprint bounded — no unbounded caches or infinite queues
       [ ] Async/sync boundary correct — blocking calls not in async hot paths
       [ ] Logging structured — context identifier in every log line
       [ ] Implementation matches the spec intent, not just its literal words
       [ ] Nothing in this file can crash and block a user response
  6. Run the spec test
  7. PASS: record landmark via agent_context.py --complete
  8. FAIL: fix the code, return to step 5

A passing test on unoptimized code is NOT done. Quality check is not optional.

---

DOMAIN 1 — DER LOOP GAPS (agent brain completeness)
These are architectural features that are defined in code but not yet wired or enforced.
They directly affect the quality of every task the agent executes.

  [1.1] Wire TrailingDirector into _execute_plan_der()
    Status: DONE (verified 2026-03-31 — 17/17 test_trailing_director.py pass)
    File: backend/agent/agent_kernel.py → _execute_plan_der() line ~2751
    What: After each queue.mark_complete(), if len(completed_items) % TRAILING_GAP_MIN == 0,
          calls self._trailing_director.analyze_gaps(item, plan, context_package, is_mature)
          and adds returned QueueItems via queue.add_item(). Gap items have critical=False.
    Test: python -m pytest backend/tests/test_trailing_director.py -v
    Landmark: trailing_director_wired (in der_kernel_full_integration)

  [1.2] Enforce DER token budgets (replace cycle counting)
    Status: DONE (verified 2026-03-31 — 18/18 test_der_loop.py pass)
    File: backend/agent/agent_kernel.py → _execute_plan_der() line ~2515
    What: _token_budget = DER_TOKEN_BUDGETS.get(task_class, ...). _tokens_used
          incremented per step (len(result)/4). Loop exits early when exceeded.
    Test: python -m pytest backend/tests/test_der_loop.py -v
    Landmark: der_token_budget_enforced (in der_kernel_full_integration)

  [1.3] Wire ModeDetector result into _plan_task() and _execute_plan_der()
    Status: DONE (verified 2026-03-31 — 25/25 test_mode_detector.py pass)
    File: backend/agent/agent_kernel.py
    What: _mode_name = _mode_result.mode.name.lower() flows into _execute_plan_der()
          as _der_task_class when mode in DER_TOKEN_BUDGETS.
    Test: python -m pytest backend/tests/test_mode_detector.py -v

  [1.4] Fix record_plan_stats() signature mismatch
    Status: DONE (verified 2026-03-31 — 13/13 test_mycelium_proxies.py pass)
    Files: backend/memory/interface.py, backend/memory/mycelium/interface.py
    Test: python -m pytest backend/tests/test_mycelium_proxies.py -v

  [1.5] Implement CoordinateInterpreter and BehavioralPredictor
    Status: DONE (verified 2026-03-31 — both classes fully implemented)
    File: backend/memory/mycelium/interpreter.py
    What: CoordinateInterpreter.resolve() — 3-rule arbitration (confidence → recency →
          pheromone edge weight). BehavioralPredictor.predict() — pheromone edge analysis.
    Landmark: resolution_encoder (captures all three classes)

  [1.6] Context Engineering C.4 — Mid-loop episodic retrieval
    Status: DONE (verified 2026-03-31 — wired in _execute_plan_der() line ~2612)
    File: backend/agent/agent_kernel.py → _execute_plan_der()
    What: At each DER cycle, queries episodic store for item.description (sub-task).
          Injects matching episodes into item.coordinate_signal as "SUB-TASK HINT: ..."
          when similarity >= 0.55. Uses retrieve_similar() already proven in Option A.
    Test: python -m pytest backend/tests/test_context_engineering.py -v
    Landmark: mid_loop_episodic_c4

  [1.7] Unlimited effective context — _respond_direct uses three memory layers
    Status: DONE (implemented this session)
    File: backend/agent/agent_kernel.py → _assemble_direct_context()
    What changed: Replaced context[-8:] hard roll window with:
      - Layer 2: Episodic store injection (past task summaries via assemble_episodic_context)
      - Layer 3: Token-aware full history (trims oldest messages when budget exceeded,
                 never drops the current turn, never a hard N-message cap)
    Token budget: 20k tokens for history + episodic, leaving ~8k for system + response
    Why this gives unlimited effective context:
      - The agent sees ALL conversation history that fits the 32k window
      - When history grows beyond budget, oldest messages are trimmed BUT
        Layer 2 episodic summaries from Mycelium carry the gist forward
      - DER-executed tasks write episodes to Layer 2 via _store_task_episode() (Option A)
        so every completed task becomes a retrievable memory
      - The 32k window is the immediate execution buffer; Mycelium + episodic is the
        permanent long-term store — together they give unbounded effective recall
    Note: Absolute verbatim recall of very old turns is not possible within a fixed
    context window. The architecture trades verbatim recall for semantic density:
    compressed episodic summaries + coordinate signals carry more actionable context
    per token than raw message history. This matches the Titans/MIRAS research model.
    Landmark: unlimited_context_direct_response

  [1.8] Pacman context lifecycle — zone membrane, decay, crystallization
    Status: DONE (implemented 2026-03-31)
    Files: backend/memory/episodic.py, backend/agent/agent_kernel.py
    What changed (aligned with docs/PACMAN.md blueprint):
      - Zone membrane (Dimension 1): chunk_type maps to zone
          context_fragment → trusted (user's own conversation)
          der_output       → tool    (verified DER/executor output)
          reference/system reserved for future use
      - Age-weighted retrieval scoring (Compounding Cost Curve):
          combined = similarity × 0.80 + recency × 0.20
          recency = 1 / (1 + age_hours / 24.0)   [half-life = 24h]
          Stale chunks cannot win on recency if semantically irrelevant
      - Crystallization pathway: retrieval_count >= 5 triggers
          episode_indexer.index_episode() signal to Mycelium
          Crystallization candidates are never pruned by cleanup_stale_chunks
      - Pacman decay: cleanup_stale_chunks() removes chunks older than
          max_age_hours with retrieval_count <= min_retrievals
      - Schema migration: _migrate_chunk_schema() adds zone + retrieval_count
          columns to existing DBs without data loss (PRAGMA table_info probe)
      - Token budget: chunk_tokens deducted from budget_for_history before
          computing recency anchor size (never overflows _DIRECT_CTX_BUDGET)
    Test: python -m pytest backend/tests/test_context_engineering.py -v
          18/18 pass (9 context engineering + 9 TTS normalizer)
    Docs: docs/CONTEXT_ENGINEERING.md — v2.0 rewrite with full data flow diagram,
          zone taxonomy, scoring formula, call sites table
    Landmark: pacman_lifecycle

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
    Status: DONE — backend/agent/tool_bridge.py AgentToolBridge._mcp_servers["vision"]
    VisionMCPServer registered in initialize(); execute_tool() dispatches
    vision_detect_element, vision_analyze_screen, vision_validate_action,
    vision_get_context through execute_vision_tool() to VisionMCPServer.
    All 5 vision.* tools available. 16/16 test_vision_mcp.py pass.
    Landmark: vision_wired_to_der

  Graduate condition: Agent can describe what is on screen when asked, and can
  click a UI element identified by vision — verified with paint_iris_demo passing.

---

DOMAIN 4 — SKILLS SYSTEM (self-extension)
The skill creator works end-to-end. The skill library is minimal.
This domain is about building a useful library of skills the agent can actually use.

  [4.1] Credential request skill
    Status: DONE — backend/agent/skills/credential-request/SKILL.md exists
    Protocol: bridge.notify_credential_needed(service, what_is_needed) →
    record gradient warning → pivot to other work. Fallback if no Telegram.
    Landmark: credential_request_skill

  [4.2] File read / write skills
    Status: DONE — backend/agent/skills/file-operations/SKILL.md exists
    file_manager MCP server registered in tool_bridge.py with read_file,
    write_file, list_directory, create_directory, delete_file. All routed
    through execute_tool() dispatch path.

  [4.3] Web search skill
    Status: DONE — backend/agent/skills/web-search/SKILL.md exists
    browser MCP server: search (opens Google) + open_url. Registered in
    tool_bridge.py. Opens in user's browser — no text results yet (future).

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
    Status: DONE (permanent landmark: resolution_encoder)
    File: backend/memory/mycelium/interpreter.py
    3-rule arbitration: confidence > recency > pheromone edge strength.
    Stores resolution basis in mycelium_conflicts table. Never raises.

  [5.2] BehavioralPredictor — predict likely next agent actions
    Status: DONE (permanent landmark: resolution_encoder)
    File: backend/memory/mycelium/interpreter.py
    Ranks outgoing pheromone edges by (hit_count/traversal_count)*confidence.
    Returns top-3 predicted tool names. Feeds ContextPackage.tier2_predictions.

  [5.3] Memory transfer — bootstrap DB to runtime DB
    Status: DONE (permanent landmark: memory_transfer_complete)
    Bootstrap landmarks seeded to Mycelium runtime DB on startup — 28 landmarks
    transferred. Verified session 23.

  [5.4] Mycelium maintenance schedule
    Status: DONE — wired in backend/memory/interface.py lines 491-502
    File: backend/memory/interface.py → record_task_outcome() → fires every
    MAINTENANCE_INTERVAL completed tasks via _task_completion_count counter.
    Five-step sequence: edge decay → condense → expand → landmark decay → render dirty.

  Graduate condition: python bootstrap/query_graph.py --summary shows
  BehavioralPredictor returning non-empty tier2_predictions for a real task.

---

DOMAIN 6 — FRONTEND PRODUCTION QUALITY
The UI works but has missing features, rough edges, and unfinished panels.

  [6.1] InferenceConsolePanel — local model status
    Status: DONE — fully wired
    InferenceConsolePanel.tsx listens to iris:ws_message for inference_event
    and model_load_event. useIRISWebSocket.ts now forwards both types.
    backend/agent/agent_kernel.py _respond_direct() emits inference_event after
    every LLM call (streaming: char-estimated tokens; sync: uses resp.usage).
    _broadcast_inference_event() helper: fire-and-forget, never raises.

  [6.2] ModelsScreen — GGUF model management
    Status: DONE — fully wired
    Gap fixed: useIRISWebSocket.ts was not forwarding local_models_list,
    hardware_info, local_model_status, local_model_loading, gguf_download_progress,
    model_pin_updated, hf_models_list to iris:ws_message. All now forwarded.
    ModelsScreen.tsx already listens on iris:ws_message and handles all types.
    handleLoad sends load_local_model with model_path + profile + optional
    custom_params. handleUnload sends unload_local_model.

  [6.3] Orb animation → voice pipeline sync
    Status: DONE — fully wired to backend audio levels
    How: voice_command.py emits audio_level (float, ~100ms cadence) via callback.
         iris_gateway.py broadcasts {type:"audio_level", level:float} via WS.
         useIRISWebSocket sets audioLevel state on audio_level message.
         IrisOrb.tsx: audioLevelScale = 1 + audioLevel*0.15 during listening;
         glow pulse opacity scales with audioLevel. isSpeaking → larger orb + brighter glow.
         All wired: STT mic level → orb pulse, TTS state → orb glow.

  [6.4] Chat history persistence
    Status: DONE (permanent landmark: chat_history_persistence)
    Conversations + activeConversationId persisted to localStorage. Verified.

  [6.5] Settings panel — field save/load
    Status: DONE — settings persist in backend/sessions/session_iris/
    How: ws_manager.connect() derives stable session_id = "session_iris" from
         client_id "iris" when no session_id query param is provided. Session
         state saved to backend/sessions/session_iris/{category}.json files.
         request_state on reconnect restores full state from session files.
    Verified: backend/sessions/session_iris/ exists with theme, voice, agent,
         customize, automate, monitor fields all persisted.

  [6.6] Tab bar state persistence
    Status: DONE (permanent landmark: tab_state_persistence)
    Active tab saved to localStorage iris_active_tab_v1 on change. Verified.

  Graduate condition: App opens, loads previous conversation, last active model
  is loaded, settings are as the user left them — no configuration required.

---

DOMAIN 7 — BACKEND PRODUCTION QUALITY
Core backend correctness issues that affect reliability under real use.

  [7.1] AgentKernel — der_kernel_full_integration
    Status: DONE (permanent landmark: der_kernel_full_integration)
    DER loop 16/16 tests pass — token budget, TrailingDirector, CoordinateInterpreter
    all integrated. Verified session 23.

  [7.2] Error handling — WebSocket disconnect during DER loop
    Status: DONE — wired in backend/agent/agent_kernel.py _execute_plan_der()
    _session_has_client() calls ws_manager.get_clients_for_session() at start
    of each DER cycle. Logs partial outcome + breaks cleanly on disconnect.

  [7.3] Session management — multiple simultaneous users
    Status: DONE — verified in backend/agent/agent_kernel.py
    _agent_kernel_instances dict is keyed by session_id. Each session has its
    own AgentKernel (Reviewer, _mycelium_write_lock, _der_tokens_used all
    per-instance). Model config is intentionally propagated to new sessions
    from existing peers (same model for all sessions). No shared mutable state.

  [7.4] Backend startup sequence
    Status: DONE — /ready endpoint in backend/main.py lines 439-451
    app.state.ready set False at lifespan start, True after full startup.
    /ready returns 503 while starting, 200 when ready. /health always 200.

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
    Status: DONE — binary bundled, auto-start wired
    File: src-tauri/binaries/iris-backend-x86_64-pc-windows-msvc.exe (35 MB)
    What: iris-backend-x86_64-pc-windows-msvc.exe exists in src-tauri/binaries/.
          Tauri main.rs spawns it via app.shell().sidecar("iris-backend") — kills
          on exit. scripts/build_backend.py (PyInstaller) rebuilds when source changes.
    Note: Binary is from a previous build (2026-03-15). Rebuild after source changes
          with: python scripts/build_backend.py

  [8.3] First-run setup
    Status: DONE (permanent landmark: first_run_wizard)
    4-step modal guides new users through model config. Verified session 23.

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

DOMAIN 10 — PERFORMANCE & MEMORY RELIABILITY
IRIS must run without degrading the host machine. A memory spike must never
force the user to restart. Model loading, switching, and unloading must be
clean — no orphan processes, no stale kernel state, no silent crashes.
All inference must stay within safe resource bounds at all times.

Background: A memory spike was identified and fixed (session 28). Session 29
startup audit found four additional root causes fixed:
  1. Porcupine init failure with `raise` crashed entire backend (-> warning now)
  2. pvporcupine DLL imported at module level (-> lazy, inside _initialize_porcupine)
  3. sounddevice (PortAudio) imported at module level in pipeline.py (-> lazy _sd())
  4. TTS prewarm loaded 2 GB CosyVoice with no RAM check (-> psutil 4 GB guard added)
  5. Session cleanup command accidentally deleted session/*.py source files (restored)
Three lines of defense in place: psutil RAM guard, VRAM threshold check, lazy imports.
This domain ensures they stay in place and adds the missing model lifecycle protections.

  [10.1] Memory safety — startup footprint
    Status: DONE — verified 26.8 MB RSS delta (session 29 audit)
    Rule: Backend startup must not load any ML model unless user explicitly loads
          one through the UI. Lazy imports only. No GPU init at import time.
    Verified: import backend → 26.8 MB delta, pvporcupine=False, sounddevice=False,
               faster_whisper=False, torch=False
    Regression test (run after any backend dependency change):
      python -c "
        import psutil, os, sys
        sys.path.insert(0, 'IRISVOICE')
        proc = psutil.Process(os.getpid())
        before = proc.memory_info().rss / 1024 / 1024
        import backend
        after = proc.memory_info().rss / 1024 / 1024
        assert after - before < 200, f'FAIL: RSS delta {after-before:.1f} MB > 200 MB'
        print(f'[PASS] Startup delta: {after-before:.1f} MB')
      "

  [10.2] VRAM guard — audio model loading
    Status: DONE — backend/audio/model_manager.py
    Rule: Never load audio models onto GPU when free VRAM < 8.0 GB. CPU fallback.
    Test: python -m pytest backend/tests/test_model_manager.py::TestVRAMThreshold -v

  [10.3] RAM guard — voice transcription
    Status: DONE — backend/audio/voice_command.py _transcribe_with_fallback()
    Rule: psutil 4 GB RAM check before loading native audio model.
          Low RAM falls through to Google Web Speech API.
    Test: python -m pytest backend/tests/test_voice_command.py::TestVoiceCommandFallback -v

  [10.4] Session cleanup — UUID session directories
    Status: DONE — backend/main.py startup sweep
    Rule: backend/sessions/ pruned at startup. Dirs older than 7 days removed.
          session_iris* dirs are permanent and never pruned.
    Landmark: session_cleanup_on_startup

  [10.5] Pre-load resource validation — GGUF model loading
    Status: DONE — backend/agent/local_model_manager.py _preflight_resource_check()
    Gap: load_model() in local_model_manager.py spawns the subprocess first and
         discovers it fails (OOM, no VRAM) only after the process crashes.
         No pre-flight check exists before Popen().
    Rule: Before spawning the llama-cpp server, validate:
          - Estimate model VRAM from file size (rough: file_size_bytes * 1.1)
          - Free VRAM must be >= estimated_vram (from psutil/nvidia-smi)
          - Free RAM must be >= model_size * 0.5 (for CPU layers + KV cache)
          - If either check fails: send local_model_loading {status: "error",
            error: "Insufficient VRAM/RAM — model requires ~Xgb, Ygb available"}
          - Never spawn the subprocess if the pre-flight fails
    File: backend/agent/local_model_manager.py → load_model() before Popen()
    Test: Mock available VRAM below model size, verify load_model returns False
          immediately with an error event — no subprocess ever spawned.

  [10.6] Concurrent load guard
    Status: DONE — asyncio.Lock (_load_lock) in LocalModelManager.load_model()
    Gap: No lock prevents two simultaneous load_model() calls. Two rapid "Load"
         clicks spawn two subprocesses, the first unload races the second load,
         and the manager ends up in an inconsistent state.
    Rule: load_model() must hold an asyncio.Lock for its full duration.
          A second call while a load is in progress returns immediately with
          {status: "error", error: "Load already in progress"}.
    File: backend/agent/local_model_manager.py — add _load_lock: asyncio.Lock
    Test: Await two concurrent load_model() calls. Verify exactly one succeeds,
          the other returns False with a clear error. No orphan subprocess.

  [10.7] Clean model unload — kernel de-wire and subprocess death
    Status: DONE — watchdog task in LocalModelManager; kernel.configure_openai_compat(None)
            called in _handle_unload_local_model and crash_cb
    Gaps found in code audit:
      a) After unload_model(), the AgentKernel is still wired to port 8082.
         The next user message hits a dead endpoint and gets a silent error.
      b) If the llama-cpp server crashes on its own (OOM, segfault), the
         frontend shows the model as "loaded" because no watchdog exists.
    Rule A (kernel de-wire): _handle_unload_local_model() must call
          kernel.configure_openai_compat(None) to reset the provider after
          unload — or broadcast a local_model_status {status: "unloaded"}
          event so the frontend prompts the user to choose a provider.
    Rule B (watchdog): A background asyncio task polls is_loaded() every 5s
          after a successful load. On crash detected, broadcast:
          {type: "local_model_status", payload: {status: "crashed",
           error: "Model server exited unexpectedly"}}
          and reset _current_model_path = None.
    File: backend/agent/local_model_manager.py (watchdog task)
          backend/iris_gateway.py (kernel de-wire on unload)
    Test: Kill the llama-cpp subprocess manually. Within 10s the frontend
          should receive a local_model_status crashed event.

  [10.8] Clean model switch — no gap state
    Status: DONE — "switching" broadcast in _handle_load_local_model before unload+load
    Gap: Model switch = unload + load. During the gap between the two, the
         frontend shows nothing and any queued user message hits a dead kernel.
         No "switching" transition state is broadcast.
    Rule: Switching models must follow this exact sequence:
          1. Broadcast {status: "switching", from_model: X, to_model: Y}
          2. Wait for any in-flight inference task to complete (or abort it cleanly)
          3. Unload current model (kernel de-wired per 10.7)
          4. Load new model (with pre-flight check per 10.5)
          5. Broadcast {status: "ready", model: Y} or {status: "error"}
    The frontend must disable chat input during "switching" state.
    File: backend/iris_gateway.py → _handle_load_local_model() (already calls
          unload first — needs the broadcast and inference-wait wrapping)
    Test: Load model A, start a chat message, switch to model B mid-response.
          Verify: message completes or is cleanly aborted, model B loads, chat
          re-enables. No exception. No orphan process.

  [10.9] Inference settings hot-apply
    Status: DONE — apply_inference_settings WS message handled in iris_gateway.py;
            would_require_reload() in LocalModelManager decides reload vs. save-only
    Gap: When user changes n_ctx, n_batch, or profile in settings and clicks
         "Apply", there is no dedicated path. The only option is manual
         unload + reload, which is undiscoverable and leaves the user guessing.
    Rule: Implement apply_inference_settings WebSocket message:
          - Receives {profile, custom_params} from frontend
          - Compares to current loaded params
          - If only n_batch changes: apply without reload (server supports it)
          - If n_ctx or n_gpu_layers change: must reload — broadcast
            {status: "reloading_for_settings"} then follow model-switch sequence
          - Saves new params to load_model_settings() for persistence
    File: backend/iris_gateway.py (new handler)
          backend/agent/local_model_manager.py (compare_params helper)
    Test: Apply a profile change while model is loaded. Verify either:
          - Settings applied without reload (for compatible params), OR
          - Clean reload with correct new params (for incompatible params)
          Never crashes. Never leaves model in inconsistent state.

  [10.10] TPS monitoring with gradient warning emission
    Status: DONE — record_tps() in LocalModelManager called from _broadcast_inference_event;
            rolling 3-window with threshold (8 tok/s GPU / 2 tok/s CPU), emits coordinate note
    Gap: [10.6] was listed as MONITORING but no code actually measures or
         enforces TPS. AgentKernel does not log tok/s after responses.
    Rule: After each _respond_direct() or DER loop completion:
          - Measure elapsed_ms / tokens_generated = ms_per_token
          - Convert to tok/s and log: [AgentKernel] TPS: X.X tok/s
          - Maintain a rolling window of last 3 TPS measurements
          - If all 3 are below threshold (8 tok/s GPU / 2 tok/s CPU):
            emit gradient warning to coordinate graph:
            record_event --type note --desc "TPS degraded: X tok/s for 3 runs"
    File: backend/agent/agent_kernel.py → _respond_direct(), _execute_plan_der()
    Test: Mock a slow LLM response (> 125ms/token). Verify warning is emitted
          after 3 consecutive slow responses.

  Graduate condition: All 10 items above have DONE status.
  Final verification:
    1. Start the app cold — startup RSS delta < 200 MB
    2. Load a model — no crash, clean progress events to frontend
    3. Send a message — response received, TPS logged
    4. Change inference settings — clean reload or hot-apply
    5. Switch to a different model — no gap state, no orphan subprocess
    6. Unload the model — kernel de-wired, frontend notified
    7. Kill the backend process manually mid-inference — app recovers cleanly
    8. Run 30 minutes of active use — RSS growth < 500 MB (psutil sampled)

---

SESSION START CHECKLIST
At the start of every session (Claude Code: fully automated via hooks):

  1. session_start.py runs automatically on every prompt (UserPromptSubmit hook)
     — loads coordinate state, auto-syncs any unrecorded git commits
  2. python bootstrap/agent_context.py          (check available work)
  3. Read this file — pick the highest-priority incomplete item
  4. Read the spec for that item before touching any file
  5. Navigate the graph before touching any file:
       python bootstrap/query_graph.py --file path/to/file.py
  6. Build → QUALITY CHECK → test → record → repeat

  Other agents (Cursor, Windsurf, etc.): run session_start.py manually in step 1.

At the end of every session (Claude Code: automated via Stop hook):

  Stop hook runs automatically:
    - mid_session_snapshot.py saves progress notes
    - update_coordinates.py --auto closes the session in the graph

  Other agents: run manually:
    python bootstrap/update_coordinates.py --auto --tasks "..." [--landmark ...] [--warning ...]
    python bootstrap/mid_session_snapshot.py --progress "what was just completed"

MID-SESSION (at ~50k tokens):

  python bootstrap/mid_session_snapshot.py --progress "current progress"
  Then condense context.
  After condensing: session_start.py runs automatically on next prompt (Claude Code)
  Other agents: run python bootstrap/session_start.py --compact manually.

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
  [1.00] Run the quality check before running any test. A passing test on
         unoptimized code is a time bomb, not a landmark.
  [0.95] Navigate the graph (query_graph.py --file) before touching any file.
  [0.90] Session state loads automatically on every prompt — do not skip it.
  [0.85] Send Telegram before stopping on auth blockers.
  [0.80] Classification before context assembly (Step 2 before Step 3).
  [0.75] Read the spec for an area before touching its files.
  [0.70] Run the spec's requirements test — never write tests to pass your code.

IRIS Production Roadmap — bootstrap/GOALS.md
Nine domains. One objective. Ship a working autonomous assistant.
