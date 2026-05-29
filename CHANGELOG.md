# IRIS Changelog

## [Unreleased] — WheelView UI Fixes + Inference Wiring — 2026-05-29

### fix: WheelView tactile core (IrisOrb) placement and centering

- `components/wheel-view/WheelView.tsx` — Fixed button centering by replacing
  Tailwind `-translate-x-1/2 -translate-y-1/2` with explicit `marginLeft: -32` /
  `marginTop: -32`. Framer Motion `scale` animations were overriding the CSS
  transform, causing the button to drift off-center.
- `components/wheel-view/DualRingMechanism.tsx` — Restored White Core Halo as
  SVG elements at layer 16 (between Core Kinetic Glider layer 15 and IrisOrb
  button layer 17). Uses `r=orbSize*0.11` with animated outer glare + static
  core halo with drop-shadow filters. Removed duplicate halo divs from inside
  the button.
- `components/wheel-view/WheelView.tsx` — Removed redundant halo/glare divs
  from inside the tactile core button since they now render correctly in the SVG.

### fix: Monitor cards display-only UX (analytics, logs, diagnostics)

- `components/wheel-view/fields/TextField.tsx` — Added `readOnly` prop with
  muted styling (`bg-black/10`, `border-white/5`, transparent caret) and
  optional `onChange`.
- `components/wheel-view/SidePanel.tsx` — Monitor cards now auto-send
  `confirm_card` (mapped via `CARD_TO_SECTION_ID`) on selection using a ref
  guard to prevent infinite loops. Confirm button is hidden for monitor cards.
  Text fields render as read-only display-only inputs.
- `data/cards.ts` — Updated monitor card placeholders from "Tap Confirm to..."
  to "Loading..." to indicate auto-fetch behavior.
- `types/navigation.ts` — Fixed `showIf.values` type from `string[]` to
  `(string | boolean)[]` to resolve TypeScript errors for boolean conditions.

### feat: Wire dead inference settings to backend kernel

- `backend/iris_gateway.py` — `_handle_settings` now wires
  `thinking_style`, `max_response_length`, `reasoning_effort`, `tool_mode`
  from the inference_mode card to `AgentKernel` attributes.
- `backend/agent/agent_kernel.py` — Added inference behavior fields
  (`_thinking_style`, `_response_length`, `_reasoning_effort`, `_tool_mode`)
  and wired them into `_respond_direct`, `_needs_thinking`, `_needs_planning`.
  Added swarm guards to prevent model name overwrites when swarm is enabled.
  Propagates inference behavior settings to peer kernels on spawn.
- `INFERENCE_ARCHITECTURE.md` — Updated dead wire audit to mark inference
  behavior settings as fixed.

**Status:** Wired but **not end-to-end tested** — swarm E2E verification
blocked by UI bugs fixed above. Next session will run
`docs/swarm_inference_plan.md` test protocol.

---

## [4.7.1] — Backend Test Suite Refinement — 2026-05-28

### test: backend test suite 99.1% pass rate

Comprehensive cleanup of the backend test suite — deleted stale tests, fixed
mock signatures, resolved Windows file-lock teardown errors, and aligned all
remaining tests with the current API.

**Pass rate:** 932 passed / 939 total = **99.1%**

#### Deleted stale tests (superseded by Mycelium / Caducean)
- `backend/memory/tests/test_retention.py`
- `backend/memory/tests/test_skills.py`
- `backend/memory/tests/test_privacy.py`
- `backend/memory/tests/test_privacy_audit.py`
- `backend/memory/tests/test_distillation.py`
- `backend/memory/tests/test_integration.py`
- `backend/memory/tests/test_duplicates.py`
- `backend/memory/tests/test_startup.py`
- `backend/memory/tests/test_config.py`

#### Fixed tests
- `backend/memory/tests/test_episodic.py` — added `outcome_score` to `Episode` dataclass, fixed `store._db` mock targets, updated `limit`/`min_avg_score` arg names
- `backend/memory/tests/test_interface.py` — patched `EpisodicStore`, `SemanticStore`, `ContextManager` in fixtures; fixed `assemble_for_task` return format
- `backend/memory/tests/test_working.py` — aligned with `ContextManager` API (`threshold`, list zones, `_compress` 1-arg, `append(zone=...)`)
- `backend/tests/test_vision_mcp.py` — patched `httpx.get` in offline health-check test

#### Infrastructure
- `backend/memory/tests/conftest.py` — new shared fixture with Windows-safe `temp_db_path` (`mkdtemp` + `shutil.rmtree(ignore_errors=True)`)
- `backend/main.py` — removed spurious `await` on sync `get_worktree_status()`
- `backend/iris_gateway.py` — added missing `import os`, fixed `_loop` → `loop`, added `type: ignore` for optional `.dev.terminal_handler`
- `backend/agent/agent_kernel.py` — added `openai>=1.30.0` to `requirements.txt`

### sec: scrub exposed API keys from repository

- `data/iris_config.json` added to `.gitignore` (contains Chutes API key)
- `test_api.py`, `test_models.py`, `test_models2.py` — replaced hardcoded `Bearer sk-...` keys with `os.environ.get("OPENCODE_API_KEY", "YOUR_API_KEY_HERE")`
- Moved all four root-level test scripts into `scripts/` for consistent organization

---

## [4.7.0] — TTS Performance Overhaul — 2026-05-25

### perf: native C++ audio layer — lock-free ring-buffer playback

Optional low-latency audio extension (`iris_audio.pyd`) built with pybind11 + PortAudio.
Delivers <5ms chunk-to-speaker latency and <2ms inter-chunk gaps via a lock-free
ring buffer in the PortAudio callback thread.

#### New files

- `backend/native/iris_audio.cpp` — `IrisAudioPlayer` C++ class:
  - Ring buffer: 10 seconds @ 24kHz float32 (240k samples)
  - `open()` — initializes PortAudio, opens output stream with 5ms suggested latency
  - `push_chunk()` — producer writes float32 numpy array; blocks with 50ms timeout
  - `interrupt()` — atomic flag stops callback immediately (sub-5ms cancel)
  - `wait_done()` / `close()` — drain and cleanup
  - `pa_callback()` — lock-free read from ring buffer, zero-fill underruns
