# Live context, strand contents, and the galaxy cortex — design plan (proposal)

Status: **FINAL DESIGN** - owner decisions 2026-11-22 (§7 resolved, §8-§10). Nothing here is
built yet; the build order is §6. Where an earlier section and §8-§10 differ, §8-§10 win. It extends
`MEMORY-INTERFACE.md` (the final interface design) and `specs/clm-memory/` (CLM, the live view of
the model's context). Every visual below is tied to a real value; nothing is decoration.

The owner's asks (2026-11-22):

- **A.** The live-context view in the corridor, and the progression of its edits for each strand,
  across the strands of a thread, over time.
- **B.** Let the user see what a strand was about (what IRIS did in it) without opening the chat
  view's dropdown. Does the tool-result ref connect to the strands?
- **C.** The inside of the orb as a constellation: galaxies intertwined and emerging. Keep the
  overall look of the memory surface.
- **D.** Smooth UX first. The whole design must be breathtaking and seem alive.

---

## 0. In plain words

- **The corridor gets a third line: the context.** The corridor already shows the conversation
  (pink) and the memory (cyan) coiling down it. A third, translucent band follows them: the model's
  working context at each step. Its width is how full the context was. When IRIS sets a thought
  aside, a shard leaves the band and sticks to the wall with its label. When IRIS brings it back,
  the shard flies home. When IRIS let one go too early, that shard glitches (the desync language).
  Walking the corridor IS walking through time, so the progression is the corridor itself. The far
  door leads to the next strand of the thread, so a thread's progression is a walk through its
  corridors. On the timeline, each strand's bead gets a thin ring: how full its context ever got.
- **Most strands will show a calm band, and that is the truth.** On the cloud model the context
  never fills (measured 0.06–0.33 of the window). The band then says "the context never had to make
  room". On a small local model the band breathes, shards leave and return.
- **Every strand says what it did, on hover.** The strand card (timeline hover, corridor rail)
  lists what was asked and the steps: tool, what it acted on, its purpose line, success or failure.
  That record already exists in the memory and survives. The exact output of a step opens on
  click, while the chat record still keeps it.
- **The orb becomes a small universe ("A + C", §8).** The whole memory is one spiral galaxy;
  each root sector is an arm, and young or side sectors are satellite galaxies fed by tidal
  streams of the claims they share. The claims are bright star clusters on the arms. They are
  joined by curved, branching hyphae that follow the arm and light up only when a recall uses
  them - the mycelium inside the galaxy. A new claim is a knot of stars that brightens as it
  forms (emerging); fading memory drifts out; pins are the one thing that stays still (§10).
  At the centre, the nucleus is what IRIS has on its mind right now: the live context, the same
  blocks the corridor band shows. The coordinate spaces sit inside each sector (§9.2).

---

## 1. Measured facts this plan is built on (read-only, 2026-11-22)

| Fact | Value | Consequence |
|---|---|---|
| CLM `OFFLOADED` events, ever | 7 rows, 5 threads, all with `window` 8,192 | edits are RARE; the honest calm state is the common view |
| `RESTRETCHED`, `PREMATURE_EVICTION` | 0 and 0 | the return and the glitch must be built from replays of small-model runs (TG-2) |
| context fill on the cloud model | 0.06–0.33 (CLM T2.7 report) | the band is thin and still on most strands |
| context fill per step | NOT stored anywhere (the view is in memory only) | A needs two numbers per step (W2) |
| `tool_results` rows | 4,000 = the store-wide cap; 779 conversations; 2026-11-18 → now | user results are evicted in ~4 days, mostly by eval runs |
| `tool_results` by tool | run_python 2,230 · wb_spill 1,757 · search 9 · read_file 2 | mostly Workbench code and spills |
| `tool_results.turn_id` | NULL on 3,987 of 4,000 rows | Workbench spills and run_python rows cannot be placed on a turn (W0 fixes) |
| `tool_results.target` | run_python = its purpose line ("Read roman.py and test_roman.py contents"); search = the query; read_file = the path | a good one-line "what it did" |
| `episodes.tool_sequence` | per step: tool, params, target, success, step, description | the DURABLE "what it did", in the encrypted store; the surface reads only the tool names today (`surface_queries.py` ~904, ~1431) |
| cortex motes (`engine.ts` ~1148, "on-mind motes") | fed from `M.mind`, which the snapshot sends as `[]` (`surface_queries.py` ~1657) | the nucleus of the orb is empty on real memory today; the live context fills it |
| mist (`engine.ts` ~1137) | 7,000 random points standing for 84k fragments | per-point it carries no data; the galaxy stars replace it with per-territory counts |
| live taps (`backend/utils/memory_live.py`) | every `memory_events` row reaches the surface as `memory_event` | CLM edits already arrive live; only the fill gauge has no live tap |

---

## 2. (A) The live context in the corridor

### 2.1 What the user sees

- **The context band.** A third strand in the corridor, translucent, the brand colour, between the
  conversation and the memory strands. One sample per DER node boundary (a step). Width = fill
  (`ctx_tokens / window`), clamped; a thin dashed line marks the gauge margin where CLM starts to
  make room.
- **Set aside (`OFFLOADED`).** At the step where it happened, a shard (one per ref in the payload)
  leaves the band and settles on the wall, with its label: tool + target ("read_file · billing/report.py
  · 2.2k tokens set aside"). Hover: what was set aside, how much it saved, and the open item it
  carried. Click: the exact text (§3.3).
- **Brought back (`RESTRETCHED`).** A thin spark from the wall shard back into the band at the step
  it came back; the shard dims to an outline (it is no longer aside).
- **Let go too early (`PREMATURE_EVICTION`).** The shard glitches (chromatic offset ≤ 300 ms, the
  desync language) and stays amber.
- **The calm state.** A strand whose band never neared the margin shows the thin band and, on the
  rail, "the context never had to make room · peak 18%". That line is a real reading, never filler.
- **Live.** While a turn runs, the band grows at the far end of the corridor (edge case 19 in
  `MEMORY-INTERFACE.md` §10.6: "a growing strand assembles at the far end, your place kept"). A CLM
  edit arrives through the existing `memory_event` tap and plays at once.

### 2.2 Progression over time

- **Inside one strand:** the corridor is the time axis, so the band IS the progression. Shift+← →
  (turn to turn) already exists; the band's turn rungs reuse it.
- **Across a thread:** the far door leads to the next strand of the thread. Each corridor starts
  its band at the width the previous one ended (a new turn starts a new view, so it is usually
  thin again: that also is true).
- **Across the whole memory:** on the timeline, each bead gets a thin fill ring = the strand's peak
  fill; a strand with edits gets a small notch per edit. The braid of a thread then shows where
  the context worked hardest, without entering anything.
- **In the orb:** the nucleus shows the CURRENT context only (§4.3). History lives in the corridor
  and the timeline; the orb shows now.

### 2.3 Data (existing vs new)

| Need | Source | Change |
|---|---|---|
| the edits | `memory_events` OFFLOADED / RESTRETCHED / PREMATURE_EVICTION, by `thread_id` | none (labels exist; alphabet stays closed) |
| fill at the edit | OFFLOADED payload has `saving`, `need`, `window` | add `fill` (one float, before the edit) to the three payloads; payloads stay refs + small numbers (S12) |
| fill per step | — | add two nullable columns `ctx_tokens`, `ctx_window` to the existing per-step row `der_fan_traces` (it already has one row per step: `session_id, step_id, tool, outcome, u, xi`), written on its existing lane. The same ALTER goes into `scripts/migrate_build_store_inheritance.py` so the build store stays schema-identical (REQ-2b) |
| fill live | — | one new live tap kind `context_gauge` in `memory_live.py` (a WebSocket message type, not a memory-event label), coalesced, at most one per node boundary |
| per-strand series | `GET /api/memory/strand/<id>` (`surface_queries.strand()`) | add `context: [{turn, step, ts, tokens, window}]`, LIMITed, from the indexed `der_fan_traces` read |

Not stored: the contents of the view. The view stays "derived, never a file" (CLM design).

---

## 3. (B) What a strand was about, without the chat dropdown

### 3.1 The answer to the owner's question

Yes, but not through the tool-result ref alone. Three records connect to a strand:

1. **`episodes.tool_sequence`** (memory.db, encrypted, durable): per step the tool, target,
   one-line description and success. This is the "what it did" that survives. The surface reads
   only the tool names from it today.
2. **`tool_results`** (conversations.db, plaintext): the exact output text, keyed by conversation.
   It is a short-lived cache: 4,000 rows store-wide, evicted in ~4 days, and 99.7% of rows have no
   turn id (W0).
3. **The OFFLOADED ref** points to one `tool_results` row: it connects a CLM edit to its text.

So the strand shows (1) always, and offers (2) on click while it is kept.

### 3.2 Where it shows

- **Timeline hover (strand card):** what was asked · outcome · then up to 5 step lines:
  `✓ read_file · billing/report.py`, `✓ run_python · Inspect the first 30 lines for storage shape`,
  `✗ run_command · pytest -q (2 failed)`. "+N more" opens the corridor.
- **Thread braid hover:** one line per strand: its title + its first step line.
- **Corridor:** each task card lists its steps the same way; each step line is a mark on the rail.
- **Search** (`/`) already searches steps; step targets and descriptions join that index (they are
  short text in the memory store, not tool output).

### 3.3 The exact output (on click only)

- `GET /api/memory/tool-result?conversation=<id>&turn=<turn>&step=<step>` returns the rows of that
  step: tool, target, chars, cut, and the first 4,000 chars of content, with "show all".
- Evicted: the tombstone table answers "IRIS no longer keeps this output (kept 200 per strand, 4,000
  in all)". Never a fake preview.
- Privacy line on the panel, once: "stored as plain text on this machine". Never in the snapshot,
  never in hover, never in a deep link (ids only, §6.3 of the interface).

---

## 4. (C) The galaxy cortex

### 4.1 What stays (the aesthetic)

The claim crystal glyph (one glyph everywhere), the Oracle's pupil and its lens, cards, HUD,
tunnel, brand palette, the dark field, pale white-cyan points and lines, "brightness never builds
up over time", "every motion is driven by a real value". What changes is the tissue inside (the
neuron forest, the mist and the arbors) AND the shell: owner decision §8.7 replaces the hex skin,
the wire and the rings with a shell woven from the galaxy's own arms.

