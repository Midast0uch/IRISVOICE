# Agent Multi-Step Tool Execution â€” Gap Analysis

> Date: 2026-07-01
> Status: Investigation complete. No code changes made.
> Blocks: Domain 17 (Self-Coding Agent), Gate 1.8 verification, long-horizon tasks.

---

## Executive Summary

The agent kernel has infrastructure for multi-step tool execution (DER loop, tool bridge, capability gating) but **five critical gaps** prevent it from handling long-horizon tasks end-to-end. The most impactful: there is no standard agentic tool-call loop where the LLM dynamically decides which tools to call mid-response. The permission system exists in the UI but has no backend handler. MCP servers are hardcoded at startup with no dynamic discovery.

---

## 1. How Tool Calls Currently Work

The agent kernel has **two paths**, neither implements a true multi-step agentic loop:

### Path A: DER Loop (`_execute_plan_der`, line 3418)

- Pre-plans all steps via `_plan_task()` before execution begins
- Director â†’ Reviewer (PASS/REFINE/VETO) â†’ Explorer (execute tool) â†’ repeat
- Loop condition: `while not queue.is_complete() and _tokens_used < _token_budget`
- Token budget: 15k for voice, 50k for full

**Critical limitation** â€” voice-first mode caps to **1 step** (line 3478):
```python
if task_class == "voice_first" and len(items) > 1:
    items = items[:1]
```

### Path B: Direct Response (`_respond_direct`, line 1723)

- Used for ~90% of messages (when `_needs_planning()` returns False)
- **No tool execution at all** â€” just LLM inference and text response
- `_needs_planning()` is keyword-based (line 1391): triggers on words like "search", "open", "create", "run"
- Misses semantic tool needs that don't contain explicit trigger words

### What's Missing: Standard Agentic Tool-Call Loop

There is **no OpenAI-style tool-call loop** where:
1. LLM returns `tool_calls` in its response
2. System executes those tools
3. Results are fed back to the LLM
4. Loop continues until LLM produces a final text response

The DER loop pre-decides all steps upfront rather than letting the LLM dynamically decide which tools to call based on intermediate results.

---

## 2. Permission System â€” Disconnected

### Backend: Exists but Unwired

- `PermissionRequestSystem` in `backend/vision/permission_system.py`
  - Has templates for automation permission levels: basic_automation, text_input, form_filling, navigation, advanced_interaction, system_ui
  - Can create, approve, deny permission requests
  - **Only wired for vision/GUI automation**, not general tool execution

- `CapabilitySet` in `backend/capabilities.py`
  - Binary mode switch: "personal" vs "developer"
  - Personal mode blocks repo/terminal tools
  - Developer mode allows everything
  - **No per-tool approval** â€” it's all-or-nothing based on mode

### Frontend: UI Exists but Goes Nowhere

- `chat-view.tsx` line 1565-1584: renders Allow/Deny buttons for `'permission'` type notifications
- `handlePermissionGrant/Deny` sends `notification_response` via WebSocket
- **No backend handler for `notification_response`** â€” the message is silently dropped

### Impact

The permission UI is decorative. Tools either execute or get blocked by `CapabilitySet` mode â€” there's no interactive approval flow. An agent cannot ask "should I run this?" and wait for user confirmation.

---

## 3. MCP â€” No Dynamic Discovery or Connection

### Built-in MCP Servers (Hardcoded)

In `tool_bridge.py` line 116-125, 8 servers are initialized at startup:
- Browser, AppLauncher, System, FileManager, GUIAutomation, GitHub, Vision, Internal
- All initialized at startup â€” no runtime discovery
- No way to add new MCP servers without code changes

### Marketplace Exists but is for OAuth Integrations

- `MarketplaceScreen.tsx`, `InstallConfirmModal.tsx` â€” show install confirm with permissions
- `IntegrationsContext.tsx` â€” stores marketplace preferences, gets recommendations
- These are for email, messaging, and other OAuth-based integrations
- **The agent cannot request connecting a new MCP server**
- **The agent cannot discover what MCP servers are available**

### Impact

The agent is limited to the 8 hardcoded MCP servers. If a task requires a tool that isn't in those servers (e.g., a database query, a specific API), the agent cannot self-extend. It must rely on what was pre-built.

---

## 4. Frontend Handling of Tool Results

### What Exists

