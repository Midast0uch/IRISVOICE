# Tasks: Task Card v2 — Liquid Ink + Blueprint Matrix

> Each task links to a requirement. Waves group work that can proceed in parallel.
> RIPPLE notes name what else the task touches or relies on.

## Wave 0 — Baseline characterization (BEFORE any Wave 1 edit)

> The unified-vision-routing build proved the cost of skipping this: six change sites
> had no test pinning current behavior, and a fully-built feature shipped unwired
> because nothing asserted it was reached. These tests assert what the code does TODAY.
> Each is expected to be edited exactly once, by the task that changes what it pins, and
> that edit must be called out in that task's report.

- [x] **T0a (pins T5, T6)**: Characterize `useTaskProgress` as it is — a SINGLE card
  state, wiped on `iris:new_conversation` / `iris:conversation_switched`, merged by the
  `prev.turnId === d.task_id && prev.isWorking` heuristic
  — `__tests__/hooks/useTaskProgress.baseline.test.ts`
  BASELINE GAP: no test pins the single-card model or the reset-on-switch that makes
  cards vanish. Without it, the Map migration is unmeasurable.

- [x] **T0b (pins T1)**: Characterize `_task_start_payload` — snapshot the exact key set
  it emits today, asserting `card_id` / `card_relation` / `conversation_id` are ABSENT
  — `backend/tests/unit/test_task_start_payload_baseline.py`
  BASELINE GAP: the payload is a contract shared by 6+ emit sites with no shape test.

- [x] **T0c (pins T7, T8)**: Characterize the answer paths — voice reaches
  `resolve_answer`, the gateway's `question_response` calls `receive_answer` DIRECTLY
  (`iris_gateway.py:5399`), and a card click therefore does NOT resume a parked source
  — `backend/tests/contract/test_answer_funnel_baseline.py`
  BASELINE GAP: the asymmetry is the bug; pin it so the fix is provable.

- [x] **T0d (pins T9)**: Characterize `QuestionCard` — single-question props render one
  question, and a second pending question is invisible
  — `__tests__/components/QuestionCard.baseline.test.tsx`
  BASELINE GAP: no test covers the card at all today.

- [x] **T0e (pins T12)**: Characterize the CLI renderer — content lines open a left wall
  and do NOT close a right wall; assert the current ragged output verbatim
  — `__tests__/cli/CLITaskProgressRenderer.baseline.test.ts`
  BASELINE GAP: zero coverage; the leak is invisible to CI.

- [x] **T0f (pins T4)**: Characterize conversation persistence — a stored message is
  `{role, content, turn_id}` only, and NO card state is persisted
  — `backend/tests/contract/test_conversation_card_persistence_baseline.py`
  BASELINE GAP: this absence is the root cause of vanishing cards; assert it explicitly.

### Already covered — do NOT re-derive
- Document rehydration: `__tests__/components/chat-view-rehydration.test.ts` — the
  no-blank / no-duplicate guard. EXTEND for cards (T11); do not replace.

## Wave 1 — Backend identity and contracts (parallel)

- [x] **T1 (REQ-3)**: Add `card_id`, `card_relation`, `conversation_id` to
  `_task_start_payload` — `backend/agent/agent_kernel.py:7588`
  RIPPLE: ONE construction point, so all 6+ TASK_START emit sites inherit it. Must be
  ADDITIVE — CT-1. Inverts T0b.

- [x] **T2 (REQ-3 AC5)**: Decide `new` vs `continues` from task identity on the backend
  — `backend/agent/agent_kernel.py`
  RIPPLE: the actual judgement, separate from T1's transport. A sub-loop split
  CONTINUES the parent card (REQ-3 edge case) — do not let it branch. Internal names
  (`sub_loop_split`, `is_subloop`) are unchanged; only the user-facing LABEL becomes
  "Diving Deeper" (Decision 13), emitted in `branchLabel`.

- [x] **T2a (REQ-1 AC8) — CLOSED 2026-08-19, NO CHANGE NEEDED. See T2b.**
  Original intent: emit the user-facing branch label wherever `branchLabel` is
  populated — `backend/agent/agent_kernel.py`.
  OUTCOME: `branchLabel` is populated NOWHERE in production code. It exists only in
  `temp/task-card-redesign/` demo scaffolding, which is out of scope. There was
  therefore no user-facing string to rename, and this task closed with no edit. The
  real work is EMITTING the label in the first place — that is T2b, added below.
  Locked by CT-9, which asserts "Sub-Loop" reaches no user-facing surface.

