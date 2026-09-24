# Tasks: Reply Surface Contract

> **How to read this file.** Tasks are numbered in the order you execute them.
> Each wave is a self-contained, shippable increment: it changes code, then
> verifies it with its own tests, before the next wave begins. Do not start a
> wave until the previous one is green.
>
> **Legend**
> - `REQ-n` — the requirement (in `requirements.md`) this task satisfies.
> - **Also affects:** — other files/functions that must keep working; the task is
>   not done if one breaks.
> - **Verify:** — the tests that prove the wave is done. `CT-n` = contract test
>   (pins an interface *shape*); `BT-n` = behavioral test (drives a full turn and
>   checks the *outcome*).
>
> **Wave order (each builds on the last):**
> 1. Card trigger is correct (backend) — *what gets a card*
> 2. Card presentation (frontend) — *how a card looks*
> 3. Progressive reply (latency) — *when the reply appears*
> 4. Card identity + question lifecycle (separate feature)
> 5. Render-as-tool (depends on 1 + 3)

---

## Wave 1 — Card trigger is correct (backend, one atomic change)

**Goal:** a card appears **iff** the agent produced a `show` artifact — never because
the reply was long, nor because it looked structural. This wave is deliberately
atomic: the length/zone heuristic is *removed* in the same wave the `show`-presence
rule is confirmed, so cards never go missing in between.

### Code

- [x] T1 (REQ-2, REQ-14): Make `show`-presence the SOLE card trigger. ✅ DONE 2026-09-21. Delete the
      length/zone auto-render heuristic (`_heuristic_ok` block at
      `agent_kernel.py:4290-4299` and its auto-render emit `:4300-4379`; the
      empty-websearch guard `:4286-4289` and `_is_empty_websearch_synthesis` guard
      stay). Render a card **only** when the agent produced a `show` artifact —
      NEVER on length, zone, provenance, or a structural signal. Add the
      **log-only** `show_omitted_on_artifact` calibration signal (structural
      detector: table / fenced code / list) — it MUST NOT trigger a render.
      Strengthen the `show` instruction in `[RESPONSE FORMAT]` (`:2170-2179`) so the
      model emits it reliably. Preserves the 2026-08-17 pin
      (`agent_kernel.py:4416-4427`). — `backend/agent/agent_kernel.py` —
      **Also affects:** `_maybe_escalate_web_format` (`:5085`) must work with no card
      present; the DER path (`:7602`) uses the same seam; REQ-4 AC2 and
      `test_display_text_never_truncated` must stay green.
- [x] T2 (REQ-15): Demote `_engine_gate_surface` to an **async observer**. ✅ DONE 2026-09-21 — `_observe_surface_async` daemon thread; verdict recorded, never steers. Remove
      the blocking call from the reply path (`agent_kernel.py:4290`); resolve the
      `presentation` decision off-path (`:13664`); move the **live** render
      authority to the `tool_choice` consumer; record observer-vs-live disagreement
      as calibration signal. The consumer is **preserved, not deleted**. —
      `backend/agent/agent_kernel.py` — **Also affects:** cross-spec
      `specs/tool-decision-engine` REQ-11; engine default
      `IRIS_DECISION_ENFORCE="tool_choice"` unchanged (`decision_engine.py:91`).
- [x] T3 (REQ-3): Route the bubble from the agent's `speak` line on a card turn; ✅ DONE 2026-09-21.
      use `_supportive_text` only when no `speak` exists (`agent_kernel.py:4381-4399`,
      `:13736`). — `backend/agent/agent_kernel.py` — **Also affects:**
      `_finalize_response` (`:4108`) already separates TTS; do not change its
      signature.
- [x] T4 (REQ-8): Keep the TTS lane independent — `speak` → `_last_spoken_text`, ✅ DONE 2026-09-21 — plain branch passes `speak` through; gateway fallback unchanged.
      else `prepare_spoken_text` (`agent_kernel.py:4036`); assert no cross-lane
      truncation. — `backend/agent/agent_kernel.py` — **Also affects:**
      `iris_gateway.py:5897-5899` fallback and narration gate `:3852` unchanged.
