# Requirements: DER Streamed Thinking + Wake-Word Last-Active Session Binding

## Decisions Locked
- **DER stays a memory-driven thinking process.** We are NOT re-architecting DER's
  internal gates into a selectable graph. "Gates" in this spec = the *depth of DER
  engagement* (full multi-stage loop vs. DER-lite), chosen per-prompt, not a rewiring
  of the pipeline.
- **Three fixes are in scope (user-approved):** (3) DER internal thinking becomes a
  single streamed connection instead of 5 rapid discrete calls; (1) DER-lite fast path
  for simple conversational prompts (still uses memory, fewer/cheaper calls); (4)
  rate-limit-aware backoff that waits for `x-ratelimit-reset` instead of failing.
- **Final answer to ChatView is streamed token-by-token** (user preference — never
  all-at-once). This is stream #2 (answer), SEPARATE from stream #1 (internal DER
  thinking). Making internal thinking a single streamed call does NOT make the visible
  answer slower; it removes the 5-burst quota exhaustion that currently delays it.
- **Depth decision (simple vs complex) uses a LOCAL/CHEAP model**, not Cerebras — UPDATE
  (corrected 2026-07-19): the original audit claim that "simple prompts never hit DER"
  was WRONG. `_needs_planning()` (agent_kernel.py:1674) returns `not self._is_chitchat(text)`,
  so EVERY non-chitchat prompt — including simple factual questions — routes into the DER
  loop (lines 4114+), firing the Director+Reviewer+Explorer burst that exhausts the
  Cerebras 5/min quota. The docstring at 3994-3998 describes the INTENDED behavior
  ("Direct path default; planning only for tool-backed actions") which the code does NOT
  implement. REQ-4 is therefore retargeted to: (a) make `_needs_planning` actually gate DER
  to tool/action prompts only, so simple questions take the 1-call direct path (no
  "Working on it" filler, no rate-limit burst), and (b) collapse the remaining DER
  planning-path burst for genuine tool prompts. No separate depth model added.
- **Wake word always binds to the last active session / conversation thread**, at all
  times (startup included). It works with BOTH an existing thread AND a freshly created
  frontend thread. New session is created ONLY when the agent decides to, not by the
  wake-word logic. `wake_detected` is broadcast to ALL clients in the resolved session.

## Introduction
Two regressions block live use: (a) the wake word does not trigger the frontend UI at
startup because the backend cannot resolve the session/client at that moment, and (b)
every prompt fires ~4-5 rapid Cerebras calls through the DER loop, exhausting the
5-requests/minute quota and causing long delays. This spec fixes both while preserving
DER's memory-driven design and the token-by-token ChatView experience.

### Success criteria
- Wake word at startup activates the frontend `voiceState` ("listening") without a
  prior manual trigger.
- A simple conversational prompt completes without hitting the Cerebras rate limit
  (≤1 Cerebras call for the answer via the direct path; DER only for tool/action prompts).
- The final answer renders token-by-token in ChatView.
- Creating a new conversation thread in the frontend makes the wake word bind to it.

## Requirements

### REQ-1: Wake word resolves to the last active session at all times
**User Story:** As a user I want the wake word to always attach to my current
conversation thread — including at startup and after I open a new thread — so that
speaking "Hey Iris" always drives the right conversation.

**Verified:** backend/main.py:2028-2081 (`_on_wake_word_async` resolution priority);
backend/ws_manager.py:286-375 (`get_session_id_for_client`, `get_active_session_ids`,
`broadcast_to_session`); backend/sessions/session_manager.py:140-200 (`client_to_session`,
`get_session_by_client_id` — NO recency field exists today).

**Acceptance Criteria:**
- AC1: WHEN the wake word is detected THEN THE SYSTEM SHALL resolve `session_id` using,
  in priority order: (1) a tracked `last_active_session_id`, (2)
  `get_active_session_ids()[-1]` (most recent), (3) headless mode as last resort.
- AC2: THE SYSTEM SHALL track `last_active_session_id` in `SessionManager`, updating it
  on every session activity (message, connect, switch).
- AC3: WHEN a session is resolved THEN THE SYSTEM SHALL broadcast `wake_detected` to ALL
  clients in that session via `broadcast_to_session`, not a single resolved `client_id`.
- AC4: IF session resolution yields no active session THEN THE SYSTEM SHALL fall back to
  headless mode and SHALL log the fallback (no silent `except: pass`).

**Edge Cases:**
- Frontend WS connected but session not yet "active" at the instant of wake detection
  (startup race) — resolution must still find the session via `last_active_session_id`.
- Multiple frontend clients / multiple sessions open — bind to the most recently active.
- Session disconnected mid-wake — broadcast no-ops safely; audio cue still plays locally.