- [x] **T2b (REQ-1 AC8) — ADDED 2026-08-19, THE TASK T2a TURNED OUT TO BE**: EMIT
  `branchLabel` on steps created by a sub-loop split — `backend/agent/agent_kernel.py`
  (~:11570-11612, where `_children` are routed and `origin="sub_loop_split"` is emitted)
  WHY THIS EXISTS: T2a was written as "emit 'Detour' wherever `branchLabel` is populated".
  Investigation found `branchLabel` is populated NOWHERE in production code — it exists
  only in `temp/task-card-redesign/` demo scaffolding. So there was nothing to rename, and
  T2a closed with no change. Meanwhile T8's `CardChassis` now renders
  `ChassisBranchBadge` as `↳ {branchLabel}`. Without this task the badge is a renderer
  with no data source — the fifth built-but-never-reached in this codebase, and this time
  we can see it coming.
  RIPPLE: the label is FREE TEXT supplied by the backend; the chassis hardcodes no copy, so
  the wording lives here. Decision 13: the words are "Diving Deeper" — never "Sub-Loop",
  never "Detour". Set it on the CHILD steps produced by the split, not on the parent, since
  the badge marks the nested row.
  PROOF REQUIRED: a contract test asserting a real `sub_loop_split` emit carries
  `branchLabel` on the child steps — reached from the actual split path, not by calling a
  helper. Locked by CT-9, which asserts "Sub-Loop" reaches no user-facing surface.

- [x] **T3 (REQ-5, REQ-6)**: Question sets + enforce the single funnel —
  `backend/agent/tools/ask_user_tool.py`, `backend/iris_gateway.py:5399`
  RIPPLE: gateway must call `resolve_answer`, not `receive_answer`, so a card click
  resumes a parked source like voice does. Single-question payloads must still work —
  CT-2. Inverts T0c.

- [x] **T4 (REQ-4 AC1)**: Persist card state against its conversation —
  `backend/agent/conversation_context_store.py`
  RIPPLE: `ConversationMessage` is `{role, content, turn_id}`; follow the document
  persistence shape rather than inventing a second one. Inverts T0f.

- [x] **T4a (REQ-4 AC1/AC5) — ADDED 2026-08-19, THE MISSING HALF OF T4**: Wire the card
  store to the live emit sites — `backend/agent/agent_kernel.py`
  WHY THIS EXISTS: T4 built `conversation_cards` + `save_card()` /
  `get_cards_for_conversation()` and they are fully tested — but NOTHING CALLS THEM. As
  written, T4 delivers a persistence layer that no code path reaches, so cards still
  vanish. This is the FOURTH occurrence of built-but-unreached in this codebase (vision
  routing, the permission gate, the CLI registry, now this). Splitting store from wiring
  is exactly how the first three happened.
  RIPPLE: write on `task:start` (upsert, terminal_state="running") and on
  `task:done`/`task:fail` (terminal state), plus on the two TASK_PROGRESS step-transition
  sites so a card interrupted mid-run restores with current step statuses — REQ-4 AC5 is
  meaningless if the only write happens at the end, because the interrupted case never
  reaches the end.
  HOT PATH CONSTRAINT: the store is synchronous SQLite and these emit sites are async. A
  bare `save_card()` there is a blocking call in an async hot path — forbidden by the
  quality check, and the Wormhole doc already flags mid-stream latency as unresolved and
  blocking. Writes MUST be non-blocking (thread offload or a drained queue) and coalesced
  per `card_id`. A failed write must never block execution or a user response.
  PROOF REQUIRED: a contract test asserting the write is REACHED FROM A REAL EMIT PATH,
  not that `save_card` works when called directly — T4's tests already prove the latter
  and would stay green with zero wiring. This is the CT-11 guard applied to REQ-4.

