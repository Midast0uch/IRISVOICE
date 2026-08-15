# Web Toggle → Search → Crawl: End-to-End Architecture

> Complete flow documentation from web mode toggle through voice/text input,
> agent planning, crawler execution, event emission, frontend rendering,
> audio pipeline, and memory recording. Every layer, every node.

**Last updated:** 2026-07-11  
**Applies to:** IRIS Voice with Web Mode ON, `crawler_query` tool, multi-step
tool-call visualization (plan §12)

---

## Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Browser)                               │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  XurOrb    │  │ ContextPill  │  │ TaskListCard │  │ Chat Messages │  │
│  │ (phase,    │  │ (action,     │  │ (planTitle,  │  │ (text bubble, │  │
│  │  counter)  │  │  phaseLabel) │  │  steps)      │  │  TTS words)   │  │
│  └─────┬──────┘  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
│        │                │                 │                 │          │
│        └────────┬───────┴────────┬────────┘                 │          │
│                 │                │                          │          │
│          ┌──────▼────────────────▼──────────────────┐       │          │
│          │        useTaskProgress + voiceState       │       │          │
│          │  (reduces iris:task_update events)        │       │          │
│          └──────┬───────────────────────────────────┘       │          │
│                 │ window.Event('iris:task_update')          │          │
│          ┌──────▼───────────────────────────────────┐       │          │
│          │        useIRISWebSocket                   │       │          │
│          │  (WS message dispatcher)                  │       │          │
│          └──────┬───────────────────────────────────┘       │          │
│                 │ WebSocket                                │          │
└─────────────────┼──────────────────────────────────────────┼──────────┘
                  │                                          │
                  ▼                                          ▼
         ┌──────────────────────┐                  ┌─────────────────────┐
         │   WS Event Bridge    │                  │  Direct WS Messages │
         │  (task:start,        │                  │  (listening_state,  │
         │   tool:call/result,  │                  │   text_response,    │
         │   task:progress)     │                  │   tts_started,      │
         └──────────┬───────────┘                  │   chat_chunk)       │
                    │                              └─────────┬───────────┘
                    │                                        │
         ┌──────────▼────────────────────────────────────────▼──────────┐
         │                    IRIS Gateway (iris_gateway.py)             │
         │  WebSocket handler, audio pipeline, agent orchestrator       │
         └──────────┬───────────────────────────────────────────────────┘
                    │ voice STT or text message
         ┌──────────▼───────────────────────────────────────────────────┐
         │               Agent Kernel (agent_kernel.py)                  │
         │  sanitize → classify → context assembly → plan → strategy     │
         │  ┌─ DER Loop: Director → Reviewer → Explorer ──────────────┐ │
         │  │  Emits: task:start, tool:call, tool:result, task:done   │ │
         │  └─────────────────────────────────────────────────────────┘ │
         └──────────┬───────────────────────────────────────────────────┘
                    │ calls tool
         ┌──────────▼───────────────────────────────────────────────────┐
         │              Tool Bridge (tool_bridge.py)                     │
         │  execute_tool → gates → dispatch → _execute_crawler_query    │
         │  ┌─ Crawl phase: ──────────────────────────────────────────┐ │
         │  │  planner → CrawlerEngine (per-page callbacks)             │ │
         │  │  Emits: LISTENING_STATE, TASK_PROGRESS, progress speaks │ │
         │  └─────────────────────────────────────────────────────────┘ │
         │  _record_tool_event → FFI (C++ core memory log)              │
         └──────────┬───────────────────────────────────────────────────┘
                    │
         ┌──────────▼───────────────────────────────────────────────────┐
         │              Memory (mycelium/)                               │
         │  mycelium_ingest_tool_call → coordinate graph (+confidence)   │
         │  mycelium_record_outcome → landmark crystallization           │
         └──────────────────────────────────────────────────────────────┘
```

---

## Layer 0: Web Mode Toggle

### Where it lives

The `web_mode_active` flag is a boolean in `iris_gateway.py`. When ON, the agent
is allowed to use web research tools (`crawler_query`, `search`). When OFF,
`execute_tool` rejects those tools via the `InternetGate` permission check.

### Gate enforcement (execute_tool, tool_bridge.py:875)

```
execute_tool("crawler_query", params, session_id)
     │
     ▼
  ┌─────────────────────────────────────┐
  │  InternetGate                        │
  │  Checks: CapabilitySet               │
  │  .is_tool_allowed("crawler_query")   │
  │                                      │
  │  If NOT allowed:                     │
  │   return {"success": false,          │
  │           "error": "not permitted"}  │
  └─────────────────────────────────────┘
     │ allowed
     ▼
  ┌─────────────────────────────────────┐
  │  DesktopGate (if applicable)         │
  │  (checks DesktopCapability for       │
  │   desktop-mode tools)                │
  └─────────────────────────────────────┘
     │ passed
     ▼
  Generic task:progress emission
  → "Searching the web: <query>"
     │
     ▼
  Dispatch to _execute_crawler_query()