- `chat-view.tsx` has notification rendering with Allow/Deny buttons (line 1565-1584)
- `useIRISWebSocket.ts` forwards `notification` events as `iris:notification` CustomEvents
- Chat messages render tool results as part of the assistant response text

### What's Missing

- No dedicated UI for showing tool execution progress (spinning indicator, step counter)
- No visual distinction between "agent is thinking" vs "agent is executing tool X"
- No display of which tool was called, what arguments were passed, what result came back
- No retry/abort controls for in-progress tool calls
- Tool results are flattened into the text response â€” no structured display

---

## 5. Streaming and Tool Calls

### Current Behavior

In `backend/agent/streaming.py`:
- Streaming produces text chunks that are sent to the frontend in real-time
- When the LLM produces a tool_call, streaming stops, the tool executes, then a new stream begins with the tool result
- This creates a gap in the frontend where text stops flowing during tool execution

### Impact

The user sees the agent "freeze" during tool execution with no indication of what's happening. The streaming system doesn't pause/resume gracefully â€” it stops and restarts.

---

## 6. ConversationKernel/TaskKernel Separation (Deferred)

> **Status**: Designed. Not yet implemented.
> **Source**: `docs/plans/timing-sync-pipeline-overlap.md` â€” Phase 2
> **Depends on**: Phase 1 (timing/sync) verified working
> **Relates to**: Gap 1 (agentic tool-call loop), Gap 4 (frontend tool progress)

### Problem

LLM output currently flows through a single path â€” `iris_gateway.py` chunk_callback sends everything to TTS. Tool calls, planning steps, and conversation text all compete for the same channel. This creates two problems:

1. **TTS says tool-call content** â€” the agent reads JSON tool arguments aloud instead of executing them silently
2. **No UI distinction** â€” user can't tell if the agent is "thinking" vs "executing tool X" vs "reporting results"

### Proposed Architecture

```
Agent LLM Output
    â”œâ”€â”€ ConversationKernel (speech channel)
    â”‚   â”œâ”€â”€ Emits utterance events â†’ TTS subscribes
    â”‚   â”œâ”€â”€ Caducean-governed turn-taking (EXPAND = speak, COMPRESS = listen)
    â”‚   â”œâ”€â”€ Filler phrase selection during processing
    â”‚   â””â”€â”€ Status phrases during long tasks
    â”‚
    â””â”€â”€ TaskKernel (action/reasoning channel)
        â”œâ”€â”€ Emits tool-call events â†’ UI subscribes
        â”œâ”€â”€ Planning steps â†’ UI shows in dashboard
        â”œâ”€â”€ Tool execution â†’ UI shows progress
        â””â”€â”€ No audio output (never reaches TTS)
```

### Current State

- `ConversationKernel` exists (`backend/agent/conversation_kernel.py`) as a thin Caducean wrapper â€” TTS chunk sizing, barge-in nudge
- No `TaskKernel` exists
- No event bus â€” `chunk_callback` in `iris_gateway.py` (line 2195) directly appends to `sentence_buf`
- All LLM output goes to TTS regardless of type

### Implementation Files (When Ready)

| File | Change |
|------|--------|
| `backend/agent/event_bus.py` | **New** â€” IRISStreamEvent + EventBus class |
| `backend/agent/conversation_kernel.py` | Extend with utterance emission, filter speech from task content |
| `backend/agent/task_kernel.py` | **New** â€” Tool-call events, planning steps, progress |
| `backend/iris_gateway.py` | Route LLM output through kernel separation |
| `backend/agent/tts.py` | Subscribe to utterance events only (no tool calls) |

### Caducean Integration

The Caducean Engine governs the phase:
- **EXPAND (u â†’ +1)**: ConversationKernel active â€” agent speaks, reports results
- **COMPRESS (u â†’ -1)**: TaskKernel active â€” agent works, executes tools
- **Phase transition**: When TaskKernel completes a step, ConversationKernel emits a status phrase

Maps to existing `on_voice_state` in `conversation_kernel.py`:
- `RECORDING â†’ COMPRESS` (user speaking, agent listens)
- `IDLE â†’ EXPAND` (user finished, agent responds)
- `PROCESSING â†’ COMPRESS` (agent thinking/working, TaskKernel active)
- `SUCCESS â†’ EXPAND` (TTS playing, ConversationKernel active)

### Why This Matters for the Gap Analysis

