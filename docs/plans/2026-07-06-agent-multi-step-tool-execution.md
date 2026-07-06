# Agent Multi-Step Tool Execution — Implementation Plan

> Date: 2026-07-06
> Branch: `feat/agent-multi-step-tool-execution`
> Architecture overview: `docs/architecture/agent-multi-step-architecture.md`
> Gap analysis: `docs/architecture/agent-multi-step-gaps.md`
> DER + Mycelium: `docs/DER_LOOP_MYCELIUM.md`
> Pacman: `docs/PACMAN.md`
> Status: Planning. Build layers bottom to top.

---

## How to Use This Plan

1. Read the **architecture overview** first — it contains the locked design decisions and layer rationale.
2. Build layers in order (Layer 2 → Layer 6). Each layer depends only on the ones below it.
3. After each phase, run the verification commands listed. Do not proceed to the next phase until verification passes.
4. Record `record_edit()` / `record_test()` / `pin_add()` per the AGENTS.md protocol as you go.

---

## Phase 0 — Branch Setup

- [x] Create branch `feat/agent-multi-step-tool-execution` off `feat/xurorb-spiral-dissolve-winner`
- [x] Write architecture overview: `docs/architecture/agent-multi-step-architecture.md`
- [x] Write this implementation plan: `docs/plans/2026-07-06-agent-multi-step-tool-execution.md`
- [ ] Commit the two docs as the first commit on this branch

**Verification:** `git log --oneline -3` shows the docs commit on `feat/agent-multi-step-tool-execution`.

---

## Phase 1 — Layer 2: Per-Thread Context + WS Resilience (Gap 12)

**Goal:** Agent context keyed by `conversation_id`, survives WS disconnect, no crashes on reconnect.

### Step 1.1 — ConversationContextStore (new backend component)

**File:** `backend/agent/conversation_context_store.py` (new)

- Persistent store for per-thread agent context, keyed by `conversation_id`
- `get_or_restore(conversation_id) -> Optional[ConversationContext]`
- `save(conversation_id, context)` — persists to disk
- `save_current_and_load(new_id)` — atomic swap for thread switch
- `clear(conversation_id)` — for `new_conversation`
- Bounded: max 50 conversations, 200 messages each (matches frontend `MAX_CONVERSATIONS` / `MAX_MESSAGES_PER_CONV`)
- Storage: SQLite table `conversation_contexts` (reuse `data/databases/` dir) or JSON files in `data/conversations/`
- Thread-safe (WAL mode if SQLite)

**Quality check before test:**
- [ ] No unbounded caches — max 50 conversations enforced
- [ ] File handles closed after each operation
- [ ] No blocking I/O in async hot paths — use `asyncio.to_thread()` for disk writes
- [ ] Error handling: missing file/corrupt JSON → return None, log, no crash

### Step 1.2 — Agent kernel re-keying

**File:** `backend/agent/agent_kernel.py`

- `process_text_message(text, conversation_id, session_id=None)` — `conversation_id` is the context key, `session_id` is transport-only
- `clear_conversation(conversation_id)` — already exists, extend to clear from `ConversationContextStore`
- `get_conversation_context(conversation_id)` — fetch from store, not in-memory dict
- Keep `session_id` for WS routing only (which connection to send responses to)

**Lines to change:** 80-133 (context key), 2616-2624 (`process_text_message` signature)

### Step 1.3 — Gateway WS handlers

**File:** `backend/iris_gateway.py`

- `voice_command_start` handler (line 1783-1830): accept `conversation_id` from payload, pass to `agent_kernel.process_text_message()`
- New `switch_conversation` handler: calls `agent_kernel.save_current_and_load(conversation_id)`
- WS reconnect: detect reconnection (same user, new `session_id`), call `ConversationContextStore.get_or_restore(conversation_id)`, reattach agent context
- New `settings_sync` handler: frontend sends current settings on reconnect, backend re-syncs (brand color, voice mode, etc.)

