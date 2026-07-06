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
| 6 | DER + agentic loop relationship | DER absorbs agentic mode. The **Director** dynamically decides and adjusts the execution mode during the loop — not a hardcoded upfront classification. LLM emits `tool_calls` during Explorer phase when mode allows. Reviewer stays. Mycelium ingestion per tool call. |
| 7 | Caducean governance | Caducean phase (EXPAND/COMPRESS) is the single source of truth for which kernel is active. ConversationKernel speaks only during EXPAND. TaskKernel works only during COMPRESS. |
| 8 | Tool approval model | Configurable tiered risk: read-only auto-execute; side-effect require approval; destructive require approval + confirmation. Personal vs developer mode distinction = app-source modification + OS system commands. Wired through existing permission UI. |
| 9 | WS disconnect resilience | All user settings + agent state persist. Disconnect is a first-class state, not an exception. On reconnect: reattach to same `conversation_id`, restore context from backend store, re-sync settings. |
| 10 | Task list UI | Agent-generated todo list, inline in chat stream as a structured card. Live updates as DER progresses. Collapsible. Matches orb aesthetic. |
| 11 | Voice 1-step cap | Configurable per task. The Director decides mode dynamically — can start in `quick` (1-step) and escalate to `agentic`/`full` if intermediate results demand it. Default allows multi-step. Caducean COMPRESS keeps voice tasks silent during work. |
| 12 | AskUserQuestion tool | New agent tool that renders multiple-choice questions in chat-view. The agent calls it when it needs user input mid-task (clarification, choice between approaches, confirmation). User answers by clicking or voice. Answer feeds back as the tool result to the DER loop. Works whether chat-view is open or closed (orb shows a question badge). |
| 13 | Voice smart filler comments | When voice command is open (listening/processing) and there's a silence gap during COMPRESS, ConversationKernel emits context-aware filler phrases ("Let me check that...", "Searching now...") so the user knows the agent is still working. Timer-based: if no utterance for N seconds during COMPRESS, emit a filler. |
| 14 | Agent-initiated speech | The agent can open the audio pipeline itself to speak, even when chat-view isn't open. TTS becomes subscribable independent of the voice command flow. Used for: background task completion, AskUserQuestion prompts, status updates when chat-view is closed. The agent emits an utterance event → ConversationKernel → TTS, regardless of chat-view state. |

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
│   Director decides mode dynamically · LLM emits tool_calls        │
│   when agentic · Reviewer stays · Mycelium per call · voice config│
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

The DER loop pre-plans all steps via `_plan_task()` before execution. The LLM cannot dynamically decide which tools to call based on intermediate results. Voice-first mode caps to 1 step. The mode is hardcoded upfront by `TaskClassifier` — there is no way to escalate or de-escalate mid-execution when intermediate results reveal the task is simpler or more complex than initially assessed.

### 6.2 Solution

**DER absorbs agentic mode.** The DER loop stays the canonical executor. **The Director dynamically decides and adjusts the execution mode during the loop** — it is not a hardcoded upfront classification. The Director can start a task in `quick` mode (single LLM call, no tools) and escalate to `agentic` (dynamic tool_calls) or `full` (pre-planned multi-step) when intermediate results demand it. It can also de-escalate when a task turns out simpler than expected.

**Three execution modes the Director can choose between:**

| Mode | When Director picks it | Behavior | Token budget | Iteration cap |
|------|------------------------|----------|--------------|---------------|
| `quick` | Task looks simple — single LLM call suffices | 1 step, no tools, direct response | 15k | 1 |
| `agentic` | Task needs dynamic tool selection — LLM decides tools mid-response | LLM emits `tool_calls` in Explorer phase, loop until final text | 50k | 20 |
| `full` | Task needs pre-planned multi-step execution — DER classic | `_plan_task()` returns step list, Director/Reviewer/Explorer cycle | 50k | 40 cycles |

**How the Director decides mode:**

1. **Initial assessment** (before first Explorer call): Director reads the task, the ContextPackage from Mycelium, and the task classification hint (from `TaskClassifier` — still runs for Mycelium space routing, but its `task_class` is a **hint**, not a lock). Director picks initial mode.
2. **Mid-loop escalation**: After each Explorer result, Director re-evaluates. If the result reveals the task needs tools the current mode doesn't allow, Director escalates: `quick → agentic → full`. Escalation injects new steps into the `DirectorQueue`.
3. **Mid-loop de-escalation**: If a `full` plan's remaining steps turn out to be trivial after an intermediate result, Director can collapse them into a single `quick` step.
4. **Mode change is logged** to Mycelium via `ingest_statement()` — the graph learns which tasks needed escalation, improving future initial assessments.

