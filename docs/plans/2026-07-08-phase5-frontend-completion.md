# Phase 5 Frontend Completion — Execution Plan

> Date: 2026-07-08
> Branch: `feat/agent-multi-step-tool-execution`
> Parent plan: `docs/plans/2026-07-06-agent-multi-step-tool-execution.md` (Phase 5)
> Architecture: `docs/architecture/agent-multi-step-architecture.md` (§8, §9)
> Status: Ready to execute. Self-contained — an agent can carry this out without re-investigation.

---

## 0. How to Use This Plan

This plan is **self-contained**. Every fact an executing agent needs is recorded below with file paths and line references. Do NOT re-investigate from scratch — trust the evidence in §2. If something contradicts, stop and re-verify that specific point only.

**Build order is mandatory:** Tasks 1–2 (backend event delivery) before Tasks 3–9 (frontend). The frontend components are useless without the backend bridge.

**Testing discipline (from parent plan, absolute):**
- Write new target/behavioral tests for every new component. Test files listed in §8 do not exist yet — create them.
- Never modify an existing test to make it pass. The test is the requirement.
- Run the full target test suite per task, not just the ones you know pass.

**Quality check (AGENTS.md) before every test run:**
- [ ] No unnecessary work in hot paths
- [ ] Heavy imports lazy
- [ ] Error handling complete on every exception path
- [ ] Resources cleaned up
- [ ] No shared mutable state across sessions
- [ ] Memory bounded (no unbounded caches/queues)
- [ ] Async/sync boundary correct (no blocking calls in async hot paths)
- [ ] Structured logging with context identifier
- [ ] Nothing here can crash and block a user response

---

## 1. Goal

Complete Phase 5 of the multi-step branch: the three missing frontend components (OrbBadge, TaskListCard, ContextPill) and the event plumbing that makes them work end-to-end. This closes the gap discovered in review: the backend emits task/question/permission events on the EventBus, but nothing delivers them to the WebSocket, and the frontend components that would render them were never created.

**Scope is strictly Phase 5 + the minimum backend wiring to feed it.** Do not touch the DER loop, audio pipeline, Caducean engine, Mycelium, or Tauri Rust layer.

---

## 2. Evidence — What Exists vs. What's Missing (verified 2026-07-08)

### 2.1 Frontend components — existence

| File | Status | Evidence |
|------|--------|----------|
| `components/iris/OrbBadge.tsx` | ❌ MISSING | glob empty; grep "OrbBadge" across *.tsx = 0 matches |
| `components/chat/TaskListCard.tsx` | ❌ MISSING | glob empty |
| `components/chat/ContextPill.tsx` | ❌ MISSING | glob empty |
| `components/chat/PermissionCard.tsx` | ✅ EXISTS, fixed | 9/10 review issues fixed (relative+fresnel, backdrop blur, full theme, rounded-lg, accent strip, font sizes, CSS hover, consistent rgba) |
| `components/chat/QuestionCard.tsx` | ✅ EXISTS, fixed | hover/focus feedback added, color syntax consistent |

### 2.2 Frontend event wiring — already done

- `hooks/useIRISWebSocket.ts` **already forwards** question + permission events:
  - `permission:request/granted/denied` → `iris:permission_*` CustomEvents (lines ~1155–1165)
  - `question:ask/answered/timeout` → `iris:question_*` CustomEvents (lines ~1167–1177)
- `components/chat-view.tsx` **already listens**:
  - `iris:permission_request` (lines ~569–571) → renders `PermissionCard` (line 2405), `onApprove`→`sendMessage('notification_response', {notification_id, action:'grant'})`, `onDeny`→action:'deny', `onConfirm`→action:'confirm'
  - `iris:question_ask/answered/timeout` (lines ~608–610) → renders `QuestionCard` (line 2439), `onAnswer`→`sendMessage('question_response', {question_id, answer})`
- `backend/iris_gateway.py` **already handles** the response side: `notification_response` (line ~4166), `question_response` (line ~4182)

→ The **question and permission flows are fully wired on the frontend**. The only break is backend→frontend delivery (no bus→WS bridge). Fix that and those two flows work end-to-end.

### 2.3 Frontend event wiring — MISSING

- `hooks/useIRISWebSocket.ts` does **NOT** forward `task:start`/`task:progress`/`task:milestone`/`task:done`/`task:fail` (grep: 0 matches). TaskListCard and OrbBadge have no event source.
- No `iris:context_usage` forwarding exists. ContextPill has no event source.

### 2.4 Backend event system — facts