- [x] **T5 (REQ-11)**: Card footprints keyed by `card_id` — `backend/memory/`
  RIPPLE: writes through the existing store interface (NO CHANGE verified). Foundation
  only — no `@card:` addressing (Decisions Locked 6). A failed write must never block
  execution.

## Wave 2 — Frontend state model (T6 depends on T1)

- [x] **T6 (REQ-3, REQ-4)**: `useTaskProgress` single card -> `Map<card_id, Card>` scoped
  to a conversation; reset-on-switch becomes restore-on-switch
  — `hooks/useTaskProgress.ts`
  RIPPLE: the highest-risk task in the spec. `:224-229` wipe and the `:255` merge
  heuristic both change. Legacy payloads without `card_id` must fall back to today's
  merge, not drop the card. Inverts T0a.

- [x] **T7 (REQ-4 AC2/AC4)**: Render the keyed collection and rehydrate on conversation
  open/switch — `components/chat-view.tsx`
  RIPPLE: `:3445-3459` renders one card today. Must not duplicate an already-rendered
  card — CT-4. Depends on T6.

- [x] **T7a (REQ-4 AC2/AC4/AC5) — ADDED 2026-08-19, THE TRANSPORT NOBODY OWNED**: Serve
  persisted cards to the frontend on conversation open — `backend/iris_gateway.py`,
  `hooks/useIRISWebSocket.ts`, `hooks/useTaskProgress.ts`
  WHY THIS EXISTS: T4/T4a persist cards to the `conversation_cards` table and T6/T7 can
  render a keyed collection — but NOTHING READS THE TABLE BACK. Confirmed by grep: there
  is no `get_cards` handler in `iris_gateway.py` and no endpoint exposing
  `get_cards_for_conversation`. So the write path and the render path are both complete
  and are not connected to each other. A fresh page load still shows no cards, which is
  the ORIGINAL user-reported bug REQ-4 exists to fix.
  This is the SIXTH built-but-never-reached defect found in this codebase (vision routing,
  the permission gate, the CLI registry, the card store wiring, the branch label, now the
  card read path). The pattern is consistent: each half is built correctly and tested in
  isolation, and no test asks whether the halves are joined.
  RIPPLE: the store's READ path already resolves a `terminal_state == "running"` card to
  `terminated_unknown`, so REQ-4 AC5 is satisfied by transporting that value faithfully —
  do NOT re-implement the transition on the frontend.
  Rehydration must not duplicate a card already rendered, keyed on `card_id` (AC4, CT-4) —
  the document rehydration guard in `__tests__/components/chat-view-rehydration.test.ts`
  is the working precedent; extend it rather than inventing a second one.
  Never blank a card that already has content — the failure mode already guarded for docs.
  PROOF REQUIRED: a test driving conversation-open and asserting cards written by the
  backend arrive and render, failing if the handler is removed. Assert it end-to-end across
  the seam, not on either side alone — testing each half separately is precisely what let
  this gap exist.


## Wave 3 — Chassis (T8 gates T9–T11)

- [x] **T8 (REQ-1, REQ-2 AC3)**: Promote `VariantLiquidInk` out of `temp/` into a shared
  `CardChassis` — `components/chat/CardChassis.tsx`
  RIPPLE: ONE implementation for all four card types (REQ-2 AC3). Must expose the accent
  vein, header slot, counter and collapse affordance as chassis-level concerns. REQ-1
  AC5 padding lives here so every card inherits it.
  FIDELITY: reproduce the tokens in design.md "Liquid Ink tokens as built" — this is the
  variant the user chose, not a starting point. Two deliberate departures, both required:
  apply the 9px/10px type floor (Decision 14, three 8px elements move up), and label the
  branch row "Diving Deeper" not "Sub-Loop" (Decision 13). Locked by CT-8.

- [x] **T9 (REQ-1, REQ-10)**: Task card on the chassis + memory activity in the header
  — `components/chat/TaskListCard.tsx`
  RIPPLE: 434 lines today. Memory slot renders only from real events (REQ-10 AC4) —
  never fabricated. Depends on T8.

- [x] **T10 (REQ-2, REQ-5)**: Question card on the chassis + multi-question rendering
  — `components/chat/QuestionCard.tsx`
  RIPPLE: consumes T3's question set. Per-question `multiSelect`, header, and unanswered
  state (REQ-5 AC3/AC4/AC5). Inverts T0d. Depends on T8 + T3.

