# Agent Multi-Step Tool Execution — Architecture Overview

> Date: 2026-07-06
> Branch: `feat/agent-multi-step-tool-execution`
> Status: Design validated. Implementation plan in `docs/plans/2026-07-06-agent-multi-step-tool-execution.md`.
> Builds on: `docs/architecture/agent-multi-step-gaps.md`, `docs/DER_LOOP_MYCELIUM.md`, `docs/PACMAN.md`
> Foundation: Audio pipeline solidified (Domain 2 verified), DER loop operational, Mycelium memory active, Caducean engine wired.

---

## 1. Purpose

Make IRIS a true multi-step agent: the LLM dynamically calls tools mid-response, the agent speaks only appropriate feedback (not tool JSON), tasks execute in the background while the widget shows compact progress, and all state survives WebSocket disconnects without crashing.

This is the implementation that turns the gap analysis (`agent-multi-step-gaps.md`) into a shipped feature. Every gap in that doc is addressed here.

---

## 2. Design Decisions (locked)

These decisions were validated through brainstorming with the user. They are the contract for this branch.

| # | Decision | Choice |
|---|----------|--------|
| 1 | Branch scope | Full vision in one branch — all 12 gaps + widget resilience |
| 2 | Speech policy during tool use | Status phrases only — acknowledgment on start, milestone phrases per major step, final result. Tool args/JSON/reasoning are silent (UI only). |
| 3 | Context keying strategy | `conversation_id` only. `session_id` is a transport label. Context persists to disk, reattaches on WS reconnect. |
| 4 | Context window display | Compact pill in chat header: `12.4k / 128k` + thin progress bar. Color shifts green → amber → red. Phase indicator sits next to it. |
| 5 | Background task visual updates | Orb state change (working pulse, color shift) + small badge with step counter / notification count. Badge matches orb aesthetic (canvas particle style, brand color). No OS toast notifications. |
| 6 | DER + agentic loop relationship | DER absorbs agentic mode. New `agentic` task_class lets LLM emit `tool_calls` during Explorer phase. Reviewer stays. Mycelium ingestion per tool call. |
| 7 | Caducean governance | Caducean phase (EXPAND/COMPRESS) is the single source of truth for which kernel is active. ConversationKernel speaks only during EXPAND. TaskKernel works only during COMPRESS. |
| 8 | Tool approval model | Configurable tiered risk: read-only auto-execute; side-effect require approval; destructive require approval + confirmation. Personal vs developer mode distinction = app-source modification + OS system commands. Wired through existing permission UI. |
| 9 | WS disconnect resilience | All user settings + agent state persist. Disconnect is a first-class state, not an exception. On reconnect: reattach to same `conversation_id`, restore context from backend store, re-sync settings. |
| 10 | Task list UI | Agent-generated todo list, inline in chat stream as a structured card. Live updates as DER progresses. Collapsible. Matches orb aesthetic. |
| 11 | Voice 1-step cap | Configurable per task. Default multi-step. `quick` task_class caps to 1 step for fast exchanges. Caducean COMPRESS keeps voice tasks silent during work. |

---

## 3. Layer Architecture