- [x] T5 (REQ-4): Confirm both synthesis paths apply identical `show` routing ✅ DONE 2026-09-21 — VERIFIED: both call sites (`agent_kernel.py:6948` direct, `:7555` DER) invoke the shared seam with identical arguments; no helper needed.
      (direct `:6995`, DER `:7602`); add a shared helper if the two diverge. —
      `backend/agent/agent_kernel.py` — **Also affects:** `_synthesize_response`
      (`:17700`) and `_der_synthesize_success_outcome` (`:13231`) produce text only;
      no change expected (verify).
- [x] T6 (REQ-9): Per-turn surface logging records lane + `show`-present + ✅ DONE 2026-09-21 — `_log_surface` at every seam exit; `show_omitted_on_artifact` calibration signal; logger-only, off the critical path.
      bubble-source, and logs a distinct "card suppressed (no show)" signal. —
      `backend/agent/agent_kernel.py` — **Also affects:** instrumentation stays off
      the critical path (AC3); reuse existing `record_decision`.

### Verify

- [x] T7 (REQ-1, REQ-2, REQ-4) — **CT-3**: extend ✅ DONE 2026-09-21 — `TestShowPresenceIsTheSoleCardTrigger` (3 tests) added.
      `backend/tests/contract/test_display_text_never_truncated.py` — a plain reply
      never emits `DOCUMENT_RENDER`; a `show` markdown reply does; a long plain
      reply still does not. — `backend/tests/contract/` — **Also affects:** CT-1
      (`test_structured_response.py`) and CT-2
      (`test_document_render_contract.py`) stay green.
- [x] T8 (REQ-1, REQ-3) — **CT-4**: new contract test — the bubble on a card turn ✅ DONE 2026-09-21 — `test_card_turn_bubble_is_speak.py` (5 tests).
      equals the `speak` line, never the card body. — `backend/tests/contract/` —
      **Also affects:** BT-2 shares fixtures.
- [x] T9 (REQ-2, REQ-14, REQ-15) — **CT-10 + CT-12**: the decision-engine consumer ✅ DONE 2026-09-21 — `test_surface_observer_contract.py` (4 tests: consumer set, non-blocking thread proof, observer cannot steer, determinism).
      set is `{tool_choice, presentation (async observer), narration}` with no
      blocking call on the reply path; the same reply yields the same surface across
      repeated runs. — `backend/tests/contract/` — **Also affects:** cross-spec lock
      with `specs/tool-decision-engine`.
- [x] T10 (REQ-1, REQ-2, REQ-3, REQ-8, REQ-14, REQ-15) — **BT-1…BT-5 + BT-9 + ✅ DONE 2026-09-21 — `test_reply_surface_behavior.py` (7 tests).
      BT-10**: behavioral drives — 1500-char answer → plain bubble, no card;
      `show` artifact → card + supportive line; TTS speaks `speak` on both; empty
      websearch → plain text; reply completes with the decision engine stopped;
      same reply twice → same surface. — `backend/tests/behavioral/` — **Also
      affects:** each gap decomposes to its CT (BT-1 → CT-3).
- [x] T11 (REQ-9) — CDD harness: `scripts/validate_der_*.py` replays a recorded ✅ DONE 2026-09-21 — `scripts/validate_der_reply_surface.py` (13 checks, all PASS).
      websearch trajectory and asserts: card only with `show`, bubble = `speak`,
      no length-triggered card. — `scripts/` — **Also affects:** standing harness
      runs every run; must not regress.

---

## Wave 2 — Card presentation (frontend)

**Goal:** a card looks right — collapsed to a peek with a chevron, no content-type
badge, and the supportive line sits *after* the card.

### Code

- [x] T12 (REQ-6): Wire `RichDocument` to `CardChassis`'s existing `collapsible` ✅ DONE 2026-09-21 — `collapsible={hasBody}` + `defaultCollapsed`; 460px remains the PEEK cap after the chevron.
      (currently `collapsible={false}` at `RichDocument.tsx:181`) so the card is
      collapsed to its header row by default and the chevron unfolds the body in
      place; keep `COLLAPSED_MAX_HEIGHT = 460` (`:52`) as the PEEK height. —
      `components/chat/RichDocument.tsx` — **Also affects:** `CardChassis.tsx`
      (`collapsible`/`defaultCollapsed`/`onCollapsedChange` already implemented);
      `DocumentPanel.tsx` full-view unchanged (`:7-10`).
