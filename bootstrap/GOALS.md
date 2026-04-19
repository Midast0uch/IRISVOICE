IRIS Bootstrap Agent — Production Roadmap
This file defines what needs to be built, fixed, or completed to ship IRIS as a production-quality autonomous assistant.
File: IRISVOICE/bootstrap/GOALS.md
Read this at the start of every session.

OBJECTIVE ANCHOR (never changes)
Build IRIS until it can run fully autonomously: receive tasks through its own interface, execute them using its own backend, and improve itself over time without external scaffolding.

---

WHAT NEEDS WORK RIGHT NOW (quick read for session start)

  GATE STATUS: Gate 1 substantially done; Gate 2 (Launcher + Developer Mode) is next.
    G1.1–G1.5 verified. G1.6/G1.7/G1.8 need hands-on e2e confirmation.
    TOP PRIORITY THIS SPRINT: Domain 15 (Linux Build + Launcher) + Domain 13 (Gate 2).

  DOMAINS WITH OPEN ITEMS:
    Domain 2  — Voice pipeline  (PARTIAL — [2.1][2.2][2.3] manual e2e not confirmed)
    Domain 3  — Vision          (DEVELOPING — [3.1][3.2] need 2 more passing runs each)
    Domain 4  — Skills          (PARTIAL — [4.4][4.5] not done)
    Domain 7  — Backend quality (PARTIAL — [7.5] logging not standardised)
    Domain 8  — Distribution    (PARTIAL — [8.1] MSI untested on clean machine)
    Domain 11 — PiN verification (ALL 5 items not started — run these next)
    Domain 12 — MCP storage      (ALL 5 items not started — after D11 passes)
    Domain 13 — Launcher: Personal/Developer Mode (PARTIAL — [13.1-13.5] not done) ← GATE 2
    Domain 14 — CLI Toolkit + Web Crawler (PARTIAL — Phases A/B/C done; [14.2][14.16][14.19][14.21] remain)
    Domain 15 — Linux Build + Cross-Platform Launcher (ALL items not started — new)

  DOMAINS COMPLETE (do not revisit unless regression):
    Domain 1  — DER loop gaps       ✓ all 8 items verified
    Domain 5  — Mycelium stubs      ✓ all 4 items verified
    Domain 6  — Frontend quality    ✓ all 6 items verified
    Domain 10 — Performance/memory  ✓ all 10 items verified

  PRIORITY ORDER FOR NEW SESSIONS:
    1. Domain 15 — Linux Build + Cross-Platform Launcher ← TOP PRIORITY
         Start with [15.3] mode-switch flow (no Linux hardware needed, works on Windows too)
         Then [15.5] packaging decision, then [15.1] Linux Tauri build, then [15.2][15.4]
    2. Domain 13 — Launcher + Developer Mode = GATE 2 (13.1→13.2→13.3→13.4→13.5)
         D15 [15.3] and D13 [13.3] overlap heavily — do them together
    3. Domain 14 — CLI Toolkit + Web Crawler remaining items ([14.2][14.16][14.19][14.21])
    4. Domain 11 — PiN + landmark bridge verification (foundation, run tests)
    5. Domain 3  — Vision (paint_iris_demo, vision_layer — 2 more passes each)
    6. Domain 2  — Voice pipeline (primary input modality)
    7. Domain 12 — PiN + MCP storage integrations (after D11 verified)
    8. Domain 4  — Skills library (self-extension)
    9. Domain 7  — Backend reliability (logging standardisation)
    9. Domain 8  — Distribution (MSI clean install)
    10. Domain 9  — Advanced features (after everything else)

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
            Status: IMPLEMENTED — awaits e2e verification. Local inference now
            runs in-process (see Domain 2 note below); subprocess port-8082
            path retained behind IRIS_INPROCESS_LLAMA=0 as rollback lever.
            Manual test: load Qwen3.5-9B-Q3_K_S, type a chat message, confirm
            the reply streams back at ≥40 tok/s with no orphaned processes
            in Task Manager.
    [G1.7] No memory spike on startup — backend starts clean, CUDA only inits
            when user explicitly loads a model (not at startup)
            Status: startup RSS delta < 200 MB verified (Domain 10 audit), but
            end-to-end with frontend not confirmed
    [G1.8] Tool calling works with iris_local model — skills can be created and
            recalled within the same session (DER loop + episodic memory active)
            Status: IMPLEMENTED — awaits e2e verification. The in-process
            OpenAI adapter (InProcessOpenAIAdapter) preserves tools /
            tool_choice kwargs and streams tool_calls in the same shape
            openai-python emits; DER loop + episodic layer untouched. Manual
            test: in developer mode, ask the agent to "create a skill that
            lists files" — verify the tool call executes and the skill is
            recalled on a follow-up.

  Verify by: Start both servers, open the app, load a model via ModelsScreen,
  type a message in chat, confirm reply comes from the local GGUF with GPU active.
  Do NOT verify Gate 1 on CPU-only. CPU+GPU together is the requirement.

  GATE 2 — LAUNCHER + DEVELOPER MODE (activate after Gate 1 verified)
  Goal: IRIS launches in one of two modes selected at startup.
        Personal mode: voice assistant, no terminal, no source access.
        Developer mode: agent workspace — terminal observation window, direct shell access,
                        file activity monitoring, git operations. Agent kernel is the single
                        routing brain. MCP server interfaces (Figma, Blender, etc.) for
                        external tool integration — not CLI drivers.
        The launcher must work before the terminal is built — it is the prerequisite.

  Gate 2 checklist (in order — do not skip ahead):
    [G2.1] DONE — Launcher UI exists at C:\Users\midas\Desktop\dev\iris-launcher\
           ModeSelectPage, AppContext, use-iris-mode, GitPage, DiffReviewPage all built.
           /api/mode and /api/projects already in IRISVOICE backend.
    [G2.2] Backend git + diff endpoints (Domain 13.1) — NOT DONE ← start here
    [G2.3] Git worktree isolation — agent writes to isolated branch (Domain 13.2)
    [G2.4] Developer mode capabilities gated in IRISVOICE (Domain 13.3)
    [G2.5] Terminal tab visible in developer mode only (Domain 13.4)
    [G2.6] Session-end diff review in Launcher DiffReviewPage (Domain 13.5)

  Terminal architecture (developer mode only — TUI is dumb, IRIS is smart):
    User input → xterm.js → WebSocket → security_filter → iris_gateway
                                                         → agent_kernel
                                                         → tool_bridge
                                                         → output parser
    Streaming output → WebSocket → xterm.js (renders as-is)

  What the terminal does (only):
    - Accepts raw user keystrokes and sends them via WebSocket
    - Renders streaming text/ANSI output from the agent
    - Displays tool call activity, DER loop steps, memory signals as they arrive
    - No config, no setup, no state — stateless display driver
    - Only visible and active when iris_mode == "developer"

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

  Verify Gate 2 by:
    1. App launches → launcher screen appears
    2. Select Personal Mode → no terminal tab, no source access, voice works
    3. Select Developer Mode → DEV badge visible, terminal tab appears
    4. In terminal: run a git command → output streams, worktree stays isolated
    5. End session → merge/discard modal appears with diff summary

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

  [2.3] Text-to-speech (F5-TTS primary, Piper fallback)
    Status: STRUCTURAL VERIFIED + ENGINE PRIORITY UPDATED (2026-04-05)
    Engine priority (hardcoded — not user-selectable):
      1. F5-TTS (F5TTS_v1_Base) — PRIMARY — always tried first when installed
         Zero-shot voice cloning from data/TOMV2.wav. CPU, RTF ~0.15, ~800 MB.
      2. Piper (en_US-ryan-high) — FALLBACK — used when F5-TTS absent or fails
         Fast CPU, RTF ~0.04x, ~65 MB. Auto-downloads on first Piper use.
      3. pyttsx3 (SAPI5) — LAST RESORT — zero download, Windows-only.
    Voice setting "Built-in" skips F5-TTS and goes straight to Piper.
    All other settings (including default "Cloned Voice") try F5-TTS first.
    What was confirmed:
      - piper-tts installed (find_spec passes)
      - f5_tts NOT yet installed — Piper fallback active (install to activate primary)
      - _select_engine() logs correct engine priority chain — does not raise
      - synthesize() returns None when tts_enabled=False
      - synthesize_stream() yields nothing when disabled
      - f5_tts NOT imported at module level in tts.py (lazy load)
      - Gateway broadcasts "speaking" state during TTS playback
    Remaining gap: manual end-to-end (agent responds, audio plays through speakers)
    To activate F5-TTS primary: pip install f5-tts + place TOMV2.wav at data/TOMV2.wav

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

  Inference backend note (2026-04-16):
    LocalModelManager now loads GGUF weights in-process via
    `from llama_cpp import Llama` — no more `python -m llama_cpp.server`
    subprocess on port 8082. The old HTTP path hung reliably on Windows
    with n_gpu_layers=-1 on Q3_K_S. InProcessOpenAIAdapter
    (backend/agent/local_model_manager.py) duck-types the openai Python
    client's chat.completions.create surface so the agent kernel calls the
    same API it did against the subprocess. Set IRIS_INPROCESS_LLAMA=0 to
    temporarily restore the subprocess path (scheduled for deletion after
    V1–V3 verification passes). The research_rotorquant profile unlocks
    128k ctx via the llama-cpp-turboquant fork (see docs/ROTORQUANT_BUILD.md)
    — falls back to `performance` with a warning when the fork is absent.

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

