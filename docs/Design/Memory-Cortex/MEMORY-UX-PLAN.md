# Memory Cortex — the functional UX plan

Owner direction, 2026-10-21:

> "The cortex orb and timeline now are much closer to the vision… but when it comes to functionality and UX we are
> lacking on how the user would navigate the cortex to meaningful and useful [places], along with the timeline view.
> Only the Artifact view has a clear functional UX… 'How IRIS decides' to be renamed the Oracle… the XurOrb in the
> middle of those fibers looks terrible… use docs/architecture/oracle.md… make sure it is clear a user can navigate a
> thread to a strand from conversations.db from the chat view. Functionality with experience is the objective."

This plan keeps every visual decision already made (§18 language, the crystal / frost / spark / bracket shapes, the
corridor, the helix) and adds what is missing: a reason to go somewhere, a way to get there, and a way back.

---

## 1. Why the Artifact view works and the others do not

The Artifact view answers four questions at every moment, without being asked:

| Question | How Artifacts answers it |
|---|---|
| Where am I? | the cell you are in is the only thing at full size; a breadcrumb of formats › folders › item |
| What is this? | every cell IS its content (a thumbnail), and it says what kind it is |
| What can I do? | hover swells it (look), click opens it (use), Esc steps out (back) — the same three gestures at every level |
| What is next to it? | siblings stay around it, so the next step is visible before it is taken |

The cortex and the timeline answer only the first half of the first question. They show *that* there is a lot of
memory; they do not say *what* a thing is until you hover it, they do not suggest where to go, and they have no "use"
gesture at the end of the path — the Artifact view ends in a thing you open; the cortex ends in a card you read and then
nothing. **The fix is not more visuals. It is one interaction grammar, applied to every view, that always ends in an
action.**

## 2. Who uses this memory, and for what

The memory is used by two minds: the user's and IRIS's. The views must serve both directions.

| # | The user wants to… | Today | After this plan |
|---|---|---|---|
| J1 | know what IRIS knows about a topic, and how sure it is | dive into a territory, hover crystals one by one | search or territory → a ranked, labelled set of claims with their sureness and evidence in plain words |
| J2 | know **why IRIS answered that way** (what it remembered, what it decided) | not possible from chat | one click from a chat turn → the recall arches and Oracle decisions of that turn |
| J3 | find where something was discussed, and **continue it** | scroll the helix, hover beads | search or time → the strand's corridor at that turn → "continue in chat" |
| J4 | move from a **thread to its strands** and back, in both apps | strands drawn as forks, not enterable | thread braids on the helix; forks are doorways; chat ↔ memory deep links on both sides |
| J5 | see whether the memory is **healthy and trustworthy** | scattered signals (sync, rim gaps, desync) | a health reading (Kyudo) per territory and for the whole memory, with what was cleaned and why |
| J6 | **watch IRIS work** and understand it | sparks without meaning | a learnable grammar: inward = remembering, outward = recording, rays = deciding |
| J7 | **correct** IRIS's memory | not possible (read-only by spec) | v2, owner decision (§11): confirm / mark wrong / pin / forget, all as USER evidence through the backend |
| J8 | see **how IRIS is learning to decide** | iris of fibres + a XurOrb that does not belong | the Oracle view rebuilt on oracle.md: one question per run, the bar as a ladder, honest demotions |

## 3. One interaction grammar for every view

### 3.1 Five gestures, the same everywhere

