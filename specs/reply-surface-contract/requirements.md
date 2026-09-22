# Requirements: Reply Surface Contract

Created 2026-09-21, session 346. Supersedes the open tasks of
`specs/chat-communication-lanes` (session 341) and absorbs the open threads of
pins `pin_a5ca27d9b20d` (synthesis-path audit) and `pin_3d97e8ff607a` (synthesis
brittleness handoff). Triggered by owner report: "audit and improve all the
paths in the ways the agent replies in chatview … it is not consistent nor
provides good UI/UX."

## Decisions Locked

Resolved with the owner in session 346 (do not re-litigate):

1. **Plain text is the DEFAULT reply surface.** Most turns are a plain-text
   bubble with normal markdown formatting. A prism card is the EXCEPTION.
2. **A prism card is an ARTIFACT the agent deliberately made** — sourced from
   websearch data, or curated with the user. "The agent can render or edit the
   prism card artifact at any time."
3. **`show` payload = the prism card.** The existence of a `show` payload is the
   ONLY card trigger. Length is never a reason to render a card.
4. **Three independent lanes:** BUBBLE (plain text, the answer) / CARD (prism
   artifact) / TTS (conversational narration). TTS is its own lane, always
   separate from the bubble.
5. **On a card turn, the bubble shows the agent's own `speak` line** (what it
   "says"), not a derived excerpt of the document. Card holds the artifact
   detail.
6. **The model's job must not get more complex.** The typed contract already
   exists (`show.format`); this spec organizes what is emitted, it does not ask
   the model to do more.
7. **Card lifecycle is shared:** both the agent (via `show`/`document_id`) and
   the user (format pills, edit, reopen) control the artifact.
8. **No plain-text content-type icon/badge** above the bubble.
9. **The prism card is collapsed by default.** Two-tier disclosure, reusing
   existing on-brand affordances (no new component): the card renders
   collapsed to its header row; the `CardChassis` header chevron unfolds the
   body in place (peek); the existing `Expand` icon opens the full
   `DocumentPanel` viewer. Chosen over a bare "document chip/button" because it
   preserves the card's visual identity, needs no new design language, and
   matches how task cards already collapse.
10. **Prism cards get a stable `card_id` like task cards**, alongside their
    existing `document_id` (content key). `card_id` is the lifecycle key; both
    are preserved across edits and reload.
11. **Question cards (AskUserQuestion) belong in turn order**, not bottom-pinned
    after the reply.
12. **Question cards dismiss reliably** — optimistic removal on answer, backend
    confirmation idempotent, self-dismiss on countdown expiry, and dismissal when
    the turn is superseded by a reply (mirroring the Session-331 permission-card
    fix).
13. **Speak-first, progressive reply** — the bubble/TTS emit from the `speak` line
    without waiting for the full document body; the card streams after.
14. **Surface decision is deterministic** — a card appears IFF a render artifact is
    produced; never as a function of reply length, zone, or model mood. Consistency
    is a first-class goal, not a side effect.
15. **The blocking presentation gate is removed from the reply path — the consumer
    is PRESERVED as an async observer.** Owner decision (OQ-3, Option C): the LIVE
    surface decision moves to the fast, enforced `tool_choice` path (no blocking);
    the `presentation` consumer keeps running off the critical path as a
    calibration observer. No functionality or use case is lost; replies get faster;
    the engine's surface judgment stays available for tuning and can be promoted
    later.
16. **Render-as-tool IS ADOPTED (owner decision, OQ-2).** Rendering is exposed as a
    `render_document` *decision surface* to the `tool_choice` consumer, while the
    `show` envelope stays the WIRE TRANSPORT (CT-1 unchanged) — so no extra model
    round-trip. The model's job does not get more complex (consistent with
    Decision 6).