### Step 1.4 — Frontend WS changes

**File:** `hooks/useIRISWebSocket.ts`

- `voice_command_start` (line 1285-1295): send `{ conversation_id }` instead of `{}`
- New `switchConversation(conversationId)` sender
- New `settingsSync(settings)` sender (called on reconnect)
- Reconnect state: emit `iris:ws_reconnecting` and `iris:ws_reconnected` CustomEvents
- No errors thrown on disconnect — graceful state transition

**File:** `components/chat-view.tsx`

- `handleSelectConversation` (line 787-790): call `sendMessage('switch_conversation', { conversation_id })`
- Track `conversation_id` in a ref for reconnect
- On `iris:ws_reconnected`: re-send `switch_conversation` with current `conversation_id` + `settingsSync`

### Step 1.5 — Orb reconnecting state

**File:** `components/iris/XurOrb.tsx`

- Listen for `iris:ws_reconnecting` / `iris:ws_reconnected`
- Show subtle "reconnecting" visual (dimmed pulse) — no error overlay
- Return to normal on reconnect

### Verification (Phase 1)

```powershell
# Backend tests
pytest backend/tests/test_conversation_context_store.py -v
pytest backend/tests/test_chat_handler.py -v
pytest backend/tests/test_chat_persistence.py -v

# Frontend type check
npx tsc --noEmit

# Manual smoke test:
# 1. Start backend + frontend
# 2. Send a message, switch to a different conversation, send another message
# 3. Verify agent context is per-thread (no bleed)
# 4. Kill WS backend, restart — verify no crash, settings preserved, context restored
```

**Landmark on pass:** `pin_add(title='per_thread_context_gap12', pin_type='decision', content='conversation_id keying + ConversationContextStore + WS resilience')`

---

## Phase 2 — Layer 3: Kernel Separation (Gap 6, un-deferred)

**Goal:** LLM output routed through EventBus. TTS only receives utterances. Tool calls/planning reach frontend only.

### Step 2.1 — EventBus (new)

**File:** `backend/agent/event_bus.py` (new)

```python
@dataclass
class IRISStreamEvent:
    type: Literal['utterance', 'tool_call', 'tool_result',
                  'planning_step', 'status_phrase', 'phase_change',
                  'context_usage', 'permission_request']
    payload: Dict
    turn_id: str
    conversation_id: str
    timestamp: float

class EventBus:
    def emit(self, event: IRISStreamEvent) -> None
    def subscribe(self, event_type: str, handler: Callable) -> str
    def unsubscribe(self, sub_id: str) -> None
```

- Thread-safe (asyncio.Lock for emit, dict for subscribers)
- Bounded subscriber list (no unbounded growth)
- Error in one handler does not block others (try/except per handler)

### Step 2.2 — ConversationKernel extension

**File:** `backend/agent/conversation_kernel.py`

- Add `emit_utterance(text, turn_id, conversation_id)` → EventBus
- Add `emit_status_phrase(phrase, turn_id, conversation_id)` → EventBus
- Add `filter_speech(content) -> str` — strips tool-call JSON, planning markers, reasoning blocks from content before TTS
- Caducean phase check: only emit utterances during EXPAND
- Existing TTS chunk sizing + barge-in logic preserved

### Step 2.3 — TaskKernel (new)

**File:** `backend/agent/task_kernel.py` (new)

- `emit_tool_call(tool_name, args, step, total, turn_id, conversation_id)` → EventBus
- `emit_tool_result(tool_name, result, success, turn_id, conversation_id)` → EventBus
- `emit_planning_step(step_desc, step_num, turn_id, conversation_id)` → EventBus
- `emit_context_usage(used_tokens, max_tokens, turn_id, conversation_id)` → EventBus
- `emit_permission_request(tool_name, tier, turn_id, conversation_id)` → EventBus
- No audio output — never reaches TTS
- Milestone detection: every N steps, emit `status_phrase` to ConversationKernel