| Gesture | Meaning | Cortex | Timeline | Corridor | Oracle | Artifacts |
|---|---|---|---|---|---|---|
| **hover** | identify (kind first, then the thing) | territory / crystal / pin / spark | thread braid / strand bead / recall arch | message / moment / claim | consumer sector / live ray | cell swells (as today) |
| **click** | focus (the thing becomes the subject; its card opens; its paths appear) | dive / focus a claim | focus a strand (arches bloom) | focus a moment / claim | focus a consumer (its ladder) | open the cell (as today) |
| **double-click / Enter** | go in | enter the territory / walk to the claim | enter the strand's corridor | follow the claim's thread | open its history | open the thing |
| **Esc / mouse back** | step out one level (never two) | out of claim → territory → cortex | out of focus → helix | corridor → its bead on the helix | consumer → ring | up one folder (as today) |
| **/** | search everywhere, from anywhere | — | — | — | — | — |

Rules that make the grammar trustworthy:
- **Esc always undoes exactly the last "go in" or "focus".** A back stack (§5.3) holds every step; the mouse's back button
  and Alt+← walk it too.
- **Hover never moves the camera. Click may. Enter always does.** The user is never surprised by motion they did not ask for.
- **Every focus card ends in paths** (§3.2). A card with nothing to do is a dead end, and dead ends are what the owner
  felt in the cortex.
- **The kind is said first, always** (already started: "claim · proven", "pin · …"). The key shapes are the icons.

### 3.2 Paths: every focused thing says where it leads

A focused object shows its *paths* as a short line of actions under its card, in the order the user most likely wants
them. Paths are the bridges between views; each one is an animated pivot (§6.1), never a cut.

| Focused | Paths (in this order) |
|---|---|
| **claim** | where it was learned → (corridor, at that moment) · every time it was used → (timeline, recall arches from this claim) · its linked claims → (walk the frost bridges) · ask IRIS about it → (chat, composer pre-filled with `#claim`) · [v2] confirm · mark wrong |
| **strand** (a conversation) | enter it → (corridor) · continue in chat → (chat view, this strand, last turn) · its thread → (the braid; siblings shown) · what memory gave it → (arches) |
| **turn / moment** | open in chat at this turn → · what memory gave this turn → (arches of the turn) · what IRIS decided here → (Oracle rays of the turn) · the claim it touched → (cortex) |
| **thread** | its strands → (fan the braid open) · open in chat → (thread root) · rename / pin (same as the chat header, same API) |
| **pin** | what it holds → (tether travel to the claim / node / artifact) · the strand it was pinned in → · [v2] unpin |
| **artifact** | (unchanged) open · the strand it was made in → (corridor at the MADE moment) |
| **Oracle consumer** | its recent decisions → · its bar ladder (which clause it waits for) · its history (earned → demoted) |
| **recall arch** | the earlier step it carried → (source corridor) · the step it was given to → (target corridor) |

### 3.3 The key becomes the legend AND the filter AND the help

The key (bottom right) already isolates a kind. It also:
- shows a count next to each kind in the current scope ("claims 48 · pins 0 · moments live");
- shows `?` at its foot: the full control sheet for the current view, drawn in the same thin-line HUD style (never a modal);
- on first open, three coach marks (hover · click · Esc), shown once, dismissible, stored per viewer.

## 4. The thread ↔ strand model, made clear in both apps

### 4.1 One vocabulary (today the two apps disagree)

| The app's chat says | conversations.db | memory.db | The memory views say today | They will say |
|---|---|---|---|---|
| **thread** | a conversation row with `parent_id IS NULL` | — (derived through `parent_id`) | — | **thread** |
| **strand** ("main" for the root) | any conversation row (a strand IS a conversation id) | `memory_events.thread_id` (= the conversation id; `caducean_session_exits.conversation_id` when they differ) | "session" | **strand** |
| **turn** | a message pair (`turn_id`) | `memory_events.episode_id` = `"<conversation>:<turn>"` | "turn" | **turn** |
| helper strand ("reports to") | `reports_to`, tag `swarm` | same thread_id rule | a fork | **helper strand**, drawn reporting back into its parent |

"Session" disappears from every label. It stays an internal word.

### 4.2 Contract first (backend, before any UI)

The memory views cannot be trusted to link to chat until every memory row says which strand and which turn it belongs
to. Contract (guard: `backend/tests/contract/test_memory_strand_ids_contract.py`, fails on the old state):
1. every `memory_events` row typed during a chat turn carries `thread_id = <conversation id>` and
   `episode_id = "<conversation id>:<turn id>"`;
2. `GET /api/memory/strands?thread=<root>` returns the strands of a thread with their memory activity (count of moments,
   recalls, claims touched, last activity) — one indexed read joining `conversations.parent_id` to `memory_events.thread_id`;
3. a strand that has no memory rows still appears (it exists in chat; the corridor shows it quiet, not missing).

### 4.3 On the helix: threads are braids, strands are their fibres

- Beads of the strands of one thread are joined by a faint **thread line** that braids down the helix (the thread),
  with each strand bead on it. A forked strand leaves the thread line at its fork time and rejoins where it "reports
  to" (helper strands), exactly like the corridor's fork.
- Hover a braid → the thread's name, its strands as a short fan (name · tags · last activity · a running dot like the
  chat header's map). Click → the fan opens into separate beads around the axis so each strand can be picked.
- The helix labels the 3–5 most recent threads permanently (anchored typography on the outside of the helix, leader
  lines, never panels) and the rest on hover — labels by level of detail, so the helix is readable at a glance.
- Date ticks along the helix: *now* at the top, then today, yesterday, this week, older months; scrolling moves time
  and the ticks slide past like a clock face.

### 4.4 In the corridor: a fork is a doorway

- The corridor of a strand shows its sibling strands where they forked (as today). The fork becomes **a doorway in the
  wall** (the same soft arch as the end door, smaller): hover = the strand's name and tags; click = walk through into
  that strand's corridor (a short assembly, not a cut). The breadcrumb grows: memory › timeline › thread · X ›
  strand · research.
- The far door goes to the **next strand of the same thread** (chronologically), not the next unrelated session;
  the last strand's far door returns to the thread on the helix. (Today it opens the next session in the snapshot list.)
- A helper strand's corridor ends at an arch that **reports back**: walking through returns you to the parent strand
  at the moment the helper reported.
- The rail at the bottom gains the strand's tags and a "continue in chat" end marker.

### 4.5 Chat → memory (from the chat view)

| Where in chat | What the user does | Where they land |
|---|---|---|
| header `◉` menu | **Memory** (new item, first in the list) | the timeline, flown into the **current strand's corridor** at the latest turn |
| strand map `⌖` | a small `◎` on each strand row | that strand's corridor |
| thread orbit | Alt+click (or a `◎` on the front thread) | the thread's braid on the helix, fanned open |
| the matrix **memory line** ("remembered: …") | click it | the turn's recall arches (what memory gave this turn), with the remembered item focused |
| a turn's `⋯` menu | **What IRIS remembered / decided here** | the turn in the corridor, arches + Oracle rays of that turn |
| the lens (artifact) | **In memory** (beside "To dashboard") | the artifact's cell in the Artifact view, with "made in" path |

Mechanics: one app-wide event, `iris:open_memory {focus: "strand:<id>" | "turn:<conv>:<turn>" | "thread:<id>" |
"claim:<id>" | "artifact:<id>", view?}`; the memory surface listens, opens (or comes forward), and runs the pivot.
The same string is the deep-link form (§5.3). Spine knots stay as they are: the chat spec says landmarks are never
knots, so memory never adds knots to the chat spine.

### 4.6 Memory → chat

| In memory | Action | Chat does |
|---|---|---|
| a strand (bead, corridor title) | **continue in chat** | opens that conversation (`openStrand`, the same handler the strand map uses) at its last turn |
| a turn / moment | **open in chat at this turn** | opens the conversation and scrolls the timeline to that turn (the spine gutter's jump), the turn flashes once |
| a claim | **ask IRIS about it** | focuses the composer with a `#claim:<id>` reference chip (the composer's `#` contract: an address, never content) |
| any thing | drag it onto the chat wing | the same reference chip (as MADE rows already drag to the dashboard) |

Mechanics: `iris:open_conversation {conversationId, turnId?}` and `iris:composer_ref {address, label}`; chat-view
already owns `openStrand` and the composer refs. The composer's `#` list gains a third group, **IRIS knows**
(claims and pins), next to "IRIS made" and "This project".

## 5. Finding things: search, time, and the back stack

### 5.1 One search, two answers

> **Superseded (owner, 2026-10-21): text search only, built for memory.db — see `MEMORY-SURFACE-BUILD.md` §3.** The
> two-answer design below is kept for the record; answer 2 (the recall preview) is not built.

`/` opens the search line at the top centre (as today). It returns two answers side by side, because a user asks two
different questions with the same words:

1. **"Where is it?"** — a text match over strand titles, message previews, claims, moments, pins and artifacts,
   grouped by kind with the key's shapes as icons, at most 8 visible, ↑↓ to move, Enter to go.
2. **"What would IRIS remember?"** — the app's own recall, run as a dry-run preview: `POST /api/memory/recall-preview
   {query}` returns what the context package would hold for that text (path, predictions, failure warnings, prior
   research, neighbours) **without writing any event, touching the region registry or crediting a recall**
   (contract-tested). This is the unique part: the user sees memory the way IRIS sees it.

While the user moves through the results, **the scene previews without moving the camera**: matching crystals,
beads or cells light in place and everything else dims (the key's isolation, by query). Enter flies there (§6.1).
Empty result: "Nothing like that yet" (plain, calm). Typing never steals keyboard shortcuts outside the field.

### 5.2 Time is one cursor for all views

The scrubber becomes a **global time cursor** (default *now*). Set it to last Tuesday and: the cortex shows the memory
as it was (crystals not yet born are absent, claims not yet proven are outlines), the helix centres on that day,
Artifacts dims what was made later, the Oracle shows each consumer's status on that day (its bar history). The
breadcrumb shows the date in amber when the cursor is not *now*; one click returns to now. "Watch it grow" (`g`)
plays the cursor forward.

### 5.3 The back stack and deep links

Every focus and every "go in" pushes a step: `{view, focus, camera, time}`. Esc / Alt+← / mouse back pop it with the
reverse pivot. The current step serialises to `memory?view=timeline&focus=turn:abc:t7&t=now` — the same string the
chat's `iris:open_memory` uses, and what "copy link" puts on the clipboard (useful in a pin or a message).

## 6. The experience: transitions and response

### 6.1 Object constancy — the thing travels, the view follows

The signature transition: when a path leads to another view, **the focused object itself travels**. A claim crystal
lifts out of the cortex, the cortex dissolves into fragments that re-assemble as the helix, and the crystal lands on
the strand bead where it was learned; the camera follows the crystal, not the cut. The same rule everywhere:
- claim ↔ corridor: the crystal flies into the corridor and settles on its stem;
- bead → corridor: the bead opens into the white void and the corridor assembles (as today);
- corridor → helix (Esc): the corridor's fragments collapse back into the bead — the reverse, never a flash;
- search → result: the camera flies along existing structure (frost bridges, the helix, the strand) to the target;
  a long jump uses a brief fragment tunnel (§18 "assembly"), never a black frame.

Budgets: every transition ≤ 1.2 s, interruptible by any input (the new input wins), `prefers-reduced-motion` =
cross-fade of 200 ms. The black-frame sampler and the pow()/NaN rule stay standing checks.

### 6.2 Walking the memory (navigation as travel)

- **Cortex:** with a claim focused, ← → walk to its linked claims along the frost bridges, the camera gliding along the
  bridge (light runs ahead of it). ↑ climbs to the claim's territory arm and out to the skin; ↓ goes toward the core.
- **Inside a territory**, the nearest 5 claims are labelled (anchored text, fades with distance) so the space reads like
  a map, not a starfield. Claims are arranged so **depth means sureness**: proven claims near the skin of their
  territory (the surface of what IRIS knows), still-learning ones deeper toward the core (forming).
- **Corridor:** ← → already step claim to claim; add **Shift+← →** to step turn to turn (messages), and **Tab** to the
  next doorway (fork / helper / far door).
- **Timeline:** ↑ ↓ (or scroll) move through time a day at a time; ← → move between strands of the same thread.

### 6.3 How the memory responds while IRIS works

One learnable grammar, the same in every view (it extends §11 of the dashboard design):

| IRIS does | Direction | What the user sees |
|---|---|---|
| a turn starts | — | the breadcrumb's live dot; the current strand's bead brightens at *now*; in its corridor the far end begins to assemble |
| memory is delivered to a step (`RECALL_DELIVERED`) | **inward** (memory → mind) | each delivered claim wakes and a faint spark travels **from the claim to the core**; on the helix an arch grows from the source strand toward *now* |
| a step records a moment | **outward** (mind → memory) | a spark from the core to its territory (built), the skin flashes |
| the Oracle decides | **ray** | in the Oracle view a ray from the consumer into the pupil, the distribution flares; elsewhere only the ticker line |
| a step is verified after a recall | — | a quiet pulse ring on the claim; a failure after a recall = the claim's desync glitch (≤ 300 ms) |
| a claim crystallizes | **assembly** | fragments fly together into a new outline crystal at its place |
| a claim is promoted | **graduation** | its outline fills in, facet by facet, in its evidence colours |
| Kyudo cleans (integrity pass) | **dissolution** | the dissolved claims loosen into fragments and fade; the territory resettles; the health reading updates |
| a quorum signal | **desync wave** | a short glitch wave across the territory, then a resettle |
| the turn ends | — | the bead settles; the corridor's new stretch finishes assembling |

Rules: emphasis follows the evidence ladder (user evidence strongest, `none` faintest); at most 6 live effects on
screen at once (excess is summarised in the ticker); nothing builds brightness; a **follow** mode (`f`) lets the camera
drift to wherever IRIS is touching memory, off by default, on automatically in an idle cortex after 20 s ("screensaver
that is true").

### 6.4 Words the user reads

- **Do not overclaim.** Today `RECALL_HELPED` means only "the step it was given to did not fail" (§18.9 finding), so
  the card says *"the step it was given to was verified"*, never "this helped", until attribution is fixed.
- Every number has a plain meaning beside it: "sure 9 times in 10", "its confidence is honest", "needs 12 more examples".
- Relative time on the face ("2 h ago"), absolute on hover; long titles end in "…" with the full text on hover.

## 7. The cortex — from a beautiful object to a map of what IRIS knows

1. **Territory labels that inform:** name · claims (proven / learning) · sync bar · what changed this week
   ("+3 claims, 1 contradicted, 2 cleaned"). Shown for the territories facing you; others on hover.
2. **Inside a territory:** sub-sectors as labelled clusters; nearest-5 claim labels; depth = sureness; the territory's
   own health line at the top (Kyudo: trust channels present, decay, last integrity pass).
3. **A focused claim** opens its card (exists) with the §3.2 paths, and its frost arbor lights end to end so the user
   sees what it is connected to before choosing a path.
4. **"Every time it was used":** from a claim, recall arches bloom on the helix from every turn that received it —
   the synchronization view reversed. This is the most direct answer to "is this claim worth anything?"
5. **Health overlay (`k`, Kyudo):** territories tinted by health; rim gaps (weak trust) emphasised; decaying claims
   fade further; recently dissolved claims shown as ghost outlines for a week with the reason ("no use, no evidence
   for 74 active days"); quorum log as marks. A one-line reading at the top: proven · learning · decaying ·
   contradicted · cleaned this week.
6. **Pins** keep their brackets; focused, the tether to what they hold lights and the path travels it.

## 8. The timeline — from a helix of dots to a navigable history

1. Thread braids and strand beads (§4.3), date ticks, LOD labels.
2. Hover a strand: its card (title · thread · tags · turns · outcome · sync · "the memory gave it …") **and** its
   recall arches (built); click focuses it (arches stay, card stays, paths appear); Enter enters the corridor.
3. Filters as chips above the helix (same style as the key): by tag (plan / build / research / people / swarm), by
   outcome (finished / drifted / failed), by territory. Filters combine with AND and dim, never remove.
4. **Turn level:** zoom (Ctrl+wheel or pinch) on a stretch of the helix expands each strand bead into its turns
   (small ticks); hovering a tick shows that turn's first user message and the reply's first line; the arches then
   attach per turn.
5. The live strand (a turn running now) pulses at the top with the running dot — the same signal as the chat header.

## 9. The Oracle view — rebuilt on docs/architecture/oracle.md

Rename the lens **oracle**. Keep the iris of fibres (the owner likes it). ~~Remove the XurOrb from the centre.~~
**Owner, 2026-10-25:** an empty pupil felt still and not interactive; the XurOrb put back "still seems out of
place". **Built: the Oracle's own pupil** - the iris's fibres continue inward as rings of particles that turn like
aperture blades and breathe; a live decision opens it and its outer band forms the option arcs (item 1 below).

1. **The pupil = d1.** The centre becomes a single dark aperture: "one small local model, ONE question per run, zero
   text — it reads the answer from the logits". Each live decision is drawn as exactly that: a ray from the
   consumer's sector into the pupil, and for ~1 s the pupil shows **the probability distribution over the offered
   options as arcs around its rim** (arc length = probability; the chosen option bright). Enforced and acting → the
   ray returns outward bright (it decided); shadow → the ray fades (it only watched). Latency is the ray's travel
   time (112–302 ms typical, so it reads as instant; a slow one is visibly slow).
2. **Sectors grouped by job** (route, approve, guard, interpret_step, judge_review, judge_step, judge_goal,
   judge_depth, shape, interpret, classify_event, judge_call), the job name on the outer ring; each consumer one
   sector. `call_closing` is drawn as "measurement only" (refused by design), never as failing.
3. **The bar as a ladder:** each sector's fibres climb through **8 rings = the 8 clauses** (rows ≥ 100, both classes,
   minority ≥ 5%, AUROC ≥ 0.65, a threshold with precision ≥ 0.90, Wilson ≥ 0.85, ≥ 50 rows above, ECE ≤ 0.05, and the
   acting clause for asymmetric consumers). Clauses met are lit; **the first missing clause glows amber and is named
   in plain words** ("needs to rank its errors better — AUROC 0.62, needs 0.65").
4. **Three states and the owner's switch, kept apart:** Watching (shadow), Trying out (sampled), Trusted (enforced);
   a small separate mark for *switched on by the owner* (`IRIS_DECISION_ENFORCE`) — earned and switched on are two
   different facts (oracle.md 3.6). The view never toggles anything.
5. **Honest history:** focusing a consumer shows its status over time as a thin line along the sector —
   e.g. `tool_choice`: earned 2026-10-13 → **demoted 2026-10-21** ("the grown cohort no longer ranks its errors").
   Demotions are not hidden; they are the evidence that the bar is real.
6. **The acting side:** for asymmetric consumers (needs_action) the sector splits into the side that changes behaviour
   and the side that does not, each with its own precision (oracle.md 7.2a).
7. **Calibration on focus:** a small reliability curve drawn in fibres (confidence vs right), the threshold as a notch.
8. Data: `benchmarks/consumer_bar_record.json` + `benchmarks/oracle_calibration.json` + recent `system_events`
   decision rows (exporter) and the live `oracle_decision` message (§10).

## 10. Data and live path the UX needs (backend)

None of this exists yet (checked 2026-10-21: no `/api/memory/*` routes, no `memory_event` WS message; only
`memory/stats`). All read-only, LIMIT-bounded, through the backend, never the DB from the frontend (§10 of the design).

| Need | Endpoint / message | Notes |
|---|---|---|
| strands of a thread with memory activity | `GET /api/memory/strands?thread=` | joins `conversations.parent_id` to `memory_events.thread_id` (§4.2 contract) |
| a strand's corridor data | `GET /api/memory/strand/{id}` | events, messages (previews), claims touched, recalls, pins |
| a turn | `GET /api/memory/turn/{conv}:{turn}` | its recalls (+ resolved chain rows), Oracle decisions, moments |
| claims | `GET /api/memory/claims?territory=&tier=` · `/claims/{id}` (+ every turn that received it) | |
| search | `GET /api/memory/search?q=` (text) · `POST /api/memory/recall-preview` (dry-run, no writes) | the preview must be contract-tested to write nothing |
| health | `GET /api/memory/health` | counts + the last integrity pass + quorum rows |
| Oracle | `GET /api/memory/oracle` | bar record + calibration + recent decisions |
| live | WS `memory_event`, `landmark_update`, `recall` (delivered/verdict), `oracle_decision`, `integrity_pass` | broadcast from the existing single writers (the lanes), never a new writer |

## 11. Decisions (answered by the owner, 2026-10-21)

1. **Where it lives:** a **surface of the dashboard** (`components/dark-glass-dashboard.tsx` inside
   `components/dashboard-wing.tsx`), next to Workspace hub, Browser, Models and Marketplace. It is no longer a design
   demo: it is built as its own component. The build plan is `MEMORY-SURFACE-BUILD.md`.
2. **Corrections are part of v1** (confirm, mark wrong, forget, pin / unpin, hold / release), each one USER evidence
   written by the backend, undoable.
3. **The word "session" is retired from every label.** A session could sit inside any thread or strand, so it names
   nothing the user can find. The words are: thread, strand, turn, step, moment, claim, pin, node, artifact; memory
   that did not come from a chat is "outside chat" with its source (an evaluation run, a test, the system).
4. **Follow mode is ON by default, and can be turned off.** It is the camera acting like a camera operator at a live
   event: when IRIS remembers or records something, the view drifts toward it so the user sees the action. Any input
   from the user pauses it for 20 s; a toggle in the HUD (and `f`) turns it off; the choice is remembered per viewer.
5. **Search is text only, and it is built for memory.db, not like a web search** (§5.1 is replaced by
   `MEMORY-SURFACE-BUILD.md` §3): it searches what the memory holds, ranks by how alive and how proven a thing is
   under the memory's own growth/decay law, and says why each result ranks where it does. No recall preview.

## 12. Order of work (each phase has DONE / NOT THIS)

| Phase | What | DONE = | NOT THIS = |
|---|---|---|---|
| 0 | IDs contract + read API + live taps (§4.2, §10) | the contract test fails on the old state and passes; the mockup's `?live` mode reads the API instead of the snapshot | a new writer; a second store; frontend DB access |
| 1 | Grammar, back stack, deep links, paths, search (both answers), time cursor (§3, §5) | every view: hover/click/Enter/Esc/`/` behave per §3.1; Esc never jumps two levels; a deep link reproduces a state | a panel or list UI; modal dialogs |
| 2 | Timeline: braids, LOD labels, date ticks, filters, turn zoom (§4.3, §8) | a user finds a strand by thread and date without hovering more than twice | a second timeline; removing the helix |
| 3 | Chat bridge both ways (§4.5, §4.6) | from a chat turn to its recall arches in one click, and back to the turn | knots on the chat spine; content in composer refs |
| 4 | Cortex: labels, depth = sureness, claim paths, walking, "every time it was used", health (§7) | a user can answer "what does IRIS know about X and how sure" from the cortex alone | new shapes; brighter scenes |
| 5 | Oracle view (§9) | every consumer shows its state, its gap in words, its history; a live decision draws its distribution | the XurOrb; any control that switches a consumer |
| 6 | Live choreography + follow (§6.3) | a recorded live turn replays with the inward/outward/ray grammar and ≤ 6 effects | effects that build brightness; effects with no event behind them |
| 7 | Corrections (v2, after decision 2) | each correction is a USER evidence event written by the backend, undoable | direct DB edits from the UI |

Each phase is verified in the real app (not only the mockup) and on the owner's Chrome as well as the in-app browser —
the black-screen bug proved that the in-app browser can hide a GPU-specific failure.

## 13. The small details (checked one by one)

- Hover intent 80 ms; a card stays 250 ms after the pointer leaves, so moving onto its paths never loses it.
- A card never covers the thing it describes (leader line, side chosen away from the object).
- Cursor: pointer only over something that responds to a click; grab while dragging.
- Selection survives a view switch (the focused claim is still focused when you come back).
- Scrambled-text reveal only on titles, never on numbers.
- Numbers: thousands separators; percentages without decimals; a sync bar always with its number.
- The live dot means one thing everywhere: a turn is running (same as the chat header).
- Empty states: plain and true ("Nothing remembered here yet — use IRIS and it will grow"); backend offline: "the memory
  is resting" with the last snapshot, never a black or blank screen.
- Loading: fragments assembling, never a spinner.
- Large memories: LOD labels, capped results ("show more"), the arbor and arch budgets already in place.
- Window resize, detach and DPR changes keep every screen-space width right (the `uRes` uniforms).
- Keyboard: every action reachable without a mouse; focus is visible; `?` lists the keys for the current view.
- Reduced motion and reduced transparency honoured everywhere; the white void on entry becomes a quick fade.
- Privacy: the memory never leaves the machine; a copied deep link holds ids, never content.