- [x] T13 (REQ-6 AC3/AC4): Verify the existing `Expand` icon → `DocumentPanel` ✅ DONE 2026-09-21 — pinned by `prism-card-collapse.contract.test.tsx` (onExpand fires; inline card stays collapsed).
      path (`RichDocument.tsx:204-217`; `chat-view.tsx:4669-4705`) still opens the
      full view and that panel close returns to the collapsed card. —
      `components/chat/RichDocument.tsx`, `components/chat-view.tsx` — **Also
      affects:** the shared-chassis import (`DocumentPanel.tsx:7-10`).
- [x] T14 (REQ-5): Remove `ContentTypeIcon` + `{contentType}` label from both ✅ DONE 2026-09-21 — both bubble branches + the component; `detectContentType`/`getContentType` retained.
      bubble branches (`chat-view.tsx:3738-3739`, `:4003-4004`); keep
      `detectContentType` (`:2480`) for other uses. — `components/chat-view.tsx` —
      **Also affects:** file/image/video explicit-upload rendering unaffected;
      truncated-message expand retained.
- [x] T15 (REQ-3 AC3): Order the supportive bubble AFTER the prism card in the ✅ DONE 2026-09-21 — doc-join block hoisted above the bubble; `bubbleDuplicatesCard` guard suppresses a duplicated opening (emit-failure equality case protected).
      thread (doc join by `turnId`, `chat-view.tsx:4190-4206`); suppress the bubble
      when `speak` duplicates the card opening. — `components/chat-view.tsx` —
      **Also affects:** history reload ordering (`:4200`); multi-doc websearch turn
      (JSON card + markdown synthesis) attaches the line to the synthesis card.

### Verify

- [x] T16 (REQ-5, REQ-6) — **CT-5 + CT-6**: frontend contract tests — no ✅ DONE 2026-09-21 — `chat-view-surface.contract.test.ts` (4 tests, source-level) + `prism-card-collapse.contract.test.tsx` (collapsed/chevron/empty-body AC5).
      content-type badge in the plain-text branch; card renders collapsed with a
      chevron and the Expand→panel path works; a card with NO body renders
      header-only with no chevron and no Expand (REQ-6 AC5). —
      `__tests__/components/` (or existing FE harness) — **Also affects:** none.
- [x] T17 (REQ-3, REQ-5, REQ-6) — **BT-11** (renumbered from BT-4; design BT-4 is ✅ DONE 2026-09-21 — in `prism-card-collapse.contract.test.tsx`: collapsed → peek in place → panel, one drive.
      the REQ-7 card-edit drive): frontend behavioral drive — a card
      turn renders collapsed, expands in place, and shows the supportive line after
      the card. — `__tests__/components/` — **Also affects:** shares fixtures with
      CT-5/CT-6.

---

## Wave 3 — Progressive reply (latency)

**Goal:** the bubble and TTS appear as soon as the `speak` line exists — they no
longer wait for the whole document. Independent of the engine work; may start once
Wave 1 is green.

### Code

- [x] T18 (REQ-13 AC1/AC3/AC4): Speak-first progressive reply — emit the `speak` line ✅ DONE 2026-09-21 — `_emit_reply_progressively` in the DER path; `card_ms` + `mark_card()` in TurnMetrics; `_active_turn_metrics` hand-off.
      as the first streamed chunk, then stream the `show` body; do not gate bubble/TTS
      on document completion (`agent_kernel.py:17700`, `:7592-7595`); add TTFT +
      time-to-card to `TurnMetrics` (`observability.py:136,137`). —
      `backend/agent/agent_kernel.py`, `backend/utils/observability.py` — **Also
      affects:** `inference/router.py:895` `chunk_callback` already supports
      streaming (NO CHANGE); gateway `sentence_queue` (`iris_gateway.py:3300`)
      consumes chunks.