- [x] **T11 (REQ-2)**: Permission and rich-document cards on the chassis
  — `components/chat/PermissionCard.tsx`, `components/chat/RichDocument.tsx`
  RIPPLE: RichDocument is 889 lines and the highest regression risk in the spec — swap
  the chassis ONLY, do not touch its content logic. REQ-2 AC4 forbids any capability
  change. Depends on T8.

- [x] **T11a (REQ-2 AC6) — FOUND IN FINAL AUDIT**: Expanded document panel on the chassis
  — `components/chat/DocumentPanel.tsx`
  RIPPLE: it is the EXPANDED form of RichDocument (`chat-view.tsx:3606`) with its own
  gradient. Restyle T11's card without this and expanding a document jumps style
  mid-interaction. Depends on T8 + T11.


## Wave 3b — Registries (gates the card and CLI rendering)

- [x] **T8a (REQ-14)**: Action verb registry — `lib/cards/verbRegistry.ts`
  RIPPLE: consumed by BOTH the GUI card (T9) and the CLI renderer (T12) — build it before
  either renders a verb, or the mapping forks. Must cover all 51 registered tools across
  10 families; longest verb is 6 chars so the column is fixed at 6 with no truncation.
  Locked by CT-6.

- [x] **T8b (REQ-15)**: Memory event registry — `lib/cards/memoryRegistry.ts`
  RIPPLE: fixed fields in fixed order per Wormhole doc Section 9. Register `learning`
  (already emitting), plus `recall` / `compress` / `episodic` (emits added in T8c), and
  RESERVE the Wormhole vocabulary (tier, posterior, hex_bin_id, resonance, elevation)
  without implementing it. Locked by CT-7.

- [x] **T8c (REQ-10 AC5)**: Emit the memory events the card renders —
  `backend/agent/mcm.py`, `backend/agent/agent_kernel.py`
  RIPPLE: `mcm.py` has ZERO `emit`/`event_bus` references today, so `recall()` (`:161`)
  and `compress()` (`:86`) are silent, as is episodic `get_task_context`
  (`agent_kernel.py:752`). Without this the footer is honest and permanently empty.
  Emits must stay OFF the recall hot path — the Wormhole doc flags mid-stream recall
  latency as an unresolved blocking concern; do not add synchronous work there.

## Wave 4 — CLI (parallel with Wave 3)

- [x] **T12 (REQ-8, REQ-9)**: Promote `CLITaskProgressRenderer` out of `temp/`; close
  every right wall using VISIBLE width (ANSI-stripped, display-width aware); add the
  header icon — `lib/cli/CLITaskProgressRenderer.ts`
  RIPPLE: naive `padEnd` misaligns every coloured line — measure visible width, not
  `String.length`. Alignment must be identical with colour on and off — CT-5. Inverts
  T0e.
  FIDELITY: reproduce the tokens in design.md "Blueprint Matrix tokens as built". Frame
  inner width is 66. The verb is ALREADY `padEnd(6)` (`:311`) — Decision 12 follows the
  variant here, it does not override it. Branch chamber label becomes "Diving Deeper"
  (Decision 13); the brightMagenta treatment is unchanged.
  LABEL WIDTH — a real consequence of Decision 13's revision: "Diving Deeper" is 13 chars
  where "Detour" was 6. The variant in `temp/` closes the branch chamber with a FIXED
  literal dash run (`┌┄┄ ↳ [label] ┄┄┄…┐`), so a longer label pushes the corner past the
  66-wide frame. The filler MUST be computed from the remaining visible width, not
  hardcoded. This is the same measure-don't-assume rule as the right wall — the label
  change simply makes an already-latent bug visible.
  ALSO FIX: `CLITaskProgressRenderer.render()` (`:348-350`) currently delegates to
  `renderCyberDoubleRailCLI` — the Flow Pipeline variant, NOT the selected Blueprint
  Matrix. Repoint it, and drop the unselected variants when promoting out of `temp/`.

