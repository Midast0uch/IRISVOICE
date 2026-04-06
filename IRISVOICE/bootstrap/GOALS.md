IRIS Bootstrap Agent — Production Roadmap
This file defines what needs to be built, fixed, or completed to ship IRIS as a production-quality autonomous assistant.
File: IRISVOICE/bootstrap/GOALS.md
Read this at the start of every session.

OBJECTIVE ANCHOR (never changes)
Build IRIS until it can run fully autonomously: receive tasks through its own interface, execute them using its own backend, and improve itself over time without external scaffolding.

---

WHAT NEEDS WORK RIGHT NOW (quick read for session start)

  GATE STATUS: Gate 1 is the current gate.
    G1.1–G1.5 verified. G1.6, G1.7, G1.8 need hands-on confirmation.

  DOMAINS WITH OPEN ITEMS:
    Domain 2  — Voice pipeline  (PARTIAL — [2.1][2.2][2.3][2.4] open)
    Domain 3  — Vision          (DEVELOPING — [3.1][3.2] need 2 more passing runs each)
    Domain 4  — Skills          (PARTIAL — [4.4][4.5] not done)
    Domain 7  — Backend quality (PARTIAL — [7.5] logging not standardised)
    Domain 8  — Distribution    (PARTIAL — [8.1] MSI untested on clean machine)
    Domain 11 — PiN verification (ALL 5 items not started — run these next)
    Domain 12 — MCP storage      (ALL 5 items not started — after D11 passes)

  DOMAINS COMPLETE (do not revisit unless regression):
    Domain 1  — DER loop gaps       ✓ all 8 items verified
    Domain 5  — Mycelium stubs      ✓ all 4 items verified
    Domain 6  — Frontend quality    ✓ all 6 items verified
    Domain 10 — Performance/memory  ✓ all 10 items verified

  PRIORITY ORDER FOR NEW SESSIONS:
    1. Domain 11 — PiN + landmark bridge verification (foundation, run tests)
    2. Domain 3  — Vision (paint_iris_demo, vision_layer — 2 more passes each)
    3. Domain 2  — Voice pipeline (primary input modality)
    4. Domain 12 — PiN + MCP storage integrations (after D11 verified)
    5. Domain 4  — Skills library (self-extension)
    6. Domain 7  — Backend reliability (logging standardisation)
    7. Domain 8  — Distribution (MSI clean install)
    8. Domain 9  — Advanced features (after everything else)

---

GATED MILESTONES (gates are sequential — do not start Gate 2 until Gate 1 verified)

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
    [G1.5] DONE — Load a 9B model with balanced profile (32k ctx, n_batch=2048, full GPU)
            Verified: Qwen3.5-9B-Q3_K_S loads in ~55s, 50.8 tok/s at 32k.
    [G1.6] Send chat through IRIS — response from local GGUF confirmed
            Status: needs hands-on run (G1.4/G1.5 done, full chat loop not confirmed)
    [G1.7] No memory spike on startup — backend starts clean, CUDA only inits
            when user explicitly loads a model (not at startup)
            Status: startup RSS delta < 200 MB verified (Domain 10 audit), but
            end-to-end with frontend not confirmed
    [G1.8] Tool calling works with iris_local model — skills can be created and
            recalled within the same session (DER loop + episodic memory active)
            Status: DER loop + episodic verified in tests; end-to-end not confirmed

  Verify by: Start both servers, open the app, load a model via ModelsScreen,
  type a message in chat, confirm reply comes from the local GGUF with GPU active.
  Do NOT verify Gate 1 on CPU-only. CPU+GPU together is the requirement.

  GATE 2 — CHAT/TERMINAL HYBRID (spec written — activate after Gate 1 verified)
  Goal: chat-view.tsx becomes a chat/terminal hybrid by embedding an existing
        open-source terminal interface (xterm.js or equivalent). The TUI is a
        pure display/input layer — IRIS owns all intelligence, context, security,
        and output parsing. Zero setup or config required inside the terminal.
        Works in tandem with dashboard-wing.tsx.

  Architecture (TUI is dumb, IRIS is smart):
    User input → xterm.js → WebSocket → security_filter → iris_gateway
                                                         → agent_kernel
                                                         → tool_bridge
                                                         → output parser
    Streaming output → WebSocket → xterm.js (renders as-is)

  What the TUI does (only):
    - Accepts raw user keystrokes and sends them via WebSocket
    - Renders streaming text/ANSI output from the agent
    - Displays tool call activity, DER loop steps, memory signals as they arrive
    - No config, no setup, no state — stateless display driver

  What IRIS handles (unchanged, just wired to the new driver):
    - security_filter.py + mcp_security.py: all permission checks, allowlists,
      audit logging — every tool call validated before execution, result sanitized
      before it reaches the terminal
    - iris_gateway.py: application context management — session, persona, mode
    - agent_kernel.py: DER loop, task planning, tool orchestration
    - tool_bridge.py: MCP tool execution and output parsing — raw tool results
      are parsed and formatted before being written to the terminal stream
    - Mycelium memory: context assembly, episodic recall, landmark injection
      all happen transparently — terminal never needs to know

  Security wiring (already built, needs UI connection):
    - gateway/security_filter.py: message sanitization + injection detection
    - security/allowlists.py: tool execution allowlists
    - security/mcp_security.py: MCP channel trust + HyphaChannel guards
    - All three must be in the request path before any tool runs through the TUI
    - Security violations surface as formatted error lines in the terminal output

  Alternate drivers:
    - Any open-source CLI tool that writes to stdout can pipe through as an
      alternate agent driver without backend changes
    - The WebSocket protocol is the only interface — the TUI is interchangeable

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