### Step 2.4 — Gateway routing

**File:** `backend/iris_gateway.py`

- `chunk_callback` (line 2195): route through EventBus instead of direct `sentence_buf` append
- TTS subscribes to `utterance` events only
- WS broadcast subscribes to `tool_call` / `tool_result` / `planning_step` / `context_usage` / `permission_request` events
- `sentence_buf` becomes an EventBus subscriber, not a direct append target

### Step 2.5 — TTS subscription

**File:** `backend/agent/tts.py`

- Subscribe to `utterance` events from EventBus
- Unsubscribe from direct `chunk_callback` path
- Existing TTS chunk sizing, word timing, barge-in preserved

### Verification (Phase 2)

```powershell
pytest backend/tests/test_event_bus.py -v
pytest backend/tests/test_kernel_separation.py -v
pytest backend/tests/test_chunk_callback_fix.py -v

# Manual smoke test:
# 1. Send a message that triggers tool use
# 2. Verify TTS does NOT speak tool-call JSON
# 3. Verify TTS speaks status phrases + final result only
# 4. Verify frontend receives tool_call / tool_result events
```

**Landmark on pass:** `pin_add(title='kernel_separation_gap6', pin_type='decision', content='EventBus + ConversationKernel/TaskKernel split, Caducean governs phase')`

---

## Phase 3 — Layer 4: DER Agentic Mode (Gap 1)

**Goal:** Director dynamically decides and adjusts execution mode. LLM can emit tool_calls when mode=agentic. Voice cap removed, Director decides.

### Step 3.1 — Mode constants + Director mode logic

**File:** `backend/agent/der_constants.py`

- Add `ExecutionMode` enum: `QUICK`, `AGENTIC`, `FULL`
- Add mode budgets: `MODE_TOKEN_BUDGETS = {QUICK: 15000, AGENTIC: 50000, FULL: 50000}`
- Add `MAX_AGENTIC_ITERATIONS = 20`
- Add `MAX_FULL_CYCLES = 40` (existing cycle cap, now named explicitly)
- Add `VOICE_PREFERENCE_DEFAULT = "quick_first"` (try quick, escalate if needed)

### Step 3.2 — DirectorQueue mode management

**File:** `backend/agent/der_loop.py`

- `DirectorQueue` gains:
  - `current_mode: ExecutionMode` — the active mode
  - `set_mode(mode: ExecutionMode)` — change mode mid-loop
  - `escalate()` — quick → agentic → full
  - `de_escalate()` — full → agentic → quick
  - `mode_history: List[Tuple[ExecutionMode, cycle, reason]]` — for Mycelium logging
- `QueueItem` gains `mode: ExecutionMode` (the mode it was created under)
- Dynamic step injection on escalation: when escalating to `full`, Director can call `_plan_task()` for remaining work and inject steps
- When escalating to `agentic`, Director injects a single "dynamic tool execution" step
- When de-escalating, Director collapses remaining steps into a single `quick` step

### Step 3.3 — Director mode decision logic

**File:** `backend/agent/agent_kernel.py`

- **Initial assessment** (before first Explorer call): Director reads task + ContextPackage + classifier hint → picks initial mode
  - Hint from `TaskClassifier` is one input, not a lock
  - Mycelium `tier2_predictions` (predicted tools) inform the decision
  - If no tools predicted → `quick`
  - If tools predicted but task looks simple → `agentic`
  - If task looks complex / multi-step → `full`
- **Mid-loop re-evaluation** (after each Explorer result): Director re-assesses
  - If `quick` result reveals tools needed → escalate to `agentic`
  - If `agentic` iteration count approaching cap and task not done → escalate to `full`
  - If `full` plan's remaining steps are trivial after intermediate result → de-escalate to `quick`
- **Mode change logging**: `memory_interface.mycelium_ingest_statement()` logs the mode change + reason
  - Over many sessions, Mycelium learns which tasks need escalation → improves initial assessment