**Agentic mode flow (when Director selects `agentic`):**
1. Director sets mode = `agentic` on the queue
2. Explorer calls the LLM with tool definitions
3. LLM returns `tool_calls` in its response
4. System executes those tools, feeds results back to the LLM
5. Loop continues until LLM produces a final text response (no `tool_calls`)
6. Reviewer still runs on each tool call — can PASS/REFINE/VETO
7. Mycelium `ingest_tool_call()` fires per tool execution (same as today)
8. TrailingDirector gap-filling still runs
9. Director re-evaluates mode after each iteration — can escalate to `full` if the LLM keeps needing more tools than the iteration cap allows

**Voice cap — removed, Director decides:**
- Remove the hard 1-step cap at line 3478
- The Director decides whether a voice task is `quick` (1 step) or needs more
- A user-configurable "voice preference" setting hints the Director: `quick_first` (try quick, escalate if needed) or `multi_step` (default to agentic)
- Caducean COMPRESS phase keeps voice tasks silent during work regardless of mode

**Token budget — dynamic, set by mode:**
- `quick`: 15k token budget
- `agentic`: 50k token budget
- `full`: 50k token budget (existing)
- Max iterations: 20 for `agentic`, 40 cycles for `full` (configurable) — prevents infinite loops
- Director can request a budget extension from Mycelium if a high-value task is approaching the cap (rare, logged)

**Semantic planning trigger (Gap 4 in root cause):**
- Replace keyword-based `_needs_planning()` with LLM-based intent classification
- A small classifier call (or a fast LLM inference) provides a **hint** to the Director about whether tools are likely needed
- The Director uses this hint as one input among many — not a lock
- Falls back to keyword matching if classifier unavailable

### 6.3 Files Touched

| File | Change |
|------|--------|
| `backend/agent/agent_kernel.py` | Director decides mode dynamically; implement tool-call loop in Explorer when mode=agentic; remove 1-step cap; semantic `_needs_planning()` provides hint not lock |
| `backend/agent/der_loop.py` | `DirectorQueue` gains `current_mode` + `set_mode()` + `escalate()` + `de_escalate()`; `QueueItem` supports mode-aware execution; dynamic step injection on escalation |
| `backend/agent/der_constants.py` | Add mode budgets (`QUICK=15k`, `AGENTIC=50k`, `FULL=50k`), `MAX_AGENTIC_ITERATIONS=20`, `MAX_FULL_CYCLES=40` |
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
| `hooks/useIRISWebSocket.ts` | Forward `iris:task_update`, `iris:context_usage`, `iris:agent_question` as CustomEvents |
| `hooks/useUILayoutState.ts` | Expose working state for orb badge |

---

## 9. AskUserQuestion Tool + Voice Filler + Agent-Initiated Speech

Three interconnected features that make the agent conversational and proactive, not just reactive.

### 9.1 AskUserQuestion Tool

**What it is:** A new agent tool (`ask_user_question`) that the DER loop can call during Explorer phase when the agent needs user input mid-task. Unlike the permission system (which asks "should I do this?"), AskUserQuestion asks "which approach should I take?" or "can you clarify?".

**When the agent calls it:**
- Clarification needed: "Did you mean file X or file Y?"
- Approach choice: "I can do this quickly with approach A, or thoroughly with approach B. Which?"
- Missing information: "Which directory should I search in?"
- Confirmation on ambiguous intent: "You said 'delete the old ones' — do you mean files older than 30 days?"

**How it works:**
1. Agent LLM emits `tool_call` for `ask_user_question` with `question` + `options` (multiple choice)
2. TaskKernel emits `agent_question` event via EventBus → WS → frontend
3. Frontend renders a question card in chat-view (if open) or shows a question badge on the orb (if wings closed)
4. User answers by:
   - Clicking an option (chat-view open)
   - Speaking the answer (voice command open — STT captures the answer, fuzzy-matched to options, see §9.2 voice filler integration)
   - Clicking the orb to open wings, then clicking an option
5. Answer is fed back to the DER loop as the tool result
6. DER loop continues with the user's answer