DOMAIN 1 — DER LOOP GAPS ✓ COMPLETE
All items verified. Do not re-open unless a regression test fails.

  [1.1] Wire TrailingDirector into _execute_plan_der()
    Status: DONE (verified 2026-03-31 — 17/17 test_trailing_director.py pass)
    Landmark: trailing_director_wired

  [1.2] Enforce DER token budgets (replace cycle counting)
    Status: DONE (verified 2026-03-31 — 18/18 test_der_loop.py pass)
    Landmark: der_token_budget_enforced

  [1.3] Wire ModeDetector result into _plan_task() and _execute_plan_der()
    Status: DONE (verified 2026-03-31 — 25/25 test_mode_detector.py pass)

  [1.4] Fix record_plan_stats() signature mismatch
    Status: DONE (verified 2026-03-31 — 13/13 test_mycelium_proxies.py pass)

  [1.5] Implement CoordinateInterpreter and BehavioralPredictor
    Status: DONE — 3-rule arbitration + pheromone edge ranking both operational
    Landmark: resolution_encoder

  [1.6] Context Engineering C.4 — Mid-loop episodic retrieval
    Status: DONE (verified 2026-03-31 — wired in _execute_plan_der())
    Landmark: mid_loop_episodic_c4

  [1.7] Unlimited effective context — _respond_direct uses three memory layers
    Status: DONE — Layer 2 episodic + Layer 3 token-aware full history
    Landmark: unlimited_context_direct_response

  [1.8] Pacman context lifecycle — zone membrane, decay, crystallization
    Status: DONE (implemented 2026-03-31)
    Zone membrane: trusted (user context) / tool (DER output)
    Age-weighted retrieval: combined = similarity×0.80 + recency×0.20
    Crystallization: retrieval_count >= 5 → index_episode() signal
    Landmark: pacman_lifecycle

  Regression tests (run if any DER-adjacent file is changed):
    python -m pytest backend/tests/test_trailing_director.py -v
    python -m pytest backend/tests/test_der_loop.py -v
    python -m pytest backend/tests/test_context_engineering.py -v

---