17. **`show`-PRESENCE IS THE SOLE CARD TRIGGER (owner decision, OQ-1 — session 346).**
    A card is produced IFF the agent emitted a `show` payload; that payload IS the
    artifact signal. The structural signal (table/code/list/fenced block) is kept
    **LOG-ONLY as a calibration signal** — it is NEVER a render trigger. Length,
    zone, provenance, and model mood are never reasons to render a card. The
    `[RESPONSE FORMAT]` prompt is strengthened so the model emits `show` reliably;
    a "show omitted on artifact-shaped reply" signal is logged so prompt drift is
    measurable. This preserves the 2026-08-17 owner pin ("`show` IS THE STORAGE
    SIGNAL. No gate here.", `agent_kernel.py:4416-4427`).

## Introduction

Every synthesized reply funnels through one seam, `_process_structured_response`
(`agent_kernel.py:4195`), which infers reply structure from untyped model text.
The presentation decision and the bubble/card split are then made from length and
regex heuristics rather than from the artifact type the model already declared in
`show.format`. The result is inconsistent UX: cards for ordinary long answers,
bubbles that duplicate their card, supportive lines that never follow their card,
markdown artifacts that land as plain text, and content-type chrome the owner does
not want. This spec defines one coherent three-lane reply contract and makes
`show`-presence the sole artifact signal.

### Success criteria

- A long conversational answer never renders a prism card (no length-triggered
  card exists anywhere in the reply path).
- On a card turn, the bubble never duplicates the card body, and the supportive
  line renders AFTER the card, not before.
- A markdown artifact the agent produces renders as a prism card, not as plain
  text.
- No content-type icon/label renders above a plain-text bubble.
- A prism card is collapsed by default and expands via an explicit affordance.
- A prism card carries a stable `card_id` alongside its `document_id`.
- A question card appears in turn order and disappears when answered, timed out,
  or superseded by a reply.
- The three lanes (bubble / card / TTS) each have exactly one source of truth.
- All changes are covered by contract tests that fail on regression.

## Requirements

### REQ-1: Three-lane reply contract

**User Story:** As the owner I want each reply surface (bubble, card, TTS) to
have exactly one source of truth so that replies are consistent and never
duplicate each other.

**Verified:** `agent_kernel.py:4195` (`_process_structured_response`, the single
seam); `agent_kernel.py:4108` (`_finalize_response`, the single exit);
`agent_kernel.py:2170-2183` ([RESPONSE FORMAT] prompt already declares the
`speak`/`show` lanes).

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL route every reply through `_process_structured_response`
  as the single seam that assigns the bubble, card, and TTS lanes.
- AC2: WHILE no `show` payload is present, THE SYSTEM SHALL render the full
  model text in the chat bubble and emit no card.
- AC3: WHILE a `show` payload is present, THE SYSTEM SHALL assign the bubble from
  the model's `speak` line, the card from `show.content`, and the TTS line from
  `speak` — never deriving the bubble from the document body.
- AC4: THE SYSTEM SHALL assign the TTS line independently of whether a card
  rendered.

**Edge Cases:**

- Empty `speak` with a `show` present → bubble falls back to a deterministic
  first-sentence excerpt (existing `_supportive_text` behavior) but the card still
  carries full content.
- `show` present but card emit fails → full `show.content` returns to the bubble
  (existing `agent_kernel.py:4556-4559` behavior preserved).
- `speak` absent on a plain turn → TTS derived by `prepare_spoken_text`
  (`agent_kernel.py:4036`).

### REQ-2: `show` is the sole card trigger (remove length heuristics)

**User Story:** As the owner I want a card to render only when the agent
deliberately produced an artifact so that ordinary answers stay plain text.

**Verified:** REAL GAP. `agent_kernel.py:4291` currently sets
`_heuristic_ok = (self._pacman_zone_for_turn() == "reference" and len(response) >= 300)`,
which fabricates a card from plain text at `agent_kernel.py:4300-4379` even when
the agent emitted no `show`. The [RESPONSE FORMAT] prompt at
`agent_kernel.py:2166-2168` already says "A document card is not a way to present
a reply" — the code contradicts its own prompt.

**Acceptance Criteria:**

- AC1: WHEN a reply has no `show` payload THEN THE SYSTEM SHALL NOT emit a
  `DOCUMENT_RENDER` for that turn, regardless of response length or zone.
- AC2: THE SYSTEM SHALL remove the length/zone auto-render heuristic
  (`agent_kernel.py:4286-4379`) from the reply path.
- AC3: IF a reply has no `show` payload THEN THE SYSTEM SHALL return the full
  text to the bubble unchanged.
- AC4: WHERE the presentation engine gate (`_engine_gate_surface`,
  `agent_kernel.py:13664`) is consulted, THE SYSTEM SHALL NOT use it to fabricate
  a card for a reply that has no `show` payload.

**Edge Cases:**

- Empty-result websearch synthesis → plain bubble (preserve
  `_is_empty_websearch_synthesis`, `agent_kernel.py:4129` — the `def`; the
  `@staticmethod` decorator is on 4128).
- Web result captured but agent rendered no `show` → existing format-escalation
  QuestionCard path (`_maybe_escalate_web_format`, `agent_kernel.py:5085`) still
  applies; it must not be replaced by a fabricated card.
- Engine gate enforced but reply has no `show` → no card.

### REQ-3: No bubble/card duplication; supportive line follows the card

**User Story:** As the owner I want the bubble to support the card (not repeat
it) and to appear after the card so that the thread reads coherently.

**Verified:** REAL GAP. `_supportive_text` (`agent_kernel.py:13736`) is used at
`agent_kernel.py:4392-4399`; the bubble/card ordering is fixed by the frontend
render timeline (`chat-view.tsx:4190-4206` joins docs to a turn by id), so a
supportive bubble currently precedes the card and can duplicate the card body.

**Acceptance Criteria:**

- AC1: WHEN a card renders THEN THE SYSTEM SHALL NOT include the card body text
  in the bubble.
- AC2: WHEN a card renders with a `speak` line THEN THE SYSTEM SHALL render the
  `speak` line as the supportive bubble text.
- AC3: THE SYSTEM SHALL render the supportive bubble AFTER the prism card in the
  thread, not before it.
- AC4: THE SYSTEM SHALL NOT derive the supportive line by excerpting the card
  body when the agent supplied a `speak` line.

**Edge Cases:**

- `speak` line equal to card opening → treated as duplicate; bubble suppressed or
  replaced with a status-only line.
- Multiple documents in one turn (websearch: JSON card then markdown synthesis) →
  the supportive line attaches to the synthesis card, not the raw JSON card.
- History reload → ordering preserved after rehydration (docs joined by
  `turnId`, `chat-view.tsx:4200`).

### REQ-4: Markdown artifact renders as a prism card, not plain text

**User Story:** As the owner I want markdown the agent produced as an artifact to
render as a prism card so that it is not lost as a plain bubble.

**Verified:** REAL GAP. The frontend previously converted long markdown to a fake
"document" by length (`chat-view.tsx:3618-3628`, logic removed 2026-08-17), and
the reply path still routes a `show` with `format:"markdown"` inconsistently
depending on which synthesis path produced it.

**Acceptance Criteria:**

- AC1: WHEN the agent emits a `show` payload with `format:"markdown"` THEN THE
  SYSTEM SHALL render it as a prism card via `DOCUMENT_RENDER`.
- AC2: WHEN the agent returns a markdown artifact WITHOUT a `show` payload THEN
  THE SYSTEM SHALL render it as plain text (the agent failed to declare an
  artifact; the system SHALL NOT infer one from markdown syntax alone).
- AC3: THE SYSTEM SHALL ensure both synthesis paths (direct
  `agent_kernel.py:6995` and DER `agent_kernel.py:7602`) apply identical
  `show`-routing rules.

**Edge Cases:**

- Markdown with code fences only (conversation, not artifact) → plain bubble.
- `show.format` unknown value → treat as `text` and render as card if `show`
  present.
- Bare `.md` returned with no `show` → prompt already forbids it
  (`agent_kernel.py:2194-2195`); system renders plain text and does not fabricate.

### REQ-5: Remove plain-text content-type icon/badge chrome

**User Story:** As the owner I do not want a content-type icon or label above
plain-text replies so that the thread is visually clean.

**Verified:** REAL GAP. `ContentTypeIcon` plus an uppercase `{contentType}` label
render above the bubble at `chat-view.tsx:3738-3739` and
`chat-view.tsx:4003-4004`; `contentType` is assigned by
`detectContentType` (`chat-view.tsx:2480`) and typed at `chat-view.tsx:133`.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL NOT render `ContentTypeIcon` or the `{contentType}`
  uppercase label above a plain-text reply bubble.
- AC2: THE SYSTEM SHALL remove the `text` content-type badge from the truncated
  and non-truncated bubble branches.
- AC3: WHERE the card header already carries a trust pill, THE SYSTEM SHALL NOT
  add a redundant format/content-type badge (preserve the 2026-08-27 removal at
  `RichDocument.tsx:185-187`).

**Edge Cases:**

- File/image/video explicit uploads → their dedicated rendering is unaffected;
  only the generic plain-text badge is removed.
- Truncated long message → expand affordance retained, badge removed.
- Rehydrated history messages → no badge.

### REQ-6: Prism card collapsed by default with two-tier expand affordance

**User Story:** As the owner I want the prism card collapsed by default so the
thread stays clean and I click a chevron or the view icon to see it in full.

**Verified:** PARTIAL. `RichDocument.tsx` already measures overflow and offers an
in-body expand control (`bodyRef`/`expanded`/`overflows`, `RichDocument.tsx:157-176`;
`COLLAPSED_MAX_HEIGHT = 460`, `RichDocument.tsx:52`) and already has a full-view
`Expand` icon → `DocumentPanel` (`RichDocument.tsx:204-217`; `chat-view.tsx:4669-4705`;
`DocumentPanel.tsx:32`). BUT the chassis-level collapse is switched off:
`CardChassis collapsible={false}` (`RichDocument.tsx:181`), so there is no
always-present collapsed state and the header chevron is not used.

**Acceptance Criteria:**

- AC1: WHEN a prism card renders THEN THE SYSTEM SHALL present it collapsed to its
  header row by default.
- AC2: THE SYSTEM SHALL enable the `CardChassis` header chevron (`collapsible`,
  currently `false` at `RichDocument.tsx:181`) as the in-place peek affordance,
  rather than adding a new component.
- AC3: THE SYSTEM SHALL retain the existing `Expand` icon → `DocumentPanel`
  full-view path as the second disclosure tier.
- AC4: WHEN the user activates the chevron THEN THE SYSTEM SHALL unfold the card
  body in place without page navigation; WHEN the user activates Expand THEN THE
  SYSTEM SHALL open `DocumentPanel`.
- AC5: THE SYSTEM SHALL show the chevron only when the card has body content to
  reveal; an artifact with no body renders header-only with no affordance
  (preserving the existing `RichDocument.tsx:154-156` "no chrome at all" intent).
- AC6: THE SYSTEM SHALL NOT introduce a new document-chip/button component or a
  new visual language; the collapse reuses `CardChassis`.
- AC7: THE SYSTEM SHALL use the existing `COLLAPSED_MAX_HEIGHT = 460`
  (`RichDocument.tsx:52`) as the height of the in-place PEEK state (after the
  chevron is clicked), not as the default collapsed state.

**Edge Cases:**

- Artifact with an empty body → header-only, no chevron, no Expand.
- Very short artifact with a body → still collapsed to header; chevron present,
  peek reveals the (short) body.
- Peeked then format-switched → expansion state preserved.
- Peeked/expanded card on history reload → resets to collapsed (documented
  default).
- Image/diagram artifact → collapse applies to the card body; image still loads
  in the panel.
- Card opened from `DocumentPanel` → panel close returns to the collapsed card.

### REQ-7: Shared card lifecycle (agent and user)

**User Story:** As the owner I want both the agent and the user to create, edit,
and reformat the card artifact so that it is a shared workspace surface.

**Verified:** `update_document` (`agent_kernel.py:4894`), `reformat_document`
(`agent_kernel.py:5136`), format pills, and `DocumentDataStore`
(`document_store.py:76`) already exist; the gateway reformat entry is
`iris_gateway.py:10197`.

**Acceptance Criteria:**

- AC1: WHEN the agent emits a `show` with an existing `document_id` THEN THE
  SYSTEM SHALL revise that document in place and re-emit `DOCUMENT_RENDER`.
- AC2: WHEN the user selects a format pill THEN THE SYSTEM SHALL re-render the
  stored document in the chosen format via `reformat_document`.
- AC3: THE SYSTEM SHALL preserve `document_id` stability across edits so the card
  stays attached to its turn after a history reload.

**Edge Cases:**

- `document_id` no longer in store → create a new document and log the miss.
- Reformat on a card with no stored variants → generate the variant on demand.
- Concurrent agent edit and user reformat → last write wins, revision bumped.

### REQ-8: TTS lane independence

**User Story:** As the owner I want TTS to be its own lane so that speech quality
never depends on the card decision.

**Verified:** `prepare_spoken_text` (`agent_kernel.py:4036`), `_last_spoken_text`
(`_finalize_response`, `agent_kernel.py:4108`), gateway fallback at
`iris_gateway.py:5897-5899`, narration gate `_engine_permits_speech`
(`iris_gateway.py:3852`).

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL derive the TTS line from the agent's `speak` field when
  present, regardless of card state.
- AC2: WHEN no `speak` field is present THEN THE SYSTEM SHALL derive the TTS line
  via `prepare_spoken_text`.
- AC3: THE SYSTEM SHALL NOT truncate the bubble because TTS is speaking a shorter
  line.

**Edge Cases:**

- `speak` longer than the bubble → both retained; no cross-truncation.
- Empty reply → no TTS, no card.
- Card-only turn (`prism_card` surface) → TTS still speaks `speak`.

### REQ-9: Observability / tuning instrumentation

**User Story:** As the tuner I want each turn's surface decision recorded so that
I can measure how often each lane is chosen and tune the contract.

**Verified:** `_tool_bridge.record_decision(..., kind="surface")` already exists
at `agent_kernel.py:13717-13724`; contract tests exist for the structured seam.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL log, per turn, which lane was chosen (plain / card /
  card_plus_summary), whether a `show` payload was present, and whether the
  bubble was derived or from `speak`.
- AC2: THE SYSTEM SHALL log a distinct signal when a card was suppressed because
  no `show` payload was present.
- AC3: THE SYSTEM SHALL keep instrumentation off the critical response path.

**Edge Cases:**

- Missing turn id → log with a fallback id.
- High volume → sampled or debug-level only.
- Instrumentation failure → never blocks the reply.

### REQ-10: Unified card identity (prism cards carry a stable `card_id`)

**User Story:** As the owner I want a prism card to have a stable identity like a
task card so that lifecycle events (settle, dismiss, update) can address it and
it survives reload.

**Verified:** PARTIAL — REAL GAP. Prism cards already get a `document_id`
(`agent_kernel.py:4463`, `str(uuid.uuid4())`) that is stable across edits
(REQ-7 AC3) and persisted (`_store_document_data`, `agent_kernel.py:4632`). But
they do NOT participate in the `card_id` envelope: `_card_envelope`
(`agent_kernel.py:10042-10054`) resolves `card_id` only from `_card_by_task`
(task cards), and the `DOCUMENT_RENDER` payload carries `document_id` but no
`card_id` (emit at `agent_kernel.py:4505-4523`). The two card systems therefore
have different identity models, and a prism card cannot be addressed by the same
lifecycle machinery that settles/dismisses a task card.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL assign every prism card a stable `card_id` in addition to
  its `document_id`, minted once and reused across all events of that card's
  lifetime.
- AC2: WHEN a `DOCUMENT_RENDER` is emitted THEN THE SYSTEM SHALL include the
  stable `card_id` in the payload alongside `document_id`.
- AC3: THE SYSTEM SHALL keep `document_id` as the artifact-store key (unchanged);
  `card_id` is the lifecycle key, `document_id` is the content key.
- AC4: WHEN a prism card is updated or reformatted THEN THE SYSTEM SHALL reuse the
  same `card_id` (consistent with REQ-7).
- AC5: THE SYSTEM SHALL keep the identity addition backward-compatible — an
  unknown `card_id` is treated as "no card_id", never an error.

**Edge Cases:**

- Card created outside a DER task (direct-path `show`) → mint a `card_id` at emit.
- History reload → `card_id` rehydrates from the stored document.
- Missing `card_id` (older client) → fall back to `document_id`, log once.
- Two documents in one turn → each gets its own `card_id`; the turn keeps both.

### REQ-11: Question cards arrive in turn order, not bottom-pinned after the reply

**User Story:** As the owner I want a question card to appear where the agent
asked it in the thread so that the conversation reads in order.

**Verified:** REAL GAP. Question cards render from a standalone
`pendingQuestions` Map in a fixed block (`chat-view.tsx:4514-4538`), not joined
to the message timeline the way documents are (`chat-view.tsx:4190-4206` joins
docs by `turnId`). A question therefore always renders at the bottom of the
thread, after the reply that preceded it.

**Acceptance Criteria:**

- AC1: WHEN a question is asked during a turn THEN THE SYSTEM SHALL render its
  card in turn order, anchored to the turn that asked it.
- AC2: THE SYSTEM SHALL attach the question to its `turn_id` (already emitted on
  the `QUESTION_ASK` payload, `ask_user_tool.py:161`) so the frontend can place
  it inline.
- AC3: WHILE a question is pending THEN THE SYSTEM SHALL keep the card visible at
  its turn position (not re-ordered to the bottom).

**Edge Cases:**

- Question asked before any reply in the turn → card renders at the turn head.
- Multiple questions in one turn (a QuestionSet, `ask_user_tool.py:172`) → cards
  stay grouped in the order asked.
- History reload → question cards rehydrate at their turn (or are dropped if the
  question is no longer pending — see REQ-12).

### REQ-12: Question cards dismiss reliably (no lingering)

**User Story:** As the owner I want a question card to disappear as soon as it is
answered or the turn moves on so that stale cards never pile up.

**Verified:** REAL GAP. `onAnswer` only sends `question_response`
(`chat-view.tsx:4524-4535`) — there is NO optimistic removal, unlike the
permission-card path which removes optimistically via
`removePendingPermission(id)` (`chat-view.tsx:4494,4501,4508`, fixed Session-331
per the comment at `:4484-4490`). Question cards are removed ONLY by the backend
`question:answered`/`question:timeout` broadcast (`chat-view.tsx:1639-1660`), so a
missing or mis-routed frame leaves the card rendered indefinitely. The card also
has a self-countdown (`QuestionCard.tsx:84,95`) that reaches zero without
self-dismissing. Default backend timeout is 120s (`ask_user_tool.py:33`).

**Acceptance Criteria:**

- AC1: WHEN the user answers a question (click or text) THEN THE SYSTEM SHALL
  remove the card OPTIMISTICALLY, before the backend confirmation.
- AC2: WHEN the backend emits `question:answered` or `question:timeout` THEN THE
  SYSTEM SHALL remove the card (idempotent with AC1).
- AC3: WHEN the turn that asked the question finalizes with a reply THEN THE
  SYSTEM SHALL dismiss any still-pending question card for that turn, so a
  superseded question never lingers.
- AC4: WHEN the card's own countdown reaches zero THEN THE SYSTEM SHALL treat the
  question as timed out and dismiss it, without waiting for a broadcast.
- AC5: THE SYSTEM SHALL reconcile pending question cards against the message
  timeline on reload so a stale card from a prior session cannot rehydrate.

**Edge Cases:**

- Answer sent but backend broadcast lost → card already gone (AC1).
- Turn finalizes while a question is genuinely still awaiting the user → AC3 does
  NOT dismiss an actively-blocking question; only a superseding reply does.
- Question timed out then answered late → late answer is ignored
  (`resolve_answer` returns None, `iris_gateway.py:6296-6304`).
- Rapid ask → answer → ask in one turn → each card dismissed by its own id.

### REQ-13: Progressive reply (speak-first, never block the bubble on the card)

**User Story:** As the owner I want the reply to appear the moment the agent has
something to say so that a long document never stalls the conversation.

**Verified:** REAL GAP. `_synthesize_response` (`agent_kernel.py:17700`) returns the
**whole** string (`:17837`) with **no streaming** and a 120s deadline
(`der_constants.py:325`). The DER path emits it as a **single full-string chunk**
(`agent_kernel.py:7592-7595`), so the sentence splitter receives the entire answer
at once — there is no incremental first token. The bubble and TTS therefore wait
for the complete document (which may be thousands of tokens) before rendering.

Verification also confirmed three capabilities AC2/AC5/AC6 depend on **do not
exist yet** and must be BUILT, not merely wired:
- `DOCUMENT_RENDER` (`event_bus.py:97`) carries **no** `partial`/`chunk`/`streaming`
  field; every emit is a complete body, and `DocumentDataStore`
  (`document_store.py:119,177`) only writes whole documents. Re-emitting the same
  `document_id` replaces the body in place (`chat-view.tsx:1327-1337`), but there is
  no delta channel and `updated:true` renders an "Updated" badge
  (`chat-view.tsx:1309`) — wrong for a streaming card (AC5).
- `RichDocument.tsx` has **no** `partial`/`streaming` prop (`:15-31`); the card
  cannot receive progressive content (AC2).
- The text path sends `chat_chunk` with **no** `turn_id`
  (`iris_gateway.py:5755-5756`) and the frontend drops any chunk lacking one
  (`chat-view.tsx:1241-1242`), so the non-voice path is not progressively rendered
  today even though chunks are emitted (AC6).

**Acceptance Criteria:**

- AC1: WHEN the agent produces a reply THEN THE SYSTEM SHALL emit the `speak` line
  FIRST and render the bubble + TTS from it without waiting for the `show` document
  body.
- AC2: THE SYSTEM SHALL stream the `show` document content after the `speak` line
  so the card fills in progressively.
- AC3: THE SYSTEM SHALL NOT gate bubble/TTS emission on the completion of the full
  document generation.
- AC4: THE SYSTEM SHALL log time-to-first-token and time-to-card per turn
  (extends REQ-9).
- AC5: WHEN a card body is streamed THEN THE SYSTEM SHALL carry a stable
  `document_id` on the FIRST partial emit (so the frontend updates the same card
  in place) AND a partial/streaming discriminator on the payload, so a partial
  emit is never rendered as a final "Updated" revision.
- AC6: WHEN the text (non-voice) reply path streams a chunk THEN THE SYSTEM SHALL
  include the `turn_id` on the `chat_chunk` payload so the frontend can attach the
  delta to the correct turn (today the text-path payload is `{"chunk": ...}` only,
  `iris_gateway.py:5755-5756`, and the frontend drops any chunk without a
  `turn_id`, `chat-view.tsx:1241-1242`).

**Edge Cases:**

- Model emits `show` before `speak` → reorder to speak-first, or emit both when the
  document is small.
- No `speak` line → bubble uses the `prepare_spoken_text` fallback (`:4036`), still
  emitted before the document body.
- Streaming unsupported by the bound provider → fall back to whole-string emit,
  log once.
- Synthesis timeout → see REQ-14 degradation.
- Bound provider streams but the card channel has no partial semantics → fall back
  to a single whole-body emit AFTER the `speak` bubble (never block the bubble);
  log once. (Today `DOCUMENT_RENDER` carries no `partial`/`chunk` field and
  `DocumentDataStore` only writes whole documents — see Ripple-Effect Map.)
- Voice path already carries `turn_id` on `chat_chunk` (`iris_gateway.py:3336-3337`)
  → no change; only the text path needs AC6.
- REST path (`api/chat.py:185-201`) has no `chunk_callback` → REST clients receive
  the final reply only; progressive reply over REST is OUT OF SCOPE (Non-Requirements).

### REQ-14: Deterministic, consistent surface (no model-whim cards)

**User Story:** As the owner I want the card/no-card decision to be the same for
the same kind of reply every time so that replies feel consistent, not random.

**Verified:** REAL GAP. Today the card decision is split between a length/zone
heuristic (`agent_kernel.py:4291`) and a model-authored `show` field — neither is
deterministic across runs, which is the "sometimes it's not consistent" symptom.
Owner decision (session 346, Decision 17): accept `show`-presence as the sole,
deterministic trigger. The residual "model forgets to mark an artifact" risk is
made MEASURABLE (`show_omitted_on_artifact` log) and mitigated by a strengthened
prompt, rather than papered over with a non-deterministic structural fallback.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL make the card/no-card decision deterministically: a card is
  produced IFF a render artifact is produced — never as a function of reply length,
  zone, or model mood.
- AC2: THE SYSTEM SHALL resolve the card decision with NO classifier on the reply
  path: `show`-presence alone decides (Decision 17). The decision engine MAY observe
  the turn asynchronously for calibration (REQ-15) but MUST NOT gate the card.
- AC3: IF the model fails to mark an artifact (emits no `show` on a reply that
  carries a structural signal — table/code/list/fenced block) THEN THE SYSTEM SHALL
  NOT fabricate a card; it SHALL emit the reply as plain text AND log a
  `show_omitted_on_artifact` calibration signal so prompt drift is measurable
  (Decision 17). The structural signal is a *detector for logging*, never a render
  trigger.
- AC4: THE SYSTEM SHALL make the same reply produce the same surface across repeated
  runs (idempotent surface decision).

**Edge Cases:**

- Model emits no `show` but the content is a table/code block → **no card** (plain
  bubble) + `show_omitted_on_artifact` log line. (This is the case REQ-4 AC2 governs;
  AC3 above must agree with it — see Decisions Locked 17.)
- Model emits `show` for a one-line answer → card still produced (model is explicit;
  `show`-presence wins over any structural/length heuristic).
- Classifier unavailable → fall back to `show`-presence only (never length, never
  structural inference).
- Determinism test: same input twice → same surface.

### REQ-15: Decision-engine alignment (presentation gate demoted to async observer)

**User Story:** As the owner I want the reply path to pay no avoidable blocking
cost while KEEPING the decision engine's surface judgment so that replies are fast
AND the engine's value is preserved for calibration.

**Verified:** REAL GAP (latency). `_engine_gate_surface` (`agent_kernel.py:13664`) is
called on **every** reply (`:4290`) and invokes `eng.decide("presentation", …)`
(`:13698`) — a **blocking** call that acquires a lock with a **2s timeout**
(`decision_engine.py:108,476`), and `_load()` runs **inside** the lock (`:480`), so
the first reply after startup pays model-load while holding it. Because
`presentation` is **shadow by default** (`IRIS_DECISION_ENFORCE="tool_choice"`,
`decision_engine.py:91`), the result is **discarded** (`agent_kernel.py:13730-13731`)
— the cost is paid and the answer thrown away. Once REQ-2 makes `show` the sole
trigger, this gate also decides a surface that no longer exists.

**Owner decision (OQ-3, Option C):** do NOT delete the consumer — DEMOTE it.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL NOT run a blocking decision-engine call on the reply path.
- AC2: WHEN the `presentation` decision is taken THEN THE SYSTEM SHALL record it
  OFF the critical path (async or post-emit), so it never blocks the reply.
- AC3: THE SYSTEM SHALL move the LIVE render decision authority to the
  `tool_choice` consumer (aligned with REQ-14 AC2 and REQ-16).
- AC4: THE SYSTEM SHALL PRESERVE the `presentation` consumer as a calibration
  observer — its choices are recorded and comparable to the live `tool_choice`
  outcome, and it can be promoted to live later without a rebuild.
- AC5: THE SYSTEM SHALL keep `narration` as an engine consumer; the consumer set
  remains `{tool_choice, presentation (observer), narration}` (CT-10).
- AC6: WHEN the presentation consumer is demoted off-path THEN THE SYSTEM SHALL NOT
  regress the tool-decision-engine spec's contract (cross-spec ripple:
  `specs/tool-decision-engine` REQ-11).

