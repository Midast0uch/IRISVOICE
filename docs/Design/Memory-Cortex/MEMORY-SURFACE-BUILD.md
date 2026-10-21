# Memory surface — the build plan (from mockup to a dashboard surface)

Owner, 2026-10-21: the memory goes into `components/dark-glass-dashboard.tsx` (inside `components/dashboard-wing.tsx`)
as one of the surfaces; corrections are part of v1; the word "session" is retired; follow mode is on by default and
can be turned off; search is text only and built for memory.db. "This is no longer really a design demo … the visual is
basically 85% complete; we can start making sure it is fully implemented as its own component."

Read with: `MEMORY-UX-PLAN.md` (the grammar, paths, chat bridge, transitions), `MEMORY-DASHBOARD-DESIGN.md` §18 (the
visual language), `MEMORY-FOUNDATION-ANALYSIS.md` §11–16 (the growth/decay law, Kyudo, integrity).

---

## 1. Facts measured on the live stores (2026-10-21, read-only)

| Fact | Value | Consequence |
|---|---|---|
| `data/memory.db` size | 899 MB | no endpoint may scan; every read is indexed and LIMITed; EXPLAIN QUERY PLAN before shipping (the S113 lesson: one unindexed scan cost 73 s) |
| `memory_events` | 40,602 rows; **35,405 (87%) from `eval-*` threads**; 6,457 distinct threads | evaluation traffic hides by default, counted and one toggle away |
| `memory_chain` | 41,773 rows | the "what a step did" text (`insight`) is the richest searchable field |
| `mycelium_landmarks` | 3,292 rows, **3,220 absorbed by Kyudo**, 72 live | search and links must handle cleaned claims (re-point to the survivor or say how it was cleaned) |
| live claims' `conversation_ref` | 30 of 72 are `bootstrap_seed`; the rest are memory thread ids; **0 are conversation ids** | "where it was learned" needs one resolver: thread id → conversation, or "built in at the start" |
| non-eval memory threads that resolve to a conversation | 3,233 of 3,246; the 13 others are test or system ids (`session_iris`, `t23-inet`, `s1`, …) | an "outside chat" bucket is real, not hypothetical |
| `conversations.db` | 4,316 conversations, 4,312 thread roots | strands are rare today; the design must still treat every strand properly |
| titles | live ONLY in `conversations.db` | **deleting a conversation in chat erases its name from everything the memory can show** (§4, case 1) |
| `/api/memory/*` routes, `memory_event` WS message | none exist (only `memory/stats`) | phase 0 builds the read API and the live taps |
| `three` in `package.json` | not installed (the mockup loads 0.160 from a CDN) | `npm install three@0.160.0 @types/three` — **needs the owner's OK** (project rule) |
| dashboard wing Escape handler | closes the whole dashboard on any Escape | memory's "Esc = one step out" must take precedence (§4, case 9) |
| dashboard wing transform | `rotateY(-15deg)` unless spotlighted | WebGL picking is wrong on a perspective-transformed element (§4, case 10) |

## 2. Where it plugs in

- `SURFACE_IDS` gains `'memory'` (after `'hub'`); the rail's surface places gain **Memory** with a badge `live` while
  IRIS writes memory and a count of corrections pending undo; the body renders `<MemorySurface …/>` when
  `activeSubApp === 'memory'`.
- Opening from anywhere uses the app's existing path: `iris:card_action {action: 'open_memory', focus}` →
  `pendingSubApp = 'memory'` → `openDashboardSolo()` (app/page.tsx already does this for `models`). The focus string
  rides with it (`strand:<id>`, `turn:<conv>:<turn>`, `thread:<id>`, `claim:<id>`, `artifact:<id>`).
- A detached dashboard (`?pane=dashboard`) receives the same request over a Tauri event (`memory:open`), the pattern
  `wing:reattach` already uses.
- Opening Memory asks for the dashboard spotlight (`onRequestSpotlight`): the surface is flat and full-size, so
  picking is exact (§4 case 10).

## 3. Search, built for memory.db (not a web search)

