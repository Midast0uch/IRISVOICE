# Tasks: Task Card v2 — Liquid Ink + Blueprint Matrix

> Each task links to a requirement. Waves group work that can proceed in parallel.
> RIPPLE notes name what else the task touches or relies on.

## Wave 0 — Baseline characterization (BEFORE any Wave 1 edit)

> The unified-vision-routing build proved the cost of skipping this: six change sites
> had no test pinning current behavior, and a fully-built feature shipped unwired
> because nothing asserted it was reached. These tests assert what the code does TODAY.
> Each is expected to be edited exactly once, by the task that changes what it pins, and
> that edit must be called out in that task's report.

- [ ] **T0a (pins T5, T6)**: Characterize `useTaskProgress` as it is — a SINGLE card
  state, wiped on `iris:new_conversation` / `iris:conversation_switched`, merged by the
  `prev.turnId === d.task_id && prev.isWorking` heuristic
  — `__tests__/hooks/useTaskProgress.baseline.test.ts`
  BASELINE GAP: no test pins the single-card model or the reset-on-switch that makes
  cards vanish. Without it, the Map migration is unmeasurable.

- [ ] **T0b (pins T1)**: Characterize `_task_start_payload` — snapshot the exact key set
  it emits today, asserting `card_id` / `card_relation` / `conversation_id` are ABSENT
  — `backend/tests/unit/test_task_start_payload_baseline.py`
  BASELINE GAP: the payload is a contract shared by 6+ emit sites with no shape test.

- [ ] **T0c (pins T7, T8)**: Characterize the answer paths — voice reaches
  `resolve_answer`, the gateway's `question_response` calls `receive_answer` DIRECTLY
  (`iris_gateway.py:5399`), and a card click therefore does NOT resume a parked source
  — `backend/tests/contract/test_answer_funnel_baseline.py`
  BASELINE GAP: the asymmetry is the bug; pin it so the fix is provable.

- [ ] **T0d (pins T9)**: Characterize `QuestionCard` — single-question props render one
  question, and a second pending question is invisible
  — `__tests__/components/QuestionCard.baseline.test.tsx`
  BASELINE GAP: no test covers the card at all today.

- [ ] **T0e (pins T12)**: Characterize the CLI renderer — content lines open a left wall
  and do NOT close a right wall; assert the current ragged output verbatim
  — `__tests__/cli/CLITaskProgressRenderer.baseline.test.ts`
  BASELINE GAP: zero coverage; the leak is invisible to CI.

- [ ] **T0f (pins T4)**: Characterize conversation persistence — a stored message is
  `{role, content, turn_id}` only, and NO card state is persisted
  — `backend/tests/contract/test_conversation_card_persistence_baseline.py`
  BASELINE GAP: this absence is the root cause of vanishing cards; assert it explicitly.

### Already covered — do NOT re-derive
- Document rehydration: `__tests__/components/chat-view-rehydration.test.ts` — the
  no-blank / no-duplicate guard. EXTEND for cards (T11); do not replace.

## Wave 1 — Backend identity and contracts (parallel)

- [ ] **T1 (REQ-3)**: Add `card_id`, `card_relation`, `conversation_id` to
  `_task_start_payload` — `backend/agent/agent_kernel.py:7588`
  RIPPLE: ONE construction point, so all 6+ TASK_START emit sites inherit it. Must be
  ADDITIVE — CT-1. Inverts T0b.

- [ ] **T2 (REQ-3 AC5)**: Decide `new` vs `continues` from task identity on the backend
  — `backend/agent/agent_kernel.py`
  RIPPLE: the actual judgement, separate from T1's transport. A sub-loop split
  CONTINUES the parent card (REQ-3 edge case) — do not let it branch. Internal names
  (`sub_loop_split`, `is_subloop`) are unchanged; only the user-facing LABEL becomes
  "Detour" (Decision 13), emitted in `branchLabel`.

- [ ] **T2a (REQ-1 AC8)**: Emit "Detour" as the user-facing branch label — wherever
  `branchLabel` is populated — `backend/agent/agent_kernel.py`
  RIPPLE: content change only; the purple/magenta rendering is untouched. Locked by
  CT-9, which asserts "Sub-Loop" reaches no user-facing surface.

- [ ] **T3 (REQ-5, REQ-6)**: Question sets + enforce the single funnel —
  `backend/agent/tools/ask_user_tool.py`, `backend/iris_gateway.py:5399`
  RIPPLE: gateway must call `resolve_answer`, not `receive_answer`, so a card click
  resumes a parked source like voice does. Single-question payloads must still work —
  CT-2. Inverts T0c.

