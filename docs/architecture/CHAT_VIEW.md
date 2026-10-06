# Chat view — the turn protocol and the split (execution audit Phase 3)

Status: built 2026-10-06 on `feat/agent-multi-step-tool-execution-20260915`
(commits "feat(turns)…", "feat(chat): live turns render…", "refactor(chat): move …").
Line numbers drift; search by name. Related: `docs/audits/2026-09-29/execution-audit.html`
(Phase 3/4 spec), `docs/audits/2026-09-29/reply-surface.html` (Phases B–D),
`docs/design/chatview-2026-10-06/` (the owner-approved look, concept 2 rev 3),
`docs/architecture/TASK_CARD.md`, `docs/architecture/DER_DAG.md`,
`docs/audits/2026-09-29/PROGRESS.md` (Standards S66, S67).

---

## 0. The idea in plain words

Before: one reply reached the chat in three envelope types (`chat_chunk`, `chat_message`,
`text_response`) plus loose task / tool / card events, and one 5,600-line component guessed
which envelopes belonged together by matching turn ids as strings. When a guess failed, a
card landed in the "orphan" pile or a reply landed in the wrong thread.

Now: the backend puts every turn in **one numbered folder**. It opens the folder
(`turn.start`), adds numbered pages (`turn.part`, seq 1, 2, 3 …) and closes it exactly once
(`turn.end`: ok, error or cancelled). A small **store** files each folder under the
conversation written on it. Small **views** draw what the store holds; none of them guesses.

```mermaid
flowchart LR
  subgraph Backend
    GW[iris_gateway<br/>text + voice paths] -->|TurnEmitter| W((WS))
    BUS[EventBus] --> BR[WSEventBridge] -->|route_bus_event| W
  end
  W --> HOOK[useIRISWebSocket<br/>turn.* -> applyTurnMessage]
  HOOK --> ST[(turnStore<br/>by turn, filed by<br/>event conversation)]
  ST --> SHELL[ChatWing = shell<br/>chat-view.tsx]
  SHELL --> HDR[ChatHeader · NotificationsPanel · HistoryPanel]
  SHELL --> TL[Timeline]
  TL --> TV[TurnView per message]
  TL --> TCE[TaskCardEntry per card]
  TV --> PV[TurnParts = PartView<br/>reasoning · notice · error · stopped]
  SHELL --> CMP[Composer]
```

## 1. The turn protocol (backend)

**Module:** `backend/agent/turn_protocol.py`. `SCHEMA` is the single source of truth; the
TypeScript types in `lib/turns/protocol.ts` are **generated** by
`python scripts/gen_turn_protocol_ts.py` (`--check` fails when stale; the contract test runs it).

Wire envelope: `{"type": "turn.start" | "turn.part" | "turn.end", "payload": {…}}`.

| Message | Payload | Guarantee |
|---|---|---|
| `turn.start` | `turn_id, conversation_id, strand_id, author, to[], refs[], mode, prompt, client_ref?, ts, v` | once, before any part (a part or an end before start sends start first) |
| `turn.part` | `turn_id, conversation_id, seq, ts, v, part{type, …}` | seq 1..N dense even with many threads emitting; after end: dropped and counted |
| `turn.end` | `turn_id, conversation_id, status, parts (=N), text (final, authoritative), speak, error?, ts, v` | exactly once on every path |

**Part types:** `text` / `reasoning` (deltas), `tool_call`, `tool_result` (`ok`), `todo`
(task-card lifecycle: task:start/progress/milestone/done/fail/paused/resumed, memory:event,
task:learning), `card` (document:render), `interaction` (permission / question / browser
takeover), `notice` (plan:validation_failed, budget, recovery, vision unavailable,
steering ack), `error` (`code, message, recoverable`). Add LABELS freely; a new part TYPE is
a schema change (re-generate the TS, update the store and its views).

**Producers:**