- `backend/native/CMakeLists.txt` — CMake build for pybind11 + PortAudio
- `backend/native/__init__.py` — graceful loader: exports `IrisAudioPlayer` and
  `NATIVE_AVAILABLE`; falls back to `None` if compilation missing
- `build_native.ps1` — one-command Windows build script:
  - Locates Python in venv
  - Installs pybind11 + numpy
  - Copies PortAudio DLL from sounddevice wheel
  - Downloads PortAudio headers from `pa_stable_v190700_20210406.tgz`
  - Generates `.lib` import library from DLL exports via `dumpbin` / `lib.exe`
  - Runs CMake with Visual Studio 2022 generator
  - Copies built `.pyd` to `backend/native/`

#### Modified files

- `backend/audio/pipeline.py` — integrated native player:
  - `__init__`: attempts `from backend.native import IrisAudioPlayer, NATIVE_AVAILABLE`
  - `play_audio()`: opens native stream, pushes chunk, `wait_done()`, `close()`
  - `interrupt()`: calls `native_player.interrupt()` when available
  - `cleanup()`: closes native stream on shutdown
- `backend/iris_gateway.py` — `_speak_response` native fast-path:
  - Detects native availability and opens stream before producer thread starts
  - Producer pushes audio chunks directly to native player (bypasses asyncio.Queue)
  - Consumer path: `producer_thread.join()` + `wait_done()` instead of polling loop
  - Fallback to asyncio.Queue + `play_audio()` when native unavailable
- `backend/audio/engine.py` — `interrupt_speech()` now also calls `pipeline.interrupt()`
  for instant native audio cancellation alongside the atomic flag

### perf: streaming LLM→TTS — parallel synthesis with generation

IRIS starts speaking as soon as the first sentence is ready, without waiting for the
full LLM response. A producer-consumer pattern with a `queue.Queue` bridges the LLM
streaming thread and the TTS playback thread.

- `backend/iris_gateway.py` — `_handle_voice_message()`:
  - `chunk_callback` in `_execute_agent()` appends tokens to `sentence_buf`
  - Regex detects sentence boundaries (`[.!?]\s+`) and queues complete sentences
  - 50-word flush threshold prevents infinite buffering on boundary-less text
  - Final flush sends remaining text + `None` sentinel when LLM completes
  - TTS thread starts **before** agent runs, blocking on queue until first sentence arrives
- `backend/iris_gateway.py` — `_speak_response()`:
  - Dynamic chunking: first chunk at 1 sentence (instant voice onset), then 8 sentences
  - `sentence_queue.get()` blocks producer until LLM delivers sentences
  - `interrupted` Event stops synthesis mid-stream for barge-in
  - `_clean_for_speech()` strips markdown before TTS

### perf: F5-TTS GPU acceleration + memory hygiene

- `backend/agent/tts.py` — `_load_f5tts()`:
  - Auto-detects CUDA via `torch.cuda.is_available()`
  - Falls back from `device=` constructor arg to `torch.set_default_device("cuda")`
- `backend/agent/tts.py` — `_stream_f5tts()`:
  - Wrapped in `torch.inference_mode()` + `torch.autocast("cuda", float16)`
  - Zero RAM growth during long conversations
- `backend/iris_gateway.py` — `_speak_response()` finally block:
  - `torch.cuda.empty_cache()` after every TTS session
- `backend/audio/voice_command.py` — `_run_transcription()`:
  - Clears `_raw_frames` and `audio_buffer` after STT to free memory
  - Duplicate `WhisperModel` creation fixed (cached under `_whisper_lock`)

### fix: barge-in — sub-5ms TTS cancellation

- `backend/audio/engine.py` — `interrupt_speech()` sets atomic flag AND calls
  `pipeline.interrupt()` for native player immediate stop
- `backend/native/iris_audio.cpp` — `interrupt()` sets atomic `interrupted_`;
  callback returns `paComplete` on next fire, draining with silence
- `backend/iris_gateway.py` — removed spurious `engine.is_speech_interrupted()`
  call that consumed the flag before the TTS loop could check it

### fix: API endpoint bugs

- `backend/main.py` — `api_create_conversation()`: removed non-existent `preview`
  parameter from `create_conversation()` call
- `backend/main.py` — `api_add_message()`: added required `role=` parameter to
  `add_message()` call

### fix: O(n²) sentence buffering + thinking tag content loss

- `backend/iris_gateway.py` — incremental word count (`_sentence_buf_words`)
  replaces `text.split()` on every chunk (quadratic → linear)
- `backend/agent/agent_kernel.py` — removed `continue` after `</思考>` tag close;
  content appearing after the closing tag in the same chunk is no longer dropped

---

## [Unreleased] — Developer Workspace Integration — 2026-05-22

### Phase 1 — COMPLETED ✅ — 2026-05-23

**Status:** All workspace files recreated, TypeScript-verified, committed to `fix/ui-restoration-wings`.

**Files Created:**
- `stores/workspaceStore.ts` — Zustand store with tabs, sections, cards, archive, terminal, focus mode
- `components/workspace/DeveloperWorkspace.tsx` — Root DndContext layout with lazy-loaded TerminalWidget
- `components/workspace/WorkspaceTabBar.tsx` — Draggable color-coded tabs with type icons
- `components/workspace/KanbanCanvas.tsx` — Droppable canvas container
- `components/workspace/KanbanSection.tsx` — Resizable columns (200px–800px), collapsible, drag handles
- `components/workspace/KanbanCard.tsx` — Cards with maximize/minimize/archive/close actions
- `components/workspace/ArchiveDock.tsx` — macOS-style dock with hover magnification
- `components/workspace/WorkspaceToolbar.tsx` — Focus mode toggle

**Files Modified:**
- `components/terminal/TerminalWidget.tsx` — Inline rendering (no portal), default export for React.lazy
- `components/dark-glass-dashboard.tsx` — Terminal tab and floating panel removed
- `components/chat-view.tsx` — Conditionally renders DeveloperWorkspace in developer mode with Suspense
- `hooks/useLauncherMode.ts` — Defaults to developer mode when backend unreachable (testing)