### Step 3.4 — Agentic Explorer implementation

**File:** `backend/agent/agent_kernel.py`

- When `queue.current_mode == AGENTIC`:
  - Explorer calls LLM with tool definitions
  - LLM returns `tool_calls` in response
  - System executes tools, feeds results back
  - Loop continues until LLM produces final text (no `tool_calls`)
  - Reviewer still runs on each tool call (PASS/REFINE/VETO)
  - Mycelium `ingest_tool_call()` fires per execution
  - TrailingDirector gap-filling still runs
- When `queue.current_mode == QUICK`:
  - Single LLM call, no tools, direct response
  - If result reveals tools needed, Director escalates
- When `queue.current_mode == FULL`:
  - Existing DER behavior — pre-planned steps, Director/Reviewer/Explorer cycle

### Step 3.5 — Remove voice 1-step cap

**File:** `backend/agent/agent_kernel.py`

- Remove the hard 1-step cap at line 3478
- Replace with Director-decided mode
- User-configurable "voice preference" setting hints the Director:
  - `quick_first` (default): try quick, escalate if needed
  - `multi_step`: default to agentic
- Caducean COMPRESS phase keeps voice tasks silent during work regardless of mode

### Step 3.6 — Semantic planning trigger (hint, not lock)

**File:** `backend/agent/agent_kernel.py`

- Replace keyword-based `_needs_planning()` (line 1372-1430) with LLM-based intent classification
- Fast LLM inference (small model, max 100 tokens) provides a **hint** to the Director about whether tools are likely needed
- The Director uses this hint as one input among many — not a lock
- Falls back to keyword matching if classifier unavailable

### Step 3.7 — Streaming integration

**File:** `backend/agent/streaming.py`

- Stream tool-call results through EventBus (not direct TTS)
- Stream final text response through ConversationKernel → TTS
- Stream planning steps through TaskKernel → frontend
- Stream mode changes through TaskKernel → frontend (TaskListCard shows mode transitions)

### Verification (Phase 3)

```powershell
pytest backend/tests/test_der_loop.py -v
pytest backend/tests/test_der_caducean_gaps.py -v
pytest backend/tests/test_agent_loop_upgrade.py -v

# Manual smoke test:
# 1. Ask agent a simple question ("what's 2+2?") — verify Director picks quick mode
# 2. Ask agent to "search for X and summarize" — verify Director picks agentic mode
# 3. Ask agent a complex task ("refactor this file and run tests") — verify Director picks full mode
# 4. Ask a task that starts simple but needs tools mid-response — verify escalation
# 5. Voice command: speak "find my latest file and open it" — verify multi-step, not capped at 1
# 6. Check logs for mode_history — verify changes are logged to Mycelium
```

**Landmark on pass:** `pin_add(title='der_director_mode_gap1', pin_type='decision', content='Director dynamically decides and adjusts execution mode (quick/agentic/full), not hardcoded upfront')`

---

## Phase 4 — Layer 5: Permission System Wiring (Gap 2)

**Goal:** `notification_response` handled. Tiered risk applies. Personal/developer mode distinction works.

### Step 4.1 — Tiered risk classification

**File:** `backend/vision/permission_system.py`

- Extend `PermissionRequestSystem` for general tool execution (not vision-only)
- Add `ToolRiskTier` enum: `READ_ONLY`, `SIDE_EFFECT`, `DESTRUCTIVE`
- Add `classify_tool_risk(tool_name, params) -> ToolRiskTier`
- Risk mapping:
  - READ_ONLY: file_read, web_search, list_dir, get_status
  - SIDE_EFFECT: file_write, terminal_command, git_commit, mcp_call_write
  - DESTRUCTIVE: delete, git_push, system_config, rm_rf

### Step 4.2 — CapabilitySet extension

**File:** `backend/capabilities.py`