- `TurnEmitter(send, turn_id, conversation_id, …)` — thread-safe; `send` must be thread-safe
  (the gateway passes one that schedules the WS send on the main loop and buffers for the
  reconnect replay on failure). Used as a guard: an exception → `error` part + `end("error")`;
  `CancelledError` → `end("cancelled")`; a body that forgets to end → `end("ok")` + a warning.
- Gateway **text path** (`_handle_chat`, `text_message`): opens the turn right after
  validation with the kernel's `turn_id`; chunk and reasoning callbacks feed `text` /
  `reasoning`; `turn.end` follows the final `chat_message` with the full response and the
  spoken line; the error branch adds an `error` part; a `finally` guard closes a turn that
  left without an end.
- Gateway **voice path** (`_process_voice_transcription`): same, with one `turn_id` minted
  before the kernel call and shared by the kernel, `tts_started` and the assistant
  `text_response`. A transcript that answers a question card is not a turn.
- **Event bridge** (`ws_event_bridge`): after its card-free-turn gate, every bridged bus
  event also goes through `route_bus_event`, which files it into the live turn (by `turn_id`,
  else the conversation's live turn) as the matching part. A withheld card stays withheld.

**Recording real turns:** `IRIS_TURN_RECORD_DIR=<dir>` writes each turn's messages to
`<dir>/<turn_id>.jsonl` on the `turn_record` lane (never on the reply path). Convert one into
a replay fixture with `python scripts/gen_turn_replay_fixtures.py --from-jsonl <file> <name>`.

**Migration:** the legacy messages (`chat_chunk`, `chat_message`, `text_response`, the bridged
`task:*` / `tool:*` / `document:render` …) still go out. The chat view stopped reading
`chat_chunk`; the rest are retired view by view (Phase 4 matrix, reply-surface Phase B cards
and receipts), then removed from the backend in one change.

## 2. The turn store (frontend)

**Module:** `lib/turns/turnStore.ts` — module-level store (same lifetime pattern as
`useTaskProgress`, REQ-38), read with `useSyncExternalStore`
(`useConversationTurns(conversationId)`, `useTurn(turnId)`); pure reducer
`reduceTurnMessage` for tests and replay.

Filing rules (each one closes an audit bug):

1. A turn is filed under the `conversation_id` its **event** names — never the conversation
   on screen.
2. Parts are ordered by `seq`; a replayed seq (reconnect buffer) is ignored; a delta that
   arrives late, even after the end, lands in place.
3. Exactly one end: a second / replayed end changes nothing.
4. `turn.end.text`, when present, replaces the streamed deltas (a JSON envelope streamed
   nothing; a DER reply streamed all at once).
5. A part numbered past the end's count is dropped and counted (`dropped`); a malformed
   message is counted, never thrown.
6. Bounded: `MAX_TURNS` (oldest ENDED turns evicted, never a running one),
   `MAX_PARTS_PER_TURN`.

`lib/turns/mergeTurns.ts` places live turns in the message list: a turn without its final
message yet (streaming, error, cancelled) becomes a placeholder whose id **is** the turn id —
the existing anchor rule (assistant message id === turn_id) — right under the prompt it
answers (`turn.start.client_ref` = the user message id the composer sent).

## 3. The split

| File | Role | Notes |
|---|---|---|
| `components/chat-view.tsx` (`ChatWing`) | **Shell**: conversations state, WS listeners that remain, send / resend / retry, wing geometry and frame, wiring of the children | the only component with app state |
| `components/chat/ChatHeader.tsx` | header bar (pulse, title, dashboard, detach, launcher, spotlight aperture, alerts, history, close) | pure view, props only |
| `components/chat/NotificationsPanel.tsx` · `HistoryPanel.tsx` | the two dropdowns | HistoryPanel is replaced by the thread orbit in the approved design |
| `components/chat/Timeline.tsx` | the one scroll area: pin-to-bottom, empty state, entries, orphan docs, typing, inline permission / question fallbacks | |
| `components/chat/TurnView.tsx` | one message entry (user or assistant), its inline cards and its `TurnParts` | the place Phase 4 swaps in the matrix for developer mode |
| `components/chat/TaskCardEntry.tsx` | one task-card entry (developer: Blueprint matrix string; personal: `TaskListCard`) | the one `<TaskListCard` render site |
| `components/chat/turn/TurnParts.tsx` | **PartView**: reasoning line (THK in developer mode), notices, errors (+Retry), "Stopped" | draws events that had no listener |
| `components/chat/Composer.tsx` | the input area (pills, menus, toolbar) | |

The moves were pure: the moved JSX is line-for-line identical to the old code (compared
whitespace-insensitively). Guards that pinned code to `chat-view.tsx` read the shell plus its
timeline files as one source since the split (owner-approved 2026-10-06; assertions
unchanged): `__tests__/components/chat-view-surface.contract.test.ts`,
`backend/tests/contract/test_one_task_card_render_site.py`. New files in `components/chat/`
are triaged in the CT-10 guard (`cardChassis.coverage.test.tsx`, `NON_CARD_ALLOWLIST`).

## 4. Bugs this closed (execution audit, frontend list)

| Bug | Fix |
|---|---|
| card-anchor early return (card fell to the orphan pile) | the rendered-as-document branch no longer marks the turn as seen before the anchor exists |
| 500-char clamp + remount while a reply streams | a running turn is never truncated |
| chunk / text / plan events written to the ACTIVE conversation | no chunk handler; streaming renders from the store; the final message goes to the turn's conversation |
| suggestion pills sent without conversation_id / typing / dev routing | pills take the one send path; a pill never wipes a draft |
| retry fetch inside a state updater + stray "Retrying…" | retry = resend of the prompt above the error (pure updater, fetch outside) |
| backend errors and live reasoning had no listener | `error` / `reasoning` parts render in their turn; the legacy error message is skipped when the turn shows it |
| frontend copy of the failed-search rule | removed (one trigger for cards: `create_artifact`) |
| voice path: `_sttproc_stop` read in `finally` before assignment | bound before the `try` |

## 5. Tests and guards

- `backend/tests/contract/test_turn_protocol_contract.py` (32): framing on every path, seq
  density (8 threads × 200 parts), parts after end, bus routing per event family, other
  conversations never leak in, generated TS current, both producers wired (the wiring guards
  failed on the old code).
- `__tests__/turns/turnStore.test.ts` (13): replays of emitter-produced fixtures + the filing
  rules.
- `__tests__/turns/turnView.replay.test.tsx` (12): each fixture replayed and rendered in
  **personal and developer** mode — error visible with Retry, recovered error, cancelled,
  reasoning only while running; timeline placement.
- Fixtures: `__tests__/fixtures/turns/*.json` from `scripts/gen_turn_replay_fixtures.py`
  (scripted through the real emitter; replace with `IRIS_TURN_RECORD_DIR` recordings).

## 6. How the approved design maps onto this (Phase 4 and reply-surface B–D)

The owner approved concept 2 rev 3 (`docs/design/chatview-2026-10-06/iris-strands.html`).
Where each piece lands:

| Approved piece | Lands in | Data |
|---|---|---|
| live matrix (rows born / running / fold; "looked closer" chambers; parallel light) | `TurnView` developer branch → `components/chat/matrix/*` | `todo` / `tool_call` / `tool_result` parts + `useTaskProgress` rows |
| the spine (Xur trail, agent rides to the running step, knots, chips on the spine) | `Timeline` (one canvas overlay per scroll area) | turn status + running-row positions; knots from `refs` / foreign authors / helper strands |
| vertical personal task card (every event, plain words) | `TaskCardEntry` personal branch (`TaskListCard`) | unchanged store; spine bends into its step line |
| permission / question receipts in the turn | `TurnParts` (`interaction` parts) | reply-surface Phase B |
| `±` diffs + review lens | `TurnView` + a lens in the shell | tool results of edit tools (needs the diff in the part data) |
| thread orbit, strand map, edge light + aperture | `ChatHeader` (+ dashboard header) | strands need the conversation-store fields below |
| `to:` / `#refs` composer, project bar, steer / stop | `Composer` | `turn.start.to` / `refs` already exist |

**Strands** (owner, 2026-10-06): a thread is the whole; each chat under it is a strand
(user-named, preset tags + own tags); all strands of a thread share one memory; helpers get
their own strand and report back. The protocol already carries `strand_id`, `author`, `to`,
`refs`; the conversation store still needs `parent_id`, `kind`/tags, `project_id` (not built).

## 7. Phase 4 — the live execution matrix (built 2026-10-06)

The developer turn is now three parts: the **prompt line** (`❯ text`, 12.5 px mono, no
"You" header), the **live matrix**, and the **answer** rendered as markdown in the mono
family (`MarkdownMessage variant="cli"` → `.iris-md.iris-md-cli`; it used to print raw text
with literal `**` and fences). Personal mode is unchanged (NOT THIS).

| File | Role |
|---|---|
| `components/chat/matrix/matrixModel.ts` | pure model: rows from `TaskCardProps`, split children (`<parent>_s<n>`) grouped into a chamber after their parent, plain-word fold line (DONE / FAILED / STOPPED), memory line without learning/crystallize events |
| `components/chat/matrix/LiveMatrix.tsx` | `MatrixFrame` (header TASK · n/m · time · fold, THK line, rail, memory line), `MatrixRow` (orb · verb · target · chip · chevron), `SubLoopChamber` ("↳ looked closer", folds to "· found it"), `RowDetail` (recent actions, preview, page) |
| `components/chat/matrix/ShellRunEntry.tsx` | a developer `>cmd`: prompt line + one-node matrix with an EXEC row that opens to its output (does not fold: the output is the point) |
| `lib/cli/shellRuns.ts` | groups the terminal scrollback into runs (command + output); `[exit N]` / `Terminal error:` / `^C aborted` = failed; the newest run is running until its output is quiet 2.5 s; runs are tagged with the conversation they were typed in |
| `components/chat/TaskCardEntry.tsx` | developer branch renders `MatrixFrame` (was a 9 px ANSI `<pre>` that scrolled sideways) |

Motion (approved concept 2): rows are born (`iris-mx-born`), the running row scans
(`iris-mx-scan`), its orb breathes, the agent's Xur rides the rail to the running row(s)
(faster when several run in parallel), a finished run folds to one line, a failed row opens
its output by default. All of it stops under `prefers-reduced-motion`. The CSS lives in
`css-src/globals.css` AND the served `public/globals.css` (the app loads the compiled file;
`app/globals.css` is not loaded) — new arbitrary Tailwind classes must exist in
`public/globals.css` or be inline styles (no Tailwind CLI in the cloud container).

Parity: the GUI matrix and the ANSI export (`renderBlueprintCellMatrixCLI`, kept for terminal
export and logs) render from the same `taskCardToMatrixProps`; a test asserts the same rows,
order and verbs. Guards: `__tests__/matrix/liveMatrix.test.tsx` (15; the TaskCardEntry guard
fails on the old `<pre>`).

Not yet (the approved design, next steps): the timeline-wide spine (the Xur trail down the
whole strand, knots, chips on the spine), the personal-mode spine through the vertical card,
`±` diff icons + review lens, MADE / ASK / permission rows (reply-surface Phase D),
parallel-row light lines.

## 8. Open

- Retire the legacy couriers (after Phase 4 and reply-surface B read parts only).
- `turn.part` `interaction` / `card` / `todo` parts are filed but still drawn by their old
  views.
- Strands in the conversation store; the thread list lag (it downloads every thread with every
  message on each open — `openHistory()` → `fetchConversations()`).
- Live gate on the owner's machine (a real text turn, a voice turn, an error turn; record
  them with `IRIS_TURN_RECORD_DIR` and add them as fixtures).