- [x] T18b (REQ-13 AC2/AC5): **BUILD the card partial channel** (does not exist ✅ DONE 2026-09-21 — `partial` on the seam emit (False=final) with documented first-partial-id contract; `handleDocumentRender` suppresses the badge while partial; `RichDocument` gains `partial` prop rendering open during streams.
      today). Add a `partial`/`streaming` discriminator to the `DOCUMENT_RENDER`
      payload (`event_bus.py:97`; emits `agent_kernel.py:4508`), carry the stable
      `document_id` on the FIRST partial emit, and branch the frontend
      `handleDocumentRender` (`chat-view.tsx:1289-1338`) to suppress the "Updated"
      badge (`:1309`) while `partial` is set; add a `partial`/`streaming` prop to
      `RichDocument.tsx` (`:15-31`) so the body fills progressively. —
      `backend/agent/event_bus.py`, `backend/agent/agent_kernel.py`,
      `components/chat-view.tsx`, `components/chat/RichDocument.tsx` — **Also
      affects:** `DocumentDataStore` (`document_store.py:119,177`) stays
      whole-document (NO CHANGE — the stream rides the event, not the store);
      `CardChassis` unchanged. Fall back to a single whole-body emit after the
      `speak` bubble if the provider cannot stream a partial card.
- [x] T18c (REQ-13 AC6): Add `turn_id` to the text-path `chat_chunk` payload ✅ DONE 2026-09-21 — all three text-path emits carry the turn's id; text response at :5910 already uses the same.
      (`iris_gateway.py:5755-5756`); the frontend already drops a chunk without it
      (`chat-view.tsx:1241-1242`), so this makes the non-voice path progressively
      render. Voice path already carries `turn_id` (`iris_gateway.py:3336-3337`) —
      do not change it. — `backend/iris_gateway.py` — **Also affects:** CT-11 must
      pin the `chat_chunk` payload shape on BOTH paths.

### Verify

- [x] T19 (REQ-13) — **CT-11 + BT-8**: the first streamed chunk contains the ✅ DONE 2026-09-21 — `test_progressive_reply_contract.py` (7 tests: speak-first, body-never-streams, plain single chunk, flush-only, never-raises, payload partial+id, card_ms, chat_chunk turn_id) + `test_progressive_reply_behavior.py` (BT-8 ×2).
      spoken line, not the document; assert `ttft_ms < time_to_card_ms`; assert the
      `chat_chunk` payload carries `turn_id` on the text path; assert a partial
      `DOCUMENT_RENDER` updates the same card in place without an "Updated" badge. —
      `backend/tests/contract/`, `backend/tests/behavioral/` — **Also affects:**
      none.

---

## Wave 4 — Card identity + question-card lifecycle (separate feature)

**Goal:** every card has a stable identity, and question cards dismiss reliably.
Touches different surfaces from Waves 1–3; may run in its own lane once Wave 1 is
green.

### Code

- [x] T20 (REQ-10): Mint a stable `card_id` for every prism card at emit ✅ DONE 2026-09-21 — `card_doc_*` minted in the seam, reused by update/reformat, `_card_envelope` extended for document ids.
      (`agent_kernel.py:4463` mint; `:4505-4523` payload), keep `document_id` as
      the store key, and extend `_card_envelope` (`:10042`) to resolve prism
      `card_id`. — `backend/agent/agent_kernel.py` — **Also affects:**
      `DOCUMENT_RENDER` consumers get an additive field; `_store_document_data`
      (`:4632`) unchanged; update/reformat reuse the same `card_id` (REQ-7).
- [x] T21 (REQ-11): Render question cards in turn order instead of the bottom ✅ DONE 2026-09-21 — `turn_id` now rides the QUESTION_ASK data payload (bridge drops the envelope one); anchored join in the message block; bottom block is the unanchored fallback.
      block (`chat-view.tsx:4514-4538`), anchoring to the `QUESTION_ASK` `turn_id`
      (already emitted, `ask_user_tool.py:161`). — `components/chat-view.tsx` —
      **Also affects:** `useAgentQuestion.ts` event handling; multi-question sets
      stay grouped; reload rehydration.
