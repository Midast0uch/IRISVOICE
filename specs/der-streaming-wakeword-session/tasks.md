# Tasks: DER Streamed Thinking + Wake-Word Last-Active Session Binding

> Each task links to a requirement. Grouped into waves for parallel execution.
> Ripple areas are called out per task so no dependent code is missed.

## Wave 1 — Session recency foundation (REQ-1, REQ-2)
- [ ] T1 (REQ-1, REQ-2): Add `last_active_session_id` + `_session_activity_order` and
  `touch_session(session_id)` to `SessionManager` (backend/sessions/session_manager.py).
  Update on connect/message/switch. — UNIT: UT-1
- [ ] T2 (REQ-1, REQ-2): Call `touch_session` from `ws_manager.connect`
  (backend/ws_manager.py:117-138) after `create_session`, and from the message dispatch
  path. RIPPLE: ensures new frontend threads register as last-active.
- [ ] T3 (REQ-1, REQ-2): Rewrite `main.py:_on_wake_word_async` (2028-2081) resolution
  priority: last_active_session_id → get_active_session_ids()[-1] → headless. Replace
  `except: pass` with logged fallback. RIPPLE: none on frontend (handler already correct).

## Wave 2 — Wake-word broadcast (REQ-1, REQ-2)
- [ ] T4 (REQ-1, REQ-3): Send `wake_detected` via `broadcast_to_session(session_id, ...)`
  (ws_manager.py:332) to ALL clients in the session. RIPPLE: frontend useIRISWebSocket.ts:652
  already handles it — add contract test CT-1 to lock the shape.
- [ ] T5 (REQ-6): Add observability log for wake resolution (resolved session_id, source,
  delivered?) scoped by session_id. Bounded/sampled.

## Wave 3 — DER intent gating (REQ-4, CORRECTED 2026-07-19)
> CORRECTION: the original REQ-4 assumed "simple prompts never hit DER" (false — see
> requirements.md REQ-4 Verified). The real fix is a layered, rule-first intent classifier
> (`_classify_intent`) that routes action/followup prompts to DER and standalone
> questions/chit-chat to the direct path. Memory is preserved on BOTH paths (direct path
> still fragments to Pacman/vector store — agent_kernel.py:4148-4184), so gating is about
> COST (Cerebras burst), NOT memory coverage.
- [x] T6 (REQ-4): Implement `_classify_intent` layered cascade (deterministic prefix →
  action-verb keyword → follow-up-to-task context → default question) returning
  chat/action/followup/question. 0 model calls (negative routing, per Hermes ARC /
  Anthropic agentic patterns). Replaced `_is_action_request` with `_is_action_request` +
  `_is_followup_to_task`. RIPPLE: `_needs_planning(text, context)` now takes context for
  multi-turn inertia; call site at process_text_message:4042 updated.
- [x] T7 (REQ-4): Rewrite `_needs_planning` to return True only for intent in
  (action, followup); chat/question → direct path. Ambiguous middle defaults to DER (safe
  fallback), never to the dumb direct path. Added "list" to _ACTION_VERBS. RIPPLE: none on
  frontend.
- [x] T6b (REQ-4, AC5/AC6): Verified direct path persists to memory (conversation +
  Pacman) so chit-chat is NOT excluded from memory. Added `_is_followup_to_task` for
  anaphora/confirmation follow-ups → DER (richer memory + planning).
- [x] T6c (REQ-4): Updated backend/tests/test_universal_planning.py to assert corrected
  behavior (action→DER, standalone question→direct, followup→DER, chit-chat→direct). All 7
  tests pass.

## Wave 4 — Streamed DER + answer (REQ-3)
- [ ] T8 (REQ-3): Switch Cerebras path (agent_kernel.py:2289) to streaming; extend
  `chunk_callback` (2332-2341) so the answer streams token-by-token to ChatView.
  RIPPLE: ChatView consumes existing stream shape — contract test CT-2.
- [ ] T9 (REQ-3): For complex prompts, run DER full as ONE streamed connection (replace
  the 5 discrete sequential calls in the 4953-5042 loop with a streamed reasoning call
  that still consults Mycelium). Preserve Director→Reviewer→Explorer gating.

## Wave 5 — Rate-limit backoff (REQ-5)
- [ ] T10 (REQ-5): Rewrite 429 retry (agent_kernel.py:2291-2298) to read
  `x-ratelimit-reset`/`Retry-After` and wait for the window; bounded exponential backoff
  (cap 30s) when no header; ledger record + user-visible error on exhaustion.
- [ ] T11 (REQ-6): Add per-prompt observability log (Cerebras calls, local calls,
  lite/full path) scoped by session_id/thread_id. Bounded.

## Wave 6 — Verification
- [ ] T12 (REQ-1, REQ-2): Behavioral BT-1 (wake at startup), BT-2 (new-thread wake).
- [ ] T13 (REQ-3, REQ-4): Behavioral BT-3 (simple ≤1 Cerebras call + stream), BT-4
  (short-complex → full DER).
- [ ] T14 (REQ-5): Behavioral BT-5 (429 → wait reset → retry success).
- [ ] T15: Extend scripts/validate_der_*.py CDD harness with trajectories (a-e).

## Dependency / parallelization notes
- Wave 1 MUST land before Wave 2 (broadcast needs last_active_session_id).
- Wave 3 (intent gating, REQ-4 CORRECTED) is COMPLETE — `_classify_intent` cascade +
  `_needs_planning` + follow-up detection + test_universal_planning.py all done. Memory
  persistence on the direct path verified (AC5/AC6).
- Wave 4 (streaming) depends on Wave 3's entry hook (process_text_message) but not on
  session work — can overlap with Wave 2.
- Wave 5 (backoff) is fully independent of session work; parallel with Waves 1-4.
- Frontend needs NO code changes (verified: useIRISWebSocket.ts:652 and NavigationContext
  already correct) — only contract tests CT-1/CT-2 to lock shapes.
- Backend-independent work (T6, T10, T7) may run parallel with frontend contract tests.
- KEY INVARIANT (user concern, resolved): gating DER on intent is about COST, not memory.
  The direct path STILL writes chit-chat/questions to conversation history + Pacman vector
  store (agent_kernel.py:4148-4184). The agent's memory is never starved of conversational
  context; only the expensive DER planning burst is skipped for trivial turns.
