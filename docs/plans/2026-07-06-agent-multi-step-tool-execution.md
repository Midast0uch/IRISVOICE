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
5. **Follow the Testing Discipline (below) — it is mandatory, not optional.**

---

## Testing Discipline — Mandatory

This branch introduces architectural changes to the DER loop, kernel separation, context keying, and permission system. These are load-bearing components. **Proper testing validates the implementation.** The testing rules below are absolute and apply to every phase.

### Rule 1: Target tests, not stale tests

- **Write new target tests** for every new component and every modified behavior. Target tests verify the *new* contract, not the *old* one.
- **Never run stale or old tests just to get things to pass.** If an existing test encodes the old behavior (e.g. `session_id` keying, 1-step voice cap, direct `chunk_callback` → TTS), that test is now wrong. It must be updated to assert the new contract — not deleted, not skipped, not marked `xfail`.
- If an existing test still encodes valid behavior that hasn't changed, it stays. But verify it actually tests what it claims before relying on it.
- **Before relying on any existing test file:** read it. Confirm it asserts the current contract. If it asserts the old contract, update it. Do not assume a passing test means the implementation is correct — a test that checks the wrong thing is worse than no test.

### Rule 2: Behavioral testing

Behavioral tests verify *what the system does* from the outside, not *how it's implemented*. For each phase:

- **Write behavioral tests** that exercise the user-visible behavior:
  - Phase 1: "When I switch conversation threads, the agent's next response uses the correct thread's context — not the previous thread's."
  - Phase 2: "When the agent executes a tool, TTS never speaks the tool-call JSON — only status phrases and the final result."
  - Phase 3: "When I ask a simple question, the Director picks `quick` mode. When I ask for a multi-step task, the Director escalates to `agentic` or `full`."
  - Phase 4: "When the agent calls a side-effect tool in personal mode, an approval prompt appears. Denying aborts the tool."
  - Phase 5: "When a multi-step task runs, the TaskListCard renders live updates. The ContextPill shows token count. The OrbBadge shows step counter when wings are closed."
- Behavioral tests use the public interface (WS messages, REST endpoints, CustomEvents) — not internal function calls. They survive refactors.
- **A behavioral test that passes after a refactor is worth more than a unit test that passes.** Unit tests verify the implementation; behavioral tests verify the contract.

### Rule 3: Contract testing

Contract tests verify that the interfaces between components honor their agreements. For each new or modified interface:

- **EventBus contract:** `emit(event)` delivers to all subscribers of that event type. A handler error does not block other handlers. Subscribers can unsubscribe cleanly.
- **ConversationContextStore contract:** `get_or_restore(id)` returns the stored context or None. `save(id, context)` persists. `save_current_and_load(new_id)` is atomic — no partial state on crash.
- **ConversationKernel contract:** Only emits `utterance` events during EXPAND phase. `filter_speech()` strips tool-call JSON, planning markers, and reasoning blocks. Never emits during COMPRESS.
- **TaskKernel contract:** Emits `tool_call` / `tool_result` / `planning_step` events. Never reaches TTS. Emits `status_phrase` to ConversationKernel on milestones.
- **DirectorQueue mode contract:** `set_mode()` changes the active mode. `escalate()` only moves in the direction quick→agentic→full. `de_escalate()` only moves in the direction full→agentic→quick. `mode_history` records every change with cycle number and reason.
- **Permission system contract:** `notification_response` with `action=grant` resumes the paused tool. `action=deny` aborts it. Timeout (30s non-critical, 60s destructive) auto-denies. Tier classification is deterministic for the same tool+params.
- **WS reconnect contract:** On reconnect, the frontend re-sends `switch_conversation` + `settings_sync`. The backend restores context from `ConversationContextStore`. No exceptions thrown on disconnect.

### Rule 4: Never fake a pass

- **Do not modify a test to make it pass.** If a test fails, the implementation is wrong — fix the implementation, not the test. The test is the requirement. (AGENTS.md: "Never write new tests to match your code. Never modify existing tests to make them pass.")
- **Do not skip a failing test.** If a test is genuinely obsolete (the behavior it tests no longer exists), update it to test the new behavior. But document *why* it changed in the commit message.
- **Do not run only the tests you know pass.** Run the full target test suite for the phase. A green build with a red test you didn't run is a failure.
- **Do not use `xfail` to hide a real failure.** `xfail` is for known limitations with a documented reason. If the test should pass, make it pass by fixing the code.

### Rule 5: Quality check before every test run