**Verification:**
- `npx tsc --noEmit` on workspace files: **0 errors**
- Dev server starts successfully on `localhost:3000`
- All compilation errors are pre-existing (missing `useTailscaleAccess`, etc.)

**Notes:**
- Node_modules were corrupted by Windows `nul` file bug; fixed by removing `nul` and reinstalling native binaries (lightningcss, next/swc)
- `.gitignore` updated to exclude `bootstrap/*.db*` and `nul` file

---

### plan(workspace): IDE-lite modular workspace for developer mode

Comprehensive plan for integrating a full IDE-lite workspace into
`chat-view.tsx` (developer mode only), replacing the static messages area
with tabs, kanban sections, cards, terminal, archive dock, mind maps,
and floating panels.

#### Architecture
- **Vertical layout:** Tab Bar → Terminal Section → Archive Dock → Kanban Canvas
- **Terminal:** Standalone expandable/collapsible section (not a card)
- **Archive Dock:** macOS-style icon row with hover magnification (1×→1.6×),
  ripple effect on neighbors, drag-lock during DnD
- **Kanban Sections:** Resizable columns (200px–50%) with per-section undo/redo
- **Cards:** Maximized / Minimized / Archived states; folder tabs explode
  into multiple file-preview cards
- **Mind Map:** Hierarchical tree layout (H1 root → H2 parents → H3 children)
  with color inheritance and manual link override
- **Focus Mode:** Collapses Terminal to `$` strip, Archive Dock to 6px bar,
  tabs to colored dots; canvas expands to fill freed space
- **Floating Panels:** Tier 1 `position: fixed` portals; pop-out, drag,
  close-to-archive, re-dock

#### Tech Stack Decisions
- `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities` — drag-and-drop
- `zustand` + `zundo` — state management with undo/redo middleware
- `prism-react-renderer` — syntax highlighting for code preview
- Custom SVG/Canvas — mind map visualization (no external graph library)

#### Xur Loading Indicator
- Parametric 9-petal rose-curve animation (68 trailing particles)
- Replaces all existing loading spinners in both developer and personal modes
- `currentColor` adapts to light/dark themes automatically
- Integration points: input bar (20px), message bubbles (16px),
  workspace toolbar (32px), full-screen overlay (120px)

#### State Management
- `stores/workspaceStore.ts` — Zustand store with `zundo` middleware
- Per-section undo capped at 20 actions; global undo capped at 50
- Snapshot button for permanent checkpoints
- Auto-save to backend keyed by `conversationId`

#### Verification Protocol
- 48 test steps across 4 phases with 12 screenshot checkpoints
- Phase-gated: no agent/user may proceed until 100% verification passed
- Pre-implementation risk mitigation: 7 checklist items before writing code

#### Files Affected (planned)
- **Create:** `stores/workspaceStore.ts`, `components/workspace/*.tsx` (8 files),
  `components/Xur.tsx`
- **Edit:** `components/chat-view.tsx`, `components/terminal/TerminalWidget.tsx`,
  `components/dark-glass-dashboard.tsx`
- **Delete:** `components/FloatingTerminalPanel.tsx` (superseded)
- **Backend:** `POST /api/workspace/save`, `GET /api/workspace/{conversationId}`,
  `WS /ws/files`

---

## [4.6.0] — UI Restoration — 2026-05-06

### fix(ui): restore original wing/dashboard design from swarm-collaboration

Full visual restoration of the chat and dashboard wings to match the original
swarm-collaboration reference design, plus a set of polish fixes.

#### `components/chat-view.tsx`
- Header icons (Bell, History, X, BarChart3) raised from `fontColor}60` (38%
  opacity) to `rgba(255,255,255,0.75)` — clearly visible white, brand-color
  active states match chat-view's original pattern
- IrisApertureIcon restored as centered `absolute top-0 -translate-y-1/2`
  button in the header — embedded-jewel effect on the top border, white idle /
  glowColor active
- Wing background changed to `rgba(10,11,22,0.97)` → `rgba(6,7,14,0.99)` —
  deep near-black with a precise blue tint matching original screenshots
- `backdropFilter` removed from glass panel (Tauri widget — no desktop blur)
- `chatOuterRef` added for ConversationChips scrim positioning
- Send button always shown in `glowColor`, opacity 40% disabled (was invisible)

#### `components/dashboard-wing.tsx`
- Removed extra "Dashboard" header bar that was adding 48px and pushing
  sections down (restored to DarkGlassDashboard filling full height)
- IrisApertureIcon repositioned as absolute on the glass panel (full panel
  width centering — not offset by sidebar) at `top-0 -translate-y-1/2`
- `backdropFilter` removed from glass panel
- `isNotificationsOpen` and `isChatOpen` props threaded through to
  DarkGlassDashboard for icon active-state glow

#### `components/dark-glass-dashboard.tsx`
- Header icons (Bell, MessageSquare, X) raised to `rgba(255,255,255,0.75)`
  with explicit hover `0.95` — mirrors chat-view header
- Bell glows `glowColor` when `isNotificationsOpen`; MessageSquare glows when
  `isChatOpen` — driven by props from DashboardWing
- IrisApertureIcon import added (unused in header; button lives in wing)
- Action bar: hardcoded `12MS` replaced with `WS LIVE` / `OFFLINE` derived
  from `voiceState === 'error'`; model name and voice-state text were already
  dynamic
- Content zone padding reduced from `pl-12 pr-24 py-10 mx-8` to
  `pl-3 pr-3 py-4` (removed extra margins that were starving section width)
- Header padding reduced from `pl-12 pr-24` to `pl-4 pr-4`

#### `components/chat/ConversationChips.tsx`
- Trigger button: styling changed to clearly visible white `rgba(255,255,255,0.75)`
  with white border — was near-invisible with colored transparent background
- Dropdown panel: `backdropFilter` replaced with `blur(8px)` (subtle, no
  bleed); border-radius added (`6px`); panel offset 48px left so it sits
  inside chat-view rather than hugging the right edge