- `backend/agent/event_bus.py` defines `IRISStreamEvent` enum. Frontend-relevant values:
  - `TASK_START="task:start"`, `TASK_PROGRESS="task:progress"`, `TASK_MILESTONE="task:milestone"`, `TASK_DONE="task:done"`, `TASK_FAIL="task:fail"`
  - `TOOL_CALL="tool:call"`, `TOOL_RESULT="tool:result"`, `TOOL_ERROR="tool:error"`
  - `QUESTION_ASK="question:ask"`, `QUESTION_ANSWERED="question:answered"`, `QUESTION_TIMEOUT="question:timeout"`
  - `PERMISSION_REQUEST="permission:request"`, `PERMISSION_GRANTED="permission:granted"`, `PERMISSION_DENIED="permission:denied"`
  - `MODE_CHANGED="mode:changed"`
  - **There is NO `context_usage` event.** Task 2 adds it.
- `IRISStreamEvent` dataclass fields: `type`, `payload` (dict), `turn_id`, `conversation_id`, `timestamp`, and `session_id` (carried in `payload` dict — confirmed: `task_kernel.py` reads `payload.session_id`/`payload.conversation_id`).
- `EventBus` is a singleton via `get_event_bus()`. `emit(event)` delivers to subscribers; `subscribe(event_type, handler)` returns a sub id; errors in one handler do not block others.

### 2.5 Backend → frontend delivery — the core gap

- **The EventBus is internal-only.** Nothing forwards bus events to the WebSocket. Grep for the literal event-type strings (`"question:ask"`, `"permission:request"`, `"task:start"`, …) finds them **only** in `event_bus.py` (enum), `task_kernel.py` (its `ws_sender` path), and tests — never in a `broadcast_to_session` call.
- Frontend delivery today is done by **direct `broadcast_to_session`/`broadcast` calls inline** (~50 sites in `iris_gateway.py`). Examples:
  - `tool_bridge.py:881` — broadcasts `tool_result` directly (the existing tool-result delivery)
  - `main.py:998` — `await ws.broadcast({"type": "mode_changed", "mode": mode})`
- `backend/agent/task_kernel.py` has a `ws_sender` path (`_emit_frontend` calls `self._ws_sender(event_type, payload_data)`), but `set_task_kernel()` is **never called in production** (only tests) → task events emitted on the bus have no WS-forwarding subscriber.
- `backend/agent/tools/ask_user_tool.py` emits `QUESTION_ASK` on the bus (line ~89) — never broadcast to WS.
- `backend/agent/permissions.py` emits `PERMISSION_REQUEST` on the bus (line ~297) — never broadcast to WS.

→ **Task 1 builds a single bus→WS bridge** that subscribes to the frontend-relevant events and broadcasts them. This fixes task, question, AND permission delivery in one place.

### 2.6 WS broadcast API (the contract)

- `backend/ws_manager.py`:
  - `async def broadcast(self, message: dict, exclude_clients=None)` — line 311, sends to ALL clients
  - `async def broadcast_to_session(self, session_id: str, message: dict, exclude_clients=None)` — line 332, sends to one session
- Message shape: `{"type": "<event.value>", "payload": {…}}`
- **Async-from-sync pattern** (emit sites are sync; broadcast is async): `backend/utils/observability.py:187` — `loop.create_task(ws.broadcast_to_session(session_id, payload))`. Use this pattern in the bridge.

### 2.7 Orb design language (for OrbBadge — locked)

- `components/iris/XurOrb.tsx`: 120px container (`CONTAINER_SIZE`), `orbRef` div is `position: relative` + `overflow: visible` (overlays may extend outside the 120px box). Draggable via `useManualDragWindow`.
- `components/iris/orb/OrbCanvas.tsx`: 120px canvas, 3 particle shells (105/70/42% scale), `globalCompositeOperation = 'lighter'`, central white core, breath halos — all in `glowColor`. Tiny additive-glow particles. **Not** shapes/chips.
- Three labels at 45px radius, always visible at idle: **Chat (bottom, y+45)**, **Menu (top, y−45)**, **Voice (left, x−45, y+20)**. → Only label-free zones: **top-right, right, bottom-right**.
- Voice haze: `radial-gradient(circle, ${glowColor}22, transparent 70%)` at `inset:-60`.
- Orb-adjacent text: `'Courier New', Courier, monospace`, 11px, weight 700, `letter-spacing: 0.12em`, uppercase, `textShadow: 0 0 16px ${glowColor}55, 0 0 4px ${glowColor}88`.
- `glowColor` from `getThemeConfig().glow.color` (aether = `#00c8ff`); `shimmer.primary/secondary/accent`, `glass.opacity/blur/borderOpacity` also available (see `contexts/BrandColorContext.tsx`).
- The orb itself is **pure canvas particles, NOT glass**. Glass treatment (`rgba(10,11,22,…)` + `backdropFilter` + `borderLeft`) belongs to chat cards only. **OrbBadge must be particle/glow, not a glass chip.**

