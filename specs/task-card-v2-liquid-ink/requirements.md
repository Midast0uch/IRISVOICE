# Requirements: Task Card v2 — Liquid Ink + Blueprint Matrix

## Decisions Locked
User-resolved 2026-08-18. Do not re-litigate.

1. **Card identity is declared by the BACKEND, not inferred by the frontend.** The
   agent kernel owns task identity and emits a `card_id` plus a continuation/branch
   relation. The frontend renders what it is told. Only the backend knows whether it
   reopened the same task thread.
2. **Cards MUST rehydrate in the conversation they were created in.** They currently
   disappear. This is a defect, not a preference.
3. **The GUI chassis is Liquid Ink** (`VariantLiquidInk.tsx` — fluid ink surface,
   animated warm accent vein on the left edge, ripple-ring active nodes, bracketed
   `[done/total]` counter). Use that exact variant's design language, not an
   approximation.
4. **ALL inline chat cards adopt the Liquid Ink chassis** — task progress, question,
   permission, and rich document — so the chat stream reads as one system.
5. **The CLI chassis is Blueprint Matrix** (`┌──┐` / `├──┤` / `└──┘` outer walls with
   dotted `┊` guide rails and hairline `┄` sub-chambers), applied to TASK PROGRESS
   BLOCKS ONLY. Terminal chrome, prompt and shell behaviour are out of scope.
6. **Card IDs and memory footprints are built now; the @-tagging UX is a later spec.**
   Every card gets a stable ID tied to its conversation session and persists its
   footprint. Cross-thread/subagent card referencing is explicitly deferred.
7. **Padding is a requirement, not polish.** No text or icon may overflow or be clipped
   at any card edge, in either chassis.
8. **`task-preview` is a DEMO, not the target.** Take the concepts; match the real event
   stream and the real components. Do not port demo scaffolding into production.
9. **The always-present terminal panel is REMOVED.** In developer mode the chat stream
   IS the CLI. The terminal icon stays and opens an on-demand SLIDE-OVER for a raw pty.
10. **`>cmd` / `/run` output renders as a Blueprint Matrix block**, not plain passthrough.
11. **Verbs and memory-footer entries live in CENTRAL REGISTRIES.** The Wormhole
    resonant-recall upgrade (`docs/Wormhole-resonant-recall-.md`, `specs/node-chains`) is
    planned but NOT built here. This design must let that work ADD entries without
    restructuring the card. The registries are the seam that makes that true.
12. **Verbs are capped at SIX characters and are real words, never acronyms.** All 26
    verbs in the vocabulary fit natively (`COMMIT`, `BRANCH`, `SEARCH`, `SCRIBE`,
    `RECALL` are the longest). A fixed 6-character column keeps the CLI matrix aligned
    and stops the verb overpowering the target text — with no truncation, no ellipsis,
    and no shrinking below legible type. Compatible with the variant as built: the verb
    column is `w-12` (48px) at 10px mono, so 6 characters fit with room to spare.
13. **"Sub-Loop" is BANNED as user-facing terminology. The words are "Diving Deeper".**
    REVISED 2026-08-19: the label was briefly "Detour" and the user overruled it, correctly.
    A detour is by definition a route AROUND an obstruction that still reaches the same
    destination — the opposite of what happens here. Verified in
    `agent_kernel.py:11570-11612`: when a step yields child steps the agent routes those
    children and re-emits the plan, so it goes INTO the step and expands it. "Diving
    Deeper" describes that and matches the nested indent the row already has.
    Rejected alongside it: "Breaking down", which reads as decomposition but equally reads
    as MALFUNCTIONING — the same category of error as "Detour", in a new costume.
    User-resolved. It renders as `↳ Diving Deeper: <topic>` and keeps the existing colour
    treatment exactly (purple on the card, bright magenta in the CLI) — the coloured
    action text is liked and stays. This is a CONTENT change: `branchLabel` is free
    text, not a hardcoded string, so nothing about the rendering changes. "Sub-loop"
    remains valid INTERNAL vocabulary (`is_subloop`, `sub_loop_split`); it must never
    reach a surface a non-developer reads.
14. **The permission/security system is IN SCOPE.** User-reported: the agent has never
    once asked for permission. Root cause found — the plumbing is complete and correct;
    the GATE is effectively off because `data/iris_config.json` has no `mode` key, so
    `CapabilitySet.get_mode()` falls back to `"personal"`, where everything except
    `DESTRUCTIVE` auto-approves. Fix the binding and prove it with tests. Do NOT rewrite
    the permission policy — the tier matrix is sound.
15. **Minimum legible type: nothing below 9px, and anything carrying meaning is at
    least 10px.** The variant as built uses 8px in three places — including
    `branchLabel`, which is precisely the element the user singled out as wanting to be
    understood. 8px is eliminated.

16. **A capability-blocked tool in personal mode ASKS — it does not silently fail.**
    User-resolved 2026-08-19. Today `is_tool_allowed()` returns false for the 23
    repo/terminal tools in personal mode and the `[13.3]` gate returns an error before
    the permission gate is ever reached, which is why `delete_file` — believed to be the
    one promptable tool — can never prompt. Capability denial becomes an ESCALATION into
    the permission gate, not a terminating error. Developer mode is unaffected
    (`is_tool_allowed` already returns true for everything there).
17. **Approval has three classes, and each class is derived from the existing tier
    constants — never from a new hardcoded list.**
    - ALWAYS_ASK = `_DESTRUCTIVE_TOOLS` ∪ `_TERMINAL_TOOLS`. Prompts on EVERY
      invocation. Never session-cached. Never eligible for the standing list.
    - SESSION_APPROVABLE = `_REPO_TOOLS` − ALWAYS_ASK. Approving once allows that tool
      for the rest of the session; the approval dies with the process.
    - UNGATED = everything else, per the existing tier matrix, unchanged.
