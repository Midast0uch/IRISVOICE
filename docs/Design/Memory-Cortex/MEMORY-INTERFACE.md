# The Memory Interface — final design

**Status: FINAL (2026-10-27).** This is the one design document for IRIS's memory interface (the Memory surface of
the dashboard). It replaces three working documents that were removed on 2026-10-27:
`MEMORY-DASHBOARD-DESIGN.md` (the first design, 2026-10-13 → 10-19), `MEMORY-SURFACE-BUILD.md` (the build plan,
2026-10-21) and `MEMORY-UX-PLAN.md` (the functional UX plan, 2026-10-21 → 10-27, closed DONE). Code comments still
cite them as `UX-PLAN 4.3`, `SURFACE-BUILD section 4 case 9`, `DASHBOARD-DESIGN §18`: **§14 maps every cited section
to this document.**

Read with: `MEMORY-FOUNDATION-ANALYSIS.md` (the memory system itself: sectors, spaces, the growth/decay law, Kyudo,
integrity — this interface only shows it), `docs/Design/EVENT_TAXONOMY.md` (the closed event alphabet),
`docs/architecture/oracle.md` (the decision engine the Oracle view shows), `docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md`.

The memory this interface shows is the APP memory: the store resolved by `resolve_memory_store_path`
(`D:/IRIS/store/memory.db` since 2026-10-26) and `data/conversations.db`. It never shows the MCM build memory.

---

## 1. Purpose

IRIS stores everything it learns in one local store per user. The memory interface is the window into it: where a
user sees **what IRIS knows, how sure it is, where it learned it, what it did with it, and how it decides** — and
can correct it.

- **Audience: the end user, not a developer.** No internal words on screen (§9.4). Calm, factual, trust-building:
  it proves memory works; it does not try to impress.