A web search answers "which documents contain these words, most popular first". The memory is not a pile of
documents: every item is alive or fading under one growth/decay law, proven or still learning, trusted or not, and
tied to a thread in time. So the search answers **"what does the memory hold about this, and how much does it hold
it"**.

### 3.1 What it searches (the memory's own records)

| Kind (key shape) | Source in memory.db | Fields searched |
|---|---|---|
| claim | `mycelium_landmarks` (live and absorbed) | `micro_abstract_text`, `label`, `task_class` in plain words |
| step (what IRIS did) | `memory_chain` | `insight`, the tool (`mediator`), `result` |
| moment | `memory_events` | the label in plain words (the translation table), the family word, `payload` text fields |
| turn / task | `episodes` | `task_summary`, `failure_reason` |
| pin | `pins` / `mycelium_pins` | title, content, tags (the pin store's weighted fields) |
| artifact | `document_data` | title, format, folder |
| node | `mycelium_nodes` | label, layer word |
| thread / strand | `conversations.db` titles + tags, and the memory's own tombstones (§4 case 1) | title and tags only — the message bodies belong to the chat, not to the memory |

### 3.2 How it matches

- All the words must appear (AND), case- and accent-insensitive, word-prefix matching ("deploy" finds "deployment");
  `"quoted phrases"` match exactly.
- **Facets in the memory's own vocabulary**, typed or picked from chips under the search line:
  `proven` · `learning` · `contradicted` · `pinned` · `cleaned` · `kind:claim|step|moment|turn|pin|artifact|node` ·
  `in:<thread words>` · `territory:<topic>` · `from:you|test|finished|held-up|reviewer|iris` (evidence in plain
  words) · `failed` · `helped` · `before:<date>` / `after:<date>` / `last week` · `outside` (outside chat) · `eval`
  (evaluation runs; hidden otherwise).
- Typing `in:` suggests thread names; typing `territory:` suggests the topic words.

### 3.3 How it ranks — by the memory's own law

`rank = match × kind × strength`, where **strength** is the memory's own number, not popularity:
- **alive** — the item's current strength after decay on the active-day clock (the §11 law, computed, never written
  back): a fading claim sinks, a renewed one rises;
- **proven** — the evidence ladder (you > held up again / a second source > tests / finished > reviewer > IRIS's own
  word > unconfirmed), and tier (proven above learning);