18. **The user keeps a standing, editable list of approved tools that applies every
    session** — surfaced in the dark glass dashboard / wheelview side panel. Only
    SESSION_APPROVABLE tools may be on it. ALWAYS_ASK tools are shown LOCKED with a
    reason rather than hidden, so their absence reads as deliberate rather than as a
    missing feature. Deletion tools and shell commands NEVER persist across sessions or
    restarts under any setting — the agent always asks.

19. **`git_push` and `github_delete_ssh_key` stay SESSION_APPROVABLE.** User-confirmed
    2026-08-19 after being flagged as outward-facing and effectively irreversible. They
    are neither deletion tools nor shell commands, so the REQ-19 rule applies unchanged
    and the derivation stays clean — no per-tool exception is carved into the class
    boundaries. Do not re-raise this.
20. **ALWAYS_ASK means EVERY INVOCATION.** User-confirmed 2026-08-19. Deletion tools and
    shell commands prompt on every single call — not once per session, not once per
    restart. There is no approval that suppresses a second prompt for these tools, and no
    setting that can. This is stricter than "does not persist across restarts", which was
    the weaker reading offered and explicitly rejected.

21. **ERASE is the 27th verb; `delete_file` uses it, not PATCH.** Added 2026-08-19 during
    T8a. The original 26-verb vocabulary had no deletion verb, and the closest io verb —
    PATCH, "mutate existing state" — UNDERSTATES a destructive action. The task card is
    the user's record of what the agent actually did, so the one place a verb must not be
    softened is the destructive one. This also keeps the label consistent with Decision
    17, where `delete_file` is ALWAYS_ASK: the permission layer treats it as the most
    dangerous class and the display must agree. ERASE is 5 chars, a real word, no acronym
    — it obeys REQ-14 AC2, so the vocabulary's RULES are unchanged; only its COVERAGE
    grew. This is what REQ-14 AC6 exists for: a verb change is a registry edit alone.
    STILL OPEN, deliberately not changed: `git_status` maps to DIFF because no STATUS
    verb exists. That is cosmetic and harmless (read-only tool, and REQ-14 explicitly
    allows two tools to share a verb), so it was left rather than growing the vocabulary
    a second time. Say the word if you want STATUS added — it is exactly 6 chars and
    would fit.

## Introduction
The task progress card is IRIS's living execution surface, but today it is a single
mutable blob of state: one card at a time, wiped on every conversation switch, with no
identity, no persistence, and no relationship to the conversation that produced it.
Alongside it, the question card cannot represent more than one question, and answering
by click takes a different code path from answering by voice. This feature replaces the
card with the Liquid Ink chassis, gives cards backend-declared identity and persistence,
repairs the question path, and brings the same discipline to the developer CLI.

### Success criteria
- Switching away from a conversation and back shows the same task cards, intact.
- A follow-up prompt on the same task extends its card; a new intent creates a new one.
- A multi-question `AskUserQuestion` renders every question, and each answer reaches the
  agent that asked it.
- No text or icon is clipped at any card edge, in the GUI or the terminal.
- Every CLI content line closes its right wall — nothing leaks outside the brackets.
- Every card carries an ID that can later be addressed as `@card:<id>`.

## Requirements

### REQ-1: Liquid Ink chassis for the task progress card
**User Story:** As a user I want the task card to look and feel like the Liquid Ink
variant I chose, so that the execution surface is legible and calm.

**Verified:** `temp/task-card-redesign/variants/VariantLiquidInk.tsx:44-120` defines the
chassis (vein colour by state: `#f97316` idle / `#fbbf24` thinking / `#34d399`
crystallized; `Xur` nucleus; bracketed counter; collapse chevron). Current production
card is `components/chat/TaskListCard.tsx` (434 lines).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL render the task progress card with the Liquid Ink chassis: ink
  surface, left accent vein, ripple-ring active nodes, and bracketed `[done/total]`
  counter.
- AC2: THE SYSTEM SHALL drive the vein colour from execution state — working, thinking,
  and crystallized are visually distinct.
- AC3: WHILE any step is running THE SYSTEM SHALL animate the vein and the active step
  node; WHEN execution converges THE SYSTEM SHALL settle both to a static state.
- AC4: THE SYSTEM SHALL keep the existing collapse/expand affordance.
- AC5: THE SYSTEM SHALL apply internal padding such that no glyph, icon, badge or
  counter is clipped or overflows the card edge at any viewport width.
- AC6: THE SYSTEM SHALL reproduce the variant's design tokens as built, not an
  approximation — vein geometry and state colours, the `w-12` verb column, the four step
  node states (ripple-ping while running, emerald glow when crystallized, vein-coloured
  dot when done, dim ring when pending), the THK badge, the indented branch row, and the
  footnote's memory slot plus elapsed timer. See design.md "Liquid Ink tokens as built".
- AC7: THE SYSTEM SHALL render no type below 9px, and SHALL render any element carrying
  meaning at 10px or larger. The `branchLabel` badge, at 8px in the variant, moves to
  10px.
- AC8: THE SYSTEM SHALL label a nested investigation "Diving Deeper" and SHALL NOT surface
  "Sub-Loop" anywhere a user reads.

**Edge Cases:**
- Zero steps -> the card renders header and thought stream without an empty step well.
- Very long objective -> truncates with ellipsis, never wraps outside the chassis.
- Reduced-motion preference -> vein and ripples render static, no animation.

### REQ-2: Liquid Ink chassis for all inline chat cards
**User Story:** As a user I want every card in the chat stream to belong to the same
visual system, so the stream does not look assembled from parts.

**Verified:** Inline cards today are `TaskListCard.tsx`, `QuestionCard.tsx` (153),
`PermissionCard.tsx`, `RichDocument.tsx` (889). `QuestionCard` currently uses a
borderless "orbital" treatment keyed to `useBrandColor()`
(`components/chat/QuestionCard.tsx:31-33`) — a different system from the task card.