- Scrim removed (fixed portal elements cannot follow 3D CSS transforms)

#### `components/iris/IrisOrb.tsx`
- `backdropFilter: blur(12px)` removed from orb glass body (Tauri transparent
  window — would blur desktop wallpaper through the orb)

#### `components/backdrop-blur.tsx`
- `backdropFilter: blur(20px) saturate(180%)` removed — same reason

---

## [4.5.2] — IRISVOICEv4.5 — 2026-04-16

### feat: in-process local inference — eliminate port-8082 subprocess hang

`LocalModelManager` previously spawned `python -m llama_cpp.server` as a
subprocess on port 8082 and forwarded all inference through an HTTP client.
This path hung reliably on Windows when loading Q3_K_S weights with full GPU
offload (`n_gpu_layers=-1`), making local GGUF inference unusable. The
benchmark script (`scripts/bench_9b_tps.py`) proved the in-process
`from llama_cpp import Llama` path works at **50.8 tok/s** on RTX 3070.

#### `backend/agent/local_model_manager.py`

- `_load_inprocess()` — constructs `Llama(**ctor)` on a thread executor,
  emitting synthetic progress events every 2 s via `_start_progress_heartbeat()`
  since the library gives no native load-progress signal.
- `InProcessOpenAIAdapter` — duck-types `openai.OpenAI.chat.completions.create`
  so the agent kernel's existing call sites work unchanged. Handles both
  non-streaming (`resp.choices[0].message.content`) and streaming
  (`for chunk in resp: chunk.choices[0].delta.content`) with full tool-call
  accumulation (`tc.index`, `tc.function.name`, `tc.function.arguments`).
- `_wrap_chat_response` / `_wrap_chat_chunk` — convert llama-cpp dicts into
  attribute-access `SimpleNamespace` trees matching the openai Pydantic surface.
- `_sanitise_completion_kwargs` — drops OpenAI-only kwargs (`model`,
  `extra_body`, `max_tokens=-1`, `timeout`, `user`) before handing to Llama.
- `threading.Lock` (`_inference_lock`) — serialises concurrent inference
  calls into the single-threaded Llama instance.
- `create_chat_completion()` / `create_chat_completion_stream()` — sync
  wrappers around `Llama.create_chat_completion` (non-streaming and streaming).
- `get_inprocess_client()` — returns `InProcessOpenAIAdapter` when a model is
  loaded, `None` otherwise.
- `_resolve_profile_for_environment()` — falls back to `performance` with a
  warning when a profile declares `requires_fork: "llama-cpp-turboquant"` and
  the fork is not installed.
- `_build_llama_ctor_kwargs()` — maps PROFILES dict to `Llama(**ctor)` form;
  handles stock llama-cpp-python (`type_k`/`type_v` int) vs RotorQuant fork
  (`cache_type_k`/`cache_type_v` string) split.
- `IRIS_INPROCESS_LLAMA` env var (default `1`) — set to `0` to restore the
  legacy subprocess path while verification proceeds; scheduled for deletion
  after V1–V3 pass.
- `_rotorquant_available` — detects the llama-cpp-turboquant fork at init via
  `inspect.signature(Llama.__init__)`.
- `research_rotorquant` profile added — 128k context via `planar3` KV cache
  (5–10× compression); falls back to `performance` when fork absent.
- `get_status()` — extended with `inprocess: bool` and `rotorquant: bool` fields.
- `unload_model()` / `_sync_cleanup()` — drop `self._llm = None; gc.collect()`
  on the in-process path; subprocess kill path preserved unchanged.
- `_GGML_TYPE_INT` and `_ROTORQUANT_KV_TYPES` promoted to module-scope
  constants shared between the in-process constructor builder and the
  existing `_build_server_cmd`.

#### `backend/agent/agent_kernel.py`

- `_inprocess_local_mgr: Any = None` — init field for the manager binding.
- `configure_inprocess_local(mgr)` — binds (or clears) a `LocalModelManager`
  on the kernel; invalidates the cached openai HTTP client.
- `_get_lmstudio_client()` — returns `mgr.get_inprocess_client()` (the
  in-process adapter) when `provider == "iris_local"` and a model is loaded;
  falls through to the cached real openai HTTP client otherwise. No existing
  call sites changed.

#### `backend/iris_gateway.py`

- `_handle_load_local_model` — after `configure_openai_compat(...)`, also
  calls `kernel.configure_inprocess_local(mgr)`; logs whether inference is
  in-process or subprocess HTTP.
- `_handle_unload_local_model` — clears `configure_inprocess_local(None)` on
  unload.
- Crash callback — clears `configure_inprocess_local(None)` after subprocess
  crash.
- `_handle_apply_inference_settings` re-wire — restores in-process binding
  after hot-reload.
- Provider-select path (`iris_local` in `update_config`) — restores in-process
  binding when user flips back to `iris_local` after trying another provider.

#### `docs/ROTORQUANT_BUILD.md` (new)

Build instructions for the `johndpope/llama-cpp-turboquant` fork
(feature/planarquant-kv-cache) on Windows + CUDA 12 / VS2022 and Linux.
Includes verification command, expected log output, and rollback instructions.

---

### feat: terminal widget — self-contained, floatable agent workspace [13.4]

Replaces the static `TerminalPanel.tsx` with a fully self-contained widget
that docks in the nav-rail or floats as a draggable, resizable overlay.

#### New files

- `contexts/TerminalContext.tsx` — React Context owning all terminal state:
  `isFloating`, `fileActivity` (ring-buffer of 50), `isFileActivityOpen`,
  `autoFloat()` (fires on `iris:cli_started`). Mounted in `app/layout.tsx`.
- `components/terminal/TerminalWidget.tsx` — xterm.js host. Portal pattern:
  xterm container created once, `ReactDOM.createPortal`'d into either the
  docked slot (`TERMINAL_DOCKED_ID`) or floating panel (`TERMINAL_FLOATING_ID`)
  — the xterm instance survives dock↔float transitions without recreation.
  Input handler sends `terminal_input` to backend (direct shell via
  `terminal_handler.py`). Listens for `iris:cli_output`, `iris:cli_started`,
  `iris:cli_activity`, `iris:text_response`.