**Edge Cases:**

- Engine unavailable → reply unaffected (already the case).
- Enforced `presentation` via env override → honor it as a live decision, but
  resolve it without blocking the reply where possible; log the override.
- Observer and live `tool_choice` disagree → record the disagreement as calibration
  signal (this is the tuning data that justifies promotion).
- Calibration data: demotion must be visible in counters so the engine's value is
  measurable (REQ-9).

### REQ-16: Render-as-tool (unify the render surface) — ADOPTED

**User Story:** As the owner I want rendering to be a first-class agent action so
that the deterministic engine can govern it and the surface is unified.

**Verified:** NEW (unverified — implementation pending). Today rendering is NOT a
tool: it is the model-authored `show` JSON field (`agent_kernel.py:2170-2179`),
parsed by `structured_response.py`, emitted as `DOCUMENT_RENDER` by the kernel. No
`render_document`/`create_document` tool exists (only read-side `get_rendered_documents`
and `combine_documents` in `tool_registry.py:940,976`). Native function-calling is
already the primary tool path (`tool_decision.py:985-1009`).

**Owner decision (OQ-2): ADOPT render-as-tool as a decision surface, keep the
`show` envelope as wire transport.**

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL expose a `render_document` action to the tool layer so the
  `tool_choice` consumer can select it.