ONE MORE CARD SURFACE, found in the final audit and originally MISSED by this spec —
the exact "unaligned ripple" failure of restyling most of the stream and leaving part of
it behind:
  - `DocumentPanel.tsx` is the EXPANDED form of `RichDocument`, opened as a modal
    (`chat-view.tsx:3606`, `role="dialog"`). It carries its own gradient
    `linear-gradient(135deg, rgba(10,10,20,.99), rgba(5,5,10,.98))`, which is NOT the
    Liquid Ink surface. Restyling the card without the panel means expanding a document
    changes its appearance mid-interaction.
  - (Plan events were briefly listed here as a third gap. They are NOT — see the
    two-path note below. Corrected during the audit.)

**THE TWO PATHS — do not conflate them.** The chat stream carries two distinct kinds of
content, deliberately:
  1. **The MESSAGE path** — `Message.sender` is `"user" | "assistant" | "error" |
     "system"` (`chat-view.tsx:112`). Plan events are first-class SYSTEM MESSAGES on this
     path (`chat-view.tsx:978-983`, text from `planEventMessage.ts:16`), as are error
     messages. These are meant to be plain text and MUST STAY plain text.
  2. **The CARD path** — task progress, question, permission and rich document, each
     rendered as a card with a chassis.
REQ-2 applies to the CARD path only. Forcing a system message into a card chassis would
merge two paths the design keeps apart.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL render the question, permission and rich-document cards on the
  same Liquid Ink chassis as the task card.
- AC2: THE SYSTEM SHALL express each card's role through the accent vein colour and
  header badge rather than through a different chassis.
- AC3: THE SYSTEM SHALL share one chassis implementation across all inline cards so a
  future change lands in one place.
- AC4: THE SYSTEM SHALL preserve every existing interactive affordance of each card —
  visual change only, no capability regression.
- AC5: THE SYSTEM SHALL apply the REQ-1 AC5 padding guarantee to every inline card.
- AC6: THE SYSTEM SHALL render the expanded document panel on the same chassis as the
  card it expands from, so expanding does not change the surface.
- AC7: THE SYSTEM SHALL leave the MESSAGE path unstyled by this feature — plain system
  and error messages stay plain text. The chassis applies to the CARD path only.
- AC8: THE SYSTEM SHALL enforce chassis coverage by test — a CARD-path surface that does
  not render through the shared chassis SHALL fail, unless it is on an explicit allowlist
  of non-card surfaces (message body, system/error messages, pills, chips). Coverage
  asserted, not assumed: this requirement exists because the first draft of this spec
  missed `DocumentPanel`.

**Edge Cases:**
- Brand colour set by the user -> the chassis honours it without breaking state colours.
- A card type added later -> inherits the chassis by construction, not by copy-paste.

### REQ-3: Backend-declared card identity
**User Story:** As a user I want a follow-up on the same task to extend its card, and a
new request to start a fresh one, so the stream reflects what actually happened.

**Verified:** REAL GAP. `hooks/useTaskProgress.ts:224-229` holds a SINGLE card state and
resets it wholesale on `iris:new_conversation` / `iris:conversation_switched`. Merge is a
frontend heuristic at `:255` (`prev.turnId === d.task_id && prev.isWorking &&
prev.steps.length > 0`). The backend has ONE payload construction point,
`agent_kernel._task_start_payload` (`:7588-7610`), already carrying an `origin`
discriminator (`initial` / `sub_loop_split` / `user_steering`) — the natural home for
card identity.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL include a stable `card_id` in every `task:start` payload.
- AC2: THE SYSTEM SHALL include a `card_relation` of `new` or `continues` in every
  `task:start` payload.
- AC3: WHEN `card_relation` is `continues` THEN THE SYSTEM SHALL extend the existing
  card bearing that `card_id` rather than replacing or duplicating it.
- AC4: WHEN `card_relation` is `new` THEN THE SYSTEM SHALL render an additional card and
  SHALL leave prior cards in the stream intact.
- AC5: THE SYSTEM SHALL derive `card_relation` from task identity on the backend and
  SHALL NOT require the frontend to infer it.
- AC6: THE SYSTEM SHALL keep `card_id` stable across every event of one card's lifetime
  (`task:start`, `task:progress`, `tool:call`, `tool:result`, `task:done`).

**Edge Cases:**
- Two `task:start` emits for one task (the existing early/refined pattern) -> same
  `card_id`, relation `continues`, no flicker.
- A sub-loop split -> continues the parent card; it is a branch WITHIN a card, not a new
  card.
- Legacy payload with no `card_id` -> the frontend falls back to today's `task_id`
  merge behaviour rather than dropping the card.

### REQ-4: Cards rehydrate in their conversation
**User Story:** As a user I want to leave a conversation and come back to find my task
cards still there, so I do not lose the record of what the agent did.

**Verified:** REAL GAP, TWO CAUSES. (1) `hooks/useTaskProgress.ts:224-229` wipes card
state on conversation switch. (2) `backend/agent/conversation_context_store.py:49-50`
persists only `{role, content, turn_id}` per message — card state is never stored, so
there is nothing to rebuild from. Rich documents DO rehydrate, keyed on `document_id`
(`__tests__/components/chat-view-rehydration.test.ts:3`) — that is the working precedent
to follow.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL persist each card's state against its conversation.
- AC2: WHEN a conversation is opened, resumed or switched to THEN THE SYSTEM SHALL
  restore every card belonging to that conversation, in order.
- AC3: THE SYSTEM SHALL scope cards to their conversation — a card SHALL NOT appear in a
  conversation it was not created in.
- AC4: WHEN rehydrating THE SYSTEM SHALL NOT duplicate a card that is already rendered,
  keyed on `card_id`.
- AC5: THE SYSTEM SHALL restore a card that was mid-execution when the user navigated
  away as terminated-unknown rather than perpetually running.

**Edge Cases:**
- Card count exceeds the per-conversation message cap -> oldest cards drop with the
  conversation's existing retention rule, never a partial card.
- Rehydration payload missing fields -> render what is present; never blank a card that
  already has content (the failure mode already guarded for documents).
- Conversation switched mid-execution -> live events for the departed conversation do
  not mutate the newly-shown one.

### REQ-5: Multi-question support
**User Story:** As a user I want every question the agent asks to be shown, so I am not
answering one question while another waits invisibly.