```

### Setting the flag

The flag is toggled via WebSocket message or config. When the user activates
"web mode" from the frontend (e.g. toggle switch in dashboard-wing):

```
Frontend toggle ON
  → WS: {type: "web_mode_toggle", payload: {active: true}}
  → iris_gateway: self._web_mode_active = True
  → BROADCAST: {type: "web_mode_changed", payload: {active: true}}
```

---

## Layer 1: Voice Input → Agent Kernel

### Voice path

```
User speaks
  → Porcupine wake word detection
  → STT (Whisper / WebRTC) → transcript text
  → iris_gateway._process_voice_transcription(transcript, ...)

_process_voice_transcription (iris_gateway.py:2150):
  1. Send user bubble: text_response to chat
  2. Enrich transcript with audio context
  3. Get agent_kernel instance
  4. Broadcast listening_state: processing_conversation
     → frontend orb shows "WORKING"
  5. Start STTPROC.wav loop (processing sound)
     ┌─────────────────────────────────────────┐
     │  Thread: _loop_sttproc                  │
     │  Loops STTPROC.wav playback             │
     │  until _sttproc_stop.set()              │
     │  (stopped when TTS speech starts)       │
     └─────────────────────────────────────────┘
  6. Set up sentence_queue for streaming TTS
  7. Start _execute_agent in thread pool
```

### Text path (alternative)

```
User types message
  → WS: {type: "text_message", payload: {text: "..."}}
  → iris_gateway._handle_chat()
  → security_filter (sanitization + injection detect)
  → mcp_security (HyphaChannel trust enforcement)
  → agent_kernel.process_text_message(text, session_id)
```

### _execute_agent (iris_gateway.py:2287)

```
_execute_agent (runs in thread pool):
  1. agent_kernel.process_text_message(enriched, session_id)
  2. Collects response text via chunk_callback
  3. chunk_callback builds sentences → sentence_queue
  4. TTS thread reads sentence_queue → audio playback
```

---

## Layer 2: Planning & DER Loop

### process_text_message routing (agent_kernel.py:3760)

```
process_text_message(text, session_id):
     │
     ├─ [1] _sanitize_task(text)
     │      (replaces coordinate markers like [CORE])
     │
     ├─ [2] TaskClassifier.classify(text)
     │      → task_class ("full" | "partial" | "quick")
     │      → space_subset (which Mycelium spaces to query)
     │
     ├─ [3] memory_interface.get_task_context_package(task, session_id, space_subset)
     │      → ContextPackage (coordinates, PiNs, landmarks)
     │      → is_mature (bool)
     │
     ├─ [4] _plan_task(text, context_package, is_mature)
     │      → LLM generates JSON plan:
     │        {"strategy": "do_it_myself",
     │         "plan_title": "Search web for AI news",    ← NEW
     │         "reasoning": "...",
     │         "steps": [{"step_id": "s1", "description": "...", "tool": "crawler_query", ...}]}
     │      → ExecutionPlan (core_models.py)
     │
     ├─ [5] memory_interface.mycelium_ingest_statement(reasoning)
     │
     ├─ [6] EARLY TASK_START emission (if strategy == "do_it_myself")
     │      ┌──────────────────────────────────────────────────┐
     │      │ bus.emit(TASK_START, {                           │
     │      │   task_id, plan_title, description,              │
     │      │   mode, steps: [plan steps, status: "pending"]   │
     │      │ })                                                │
     │      │ → Frontend gets plan skeleton BEFORE any tools   │
     │      └──────────────────────────────────────────────────┘
     │
     └─ [7] route by strategy:
              if "do_it_myself" → _execute_plan_der(plan, ...)
              else → ReAct / fallback