Note for the design doc: §2 says "no organic silhouettes". A galaxy is a form, not a leaf or a
vine; it is drawn only from points and lines, so it keeps the rule's intent. The owner's ask
overrides the letter; §2 gets one line when this is accepted.

### 4.2 Three concepts (the record of what was weighed)

**Decided: "A + C" (§8)** - the one spiral of Option 2 with the satellites and tidal streams of
Option 1, and the living links of the constellation option as arm-following hyphae lit by use.
The data-to-visual mapping below still holds per galaxy and per stream; §8-§9 add the hyphae,
the sector halos and the event grammar. The shader approach of §4.4 is unchanged.

**Option 1 — Interacting galaxies.** One galaxy per territory, placed where the
territory sits on the skin today, tilted to face outward.

| Memory | Galaxy |
|---|---|
| territory | a galaxy: a disc of stars, its tint the territory tint |
| moments in the territory | its stars (count ∝ log of real moments; a budget of ~40k stars in all) |
| territory sync (proven share) | the arm order: proven = two crisp, tight arms; learning = loose, flocculent arms; contradicted = a disturbed disc with a warp |
| a claim | a bright star cluster on an arm; at close range it resolves into the crystal glyph (LOD) |
| claim links across territories (frost bridges, landmark edges) | tidal streams: thin rivers of stars that leave one galaxy and enter the other. Strong, used links = bright, thick streams. Many links = galaxies that lean into each other: the intertwining |
| a new claim crystallizing | a star-forming knot: points condense and brighten over ~2 s, then the cluster holds |
| decay (the one law, active days) | stars drift outward into the halo and dim; Kyudo dissolving a claim = its cluster disperses |
| Kyudo merge | two clusters spiral into one |
| Σ (F6): x / y | the discs inhale (expand) / exhale (tighten) |
| Σ: ξ | the rotation phase of the arms |
| Σ: u | the flow along the tidal streams (outward > 0, inward < 0) |
| the nucleus at the orb centre | the live context (§4.3) |