Per AGENTS.md, verify ALL of these before running any test:

- [ ] No unnecessary work in hot paths — loops, I/O, DB calls as few as needed
- [ ] Heavy imports are lazy — no ML model or GPU init at module level
- [ ] Error handling complete — every exception path has an explicit outcome
- [ ] Resources cleaned up — file handles, connections, subprocesses closed
- [ ] No shared mutable state across sessions or concurrent requests
- [ ] Memory footprint bounded — no unbounded caches or infinite queues
- [ ] Async/sync boundary correct — blocking calls not in async hot paths
- [ ] Logging structured — context identifier in every log line
- [ ] Nothing in this file can crash and block a user response

A passing test on unoptimized code is not done. Quality check is not optional.

### Test file naming convention

| Test type | Naming | Location |
|-----------|--------|----------|
| Target unit tests | `test_<component>_<behavior>.py` | `backend/tests/` |
| Behavioral tests | `test_<phase>_behavior.py` | `backend/tests/` |
| Contract tests | `test_<interface>_contract.py` | `backend/tests/` |
| Frontend tests | `test_<component>.tsx` | `__tests__/` or co-located |

### Test inventory per phase

| Phase | New test files | What they verify |
|-------|----------------|------------------|
| 1 | `test_conversation_context_store.py` | Store contract: save/restore/atomic swap/bounded |
| 1 | `test_per_thread_context_behavior.py` | Behavioral: thread switch restores context, WS reconnect preserves state |
| 1 | `test_voice_command_start_contract.py` | Contract: `voice_command_start` payload includes `conversation_id` |
| 2 | `test_event_bus.py` | Contract: emit/sub/unsub, handler isolation, bounded subscribers |
| 2 | `test_kernel_separation_behavior.py` | Behavioral: TTS never speaks tool JSON, only utterances during EXPAND |
| 2 | `test_conversation_kernel_contract.py` | Contract: filter_speech strips tool content, only emits during EXPAND |
| 2 | `test_task_kernel_contract.py` | Contract: emits tool events, never reaches TTS, milestone status phrases |
| 3 | `test_director_mode_behavior.py` | Behavioral: Director picks correct mode, escalates/de-escalates correctly |
| 3 | `test_director_queue_contract.py` | Contract: set_mode/escalate/de_escalate, mode_history logging |
| 3 | `test_agentic_explorer_behavior.py` | Behavioral: LLM emits tool_calls, loop until final text, Reviewer runs |
| 4 | `test_permission_system_contract.py` | Contract: tiered risk, grant/deny/timeout, personal/developer distinction |
| 4 | `test_permission_flow_behavior.py` | Behavioral: approval prompt appears, deny aborts, grant resumes |
| 5.5 | `test_ask_user_tool.py` | Contract: question/answer flow, timeout, fuzzy match, voice integration |
| 5.5 | `test_voice_filler_behavior.py` | Behavioral: filler fires during silence, no EXPAND filler, no repeat, AskUserQuestion voice flow |
| 5.5 | `test_agent_speech_behavior.py` | Behavioral: agent-initiated TTS, orb speaking state, chat-view closed |
| 5.5 | `test_question_card_behavior.tsx` | Behavioral: renders question, click answer, free-form input, voice match |
| 5 | `test_task_list_card_behavior.tsx` | Behavioral: live updates, collapsible, renders in chat stream |
| 5 | `test_context_pill_behavior.tsx` | Behavioral: token count, color shifts, phase indicator |
| 5 | `test_orb_badge_behavior.tsx` | Behavioral: step counter, question badge, aesthetic match, clears on done |

### Existing tests that must be updated (not deleted)

These existing test files encode the old contract and **must be updated** to assert the new contract. They are not stale — they test real behavior — but the behavior has changed.

| Existing test file | Old contract | New contract |
|--------------------|--------------|--------------|
| `backend/tests/test_der_loop.py` | Pre-planned steps only, no mode concept | Director decides mode, escalation/de-escalation |
| `backend/tests/test_chat_handler.py` | `session_id` keying | `conversation_id` keying |
| `backend/tests/test_chat_persistence.py` | In-memory context | `ConversationContextStore` persistence |
| `backend/tests/test_chunk_callback_fix.py` | Direct `chunk_callback` → TTS | EventBus → ConversationKernel → TTS |
| `backend/tests/test_agent_loop_upgrade.py` | Single execution path | Three modes, Director decides |
| `backend/tests/test_tool_permissions_security.py` | Binary personal/developer | Tiered risk + per-tool approval |
| `backend/tests/test_der_caducean_gaps.py` | No kernel separation | Kernel separation, Caducean governs phase |