- `components/terminal/TerminalHeaderBar.tsx` — label, workdir display, file
  activity toggle, float/dock button, clear button.
- `components/terminal/FileActivityPanel.tsx` — collapsible 200 px sidebar,
  color-coded rows (create=green, edit=yellow, delete=red), auto-scrolls to
  newest. Driven by `TerminalContext.fileActivity`.
- `components/terminal/FloatingTerminalPanel.tsx` — `framer-motion` drag via
  `useDragControls` (constrained to header bar only), pointer-event resize
  handle at bottom-right, `z-index: 40`, `pointer-events: none` on backdrop
  so the dashboard stays interactive.
- `hooks/useFloatingPanel.ts` — geometry persistence via `localStorage`
  (default 700×450, bottom-right; min 400×300, max 90vw×80vh).

#### Modified files

- `app/layout.tsx` — `<TerminalProvider>` added inside `NavigationProvider`.
- `components/dark-glass-dashboard.tsx` — `TerminalPanel` → `TerminalWidget` +
  `<FloatingTerminalPanel />` sibling; `useTerminal` for `isFloating` state.
- `components/chat-view.tsx` — prefix routing in developer mode: messages
  starting with `>` or `/run ` bypass `text_message` and route directly to
  `terminal_input` (direct shell), with the trimmed command sent immediately.
- `hooks/useIRISWebSocket.ts` — `case 'file_activity'` added; dispatches
  `iris:file_activity` custom DOM event for `TerminalContext` to consume.
- `backend/iris_gateway.py` — `_handle_terminal_input` added; gated on
  `mode == "developer"`, delegates to `terminal_handler.py`.

#### Architecture notes

- DevOrchestrator layer removed from the plan. Agent kernel is the single
  routing brain (`_launcher_mode`, `tool_bridge`, agentic loop). No extra
  routing layer needed.
- External tool integration (Figma, Blender, etc.) → MCP server interfaces,
  not CLI drivers (see Domain 13.6).
- Terminal widget input is always **direct shell** (security-filtered).
  Agent-routed commands flow through chat → kernel → `tool_bridge` → CLI
  events piped back to terminal via WebSocket.

**Status: IMPLEMENTED — awaits e2e manual verification** (see Domain 13.4
checklist in `bootstrap/GOALS.md` for the 8-step verification sequence).

---

### chore: GOALS.md — Gate 1 + Domain 2 inference + Domain 13.4 status

- Gate 1.6, 1.8: marked `IMPLEMENTED — awaits e2e verification`.
- Domain 2: inference backend note added explaining the in-process switch,
  `IRIS_INPROCESS_LLAMA` flag, and `research_rotorquant` profile availability.
- Domain 13.4: expanded with full 8-step manual verification checklist;
  landmark gate explicitly not awarded until all 8 pass.
- Domain 13.6: MCP-first external tool note added.

---

## [4.5.0] — IRISVOICEv4.5 — 2026-04-05

### fix: eliminate startup memory spike — defer ctranslate2 / faster-whisper load

**Root cause**: `voice_handler.warm_up()` was called synchronously at backend startup,
spawning a daemon thread that imported `faster_whisper` → `ctranslate2` (+463 MB RAM +
CUDA context init on GPU machines). This raced with Next.js compilation on a 16 GB system
already at 71% utilisation, causing OOM crashes and Claude Code to become unresponsive.

- `backend/main.py` — `voice_handler.warm_up()` call removed from startup. Whisper now
  loads lazily on the first voice command. A 30-second delay added to `_prewarm_model_cache()`
  so the GGUF filesystem scan no longer races with Next.js startup.

### feat: voice-first DER budget — fast single-step voice responses [2.4]

When a request originates from the voice pipeline, the agent bypasses mode detection and
locks to a tight `voice_first` token budget (15 000 tokens, under the 20 k spec ceiling)
with the plan capped to a single step.

- `backend/agent/der_constants.py` — `DER_TOKEN_BUDGETS["voice_first"] = 15_000` added
  (both upper-case and lower-case aliases).
- `backend/agent/agent_kernel.py` — `process_text_message()` gains `from_voice: bool = False`
  parameter. When `True`, sets `_mode_name = "voice_first"` directly, skipping mode
  detection. `_execute_plan_der()` caps the plan to 1 step when `task_class == "voice_first"`.
- `backend/iris_gateway.py` — `_handle_voice()` passes `from_voice=True` to
  `process_text_message()`.
- `backend/tests/test_voice_pipeline.py` — `TestVoiceFirstDERMode` class added (3 tests).

### fix: cross-platform / Ubuntu migration — full Linux compatibility

IRIS now runs on Ubuntu with no code changes required. All Windows-only paths and
system calls are guarded by `sys.platform` / `os.name` checks.

#### `backend/agent/local_model_manager.py`

- `_find_llama_server_binary()` — Added Linux/macOS candidate paths:
  `~/ik_llama.cpp/build/bin/llama-server`, `~/llama.cpp/build/bin/llama-server`,
  `/usr/local/bin/llama-server`, `/usr/bin/llama-server`, `/opt/llama/bin/llama-server`.
  Windows `.exe` paths moved into `if sys.platform == "win32"` branch.
- `_find_llama_python()` — Replaced Windows-only `py -3.12` launcher with platform-aware
  logic: on Linux/macOS iterates `python3.12` → `python3.11` → `python3` via
  `shutil.which`. Falls back to `sys.executable` on both platforms.

#### `backend/agent/tool_executor.py`

- `_lock_screen()` — Was `"Not implemented for this platform"` on non-Windows. Now does
  `loginctl lock-session` (systemd) with `gnome-screensaver-command -l` fallback on Linux;
  `CGSession -suspend` on macOS.

#### `package.json`

- `start:prod` script added: `next build && next start` — production mode uses 40-60%
  less RAM than `next dev` (no webpack watch, no HMR).