**Voice mode integration (see §9.2):** When voice command is open and the agent calls `ask_user_question`, the question is spoken aloud via the ConversationKernel utterance mechanism. After TTS finishes, the agent listens for a spoken answer. The spoken answer is fuzzy-matched to the options. If no response within N seconds, filler prompts re-state the question. This makes AskUserQuestion fully hands-free in voice mode.

**Question card UI:**
- Renders inline in chat stream (like TaskListCard)
- Shows: question text, options as clickable buttons
- Optional: "Other" option that opens a text input for free-form answer
- Voice-eligible: if voice command is open, the user can speak their answer and the agent matches it to the closest option
- Matches orb aesthetic: dark glass, brand-color option buttons, monospace question text

**Orb question badge (when wings closed):**
- Small badge with a question mark icon
- Pulsing brand color to draw attention
- Clicking the orb opens wings to reveal the question card
- If voice command is open, the agent speaks the question aloud and listens for the answer

### 9.2 Voice Smart Filler Comments

**What it is:** Context-aware filler phrases that ConversationKernel emits during COMPRESS phase when the voice command is open and there's a silence gap. Prevents the user from thinking the agent froze. **Also supports AskUserQuestion** — the question is spoken aloud via the filler/utterance mechanism, and the agent listens for a spoken answer.

**When it fires:**
- Voice command is open (listening or processing state)
- Caducean phase is COMPRESS (agent is working)
- No utterance has been emitted for N seconds (configurable, default 5s)
- Timer resets after each filler or utterance

**Filler phrase selection:**
- Context-aware: the filler matches what the agent is doing
  - Searching: "Let me search for that...", "Searching now..."
  - Reading files: "Let me check that file...", "Reading through it..."
  - Executing tool: "One moment, working on it...", "Let me handle that..."
  - Planning: "Let me think about the best approach...", "Considering options..."
  - Generic: "Hmm...", "Let me see...", "Working on it..."
- Phrase selection uses the current tool name / task phase to pick a relevant filler
- Phrases are short (3-7 words) — they fill silence, they don't narrate
- No filler during EXPAND phase (agent is already speaking)
- No filler if the user is speaking (barge-in detection)

**How it works:**
1. ConversationKernel starts a silence timer when entering COMPRESS with voice command open
2. If timer exceeds threshold, ConversationKernel emits a `status_phrase` event
3. TTS plays the filler phrase
4. Timer resets
5. If another N seconds pass with no utterance, another filler fires (different phrase to avoid repetition)

**AskUserQuestion + voice filler integration:**
When the agent calls `ask_user_question` and voice command is open:
1. ConversationKernel emits the question text as an `utterance` event (not a filler — a real utterance)
2. TTS speaks the question aloud: "Did you mean file X or file Y?"
3. After TTS finishes, the agent enters listening mode to capture the user's spoken answer
4. The user speaks their answer (e.g., "file X" or just "X")
5. STT captures the transcript
6. The transcript is matched to the closest option (fuzzy match) or treated as free-form if "Other" is enabled
7. The matched answer feeds back to the DER loop as the tool result
8. If the user doesn't respond within N seconds after the question is spoken, a filler prompt fires:
   - "Did you catch that? I asked: [question rephrased shorter]"
   - Or: "Take your time — which option do you prefer?"
9. If the user still doesn't respond after 2 filler prompts, the question is rendered as a visual card in chat-view (if open) or the orb badge pulses (if wings closed), and the DER loop waits for a click answer

**Voice answer matching:**
- Fuzzy match the spoken transcript against the option labels
- If confidence > 0.7, accept the match
- If confidence 0.4-0.7, ask for confirmation: "Did you mean [option]? Say yes or no."
- If confidence < 0.4, re-state the question and ask the user to speak the option number: "I didn't catch that. Say option 1 for [A], option 2 for [B]."
- If "Other" option is enabled and the transcript doesn't match any option, treat it as free-form input

### 9.3 Agent-Initiated Speech

**What it is:** The agent can open the audio pipeline itself to speak, even when chat-view isn't open and no voice command is in progress. TTS becomes subscribable independent of the voice command flow.

**When the agent speaks proactively:**
- Background task completed: "Done. I found 3 files matching your search."
- AskUserQuestion prompt (when voice command is open): "Did you mean file X or file Y?"
- Long-running task milestone: "Still working — step 3 of 5 done."
- Error that needs user attention: "I hit an error trying to access that file. Want me to try a different approach?"