- [ ] **T4 (REQ-4 AC1)**: Persist card state against its conversation —
  `backend/agent/conversation_context_store.py`
  RIPPLE: `ConversationMessage` is `{role, content, turn_id}`; follow the document
  persistence shape rather than inventing a second one. Inverts T0f.

- [ ] **T5 (REQ-11)**: Card footprints keyed by `card_id` — `backend/memory/`
  RIPPLE: writes through the existing store interface (NO CHANGE verified). Foundation
  only — no `@card:` addressing (Decisions Locked 6). A failed write must never block
  execution.

## Wave 2 — Frontend state model (T6 depends on T1)

- [ ] **T6 (REQ-3, REQ-4)**: `useTaskProgress` single card -> `Map<card_id, Card>` scoped
  to a conversation; reset-on-switch becomes restore-on-switch
  — `hooks/useTaskProgress.ts`
  RIPPLE: the highest-risk task in the spec. `:224-229` wipe and the `:255` merge
  heuristic both change. Legacy payloads without `card_id` must fall back to today's
  merge, not drop the card. Inverts T0a.

- [ ] **T7 (REQ-4 AC2/AC4)**: Render the keyed collection and rehydrate on conversation
  open/switch — `components/chat-view.tsx`
  RIPPLE: `:3445-3459` renders one card today. Must not duplicate an already-rendered
  card — CT-4. Depends on T6.

## Wave 3 — Chassis (T8 gates T9–T11)

- [ ] **T8 (REQ-1, REQ-2 AC3)**: Promote `VariantLiquidInk` out of `temp/` into a shared
  `CardChassis` — `components/chat/CardChassis.tsx`
  RIPPLE: ONE implementation for all four card types (REQ-2 AC3). Must expose the accent
  vein, header slot, counter and collapse affordance as chassis-level concerns. REQ-1
  AC5 padding lives here so every card inherits it.
  FIDELITY: reproduce the tokens in design.md "Liquid Ink tokens as built" — this is the
  variant the user chose, not a starting point. Two deliberate departures, both required:
  apply the 9px/10px type floor (Decision 14, three 8px elements move up), and label the
  branch row "Detour" not "Sub-Loop" (Decision 13). Locked by CT-8.

- [ ] **T9 (REQ-1, REQ-10)**: Task card on the chassis + memory activity in the header
  — `components/chat/TaskListCard.tsx`
  RIPPLE: 434 lines today. Memory slot renders only from real events (REQ-10 AC4) —
  never fabricated. Depends on T8.

- [ ] **T10 (REQ-2, REQ-5)**: Question card on the chassis + multi-question rendering
  — `components/chat/QuestionCard.tsx`
  RIPPLE: consumes T3's question set. Per-question `multiSelect`, header, and unanswered
  state (REQ-5 AC3/AC4/AC5). Inverts T0d. Depends on T8 + T3.

- [ ] **T11 (REQ-2)**: Permission and rich-document cards on the chassis
  — `components/chat/PermissionCard.tsx`, `components/chat/RichDocument.tsx`
  RIPPLE: RichDocument is 889 lines and the highest regression risk in the spec — swap
  the chassis ONLY, do not touch its content logic. REQ-2 AC4 forbids any capability
  change. Depends on T8.

- [ ] **T11a (REQ-2 AC6) — FOUND IN FINAL AUDIT**: Expanded document panel on the chassis
  — `components/chat/DocumentPanel.tsx`
  RIPPLE: it is the EXPANDED form of RichDocument (`chat-view.tsx:3606`) with its own
  gradient. Restyle T11's card without this and expanding a document jumps style
  mid-interaction. Depends on T8 + T11.


## Wave 3b — Registries (gates the card and CLI rendering)

- [ ] **T8a (REQ-14)**: Action verb registry — `lib/cards/verbRegistry.ts`
  RIPPLE: consumed by BOTH the GUI card (T9) and the CLI renderer (T12) — build it before
  either renders a verb, or the mapping forks. Must cover all 51 registered tools across
  10 families; longest verb is 6 chars so the column is fixed at 6 with no truncation.
  Locked by CT-6.

- [ ] **T8b (REQ-15)**: Memory event registry — `lib/cards/memoryRegistry.ts`
  RIPPLE: fixed fields in fixed order per Wormhole doc Section 9. Register `learning`
  (already emitting), plus `recall` / `compress` / `episodic` (emits added in T8c), and
  RESERVE the Wormhole vocabulary (tier, posterior, hex_bin_id, resonance, elevation)
  without implementing it. Locked by CT-7.

- [ ] **T8c (REQ-10 AC5)**: Emit the memory events the card renders —
  `backend/agent/mcm.py`, `backend/agent/agent_kernel.py`
  RIPPLE: `mcm.py` has ZERO `emit`/`event_bus` references today, so `recall()` (`:161`)
  and `compress()` (`:86`) are silent, as is episodic `get_task_context`
  (`agent_kernel.py:752`). Without this the footer is honest and permanently empty.
  Emits must stay OFF the recall hot path — the Wormhole doc flags mid-stream recall
  latency as an unresolved blocking concern; do not add synchronous work there.

