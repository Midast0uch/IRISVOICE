# Tasks: ChatView Dev Cleanup (scroll + render structure)

> Each task links to a requirement. Group into waves for parallel execution.
> Verify-before-edit per task: read the cited lines, confirm the gap is still REAL.

## Wave 1 — Foundation (structure + instrumentation, parallel-safe)

- [x] T1 (REQ-1, REQ-8): Turn grouping in `renderTimeline` memo — ALREADY PRESENT
  when the spec was written (verified 2026-09-04): `:864-922` joins cards inline by
  `responseTurnId === message.id`, keeps `latestPerTurn` one-card-per-turn dedup, and
  falls back to chronological insertion for orphans. No grouping work remained; the
  checkbox was stale. Placement LOGGING remains as T2.
  `components/chat-view.tsx:858-916`, `:4054-4206`, `:4218-4247` —
  RIPPLE: task-card `latestPerTurn` dedup untouched; `useTaskProgress` NO CHANGE;
  CT-1/CT-2 lock event shapes this grouping relies on.
- [ ] T2 (REQ-8): `logStructured` placement events (inline join + orphan fallback +
  predicate outcome) — same file, precedent `:944-957` — RIPPLE: logger only, no
  render path change; keep off the hot path (batch per turn).
- [x] T3 (REQ-1 AC4, REQ-2): **DONE 2026-09-04 — deterministic 11:52 fixture.**
  Shared wire-shaped fixture at `__tests__/fixtures/chatviewTurn1152.ts` carries
  `document:render` (markdown body + stable document_id), same-turn `chat_message`,
  and matching TaskCard. Pure `buildChatTimeline` helper at
  `lib/chatview-turn-timeline.ts` makes the join deterministic without a DOM or
  backend. Shared by CT-1/CT-2/CT-3 now; BT-1 can consume the same fixture.
  No backend contract changed.

## Wave 2 — Scroll contract (depends on T1 for timeline behavior)

- [x] T4 (REQ-3): IMPLEMENTED 2026-09-04 live-verified — History panel resolvable cap (`vh`/measured px via
  `getOuterMaxHeight` pattern `:2831`) — `components/chat-view.tsx:3235-3249` —
  RIPPLE: framer `height:'auto'` animation must coexist with the cap (animate
  maxHeight, not height, or measure-then-set); `handleSelectConversation` untouched.
- [x] T5 (REQ-4): COMPLETE 2026-09-04. History list done earlier; remainder landed now:
  notifications panel cap `50%` -> `min(46vh, 520px)` (same indefinite-parent bug the
  history dropdown had) + inner list `maxHeight: inherit` + `overscroll-behavior: contain`;
  slash menu was `overflow-hidden` and therefore never a scroll container, so containment
  alone would have been inert — capped `min(30vh, 260px)` + `overflow-y: auto` +
  `contain`; document modal content `overscroll-behavior: contain`.
  RIPPLE: detached-window layout (`isDetached`) inherits all three (same components);
  no global-CSS conflict (inline styles only).
- [x] T6 (REQ-5): IMPLEMENTED 2026-09-04 (content-visibility + intrinsic size on rows) — mount-animation capping deferred (content-visibility covers the cost); revisit past ~5k measured jank
  thread rows; cap mount animations to first screen —
  `components/chat-view.tsx:3283-3294` — RIPPLE: active-row highlight + Pin/Delete
  keyboard reach preserved; reduced-motion path already gated.
- [x] T7 (REQ-6 AC3/AC4): IMPLEMENTED 2026-09-04, live verification pending (T10).
  Auto-scroll now gated on `pinnedToBottomRef` (48px threshold) written by the
  container's `onScroll` — a ref, not state, so the effect reads the PRE-insertion
  pinned state (appending content fires no scroll event). Re-pins on
  `activeConversationId` change. "Jump to latest" button (ChevronDown, reduced-motion
  aware, `data-testid="jump-to-latest"`) sits in the composer's `bottom-full` slot.
  `components/chat-view.tsx:1015-1022` — RIPPLE: streaming chunk path
  (`iris:chat_chunk` `:1207`) and REST path share the pinned check; `awaitingFirstBlock`
  glyph (`:4277`) unmount behavior unchanged.
- [x] T8 (REQ-7): **DONE 2026-09-04 — personal mode only.**
  Icon send control (`Send` from lucide, 32px circle matching the Web toggle)
  rendered after the textarea, gated on `!isDeveloper`, at `chat-view.tsx:5008+`.
  `onClick={handleSendMessage}` — AC3, no second send path. `disabled` on
  `!inputText.trim() || voiceState === 'listening'` — the send-path guards
  (`:1844`); `isChatTyping` deliberately excluded (messages queue).

  **Blocker resolved, not worked around.** The width budget was measured first
  (phase-5 OQ-1 asked for it): container `px-3`, row `gap-2` + `marginRight: 4px`,
  wings 360/510/680. Personal mode's textarea is `flex-1` with no min-width, so it
  absorbs the 40px — 292→252 / 442→402 / 612→572. Developer mode's REQ-2 toolbar
  is 454px against 486px usable at the balanced wing, so +44px overflows by 12px;
  it also reads as a CLI surface and stays without the control. Scope decision
  recorded in requirements.md REQ-7.

  **Test change is deliberate and signed off (user, 2026-09-04).**
  `__tests__/InputRow.test.tsx` AC1 rewritten from "absent" to "present", with the
  reasoning recorded inline in the test. Two REQ-7 describe blocks ADDED: AC2 guards
  (4 tests: empty, listening, enabled-with-text, isChatTyping-stays-enabled) and AC3
  single-path (2 tests: click sends+clears, disabled click cannot send).
  `InputRow.test.tsx`: **13 passed** (was 8 — five net NEW tests, zero assertions
  removed or relaxed).
  RIPPLE: Enter behavior unchanged; mic-`listening` disables both identically;
  developer mode row and REQ-2 toolbar byte-identical.

## Wave 3 — Verification (gates, all live on the running app)

- [ ] T9 (REQ-1, REQ-2): Contract suite green — CT-1/CT-2/CT-3 — RIPPLE: locks the
  two backend event shapes (CONTRACT LOCK, no backend code).
- [ ] T10 (REQ-1 AC4, REQ-3, REQ-6): Behavioral + live gates via DevTools
  (`app-testing` skill): BT-1 fixture replay inline + zero orphans; 778-row wheel
  test; scrolled-up hold + pinned follow; one tailored prompt turn renders
  bubble+table inline with TTS spoken — RIPPLE: backend + frontend must both be on
  current source (stale-bundle lesson 2026-09-04: verify BUILD freshness first).
- [ ] T11 (REQ-5): Perf gate — history open frames measured (target: no >100ms
  task on open; UNVERIFIED baseline — measure current 778-animation open first,
  then assert improvement, never an assumed number).

## Dependency / parallelization notes
- Wave 1 tasks are mutually parallel (different regions/fixtures); land T1 before
  Wave 2's T7 (both touch timeline render behavior).
- T4/T5/T6 are CSS/DOM-only and parallel with each other; T8 is composer-only and
  parallel with everything except T10's live pass.
- T3's fixture unblocks T9/T10 — write it first if sequencing tightly.
- NO-CHANGE areas needing only contract cover: `useTaskProgress` keys,
  `documentMerge`, socket conversation identity (all in Ripple-Effect Map).
- Refinements wave: if implementation beats this design (e.g. measured data favors
  virtualization past ~5k threads), add Wave 4 and update requirements/design —
  the spec stays as-built per the living-document rule.