DOMAIN 2 — VOICE PIPELINE (sensory input)
IRIS is a voice assistant. Without a working voice pipeline, users cannot
interact naturally. This is the primary input modality.

  Architecture summary (verified via test suite 2026-04-05):
    wake word (Porcupine, lazy) → AudioEngine frame loop → VoiceCommandHandler
    → faster-whisper STT (lazy, tiny/int8) → iris_gateway._on_voice_result
    → _process_voice_transcription() → process_text_message(from_voice=True)
    → _speak_response() → TTSManager.synthesize_stream() → Piper (F5-TTS optional)
    All lazy imports confirmed. Platform-aware .ppn selection confirmed.

  [2.1] Wake word detection (Porcupine)
    Status: STRUCTURAL VERIFIED (test_domain2_voice.py 38/38 pass)
    What was confirmed:
      - PorcupineWakeWordDetector disables gracefully (no access key → _disabled=True)
      - Disabled reason string is descriptive (mentions PICOVOICE_ACCESS_KEY)
      - Disabled on no wake words configured (v1 path also tested)
      - pvporcupine lazy-loaded inside _initialize_porcupine (not at module level)
      - Gateway has set_voice_handler() wired to _on_voice_result callback
      - gateway._voice_handler checked before start_recording()
    Remaining gap: manual end-to-end test needed (say wake word → orb activates)
    Test: say wake word, verify orb activates and STT begins (manual)
    Regression: python -m pytest backend/tests/test_domain2_voice.py -v

  [2.2] Speech-to-text (faster-whisper)
    Status: STRUCTURAL VERIFIED
    What was confirmed:
      - faster-whisper installed (find_spec passes)
      - WhisperModel lazy-loaded (not at module level) — confirmed by test
      - VoiceCommandHandler.set_command_result_callback() exists
      - Transcription fires callback → iris_gateway._on_voice_result
      - _on_voice_result dispatches to main event loop (run_coroutine_threadsafe)
      - process_text_message called with from_voice=True
    Remaining gap: manual end-to-end (speak, verify transcript in chat)
    Test: speak a sentence, verify transcript appears in ChatView (manual)

  [2.3] Text-to-speech (F5-TTS or Piper)
    Status: STRUCTURAL VERIFIED
    What was confirmed:
      - piper-tts installed (find_spec passes)
      - f5_tts NOT installed (optional — Piper fallback active automatically)
      - _select_engine() falls back to Piper without raising when F5-TTS absent
      - synthesize() returns None when tts_enabled=False (no audio produced)
      - synthesize_stream() yields nothing when disabled
      - f5_tts NOT imported at module level in tts.py
      - Gateway broadcasts "speaking" state during TTS playback
    Remaining gap: manual end-to-end (agent responds, audio plays through speakers)
    To enable Cloned Voice (F5-TTS): pip install f5-tts + place TOMV2.wav at data/TOMV2.wav

  [2.4] Voice-first DER loop mode
    Status: DONE — already fully implemented
    What was found:
      - DER_TOKEN_BUDGETS["voice_first"] = 15000 (< 20k — tight budget enforced)
      - process_text_message(from_voice=True) → _mode_name = "voice_first" (bypasses mode detector)
      - task_class == "voice_first" → single queue item limit (single-step response)
      - All 6 DER mode tests pass
    Landmark: voice_first_der_mode (via test_domain2_voice.py)

  Linux compatibility (verified via TestLinuxCompatibility, 11/11 pass):
    - sounddevice lazy-loaded (not at module level in pipeline.py) ✓
    - wake_word_discovery picks linux .ppn path on Linux ✓
    - Fallback to Windows .ppn warns but doesn't crash (returns bool) ✓
    - pvporcupine lazy-loaded (not at module level in porcupine_detector.py) ✓
    - requirements.txt has Linux system dep instructions (portaudio19-dev etc.) ✓
    Linux prerequisites: sudo apt install portaudio19-dev libsndfile1 libasound2-dev
    Then: pip install -r requirements.txt

  Graduate condition: wake word → STT → agent response → TTS plays — full cycle
  without any manual keyboard input.
  Regression test: python -m pytest backend/tests/test_domain2_voice.py -v (38 tests)

---

DOMAIN 3 — VISION SYSTEM (desktop perception)
IRIS needs to see the screen to act as a desktop automation agent.

  [3.1] Verify LFM2.5-VL MCP server is operational
    Status: DEVELOPING — 1/3 passes for vision_layer landmark (needs 2 more)
    Files: backend/tools/vision_mcp_server.py, backend/tools/lfm_vl_provider.py
    Test: python -m pytest backend/tests/test_vision_mcp.py -v
    Fix: Get the test passing 2 more times to crystallize vision_layer as permanent.
    Landmark: vision_layer (needs 2 more passes to crystallize)

  [3.2] UniversalGUIOperator — perception-action-verify loop
    Status: DEVELOPING — 1/3 passes for paint_iris_demo (needs 2 more)
    Files: backend/agent/universal_gui_operator.py, scripts/paint_iris_demo.py
    Test: python scripts/paint_iris_demo.py
    Gap: High-signal failures (score 0.68-0.72). Run the demo, read the failure output.
    Landmark: paint_iris_demo (needs 2 more passes to crystallize)

  [3.3] Wire vision into agent tool dispatch
    Status: DONE — VisionMCPServer registered; all 5 vision.* tools dispatched.
            16/16 test_vision_mcp.py pass.
    Landmark: vision_wired_to_der

  Graduate condition: Agent can describe what is on screen when asked, and can
  click a UI element identified by vision — verified with paint_iris_demo passing.