### 2.8 Layout state (OrbBadge visibility gate)

- `hooks/useUILayoutState.ts`: `UILayoutState.UI_STATE_IDLE` = wings closed (orb-only). `UI_STATE_CHAT_OPEN` / `UI_STATE_BOTH_OPEN` / `UI_STATE_DASHBOARD_OPEN` = wings open.
- OrbBadge shows **only when `uiState === UI_STATE_IDLE`** AND (task working OR pending question). When wings open, the badge hides (the full TaskListCard/QuestionCard is visible in chat-view).

### 2.9 XurOrb integration point

- `components/iris/types.ts`: `XurOrbProps` has `glowColor?: string`, `uiState?: UILayoutState`, `onClick`, `onDoubleClick`, etc.
- OrbBadge renders **inside XurOrb's `orbRef` container** (relative, overflow visible), absolutely positioned. XurOrb already opens wings on click — OrbBadge is purely visual; no new click handler.

### 2.10 Test/config

- `package.json` scripts: `lint` = `eslint .`; `test` = `node --experimental-vm-modules node_modules/jest/bin/jest.js`; type check = `npx tsc --noEmit`.
- Plan's Phase 5 test files (§8) **do not exist** — create them.
- Path alias: `@/` → repo root (e.g. `@/contexts/...`, `@/hooks/...`).

---

## 3. Locked Design Decisions (from user consultation 2026-07-08)

| # | Decision | Choice |
|---|----------|--------|
| D1 | OrbBadge visual style | **Particle pip** — glowing dot/ring in `glowColor` via radial gradient + `lighter` blend (matches OrbCanvas particles), counter in the orb's monospace label font. No flat Material badges. |
| D2 | OrbBadge position | **Top-right** of the 120px orb, just outside the shell edge (~radius 55px, angle −45°). Only fully label-free corner. |
| D3 | OrbBadge content | **Dot at rest, counter when working.** Quiet glowing pip while idle; expands to show `2/5` while a task is actively progressing. Question state = same pip with `?` glyph + distinct pulse. |
| D4 | Build scope | **Full Phase 5** — OrbBadge + TaskListCard + ContextPill + WS event forwarding + backend bus→WS bridge + XurOrb/chat-view integration. |
| D5 | Backend delivery | **Single bus→WS bridge** (`ws_event_bridge.py`) rather than per-emit-site direct broadcasts. Centralizes task/question/permission delivery. Must NOT double-broadcast `tool_result` (already direct at `tool_bridge.py:881`) or `mode_changed` (already direct at `main.py:998`). |

---

## 4. Out-of-Bounds Guardrails (do NOT do these)

1. **Do not touch the DER loop logic** (`agent_kernel.py` planning/execution). Only ADD a `CONTEXT_USAGE` emit at the existing `_tokens_used` update site (Task 2). No mode/budget changes.
2. **Do not touch the audio pipeline, Caducean engine, Mycelium, or Tauri Rust layer.**
3. **Do not double-broadcast.** The bridge must skip `TOOL_RESULT` and `MODE_CHANGED` (already delivered directly).
4. **Do not modify existing tests to pass.** Update stale tests only if they assert the old contract that this work changes (none expected here — this work is additive).
5. **Do not change `PermissionCard`/`QuestionCard`** — they are already fixed (9/10 issues done; the 10th is OrbBadge, separate).
6. **Do not re-key the agent kernel** (Phase 1, already done) or alter `conversation_id` keying.
7. **Do not add OS toast notifications** — the orb badge is the only background-task indicator (per architecture §8.3).
8. **Do not make OrbBadge a glass chip** — it must match the orb's canvas-particle language (D1).
9. **Do not block the DER loop** in the bridge — bridge handlers must be fire-and-forget (`create_task`), never `await`ed inline.
10. **Do not introduce unbounded state** — task step lists and question state must be bounded and cleared on task done/fail.

---

## 5. Task Breakdown

### Task 1 — Backend: bus→WS bridge

**New file:** `backend/agent/ws_event_bridge.py`

Purpose: subscribe to frontend-relevant EventBus events and broadcast `{"type": event.type.value, "payload": event.payload}` to the WebSocket.