**Verified:** REAL GAP ON BOTH SIDES. `components/chat/QuestionCard.tsx:9-14` takes
`text: string` and `options?: string[]` — structurally one question. The backend is also
single-question: `ask_user_tool.ask(text, options, ...)`
(`backend/agent/tools/ask_user_tool.py:70-104`). Multiple questions CAN be pending
simultaneously, and the tool resolves that by "most recent wins; the other stays pending"
(`:192-194`) — so a pending question can be invisible to the user.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL support a question set containing one or more questions.
- AC2: THE SYSTEM SHALL render every question in the set, each with its own prompt,
  options and answer control.
- AC3: THE SYSTEM SHALL support a per-question `multiSelect` flag and SHALL allow
  multiple selections only where it is set.
- AC4: THE SYSTEM SHALL carry a per-question header/label so questions are
  distinguishable.
- AC5: THE SYSTEM SHALL indicate which questions in the set remain unanswered.
- AC6: THE SYSTEM SHALL remain backward compatible with a single-question payload.

**Edge Cases:**
- One question answered, others pending -> answered ones lock, pending stay live.
- Timeout with a partially-answered set -> answered questions are reported; unanswered
  are reported as unanswered.
- Empty option list with `allowOther` -> free-text only, still valid.

### REQ-6: One answer funnel for every input path
**User Story:** As a user I want clicking an option to reach the agent exactly as
answering by voice does, so my answer is not silently dropped.

**Verified:** REAL GAP. `resolve_answer` is documented as the "SINGLE resolution funnel
(REQ-14 AC5, CT-4 first-wins)" and additionally resumes a parked source
(`backend/agent/tools/ask_user_tool.py:171-190`). Voice uses it
(`resolve_via_voice` -> `resolve_answer`, `:229`). The card click does NOT: the gateway
calls `tool.receive_answer(...)` directly (`backend/iris_gateway.py:5399`), bypassing the
funnel — so a click never resumes a parked source. The gateway's own comment at `:2835`
claims voice routes "through the same funnel as a card click", describing an intent the
code does not implement.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL route every answer — card click, free text, and voice — through
  one resolution funnel.
- AC2: WHEN an answer is submitted from a card THEN THE SYSTEM SHALL perform the same
  side effects as a voice answer, including resuming any parked source.
- AC3: THE SYSTEM SHALL preserve first-wins semantics — a second answer to an already
  resolved question is a no-op.
- AC4: WHEN an answer is submitted THEN THE SYSTEM SHALL confirm resolution in the card,
  so the user can see the answer landed.
- AC5: IF an answer references an unknown or already-resolved question THEN THE SYSTEM
  SHALL log it and SHALL NOT raise.

**Edge Cases:**
- Answer arrives after timeout -> treated as unknown, no crash.
- Click and voice race -> first wins, second is a silent no-op.
- Multi-question set -> each question resolves independently through the same funnel.

### REQ-7: AskUserQuestion in the developer CLI
**User Story:** As a developer in CLI mode I want the agent's questions rendered and
answerable in the terminal, so the loop is not GUI-only.

**Verified:** NEW. Terminal input is buffered per keystroke and submitted on Enter via
the `dev_cli` pipeline (`components/terminal/TerminalPanel.tsx:113-140`). No question
rendering path exists there today.

**Acceptance Criteria:**
- AC1: WHEN the agent asks a question WHILE the developer terminal is the active surface
  THEN THE SYSTEM SHALL render the question set in the Blueprint Matrix chassis.
- AC2: THE SYSTEM SHALL let the user select an option by index and submit free text.
- AC3: THE SYSTEM SHALL route CLI answers through the REQ-6 funnel — no separate path.
- AC4: THE SYSTEM SHALL render multi-question sets with the same completeness as the GUI.
- AC5: WHILE a question is awaiting an answer THE SYSTEM SHALL make the pending state
  visible in the terminal.

**Edge Cases:**
- Question arrives mid-command -> the in-progress input buffer is preserved.
- Invalid index -> re-prompt, never resolve with a wrong option.
- Question times out -> the terminal shows it closed and restores the prompt.

### REQ-8: Blueprint Matrix containment in the CLI
**User Story:** As a developer I want the terminal task block to be a sealed box, so
output does not leak past its walls.

**Verified:** REAL GAP. `temp/task-card-redesign/CLITaskProgressRenderer.ts` opens each
content line with a left wall but never pads to a fixed width nor closes a right wall —
e.g. `:181` pushes `${wall}  ${stem} ${orb} ${verb} ${s.target}` with no trailing wall.
Only the top and bottom borders close. Compounding it, ANSI colour codes inflate
`String.length`, so naive padding misaligns.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL close every content line of a task block with its right wall.
- AC2: THE SYSTEM SHALL compute padding from VISIBLE width, excluding ANSI escape
  sequences.
- AC3: WHEN content exceeds the inner width THEN THE SYSTEM SHALL truncate or wrap it
  inside the walls and SHALL NOT allow it to cross them.
- AC4: THE SYSTEM SHALL apply containment to header, body, sub-chambers and footer
  alike.
- AC5: THE SYSTEM SHALL keep all vertical rules (`│`, `┊`) in the same column on every
  line of a block.

**Edge Cases:**
- Wide (CJK/emoji) glyphs -> measured by display width, not code-point count.
- Terminal narrower than the block -> the block degrades to the available width rather
  than wrapping raggedly.
- Colour disabled -> alignment identical to the coloured rendering.

### REQ-9: Blueprint Matrix header
**User Story:** As a developer I want the task header to carry an icon and stay aligned
with the matrix rules, so the block scans as one grid.

**Verified:** `CLITaskProgressRenderer.ts:144` renders `TASK :` with no icon.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL render an icon immediately left of the `TASK` label in the
  header.
- AC2: THE SYSTEM SHALL keep the icon within the block walls and aligned to the matrix
  columns.
- AC3: THE SYSTEM SHALL keep the header's right wall closed per REQ-8.
- AC4: THE SYSTEM SHALL account for the icon's display width when aligning the label.