- AC2: THE SYSTEM SHALL keep the `show` envelope as the WIRE TRANSPORT (CT-1
  unchanged) while presenting render as a tool DECISION — so no extra model
  round-trip is required.
- AC3: WHEN the decision engine selects render THEN THE SYSTEM SHALL stream the
  document args progressively (REQ-13 AC2), not block on a second turn.
- AC4: THE SYSTEM SHALL NOT increase the model's task complexity — the typed
  `show.format` contract already exists (Decision 6); the tool surface is a
  decision layer, not a new model obligation.
- AC5: IF the tool layer is unavailable THEN THE SYSTEM SHALL fall back to the
  `show` envelope as the sole card trigger (Decision 17; the structural signal is
  log-only, never a render fallback).

**Edge Cases:**

- Engine selects render but the model produces no content → empty artifact guard
  (existing `_is_empty_websearch_synthesis`, `:4129`).
- Two render intents in one turn → one card per turn rule holds (AC11.4, `:13682`).
- Tool-layer unavailable → fall back to the `show` envelope.

### REQ-17: Hydrated card body is fetchable (no blank card after reload)

**User Story:** As the owner I want a card that survives a page reload to still
show its full body when I expand it so that history is not a graveyard of empty
cards.

**Verified:** REAL GAP (cross-spec deadlock, session 347). `document_store.list_for_conversation(..., metadata_only=True)`
(`document_store.py:404-408`) deliberately returns **no** `content` column, so the
WS `get_documents` hydration payload is metadata-only. `lib/documentMerge.ts:36-52`
preserves a prior in-memory `content` on merge — but on a **fresh page load** there
is no prior entry, so the card hydrates blank. The merge's own comment asserts
"the full body is fetched on expand", yet **no such fetch exists**: no
`get_document_content` / `fetch_document_body` handler is registered in
`iris_gateway.py`, and `DocumentPanel` (`components/chat/DocumentPanel.tsx:32`)
renders whatever `content` prop it is handed (`chat-view.tsx` passes
`content={d.content}`). Net: reload → card present, body empty, expand shows
nothing. This spec's REQ-6 collapse and REQ-7 AC3 (id stability) both make the
blank-body failure more visible, so the contract must be closed here.