**Spec:**
```python
# backend/agent/ws_event_bridge.py
"""Bridge: EventBus frontend-relevant events → WebSocket delivery.

The EventBus is internal-only. This component subscribes to the events the
frontend needs and broadcasts them to the WS. It is the single delivery path
for task/question/permission events.

Exclusions (already delivered directly — DO NOT re-forward):
  - TOOL_RESULT  (tool_bridge.py:881 broadcasts directly)
  - MODE_CHANGED  (main.py:998 broadcasts directly)
"""
import asyncio, logging
from typing import Optional
from .event_bus import get_event_bus, IRISStreamEvent

logger = logging.getLogger(__name__)

# Events the bridge forwards to the frontend.
_BRIDGED_EVENTS = (
    IRISStreamEvent.TASK_START,
    IRISStreamEvent.TASK_PROGRESS,
    IRISStreamEvent.TASK_MILESTONE,
    IRISStreamEvent.TASK_DONE,
    IRISStreamEvent.TASK_FAIL,
    IRISStreamEvent.TOOL_CALL,
    IRISStreamEvent.TOOL_ERROR,
    IRISStreamEvent.QUESTION_ASK,
    IRISStreamEvent.QUESTION_ANSWERED,
    IRISStreamEvent.QUESTION_TIMEOUT,
    IRISStreamEvent.PERMISSION_REQUEST,
    IRISStreamEvent.PERMISSION_GRANTED,
    IRISStreamEvent.PERMISSION_DENIED,
    # CONTEXT_USAGE added in Task 2 — add to this tuple after Task 2
)


class WSEventBridge:
    """Subscribes to EventBus events and broadcasts them to the WebSocket.

    Fire-and-forget: handlers schedule the async broadcast via create_task and
    return immediately. Never blocks the DER loop.
    """

    def __init__(self, ws_manager, loop: asyncio.AbstractEventLoop):
        self._ws = ws_manager
        self._loop = loop
        self._bus = get_event_bus()
        self._sub_ids: list[str] = []

    def start(self):
        for evt in _BRIDGED_EVENTS:
            sid = self._bus.subscribe(evt, self._make_handler(evt))
            self._sub_ids.append(sid)
        logger.info("[WSEventBridge] subscribed to %d event types", len(self._sub_ids))

    def stop(self):
        for sid in self._sub_ids:
            try: self._bus.unsubscribe(sid)
            except Exception: pass
        self._sub_ids.clear()

    def _make_handler(self, evt):
        def handler(event):
            try:
                payload = dict(event.payload or {})
                session_id = payload.get("session_id")
                msg = {"type": evt.value, "payload": payload}
                if session_id:
                    self._loop.create_task(self._ws.broadcast_to_session(session_id, msg))
                else:
                    # No session routing info — broadcast to all (IRIS is single-user).
                    self._loop.create_task(self._ws.broadcast(msg))
            except Exception as e:
                logger.warning("[WSEventBridge] %s forward failed: %s", evt.value, e)
        return handler
```

**Instantiation:** In the gateway startup, where the WS manager and event loop are available. Find the existing startup in `backend/iris_gateway.py` (or `backend/main.py`) where `get_websocket_manager()` and the running loop are ready. Add:
```python
from .agent.ws_event_bridge import WSEventBridge
# after ws_manager is ready and loop is running:
self._ws_bridge = WSEventBridge(self._ws_manager, asyncio.get_event_loop())
self._ws_bridge.start()
```
- If the gateway is constructed before the loop runs, defer `start()` to an async startup hook (use `asyncio.get_event_loop()` inside an async context). Match the existing pattern used for other async-setup in the gateway.
- Call `stop()` on shutdown if a shutdown hook exists; otherwise it's process-lifetime.

**Quality:**
- Handlers are fire-and-forget (`create_task`, never `await`). DER loop never blocks.
- `try/except` per handler — one bad payload never breaks others.
- No unbounded state — no buffers; pure forward.
- Bounded subscriber list (fixed tuple).

**Test:** `backend/tests/contract/test_ws_event_bridge.py`
- Contract: emits `TASK_START` on bus → `broadcast_to_session` called with `{"type":"task:start","payload":{...,"session_id":"s1"}}`.
- Contract: `TOOL_RESULT` is NOT forwarded (skip). `MODE_CHANGED` NOT forwarded.
- Contract: handler exception does not raise (swallowed + logged).
- Contract: no `session_id` → `broadcast` (all) called.

---

### Task 2 — Backend: CONTEXT_USAGE event + emission

**Edit:** `backend/agent/event_bus.py`
- Add to `IRISStreamEvent`: `CONTEXT_USAGE = "context:usage"`
- Add `CONTEXT_USAGE` to `_BRIDGED_EVENTS` in `ws_event_bridge.py` (Task 1).

