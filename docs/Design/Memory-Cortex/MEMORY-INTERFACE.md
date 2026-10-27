# IRIS Memory — the interface and its foundation (final)

**Status: FINAL (2026-10-27).** This is the one document for IRIS's memory: **Part I** (§1–§14) is the memory
interface (the Memory surface of the dashboard); **Part II** (§F0–§F16) is the memory foundation it shows (folded in
from `MEMORY-FOUNDATION-ANALYSIS.md`). It replaces three working documents that were removed on 2026-10-27:
`MEMORY-DASHBOARD-DESIGN.md` (the first design, 2026-10-13 → 10-19), `MEMORY-SURFACE-BUILD.md` (the build plan,
2026-10-21) and `MEMORY-UX-PLAN.md` (the functional UX plan, 2026-10-21 → 10-27, closed DONE). Code comments still
cite them as `UX-PLAN 4.3`, `SURFACE-BUILD section 4 case 9`, `DASHBOARD-DESIGN §18`: **§14 maps every cited section
to this document.**

Read with: Part II below (the memory system itself: sectors, spaces, the growth/decay law, Kyudo, integrity — the
interface only shows it), `docs/Design/EVENT_TAXONOMY.md` (the closed event alphabet),
`docs/architecture/oracle.md` (the decision engine the Oracle view shows), `docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md`.

The memory this interface shows is the APP memory: the store resolved by `resolve_memory_store_path`
(`D:/IRIS/store/memory.db` since 2026-10-26) and `data/conversations.db`. It never shows the MCM build memory.

---

# Part I — The interface

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

**A turn names the claims it used** (2026-10-27): at the turn's end the claims Mycelium activates
(`observe_landmark_use`) are typed as `RECALL_USED`, one per claim (at most 8), `links.landmark_id` = the claim,
`episode_id = "<conversation>:<turn>"` (`Episode.turn_id`), on the memory_events lane, never in the chain
(`memory_events.record_claims_used`). `/claims/{id}/uses` reads them as exact uses (a use the episode index also
holds counts once), and a turn's card says "used here". Live: one coding turn typed 6 claims; the episode index
held 0 rows for them. Guards: `test_event_emitters_memory_contract.py`, `test_memory_claim_uses_contract.py`.

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

1. **Coding claims have no territory of their own** (measured 2026-10-27, owner decision: keep "general" for now).
   A claim's territory is the root of its best sector (`mycelium_landmark_sectors`); 229 of 259 live claims have one
   (data 48, web 40, hardware 5, finance 3, systems 2), 30 are the bootstrap seeds. The 131 in "general" are coding
   tasks ("make test_roman.py pass", "fix the geometry package"): the topic list (`extractor._DOMAIN_KEYWORDS`, 13
   closed values) has no value for general software work, so "general" is the true reading. Their sub-sectors
   (general/evals, /appdata, /iris) are the weak word-recurrence sectors. The fix is one new closed value (e.g.
   "software": python, tests, bug, function, refactor, script) — a change to a closed lattice and its coordinate ids,
   and a new root, so it waits for the owner's design of sector births (only after a Kyudo reorganization).
2. ~~Recall events do not name the claim they delivered~~ — done 2026-10-27 (§10.4: `RECALL_USED` per claim used).
3. **Recall reached only the newest 200 chunks of its filter** — reach done 2026-10-27 (S128: fingerprints, recall@10
   0.90-0.975 vs exact search); honest vectors, exact words, compression, budgets and memory-native ranking are
   specified in `specs/memory-recall-reach/` and measured by `evals/memory_bench.py`.
4. **The view holds the newest 48 threads**; older ones are reached by search only. Loading a thread on demand makes
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

**`MEMORY-FOUNDATION-ANALYSIS` §n** (the folded-in analysis) → Part II §Fn of this file (same numbers, with an F).

**The mockup** (`index.html`, a single-page port source of `lib/memory/scene`) was removed with these documents; the
engine is the reference now. `index.html?real` data came from `export_snapshot.py`, which remains as a command-line
export of the same snapshot.

---

# Part II — The memory foundation (analysis and growth design)

> Folded in from `MEMORY-FOUNDATION-ANALYSIS.md` on 2026-10-27 (owner: one file). The text is unchanged except
> the headings, which carry an **F** so they never clash with Part I: a bare `§n` inside Part II means `§Fn` here;
> code that cites `MEMORY-FOUNDATION-ANALYSIS §n` means `§Fn` (see §14).

Status: ANALYSIS + PROPOSAL for owner review, 2026-10-18. Read-only throughout: code read, live
`data/memory.db` queried with `mode=ro`, nothing written. Every number below was measured on the
live store on 2026-10-18 unless marked *code-read* (found by reading code, not run) or
*UNVERIFIED*. Part I of this file is the interface that shows this memory.

Sources: `docs/CADUCEAN_ARCHITECTURE.md`, `docs/CADUCEAN_TECHNICAL_OVERVIEW.md`,
`docs/Design/EVENT_TAXONOMY.md`, `docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md`,
`specs/wormhole-aperture/`, `specs/der-dag-inversion/ontology.md`,
`backend/memory/mycelium/*.py`, `backend/memory/event_alphabet.py`,
`backend/agent/caducean_trajectory.py`, `backend/gateway/iris_ffi.py`.

---

## F0. In one paragraph

The design is organic and coherent: one operator — *expand where outcomes disagree, compress
where they agree* — already shapes execution (split width), the session (context compression),
cross-session tuning, and the Mycelium graph (condense / expand). Growth of sectors (topic
domains) and of coordinate spaces should be that same operator, not a hand-edited list. **But the
seed is not yet alive.** On live data the coordinate graph has never been walked: 116 nodes, every
access count 0, every traversal empty, 0 routing edges, a closed maturity gate, inert resonance,
merges that zero their own scores. One closed gate near the root starves everything downstream.
So the foundation work is, in order: make the seed breathe, make the registries data-driven, then
let sectors and spaces grow by the operator — in shadow first, as the Oracle does.

---

## F1. The one idea, applied to memory

> "Compress everything that happened into one honest current position, then let moment-to-moment
> behavior be a pure, memory-free reaction to that position." (CADUCEAN_ARCHITECTURE §1)

The Caducean state Σ = (x, y, ξ, u) — expansion accumulator, compression accumulator, phase angle,
attentional velocity — is that position for the *work*. Mycelium does the same for *memory*:
thousands of outcomes become one edge score; routing reads the score, never the history. And the
graph "reshapes itself — condense merges near-duplicate nodes, expand splits a node when its
outbound hit/miss variance exceeds 0.40. That is the Caducean duality at graph scale"
(CADUCEAN_ARCHITECTURE §8).

The physics adds two rules that matter for growth:

- **Wall-pair closure.** The topological charge Q = (x − y)/(x + y + 1) must return toward 0 for a
  natural exit; "a lone kink — a session that only expands, never compresses — is topologically
  forbidden" (OVERVIEW §5). Measured: natural exits |Q| 0.53, budget exits 0.91.
- **Windings give identity.** ξ = l·x − m·y (mod 2π); each execution domain has its own winding
  (der (1,1), voice (2,1), research (3,3)) and therefore its own cycle speed
  c_eff = c·√(l² + m²). "The physics is universal; the interpretation is local."

**The organic rule for this foundation:** anything that grows (a sector, a landmark, a chain) is
born by expansion and survives only by closure through compression — outside evidence that it
holds. Anything that only expands and never closes folds back into its parent. This is the
landmark rule (candidate → proven by ≥ 2 outside-evidence sessions) generalized, and it is Q → 0
applied to structure.

---

## F2. What the memory is made of (map)

### F2.1 Seven layers of meaning, and how fast each may grow

| Layer | What it is | Today | How it should grow |
|---|---|---|---|
| **Alphabet** | closed lattices: family 9, valence 3, actor 5, evidence 8, cause 27, outcome 27, trigger (EVENT_TAXONOMY §3) | code `event_alphabet.py`, schema_version 1 | **never** — only an owner-approved schema_version bump |
| **Vocabulary** | open words: labels, tools, bars | seed labels in code, Layer 3 counts unknowns | data edits from evidence (exists) |
| **Coordinate spaces** | the profile of the user and the machine: conduct, domain, style, chrono, context, capability, toolpath — each in a Kyudo trust zone | `SPACES` dict in code + a `mycelium_spaces` table | **deliberately**: a reviewed registry row, never auto-minted (a space is a new dimension of meaning) |
| **Sectors** (topic domains) | what a thing is ABOUT: 13 registry keys (ai, web, data, devops, mobile, systems, security, finance, science, design, hardware, gaming, general) | `DOMAIN_IDS` constant; keyword classifier | **organically**, evidence-gated (§5) |
| **Modes** (execution domains) | HOW a thing runs: der, voice, research — each with its own windings | derived from the path, not text | when a new execution path exists (rare, code) |
| **Landmarks** | a claim proven true by outside evidence, anchored to a cluster of coordinate nodes | candidate → landmark → permanent; merge at Jaccard ≥ 0.5 | organically (exists, but starved — §3) |
| **Time** | Immortus chain (transitions + references), trajectories, episodes, events | append-only | by work (exists) |

The physics Σ sits across all of them: it is the *position of the work* when anything happens.

### F2.2 The word "domain" means six things