- **Local, and said once:** "everything here lives on this machine" (the brand's tooltip in the tidy view).
- **It reads; the agent writes.** The surface never writes the store. A correction is a request the backend
  carries out on its own writer as USER evidence (§8.3).
- **Every view answers four questions without being asked** (the lesson of the Artifact view): where am I · what
  is this · what can I do · what is next to it.

The jobs it serves (each has a path in §6):

| # | The user wants to… | How |
|---|---|---|
| J1 | know what IRIS knows about a topic, and how sure | search, or a territory → its claims with sureness and evidence in plain words |
| J2 | know why IRIS answered that way | one click from a chat turn → what memory gave that turn, the claims it touched |
| J3 | find where something was discussed, and continue it | search or time → the strand's corridor at that turn → continue in chat |
| J4 | move between a thread and its strands, in both apps | braids on the helix; forks and helpers are doorways; deep links both ways |
| J5 | see whether the memory is healthy and trustworthy | territory health lines, the health view (`k`), ghosts of what was cleaned |
| J6 | watch IRIS work and understand it | one live grammar: inward = remembering, outward = recording, ray = deciding |
| J7 | correct IRIS's memory | that's right · that's wrong · forget · pin; forget a strand; purge |
| J8 | see how IRIS is learning to decide | the Oracle view: one question per run, the bar as a ladder, honest demotions |

## 2. The design language — a memory you synchronize with

> Owner, 2026-10-19: "the interface was looking similar to Assassin's Creed's Animus, which I liked… a biological
> plant-like organism but not so explicit… a UI/UX experience never seen before."

**The concept: the Cortex is IRIS's Animus.** You do not look AT a memory; you enter it, it assembles around you out
of light and fragments, you synchronize with it, and where it does not hold together it glitches (desync). That is
what IRIS's memory is: a store you can enter, replay, prove and repair.

**Organic only in how it behaves.** Nothing is drawn as a leaf, vine, root or brain fold. The organism shows in
motion: it **breathes** (slow scale and density, 4–7 s), **grows** (fragments accrete where memory is earned),
**sheds** (fragments drift loose and dim where it decays), **heals** (Kyudo knits gaps), **reacts** (a threat is a
desync glitch, a reorganization a pulse that resettles).

**One vocabulary, six words, in every view:**

| Word | In the memory | How it looks |
|---|---|---|
| Fragment | the atom: an event, a context chunk, a coordinate node | a small low-poly shard of pale light; its solidity is its trust |
| Strand | continuity: a conversation, a route between ideas | a thin continuous line; a conversation is a DOUBLE strand (chat + memory) with rungs where a moment belongs to a turn |
| Glyph | meaning: a claim | one glyph design everywhere; its spokes are its evidence |
| Sync | proof and confidence | a 0–100% value on every claim, strand and territory; high = sharp and assembled, low = soft and drifting |
| Desync | contradiction, failure, threat | a short glitch (≤ 300 ms): chromatic offset, fragments jolt, a scan line |
| Assembly / dissolution | recall / forgetting | recalled memory flies together; decaying memory loosens and fades |

**Visual rules (standing):** dark field; pale white-cyan line work; desaturated territory tints; **brightness never
builds up over time** and depends only on current values; facets, lines, glyphs and points — no organic silhouettes;
every motion is driven by a real value; transitions assemble and dissolve, never cut to black; the app's brand
palette is followed live (`useBrandPalette`).

## 3. The views

### 3.1 Cortex — a map of what IRIS knows

The hex-lattice orb. **Territories** (topic domains, or the sector registry when it has rows) are tinted regions of
the skin's own lattice. **Claims** (landmarks) are glyph cells inside, joined by frost bridges (landmark edges);
**pins** are bracketed crystals set into the wall; **sparks** run from the core to a territory when a moment is
recorded, and from a claim to the core when memory is delivered.

- **Territory labels** (for the territories facing you, the rest on hover): name · moments · sync bar · "N of M
  claims proven" · "+N new this week · N contradicted" · the two most-used claims ("knows: …").
- **Hover** a territory, claim or pin: its card. **Click** a territory: dive in. **Click** a claim: its cell card
  (centred on the claim, the text kept inside the cell's curved edge) with its paths (§6.1).
- **Layers (`s`):** one faint geodesic shell per coordinate space, tinted by its write lock; nodes on their shells;
  each shell names itself and who may write there.
- **Health view (`k`):** territories tinted cyan (proven) → amber (learning) → red (contradicted); a one-line
  reading at the top (proven · still learning · contradicted · cleaned or merged · dissolved this week); claims
  dissolved in the last 7 days as **dashed ghost outlines** on their territory — hover gives the claim and the
  reason in plain words ("too many different claims shared its place", "no use and no evidence — last touched 74
  active days ago").
- **Membrane (Kyudo trust):** a strong source keeps a glyph's ring sealed and warm; a weak one leaves gaps and a
  pale, cooler hue; it only ever dims. **Fading:** opacity follows the earned part of confidence; nothing brightens
  with age. **Immune response:** a quorum signal tightens and flickers its territory briefly; a reset relaxes it.

### 3.2 Inside a territory — the room grows

Diving in, **you shrink**: the room is set by what it holds, not by the orb's size (owner, 2026-10-26: "treat the
inside as almost infinite space"). The scale takes the territory's median nearest-neighbour gap up to one orb radius
(×1–×24; live "everyday" ×7). Movement, glides, the wheel, the idle drift, the stop in front of a claim and its
evidence satellites divide by the scale; claim cells and nuclei keep their size (`uRoom`), so gaps open up instead of
everything zooming; the wall stays put in the world, so from inside it moves out. **Speed follows the nearest claim:**
×0.3 beside one, up to ×4 in empty space. The hint names the room's size.

The title shows the territory's **health line**: "N claims · N from inside IRIS · N from you" (by trust channel) and
"N fading · last cleaning 3 h ago" (the decay law on the active-day clock, and the newest integrity pass). The 5
nearest claims carry labels that fade with distance; depth means sureness (surer = deeper).

### 3.3 Timeline — the helix of conversations

The hex spiral going down (owner: "really good"): each conversation (a **strand**) is a bead at its start time; date
ticks slide past like a clock face (now, today, yesterday, this week, the months); the 4 newest strands are named, the
rest on hover.

- **Threads are braids:** the strands of one thread (the snapshot's `thread`, else the fork links) are joined by a
  faint line down the helix; a **helper's amber dashed line rejoins the strand it reports to**. Hover a braid: the
  thread and its strands (live dot, helper, last activity). A strand's card also offers "⟡ its thread · N strands —
  open them round the axis" (strands made minutes apart sit at one height, so their braid line lies inside the
  beads' hover zones — the card link is the reliable way in). Open = the thread's beads spread round the axis so each
  can be picked; Esc or the same link folds them.
- **Strand card:** age · duration · outcome · #tags · what was asked · sync · tasks · "the memory gave it …"
  (recall arches from earlier steps); **click** = step inside (the corridor).
- **Turn zoom (Ctrl+wheel):** each bead opens into its turns; a turn's card names the claims it touched (§6.1).
- **Filter chips** (outcome, territory) dim what does not match, never remove it; they hide while a group has one
  value.
- **Live:** the strand a turn is writing to pulses (12 s after its last live event, then settles with one ring); a
  strand the view does not hold yet (a chat opened after it loaded) pulses as **one new bead at "now"** — click
  continues it in chat.

### 3.4 Corridor — one conversation, relived

Entering a strand assembles its corridor out of fragments (a pale void that clears in ~1.3 s). The double strand —
conversation (pink) and memory (cyan) — coils wide and slow down it; messages are shards on the conversation strand,
moments on the memory strand, claims are glyphs on stems; a failed task desyncs its stretch of wall.

- **Doorways:** the far door leads to the **next strand of the same thread** (the last returns to the timeline); a
  **helper's far door is an amber arch that reports back** — it walks into the parent strand at the moment of the
  helper's newest report; a **fork is a small arch in the wall** where a strand forked off (into its corridor, or to
  the chat when the view does not hold it); a side door returns to the thread's beginning.
- **The rail** (bottom): messages, tasks, pins and claims as marks you can click; the strand's #tags; past the
  doorway "↗ chat" (continue this conversation at its newest turn).
- **Task cards** name what IRIS did and the claims the task touched ("→ learned here · …", "→ evidence here: a test
  passed · …"); a click flies to the claim.
- **Breadcrumb:** memory › timeline › thread · X › strand · Y.

### 3.5 Artifacts — the things IRIS made

The cell tissue (owner: "happy about it"), unchanged: formats › folders › items; hover swells, click opens, Esc steps
up. A focused artifact's card says what it was made while ("→ step into that thread") and has a drag grip (§6.2).

### 3.6 Oracle — how IRIS decides

The iris of fibres around **the Oracle's own pupil** (rings of particles that turn like aperture blades and breathe).
One small local model, ONE question per run: each live decision is a ray from the consumer's sector into the pupil,
and the pupil's rim shows the probability over the offered options (the chosen one bright); enforced and acting → the
ray returns bright, shadow → it fades. Sectors are grouped by job; each consumer's fibres climb **the bar as a ladder**
(the clauses of `docs/architecture/oracle.md`), the first missing clause amber and named in words; three states kept
apart from the owner's switch (Watching · Trying out · Trusted); honest history (demotions shown); a reliability curve
on focus. The view never toggles anything.

## 4. Interaction grammar

### 4.1 Gestures, the same everywhere

| Gesture | Meaning |
|---|---|
| hover | identify — the kind first, then the thing |
| click | focus — the thing becomes the subject; its card opens with its paths |
| Enter / double-click | go in |
| Esc / Alt+← / mouse back | step out exactly one level |
| `/` | search, from anywhere |

Rules: **hover never moves the camera; click may; Enter always does.** Every focus card ends in paths — no dead ends.
The kind is said first ("claim · proven", "pin · …").

### 4.2 Keys

`?` the keys of the current view (a thin-line sheet, never a modal) · `/` search · `k` health · `s` layers · `f`
follow · `g` watch it grow (replay the time cursor) · `t` theme · Esc out. Walking: **cortex** — ← → along a claim's
frost bridges; **corridor** — ← → claim to claim, Shift+← → turn to turn, Tab to the far doorway; **timeline** —
← → strand to strand, ↑ ↓ a day. Coach marks (hover · click · Esc · ?) show once per viewer. No shortcut fires while
typing anywhere in the app.

### 4.3 Cards

Hover intent 80 ms; a card stays 250 ms after the pointer leaves and while the pointer is on it, so its links are
reachable; a card never covers the thing it describes (leader line, side chosen away from it). The claim card is a
**cell** centred on its claim; its first and last rows stay narrow so the text sits inside the curved edge; a long
title stops at 4 lines with "…" and the full text on hover. Two links on one card never run together. Text reveals
with a scramble on **words only** — digits always show their real value.

### 4.4 The key (bottom right)

Legend, filter and help in one: a count beside each kind in the current scope, a click isolates a kind, "? keys" at
its foot. In the tidy view it shows icons and counts; the words appear on hover.

## 5. Transitions

- **Every flight ≤ 1.2 s** (the dive and the way out included).
- **Any input ends a flight at once:** a click, the wheel or a key lands the camera where it was going and runs the
  flight's own end step (so the state is the same as after a full flight); then the input acts — the new input wins.
- **Long jumps pass a fragment tunnel:** a jump to a claim in another view or territory (search, a deep link, a card's
  path) plays fragments rushing past, pale at the heart, while the move happens beneath and every flight lands at once
  (min 0.52 s, max 2.4 s); never a black frame. Live: timeline → a claim elsewhere, focused at 543 ms, tunnel gone at
  891 ms (was ~2.6 s of flights).
- **Into a corridor:** a pale void, then assembly; out: the reverse.
- **Reduced motion:** cuts or a 200 ms pale cross-fade instead of flights and tunnels; no auto-drift; pulses become
  brightness changes.

## 6. Moving between things

### 6.1 Paths

| Focused | Paths |
|---|---|
| claim | where it was learned (corridor) · every time it was used (recall arches on the helix; the newest use in chat) · step into that strand · ask IRIS about it (a `#claim` chip in the composer) · pin it · that's right · that's wrong · forget this · drag to the chat |
| strand | step inside · continue in chat · its thread (fan) · what memory gave it (arches) · rename · pin thread · forget what IRIS learned here · purge its words · drag · link |
| turn / task | the claims it touched → the claim · open in chat at this turn |
| thread | its strands round the axis · (rename / pin from any of its strands) |
| helper strand | reports back → the parent strand at the moment of the report |
| artifact | open · step into the thread it was made in · drag to the chat |
| pin | what it holds · the strand it was pinned in |

### 6.2 Chat ↔ memory

One event each way. **Chat → memory:** `iris:card_action {action: "open_memory", focus}`, focus one of
`strand:<id>` · `turn:<conversation>:<turn>` · `thread:<id>` · `claim:<id>` · `artifact:<id>` · `lens:<view>`.
Entry points: the chat header's ◉ menu "Memory" (this strand's corridor); the strand map's ◎ per strand; the thread
orbit — Alt+click, or the front thread's ◎ (the braid, fanned); a turn's memory button and the matrix memory line
(`turn:…`); the artifact lens's "In memory". From an open chat, the memory opens beside it.
**Memory → chat:** `iris:open_conversation {conversationId, turnId?}` (continue in chat, open at a turn, the rail's
↗ chat, a fork or helper not in view); "ask IRIS about it" and **drag** put a reference chip in the composer — an
address and a label, never the content (`application/x-iris-ref`; a claim arrives as kind "knows"). The composer's
`#` list has a group "IRIS knows" (claims from the memory search).

**Helper strands.** In the chat's strand map a new strand can **help** the open strand (`reports_to`), and a helper row
has **↩ report back**: its newest IRIS answer (or a text) becomes a message in the strand it reports to, marked
`source = "strand_report:<helper>"` — that message's time IS the report moment the corridor's arch walks to.

### 6.3 Deep links

"⧉ link" in the breadcrumb copies `<app>/?memory=<address>` (the same addresses as §6.2: ids, never content). The app
opens such a link on load (then drops it from the URL) and catches a click on one anywhere in the app — a chat
message, a pin — and opens the memory in place. If the clipboard refuses, the link text is shown to copy by hand.

### 6.4 Search

Text only, built for the memory, not like a web search (owner, 2026-10-21). It searches what the memory holds —
claims (live and cleaned), steps, moments, turns, pins, artifacts, nodes, strand titles and tags — with all words
required, word-prefix matching, quoted phrases, and facets in the memory's own words (`proven` · `learning` ·
`contradicted` · `pinned` · `cleaned` · `kind:` · `in:` · `territory:` · `from:you|test|finished|held-up|reviewer|iris`
· `failed` · `helped` · `before:` / `after:` · `outside` · `eval`). It **ranks by the memory's own law**:
`rank = match × kind × strength`, strength = alive (decay on the active-day clock) × proven (the evidence ladder) ×
used × trusted (Kyudo channel) × your word; cleaned claims last, saying how they were cleaned. Every result says why
it ranks there in one line. While you move through results the scene previews without moving the camera; Enter
goes there. Never counted as a recall.

### 6.5 Time

One time cursor for all views (default now): set it to a past day and the cortex shows the memory as it was, the
helix centres on that day; the breadcrumb shows the date in amber with "now ↻"; `g` plays it forward.

## 7. While IRIS works — the live grammar

| IRIS does | What the user sees |
|---|---|
| a turn runs | the breadcrumb's live dot (12 s after the last live event); the strand's bead pulses; a strand not in view pulses as a new bead at "now" |
| memory is delivered to a step | **inward:** a spark from the claim (or its territory) to the core; the claim wakes |
| a step records a moment | **outward:** a spark from the core to its territory; the skin flashes |
| the Oracle decides | **ray:** in the Oracle view a ray into the pupil and the distribution; elsewhere the ticker |
| a claim is activated / promoted | it wakes / graduates (a ring) |
| a new claim crystallizes | **assembly:** rings close in on the territory IRIS is working in; "a new claim crystallized" in the ticker |
| Kyudo dissolves or merges a claim | it dissolves; the next snapshot shows its ghost |
| a quorum signal | a short tightening and flicker of the territory, then a resettle |
| the turn ends (its moments stop) | the strand's bead settles with one soft ring |

Rules: emphasis follows the **evidence ladder** (user evidence strongest, none faintest) — the single most important
visual rule; at most 6 effects at once, the rest summarised in the ticker; nothing builds brightness; **follow mode is
on by default** (`f` or the toggle turns it off, remembered per viewer) and pauses 20 s on any input. Do not
overclaim: a recall "helped" only means the step it was given to was verified.

## 8. Health, trust and corrections

### 8.1 Health

The territory health line (§3.2), the health view and ghosts (§3.1), the membrane and fading (§3.1), "last cleaning".
A claim the integrity pass cleans while you look at it dissolves in place and says why.

### 8.2 Words for health

"N fading" uses the memory's own decay law (computed on the active-day clock, never written back); "nothing fading"
is a real reading when no claim has lost 15% of its score. Dissolution reasons come from Kyudo, in plain words.

### 8.3 Corrections (v1)

All through `POST /api/memory/correct {action, target, reason?}`; the backend writes USER evidence (channel 3) through
its single writer, types a memory event, and the surface updates from that event (never optimistically). Every
correction is undoable for 10 minutes and listed under **your corrections** (hidden in the tidy view when there are
none). A correction applies from the next turn.

| Target | Action | In memory |
|---|---|---|
| claim | That's right | user evidence added; may promote |
| claim | That's wrong | a user contradiction; demotes; Kyudo may dissolve it at its next pass |
| claim | Forget this | absorbed with "forgotten by you" (never a row delete); out of recall |
| claim / moment / turn / step / artifact | Pin / Unpin / Hold / Release | the pin store's own methods |
| strand | Forget what IRIS learned here | claims whose only evidence came from it are dissolved; its events marked forgotten |
| strand | Purge its words | text replaced by "[removed by you]", structure kept; irreversible; asks twice |

## 9. HUD and layout

### 9.1 Tidy view (default) and full view

Owner, 2026-10-26: "a lot of text, a bit messy". **Header:** the brand; the path on one line (memory › view ›
territory / thread › strand › claim, with the live dot); ONE action row — the common actions always (continue in
chat, as of <date> · now ↻, ⠿ drag, ⧉ link), the rarer ones behind "⋯ more" (rename, pin thread, forget, purge);
the counts as one line ("N claims · N moments · N strands ▾", ▾ for the rest: fragments, things made, pins, nodes,
fps, source); the **◐ tidy / ◑ full** switch (remembered per viewer). **Tidy folds** what you read once: the key's
words (hover shows them), the older ticker line, an empty corrections line, the key hints after 7 s (hover brings
them back). The title sits below the action row.

### 9.2 Narrow

The memory usually sits in a ~470 px dashboard pane, so the narrow layout follows **the panel's width** (a container
query, `container-type: size`), not the window's: one column, the counts and hints hidden, the footer stacked so
nothing overlaps the view tabs.

### 9.3 States

Loading: "the memory is assembling" (a cold read can take seconds). Backend unreachable: "the memory is resting" with
try again — never a blank or black screen. Empty: "Nothing remembered here yet — use IRIS and it will grow". A
deleted strand is a **ghost** (its name kept by its tombstone). Memory that never came from a chat is "outside chat"
with its source; evaluation runs hidden by default.

### 9.4 Words

The words are: thread, strand, turn, step, moment, claim, pin, node, artifact ("session" is retired). Never show the
internal word:

| Internal | The user reads |
|---|---|
| landmark, tier candidate / landmark | claim · still learning / proven |
| memory_chain / memory_events | timeline · what happened |
| valence advances / sets_back | helped / set back |
| evidence user · test · completion · recurrence · corroboration · verifier · claim · none | you confirmed this · a test passed · the task finished · it held up again · an independent source agreed · the reviewer checked it · IRIS reported this · unconfirmed |
| Oracle enforced · sampled · shadow | Trusted · Trying out · Watching |
| LANDMARK_PROMOTED · CORRECTION | IRIS is now sure about this · you corrected IRIS |

Relative time on the face ("2 h ago"); every number has a plain meaning beside it.

## 10. Data and live path

### 10.1 Rules

Read-only connections (`mode=ro`), every store path through `resolve_memory_store_path`; every read LIMIT-bounded and
indexed (EXPLAIN QUERY PLAN in the comment above it); off the event loop; never on the answer path; never counted as a
recall; no blobs or embeddings to the frontend; epoch-second timestamps; optional tables read as "none", never an
error.

### 10.2 Endpoints

`/api/memory/snapshot` (the whole model the scene draws) · `/overview` (counts, territories, last integrity pass —
the health read) · `/claims`, `/claims/{id}`, `/claims/{id}/uses` · `/threads` · `/strand/{id}` ·
`/turn/{conversation}/{turn}` · `/search` · `/oracle` · `POST /correct`, `/correct/undo`, `GET /corrections`.
Chat side: `/api/threads`, `/api/threads/{id}/strands` (GET, POST with `reports_to`), `PATCH /api/strands/{id}`,
`POST /api/strands/{id}/report`, `PATCH /api/threads/{id}`.

### 10.3 The snapshot (keys the page reads)

`meta` {source, generated, counts, eval_share, warnings, available, **last_integrity_pass**} · `famCounts` ·
`domCounts` · `sessions` (one per strand: id, objective, started, ended, exit, traj, eval, episodes, messages {role,
ts, text preview, len, **report**}, strands (forks), ghost, **thread**, **tags**, **reports_to**, **reports**) ·
`events` · `landmarks` (… evidence, activations, contradictions, channel, **fading**, steps, domain) · `edges` ·
`episodes` · `artifacts` · `oracle` · `mind` · `sectors` · `pins` · `spaces` · `nodes` · `nodeEdges` · `quorum` ·
`recalls` · **`ghosts`** (claims dissolved in the last 7 days, with the reason). The newest 48 threads are held;
older memory is reached by search. Pinned by `backend/tests/contract/test_memory_snapshot_contract.py`;
`export_snapshot.py` (this folder) is a thin command-line tool over the same function.

### 10.4 Live

WebSocket `memory_event` (each typed event, with thread and episode), `landmark_update` (activated · promoted · stale
· demoted · dissolved · merged · **crystallized**), `oracle_decision` — broadcast from the existing single writers
(`backend/utils/memory_live.py`), coalesced, never a new writer. Recall deliveries and integrity passes ride
`memory_event` (RECALL_*, LANDMARK_DISSOLVED / MERGED, MEMORY_PRUNED).

### 10.5 Ids contract

Every memory row typed during a chat turn carries `thread_id = <conversation id>` and
`episode_id = "<conversation>:<turn>"`; a chat turn's episode is filed under its conversation; claims learned in a
chat record the conversation as their evidence source (so forgetting that chat absorbs what only it taught). One
resolver maps a thread id to a strand, a ghost, "outside chat" or "built in at the start".

### 10.6 Edge cases (numbered as cited in code)

1 a strand deleted in chat keeps its memory and its name (tombstone `STRAND_DELETED` / `STRAND_RENAMED`) → a ghost ·
2 a deleted thread root → a ghost braid · 3 a helper whose parent is gone reports to "a deleted strand" · 4 memory not
from a chat → "outside chat" (evaluation hidden by default) · 5 thread id ≠ conversation id → the one resolver ·
6 "where it was learned" → strand, ghost, outside chat or "built in at the start" · 7 a link to a cleaned claim →
its survivor along the merge log, or the cleaning and its reason · 8 a renamed strand → the current title everywhere ·
9 Esc: the surface handles it first while it can step out; at the top it closes the dashboard · 10 the tilted wing
breaks picking → opening Memory asks for the spotlight (flat) · 11 two windows → links cross by Tauri event · 12 no
frame drawn while unseen; GPU resources disposed; a lost context restored · 13 no shortcut while typing · 14 the
brand palette, live · 15 a correction applies from the next turn · 16 every read LIMITed and indexed · 17 live floods
coalesced, ≤ 6 effects · 18 backend down → "resting", never blank · 19 a growing strand assembles at the far end, your
place kept · 20 a claim cleaned while seen dissolves in place, says why · 21 a correction on a merged claim lands on
its survivor · 22 the time cursor in the past → no live effect, "now" pulses · 23 one time parser for epoch and
text times · 24 very long threads page by turn · 25 deep links carry ids, never content · 26 reduced motion and full
keyboard · 27 any script in titles · 28 an empty memory → a calm, true empty state · 29 an older store missing
optional tables → "none" · 30 shader safety: no `pow(` with a negative base, no `asm` as a name; a black-frame check.

## 11. Budgets and standards

| What | Budget / measured |
|---|---|
| cold snapshot | 1.5 s on the SSD (was 404 s on the hard disk) — S121 |
| warm snapshot | ~0.2–1.3 s |
| flights | ≤ 1.2 s; any input lands them |
| long jump | ≤ 0.9 s through the fragment tunnel |
| GPU | DPR ≤ 1.6, dropped under 28 fps; nothing drawn while hidden |
| live effects | ≤ 6 at once; brightness never builds |
| inside room | ×1–×24 by claim spacing |
| logs | `logs/iris.log` ≤ 256 MB (S124) |

The surface only reads, off the answer path: an evaluation run with it open must show no change in reply time.

## 12. Code map

| Where | What |
|---|---|
| `components/memory/MemorySurface.tsx` | the surface root: loading / resting / empty states, live forwarding, focus requests |
| `lib/memory/scene/engine.ts` | the scene: all views, grammar, cards, paths, live grammar, tunnel, tidy HUD |
| `lib/memory/scene/markup.ts` | the HUD markup and styles (scoped to `.iris-memory`) |
| `lib/memory/api.ts` | the typed client (`fetchMemorySnapshot` retries a cold first read) |
| `backend/api/memory.py` | `/api/memory/*` |
| `backend/memory/surface_queries.py` | every SQL statement of the surface, read-only, EXPLAIN-checked |
| `backend/memory/corrections.py` | corrections and undo |
| `backend/utils/memory_live.py` | the live taps |
| `backend/conversation_store.py` | strands, `reports_to`, `report_back` |
| `components/chat/header/StrandMap.tsx`, `ThreadOrbit.tsx`, `ChatHeader.tsx` | the chat's ways into the memory; helper + report back |
| `components/chat-view.tsx`, `components/chat/composer/refs.tsx` | memory → chat: open a conversation, reference chips, drops |
| `app/page.tsx` | routes `open_memory`, opens deep links |

## 13. Next levers (not built)

The design is complete; the largest remaining gains are in the **data the design shows**, not in the design:

1. **Claims have no territory.** Every claim in the snapshot is "general" (landmarks carry no domain; ~90% of events
   resolve to "general"), so the cortex cannot yet show what IRIS knows *by topic*. When claims land in real
   territories, every cortex feature gains meaning at once. Tied to the owner's open decision on how sectors are born
   (pin: births only after a Kyudo reorganization).
2. **Recall events do not name the claim they delivered**, so "what memory gave this turn" and "every time it was
   used" join by time window. Carrying the landmark id on `RECALL_*` events makes them exact.
3. **The view holds the newest 48 threads**; older ones are reached by search only. Loading a thread on demand makes
   the timeline the whole history.

Polish beyond the plan, in a simpler form today: claim arches per use and frost-bridge walking; the focused object
travelling between views (the camera flies instead); a recorded back stack (Esc steps one structural level); the
Oracle's acting side as a split sector; graduation and dissolution as fragments; a grab cursor, loading fragments,
"show more", a reduced-transparency mode.

## 14. Reference map (the removed documents → this one)

**`UX-PLAN` (MEMORY-UX-PLAN.md):** 1 → §1 · 2 → §1 · 3.1 → §4.1 · 3.2 → §6.1 · 3.3 → §4.2, §4.4 · 4.1 → §9.4 ·
4.2 → §10.5 · 4.3 → §3.3 · 4.4 → §3.4 · 4.5 → §6.2 · 4.6 → §6.2 · 5.1, 5.2 → §6.4, §6.5 · 5.3 → §6.3 · 6.1 → §5 ·
6.2 → §4.2 · 6.3 → §7 · 6.4 → §9.4 · 7.1, 7.2 → §3.1, §3.2 · 7.4 → §6.1 · 7.5 → §3.1 · 8.3, 8.4, 8.5 → §3.3 · 9.x → §3.6 ·
10 → §10 · 11 → §1, §6.4, §7, §9.4 · 11.3 → §9.3 · 12 → (phases, all done) · 13 → §4.3, §9.

**`SURFACE-BUILD` (MEMORY-SURFACE-BUILD.md):** section 1 → §10.1 (measured facts) · section 2 → §6.2 · section 3 →
§6.4 · section 4 case N → §10.6 item N · section 5 → §8.3 · section 6 → §12 · section 7 / phase 0 → §10.

**`DASHBOARD-DESIGN` (MEMORY-DASHBOARD-DESIGN.md):** §1–3 → §1, §10.1 · §4.2 → `EVENT_TAXONOMY.md` · §8.1 → §3.6 and
`docs/architecture/oracle.md` · §10 / §10.1 → §10.4 · §11 → §7 · §12 → §9.4 · §13 → §4 · §15 → §10.1 · §16.4–16.7 →
§3, §11 · §17 → §3.1 · §18 → §2.

**The mockup** (`index.html`, a single-page port source of `lib/memory/scene`) was removed with these documents; the
engine is the reference now. `index.html?real` data came from `export_snapshot.py`, which remains as a command-line
export of the same snapshot.