**How it works:**
1. TaskKernel or ConversationKernel emits an `utterance` event via EventBus
2. TTS is subscribed to `utterance` events regardless of voice command state
3. TTS plays the utterance through the audio pipeline
4. If chat-view is closed, the orb shows a speaking state (canvas breathing shifts to speaking cadence)
5. If chat-view is open, the utterance also renders as a chat message

**Audio pipeline independence:**
- Currently: TTS is triggered by the voice command flow (user speaks → STT → agent → TTS)
- After: TTS is triggered by any `utterance` event from EventBus, regardless of source
- The voice command flow still works as before — it's one source of utterance events
- Agent-initiated speech is another source
- Both go through the same TTS pipeline (chunk sizing, word timing, barge-in)

**Orb speaking state (when chat-view closed):**
- Orb canvas breathing shifts to speaking cadence (same as `isSpeaking` today)
- No visual text shown (chat-view is closed)
- User can click the orb to open wings and see the text
- User can interrupt (barge-in) by speaking — same as today

### 9.4 Files Touched

| File | Change |
|------|--------|
| `backend/agent/tools/ask_user_tool.py` | **New** — `ask_user_question` tool implementation |
| `backend/agent/task_kernel.py` | Emit `agent_question` events; emit `utterance` events for agent-initiated speech |
| `backend/agent/conversation_kernel.py` | Silence timer for voice filler; emit filler `status_phrase` events; emit `utterance` for agent-initiated speech |
| `backend/agent/tts.py` | Subscribe to `utterance` events regardless of voice command state |
| `backend/agent/tool_bridge.py` | Register `ask_user_question` tool; pause DER loop until answer received |
| `components/chat/QuestionCard.tsx` | **New** — multiple-choice question card component |
| `components/iris/OrbBadge.tsx` | Add question badge state (question mark icon, pulsing) |
| `components/chat-view.tsx` | Render QuestionCard in message stream; handle answer submission |
| `components/iris/XurOrb.tsx` | Render question badge when agent has a question |
| `hooks/useIRISWebSocket.ts` | Forward `iris:agent_question` as CustomEvent; handle answer submission |
| `backend/iris_gateway.py` | Handle `agent_question_response` WS message; route to DER loop |

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
TaskClassifier → task_class hint (for Mycelium space routing, NOT a mode lock)
    ↓
Mycelium.get_task_context_package() → ContextPackage
    ↓
_plan_task() → ExecutionPlan (initial mode hint from classifier)
    ↓
Caducean: phase → COMPRESS (TaskKernel active, ConversationKernel silent)
    ↓
DER Loop (Director decides and adjusts mode dynamically):
    ├─ Director: assess task + context + classifier hint → pick initial mode
    │   mode = quick | agentic | full
    ├─ Director: next_ready()
    ├─ Reviewer: PASS/REFINE/VETO (reads Mycelium + PiNs)
    ├─ Explorer: executes based on current mode
    │   ├─ quick: single LLM call, no tools
    │   ├─ agentic: LLM emits tool_calls dynamically
    │   └─ full: pre-planned step execution
    │   ├─ Permission check (tiered risk) if tools involved
    │   │   └─ If approval needed: emit permission_request → wait
    │   ├─ Tool executes (if applicable)
    │   ├─ EventBus.emit(tool_call) → frontend: TaskListCard updates
    │   ├─ EventBus.emit(tool_result) → frontend: TaskListCard updates
    │   └─ Mycelium.ingest_tool_call()
    ├─ Director: re-evaluate mode after result
    │   ├─ Escalate: quick → agentic → full (if task needs more)
    │   ├─ De-escalate: full → agentic → quick (if task simplifies)
    │   └─ Log mode change to Mycelium via ingest_statement()
    ├─ TrailingDirector: gap analysis
    └─ Loop until complete or budget exhausted
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
| DER loop | Director dynamically decides and adjusts execution mode (quick/agentic/full) during the loop — not hardcoded upfront. LLM emits tool_calls in Explorer when mode=agentic |
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
8. **Cross-cutting concerns:** All 12 concerns in Section 14 are addressed. No layer failure blocks a user response.

---

## 14. Cross-Cutting Concerns

