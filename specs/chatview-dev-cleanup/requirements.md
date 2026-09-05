# Requirements: ChatView Dev Cleanup (scroll + render structure)

## Decisions Locked
- `:3000` rebuild approved and done — dev server (`next dev`, Turbopack) serves current source; stale 8/31 bundle retired (PID 17164 terminated).
- No websearch needed to prove prism rendering; tailored prompts are the instrument.
- Prism-anchor fix is LANDED and not re-litigated: exact-equality duplicate predicate +
  anchor message always created on WS and REST paths (`components/chat-view.tsx:481-488`,
  `:1059-1073`, `:2097-2115`).
- Orphan fallback: KEEP the bottom pile for true hydration misses (user decision, session 291).
- History list: constrained scroll IMPLEMENTED 2026-09-04 (user confirmed by asking
  for the fix): panel cap `min(46vh, 520px)`, inner list `maxHeight: inherit` +
  `overscroll-behavior: contain`, rows `content-visibility: auto`. Live-verified on
  779 threads (430px box, 76725px content, wheel-contained, last row reachable).
- Audio pipeline (Parakeet warm-on-first-wake + 25s bounded wait, TTS late-ready
  recovery) is verified live and OUT of scope.
- Personal and developer modes keep distinct renderers (Blueprint Matrix CLI vs
  TaskListCard; mono `MarkdownMessage` vs rich): the spec unifies the TURN STRUCTURE,
  never the visual language.

## Introduction
ChatView renders three timelines in one scroll (assistant messages, prism
`RichDocument` cards, agent `TaskListCard`s) plus a 778-thread history dropdown, in two
visual modes. Cards pile at the scroll bottom instead of their turn, the history
dropdown cannot be scrolled at all, and dev-mode scroll behavior (matrix + terminal +
auto-scroll) was never pinned. This spec fixes placement, scrolling, and structure
with live-verified acceptance on the running app.

### Success criteria
- A prism card whose `turnId` matches a message renders inline under that message on
  first paint; the orphan block holds zero entries whenever every parent exists
  (baseline today: 0 orphans across 4 UI turns because the model emitted no cards —
  acceptance uses fixture replay, REQ-1 AC4).
- The history dropdown scrolls all 778 threads with the wheel without moving the main
  timeline (baseline today: wheel does nothing / chains to the thread).
- Auto-scroll never yanks a user who scrolled up to read history (baseline today:
  unconditional `scrollTop = scrollHeight` on every timeline change).
- History panel opens without 778 simultaneous mount animations (baseline today: one
  `motion.div` animation per row).

## Requirements

### REQ-1: Turn-anchored prism placement
**User Story:** As a chatter I want a rendered card to sit with the answer it belongs
to so that I read text and artifact as one turn.

**Verified:** `components/chat-view.tsx:4054-4206` (inline join
`doc.turnId === message.id`), `:481-488` (exact-equality predicate),
`:1059-1073` (WS anchor always created), `:2097-2115` (REST forwards through the
same path).

**Acceptance Criteria:**
- AC1: WHEN a `document:render` arrives with a `turn_id` THEN THE SYSTEM SHALL render
  its card inline under the message whose `id === turn_id`.
- AC2: WHEN the turn's plain text differs from every rendered card body THEN THE
  SYSTEM SHALL show both the text bubble and the card (coexist rule).
- AC3: WHEN the turn's plain text exactly equals a card body (normalized) THEN THE
  SYSTEM SHALL still create the anchor message and MAY hide the duplicate bubble.
- AC4: WHEN the 11:52 fixture payload (`document:render` markdown 680ch turn
  `b1e1c0e6-4dd` + `chat_message` same turn) is replayed THEN THE SYSTEM SHALL show
  one inline card and zero orphan entries.

**Edge Cases:**
- Card arrives before its message (transient orphan until the message lands).
- Several documents share one turn (websearch): each keeps its own `document_id`
  (`chat-view.tsx:1273`), never collapsed.
- Empty-body documents render nothing, never an empty glass rectangle (`:4070`).