**Before updating each:** read the full test file. Understand what it currently asserts. Then update the assertions to match the new contract. Document the change in the commit message.

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

## Phase 5.5 — AskUserQuestion Tool + Voice Filler + Agent-Initiated Speech

**Goal:** Agent can ask the user multiple-choice questions mid-task. Voice filler comments prevent silence gaps. Agent can speak proactively even when chat-view is closed.

### Step 5.5.1 — AskUserQuestion tool (backend)

**File:** `backend/agent/tools/ask_user_tool.py` (new)

- Tool name: `ask_user_question`
- Parameters: `question: str`, `options: List[str]`, `allow_other: bool = False`
- When called by DER Explorer:
  1. Emits `agent_question` event via TaskKernel → EventBus → WS → frontend
  2. Pauses DER loop (tool execution waits for answer)
  3. If voice command is open: ConversationKernel emits question as utterance → TTS speaks it → agent listens for spoken answer (see Step 5.5.3)
  4. Receives answer from `agent_question_response` WS message
  5. Returns answer as tool result to DER loop
  6. DER loop continues

**Quality check before test:**
- [ ] DER loop pause is clean — no deadlock, no busy wait
- [ ] Timeout: if no answer in 120s, tool returns "no response" and DER loop continues with a default
- [ ] Error handling: WS disconnect during question → tool returns "connection lost", DER loop handles gracefully

### Step 5.5.2 — QuestionCard component (frontend)

**File:** `components/chat/QuestionCard.tsx` (new)

- Props: `question: string`, `options: string[]`, `allowOther: boolean`, `turnId: string`, `onAnswer: (answer: string) => void`
- Renders inline in chat stream (like TaskListCard)
- Question text + options as clickable buttons
- "Other" option opens a text input for free-form answer
- Matches orb aesthetic: dark glass, brand-color buttons, monospace question text
- Subscribes to `iris:agent_question` CustomEvent
- On answer: calls `sendMessage('agent_question_response', { turn_id, answer })`

### Step 5.5.3 — Voice filler + AskUserQuestion voice integration

**File:** `backend/agent/conversation_kernel.py`

- **Silence timer:** starts when entering COMPRESS with voice command open
  - If no utterance for N seconds (default 5s, configurable), emit a `status_phrase` filler
  - Timer resets after each filler or utterance
  - No filler during EXPAND or when user is speaking (barge-in detection)
- **Filler phrase selection:** context-aware based on current tool / task phase
  - Searching → "Let me search for that..."
  - Reading files → "Let me check that file..."
  - Executing tool → "One moment, working on it..."
  - Planning → "Let me think about the best approach..."
  - Generic → "Hmm...", "Let me see...", "Working on it..."
  - No repetition: track last 3 fillers, pick a different one
- **AskUserQuestion voice flow:**
  1. When `ask_user_question` is called and voice command is open:
     - Emit question text as `utterance` event → TTS speaks it
     - After TTS finishes, enter listening mode for spoken answer
  2. User speaks answer → STT captures transcript
  3. Fuzzy match transcript against options:
     - Confidence > 0.7 → accept match
     - Confidence 0.4-0.7 → ask confirmation: "Did you mean [option]? Say yes or no."
     - Confidence < 0.4 → re-state: "I didn't catch that. Say option 1 for [A], option 2 for [B]."
     - No match + `allow_other` → treat as free-form input
  4. If no response within N seconds after question spoken:
     - Filler prompt: "Did you catch that? I asked: [shorter rephrase]"
     - After 2 filler prompts: render visual card / orb badge, wait for click answer

### Step 5.5.4 — Agent-initiated speech (TTS independence)

**File:** `backend/agent/tts.py`