- [x] **T13 (REQ-7)**: Render task blocks and question sets in the terminal; route CLI
  answers through the REQ-6 funnel — `components/terminal/TerminalPanel.tsx`
  RIPPLE: input handling at `:113-140` is otherwise untouched (Decisions Locked 5). A
  question arriving mid-command must preserve the input buffer. Depends on T12 + T3.

  ALSO OWNS REQ-9's ASCII FALLBACK — surfaced by T12 on 2026-08-19. The renderer's API is
  `render(task, useColor)`, which carries NO signal about whether the terminal can draw box
  glyphs, so T12 could not implement the REQ-9 edge case and correctly declined to invent
  an untested parameter. T13 is the integration point that actually KNOWS the terminal's
  capability, so the signal belongs here: extend the renderer call with a glyph-capability
  flag and pass the real value. Default to glyphs ON so nothing regresses; the ASCII path
  must hold the SAME column arithmetic (T12 measures by display width, and an ASCII frame
  must not quietly reintroduce the ragged-row bug in a second code path).
- [x] **T13a (REQ-13)**: Terminal becomes an on-demand slide-over — remove the resident
  panel, keep the icon, position so it never occludes the composer or the active card;
  preserve scrollback across open/close
  — `components/workspace/DeveloperWorkspace.tsx`, `components/chat-view.tsx`
  RIPPLE: `FloatingPanel` (`DeveloperWorkspace.tsx:13`) already exists as the positioning
  primitive — reuse it rather than adding a second overlay system.

- [x] **T13b (REQ-13 AC5/AC6, REQ-20 AC1/AC4) — REWRITTEN 2026-08-19**: Make the two
  command channels DISTINCT AND LABELLED — `components/chat-view.tsx:1379-1387`,
  `components/terminal/TerminalPanel.tsx:122`,
  `components/terminal/TerminalWidget.tsx:106`, `backend/iris_gateway.py`
  ⚠ THE ORIGINAL TASK SAID "converge to one channel". THAT IS WRONG AND MUST NOT BE DONE.
  Verified 2026-08-19: `terminal_input` (`iris_gateway.py:831`) runs the line as DIRECT
  SHELL INPUT, while `dev_cli` (`:823`) hands it to the DevOrchestrator, which picks a
  registered CLI tool via an LLM and drives it through the DER loop. They are two
  capabilities, not one job done twice. Converging them deletes one.
  WHAT TO DO INSTEAD: keep both channels; make which one you are talking to OBVIOUS.
  SHELL = runs literally. DELEGATE = the orchestrator chooses a tool.
  RIPPLE: `TerminalWidget` sends `terminal_input` and `TerminalPanel` sends `dev_cli`, and
  `DeveloperWorkspace` mounts `TerminalWidget` — so which semantic a user gets depends on
  which component happens to be mounted (REQ-20 AC4). Fix that disagreement explicitly;
  do not "unify" it by deleting a channel.
  Wrap output in the T12 Blueprint Matrix block and LABEL THE BLOCK with its mode (AC3).
  Raw pty output that is not task-shaped still renders verbatim INSIDE the walls.
  PROGRESS 2026-08-19 (session 240): channel distinction + SHELL/DELEGATE user labels +
  TerminalWidget/TerminalPanel agreement DONE. chat-view routes `>`→SHELL (terminal_input)
  and `/run `→DELEGATE (dev_cli); live mode badge shows active channel before commit; both
  terminal banners relabelled user-facing (no "DER loop"). Blueprint-Matrix block mode-label
  (AC3 output labelling) is delivered via T13a / REQ-13 AC5.