Six layers, built bottom to top. Each layer depends only on the ones below it.

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 6 — Frontend Components                                    │
│   task-list card · context-window pill · orb badge               │
├─────────────────────────────────────────────────────────────────┤
│ Layer 5 — Permission System Wiring                               │
│   tiered risk classification · notification_response handler     │
│   personal/developer mode distinction                            │
├─────────────────────────────────────────────────────────────────┤
│ Layer 4 — DER Agentic Mode                                       │
│   agentic task_class · LLM emits tool_calls in Explorer phase    │
│   Reviewer stays · Mycelium ingestion per call · voice cap config│
├─────────────────────────────────────────────────────────────────┤
│ Layer 3 — Kernel Separation                                      │
│   EventBus · ConversationKernel (speech) · TaskKernel (tools)    │
│   Caducean phase governs which kernel is active                  │
├─────────────────────────────────────────────────────────────────┤
│ Layer 2 — Per-Thread Context + WS Resilience                     │
│   conversation_id keying · ConversationContextStore              │
│   disconnect first-class state · settings re-sync                │
├─────────────────────────────────────────────────────────────────┤
│ Layer 1 — Foundation (exists, solidified)                        │
│   audio pipeline · DER loop · Mycelium · Caducean · Tauri bridge │
└─────────────────────────────────────────────────────────────────┘
```

**Layer 1 is already solidified.** Audio pipeline (Domain 2 verified), DER loop, Mycelium memory, Caducean engine, Tauri bridge all exist and work. We build on top of them, not beside them.

---

## 4. Layer 2 — Per-Thread Context + WS Resilience (Gap 12)

### 4.1 Problem

The agent kernel stores conversation history keyed by `session_id` (the WebSocket connection's session — changes on every reconnect). When the user switches threads or the WS disconnects, context is lost or bleeds across threads.

### 4.2 Solution

**Context keying:** `conversation_id` becomes the sole key for agent context. `session_id` becomes a transport label used only for WS routing.

**New backend component:** `ConversationContextStore` (`backend/agent/conversation_context_store.py`)
- Persists per-thread context to disk (SQLite or JSON, keyed by `conversation_id`)
- On WS reconnect: `get_or_restore(conversation_id)` returns the stored context
- On thread switch: `save_current()` + `load(conversation_id)` swaps active context
- Bounded: max 50 conversations, 200 messages each (matches frontend limits)

**Frontend changes:**
- `voice_command_start` payload includes `conversation_id`
- New `switch_conversation` WS message when user selects a different thread
- `handleSelectConversation` sends `switch_conversation { conversation_id }` to backend

**Backend changes:**
- `voice_command_start` handler accepts `conversation_id`
- `AgentKernel.process_text_message()` keys context by `conversation_id` instead of `session_id`
- `clear_conversation()` already exists for `new_conversation` — extended for thread switch

**WS disconnect resilience:**
- Disconnect is a first-class state, not an exception
- Frontend keeps: brand color, voice mode, web toggle, conversation history (localStorage), active thread, context window token count
- On reconnect: WS reattaches to same `conversation_id`, agent kernel restores from `ConversationContextStore`, settings re-sync from frontend via a `settings_sync` message
- No errors thrown on disconnect — the UI shows a "reconnecting" state on the orb

### 4.3 Files Touched

| File | Change |
|------|--------|
| `backend/agent/conversation_context_store.py` | **New** — persistent per-thread context store |
| `backend/agent/agent_kernel.py` | Re-key context from `session_id` to `conversation_id` |
| `backend/iris_gateway.py` | `voice_command_start` accepts `conversation_id`; add `switch_conversation` handler; WS reconnect reattaches |
| `components/chat-view.tsx` | `handleSelectConversation` sends `switch_conversation`; `voice_command_start` includes `conversation_id` |
| `hooks/useIRISWebSocket.ts` | `voice_command_start` sends `{ conversation_id }`; add `switch_conversation` sender; handle reconnect state |

---

## 5. Layer 3 — Kernel Separation (Gap 6, un-deferred)

### 5.1 Problem

LLM output flows through a single path — `iris_gateway.py` `chunk_callback` sends everything to TTS. Tool calls, planning steps, and conversation text all compete for the same channel. The agent reads JSON tool arguments aloud.

### 5.2 Solution

**New component:** `EventBus` (`backend/agent/event_bus.py`)
- `IRISStreamEvent` dataclass: `type` (utterance / tool_call / tool_result / planning_step / status_phrase / phase_change), `payload`, `turn_id`, `conversation_id`
- `EventBus` class: `emit(event)`, `subscribe(event_type, handler)`
- Replaces direct `chunk_callback` → TTS path

**ConversationKernel** (extended, `backend/agent/conversation_kernel.py`):
- Emits `utterance` events → TTS subscribes
- Caducean-governed turn-taking (EXPAND = speak, COMPRESS = listen/work)
- Filler phrase selection during processing gaps
- Status phrase emission when TaskKernel completes a milestone
- **Filter:** tool-call JSON, planning steps, and intermediate reasoning never reach TTS

**TaskKernel** (new, `backend/agent/task_kernel.py`):
- Emits `tool_call` / `tool_result` / `planning_step` events → frontend subscribes
- Tool execution progress (step N of M)
- No audio output — never reaches TTS
- Emits `status_phrase` events to ConversationKernel when milestones hit (for EXPAND-phase speech)

**Caducean governance:**
- EXPAND (u → +1): ConversationKernel active — agent speaks, reports results
- COMPRESS (u → -1): TaskKernel active — agent works, executes tools silently
- Phase transition: when TaskKernel completes a milestone, ConversationKernel emits a status phrase (if in EXPAND)

**Voice state mapping (existing, preserved):**
- `RECORDING → COMPRESS` (user speaking, agent listens)
- `IDLE → EXPAND` (user finished, agent responds)
- `PROCESSING → COMPRESS` (agent thinking/working, TaskKernel active)
- `SUCCESS → EXPAND` (TTS playing, ConversationKernel active)

### 5.3 Files Touched

| File | Change |
|------|--------|
| `backend/agent/event_bus.py` | **New** — `IRISStreamEvent` + `EventBus` class |
| `backend/agent/conversation_kernel.py` | Extend with utterance emission, filter speech from task content |
| `backend/agent/task_kernel.py` | **New** — tool-call events, planning steps, progress, milestone status phrases |
| `backend/iris_gateway.py` | Route LLM output through EventBus → kernel separation |
| `backend/agent/tts.py` | Subscribe to utterance events only (no tool calls) |

---

## 6. Layer 4 — DER Agentic Mode (Gap 1)

### 6.1 Problem

The DER loop pre-plans all steps via `_plan_task()` before execution. The LLM cannot dynamically decide which tools to call based on intermediate results. Voice-first mode caps to 1 step.

### 6.2 Solution

**DER absorbs agentic mode.** The DER loop stays the canonical executor. A new `agentic` task_class (or a flag on the ExecutionPlan) lets the LLM emit `tool_calls` during the Explorer phase instead of pre-deciding all steps.

**How it works:**
1. `_plan_task()` returns a plan with `strategy = "agentic"` and a minimal step list (or a single "execute user intent" step)
2. DER loop enters Explorer phase
3. Explorer calls the LLM with tool definitions
4. LLM returns `tool_calls` in its response
5. System executes those tools, feeds results back to the LLM
6. Loop continues until LLM produces a final text response (no tool_calls)
7. Reviewer still runs on each tool call — can PASS/REFINE/VETO
8. Mycelium `ingest_tool_call()` fires per tool execution (same as today)
9. TrailingDirector gap-filling still runs

**Voice cap configurability:**
- Remove the hard 1-step cap at line 3478
- `task_class = "quick"` caps to 1 step (for fast exchanges)
- Default voice tasks can be multi-step
- Caducean COMPRESS phase keeps voice tasks silent during work

**Token budget:**
- `agentic` task_class: 50k token budget (matches "full")
- `quick` task_class: 15k token budget (matches current voice-first)
- Max iterations: 20 (configurable) — prevents infinite loops

**Semantic planning trigger (Gap 4 in root cause):**
- Replace keyword-based `_needs_planning()` with LLM-based intent classification
- A small classifier call (or a fast LLM inference) determines if tools are needed
- Falls back to keyword matching if classifier unavailable

### 6.3 Files Touched

| File | Change |
|------|--------|
| `backend/agent/agent_kernel.py` | Add `agentic` task_class; implement tool-call loop in Explorer; remove 1-step cap; semantic `_needs_planning()` |
| `backend/agent/der_loop.py` | `QueueItem` supports `agentic` flag; DirectorQueue handles dynamic step injection |
| `backend/agent/der_constants.py` | Add `DER_TOKEN_BUDGETS["agentic"]`, `MAX_AGENTIC_ITERATIONS` |
| `backend/agent/streaming.py` | Stream tool-call results through EventBus (not direct TTS) |

---

## 7. Layer 5 — Permission System Wiring (Gap 2)

### 7.1 Problem

`PermissionRequestSystem` exists in `backend/vision/permission_system.py` but is only wired for vision/GUI automation. `CapabilitySet` is binary personal/developer mode with no per-tool approval. Frontend `notification_response` is silently dropped — no backend handler.

### 7.2 Solution

**Tiered risk classification:**

| Tier | Examples | Behavior |
|------|----------|----------|
| Read-only | file read, web search, list dir | Auto-execute |
| Side-effect | file write, terminal command, git commit | Require approval |
| Destructive | delete, git push, system config change | Require approval + confirmation |

**Personal vs developer mode distinction:**
- Personal mode: auto-approve reads; deny writes to app source; deny OS system commands
- Developer mode: auto-approve reads + writes to app source; allow OS system commands (side-effect tier still requires approval; destructive requires approval + confirmation)

**Backend handler (the dead wire gets wired):**
- `notification_response` WS message → `PermissionRequestSystem.resolve(request_id, action)`
- Pauses tool execution until user approves/denies
- Timeout: auto-deny after 30s for non-critical tools, 60s for destructive
- Approval result fed back to DER loop via EventBus

**Configurable:**
- User can tune approval behavior in settings (per-tier override)
- Trust list: per-tool "always allow" toggle (persisted to settings)

### 7.3 Files Touched

| File | Change |
|------|--------|
| `backend/vision/permission_system.py` | Extend for general tool execution (not vision-only); add tiered risk |
| `backend/capabilities.py` | Add per-tool approval on top of personal/developer mode |
| `backend/iris_gateway.py` | Add `notification_response` handler |
| `backend/agent/tool_bridge.py` | Check permission tier before `execute_tool()`; pause on approval needed |
| `components/chat-view.tsx` | Permission UI already exists (line 1565-1584) — wire to real backend response |

---

## 8. Layer 6 — Frontend Components (Gaps 4, 7)

### 8.1 Task List Card (inline in chat)

**When:** The agent's plan has multiple steps (DER loop active).
**Where:** Inline in the chat stream, as a structured card (like a chat message but not a bubble).
**What it shows:**
- Plan title / objective
- Ordered list of steps, each with:
  - Description
  - Status: pending / working / done / skipped / vetoed
  - Tool name (if applicable)
  - Result preview (expandable)
- Live updates as DER loop progresses
- Collapsible (collapsed by default for long plans)
- Matches orb aesthetic: dark glass, brand-color accents, monospace step labels

**Data source:** Subscribes to `iris:task_update` CustomEvents from TaskKernel (via WS → `useIRISWebSocket`).

### 8.2 Context Window Pill (chat header)

**When:** Always visible when chat is open.
**Where:** Chat header, next to the phase indicator.
**What it shows:**
- Token usage: `12.4k / 128k`
- Thin progress bar underneath
- Color shifts: green (<60%) → amber (60-85%) → red (>85%)
- Phase indicator next to it: idle / listening / thinking / working / speaking

**Data source:** Backend reports token usage per turn via `iris:context_usage` WS event.

### 8.3 Orb Badge (background task indicator)

**When:** Only when wings are closed (orb-only view) AND agent is executing a background task.
**Where:** Small badge on the orb, positioned to match the orb's canvas particle aesthetic.
**What it shows:**
- Step counter: `2/5` or notification count
- Working pulse: orb canvas breathing shifts to a faster cadence
- Color shift: brand color brightens during work
- Clicking the orb opens wings to reveal full task list

**Aesthetic requirement:** Badge must match the orb's visual language — canvas particle style, brand color, no flat Material Design badges. Uses the same `glowColor` and particle rendering approach as `OrbCanvas`.

### 8.4 Files Touched

| File | Change |
|------|--------|
| `components/chat/TaskListCard.tsx` | **New** — inline task list card component |
| `components/chat/ContextPill.tsx` | **New** — context window + phase pill |
| `components/iris/OrbBadge.tsx` | **New** — orb badge matching canvas aesthetic |
| `components/chat-view.tsx` | Render TaskListCard in message stream; ContextPill in header; wire event listeners |
| `components/iris/XurOrb.tsx` | Render OrbBadge when working state active |
| `hooks/useIRISWebSocket.ts` | Forward `iris:task_update`, `iris:context_usage` as CustomEvents |
| `hooks/useUILayoutState.ts` | Expose working state for orb badge |

---

## 9. Data Flow — End to End

```
User speaks (or types) with conversation_id
    ↓