**Option 2 — One spiral galaxy.** The whole memory is one large galaxy. Each territory is an arm;
radius is age (new memory forms near the nucleus and drifts out along its arm); claims are clusters
on the arms. It reads very clearly and is the cheapest to draw. It is less "intertwined": topics do
not meet except at the nucleus.

**Option 3 — Constellations.** A dark sky of faint stars (the fragments); claims are named bright
stars; their evidence links are thin constellation lines; territories are soft nebula tints behind.
Closest to today's line work and the cheapest on the GPU. It is the least alive of the three.

The first recommendation was Option 1; after three rounds of moving mockups the owner chose
A + C. It keeps what Option 1 was for - topics that share knowledge pull on each other through
streams - and adds the clarity of one spiral and links that show use. The "inside a sector"
dive stays: you dive into an arm region and the room scale (§3.2 of the interface) makes its
star field almost infinite.

### 4.3 The nucleus: the live context

The motes code (`engine.ts` ~1148) already exists and draws nothing on real memory (`mind: []`).
It becomes the nucleus:

- one mote per block in the current context view (cap 24), orbiting at a radius by its age in the
  view; the brightness of the nucleus = fill;
- set aside = the mote is flung out along a short tidal tail and stays at the edge of the nucleus;
  brought back = it falls in; let go too early = an amber flicker;