These are the things that cause "works in isolation, breaks when layers combine" failures. **The system already has most of the machinery.** Each solution below connects to and refines an existing mechanism — nothing is built from scratch.

### 14.1 Concurrency Model

**Problem:** Can the agent work on a background task in conversation A while the user is in conversation B? What if the user sends a text message while a voice command is processing?

**What already exists:** `get_agent_kernel(session_id)` returns one `AgentKernel` per session. The DER loop is already single-threaded per session — `process_text_message(session_id=)` handles one message at a time. No concurrent DER loops within a session.

**Solution — re-key, don't rebuild:**
- Re-key `get_agent_kernel` from `session_id` to `conversation_id`. The existing single-threaded-per-session model becomes single-threaded-per-conversation. Same orchestration, different key.
- **Thread switching** = save current kernel context to `ConversationContextStore` + load the new thread's context. The existing `clear_conversation()` (called on `new_conversation`) is extended to handle thread switching too.
- **Background tasks in paused conversations:** a paused DER loop's in-flight tool calls complete (they're already running), but no new steps start until the user returns. The orb badge shows the active conversation's task only.
- **Text + voice simultaneity:** the frontend already disables text input during voice processing (existing UI behavior). No new locking needed — the existing disable is the lock.
- **Mycelium writes:** already serialized per session (single-threaded DER). Re-keying to `conversation_id` preserves this. WAL mode handles cross-conversation concurrency.

### 14.2 Event Ordering and Delivery Guarantees

**Problem:** EventBus emits events, but what if a `tool_call` event arrives before the TaskListCard is mounted? What about events during WS reconnect?

**What already exists:** `useIRISWebSocket.ts` already has:
- `seenTurnIds` ref for deduplication (line 222)
- Message queue for non-ephemeral messages when offline (line 1192)
- Flush queued messages on reconnect (line 318)
- Exponential backoff reconnect (line 265)
- CustomEvent forwarding (`iris:text_response`, `iris:voice_final`, etc.)

**Solution — extend existing dedup + queue:**
- **EventBus guarantees in-order delivery per `turn_id`.** Events with the same `turn_id` are delivered to subscribers in emit order. The existing `seenTurnIds` dedup handles cross-turn replay.
- **Frontend event buffer = existing message queue.** The WS hook already queues messages when offline and flushes on reconnect. TaskListCard subscribes to `iris:task_update` CustomEvents — if it mounts after events fire, the WS hook's queue has them.
- **Backend ring buffer for replay.** A small bounded ring buffer (100 events per `conversation_id`, 1000 total) on the backend. On reconnect, the backend replays the last 10 events per active `conversation_id`. The frontend deduplicates by `event_id` using the existing `seenTurnIds` pattern.
- **No new queue mechanism.** The existing message queue + flush-on-reconnect + `seenTurnIds` dedup is the foundation. The ring buffer is the only new piece, and it's small.

### 14.3 State Synchronization

**Problem:** Three state stores: ConversationContextStore (backend disk), conversations (frontend localStorage), agent kernel context (backend memory). What's the source of truth?

**What already exists:** Frontend localStorage (`iris_conversations_v1`) is already the source of truth for message history + conversation metadata. The backend agent kernel already holds context in-memory per session. They're already separate — message history (display) ≠ agent context (LLM inference).

**Solution — make the existing split persistent:**
- **Frontend localStorage stays the source of truth for UI state** (message text, timestamps, conversation metadata). Unchanged.
- **ConversationContextStore makes the existing in-memory agent context persistent.** The agent kernel already has context in-memory — we just persist it to disk so it survives WS disconnect. Same data, persistent instead of volatile.
- **On conflict:** frontend message history wins for display. Backend agent context wins for LLM inference. They don't need to be identical — the agent context is a compressed view (per Pacman: metabolized, not raw text).
- **On WS reconnect:** frontend sends `conversation_id` + last message timestamp (existing `switch_conversation` message, extended). Backend responds with any agent context updated after that timestamp. Frontend merges. The existing `settings_sync` pattern handles settings.

### 14.4 Barge-in During Agent Speech

**Problem:** When the agent is speaking a filler or a question, can the user interrupt? How does barge-in interact with the DER loop pause and AskUserQuestion flow?

**What already exists:** `ConversationKernel.on_audio_level()` already detects barge-in — if user speaks loudly (`level > 0.5`) while agent is speaking (`_was_speaking`), it nudges Caducean params and calls `audio_pipeline.interrupt()`. This is the existing, solidified barge-in path.