**Edit:** `backend/agent/agent_kernel.py`
- Find the existing `_tokens_used` / `_token_budget` update site in the DER loop (the parent plan cites lines ~2306–2430; `_tokens_used` is incremented per step). After the increment, emit:
```python
from .event_bus import get_event_bus, IRISStreamEvent
# after _tokens_used update:
get_event_bus().emit(IRISStreamEvent(
    type=IRISStreamEvent.CONTEXT_USAGE,
    payload={
        "used_tokens": int(self._tokens_used),
        "max_tokens": int(self._token_budget),
        "session_id": session_id,
        "conversation_id": conversation_id,
        "turn_id": turn_id,
    },
    turn_id=turn_id,
    conversation_id=conversation_id,
    timestamp=time.time(),
))
```
- Emit at most once per step (not per token). Guard with the existing per-step boundary.
- **Do not** change budget/mode logic. This is a read-only emit of existing values.

**Quality:** emit is best-effort (`try/except` around it); a failure must never block the DER loop.

**Test:** `backend/tests/contract/test_context_usage_emit.py`
- Contract: after a step, a `CONTEXT_USAGE` event is on the bus with `used_tokens`/`max_tokens`/`session_id`.

---

### Task 3 — Frontend: `useTaskProgress` + `useAgentQuestion` hooks

**New file:** `hooks/useTaskProgress.ts`

Centralizes task state from `iris:task_update` CustomEvents. Consumed by XurOrb (OrbBadge) and chat-view (TaskListCard).

```ts
"use client"
import { useState, useEffect, useCallback, useRef } from "react"

export interface TaskStep {
  id: string
  description: string
  status: "pending" | "working" | "done" | "skipped" | "vetoed" | "fail"
  toolName?: string
  resultPreview?: string
}
export interface TaskProgress {
  isWorking: boolean
  currentStep: number
  totalSteps: number
  steps: TaskStep[]
  mode?: string
  turnId?: string
}

export function useTaskProgress(): TaskProgress {
  const [state, setState] = useState<TaskProgress>({ isWorking: false, currentStep: 0, totalSteps: 0, steps: [] })
  const ref = useRef(state)
  ref.current = state

  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent
      const d = ce.detail || {}
      // d.type is one of task:start/progress/milestone/done/fail
      // Update steps + isWorking accordingly. On done/fail → isWorking=false (keep steps until next task:start).
      // Bounded: cap steps at 50.
    }
    window.addEventListener("iris:task_update", handler)
    return () => window.removeEventListener("iris:task_update", handler)
  }, [])

  return state
}
```

- The WS hook (Task 4) dispatches a single `iris:task_update` CustomEvent for all `task:*` types, with `detail = { type, ...payload }`. This hook reduces that to `TaskProgress`.
- **Bound:** `steps` capped at 50 entries; on `task:start` reset steps to the new plan.
- **Clears:** `task:done`/`task:fail` set `isWorking=false` (steps retained for display until next `task:start`).

**New file:** `hooks/useAgentQuestion.ts`

Lifts pending-question state for the orb (chat-view already has its own `pendingQuestions`; this hook is a lightweight read for XurOrb).

```ts
"use client"
import { useState, useEffect } from "react"
export interface AgentQuestionState { hasPendingQuestion: boolean; questionId?: string }
export function useAgentQuestion(): AgentQuestionState {
  const [s, setS] = useState<AgentQuestionState>({ hasPendingQuestion: false })
  useEffect(() => {
    const onAsk = (e: Event) => setS({ hasPendingQuestion: true, questionId: (e as CustomEvent).detail?.questionId })
    const onDone = () => setS({ hasPendingQuestion: false })
    window.addEventListener("iris:question_ask", onAsk)
    window.addEventListener("iris:question_answered", onDone)
    window.addEventListener("iris:question_timeout", onDone)
    return () => { window.removeEventListener("iris:question_ask", onAsk); window.removeEventListener("iris:question_answered", onDone); window.removeEventListener("iris:question_timeout", onDone) }
  }, [])
  return s
}
```

**Test:** `__tests__/hooks/useTaskProgress.test.tsx`, `__tests__/hooks/useAgentQuestion.test.tsx` — dispatch CustomEvents, assert state transitions + bounds + cleanup.

---

### Task 4 — Frontend: WS hook forwards `task:*` + `context:usage`

**Edit:** `hooks/useIRISWebSocket.ts`

In the message-type switch (where `permission:request` and `question:ask` are already handled, lines ~1155–1177), add:

```ts
case "task:start":
case "task:progress":
case "task:milestone":
case "task:done":
case "task:fail":
  window.dispatchEvent(new CustomEvent("iris:task_update", { detail: { type: msg.type, ...msg.payload } }))
  break
case "context:usage":
  window.dispatchEvent(new CustomEvent("iris:context_usage", { detail: msg.payload }))
  break
```