- idle (no turn running) = the nucleus at rest: slow, dim, the last settled state. Never invented
  motes.

### 4.4 How it is drawn (smooth first)

- ONE `THREE.Points` for all stars, one draw call. Per-star attributes set once at build:
  territory index, disc radius, arm phase, birth time, trust. ALL motion in the vertex shader:
  differential rotation (angular speed ∝ 1/√r) makes it alive at zero CPU cost; the CPU sets
  uniforms only (time, Σ, follow pulses). Same pattern as the existing forest and mist shaders.
- Tidal streams: one `Points` buffer sampled along each link's curve (≤ 64 links × 120 points).
- No post-processing bloom pass (a second full-screen render on a low GPU). Glow = the existing
  `GLOW` sprite texture and the point fragment shader's soft falloff.
- Additive blending with a density-aware alpha (`alpha ∝ 1/√local density`, baked per star), so
  dense cores do not burn to white and brightness never builds.
- Budget tiers by measured fps (the existing DPR ≤ 1.6 / 28 fps rule): 40k → 20k → 10k stars.
- The build stays in the existing lazy `import("@/lib/memory/scene/engine")`; star placement is
  O(n), not the O(n²) repulsion of the forest (`engine.ts` ~905).
- Reduced motion: rotation frozen; forming and dissolving become 200 ms brightness changes.
- Picking: claims are still picked as today; a galaxy is picked by its disc (ray–disc test), so no
  per-star picking.

---

## 5. Smooth-UX rules for all three parts

1. Nothing new on the snapshot's critical path: strand steps and the context series load with the
   strand (`/api/memory/strand/<id>`), tool output loads on click. The cold snapshot stays within
   S121 (1.5 s on the SSD) — measured before and after.
2. Every new motion ≤ the existing budgets: flights ≤ 1.2 s, ≤ 6 live effects at once, the rest to
   the ticker.