DOMAIN 13 — LAUNCHER: PERSONAL MODE / DEVELOPER MODE  [GATE 2]
This domain IS Gate 2. Complete all open items to verify Gate 2.
Launcher must work before the terminal — do [13.2]→[13.3]→[13.4]→[13.5] in order.

LAUNCHER EXISTS — at C:\Users\midas\Desktop\dev\iris-launcher\
  Separate Vite + React app (NOT inside IRISVOICE). Run with: cd iris-launcher && npm run dev
  Already substantially built. Do NOT rewrite — extend what is there.

WHAT IS ALREADY BUILT (do not re-do these):
  ✅ ModeSelectPage.tsx     — Personal/Developer mode selection UI (full UI, animations)
  ✅ AppContext.tsx          — mode persisted to localStorage as "iris-mode"
  ✅ use-iris-mode.ts       — setMode() updates AppContext AND POSTs to /api/mode
  ✅ App.tsx routing        — if no mode in localStorage → redirect to /mode-select
  ✅ FirstRunPage.tsx       — Dilithium3 identity + seed phrase (UI built, flow works)
  ✅ GitPage.tsx            — git status, commit all, rollback UI (wired to backend hooks)
  ✅ DiffReviewPage.tsx     — approve/reject pending agent writes before commit
  ✅ OverviewPage.tsx       — agent status dashboard
  ✅ ProjectsPage.tsx       — project list (personal/developer per project)
  ✅ use-iris-backend.ts    — React Query hooks for all backend API calls
  ✅ iris-api.ts            — API client (commitAll, rollback, getPendingWrites,
                               approveWrite, rejectWrite, getProjects, getMode, setMode)
  ✅ /api/mode GET+POST     — already in IRISVOICE backend/main.py (lines 538, 573)
  ✅ /api/projects GET+POST — already in IRISVOICE backend/main.py (lines 615, 644)