**Solution — extend the existing barge-in path, don't replace it:**
- **Barge-in during filler:** `audio_pipeline.interrupt()` halts TTS (existing path). The filler is discarded. The silence timer resets after the user's turn. No new code — the existing `on_audio_level` + `interrupt()` handles it.
- **Barge-in during AskUserQuestion (voice mode):** `audio_pipeline.interrupt()` halts the question TTS (existing path). The user's speech is captured by the existing STT pipeline. The transcript is fuzzy-matched to options. If valid, DER loop continues. If not, the agent re-asks after the user's turn. The only new code: the fuzzy matcher + the re-ask logic.
- **Barge-in during agent-initiated speech (background task result):** `audio_pipeline.interrupt()` halts TTS (existing path). The result is still saved to the conversation (text). The user's voice command takes priority. No new interrupt path — just save the text result before discarding the audio.
- **Barge-in during permission prompt:** `audio_pipeline.interrupt()` halts TTS (existing path). The user's speech is captured. If they say "yes"/"allow" → grant. If "no"/"deny" → deny. Otherwise, the permission prompt stays. The only new code: voice-to-permission-action matching.

### 14.5 Token Budget Across Mode Changes

**Problem:** Director escalates from `quick` (15k) to `agentic` (50k). Does the budget reset? Accumulate?

**What already exists:** The DER loop already has `_token_budget` and `_tokens_used` (line 2306-2430). `_tokens_used` is incremented per step (`len(step_result) // 4`). The budget is set from `DER_TOKEN_BUDGETS[task_class]` at loop start.

**Solution — keep the existing counter running:**
- **`_tokens_used` accumulates across mode changes.** The existing counter keeps running. When the Director escalates, `_token_budget` is updated to the new mode's budget, but `_tokens_used` is NOT reset.
- **Escalation does not reset the counter.** This prevents infinite loops via repeated escalation.
- **De-escalation does not restore budget.** Tokens spent are spent.
- **Budget is per-turn (per user message).** The Director can change modes freely, but the total token spend is capped by the highest mode's budget reached. A `quick` (15k) task that escalates to `agentic` (50k) has 50k total — not 65k.
- **Budget extension:** if a high-value task approaches the cap, the Director can request an extension from Mycelium (rare, logged, max 1 extension per turn of +50%). This hooks into the existing `mycelium_ingest_statement()` for logging.
- **No new tracking mechanism.** The existing `_token_budget` / `_tokens_used` pair is extended with mode-awareness. Same variables, same increment logic.

### 14.6 WS Reconnect During Paused States

**Problem:** Agent asks a question (AskUserQuestion) or requests permission, then WS disconnects before the user answers. What happens to the paused DER loop?

**What already exists:** `useIRISWebSocket.ts` already queues messages when offline (line 1192) and flushes on reconnect (line 318). The backend already has `new_conversation` → `clear_conversation()` for context lifecycle.

**Solution — persist pause state, leverage existing queue:**
- **Paused DER loop state is persisted to ConversationContextStore.** The pause reason (question, permission), the pending tool call, and the timeout deadline are saved. This is a new field on the existing store — not a new store.
- **On reconnect:** the backend restores the paused state from ConversationContextStore. If the timeout hasn't expired, the question/permission is re-sent to the frontend via the existing WS message queue + flush mechanism. If the timeout has expired, the tool returns "timeout" and the DER loop continues with the default/fallback.
- **Frontend shows the question/permission again on reconnect** — the existing flush mechanism delivers it. The user can answer as if it was never interrupted.
- **No orphaned pauses.** Every paused state has a timeout (existing pattern from permission system: 30s/60s). No DER loop hangs forever.
- **No new reconnect mechanism.** The existing queue + flush + backoff handles delivery. ConversationContextStore handles persistence. They connect at the `conversation_id` key.

### 14.7 Agent-Initiated Speech vs User Speech Priority

**Problem:** Agent tries to speak (background task done) while the user is speaking. Who wins?

**What already exists:** `ConversationKernel.on_audio_level()` already detects when the user is speaking. `voiceState` already tracks listening/speaking/processing. The existing barge-in path (`audio_pipeline.interrupt()`) already halts agent speech when the user speaks.