**Edge Cases:**
- Terminal without glyph support -> ASCII fallback that occupies the same width.

### REQ-10: Memory activity in the card header
**User Story:** As a user I want to see what the agent is doing with memory while it
works, so recall and crystallization are visible rather than implied.

**Verified:** The Liquid Ink variant accepts `memoryEvents` and reads the latest
(`VariantLiquidInk.tsx:22`, `:41`). The architecture doc specifies memory attribution in
the convergence footer. Backend memory tiers are `backend/memory/` (episodic, semantic,
skills).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL surface current memory activity in the card header in both
  chassis.
- AC2: WHEN the agent recalls from memory THEN THE SYSTEM SHALL show what was recalled
  and from which store.
- AC3: WHEN a skill crystallizes THEN THE SYSTEM SHALL show it in the card.
- AC4: THE SYSTEM SHALL render memory activity from real backend events and SHALL NOT
  fabricate it when no event has been received.
- AC5: THE SYSTEM SHALL EMIT the memory events it renders. Verified gap: only
  `task:learning` reaches the frontend today (`agent_kernel.py:11403`). The runtime MCM
  (`backend/agent/mcm.py`) contains ZERO `emit` / `event_bus` references, so its
  `recall()` (`:161`) and `compress()` (`:86`) are silent, as is episodic
  `get_task_context` (`agent_kernel.py:752`). Without new emits this requirement renders
  an honest but permanently empty slot.

**Edge Cases:**
- No memory activity -> the header omits the slot rather than showing an empty one.
- Rapid successive events -> the most recent shows; the rest remain in the trace.

### REQ-11: Card footprints in memory
**User Story:** As a user I want each card's execution recorded under a stable ID, so I
can later address that card and let other threads or agents read its footprint.

**Verified:** NEW. Foundation only — the `@card:<id>` addressing UX is out of scope
(Decisions Locked 6).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL persist a footprint per card containing its ID, conversation,
  objective, steps, tools used, files touched, and outcome.
- AC2: THE SYSTEM SHALL key the footprint by the REQ-3 `card_id`.
- AC3: THE SYSTEM SHALL associate the footprint with its conversation session.
- AC4: THE SYSTEM SHALL make footprints retrievable by `card_id` without loading the
  whole conversation.
- AC5: THE SYSTEM SHALL write footprints to the application memory store, not to
  build-time tooling.

**Edge Cases:**
- Card never completes -> footprint records the terminal state reached.
- Memory write fails -> the card still renders; the failure is logged, never surfaced as
  a crash.
- Duplicate `card_id` -> updates the existing footprint rather than creating a second.

### REQ-12: Observability for card lifecycle
**User Story:** As the tuner I want to see why a card continued or branched, so I can
tell whether the identity rule is behaving.

**Verified:** NEW

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log, per `task:start`: `card_id`, `card_relation`, the
  conversation, and the reason the relation was chosen.
- AC2: THE SYSTEM SHALL log each rehydration with the conversation and the number of
  cards restored.
- AC3: THE SYSTEM SHALL log every answer resolution with the question id, the input path
  (click / text / voice), and whether it was first-wins or a no-op.
- AC4: THE SYSTEM SHALL keep this logging off the render and inference hot paths.

**Edge Cases:**
- High-frequency progress events -> logged at a level that can be filtered out.


### REQ-13: Terminal is an on-demand slide-over, not a resident panel
**User Story:** As a developer I want the terminal out of my way until I ask for it, so
the chat stream — which is already the CLI in developer mode — gets the room.