---

DOMAIN 4 — SKILLS SYSTEM (self-extension)
The skill creator works end-to-end. The skill library is minimal.

  [4.1] Credential request skill
    Status: DONE — backend/agent/skills/credential-request/SKILL.md exists
    Landmark: credential_request_skill

  [4.2] File read / write skills
    Status: DONE — file_manager MCP server registered; read/write/list/create/delete all routed.

  [4.3] Web search skill
    Status: DONE — browser MCP server; search + open_url registered in tool_bridge.py.

  [4.4] GitHub MCP skill
    Status: NOT DONE
    Fix: Wire GitHub MCP for reading specs, creating PRs, reading issues.
         Requires bot token from Telegram credential request protocol.

  [4.5] Self-improvement skill
    Status: PARTIAL — skill creator works but agent does not use it proactively
    Gap: Agent does not create new skills when it identifies a repeated pattern.
    Fix: After any task where the same tool sequence appears 3+ times, trigger
         skill creator to codify that pattern into a SKILL.md.

  Graduate condition: Agent creates a new skill mid-task without being asked,
  the skill appears in the registry and is callable in a subsequent session.

---

DOMAIN 5 — MYCELIUM MEMORY MATURATION ✓ COMPLETE
All stubs resolved. Do not re-open unless a regression test fails.

  [5.1] CoordinateInterpreter — resolve coordinate conflicts
    Status: DONE — 3-rule arbitration permanent. Landmark: resolution_encoder

  [5.2] BehavioralPredictor — predict likely next agent actions
    Status: DONE — top-3 pheromone edge predictions. Landmark: resolution_encoder

  [5.3] Memory transfer — bootstrap DB to runtime DB
    Status: DONE — 28 landmarks seeded on startup. Landmark: memory_transfer_complete

  [5.4] Mycelium maintenance schedule
    Status: DONE — wired in backend/memory/interface.py; fires on MAINTENANCE_INTERVAL.
    Five steps: edge decay → condense → expand → landmark decay → render dirty.

  Regression test:
    python bootstrap/query_graph.py --summary
    (should show BehavioralPredictor returning non-empty tier2_predictions)

---

DOMAIN 6 — FRONTEND PRODUCTION QUALITY ✓ COMPLETE
All items verified. Do not re-open unless a regression is observed.

  [6.1] InferenceConsolePanel — DONE (inference_event + model_load_event wired)
  [6.2] ModelsScreen GGUF management — DONE (all WS message types forwarded)
  [6.3] Orb animation ↔ voice pipeline sync — DONE (audio level → orb pulse wired)
  [6.4] Chat history persistence — DONE. Landmark: chat_history_persistence
  [6.5] Settings panel field save/load — DONE (session_iris persists all fields)
  [6.6] Tab bar state persistence — DONE. Landmark: tab_state_persistence

  Graduate condition met: app opens, loads previous conversation, settings restored.

---

DOMAIN 7 — BACKEND PRODUCTION QUALITY
Core backend correctness issues that affect reliability under real use.

  [7.1] AgentKernel der_kernel_full_integration
    Status: DONE. Landmark: der_kernel_full_integration

  [7.2] WebSocket disconnect during DER loop
    Status: DONE — _session_has_client() checks at each DER cycle; logs + breaks cleanly.

  [7.3] Session management — multiple simultaneous users
    Status: DONE — _agent_kernel_instances keyed by session_id; no shared mutable state.

  [7.4] Backend startup sequence — /ready endpoint
    Status: DONE — 503 while starting, 200 when ready. /health always 200.

  [7.5] Logging — structured, queryable
    Status: PARTIAL — print() and logger.info() mixed throughout
    Fix: Standardise on Python logging. Add session_id to all log records.
         Route agent execution logs to a file tailable in InferenceConsolePanel.

  Graduate condition: 100 sequential requests processed without error or memory leak.

---

DOMAIN 8 — DISTRIBUTION & INSTALLATION

  [8.1] MSI installer — verify on clean machine
    Status: MSI built (cargo tauri build succeeded); not tested on clean machine.
    Fix: Install from MSI on a machine without the dev environment.
         Verify app launches and connects to bundled backend.

  [8.2] Backend bundling in Tauri
    Status: DONE — binary bundled, auto-start wired.
    Note: Binary is from 2026-03-15 build. Rebuild after source changes:
          python scripts/build_backend.py

  [8.3] First-run setup
    Status: DONE. Landmark: first_run_wizard

  Graduate condition: Person who has never used IRIS installs from MSI, runs the
  app, and sends their first message — no terminal required.