### REQ-2: Orphan fallback kept for true misses only
**User Story:** As a returner I want a reload to never lose a card so that
rehydrated research survives.

**Verified:** `components/chat-view.tsx:4218-4247` (orphan filter
`d.turnId && !_msgIds.has(d.turnId)`).

**Acceptance Criteria:**
- AC1: WHILE a document's `turnId` matches no loaded message THEN THE SYSTEM SHALL
  render it in the bottom fallback block (Decision Locked: pile kept).
- AC2: WHEN the parent message loads later THEN THE SYSTEM SHALL move the card
  inline and remove it from the fallback.
- AC3: THE SYSTEM SHALL log each fallback placement with `turn_id` and
  conversation id (observability for REQ-8).

**Edge Cases:**
- Store miss after conversation delete: card stays in fallback, never crashes scroll.
- Same card rehydrated twice: idempotent merge, no duplicates
  (`mergeRenderedDocuments`, `:1367`).

### REQ-3: History dropdown scrolls
**User Story:** As a power user with 778 threads I want to wheel-scroll the thread
list so that I can reach old conversations.

**Verified (REAL GAP):** `components/chat-view.tsx:3235-3249` — outer `motion.div`
animates `height: 'auto'` with `maxHeight: '50%'`; the inner `overflow-y-auto` div
has no constraint of its own. A percentage max-height against an indefinite flex
parent never constrains, so 778 rows grow past the panel, clip under
`overflow-hidden` ancestors (`:2843`), and the wheel chains to the main timeline.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL cap the dropdown panel with a resolvable height
  (viewport-relative unit or measured px, never `%`-of-auto).
- AC2: WHEN the wheel moves over the thread list THEN THE SYSTEM SHALL scroll the
  list and not the main timeline.
- AC3: WHEN the panel opens with 778 threads THEN THE SYSTEM SHALL present a
  scrollbar and reach the last row by wheel alone.

**Edge Cases:**
- Zero conversations: "No conversations yet" state unchanged (`:3278`).
- Reduced motion: container animation already gated (`prefersReducedMotion`, `:3240`).
- Small viewport (remote/phone): cap degrades to a smaller vh value, list stays usable.

### REQ-4: No scroll chaining from nested panels
**User Story:** As a reader I want nested scrollers to trap the wheel so that
scrolling a list never yanks the conversation behind it.

**Verified:** NEW (unverified — implementation pending). No `overscroll-behavior`
anywhere in `chat-view.tsx` (grep 2026-09-04).

**Acceptance Criteria:**
- AC1: WHILE the pointer is over the history list, the slash menu (`:4684`), or the
  document modal THEN THE SYSTEM SHALL NOT scroll the main timeline
  (`overscroll-behavior: contain` or equivalent).
- AC2: WHEN a nested list hits its top/bottom edge THEN THE SYSTEM SHALL stop
  (no chain) rather than pass the gesture up.

**Edge Cases:**
- Touch/trackpad momentum scrolling chains the same way — contain applies to all
  wheel/touch sources.
- Detached chat window (`isDetached`): same containment, flat layout.

### REQ-5: Thread-row render budget
**User Story:** As a user opening history I want the panel instantly so that 778
threads don't freeze the frame.

**Verified (REAL GAP):** `components/chat-view.tsx:3283-3294` — every row is a
`motion.div` with `initial={{opacity: 0, x: -10}} animate=...`: 778 mount
animations per open (observed: 1300+ a11y nodes dumped on open).

**Acceptance Criteria:**
- AC1: WHEN the panel opens THEN THE SYSTEM SHALL NOT animate more than the first
  screen of rows (cap or `content-visibility: auto` for the rest).
- AC2: WHILE rows are off-screen THEN THE SYSTEM SHALL skip their rendering work
  (`content-visibility: auto` with `contain-intrinsic-size`).
- AC3: THE SYSTEM SHALL keep per-row Pin/Delete buttons reachable by keyboard.

**Edge Cases:**
- Active conversation row stays highlighted after virtualization-style skipping.
- Filter/search text (if added later) still matches unrendered rows — out of scope,
  noted only.