3. Alive at rest = shader time only (rotation, breathing 4–7 s, the band's slow shimmer). Nothing
   alive costs a CPU loop per frame.
4. A rare signal reads honestly; a missing signal says why ("no longer kept", "the context never
   had to make room", "fill not recorded before 2026-11-xx" for strands older than W2).
5. Hover never moves the camera; the new step lines and shards follow the existing card rules
   (80 ms intent, 250 ms linger, never cover the thing).
6. An eval run with the surface open shows no change in reply time (interface §11) — checked in the
   W3 and W4 live gates.

---

## 6. Build order (waves)

| Wave | What | Backend? | DONE = | NOT THIS = |
|---|---|---|---|---|
| W0 **(built 2026-11-22)** | Workbench spills and run_python rows carry `turn_id` and `step_id` (`workbench/manager.py` `StoreSink.write`, `tool_bridge.py` `_record_code_row`) | yes, small | a live coding run writes rows with a turn id; a contract test fails on the old writers | a backfill of old rows; a new table |
| W1 **(built 2026-11-22)** | (B) strand steps: `surface_queries.strand()` and the snapshot's episode rows carry `{tool, target ≤ 80, description ≤ 120, success}` (from `tool_sequence`, ≤ 12 per episode); strand card, braid hover, corridor task cards show the step lines; `GET /api/memory/tool-result` for the click | yes (read only) | hovering a strand on the timeline names its steps without opening chat; cold snapshot time unchanged within S121 | tool output in the snapshot; a summariser model call; search over tool output |
| W2 **(built 2026-11-22)** | (A data) `fill` in the three CLM payloads; `ctx_tokens`, `ctx_window` on `der_fan_traces` (lane write) + the same ALTER in the inheritance migration; `context_gauge` live tap; the strand's `context` series | yes | a TG-2 small-model run records per-step fill with real variance (not one constant, not all at a clamp) and its edits carry `fill` | storing the view's contents; new event labels; a `live_view` table |
| W3 **(built 2026-11-22; notches are a count on the bead card)** | (A visual) the corridor band, shards, return sparks, glitch, calm line; timeline fill rings and notches; the nucleus motes fed live | no | a replay of a TG-2 small conversation draws its edits at the right steps; a cloud conversation draws the calm band and its true line; fps within budget | per-token detail; animating every block in a long run |
| W4 **(built behind `?cortex=galaxy` 2026-11-23; the default and the old tissue removal wait for the owner's choice)** | (C) the galaxy cortex "A + C" (§8): one spiral (an arm per root sector) that fills the volume, satellite galaxies with tidal streams, arm-following hyphae lit by use, the arm-woven shell with its recall pulse (§8.7-8.8), sector halos of the seven spaces (§9.2), pins (§10); first behind `?cortex=galaxy` on the REAL memory so the owner can compare, then the default; the old forest/mist/arbor code removed in the same change that makes it default | no | the owner chooses after seeing it on real memory; ≥ 28 fps at DPR 1.6 on this machine; brightness flat over 10 minutes; the old tissue code gone | a second engine; a bloom pipeline; stars that stand for nothing |

W1 is the cheapest and most useful now. W2 needs the TG-2 small-model runs (they are the only runs
that make CLM edits) to prove its values.

---

## 7. Questions - resolved (2026-11-22)

1. **Galaxy concept:** RESOLVED by the owner - "A + C" with arm-following hyphae lit by use (§8).
2. **Store the fill per step:** RESOLVED - yes. The owner asked for the progression of the
   context edits per strand over time, which needs the per-step fill (W2).
3. **Show the exact tool output on click:** RESOLVED - yes, on click only, with the one-line
   "stored as plain text on this machine" note. The owner asked to see what a strand was about
   without the chat dropdown; the output is already on this machine, shown only to its owner.
4. **Eval runs evict the user's tool outputs:** TAKEN AS RECOMMENDED - eval and dev
   conversations are evicted first, same caps (part of W1; the owner may reverse it).
5. **Inside the orb and its shell:** RESOLVED - replace the neuron forest, mist and arbors,
   and (§8.7) the hex skin, wire and rings with the arm-woven shell; keep the pupil, the claim
   crystal and the overall look (palette, points and lines, dark field).
6. **Order:** TAKEN AS RECOMMENDED - W0 → W1 (strand contents), W2 → W3 (context), W4 (galaxy);
   W4 may start in parallel now that the concept is chosen.
7. **No spaces lens** (owner): the spaces are drawn inside each sector (§9.2).

Done since this plan was written: the DER step links are session-scoped, written once and
bounded, so pin tethers can be read from `mycelium_pin_links` again (only rows whose source is
a real `pin_id`, §10); the noise child sectors are folded (§8.6).

---

## 8. Owner decisions (2026-11-22, after the mockups)

1. **The cortex is "A + C":** one main spiral (the whole memory; one arm per root sector)
   with satellite galaxies (young or side sectors, fed by tidal streams of shared claims).
2. **Links are curved hyphae that FOLLOW THE ARM** (a link between two claims of one arm runs
   along the arm's own curve and bends as the arm turns), with branching spurs, and they are
   **lit by use**: dim at rest, a light runs along a link when a recall walks it
   (`mycelium_traversals`, `RECALL_USED`), and the target claim rings. Much-used links are
   thicker (cords). A new link grows from its tip. Cross-arm and satellite links are curved
   hyphae too, lit the same way.
3. **No spaces lens.** The coordinate spaces are drawn INSIDE each sector (§9.2), not as one
   global stack.
4. **Navigation:** four fixed levels with the existing grammar (whole memory, a sector, a
   claim, the corridor); the map never moves while it is read (rotation only in the whole view
   with nothing focused; it stops on hover, focus or entry); sector compass angles are fixed
   by the sector key; one focus at a time, the rest dims to ~25%.
5. **Mycelium in the galaxy (the cosmic web):** tip growth = a claim gains a node or evidence;
   nutrient flow = a recall walks an edge; cords = edge weight; fusion = a claim or sector merge;
   fruiting = a claim proven; decay = threads thin and pull back.
6. The noise child sectors are fixed at the birth rule (`sectors.term_can_name_child`) and
   folded by `scripts/repair_noise_sectors.py` (22 of 23 live children).
7. **The shell is woven from the arms (owner, 2026-11-22, after four shell mockups).** No
   separate sphere: the hex skin, the wire and the decorative rings go. Each spiral arm runs
   past the disc's rim, splits into three strands and spirals up to a top pole and down to a
   bottom pole, carrying its sector's tint and star dust that flows toward the poles. The
   anchor hyphae and the shell are the same threads.
   - **Weave:** cross-hyphae join neighbouring strands at three heights; a cross-hypha = two
     sectors that share claims, its thickness = how many (landmark edges across sectors).
   - **Shape:** a lemon, flatter than a ball and never a perfect sphere. A larger sector
     pushes its strands further out (size from the sector's landmark count); strands near a
     satellite galaxy bow out around it and the bow travels with the satellite's orbit.
   - **Kyudo** keeps its membrane meaning in the weave: an untrusted or weak source leaves
     thinner strands and gaps; a safety event makes the weave near it tighten and flicker.
   - **Recall pulse:** claim → along its arm → up its arm's strand (the cross-hyphae it passes
     light) → the pole flashes once → the light flows back down every strand on that side.
     One recall answered by the whole organism; driven by real recall events only.
   - **Breathing** follows the physics (Σ x/y), not a timer.
8. **The galaxies fill the volume (owner).** Not flat: a thick disc whose arms rise and fall
   as they reach the rim (so they flow into the strands), a round central bulge, a faint
   cloud of stars that fills the shell up to the poles (each tinted by the nearest arm's
   sector), and satellites that are tilted 3D galaxies. Depth is shown by brightness (nearer
   = brighter). In data terms the cloud is the sector's moments (count ∝ log of real rows),
   the disc its claims and their evidence; the shader approach of §4.4 is unchanged.
   Kept from today: the claim crystal glyph (at close range), the Oracle's pupil and lens,
   cards, HUD, tunnel, brand palette and the dark field.
9. **The inside is endless (owner).** The woven shell is the edge of what you SEE, never a
   limit on what the memory HOLDS or where you can go. It extends the interface's room rule
   (MEMORY-INTERFACE §3.2, "treat the inside as almost infinite space", ×1-×24 by claim
   spacing) to the whole galaxy:
   - **Holding:** every row has a place; growth adds depth, not crowding. A sector that grows
     gets more room inside its arm (the scale follows its content), so the whole view never
     has to drop or merge things to fit.
   - **Viewing:** diving in, you shrink and the room opens: the arm region you enter becomes
     a galaxy of its own, then a claim cluster, then the claim and its evidence (the same
     levels as §8.4, each one a step down in scale). Glyphs keep their size on screen
     (`uRoom`), so gaps open instead of everything zooming; speed follows the nearest claim
     (slow beside one, fast in empty space).
   - **The shell stays the horizon:** from inside, the woven strands recede to a far, faint
     horizon that keeps you oriented (the poles above and below, the sector strands around)
     and never reads as a wall you hit. Esc rises one level and the shell comes back into
     view.
   - **Cost stays bounded:** only what is near the camera is drawn in detail (level of
     detail by distance); far regions are their tinted star cloud. The star budget of §4.4
     holds at every depth.

## 9. Landmarks in their sector, and every event family

### 9.1 How an event finds its place (measured 2026-11-22, 107,539 events)

1. `topic_domain` on the event → that sector (6.8% of rows).
2. else `links.landmark_id` → that landmark → its sector by `mycelium_landmark_sectors`
   weight (42% of rows carry a landmark id).
3. else the strand's sector (the conversation's dominant sector) → the arm, faint.
4. else it is about the work, not a topic → it plays at the nucleus and on the strand only.
   This is about half of all events, and the view says so; it never invents a sector.

### 9.2 A sector, drawn

- **The sector** is an arm segment (root) or a bright region on its arm (child, depth ≤ 3).
  A candidate is a dashed outline; proven gets its label; a folded noise child is gone (its
  alias resolves to the parent).
- **Its landmarks** are star clusters on that region. Position along the arm = when it was
  learned (older further out); brightness = the earned part of confidence (sync); the frost
  star's spokes = its evidence kinds; the membrane = its Kyudo trust.
- **Its coordinate spaces** sit round the sector as a small halo of seven orbits, in ONE fixed
  order and angle everywhere (so the eye learns it once): domain, context, toolpath, conduct,
  style, chrono (a 24-hour dial), capability. Each orbit holds the sector's PROFILE in that
  space - the centroid of its landmarks' clusters (MEMORY-INTERFACE §F2.3) - and the nodes its
  landmarks touch. A landmark's hyphae run from the cluster to those nodes in its own sector's
  halo. Whole view: the halo is seven faint dots that say which spaces hold anything (context
  is empty today). Inside a sector: the halo opens, with labels.

### 9.3 The grammar: one rule per axis of the alphabet

| Axis | Visual channel |
|---|---|
| family | WHAT moves (the table below) |
| valence | colour: advances = brighter cyan, sets_back = amber with a short desync, neutral = pale |
| evidence | strength, by the ladder: user > test/verifier > completion > corroboration > recurrence > claim > none (faintest) |
| actor | where it comes from: user = from the orb's rim inward; tool/world = along the hypha from the toolpath/capability node; agent = from the nucleus; subagent = from a satellite |

### 9.4 The nine families on a landmark and its sector

| Family (live rows) | On the landmark / sector |
|---|---|
| memory (44,618) | RECALL_DELIVERED: a spark cluster → nucleus; RECALL_USED/HELPED: the hypha is lit by use; MISLED: an amber pulse; MISSED: a dashed ghost path; LANDMARK_PROMOTED: fruiting bloom; STALE/DEMOTED: cools and drifts out; DISSOLVED: the cluster disperses; LANDMARK_MERGED: two clusters spiral into one (fusion); SECTOR_BORN/PROVEN/SPLIT/MERGED/DISSOLVED: a region condenses / takes its label / the arm forks / segments join / fades into its parent; OFFLOADED/RESTRETCHED/PREMATURE_EVICTION: nucleus motes (live context, §2); CHAIN_*, STRAND_*: the time layer - beads on the timeline, not the galaxy |
| delivery (38,794) | outward: a spark from the claims used toward the rim and the artifact tissue. The most frequent family: summarised in the ticker, never one effect per row |
| intent (11,666) | GOAL_SET: a goal light settles on the arm of the task's sector; PREFERENCE_STATED: feeds the sector's style/conduct orbit |
| control (7,528) | the work's motion, at the nucleus and in the corridor: SPLIT = the nucleus fans out; PIVOT/REPLAN = a turn of its rotation; HALTED/BUDGET_HIT = a freeze with a desync |
| knowledge (4,027) | on the claim: CORROBORATED = a new evidence spoke and more sync; UPDATED = the crystal re-facets; CONTRADICTED = desync glitch and a crack; SOURCE_UNRELIABLE = the hypha to that source dims and the membrane gaps; BELIEF_STALE = cools |
| problem (464) | near the claim the work touches: OBSTACLE/BUG = an amber dust knot; ATTEMPT = a probe tip grows; DEAD_END = it pulls back; FIX = it connects; VERIFIED_FIX = the knot condenses into a star (a problem becomes knowledge) |
| feedback (345) | user evidence, the strongest: a ray from the rim into the claim; CONFIRMATION/APPROVAL seal the ring warm; CORRECTION/DENIAL crack it and it re-settles; CORRECTION_UNDONE reverses |
| safety (92) | Kyudo's immune response: the sector's membrane tightens and flickers; the offending source hypha is cut |
| environment (5) | the sector's capability/context orbit shifts; WORLD_CHANGED marks world-dependent claims "re-check" |

Rules carried over: at most 6 effects at once (the rest in the ticker); nothing builds
brightness; every effect is a real row; follow mode plays them live (`memory_event` tap).

## 10. Pins in the galaxy

A pin is HELD memory, not earned memory (MEMORY-INTERFACE §F13.3): someone chose to keep it,
it does not decay by the one law, and it carries the pinner's trust channel. Everything that
is earned in the galaxy moves (arms turn, clusters breathe, old claims drift out); a pin is the
one thing that stays still. That stillness is the whole visual idea.

| Where | A pin looks like |
|---|---|
| in its sector | a small faceted crystal in brackets, set at the inner edge of its sector's arm. It does NOT turn with the arm: it holds its place in the sector's frame, like a fixed star the arm slides past. Facet colour = pin type (note, file, folder, image, doc, url, decision, fragment, checkpoint) |
| its references | tethers: straight, taut, thin lines to what it holds (a claim cluster, an artifact, a strand). Straight on purpose - the living links are curved hyphae; a tether is a held line. Lit by use like the hyphae: dim at rest, bright when the pin is delivered or read |
| held in context | a bright ring on the crystal, and one tether into the nucleus where it is a fixed mote that never drifts out (a held block is not set aside) |
| a pinned claim (the "Pin" correction) | the cluster gets the bracket frame and stops drifting outward with age: it stays where it is while its neighbours age out |
| timeline / corridor | a fixed bead on its strand at the moment it was made; in the corridor, the crystal set into the wall at that turn (as today); a checkpoint pin marks the doorway of the strand it paused |
| events | PIN_CORRECTED re-facets the crystal; Pin / Unpin / Hold / Release (§8.3 of the interface) bracket, unbracket, ring and unring it |

Sector of a pin: the sector of what it holds (its tethers' landmarks, by weight), else its
topic by `resolve_topic_domain(title)`, else the nucleus side of `general`.

**Measured 2026-11-22 - what the view would draw today:**
- `mycelium_pins`: 62 rows, ALL `note`, ALL titled `fact:…` (synthetic memory-eval facts,
  e.g. "fact:quill-3e05 … retention class"), `origin_id` empty. There is no user pin yet; the
  surface hides eval pins by default like eval strands, so a real store shows "no pins yet".
- `mycelium_pin_links`: 56,325 rows and NONE has a pin as its source. They are the DER step
  lineage links of §F13.3 (`node:s1`, `node:s2`, … - plan-local step ids with no session
  scope), grown from 16,578 (2026-10-19) to 56,325, onto 48 distinct targets.
- **Fixed the same day:** DER links are `node:<session>:<step>`, a link is written once (unique
  index `idx_pin_links_unique`), DER links have a 20,000-row budget, and the 56,024 copies were
  removed (306 distinct rows left). The view still draws a pin's tethers only from links whose
  source is a real `pin_id`.