## Wave 4 — CLI (parallel with Wave 3)

- [ ] **T12 (REQ-8, REQ-9)**: Promote `CLITaskProgressRenderer` out of `temp/`; close
  every right wall using VISIBLE width (ANSI-stripped, display-width aware); add the
  header icon — `lib/cli/CLITaskProgressRenderer.ts`
  RIPPLE: naive `padEnd` misaligns every coloured line — measure visible width, not
  `String.length`. Alignment must be identical with colour on and off — CT-5. Inverts
  T0e.
  FIDELITY: reproduce the tokens in design.md "Blueprint Matrix tokens as built". Frame
  inner width is 66. The verb is ALREADY `padEnd(6)` (`:311`) — Decision 12 follows the
  variant here, it does not override it. Branch chamber label becomes "Detour"
  (Decision 13); the brightMagenta treatment is unchanged.
  ALSO FIX: `CLITaskProgressRenderer.render()` (`:348-350`) currently delegates to
  `renderCyberDoubleRailCLI` — the Flow Pipeline variant, NOT the selected Blueprint
  Matrix. Repoint it, and drop the unselected variants when promoting out of `temp/`.

- [ ] **T13 (REQ-7)**: Render task blocks and question sets in the terminal; route CLI
  answers through the REQ-6 funnel — `components/terminal/TerminalPanel.tsx`
  RIPPLE: input handling at `:113-140` is otherwise untouched (Decisions Locked 5). A
  question arriving mid-command must preserve the input buffer. Depends on T12 + T3.

- [ ] **T13a (REQ-13)**: Terminal becomes an on-demand slide-over — remove the resident
  panel, keep the icon, position so it never occludes the composer or the active card;
  preserve scrollback across open/close
  — `components/workspace/DeveloperWorkspace.tsx`, `components/chat-view.tsx`
  RIPPLE: `FloatingPanel` (`DeveloperWorkspace.tsx:13`) already exists as the positioning
  primitive — reuse it rather than adding a second overlay system.

- [ ] **T13b (REQ-13 AC5/AC6)**: Converge the two command channels and render `>cmd` /
  `/run` output as a Blueprint Matrix block in the chat stream
  — `components/chat-view.tsx:1379-1387`, `backend/iris_gateway.py`
  RIPPLE: chat input sends `terminal_input`, the panel sent `dev_cli` — two channels for
  one job. Converge to one, then wrap output in the T12 block renderer. Raw pty output
  that is not task-shaped must still render verbatim INSIDE the walls.

## Wave 4b — Permissions (independent of the visual work)

- [ ] **T0g (pins T20) — BASELINE**: Characterize the permission gate as it is — with no
  `mode` in config, `get_mode()` returns `"personal"` and a `SIDE_EFFECT` tool like
  `write_file` AUTO-APPROVES with no `PERMISSION_REQUEST` emitted
  — `backend/tests/contract/test_permission_gate_baseline.py`
  BASELINE GAP: nothing asserts the gate is ever reached. This pins the user-reported
  symptom — "it has never once asked me" — as a test.

- [ ] **T20 (REQ-16)**: Make the effective permission mode truthful — the launcher's
  selection must reach `cfg["mode"]`, and an ABSENT mode must not resolve to the most
  permissive policy — `backend/capabilities.py:66-73`, `backend/main.py:1070-1083`
  RIPPLE: `get_mode()` is also used by `is_tool_allowed` / `allowed_tools`
  (`tool_bridge.py:476`, `:1108`), so changing the fallback changes TOOL AVAILABILITY as
  well as permissions. Verify both. Do NOT touch the tier matrix — it is correct.
  Inverts T0g.

- [ ] **T21 (REQ-16 AC2/AC5)**: Surface the effective mode in the UI and log the resolved
  action per gated call — `components/chat-view.tsx`, `backend/agent/tool_bridge.py`
  RIPPLE: answers "why was I not asked" without reading a config file. Logging stays off
  the execution hot path.

- [ ] **T22 (REQ-17)**: Prove enforcement — CT-11/CT-12/CT-13 plus behavioral drives
  — `backend/tests/contract/`, `backend/tests/behavioral/`
  RIPPLE: CT-11 is the "reached from a real path" test whose absence let the vision
  hierarchy ship fully built and unreachable. CT-12 pins that `_DESTRUCTIVE_TOOLS` names
  8 tools of which only `delete_file` exists in the runtime registry — decide whether to
  prune the list or widen the registry, but do not leave them silently divergent.

## Wave 5 — Verification