WS → IRISGateway (conversation_id in payload)
    ↓
AgentKernel.process_text_message(text, conversation_id)
    ↓
ConversationContextStore.get_or_restore(conversation_id)
    ↓
TaskClassifier → task_class = "agentic" | "quick" | "full"
    ↓
Mycelium.get_task_context_package() → ContextPackage
    ↓
_plan_task() → ExecutionPlan (strategy="agentic" for dynamic tool use)
    ↓
Caducean: phase → COMPRESS (TaskKernel active, ConversationKernel silent)
    ↓
DER Loop (agentic mode):
    ├─ Director: next_ready()
    ├─ Reviewer: PASS/REFINE/VETO (reads Mycelium + PiNs)
    ├─ Explorer: LLM emits tool_calls
    │   ├─ Permission check (tiered risk)
    │   │   └─ If approval needed: emit permission_request → wait
    │   ├─ Tool executes
    │   ├─ EventBus.emit(tool_call) → frontend: TaskListCard updates
    │   ├─ EventBus.emit(tool_result) → frontend: TaskListCard updates
    │   └─ Mycelium.ingest_tool_call()
    ├─ TrailingDirector: gap analysis
    └─ Loop until LLM produces final text (no tool_calls)
    ↓
Caducean: phase → EXPAND (ConversationKernel active)
    ↓