WHAT IS MISSING (build these):

  [13.1] Backend git + diff API endpoints  ← START HERE
    Status: NOT STARTED
    The launcher GitPage and DiffReviewPage call these backend routes — none exist yet:
      GET  /api/git/status   → branch, clean, lastCommit, uncommittedFiles
      GET  /api/git/log      → commits list (hash, message, time)
      POST /api/git/commit   → body: {message} → git add -A && git commit
      POST /api/git/rollback → body: {target} → git reset --hard {target}
      GET  /api/diff/pending → list of pending agent writes awaiting approval
      POST /api/diff/approve → body: {id} → write approved file to disk
      POST /api/diff/reject  → body: {id} → discard pending write
    All operate on the ACTIVE project path (from /api/mode or /api/projects context).
    Use subprocess to call git. Store pending writes in a dict (in-memory is fine for now).
    File: IRISVOICE/backend/main.py (add routes) + IRISVOICE/backend/git_ops.py (logic)
    Test: Start backend, open launcher GitPage — git status must load without error.
    Landmark: launcher_git_api_wired

  [13.2] Developer mode — git worktree isolation
    Status: NOT STARTED
    What to build:
      a) IRISVOICE/backend/dev_worktree.py — manages the isolated worktree:
           setup(project_path)   → git worktree add {project_path}/dev_worktree iris-agent-YYYYMMDD
           teardown(merge=True|False) → merge branch or git worktree remove --force
           status()  → {branch, uncommitted_files, diff_summary}
      b) When /api/mode sets mode=developer: call setup() for active project
      c) Inject IRIS_SOURCE_DIR = worktree path into agent context:
           "You are working in an isolated copy of the IRIS source at {path}.
            Changes here do NOT affect the live codebase until approved.
            Commit your changes; they will be reviewed in the Launcher diff view."
      d) Pending writes → /api/diff/pending feed (wires [13.1] to [13.2])
    Test:
      POST /api/mode body={mode: "developer"}
      GET  /api/git/status → should show worktree branch (iris-agent-YYYYMMDD)
    Landmark: dev_worktree_isolation

  [13.3] Developer mode capabilities in IRISVOICE
    Status: PARTIAL — /api/mode exists but capabilities not gated on mode
    What to build:
      a) iris_gateway.py: read current mode → set CapabilitySet
           personal  = {tts, voice, chat}
           developer = {tts, voice, chat, terminal, repo_access}
      b) Terminal tab in IRISVOICE tab-bar: visible only when mode=developer
      c) Agent context injection: mode=developer → prepend IRIS_SOURCE_DIR block
    Test: Set mode=personal → no terminal tab. Set mode=developer → terminal tab appears.
    Landmark: mode_capabilities_gated

  [13.4] Terminal tab — developer mode only
    Status: IMPLEMENTED — awaits e2e verification. Cannot be landmarked until
            local model loading is verified (see Gate 1.6/1.7/1.8 + Domain 2
            inference note) because agent-routed CLI tests depend on the
            model actually running.
    What was built:
      a) TerminalContext (contexts/TerminalContext.tsx) — widget state owner,
         auto-floats on iris:cli_started, tracks file activity ring-buffer.
      b) TerminalWidget (components/terminal/TerminalWidget.tsx) — xterm.js
         host using a portal pattern so the xterm instance survives
         dock↔float transitions.
      c) FloatingTerminalPanel — framer-motion drag + resize, z-index 40,
         pointer-events passthrough so dashboard stays interactive.
      d) TerminalHeaderBar, FileActivityPanel — header controls + file
         activity sidebar (create/edit/delete color coded).
      e) ChatView prefix routing (>, /run) — direct shell bypass in
         developer mode only; routes through terminal_input message type.
      f) Backend: iris_gateway._handle_terminal_input gated on developer
         mode, dispatches to terminal_handler.py (allowlist/blocklist).
      g) file_activity WebSocket message type added to useIRISWebSocket.ts
         → fires iris:file_activity custom event.
    Manual verification checklist (run these to crystallise the landmark):
      1. Developer mode → Terminal tab → `git status` → output appears.
      2. Click float button → terminal becomes draggable floating panel;
         dashboard underneath stays clickable.
      3. Float → Dock → xterm history preserved (portal pattern).
      4. Chat `> npm -v` → terminal auto-floats, npm version appears.
      5. Chat "list files in this directory" (no prefix) → agent kernel
         invokes an appropriate tool; terminal auto-floats and output streams.
      6. Agent edits a file → FileActivityPanel row appears in <1s.
      7. Terminal: `rm -rf /` → rejected by terminal_handler security.
      8. Personal mode → terminal tab hidden; sending terminal_input from
         devtools is rejected by backend.
    Landmark (DO NOT ADD until 1–8 all pass manually): developer_terminal_wired
    Note: Terminal is the last piece of Gate 2. Do [13.1]→[13.2]→[13.3] first.

  [13.5] Session end — merge or discard in Launcher
    Status: PARTIAL — DiffReviewPage exists, approve/reject hooks built
    The Launcher DiffReviewPage already has the UI for approve/reject.
    What still needs wiring:
      a) Backend Stop hook (developer mode): push pending diff summary to /api/diff/pending
      b) Launcher auto-opens DiffReviewPage on backend "session_end" WebSocket event
      c) "Approve all" → commit, "Discard all" → git worktree remove --force
    Test: Make a file edit in developer mode, end session, verify DiffReviewPage
          shows the diff. Approve → verify commit appears in GitPage log.
    Landmark: session_end_diff_review

  [13.6] MCP-first external tool integration
    Status: PLANNED
    Note: CLI driver approach deprioritized. External tools (Figma, Blender, etc.)
          will integrate via MCP server interfaces, not terminal/CLI drivers.
          Agent kernel routes to MCP tools through tool_bridge.

  Graduate condition:
    Personal mode: Launcher opens, user selects Personal, IRISVOICE loads, no terminal tab.
    Developer mode: Launcher opens, user selects Developer, IRISVOICE loads with DEV
    context, terminal tab visible, agent works in isolated worktree, session end
    routes to DiffReviewPage for approve/discard. Main repo clean throughout.

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

---

DOMAIN 14 — CLI TOOLKIT + WEB CRAWLER
Spec: IRISVOICE/CLI-crawler-Spec.md (v3.1)
Gives IRIS the ability to invoke any registered CLI on the user's behalf (developer mode),
show real-time file activity in the wing, and crawl the web headlessly in both modes using
Crawl4AI. Crawler results surface as a structured dashboard tab — never as raw HTML.

Architecture decisions (locked):
  - CLI routing handled by DER Director inside iris_gateway.py — no separate orchestrator module
  - Crawler results labeled "external" zone in Pacman context window (not user/tool zone)
  - SuggestionPills appear in both personal and developer mode (different visual style)
  - Crawler activates in both modes when brain model detects web-search intent
  - Wing: extend existing browser tab in dashboard-wing.tsx — no new WingComponent
  - CLI tools pre-configured: kilo code CLI, claude CLI, opencode CLI
  - DEV_ALLOWED_ROOTS left blank in .env — user fills in before use

