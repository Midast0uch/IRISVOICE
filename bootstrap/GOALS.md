IRIS Bootstrap Agent — Production Roadmap
This file defines what needs to be built, fixed, or completed to ship IRIS as a production-quality autonomous assistant.
File: IRISVOICE/bootstrap/GOALS.md
Read this at the start of every session.

OBJECTIVE ANCHOR (never changes)
Build IRIS until it can run fully autonomously: receive tasks through its own interface, execute them using its own backend, and improve itself over time without external scaffolding.

---

WHAT NEEDS WORK RIGHT NOW (quick read for session start)

  GATE STATUS: Gate 1 structurally verified; Gate 2 (Launcher + Developer Mode) is next.
    G1.1–G1.5 verified. G1.6/G1.7/G1.8 need hands-on e2e confirmation — BLOCKING.
    Domain 16 (Backend Stability) fully complete — idle memory flat, watchdog active.
    Domain 18 (C++ Hybrid Core Memory Engine) fully complete — all 6 phases verified, smoke tests pass.
    Domain 19 (Caducean v2) ✓ — backend endpoints re-verified end-to-end via Playwright MCP
      on 2026-06-13: /health, /state, /direction, /params (all clamps, all 422 validations).
      Frontend visual rendering still blocked by dev-server compile hang (see cmd.exe
      memory leak incident note below). All 4 v2 endpoints return real C++ values,
      state mutation works, contract verified. 5/5 Playwright MCP tests pass.
    NEW: API provider routing working — named providers (Cohere, DeepSeek, Anthropic, Chutes AI,
    Cerebras, OpenCodeGo) with pre-configured endpoints, verified across multiple providers.
    DER _is_api_provider bug fixed — providers now route correctly through infer().
    Simplified MODEL SELECTION card — named providers replace old generic api/vps/iris_local.
    Structured telemetry logging added — context assembly metrics, API request shapes,
    and DER metrics (xi, pacman_store/recall, der_steps, etc.) logged to irisvoice.log.
    NEW NORTH STAR: Domain 17 — Self-Coding Agent (agent inside IRIS).
    Complete G1.6→G1.7→G1.8 e2e → then Gate 2 → then Domain 17.
    ⚠️ BLOCKER: Domain 20 (Agent Multi-Step Tool Execution) must ship first —
    the agent kernel lacks a dynamic tool-call loop, permission wiring, and
    MCP discovery. Without D20, D17 cannot do multi-step self-coding.

   WINDOWS TAILSCALE MOBILE ACCESS — FIXED (2026-06-16):
     ChatWing (port 3000) now renders correctly on phone via Tailscale
     QR code at http://{tailscale_ip}:3000/?remote=1&mode=personal.
     Root cause: Next.js 16 dev server blocked ALL requests from
     unregistered origins (Tailscale IP 100.117.236.6 was not in
     allowedDevOrigins). JS bundles never loaded, React never hydrated.
     Fix: added Tailscale IP + regex for 100.x.x.x and *.ts.net to
     allowedDevOrigins in next.config.mjs. Also: removed React.use()
     on searchParams Promise (caused suspense during hydration), merged
     isMobile/isTailscaleAccess/isRemoteView into single mobile path
     with tab switching, added 12px horizontal padding for mobile panel.
     See pin_7255292b0b5f for full session record.

   WINDOWS DEV-SERVER MEMORY LEAK (2026-06-13) — PERMANENT FIX APPLIED:
    Symptom: cmd.exe parent shell spikes to 9-15+ GB working set when frontend dev
    server compiles. Observed at 8.9 GB, 11.8 GB, and 15.7 GB across three separate
    starts. User had to end-task the parent process manually each time.
    Root cause (three compounding Windows bugs):
      1. conhost.exe leak (vercel/turborepo#11808) — detached+stdio:'inherit' leaks
         a Windows Console Host per child that never reaps.
      2. Pipe buffer in parent (nodejs/node#49631) — child stdout buffered in parent
         memory up to pipe capacity when child hangs (e.g. slow fs, hung PostCSS).
      3. No tree cleanup on Windows (vercel/turborepo#11829) — TerminateProcess
         only kills direct child, not grandchildren.
    Permanent fix: scripts/iris_process_manager.py (Windows-aware process manager)
      uses windowsHide:true, redirects stdout to .iris-logs/*.log (not parent memory),
      wraps each child in a Windows Job Object for tree cleanup, writes PIDs to
      .iris-pids/*.pid. Verified: killing manager → Job Object closes → entire
      child tree killed by Windows. cmd.exe spike is structurally impossible.
    Plus: package.json `dev` switched to `next dev --webpack` to bypass the
    Turbopack postcss-subprocess hang on slow filesystems (vercel/next.js#91396).
    See pin pin_481e1aaee8cd for full incident record.

  LAUNCHER PATH CORRECTION (2026-06-13):
    Domain 13 docs previously stated launcher was at C:\Users\midas\Desktop\dev\iris-launcher\
    (a path that does not exist). The actual location is at IRISVOICE\iris-launcher\ —
    a sibling project within the same IRISVOICE repo, NOT a separate desktop directory.
    Verified by running launcher dev server on port 8080, navigating via Playwright
    MCP, confirming mode-select page renders at / with Personal/Developer cards.
    The orb (IRISVOICE Next.js on :3000) is launched FROM the launcher via the
    "Launch IRIS Widget" button in OverviewPage — not the entry point.

  DOMAINS WITH OPEN ITEMS:
    Domain 3  — Vision          (DEVELOPING — [3.1][3.2] need 2 more passing runs each)
    Domain 4  — Skills          (PARTIAL — [4.4] DONE; [4.5] self-improvement not proactive)
    Domain 7  — Backend quality (PARTIAL — [7.5] logging not standardised)
    Domain 8  — Distribution    (PARTIAL — [8.1] MSI untested on clean machine)
    Domain 11 — PiN verification (ALL 5 items not started — run alongside G1.6-G1.8)
    Domain 12 — MCP storage      (ALL 5 items not started — after D11 passes)
    Domain 13 — Launcher: Personal/Developer Mode (PARTIAL — [13.1] DONE, [13.2] NOT STARTED, [13.3] DONE, [13.4] DONE, [13.5] PARTIAL) ← GATE 2
    Domain 14 — CLI Toolkit + Web Crawler (PARTIAL — Phases A/B/C/E done; [14.2][14.16][14.19][14.21] remain)
    Domain 15 — Linux Build + Cross-Platform Launcher (PARTIAL — tauri.conf.json targets set; needs Linux build machine)
    Domain 17 — Self-Coding Agent (BLOCKED on Domain 20) ← NORTH STAR
    Domain 18 — C++ Hybrid Core Memory Engine ✓ all 6 phases verified
    Domain 19 — Caducean v2: Mitochondria to Mycelium ✓ ALL 7 PHASES COMPLETE (2026-06-13) ← BRANCH feat/caducean-v2-mitochondria-mycelium
      78 new v2 tests pass via pytest, 0 regressions, kill switch in place.
      Critical: Phase 0 fixes a dead-code bug where ffi_init_engine() was never called.
      End-to-end browser verification (2026-06-13): 4/4 v2 endpoints exercised via
      Playwright MCP against running backend. State mutation verified, clamping
      (a,b→[1,4], s→[0.1,0.8]) verified, 422 validation verified, engine_live
      confirmed. Visual IrisOrb / CaduceanDebugPanel rendering NOT verified
      (blocked by dev-server compile hang — see cmd.exe memory leak note above).
   Domain 20 — Agent Multi-Step Tool Execution (NEW — 7 items, investigation complete 2026-07-01)
     ⚠️ CRITICAL BLOCKER for D17 and long-horizon tasks. See docs/architecture/agent-multi-step-gaps.md
     Root cause: no agentic tool-call loop, permission UI disconnected, MCP static.

     SUB-INITIATIVE — Trust-Routing + Data-Centric Document Memory (W1–W10 DONE 2026-07-10):
       Plan: docs/plans/2026-07-10-trust-routing-document-store.md
       Architecture doc: docs/architecture/trust-routing-document-memory.md
       Branch: feat/agent-multi-step-tool-execution
         (commits 5d12dc55, 30b2b820, 756b4405, c5dc1111, 393d0660)
       What shipped (test-first CDD, all green):
         - W1/W2 Trust-zone routing: web/crawler tool outputs → "reference" (untrusted) zone;
                  per-turn external flag propagates to episodic fragment + Mycelium trust-cap.
         - W3 Frontend sanitization: DOMPurify on RichDocument html when trust≠trusted;
                  MermaidDiagram securityLevel→strict for untrusted. tsc clean, jest 4/4.
         - W4 Canonical DATA store keyed by document_id: DocumentDataStore (SQLite-WAL) +
                  Mycelium semantic + Immortus 4D chain (coords_from = real trajectory coord).
         - W5 Data-centric reformat: reformat_document(document_id, target_format) retrieves
                  canonical data; deterministic-first (stored variant → no LLM call).
         - W7 Trajectory-conditioned retrieval (O1): coordinate-proximity query over Immortus
                  4D chain (C++ iris_core + Python fallback) — "data gathered while thinking
                  like this," distinct from embedding cosine.
         - W8 Crystallization seeding (O2): document data seeded as trust-routed Mycelium
                  context node; trusted data crystallizes at PERMANENCE_THRESHOLD=8; trust-cap
                  (0.30) auto-excludes untrusted/web data from permanent memory.
         - W9 Proactive capture (O3): _capture_tool_result hooks the DER loop; any non-trivial
                  tool result (web/file) → DocumentDataStore → reformat-able. Threshold gate
                  skips None/error/trivial/low-relevance.
         - W10 Pheromone + cross-modal (O4): reformat_document reinforces a from→to pheromone
                  edge (DocumentDataStore); suggest_reformat() offers the sticky next format;
                  vocalize_document() speaks via SpeakTool; diagram_document() returns the
                  mermaid view. Test test_reformat_pheromone.py 11/11.
       Why it matters for D20: gives the agent a durable, trust-scoped, reformat-able memory
         of everything it produces/retrieves — the substrate D17 self-coding builds on.

  DOMAINS COMPLETE (do not revisit unless regression):
    Domain 1  — DER loop gaps       ✓ all 8 items verified
    Domain 2  — Voice pipeline       ✓ all 5 items verified (session 155, 91 tests)
    Domain 5  — Mycelium stubs      ✓ all 4 items verified
    Domain 6  — Frontend quality    ✓ all 6 items verified
    Domain 10 — Performance/memory  ✓ all 10 items verified
    Domain 16 — Backend stability   ✓ all 8 items verified — memory watchdog, idle tracker, wing fix, DCP panel
    Domain 18 — C++ Hybrid Core     ✓ all 6 phases verified — CMake+RE2, DBManager, Caducean+Sanitizer, EventIngestor+FFI, Python bridge, PyInstaller

  PRIORITY ORDER FOR NEW SESSIONS:
    0. VERIFY G1.6, G1.7, G1.8 — these block every downstream dependency
         Load Qwen3.5-9B through ModelsScreen, send a chat, confirm in-process inference
         streams at ≥40 tok/s with no orphaned processes. Then confirm tool calling
         works with iris_local model (create a skill, recall it same session).
    1. Domain 19 — Caducean v2: Mitochondria to Mycelium ✓ DONE 2026-06-13
         All 7 phases + Phase 0 complete on feat/caducean-v2-mitochondria-mycelium.
         78 new v2 tests pass via pytest, 3 pre-existing bugs fixed, kill switch in place.
         Ready for PR back to main. See docs/plans/cad_v2_integration_test_report.md.
    2. Domain 20 — Agent Multi-Step Tool Execution ← NEW CRITICAL BLOCKER
         Investigation complete (2026-07-01). 7 items identified. See:
         docs/architecture/agent-multi-step-gaps.md
         Items [20.1]-[20.3] (tool-call loop, permission wiring, tool progress UI)
         must ship before Domain 17 can function. See D20 for full spec.
    3. Domain 17 — Self-Coding Agent ← NORTH STAR (BLOCKED on D20 items [20.1]-[20.3])
    4. Domain 13 — Gate 2: Launcher + Developer Mode (13.1→13.2→13.3→13.5)
    5. Domain 14 — CLI Toolkit + Web Crawler remaining items ([14.2][14.16][14.19][14.21])
    6. Domain 11 — PiN + landmark bridge verification (foundation, run tests)
    7. Domain 3  — Vision (paint_iris_demo, vision_layer — 2 more passes each)
    8. Domain 12 — PiN + MCP storage integrations (after D11 verified)
    9. Domain 4  — Skills library (self-extension)
    10. Domain 7  — Backend reliability (logging standardisation)
    11. Domain 15 — Linux Build (blocked on Linux machine or CI)
    12. Domain 8  — Distribution (MSI clean install)
    13. Domain 9  — Advanced features (after everything else)

---

GATED MILESTONES (gates are sequential — do not start Gate 2 until Gate 1 verified)

  GATE 1 — DEVELOPER MODE (CURRENT GATE)
  ↓ Verify G1.1–G1.8 → proceed to Gate 2 → then Domain 17 (Self-Coding Agent)
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

  Session 2026-05-30 milestone — API Provider Routing:
    ✅ Named API providers working across multiple providers (2026-05-30)
      - Fixed DER _is_api_provider() to recognize named provider values (cohere, deepseek, etc.)
      - Provider→URL mapping with correct OpenAI-compatible endpoints
      - Cohere: https://api.cohere.ai/compatibility/v1 (dedicated OpenAI compat API)
      - Anthropic: https://api.anthropic.com/v1 (OpenAI SDK compat endpoint)
      - Deferred DER _swarm_enabled flag polish (see notes) to unblock Gate 1.6→1.8
    ✅ UI simplified: MODEL SELECTION has named providers with pre-configured endpoints
      - LM Studio and Local (GGUF) remain as separate connection types
      - Reasoning Model / Tool Model dropdowns show per-provider model lists
      - Swarm auto-off when API provider is selected
    ✅ Structured telemetry logging added to irisvoice.log
      - Context assembly: total_chars, episodic_chars, history_turns, etc.
      - API request: provider, model, messages count, chars, max_tokens
      - DER metrics: xi, der_steps, pacman_store/recall, traj_rows, map_events
      - Query with: python -c "import json; [print(json.dumps(d,indent=2)) for l in open('backend/logs/irisvoice.log') if (d:=json.loads(l.strip())) and 'xi' in d]"
    ⬜ G1.6-G1.8 still need local GGUF model verification (next session)
    ⬜ Bootstrap DB migration to runtime DB (next session)
    ⬜ Stress test prompt list development (next session)

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
    [G2.1] DONE — Launcher UI exists at IRISVOICE\iris-launcher\
           (sibling project within the same repo, Vite+React+Tauri, port 8080).
           ModeSelectPage, AppContext, use-iris-mode, GitPage, DiffReviewPage all built.
           /api/mode and /api/projects already in IRISVOICE backend.
           Verified live 2026-06-13: launcher dev server on :8080 renders
           mode-select page at /, shows Personal + Developer cards. Orb
           (Next.js on :3000) is launched FROM launcher via OverviewPage
           "Launch IRIS Widget" button, not the entry point.
    [G2.2] Backend git + diff endpoints (Domain 13.1) — DONE (git_ops.py, github_ops.py, network_ops.py, conversation_store.py created; backend boots cleanly)
    [G2.3] Git worktree isolation — agent writes to isolated branch (Domain 13.2)
    [G2.4] Developer mode capabilities gated in IRISVOICE (Domain 13.3) — DONE (capabilities.py, CapabilitySet gating on WS handlers, REST endpoints, tool_bridge, agent_kernel; backend boots cleanly)
    [G2.5] Terminal tab visible in developer mode only (Domain 13.4) — DONE (all 4 phases of terminal-chat-integration implemented, build passes)
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

  After Gate 2: proceed to Domain 17 (Self-Coding Agent) — the new strategic goal.
  Gate 3 (Agent Kernel Upgrade) is subsumed by Domain 17, since self-coding requires
  the strongest possible DER loop with real-time tool evaluation.

  GATE 3 — SELF-CODING AGENT (Domain 17)
  Goal: IRIS uses its own agent kernel, file editing tools, and DER loop to
        write, test, and commit its own remaining features without external
        AI assistance. See Domain 17 (added in this file) for full spec.
        Domain 17 IS Gate 3. Gate 4 is its graduate condition.

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

DOMAIN 2 — VOICE PIPELINE (sensory input) ✓ COMPLETE (session 155)
IRIS is a voice assistant. Without a working voice pipeline, users cannot
interact naturally. This is the primary input modality.

  Architecture summary (verified via test suite 2026-07-05):
    wake word (Porcupine, lazy) → AudioEngine frame loop → VoiceCommandHandler
    → Parakeet GPU (in-process, lazy-loaded) with faster-whisper CPU fallback
    → iris_gateway._on_voice_result → _process_voice_transcription()
    → process_text_message(from_voice=True) → _speak_response()
    → Pocket-TTS streaming → sd.OutputStream (fallback) or native C++ player
    → Word highlight thread (15.8 chars/sec, character-proportional timing)
    → Barge-in interrupt + flush_ms=400 VAD echo suppression
    All lazy imports confirmed. Platform-aware .ppn selection confirmed.

  [2.1] Wake word detection (Porcupine)
    Status: DONE — structural + manual e2e verified
    What was confirmed:
      - PorcupineWakeWordDetector disables gracefully (no access key → _disabled=True)
      - Disabled reason string is descriptive (mentions PICOVOICE_ACCESS_KEY)
      - Disabled on no wake words configured (v1 path also tested)
      - pvporcupine lazy-loaded inside _initialize_porcupine (not at module level)
      - Gateway has set_voice_handler() wired to _on_voice_result callback
      - gateway._voice_handler checked before start_recording()
    Regression: python -m pytest backend/tests/test_domain2_voice.py -v

  [2.2] Speech-to-text (Parakeet GPU + Whisper fallback)
    Status: DONE — Parakeet embedded in-process, HTTP boundary removed
    What was confirmed:
      - ParakeetTranscriber lazy-loads nvidia/parakeet-tdt-0.6b-v3 (~1.2GB VRAM)
      - Preloaded at startup via asyncio.create_task() to avoid first-call latency
      - dtype mismatch fixed (device_map=cuda + float32 input → cast to fp16)
      - Hallucination guard: VAD returns False → skip transcription entirely
      - Barge-in VAD flush: flush_ms=400 drops first ~400ms of frames
      - faster-whisper fallback (tiny/int8, ~40MB CPU) on Parakeet failure
    Regression: python -m pytest backend/tests/test_domain2_voice.py -v

  [2.3] Text-to-speech (Pocket-TTS streaming + native C++ player)
    Status: DONE — streaming playback + word highlighting + barge-in
    What was implemented:
      - Streaming LLM→TTS: sentences queue into _speak_response while LLM generates
      - sd.OutputStream for immediate playback (no waiting for full sentence)
      - Native C++ ring-buffer player (sub-5ms latency, lock-free)
      - Word highlight thread: 15.8 chars/sec, character-proportional timing
      - Barge-in: catch up remaining words at 30ms intervals
      - _playback_event synchronizes word thread with actual audio start
      - Sentence boundary 40→15 chars for faster TTS onset
    Regression: python -m pytest backend/tests/test_voice_pipeline.py -v (91 tests)

  [2.4] Voice-first DER loop mode
    Status: DONE — already fully implemented
    What was found:
      - DER_TOKEN_BUDGETS["voice_first"] = 15000 (< 20k — tight budget enforced)
      - process_text_message(from_voice=True) → _mode_name = "voice_first"
      - task_class == "voice_first" → single queue item limit (single-step response)
      - All 6 DER mode tests pass
    Landmark: voice_first_der_mode

  [2.5] Audio pipeline end-to-end solidification (session 150-155)
    Status: DONE — all bugs fixed, 91 tests passing
    What was fixed across sessions 150-155:
      - TTS double-play (duplicate play_stream call removed)
      - Parakeet silent failure (HTTP boundary → in-process embedding)
      - Voice state stuck (error handling + watchdog in _speak_response)
      - Word highlighting sync (character-proportional 15.8 chars/sec)
      - Cadence animations consistent across STT backends
      - Stale HTTP/8765 references cleaned up
      - Re-entrancy race (tts_started carries turn_id)
      - Multi-sentence word coverage (dynamic while True loop)
      - Fallback timing race (fallbackActive=false initially)
      - Turn_id propagation through text_response CustomEvent
      - Play-button TTS orb breathing (isolated playbackSpeaking state)
      - DER path TTS playback (chunk_callback fix)
      - Activation beep restored during STTPROC sound
    Architecture doc: docs/architecture/audio-pipeline.md (816 lines, definitive)
    Commit chain: fa9313c7 → 8a2bc8f4 → 3997c3ca

  Graduate condition: wake word → STT → agent response → TTS plays — full cycle
  without any manual keyboard input. Word highlighting in sync with audio.
  Barge-in interrupts TTS and starts new recording. Play button on any response
  triggers orb breathing + TTS audio.
  Regression test: python -m pytest backend/tests/test_voice_pipeline.py -v (91 tests)

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

  [3.4] SPATIAL LANGUAGE PHASE3: 3D Physics-Evolved Scalar Field Vision Pipeline (Future Experimental Milestone)
    Status: PROPOSED (Awaiting Experimental Validation)
    Goal: Fuses spatial NBL coordinate distribution into a 3D isotropic scalar field ψ(x,y,z,t) governed by the wave equation:
          ∂²ψ/∂t² = c²∇²ψ - γ(∂ψ/∂t) + F_data + F_topo
          To ensure physical stability, the field engine must enforce the Courant-Friedrichs-Lewy (CFL) condition:
          dt ≤ dx / (c · √3)
          Projections are rendered via Maximum Intensity Projection (MIP):
          MIP[x,y] = max_z |ψ(x,y,z)|
          and depth-colored RGB composites (Blue = low z, Green = mid z, Red = high z) to present full 3D spatial properties natively to any standard vision model.
          Particles are driven by Acoustic Radiation Force (ARF):
          F_ARF = -∇(ψ²) = -2ψ·∇ψ
          clustering them into orbit pathways and self-organizing torus vortex loops under a quasiperiodic topological kick:
          F_topo = A_topo · osc(t) · ∇ψ / |∇ψ|
          using three incommensurate frequencies (1.0, 1.6180339887, 1.4142135623) to represent stable landmarks as visual knots.
          *Note: Hold off implementation until experimental validation data confirms zero-shot structure recovery.*

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
    Status: DONE — GitHubServer (PAT-based) registered in tool_bridge.py
    Tools: github_get_user, github_list_repos, github_get_repo_branches,
           github_generate_ssh_key, github_list_ssh_keys, github_delete_ssh_key,
           github_connect_pat. Delegates to backend/github_ops.py.
    Landmark: github_mcp_wired

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
    Status 2026-06-13: SQLite persistence actually implemented (was
    previously claimed DONE but was in-memory only; fixed in Domain 19
    v2 commit ad1a50d5 as a discovered pre-existing bug). 12
    chat_persistence tests pass via pytest. Conversations now survive
    backend restarts. Schema: conversations (id, title, created_at,
    updated_at, pinned) + messages (id, conv_id FK CASCADE, role,
    text, turn_id, thinking, timestamp). WAL mode for concurrent
    read/write.
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

  NEW (2026-05-25) — TTS Performance & Memory Overhaul:
    - [10.11] F5-TTS GPU acceleration — inference_mode + autocast(fp16) — DONE in code
    - [10.12] Streaming LLM→TTS — parallel synthesis with generation — DONE in code
    - [10.13] Native C++ audio layer — lock-free ring buffer, sub-5ms latency — DONE in code
    - [10.14] Memory hygiene — duplicate Whisper fix, buffer release, cuda.empty_cache() — DONE
    Build native audio: .\build_native.ps1 | Install CUDA torch: pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126

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

LAUNCHER EXISTS — at IRISVOICE\iris-launcher\
  Vite + React + Tauri app, sibling to IRISVOICE/ (NOT a separate desktop directory).
  Run with: cd iris-launcher && npm run dev  (port 8080).
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

  [13.1] Backend git + diff API endpoints
    Status: DONE (2026-05-24)
    Created: backend/git_ops.py, backend/github_ops.py, backend/network_ops.py,
             backend/conversation_store.py, backend/mcp/github_server.py.
    All routes wired in backend/main.py. Backend boots cleanly. Next: e2e test from launcher.
    Landmark: launcher_git_api_wired
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
    Status: DONE (2026-05-24)
    What was built:
      a) backend/capabilities.py — centralized CapabilitySet with:
         personal = {tts, voice, chat}; developer = {tts, voice, chat, terminal, repo_access}
      b) iris_gateway.py — _handle_dev_cli, _handle_dev_abort, _handle_terminal_input
         now use CapabilitySet.require(CapabilitySet.TERMINAL) instead of ad-hoc config reads
      c) main.py — all git/diff/worktree/github REST endpoints gated with
         dependencies=[Depends(require_developer_mode)] → 403 in personal mode
      d) tool_bridge.py — get_available_tools() filters out developer-only tools
         (write_file, git_*, run_command, github_*, etc.) in personal mode.
         execute_tool() adds runtime rejection for blocked tools.
      e) agent_kernel.py — _build_system_prompt() keeps existing IRIS_SOURCE_DIR
         block AND prepends spec-mandated 3-line block in developer mode.
      f) dev_worktree.py — added get_active() / get_path() API so agent_kernel
         can resolve the active worktree path.
    Test: Set mode=personal → no terminal tab, repo APIs return 403, agent sees
         only basic tools. Set mode=developer → all capabilities unlocked.
    Landmark: mode_capabilities_gated

  [13.4] Terminal tab / Developer Workspace UI — developer mode only
    Status: DONE — all 4 phases of terminal-chat-integration plan implemented
            and build-verified (2026-05-24). Includes: DeveloperWorkspace,
            KanbanCanvas, KanbanSection, KanbanCard, CardContentRenderer,
            MindMapView, CodePreviewPanel, FloatingPanel, Xur spinner,
            WorkspaceToolbar, ArchiveDock. Backend e2e still pending
            Gate 1.6/1.7/1.8 + Domain 2 inference verification.
    What was built:
      a) TerminalContext (contexts/TerminalContext.tsx) — widget state owner,
         auto-floats on iris:cli_started, tracks file activity ring-buffer.
      b) TerminalWidget (components/terminal/TerminalWidget.tsx) — xterm.js
         host using a portal pattern so the xterm instance survives
         dock↔float transitions. Solid dark background (#0b0c1a) + inner
         gradient overlay to blend with chat-view aesthetic.
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
      h) WorkspaceTabBar — glass aesthetic, glow accents, '+' button for new tabs,
         draggable tabs with type-colored indicators.
      i) Focus Mode — 4-state cycle (Full → Work → Chat → Zen) with individual
         section toggles (Terminal / Archive / Kanban). Smooth AnimatePresence
         transitions. Focus button label reflects current preset.
      j) KanbanCanvas + KanbanSection + KanbanCard — glass panels, glow borders,
         type-specific content previews (code snippet, doc excerpt, conversation
         last message), compact mode for Chat preset.
      k) ArchiveDock — auto-collapses to 2px glow line when empty, expands on
         hover. Actual tab labels instead of cryptic IDs.
      l) ConversationChips — repositioned inline in input toolbar (Send button
         row) so it is never overlapped by workspace content. Always visible
         with count badge; subdued style when empty.
    UI verification screenshots: verification/p1-focus-{full,work,chat,zen}.png
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

  [13.6] Tailscale Mobile Integration
    Status: DONE — network exposure, setup wizard, QR codes, mobile chat, Tailscale spotlight
    What was built:
      a) Backend listens on 0.0.0.0 (env IRIS_BACKEND_HOST override)
      b) CORS allows *.ts.net + 100.* CGNAT range
      c) /api/network/status + /api/network/qrcode endpoints
      d) Launcher TailscalePage fetches real status, shows QR codes + setup checklist
      e) Main app renders chat-only on mobile (< 768px)
      f) Conversation history syncs via backend SQLite (/api/conversations)
      g) `hooks/useTailscaleAccess.ts` — detects non-localhost access (Tailscale/LAN IPs)
      h) `app/page.tsx` — renders chat-only CHAT_SPOTLIGHT mode when accessed via Tailscale IP
         (no orb, no dashboard wing, no control center; conversation history preserved)
    Verification:
      - Screenshots captured 2026-05-20: localhost view + Tailscale IP view (100.117.236.6:3000)
      - Tailscale currently active: IP 100.117.236.6, DNS desktop-or4l5im.taildad851.ts.net
      - Code review passed: useTailscaleAccess hook + page.tsx early-return branch verified
    Landmark: tailscale_mobile_wired

  [13.7] Conversation history cross-device sync 
    Status: DONE — backend SQLite is source of truth; localStorage is offline cache
    API: GET /api/conversations, POST /api/conversations, GET /api/conversations/{id},
         POST /api/conversations/{id}/messages, DELETE /api/conversations/{id},
         PATCH /api/conversations/{id}
    Frontend: chat-view.tsx fetches on mount, POSTs new convs + messages, shows sync status indicator.
    Landmark: conversation_sync_wired

  [13.8] MCP-first external tool integration
    Status: PLANNED
    Note: CLI driver approach deprioritized. External tools (Figma, Blender, etc.)
          will integrate via MCP server interfaces, not terminal/CLI drivers.
          Agent kernel routes to MCP tools through tool_bridge.

  [13.9] GitHub MCP wiring 
    Status: DONE
    What was built:
      a) MCP tool: github_read_issue(owner, repo, number) → body + comments
      b) MCP tool: github_read_pull_request(owner, repo, number) → body + comments
      c) MCP tool: github_create_issue(owner, repo, title, body) → issue_url
      d) MCP tool: github_create_pull_request(owner, repo, title, body) → pull_request_url
    Landmark: github_mcp_wired

  Graduate condition:
    Personal mode: Launcher opens, user selects Personal, IRISVOICE loads, no terminal tab.
    Developer mode: Launcher opens, user selects Developer, IRISVOICE loads with DEV
    context, terminal tab visible, agent works in isolated worktree, session end
    routes to DiffReviewPage for approve/discard. Main repo clean throughout.

---

## Domain 16 — Backend Stability & Memory Optimization ✓ COMPLETE

All 8 items verified and operational. Do not re-open unless a regression is observed.

  [16.1] Orphan process cleanup — DONE (2026-04-25)
    PyInstaller --onefile spawns parent stub + child Python. start-backend.py now skips
    both os.getpid() AND os.getppid() when killing orphans. Tauri exit uses
    taskkill /F /T /IM iris-backend* to kill entire process tree.
    Landmark: orphan_cleanup_fix

  [16.2] IdleTracker — DONE (2026-04-26)
    New: backend/core/idle_tracker.py — process-wide singleton.
    touch() called on every WS message (iris_gateway.py) and every HTTP request
    (middleware in main.py, skips health-check polls).
    DistillationProcess.idle_minutes now delegates to IdleTracker — record_activity()
    was never called from production code before this fix.
    MCP health check loop skips ping when user active (< 30s idle).
    Landmark: idle_tracker

  [16.3] Remove 30-second GGUF pre-warm scan — DONE (2026-04-26)
    backend/main.py: deleted asyncio.ensure_future(_prewarm_model_cache()).
    GGUF scan now fires lazily on first ModelsScreen open.
    Eliminates the RSS spike visible at t=30s on every cold start.
    Landmark: defer_gguf_prewarm

  [16.4] Memory watchdog — DONE (2026-04-26)
    New: backend/core/memory_watchdog.py
    Soft cap 800MB → gc.collect() + Mycelium maintenance.
    Hard cap 1400MB → also unload active local LLM.
    Both caps configurable via IRIS_MEM_SOFT_MB / IRIS_MEM_HARD_MB env vars.
    Watchdog task started in main.py lifespan, cancelled cleanly on shutdown.
    Landmark: memory_watchdog

  [16.5] Vision model swap LFM2.5-VL-1.6B → LFM2.5-VL-450M — DONE (2026-04-26)
    Old 1.6B GGUF uninstalled (HF cache deleted via scripts/uninstall_old_vl.py).
    New: LiquidAI/LFM2.5-VL-450M-GGUF (LFM2.5-VL-450M-Q4_0.gguf + mmproj-LFM2.5-VL-450m-Q8_0.gguf).
    Model files downloaded to ~/models/LFM2.5-VL-450M/.
    start_vl.sh updated; scripts/start_vl.ps1 added for Windows.
    scripts/download_vl_model.py added for one-command download.
    llama-server alias remains "lfm2.5-vl" — no backend code changes needed.
    Landmark: vision_model_450m

  [16.6] Wing overflow fix — DONE (2026-04-26)
    chat-view.tsx and dashboard-wing.tsx: `top: '50%'` with no translateY placed
    wings 258px below Tauri window bottom (WIN_H=680px). Fixed to `top: '6vh'`
    + `overflow: 'hidden'` + `maxHeight: calc(100vh - 24px)`.
    html/body already had `overflow: hidden !important; position: fixed;`.
    Landmark: wing_overflow_fix

  [16.7] DCPStatsPanel — DONE (2026-04-26)
    New: components/dev/DCPStatsPanel.tsx — real-time DCP stats card grid.
    Mounted in dark-glass-dashboard.tsx monitor tab, developer mode only.
    WS event `dcp_pruned` forwarded as `iris:dcp_pruned` CustomEvent in useIRISWebSocket.ts.
    Landmark: dcp_stats_panel

  [16.8] Idle memory profiler — DONE (2026-04-26)
    New: scripts/profile_backend_idle.py — records RSS/VMS/CPU% every 5s for 5 min.
    Run before/after optimization passes to prove impact.
    Output: backend/logs/idle_profile_<UTC>.csv

  Graduate condition — MET:
    1. scripts/profile_backend_idle.py FINAL run shows flat RSS over 5 min ✓
    2. No process with CPU% > 1 while user is idle ✓
    3. Memory watchdog log shows no SOFT cap hits during a normal 30-min session ✓
    4. Tauri exits cleanly — Get-Process iris-backend* returns nothing after close ✓

---

## Domain 17 — Self-Coding Agent (Agent Inside IRIS)  ⭐ NEW NORTH STAR

**Priority: #1** — The strategic goal. IRIS must be able to use its own agent kernel,
file editing tools, and DER loop to write, test, and commit its own remaining features
without relying on an external AI assistant (Claude Code, Copilot, etc.).

**Why this exists**: Every domain below Domain 17 will be built by IRIS itself — not
by an external AI. This is the completion condition: IRIS ships itself.

**Prerequisites** (Gate 1 + Gate 2 must be structurally in place):
  ○ Gate 1.6 verified — in-process local inference confirmed (model loads,
    chat sends, reply streams at ≥40 tok/s)
  ○ Gate 1.8 verified — tool calling works with iris_local model
    (skills created and recalled within the same session)
  ○ Gate 2 terminal — agent has CLI access for git, test, build commands
    (developer mode terminal tab, worktree isolation)
  ○ DER loop operational — agent can plan, execute tools, evaluate results

**Architecture**:
  The existing AgentKernel + DER loop + tool_bridge already support self-coding.
  What is missing is the specific MCP tooling and agent prompt structure that
  makes IRIS treat its own source as a work product — not just a conversational topic.

  Flow:
    1. User gives high-level task → DER loop plans subtasks
    2. IRIS reads its own source (file_manager MCP: read_file, list_directory)
    3. IRIS edits its own source (file_manager MCP: write_file, edit_file)
    4. IRIS runs tests (dev_cli → npm test, pytest)
    5. IRIS commits changes (dev_cli → git commit via GitPage hooks)
    6. IRIS reports what it changed and why

**Prompt injection**:
  When self-coding mode is active, the agent system prompt includes:
    "You are writing code for yourself — your own source repository.
     The code you write is your own future self.
     Follow the coding standards already established in the codebase.
     Do NOT add docstrings or comments that explain what the code does
     unless the existing codebase uses that style.
     Each edit must be the minimum change needed."

  [17.1] Self-coding mode trigger
    Status: NOT STARTED
    What to build:
      a) `/api/mode` extended with mode=`self-coding` (or `developer` extends to self-coding)
      b) On self-coding mode: inject the "you are writing your own code" prompt
      c) Gate file_manager MCP to the repo root (one level up permission)
      d) Enable git commit/push through the dev_cli tool
    Test: Set mode=self-coding. Send "add a /healthz endpoint to main.py".
          Verify IRIS reads main.py, writes the edit, and the /healthz endpoint
          returns 200 when tested.
    Landmark: self_coding_mode_wired

  [17.2] Self-coding prompt layer
    Status: NOT STARTED
    What to build:
      a) backend/agent/prompts/self_coding.py — the prompt layer injected when
         mode=self-coding or mode=developer with self-coding enabled
      b) Key prompt sections:
         - "You are writing code for your own source repo" (top-level)
         - Code quality constraints (no unnecessary work, bounded memory, etc.)
         - Git workflow: read → edit → test → commit → report
         - When in doubt: read first, ask for clarification second, edit last
      c) Prompt injection point: agent_kernel.py `_build_system_prompt()` or
         equivalent — check mode and prepend self-coding block
    Test: Switch to self-coding mode, inspect the DER loop system prompt,
          verify the self-coding block is present (test via string assertion).
    Landmark: self_coding_prompt_loaded

  [17.3] Self-coding tool chain
    Status: NOT STARTED
    What to build:
      a) Verify file_manager MCP tools are available in self-coding mode:
         read_file, write_file, edit_file, list_directory, create_directory,
         delete_file, search_files
      b) Add a new MCP tool if needed: `run_test` — wraps `pytest` or `npm test`
         and returns pass/fail + output
      c) Add `git_commit` tool: git add -A && git commit -m "message"
         (links to the existing GitPage workflow, uses same underlying git)
      d) Add `git_push` tool: pushes current branch (developer mode only,
         requires user confirmation for main/master)
      e) All tools must be gated on developer or self-coding mode
    Test: In self-coding mode, call each tool and verify it works.
          Locked in personal mode: all self-coding tools return 403.
    Landmark: self_coding_tool_chain

  [17.4] Test-evaluate loop for self-coding
    Status: NOT STARTED
    What to build:
      a) After every file edit during self-coding, DER loop automatically runs
         the affected test suite (or nearest test file)
      b) On test failure: DER loop reads the test output, plans a fix, re-edits,
         re-runs, retry up to 3 times
      c) On 3 consecutive test failures: stop, present the diff + failure output
         to the user, ask for guidance
      d) On all tests pass: proceed to next subtask in the task plan
    Implementation:
      - Modify `_execute_plan_der()` or add a `_self_coding_evaluate()` step
        that runs after each tool call when mode=self-coding
      - Use `subprocess_manager` (already built in Domain 14) to run tests
    Test: Make a deliberate small error in a Python file, let IRIS self-correct
          via the test-evaluate loop. Verify it fixes the error within 3 attempts.
    Landmark: self_coding_test_evaluate

  [17.5] Self-coding safety constraints
    Status: NOT STARTED
    What to build:
      a) Protect critical files from accidental overwrite:
         - bootstrap/coordinates.db (graph database)
         - .env (credentials config — never read/write)
         - backend/sessions/* (user session data)
         - node_modules/, __pycache__/, .git/ (build artifacts)
      b) Before any write_file or edit_file: validate target path is within
         the project repo (not /etc, not C:\Windows, not user home)
      c) Before git commit: run a pre-commit check that no test suite is
         completely broken (smoke test at minimum)
      d) All MCP tool calls logged to backend/logs/security/security_audit.log
         with session_id, tool, target_path, timestamp
      e) Maximum edit depth per session: 50 file operations (configurable via
         IRIS_MAX_SELF_EDITS env var)
    Test: Try to write to /etc/passwd → rejected. Try to overwrite .env → rejected.
          Try to delete coordinates.db → rejected. Verify audit log entries created.
    Landmark: self_coding_safety

  Graduate condition:
    1. User says "add a /healthz endpoint to main.py" in self-coding mode
    2. IRIS reads main.py, writes the edit, runs the test suite, commits the change
    3. No critical files were touched
    4. The diff is visible in the Launcher DiffReviewPage
    5. User can approve or discard the change
    6. All remaining domains (2, 3, 4, 7, 8, 11, 12, 13, 14, 15) can be completed
       by IRIS operating in self-coding mode — the external AI assistant is
       only needed for Domain 17 itself and for Gate 2 terminal wiring.

  Final objective:
    When Domain 17 graduate condition is met, IRIS can complete every remaining
    open item in Domains 2–15 on its own. The bootstrap scaffolding (this file,
    the external AI, the MCM SDK) exists only to bring IRIS to this point.
    After Domain 17 is done, IRIS ships itself.

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

DOMAIN 18 — C++ HYBRID CORE MEMORY ENGINE ✓ COMPLETE
Replace the pure-Python memory hot path with a C++ core that eliminates
ReDoS (via Google RE2) and read connection overhead (via pre-keyed pool).
All math (Caducean + EML) verified, all audited bugs fixed.

Source of truth: `backend/memory/implementation_plan.md` (audited, bug-fixed).
Phased plan: `.windsurf/plans/cpp-memory-engine-23ec52.md`

  [18.1] Phase 1 — Infrastructure & CMake Setup
    Status: DONE
    What to build:
      a) `src-tauri/src/iris_core/` directory + `CMakeLists.txt`
         - FetchContent for RE2 (tag 2024-07-01), find_package for SQLCipher
         - CMAKE_CXX_STANDARD 17, POST_BUILD copy to lib/
      b) `iris_core.h` — FFI C-interface header (extern "C", all API exports)
      c) Stub `iris_core.cpp` — init/shutdown/health only
    Gate: `iris_core.dll` compiles and links. No runtime test yet.
    Test: `cmake --build .` produces `lib/iris_core.dll`
    Landmark: cpp_core_cmake_ready

  [18.2] Phase 2 — DBManager + Schema Migration
    Status: DONE
    What to build:
      a) `db_manager.h` — singleton, writer thread, read pool, ReadGuard RAII
      b) `db_manager.cpp` — all audited fixes:
         - hex_to_bytes validates characters (endptr + range check)
         - is_healthy() locks queue_mutex
         - run_writer_loop() try/catch with set_exception
         - PRAGMA cache_size=-2000 (~2MB per connection)
         - init_read_pool() pre-opens 4 connections
         - drain_read_pool() closes all on shutdown
      c) `backend/memory/migrations/001_swarm_and_security_migration.sql`
    Gate: async writes + pooled reads both functional. No SQLite locks.
    Test: `g++ test_db_manager.cpp db_manager.cpp -lsqlcipher`, all asserts pass
    Landmark: cpp_db_manager_operational

  [18.3] Phase 3 — Caducean + Security Sanitizer
    Status: DONE
    What to build:
      a) `caducean.h/.cpp` — mutex-guarded singleton, F(u)=au-bu³, thresholds
      b) `security_sanitizer.h/.cpp` — RE2 patterns, sanitize-then-truncate:
         - 5 bounded regexes (API keys, OpenAI, SSH, connection strings)
         - MAX_STORED_BYTES = 65536 (post-sanitization truncation)
         - No hard cap before scan (RE2 O(n) guarantee)
    Gate: RE2 scrubs all patterns. 1MB payload <5ms. Truncation preserves suffix.
    Test: RE2 unit test with malicious regex payload (no hang)
    Landmark: cpp_sanitizer_re2_proven

  [18.4] Phase 4 — Event Ingestor + Full FFI Gateway
    Status: DONE
    What to build:
      a) `event_ingestor.h/.cpp` — UUID gen, sanitize, async queue, spill buffer
      b) `iris_core.cpp` — all FFI functions:
         - calculate_eml uses ReadGuard (not manual acquire/release)
         - immortus_chain_append waits on future.get()
         - EML queries use ORDER BY created_at DESC LIMIT 3
      c) `generate_sqlite_uuid()` with sqlite3_randomness() + v4 bit masking
    Gate: All FFI functions callable from C. Health check passes after ingest.
    Test: C++ integration test — init → ingest → calculate_eml → shutdown
    Landmark: cpp_ffi_gateway_complete

  [18.5] Phase 5 — Python FFI Bridge + Integration
    Status: DONE
    What to build:
      a) `backend/gateway/iris_ffi.py` — ctypes bindings + fallback engine
         - ffi_init_engine returns False on C++ failure (not always True)
         - PythonCaduceanFallbackState when DLL missing
      b) `ws_manager.py` — observe_command_execution auto-recording
      c) `der_loop.py` — Caducean-modulated next_ready step prioritizer
    Gate: All 4 test suites pass (FFI, fallback, concurrency, agent loop).
    Test:
      python -m pytest backend/gateway/tests/test_iris_ffi.py -v
      python -m pytest backend/gateway/tests/test_iris_ffi_fallback.py -v
      python -m pytest backend/memory/tests/test_db_concurrency_stress.py -v
      python -m pytest backend/tests/test_agent_loop_upgrade.py -v
    Landmark: python_ffi_bridge_wired

  [18.6] Phase 6 — PyInstaller Packaging
    Status: DONE
    What to build:
      a) Update `iris-backend.spec` to bundle `lib/iris_core.dll`
      b) Verify frozen binary starts with no import errors
    Gate: Frozen binary contains `lib/iris_core.dll`. Backend starts clean.
    Test: `python build_pyinstaller/compile.py`, run binary, /health returns 200
    Landmark: pyinstaller_bundles_cpp_core

  Graduate condition: MET (2026-05-25)
    All 6 phases complete and gated. C++ core runs in-process with Python.
    Write throughput ≥1000 events/s. Read latency <2ms (pooled).
    RE2 sanitization on 1MB payload <5ms with zero ReDoS risk.
    Frozen binary ships with `iris_core.dll` embedded.
    Tauri cargo check passes with no Windows file-locking errors.

  Regression tests after any phase change:
    & build_cpp_core.ps1                      (C++ compiles clean)
    python -m pytest backend/tests/test_iris_core_smoke.py -v  (9/9 pass)
    cargo check --manifest-path src-tauri/Cargo.toml             (frontend clean)
    python -c "from backend.gateway.iris_ffi import IrisCoreEngine; print('OK')"

---

## DOMAIN 19 — CADUCEAN v2: MITOCHONDRIA TO MYCELIUM  ⭐ NEW
Branch: `feat/caducean-v2-mitochondria-mycelium`
Spec: `docs/plans/Cadv2plan.md` (implementation) + `docs/cad_v2_architecture.md` (architecture)
Date opened: 2026-06-12

**The strategic goal:** Make the Caducean Engine the **mitochondria** of the Mycelium memory
system. It already exists as C++ code (Domain 18) but is currently dead code — `ffi_init_engine()`
was never called from `MemoryInterface.__init__`, so every Caducean call fell back to the Python
stub returning `MAINTAIN`. v2 fixes this and wires the engine's physics state (u, ξ, phase_accel)
into Mycelium decay, resonance retrieval, the DER loop, and the voice pipeline.

**Why now:** Domain 17 (self-coding) needs the strongest possible DER loop with real-time
tool evaluation. The Caducean v2 mitochondrial governor is the foundation that makes the DER
loop stable on long-tier tasks (Gate 2 result: 22.75× efficiency on 150–200 step sessions).
Without it, self-coding would be the rambling baseline.

**Architectural decisions (2026-06-12):**
  - Biometric key: Option C — frontend generates session_id, passed via WS handshake
  - Tauri↔Python comms: Option A — HTTP POST to FastAPI /api/caducean/*
  - Frontend state: Option A — polling Tauri commands at 500ms
  - Future: Option B — WebSocket broadcast when latency becomes a felt problem
  - DLL ownership: Python owns iris_core.dll (single ctypes load), Tauri is thin proxy
  - This avoids: memory spikes from duplicate loading, race conditions, version mismatch

  [19.0] Phase 0 — Critical engine initialization fix (P0, blocks everything else)
    Status: ✓ DONE 2026-06-12 (commit dbc4384f)
    Built: 1 file, 1 try/except block (~30 lines), `_caducean_engine_initialized` flag
    Result: 415+ existing tests pass, 0 regressions, engine init returns True
    Landmarked: caducean_engine_actually_initialized ✓
    Bug: `backend/memory/interface.py` accepts `biometric_key` but never calls `ffi_init_engine()`.
         The C++ engine is loaded by ctypes lazily but never initialized → all Caducean calls
         fall through to `_PythonCaduceanFallbackState.recommend()` which returns 2 (MAINTAIN).
    Fix: Add at end of `MemoryInterface.__init__`:
      ```python
      try:
          from backend.gateway.iris_ffi import ffi_init_engine
          ffi_init_engine(db_path, biometric_key.hex())
      except Exception as _e:
          logger.warning(f"[MemoryInterface] C++ engine init failed: {_e} — Python fallback")
      ```
    Wrapped in try/except so backend never crashes if DLL missing.
    `ffi_init_engine()` is idempotent (checks `_initialized` flag).
    Test: Run `python -c "from backend.memory.interface import MemoryInterface; m = MemoryInterface(None, 'test.db', b'\\x00'*32); print('OK')"`
    Verify log line `[iris_ffi] C++ core loaded from ...` appears.
    Landmark: caducean_engine_actually_initialized

  [19.1] Phase 1 — C++ core: winding numbers, phase history, adaptive safety net, DirectionSignal
    Status: ✓ DONE 2026-06-12 (commits 20bb05c7 + 6e96a0a9)
    Files: `src-tauri/src/iris_core/caducean.h`, `caducean.cpp`, `iris_core.h`, `iris_core.cpp`
    What to build:
      a) SessionState: add `l, m, xi_prev1, xi_prev2, c_eff`
      b) DirectionSignal struct: `{target_u, force_magnitude, u_current, phase, balance}`
      c) caducean_init_session(session_id, l, m) — compute c_eff
      d) update(): shift phase history, advance with c_eff
      e) recommend() with adaptive safety net:
         Q > 0.8 AND phase_accel > 0.05 → return 3 (TOPO_VIOLATION)
      f) get_direction_signal(): F = a*u - b*u^3, target_u = sign(u)
      g) set_params(session_id, a, b, s): dynamic Duffing potential tuning
      h) iris_core.cpp: O(1) EML formula (Ne=x, Nt=y, L=min, V=sum+1)
      i) FFI exports: caducean_init_session, caducean_get_direction_signal, caducean_set_params
    Gate: build_cpp_core.ps1 succeeds; smoke test loads DLL; DirectionSignal struct has all 5 fields
    Test: python -m pytest backend/tests/test_iris_core_smoke.py -v (existing 9 + new ~6 tests)
    Landmark: caducean_v2_cpp_complete

  [19.2] Phase 2 — Python FFI: ctypes bindings, fallback updates
    Status: ✓ DONE 2026-06-12 (commit e7935f4e)
    File: `backend/gateway/iris_ffi.py`
    What to build:
      a) `IrisDirectionSignal(ctypes.Structure)` with the 5 double fields
      b) _IrisFFI: register argtypes/restypes for 3 new FFI functions
      c) Module-level helpers: ffi_caducean_init_session, ffi_caducean_get_direction_signal, ffi_caducean_set_params
      d) _PythonCaduceanFallbackState: return mock DirectionSignal
    Test: All FFI tests + fallback tests pass.
    Landmark: caducean_v2_ffi_wired

  [19.3] Phase 3 — Mycelium modulation + new schema
    Status: ✓ DONE 2026-06-12 (commit cda07d56)
    Files: `backend/memory/interface.py`, `mycelium/interface.py`, `mycelium/scorer.py`, `mycelium/resonance.py`
    New: `backend/migrations/003_caducean_trajectories.sql`
    What to build:
      a) caducean_trajectories table: (session_id, step, x, y, xi, u, balance, recommendation)
      b) Migration call in MemoryInterface.__init__ (idempotent)
      c) mycelium_record_anomaly(session_id, signal_type) → QuorumSensor
      d) EdgeScorer.apply_decay(): read latest u, set multiplier 0.5 (u>0) | 1.0 (u≈0) | 1.8 (u<0)
      e) ResonanceScorer._score_candidate(): modulate multiplier by 0.5 (creativity) | 1.8 (focus)
    Test: All memory tests pass + new trajectory tests.
    Landmark: mycelium_caducean_modulated

  [19.4] Phase 4 — Agent kernel: DER queue modulation, TOPO_VIOLATION, trajectory controller
    Status: ✓ DONE 2026-06-12 (commit f58e6193)
    New: `backend/agent/coupled_registry.py`
    What to build:
      a) der_loop.next_ready(): fetch DirectionSignal, restrict to critical when target_u=-1
      b) agent_kernel: compute balance=clamp(EML/2.34, 0.1, 3.0); handle recommendation=3
      c) agent_kernel: persist trajectory row to caducean_trajectories
      d) trajectory_controller: tune a, b, s based on violation count (clamped)
      e) coupled_registry: singleton; rational c_eff ratio → angular momentum exchange;
         irrational → destructive interference
    Test: All DER tests + new coupled_registry tests.
    Landmark: der_caducean_v2_wired

  [19.5] Phase 5 — Tauri shell + FastAPI endpoints (thin proxy)
    Status: ✓ DONE 2026-06-12 (commit 5d60aa66)
    What to build:
      a) 3 Tauri commands: get_state, get_direction_signal, set_params (HTTP proxy)
      b) Register in main.rs invoke_handler
      c) 3 FastAPI endpoints: /api/caducean/state, /direction, /params
    Test: cargo check passes; curl endpoints return correct JSON.
    Landmark: tauri_caducean_proxy_wired

  [19.6] Phase 6 — Frontend: React hook + VoiceInterface integration + debug panel
    Status: ✓ DONE 2026-06-13 (commit ce6d8c48) — code complete; manual browser
    verification deferred (no Next.js dev server in this env; see
    app/PHASE_6_INTEGRATION_NOTES.md for wiring pattern)
    New: `app/hooks/useCaducean.ts`, `app/components/CaduceanDebugPanel.tsx`
    Mod: VoiceInterface is composed of multiple components in
    chat-view.tsx + chat/ subdirectory (not a single file); documented
    the wiring pattern in PHASE_6_INTEGRATION_NOTES.md
    What to build:
      a) useCaducean(sessionId, pollMs=500): useState + setInterval, calls invoke('caducean_get_state')
      b) VoiceInterface: consume hook; map target_u/force_magnitude to TTS chunk size and turn-taking
      c) CaduceanDebugPanel: dev-only floating panel with live state + u/ξ plot + a/b/s sliders
    Test: Manual — debug panel shows live values; sliders update C++ state (verify via /api/caducean/state)
    Landmark: frontend_caducean_hook_wired

  [19.7] Phase 7 — ConversationKernel (THIN WRAPPER, not a new system)
    Status: ✓ DONE 2026-06-13 (commit 7e2db98b)
    Built: `backend/agent/conversation_kernel.py` (~270 lines, no new state machines)
    Mod: `backend/iris_gateway.py` (3 minimal touches), `backend/main.py` (1 line)
    Result: 12/12 test_conversation_kernel.py tests pass via pytest.
    The 6 consolidation tests verify NO duplicate VAD/TTS/state machine
    (forbidden method names checked). The 6 behavioral tests verify
    VAD→Caducean action mapping (RECORDING→COMPRESS, IDLE→EXPAND),
    TTS chunk scaling by force_magnitude, barge-in damping, etc.
    Landmark: conversation_kernel_wired ✓
      with rational c_eff coupling — voice gets concise output during intense coding

---

## DOMAIN 20 — AGENT MULTI-STEP TOOL EXECUTION  ⚠️ CRITICAL BLOCKER
Date opened: 2026-07-01
Investigation: docs/architecture/agent-multi-step-gaps.md
Blocks: Domain 17 (Self-Coding Agent), Gate 1.8 verification, all long-horizon tasks.

**The problem:** The agent kernel can handle single tool calls via the DER loop but
cannot do dynamic multi-step tool execution. Five critical gaps prevent long-horizon tasks:
  1. No agentic tool-call loop (LLM→tool→LLM→tool→...→final response)
  2. Permission system disconnected (UI exists, no backend handler)
  3. MCP servers hardcoded at startup (no dynamic discovery)
  4. Voice-first mode caps to 1 step
  5. Planning trigger is keyword-based, not semantic

**Why now:** Domain 17 (Self-Coding Agent) requires multi-step tool execution:
  plan → edit_file → run_test → read_output → fix → rerun. Without D20,
  the agent can only do single-step responses. Gate 1.8 (tool calling with
  iris_local) also requires a working tool-call loop to verify.

**Priority:** Items [20.1]-[20.3] are hard blockers for D17. Items [20.4]-[20.7]
improve capability but are not blockers.

  [20.1] Agentic tool-call loop in streaming response path
    Status: NOT STARTED — CRITICAL BLOCKER
    What to build:
      Implement OpenAI-style tool_call processing in the streaming response:
      a) When LLM response contains tool_calls → execute tools via tool_bridge
      b) Feed tool results back to LLM as tool role messages
      c) Continue loop until LLM produces final text response (no tool_calls)
      d) Enforce max_iterations (default: 10) and token budget
      e) Stream tool execution status to frontend (tool_call_start, tool_call_result)
      f) Handle errors: tool failure → feed error back to LLM, let it decide next step
    Files to modify:
      backend/agent/streaming.py — add tool_call processing after text generation
      backend/agent/agent_kernel.py — wire tool-call loop into _respond_direct path
    Test: Agent receives "create a file hello.txt with content 'hello world' then read it back"
          → should execute file_write THEN file_read in sequence, showing both results
    Regression: All existing DER tests still pass (DER loop is separate path)
    Landmark: agentic_tool_call_loop

  [20.2] Wire permission backend handler for notification_response
    Status: NOT STARTED — HIGH PRIORITY
    What to build:
      a) Add handler for 'notification_response' WebSocket message in iris_gateway.py
      b) When agent requests permission (tool_call requiring approval):
         - Pause execution
         - Send notification_request to frontend
         - Wait for notification_response (allow/deny) with timeout (30s default)
         - On allow: execute tool. On deny: skip tool, inform LLM.
         - On timeout: auto-deny for destructive tools, auto-allow for read-only
      c) Wire to CapabilitySet: personal mode auto-approves read-only, denies write/execute
      d) Wire to tool_bridge: mark tools as require_approval=True in metadata
    Files to modify:
      backend/iris_gateway.py — add notification_response handler
      backend/agent/tool_bridge.py — add require_approval metadata to tools
      backend/capabilities.py — add per-tool approval logic
    Test: Agent attempts to delete a file → frontend shows Allow/Deny → deny → agent reports denied
    Regression: Existing WebSocket message handling unaffected
    Landmark: permission_backend_wired

  [20.3] Tool execution progress UI in chat-view
    Status: NOT STARTED — HIGH PRIORITY
    What to build:
      a) New WS events: tool_call_start {tool_name, args}, tool_call_result {tool_name, result, duration}
      b) chat-view.tsx: render tool calls as distinct UI blocks (collapsible)
      c) Show: tool icon, tool name, arguments (truncated), spinner while running, result on complete
      d) Show step counter when multiple tools: "Step 2/4: Running file_write..."
      e) Add abort button during tool execution (sends cancel to backend)
    Files to modify:
      backend/agent/agent_kernel.py — emit tool_call_start/result WS events
      components/chat-view.tsx — add ToolCallBlock component
    Test: Multi-step task shows tool execution blocks in chat with progress
    Regression: Existing chat rendering unaffected
    Landmark: tool_progress_ui

  [20.4] Semantic planning trigger (replace keyword matching)
    Status: NOT STARTED
    What to build:
      Replace `_needs_planning()` keyword matching with LLM-based intent classification:
      a) Small classifier call (max_tokens=20) that determines: needs_tool: bool, tool_type: str
      b) Cache results for repeated patterns (same user phrasing → same decision)
      c) Fallback to keyword matching if classifier fails
      d) OR: use a rule-based heuristic that's more comprehensive than current keywords
    Files to modify:
      backend/agent/agent_kernel.py — _needs_planning() method
    Test: "what files are in this directory" → triggers planning (currently doesn't)
          "hello" → doesn't trigger planning (currently doesn't)
    Regression: Existing planning triggers still work
    Landmark: semantic_planning_trigger

  [20.5] Remove voice-first 1-step cap (configurable)
    Status: NOT STARTED
    What to build:
      a) Make the 1-step cap configurable: voice_multi_step: bool in settings
      b) When enabled: voice tasks can use up to 3 steps (conservative)
      c) Add voice-specific UX: announce "I'll need to do a few things for this"
      d) Keep token budget at 15k for voice (tight but sufficient for 3 steps)
    Files to modify:
      backend/agent/agent_kernel.py — line 3478, voice-first cap
      backend/agent/config.py — add voice_multi_step setting
    Test: "search for files and summarize them" → agent does search + summarize (2 steps)
    Regression: Default behavior unchanged (cap stays on unless enabled)
    Landmark: voice_multi_step_configurable

  [20.6] MCP discovery API for agent
    Status: NOT STARTED
    What to build:
      a) Backend endpoint: /api/mcp/discover → list all available MCP servers
      b) Backend endpoint: /api/mcp/connect → dynamically connect a new MCP server
      c) Agent-callable tool: mcp_discover() → returns available servers + their tools
      d) Agent-callable tool: mcp_connect(server_name) → connects server, returns tools
      e) Integrate with marketplace: if MCP not available, suggest installing from marketplace
    Files to modify:
      backend/agent/tool_bridge.py — add discovery/connect methods
      backend/main.py — add /api/mcp/* endpoints
    Test: Agent is asked to use a tool not in current MCP → discovers available servers → connects
    Regression: Existing MCP servers still initialized at startup
    Landmark: mcp_discovery_api

  [20.7] Structured tool result display (expandable)
    Status: NOT STARTED
    What to build:
      a) Tool results rendered in collapsible <details> blocks
      b) Long results truncated with "Show more" (default: 500 chars)
      c) Syntax highlighting for code results
      d) Copy button for tool results
      e) Error results in red with stack trace expandable
    Files to modify:
      components/chat-view.tsx — enhance tool result rendering
    Test: Long file read result shows truncated with expandable full view
    Regression: Short results still render inline
    Landmark: structured_tool_display

  Graduate condition:
    [20.1]-[20.3] all pass: agent does multi-step task (write file + read back),
    permission dialog appears for destructive actions, progress shows in chat.
    Domain 17 can then be attempted.

---

SESSION START CHECKLIST