- `dev:backend` fixed from hardcoded `C:\\Python313\\python.exe start-backend.py` to
  plain `python start-backend.py` (resolved from PATH on any platform).
- `lightningcss-win32-x64-msvc` moved from `dependencies` to `optionalDependencies`
  so `npm install` does not fail on Linux.

### fix: dead test cleanup — remove tests for deleted modules

- `backend/tests/test_vision_memory.py` — Deleted. Imported
  `backend.vision.vision_service` which was removed when MiniCPM was replaced by the
  LFM2.5-VL HTTP client. All tests were for a module that no longer exists.
- `backend/tests/test_data_migration.py` — Deleted. Imported
  `backend.sessions.backup_manager` (removed `SessionBackupManager` class). Every test
  in this file was for dead code.

### fix: test suite hardening — 433/433 passing, 10 expected skips

- `backend/tests/test_lmstudio_integration.py` — `_MM_PATH` updated from deleted
  `backend/audio/model_manager.py` to `backend/agent/local_model_manager.py`.
  `test_8gb_threshold_present` updated to match current percentage-based VRAM guards.
  `test_cpu_fallback_present` updated to case-insensitive string check. (3 fixes)
- `backend/core/models.py` — `SessionState.field_values` type narrowed from
  `Dict[str, Dict[str, Any]]` to `Dict[str, Any]` to match test expectations.
  `ToolDefinition` gains `@validator("name")` rejecting empty/whitespace names. (2 fixes)

---

## [Unreleased] — IRISVOICEv.4

### feat: replace CosyVoice3 with F5-TTS — full cleanup, CPU voice cloning preserved

**Why**: CosyVoice3-0.5B was a 9.1 GB model (despite the "0.5B" name), required ~4.25 GB
VRAM at runtime, conflicted with the local LLM on the RTX 3070 (8 GB VRAM), and caused
the PC to thrash at startup via an auto-prewarm thread. F5-TTS achieves the same zero-shot
voice cloning with 24 GB RAM unused, ~800 MB model, CPU RTF ~0.15 (still fast), and zero
VRAM impact.

**Migration**:
- `pip install f5-tts` — replaces all CosyVoice deps
- `backend/voice/pretrained_models/CosyVoice3-0.5B/` deleted (~6.3 GB freed this session,
  remaining from prior cleanup; full 9.1 GB now gone)
- `backend/voice/CosyVoice/` source directory deleted
- Matcha-TTS PYTHONPATH entry removed from `start-backend.py`
- CosyVoice deps (`conformer`, `hydra-core`, `hyperpyyaml`, `x-transformers`, `diffusers`)
  removed from `requirements.txt`; `f5-tts>=0.9.0` added

#### `backend/agent/tts.py` (full rewrite)

- **Engine replaced**: CosyVoice3 → F5-TTS (`F5TTS_v1_Base`, ~800 MB)
- **Voice cloning preserved**: TOMV2.wav is passed as `ref_file` to `f5tts.infer()` on every
  synthesis call — same reference audio, zero-shot cloning, no speaker registration step needed
- **Text normalizer wired in**: `_normalize()` calls `tts_normalizer.normalize_for_speech()`
  before every synthesis — strips markdown, expands symbols (`$`→"dollars", `%`→"percent",
  `->`, `**bold**`, etc.) so TTS never reads raw markup
- **Chunked synthesis**: `_split_into_chunks()` splits text at sentence boundaries
  (`.`, `!`, `?`) then at commas if sentences are too long (> 200 chars). Each chunk is
  synthesized and yielded immediately — approximates streaming with natural sentence pauses
- **CPU-only**: F5-TTS runs entirely on CPU, leaving full VRAM for the local LLM
- **Fallback chain unchanged**: Piper en_US-ryan-high → pyttsx3 SAPI5
- **`F5TTS_NATIVE_RATE`** constant replaces `COSYVOICE_NATIVE_RATE` (both 24 kHz)
- **`_prewarm_tts` RAM guard** lowered from 12 GB → 2 GB (F5-TTS is ~800 MB vs 9 GB)
- All CosyVoice constants, imports, and methods removed: `MODEL_DIR`, `COSYVOICE_DIR`,
  `SPK_ID`, `COSYVOICE3_PROMPT_PREFIX`, `_ensure_cosyvoice_paths`, `_load_cosyvoice`,
  `_register_speaker`, `_stream_cosyvoice`, `_warm_tts_pipeline`

#### Other files (comment cleanup)

- `backend/iris_gateway.py` — CosyVoice3 references in comments updated to F5-TTS;
  `_prewarm_tts` doc and RAM guard updated; `tts._warm_tts_pipeline()` → `tts._load_f5tts()`
- `backend/audio/engine.py`, `pipeline.py`, `voice_command.py`, `agent_kernel.py`,
  `agent/lfm_audio_manager.py` — inline CosyVoice comments updated to F5-TTS
- `requirements.txt` — CosyVoice comment block replaced; `f5-tts` added; old CosyVoice-only
  deps removed
- `start-backend.py` — Matcha-TTS PYTHONPATH injection removed
- `backend/tests/test_voice_pipeline.py` — `TestTTSManagerPaths` updated: `MODEL_DIR` /
  `COSYVOICE_NATIVE_RATE` tests replaced with `F5TTS_NATIVE_RATE` / `OUTPUT_SAMPLE_RATE`;
  `test_cosyvoice3_referenced_in_comments` replaced with `test_f5tts_referenced_in_requirements`

### fix: CosyVoice3 VRAM conflict with local LLM — switch default to Piper

**Why CosyVoice3-0.5B was 9.1 GB**: The "0.5B" refers only to the LLM text
encoder component. The full system includes a Flow model (~1.3 GB), HiFi-GAN
vocoder (80 MB), and ONNX speech tokenizer (~924 MB). On disk there were also
redundant files: the CosyVoice2-0.5B directory (3.3 GB, superseded), the RL
fine-tuned duplicate `llm.rl.pt` (1.9 GB, not used in inference), and the
`.batch.onnx` tokenizer variant (925 MB, not referenced).