- Add per-tool approval on top of personal/developer mode
- Personal mode: auto-approve READ_ONLY; deny SIDE_EFFECT to app source; deny DESTRUCTIVE
- Developer mode: auto-approve READ_ONLY + SIDE_EFFECT to app source; SIDE_EFFECT for OS commands requires approval; DESTRUCTIVE requires approval + confirmation
- `check_permission(tool_name, params, mode) -> PermissionDecision`

### Step 4.3 — Tool bridge permission check

**File:** `backend/agent/tool_bridge.py`

- Before `execute_tool()` (line 690-810): call `check_permission()`
- If approval needed: emit `permission_request` via TaskKernel → EventBus → frontend
- Pause tool execution until `notification_response` received
- Timeout: auto-deny after 30s (non-critical), 60s (destructive)

### Step 4.4 — Backend notification_response handler

**File:** `backend/iris_gateway.py`

- Add handler for `notification_response` WS message
- Calls `PermissionRequestSystem.resolve(request_id, action)`
- Resumes paused tool execution on `grant`
- Aborts tool on `deny` or timeout

### Step 4.5 — Frontend permission UI (already exists, wire it)

**File:** `components/chat-view.tsx`

- Permission UI exists (line 1565-1584) — `handlePermissionGrant/Deny` already sends `notification_response`
- No frontend changes needed — the dead wire gets wired on the backend side
- Verify the permission notification renders correctly with real data

### Verification (Phase 4)

```powershell
pytest backend/tests/test_tool_permissions_security.py -v
pytest backend/tests/test_permission_system.py -v

# Manual smoke test:
# 1. In personal mode, ask agent to write a file — verify approval prompt
# 2. Grant approval — verify tool executes
# 3. Deny approval — verify tool aborts
# 4. Switch to developer mode — verify app source writes auto-approve
# 5. Destructive tool (git push) — verify approval + confirmation
```

**Landmark on pass:** `pin_add(title='permission_system_wired_gap2', pin_type='decision', content='Tiered risk + personal/developer distinction + notification_response handler')`

---

## Phase 5 — Layer 6: Frontend Components (Gaps 4, 7)

**Goal:** Task list card, context pill, orb badge — all matching orb aesthetic.

### Step 5.1 — TaskListCard component

**File:** `components/chat/TaskListCard.tsx` (new)

- Props: `steps: TaskStep[]`, `turnId: string`, `isCollapsed: boolean`
- `TaskStep`: `{ id, description, status, toolName?, resultPreview? }`
- Status: `pending | working | done | skipped | vetoed`
- Live updates: subscribes to `iris:task_update` CustomEvent
- Collapsible (collapsed by default for long plans)
- Aesthetic: dark glass background, brand-color accents, monospace step labels, matches `OrbCanvas` particle style
- Renders inline in chat message stream (not a separate panel)

### Step 5.2 — ContextPill component

**File:** `components/chat/ContextPill.tsx` (new)

- Props: `usedTokens`, `maxTokens`, `phase: SpotlightStateType | string`
- Displays: `12.4k / 128k` + thin progress bar
- Color: green (<60%) → amber (60-85%) → red (>85%)
- Phase indicator next to it: idle / listening / thinking / working / speaking
- Subscribes to `iris:context_usage` CustomEvent
- Positioned in chat header

### Step 5.3 — OrbBadge component

**File:** `components/iris/OrbBadge.tsx` (new)

- Props: `stepCount?, notificationCount?, glowColor, isVisible`
- Renders small badge on orb when working state active
- Shows: step counter (`2/5`) or notification count
- Aesthetic: matches `OrbCanvas` particle style — no flat Material badges
- Uses same `glowColor` and particle rendering approach
- Positioned to not obscure orb center
- Clicking orb opens wings to reveal full task list

### Step 5.4 — ChatView integration

**File:** `components/chat-view.tsx`

- Render `TaskListCard` in message stream when DER plan active
- Render `ContextPill` in chat header
- Add event listeners for `iris:task_update`, `iris:context_usage`
- Track active task steps in state