| Existing Gap | How Kernel Separation Helps |
|-------------|---------------------------|
| Gap 1: No agentic tool-call loop | TaskKernel provides the event structure for tool-call/result cycle |
| Gap 4: No tool progress UI | TaskKernel emits events the frontend can subscribe to |
| Gap 5: Streaming gap during tool calls | TaskKernel handles tool execution channel, ConversationKernel stays silent |

### Deferral Reason

Phase 1 (timing/sync fixes) must be verified in live testing first. Kernel separation is an architecture change that touches the core LLMâ†’TTS pipeline. Better to confirm Phase 1 works before restructuring.

---

## 7. Root Cause Analysis

| Gap | Root Cause | Severity |
|-----|-----------|----------|
| No agentic tool-call loop | DER loop pre-plans all steps; no dynamic LLM-driven tool selection | **Critical** |
| Permission system disconnected | `notification_response` has no backend handler | **High** |
| MCP static | No agent-facing API for discovery/install | **High** |
| Voice-first 1-step cap | Speed optimization blocks multi-step voice tasks | **Medium** |
| Keyword-based planning trigger | `_needs_planning()` uses string matching, not semantic understanding | **Medium** |
| No tool progress UI | Frontend treats tool calls as opaque text | **Medium** |
| No structured tool result display | Results flattened into text response | **Low** |

---

## 8. What Would Need to Change

### For True Multi-Step Long-Horizon Tasks

1. **Implement agentic tool-call loop** in the streaming response path:
   - Process `tool_calls` from LLM response
   - Execute tools, feed results back
   - Continue until LLM produces final text response
   - Respect token budget and max iteration limits

2. **Wire permission backend handler**:
   - Handle `notification_response` WebSocket messages
   - Pause tool execution until user approves/denies
   - Add timeout (auto-deny after N seconds for non-critical tools)

3. **Add MCP discovery API**:
   - Agent-callable endpoint to list available MCP servers
   - Agent-callable endpoint to request connecting a new server
   - Integration with marketplace for discovery

4. **Remove or configurable 1-step cap**:
   - Allow multi-step voice tasks when user explicitly requests
   - Or add a "deep work" mode that bypasses the cap

5. **Make planning trigger semantic**:
   - Replace keyword matching with LLM-based intent classification
   - Or use a small classifier model that runs before the main LLM

6. **Add tool progress UI**:
   - Show which tool is executing
   - Show step count (step 3 of 7)
   - Allow abort/cancel

7. **Structured tool result display**:
   - Render tool calls in a distinct UI component
   - Show arguments and results separately
   - Allow expand/collapse for long results

---

## 9. Dependency Map

```
Domain 17 (Self-Coding Agent)
  â”œâ”€â”€ Requires: Agentic tool-call loop (multi-step execution)
  â”œâ”€â”€ Requires: Permission system wired (user approval for file writes)
  â”œâ”€â”€ Requires: MCP tool chain (file_manager, run_test, git_commit)
  â””â”€â”€ Requires: Test-evaluate loop (run tests after edits)

Gate 1.8 (Tool calling with iris_local)
  â””â”€â”€ Currently: DER loop can execute tools, but only pre-planned steps
      â””â”€â”€ Gap: LLM can't dynamically choose tools mid-response

Long-horizon tasks (any domain)
  â”œâ”€â”€ Requires: Agentic tool-call loop
  â”œâ”€â”€ Requires: Permission system (interactive approval)
  â””â”€â”€ Requires: Progress reporting (user sees what's happening)

Kernel Separation (Phase 2 of timing plan)
  â”œâ”€â”€ Depends on: Phase 1 (timing/sync) verified working
  â”œâ”€â”€ Enables: TaskKernel events for tool-call/result cycle
  â”œâ”€â”€ Enables: Frontend subscribes to tool progress events
  â””â”€â”€ Enables: TTS only receives speech (not tool calls)
```

---


## 10. Recommended Priority Order

| # | Change | Effort | Impact |
|---|--------|--------|--------|
| 1 | Agentic tool-call loop in streaming path | Large | Unblocks everything |
| 2 | Wire `notification_response` backend handler | Small | Enables interactive approval |
| 3 | Tool progress WS events + frontend display | Medium | User sees what's happening |
| 4 | Make `_needs_planning()` semantic | Medium | More requests trigger tools |
| 5 | Remove voice 1-step cap (configurable) | Small | Voice tasks can be multi-step |
| 6 | MCP discovery API | Large | Agent can self-extend |
| 7 | Structured tool result display | Medium | Better UX for tool outputs |