- Match the existing dispatch style exactly (see how `iris:question_ask` is dispatched — same `CustomEvent` pattern, same `seenTurnIds` dedup if used for those).
- Do NOT alter existing `permission:*`/`question:*`/`tool_result` handling.
- Do NOT forward `tool:call`/`tool:error` unless TaskListCard needs them (decide in Task 6; if not needed, leave them unforwarded to avoid noise).

**Test:** `__tests__/hooks/useIRISWebSocket.test.ts` (extend existing if present, else new) — feed a `task:progress` WS message, assert `iris:task_update` CustomEvent fired with correct detail.

---

### Task 5 — Frontend: `OrbBadge` component

**New file:** `components/iris/OrbBadge.tsx`

**Props:**
```ts
interface OrbBadgeProps {
  isVisible: boolean
  variant: "working" | "question"
  currentStep?: number   // for working
  totalSteps?: number    // for working
  glowColor: string
}
```

**Render (inside XurOrb's `orbRef` — absolute positioning):**
- Container: `position: absolute`, top-right of the 120px orb. Compute position: center is (60,60); place at ~(60 + 40, 60 − 40) = (100, 20) within the 120px box, i.e. `style={{ top: 14, right: 14 }}` (tune so it sits just outside the shell edge, clear of the top Menu label which is at y−45 and the right edge has no label).
- **Particle pip:** a radial-gradient dot in `glowColor` with `mixBlendMode: 'lighter'` (matches OrbCanvas additive glow). ~10px dot, `boxShadow: 0 0 12px ${glowColor}, 0 0 4px ${glowColor}`.
- **Working state (variant=working):** when `currentStep` and `totalSteps` are present and `isWorking`, expand to show `"{currentStep}/{totalSteps}"` in the orb's monospace label style (`'Courier New', monospace`, 11px, weight 700, `letter-spacing: 0.12em`, uppercase, `textShadow: 0 0 16px ${glowColor}55, 0 0 4px ${glowColor}88`). Use `shimmer.primary` (brightened brand) while working; plain `glowColor` at rest.
- **Question state (variant=question):** show `?` glyph in the same monospace glow style; distinct pulse (slower, larger amplitude).
- **Pulse:** framer-motion `animate` on scale + opacity. Working = faster cadence (e.g. scale 1→1.15, opacity 0.7→1, duration 0.8s repeat). Question = slower (duration 1.4s).
- **No glass, no flat chip.** Pure glow + monospace text.
- Clicking does nothing (the orb's existing onClick opens wings). The badge is `pointer-events: none` so it never intercepts the orb's drag/click.

**Visibility:** `isVisible` is computed by XurOrb (Task 8): `uiState === UI_STATE_IDLE && (taskProgress.isWorking || agentQuestion.hasPendingQuestion)`.

**Test:** `__tests__/components/OrbBadge.test.tsx` — renders when visible; hidden when not; shows `2/5` in working variant; shows `?` in question variant; matches snapshot of particle style (no glass classes); pointer-events none.

---

### Task 6 — Frontend: `TaskListCard` component

**New file:** `components/chat/TaskListCard.tsx`

**Props:**
```ts
interface TaskListCardProps {
  steps: TaskStep[]      // from useTaskProgress
  turnId?: string
  mode?: string
  defaultCollapsed?: boolean
}
```

**Render (inline in chat stream — same mount point as PermissionCard/QuestionCard, see chat-view.tsx lines 2402–2454):**
- Dark glass background matching PermissionCard/QuestionCard: `rgba(10,11,22,0.6)` + `backdropFilter: blur(20px)` + `borderLeft: 2px solid ${glowColor}` + fresnel edge + `rounded-lg` + `relative` on the inner container.
- Title/objective row + ordered step list. Each step: description, status icon (pending/working/done/skipped/vetoed/fail), tool name, expandable result preview.
- Live updates: subscribe to `iris:task_update` CustomEvent directly (or accept `steps` prop from chat-view which uses `useTaskProgress`). Prefer prop-from-chat-view to keep one source of truth.
- Collapsible (collapsed by default if >4 steps). Use framer-motion `AnimatePresence` for expand/collapse, matching SuggestionPills enter/exit (`y:8, scale:0.98`).
- Monospace step labels (orb label font), brand-color accents.
- **Bound:** render at most 50 steps.

**Test:** `__tests__/components/TaskListCard.test.tsx` — renders steps; live update changes status; collapse/expand; bounded at 50.

---

### Task 7 — Frontend: `ContextPill` component

**New file:** `components/chat/ContextPill.tsx`

**Props:**
```ts
interface ContextPillProps {
  usedTokens: number
  maxTokens: number
  phase: string   // idle/listening/thinking/working/speaking
}
```

**Render (chat header, next to phase indicator):**
- `12.4k / 128k` (format tokens as `k` with one decimal).
- Thin progress bar underneath. Color: green (<60%) → amber (60–85%) → red (>85%).
- Phase indicator next to it.
- Subscribe to `iris:context_usage` CustomEvent for `usedTokens`/`maxTokens`. Phase comes from existing voiceState/spotlight state (chat-view passes it).
- Monospace font (orb label style) for the token count; small, unobtrusive.

**Test:** `__tests__/components/ContextPill.test.tsx` — token format; color thresholds (green/amber/red); updates on `iris:context_usage` event.

---

### Task 8 — Frontend: XurOrb integration (render OrbBadge)

**Edit:** `components/iris/XurOrb.tsx`

- Import `OrbBadge`, `useTaskProgress`, `useAgentQuestion`.
- Inside the `orbRef` container (the `relative` + `overflow: visible` div that holds `OrbCanvas`), render:
```tsx
<OrbBadge
  isVisible={uiState === UILayoutState.UI_STATE_IDLE && (taskProgress.isWorking || agentQuestion.hasPendingQuestion)}
  variant={agentQuestion.hasPendingQuestion ? "question" : "working"}
  currentStep={taskProgress.currentStep}
  totalSteps={taskProgress.totalSteps}
  glowColor={glowColor}
/>
```
- `uiState` is already a prop (`XurOrbProps.uiState`). `glowColor` is already available.
- Do NOT change orb drag, labels, canvas, or state machine. OrbBadge is additive only.
- Ensure `pointer-events: none` on the badge so it never blocks orb drag/click.

**Test:** extend `__tests__/components/OrbBadge.test.tsx` or add `XurOrb.badge.test.tsx` — OrbBadge present when IDLE + working; absent when wings open; question variant when pending question.

---

### Task 9 — Frontend: chat-view integration (render TaskListCard + ContextPill)

**Edit:** `components/chat-view.tsx`

- Import `TaskListCard`, `ContextPill`, `useTaskProgress`.
- Render `TaskListCard` in the message stream, adjacent to the existing `PermissionCard`/`QuestionCard` blocks (lines 2402–2454). Place it before the PermissionCard block, gated on `taskProgress.steps.length > 0`:
```tsx
{taskProgress.steps.length > 0 && (
  <TaskListCard steps={taskProgress.steps} turnId={taskProgress.turnId} mode={taskProgress.mode} />
)}
```
- Render `ContextPill` in the chat header. Find the header render section (search for the phase indicator / chat title). Pass `usedTokens`/`maxTokens` from a local state subscribed to `iris:context_usage`, and `phase` from existing voiceState.
- Do NOT alter the existing `PermissionCard`/`QuestionCard` blocks or their event listeners.
- Add a `useEffect` listening to `iris:context_usage` to update local token state (or a small `useContextUsage` hook).

**Test:** `__tests__/components/chat-view.tasklist.test.tsx` — TaskListCard renders when steps exist; ContextPill renders in header; no regression to PermissionCard/QuestionCard rendering.

---

## 6. Event Flow (end-to-end, after all tasks)

```
Backend DER loop
  ├─ agent_kernel emits TASK_START/PROGRESS/MILESTONE/DONE/FAIL on EventBus
  ├─ agent_kernel emits CONTEXT_USAGE on EventBus (Task 2)
  ├─ ask_user_tool emits QUESTION_ASK on EventBus
  └─ permissions emits PERMISSION_REQUEST on EventBus
        ↓
WSEventBridge (Task 1) subscribes → broadcast_to_session({"type": <evt>, "payload": {...}})
        ↓ (skips TOOL_RESULT + MODE_CHANGED — already direct)
WebSocket
        ↓
useIRISWebSocket (Task 4) forwards:
  task:* → iris:task_update CustomEvent
  context:usage → iris:context_usage CustomEvent
  (question:* / permission:* already forwarded)
        ↓
useTaskProgress (Task 3) → TaskListCard (Task 6) + OrbBadge via XurOrb (Task 8)
useAgentQuestion (Task 3) → OrbBadge (question variant) via XurOrb (Task 8)
iris:context_usage → ContextPill (Task 7) in chat-view (Task 9)
iris:question_ask → QuestionCard (existing) + OrbBadge question variant
iris:permission_request → PermissionCard (existing)
```

---

## 7. Acceptance Criteria

1. `OrbBadge.tsx`, `TaskListCard.tsx`, `ContextPill.tsx` exist and match the orb aesthetic (particle pip, monospace glow, no glass chips).
2. `WSEventBridge` forwards task/question/permission events to the WS; does NOT forward `TOOL_RESULT` or `MODE_CHANGED`.
3. `CONTEXT_USAGE` event exists, emitted once per DER step, forwarded to `iris:context_usage`.
4. `useIRISWebSocket` forwards `task:*` → `iris:task_update` and `context:usage` → `iris:context_usage`.
5. XurOrb renders OrbBadge only at `UI_STATE_IDLE` + (working|question); badge is `pointer-events:none`.
6. chat-view renders TaskListCard (inline) and ContextPill (header) without regressing PermissionCard/QuestionCard.
7. `npx tsc --noEmit` passes; `npm run lint` passes; `npm test` passes (new + existing).
8. `pytest backend/tests/contract/test_ws_event_bridge.py`, `test_context_usage_emit.py` pass.
9. Manual smoke (§9) passes.

---

## 8. Test Files to Create

| File | Type | Verifies |
|------|------|----------|
| `backend/tests/contract/test_ws_event_bridge.py` | Contract | bridge forwards task/question/permission; skips tool_result/mode_changed; handler exception swallowed; routes by session_id |
| `backend/tests/contract/test_context_usage_emit.py` | Contract | CONTEXT_USAGE emitted per step with used/max/session_id |
| `__tests__/hooks/useTaskProgress.test.tsx` | Behavioral | task:start→working, done/fail→idle, steps bounded at 50, cleanup |
| `__tests__/hooks/useAgentQuestion.test.tsx` | Behavioral | ask→pending, answered/timeout→cleared, cleanup |
| `__tests__/hooks/useIRISWebSocket.task.test.ts` | Contract | task:progress WS msg → iris:task_update CustomEvent; context:usage → iris:context_usage |
| `__tests__/components/OrbBadge.test.tsx` | Behavioral | visible when working/question; 2/5 in working; ? in question; particle style (no glass); pointer-events none |
| `__tests__/components/TaskListCard.test.tsx` | Behavioral | renders steps; live status update; collapse/expand; bounded at 50 |
| `__tests__/components/ContextPill.test.tsx` | Behavioral | token format; green/amber/red thresholds; updates on iris:context_usage |
| `__tests__/components/XurOrb.badge.test.tsx` | Behavioral | OrbBadge present at IDLE+working; absent when wings open; question variant when pending |

---

## 9. Verification Commands

```powershell
# Backend
pytest backend/tests/contract/test_ws_event_bridge.py -v
pytest backend/tests/contract/test_context_usage_emit.py -v
pytest backend/tests/test_ask_user_tool.py -v   # ensure no regression

# Frontend
npx tsc --noEmit
npm run lint
npm test

# Manual smoke (requires backend + tauri dev):
# 1. Trigger a multi-step task → TaskListCard renders inline, live status updates
# 2. ContextPill shows token count in header, color shifts with usage
# 3. Close wings (orb only) → OrbBadge shows "2/5" pip top-right, pulses
# 4. Agent asks a question with wings closed → OrbBadge shows "?" pip
# 5. Click orb → wings open → TaskListCard/QuestionCard visible; OrbBadge hides
# 6. Permission prompt → PermissionCard renders (no regression)
# 7. Task done → OrbBadge clears, TaskListCard shows completed steps
```

---

## 10. Recording (per AGENTS.md)

After each task passes its test:
- `record_edit(file)` / `record_create(file)` for every file touched
- `record_test(test_file, 'pass', covers=[...])`
- `pin_add(title='phase5_<component>', pin_type='decision', content='...')`
After all tasks pass:
- `crystallize_landmark(feature_id, name='phase5_frontend_completion', description='...')`

---

## 11. Open Risks (flag, do not silently absorb)

1. **Bridge instantiation timing** — the gateway must construct `WSEventBridge` after the WS manager and event loop are ready. If the gateway has no clear async startup hook, the agent may need to lazily start the bridge on first WS connection (where `session_id` is first known). Prefer lazy start if the eager start is ambiguous.
2. **Double-broadcast of tool_result** — if `tool_bridge.py:881` already broadcasts `tool_result` AND the bridge forwards `TOOL_CALL`/`TOOL_ERROR` (not result), there's no duplication. But verify `tool:call`/`tool:error` aren't ALSO broadcast directly somewhere before forwarding them; if they are, exclude from the bridge too.
3. **ContextPill phase source** — confirm where chat-view gets the phase/voiceState for the pill; reuse the existing variable rather than introducing a new one.
4. **OrbBadge position tuning** — the top-right coordinates (top:14, right:14) are a starting point; verify visually it clears the Menu label (y−45) and doesn't clip at orb scale 1.15 (listening). The badge is inside `overflow: visible` so it can extend beyond the 120px box if needed.