## 9. The living spine (built 2026-10-06)

One canvas overlay per timeline (`components/chat/spine/Spine.tsx`, pure model in
`spineModel.ts`, gutter in `SpineGutter.tsx`), mounted by `Timeline` as a sibling of the scroll
area (`pointer-events: none`; it never scrolls the content). Look: `iris-strands.html`
(`measure`, `xAt`, `drawSpine`, `showChips`). The DOM is measured on change (observers,
coalesced to one pass per 80 ms), never per frame; a frame reads `scrollTop` and draws only the
visible range. The rAF loop stops while the page is hidden. Under `prefers-reduced-motion` one
static frame is drawn on demand (scroll, new measurement); nothing animates.

**Where the agent Xur rides** (there is ONE agent Xur; the matrix rail has none):

| Mode | Target | Marker the spine reads |
|---|---|---|
| developer | the matrix row(s) that run | `[data-state="running"]` (`LiveMatrix.tsx`) |
| personal | the task card's running step dot; the spine bends into each card's step line | `[data-task-step="working"]` inside `[data-task-steps]` (`TaskListCard.tsx`; the value is the displayed step status) |
| either, no row runs | the streaming reply (`#msg-<running turn id>`), else the newest entry while a turn runs | turn store `status === "running"` |

Several running rows: a wider loop and a faint light line to each row.