### Step 5.5 — XurOrb integration

**File:** `components/iris/XurOrb.tsx`

- Render `OrbBadge` when working state active (`voiceState === "processing_tool"`)
- Pass `glowColor` to badge for aesthetic match
- Badge clears when working state ends

### Step 5.6 — WebSocket event forwarding

**File:** `hooks/useIRISWebSocket.ts`

- Forward `task_update` WS events as `iris:task_update` CustomEvents
- Forward `context_usage` WS events as `iris:context_usage` CustomEvents
- Forward `permission_request` WS events as `iris:notification` CustomEvents (already partially exists)

### Verification (Phase 5)

```powershell
npx tsc --noEmit
npm run lint
npm test

# Manual smoke test:
# 1. Trigger a multi-step task — verify TaskListCard renders inline
# 2. Verify live updates as steps complete
# 3. Verify ContextPill shows token count in header
# 4. Close wings (orb only) — verify OrbBadge shows step counter
# 5. Verify badge matches orb aesthetic (particle style, brand color)
# 6. Click orb — wings open, task list visible
```

**Landmark on pass:** `pin_add(title='frontend_components_gap4_7', pin_type='decision', content='TaskListCard + ContextPill + OrbBadge, all matching orb aesthetic')`

---

## Phase 6 — Integration + End-to-End Verification

**Goal:** All layers work together. Full multi-step agent experience.

### Step 6.1 — End-to-end smoke test

```powershell
# Full stack
pytest backend/tests/ -v --tb=short
npx tsc --noEmit
npm run lint
npm test

# Manual E2E:
# 1. Start backend + frontend + Tauri
# 2. Voice command: "Find my latest IRIS doc and summarize it"
# 3. Verify:
#    - Agent dynamically calls file_search + file_read tools
#    - TTS speaks status phrases only ("On it.", "Found 3 files...", "Here's the summary...")
#    - TaskListCard shows live progress in chat
#    - ContextPill shows token count
#    - OrbBadge shows step counter when wings closed
#    - Reviewer runs (check logs)
#    - Mycelium ingest_tool_call fires (check logs)
# 4. Switch to a different conversation thread
# 5. Verify agent context switches correctly
# 6. Kill WS backend, restart
# 7. Verify no crash, settings preserved, context restored
# 8. Permission: in personal mode, ask agent to delete a file
# 9. Verify approval prompt, deny, verify tool aborts
```

### Step 6.2 — Widget resilience test

```powershell
# Manual:
# 1. Drag orb to different desktop position
# 2. Open wings, start a multi-step task
# 3. Close wings mid-task (orb only visible)
# 4. Verify task continues in background
# 5. Verify OrbBadge updates
# 6. Disconnect WiFi (WS disconnect)
# 7. Verify no crash, orb shows reconnecting state
# 8. Reconnect WiFi
# 9. Verify settings preserved, context restored, task resumes
```

### Step 6.3 — Final landmark

```python
pin_add(
    title='agent_multi_step_tool_execution_complete',
    pin_type='decision',
    content='Full vision: per-thread context + kernel separation + DER agentic mode + permission wiring + frontend components + widget resilience'
)
```

---

## File Inventory

### New Files (13)

| File | Layer | Purpose |
|------|-------|---------|
| `backend/agent/conversation_context_store.py` | 2 | Persistent per-thread context |
| `backend/agent/event_bus.py` | 3 | IRISStreamEvent + EventBus |
| `backend/agent/task_kernel.py` | 3 | Tool-call events, planning steps, progress |
| `components/chat/TaskListCard.tsx` | 6 | Inline task list card |
| `components/chat/ContextPill.tsx` | 6 | Context window + phase pill |
| `components/iris/OrbBadge.tsx` | 6 | Orb badge for background tasks |
| `backend/tests/test_conversation_context_store.py` | 2 | Phase 1 tests |
| `backend/tests/test_event_bus.py` | 3 | Phase 2 tests |
| `backend/tests/test_kernel_separation.py` | 3 | Phase 2 tests |
| `backend/tests/test_permission_system.py` | 5 | Phase 4 tests |