---

DOMAIN 9 — ADVANCED FEATURES (do not start until Domains 2–8 complete)

  [9.1] Torus network preparation
    Build and make dormant: ZeroMQ messaging, Dilithium3 identity, Kyber session keys.

  [9.2] Two-brain DER — second instance with different context
    Two AgentKernel instances on same task. Instance B sees what Instance A vetoed.

  [9.3] Trailing crystallizer — full crystallization cycle
    TrailingDirector (D1.1 done) + landmark crystallization verify gap-fill fires correctly.

---

DOMAIN 10 — PERFORMANCE & MEMORY RELIABILITY ✓ COMPLETE
All 10 items verified. Three lines of defense: psutil RAM guard, VRAM threshold,
lazy imports. Do not re-open unless a regression is observed.

  Summary of what was fixed (session 28-29 audit):
    1. Porcupine init failure now warns instead of crashing entire backend
    2. pvporcupine DLL: lazy import inside _initialize_porcupine
    3. sounddevice (PortAudio): lazy import via _sd() in pipeline.py
    4. TTS prewarm: psutil 4 GB guard added before CosyVoice load
    5. Session cleanup: no longer deletes session/*.py source files

  [10.1] Startup footprint — DONE (26.8 MB RSS delta verified)
  [10.2] VRAM guard audio model — DONE
  [10.3] RAM guard voice transcription — DONE
  [10.4] Session cleanup UUID dirs — DONE. Landmark: session_cleanup_on_startup
  [10.5] Pre-load VRAM/RAM preflight — DONE
  [10.6] Concurrent load guard (asyncio.Lock) — DONE
  [10.7] Clean model unload (kernel de-wire + watchdog) — DONE
  [10.8] Clean model switch (no gap state) — DONE
  [10.9] Inference settings hot-apply — DONE
  [10.10] TPS monitoring with gradient warning — DONE

  Regression test:
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

---

DOMAIN 11 — PiN + CROSS-PROJECT LANDMARK BRIDGE VERIFICATION
PiNs and landmark bridges are built. They need end-to-end testing before
they can be trusted as production memory infrastructure.

PiN = Primordial Information Node. Any knowledge artifact anchored to the
coordinate graph — files, folders, images, URLs, decisions, fragments.
Named after mycological primordia (first growth points of a fungal network).

  [11.1] PiN round-trip — bootstrap layer
    Status: NOT STARTED
    What to test:
      a) Add a PiN via pin.py --add and confirm it appears in --list
      b) Add a PiN via record_event.py --type pin and confirm it appears
      c) Mark a PiN --permanent, verify it survives a decay pass
      d) Add a non-permanent PiN, simulate decay, confirm it fades
      e) Search: pin.py --search "keyword" returns matches on file_refs + content
    Test command:
      python -c "
        from bootstrap.coordinates import CoordinateStore
        s = CoordinateStore()
        pid = s.add_pin('Test PiN', pin_type='decision', content='test', is_permanent=True)
        pins = s.get_pins()
        assert any(p['pin_id'] == pid for p in pins), 'PiN not found'
        results = s.search_pins('Test')
        assert any(p['pin_id'] == pid for p in results), 'search failed'
        print('[PASS] PiN round-trip OK')
      "
    Landmark: pin_bootstrap_verified

  [11.2] PiN link traversal
    Status: NOT STARTED
    What to test:
      a) Create a PiN and a landmark, add a pin_link between them
      b) Verify the link appears in the graph edge table
      c) Verify link weight compounds on repeated reference
    Test command:
      python -c "
        from bootstrap.coordinates import CoordinateStore
        s = CoordinateStore()
        pid = s.add_pin('Link test', pin_type='doc')
        landmarks = s.get_landmarks()
        if not landmarks:
            print('[SKIP] no landmarks to link to')
        else:
            link_id = s.add_pin_link('pin', pid, 'landmark',
                                     landmarks[0]['landmark_id'], 'documents')
            assert link_id > 0, 'link not created'
            print('[PASS] PiN link OK')
      "
    Landmark: pin_links_verified

  [11.3] Landmark bridge — same-instance round-trip
    Status: NOT STARTED
    What to test:
      a) Register a bridge between two local landmarks
      b) find_bridge() returns it by remote_landmark_name
      c) Bridge survives restart (persisted to DB)
    Test command:
      python -c "
        from bootstrap.coordinates import CoordinateStore
        s = CoordinateStore()
        landmarks = s.get_landmarks()
        if len(landmarks) < 2:
            print('[SKIP] need >= 2 landmarks')
        else:
            bid = s.add_landmark_bridge(
                local_landmark_id=landmarks[0]['landmark_id'],
                remote_landmark_name='test_remote_landmark',
                confidence=0.90, bridge_type='equivalent',
                notes='test bridge'
            )
            result = s.find_bridge('test_remote_landmark')
            assert result is not None, 'bridge not found'
            assert result['confidence'] == 0.90, 'confidence mismatch'
            print(f'[PASS] bridge round-trip OK: {bid}')
      "
    Landmark: landmark_bridge_verified

  [11.4] Landmark bridge — cross-project pattern recognition simulation
    Status: NOT STARTED
    What to test:
      Simulate entering a new project: create a fresh CoordinateStore at a temp path,
      add a landmark with the same name as the remote bridge, call find_bridge() and
      verify it returns a match with >= 0.80 confidence. This simulates what happens
      when IRIS enters a project that has a landmark matching a known bridge — the
      pattern should activate without re-crystallising from scratch.
    Test command:
      python -c "
        from bootstrap.coordinates import CoordinateStore
        s = CoordinateStore()
        landmarks = s.get_landmarks()
        if not landmarks:
            print('[SKIP] no landmarks')
        else:
            lm = landmarks[0]
            bid = s.add_landmark_bridge(
                local_landmark_id=lm['landmark_id'],
                remote_landmark_name='g1_api_healthy',
                confidence=0.95
            )
            bridge = s.find_bridge('g1_api_healthy')
            assert bridge['confidence'] >= 0.80, 'activation threshold not met'
            print(f'[PASS] bridge activation sim OK: conf={bridge[\"confidence\"]}')
      "
    Landmark: bridge_activation_simulated

  [11.5] IRIS app-layer PiN + bridge schema presence
    Status: NOT STARTED
    What to test:
      After calling initialise_mycelium_schema(), verify that mycelium_pins,
      mycelium_pin_links, and mycelium_landmark_bridges tables all exist in the
      runtime DB (data/memory.db dev mode).
    Test command:
      python -m pytest backend/tests/test_mycelium_store.py -k "pin or bridge" -v
      (add test cases for the three tables if they do not exist yet)
    Landmark: mycelium_pin_schema_verified

  Graduate condition: All 5 tests pass. PiN write → persist → read → decay →
  bridge register → bridge lookup all verified. Foundation is solid.

---

DOMAIN 12 — PiN + MCP STORAGE INTEGRATIONS
PiNs become the bridge between IRIS memory and external storage systems.
Every external artifact IRIS reads or writes becomes a PiN — a named,
typed, traversable node in the memory graph.

Architecture principle:
  External artifact → read via MCP → anchor as PiN → link to relevant landmark
  The PiN carries: url_refs (the external link), file_refs (any local copy),
  tags (for search), content (markdown snapshot), pin_type (the artifact kind).
  Permanent PiNs survive across sessions and federation merges.

Prerequisite: Domain 11 must be fully verified before starting Domain 12.

  [12.1] Google Drive PiN integration
    Status: NOT STARTED
    What: When IRIS reads or references a Google Drive file, anchor a PiN:
          pin_type='doc', url_refs=[drive_url], content=first_500_chars
          Link to the landmark active during the task.
    MCP: Google OAuth2 — already modeled in backend/integrations/models.py
         OAuthConfig provider="google". Wire via integrations/mcp_bridge.py.
    Implementation:
      a) MCP tool: gdrive_read_file(file_id) → text content + metadata
      b) After read: auto-anchor PiN if content is relevant (>100 chars)
      c) PiN title = Drive file name, url_refs = share link
      d) Set is_permanent=True for files explicitly saved to graph by user
    Test: Read a Drive file through IRIS, verify PiN appears in pin.py --list
    Landmark: gdrive_pin_wired

  [12.2] Discord channel PiN integration
    Status: NOT STARTED
    What: When IRIS reads a Discord thread or message, anchor a PiN:
          pin_type='note', url_refs=[message_url], content=message_body,
          tags=['discord', channel_name]
    MCP: Discord OAuth2 or bot token — OAuthConfig provider="discord" exists.
         Wire via integrations/mcp_bridge.py.
    Implementation:
      a) MCP tool: discord_read_channel(channel_id, limit=20) → messages
      b) Anchor PiN per thread (not per message) — group by conversation
      c) If thread references a file or issue, auto-link PiN to that file node
    Test: Read a Discord thread through IRIS, verify PiN appears in --search
    Landmark: discord_pin_wired

  [12.3] Notion page PiN integration
    Status: NOT STARTED
    What: When IRIS reads a Notion page, anchor a PiN:
          pin_type='doc', url_refs=[notion_url], content=markdown_export,
          tags=['notion']
    MCP: Notion API token (credentials type). Wire via integrations/.
    Implementation:
      a) MCP tool: notion_read_page(page_id) → markdown content
      b) Anchor PiN with full markdown snapshot (first 2000 chars)
      c) If the Notion page has subpages, create child PiNs linked via 'contains'
    Test: Read a Notion page through IRIS, verify PiN + content saved
    Landmark: notion_pin_wired

  [12.4] GitHub issue/PR PiN integration
    Status: NOT STARTED (Domain 4.4 partially addressed the skill level)
    What: When IRIS reads a GitHub issue or PR, anchor a PiN:
          pin_type='fragment', url_refs=[github_url],
          file_refs=[affected_files], tags=['github', repo_name]
    Link: PiN → relevant file_nodes for files mentioned in the PR diff
    Implementation:
      a) MCP tool: github_read_issue(owner, repo, number) → body + comments
      b) Parse diff to extract file_refs automatically
      c) Auto-link PiN → file_node for each affected file (relationship='references')
    Test: Fetch a GitHub issue through IRIS, verify PiN anchored with file_refs
    Landmark: github_pin_wired

  [12.5] PiN auto-anchor policy
    Status: NOT STARTED
    What: Define when IRIS should anchor a PiN automatically vs. requiring
          explicit user instruction. Prevents PiN graph from becoming noise.
    Policy:
      AUTO-ANCHOR (always):
        - Files edited during a DER task (file_refs, pin_type='file')
        - External URLs fetched during RESEARCH mode (url_refs, pin_type='url')
        - Design decisions made in a SPEC task (pin_type='decision', permanent=True)
      ASK-FIRST:
        - Large documents (>5000 chars) — ask before snapshotting
        - External files the user hasn't explicitly referenced
      NEVER:
        - Authentication tokens or credentials
        - Ephemeral session data
    Implementation: Policy checked in tool_bridge.py after each tool execution.
    Test: Run a DER task that edits a file, verify auto-PiN anchored.
          Run a task that fetches a URL, verify URL PiN anchored.
    Landmark: pin_auto_anchor_policy

  Graduate condition: IRIS reads a Google Drive doc, a Discord thread,
  and fetches a GitHub issue in a single session. All three appear as PiNs
  in pin.py --list with correct types, refs, and links to active landmarks.
  The Reviewer sees them in subsequent tasks involving the same landmark cluster.

---

SESSION START CHECKLIST
At the start of every session (Claude Code: fully automated via hooks):

  1. session_start.py runs automatically on every prompt (UserPromptSubmit hook)
     — loads coordinate state, auto-syncs any unrecorded git commits
  2. python bootstrap/agent_context.py          (check available work)
  3. Read the "WHAT NEEDS WORK RIGHT NOW" section at the top of this file
  4. Read the spec for the highest-priority incomplete item
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
  Then condense. After condensing: session_start.py runs automatically on next prompt.

---

AGENT RULES (weight = minimum confidence before acting)

  [1.00] Never mark a landmark without a passing test.
  [1.00] Run the quality check before running any test. A passing test on
         unoptimized code is a time bomb, not a landmark.
  [0.95] Navigate the graph (query_graph.py --file) before touching any file.
  [0.90] Session state loads automatically on every prompt — do not skip it.
  [0.85] Send Telegram before stopping on auth blockers.
  [0.80] Classification before context assembly (Step 2 before Step 3).
  [0.75] Read the spec for an area before touching its files.
  [0.70] Run the spec's requirements test — never write tests to pass your code.

---

IRIS Production Roadmap — bootstrap/GOALS.md
Twelve domains. One objective. Ship a working autonomous assistant.