### REQ-6: Dev-mode timeline coherence
**User Story:** As a developer I want matrix, mono message, terminal scrollback, and
slash menu to share one coherent scroll so that live progress reads top-to-bottom.

**Verified:** `components/chat-view.tsx:3404-3464` (card branch: matrix vs
`TaskListCard` by `isDeveloper`), `:3507-3511` (document = stored `show` only),
`:920-929` (matrix elapsed timer bounded to working cards),
`:1015-1022` (auto-scroll effect — UNCONDITIONAL, the yank to fix).

**Acceptance Criteria:**
- AC1: WHERE developer mode is on THEN THE SYSTEM SHALL render the Blueprint Matrix
  CLI block inline at the card's timeline position (never bottom-stacked), with the
  elapsed timer only while working.
- AC2: WHERE developer mode is on THEN THE SYSTEM SHALL render assistant text as
  mono `MarkdownMessage` with truncate/expand, never as a fake length-based document
  (regression guard for the removed `isAssistantMarkdown` rule).
- AC3: WHEN new timeline entries arrive WHILE the user has scrolled up THEN THE
  SYSTEM SHALL NOT move the scroll (pinned-to-bottom auto-scroll only).
- AC4: WHEN the user is pinned to the bottom THEN THE SYSTEM SHALL keep them pinned
  as entries stream (no drift).

**Edge Cases:**
- `awaitingFirstBlock` glyph mounts at most once and unmounts on first content
  (`:4277-4288`).
- Terminal `>`, `/run`, `@taskcard` dispatches keep working while scrolled up.
- Settled conversation-reply cards stay suppressed (`isConversationReplyCard`).

### REQ-7: Explicit send affordance
**User Story:** As a chatter I want a visible way to send so that I never wonder
whether Enter is the only path.

**Verified:** `components/chat-view.tsx:4812-4817` (Enter-only send),
`:4921` (send pill removed, "Enter already sends"), `:1789-1798` (empty-input and
mic-listening guards). Live finding: programmatic fill + Enter never reaches
`inputText` state — only real keystrokes send.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL present an explicit send control next to the composer in
  both modes.
- AC2: WHEN input is empty or the mic is listening THEN THE SYSTEM SHALL disable
  the control (same guards as Enter).
- AC3: WHEN the control activates THEN THE SYSTEM SHALL run exactly
  `handleSendMessage` (no second send path).

**Edge Cases:**
- Multiline drafts (Shift+Enter) never send.
- Voice `listening` state disables both Enter and the control identically.

### REQ-8: Placement observability
**User Story:** As the tuner I want timestamped placement signals so that the next
iteration can measure inline-vs-orphan rates.

**Verified:** NEW. Precedent: `matrix_transition` structured logging
(`components/chat-view.tsx:944-957`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL emit a structured event for every inline card join and
  every orphan-fallback placement, scoped by conversation and `turn_id`.
- AC2: THE SYSTEM SHALL include the duplicate-predicate outcome
  (exact-match true/false) on suppressed-bubble turns.

**Edge Cases:**
- High-volume turns (multi-doc websearch): one event per card, off the render hot
  path.
- Missing `turn_id`: event carries `turn_id: null`, never throws.

## Non-Requirements (Out of Scope)
- Audio pipeline (STT warm-up, TTS recovery, wake cooldowns) — verified live, untouched.
- Forcing the model to emit `show` — emission is model-nondeterministic per turn
  (1 of 5 live turns); the UI must handle both shapes, never coerce the backend.
- New virtualization dependencies for the history list (REQ-3/5 are CSS-only).
- Backend API changes — `GET DOCS`/`GET CARDS` shapes already satisfy the joins.
- Websearch/crawl behavior, memory distillation, self-tuning loops.

## Open Questions
- Send-control visual treatment (icon button vs pill) — developer taste call, resolve
  with user before Wave 2.
- Slash menu + document modal containment (REQ-4 remainder): same one-line pattern
  as history, left untouched per scope discipline — fold into Wave 2 or leave.