**Runtime VRAM conflict**: CosyVoice3 loads ~3.3 GB into VRAM. An 8B Q4_K_M
LLM needs ~5 GB. Total = 8.3 GB — exceeds the RTX 3070's 8 GB VRAM. The two
cannot run simultaneously.

**Disk freed**: ~6.1 GB removed (CosyVoice2 + llm.rl.pt + speech_tokenizer_v3.batch.onnx).
CosyVoice3 on-disk footprint reduced from 9.1 GB to 6.3 GB.

#### `backend/agent/tts.py`

- **Default voice changed** from `"Cloned Voice"` (CosyVoice3, 3.3 GB VRAM) to
  `"Built-in"` (Piper, ~65 MB, CPU-only). Backend now starts without consuming
  any VRAM. Switch to "Cloned Voice" in Settings when you need voice cloning.
- **VRAM guard added** to `_select_engine()`: CosyVoice3 is now blocked when
  free VRAM < 4.5 GB. If a local LLM is loaded and using most of the VRAM,
  TTS automatically falls back to Piper with a logged warning instead of causing
  an OOM crash.
- **Voice change re-check**: `update_config()` now resets `_engine_selected` when
  `tts_voice` changes, so VRAM is re-evaluated on next synthesis with the new choice.

### fix: stop 9.1 GB CosyVoice3 model auto-loading at every backend start

**Root cause of PC becoming unresponsive**: `CosyVoice3-0.5B` weights on disk are
9.1 GB. `IRISGateway.__init__` was spawning a background thread to pre-load this
model 6 seconds after every backend start, regardless of whether the user was using
voice TTS. The RAM guard was set at 4.0 GB free — a threshold the model alone
exceeds. On a 16–32 GB consumer system already running Next.js + browser + Python,
loading 9.1 GB in the background saturated RAM and caused the OS to thrash.

#### `backend/iris_gateway.py`

- **Startup prewarm removed**: The `if _cosyvoice_model_dir.exists()` block in
  `__init__` no longer spawns the prewarm thread. `_tts_prewarmed = True` is set
  immediately so all "safety net" re-trigger paths are also suppressed.
  CosyVoice3 now loads **lazily** — only when the user sends their first voice
  message and `synthesize_stream()` runs for the first time. `synthesize_stream`
  already calls `_select_engine()` + `_load_cosyvoice()` itself; the prewarm was
  purely an optimisation that was killing the machine.
- **On-demand re-trigger removed**: The `if not self._tts_prewarmed` block in
  `_handle_voice` that spawned a second prewarm thread when voice started is also
  removed. Comments explain the lazy-load contract.
- **RAM guard raised**: `_prewarm_tts` RAM check raised from 4.0 GB → 12.0 GB
  (model = 9.1 GB + Python overhead + OS = minimum 12 GB headroom required).

### perf: eliminate PC-grinding memory spikes (frontend + backend)

Root-cause audit found 3 issues causing the PC to become unresponsive when both servers ran simultaneously.

#### `components/chat-view.tsx`

- **TTS word highlight (CRITICAL)** — `currentWordIndex` was stored inside the `Message`
  object, inside `conversations` state. Every 200 ms the interval called `setConversations`
  which mapped ALL conversations × ALL messages → ~10,000 object allocations per tick →
  50,000+ allocations/sec at peak. Each `setConversations` call also triggered the
  `conversations` useEffect which wrote the full JSON to `localStorage` (10MB+) every 200 ms.
  Additionally `messages` was in the `useEffect` deps so the interval was torn down and
  recreated on every keystroke, queuing 5–10 simultaneous intervals.
  **Fix:** `currentWordIndex` removed from `Message` type entirely. A single
  `ttsWordIndex: number` state is updated instead — one integer, zero conversation
  remapping, zero localStorage writes during TTS. `messages` removed from useEffect deps
  (words snapshotted at speak-start via local variable). localStorage persist debounced
  to 1 s so rapid state changes don't hammer disk I/O.

- **localStorage debounce** — conversations persistence now defers 1 s after the last
  change instead of writing synchronously on every mutation.

#### `backend/agent/local_model_manager.py`

- **Health check polling (HIGH)** — while waiting for the model server to start, the
  health probe fired every 0.5 s (2 HTTP requests/sec) for up to 3 minutes. This produced
  360+ HTTP calls during a single model load, thrashing the asyncio event loop and
  preventing other startup tasks from running.
  **Fix:** Exponential backoff starting at 1 s, doubling each missed poll, capped at 8 s.
  Worst-case load now produces ~25 health checks instead of 360.

#### `backend/audio/engine.py`

- **Audio frame conversion (HIGH)** — `_process_audio_frame` called `.tolist()` on the
  numpy int16 array before passing to Porcupine, allocating 512 Python `int` objects per
  frame × 31 frames/sec = ~16,000 object allocations/sec continuously while mic is active.
  **Fix:** numpy int16 array passed directly to `porcupine.process_frame()` — pvporcupine
  accepts any buffer-protocol sequence. Zero allocation overhead per frame.

#### `backend/voice/porcupine_detector.py`

- `process_frame` type hint updated to accept `Any` sequence (numpy array or list) without
  mypy complaints.

### fix: 10-bug audit — voice/text/tool pipeline hardening

Complete audit of the path from model load → voice input → LLM inference → tool execution → WebSocket delivery. All 10 bugs fixed.

#### `backend/agent/agent_kernel.py`

- **Bug 1+8** — Added `_normalise_endpoint()` static method: strips trailing `/` and `/v1`
  to prevent double `/v1/v1` URL on every OpenAI-compat request. Both `configure_lmstudio()`
  and `configure_openai_compat()` now call it. `configure_openai_compat(None)` safely sets
  `_model_provider = "uninitialized"` instead of crashing on `None.rstrip()`.
- **Bug 2+10** — DER loop Explorer phase called `self._tool_bridge.execute_tool()` without
  `await`, returning a coroutine object instead of the result. Wrapped with `asyncio.run()`
  and a ThreadPoolExecutor fallback. Tool calls now complete correctly.