**Verified:** REAL REDUNDANCY. Two CLIs exist on two different channels. The chat input
routes `>cmd` and `/run cmd` to `terminal_input` (`components/chat-view.tsx:1379-1387`),
while the xterm panel sends `dev_cli` (`components/terminal/TerminalPanel.tsx:120`). The
workspace already lazy-loads a `TerminalWidget`
(`components/workspace/DeveloperWorkspace.tsx:17`) and already has a `FloatingPanel`
primitive (`:13`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL NOT render a resident terminal panel in the chat view.
- AC2: THE SYSTEM SHALL keep the terminal icon as the entry point.
- AC3: WHEN the icon is activated THEN THE SYSTEM SHALL open the terminal as a
  slide-over positioned so it never occludes the composer or the active card.
- AC4: WHEN the slide-over is dismissed THEN THE SYSTEM SHALL preserve terminal
  scrollback and session state for the next open.
- AC5: THE SYSTEM SHALL render `>cmd` / `/run` output as a Blueprint Matrix block in the
  chat stream.
- AC6: THE SYSTEM SHALL converge the two command channels so one path carries developer
  commands.

**Edge Cases:**
- Slide-over open on a narrow viewport -> takes full width rather than clipping.
- Long-running command while dismissed -> output continues and is visible on reopen.
- Raw pty output that is not task-shaped -> renders verbatim inside the block walls.

### REQ-14: Central action verb registry
**User Story:** As a maintainer I want one place that maps tools to verbs, so adding a
tool does not mean editing the GUI and the CLI separately.

**Verified:** REAL GAP. 52 tools are registered in `backend/agent/tool_registry.py`
(the spec previously said 51 — corrected 2026-08-19 by counting `get_all_specs()`). The
demo parser `temp/task-card-redesign/actionParser.ts:15-60` maps roughly 15 of them and
omits whole families (git 7, github 8, vision 6, gui 5, media 4). Anything unmapped falls
through to a raw tool name.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define tool-to-verb mapping in ONE registry consumed by both the
  GUI card and the CLI renderer.
- AC2: THE SYSTEM SHALL express each verb in at most SIX characters as a real word —
  never an acronym, never a truncation with an ellipsis.
- AC3: THE SYSTEM SHALL render verbs in a fixed-width column so targets align in both
  surfaces.
- AC4: THE SYSTEM SHALL assign every registered tool a verb, covering the io, exec, vcs,
  forge, web, vision, gui, media, memory and dialog families.
- AC5: WHEN a tool is not in the registry THEN THE SYSTEM SHALL fall back to its family
  verb, and failing that to the raw tool name — never to a blank cell.
- AC6: THE SYSTEM SHALL allow a verb to be added, changed or removed by editing the
  registry alone, with no change to any card or renderer.
- AC7: THE SYSTEM SHALL size verb type for legibility rather than shrinking it to fit;
  the fixed column exists precisely so no verb ever needs shrinking.

**Edge Cases:**
- A tool registered at runtime the registry has never seen -> family fallback.
- Two tools sharing a verb -> allowed; the target disambiguates.
- A proposed verb longer than six characters -> rejected by a test, not silently clipped.

### REQ-15: Central memory event registry
**User Story:** As a maintainer I want one place that defines what memory activity the
card shows, so the planned recall upgrade extends it instead of rewriting the card.

**Verified:** NEW, and forward-looking by explicit instruction. `task:learning` is the
only memory signal reaching the frontend today. The planned Wormhole work
(`docs/Wormhole-resonant-recall-.md` Section 9) requires the recall surface be rendered
"directly from the node schema every time, so the agent learns to recognize a stable
shape rather than parse variable prose" — fixed fields, fixed order: `hex_bin_id`,
`tier` (hash | walk), `hyperedge_posterior`, `last_activated`. A registry is what lets
those arrive as entries rather than as a card rewrite.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define every memory event kind it can display in ONE registry,
  each entry carrying its label, glyph and value formatter.
- AC2: THE SYSTEM SHALL render the card footer and the header memory slot exclusively
  from that registry.
- AC3: THE SYSTEM SHALL allow a memory event kind to be added or removed by editing the
  registry alone, with no change to any card or renderer.
- AC4: THE SYSTEM SHALL render each entry in fixed fields in a fixed order, so the shape
  is stable across events of the same kind.
- AC5: WHEN an event arrives whose kind is not registered THEN THE SYSTEM SHALL ignore it
  and log once, and SHALL NOT render a partial or malformed entry.
- AC6: THE SYSTEM SHALL accommodate the planned recall vocabulary — tier, posterior,
  bin/region identity, resonance and landmark elevation — as registry entries, WITHOUT
  implementing any recall mechanics in this feature.

**Edge Cases:**
- Registry entry missing a formatter -> renders its raw value, never a crash.
- Two events of one kind in quick succession -> latest shows, earlier stays in the trace.
- Wormhole work adds fields to an existing kind -> additive, no card change.


### REQ-16: The permission gate is actually reached
**User Story:** As a user I want the agent to honour the permissions I configured, so it
asks before doing something consequential instead of silently proceeding.

**Verified:** REAL DEFECT, ROOT-CAUSED. The permission system is NOT unwired — the whole
chain exists and is correct:
`tool_bridge.py:1168-1200` (Phase 4 check) -> `permissions.request_permission` (`:249`)
-> emits `PERMISSION_REQUEST` (`:299`) -> bridged (`ws_event_bridge.py:45`) ->
`useIRISWebSocket.ts:1504` -> `PermissionCard` rendered (`chat-view.tsx:3411`) ->
`notification_response` -> `respond_to_permission` (`iris_gateway.py:5375-5387`).

It never fires because of the GATE, not the plumbing:
  - `CapabilitySet.get_mode()` (`backend/capabilities.py:66-73`) reads
    `cfg.get("mode", "personal")` and **`data/iris_config.json` has NO `mode` key**, so
    every call returns `"personal"`.
  - In personal mode `get_permission_action` (`permissions.py:217-221`) AUTO-APPROVES
    everything except `DESTRUCTIVE`.
  - `_DESTRUCTIVE_TOOLS` (`:129-138`) is 8 names, and only ONE of them (`delete_file`)
    is in the 51-tool runtime registry.
So in practice exactly one tool can ever prompt, and the user correctly reports never
being asked. Developer mode would gate every `SIDE_EFFECT` tool (`:223-228`) — but the
backend never learns the user is in developer mode.
  - The mode IS persistable: `main.py:1070-1083` validates and writes `cfg["mode"]`. It
    is the launcher's mode-select that feeds it — and the launcher's own launch config
    was broken until 2026-08-18, so the selection may never have reached the backend.

**INCOMPLETE — CORRECTED 2026-08-19 (session 239). Read REQ-18 before implementing this.**
The analysis above is accurate but names only ONE of the mechanisms suppressing the gate.
The `[13.3]` capability gate hard-denies the 23 repo/terminal tools BEFORE Phase 4 is
reached, and `delete_file` — named above as the one tool that could prompt — is inside
that blocked set. So the prompt is not rare, it is unreachable. Fixing the `mode` binding
alone does not make the user's symptom go away. Two further silent-permissive paths were
also found: `permission_level_from_config()` (`permissions.py:189`) returns `"developer"`
unconditionally and has no caller while the live gate uses `get_mode()`, and the Phase 4
block fails OPEN on any exception. See REQ-18 and pins `pin_956fe7e576b3`,
`pin_6c7b5a8ef4b2`.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL make the backend's effective permission mode reflect the mode the
  user actually selected.
- AC2: THE SYSTEM SHALL surface the effective mode so the user can see which policy is in
  force without reading a config file.
- AC3: WHEN no mode has ever been selected THEN THE SYSTEM SHALL NOT silently assume the
  most permissive policy.
- AC4: WHILE the effective mode is developer THE SYSTEM SHALL require approval for
  `SIDE_EFFECT` tools, per the existing matrix — no new policy is invented here.
- AC5: THE SYSTEM SHALL log the effective mode and the resolved action for every gated
  tool call, so "why was I not asked" is answerable from the logs.

**Edge Cases:**
- Config unreadable -> fail CLOSED to the more restrictive policy, not to personal.
- Mode changed mid-session -> the next tool call uses the new policy.
- A tool absent from all three tier sets -> classified conservatively, not as READ_ONLY.

### REQ-17: Permission enforcement is proven, not assumed
**User Story:** As a user I want evidence the permission gate works, so I am not relying
on a subsystem that has never once been observed doing its job.

**Verified:** NEW. No test asserts a tool call is ever gated. This is the same failure
class as the unified-vision-routing feature, which was fully built, fully unit-tested and
completely unreachable in production — caught only by a behavioral test that asked
"is this reached from a real path?".

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL have a test proving a gated tool call emits `PERMISSION_REQUEST`
  and blocks until answered.
- AC2: THE SYSTEM SHALL have a test proving denial actually prevents execution, not just
  records a denial.
- AC3: THE SYSTEM SHALL have a test proving the effective mode is derived from the user's
  selection rather than the fallback default.
- AC4: THE SYSTEM SHALL have a test proving the card's approve and deny actions reach
  `respond_to_permission` — the same click-path guarantee REQ-6 makes for questions.
- AC5: THE SYSTEM SHALL have a test asserting the destructive tool set covers the
  destructive tools that actually exist in the runtime registry.

**Edge Cases:**
- Permission times out -> treated as denied, execution does not proceed.
- Two approvals race -> first wins, second is a no-op.
- Card dismissed without answering -> request remains pending until timeout, never
  auto-approves.

### REQ-18: A capability-blocked tool asks instead of silently failing
**User Story:** As a user I want to be asked before the agent writes a file or runs a
command, so that a tool I did not pre-approve is a decision I get to make rather than an
error I never see.

**Verified:** REAL DEFECT, ROOT-CAUSED 2026-08-19 (session 239). This is the cause REQ-16
missed. `CapabilitySet.is_tool_allowed()` (`backend/capabilities.py:104`) returns false in
personal mode for `_REPO_TOOLS ∪ _TERMINAL_TOOLS` — 23 tools including `write_file`,
`delete_file`, `run_command` and every `git_*` / `github_*`. The `[13.3]` gate
(`tool_bridge.py:1108-1116`) acts on that by RETURNING AN ERROR:
```
if not CapabilitySet.is_tool_allowed(tool_name):
    return {"error": f"Tool '{tool_name}' is not available in {mode} mode",
            "success": False}
```
It runs at Phase 2 — BEFORE the Phase 4 permission check at `:1168`. So:
  - the 23 repo/terminal tools are hard-denied and never reach the permission gate;
  - every remaining tool is `READ_ONLY` or `SIDE_EFFECT` and AUTO-APPROVES in personal;
  - `delete_file`, the only registry tool classified `DESTRUCTIVE` and therefore the only
    one REQ-16 expected could prompt, is itself in `_REPO_TOOLS` and dies at `[13.3]`.
**Net: with no `mode` key the permission prompt is UNREACHABLE for every tool.** Two
independent mechanisms each suppress it, so REQ-16's fix alone leaves the symptom intact.
Confirmed against the live `data/iris_config.json`, which still has no `mode` key.

**Acceptance Criteria:**
- AC1: WHEN a tool is capability-blocked in personal mode THEN THE SYSTEM SHALL request
  permission rather than return an error.
- AC2: WHEN that request is approved THEN THE SYSTEM SHALL execute the tool.
- AC3: WHEN that request is denied or times out THEN THE SYSTEM SHALL NOT execute the
  tool, and SHALL return the existing denial shape
  (`{"success": False, "error": ...}`) so the agent can reason about the refusal.
- AC4: THE SYSTEM SHALL NOT change behaviour in developer mode, where `is_tool_allowed`
  already permits everything.
- AC5: THE SYSTEM SHALL keep the internet/desktop capability gate
  (`capability_allowed(spec)`) unchanged — it denies for a different reason and is not
  a permission question.
- AC6: THE SYSTEM SHALL NOT allow an error inside the permission gate to result in
  execution. The current bare `except Exception` logs "allowing tool to proceed" and
  permits; it SHALL fail closed.

**Edge Cases:**
- Gate ordering — a test SHALL assert the escalation happens BEFORE any terminating
  return, not merely that Phase 4 can emit. A test that only proves Phase 4 works stays
  green while `[13.3]` keeps the prompt unreachable in production.
- A tool blocked by BOTH capability and internet/desktop gates -> the non-permission
  denial wins; do not prompt for something that would fail anyway.
- Param-pattern escalation (`_DESTRUCTIVE_PARAM_PATTERNS`) SHALL be re-proven on a tool
  that actually clears `[13.3]` — the existing baseline proves it on `write_file`, which
  does not.

### REQ-19: A standing, user-managed approved-tools list
**User Story:** As a user I want to curate which tools are pre-approved and have that
choice persist, so the agent asks about what I care about instead of asking about
everything until I turn the gate off.

**Verified:** NEW. User-resolved 2026-08-19. There is no such surface today; permissions
are decided entirely per-invocation by the tier matrix.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL classify every gated tool as ALWAYS_ASK, SESSION_APPROVABLE or
  UNGATED, derived from the existing tier constants rather than a new hardcoded list, so
  the classes cannot drift from the tier sets.
- AC2: WHEN a SESSION_APPROVABLE tool is approved THEN THE SYSTEM SHALL NOT ask again for
  that tool for the remainder of the session, and SHALL discard that approval on restart.
- AC3: THE SYSTEM SHALL let the user maintain a standing list of approved tools that
  applies to every session, editable as toggles in the UI.
- AC4: THE SYSTEM SHALL refuse to honour an ALWAYS_ASK tool on the standing list, INCLUDING
  when the config file has been hand-edited to add one. The list is re-validated on read,
  never trusted as stored.
- AC5: THE SYSTEM SHALL display ALWAYS_ASK tools in the UI as locked, with the reason,
  rather than hiding them.
- AC6: WHILE the config is unreadable THE SYSTEM SHALL behave as though the standing list
  is empty and still prompt — never as though everything is approved.
- AC7: THE SYSTEM SHALL apply precedence: ALWAYS_ASK beats the standing list, which beats
  a session approval, which beats prompting.
- AC8: THE SYSTEM SHALL prompt for an ALWAYS_ASK tool on EVERY invocation. Approving one
  call SHALL NOT suppress the prompt on the next, in the same session or any other. No
  setting, standing-list entry or session approval SHALL be capable of suppressing it.

**Edge Cases:**
- A tool on the standing list that no longer exists in the registry -> ignored, and
  surfaced as stale rather than silently dropped.
- The standing list edited mid-session -> the next tool call uses the new list.
- A tool that moves between tier sets in a later release -> the classes are derived, so it
  moves class automatically; a test SHALL assert the derivation, not the membership.

### REQ-20: The developer command surface explains itself
**User Story:** As a user I want to know what I can type and what will happen when I type
it, so the developer CLI is usable by someone who did not build it.

**Verified:** REAL DEFECT, ROOT-CAUSED 2026-08-19 (session 239). User report: "i like the
concept but the ux is terrible, dont know how to fully use it myself." The cause is not
styling. It is that TWO DIFFERENT EXECUTION SEMANTICS are presented through IDENTICAL,
UNLABELLED affordances, and nothing anywhere tells the user which is which.

THE TWO CHANNELS ARE NOT DUPLICATES — THEY DO DIFFERENT THINGS:
  - `terminal_input` (`iris_gateway.py:831` -> `_handle_terminal_input`) runs the line as
    DIRECT SHELL INPUT. No LLM involved.
    Reached from: chat input with a `>` or `/run ` prefix (`chat-view.tsx:1379`), and from
    `TerminalWidget` (`:106`).
  - `dev_cli` (`iris_gateway.py:823` -> `_handle_dev_cli`) routes the line to the
    DevOrchestrator, which uses an LLM to pick one of the registered CLI tools and drives
    it through the agent kernel DER loop.
    Reached from: `TerminalPanel` (`:122`).
So `>ls` typed in chat runs a shell command, while `ls` typed in the terminal panel invokes
an orchestrator that chooses a tool for you. Same-looking box, same-looking prompt,
completely different behaviour, no label on either.

WORSE, THE TWO TERMINAL COMPONENTS DISAGREE WITH EACH OTHER: `TerminalWidget` sends
`terminal_input` (shell) and `TerminalPanel` sends `dev_cli` (orchestrated), and
`DeveloperWorkspace` mounts `TerminalWidget`. Which semantic a user gets depends on which
component happens to be mounted.

WHAT THE USER ACTUALLY SEES TODAY: a chat placeholder reading "Type command or drop
file..." (never mentions `>` or `/run `), and a terminal banner reading "Routes through
agent kernel DER loop" — an implementation detail, not an instruction. There is NO help
text, NO command list, NO autocomplete, NO hint, on any surface.

THE HELP CONTENT ALREADY EXISTS AND IS NEVER SHOWN: `backend/dev/cli_tools.yaml` +
`backend/dev/cli_registry.py` register three tools (`kilo_code`, `claude_code`,
`opencode`), each carrying `display_name` AND a `when_to_use` string. That metadata is fed
only to the DevOrchestrator's own LLM prompt. The human is told nothing.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL NOT converge `terminal_input` and `dev_cli` into one channel. They
  are distinct capabilities and collapsing them destroys one. (This CORRECTS T13b as
  originally written — see tasks.md.)
- AC2: THE SYSTEM SHALL name the two modes in the UI in user-facing language — SHELL (runs
  literally) and DELEGATE (hands the request to the dev orchestrator) — never
  `terminal_input` / `dev_cli`, and never "DER loop".
- AC3: THE SYSTEM SHALL show which mode is active BEFORE the user commits, and SHALL label
  every rendered output block with the mode that produced it, so scrollback stays readable.
- AC4: THE SYSTEM SHALL make the two terminal components agree — one semantic per
  component, explicitly chosen, with the mounted component's mode visible.
- AC5: THE SYSTEM SHALL surface the CLI tool registry to the user, including each tool's
  `when_to_use`, from the existing `cli_tools.yaml` — not a second hardcoded copy.
- AC6: THE SYSTEM SHALL provide an in-app command reference reachable without leaving the
  surface (a `/help` command and a persistent affordance), listing the prefixes, what each
  does, and the available tools.
- AC7: THE SYSTEM SHALL replace implementation-detail text in the empty state and
  placeholder with text that states what the user can type.

**Edge Cases:**
- Registry unreadable -> help still renders the prefixes it knows statically; it never
  shows an empty help panel.
- A tool listed in the registry but not installed -> shown as unavailable with the reason,
  not hidden (the same rule REQ-19 AC5 applies to locked tools).
- `/help` typed in either surface -> answered locally, never sent to the agent as a task.
- Mode indicator must not occupy space the composer needs on a narrow window; it collapses
  to the mode glyph, never disappears.

## Non-Requirements (Out of Scope)
- The `@card:<id>` tagging UX, cross-thread card referencing, and subagent/swarm
  card-to-card messaging (Decisions Locked 6 — a later spec builds on REQ-11).
- Blueprint Matrix as chrome for the whole developer terminal; banner, prompt and shell
  behaviour are untouched (Decisions Locked 5).
- Porting `app/task-preview` demo scaffolding into production (Decisions Locked 8).
- The Flow Pipeline CLI variant and the seven non-selected GUI variants.
- Changing what the agent does — this feature changes how execution is represented.
- Implementing resonant recall, wormholes, hex binning, landmark elevation or the
  Beta-Bernoulli scorecards (`docs/Wormhole-resonant-recall-.md`, `specs/node-chains`).
  REQ-15 builds the SEAM those land in; it does not build them.
- Reworking the terminal's xterm input handling beyond what REQ-7 requires.

## Open Questions
- The developer terminal renders typed input invisibly. `TerminalPanel.tsx:135-138`
  echoes correctly and the theme foreground is `#e2e8f0`, so the likely cause is
  `background: 'transparent'` with `allowTransparency: true` (`:70-92`) compositing
  against the panel. This is a real defect but a DIFFERENT one from this feature — it
  needs a live diagnosis before it can be specced. Confirm whether it is folded in or
  tracked separately.
- Should a rehydrated card be replayable (re-emitting its events) or is a static
  restoration sufficient? AC5 of REQ-4 assumes static.