- [ ] **T14 (REQ-1..15)**: Contract tests CT-1..CT-10 — `backend/tests/contract/`,
  `__tests__/`
  RIPPLE: CT-3 and CT-4 encode bugs observed live (dropped click answer, vanishing
  card). CT-10 encodes a spec bug — the two surfaces this document missed on its first
  pass — and is the guard against the same omission when a card type is added later.
  Write CT-10 EARLY, not last: it is the one test that fails loudly if the stream is
  only partly restyled.

- [ ] **T15 (REQ-3, REQ-4, REQ-5, REQ-6)**: Behavioral tests — continue vs branch,
  rehydration across a switch, multi-question independence, click-equals-voice
  — `backend/tests/behavioral/`, `__tests__/`
  RIPPLE: the continue-vs-branch test must assert the SECOND card does not appear on a
  follow-up — the whole point of REQ-3.

- [ ] **T16 (REQ-12)**: Card lifecycle observability — `backend/agent/agent_kernel.py`,
  `hooks/useTaskProgress.ts`
  RIPPLE: log relation decisions, rehydration counts, and answer resolutions with their
  input path. Off the render and inference hot paths (REQ-12 AC4).

- [ ] **T17 (REQ-3, REQ-4)**: Extend the standing CDD harness with a card lifecycle
  replay — `scripts/validate_der_card_lifecycle.py`
  RIPPLE: drives start -> continue -> branch -> switch -> rehydrate every run. Must be
  observed going RED before being trusted — a harness never seen to fail proves nothing.

## Wave 6 — Cleanup

- [ ] **T18**: Delete `backend/agent/ask_user_tool.py` (192 lines, dead)
  RIPPLE: verified dead — every caller imports `backend.agent.tools.ask_user_tool`
  (agent_kernel `:4317`, tool_bridge `:1001`, iris_gateway `:2840`/`:5394`, crawler
  `:1016`). Do this LAST, after T3 has settled, so the diff is unambiguous.

- [ ] **T19**: Remove `temp/task-card-redesign/` once T8 and T12 have promoted what they
  need — RIPPLE: confirm no import still points into `temp/` before deleting.

## Dependency / parallelization notes
- **Wave 0 gates Wave 1.** Six of the seven change sites have no coverage; without the
  baselines the first four tasks change behavior nothing measures.
- **T1 and T2 are separate on purpose** — T1 is transport (mechanical), T2 is the
  identity judgement (the part that can be wrong). Landing T1 alone is safe and additive.
- **T6 is the riskiest task.** Everything visual depends on it, and it rewrites a state
  machine that currently works for the single-card case. Land it with T0a green.
- **T8 gates T9, T10, T11** — all three consume the shared chassis.
- **T8a gates T9 and T12** — the verb registry is shared by the GUI card and the CLI
  renderer; building either renderer first forks the mapping.
- **T8b gates T9's memory slot; T8c gates whether that slot has anything to show.** T8b
  can land first and render only `learning` until T8c adds the rest.
- **The registries (T8a/T8b) are the forward-compatibility seam** for the Wormhole
  recall upgrade. If they slip, that work becomes a card rewrite instead of a data edit.
- **CT-10 is the anti-drift guard for the whole visual half.** The first draft of this
  spec restyled four cards and missed two more surfaces. Land CT-10 with T8 so any card
  left behind fails immediately rather than at review.
- **Wave 4b (permissions) is fully independent of the visual work** and can run in
  parallel with any other wave. It shares only `PermissionCard`, which T11 re-chassis and
  T20-T22 make actually appear.
- **T20 changes tool AVAILABILITY as well as permissions** — `get_mode()` feeds
  `is_tool_allowed` / `allowed_tools` too. A stricter fallback could block tools that
  currently run. Verify both surfaces before landing.
- **Plan-event / system / error messages are OUT OF SCOPE and must stay plain text.**
  They are the MESSAGE path, not the card path (`Message.sender` union,
  `chat-view.tsx:112`). CT-10's allowlist is what enforces that separation — the test
  must fail if a future change cards them.
- **Wave 4 is backend-independent except T13's dependency on T3's question set**, so T12
  can start immediately.
- **T11 is the highest regression risk** (889-line RichDocument) — chassis swap only.
- **NO-CHANGE-verified areas needing only contract tests:** `event_bus.py` (events
  already exist), both `useIRISWebSocket` forwarding cases (payloads pass through
  untouched), `backend/memory/` stores. Evidence in design.md's Ripple-Effect Map.
- **OPEN, not scheduled:** the developer terminal renders typed input invisibly
  (likely `allowTransparency` compositing, `TerminalPanel.tsx:70-92`). A real defect but
  a different one — it needs live diagnosis before it can be specced. See
  requirements.md Open Questions.