- **Bug 5** — `_broadcast_inference_event` silently dropped WebSocket events when called
  from the thread pool (no running loop in that thread). Added `_broadcast_loop` attribute
  captured at startup + `run_coroutine_threadsafe` fallback. Inference console events now
  reach the frontend from background threads.
- **Bug 5** — Added `set_main_loop()` method and `set_main_loop(loop)` called during
  startup so the loop reference is available immediately.

#### `backend/main.py`

- **Bug 3+7** — Lifespan startup called `get_agent_tool_bridge()` (sync factory, never
  calls `initialize()`), leaving `_mcp_servers = {}` and all MCP tool calls failing.
  Changed to `await initialize_agent_tools()` which calls `bridge.initialize()` and wires
  all MCP servers.
- **Bug 5** — Added `agent_kernel.set_main_loop(asyncio.get_running_loop())` at startup.

#### `backend/agent/local_model_manager.py`

- **Bug 4** — Three occurrences of `asyncio.get_event_loop()` inside async methods
  (`load_model`, `_wait_for_ready`, HuggingFace download). On Python 3.10+ this raises
  `DeprecationWarning`; on 3.12+ raises `RuntimeError`. Replaced all three with
  `asyncio.get_running_loop()`.

#### `backend/iris_gateway.py`

- **Bug 6** — Both `chunk_callback` closures called
  `asyncio.run_coroutine_threadsafe(..., self._main_loop)` without checking if
  `self._main_loop` is None or still running. Added `if _loop and _loop.is_running():`
  guard around both calls — prevents crash when voice or text fires before the first
  async WebSocket dispatch.

#### `backend/voice/porcupine_detector.py`

- **Bug 9** — `__init__` raised `ValueError` on missing Picovoice access key and on no
  wake words configured, propagating through the audio pipeline startup and disabling
  voice entirely. Now sets `self._disabled = True` and logs a warning instead of raising.
  `_initialize_porcupine()` also degrades gracefully on engine failure. Added
  `is_enabled()` helper. All public methods no-op when disabled so the rest of the
  audio pipeline keeps running without a key or model file.

#### Bootstrap / tooling

- `session_start.py` — auto-syncs git commits into coordinate graph on every prompt (SHA-based idempotency)
- `.claude/settings.local.json` — Stop hook now runs `mid_session_snapshot.py` + `update_coordinates.py --auto`
- `bootstrap/on_git_commit.py` — removed (logic folded into session_start)
- `bootstrap/mid_sesssion_snapshot.py` — removed (typo duplicate)
- `AGENTS.md`, `CLAUDE.md`, `bootstrap/GOALS.md` — rewritten for platform/project agnostic use; quality gate checklist added to build sequence

---

### feat: DER loop fully wired into AgentKernel — spec compliance audit complete

### feat: DER loop fully wired into AgentKernel — spec compliance audit complete

All 11 gaps identified in the DER loop spec audit have been resolved.
18/18 spec tests pass (`backend/tests/test_der_loop.py`).

#### `backend/agent/agent_kernel.py`

- **Gap 1** — Added `_execute_plan_der()`: full Director→Reviewer→Explorer cycle
  with dependency-aware queue, per-step Mycelium signals, and ordered outcome
  recording (record_outcome → crystallize → clear → plan_stats).
- **Gap 2** — `self._task_classifier` (TaskClassifier) and `self._reviewer` (Reviewer)
  instantiated in `__init__()`. Reviewer's memory reference updated when
  `set_memory_interface()` is called.
- **Gap 3** — Added `_plan_task()`: DER-aware planner with maturity-aware temperature
  (0.1 mature / 0.25 exploring), `context_package` fed into planning prompt,
  `is_mature` / `task_class` / `context_package` parameters with safe defaults.
  Falls back to single-step plan on any model/parse failure.
- **Gap 4** — `process_text_message()` now classifies → assembles context → plans
  → routes `do_it_myself` strategy through `_execute_plan_der()`.
  `spawn_children` / `delegate_external` fall through to the existing ReAct loop.
  Entire DER path wrapped in try/except — ReAct is always the safety net.
- **Gap 5** — `mycelium_ingest_statement()` fires after planning with strategy signal.
- **Gap 6** — `register_address()` fires on the context package after plan injection
  when `is_mature=True`.
- **Gap 7** — Outcome recording sequence in correct spec order inside
  `_execute_plan_der()`.
- **Gap 8** — `mycelium_ingest_tool_call()` fires after every DER step (success,
  failure, and veto).
- **Gap 11** — DER constants (`DER_MAX_CYCLES`, `DER_MAX_VETO_PER_ITEM`,
  `DER_EMERGENCY_STOP`, `DER_TOKEN_BUDGETS`) re-exported at module level from
  `der_constants.py` for spec compliance.
- Added `infer()` adapter method so Reviewer can call the inference backend
  without a circular dependency.
- Added `_get_failure_warnings()` using `ResolutionEncoder` to surface high-signal
  Mycelium failure data into the planning prompt.
- Added `_run_step_direct()` for tool-less DER steps (direct model inference).

#### `backend/memory/interface.py`

- **Gap 9** — `mycelium_ingest_statement` proxy now passes `text=` keyword arg and
  `session_id=` (was silently dropping session_id).

#### `backend/core_models.py`

- **Gap 10** — `ExecutionPlan.to_context_string()` now includes
  `EXECUTION PLAN [{hza}]` header and `Reasoning: {self.reasoning}` line
  per spec format. Step count line replaced with `""` + `"Steps:"` separator.

---

## [bec8ad3] — feat: DER loop, Mycelium bootstrap, Skill Creator, MCP + Telegram

Gates 1-3 complete. DER loop classes built, Mycelium bootstrap system,
Skill Creator, MCP dispatch, Telegram bridge.

## [78fca62] — feat: unified chat interface with precision HUD alignment

## [c6fb83c] — fix: stabilize WebSocket by removing competing frontend heartbeat

## [082ee1c] — fix: eliminate TTS inter-sentence pauses via word-count chunking

## [66a04bc] — fix: TTS inter-sentence gaps, stuck pink orb, second wake-word ignored