Phase A — Frontend Foundations (no backend required, can mock):
  [14.1] types/iris.ts — shared TypeScript interfaces
    Status: DONE — IRISVOICE/types/iris.ts created; tsc --noEmit passes. Landmark: iris_types_defined
    What to build:
      Tab { id, type: 'code'|'web'|'html'|'dashboard', title, data?, url?, content? }
      DashboardData { title, query, timestamp, summary, sections: DashboardSection[] }
      DashboardSection = MetricsSection | TableSection | CardsSection | ChartSection
      MetricsSection { type:'metrics', items:[{label,value,delta?,trend?}] }
      TableSection   { type:'table',   title?, headers, rows }
      CardsSection   { type:'cards',   title?, items:[{title,subtitle?,body,url?,tag?}] }
      ChartSection   { type:'chart',   title?, chart_type:'bar'|'line'|'pie', labels, datasets }
      Suggestion { id, label, message }
      DevModeState { isDevMode, workDir, activeTool, model }
      CrawlerStatus { state:'idle'|'planning'|'crawling'|'extracting', urlCount, pagesDone }
    File: types/iris.ts (new file at IRISVOICE/types/iris.ts)
    Test: tsc --noEmit passes after creation
    Landmark: iris_types_defined

  [14.2] components/chat/SuggestionPills.tsx — context-aware action pills
    Status: NOT STARTED (Phase F dependency — backend suggestion injection needed first)
    What to build:
      Props: suggestions: Suggestion[], onSelect: (s: Suggestion) => void, onDismiss: () => void
             mode: 'personal' | 'developer'
      Personal mode: rounded pill buttons, glass style, Framer Motion layout animation
      Developer mode: monospace, "> " prefix on each pill, subtle terminal aesthetic
      Behaviours:
        - Maximum one pill row visible at a time (replaces previous on new response)
        - Selecting a pill calls onSelect(s) and removes the row permanently
        - Backdrop click (or Escape) calls onDismiss() — row never reappears on scroll
        - Pills morph/animate into user bubble on select (Framer Motion layoutId)
      Integration: mount inside chat-view.tsx below last assistant message
    File: components/chat/SuggestionPills.tsx (new)
    Test: renders with mock suggestions, click fires onSelect, backdrop fires onDismiss
    Landmark: suggestion_pills_component

  [14.3] Modify components/chat-view.tsx — dev mode CLI skin + mount SuggestionPills
    Status: PARTIAL — isCrawlerQuery heuristic added; crawler_query WS routing wired.
            ConversationChips fully built and mounted. Scroll fix (container ref) done.
            Orb→ChatView display fix (lastProcessedResponseRef + activeConversationIdRef) done.
            Remaining: dev mode CLI skin (monospace bubbles, top status bar, DEV badge) + SuggestionPills mount
    What to add (conditional on iris_mode === 'developer'):
      a) Top status bar: workDir (truncated), activeTool name, model name
         Uses DevModeState from useDevMode hook (or read from WS message)
      b) CLI skin: user messages → monospace text with "> " prefix, no rounded bubble
         Assistant messages → monospace block, no glass bubble styling
      c) Mount <SuggestionPills> below last assistant message block
         Pass currentSuggestions state (updated on each text_response WS message)
         onSelect → sendMessage(s.message), clear suggestions
         onDismiss → clear suggestions
      d) Dev mode badge in header (small "DEV" pill, brand color border)
      IMPORTANT: Normal mode layout must be completely unchanged. All changes
      are behind if (isDevMode) guards. No shared JSX restructuring.
    Files: components/chat-view.tsx, hooks/useDevMode.ts (read from it)
    Test: toggle dev mode, verify CLI skin appears; toggle back, verify normal skin
    Landmark: chatview_dev_skin

  [14.4] Extend components/dashboard-wing.tsx — tabbed content in browser tab
    Status: DONE — Tab state (tabs[], activeTabId), openTab/closeTab callbacks, CustomEvent
            listeners for iris:open_tab + iris:close_tab, tab bar with close buttons,
            TabContent switcher for code/web/html/dashboard types. Landmark: wing_tab_system
    What to build inside the existing browser tab section of dashboard-wing.tsx:
      a) TabBar sub-component (inline or extracted): tabs array state
         Each tab: { id, type, title, closeable }
         Tab types shown: code | web | html | dashboard
         Tab bar only visible when tabs.length > 0
         Close (×) on each tab → removes tab, switches to adjacent automatically
      b) TabContent renderer:
         'code'      → code block with syntax highlighting (highlight.js or Prism, lazy)
                        Shows "modified" indicator dot if written this session
         'web'       → <iframe src={url} sandbox="allow-scripts allow-same-origin" />
         'html'      → <iframe srcDoc={content} sandbox="allow-scripts" />
         'dashboard' → <DashboardRenderer data={data} />
      c) open_tab WS message handling: if tab.id already exists → update in place (no duplicate)
      d) close_tab WS message handling: remove tab by id
      e) File activity panel (developer mode only, collapsible):
         Lists files modified by CLI this session: filename, change type (edit/create/delete)
         Clicking a file → opens it as a 'code' tab
         Populated by file_activity WS messages
      IMPORTANT: Do NOT restructure existing notification system, nav, or sub-app routing.
      The tab system lives inside the browser/web sub-app panel only.
    Files: components/dashboard-wing.tsx, components/wing/DashboardRenderer.tsx (new)
    Test: send mock open_tab message via WS, verify tab appears and content renders
    Landmark: wing_tab_system

  [14.5] components/wing/DashboardRenderer.tsx — structured data renderer
    Status: DONE — MetricsSection KPI cards with trend arrows, sortable TableSection,
            CardsSection 2-col grid, ChartSection CSS bar chart, JSON/CSV export,
            Save button → POST /api/crawler/pin/save. Landmark: dashboard_renderer
    What to build:
      Props: data: DashboardData
      Renders in order:
        Header: title + query + timestamp (ISO → human readable)
        Summary: italic one-liner
        Sections (in array order):
          MetricsSection → row of KPI cards: value (xl, brand color), label (sm, muted),
                           delta (colored: green up / red down / gray flat), trend arrow
          TableSection   → table with sticky header, sortable columns (click header → sort),
                           alternating row shading, horizontal scroll on overflow
          CardsSection   → 2-column grid (1-col mobile), each card: title bold, subtitle
                           muted, body text, optional url (opens in browser tab), tag pill
          ChartSection   → Recharts BarChart | LineChart | PieChart
                           Lazy import Recharts (heavy dep, only load when chart present)
                           Axes, legend, tooltip with brand color theme
        Footer: "Crawled N pages · Xms · Export " [JSON] [CSV] buttons
          JSON: Blob download, filename = title.json
          CSV: flatten all TableSection rows → CSV string → download (no backend call)
    File: components/wing/DashboardRenderer.tsx (new)
    Test: render with mock DashboardData containing all 4 section types
    Landmark: dashboard_renderer