### REQ-2: Wake word binds to newly created frontend threads
**User Story:** As a user I want a conversation thread I just opened in the UI to be
wake-word-addressable, so "Hey Iris" on a fresh thread works immediately.

**Verified:** backend/ws_manager.py:117-138 (session auto-created as
`session_{client_id}` on WS connect); frontend has NO manual `create_session` call
(relies on backend auto-creation).

**Acceptance Criteria:**
- AC1: WHEN a new frontend connection creates a session THEN THE SYSTEM SHALL register
  it as the `last_active_session_id`.
- AC2: WHEN the wake word fires THEN THE SYSTEM SHALL be able to resolve the most
  recently created/active session, including one created after process start.
- AC3: THE SYSTEM SHALL NOT require a manual double-click/voice-label trigger before the
  wake word can address any session.

**Edge Cases:**
- Thread created but frontend tab backgrounded — session still resolvable.
- Rapid thread switching — `last_active_session_id` reflects the true latest.

### REQ-3: DER internal thinking is a single streamed connection (not 5 rapid calls)
**User Story:** As the system I want DER's reasoning to flow as one streamed thinking
process that consults memory, so that I do not fire 5 discrete blocking API calls that
exhaust the provider rate limit.

**Verified:** backend/agent/agent_kernel.py:4953-5042 (Director→Reviewer→Explorer loop,
re-reads Mycelium each cycle); :2289 (Cerebras non-streaming `httpx.Client`, 60s
timeout — the burst source); :2332-2341 (`chunk_callback` exists but unused on Cerebras
path).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL execute DER's internal reasoning as a single streamed provider
  connection per prompt (for complex prompts), replacing the 5 discrete sequential
  calls.