- [x] **T13c (REQ-20 AC5/AC6/AC7) — NEW**: Surface the command reference —
  `backend/dev/cli_registry.py`, `backend/main.py`, `components/terminal/`,
  `components/chat-view.tsx`
  RIPPLE: `backend/dev/cli_tools.yaml` ALREADY carries `display_name` and `when_to_use`
  for `kilo_code` / `claude_code` / `opencode`, and that metadata is currently fed only to
  the DevOrchestrator's own LLM prompt — the human is told nothing. Expose the EXISTING
  registry through an endpoint and render it; do NOT hardcode a second copy in the
  frontend, or the two will drift the way the verb mapping would have without T8a.
  DELIVERABLES: a `/help` command answered LOCALLY (never sent to the agent as a task —
  REQ-20 edge case); a persistent affordance that opens the same reference; prefix
  documentation (`>` and `/run ` are currently undocumented anywhere in the UI); and
  replacement text for the two implementation-detail strings the user sees today —
  the chat placeholder "Type command or drop file..." (`chat-view.tsx:3744`) and the
  terminal banner "Routes through agent kernel DER loop"
  (`TerminalPanel.tsx:106-111`), neither of which tells anyone what to type.
  A tool in the registry that is not installed renders as unavailable WITH the reason,
  never hidden — same rule as REQ-19 AC5.
  PROGRESS 2026-08-19 (session 240): replacement text DONE — chat placeholder now reads
  "> shell • /run delegate" (developer) and terminal banners relabelled user-facing
  (no "DER loop" / "Direct shell access"). PENDING: `/help` command (local, never to agent),
  persistent affordance, and the cli_tools.yaml endpoint + render (AC5/AC6).

## Wave 4b — Permissions (independent of the visual work)

- [x] **T0g (pins T20) — BASELINE**: Characterize the permission gate as it is — with no
  `mode` in config, `get_mode()` returns `"personal"` and a `SIDE_EFFECT` tool like
  `write_file` AUTO-APPROVES with no `PERMISSION_REQUEST` emitted
  — `backend/tests/contract/test_permission_gate_baseline.py`
  BASELINE GAP: nothing asserts the gate is ever reached. This pins the user-reported
  symptom — "it has never once asked me" — as a test.

- [x] **T20 (REQ-16)**: Make the effective permission mode truthful — the launcher's
  selection must reach `cfg["mode"]`, and an ABSENT mode must not resolve to the most
  permissive policy — `backend/capabilities.py:66-73`, `backend/main.py:1070-1083`
  RIPPLE: `get_mode()` is also used by `is_tool_allowed` / `allowed_tools`
  (`tool_bridge.py:476`, `:1108`), so changing the fallback changes TOOL AVAILABILITY as
  well as permissions. Verify both. Do NOT touch the tier matrix — it is correct.
  Inverts T0g.
  TWO TRAPS — both verified 2026-08-19, do not discover them the hard way:
  (a) `CapabilitySet.allowed_tools()` (`capabilities.py:94`) is NAMED BACKWARDS. Its
      docstring says "the set of tool names permitted" and it RETURNS THE BLOCKED SET in
      personal mode (empty set in developer means "block nothing"). Its only caller reads
      it correctly as `blocked = CapabilitySet.allowed_tools()` (`tool_bridge.py:477`), so
      behaviour is right and the name lies. This task's instruction to "verify both
      surfaces" is precisely where an implementer who trusts the name inverts the logic.
      Rename it `blocked_tools`, or leave it and put the warning in a comment — but decide.
  (b) `permission_level_from_config()` (`permissions.py:189`) returns `"developer"`
      unconditionally from BOTH branches and has NO caller; the live gate uses
      `get_mode()`. Reading `permissions.py` alone gives the opposite of production
      behaviour. Delete it, or make it THE resolver and route `tool_bridge` through it —
      pick one, do not leave both.
  SCOPE NOTE: T20 fixes the mode binding only. It does NOT make the gate reachable for
  repo/terminal tools — that is T23 (REQ-18). Landing T20 alone leaves the user's
  reported symptom in place.

- [x] **T21 (REQ-16 AC2/AC5)**: Surface the effective mode in the UI and log the resolved
  action per gated call — `components/chat-view.tsx`, `backend/agent/tool_bridge.py`
  RIPPLE: answers "why was I not asked" without reading a config file. Logging stays off
  the execution hot path.

- [x] **T22 (REQ-17)**: Prove enforcement — CT-11/CT-12/CT-13 plus behavioral drives
  — `backend/tests/contract/`, `backend/tests/behavioral/`
  RIPPLE: CT-11 is the "reached from a real path" test whose absence let the vision
  hierarchy ship fully built and unreachable. CT-12 pins that `_DESTRUCTIVE_TOOLS` names
  8 tools of which only `delete_file` exists in the runtime registry — decide whether to
  prune the list or widen the registry, but do not leave them silently divergent.