- [x] T22 (REQ-12): Add optimistic removal on `onAnswer` (`chat-view.tsx:4524-4535`) ✅ DONE 2026-09-21 — optimistic removal, idempotent resolve handler, self-dismiss at countdown zero, supersession prune on turn finalization, in-memory map means empty on reload (AC5).
      mirroring `removePendingPermission` (`:4494,4501,4508`); make the
      resolved/timeout handler (`:1639-1660`) idempotent; self-dismiss on countdown
      expiry (`QuestionCard.tsx:84,95`); dismiss a superseded question when its turn
      finalizes; reconcile on reload. — `components/chat-view.tsx`,
      `components/chat/QuestionCard.tsx` — **Also affects:** late-answer guard
      (`iris_gateway.py:6296-6304`) already ignores late answers; do not dismiss an
      actively-blocking question on AC3.

### Verify

- [x] T23 (REQ-10) — **CT-7**: extend CT-2 — `DOCUMENT_RENDER` carries a stable ✅ DONE 2026-09-21 — 3 tests in `test_document_render_contract.py` (mint shape, update+reformat reuse, unknown inert).
      `card_id`; the same `card_id` survives update + reformat; an unknown
      `card_id` is inert. — `backend/tests/contract/test_document_render_contract.py`
      — **Also affects:** BT-6 shares the fixture.
- [x] T24 (REQ-11, REQ-12) — **CT-8 + CT-9 + BT-6 + BT-7**: question card anchored ✅ DONE 2026-09-21 — CT-8/CT-9 source pins in `chat-view-surface.contract.test.ts`; BT-6/BT-7 in `QuestionCard.lifecycle.test.tsx`.
      to its `turn_id`; answering removes it without a backend broadcast; a lost
      broadcast does not resurrect it; a superseded question does not linger. —
      `__tests__/components/` + `backend/tests/behavioral/` — **Also affects:**
      BT-6 shares the CT-7 fixture.

---

## Wave 5 — Render-as-tool (depends on Waves 1 + 3)

**Goal:** the deterministic engine can *decide* to render, while the `show`
envelope remains the wire format (no extra round-trip).

### Code

- [x] T25 (REQ-16): Expose `render_document` to the `tool_choice` consumer so the ✅ DONE 2026-09-21 — registered ToolSpec + `_execute_render_document` dispatch in tool_bridge; emits the same DOCUMENT_RENDER shape with card_id; content required.
      engine governs render; keep the `show` envelope as the WIRE TRANSPORT (CT-1
      unchanged); stream args progressively (REQ-13 AC2); do NOT add model-task
      complexity (Decision 6). — `backend/agent/tool_registry.py`,
      `backend/agent/agent_kernel.py` — **Also affects:** read-side
      `get_rendered_documents`/`combine_documents` (`tool_registry.py:940,976`) NO
      CHANGE; empty-artifact guard `_is_empty_websearch_synthesis` (`:4129`)
      retained.

### Verify

- [x] T26 (REQ-16) — **CT-1**: the `show` wire shape is unchanged after render ✅ DONE 2026-09-21 — `test_render_as_tool.py` (3 tests); CT-1 suite untouched and staying green.
      becomes a tool decision; a missing tool layer falls back to the `show`
      envelope as the SOLE trigger (structural signal is log-only, never a render
      fallback). — `backend/tests/contract/` — **Also affects:**
      `test_structured_response.py` stays green.

---

## Wave 6 — Hydrated card body (depends on Wave 1; independent of 2–5)

**Goal:** a card that survives a reload still shows its body on expand — close the
cross-spec deadlock where hydration ships metadata-only and no expand-fetch exists.

### Code

- [x] T27 (REQ-17): Add a single-document body read scoped to the conversation — ✅ DONE 2026-09-21 — `_handle_get_document_body` + `get_document_body` dispatch + `iris:document_body` WS forwarding; scoped, missing-safe.
      gateway handler (e.g. `get_document_body`) returning stored `content` +
      `variants` for one `document_id` via `DocumentDataStore.get`
      (`document_store.py:364`); blob cards resolve through `get_blob`
      (`:232`). — `backend/iris_gateway.py`, `backend/agent/document_store.py` —
      **Also affects:** hydration payload stays metadata-only (CT-DOC-1, NO
      CHANGE); `ws_event_bridge.py` forwarding set (add the new message id).