- AC2: WHILE the streamed thinking connection is open THEN THE SYSTEM SHALL consult
  Mycelium memory within the reasoning flow (DER's memory-driven property is preserved).
- AC3: THE SYSTEM SHALL emit the final answer to ChatView token-by-token via the
  existing `chunk_callback` / streaming message path (separate from internal thinking).
- AC4: IF the provider does not support streaming THEN THE SYSTEM SHALL fall back to the
  existing non-streaming path without changing DER behavior.

**Edge Cases:**
- Stream mid-flight error — THE SYSTEM SHALL surface a clear failure and record it to the
  ledger (no silent hang).
- Very long thinking — THE SYSTEM SHALL bound total thinking time and escalate to the
  Reviewer/VETO path if exceeded.

### REQ-4: Gate DER to tool/action prompts only (corrected reality)
**User Story:** As the system I want simple factual/conversational prompts to take the
fast direct-response path (1 Cerebras call, no "Working on it" filler), and ONLY
tool/action prompts to enter the DER planning loop — so I do not exhaust the
5-requests/minute Cerebras quota on prompts that never needed planning.

**Verified (against actual code, 2026-07-19 — corrected):** `_needs_planning()`
(agent_kernel.py:1674) returns `not self._is_chitchat(text)`. `_is_chitchat` (1627) only
matches pure social phrases (hi/thanks/how are you). Therefore EVERY non-chitchat prompt —
including simple questions like "what time is it" or "explain recursion" — routes into the
DER loop (lines 4114+), which fires the Director→Reviewer→Explorer burst (4953-5042) with
per-stage `for _attempt in range(3)` retries (2165/2287/2402/2511). That burst is what
burns the quota. The docstring at 3994-3998 describes the INTENDED behavior ("Direct path
default; planning only for tool-backed actions") which the code does NOT implement. The
fix is to make `_needs_planning` detect action/tool intent (web search, open/create/send/
set/remind/play/run, etc.) and return False (direct path) for everything else. A redundant
local-model depth decision is UNNEEDED: the existing heuristic gates depth for free.

**Memory is NOT starved by the direct path (verified 2026-07-19):** The user raised a
concern that the agent's memory is action-centric and conversational content must still
land in memory (incl. Pacman vector store) or the agent "falls on its face" dynamically.
Code review of `process_text_message` (agent_kernel.py:4148-4184) confirms the DIRECT path
STILL persists the turn: it calls `_conversation_memory.add_message("assistant", response)`
(4150) AND fragments the turn into the Pacman/vector store via `_mcm_orch.post_turn` /
`fragment_and_store` (4156-4184). So chit-chat and simple questions are written to BOTH the
conversation history and the semantic memory store — they only skip the DER *planning/tool
burst*, not memory persistence. The DER path additionally writes richer structured memory
(task outcomes, plan steps, tool results); for pure chit-chat that extra structure is
unneeded. Follow-ups that continue a prior task are routed to DER (see `_is_followup_to_task`)
so they get the richer memory + planning. Conclusion: gating DER on intent does NOT exclude
conversational content from memory — the concern is already handled by the existing direct-
path persistence. The spec correction is about COST (Cerebras burst), not memory coverage.

**Acceptance Criteria:**
- AC1: WHEN a prompt enters the DER planning path THEN THE SYSTEM SHALL reduce the
  discrete Cerebras call count versus the current 4-stages x 3-retries burst (e.g. via
  streaming the reasoning as one connection per REQ-3, and/or collapsing classifier
  stages), while still consulting Mycelium memory.
- AC2: THE SYSTEM SHALL NOT add a separate model call purely to decide depth — the
  existing `_is_chitchat`/`_needs_planning` heuristic gate is retained (free, no quota
  cost).
- AC3: IF a planning prompt is short-but-complex THEN THE SYSTEM SHALL still engage the
  FULL DER path (the heuristic already routes it there; no "short = simple" hardcoding).
- AC4: THE SYSTEM SHALL preserve DER's memory-driven property (Mycelium read) in the
  planning path.
- AC5: THE SYSTEM SHALL persist conversational/chit-chat turns to memory on the DIRECT path
  (conversation history + Pacman/vector fragmentation, agent_kernel.py:4148-4184) so that
  gating DER on intent never starves the agent's memory of conversational context. DER is
  gated on COST (Cerebras burst), NOT on memory coverage.
- AC6: THE SYSTEM SHALL route follow-ups that continue a prior task (anaphora / confirmation
  markers, `_is_followup_to_task`) into DER so they receive planning + richer structured
  memory, even when the follow-up carries no action verb of its own.

**Edge Cases:**
- Planning prompt that fails mid-loop — THE SYSTEM SHALL record to ledger and surface a
  user-visible error (no silent hang), per REQ-5.
- Ambiguous prompt — THE SYSTEM SHALL prefer FULL DER over skipping stages when uncertain.
- Chit-chat / simple question — THE SYSTEM SHALL take the direct path BUT still write the
  turn to memory (conversation + Pacman); it must NOT be excluded from memory entirely.

### REQ-5: Rate-limit-aware backoff (wait for reset, do not fail)
**User Story:** As the system I want a 429 response to wait for the provider's rate-limit
reset window instead of retrying immediately and failing, so that prompts are not
needlessly delayed or dropped.

**Verified:** backend/agent/agent_kernel.py:2291-2298 (retry sleeps only 1s→2s, does not
read `x-ratelimit-reset`; 3 attempts then gives up).

**Acceptance Criteria:**
- AC1: WHEN a provider returns HTTP 429 THEN THE SYSTEM SHALL read
  `x-ratelimit-reset` (or `Retry-After`) and wait until the window passes before
  retrying.
- AC2: IF no reset header is present THEN THE SYSTEM SHALL apply a bounded exponential
  backoff with a hard cap (e.g. max 30s) before giving up.
- AC3: IF all retries are exhausted THEN THE SYSTEM SHALL record the failure to the
  ledger and return a clear user-visible error (no silent drop).

**Edge Cases:**
- Reset window longer than user tolerance — THE SYSTEM SHALL surface "rate limited,
  retrying" to the user rather than blocking silently.
- Multiple concurrent prompts — THE SYSTEM SHALL coordinate quota usage so they do not
  all stampede the reset boundary.

### REQ-6: Observability for DER call-count and wake-word session binding
**User Story:** As the tuner I want measured signals for DER call-count per prompt and
wake-word session resolution, so that I can verify the rate-limit fix and the session
binding without guesswork.

**Verified:** NEW.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log, scoped by `session_id` and `thread_id`, the number of
  Cerebras calls and local-model calls per prompt, and which DER path (lite/full) was
  taken.
- AC2: THE SYSTEM SHALL log each wake-word resolution: resolved `session_id`, source
  (last_active / active_list / headless), and whether `wake_detected` was delivered.
- AC3: THE SYSTEM SHALL emit these on a non-critical path (no latency added to the
  user-facing response).

**Edge Cases:**
- High-volume — logs MUST be bounded / sampled, never grow unbounded.
- Missing `session_id` — fallback identifier used, never crash.

## Non-Requirements (Out of Scope)
- Re-architecting DER's internal gates into a selectable graph (user explicitly declined).
- Changing the provider tier or switching providers (Option 5) — config concern.
- Modifying the audio cue / Porcupine wake-word detection itself (detector is armed;
  only session resolution is broken).
- Frontend session-creation UI changes (backend auto-creates sessions on WS connect).

## Open Questions
- None blocking. All user decisions captured in Decisions Locked.
