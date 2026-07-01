# Agent Multi-Step Tool Execution — Gap Analysis

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
- Director → Reviewer (PASS/REFINE/VETO) → Explorer (execute tool) → repeat
- Loop condition: `while not queue.is_complete() and _tokens_used < _token_budget`
- Token budget: 15k for voice, 50k for full

**Critical limitation** — voice-first mode caps to **1 step** (line 3478):
```python
if task_class == "voice_first" and len(items) > 1:
    items = items[:1]
```

### Path B: Direct Response (`_respond_direct`, line 1723)

- Used for ~90% of messages (when `_needs_planning()` returns False)
- **No tool execution at all** — just LLM inference and text response
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

## 2. Permission System — Disconnected

### Backend: Exists but Unwired

- `PermissionRequestSystem` in `backend/vision/permission_system.py`
  - Has templates for automation permission levels: basic_automation, text_input, form_filling, navigation, advanced_interaction, system_ui
  - Can create, approve, deny permission requests
  - **Only wired for vision/GUI automation**, not general tool execution

- `CapabilitySet` in `backend/capabilities.py`
  - Binary mode switch: "personal" vs "developer"
  - Personal mode blocks repo/terminal tools
  - Developer mode allows everything
  - **No per-tool approval** — it's all-or-nothing based on mode

### Frontend: UI Exists but Goes Nowhere

- `chat-view.tsx` line 1565-1584: renders Allow/Deny buttons for `'permission'` type notifications
- `handlePermissionGrant/Deny` sends `notification_response` via WebSocket
- **No backend handler for `notification_response`** — the message is silently dropped

### Impact

The permission UI is decorative. Tools either execute or get blocked by `CapabilitySet` mode — there's no interactive approval flow. An agent cannot ask "should I run this?" and wait for user confirmation.

---

## 3. MCP — No Dynamic Discovery or Connection

### Built-in MCP Servers (Hardcoded)

In `tool_bridge.py` line 116-125, 8 servers are initialized at startup:
- Browser, AppLauncher, System, FileManager, GUIAutomation, GitHub, Vision, Internal
- All initialized at startup — no runtime discovery
- No way to add new MCP servers without code changes

### Marketplace Exists but is for OAuth Integrations

- `MarketplaceScreen.tsx`, `InstallConfirmModal.tsx` — show install confirm with permissions
- `IntegrationsContext.tsx` — stores marketplace preferences, gets recommendations
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
- Tool results are flattened into the text response — no structured display

---

## 5. Streaming and Tool Calls

### Current Behavior

In `backend/agent/streaming.py`:
- Streaming produces text chunks that are sent to the frontend in real-time
- When the LLM produces a tool_call, streaming stops, the tool executes, then a new stream begins with the tool result
- This creates a gap in the frontend where text stops flowing during tool execution

### Impact

The user sees the agent "freeze" during tool execution with no indication of what's happening. The streaming system doesn't pause/resume gracefully — it stops and restarts.

---

## 6. Root Cause Analysis

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

## 7. What Would Need to Change

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

## 8. Dependency Map

```
Domain 17 (Self-Coding Agent)
  ├── Requires: Agentic tool-call loop (multi-step execution)
  ├── Requires: Permission system wired (user approval for file writes)
  ├── Requires: MCP tool chain (file_manager, run_test, git_commit)
  └── Requires: Test-evaluate loop (run tests after edits)

Gate 1.8 (Tool calling with iris_local)
  └── Currently: DER loop can execute tools, but only pre-planned steps
      └── Gap: LLM can't dynamically choose tools mid-response

Long-horizon tasks (any domain)
  ├── Requires: Agentic tool-call loop
  ├── Requires: Permission system (interactive approval)
  └── Requires: Progress reporting (user sees what's happening)
```

---

## 9. Recommended Priority Order

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

## 10. Files Referenced

| File | Relevant Lines | What's There |
|------|---------------|--------------|
| `backend/agent/agent_kernel.py` | 1372-1430 | `_needs_planning()` keyword logic |
| `backend/agent/agent_kernel.py` | 1723-1823 | `_respond_direct()` — no tool execution |
| `backend/agent/agent_kernel.py` | 2306-2430 | DER loop with token budget |
| `backend/agent/agent_kernel.py` | 2620-2740 | Tool execution via `_tool_bridge.execute_tool()` |
| `backend/agent/agent_kernel.py` | 2850-2930 | Streaming response with agentic loop comment |
| `backend/agent/agent_kernel.py` | 3418-3538 | `_execute_plan_der()` — pre-planned steps |
| `backend/agent/agent_kernel.py` | 3478 | Voice-first 1-step cap |
| `backend/agent/streaming.py` | 55-185 | Streaming response generation |
| `backend/agent/tool_bridge.py` | 28-158 | MCP server initialization (8 hardcoded) |
| `backend/agent/tool_bridge.py` | 690-810 | `execute_tool()` — security + capability check |
| `backend/capabilities.py` | 1-120 | `CapabilitySet` — binary personal/developer mode |
| `backend/vision/permission_system.py` | 1-100 | `PermissionRequestSystem` — vision-only |
| `backend/gateway/security_filter.py` | 1-80 | Message sanitization + injection detection |
| `components/chat-view.tsx` | 20-90 | Notification types + state |
| `components/chat-view.tsx` | 1115-1145 | `handlePermissionGrant/Deny` — sends to WS |
| `components/chat-view.tsx` | 1555-1595 | Permission notification rendering (Allow/Deny) |
| `components/integrations/InstallConfirmModal.tsx` | 1-80 | Marketplace install confirm |
| `components/integrations/IntegrationsScreen.tsx` | 1-80 | Integrations + marketplace |