---

## 11. Files Referenced

| File | Relevant Lines | What's There |
|------|---------------|--------------|
| `backend/agent/agent_kernel.py` | 1372-1430 | `_needs_planning()` keyword logic |
| `backend/agent/agent_kernel.py` | 1723-1823 | `_respond_direct()` â€” no tool execution |
| `backend/agent/agent_kernel.py` | 2306-2430 | DER loop with token budget |
| `backend/agent/agent_kernel.py` | 2620-2740 | Tool execution via `_tool_bridge.execute_tool()` |
| `backend/agent/agent_kernel.py` | 2850-2930 | Streaming response with agentic loop comment |
| `backend/agent/agent_kernel.py` | 3418-3538 | `_execute_plan_der()` â€” pre-planned steps |
| `backend/agent/agent_kernel.py` | 3478 | Voice-first 1-step cap |
| `backend/agent/streaming.py` | 55-185 | Streaming response generation |
| `backend/agent/tool_bridge.py` | 28-158 | MCP server initialization (8 hardcoded) |
| `backend/agent/tool_bridge.py` | 690-810 | `execute_tool()` â€” security + capability check |
| `backend/capabilities.py` | 1-120 | `CapabilitySet` â€” binary personal/developer mode |
| `backend/vision/permission_system.py` | 1-100 | `PermissionRequestSystem` â€” vision-only |
| `backend/gateway/security_filter.py` | 1-80 | Message sanitization + injection detection |
| `components/chat-view.tsx` | 20-90 | Notification types + state |
| `components/chat-view.tsx` | 1115-1145 | `handlePermissionGrant/Deny` â€” sends to WS |
| `components/chat-view.tsx` | 1555-1595 | Permission notification rendering (Allow/Deny) |
| `components/integrations/InstallConfirmModal.tsx` | 1-80 | Marketplace install confirm |
| `components/integrations/IntegrationsScreen.tsx` | 1-80 | Integrations + marketplace |


## 12. Per-Thread Conversation Context (New Gap)

> **Date identified**: 2026-07-04
> **Status**: New conversation fix implemented. Thread switching not yet handled.
> **Blocks**: Switching between existing conversation threads while using STT.

### Problem

The agent kernel stores conversation history keyed by `session_id` (the WebSocket connection's session â€” never changes for a single user session). When the user switches between conversation threads in the frontend:

1. No backend message is sent about the switch
2. `voice_command_start` sends `{}` â€” no `conversation_id` is included
3. The agent kernel always uses the WS `session_id` for context
4. All conversation threads share the same agent context

### Current Fix (July 4)

`new_conversation` now calls `agent_kernel.clear_conversation()`. This handles the **"start a new conversation"** case â€” the next STT command starts fresh.

### Remaining Gap: Thread Switching

Switching to an **existing** conversation thread (e.g., clicking a different conversation in the sidebar) doesn't restore that thread's context because:

- The frontend never tells the backend which thread is active
- The backend stores context by `session_id`, not `conversation_id`
- No mechanism exists to save/restore per-thread contexts

### Required Changes

| Layer | Change |
|-------|--------|
| Frontend | Send `switch_conversation { conversation_id }` when user selects a different thread |
| Frontend | Include `conversation_id` in `voice_command_start` payload |
| Backend | Accept `conversation_id` in voice command handler |
| Backend | Agent kernel stores/retrieves context by `conversation_id` instead of (or alongside) `session_id` |

### Files Referenced

| File | Relevant Lines | What's There |
|------|---------------|--------------|
| `backend/iris_gateway.py` | 1783-1830 | `voice_command_start` handler â€” no `conversation_id` |
| `backend/iris_gateway.py` | 3578-3615 | `_handle_chat` â€” `new_conversation` handler added |
| `backend/agent/agent_kernel.py` | 80-133 | `session_id` as context key |
| `backend/agent/agent_kernel.py` | 2616-2624 | `process_text_message(session_id=)` |
| `components/chat-view.tsx` | 787-790 | `handleSelectConversation` â€” no backend message |
| `hooks/useIRISWebSocket.ts` | 1285-1295 | `voice_command_start` â€” sends `{}` |

---