- [ ] **T0h (pins T23) — BASELINE**: Characterize the `[13.3]` gate — in personal mode
  `is_tool_allowed("write_file")` is False and `tool_bridge` RETURNS AN ERROR at Phase 2
  without ever reaching Phase 4; assert `delete_file` is in `_REPO_TOOLS` and therefore
  can never prompt despite being the only registry tool classified `DESTRUCTIVE`
  — extend `backend/tests/contract/test_permission_gate_baseline.py`
  BASELINE GAP: the existing T0g baseline pins Phase 4's auto-approve but assumes the
  call REACHES Phase 4. For repo/terminal tools it does not. This is the sanctioned
  second edit to that file; call it out in the report.

- [x] **T23 (REQ-18)**: Turn capability denial into a permission ESCALATION —
  `backend/agent/tool_bridge.py:1108-1116`, `backend/agent/permissions.py`
  RIPPLE: the `[13.3]` block must stop returning an error in personal mode and instead
  mark the call so Phase 4 gates it. Do NOT move the internet/desktop gate
  (`capability_allowed(spec)`) — it denies for a different reason (REQ-18 AC5). Developer
  mode must be byte-identical (AC4). Reuse the existing tier matrix: escalation maps onto
  `REQUIRE_APPROVAL` / `REQUIRE_CONFIRMATION`, no new policy. Inverts T0h.
  ALSO: make the Phase 4 `except Exception` fail CLOSED (AC6). It currently logs
  "allowing tool to proceed" and permits.

- [x] **T24 (REQ-19 AC1/AC2/AC7)**: Approval classes + per-session approval cache —
  `backend/agent/permissions.py`
  RIPPLE: ALWAYS_ASK = `_DESTRUCTIVE_TOOLS` ∪ `_TERMINAL_TOOLS`; SESSION_APPROVABLE =
  `_REPO_TOOLS` − ALWAYS_ASK. DERIVE both from the module constants — a literal list here
  is the bug this task exists to prevent, because the classes would drift from the tiers
  the matrix uses. Session cache is in-memory, keyed by session and tool name, and must
  not survive the process. Precedence is AC7 and is testable in isolation.
  ALWAYS_ASK TOOLS NEVER ENTER THE CACHE AT ALL — do not write an entry and then check a
  precedence rule against it later. Approving `delete_file` or `run_command` records
  nothing; the next call prompts again (AC8, Decision 20). The safest structure is a cache
  whose write path physically refuses ALWAYS_ASK names, so a future precedence bug cannot
  resurrect them.

- [x] **T25 (REQ-19 AC3/AC4/AC6)**: Persist and re-validate the standing list —
  `backend/capabilities.py`, `backend/main.py`
  RIPPLE: `cfg["approved_tools"]`, written through the same validated path
  `main.py:1070-1083` uses for `mode`. RE-VALIDATE ON READ: a hand-edited config naming
  an ALWAYS_ASK tool must be rejected at read time, not honoured (AC4) — the config is a
  file the user can edit, so storage is not trust. Unreadable config -> empty list AND
  still prompt (AC6), never open.

