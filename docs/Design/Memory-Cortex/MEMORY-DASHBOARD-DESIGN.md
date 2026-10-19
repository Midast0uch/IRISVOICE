# MEMORY_DASHBOARD_DESIGN.md — IRIS Memory Dashboard Layer

Status: DESIGN FOR HANDOVER, 2026-10-13. Reviewed 2026-10-14 against the live store and the
owner's vision: **section 16 is authoritative where it differs from sections 1-15** (data
gaps, value findings, corrections, the experience model). The reference mockup is
`docs/Design/Memory-Cortex/index.html` (open it directly for the demo data; run
`export_snapshot.py` and serve the folder to see this machine's memory with `?real`).
Read all of it before designing anything.

Read with: `docs/Design/EVENT_TAXONOMY.md` (the alphabet), `docs/architecture/oracle.md`
(the decision engine), `docs/architecture/RECALL_AS_COGNITION.md`,
`docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md`.

---

## 1. Purpose and audience

IRIS Voice stores everything it learns in one local file per user: `data/memory.db`.
Every user grows their own. The dashboard is the window into that file — the surface
where a user sees what IRIS remembers, what it has proven, and how it decides.

**The audience is the END USER of IRIS, not a developer.** Consequences:

- No internal jargon in visible copy. `mycelium_landmarks`, `ECE`, `criteria_version`,
  `valence`, `sigma_to` — these are our words, never the user's. Section 12 has the
  translation table. Column names never appear on screen.
- Tone: calm, factual, trust-building. The dashboard proves memory is working, it does
  not impress.
- Privacy is inherent but worth surfacing: all of this is local, in their file, on
  their machine. Say so once, plainly.
- Read-only. The user looks, filters, drills down. They do not edit, delete, or
  promote anything from this surface in v1.

## 2. What is prescribed and what is open

The owner will give the mockup agent a **foundational visual** (a base look). The
entire dashboard inherits that visual language.

| Area | Status in this doc |
|---|---|
| Data contracts (what each view shows, field by field) | PRESCRIBED — sections 4-9 |
| Semantics (what every value means) | PRESCRIBED — sections 4-9 + 12 |
| Live data path (REST + WebSocket contract) | PRESCRIBED — section 10 |
| Reactivity model (how the UI responds to the agent's memory activity) | PRESCRIBED — section 11 |
| Interaction spec (filter, drill-down, hover, transitions) | PRESCRIBED — section 13 |
| **Visual form of the live event stream and the episodes view** | **OPEN — the mockup agent designs these on top of the foundational visual** |
| Visual form of Landmarks, Timeline, Decisions | Guided (section 6-8 give content + suggested layout; the foundational visual wins on style) |

The mockup must run against a REAL `data/memory.db` (read-only) or a replayed copy.
Fake filler data is not acceptable — the point is that real memory drives the visuals.

## 3. The memory store — access rules

- **File**: `data/memory.db` at the repo root. SQLite, WAL mode. Row counts as of
  2026-10-13 (for realistic mockup data expectations): `memory_events` 18.8k,
  `memory_chain` 20.7k, `mycelium_landmarks` 2.0k (+6.6k edges, 1.8k merges),
  `episodes` 407, `caducean_trajectories` 5.2k, `context_chunks` 84.7k,
  `system_events` 44.9k, `der_fan_traces` 4.8k, `sessions` 108.
- **Read-only, always.** Every connection the dashboard opens must be
  `sqlite3.connect("file:data/memory.db?mode=ro", uri=True)` or the equivalent. The
  dashboard never writes to memory. Writes belong to the agent alone.
- **Never block the answer path.** All reads use `LIMIT`, run through the backend's
  API layer (not direct DB access from the frontend), and return under ~200 ms. The
  agent's writers use durability-queue lanes; the dashboard never touches those lanes.
- **No blobs, no embeddings to the frontend.** `embedding` (BLOB) and
  `document_blobs.data` columns never cross the wire. They exist for the backend only.
- **Everything JSON-safe.** Every endpoint returns `application/json`, ISO-8601 or
  epoch-second timestamps (existing tables mix both; the API normalizes to epoch
  seconds), camelCase or snake_case consistently (use snake_case, matching the
  existing WS payloads).

## 4. Layer 1 — The event stream (`memory_events`)

This is the canonical, append-only record of everything typed that happened.
18,801 rows today. This is the heart of the dashboard.

### 4.1 Full column semantics

| Column | Type | Meaning |
|---|---|---|
| `event_id` | TEXT PK | Unique per event. |
| `ts` | REAL | Epoch seconds (float, sub-second). |
| `schema_version` | INT | Alphabet version. Currently 1. |
| `episode_id` | TEXT | Links to `episodes.id` — "the task run this happened inside". |
| `step_index` | TEXT | Step id inside the episode (e.g. `s1`). |
| `thread_id` | TEXT | Conversation/session thread. |
| `family` | TEXT | One of 9 closed values (see 4.2). |
| `label` | TEXT | An open vocabulary word inside the family (see 4.3). |
| `valence` | TEXT | `advances` / `sets_back` / `neutral` — did this move the GOAL. |
| `actor` | TEXT | `user` / `agent` / `tool` / `world` / `subagent` — who caused it. |
| `evidence` | TEXT | `none` / `claim` / `verifier` / `test` / `completion` / `user` / `recurrence` / `corroboration`. |
| `cause_key` | TEXT | Failure address: `{retryable}.{blame}.{info_state}` (27 cells, closed). |
| `outcome_key` | TEXT | Result address: `{alignment}.{identity}.{yield_state}` (27 cells, closed). |
| `trigger` | TEXT | Closed enum — why a node failed or pivoted (`empty`, `challenge`, `transport_error`, `wall`, `robots_refused`, `permission_denied`, ...). |
| `exec_domain` | TEXT | Execution domain (e.g. `voice`, `der`, `research`). |
| `topic_domain` | TEXT | Topic domain from the registry. |
| `label_source` | TEXT | Who typed it: `rule` (exact, trusted) / `oracle` / `brain` / `user`. |
| `label_confidence` | REAL | 0.0-1.0, present on non-rule labels. |
| `sigma_from` / `sigma_to` | TEXT | Caducean phase before/after this event. |
| `hash_signature` / `hash_scheme` | TEXT/INT | Chain-hash address (Wormhole). Internal. |
| `action_signature` | TEXT | Dedup key for repeated actions. |
| `cost` | TEXT | JSON: `{ms, tokens_in, tokens_out, tool_calls, context_tokens}`. |
| `links` | TEXT | JSON: hyperedge pointers — `episode_id`, `case`, `claim`, `goal`, `chain`+`node_index`, `recall_trace_id`, `parent_event`. |
| `payload` | TEXT | JSON, bounded ≤ 2000 chars. References, never content. |

### 4.2 The alphabet (CLOSED — do not invent values)

Nine families. Each is a complete problem-solving arc. The user's UI never says
"family" — it says the plain word on the right.

| `family` | What it means | User sees |
|---|---|---|
| `intent` | The user stated, refined, or dropped a goal | Goal |
| `control` | The agent planned, pivoted, split, escalated, halted | Plan |
| `problem` | An obstacle, attempt, dead end, fix, verified fix | Problem |
| `knowledge` | Something observed, a claim confirmed or contradicted | Knowledge |
| `feedback` | User confirmed, corrected, approved, denied | Feedback |
| `delivery` | An answer, artifact, narration, card reached the user | Delivery |
| `memory` | A recall was delivered/used/helped/misled/missed; something offloaded, promoted, or went stale | Memory |
| `safety` | An unsafe action refused, injection suspected, permission denied | Safety |
| `environment` | A dependency changed, a resource limit hit, the world changed | World |

Three valences:

| `valence` | Meaning | UI weight |
|---|---|---|
| `advances` | Moved the goal forward | Positive |
| `sets_back` | Moved it backward | Attention |
| `neutral` | Neither | Resting |

Five actors:

| `actor` | Meaning |
|---|---|
| `user` | The human did or said it |
| `agent` | IRIS itself |
| `tool` | A tool returned it |
| `world` | Something external changed |
| `subagent` | A helper agent |

Eight evidence kinds — the trust dimension. **Five are OUTSIDE evidence** (something
other than the agent's own say-so confirmed it) and gate landmark promotion:

| `evidence` | Outside? | Meaning |
|---|---|---|
| `user` | YES | The user confirmed or corrected it |
| `completion` | YES | The task actually completed |
| `test` | YES | A test passed |
| `recurrence` | YES | The same thing held again later |
| `corroboration` | YES | An independent source agreed |
| `verifier` | NO (inside) | The internal reviewer liked it |
| `claim` | NO (inside) | The agent said it |
| `none` | NO | No evidence |

**The evidence ladder drives the visual emphasis everywhere.** User > recurrence /
corroboration > test / completion > verifier > claim > none. An event with `user`
evidence renders strong; one with `none` renders faint.

### 4.3 The labels (OPEN vocabulary — examples, not a closed list)

Labels are words inside a family. New ones appear over time; the UI must not crash on
an unknown label (show the family word + the raw label, never break).

- intent: `GOAL_SET`, `GOAL_REFINED`, `CLARIFY_ASKED`, `CLARIFY_ANSWERED`, `PREFERENCE_STATED`, `GOAL_ABANDONED`
- control: `PLAN_MADE`, `REPLAN`, `PIVOT`, `SPLIT`, `DELEGATED`, `ESCALATED`, `HALTED`, `BUDGET_HIT`
- problem: `OBSTACLE` (coding: `BUG`), `ATTEMPT`, `DEAD_END`, `RESOLUTION` (coding: `FIX`), `VERIFIED_RESOLUTION` (coding: `VERIFIED_FIX`)
- knowledge: `OBSERVED`, `CLAIM_CORROBORATED`, `CLAIM_UPDATED`, `CLAIM_CONTRADICTED`, `SOURCE_UNRELIABLE`, `BELIEF_STALE`
- feedback: `CONFIRMATION`, `CORRECTION`, `APPROVAL`, `DENIAL`, `NO_RESPONSE`
- delivery: `ANSWER_GIVEN`, `ARTIFACT_PRODUCED`, `NARRATED`, `CARD_SHOWN`
- memory: `RECALL_DELIVERED`, `RECALL_USED`, `RECALL_HELPED`, `RECALL_MISLED`, `RECALL_MISSED`, `APERTURE_DROPPED`, `OFFLOADED`, `RESTRETCHED`, `PREMATURE_EVICTION`, `LESSON`, `LANDMARK_PROMOTED`, `LANDMARK_STALE`, `LANDMARK_DEMOTED`, `CHAIN_CREATED`, `CHAIN_VARIANT`
- safety: `UNSAFE_REFUSED`, `ESCALATED_UNSURE`, `INJECTION_SUSPECTED`, `PERMISSION_DENIED`
- environment: `DEPENDENCY_CHANGED`, `RESOURCE_LIMIT`, `WORLD_CHANGED`

### 4.4 What the live-event view must communicate (visual form OPEN)

The mockup agent designs the visual. The data contract and behavior:

- **Newest first, live.** Newest events animate in at the top as the agent works, via
  the WebSocket (§10.2). Stream cap 500 entries in memory (existing pattern:
  `STREAM_CAP = 500` in `useMonitorData`).
- **Each event shows, in plain language**: what family it belongs to (as a colored
  word or icon), what happened (a one-line reading of the label — a translation
  table ships with the mockup), when (relative time), and how trustworthy (evidence
  ladder as visual weight, never the word).
- **Recall events are special.** `RECALL_DELIVERED` → `RECALL_USED` →
  `RECALL_HELPED` / `RECALL_MISLED` form a causal chain (linked by
  `links.recall_trace_id`). When `RECALL_HELPED` arrives, the thing that was recalled
  should visibly react — this is the centerpiece of the reactivity model (§11).
- **Filtering**: by family (the plain-word chips), by valence, by "only what IRIS is
  sure about" (evidence ∈ the five outside kinds).
- **Hover**: full detail — step, episode, payload refs, sigma transition.

## 5. Layer 2 — Landmarks (`mycelium_landmarks` + edges + merges)

A landmark is **a claim proven true by outside evidence**. 2,027 exist today. This is
the "what IRIS knows for sure" surface.

### 5.1 Columns that matter

| Column | Meaning |
|---|---|
| `landmark_id` | PK. |
| `label` | Short name. |
| `task_class` | The class of task it applies to (`bootstrap`, `implement`, ...). |
| `cumulative_score` | Standing score. |
| `micro_abstract_text` | One-line plain statement of the claim. **This is what the user reads.** |
| `tier` | `candidate` (gathering evidence) / `landmark` (proven). |
| `evidence` | JSON array `[{kind, ref, session, at}]` — the outside-evidence list. |
| `activation_count` | How many times it has been used. |
| `is_permanent` | 1 = survived enough to be permanent. |
| `last_activated` | When it was last used. |
| `last_verified` | When last re-confirmed. |
| `contradictions` | How many times something contradicted it. |
| `absorbed` | 1 = merged into another landmark. |
| `conversation_ref` | Where it came from. |

Edges (`mycelium_landmark_edges`): `from_landmark_id → to_landmark_id`, `score`,
`edge_type` (e.g. `similarity`), `traversal_count`, `hit_count`, `miss_count`.
6,628 today.

Merges (`mycelium_landmark_merges`): `survivor_id` absorbed `absorbed_id` with
`overlap_score`, pre/post merge scores. 1,806 today.

### 5.2 What the Landmarks view shows

- **A graph or organized collection of landmark cards.** Each card: the plain-language
  claim (`micro_abstract_text`), the tier as a plain badge ("Proven" / "Still
  learning"), the evidence count, "used N times" (`activation_count`), "last
  used ...", "last confirmed ...", and a small contradiction indicator if
  `contradictions > 0`.
- **Evidence strength as a whole-card treatment**, driven by the best outside evidence
  in the list. A landmark proven by a user confirmation renders stronger than one
  proven by a test alone.
- **Drill-down**: the evidence list (each with kind → plain word: "a user confirmed
  this", "a test passed", "it held up when it came up again"), the merge history, and
  the landmarks it connects to.
- **Reactivity**: when a live `RECALL_HELPED` event names this landmark, the card
  lifts (a pulse, a glow, a motion — mockup agent's call, consistent with the
  foundational visual). When `LANDMARK_PROMOTED` fires, a candidate visibly graduates.

## 6. Layer 3 — The timeline (`memory_chain` — Immortus)

20,743 rows. The time layer: an ordered, append-only record of what happened, in
order, per thread. Entries are transitions and references, never full payloads.

### 6.1 Semantics

| Column | Meaning |
|---|---|
| `thread_id` + `sequence` | Composite PK; the order within one thread. |
| `session_id` | Which session. |
| `role` | `system` / `user` / `agent` / etc. |
| `content` | The text or a compact reference. |
| `metadata` | JSON — `result`, `insight`, etc. |
| `session_ts` | When. |
| `result` | What came of it. |
| `coords_from` / `coords_to` | Caducean coordinate transition. |
| `nbl_outcome` | The transition's outcome tag (e.g. `research`). |
| `insight` | A distilled takeaway. |
| `landmark_id` | If this entry produced or touched a landmark. |
| `stale` | 1 = no longer current. |
| `node_type` | `task` / `step` / `sub_loop`. |
| `topic_domain` / `execution_domain` | Domain axes. |

### 6.2 What the Timeline view shows

- **Sessions as scrollable blocks** (108 today), most recent first. Each block: the
  session's objective in plain words (`sessions.objective`), time span, how it ended
  (`sessions.ended_at` present or not), and the chain entries inside it.
- **Entries rendered crisply**: icon by `role`, the content or reference, the outcome.
  `coords_from → coords_to` render as a small directional indicator (expand vs
  compress), never numbers. `insight` surfaces as an italic takeaway.
- **Reactive**: the active session's block is "live" — new entries append and scroll.
  A `stale` marker appears when an entry goes stale.
- **Caducean trajectories back this view** (`caducean_trajectories`, 5.2k rows): per
  step, `x` `y` `xi` `u`. The user never sees the letters; the view can use them to
  draw a smooth "work phase" line per session if the foundational visual calls for it.
  The endpoint `/api/caducean/state` already exists — reuse it.

## 7. Layer 4 — Episodes

407 rows. One row per task run: what was asked, what happened, how it went.
**Visual form OPEN — the mockup agent designs it.**

### 7.1 Data contract

| Column | Meaning | User-facing |
|---|---|---|
| `task_summary` | What was asked | The title |
| `outcome_type` | `success` / `partial` / `failure` | Plain word |
| `outcome_score` | 0.0-1.0 | A "went well" 0-100 meter |
| `failure_reason` | Why it failed | Plain words |
| `user_corrected` / `user_confirmed` | 0/1 | Strong signals — a correction stands out |
| `duration_ms` | How long | Human time |
| `tool_sequence` | JSON list of tool steps | "what I did" list |
| `model_id` | Which model | Optional detail |
| `timestamp` | When | Human time |

### 7.2 Behavior requirements

- Outcome drives the card's whole tone: success calm, partial middling, failure
  attention (red/orange per the foundational visual).
- A `user_corrected = 1` episode is a distinct, important kind — "you corrected IRIS
  here" — and must be visually findable.
- Drill-down: the tool sequence, the failure reason, links to the memory events it
  generated (via `memory_events.episode_id`), and the landmarks it touched.
- Reactive: when a new episode completes, it enters the view with the same family of
  motion as the live event stream.

## 8. Layer 5 — How IRIS decides (the Oracle panel)

This view translates the Oracle's internal shadow → enforced ladder into something a
user can read: **is IRIS learning to decide this itself, and can it be trusted yet?**

### 8.1 The underlying mechanism (for the builder, not the user)

- The Oracle is one small local model (`d1-3B-AD`) that answers ONE question per run
  with a probability distribution.
- **Consumers** are decision points. Today: `tool_choice`, `escalate_incomplete`,
  `needs_action` are **enforced** (they act); `review_verdict` is **sampled** (acts
  5% of the time, read-only); the rest are **shadow** (they watch and learn, never
  act).
- Every consumer climbs the same ladder, gated by a measured bar: ≥100 distinct rows,
  both classes ≥5%, AUROC ≥0.65, precision ≥0.90 at threshold, Wilson lower bound
  ≥0.85, ≥50 rows above threshold, ECE ≤0.05.
- Decision rows live in `system_events` where `event_type = 'tool_execution'` and the
  `interaction_payload` JSON carries the decision fields.
- The bar status persists in `benchmarks/consumer_bar_record.json`; calibration in
  `benchmarks/oracle_calibration.json`.

### 8.2 The 16 consumers and their current state (2026-10-13)

| Consumer | Job | State | Progress |
|---|---|---|---|
| `tool_choice` | picks the next tool | **ENFORCED** | 688 rows, AUROC 0.76, ECE 0.019 |
| `escalate_incomplete` | is this result incomplete? | **ENFORCED** | 513 rows, AUROC 0.84 |
| `needs_action` | does this step need a tool? | **ENFORCED** | 216 rows, AUROC 0.80, precision 0.92 |
| `review_verdict` | pass / refine / veto a step | SAMPLED | 1381 rows, AUROC 0.63 (just under 0.65) |
| `user_feedback` | what does this message mean? | shadow | 165 rows, AUROC 0.91, ECE 0.054 (just over 0.05) |
| `narration` | should this be narrated? | shadow | 332 rows, ECE 0.054 |
| `browser_next` | next browser element | shadow | 126 rows |
| `tool_approval` | will this call succeed? | shadow | 1880 rows, weak AUROC |
| `depth_met` | is it done and deep enough? | shadow | 401 rows, AUROC 0.40 |
| `web_intent` | does this need the web? | shadow | 199 rows, AUROC 0.49 |
| `click_safety` | is this click safe? | shadow | 92 rows |
| `call_closing` | was that the final call? | shadow (refused by design) | 657 rows |
| `recovery_strategy` | how to recover? | shadow | failure-only path |
| `sufficient` | is the answer sufficient? | shadow | failure-only path |
| `event_family` | classify an event's family | shadow | low rows |
| `event_type:*` | classify an event's label | shadow | low rows |

### 8.3 What the Decisions view shows

- **One row or card per consumer**, plain name from the translation table (§12), its
  state as a ladder position: **Watching** → **Trying out** → **Trusted**.
- **Progress toward trust**: "142 of 100 examples learned" style, using the row
  count and the bar clauses. Never show AUROC/ECE to the user as-is — turn them into
  "how often it's right" and "how well-calibrated" plain statements in the drill-down.
- **A recent-decisions strip**: the last N decisions this consumer made, with
  confidence rendered as a simple dial or bar, and whether the Oracle acted or
  deferred.
- **Reactive**: when a consumer crosses the bar and the owner switches it on, it
  visibly graduates from Watching/TryingOut to Trusted. The panel is the proof the
  system learns.

## 9. Supporting tables

| Table | Rows | Use |
|---|---|---|
| `caducean_trajectories` | 5.2k | Per-step phase (x, y, ξ, u) — backs Timeline |
| `caducean_session_exits` | 5.0k | How each session ended (natural exit, drift) |
| `context_chunks` | 84.7k | Semantic fragments with embeddings — counts only, no blobs |
| `semantic_entries` | 2.0k | Distilled facts (category, key, value) |
| `system_events` | 44.9k | Tool executions incl. Oracle decisions |
| `sessions` | 108 | Session headers |
| `user_display_memory` | 1 | Learned display names |

## 10. The live data path

### 10.1 WebSocket contract (existing — reuse it)

The frontend already receives events on a `window` CustomEvent named
`iris:ws_message` whose `detail` is `{type, payload}`. Dispatchers: `ws_manager.broadcast` / `send_to_client` in `backend/ws_manager.py`. Existing memory message
types: `memory/stats`, `memory/preferences`, `memory/error`.

**Proposed additions** (new, this design):

- `memory_event` — one new `memory_events` row, broadcast at write time from the
  `memory_events` durability lane (the single writer). Payload: the row's fields,
  minus any blob, payload JSON parsed.
- `landmark_update` — activation, promotion, staleness, merge on a landmark. Payload:
  `{landmark_id, label, kind: activated|promoted|stale|merged, activation_count, evidence_best}`.
- `episode_completed` — an episode row finalized. Payload: the episode minus embedding.
- `oracle_decision` — a decision event for the Decisions strip. Payload:
  `{consumer, confidence, acted, outcome_label, ts}`; a state change on a consumer
  emits one with `acted: "enforced"`.

The mockup may implement these as a simple tailer (poll `memory_events` by `ts` every
~1 s and diff — `idx_memory_events_ts` exists) if wiring the lane writers is out of
mockup scope; the WS contract is what matters.

### 10.2 REST snapshot endpoints (read-only, all `LIMIT`-bounded)

| Endpoint | Returns |
|---|---|
| `GET /api/memory/events?limit=200&before=<ts>&family=<f>&evidence=<e>` | Event stream page |
| `GET /api/memory/landmarks?tier=&limit=100` | Landmark cards |
| `GET /api/memory/landmarks/{id}` | One landmark: evidence, merges, neighbors |
| `GET /api/memory/timeline?session=<id>&limit=N` | Chain entries |
| `GET /api/memory/sessions?limit=20` | Session blocks |
| `GET /api/memory/episodes?limit=50&outcome=` | Episode cards |
| `GET /api/memory/episodes/{id}` | Episode detail + linked events |
| `GET /api/memory/oracle/consumers` | Consumer states + bar progress |
| `GET /api/memory/oracle/recent?limit=50` | Recent decisions |
| `GET /api/caducean/state` | (EXISTS — reuse for the phase line) |

All endpoints sit behind the existing backend API (`backend/main.py`), never touch the
DB directly from the frontend, open read-only connections, and always `LIMIT`.

## 11. The reactivity model — how it responds to the agent

Inspired by the Oracle's operation: the dashboard is not a query tool, it is a live
reflection. The user should *see memory being used*.

| Agent does | The dashboard does |
|---|---|
| Writes any `memory_events` row | The live stream inserts it (animated in) |
| Recalls a landmark into a turn (`RECALL_DELIVERED`) | That landmark's card "wakes" subtly |
| The recall gets used (`RECALL_USED`) | The wake strengthens; a thread-line links the event to the landmark |
| It helped (`RECALL_HELPED`) | A clear positive pulse on the landmark, and the episode advances |
| It misled (`RECALL_MISLED`) | A caution pulse — the contradiction count ticks |
| Promotes a landmark (`LANDMARK_PROMOTED`) | The card graduates from candidate to proven |
| A user corrects IRIS (`CORRECTION`, `actor: user`) | The strongest emphasis — user outside evidence outranks all |
| An episode completes | It enters the episodes view, tone set by outcome |
| The Oracle decides (`oracle_decision`) | The decisions strip updates; on state change, the consumer graduates |

**Emphasis follows the evidence ladder, always.** A `user`-evidenced event is the
strongest thing on screen. A `none`-evidenced event is the faintest. This hierarchy
is the single most important visual rule in the whole design.

## 12. The translation table (internal → user)

Never show the left column. Always show the right.

| Internal | User sees |
|---|---|
| `mycelium_landmarks` | "What IRIS knows for sure" / Landmarks |
| `tier: candidate` | "Still learning" |
| `tier: landmark`, `is_permanent: 1` | "Proven" |
| `memory_chain` | "Timeline" / "History" |
| `memory_events` | "Activity" / "What happened" |
| `valence: advances` | "helped" (positive tone) |
| `valence: sets_back` | "set back" (attention tone) |
| `evidence: user` | "you confirmed this" |
| `evidence: test` | "a test passed" |
| `evidence: completion` | "the task finished" |
| `evidence: recurrence` | "it held up again" |
| `evidence: corroboration` | "an independent source agreed" |
| `evidence: verifier` | "the reviewer checked it" |
| `evidence: claim` | "IRIS reported this" |
| `evidence: none` | "unconfirmed" |
| Oracle `enforced` | "Trusted" |
| Oracle `sampled` | "Trying out" |
| Oracle `shadow` | "Watching" / "Learning" |
| `RECALL_HELPED` | "remembering this helped" |
| `RECALL_MISLED` | "remembering this misled" |
| `LANDMARK_PROMOTED` | "IRIS is now sure about this" |
| `CORRECTION` | "you corrected IRIS" |
| `UNKNOWN` families | "Other" |

## 13. Interaction specification

- **Filtering**: family chips across the event stream; evidence-strength toggle
  ("only what IRIS is sure about"); time-range on the timeline; outcome on episodes;
  state on decisions. Filters combine with AND. A filtered-empty state says so
  plainly ("Nothing like that yet").
- **Drill-down**: every card, event, landmark, episode, session opens a detail view
  with the full record in plain language. The raw JSON is available behind a
  "Technical" disclosure, never by default.
- **Hover**: secondary detail (exact time, ids, evidence kind) on hover, always
  subtle.
- **Transitions**: new items animate in from the top of the stream; state changes
  (promotion, graduation, staleness) animate in place; the emphasis change on
  recall-helped is a single noticeable motion, not a loop. All motion honors
  `prefers-reduced-motion`.
- **Read-only**: no edit affordances anywhere in v1.
- **Empty states**: every view has a calm, true empty state ("Nothing remembered here
  yet — use IRIS and it will grow").
- **Performance**: stream cap 500 items, list virtualization beyond ~200 rows,
  images/blobs never loaded to the frontend.

## 14. What the mockup agent delivers

1. **A working mockup** (single Next.js route, e.g. `app/memory/page.tsx`) rendering
   the five views against a REAL read-only copy of `data/memory.db` or replayed
   traces.
2. **The live event stream and the episodes view get the agent's own visual design**,
   built on the foundational visual, honoring the data contract (§4.4, §7) and the
   reactivity rules (§11) exactly.
3. **Landmarks, Timeline, and Decisions follow §5-§8** for content; style from the
   foundational visual.
4. **The WebSocket contract (§10.1) is used as the live tap shape**, even if the
   mockup tails the table.
5. All copy comes from the translation table (§12). No internal jargon on screen.

## 15. Guardrails

- Read-only. Never write `data/memory.db` from this surface.
- Never block the agent's answer path — read-only connections, `LIMIT` everywhere,
  no unbounded queries.
- No blobs or embeddings to the frontend.
- The evidence ladder is the visual hierarchy everywhere. Do not flatten it.
- Jargon never crosses onto the screen.
- If the DB is missing or locked, show a calm empty state, never an error dump.

---

### Appendix A — quick file pointers

- Event taxonomy: `docs/Design/EVENT_TAXONOMY.md`
- Oracle: `docs/architecture/oracle.md`
- Event writer: `backend/memory/memory_events.py` (lane: `memory_events`)
- DB helper: `backend/memory/db.py` (`app_write`, `resolve_memory_store_path`)
- WS manager: `backend/ws_manager.py`
- Existing dashboard: `app/dashboard/page.tsx`, `components/dashboard/`
- Monitor data pattern: `components/dashboard/monitor/useMonitorData.ts`
- Ontology recall: `backend/agent/ontology_recall.py`
- Research memory: `backend/agent/research_memory.py`
- Bar + calibration: `benchmarks/consumer_bar_record.json`,
  `benchmarks/oracle_calibration.json`

---

## 16. Review 2026-10-14 — gaps, live-store findings, and the experience model

Reviewed against a read-only inventory of `data/memory.db` (590 MB, 2026-10-14), the
owner's two reference videos, `docs/Design/Aurora-Concept` and `components/iris/XurOrb.tsx`.
Reference mockup: `docs/Design/Memory-Cortex/index.html` (+ `export_snapshot.py`).

### 16.1 Corrections to sections 1-15

| Section | Was | Correct |
|---|---|---|
| §1, §13, §15 "read-only" | The user only looks | The owner wants **one place to see AND manage** what IRIS keeps. The surface still never writes the store; management actions are *requests to the agent* (§16.5). |
| §3 row counts | `mycelium_landmarks` 2.0k | **120 are live**; 1,907 are absorbed into survivors. Count and draw live ones (`COALESCE(absorbed,0)=0`); merges are history inside a survivor. |
| §3 "no blobs" | Never send images | Images and captures ARE content the owner wants to see. Add a bounded **thumbnail endpoint** (§16.3); never send the raw blob or an embedding. |
| §6.2, §9 `sessions` (108) | Session headers | `sessions` is **build-store (MCM) data**, like `code_events`, `file_nodes` and `landmarks` there. (Pins are not in that list: the application has its own, `mycelium_pins`, and the cortex draws them — §17.1.) A session on this surface is a **thread**: `memory_events.thread_id` (2,850), titled from `data/conversations.db conversations.title`, shaped by `caducean_trajectories` (`session_id` = thread id; `caducean_session_exits.conversation_id` maps the rest). |
| §8.2 "16 consumers" | 16 | `consumer_bar_record.json` holds **24** (3 enforced, 1 sampled, 20 shadow). Read the list from the file; never hard-code it. |
| §5.1 evidence kinds | The alphabet's eight | Landmark evidence is written as `task_complete` / `test_pass` / `recurrence` (60,960 entries over 2,027 rows). Map: `task_complete→completion`, `test_pass→test`. |
| §2, §5-§8 suggested layouts | Cards, strips, rows, panels | **Superseded by §16.4.** No card grids, list panels or side drawers. Text appears as typography anchored to the thing it describes, with a leader line. |

### 16.2 What the live store shows (the dashboard will expose these; the spec must handle them)

Measured 2026-10-14, read-only. Each is a HIDDEN-FAILURE shape (CLAUDE.md): the code runs, a
value is wrong, nobody looked.

| Finding | Value | Consequence for the dashboard |
|---|---|---|
| Recall never names its thought | `RECALL_DELIVERED.payload.refs` = episode ids; `RECALL_HELPED` carries only `recall_trace_id`; no event names a landmark | §11's centrepiece ("the recalled landmark lifts") has **no data**. Contract fix (backend): `RECALL_*` events carry `links.landmark_id` / `links.episode_ids`. Until then the dashboard joins HELPED→DELIVERED by `recall_trace_id` and lights the recalled **episodes**. |
| "Helped" is near-constant | 2,272 HELPED vs 2,321 DELIVERED; **0** `RECALL_USED`, **0** `RECALL_MISLED` | The label does not discriminate. Do not render "helped" as proof until USED/MISLED are emitted. |
| Landmarks are never used | `activation_count` max **3**, mean 0.04 | "Used N times" is 0 everywhere. Show it honestly; it is the measurement that recall does not reach landmarks. |
| Edges never walked | 6,628 edges, **one** type (`similarity`), `traversal/hit/miss` all **0** | Axon pulses must be driven by real traversals (0 today), not decoration. |
| Learned landmarks have no statement | 90 of the 120 live rows have no `micro_abstract_text`; the 30 that have one are all `bootstrap` seeds (build facts) | Not one learned certainty can be read in words today. Fall back to `label`; show seeds as "how IRIS was built". Writer fix: set the statement at promotion. |
| The memory is mostly tests | 15,684 of 18,801 events are `eval-*` threads | Default filter **"your use" vs "test runs"** — otherwise the user's mind is mostly eval noise. |
| Empty families | `problem` = **0**, `environment` = **0**, `feedback` = 42 | The problem arc (OBSTACLE→FIX→VERIFIED_FIX) is never written; `memory_cases` is 0 rows. Regions must render empty honestly ("nothing yet"). |
| Evidence is mostly absent | `none` = 12,748 of 18,801 events | The evidence ladder will look faint; that is true. |
| Things made have no names | `document_data`: 8 of 471 titled; `kind` NULL on 459 | Names fall back to summary/format. Writer should set `title` + `kind`. |

### 16.3 Data the doc did not cover (add to §9-§10)

| Store | Rows | Why it belongs here |
|---|---|---|
| `der_fan_traces`, `der_commits` | 4.8k, 5.2k | The DER fan-out / fold-back of every step — the neuron activity of a task. Drives splits in the session tunnel. |
| `document_data` (+ `document_blobs` thumbnails) | 471 (+7) | Everything IRIS made or captured: research records (223), images, documents, web captures (`capture_path`). The artifact tissue. |
| `mycelium_traversals`, `mycelium_episode_index`, `mycelium_plan_stats` | 2.3k, 2.5k, 2.3k | Recall routes walked, episode↔landmark index, plan outcomes per task class. |
| `mycelium_profile`, `mycelium_spaces`, `mycelium_nodes` | 4, 7, 116 | The rendered self-description and the coordinate spaces. |
| `semantic_entries` (+ `user_display_memory`) | 2.0k (+1) | Distilled facts and preferences; `named_skills` = learned skills (1). |
| `mycelium_pin_links` | 11.9k | Links that recall walks (`ontology_recall`). |
| `context_chunks` | 84.7k | Fragments — counts and zones only (`reference` = untrusted web). |
| The live context window (CLM / Aperture) | live | "What is on IRIS's mind right now" — not stored; needs a WS message (§16.6). |
| `consumer_bar_record.json` gap text | 24 | Each consumer's plain "what it still needs" (`gap`). |

New endpoints: `GET /api/memory/artifacts?limit=` (names, kinds, session, time),
`GET /api/memory/artifacts/{id}/thumb` (≤ 256 px, cached, never the blob),
`GET /api/memory/threads?limit=&scope=use|tests`, `GET /api/memory/search?q=` (claims,
thread titles, artifact names — `LIMIT`ed, uses existing indexes), `GET /api/memory/health`
(store size, growth, absorbed share, eval share — the numbers in §16.2).

### 16.4 The experience model — the Memory Cortex

Owner direction: it must feel like looking inside a living brain, not clicking dots that open
panels; use the orb's own body, not its orbit; sessions are their own dimension but stay
connected; navigation is first-person at times; media shows as in the owner's video
(organic Voronoi tissue); it must be captivating enough to watch while IRIS works; it must
beat Obsidian as a knowledge base.

**One organism, four forms.** The orb is the dashboard. Its ~42k skin particles morph between
forms with a staggered swarm transition (no cuts):

| Lens | Form | Data | Meaning of the form |
|---|---|---|---|
| cortex | Aurora sphere: fresnel skin, pulse wireframe, inner core, comet rings | event families as **regions of the skin's own lattice** — the geodesic cells fill with the family colour and the wire inside takes it (size = count, glint = live activity; no painted decoration); landmarks as **neurons filling the whole volume** (soma + dendrites; candidates short and flickering; contradiction = red fracture), each **wired by a tract to the skin region its knowledge belongs to**; edges as axons | what IRIS knows, and where activity lands — skin and interior are one body |
| timeline | Caduceus: two serpents around a staff | sessions as beads on the staff; serpent width = Caducean x (expand/compress) over time | the time layer (Immortus) |
| artifacts | the skin exhales spores that settle as **organic Voronoi tissue** beside the orb | `document_data` thumbnails; cell size = weight, grows on hover; words around the rim per kind with leader lines | what IRIS made and saw |
| how IRIS decides | an **iris**: radial fibres, one sector per Oracle decision point; the XurOrb 9-lobe flower is the collarette; the core is the pupil | fibre length = share of the bar met; trusted / trying out / watching = colour; each decision ripples its sector and dilates the pupil | is IRIS learning to decide, and can it be trusted yet |

**Going inside.** Clicking a region opens it like an iris aperture; the camera passes through
the skin into the knowledge forest (first-person: drag to look, W/A/S/D or scroll to move).
The whole entry is ONE continuous flight (a spline: swing round to the region, the cells open
as the camera nears, pass through, settle inside); leaving retraces it. The thoughts that
region touched stay lit; the rest fades far back. Neurons read as **tissue, not hair**: a
nucleus (evidence colour), a visible membrane, tapered dendrites in a per-kind hue, and
connections drawn as tapered particle strands. Hovering a neuron makes it **swell into an
organic cell with its full statement inside** (the artifact-cell language; dark fill, glowing
membrane in the evidence colour, high-contrast text); clicking flies to it, the cell holds the
whole record, evidence orbits it as satellites (user = largest, brightest), and "→ step into
that session" opens the thread it was learned in.

**A session is its own dimension: fibre tissue** you travel through in time, like looking into
the synapse of a neuron (owner, 2026-10-19; replaces the earlier hex-ribbon vortex). Each thread
or strand is a **bundle of many fine fibres** — the threads of cloth, the fibres of a muscle
bundle — that twist round their own axis, part and rejoin; never hex cells, never boxes. Thick
bundles come from `conversations.db` (the thread, and any strand forked from it via
`parent_id`; one lit run of fibres per message); thin bundles come from `memory.db` (one per
event family; one lit run per moment). The bundles twist together round the tunnel; hovering a
message lights the moments of that turn and draws the links, and hovering a moment lights its
turn. A fan-out opens the thread into parallel bundles that fold back (DER). Each task is a
band of fibres round the tunnel (red = failed, amber = partial, white = **you corrected
IRIS**). A faint pulse runs along the fibres at the pace of the session's own attention
(Caducean u); the tunnel's width follows x. Pins are fixed beads on the thread (§17.1). Neurons
the session touched sit on the rope as the same glyph as in the cortex, joined by a tissue
thread; click one to follow its thread (scroll / ← → step neuron to neuron; Enter opens it in
the mind). A **thread rail** at the bottom shows the session's neurons and tasks in time; click
to travel. The tunnel is lined with very faint background fibres and a fine haze of particles (the
synaptic space). The far end is a **doorway** — an arch that opens onto the next thread (or back to
the timeline for the newest); a side door returns to this thread's beginning. Rope width
follows the Caducean trajectory; the cortex glows behind the entrance. **The doorway is a tall
arch with a soft edge — no rim line, nothing round or puckered.** The tunnel's fibres part
round it and end on its outline, so the arch is framed by them; inside it the swirl turns
slowly. A checkpoint pin of the thread (§17.1) sits at the crown of the arch.

**The neuron glyph** (cortex and tunnel alike): a small nucleus with radial spokes, one per
share of evidence, coloured by kind (white you · green tests/finished · cyan held up again ·
grey IRIS's word); spoke length = use; short faded spokes = still learning; red broken spokes
= contradicted; thin outer ring = permanent; membrane hue = kind of knowledge. Low glare.

**Connected as one organism.** Every neuron links to its two nearest neighbours and sends two
tracts that land on real lattice nodes of the skin (one to its region, one straight out);
each connection is a fine line inside a tapered particle strand.

**Things made are layered:** format (images, videos, audio, documents, code, web captures,
charts, test runs) → folder → the item. No connecting lines (owner, 2026-10-18): a focused
item names the thread that made it and steps into it. A breadcrumb and Esc move between layers.

**The XurOrb shells are attention.** The three 9-lobe epitrochoid shells fill the interior
in 3D (outer lobes graze the skin; lobes rise and fall, each curve a dim particle tube, each
shell tumbling on its own axis), weaving through the neurons, breathing with Caducean x and
spinning with u. On a recall, a stream of shell particles peels
off, reaches the recalled thought, and flows back.

**The core is the mind right now.** Hovering the core shows what is in the live context
window as motes orbiting it; set-aside thoughts drift out, restretched ones return.

**Reactivity (replaces the table in §11 where it differs).** Every event lands on its family's
cells (a ripple runs out across the lattice) and fires a spark (action potential) down a
tract into a neuron wired to that region; `sets_back` turns the wireframe
pulse red; a **user** event (correction, confirmation) sends the Aurora shockwave through the
whole orb — the strongest thing on screen, per the evidence ladder; a promotion grows a
candidate's dendrites to full length; HELPED = white pulse ring, MISLED = red ring + the
contradiction count ticks.

**Beyond Obsidian.** `/` searches everything and lights the matching thoughts inside the
whole mind (non-matches dim); Enter flies to the best match. The time scrubber shows the mind
as it was on a date; `g` replays its growth. Every object links to where it came from
(thought → session → task → what was made), so navigation is by meaning, not by folder.

**Typography, not panels.** Region names are small lower-case monospace labels with leader
lines (owner video 2), with a dark glyph halo for contrast. Anything with a record (a thought,
a moment, a task ring, a session bead) opens as a swelling cell grown from its own point, text
inside; no boxes, cards or drawers. Region activity is capped so a busy region never washes
out the orb. The jargon rule (§12) holds.

### 16.4b The lattice and the domains — DECIDED: option A (owner, 2026-10-18)

The lattice's regions are **topic-domain territories** (registry values below; plain names
"everyday, the web, science, data, money, AI & models, design, mobile, systems & code,
running things, security, hardware"), sized by how much each holds. The event **families are the
activity inside a territory**: a moment lands in its domain's cells and ripples in its family's
colour; each territory's label lists its three busiest kinds of activity. Neurons sit in, and
their tracts run to, the territory of their domain; diving into a territory lights its neurons.
Built in the mockup. Data it needs (backend, before this is truthful on real data): every
`memory_events` row and every landmark carries `topic_domain` (landmarks have no domain column
today, so on real data every neuron sits in "everyday"), and `caducean_trajectories.domain` stops
being a constant.

Background (measured 2026-10-18):

Today the skin's regions are the 9 event families. Domains are barely written (measured
2026-10-18, read-only): `memory_events.topic_domain` / `exec_domain` NULL on ~90% (rest
`general` / `der`); `caducean_trajectories.domain` is `general` on **every** row (a constant —
hidden failure); only `memory_chain.topic_domain` carries 12 real values (general, web, science,
data, finance, ai, design, mobile, systems, devops, security, hardware) on ~23% of rows. The
Mycelium coordinate graph has 7 spaces (`conduct, domain, style, chrono, context, capability,
toolpath`). Options for what the lattice organizes: (A) topic domains as territories with
families as cell activity inside; (B) the 7 Mycelium spaces as lobes; (C) families stay on the
skin, domains become depth layers inside. Any option needs the domain writers fixed first.

### 16.5 Managing memory (proposal — owner decision)

The surface never writes `data/memory.db`. Each action is a request the agent executes on its
own lane, and each is recorded as a `feedback` event with `actor: user`, `evidence: user` —
the strongest outside evidence there is, so managing memory also teaches it:

| Action | Agent does |
|---|---|
| "This is right" on a thought | CONFIRMATION → evidence `user` appended; may promote |
| "This is wrong" | CORRECTION → contradiction +1; demote or retire |
| Forget this | retention path deletes the row(s) + its fragments; a `memory` event records that it was forgotten (no content) |
| Keep this in mind | pin into the context window for the current thread |
| Hide test runs | view filter only; no write |

### 16.6 Live tap additions (extend §10.1)

`mind_window` (`{in:[{ref,label}], out:[...]}` on each CLM/Aperture change),
`attention` (`{x,u}` Caducean position for the breath — reuse `/api/caducean/state` on the
same 500 ms cadence as `useCaducean`), and `landmark_id` on every `RECALL_*` event (§16.2).

### 16.7 Budgets and accessibility

- **GPU is shared with local models.** Cap device pixel ratio at 1.6; drop it when frames fall
  under 28 fps; render nothing when the window is hidden; one draw call per particle system.
  Measured target: ≤ 8 ms GPU per frame at 1440×900 on the owner's machine, with the tool
  model loaded.
- **Bounded scene.** ≤ 50k skin particles, ≤ 400 neurons drawn (the rest as dust), ≤ 3k axons,
  tunnel built on entry and disposed on exit (about 200k fibre samples, one draw call for all fibres).
- **Reduced motion.** `prefers-reduced-motion`: cuts instead of flights, no auto-drift,
  sparks slowed, shockwave becomes a brightness change.
- **Not only visual.** Every object has a text equivalent reachable by keyboard (Tab through
  regions → thoughts → sessions; Enter goes in, Esc comes out); the search box is the
  accessible entry point.


---

## 17. The Kyudo and growth concepts in the cortex (2026-10-19)

Source of each concept: `MEMORY-FOUNDATION-ANALYSIS.md` §5 (sectors, spaces), §6 (Σ as the visual
expression), §11 (the growth and decay law), §12-§14 (Kyudo), §13.3 (pins). Every one is driven by a
real value when the page runs with `?real` (`export_snapshot.py` reads the tables read-only and detects
missing tables and columns with `PRAGMA table_info`; `meta.available` lists what it found) and by
plausible demo data otherwise. A store that has none of a concept's data shows none of it, with no error.

Rules that hold for all of them (owner, standing): low brightness that never builds up over time;
glyphs not too bright; neurons distinguishable, not hair-like; smooth transitions; text inside a swelling
cell only at cortex level (the timeline keeps leader-line labels). Strands of landmark tracts are drawn
dimmer as there are more of them (`uEdge`), so a store with 3,000 edges does not glare.

### 17.1 Pins — explicit memory

- **Means:** something the user or IRIS chose to hold: a note, file, folder, image, document, web page,
  decision, fragment or checkpoint. Held, not earned: a pin does **not** fade by the §11 law.
- **Data:** `mycelium_pins` (type, title, tags, refs, created, is_permanent) and `mycelium_pin_links`
  (what it references). Link count = refs in the links table + file, image and URL refs. "Held in
  context" has no stored flag yet; the exporter reads the tag `held` or `context` (the live context
  window would send `mind_window`, §16.6). The territory comes from a tag or project naming a sector, else
  from the landmarks the pin is tied to, else "everyday". The thread comes from a `thread` link, else from
  the thread whose time span contains the pin. **The live table has 0 rows (2026-10-19): `?real` shows
  no pins.** The demo shows 17.
- **Looks:** cortex — a small, still, faceted crystal (a slim hexagonal point, like quartz) set into the
  inner wall in its territory (its nested sector when it has one), pin-type colour (note warm yellow,
  file blue, folder slate, image pink, document pale, web page teal, decision amber, fragment violet,
  checkpoint pale gold), size by link count. Fine, taut, straight tethers run to what it references (a
  certainty, a node; a thing made — that tether shows in the artifacts lens, where the tissue settles). A
  thin ring round the base = held in context, and its tethers are a little brighter. Hover swells a cell
  with the title, type, link count and age. Timeline — a fixed bead of the same crystal on its thread at the
  moment it was made; the thread's fibres part round it; a tether runs on to the doorway when later threads
  used it; a checkpoint pin sits at the crown of that thread's doorway. A diamond mark on the thread rail.
- **Over time:** nothing moves or pulses. A pin appears when it is written and stays until removed.

### 17.2 Trust channel (Kyudo) — the membrane

- **Means:** the channel a source arrived on sets how much it may write, how fast it fades and what it
  can become: 4 system, 3 you, 2 verified, 1 outside, 0 untrusted; NULL = legacy internal (§12).
- **Data:** `mycelium_nodes.source_channel` for a node; for a landmark, the highest `source_channel` of the
  episode-index rows that name it (`mycelium_episode_index`). Both columns may be missing or NULL on a store
  that predates Kyudo: the page then draws the plain sealed membrane.
- **Looks:** the membrane of a neuron glyph (cortex and timeline) and of a node. A strong source keeps it
  sealed and a little warm; a weak one leaves gaps in the ring (up to most of it for untrusted), a faint
  dashed halo that leaks outward, and a paler, cooler hue. It only ever dims: never brighter than a sealed
  cell.
- **Over time:** static texture. It changes only when the stored channel does (a reconfirmation by a better
  source raises it, §12.1).

### 17.3 Fading — the §11 law

- **Means:** only confidence above the 0.4 floor was earned; what is not renewed sinks back to the floor.
  Edge and tract strength follows score, firmed by evidence (§11.2: a belief with more proofs moves more
  slowly in both directions).
- **Data:** `mycelium_nodes.confidence`; `mycelium_edges.score`, `observation_count`, `traversal_count`;
  `mycelium_landmark_edges.score`, `traversal_count`.
- **Looks:** a node's opacity and saturation follow `(confidence - 0.4) / 0.6`: a node on the floor is a
  pale, nearly grey ghost, a well-earned one is full colour. A tract's thickness (particle count and spread)
  follows `(0.3 + 0.7 score) * (0.55 + 0.45 evidence)`, with evidence = log of the count. On the live store
  every landmark edge has score 0.4 and no traversals, so every landmark tract is equally thin: that is true.
- **Over time:** what fades dims visibly; **nothing brightens with age**. Brightness depends only on the
  current confidence and score, never on how long ago something was written.

### 17.4 Landmark tracts

- **Means:** the routes between certainties (`mycelium_landmark_edges`), and between clusters of them.
- **Looks:** a tract between two certainties is a tapered particle strand (§17.3 thickness); between two
  clusters (task classes) the tracts run as one thicker bundle, thickness by mean score and number of links.
- **Over time:** a tract is still. It carries a faint pulse **only when its traversal count grew**: in `?real`
  the page remembers the last counts it saw in the browser (`localStorage`, key `iris.memory.edgeSeen`) and
  pulses the edges that rose since; the first visit pulses none. The demo flags a few as grown. Tissue that
  always carries signal (tracts to the skin, links to near neighbours) keeps its ordinary pulse.

### 17.5 Immune response (`mycelium_quorum_log`)

- **Means:** the durable memory of the Kyudo guard: each signal that counted toward the threat
  (`shadow = 0`), each signal that was only measured (`shadow = 1`), each reorganization reset
  (`quorum_reorganization_reset`).
- **Data:** the newest 80 rows (ts, session, signal type, weight, shadow, the landmark an activation anomaly
  names). The territory it touched is the landmark's, else the session's busiest territory; with neither, the
  whole lattice at half strength. The live table is empty today, so `?real` shows nothing. The page replays
  the log oldest first, one row every 6 to 10 seconds, and the ticker says when each truly happened.
- **Looks:** a live signal — a brief, low-amplitude tightening of the touched territory (its lattice is
  pulled about 1% toward its centre) with a small flicker (at most about +14% brightness). A shadow signal —
  only a faint mark on the skin that fades over about 25 seconds, with no motion. A reset — the territory
  relaxes outward and dims slightly, then settles.
- **Over time:** amplitudes only decay: a tightening lasts about a second, a relaxation a few. A signal sets
  the amplitude (it never adds), so a busy log cannot build up brightness.

### 17.6 Sectors — the territories

- **Means:** territories are the sector registry (§5.1): roots are large territories, children nested
  sub-territories (depth 1 drawn; deeper ones fold into their depth-1 ancestor; at most 12 roots and 12
  children).
- **Data:** `mycelium_sectors` (key, parent, label, status, members) and `mycelium_landmark_sectors`
  (landmark to sector, by weight). Both tables may not exist yet (another build is creating them): the
  exporter and the page treat that as "not there", and **the topic-domain territories stand in** (the 12
  registry values), as before.
- **Looks:** a child is a smaller cap of a lighter shade of its root's colour, set toward one side inside
  it; the lattice draws it as its own patch. The root's label lists its children (`↳ name count`, "still
  forming" for a candidate).
- **Over time:** a territory's size follows its members. A candidate sector that closes becomes proven and
  loses the "still forming" mark; a dissolved one disappears.

### 17.7 Spaces — the layers

- **Means:** the coordinate spaces of `mycelium_spaces` (conduct, domain, style, chrono, context,
  capability, toolpath today). Each is a layer of the mind with its own write lock (§12.3).
- **Data:** the registry rows (description, active, `write_lock`, `render_order`; the last two may be
  missing) and the nodes in each space.
- **Looks:** one very faint geodesic shell per space inside the orb, innermost = render order 0, a space with
  no render order (toolpath) outermost; its tint is its write lock. Nodes sit on their shell (small cells with
  the §17.2 membrane and the §17.3 fade); their tracts (`mycelium_edges`) run between them. Press `s`: the
  shells brighten and each names itself in plain words with who may write there ("only you and the system
  write here"). Hover a node: what space, where it came from, how sure IRIS is, and whether it is only on the
  floor it was given.
- **Over time:** static; a space added to the registry gets its own shell with no code change.

### 17.8 What to look at in a browser

Open `index.html` (demo) and `index.html?real` (after `export_snapshot.py`). Cortex: nested patches inside
territories; crystals set in the wall (fly inside); `s` for the layers; the ticker shows the guard's rows.
Timeline lens, click a session (in the demo, `__cortex.enter(12)` and `__cortex.enter(14)` open one with a pin bead and one with a checkpoint): fibre bundles, the pins as beads, the arch at the
end. Artifacts lens: pin tethers reach the tissue.