Phase B — Backend CLI Layer (developer mode, requires Gate 2):
  [14.6] backend/dev/cli_registry.py + cli_tools.yaml
    Status: DONE — CLITool frozen dataclass, CLIRegistry loads YAML, available_tools(),
            build_selection_context(), select_tool_for_query() via LLM. Landmark: cli_registry_loaded
    cli_tools.yaml schema per entry:
      name: string            — e.g. "kilo"
      display_name: string    — e.g. "Kilo Code"
      command: string         — e.g. "kilo"
      args_template: string   — e.g. "{task}"
      when_to_use: string     — natural language descriptor for brain model routing
      allowed_modes: list     — ["developer"] (CLI only in developer mode)
      timeout_seconds: int    — per-invocation timeout
      stream_stdout: bool     — stream output in real time vs wait for completion
    Pre-configured tools:
      kilo: Kilo Code CLI — when_to_use: "write or refactor code files using AI assistance"
      claude: Claude CLI  — when_to_use: "complex reasoning, planning, or multi-step tasks"
      opencode: OpenCode  — when_to_use: "code generation or editing with model selection"
    DEV_ALLOWED_ROOTS: left blank (read from .env — user fills before use)
    cli_registry.py:
      load_tools(yaml_path) → dict[name, ToolConfig]
      get_tool_for_task(task_description, available_tools) → ToolConfig | None
        Uses when_to_use descriptor + simple keyword scoring (no LLM call in registry itself)
      is_path_allowed(path, allowed_roots) → bool
        Checks path starts with one of allowed_roots (case-insensitive, normalised)
        Returns False (with log) if allowed_roots is empty
    Files: backend/dev/__init__.py, backend/dev/cli_registry.py, backend/dev/cli_tools.yaml
    Test: load yaml, get_tool_for_task("write code"), verify returns kilo config
    Landmark: cli_registry_loaded

  [14.7] backend/dev/subprocess_manager.py — subprocess lifecycle
    Status: DONE — ActiveProcess dataclass, bounded output queue (500), daemon reader thread,
            hard kill timer, DEV_ALLOWED_ROOTS validation, abort()/is_running()/status().
            Landmark: subprocess_manager_wired
    What to build:
      class SubprocessManager:
        start(tool: ToolConfig, args: str, cwd: str, session_id: str) → proc_id: str
          - spawn subprocess with Popen(stdin=PIPE, stdout=PIPE, stderr=STDOUT)
          - stream stdout line-by-line → yield to WS as { type:'cli_output', line, proc_id }
          - set idle_timer = asyncio.create_task(kill after DEV_CLI_IDLE_TIMEOUT_SECONDS)
        send_input(proc_id, text) → forwards to stdin
        abort(proc_id) → SIGTERM + SIGKILL fallback after 3s
        cleanup_idle() → called on session end; kill all procs for session_id
        _on_stdout_line(proc_id, line) → emit WS message + reset idle_timer
      Security: validate cwd is within allowed_roots before spawn
      Never run: rm -rf, git reset --hard, pip install (blocklist in yaml)
      Output: raw stdout goes to wing terminal panel only, NOT to ChatView directly
    File: backend/dev/subprocess_manager.py
    Test: spawn "echo hello", verify line streamed, proc cleaned up after timeout
    Landmark: subprocess_manager_wired

  [14.8] backend/dev/file_watcher.py — file activity monitor
    Status: DONE — watchdog Observer, 100ms debounce per (path,change) key, FileEvent dataclass,
            graceful degradation if watchdog not installed. Landmark: file_watcher_active
    What to build:
      Uses watchdog library (already in requirements.txt candidate)
      class FileWatcher:
        start(watch_dir: str, session_id: str, ws_send: callable)
          - watchdog Observer on watch_dir (recursive)
          - on_modified / on_created / on_deleted → emit { type:'file_activity',
            path, change:'edit'|'create'|'delete', session_id }
          - Debounce: ignore events within 200ms of previous for same path
        stop() → observer.stop() + join
      Only active in developer mode. Watches the active worktree path.
      Ignored paths: __pycache__, .git, node_modules, *.pyc, .next
    File: backend/dev/file_watcher.py
    Test: create a temp file in watch dir, verify file_activity WS message fires
    Landmark: file_watcher_active

  [14.9] Wire CLI routing into iris_gateway.py + DER Director
    Status: DONE — dev_cli + dev_abort message handlers in iris_gateway; DevOrchestrator
            selects tool (LLM or tool_hint), starts FileWatcher, spawns subprocess,
            streams cli_output WS messages, emits text_response on exit. Landmark: cli_routing_wired
    What to add:
      a) On mode=developer: init SubprocessManager + FileWatcher for session
         FileWatcher.start(worktree_path, session_id, ws_send)
      b) New message type handler in iris_gateway: 'dev_cli'
         Payload: { type:'dev_cli', task, cwd? }
         Flow: validate cwd in allowed_roots → cli_registry.get_tool_for_task(task)
               → if tool found: SubprocessManager.start(tool, task, cwd, session_id)
               → send { type:'cli_started', tool_name, proc_id } to WS
               → stream stdout as { type:'cli_output', line, proc_id }
               → on complete: DER Director synthesises summary → text_response to ChatView
      c) DER Director injection: when task_class detects CLI intent (developer mode only)
         → route to dev_cli handler instead of LLM direct response
         After CLI completes: pass stdout summary through prepare_spoken_text() then TTS
      d) 'dev_abort' message type: SubprocessManager.abort(proc_id)
      e) Send { type:'cli_activity', tool_name, workdir } to update ChatView top bar
    Files: backend/iris_gateway.py, backend/agent/agent_kernel.py (DER Director routing)
    Test: send dev_cli message, verify cli_started then cli_output then text_response
    Landmark: cli_routing_wired