**Knot data contract.** A knot is a small Xur loop on the spine ONLY where something entered
from outside this strand. Landmarks are never knots. Two sources:

1. A DOM entry carries `data-knot="<kind>"`. `kind` is `ref` (pulled in from another strand,
   a task card or an artifact), `author` (another author: a person or another agent) or
   `helper` (a helper strand reporting back); an unknown kind is drawn as `ref`. Put it on the
   entry's outer element; the knot sits at the entry's top. Nothing sets `author` / `helper`
   from data yet; a view that gets that data adds the attribute.
2. `Timeline` derives knots from the turn store (`turnKnots`): a turn with non-empty `refs`
   (`ref`), or an `author` other than `user` / `iris` (`author`). The knot sits on the user's
   prompt (`turn.start.client_ref`), else on the turn's own message.

**Chips on the spine.** The conversation chips (`ConversationChips`, composer footer) moved to
the gutter, the left 30 px of the timeline: hover (or keyboard focus) lists the turns, the
turns in view are highlighted, a knot shows "from outside", click calls `handleChipClick`
(scroll to the turn), a drag on the gutter scrubs the scroll. `Composer` no longer takes
`conversationChips`, `handleChipClick` or `messagesContainerRef`. `ConversationChips.tsx` is
no longer rendered (kept in the CT-10 allowlist).