- [x] T28 (REQ-17): On expand of a rehydrated card with no in-memory body, fetch ✅ DONE 2026-09-21 — doc joins admit documentId-only cards; `expandable` prop surfaces the Expand affordance; fetch on expand; in-place iris:document_body merge; DocumentPanel loading/unavailable/retry. NOTE: also fixed a Wave-2-opened regression — DocumentPanel's inner RichDocument now renders expanded (`defaultCollapsed={false}`).
      by `document_id` and render in `DocumentPanel` without re-emitting
      `DOCUMENT_RENDER` or duplicating the card; add the "unavailable" + retry
      states. — `components/chat-view.tsx`, `components/chat/DocumentPanel.tsx`,
      `lib/documentMerge.ts` — **Also affects:** `RichDocument.tsx` collapse
      affordance (REQ-6) is the trigger; merge keeps its idempotent
      content-preserving behavior (`documentMerge.ts:36-52`, NO CHANGE).

### Verify

- [x] T29 (REQ-17) — **CT-13 + BT-12** (renumbered from BT-9; design BT-9 is the ✅ DONE 2026-09-21 — `test_get_document_body.py` (3) + source pins in `chat-view-surface.contract.test.ts` + `DocumentPanel.bodystate.test.tsx` (4).
      no-blocking-engine drive in Wave 1): after a simulated reload, expanding a card
      issues one body fetch keyed by `document_id`, renders the stored content,
      and does not duplicate the card; a missing `document_id` yields the
      explicit unavailable state. — `backend/tests/contract/`,
      `backend/tests/behavioral/`, `__tests__/components/` — **Also affects:**
      shares the CT-2/CT-7 document fixtures.

---

## Appendix A — Areas verified as needing NO change

These already do the right thing; they only need their contract pin (already
covered by the CTs above). Listed so a reviewer sees at a glance what is *not*
touched.

`_respond_direct` (`:3053`); the two seam call sites (`:6995`, `:7602`);
`_der_synthesize_*` (`:13231`, `:13148`); `_maybe_escalate_web_format` (`:5085`);
`update_document` (`:4894`); `reformat_document` (`:5136`); `DocumentDataStore`
(`document_store.py:76`); `ws_event_bridge` (`:54,131`); `iris_gateway` chat message
+ TTS fallback (`:5902`, `:5897-5899`); `DocumentPanel` (`:7-10`);
`detectContentType` (`chat-view.tsx:2480`); `inference/router.py:895`
`chunk_callback`; `decision_engine.py:456` `decide`.

## Wave 7 — Unified routing, shadow first (REQ-18, 2026-09-22)

**Goal:** every turn enters the DER routing story; the direct branch becomes a
logged shadow, then is deleted. The executor (`_respond_direct`) is NOT
rewritten — it becomes the body of the trivial step.

### Code

- [x] T30 (REQ-18 AC1/AC2): Route-shadow writer + kernel hook at the ✅ DONE 2026-09-22 — one JSONL row
      `process_text_message` fork — one JSONL row per turn
      (`data/route_shadow.jsonl`), appended off-path, never raising. The
      classification IS the gate answer (`requires_der_kernel`); no LLM call,
      no extra blocking work. — `backend/agent/agent_kernel.py`
- [x] T31 (REQ-18 AC2): Prompt battery pins the classification contract ✅ DONE 2026-09-22 — 8 tests green.
      (`backend/tests/contract/test_turn_triviality_battery.py`) — chitchat/
      questions/short commands → trivial; websearch/multi-tool/files/
      reminders/compound → DER. Drives the REAL gate (`_needs_planning`).
- [x] T32 (REQ-18 AC3): Contract test: a trivial turn emits NO task card, ✅ DONE 2026-09-22 — pinned.
      before and after flip scaffolding exists. Pins the owner's rule:
      cards only for real multi-tool tasks.
- [ ] T33 (REQ-18 AC4–AC7, FUTURE — flip wave, after shadow parity evidence):
      DER loop admits a `trivial` queue item executing `_respond_direct`;
      direct branch deleted; `IRIS_UNIFIED_ROUTING=1` rollback flag during
      the evidence window. Verify: battery + live shadow agreement rate +
      overhead bound vs the direct path.

### Verify

- T30 logs visible on both routes; T31/T32 green; existing suites stay green.

---

## Wave 8 — Live-found fixes (2026-09-23, REQ-19 … REQ-22)