Phase C — Web Crawler (both modes):
  [14.10] pip install crawl4ai + playwright install chromium
    Status: DONE — crawl4ai 0.8.6, playwright 1.58.0, watchdog installed. requirements.txt updated.
    Verified: from crawl4ai import AsyncWebCrawler → OK. Landmark: crawl4ai_installed

  [14.11] backend/crawler/robots_checker.py — polite crawling
    Status: DONE — 1h TTL domain cache, httpx fetch with 5s timeout, urllib.robotparser,
            returns True on fetch failure (don't block crawl on network issues). Landmark: robots_checker_wired
    What to build:
      class RobotsChecker:
        _cache: dict[domain, RobotFileParser]  — session-scoped, one parse per domain
        is_allowed(url: str, user_agent: str) → bool
          Parse robots.txt for domain (cache after first fetch)
          Return False if disallowed → log warning + note in crawl summary
    CRAWLER_USER_AGENT from .env (default: "IRIS-Agent/1.0 (respectful crawler)")
    File: backend/crawler/robots_checker.py
    Test: mock robots.txt disallowing /private, verify is_allowed("/private/page") = False
    Landmark: robots_checker_wired

  [14.12] backend/crawler/crawler_engine.py — Crawl4AI wrapper
    Status: DONE — async context manager, BM25ContentFilter, robots.txt gate per URL,
            polite delay, markdown_v2/markdown fallback, on_page_done callback, CrawlerUnavailable
            raised when crawl4ai missing. Landmark: crawler_engine_wired
    What to build:
      class CrawlerEngine (async context manager):
        __aenter__: AsyncWebCrawler(config=BrowserConfig(headless=True, user_agent=...))
                    await self.crawler.start()
        __aexit__: await self.crawler.close()
        async crawl(query, urls, instructions, max_pages, delay_ms) → CrawlResult:
          BM25ContentFilter(query=query, bm25_threshold=1.0)
          CrawlerRunConfig(content_filter=filter, delay_between_requests=delay_ms,
                           page_timeout=TIMEOUT, markdown=True, screenshot=False)
          For each url (up to max_pages):
            Check robots_checker.is_allowed(url) — skip if disallowed
            result = await self.crawler.arun(url, config)
            Append PageData(url, title, markdown=result.markdown, metadata=result.metadata)
            Emit { type:'crawler_page_fetched', url, page_number, total } via ws_send callback
          Return CrawlResult(query, pages, duration_ms, crawled_at)
      Dataclasses: CrawlResult, PageData (url, title, markdown, html|None, metadata, error|None)
      No browser window ever (headless=True is not optional)
    File: backend/crawler/crawler_engine.py
    Test: crawl https://example.com, verify PageData.markdown is non-empty string
    Landmark: crawler_engine_wired

  [14.13] backend/crawler/crawl_planner.py — brain model URL planner
    Status: DONE — LLM generates {urls,instructions,result_type,title} JSON, strips markdown
            fences, DuckDuckGo fallback on parse failure, URL count capped at CRAWL4AI_MAX_PAGES.
            Landmark: crawl_planner_wired
    What to build:
      async plan_crawl(user_query: str, current_date: str, llm_call: callable) → CrawlPlan:
        System prompt: "You are a URL planning assistant. Output JSON only."
        User prompt: query + date + instruction to output:
          { "urls": [...1-5...], "instructions": "Extract: ...",
            "result_type": "table"|"cards"|"metrics"|"mixed", "title": "..." }
        Call llm_call() with max_tokens=256 (small, structured output)
        Parse JSON response → CrawlPlan(urls, instructions, result_type, title)
        Fallback: if JSON parse fails → CrawlPlan with DuckDuckGo search URL for query
      CrawlPlan dataclass: urls, instructions, result_type, title
    File: backend/crawler/crawl_planner.py
    Test: mock llm_call returning valid JSON, verify CrawlPlan fields populated
    Landmark: crawl_planner_wired

  [14.14] backend/crawler/data_extractor.py — brain model data structurer
    Status: DONE — combined markdown capped at 12k chars, LLM extracts DashboardData JSON,
            defensive parse with fallback CardsSection per page. Landmark: data_extractor_wired
    What to build:
      async extract(query, pages: list[PageData], plan: CrawlPlan, llm_call) → DashboardData:
        Concatenate page markdowns (already BM25-filtered by Crawl4AI — no extra cleanup needed)
        System prompt: "You are a data extraction assistant. Output JSON only matching schema."
        Provide DashboardData JSON schema in prompt
        User prompt: query + instructions + concatenated markdown (truncate to 8000 chars if over)
        Call llm_call() with max_tokens=1500
        Parse JSON → DashboardData
        Fallback: if JSON parse fails → DashboardData with single CardsSection, one card per page
                  (title=page title, body=first 200 chars of markdown, url=page url)
      Pacman context label: crawler results are EXTERNAL zone — do NOT feed raw markdown
        into user/tool context zones; only the extracted DashboardData summary enters tool zone
    File: backend/crawler/data_extractor.py
    Test: mock pages with markdown content, verify DashboardData sections populated
    Landmark: data_extractor_wired

  [14.15] Wire crawler into iris_gateway.py — intent detection + open_tab event
    Status: DONE — _handle_crawler_query() wired: plan→crawl→extract→open_tab(dashboard)→text_response.
            Frontend isCrawlerQuery() heuristic routes matching queries to crawler_query WS type.
            external_research zone in ContextManager at 0.5x weight. Landmark: crawler_gateway_wired
    What to add:
      a) Intent classifier in iris_gateway (lightweight, keyword-first):
           CRAWLER_INTENT_PHRASES = ["find", "search", "what are people saying",
             "compare", "get the pricing", "monitor", "latest news", "fetch from"]
           is_crawler_query(message) → bool: phrase match + heuristic (contains URL-like or site name)
           Only routes to crawler if not already a dev_cli task
      b) Crawler flow in _process_text_message():
           if is_crawler_query and CrawlerEngine available:
             emit { type:'crawler_started', query, url_count } to WS
             plan = await crawl_planner.plan_crawl(query, date, llm_call)
             async with CrawlerEngine() as engine:
               result = await engine.crawl(plan.urls, plan.instructions, ws_send=self._ws_send)
             data = await data_extractor.extract(query, result.pages, plan, llm_call)
             emit { type:'open_tab', tab_type:'dashboard', id:uuid, title:plan.title, data }
             synthesis = f"Found results for '{query}' — see Dashboard →"
             generate_suggestions(query, data) → 3 contextual refinement suggestions
             emit { type:'text_response', content:synthesis, suggestions:[...] }
           on error: emit { type:'crawler_error', message:str(e) }
      c) Pacman context: crawler summary tagged EXTERNAL (not user/tool zone)
         Only DashboardData.summary injected into context assembly — not raw page content
    Files: backend/iris_gateway.py, backend/crawler/__init__.py
    Test: send "find latest AI funding rounds" → verify crawler_started, open_tab, text_response
    Landmark: crawler_gateway_wired