- [x] **T26 (REQ-19 AC3/AC5, REQ-16 AC2)**: The toggle surface — `data/cards.ts`,
  `data/navigation-constants.ts`, `components/wheel-view/fields/`,
  `components/wheel-view/SidePanel.tsx`, `backend/main.py`
  RIPPLE: define ONE card (section_id `permissions`) in `CARDS_BY_SECTION` and map it in
  `CARD_TO_SECTION_ID`. Both surfaces the user named are card-driven off the same data —
  `dark-glass-dashboard.tsx` renders `CARDS_BY_SECTION`, `SidePanel.tsx` renders fields
  per card — so one definition lands in BOTH. Do not build two lists.
  NEW FIELD TYPE REQUIRED: the existing `ToggleField` is a single boolean. This needs a
  composite that renders the DERIVED tool list with three row states — approvable
  (toggle), ALWAYS_ASK (locked + reason, AC5), and stale/absent-from-registry (marked,
  not silently dropped). Add it under `components/wheel-view/fields/` alongside the
  others; do NOT introduce a second switch primitive.
  PERSISTENCE: extend `POST /api/config/save` (`main.py:1823`) for
  `section_id="permissions"`. Check the APPLY contract first —
  `__tests__/components/dark-glass-dashboard.apply.test.tsx` asserts `confirm_card` is
  NOT re-sent for self-managed sections. A toggle list should apply immediately
  (self-managed) rather than sit behind APPLY; if you choose that, the section must be
  registered as self-managed or that test will describe a lie.
  ALSO SURFACES THE EFFECTIVE MODE (REQ-16 AC2) — same panel, one trip.
  MODE DIVERGENCE — VERIFIED 2026-08-19, this is why the panel must show the BACKEND's
  mode and not the frontend's: `hooks/useLauncherMode.ts` resolves mode from URL param ->
  `?remote=1` -> localStorage `iris_mode_override` -> localStorage `iris-widget-mode` ->
  and only THEN `GET /api/mode`. No frontend file POSTs `/api/mode`; the ONLY writer of
  `cfg["mode"]` is the launcher (`POST /api/mode`, `main.py:1059`), whose launch config
  was broken until 2026-08-18. So the UI can render developer features from localStorage
  while the backend gates every tool as personal — the two have never had to agree. The
  panel MUST read the backend's effective mode, or it will confidently display the wrong
  policy.
  WORSE THAN A RACE: `useLauncherMode.ts:39-58` deliberately SUPPRESSES the backend value
  when mode came from a URL param, and `setModeOverride()` (`:79`) writes the localStorage
  override from the browser console. So the divergence is not a startup ordering problem that
  settles — an explicit `?mode=developer` keeps the frontend permanently disagreeing with
  `cfg["mode"]`, by design. Read the backend value for the POLICY display even where the
  frontend keeps using its own for FEATURE gating; do not unify the two in this task.

- [x] **T27 (REQ-18, REQ-19)**: Contract + behavioral proof — CT-14..CT-17
  — `backend/tests/contract/`, `backend/tests/behavioral/`
  RIPPLE: CT-14 GATE ORDER — a capability-blocked tool reaches the permission gate, and
  the assertion is about ORDER, not merely that Phase 4 can emit. A test that proves only
  the latter stays green while the prompt is unreachable in production; that is exactly
  how the vision hierarchy shipped. CT-15 precedence table (AC7) driven as a matrix.
  CT-16 a hand-edited config naming an ALWAYS_ASK tool is refused. CT-17 the classes are
  DERIVED — move a name between tier constants in the test and assert its class follows.
  Behavioral: approve once -> second call in the same session does not prompt -> restart
  -> it prompts again; and `delete_file` / `run_command` prompt EVERY time regardless of
  the standing list.

## Wave 5 — Verification

- [x] **T14 (REQ-1..15)**: Contract tests CT-1..CT-10 — `backend/tests/contract/`,
  `__tests__/`
  RIPPLE: CT-3 and CT-4 encode bugs observed live (dropped click answer, vanishing
  card). CT-10 encodes a spec bug — the two surfaces this document missed on its first
  pass — and is the guard against the same omission when a card type is added later.
  Write CT-10 EARLY, not last: it is the one test that fails loudly if the stream is
  only partly restyled.

- [x] **T15 (REQ-3, REQ-4, REQ-5, REQ-6)**: Behavioral tests — continue vs branch,
  rehydration across a switch, multi-question independence, click-equals-voice
  — `backend/tests/behavioral/`, `__tests__/`
  RIPPLE: the continue-vs-branch test must assert the SECOND card does not appear on a
  follow-up — the whole point of REQ-3.

- [x] **T16 (REQ-12)**: Card lifecycle observability — `backend/agent/agent_kernel.py`,
  `hooks/useTaskProgress.ts`
  RIPPLE: log relation decisions, rehydration counts, and answer resolutions with their
  input path. Off the render and inference hot paths (REQ-12 AC4).

- [x] **T17 (REQ-3, REQ-4)**: Extend the standing CDD harness with a card lifecycle
  replay — `scripts/validate_der_card_lifecycle.py`
  RIPPLE: drives start -> continue -> branch -> switch -> rehydrate every run. Must be
  observed going RED before being trusted — a harness never seen to fail proves nothing.

## Wave 6 — Cleanup

- [x] **T18**: Delete `backend/agent/ask_user_tool.py` (192 lines, dead)
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