**Solution — check existing `voiceState` before speaking:**
- **User speech always wins.** Before emitting an agent-initiated utterance, ConversationKernel checks `voiceState`. If `voiceState === "listening"` (user is speaking), the utterance is queued, not played.
- **Queue is bounded:** max 2 pending agent utterances. If 2 are already queued, the 3rd is rendered as text only (saved to conversation) — not spoken. This uses the existing WS message queue pattern.
- **Queue drains when user finishes speaking.** After the user's voice turn completes and TTS plays the response, queued agent utterances play in order. The existing `on_voice_state` IDLE transition triggers the drain.
- **User can flush the queue.** Starting a new voice command flushes pending agent utterances (they're saved as text, not spoken). The existing `startVoiceCommand` path is extended with a queue flush.
- **Filler phrases never queue.** If a filler would fire while the user is speaking, it's skipped. The existing `on_audio_level` check prevents filler emission during user speech.
- **No new priority system.** The existing `voiceState` + `on_audio_level` + `audio_pipeline.interrupt()` is the priority mechanism. The queue is a small addition using the existing WS queue pattern.

### 14.8 Configuration Storage and UI

**Problem:** Voice preference, filler timer, approval timeouts, mode budgets — all "configurable" but where do they live?

**What already exists:** `data/iris_config.json` already exists with sections: `routing`, `inference`, `swarm_roles`, `system`, `tts`, `ports`. The customize panel (side panel) already exposes user-facing settings. `system.mode` is already `"personal"`.

**Solution — add an `agent` section to the existing config:**
```json
{
  "agent": {
    "multi_step_enabled": true,
    "voice_preference": "quick_first",
    "filler_enabled": true,
    "filler_timer_seconds": 5,
    "approval_timeout_seconds": 30,
    "destructive_approval_timeout_seconds": 60,
    "agent_speech_enabled": true,
    "background_tasks_enabled": true
  }
}
```
- **Settings UI:** extend the existing customize panel with an "Agent" section. Exposes user-facing settings: voice preference, filler enabled/timer, agent speech enabled, background tasks enabled.
- **Developer-only settings** (mode budgets, max iterations) are in `iris_config.json` but not exposed in the UI — edited manually.
- **Settings sync on WS reconnect:** the existing `settings_sync` message (defined in Layer 2) sends current frontend settings to backend. Backend uses the synced values.
- **Settings changes take effect on the next turn.** No hot-reload of in-flight DER loops. The existing config-read-at-startup pattern is preserved.
- **No new config system.** The existing `iris_config.json` + customize panel + `settings_sync` message handles everything.

### 14.9 Observability / Correlation IDs

**Problem:** With kernel separation + EventBus + mode changes, debugging is hard. Need to trace a single turn through all layers.

**What already exists:** `turn_id` is already used for deduplication in the frontend (`seenTurnIds` ref). The backend `_text_response` helper already includes `turn_id` in WS payloads. `ConversationKernel` already logs with `session_id` context.

**Solution — extend `turn_id` to all layers, follow existing logging pattern:**
- **`turn_id` is the correlation ID.** Every event, log line, WS message, and DB write includes `turn_id`. Already partially implemented — just extend to EventBus events, TaskKernel events, and mode change logs.
- **Structured logging:** follow the existing `ConversationKernel` pattern (`logger.debug("[ConversationKernel] ...")`). Every log line includes `turn_id`, `conversation_id`, `mode` (when in DER), `phase` (EXPAND/COMPRESS). Format: `[turn_id=abc conv=123 mode=agentic phase=COMPRESS] message`.
- **Mode change logging:** every Director mode change is logged with reason. This hooks into the existing `mycelium_ingest_statement()` — the mode change reason is ingested as a coordinate statement, so Mycelium learns.
- **EventBus debug log:** EventBus writes a debug log of all emitted events (bounded ring buffer, 1000 entries). Accessible via a debug endpoint. Follows the existing `memory/interface.py` try/except pattern — never blocks.
- **No new ID system.** `turn_id` already exists. No new correlation ID. No new logging framework. Just extend the existing pattern.

### 14.10 Migration Path

**Problem:** Existing conversations in localStorage use the old format. Existing agent kernel sessions in-flight when code deploys.

**What already exists:** `iris_conversations_v1` localStorage key with conversations array. The frontend already deserializes timestamps on load (line 170-174 of chat-view.tsx).

**Solution — standard localStorage version bump:**
- **`iris_conversations_v1` → `iris_conversations_v2`:** on startup, if `v2` doesn't exist but `v1` does, migrate:
  - Each conversation gets a `conversation_id` (UUID) if it doesn't have one
  - Format is otherwise identical — just add the `conversation_id` field
  - Old `v1` key is kept for one session as backup, then removed
- **Agent kernel sessions:** on backend restart, in-flight DER loops are lost (they were in-memory). ConversationContextStore has no persisted in-flight state yet. The user's next message starts a fresh DER loop. No crash — just a lost in-flight task. This is the existing behavior on restart.
- **No Mycelium migration.** Mycelium schema is unchanged. Existing coordinate graph, landmarks, PiNs all work as-is.
- **No new migration framework.** Standard localStorage version bump. The existing deserialization pattern handles it.

### 14.11 Feature Flags / Rollback

**Problem:** If the branch has a critical bug after merge, what's the rollback?

**What already exists:** `data/iris_config.json` already has config keys that control behavior (e.g., `system.mode`, `inference.tool_mode`). The backend already reads config at startup.

**Solution — one flag in existing config:**
- **`agent.multi_step_enabled`** in `iris_config.json` (default: `true` on this branch).
  - `true`: new behavior (conversation_id keying, kernel separation, Director-decided mode, agentic loop, permission tiers, AskUserQuestion, voice filler, agent-initiated speech)
  - `false`: old behavior (session_id keying, direct chunk_callback → TTS, pre-planned DER, 1-step voice cap, no permission tiers, no AskUserQuestion, no filler, no agent-initiated speech)
- **Flag is checked at entry points:** `process_text_message()`, `chunk_callback`, `voice_command_start` handler. If false, the old code path runs. The old code paths are preserved (not deleted) behind the flag.
- **Rollback = set flag to false + restart backend.** No code revert needed for emergency rollback.
- **Flag is removed** in a follow-up branch after the new behavior is verified stable for 2 weeks.
- **No new feature flag framework.** One boolean in the existing config file.

### 14.12 Error Propagation Across Layers

**Problem:** If EventBus fails, does DER hang? If ConversationContextStore corrupts, does the agent crash?

**What already exists:** `backend/memory/interface.py` already wraps all Mycelium calls in try/except — "Mycelium failures NEVER block the DER loop. When `_mycelium` is None, all calls are silent no-ops." `ConversationKernel` follows the same pattern — every method is wrapped in try/except with `logger.debug`.

**Solution — follow the existing try/except pattern for every new component:**
- **EventBus:** `emit()` wraps each handler call in try/except. A handler error is logged and dropped. Other handlers still receive the event. The DER loop continues regardless. Same pattern as `memory/interface.py`.
- **ConversationContextStore:** disk read/write wrapped in try/except. If read fails, return None — agent kernel starts fresh context. If write fails, log warning — context is volatile for that session. Same pattern as Mycelium.
- **TaskKernel:** `emit_*` methods wrapped in try/except. If emit fails, the DER loop continues. Tool results are still used by the LLM. Frontend might miss an event, but the final result is still delivered via `text_response`. Same pattern.
- **ConversationKernel:** `emit_utterance` / `emit_status_phrase` wrapped in try/except. If emit fails, TTS doesn't speak. The text response is still delivered via WS. Same pattern.
- **Permission system:** if the permission check throws, the tool is denied (fail-closed for safety). The DER loop continues with the denial. Same pattern.
- **AskUserQuestion:** if the question event can't be emitted, the tool returns "no response" after timeout. The DER loop continues with a default. Same pattern.
- **Golden rule (existing, preserved):** the user always gets a response. It might be degraded (no audio, no task list, no context), but it's never silence. A crash that blocks a user response is a P0 bug. This is the existing Mycelium philosophy extended to all new components.
- **No new error handling framework.** The existing try/except + log + continue pattern from `memory/interface.py` is applied to every new component. Same philosophy, new components.

---

## 15. References

- Gap analysis: `docs/architecture/agent-multi-step-gaps.md`
- DER loop + Mycelium: `docs/DER_LOOP_MYCELIUM.md`
- Pacman context metabolism: `docs/PACMAN.md`
- Timing/sync pipeline: `docs/plans/timing-sync-pipeline-overlap.md`
- Implementation plan: `docs/plans/2026-07-06-agent-multi-step-tool-execution.md`