1. **Topic domain** — what a node is about (registry, 13 keys). → call it a **sector** (the
   owner's word) in docs and UI.
2. **Execution domain** — how it runs (der / voice / research, with windings). → a **mode**.
3. The **`domain` coordinate space** — the user's expertise: (domain_id, proficiency, recency).
4. The **phase domain** of the scheduler (`decision.oracle_cpu`, `execution.der_nodes`).
5. A **web domain** (a site, REQ-33).
6. The **`caducean_trajectories.domain`** column — constant `general` on all 7,089 rows (a bug, §3).

Keeping one word for six meanings is how "domains" stayed half-built: each writer meant a
different one. The registries below use *sector* and *mode*; "domain" stays only as the name of the
coordinate space.

### F2.3 How they interweave

```
event  = said in the ALPHABET, with a LABEL, about a SECTOR, run in a MODE, at a Σ position
  └ touches coordinate NODES in SPACES (through Kyudo: trust channel → zone → allowed spaces)
       └ LANDMARKS condense clusters of those nodes (≤ 6 nodes, across spaces) once proven
            └ a SECTOR is (a) a region of the domain space and (b) the set of landmarks it holds
                 └ the other SPACES describe how work in that sector happens (its profile:
                   which tools, what time, which style, which project)
```

Landmarks are the **knots** that tie sectors and spaces together: each landmark belongs to one or
more sectors (weighted) and carries a cluster across spaces. A sector's *profile* is the centroid,
per space, of its landmarks' clusters. That is the interweave, and it is what the 3D cortex draws:
territories (sectors) on the skin, neurons (landmarks) inside, tracts between them, and the
spaces as the layers a neuron's cluster spans.

---

## F3. Measured state: the seed is not yet alive

| Value | Live (2026-10-18) | Effect |
|---|---|---|
| Coordinate nodes | 116: toolpath 101, domain 7, capability 4, style 3, conduct 1, **chrono 0, context 0** | the profile barely exists |
| Node access_count | **0 on all 116** | every "most-used" choice is insertion order |
| Spaces with a node at confidence ≥ 0.6 | 2 (capability, toolpath); maturity needs 3 (`interface.py:339-356`) | **gate closed** → `get_context_path` returns "" |
| Traversals | 3,025, **path empty on all 3,025**; outcomes partial 2,649, miss 354, success 22, hit 0 | navigation never returns a node |
| Routing edges (`mycelium_edges`) | **0** | expand cannot run; decay has nothing to act on |
| Episode index | 2,841 rows, **node_ids empty on all** | resonance is inert |
| Toolpath success_rate | **one value on every node** | zero variance |
| Landmarks | 2,701 rows; max activation 3; **cumulative_score 0 on 2,581** | permanence (8) and topology origin (12) unreachable |
| Merges | 2,480; merged score = activation-weighted mean, and both activations are 0 → score 0 (`profile.py:105-111`) | every merge erases the score |
| Landmark edges | 6,628, all `similarity`, score 0.4, last_traversed NULL | never decay, never learn |
| Landmarks with a sector | 0 (no column) | the cortex cannot place them |
| Event addresses | 11,887 events → **291 distinct** addresses | address ≈ "how many steps in", not the state |
| Σ inside an event | `sigma_from = sigma_to` on all 11,887 | no event records a transition |
| Trajectory rows that never compressed | **4,068 of 7,089 have y = 0** | balance pins at its 3.0 ceiling in those sessions (formula, *code-read*) |
| u | spread −1…1, mean 0.17, 335 distinct values | u is a real signal now (good) |
| `caducean_trajectories.domain` | `general` on all 7,089 | the per-domain physics has one bucket |
| `memory_chain.coords_from` | filled on 14,318 of 29,773 | the documented "honest gap" is half closed (good) |
| Sector values | `memory_chain.topic_domain` 12 real values on ~23% of rows; `memory_events.topic_domain` NULL ~90% | sectors exist, mostly unwritten |

### F3.1 The cause chain (why it is inert)

One closed gate near the root starves everything below it:

1. **Spaces are barely fed.** Extractors are keyword-only; domain, style and conduct nodes get
   confidence 0.4; chrono and context are never written (*code-read*: `extractor.py`).
2. **Maturity gate stays closed** (2 of 3 spaces) → the context path is empty.
3. **Navigation finds no entry**: keyword-in-label fails, and the fallback wants confidence > 0.7
   but nodes have 0.4 (`navigator.py:138-145`, *code-read* line 414).
4. → **access_count never rises** → condense survivors, landmark top-6 clusters and merge
   survivors are chosen by insertion order.
5. → **landmark activations stay 0** → **merges zero the score** → permanence and topology origins
   are unreachable → charts, Z-trajectory and staleness are dormant.
6. Separately: **0 routing edges** (likely the compounding decay below, *UNVERIFIED cause*) →
   expand never runs, so the graph cannot grow by the operator at all.

### F3.2 The physics → memory couplings

- **u → decay is inert in production.** `apply_decay` modulates only when given a session; all
  three production callers of `run_maintenance()` pass none, so the multiplier is always 1.0
  (`scorer.py:236-249`; `memory/interface.py:611`, `main.py:1166`). CADUCEAN_ARCHITECTURE §8
  still marks it PROVEN.
- **Decay compounds.** Each pass subtracts `rate × days_idle` measured from `last_traversed`, and
  never moves `last_traversed` (`scorer.py:268-289`) — every pass re-subtracts the whole idle span.
- **EML → recall breadth** works (PROVEN), but balance pins at 3.0 whenever min(x, y) = 0, which
  is true for 57% of trajectory rows.
- **Σ → document address** is now half populated (coords_from 48%).

---

## F4. Contradictions to resolve first

1. **Are sectors hashed?** EVENT_TAXONOMY:54 says not; `event_alphabet.py:203` and Wormhole REQ-1
   hash them.
2. **Two sector registries**: `spaces.py:89-103` vs `docs/Mycellium Specifications.md:889-903`
   (different keys). The code list is the live one; the spec is stale.
3. **"Landmark" has three definitions** (activation-12 "never decays" in the Mycelium guide; a
   proven claim in the taxonomy; demotable/stale in CLM). The proven-claim definition is the one
   the code enforces.
4. **"Beta-Bernoulli" edges** (Wormhole REQ Decisions 2) vs the additive delta in `scorer.py:55-59`.
5. **NaN ξ or u crashes the address writer**: `int(nan)` raises outside the `try`
   (`event_alphabet.py:201-203`); the spec says "write unhashed".
6. **"hash_signature" names three different hashes** (state, event address, chain sequence).
7. `RECALL_AS_COGNITION.md` claims live integration; RecallPhases has no production caller.

---

## F5. Growth design (proposal)

### F5.1 Sectors as a living registry

**Shape (data, not code):**

- `mycelium_sectors(sector_key PK, parent_key, label, status, born_at, born_from, alias_of,
  members, outside_evidence, last_activity)` — `sector_key` is a stable text path
  (`systems/memory/recall`), **never** a number. `status ∈ {candidate, proven, dissolved}`.
- `mycelium_landmark_sectors(landmark_id, sector_key, weight, source)` — a landmark belongs to one
  or more sectors with a weight; `source ∈ {rule, cluster, user, oracle}` (only rule and user are
  evidence — EVENT_TAXONOMY §6).
- Seeded with the 13 registry keys as proven roots. The `domain` space's `domain_id` axis stops
  being `id/12` (which breaks at the 14th key); it stores a stable ordinal from the registry, and
  the 3D layout reads territories from the registry, never from that float.

**Lifecycle — the one operator:**

| Step | Operator | Rule (start values; tune by measurement) |
|---|---|---|
| **Birth** | expand | items that land in `general` (or a parent) and share terms recur in ≥ 3 sessions → a *candidate* child sector, in shadow |
| **Closure** | compress | a candidate becomes *proven* when it holds ≥ 2 landmarks with outside evidence from ≥ 2 sessions — the same gate as landmark promotion; the wall-pair closes |
| **Split** | expand | a proven sector whose landmarks' outcomes disagree (variance > 0.40, the node-expand threshold) splits into children |
| **Merge** | compress | two sectors whose landmark sets overlap ≥ 0.5 (the landmark-merge threshold) merge; the absorbed key becomes an **alias** so old addresses still resolve |
| **Dissolve** | fold-back | a candidate that only expands for a set time without closure folds back into its parent — a lone kink is forbidden |

**Bounds (growth has a budget):** depth ≤ 3, a cap on children per parent, candidates expire,
every transition is a `memory` event (`LANDMARK_*`-style labels: `SECTOR_BORN`, `SECTOR_PROVEN`,
`SECTOR_SPLIT`, `SECTOR_MERGED`, `SECTOR_DISSOLVED` — new *labels*, no new alphabet values).

**Trust (Kyudo):** only channels admitted to the TOOL zone may create a candidate; untrusted web
content may propose but never close a sector; the 30% untrusted cap applies to a sector's
evidence as it does to a landmark cluster.

**Shadow first:** sector assignment runs in shadow and is measured (precision of membership,
churn, false births) before any consumer reads it — the Oracle's own discipline.

**Landmark sector at creation (the immediate fix):** at `LandmarkCondenser.condense`, assign from
(1) `resolve_topic_domain(task_entry_label)` (the rule path research memory already uses), else
(2) the `domain` nodes in the landmark's own cluster (weighted), else `general`; backfill the live
landmarks with the same rule once, idempotently.

### F5.2 Coordinate spaces as an open registry

- The `mycelium_spaces` table becomes the source of truth. Each row declares: axes, ranges, decay,
  **Kyudo zone (required)**, render order, resonance participation, extractor, schema version.
- Everything hard-coded today is derived from it (each is a silent blocker for an 8th space —
  *code-read*): `_SPACE_ORDER` (`scorer.py:31-39`, a new space would never condense or expand),
  `RENDER_ORDER` and the renderer map (`profile.py:399-406`), `RESONANCE_SPACES`
  (`spaces.py:188-190`), `TASK_CLASS_SPACE_MAP` (`kyudo.py:525-532`), literal space names in
  `navigator.py` and `topology.py`.
- **Kyudo fails closed**: a space with no zone is refused, not filed in the REFERENCE zone
  (`kyudo.py:139` is fail-open today).
- **Per-space distance scale**: dedup 0.05 and condense 0.04 are global, so chrono (0–24) and
  capability (0–5) dominate distance; normalize each axis by its declared range.
- **A new space is added deliberately**, by a reviewed proposal, never minted — it is a new
  dimension of meaning. Sectors grow organically *inside* the spaces.

### F5.3 Addresses that survive growth

- Hash a sector's **root** plus the scheme version, and carry the refined path as a separate
  field; refining `systems → systems/memory` must not move an address.
- Do not hash raw step counts. Hash the *state*: e.g. the charge Q (binned), log-binned work
  volume, ξ and u bins. Decide this before Wormhole Stage A, with a lazy re-file (REQ-10).
- Make the NaN path return "unhashed", as the spec says.

---

## F6. Caducean Σ as the visual expression of the cortex

Each visual must be driven by the real value (a computed signal must change behaviour, and must
have a sane value — CLAUDE.md "hidden failures").

| Physics | Meaning | In the cortex | In the timeline (synapse view) |
|---|---|---|---|
| **x** expansion accumulator | generative work | the organism inhales: tissue extends, buds (candidate neurons / candidate sectors) appear | fibres fan out, the passage widens |
| **y** compression accumulator | validation / consolidation | exhale: tissue tightens, merges and absorptions are visible | fibres bundle tighter, the passage narrows |
| **ξ** phase angle | position in the cognitive cycle | the rotation phase of the inner shells and of the skin's pulse bands | the twist phase of the fibre bundles |
| **u** attentional velocity | momentum, explore (+) / compress (−) | flow direction (outward / inward); trails persist longer at u > 0, fade faster at u < 0 (the decay coupling, once live) | pulse speed along the fibres |
| \|u\| bands (0.5 / 0.85) | split zone / converged | a fan-out of sparks when \|u\| < 0.5 | the fibre bundle splits and folds back |
| **Q** charge | wall-pair balance | the two serpents of the caduceus: equal = closed, one dominant = strain | the closing of the passage at a natural exit |
| **balance / EML** | phase advance rate | breathing rate | travel rhythm |
| **c_eff** (windings per mode) | cycle speed of der / voice / research | — | each mode's threads twist at their own rate |
| band crossing | "settling" / "re-opening" | one pulse across the lattice | a synaptic release |
| TOPO violation | topological drift | an immune response: the quorum reorganization (Kyudo) | the passage tightens and flickers |

**Precondition:** the values must be honest first — events must record Σ transitions
(`sigma_from ≠ sigma_to`), and the 57% of sessions that never compress must be explained (are
those steps really all expansion, or is the classifier missing consolidating calls?).

---

## F7. What we have not yet considered (prioritised)

1. **The graph has never been walked** (§3.1). Nothing grows on it until the maturity gate, entry
   matching and access counting work. Highest priority.
2. **Merges erase scores** — fix: plain mean when both activations are 0.
3. **Decay**: pass the session's u (or the last settled position) into maintenance; decay
   incrementally from a `last_decayed_at`, not from `last_traversed`. Then measure why there are
   0 edges.
4. **Events carry no Σ transition**: write the before and after positions.
5. **The address is a step counter**: change what is hashed before Wormhole is built on it.
6. **"Domain" × 6**: adopt *sector* / *mode* in docs, specs and UI.
7. **Registries are code**: move sectors and spaces into tables (§5.1, §5.2).
8. **Zero-variance values**: toolpath success_rate, domain proficiency 0.5 / recency 1.0, landmark
   edge score 0.4 — each needs a real input or must stop being drawn.
9. **Episode index never records nodes** — resonance cannot work until it does.
10. **Growth budgets**: `caducean_trajectories` has no retention; sector minting needs bounds
    (§5.1); toolpath windows per session are unbounded (*code-read*).
11. **Kyudo zone default is fail-open** (§5.2).
12. **The hive network** (GOALS §7b): sector keys must be stable, versioned text so peers can read
    them; a remote sector enters only as a candidate and closes only on local evidence.
13. **Docs out of date**: CADUCEAN_ARCHITECTURE §8 (decay PROVEN), RECALL_AS_COGNITION, the stale
    sector list in the Mycelium specification, the "five" topology primitives (there are six).

---

## F8. Order of work (foundation first)

| Phase | Goal | Done when (measured) |
|---|---|---|
| **0 Measure & guard** | a curation/liveness report over the live store (the numbers in §3) | the report runs and each value has a guard that fails on today's state |
| **1 Make the seed breathe** | maturity, entry matching, access counts, merge score, decay, Σ transitions, episode-index nodes | traversals return nodes; access counts vary; merged scores ≠ 0; events record transitions |
| **2 Registries as data** | `mycelium_sectors` + landmark membership; spaces table as source of truth; Kyudo fail-closed; landmark sector at creation + backfill | every live landmark has ≥ 1 sector; an 8th test space works end to end in a test store |
| **3 Organic sectors, in shadow** | birth / closure / split / merge / dissolve running in shadow | precision and churn measured over real sessions |
| **4 Visuals on real values** | the cortex reads registries and Σ, not synthetic layout | every visual in §6 varies with its value on real data |
| **5 Hive-ready keys** | versioned, shareable sector keys; remote = candidate | — (later, GOALS §7b) |

## F9. Decisions (owner, 2026-10-18)

1. **Sector** (topic domain) and **mode** (execution domain): ADOPTED.
2. Sector registry + weighted membership + lifecycle: APPROVED, **in shadow mode** until its
   structure and place in the system are verified.
3. Growth speeds (alphabet never, spaces deliberately, sectors organically, labels as data): AGREED.
4. Make the seed live first: AGREED.
5. Change the event address, and build whatever else makes `specs/wormhole-aperture` easier to
   implement later: APPROVED.

## F10. Work order (approved 2026-10-18) — each item carries its scope bound

Method: CLAUDE.md "BUILD + VERIFY IRIS — THE MEASURED LOOP". Targeted tests only; a guard that
fails on the old state for every measured fix; values checked on the live store read-only.

| # | Item | DONE = | NOT THIS = |
|---|---|---|---|
| W1 | **State address v2** (`event_alphabet.hash_signature`, scheme 2): x, y enter as the charge Q (5 bins) and the work volume (log2, 6 bins), not raw counts; ξ and u bins kept; the sector ROOT and the mode; NaN or inf → no address (logged, counted); a `hex_bin_id` minted from the same quantized state (Wormhole REQ-2 AC1; Tier-1b querying stays deferred) | new events carry scheme 2 + a hex bin; addresses no longer grow with step count (guard); NaN cannot raise | no bulk re-hash of old rows (REQ-10 AC4); no Tier-1b lookup; no hyperedges |
| W2 | **Σ transitions on events**: every writer passes the position before AND after the step | `sigma_from ≠ sigma_to` where the step moved Σ (guard) | no new Σ source; reuse the DER lane's before/after |
| W3 | **Merge keeps the score** (`profile.py`): plain mean when both activations are 0 | a merge of two unactivated landmarks keeps a non-zero score (guard) | no backfill of the 2,480 historical merges in this item |
| W4 | **Decay = the counterpart of growth (§11)**: incremental from a `last_decayed_at`; the evidence weight a(n) on decay as on growth; Kyudo channel and Caducean phase multipliers; node confidence decays to the stated floor; landmark edges on the same law; the reorganization is the law at m_quorum | two passes subtract once (guard); young and old beliefs cross at the same use frequency (guard); the phase multiplier varies on live data (measured 0.68-1.37 per day) | no change to the base rates or the prune threshold |
| W5 | **Why 0 routing edges** (Wormhole spec U3 / S54): find where the region-mediator write goes and fix it | a DER node step writes a `mycelium_edges` row on the live app (measured) | no new edge model (Beta posteriors are Stage A) |
| W6 | **The graph walks**: confidence grows with repeated observation; entry matching reaches the nodes that exist; spaces that are never fed get their feed | live traversals return nodes; access counts vary; maturity measured honestly | no lowered thresholds as the fix; no fake nodes |
| W7 | **Episode index records nodes** (follows W6) | new index rows carry node ids | — |
| W8 | **Caducean `domain` constant**: the trajectory row takes the node's real sector | trajectories show more than one sector on new rows | — |
| W9 | **Sectors, shadow mode**: `mycelium_sectors` + `mycelium_landmark_sectors`; landmark sector at creation (rule, then cluster, then `general`); idempotent backfill; lifecycle (birth / closure / split / merge / dissolve) computed and LOGGED, consumed by nothing | every live landmark has ≥ 1 sector; lifecycle decisions measured over real sessions | no consumer reads sectors yet (shadow); no auto-created space |
| W10 | **Spaces registry** as the source of truth. Each row declares its Kyudo terms (§12.3): write lock (the lowest channel that may write), render zone, subagent write owners, task classes, decay rate, confidence floor. An unknown space or channel fails closed | an 8th test space works end to end in a test store, including its Kyudo terms | no new real space |
| W11 | **Kyudo repairs (§12)**, built with W4: node channel + confidence caps + trust cap on the cluster; reorganization (scope, nodes, re-render, conflict log); threat fades per clean session; the suspension ends with the session | each has a guard that fails on the old code | the §12.2 items stay proposals until measured |

### F10.1 Status (2026-10-19)

W1, W2, W3, W8 committed (`04b8f858`). W5/W6/W7 committed (`7cd434e9`): the session region,
confidence that grows on recurrence, the chrono feed. W4 + W11 committed (`14e3452b`); the
active-day clock (§11.4) follows. Open: W9, W10, the live gate.


---

## F11. Growth and decay as one law (owner, 2026-10-19)

> "make sure there's an algo that is in alignment with the speed growth of the memory and decay
> together" — and "don't forget about the reorganization as well with the decay".

### F11.1 What was wrong (code-read; live values read-only)

- **Growth was weighted by evidence, decay was not.** An edge observation moves the score by
  `delta / (1 + n)` (REQ-26), so belief converges. Decay took `rate × days` whatever n was. A
  route with 100 proofs that was used once a day gained 0.05/101 and lost 0.02: it shrank while
  in use. The two halves ran at different speeds.
- **Decay compounded.** Each pass subtracted the whole time since the last traversal again.
- **Node confidence had growth and no decay** (after W6): repetition could only ratchet it up.
- **The physics coupling never ran.** The scorer asked the *store* for `get_latest_u`; only the
  interface has it, so the u multiplier was 1.0 on every pass, even when a session was passed.
- **Landmark edges are inert**: 6,628 rows, all score 0.4, traversal count 0, never traversed —
  nothing makes them grow. (A writer is still needed; the law is ready for it.)

### F11.2 The law (`backend/memory/mycelium/decay.py`)

For every learned strength s with evidence n (edge score; landmark-edge score with n = traversal
count):

```
growth  (an observation):  s += delta · a(n)            a(n) = 1 / (1 + n)
decay   (an idle span):    s -= rate · m · days · a(n)
m = m_channel (weaker endpoint, Kyudo Part 3) · m_phase (Caducean, over the span) · m_quorum
```

The net drift per day is `a(n) · (delta · f − rate · m)`, where f is the use frequency. **Its
sign does not depend on n**: a young and an old belief cross at the same frequency
`f* = rate · m / delta`; a belief with more evidence only moves more slowly — in both
directions. That is the alignment: one speed, set by the evidence, for growth and for decay.
Examples: toolpath (0.02/day, hit +0.05) needs a hit every 2.5 days; a default edge (0.01) one
every 5 days; a weak (EXTERNAL) source needs 3x the reconfirmation.

**Node confidence** is the same pair in multiplicative form (a node has no count): growth
shrinks doubt, `c → 1 − (1 − c)(1 − 0.25·w)` (W6); decay shrinks only what repetition earned,
`c → floor + (c − floor)·exp(−rate · m · days)`, floor = the stated value 0.4 (Req 4.4).
Each moves in proportion to its distance from its bound, so they meet at an equilibrium set by
f. What was stated stays; what was earned must keep being earned.

**The phase** is the time-mean of the per-step multipliers over the span (expand 0.5,
compress 1.8, neutral 1.0). The multiplier of the *mean u* was 0.5 on every span of the live
store (72% of steps expand) — a constant, so a failure by §3's rule. The step mean varies with
the work: 0.68–1.37 per day (measured 2026-10-19). Compression phases prune; expansion phases
preserve.

**Incremental**: each span counts once, from `max(last touch, last_decayed_at)`.

### F11.3 The reorganization is the same law, faster

The quorum reorganization runs this law with `m_quorum = 3.0` for one day-span, on what the
**current and previous day touched** (edges by `last_traversed`, nodes by `updated_at`). It no
longer decays every edge by a separate rule, and it now reaches node confidence, where poisoned
coordinates live. Because a(n) is in the law, it strips **new, unproven growth** (the shape of
an injection) while well-proven memory barely moves — the immune response targets what is new,
by construction. Measured in the guard: a fresh edge loses 0.03, a 50-proof edge less than a
tenth of that, an edge outside the window nothing.

### F11.4 The clock: active days (owner decision, 2026-10-19)

The law counts **active days** — UTC dates with at least one episode (`decay.ActivityClock`;
52 of the last 90 calendar days on the live store). Decay follows the speed at which the memory
grows: an away month forgets nothing; a busy week fades unreinforced memory per use, not per
calendar day. One query per pass on the covering index `idx_ep_timestamp`. A span counts the
active dates strictly after the date of its last touch, up to today. An empty episode table
means no activity, so nothing decays.

Req 7.2 ("score −= rate × days idle") now reads *active* days. A store with no episode
**table** (a Mycelium-only store: test fixtures, a partial schema) has no activity record; it
counts calendar days, logged at WARNING — the existing Req 7.2 test runs on such a store and is
unchanged. Replay on the live store (read-only): active idle 0–52 days against 0–99 calendar;
node confidence after one pass 0.42–0.95; three spaces keep a node ≥ 0.6, so the maturity gate
opens honestly.

---

## F12. Kyudo — the self-cleaning security of the memory (analysis, 2026-10-19)

Source: `Mycellium Kyudo Layer Guide.md` (v1.0, March 2026; partly stale, the concepts hold).
Kyudo is **one mechanism with two names**: the channel a source arrives on sets how much it may
write, how fast its signal fades, which context zone it reaches, and whether it can become
permanent. Precision and security are the same property; the decay system *is* the security
system; the reorganization is the decay system with an emergency multiplier.

### F12.1 Guide against code (measured / code-read)

| Guide | Code (before 2026-10-19) | Now |
|---|---|---|
| Channel per content item, permanent | channel only on episode-index rows — **0 of 2,850 rows carry one**; nodes carry none | nodes record `source_channel` (the highest channel that ever observed them: reconfirmation earns trust) |
| Initial confidence by channel (EXTERNAL 0.30) | the document bridge wrote EXTERNAL content at **0.8**, above every stated value | capped per channel at the store |
| Decay multiplier by channel (EXTERNAL 3x) | absent | in the law (§11.2) |
| Rule 2: landmark trust cap, 30% of constituent nodes | checked a *session* channel argument that **no caller passes** — never ran | measured on the cluster's own nodes on every condense |
| Rule 1: conduct is behavioural only | CellWall `can_write_space` blocks it on the RAG/document paths | unchanged (holds) |
| Quorum signals (4 kinds) | **1 of 4 emitted**, and it is a physics TOPO_VIOLATION filed as `update_velocity_anomaly` | unchanged — §12.2 |
| Threat fades per clean session | `decay_clean_session` had **no caller**: anomalies piled up for the life of the process | fades at session end when the session raised no signal |
| Reorganization: decay what the suspect sessions touched | decayed **every** edge, never nodes | §11.3 |
| … re-render the profile | read `_profile_renderer`; the attribute is `_renderer` — **skipped** | fixed |
| … log to `mycelium_conflicts` | wrote columns `resolution`, `resolved_at` that do not exist — **0 rows ever** | fixed |
| … suspend crystallisation until `clear_session` | never lifted — one reorganization blocked landmarks until restart | lifted at session end |
| MCP pin mismatch → UNTRUSTED | registry loaded, **never compared** | open — §12.2 |
| RAG ingestion bridge at the boundary | `ingest_rag_content` has **no production caller**: web retrieval enters memory with no channel | open — §12.2 |
| Subagent write profiles | read slicing exists; **writes are not checked** | open — §12.2 |
| Precision half (whiteboard slicer, micro-abstract, delta encoder) | **no production caller** | open — measure, then wire or remove |

### F12.2 Proposals (not built; each needs its measurement first)

1. **The immune signals, from places that already know.** Velocity: count node upserts per
   session and fire above the live p99 (`QUORUM_VELOCITY_THRESHOLD` is "TBD post-deployment" —
   measure it from the store). Landmark activation anomaly: an activation above mean + 3σ for
   its task class. Channel mismatch: a VERIFIED source whose coordinates move where EXTERNAL
   content predicted. Give the physics violation its own label instead of borrowing "velocity".
   Run in shadow first and measure the false-alarm rate, as the Oracle does.
2. **A durable immune memory**: persist the threat level and the signals (the docstring's
   `quorum_log` table does not exist). In memory only, a restart erases the evidence, and an
   attacker who spreads across restarts never reaches quorum.
3. **Every external write through the bridge**: research memory and web results enter with a
   channel (EXTERNAL), or none of §12.1 applies to them.
4. **MCP pin check at call time**: compare the server's identity with its pin; downgrade to
   UNTRUSTED and raise `channel_trust_violation` on drift.
5. **Enforce subagent write profiles on writes** (silent drop, as the guide says — no threat
   signal for a normal boundary).
6. **Separate the write lock from the render zone** (W10). The code reuses the guide's
   *context-window* zones as *write* permissions per space, so `toolpath` sits in REFERENCE and
   any channel may write it — the document bridge files untrusted documents into toolpath, a
   behavioural space. Each space declares both in the registry; unknown fails closed.
7. **A landmark-edge writer** (co-activation), so landmark edges grow under the law.

### F12.3 What a space declares (for W10)

`space_id`, axes and ranges, base decay rate, confidence floor, **write lock** (the lowest
channel that may write it), **render zone** (where its profile section enters the context),
subagent **write owners**, the **task classes** that navigate it, resonance participation,
extractor, schema version. A new space is added deliberately (a reviewed row), and inherits the
law and the immune response with no new code.


---

## F13. Findings while building §12 (2026-10-19)

### F13.1 The memory never reaches the agent's step prompts (largest gap)

The DER loop expects a `ContextPackage` object (`memory/mycelium/interface.py:48`: tier-1
directives, tier-2 predictions, tier-3 failures, gradient warnings, the Mycelium path, the
topology path) and reads it at `agent_kernel.py:8191-8198`, `:10653`, `:16736`, and through
`LiveContextPackage` (`memory/live_context.py`). **Nothing in production constructs a
`ContextPackage`.** `MemoryInterface.get_task_context_package` always returns a plain string
(its direct `get_context_path(..., space_subset=...)` call raises `TypeError` — the parameter does
not exist — and the fallback returns the prose/coordinate string), so every attribute read is
empty. The coordinate graph, landmarks, failure warnings and predictions are computed and
**never shown to the agent**. This is not a Kyudo item; it is the connection from memory to
answers, and it changes every prompt — so it needs the measured loop (CLAUDE.md "BUILD + VERIFY
IRIS"): build the package, run the eval tasks before/after, keep it only if pass and reply_s do
not regress, with an off switch.

### F13.2 The precision half (proposal from §12.1, measured)

| Component | Live? | Finding |
|---|---|---|
| TaskClassifier | live (keyword path) | its labels (`research_task` …) never match the kernel's `research/explore/investigate` check (`agent_kernel.py:18688`) |
| PredictiveLoader | half-wired | `pre_warm` calls `navigator.navigate_subgraph`, which does not exist (error swallowed at debug); the cached hint text is `""`, so the Jaccard check is 0 and every lookup misses; `hit_rate` is never logged |
| MicroAbstractEncoder | dead | no production caller; the 30 `micro_abstract` rows are bootstrap seeds |
| WhiteboardSlicer | dead | no caller; `whiteboard_broadcast_tokens` hard-coded 0 |
| DeltaEncoder / PathDelta | dead | no caller; `mycelium_path_deltas` table never created |

Decision: the dead three stay dormant (their tests pin them; deleting them is an owner call);
each is wired only together with a consumer that changes behaviour. PredictiveLoader and the
TaskClassifier labels are fixed as part of §13.1, because they only matter once the package
reaches the prompt.

### F13.3 Pins in the application memory

Pins are a port of the MCM PiN into the app store (`backend/memory/pin_store.py`: types note,
file, folder, image, doc, url, decision, fragment, checkpoint).

- `mycelium_pins`: **0 rows**. `PinStore.add/update/checkpoint` have no production caller; the
  two raw inserts (`agent/swarm/coordinator.py:162`, `agent/swarm/context_control.py:104`) run
  only with swarm on (default off).
- The recall path for pins (`recall_decoder._resolve_pin`) is unreachable: nothing imports
  `recall_phases` / `recall_decoder` in production.
- `mito_inject.py:50` counts permanent pins from table `pins` / column `permanent` (the build
  store's shape) every turn; the error is swallowed, so the count is always 0.
- `mycelium_pin_links`: 16,578 rows — not pins. They are DER step links (`relevant_to` 12,757,
  `depends_on` 3,535, `part_of` 279, `failed_like` 7). Their ids are `node:<step_id>` with plan-
  local step ids (`s1`, `s2` …), so **every plan's `s1` is the same node**: 16,569 of the links
  resolve to `der_fan_traces.step_id`, but without a session scope the lineage graph collapses
  onto ~64 ids. `weight` is 1.0 on every row.
- the former `DASHBOARD-DESIGN:712` (now `MEMORY-INTERFACE.md` §8.3) lists a "Keep this in mind: pin into
  the context window" action; nothing implements it, and the mockup draws no pins.

**What a pin is in IRIS (proposal).** Learned memory grows (neurons, edges, landmarks); a pin is
**explicit** memory — something the user or IRIS chose to hold: a file, a URL, a decision, a
note, a checkpoint. It does not decay by the §11 law (it is held, not earned), it carries the
channel of whoever pinned it (user = USER), and it is either *resting* or *held in context*
(the dashboard action).

**How pins look in the cortex (proposal).**
- **Cortex level:** a pin is a small **faceted crystal set into the inner wall**, in the territory
  (sector) of its topic — still, not pulsing, which is what separates held memory from living
  neurons. Its facets take the pin-type colour; its size follows its link count. Fine, taut
  **tethers** run from it to what it references (an artifact in the format layers, a landmark
  cluster, a thread) — straight and tense, unlike the soft fibre tissue.
- **Held in context:** the crystal gets a thin bright ring and its tethers brighten — "IRIS is
  holding this right now".
- **Timeline:** a pin sits on its thread at the moment it was made, as a fixed bead the fibres
  part around; scrolling past it shows its tethers to later threads that used it.
- **Checkpoint pins** (session checkpoints) mark doorways: the tunnel's doorway to a thread can
  carry the checkpoint crystal of where that thread was paused.

Work to make pins real (not built): a session-scoped id for DER links (`node:<session>:<step>`)
so the lineage stops collapsing; a production writer for user pins (the "keep this in mind"
action and an agent tool), routed through Kyudo with the pinner's channel; fix the `mito_inject`
count; then the cortex reads `mycelium_pins` + `mycelium_pin_links`.


---

## F14. §12.2 proposals — status (2026-10-19)

| # | Proposal | Status | Commit | Measured / open |
|---|---|---|---|---|
| 3 | Every write through the trust bridge | **built** | `588036cd` | one vocabulary (zones, document labels → HyphaChannel; unknown = UNTRUSTED); bookkeeping (2,775 card rows, skills) no longer filed as the user's words; episode-index rows carry a channel (backfill 387 + 2,349); channel-weighted retrieval in SHADOW (`kyudo.trust_rank.*` counters). Open: a failed web-tool step still fragments into the `tool` zone (`agent_kernel.py` der_failure). |
| 7 | Landmark edges grow | **built** | `bcb6c8ea`, `d1f255e1` | landmarks activate when the session's region overlaps their cluster (≤ 6), and their edges take one observation per turn by the §11 law. Found: the region was cleared before the turn-end job, so every episode-index row had `'[]'` — fixed. Open: 91 live landmarks share 7 clusters (duplicates that never merged — W9). |
| 1+2 | Immune signals in shadow + durable immune memory | **built** | `526a6d03` | `mycelium_quorum_log`, threat level restored on start, retention 2,000 rows; TOPO violation has its own label. Velocity shadow (> 11 upserts) fires on 5 of 2,365 sessions — all honest long sessions: it does not separate an attack. Activation shadow: 0 fires (no activation history until now). `channel_mismatch` not built. |
| 6 | Write lock separate from the render zone (W10) | **built** | `c209f33a` | `mycelium_spaces` is the registry; locks: conduct/style/chrono ≥ USER, capability/toolpath = SYSTEM, context ≥ VERIFIED, domain ≥ EXTERNAL; fails closed; an 8th test space works end to end; untrusted documents no longer write toolpath. |
| 4 | MCP pin check | **built, dormant** | `0c9341ca` | identity hash over endpoint + serverInfo + tools (with descriptions); drift → UNTRUSTED + conflict row + signal. Nothing in production connects an external MCP server yet. Pin creation is an owner decision. |
| 5 | Subagent write limits | **closed** | — | no production path writes nodes under a worker identity; the profiles are read-only (evidence in `0c9341ca`). |
| — | Precision half | **measured** | — | §13.2: three components dead, the predictive loader half-wired; tied to §13.1. |

The largest open item is not in §12: **§13.1, the memory never reaches the agent's step
prompts.**


---

## F15. The next three, and the live gate (2026-10-19)

| Item | Commit | State |
|---|---|---|
| The memory reaches the step prompts (§13.1) | `a0b0924c` | ContextPackage built from existing producers (path, topology, predictions, failures, task class); capped 1,600 chars, 150 ms budget; off switch `IRIS_MEMORY_CONTEXT_PACKAGE=0`. ON by default. |
| Landmark duplicates + sectors in shadow (W9) | `c8852bb5` | merge-all at Jaccard ≥ 0.5, region clusters, uuid merge ids, specificity tie-break; sectors table, roots, sector at save + backfill (91: rule 19, cluster 51, general 21), lifecycle logged only. A session with no region crystallizes no landmark. `collapse_duplicates()` is NOT in maintenance (decision below). |
| Cortex visual | `c198f97a` | timeline = fibre tissue; the doorway is a tall soft arch with no rim; pins, trust membranes, fading, landmark tracts, immune response, sectors, spaces; MEMORY-DASHBOARD-DESIGN §17. |
| First-turn stall found by the gate | `d706941c` | 73 s in the chart-origin query (cold SCAN) → 196 ms with an index. Standard S113. |

**Live gate (coding group, 15 tasks, real backend).**

| Run | Pass | Sum of reply_s | Note |
|---|---|---|---|
| ON #1 | 14/15 | 685 s | includes the 12.8 s cold first turn (the S113 stall) |
| OFF | 13/15 | 643 s | `IRIS_MEMORY_CONTEXT_PACKAGE=0`, same build |
| ON #2 (after S113) | 13/15 | 816 s | 8 packages built; 22 extra model calls (below) |

Run-to-run noise is large (the two ON runs differ by 19%; failures move between tasks:
ON#1 c14, OFF c04+c06, ON#2 c05+c11). Pass does not regress. The reply time is higher in
ON#2, and the measured cause is **the step reviewer's model branch** (`der_loop.py` ~1167):
it runs when the graph is mature and a package exists — which never happened before today —
and in ON#2 it made 22 extra calls (role EXECUTION). It judges a step against the package's
gradient warnings and active contracts, and **no producer fills either field**, so it reviews
with no memory signal. Gating it on non-empty warnings/contracts conflicts with five existing
tests (`tests/unit/test_reviewer_split.py`, `tests/contract/test_verdict_consumer_shape.py`)
that pin "mature + package → model review" — reported, not changed (owner decision below).

**Live values after the gate (read-only):** 48 `mycelium_edges` (was 0; scores 0.5–1.0,
evidence up to 12); 23 landmarks activated by use (max 14 — one is now a chart origin); 55
landmark edges grown (0.42–0.45, up to 8 traversals); 5 landmarks permanent through use
(tier `landmark` + 8 activations — the rule that was always there, now reachable); new nodes
carry their channel (21 SYSTEM, 1 USER); 13 proven sector roots; quorum log empty (no signal).
**Not exercised:** the episode index — every eval task is a repeat, the episode store dedups
it (UPDATE, early return) before the index step, so no new index row formed; check with a new
task.

**Decisions for the owner.**
1. The reviewer's model branch: keep it live (the tests' contract; +~22 calls/run, no memory
   signal to judge), or require a warning/contract first (change the five tests' contract).
2. `collapse_duplicates()` on the live store: it would absorb 88 of 91 landmarks into 3, but
   they look alike only because of the old global-top-6 cluster bug — their claims differ.
3. Permanence through use: a `landmark`-tier claim becomes permanent at 8 activations; the
   activations are now real (one landmark reached 14 in ~46 turns — hub concentration).

**Visual check (in-app browser):** demo + `?real` load with no console errors; `?real` reads 7
spaces, 120 nodes, 0 pins. The orb renders as a bright white core in the in-app browser — the
same for the version before this work (software rendering, ~17 fps); check brightness in your
own browser.

---

## F16. The Kyudo integrity pass - the memory cleans itself (owner, 2026-10-19)

> "This memory.db for the application is still test and development ... Kyudo should NATURALLY
> clean up old landmarks or anything that would interfere with the structural integrity and
> credibility of the memory."

`mycelium/integrity.py`, run by `MyceliumInterface.run_maintenance` (never the answer path), bounded
per pass, every action counted (`kyudo.integrity.*`), logged, typed (`LANDMARK_DISSOLVED`,
`LANDMARK_MERGED`, `MEMORY_PRUNED` - new words in the memory family, no new letters) and written
through `app_write`. Landmark rows are never deleted: a landmark is ABSORBED (`absorbed = 1`, the
reason appended to `falsify_if`). It answers decision 2 of section 15: `collapse_duplicates()` is now
wired in, AFTER the hub landmarks are dissolved.

| Rule | What | Threshold and why |
|---|---|---|
| 1b `hub_cluster` | a cluster shared (Jaccard >= 0.5) by landmarks making >= 3 DIFFERENT claims (task_class) | a place that "supports" three claims proves none; found by what it is, not by when it was made. Protected: permanent landmarks and PROVEN claims (tier landmark with outside evidence other than recurrence - recurrence between hub landmarks is circular). |
| 1a `dangling_cluster` | fewer than half the cluster's nodes still exist | the same 0.5 bar as "the same landmark". |
| 2 `no_credibility` | score - 0.005 * active_days_idle * a(n) < 0.08 | the section 11 law (edge law, non-permanent landmark rate), n = activations + independent outside evidence, idle since the last touch, computed not written back (idempotent). No evidence, no use: 74 active days at the 0.45 floor; proven (n >= 2) three times that. Permanent exempt. |
| 3 dangling references | landmark edges, episode-index `landmark_id`, sector rows -> absorbed or missing landmark; node edges -> missing node | re-pointed along the merge log to the live survivor, else removed (edges, sector rows) or cleared (episode-index id; the episode row stays). |
| 4 orphan nodes | no edge, in no live cluster, never accessed, earned confidence <= 0.05 above the space floor, idle >= 30 active days; never a `stated_*` node | nodes are re-created by observing again; the user's own statement is the observation itself (Req 4.4). The live idle values cluster at 0-19 and 34-52 active days (one node at 25): 30 sits in the gap. |
| 5 | `collapse_duplicates` | the crystallisation merge rule, applied to the backlog; only while <= 500 live landmarks. |

Bounds per pass: 100 landmarks dissolved, 500 dead landmark ids swept, 100 nodes, 500 node edges.
A cut pass defers the merge step (a hub left live must not be merged into a crowned claim).
The quorum reorganization is the same cleaning in an emergency: while crystallisation is suspended
the pass steps aside (`kyudo.integrity.skipped_quorum`) and runs after `clear_session`.

**Replay (copy of the live store, backup API from a `mode=ro` connection; second pass changes nothing):**

| | before | after |
|---|---|---|
| live landmarks | 97 (19 distinct clusters, 75 claims) | 14 (14 distinct clusters, 14 claims) |
| `hub_cluster` / `dangling_cluster` / `no_credibility` | - | 83 / 0 / 0 |
| landmark edges (dangling) | 6,289 (2,704) | 33 (0) |
| episode-index rows pointing at absorbed landmarks | 517 | 0 (525 cleared) |
| sector rows (dangling) | 291 (45) | 47 (0) |
| nodes | 121 | 110 (11 orphans) |
| live per sector | hardware 52, finance 47, data 46, general 31, ... | general 10 (+3 sub-sectors, same 10), hardware 2, web 2, data/design/finance 1 |

Two rules acted on nothing live today (`dangling_cluster`, `no_credibility`: the 14 survivors were
touched in the last days) and are pinned by guards on constructed cases. Open: the 14 survivors all
carry `cumulative_score` 0.6 (a constant - the crystallisation score is not a measure);
the reorganization does not touch landmarks created inside its suspect window.