Phase D — Frontend WS Hooks:
  [14.16] hooks/useDevMode.ts — developer mode state + WS handlers
    Status: NOT STARTED — cli_activity/cli_started/cli_output/file_activity WS handlers needed
    What to build:
      State: workDir (string), activeTool (string|null), fileActivity (FileActivityEvent[])
      WS message handlers:
        'cli_activity'  → update workDir + activeTool
        'cli_started'   → set activeTool = tool_name
        'cli_output'    → append to terminal buffer (wing panel consumes this)
        'file_activity' → prepend to fileActivity list (cap at 50 items)
      openFileAsTab(path) → emit open_tab message with type='code', content=file content
        (reads via GET /api/files/read?path=... endpoint — add to main.py)
      Export: { workDir, activeTool, fileActivity, openFileAsTab }
    File: hooks/useDevMode.ts (new)
    Test: dispatch mock WS events, verify state updates
    Landmark: use_dev_mode_hook

  [14.17] hooks/useCrawler.ts — crawler state + WS handlers
    Status: PARTIAL — crawler_started/crawler_page_fetched/open_tab/close_tab/crawler_error
            forwarded as CustomEvents via useIRISWebSocket; dark-glass-dashboard.tsx listens.
            Dedicated useCrawler.ts hook not yet extracted.
    What to build:
      State: status: CrawlerStatus, tabs: Tab[]
      WS message handlers:
        'crawler_started'      → status = { state:'planning', urlCount, pagesDone:0 }
        'crawler_page_fetched' → status.pagesDone++, status.state='crawling'
        'open_tab'             → add/update tab in tabs array (dedup by id)
        'close_tab'            → remove tab by id, auto-select adjacent
        'crawler_error'        → status = { state:'idle', ... }, show error toast
      Export: { status, tabs, activeTabId, setActiveTabId }
    File: hooks/useCrawler.ts (new)
    Test: dispatch mock crawler WS sequence, verify tabs and status update correctly
    Landmark: use_crawler_hook

  [14.18] Modify hooks/useIRISWebSocket.ts — forward new message types
    Status: DONE — open_tab, close_tab, crawler_started, crawler_page_fetched, crawler_error
            all forwarded as window CustomEvents. Landmark: websocket_forwarding_updated
    What to add:
      Forward to useDevMode handlers: cli_activity, cli_started, cli_output, file_activity
      Forward to useCrawler handlers: crawler_started, crawler_page_fetched, open_tab,
                                      close_tab, crawler_error
      text_response: extract suggestions array if present → pass to ChatView suggestion state
    File: hooks/useIRISWebSocket.ts
    Test: verify existing message types still work after changes
    Landmark: websocket_forwarding_updated