ConversationKernel emits utterance events:
    ├─ Status phrase: "Done. Here's what I found..."
    └─ Final result text
    ↓
TTS plays utterance (status phrases only, not tool JSON)
    ↓
Frontend: chat shows final text + TaskListCard (completed)
Frontend: orb badge clears, returns to idle
Frontend: context pill updates token count
    ↓
Mycelium: record_outcome → crystallize_landmark → clear_session → record_plan_stats
```

---

## 10. WS Disconnect Resilience — State Diagram

```
[Connected] ──disconnect──> [Disconnected]
     │                           │
     │                    frontend keeps:
     │                    - brand color, voice mode, web toggle
     │                    - conversation history (localStorage)
     │                    - active conversation_id
     │                    - context window token count
     │                    - orb position (Tauri window pos)
     │                           │
     │                    orb shows "reconnecting" state
     │                    no errors thrown
     │                           │
     │                    backend keeps:
     │                    - ConversationContextStore (disk)
     │                    - agent state per conversation_id
     │                    - in-flight task state (paused)
     │                           │
     │<────reconnect─────────────┘
     │
     frontend sends:
     - reconnect with conversation_id
     - settings_sync (brand color, voice mode, etc.)
     │
     backend:
     - ConversationContextStore.get_or_restore(conversation_id)
     - agent kernel reattaches to stored context
     - settings re-synced
     - in-flight task resumes (if Layer 2+ complete)
     │
