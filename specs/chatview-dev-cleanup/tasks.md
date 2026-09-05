# Tasks: ChatView Dev Cleanup (scroll + render structure)

> Each task links to a requirement. Group into waves for parallel execution.
> Verify-before-edit per task: read the cited lines, confirm the gap is still REAL.

## Wave 1 — Foundation (structure + instrumentation, parallel-safe)

- [ ] T1 (REQ-1, REQ-8): Turn grouping in `renderTimeline` memo + placement logging —
  `components/chat-view.tsx:858-916`, `:4054-4206`, `:4218-4247` —
  RIPPLE: task-card `latestPerTurn` dedup untouched; `useTaskProgress` NO CHANGE;
  CT-1/CT-2 lock event shapes this grouping relies on.
- [ ] T2 (REQ-8): `logStructured` placement events (inline join + orphan fallback +
  predicate outcome) — same file, precedent `:944-957` — RIPPLE: logger only, no
  render path change; keep off the hot path (batch per turn).
- [ ] T3 (REQ-1 AC4, REQ-2): 11:52 fixture (wire shapes: markdown 680ch render +
  same-turn chat text) under `tests/contract/` + `tests/behavioral/` —
  RIPPLE: shares fixture across CT-3/BT-1 (intertwined); no backend needed.

## Wave 2 — Scroll contract (depends on T1 for timeline behavior)

- [x] T4 (REQ-3): IMPLEMENTED 2026-09-04 live-verified — History panel resolvable cap (`vh`/measured px via
  `getOuterMaxHeight` pattern `:2831`) — `components/chat-view.tsx:3235-3249` —
  RIPPLE: framer `height:'auto'` animation must coexist with the cap (animate
  maxHeight, not height, or measure-then-set); `handleSelectConversation` untouched.
- [ ] T5 (REQ-4): `overscroll-behavior: contain` on history list DONE 2026-09-04; REMAINDER: slash menu
  (`:4684`), document modal — RIPPLE: detached-window layout (`isDetached`) gets
  the same containment when done; no global-CSS conflict (inline styles only).
- [x] T6 (REQ-5): IMPLEMENTED 2026-09-04 (content-visibility + intrinsic size on rows) — mount-animation capping deferred (content-visibility covers the cost); revisit past ~5k measured jank
  thread rows; cap mount animations to first screen —
  `components/chat-view.tsx:3283-3294` — RIPPLE: active-row highlight + Pin/Delete
  keyboard reach preserved; reduced-motion path already gated.
- [ ] T7 (REQ-6 AC3/AC4): Pinned-to-bottom auto-scroll + jump-to-latest affordance —
  `components/chat-view.tsx:1015-1022` — RIPPLE: streaming chunk path
  (`iris:chat_chunk` `:1207`) and REST path share the pinned check; `awaitingFirstBlock`
  glyph (`:4277`) unmount behavior unchanged.
- [ ] T8 (REQ-7): Explicit send control reusing `handleSendMessage` with existing
  guards (`:1789-1798`) — composer `:4760-4835` — RIPPLE: Enter behavior unchanged;
  mic-`listening` disables both identically; no second send path.

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