Guards: `__tests__/spine/spineModel.test.ts` (detour math, knot rules, chips in view, scrub),
`__tests__/spine/spineGutter.test.tsx` (hover list, click, drag, canvas frame, reduced motion,
structure: no chips in the composer, no second Xur in the matrix).

## The composer (2026-10-06 design)

Both modes: a tray (`RefTray`: the `to @iris` chip, the picked `#` chips, a hint), the project bar
(`ProjectBar`), then the message box. Files: `components/chat/composer/{refs,ProjectBar}.tsx`.

- **Project bar.** Reads `workspaceStore` (the folder tab and the open file tabs) and adds through
  `FilePickerModal`. The old developer-only `WorkspaceTabBar` strip in `chat-view.tsx` is gone (the
  archive badge stays). No branch: the app knows the branch of its own repo (`/api/git/status`), not
  of the folder the user opened.
- **`to`.** Only `@iris` exists (no people yet); the payload carries `to: ["@iris"]`.
- **`#` refs.** Typing `#` opens a picker of ADDRESSES: this conversation's task cards, its
  artifacts, the strands of its thread (`fetchStrands`, loaded when the picker first opens). A pick
  becomes a removable chip; `text_message` carries `refs: ["#<id>", ...]`. The gateway adds them to
  `turn.start.refs`. Never content.