**Acceptance Criteria:**

- AC1: WHEN the frontend expands a rehydrated card whose body is not in memory THEN
  THE SYSTEM SHALL fetch the body by `document_id` from `DocumentDataStore`.
- AC2: THE SYSTEM SHALL expose a single-document body read (gateway message or
  route) that returns the stored `content`/`variants` for one `document_id`,
  scoped to the requesting conversation.
- AC3: WHEN the body fetch succeeds THEN THE SYSTEM SHALL render it in
  `DocumentPanel` without duplicating the card or re-emitting `DOCUMENT_RENDER`.
- AC4: THE SYSTEM SHALL keep the hydration payload metadata-only (CT-DOC-1) — the
  body is fetched lazily, never shipped wholesale with history.

**Edge Cases:**

- `document_id` no longer in store → panel shows an explicit "document
  unavailable" state, not a silent blank.
- Blob-backed card (image) → fetch resolves via `get_blob` (`document_store.py:232`).
- Offline / fetch failure → panel shows a retry affordance; the card header stays.
- Card already rendered live this session (body in memory) → no fetch is issued.

## Non-Requirements (Out of Scope)

- Changing the model prompt to require a richer typed object. The owner's
  constraint: "we don't want the model's job to be more complex." `show.format`
  already carries the type; this spec consumes it, it does not extend it.