### Modified Files (12)

| File | Layer | Change |
|------|-------|--------|
| `backend/agent/agent_kernel.py` | 2, 3, 4 | Re-key to conversation_id; Director mode decision logic; agentic Explorer; remove 1-step cap; semantic `_needs_planning()` as hint |
| `backend/iris_gateway.py` | 2, 3, 5 | voice_command_start accepts conversation_id; switch_conversation handler; notification_response handler; EventBus routing; settings_sync |
| `backend/agent/conversation_kernel.py` | 3 | Emit utterances, filter speech from task content |
| `backend/agent/tts.py` | 3 | Subscribe to utterance events only |
| `backend/agent/streaming.py` | 3, 4 | Stream through EventBus, not direct TTS; stream mode changes |
| `backend/agent/der_constants.py` | 4 | Add `ExecutionMode` enum, mode budgets, iteration caps, voice preference default |
| `backend/agent/der_loop.py` | 4 | `DirectorQueue` gains `current_mode`/`set_mode`/`escalate`/`de_escalate`/`mode_history`; `QueueItem` gains mode field; dynamic step injection on escalation |
| `backend/agent/tool_bridge.py` | 5 | Permission check before execute_tool |
| `backend/vision/permission_system.py` | 5 | Extend for general tools, tiered risk |
| `backend/capabilities.py` | 5 | Per-tool approval on top of mode |
| `hooks/useIRISWebSocket.ts` | 2, 6 | conversation_id in voice_command_start; switch_conversation; settings_sync; task_update/context_usage forwarding |
| `components/chat-view.tsx` | 2, 6 | switch_conversation on thread select; TaskListCard + ContextPill rendering; event listeners |
| `components/iris/XurOrb.tsx` | 2, 6 | Reconnecting state; OrbBadge rendering |

### Docs (2, already written)

| File | Purpose |
|------|---------|
| `docs/architecture/agent-multi-step-architecture.md` | Architecture overview (this plan references it) |
| `docs/plans/2026-07-06-agent-multi-step-tool-execution.md` | This plan |

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| DER agentic mode breaks existing DER tests | Run `test_der_loop.py` after Step 3.2; fix before proceeding |
| Kernel separation breaks TTS timing | Phase 2 verification includes TTS smoke test; preserve existing chunk sizing logic |
| ConversationContextStore disk I/O blocks async | Use `asyncio.to_thread()` for all disk operations |
| Permission timeout kills long tasks | Timeout only applies to approval wait, not tool execution; 30s/60s is generous |
| OrbBadge aesthetic mismatch | Use same `glowColor` and particle rendering as `OrbCanvas`; review in Phase 5 smoke test |
| WS reconnect race condition | `ConversationContextStore.get_or_restore()` is atomic; frontend re-sends `switch_conversation` on reconnect |

---

## Out of Scope (Deferred)

- **MCP dynamic discovery** (Gap 3) — 8 hardcoded servers remain; follow-up branch
- **SpecEngine** — not built; out of scope
- **Structured tool result display** (Gap 7, low severity) — TaskListCard covers the primary need; rich result rendering deferred
- **Tauri Rust changes** — no Rust changes; widget resilience is frontend + backend only

---

## References

- Architecture overview: `docs/architecture/agent-multi-step-architecture.md`
- Gap analysis: `docs/architecture/agent-multi-step-gaps.md`
- DER loop + Mycelium: `docs/DER_LOOP_MYCELIUM.md`
- Pacman context metabolism: `docs/PACMAN.md`
- Timing/sync pipeline: `docs/plans/timing-sync-pipeline-overlap.md`
- Audio pipeline solidification: `docs/HANDOFF_AUDIO_PIPELINE.md`