```

### DER Loop — _execute_plan_der (agent_kernel.py:4429)

```
_execute_plan_der(plan, ...):
   ┌─────────────────────────────────────────────────────┐
   │  Build DirectorQueue from plan.steps                │
   │  Set token budget from mode (15k-80k tokens)        │
   │                                                      │
   │  while not queue.is_complete():                      │
   │    1. DIRECTOR: queue.next_ready() → item            │
   │    2. REVIEWER: review(item, ...)                    │
   │       → PASS / REFINE / VETO                         │
   │    3. (If VETO'd twice, mark vetoed, continue)       │
   │    4. Mid-loop episodic retrieval (C.4)              │
   │    5. EXPLORER: execute item                         │
   │       ┌──────────────────────────────────────────┐   │
   │       │  if item.tool exists:                     │   │
   │       │    tool_bridge.execute_tool(              │   │
   │       │      item.tool, item.params,              │   │
   │       │      session_id,                          │   │
   │       │      plan_title=plan.plan_title           │   │
   │       │    )                                      │   │
   │       │  else: _run_step_direct(item, ...)        │   │
   │       │  tool:call EMITTED by DER loop BEFORE     │   │
   │       │    calling execute_tool                   │   │
   │       │  tool:result EMITTED by DER loop AFTER    │   │
   │       │    execute_tool returns                   │   │
   │       └──────────────────────────────────────────┘   │
   │    6. mycelium_ingest_tool_call(...)                  │
   │    7. Check token budget                             │
   │    8. TrailingDirector (gap analysis)                 │
   │    9. queue.mark_complete(item.step_id)               │
   │                                                      │
   │  POST-LOOP (strict order):                            │
   │    mycelium_record_outcome()                          │
   │    mycelium_crystallize_landmark()                    │
   │    mycelium_clear_session()                           │
   │    mycelium_record_plan_stats()                       │
   └─────────────────────────────────────────────────────┘
```

### Events emitted by DER loop

| Event | When | Data | Frontend effect |
|-------|------|------|-----------------|
| `task:start` | At DER start (also early in process_text_message) | `task_id, plan_title, description, mode, steps, total_steps` | TaskListCard renders plan skeleton with "pending" steps |
| `tool:call` | Before each tool executes | `task_id, step_number, description, tool_name` | Step flips to "working" icon; currentAction updates |
| `tool:result` | After each tool returns | `task_id, step_number, result_summary` | Step flips to "done" icon |
| `tool:error` | On tool failure | `task_id, step_number, error` | Step flips to "fail" icon |
| `task:done` | DER loop completes | `task_id, outcome` | isWorking=false; planTitle cleared |
| `task:fail` | DER loop fails | `task_id` | Same as done |

---

## Layer 3: Tool Bridge — crawler_query Execution

### execute_tool routing (tool_bridge.py:853)

```
execute_tool("crawler_query", params, session_id, plan_title=""):
     │
     ├─ [1] Permission gates (InternetGate, DesktopGate)
     ├─ [2] Generic task:progress emission
     │      → data: {description: "Searching the web: <query>",
     │                action: "Searching the web: <query>",
     │                plan_title: plan_title}
     │      → Frontend ContextPill shows "Searching the web: <query>"
     │
     ├─ [3] dispatch by tool_name == "crawler_query"
     │      → _execute_crawler_query(params, session_id)
     │
     └─ [4] _record_tool_event(session_id, tool_name, outcome, params, result, plan_title)
            → FFI: {tool, params, result, plan_title}
            → Immortus thread
```

### _execute_crawler_query — The crawl phase (tool_bridge.py:1412)

```
_execute_crawler_query(params, session_id):
     │
     ├─ [1] Plan the research
     │      plan = get_crawl_planner().plan(query)
     │      → returns: urls, instructions, result_type, title
     │
     ├─ [2] EMIT LISTENING_STATE: processing_tool
     │      → bus.emit(LISTENING_STATE, {state: "processing_tool"})
     │      → Frontend orb phase → "SEARCHING"
     │      → ContextPill label → "SEARCHING"
     │
     ├─ [3] Crawl with per-page callbacks
     │      async with CrawlerEngine() as engine:
     │          result = await engine.crawl(query, urls, instructions, on_page_done)
     │
     │      on_page_done(url, page_number, total) — called per page:
     │      ├─ [3a] Progress speak (audio)
     │      │    _speak_tool.speak("Researching — fetched page N of M", priority="low")
     │      │    → SpeakBroadcaster → TTS pipeline (non-blocking)
     │      │
     │      └─ [3b] TASK_PROGRESS emission (live step update)
     │             bus.emit(TASK_PROGRESS, {
     │               description: "Reading example.com (N/M)",
     │               action: "Reading example.com (N/M)",
     │               update_step: True,  ← rewrites plan step text
     │             })
     │             → Frontend: working step text rewrites to "Reading example.com (N/M)"
     │             → ContextPill: currentAction → "Reading example.com (N/M)"
     │
     ├─ [4] EMIT LISTENING_STATE: processing_conversation
     │      → bus.emit(LISTENING_STATE, {state: "processing_conversation"})
     │      → Frontend orb phase → "WORKING" (agent may summarise next)
     │
     ├─ [5] Extract findings
     │      dashboard_data = get_data_extractor().extract(crawl_result)
     │
     └─ [6] Return result dict
            {success, query, title, summary, sources, pages}
```

### Crawl failure handling

```
If CrawlerUnavailable or Exception during crawl:
   │
   ├─ If _bus exists (was created before error):
   │    EMIT LISTENING_STATE: processing_conversation
   │    → Prevents orb from staying stuck on "SEARCHING"
   │
   └─ Return {success: false, error: "..."}
```

### Per-page progress speaks — SpeakBroadcaster pattern

```
Progress speaks fire via SpeakBroadcaster (get_speak_tool().speak()):

  ┌─────────────────────────────────────────────────────────┐
  │  speak("Researching — fetched page N of M", priority="low") │
  │                                                          │
  │  Fire-and-forget, non-blocking                           │
  │  Rate-limited by SpeakBroadcaster (max 3 pending)        │
  │  500-char cap per utterance                              │
  │  If audio pipeline is closed, buffered/suppressed        │
  │  by ConversationKernel                                   │
  └─────────────────────────────────────────────────────────┘
```

---

## Layer 4: Event Bus & WebSocket Bridge

### EventBus flow

```
IRISStreamEvent emission
     │
     ▼
  EventBus (event_bus.py)
     │  (in-process, synchronous dispatch)
     │
     ├─ Local subscribers (in-thread)
     │  e.g. task_kernel.py (subscribes to TOOL_CALL, TOOL_RESULT)
     │
     └─ WSEventBridge subscriber (async)
            │
            ▼
     WSEventBridge._handle_event(payload)
        │  async — scheduled on main event loop
        │  via asyncio.run_coroutine_threadsafe
        │
        ├─ Builds WS message:
        │    {type: event.value, payload: payload.data}
        │
        └─ Broadcasts to all WS connections for session
             async for ws in ws_manager.get_session_connections(session_id):
                 asyncio.ensure_future(ws.send_json(msg))
```

### Event types emitted during a crawl

| Event (IRISStreamEvent) | WS message type | From | When |
|-------------------------|-----------------|------|------|
| `TASK_START` | `task:start` | agent_kernel.py + process_text_message | Plan created |
| `TOOL_CALL` | `tool:call` | DER loop | Before execute_tool |
| `LISTENING_STATE` | `listening_state` | tool_bridge.py | Crawl start/end |
| `TASK_PROGRESS` | `task:progress` | tool_bridge.py | Per page fetched |
| `TOOL_RESULT` | `tool:result` | DER loop | After execute_tool returns |
| `TOOL_ERROR` | `tool:error` | DER loop | On tool failure |
| `TASK_DONE` | `task:done` | DER loop | Loop completes |

### Direct WS messages (not via EventBus)

| WS message | From | When |
|------------|------|------|
| `listening_state: processing_conversation` | iris_gateway.py ~2196 | LLM thinking / agent running |
| `text_response` (user bubble) | iris_gateway.py | STT result shown |
| `text_response` (agent reply) | iris_gateway.py | Final agent response |
| `tts_started` | iris_gateway.py | First TTS audio chunk |
| `tts_word` | iris_gateway.py | Per-word TTS timing |
| `chat_chunk` | iris_gateway.py | Streaming text |
| `crawler_page_fetched` | iris_gateway.py | (legacy, dashboard-wing only) |
| `document:render` | iris_gateway.py | Rich content display |

---

## Layer 5: Frontend — WebSocket Reception

```
WS message arrives
     │
     ▼
  useIRISWebSocket.ts — message handler
     │
     ├─ switch(message.type)
     │
     ├─ "listening_state":
     │    setVoiceState(payload.state)
     │    dispatch CustomEvent('iris:voice_state_change', {detail: {state}})
     │    → XurOrb reads voiceState
     │
     ├─ "task:start" / "task:progress" / "tool:call" / "tool:result" /
     │  "task:done" / "task:fail" / "tool:error":
     │    dispatch CustomEvent('iris:task_update', {detail: message.payload})
     │    → useTaskProgress listeners picks it up
     │
     ├─ "tts_started":
     │    dispatch CustomEvent('iris:tts_started', {detail: {...}})
     │    → chat-view sets currentTtsMessageId
     │
     ├─ "text_response":
     │    dispatch CustomEvent('iris:text_response', {detail: {...}})
     │    → chat-view renders message bubble
     │
     ├─ "chat_chunk":
     │    dispatch CustomEvent('iris:chat_chunk', {detail: {...}})
     │    → chat-view updates streaming text
     │
     ├─ "crawler_page_fetched":
     │    dispatch CustomEvent('iris:crawler_page_fetched', {detail: {...}})
     │    → dashboard-wing (legacy, superseded by task:progress)
     │
     └─ other types → handled individually
```

### Event timing (critical for plan card visibility)

```
BEFORE fix (Q4 bug):
  Agent thread:  [TASK_START] → [tool:call] → [crawl...]
  WS bridge:     (schedules)     (schedules)
  Frontend:                  [BOTH arrive together]
  → Plan card jumps to "working", user misses "pending" phase

AFTER fix (early TASK_START):
  process_text_message:  [TASK_START]
  Agent thread:                           [tool:call] → [crawl...]
  WS bridge:   (schedules)                 (schedules)
  Frontend:    [TASK_START arrives first]
               Steps in "pending"
               Plan card visible BEFORE any tool executes
                              ↓
               [tool:call arrives later]
               Step flips to "working" during crawl
```

---

## Layer 6: Frontend — State Stores

### useTaskProgress (useTaskProgress.ts)

```
iris:task_update event
     │
     ▼
  reducer switch(detail.type):
     │
     ├─ "task:start" → setState({
     │     isWorking: true, steps: [status: "pending"],
     │     totalSteps, mode, turnId,
     │     planTitle: d.plan_title,        ← NEW
     │     currentAction: d.description     ← derived from first step
     │   })
     │
     ├─ "tool:call" → mark steps[step_number-1].status = "working"
     │   set currentAction = d.description (generic, all tools)
     │
     ├─ "task:progress" → if d.update_step:
     │     rewrite working step's description to d.description
     │   set currentAction = d.action || d.description
     │
     ├─ "tool:result" → mark steps[step_number-1].status = "done"
     │
     ├─ "tool:error" → mark steps[step_number-1].status = "fail"
     │
     └─ "task:done" / "task:fail":
         isWorking = false, currentAction = undefined, planTitle = undefined
         (steps preserved for display)
```

### Exposed state

```typescript
interface TaskProgress {
  isWorking: boolean
  currentStep: number
  totalSteps: number
  steps: TaskStep[]           // {id, description, status, toolName, stepNumber, resultPreview?}
  mode?: string               // e.g. "balanced", "voice_first"
  turnId?: string             // DER turn_id
  planTitle?: string          // from planner LLM — shown as card header
  currentAction?: string      // live action text — shown in ContextPill
}
```

### voiceState

```typescript
type VoiceState =
  | "idle"
  | "listening"
  | "processing_conversation"   // LLM thinking / agent running
  | "processing_tool"           // ← NEW: crawler sets this during tool execution
  | "speaking"
  | "error"
```

The voiceState is set by two paths:
1. **WS message** `listening_state` → `useIRISWebSocket.setVoiceState(payload.state)` (authoritative)
2. **Optimistic** → `setVoiceState("processing_conversation")` at line 1447 when user sends a message (fallback until backend responds)

---

## Layer 7: Frontend — UI Components

### XurOrb (components/iris/XurOrb.tsx)

```
XurOrb
  ├─ Reads: voiceState (from useIRISWebSocket)
  │         taskProgress (from useTaskProgress)
  │
  ├─ Orb animation:
  │    idle                  → slow pulse
  │    listening             → active listening rings
  │    processing_*          → OrbitDot spinning ring
  │    speaking              → speech pulse
  │
  ├─ OrbBadge (top-right overlay):
  │    Shows step counter "N/M" when taskProgress.isWorking
  │    Reads taskProgress.currentStep / taskProgress.totalSteps
  │
  └─ OrbWorkingIndicator (beneath orb):
       Shows "Working..." when taskProgress.isWorking
       Hidden when not working
```

### ContextPill (components/chat/ContextPill.tsx)

```
ContextPill
  Props: usedTokens, maxTokens, phase (voiceState), currentAction?

  Renders:
  ┌─────────────────────────────────────────────────┐
  │  [12.4k / 128k]  ████████░░░░  SEARCHING         │
  │  or, when currentAction is set:                  │
  │  [12.4k / 128k]  ████████░░░░  Reading example.. │
  └─────────────────────────────────────────────────┘

  Phase label mapping (PHASE_LABELS):
    "idle"                     → "IDLE"
    "listening"                → "LISTENING"
    "processing_conversation"  → "WORKING"
    "processing_tool"          → "SEARCHING"    ← crawler active
    "speaking"                 → "SPEAKING"
    "error"                    → "ERROR"

  CurrentAction: When present (from taskProgress.currentAction),
                 shown instead of phase label, truncated to 160px.
                 Title attribute shows full text.
```

### TaskListCard (components/chat/TaskListCard.tsx)

```
TaskListCard
  Props: steps, turnId?, mode?, planTitle?, defaultCollapsed=true?

  Renders:
  ┌─────────────────────────────────────────────────────┐
  │  [Search web for AI news]  [voice_first]  [1/3]  ▶ │
  │  ─────────────────────────────────────────────────  │
  │  ✓  Search web for AI news                          │
  │  ◉  Reading example.com (2/5)          ← live update│
  │  ○  Summarize findings                              │
  └─────────────────────────────────────────────────────┘

  Status icons:
    "pending"  → ○  (empty circle)
    "working"  → ◉  (pulsing filled circle)
    "done"     → ✓  (checkmark)
    "fail"     → ✗  (X)

  Header: planTitle (or "Plan" fallback) + mode + progress "N/M"
  Steps: Each step's description, status icon, optional resultPreview
  Collapse: Default collapsed — toggle via "▶" / "▼"
  Mount condition: steps.length > 0
```

---

## Layer 8: Audio Pipeline

### Audio pipeline during a web-search query

```
PHASE 1 — STT (speech-to-text)
═══════════════════════════════════════════════════════════
  User speaks
     │
     ├─ Porcupine wake word detection (if needed)
     ├─ WebRTC / Whisper STT
     └─ → transcript text

PHASE 2 — Processing sound (STTPROC.wav loop)
═══════════════════════════════════════════════════════════
  iris_gateway starts at ~2246:
    Thread: _loop_sttproc
      while not _sttproc_stop.is_set():
        sd.play(STTPROC.wav, blocking=True)
     │
     └─ Stops when TTS begins (text_response → _sttproc_stop.set())
        or when agent finishes speaking

PHASE 3 — Crawl progress speaks
═══════════════════════════════════════════════════════════
  During CrawlerEngine.crawl(), per page:
    _speak_tool.speak("Researching — fetched page N of M", priority="low")
       │
       └─ SpeakBroadcaster (fire-and-forget, rate-limited, non-blocking)
            │
            ├─ If STTPROC.wav is still playing:
            │   Speak is QUEUED — plays after processing sound stops
            │
            └─ If TTS pipeline is closed:
                Speak is SUPPRESSED / buffered by ConversationKernel

PHASE 4 — TTS (text-to-speech) — agent response
═══════════════════════════════════════════════════════════
  chunk_callback (iris_gateway.py:2292):
    Receives LLM response chunks → builds sentences
    ┌──────────────────────────────────────────────┐
    │  sentence_buf.append(chunk)                   │
    │  When sentence boundary detected:             │
    │    sentence_queue.put(sentence)               │
    └──────────────────────────────────────────────┘
       │
       ▼
  TTS thread reads sentence_queue:
    ┌──────────────────────────────────────────────┐
    │  while True:                                  │
    │    text = sentence_queue.get()                │
    │    if text is STOP sentinel: break            │
    │    audio = tts.synthesize(text)               │
    │    sd.play(audio, blocking=True)             │
    │    # Also sends tts_word events for frontend  │
    │    # word-level highlighting                  │
    └──────────────────────────────────────────────┘
       │
       ├─ _sttproc_stop.set()   ← stops STTPROC.wav
       │
       ├─ WS: tts_started {turn_id, total_words}
       │
       ├─ WS: tts_word {word, start_sec, end_sec}
       │
       └─ WS: text_response {text, turn_id} (final response text)

PHASE 5 — Complete
═══════════════════════════════════════════════════════════
  TTS finishes
  VoiceState → "idle" (sent by backend)
```

### SpeakBroadcaster utility

```
SpeakBroadcaster (get_speak_tool().speak()):
  ┌───────────────────────────────────────────────┐
  │  Fire-and-forget audio utterance              │
  │  Non-blocking — never stalls the caller       │
  │  Rate-limited: max 3 pending speaks           │
  │  Capped at 500 chars per utterance            │
  │  If audio pipeline is closed: auto-suppressed │
  │  Priority: "low" for progress speaks          │
  └───────────────────────────────────────────────┘
```

---

## Layer 9: Memory Recording

There are TWO parallel memory recording paths when a tool executes:

### Path A: FFI / C++ core (raw event log)

```
execute_tool → _record_tool_event (tool_bridge.py:1197):
  │
  └─ ffi_ingest_event({
       session_id,
       domain: "SYSTEM",
       event_type: "tool_execution",
       actor: "agent_tool_bridge",
       outcome: "success" | "failure",
       summary: "Tool <name> executed: <outcome>",
       payload_json: {
         "tool": "crawler_query",
         "params": {query: "...", ...},
         "result": {success: true, title: "...", ...},
         "plan_title": "Search web for AI news"    ← NEW
       }
     })
```

→ Queryable via `mcm_recall("Search web for AI news")`

### Path B: Mycelium coordinate graph (scored)

```
After each DER step → mycelium_ingest_tool_call (memory/interface.py):
  │
  └─ extractor.ingest_tool_call(session_id, tool_name, success, seq_pos, total)
       │
       └─ Maintains per-session observation window
          After ≥3 same-tool observations:
            Upserts toolpath coordinate node:
              coords: [tool_id_hash, call_freq, success_rate, avg_seq_pos]
              confidence: min(0.3 + 0.05*n, 0.9)
              space: "toolpath"
```

→ Feeds the coordinate graph → pheromone edges → landmark crystallization

### Post-loop recording (strict order — DER_LOOP_MYCELIUM.md §11)

```
1. mycelium_record_outcome()      → "hit" / "partial" / "miss"
2. mycelium_crystallize_landmark() → permanent landmark if score high
3. mycelium_clear_session()        → clean session state
4. mycelium_record_plan_stats()    → execution stats summary
```

---

## Complete Voice Flow — Sequence Diagram

```
User          Frontend       iris_gateway       agent_kernel      tool_bridge        mycelium
 │              │                │                  │                  │               │
 │ speak        │                │                  │                  │               │
 ├─────────────>│                │                  │                  │               │
 │              │ WS STT result  │                  │                  │               │
 │              │<──────────────>│                  │                  │               │
 │              │                │  transcript      │                  │               │
 │              │                │─────────────────>│                  │               │
 │              │                │                  │ task:start early │               │
 │              │                │                  │──────────────────>               │
 │              │<──WS: task:start─────────────────────────────────────│               │
 │              │ planTitle, steps(pending)         │                  │               │
 │              │                │  processing_conversation            │               │
 │              │<──WS: listening_state─────────────│                  │               │
 │              │ orb→"WORKING"  │                  │                  │               │
 │              │                │ STTPROC.wav loop │                  │               │
 │              │<──(audio)──────│                  │                  │               │
 │              │                │                  │ DER: tool:call   │               │
 │              │                │                  │─────────────────>│               │
 │              │<──WS: tool:call───────────────────│                  │               │
 │              │ step→"working" │                  │                  │               │
 │              │                │                  │                  │ search&crawl  │
 │              │                │                  │                  │─────┐         │
 │              │                │                  │                  │     │ plan    │
 │              │                │                  │                  │<────┘         │
 │              │                │                  │  listening_state │               │
 │              │                │                  │  processing_tool │               │
 │              │<──WS: listening_state─────────────│                  │               │
 │              │ orb→"SEARCHING"│                  │                  │               │
 │              │                │                  │                  │ crawl start   │
 │              │                │                  │                  │─────┐         │
 │              │                │                  │  task:progress   │     │ page 1  │
 │              │                │                  │ Reading host(1/3)│     │         │
 │              │<──WS: task:progress───────────────│                  │<────┘         │
 │              │ step desc→"Reading... (1/3)"      │                  │               │
 │              │                │                  │                  │     │ page 2  │
 │              │                │                  │  task:progress   │     │         │
 │              │                │                  │ Reading host(2/3)│     │         │
 │              │<──WS: task:progress───────────────│                  │<────┘         │
 │              │ step desc→"Reading... (2/3)"      │                  │               │
 │              │                │                  │ progress speak   │               │
 │              │ progress speaks (audio, if TTS pipeline avail)       │               │
 │              │                │                  │  listening_state │               │
 │              │                │                  │  processing_conversation          │
 │              │<──WS: listening_state─────────────│                  │               │
 │              │ orb→"WORKING"  │                  │                  │               │
 │              │                │                  │ DER: tool:result │               │
 │              │                │                  │─────────────────>│               │
 │              │<──WS: tool:result─────────────────│                  │               │
 │              │ step→"done"    │                  │                  │ record_event  │
 │              │                │                  │                  │─────> FFI     │
 │              │                │                  │ mycelium_ingest  │               │
 │              │                │                  │────────────────────────────────>│
 │              │                │                  │                  │               │
 │              │                │                  │ (DER loop continues or ends)    │
 │              │                │                  │                  │               │
 │              │                │ TTS: agent reply │                  │               │
 │              │                │───────────────────|                  │               │
 │              │<──WS: tts_started, tts_word, text_response           │               │
 │              │ stop STTPROC    │                  │                  │               │
 │              │<──(audio TTS)───│                  │                  │               │
 │              │                │                  │ task:done        │               │
 │              │<──WS: task:done───────────────────│                  │               │
 │              │ isWorking=false │                  │                  │               │
 │User          Frontend         iris_gateway       agent_kernel      tool_bridge     mycelium
```

---

## Complete Text Flow — Sequence Diagram

```
User types "research X"       Frontend         agent_kernel          tool_bridge
 │                              │                  │                    │
 │ type message                 │                  │                    │
 ├─────────────────────────────>│                  │                    │
 │                              │ WS text_message  │                    │
 │                              │─────────────────>│                    │
 │                              │                  │ sanitize           │
 │                              │                  │ classify           │
 │                              │                  │ context package    │
 │                              │                  │ plan task          │
 │                              │                  │ ─── LLM generates  │
 │                              │                  │ plan with steps    │
 │                              │                  │                    │
 │                              │                  │ EARLY TASK_START   │
 │                              │<──WS: task:start─│                    │
 │                              │ planTitle, steps │                    │
 │                              │                  │                    │
 │                              │                  │ _execute_plan_der  │
 │                              │                  │ TASK_START (2nd)   │
 │                              │                  │ (idempotent)       │
 │                              │                  │                    │
 │                              │                  │ DER: tool:call     │
 │                              │                  │───────────────────>│
 │                              │<──WS: tool:call──│                    │
 │                              │ step→"working"   │                    │
 │                              │                  │ execute_tool()     │
 │                              │                  │ task:progress      │
 │                              │<──WS: progress───│  (generic label)   │
 │                              │                  │                    │
 │                              │                  │ [_execute_crawler_query from here,
 │                              │                  │  same as Voice flow above]
 │                              │                  │                    │
 │                              │<──WS: tool:result│                    │
 │                              │ step→"done"      │                    │
 │                              │                  │                    │
 │                              │<──WS: text_response                   │
 │                              │ agent reply text │                    │
 │                              │                  │ task:done          │
 │                              │<──WS: task:done──│                    │
 │                              │ isWorking=false  │                    │
```

---

## File Reference Index

### Backend

| File | Role | Key functions/lines |
|------|------|---------------------|
| `backend/iris_gateway.py` | WebSocket handler, audio pipeline | `_process_voice_transcription` (~2150), `_execute_agent` (~2287), STTPROC loop (~2246), sentence_queue TTS (~2274) |
| `backend/agent/agent_kernel.py` | Agent loop, DER execution | `process_text_message` (~3760), `_plan_task` (~3361), `_execute_plan_der` (~4429), TASK_START emission (~4520) |
| `backend/agent/tool_bridge.py` | Tool dispatch, crawl execution | `execute_tool` (~853), `_execute_crawler_query` (~1412), `_record_tool_event` (~1197), `_tool_action_label` (~1161) |
| `backend/agent/event_bus.py` | In-process event dispatch | `IRISStreamEvent` enum, `TASK_PROGRESS`, `LISTENING_STATE` |
| `backend/agent/ws_event_bridge.py` | EventBus → WS bridge | `_BRIDGED_EVENTS` tuple, `_handle_event` async handler |
| `backend/core_models.py` | Data models | `ExecutionPlan` (plan_title), `PlanStep` |
| `backend/memory/interface.py` | Mycelium proxy | `mycelium_ingest_tool_call` (~537) |
| `backend/agent/agent_kernel.py` | DER token budgets | `DER_TOKEN_BUDGETS` dict |

### Frontend

| File | Role | Key sections |
|------|------|--------------|
| `hooks/useIRISWebSocket.ts` | WS message dispatcher | Case `listening_state` (~599), case `task:*` (~1180) |
| `hooks/useTaskProgress.ts` | Task state reducer | Interface (`currentAction`, `planTitle`), reducer cases |
| `components/iris/XurOrb.tsx` | Orb + badge | OrbBadge (~484), OrbWorkingIndicator (~141) |
| `components/chat/ContextPill.tsx` | Phase pillar | `PHASE_LABELS`, `currentAction` rendering |
| `components/chat/TaskListCard.tsx` | Plan step card | `planTitle` header, step status icons |
| `components/chat-view.tsx` | Chat assembly | TaskListCard mount (~2532), ContextPill pass (~2976) |

### Tests

| File | Tests |
|------|-------|
| `backend/tests/test_crawler_task_progress.py` | 3 CDD tests: tool label, crawler event emission, generic progress |
| `backend/tests/test_voice_tool_calling.py` | 4 voice tool tests (regression) |

---

## Key design decisions

| Decision | Rationale |
|----------|-----------|
| `listening_state: processing_tool` emitted by crawler, not agent | Agent doesn't know which tool is running; tool emits its own phase |
| `TASK_PROGRESS` with `update_step=True` only for crawler | Generic tools don't need per-page granularity; single step is enough |
| `task:start` emitted EARLY (before DER thread) | Prevents race where task:start and tool:call arrive together |
| `plan_title` generated by planner LLM | Agent chooses its own title based on steps, not raw user prompt |
| `plan_title` threaded through `execute_tool` → `_record_tool_event` | Tool executions are recallable by plan context in Immortus thread |
| Progress speaks are fire-and-forget, priority="low" | Never stalls the crawl; suppressed if TTS pipeline is busy |
| Mycelium `ingest_tool_call` only records toolpath nodes (not plan context) | Plan context in tool_path nodes is future work; FFI events carry it now |

---

*End of architecture document. For DER loop details, see `docs/DER_LOOP_MYCELIUM.md`. 
For topology layer, see `docs/mycelium-topology-v2.md`. For the implementation plan, 
see `docs/plans/2026-07-11-web-mode-voice-crawler-fix.md`.*