- Rebuilding `CardChassis` or the prism visual design beyond the collapse
  affordance (REQ-6).
- TTS voice/engine changes; only lane separation is in scope.
- Crawler / capture-404 race work (tracked separately in `pin_3d97e8ff607a` §B).
- The `write_file` / personal-mode tool-menu thread (separate).
- Progressive/streamed reply over the REST path (`api/chat.py:185-201`, no
  `chunk_callback`). REQ-13 targets the WS path; REST clients continue to receive
  the final reply only.
- A streaming persistence model for `DocumentDataStore`. The card stream rides the
  `DOCUMENT_RENDER` event; the store keeps whole-document upserts (REQ-13 AC5).

## Open Questions

### Resolved (session 346 — captured in Decisions Locked 15–17)

- **OQ-1 RESOLVED → Decision 17 (REVISED session 346, owner follow-up):**
  **`show`-PRESENCE is the SOLE card trigger.** The owner confirmed the `show`-payload
  / artifact logic is KEPT as the only signal: a card renders IFF the agent emitted
  `show`. The structural signal (table/code/list) is retained **log-only** as a
  calibration detector — it is NEVER a render trigger. This supersedes the earlier
  session-346 wording ("structural rule is the safety net when the model omits
  `show`"), which contradicted REQ-4 AC2 and the 2026-08-17 owner pin
  (`agent_kernel.py:4416-4427`). The `[RESPONSE FORMAT]` prompt is strengthened so
  the model emits `show` reliably; a `show_omitted_on_artifact` log makes drift
  measurable. REQ-14 AC3 and T1 are aligned to this.
- **OQ-2 RESOLVED → Decision 16:** render-as-tool IS adopted as a decision surface,
  keeping the `show` envelope as wire transport (no extra round-trip).
- **OQ-3 RESOLVED → Decision 15 / REQ-15:** the blocking presentation gate is
  demoted to an async observer — the consumer is PRESERVED, the live render call
  moves to `tool_choice`. No use case lost.

### Non-blocking

- **OQ-4 (REQ-13): streaming granularity** — token-level vs paragraph-level card
  streaming; depends on provider capability.
- **OQ-5: degradation UX** — what the user sees when synthesis times out or returns
  empty (currently a deterministic fallback summary, `agent_kernel.py:13339,13378`).
- **OQ-6: superseded cards** — when a follow-up replaces a card, does the old card
  stay, archive, or get marked stale?
- **OQ-7: multi-card turns** — a websearch can yield a JSON card + a markdown card;
  which is primary, and where does the bubble attach? (Partially covered by T15.)
- **OQ-8: mobile + accessibility** — collapsed card + panel on a phone;
  screen-reader semantics for the chevron/Expand affordance.
- **OQ-9: history fidelity** — after an edit, does the reloaded card show the edited
  version? (REQ-7 AC3 implies yes; needs a behavioral test.)
- **OQ-10: card collapse default height** (REQ-6) reuses `COLLAPSED_MAX_HEIGHT = 460`;
  revisit only if the owner wants a shorter preview.