- Subscribe to `utterance` events from EventBus regardless of voice command state
- Currently TTS is triggered by voice command flow — after this, any `utterance` event triggers TTS
- Voice command flow still works (it's one source of utterance events)
- Agent-initiated speech is another source
- Both go through same TTS pipeline (chunk sizing, word timing, barge-in)

**File:** `backend/agent/task_kernel.py`

- `emit_utterance(text, turn_id, conversation_id)` — for agent-initiated speech
- Used when: background task completes, milestone reached, error needs attention
- Emits to EventBus → TTS plays it → orb shows speaking state if chat-view closed

### Step 5.5.5 — Orb question badge + speaking state

**File:** `components/iris/OrbBadge.tsx`

- Add question badge state: question mark icon, pulsing brand color
- Renders when agent has a pending question and wings are closed
- Clicking orb opens wings to reveal QuestionCard

**File:** `components/iris/XurOrb.tsx`

- Render question badge when `iris:agent_question` received and wings closed
- Orb speaking state already exists (`isSpeaking` / `playbackSpeaking`) — agent-initiated speech uses the same visual
- No new visual needed for speaking — just ensure agent-initiated utterances trigger the existing speaking state

### Step 5.5.6 — WebSocket + gateway wiring

**File:** `hooks/useIRISWebSocket.ts`

- Forward `agent_question` WS events as `iris:agent_question` CustomEvents
- Add `sendAgentQuestionResponse(turnId, answer)` sender

**File:** `backend/iris_gateway.py`

- Handle `agent_question_response` WS message → route to DER loop (resolves the paused `ask_user_question` tool)

### Step 5.5.7 — Tool bridge registration

**File:** `backend/agent/tool_bridge.py`

- Register `ask_user_question` tool in the MCP tool list
- Tool is available in all modes (personal + developer)
- No permission tier — this is a conversational tool, not a side-effect tool

### Verification (Phase 5.5)

```powershell
# Backend
pytest backend/tests/test_ask_user_tool.py -v
pytest backend/tests/test_voice_filler_behavior.py -v
pytest backend/tests/test_agent_speech_behavior.py -v

# Frontend
npx tsc --noEmit
npm test -- --verbose test_question_card_behavior

# Manual smoke test:
# 1. Ask agent a task that needs clarification — verify QuestionCard renders
# 2. Click an option — verify DER loop continues with that answer
# 3. Voice mode: ask a task, when agent asks a question, verify TTS speaks it
# 4. Speak the answer — verify fuzzy matching works
# 5. Voice filler: start a long task with voice open — verify filler phrases fire during silence
# 6. Close chat-view mid-task — verify agent-initiated speech still plays (task completion)
# 7. Verify orb shows speaking state during agent-initiated speech
# 8. Verify orb shows question badge when agent asks a question with wings closed
# 9. Click orb with question badge — verify wings open to reveal QuestionCard
```

**Landmark on pass:** `pin_add(title='ask_user_voice_filler_agent_speech', pin_type='decision', content='AskUserQuestion tool + voice filler + agent-initiated speech, all integrated')`

---

## Phase 6 — Integration + End-to-End Verification

**Goal:** All layers work together. Full multi-step agent experience. **This phase is a testing gate — nothing merges until every test category passes.**

### Step 6.1 — Full target test suite

Run the complete target test suite. This is not a subset — every test file listed in the Testing Discipline test inventory must pass.

```powershell
# Backend — all target tests, no skips, no xfails hiding failures
pytest backend/tests/ -v --tb=short --no-header -rA

# Frontend
npx tsc --noEmit
npm run lint
npm test -- --verbose
```

**Before running:** verify the quality check (Rule 5) on every file touched in this branch. A passing test on unoptimized code is not done.

**After running:** if any test fails, do not proceed. Fix the implementation (not the test). The test is the requirement. Re-run until green.

### Step 6.2 — Contract test verification

Verify every contract defined in the Testing Discipline (Rule 3) holds:

```powershell
# Contract tests — run explicitly, verify each contract
pytest backend/tests/test_event_bus.py -v
pytest backend/tests/test_conversation_kernel_contract.py -v
pytest backend/tests/test_task_kernel_contract.py -v
pytest backend/tests/test_director_queue_contract.py -v
pytest backend/tests/test_permission_system_contract.py -v
pytest backend/tests/test_voice_command_start_contract.py -v
```

Each contract test must pass without modification. If a contract test fails, the interface is wrong — fix the implementation.

### Step 6.3 — Behavioral test verification

Verify every behavioral scenario from the Testing Discipline (Rule 2):

```powershell
pytest backend/tests/test_per_thread_context_behavior.py -v
pytest backend/tests/test_kernel_separation_behavior.py -v
pytest backend/tests/test_director_mode_behavior.py -v
pytest backend/tests/test_agentic_explorer_behavior.py -v
pytest backend/tests/test_permission_flow_behavior.py -v
npm test -- --verbose test_task_list_card_behavior
npm test -- --verbose test_context_pill_behavior
npm test -- --verbose test_orb_badge_behavior
```

### Step 6.4 — Stale test audit

Before merging, audit every existing test file that was *not* updated in this branch. For each:

1. Read the test file.
2. Confirm it still asserts valid behavior that hasn't changed.
3. If it asserts old behavior (e.g. `session_id` keying, 1-step cap, direct `chunk_callback`), it must be updated — do not leave it stale.
4. If it's genuinely obsolete (the behavior no longer exists), document why in the commit and remove it.

**A stale test that passes is a false positive.** It gives confidence that doesn't exist. Audit is mandatory.

### Step 6.5 — End-to-end smoke test

```powershell
# Manual E2E:
# 1. Start backend + frontend + Tauri
# 2. Voice command: "Find my latest IRIS doc and summarize it"
# 3. Verify:
#    - Agent dynamically calls file_search + file_read tools
#    - Director picked correct mode (check logs for mode_history)
#    - TTS speaks status phrases only ("On it.", "Found 3 files...", "Here's the summary...")
#    - TTS never speaks tool-call JSON or planning steps
#    - TaskListCard shows live progress in chat
#    - ContextPill shows token count
#    - OrbBadge shows step counter when wings closed
#    - Reviewer runs (check logs for PASS/REFINE/VETO)
#    - Mycelium ingest_tool_call fires (check logs)
# 4. Switch to a different conversation thread
# 5. Verify agent context switches correctly (no bleed)
# 6. Kill WS backend, restart
# 7. Verify no crash, settings preserved, context restored
# 8. Permission: in personal mode, ask agent to delete a file
# 9. Verify approval prompt, deny, verify tool aborts
# 10. Ask a simple question ("what's 2+2?") — verify Director picks quick mode
# 11. Ask a task that starts simple but needs tools — verify escalation
```

### Step 6.6 — Widget resilience test

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

### Step 6.7 — Final landmark (only after ALL tests pass)

```python
# Only call this after:
# - All target tests pass (Step 6.1)
# - All contract tests pass (Step 6.2)
# - All behavioral tests pass (Step 6.3)
# - Stale test audit complete (Step 6.4)
# - E2E smoke test passes (Step 6.5)
# - Widget resilience test passes (Step 6.6)
pin_add(
    title='agent_multi_step_tool_execution_complete',
    pin_type='decision',
    content='Full vision verified: per-thread context + kernel separation + DER Director-decided mode + permission wiring + frontend components + widget resilience. All target, contract, and behavioral tests pass. Stale test audit complete.'
)
```

---

## File Inventory

### New Files (30)

| File | Layer | Purpose |
|------|-------|---------|
| `backend/agent/conversation_context_store.py` | 2 | Persistent per-thread context |
| `backend/agent/event_bus.py` | 3 | IRISStreamEvent + EventBus |
| `backend/agent/task_kernel.py` | 3 | Tool-call events, planning steps, progress, agent-initiated speech |
| `backend/agent/tools/ask_user_tool.py` | 5.5 | AskUserQuestion tool — multiple-choice questions mid-task |
| `components/chat/TaskListCard.tsx` | 6 | Inline task list card |
| `components/chat/ContextPill.tsx` | 6 | Context window + phase pill |
| `components/chat/QuestionCard.tsx` | 5.5 | Multiple-choice question card component |
| `components/iris/OrbBadge.tsx` | 6 | Orb badge for background tasks + question badge |
| `backend/tests/test_conversation_context_store.py` | 2 | Contract: store save/restore/atomic swap/bounded |
| `backend/tests/test_per_thread_context_behavior.py` | 2 | Behavioral: thread switch, WS reconnect |
| `backend/tests/test_voice_command_start_contract.py` | 2 | Contract: payload includes conversation_id |
| `backend/tests/test_event_bus.py` | 3 | Contract: emit/sub/unsub, handler isolation |
| `backend/tests/test_kernel_separation_behavior.py` | 3 | Behavioral: TTS never speaks tool JSON |
| `backend/tests/test_conversation_kernel_contract.py` | 3 | Contract: filter_speech, EXPAND-only emission |
| `backend/tests/test_task_kernel_contract.py` | 3 | Contract: tool events, no TTS, milestones |
| `backend/tests/test_director_mode_behavior.py` | 4 | Behavioral: mode selection, escalation |
| `backend/tests/test_director_queue_contract.py` | 4 | Contract: set_mode/escalate/de_escalate/history |
| `backend/tests/test_agentic_explorer_behavior.py` | 4 | Behavioral: LLM tool_calls, loop, Reviewer |
| `backend/tests/test_permission_system_contract.py` | 5 | Contract: tiered risk, grant/deny/timeout |
| `backend/tests/test_permission_flow_behavior.py` | 5 | Behavioral: approval prompt, deny aborts |
| `backend/tests/test_ask_user_tool.py` | 5.5 | Contract: question/answer flow, timeout, fuzzy match |
| `backend/tests/test_voice_filler_behavior.py` | 5.5 | Behavioral: filler fires during silence, no EXPAND filler, no repeat |
| `backend/tests/test_agent_speech_behavior.py` | 5.5 | Behavioral: agent-initiated TTS, orb speaking state, chat-view closed |
| `__tests__/test_task_list_card_behavior.tsx` | 6 | Behavioral: live updates, collapsible |
| `__tests__/test_context_pill_behavior.tsx` | 6 | Behavioral: token count, color shifts |
| `__tests__/test_orb_badge_behavior.tsx` | 6 | Behavioral: step counter, question badge, aesthetic match |
| `__tests__/test_question_card_behavior.tsx` | 5.5 | Behavioral: renders question, click answer, free-form input |

### Modified Files (12)

| File | Layer | Change |
|------|-------|--------|
| `backend/agent/agent_kernel.py` | 2, 3, 4 | Re-key to conversation_id; Director mode decision logic; agentic Explorer; remove 1-step cap; semantic `_needs_planning()` as hint |
| `backend/iris_gateway.py` | 2, 3, 5 | voice_command_start accepts conversation_id; switch_conversation handler; notification_response handler; EventBus routing; settings_sync |
| `backend/agent/conversation_kernel.py` | 3, 5.5 | Emit utterances, filter speech; silence timer for voice filler; AskUserQuestion voice flow; agent-initiated speech |
| `backend/agent/tts.py` | 3, 5.5 | Subscribe to utterance events only; subscribe regardless of voice command state (agent-initiated speech) |
| `backend/agent/streaming.py` | 3, 4 | Stream through EventBus, not direct TTS; stream mode changes |
| `backend/agent/der_constants.py` | 4 | Add `ExecutionMode` enum, mode budgets, iteration caps, voice preference default |
| `backend/agent/der_loop.py` | 4 | `DirectorQueue` gains `current_mode`/`set_mode`/`escalate`/`de_escalate`/`mode_history`; `QueueItem` gains mode field; dynamic step injection on escalation |
| `backend/agent/tool_bridge.py` | 5, 5.5 | Permission check before execute_tool; register `ask_user_question` tool |
| `backend/vision/permission_system.py` | 5 | Extend for general tools, tiered risk |
| `backend/capabilities.py` | 5 | Per-tool approval on top of mode |
| `hooks/useIRISWebSocket.ts` | 2, 5.5, 6 | conversation_id in voice_command_start; switch_conversation; settings_sync; task_update/context_usage/agent_question forwarding; sendAgentQuestionResponse |
| `components/chat-view.tsx` | 2, 5.5, 6 | switch_conversation on thread select; TaskListCard + ContextPill + QuestionCard rendering; event listeners |
| `components/iris/XurOrb.tsx` | 2, 5.5, 6 | Reconnecting state; OrbBadge rendering (working + question states) |

### Docs (2, already written)

| File | Purpose |
|------|---------|
| `docs/architecture/agent-multi-step-architecture.md` | Architecture overview (this plan references it) |
| `docs/plans/2026-07-06-agent-multi-step-tool-execution.md` | This plan |

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| DER mode changes break existing DER tests | Update `test_der_loop.py` to assert new Director-decided mode contract; do not skip |
| Kernel separation breaks TTS timing | Phase 2 contract tests verify TTS only receives utterances; preserve existing chunk sizing logic |
| ConversationContextStore disk I/O blocks async | Use `asyncio.to_thread()` for all disk operations |
| Permission timeout kills long tasks | Timeout only applies to approval wait, not tool execution; 30s/60s is generous |
| OrbBadge aesthetic mismatch | Use same `glowColor` and particle rendering as `OrbCanvas`; behavioral test verifies aesthetic match |
| WS reconnect race condition | `ConversationContextStore.get_or_restore()` is atomic; frontend re-sends `switch_conversation` on reconnect |
| Stale tests give false confidence | Step 6.4 stale test audit is mandatory; every existing test file read and verified |
| Agent runs old tests to fake a pass | Testing Discipline Rule 4: never modify tests to pass, never skip failures, never use xfail to hide |
| Behavioral tests miss edge cases | Contract tests cover interface edges; behavioral tests cover user-visible flows; both required |

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