[Connected] (state restored, no crash)
```

---

## 11. Relationship to Existing Architecture

| Existing System | How This Branch Extends It |
|-----------------|---------------------------|
| DER loop | Absorbs agentic mode — LLM emits tool_calls in Explorer phase |
| Mycelium memory | Unchanged — ingestion per tool call continues as today |
| Caducean engine | Becomes governor of kernel phase (EXPAND/COMPASS) |
| ConversationKernel | Extended — emits utterance events, filters task content |
| TaskKernel | New — tool-call events, planning steps, progress |
| EventBus | New — routes LLM output to correct kernel |
| PermissionRequestSystem | Extended — general tool execution, tiered risk |
| CapabilitySet | Extended — per-tool approval on top of personal/developer |
| PiN layer | Unchanged — Reviewer reads PiNs as today |
| Landmark bridges | Unchanged — cross-project transfer continues |
| Audio pipeline | Unchanged — solidified foundation |
| Tauri bridge | Unchanged — widget positioning, tray, shortcuts |

---

## 12. What This Branch Does NOT Change

- **SpecEngine** (`backend/agent/spec_engine.py`) — not built yet, out of scope
- **MCP dynamic discovery** (Gap 3) — deferred to a follow-up branch; the 8 hardcoded MCP servers remain
- **Mycelium schema** — no DB migration needed
- **Audio pipeline** — solidified, no changes
- **Tauri Rust layer** — no Rust changes (frontend-only for widget resilience)

---

## 13. Success Criteria

The branch is mergeable when:

1. **Per-thread context:** Switching between conversation threads restores correct agent context. WS disconnect + reconnect preserves all settings and agent state without errors.
2. **Kernel separation:** TTS never speaks tool-call JSON or planning steps. Only status phrases and final results reach TTS.
3. **Agentic tool loop:** LLM can dynamically call tools mid-response. Reviewer still runs. Mycelium ingestion fires per call.
4. **Permission system:** `notification_response` is handled. Tiered risk applies. Personal/developer mode distinction works.
5. **Task list UI:** Inline card shows live DER progress. Context pill shows token usage. Orb badge shows step counter when wings closed.
6. **Voice multi-step:** Voice tasks can be multi-step by default. `quick` mode caps to 1 step.
7. **Widget resilience:** Orb can be moved, wings opened/closed, WS disconnects — no crashes, no lost settings.

---

## 14. References

- Gap analysis: `docs/architecture/agent-multi-step-gaps.md`
- DER loop + Mycelium: `docs/DER_LOOP_MYCELIUM.md`
- Pacman context metabolism: `docs/PACMAN.md`
- Timing/sync pipeline: `docs/plans/timing-sync-pipeline-overlap.md`
- Implementation plan: `docs/plans/2026-07-06-agent-multi-step-tool-execution.md`