**Goal:**
kill the live-observed defects from the 2026-09-23 app drive (see the pin
`pin_19889f7af5fe`). Each requirement is in requirements.md under the
2026-09-22 review-notes wave.

### Code

- [x] T34 (REQ-19): turn-finalized stop-work — `_der_amend_graph` refuses ✅ DONE 2026-09-23.
      grafts/amendments once the turn's settle marker fired; refusals log
      `recovery_stopped_turn_finalized`. Also: the amendment / user-steering
      task:start emits now carry the REAL turn id in the event envelope
      (they used the conversation id — the "second agent" phantom).
- [x] T35 (REQ-20): card settle is final — `TaskCard.settled` marks the ✅ DONE 2026-09-23.
      terminal event; task:progress / task:learning / tool:call must not
      re-arm a settled card; mergeStart (a real task:start revision) clears
      it. Fixes the "Active Execution 23:59" on a failed run.
- [x] T36 (REQ-21 AC1): TTS first-chunk consumer budget 60s → 180s given the ✅ DONE 2026-09-23.
      measured ~90s lazy worker cold boot. (Boot stays lazy per the earlier
      REQ-5 decision; `_async_preload_tts` now also pre-warms the worker for
      the callers that do use it.)
- [x] T37 (REQ-22): (a) [RESPONSE FORMAT] now names document intent ✅ DONE 2026-09-23.
      directly ("write/make/create/draft a note/list/report/plan/document →
      produce `show`; never fence the whole answer in markdown"); (b) a
      whole-reply fenced answer is unwrapped at ingest — plain bubbles can
      no longer show raw `**` markers or clip a fence at the right edge.
- [x] T38 (REQ-22 + REQ-23 follow-up, 2026-09-23): the success-synthesis ✅ DONE 2026-09-23.
      fallback apology (": success, unclear — proceed" plan-step fragments)
      no longer lands in the bubble after a `show` runs; the same-stem retry
      graft is refused before `_split_step` runs. Bubble shows `speak`, the
      card is the artifact.

### Verify

- Backend targeted suites green (56 tests incl. all REQ-18 audit suites);
  frontend `prism-card-collapse`, `chat-view-surface`, `QuestionCard.lifecycle`,
  `DocumentPanel.bodystate`, `trust-routing`, `rich-document-expandable`,
  `chat-view-rehydration`, `chat-final-turnid` all green (50 tests); `tsc
  --noEmit` clean; `py_compile` clean. Live reinvents: restart the app and
  re-drive the green-tea/document prompt to confirm the card path engages.

---

## Appendix B — Contract locks (interface shapes pinned by a test)

| Shape | CT | Requirement |
|---|---|---|
| `{speak, show}` structured response | CT-1 | REQ-1, REQ-4 |
| `DOCUMENT_RENDER` event | CT-2 | REQ-2 |
| no card without an artifact | CT-3 | REQ-1, REQ-2 |
| bubble = `speak` on a card turn | CT-4 | REQ-1, REQ-3 |
| no content-type badge | CT-5 | REQ-5 |
| card collapsed by default | CT-6 | REQ-6 |
| stable prism `card_id` | CT-7 | REQ-10 |
| question card turn order | CT-8 | REQ-11 |
| question optimistic dismissal | CT-9 | REQ-12 |
| no blocking presentation on reply path | CT-10 | REQ-15 |
| speak-first streaming | CT-11 | REQ-13 |
| deterministic surface | CT-12 | REQ-14 |
| hydrated card body fetch | CT-13 | REQ-17 |

## Appendix C — Wave dependencies

- **Wave 1 is atomic** and must land first: it removes the length heuristic *and*
  confirms `show`-presence as the sole trigger together, so cards never go missing
  in between.
- **Waves 2 and 3 are independent of each other** and may run in parallel once
  Wave 1 is green (Wave 2 = frontend presentation; Wave 3 = backend streaming).
- **Wave 4 is a separate lane** (card identity + question lifecycle) and may run
  alongside Waves 2–3 once Wave 1 is green.
- **Wave 5 depends on Waves 1 + 3** (render authority + progressive streaming).
- **Wave 6 depends on Wave 1 only** and is independent of Waves 2–5 (it closes the
  rehydration blank-body gap; may run in its own lane).