Phase E — Backend Config + State:
  [14.19] backend/state_manager.py — persist CLI working directory + dev mode state
    Status: NOT STARTED — working_directory, recent_directories, active_cli_tool per session
    What to add:
      working_directory: str (per session) — default to project root or last used dir
      recent_directories: list[str] (last 5) — persisted in session state
      active_cli_tool: str | None — cleared on session end
      dev_mode_active: bool — mirrors iris_mode == "developer"
      Methods: set_working_directory(path), get_recent_directories(), clear_cli_state()
    File: backend/state_manager.py
    Test: set working directory, verify persisted and retrieved next call
    Landmark: state_manager_cli_extended

  [14.20] backend/main.py + .env + requirements.txt — config additions
    Status: PARTIAL — requirements.txt updated (crawl4ai, playwright, watchdog). .env vars
            (CRAWL4AI_* and DEV_ALLOWED_ROOTS) read from env in crawler_engine.py + subprocess_manager.py.
            main.py startup warning for empty DEV_ALLOWED_ROOTS not yet added.
    .env additions:
      DEV_ALLOWED_ROOTS=          # blank — user fills in their allowed paths
      DEV_CLI_IDLE_TIMEOUT_SECONDS=300
      CRAWLER_DELAY_MS=1000
      CRAWLER_MAX_PAGES=5
      CRAWLER_TIMEOUT_MS=10000
      CRAWLER_USER_AGENT=IRIS-Agent/1.0 (respectful crawler; contact: set-in-env)
    requirements.txt: add watchdog, crawl4ai, playwright
    package.json: verify recharts present (add if missing)
    main.py: on startup (developer mode): init CLIRegistry, warn if DEV_ALLOWED_ROOTS empty
             on startup (both modes): lazy-import CrawlerEngine (don't init until first crawl)
    Landmark: crawler_cli_config_wired

Phase F — Agent Suggestion Injection:
  [14.21] Modify backend/agent/agent_kernel.py — suggestion generation
    Status: NOT STARTED — short LLM call after each response to generate 3 contextual follow-up pills
    What to add:
      After every _respond_direct() or DER loop final response:
        generate_suggestions(response_text, task_class, mode) → list[Suggestion]
        Uses a short LLM call (max_tokens=100) with prompt:
          "Given this assistant response, suggest 3 short follow-up actions the user
           might want. Output JSON array: [{id, label, message}]. Be specific and
           contextually relevant. Never repeat the last user message."
        Attach suggestions to the text_response WS payload:
          { type:'text_response', content:..., suggestions:[...] }
        Suggestions must be contextually relevant — not generic ("tell me more" is banned)
        If LLM call fails: emit text_response without suggestions (graceful degradation)
    File: backend/agent/agent_kernel.py
    Test: mock LLM response, verify text_response payload contains suggestions array
    Landmark: suggestion_injection_wired

  Graduate condition:
    Phase A: TypeScript compiles clean. SuggestionPills render after responses in both modes.
             Dev mode CLI skin shows in ChatView. Dashboard wing shows tabbed content.
             DashboardRenderer renders all 4 section types.
    Phase B: Send dev_cli task in developer mode. Correct CLI tool selected and spawned.
             stdout streams to wing. ChatView receives synthesised summary. File activity updates.
    Phase C: Say "find the latest AI funding rounds". Crawler fires (no browser window).
             Dashboard tab opens with MetricsSection + CardsSection. ChatView gets one-liner.
             Suggestion pills offer: filter, sort, export, dig deeper.
    Phase D: Hooks tested. WS forwarding verified. No existing message types broken.
    Phase E: Config clean. Requirements installable. No startup regression.
    Phase F: Every response has contextual suggestion pills. LLM failure degrades gracefully.

  Dependency notes:
    Phase A: no backend needed, start immediately after Gate 2 verified
    Phase B: requires Gate 2 [13.2] worktree isolation for cwd safety
    Phase C: requires crawl4ai install [14.10] — can be done in parallel with Phase B
    Phase D: requires Phase A interfaces (types/iris.ts) and Phase B+C WS message shapes
    Phase E: config file edits only — no dependencies
    Phase F: requires Phase C (suggestions wired to crawler flow) + Phase A (pills UI)

  Regression tests after any Phase change:
    npx tsc --noEmit                              (TypeScript clean)
    python -m pytest backend/tests/ -v --tb=short (no backend regressions)
    python -c "from backend.iris_gateway import IRISGateway; print('OK')"

---

DOMAIN 15 — LINUX BUILD + CROSS-PLATFORM LAUNCHER
Goal: IRIS ships on Linux (Ubuntu/Debian .deb + AppImage) and the iris-launcher
works on both Windows and Linux, correctly launching IRIS in personal or developer mode.
The user must be able to switch modes from the launcher and have IRIS start in the
selected mode — on both platforms.

  Architecture note:
    iris-launcher is a Vite+React app (NOT Tauri). On desktop it opens at localhost:5173.
    It calls POST localhost:8000/api/mode to set the mode, then navigates to the IRIS app.
    For Linux: the launcher needs to spawn the correct backend + frontend commands for Linux.
    For Tauri (Windows MSI + Linux .deb/.AppImage): the Tauri shell auto-starts the backend.
    The launcher should detect whether it is in a Tauri context or a standalone dev context
    and adjust how it starts IRIS accordingly.

  [15.1] Linux Tauri build — .deb + AppImage
    Status: PARTIAL — tauri.conf.json updated: targets now ["msi", "deb", "appimage"],
            linux.deb.depends + linux.appimage.bundleMediaFramework set.
            build_backend.py already outputs iris-backend-x86_64-unknown-linux-gnu.
            Remaining: run cargo tauri build on a Linux machine (or CI) to produce artifacts.
    Prerequisites:
      - Install Rust + Cargo: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
      - Install Tauri CLI deps:
          sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev \
            libayatana-appindicator3-dev librsvg2-dev patchelf
      - Build: cd IRISVOICE && cargo tauri build
    Output: src-tauri/target/release/bundle/deb/*.deb AND .AppImage
    Verify: install .deb, launch app, confirm backend starts, orb connects
    Gaps to fix before building:
      a) src-tauri/tauri.conf.json: verify bundle.targets includes "deb" and "appimage"
      b) Backend binary bundled via build_backend.py must produce Linux ELF, not PE
         (currently built on Windows — needs Linux CI or cross-compile setup)
      c) src-tauri/src/main.rs: backend launch path must handle forward slashes on Linux
    Landmark: linux_tauri_build

  [15.2] iris-launcher Linux compatibility
    Status: PARTIAL — ModeSelectPage.tsx updated: after setMode() succeeds, detects Tauri via
            window.__TAURI__ check. In Tauri: stays in-app (navigate "/""). In dev/standalone:
            window.open(VITE_IRIS_APP_URL || 'http://localhost:3000', '_blank') + navigate('/').
            VITE_IRIS_APP_URL env var configurable for non-standard ports.
            Remaining: install node_modules in iris-launcher, verify tsc clean, test flow.
    Landmark: launcher_linux_compat (pending manual verification)

  [15.3] Mode switch → IRIS launch flow (both platforms)
    Status: DONE — Full real-time flow wired:
      backend /api/mode POST now broadcasts { type:'mode_changed', mode } to all WS clients.
      useIRISWebSocket.ts forwards it as iris:mode_changed CustomEvent.
      useLauncherMode.ts listens for iris:mode_changed → updates mode state instantly (no polling).
      iris-launcher ModeSelectPage opens IRISVOICE after mode set (__TAURI__ aware).
    Verified: CustomEvent dispatch/receive tested in browser preview. tsc exit 0.
    Landmark: mode_switch_launch_flow
    Full end-to-end flow:
      1. User opens launcher / IRIS startup screen
      2. Picks Personal or Developer
      3. Launcher POSTs /api/mode → backend stores mode
      4. IRIS frontend reads GET /api/mode (or receives mode_changed WS event)
      5. useLauncherMode() reflects mode immediately
      6. ChatView, tab bar, terminal tab all update
    What to build:
      a) useLauncherMode.ts: add WS event listener for 'mode_changed' (avoid polling)
      b) Backend /api/mode POST: broadcast { type:'mode_changed', mode } WS event
      c) IRISVOICE tab bar: terminal tab gated on isDeveloper
      d) iris-launcher ModeSelectPage: after POST succeeds, navigate to IRIS
         - Packaged Tauri: Tauri window already IS the IRIS app (same shell)
         - Dev standalone: window.open('http://localhost:3000') or redirect
    Files: IRISVOICE/hooks/useLauncherMode.ts, IRISVOICE/components/chat-view.tsx,
           iris-launcher/src/pages/ModeSelectPage.tsx, IRISVOICE/backend/main.py
    Landmark: mode_switch_launch_flow

  [15.4] Linux voice pipeline — end-to-end verification
    Status: PARTIAL — Linux compat confirmed in tests (Domain 2); manual test needed
    Linux prerequisites:
      sudo apt install portaudio19-dev libsndfile1 libasound2-dev
      pip install -r requirements.txt
    Remaining gaps:
      a) Piper TTS: downloads en_US-ryan-high.onnx on first run — verify writable path in AppImage
         Default download target should be ~/.iris/models/ not the bundle dir
      b) Wake word .ppn: Linux path exists in code; actual .ppn file must be present at that path
      c) faster-whisper: downloads model on first use — verify ~/.cache/huggingface writable
    Landmark: linux_voice_verified

  [15.5] Single-app packaging — merge launcher into IRISVOICE (recommended)
    Status: DECISION NEEDED — implement after Gate 2 [13.1-13.4] complete
    Option A (recommended): Merge launcher as IRISVOICE startup route
      - Tauri app starts → no mode in localStorage → show ModeSelectPage
      - Same Tauri window, no IPC, no port conflicts, one installer on each platform
      - iris-launcher components embedded in IRISVOICE/app/mode-select/
    Option B: Two separate apps
      - More complex install story, but cleaner separation
    Landmark: packaging_decision_recorded

  Graduate condition:
    1. Linux .deb installs cleanly on Ubuntu 22.04 LTS
    2. App launches → mode select screen appears (no terminal required)
    3. Select Personal → IRIS starts in personal mode (no terminal tab)
    4. Select Developer → IRIS starts with DEV badge + terminal tab + CLI routing active
    5. Voice pipeline functional on Linux (wake word, STT, TTS)
    6. Same mode-switch flow verified on Windows Tauri build

---

SESSION START CHECKLIST