- **used** — log of activations / recalls;
- **trusted** — the Kyudo channel (an UNTRUSTED source counts less);
- **your word** — anything you confirmed or pinned ranks first among equals.
Cleaned (absorbed) claims rank last and say how they were cleaned ("merged into …", "no use and no evidence for 74
active days"); a click on a merged one goes to its survivor.

Each result shows **why it ranks there**, in one line: "proven · used 14 times · you confirmed it" or "learning ·
fading — not used for 31 active days". The search teaches how the memory works while it finds things.

### 3.4 How it runs

- `GET /api/memory/search?q=&facets=&limit=40`: one bounded query per kind on a read-only connection, merged and
  ranked in Python, off the event loop (a worker thread), never on the answer path, never counted as a recall (no
  activation, no RECALL event — contract test).
- Budget: p95 ≤ 150 ms on the live store. First build: indexed prefilters + `LIKE` on the bounded candidate sets;
  measured. If the budget fails, an FTS5 index maintained by the single writer (the lanes) — added only on the
  measurement, then guarded as a standard with its tolerance.
- The surface shows at most 8 results per kind (↑↓ Enter; "show more"), previews them in the scene without moving the
  camera, and flies to the chosen one.

## 4. Edge cases — asked, ranked, answered

I asked of each object: what if it is gone, renamed, moved, merged, cleaned, huge, empty, live, or seen from another
window? The answers below are ranked: **P0** = the memory would show something false or the app would misbehave;
**P1** = it would be confusing or slow at real scale; **P2** = polish and safety.

### P0 — truth of the data

1. **A strand or thread is deleted in chat; its memory remains.** Today `delete_conversation` removes the rows and
   their messages (and a root takes all its strands); the memory keeps every event, step and claim under that id, but
   the **title is lost** (titles live only in conversations.db). Fix: a **tombstone** — on delete (and on rename),
   the backend types one memory event per conversation (`STRAND_DELETED` / `STRAND_RENAMED`, new LABELS in an existing
   family; no new values) with `{title, parent_id, tags, message_count, at}`, through the `memory_events` lane. The
   surface draws a deleted strand as a **ghost**: a dashed bead on the helix, a desaturated corridor, the title in
   italics with "deleted in chat on 21 Oct". "Continue in chat" becomes **"start a new strand from this memory"**
   (a new strand whose first message carries a `#` reference to the ghost) and "forget its memory" is offered.
   Conversations deleted before tombstones existed get a name derived from the memory (the first GOAL_SET, else the
   first task summary, else the first step) marked "(title lost)".
2. **A thread root is deleted** → all its strands go too → the whole braid becomes a ghost braid, still searchable.
3. **A helper strand outlives its parent** (`reports_to` points nowhere) → it reports to "a deleted strand" (ghost).
4. **Memory that never came from a chat** (`eval-*`, test ids, the system: Kyudo integrity, maintenance;
   `bootstrap_seed` claims) → an **outside chat** bucket with the source word; evaluation hidden by default (87% of
   events) but counted, one toggle away; developer mode shows it.
5. **thread_id ≠ conversation id** for some rows (`caducean_session_exits.conversation_id`) → one resolver
   (`resolveStrand(threadId)`) used everywhere; the phase-0 contract makes every new row carry the conversation id
   and `"<conversation>:<turn>"`.
6. **"Where it was learned"** reads `conversation_ref` = a memory thread id or `bootstrap_seed` → the resolver maps it
   to a strand, a ghost, "outside chat", or "built in at the start".
7. **A link points at a cleaned claim** (pins, frost bridges, deep links, search hits; 3,220 of 3,292 rows are
   absorbed) → re-point along the merge log to the live survivor; with no survivor, show the cleaning and its reason.
8. **A renamed thread or strand** → the current title everywhere; old titles kept by the rename tombstone (searchable).

### P0 — the surface inside the app

9. **Esc collides.** The dashboard wing closes the whole dashboard on Escape; memory uses Esc to step out one level.
   The surface handles Escape first (capture phase) while its back stack is not empty and marks the event handled;
   the wing ignores a handled Escape. At the top level, Esc passes through and closes the dashboard as today. Guard:
   a unit test on the precedence.
10. **3D tilt breaks picking.** The wing is `rotateY(-15deg)` unless spotlighted; pointer positions on a perspective
    transform do not match the canvas. Opening Memory requests the spotlight (flat); if the user returns to the
    balanced, tilted layout, the surface becomes a calm **glance** (it keeps rendering, no hover picking) with
    "open" restoring the spotlight.
11. **Two windows.** Chat in the widget, dashboard detached → links cross windows by Tauri event; the surface opens
    in whichever window holds the dashboard.
12. **Cost when unseen.** The render loop stops when the surface is not the active one, the dashboard is closed, the
    chat spotlight blurs it, or the page is hidden; every GPU resource is disposed on unmount; a lost WebGL context is
    restored and the scene rebuilt; no WebGL2 → the same grammar on a flat list view.
13. **Keyboard shortcuts while typing.** No memory shortcut fires while focus is in any input (its own search line,
    dashboard fields, the chat composer in the other wing).
14. **Brand colours.** The surface takes the app's palette (`useBrandPalette`) and follows a theme change live;
    the mockup's own theme list goes.
15. **Corrections during a turn.** A correction applies from the NEXT turn (the running turn already has its
    context); the card says so.

### P1 — scale, live traffic, time

16. **Size.** Every endpoint LIMITed and index-checked; the helix aggregates old months into segments (6,457
    threads cannot be 6,457 labelled beads); corridors cap their length (the existing 260-moment bound) and page by
    turn.
17. **Live flood during evaluation runs.** The backend coalesces live messages per 250 ms; the surface keeps ≤ 6
    effects at once, updates counts for the rest, and never builds brightness.
18. **Backend offline or restarting.** "The memory is resting" with the last data, reconnect on its own; never a
    blank or black screen.
19. **The strand you are inside grows.** New turns assemble at the far end of the corridor; your place stays.
20. **Kyudo cleans the claim you are looking at.** The crystal dissolves in place; the card says "cleaned just now —
    <reason>" with a path to its survivor if merged.
21. **A correction meets a merge.** A correction on a claim that was just absorbed is applied to the survivor (merge
    log) and says so.
22. **The time cursor is in the past and a live event arrives.** No live effect; a "now" chip pulses to return.
23. **Time formats.** Epoch floats and `YYYY-MM-DD HH:MM:SS` strings coexist (the exporter's `ts_of`): one parser;
    decay is shown on the active-day clock, the calendar on the user's local time.
24. **Very long threads.** Turn zoom pages through turns; arches attach per turn only in the visible range.

### P2 — polish and safety

25. **Privacy.** Deep links carry ids, never content. "Purge" (see §5) removes text but keeps structure.
26. **Accessibility.** Reduced motion (white void → quick fade, flights → cross-fades); every action by keyboard;
    visible focus; readable contrast on every label.
27. **Any script in titles.** Canvas inscriptions use a font stack with fallbacks.
28. **An empty memory** (new install): every view has a calm, true empty state; no division by zero with 0 claims,
    0 edges, 0 territories (audit every `Math.max(1, …)` site of the mockup).
29. **An older store** missing optional tables (sectors, pins, quorum log): read as "none", never an error (the
    exporter already does this; the API must too).
30. **Shader safety.** A lint test fails on `pow(` with a base that can be negative and on `asm` used as a name — the
    two shader faults this work has met — and a black-frame check runs in the e2e smoke test.

### Questions I asked myself that changed the plan

- *If the user deletes a conversation, do they expect the memory to forget it?* Not necessarily — the owner says the
  memory remains — but they must be able to make it forget. Hence the ghost **and** "forget its memory".
- *Can a correction be wrong?* Yes, so every correction is undoable for 10 minutes and listed under "your
  corrections".
- *What if the user corrects IRIS through the chat instead (an edit undo already types a CORRECTION)?* The surface
  shows those too, in the same list, so both paths agree.
- *What would make the memory lie on screen?* A missing title, a dead link, a cleaned claim shown as live, an eval
  run shown as the user's work, "helped" when it only means "did not fail". Each has a case above.
- *What would make the app worse with the surface open?* A blocking query on the event loop, a render loop that never
  sleeps, an Escape that closes the wrong thing, wrong picking under the tilt. Each has a case above; the live gate
  (§7) measures the first two.

## 5. Corrections in v1

All through `POST /api/memory/correct {action, target, reason?}`; the backend writes them as **USER evidence (channel
USER = 3)** through the single writer (`app_write`, the pin store), types a memory event, and the surface updates from
that event (never optimistically). Every correction can be undone for 10 minutes and appears in **your corrections**.

| Target | Action | What happens in memory |
|---|---|---|
| claim | **That's right** | user evidence added (the strongest); a learning claim is promoted when the rule allows |
| claim | **That's wrong** | a user contradiction; a proven claim drops to learning; with no other support Kyudo dissolves it at its next pass; recall stops using it from the next turn |
| claim | **Forget this** | absorbed with the reason "forgotten by you" (Kyudo's absorb, never a row delete); excluded from recall |
| pin | **Pin** (a claim, moment, turn, step, artifact) / **Unpin** / **Hold in context** / **Release** | the pin store's own methods (PIN_SYSTEM.md) |
| strand / thread | **Forget what IRIS learned here** | claims whose only evidence came from it are dissolved; its events are marked forgotten (kept for history, excluded from recall) |
| strand / thread | **Purge** (privacy) | text fields of its memory rows are replaced by "[removed by you]" while structure and references stay (the chain stays intact); irreversible; asks twice; says how many rows changed |

Guards (backend contract tests): each action writes through the single writer with channel USER; no action deletes a
landmark row; purge leaves every reference valid; undo restores the exact prior state; a correction on an absorbed
claim lands on its survivor.

## 6. The component — architecture

The mockup (`docs/Design/Memory-Cortex/index.html`, ~2,900 lines) stays the visual reference. The component is a
port, section by section, with a side-by-side screenshot check for each view.

```
components/memory/
  MemorySurface.tsx      the surface root: props {isActive, spotlit, onRequestSpotlight, isDetached, isRemoteView}
  hud/Breadcrumb.tsx · Key.tsx · SearchLine.tsx · FocusCard.tsx · Paths.tsx · Ticker.tsx · Hint.tsx
       · CorridorRail.tsx · FollowToggle.tsx · Corrections.tsx · TimeCursor.tsx
lib/memory/
  api.ts                 typed client for /api/memory/* (relative paths, AbortSignal.timeout, like lib/strands/api.ts)
  model.ts               the model types (the snapshot shape is the API shape), normalize, resolvers
                         (resolveStrand, claimOrigin, survivorOf), sync / desync, the translation table
  nav.ts                 back stack, deep links ("memory?view=…&focus=…&t=…"), Escape precedence
  search.ts              the query parser (words, phrases, facets)
  live.ts                iris:ws_message memory_* subscription, coalescing, the effect budget
  scene/
    MemoryScene.ts       framework-free engine: init(canvas) · setModel · setView · focus(ref) · on(evt) · pause/resume · dispose
    renderer.ts          renderer + bloom + the NaN-safe shader rules; context-loss recovery
    camera.ts · picking.ts · anchors.ts (projected anchor store; React reads it by ref at frame rate, never via state)
    cortex/ · timeline/ · corridor/ · oracle/ · artifacts/ · shaders/
hooks/useMemorySurface.ts   wires the scene to React (mount, resize, visibility, palette)
backend/api/memory.py       router /api/memory: strands, strand, turn, claims, search, health, oracle, correct
backend/memory/surface_queries.py   every SQL statement of the surface: read-only connection per thread, LIMIT, EXPLAIN-checked
```

Rules carried from the project: every store path through `resolve_memory_store_path`; writes only through
`app_write` / the lanes; no blocking call in an async handler; one query module also used by `export_snapshot.py`, so
the mockup and the app read the same shape from the same SQL.

## 7. Order of work

| Phase | What | DONE = | NOT THIS = |
|---|---|---|---|
| 0 | IDs contract; tombstones on delete/rename; `/api/memory/*` read endpoints; live taps from the lanes | contract tests fail on the old state and pass; every endpoint's query plan uses an index; p95 ≤ 150 ms on the live store | a new writer; frontend DB access; a scan |
| 1 | Port the engine to `lib/memory/scene`; `MemorySurface` in the dashboard (rail place, spotlight, Esc precedence, loop pause, context loss, palette) | the four views render in the app at parity with the mockup (screenshots side by side); Esc steps out one level; no frame drawn while hidden | new visuals; the mockup's DOM code copied as is |
| 2 | Grammar, paths, back stack, deep links, key with counts, memory-native search, time cursor, follow mode (on, toggle) | every gesture in UX-PLAN §3.1 works in every view; a deep link restores a state; search meets 150 ms p95 | a list or panel UI; a recall preview |
| 3 | Timeline braids, ghosts, outside-chat bucket, date ticks, turn zoom; chat bridge both ways (header Memory, strand map ◎, matrix memory line, open in chat at a turn, `#claim` refs) | from a chat turn to what memory gave it in one click and back to the turn; a deleted strand shows as a ghost with its name | knots on the chat spine; message bodies in the memory |
| 4 | Cortex map (labels by distance, depth = sureness, claim paths, walking, "every time it was used", health) + corrections v1 | "what does IRIS know about X, how sure, and fix it" from the cortex alone; every correction undoable | row deletes; optimistic UI that the backend did not confirm |
| 5 | Oracle view (UX-PLAN §9) | every consumer shows state, gap in words, history; a live decision draws its distribution | the XurOrb; any switch |
| 6 | Live choreography (UX-PLAN §6.3) | a recorded turn replays with the inward / outward / ray grammar, ≤ 6 effects | effects with no event behind them |

**Live gate for every phase (the measured loop):** an evaluation group run with the surface open and following must
show no change in `reply_s` against the same run with the dashboard closed (the surface only reads, off the answer
path); and a manual check on the owner's Chrome, because the in-app browser hid the black-screen bug.

**Needs the owner before phase 1:** `npm install three@0.160.0 @types/three` (the same version the mockup uses).