- **Steer.** A turn running in this conversation (turn store) or a working card: Enter sends
  `steer`, not a prompt. The timeline shows `↳ you steered: ... · noted` (developer) or
  `↳ you said: ... · IRIS noted it` (personal) as a `steer-note-` system message (`TurnView`).
- **Stop.** The one button is `↵` / `Send message` when idle and `■` / `Stop IRIS` while a turn
  runs. It sends `stop {conversation_id}`. `main.py` pushes it to the steering inbox (the DER loop
  winds down at its next step boundary) and cancels the text-turn task of that conversation
  (`cancel_turn_tasks`); the gateway ends the turn `cancelled`. Guard:
  `backend/tests/contract/test_stop_turn_contract.py`.
- **No mic button.** Voice stays wake-word.

Guards: `__tests__/composer/composer.test.tsx` (both modes, whole `ChatWing`).

## 10. In-turn interactions: ±, the lens, asks (built 2026-10-06)

Look: `iris-strands.html` (`.dfx`, `.lens`, diff review, `.receipt`). Tests: `__tests__/turnui/*`
(driven through the real `Timeline` from turn parts and card data shaped like the backend's).

| Piece | Where | Notes |
|---|---|---|
| `±` | `components/chat/diff/DiffMark.tsx` | on the matrix row of an editing step (developer), on the step of the personal card, and a summary chip under the reply (both, from the turn's `tool_result` parts). Data: `step.diffs` (`useTaskProgress` keeps `diff` / `diffs` of `tool:result`) |
| diff review | `components/chat/diff/DiffReview.tsx`, `lib/diffs/undoStore.ts` | per file, per hunk Keep / Undo, per file Undo all -> `sendDiffUndo`. A hunk is "undone" ONLY after `diff_undo_result` ok (the hook files it with `applyDiffUndoResult`); a refusal shows its reason; `undoable:false`, `new_file`, `truncated` each say so |
| lens | `components/chat/lens/*`, `lib/lens/lensStore.ts` | one overlay inside `Timeline`'s relative wrapper (over the timeline, inside the wing). Artifact opens by doc id and resolves live; Pop out = the full-wing `DocumentPanel` (`setExpandedDocId`); Esc / back close; a thread switch closes |
| artifact card | `ArtifactChip.tsx` | compact title + `kind · size/rows · time` (`DocRender.createdAt`, live cards only). A streaming (partial) doc and the live sources list stay inline |
| dashboard drop | `lib/lens/dragPayload.ts`, `lib/workspace/addLensItem.ts`, `DeveloperWorkspace` | the drag carries the payload (`application/x-iris-lens`, body capped at 200 KB); the Workspace Hub makes a document card (`WorkspaceTab.content` / `.diffs`). "To dashboard" in the lens uses the same path |
| asks | `lib/turns/asks.ts`, `components/chat/turn/AskPrompt.tsx` | folded from the turn's `interaction` parts. Matrix: an ASK row at the end of the rows; personal: inside the card (subheader, so a folded plan still shows it); no card: in the turn. Keys `y`/Enter allow, `n`/Esc deny when the ask has focus. Countdown only when the backend sent `timeout_seconds`. After the answer: a receipt line. Answers use the existing `notification_response` / `question_response`; the legacy card of an ask is hidden only when the turn really shows it |
| MADE row | `LiveMatrix.tsx` `MadeRow`, `matrix/madeRows.ts` | under the step that ran `create_artifact` / `show`, else last. GUI only: the ANSI export and the parity guard read steps |
| plain words | `lib/cards/plainWords.ts` | personal card: a split child says "looked closer" and "reported back" once done; engine words in labels / memory summaries are rewritten |

Open: `TaskListCard.display.test.tsx` pins the footer text "Crystallized" / "Learning signal: Crystallized"
for `learningSignal="crystallized"`; the plain-words rule wants "done". Left as the test has it (a test is
the requirement); decide which side moves.
