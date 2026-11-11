# Requirements: CLM Memory (the live view the model can manage)

Status: REVISED 2026-11-11 (replaces the 2026-10-28 draft; code-verified this date).
Predecessor: `specs/memory-recall-reach` (COMPLETE 72/72, gate green 2026-11-01;
hand-off `docs/handoffs/2026-11-01-recall-spec-complete-clm-next.md`, MCM `pin_0fc690093220`).
Source design: `docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md`.
Sibling plan: `docs/architecture/KERNEL_DECOMPOSITION.md` (the kernel split; this spec
builds in the modules that plan creates - see Decisions Locked).
Owner: Midas. Audience: the implementing agent.

## STATUS UPDATE - what the 2026-10-28 draft had wrong (verified in code 2026-11-11)

| # | Draft claim | Verdict | Evidence |
|---|---|---|---|
| U1 | DCP is called at `agent_kernel.py:4269` and hard-codes the shrink policy on the answer path | WRONG | The kernel never constructs `DCP` (`agent_kernel.py:18970-18979`). Its only production callers are `swarm/context_control.py:83-90` (MCM:999) and `mcm_protocol/actions/dcp_prune.py:18-35`, both swarm/protocol paths. |
| U2 | `DCP._emit_fan_traces` is the only writer of `der_fan_traces`; migrate it first | ALREADY FIXED | `AgentKernel._der_emit_fan_trace` (`agent_kernel.py:18834`) writes one row per node at its terminal outcome, called at `:18980`. The DCP pass writes 0 rows in production (every caller passes no `traj`, `dcp.py:163-164`). |
| U3 | (not in the draft) what shrinks the window today | REAL GAP | Two blind cuts: `InferenceRouter._cap_messages_to_window` (`inference/router.py:429-495`) drops the OLDEST non-system messages on every model call and only logs a count; `_assemble_direct_context` (`agent_kernel.py:4131`) trims history by a chars/4 estimate. Neither records WHAT left, neither leaves an address. |
| U4 | "use the active backend's tokenizer" | REAL GAP, reframed | Three estimators, no authority: chars/4 (`agent_kernel.py:4126`), chars/3.5 + 16/message (`router.py:349-377`), tiktoken-or-chars/4 (`mcm.py:311-337`). The router path loads no tokenizer. The only true number is the server's `usage.prompt_tokens` (`inference/transport.py:436-481`). |
| U5 | every injected block can carry an id | REAL GAP | Recalled chunks are plain strings joined with `\n---\n` (`agent_kernel.py:4313-4314`); `retrieve_context_chunks` returns content strings by default (`episodic.py:1603`). |
| U6 | need new chain labels `VIEW_EDITED` / `VIEW_ASSEMBLED` | NOT NEEDED | `OFFLOADED`, `RESTRETCHED`, `PREMATURE_EVICTION` are already seeded (`memory/event_alphabet.py:169-171`) with NO emitter; the dashboard already names them (`surface_queries.py:1737-1738`). The alphabet is ready; the signal has no producer. |
| U7 | `mycelium_pins` has 0 rows; pick a pin surface | SETTLED | `PinStore` (`memory/pin_store.py:167`, table `mycelium_pins`) is the app surface with production writers (`tool_bridge.py:612`, `corrections.py:56`). 5 rows at 2026-11-01. Do not add a second surface. |
| U8 | (not in the draft) level 1 is ready to use | REAL GAP | `thread_context` (L1) has NO production reader; only `memory/levels.py` touches it. |
| U9 | "brief section 5.2" | WRONG REFERENCE | The backup finding is brief section 5 item 2 (line 139). |
| U10 | `dcp.py` derives its protection from the context window | SILENT FALLBACK | `dcp.py:51` imports `resolve_context_window` as a module function; it is a method (`agent_kernel.py:3054`). The `except` at `:53` always fires; `turn_protection` is always 6. Goes away with CLM-9. |

## Decisions Locked

- **Mycelium is the source of truth; CLM is fitted to it** (brief section 0). No store or
  path is migrated, flattened or replaced.
- **No file-based context.** The live view is a DERIVED view over the record, never a
  file on disk. Recovery is recall by reference, never grep.
- **Two halves of the rubber band.** Shrink/stretch is this spec. "Where everything was"
  is the record and is already built. This spec builds only the first.
- **The record is append-only and never model-editable.** An edit changes the view only.
- **No new dependency without the owner.** CPU only. One writer (`db.app_write`).
  Anything the current reply does not need runs on a lane.
- **Policy does not live in an instruction document** (brief section 0 rule 7). The
  model gets a short factual tool description; behavior comes from the harness, the
  record and measured outcomes.
- **The benchmark is part of done.** A wave closes with its number, measured live.
- **Prepared ground is not re-litigated**: two planes (recall REQ-10), the codec (REQ-4),
  the Kyudo decay law (REQ-5), the three levels (REQ-11).
- **DCP is removed, not adapted** (owner, 2026-10-28). Reframed by U1/U2: there is no
  emitter to migrate. Removal is CLM-9: delete `dcp.py` and its two callers' use once
  the view owns shrink on those paths.
- **The harness guarantees; the model chooses** (new, 2026-11-11). The brief's own
  evidence (section 5 items 2 and 4): backups do not happen unless enforced, and small
  models edit about 1.4 times per task. So the harness ALWAYS enforces the offload gate
  and applies a default shrink order under pressure; the model MAY edit earlier or
  differently through two tool operations. A model that never edits still gets a
  correct, reversible view.
- **CLM lands in the split kernel, not the monolith** (new, 2026-11-11). The view is its
  own module (`backend/agent/context_view.py`); the kernel holds only call sites, in
  the context domain that `KERNEL_DECOMPOSITION.md` extracts first. No CLM task adds
  logic to `agent_kernel.py`.
- **The view is the shared valve with the Aperture** (GOALS 7a: "one valve seen from two
  sides"). CLM decides what LEAVES; the Aperture (`specs/wormhole-aperture`, later) will
  decide what ENTERS through the same admit call. This spec defines the seam and builds
  only the leaving side.

## Introduction

Today the window is managed by two blind cuts. When a prompt is too large the router
drops the oldest messages and logs a number; the direct path trims history by a
character estimate. What left is not recorded, has no address, and cannot come back.
The model cannot see how full its window is, and the three places that estimate
tokens disagree.

This spec replaces the blind cut with a live view: every block in the window has a
reference into the record, a block leaves only through a gate that keeps its address
and its open items, and it returns exactly, by reference. The model can steer this;
the harness guarantees it.

### Success criteria

- Blind drops on the answer path = 0 (a router-cap drop of a block the view did not
  offload is an alarm, counted).
- Every offloaded block re-expands byte-for-byte from its reference, or says why not.
- Gauge error against the server-reported `prompt_tokens`: p95 <= 5 % after
  calibration, per (provider, model).
- ContextBench analogues (CLM-7.1) pass at context pressure >= 8x on the live app.
- Recall by time frame and by domain (CLM-7.2) is measured and has a stated bar.
- No answer-path standard regresses (`evals/standards.json`, PROGRESS "Standards").
- `backend/agent/dcp.py` is deleted and no test or caller references it.

## Requirement ID mapping

IDs CLM-1 to CLM-7 keep their 2026-10-28 meaning. New: CLM-0 (baseline), CLM-8
(observability), CLM-9 (DCP removal), CLM-10 (edit cost and layout).

## Requirements

### CLM-0: Measured baseline before any change
**User Story:** As the owner I want the current window behavior measured, so every
later number has a "before".

**Verified:** NEW. Baseline sources exist: the router cap warning
(`router.py:487-494`), `usage.prompt_tokens` (`transport.py:436-481`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL record, over a stated eval cohort (coding 8, research >= 10,
  memory 3), the count and total estimated tokens of messages dropped by
  `_cap_messages_to_window` and by the direct-path trim, per task.
- AC2: THE SYSTEM SHALL record the error of each of the three estimators against the
  server-reported `prompt_tokens`, per (provider, model), as a distribution.
- AC3: THE SYSTEM SHALL record the token-size distribution of each block kind that
  enters the window (tool result, recalled chunk, history turn, step digest, system
  prompt) - min, median, p95, max.
- AC4: THE SYSTEM SHALL answer design open questions Q1-Q4 (design.md "Open
  questions") from code, with file:line, before Wave 1 starts.

**Edge Cases:**
- A provider reports no usage: that (provider, model) is listed as "no ground truth",
  not averaged in.
- A cohort run hits the TTS wedge (hand-off open issue 1): the run is discarded, not
  mixed (PROGRESS: never mix results).

### CLM-1: The live view is a derived representation with addressable blocks
**User Story:** As IRIS I want to own the window I am thinking in, so I can keep what
matters for this task and set aside what does not.

**Verified:** NEW. Assembly sites today: `_assemble_direct_context`
(`agent_kernel.py:4131-4565`); the node message list (`_der_run_node`,
`agent_kernel.py:17948`); synthesis (`_synthesize_response`, `:21900`). Block ids:
absent (U5).

**Acceptance Criteria:**
- AC1: WHEN a model call is assembled on the answer path THEN THE SYSTEM SHALL build it
  from a view made of blocks, not from an anonymous message list.
- AC2: THE SYSTEM SHALL give every block a stable reference that resolves to a record
  row (chunk id, chain entry id, level row id, pin id) or mark it `ephemeral` with the
  reason (system prompt, current user turn).
- AC3: THE SYSTEM SHALL render a view to the provider message list with the SAME
  wire-format guarantees as today (`_sanitize_messages`, a tool result stays with its
  call, system first).
- AC4: WHEN the view changes by an edit (harness or model) THEN THE SYSTEM SHALL emit
  one memory event per edit batch (CLM-8), so history never depends on the view's
  current shape.
- AC5: THE SYSTEM SHALL never let a view edit delete or alter a record row.
- AC6: WHILE no edit has happened THE SYSTEM SHALL produce a message list equal to
  today's list for the same inputs (parity; the guard for the migration).

**Edge Cases:**
- Record lookup of a reference fails at assembly: the block is rendered and marked
  `ref_unresolved`; the turn is never blocked.
- Two blocks resolve to the same row (recall returned a chunk already in history): one
  block, the higher zone wins.
- The view object is per turn/run; no view state is shared across conversations.

### CLM-2: Offload leaves a placeholder; nothing is lost
**User Story:** As IRIS I want a set-aside block to leave its address behind, so I can
bring back exactly that block later.

**Verified:** NEW. Labels exist with no emitter (U6). Chunk rows keep content; file
chunks are re-ingestable while the hash matches (recall spec REQ-9).

**Acceptance Criteria:**
- AC1: WHEN a block leaves the view THEN THE SYSTEM SHALL leave one placeholder line
  that carries its reference, its time frame, its domain and a one-line reason it
  mattered.
- AC2: THE SYSTEM SHALL refuse to drop a block until (a) its content is in the record
  and readable by its reference, (b) the placeholder exists, and (c) its open items
  are carried forward (CLM-5 AC2). The harness enforces this; the model cannot bypass it.
- AC3: WHEN a placeholder is re-expanded THEN THE SYSTEM SHALL return the original
  block content by reference, byte-for-byte, not a summary.
- AC4: IF a placeholder cannot resolve THEN THE SYSTEM SHALL say so in the view and name
  the case: `pruned` (decay removed the row), `reingestable` (file chunk, hash
  matches), or `forgotten` (user forget). It SHALL NOT return an empty block.
- AC5: THE SYSTEM SHALL keep a placeholder's token cost bounded (design sets the bound
  from the CLM-0 AC3 distribution; a placeholder larger than the block it replaces is
  refused).
- AC6: IF the router cap would drop a message the view did not offload THEN THE SYSTEM
  SHALL count it as a `blind_drop` and log it with the conversation id.

**Edge Cases:**
- The record write is still queued on a lane: the drop waits for that write (fold-back:
  the consumer waits only where it decides), with a bound; on the bound the block
  STAYS in the view.
- A forgotten strand: re-expand returns `forgotten`, never the content (the forget
  guard `test_every_recall_path_leaves_a_forgotten_strand_out` must cover this path).
- A block below the break-even size is never offloaded (it would cost more than it saves).

### CLM-3: Model-written summaries are pins with provenance
**User Story:** As the owner I want a model summary to be a pointer plus a claim, so it
can never replace or outrank what it summarises.

**Verified:** `PinStore.add` (`memory/pin_store.py:198`), `PinStore.link` (`:327`,
`LINK_VOCABULARY` `:61`); landmark promotion needs outside evidence
(`event_alphabet.py:44` `OUTSIDE_EVIDENCE`).

**Acceptance Criteria:**
- AC1: WHEN the model summarises blocks THEN THE SYSTEM SHALL store a pin through
  `PinStore` with author = model, a timestamp, the claim text, and links to the
  references of the raw material.
- AC2: THE SYSTEM SHALL render a pin in the view as distinguishable from raw record,
  with its source count.
- AC3: WHEN a pin enters the view THEN THE SYSTEM SHALL frame it as reference data and
  SHALL NOT place it in the system or instruction block.
- AC4: THE SYSTEM SHALL keep model-written pins out of the landmark authority path: a
  pin is a candidate; only outside evidence promotes.
- AC5: WHEN asked THE SYSTEM SHALL return a pin's source set for audit (CLM-6 AC3).

**Edge Cases:**
- A pin whose every source is pruned is rendered `unsourced`; it stays a candidate.
- Pin text that reads as an instruction ("always...", "ignore...") is still only
  framed as reference data; no content filter is added (the frame is the control).

### CLM-4: The gauge is real
**User Story:** As IRIS I want to know how full my window is, because I cannot
estimate it myself (brief Appendix G finding).

**Verified:** window authority exists (`resolve_context_window_with_source`,
`agent_kernel.py:2932`); count authority does not (U4). Pill fullness uses
`_context_fill` (PROGRESS 2026-10-25).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL have ONE token-count function used by the view, the router cap
  and the pill.
- AC2: THE SYSTEM SHALL calibrate that function per (provider, model) from the
  server-reported `prompt_tokens` of real calls, and SHALL report the calibration
  error (CLM-8).
- AC3: THE SYSTEM SHALL show the model its current view size against the budget in tool
  results, as one short line.
- AC4: WHEN the view is within a set margin of the budget THEN THE SYSTEM SHALL add one
  reminder line (the paper uses 2,048 tokens; the margin is set from CLM-0 data).
- AC5: IF no usage has been observed for a (provider, model) THEN THE SYSTEM SHALL use
  the conservative estimator and mark the gauge `uncalibrated`.

**Edge Cases:**
- Images: the per-image constant stays (`router.py` 3,500) until measured.
- A model switch mid-conversation: calibration is keyed by model, never carried over.
- The gauge line itself is counted.

### CLM-5: Recent-to-past zones, open items carried forward
**User Story:** As IRIS I want recent work verbatim and old work as addresses, so the
window stays small without losing the thread.

**Verified:** dead ends exist as events and a bounded per-case list
(`memory_events.py:49`, `:597-607`); failed-like links (`ontology_recall.py:307`);
stale marking (`mycelium/landmark.py:233-252`). L1 has no reader (U8).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL hold recent blocks verbatim, middle blocks as a pin or ledger
  line with references, and past blocks as placeholders only.
- AC2: THE SYSTEM SHALL carry every open item of a leaving block forward into the view
  (unresolved errors, untried ideas, TODOs, dead ends) before the block leaves.
- AC3: THE SYSTEM SHALL keep a dead-end ledger in the view, bounded, built from the
  existing `DEAD_END` events - not a new store.
- AC4: WHEN the task's domain touches a landmark, OR an error matches a past event, OR
  the next action matches a ledger dead end THEN THE SYSTEM SHALL re-expand the
  matching placeholder (re-stretch).
- AC5: THE SYSTEM SHALL edit the view at subtask boundaries and at the gauge margin,
  not inside a node's tool loop (CLM-10).
- AC6: THE SYSTEM SHALL show a fixed-size header of landmarks relevant to the current
  target, and SHALL flag a stale landmark as stale when shown.
- AC7: WHERE a whole earlier thread is relevant THE SYSTEM SHALL represent it by its L1
  row (`thread_context`) as a placeholder, giving L1 its first production reader.

**Edge Cases:**
- No landmark matches: the header is empty, not padded.
- A re-stretch would exceed the budget: the harness offloads by the default order
  first; if still over, the re-stretch is refused and counted.
- The ledger is full: the oldest resolved entry leaves first; an unresolved one never
  leaves silently.

### CLM-6: Safety
**User Story:** As the owner I want an editable view that cannot become a channel for
persistent injected instructions.

**Verified:** NEW for the view. Record append-only is existing practice (`app_write`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL keep the record append-only and never model-editable.
- AC2: THE SYSTEM SHALL NOT let the model edit the system prompt, the tool
  descriptions, or the view's own interface text.
- AC3: WHEN asked THE SYSTEM SHALL audit a pin against its sources and return the
  source set and whether each still resolves.
- AC4: THE SYSTEM SHALL render every re-entering block (re-expanded content, pin,
  recalled chunk) inside a reference-data frame.

**Edge Cases:**
- A model edit names a block id that is `ephemeral` (system prompt): refused, counted.
- A model edit names an unknown id: refused with the list of valid ids, no exception.

### CLM-7: Measurement (the completion test)
**User Story:** As the owner I want the rubber band proven on the live app, graded on
what reaches the window.

**Verified:** NEW. Runner: `evals/run_evals.py`; standards: `evals/standards.json`.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL pass a ContextBench-style suite on the live app: exact recall
  of a value offloaded N turns ago; counting and lookup over offloaded logs;
  keep-specific-delete-filler; in-place update of a state block. Graded from the view,
  not from the store.
- AC2: THE SYSTEM SHALL measure recall by TIME FRAME and by DOMAIN ("what did we decide
  about auth last week?"), graded on the reference that reaches the view.
- AC3: THE SYSTEM SHALL report: premature eviction, re-recall cost, repeated dead-end
  actions, stale-landmark use, wrong-landmark rate, blind drops.
- AC4: THE SYSTEM SHALL measure edit cost on the serving backend (CLM-10 AC3).
- AC5: THE SYSTEM SHALL run every comparison under the same conditions (same commit
  pair, same model, same cohort) and name the cohort beside every number.

**Edge Cases:**
- A task passes because the value was still in the window (no pressure): the suite
  asserts the pressure ratio per task; a no-pressure pass does not count.

### CLM-8: Observability
**User Story:** As the tuner I want every view decision recorded, so thresholds come
from data.

**Verified:** labels seeded, no emitter (U6); `memory_events` schema
(`memory_events.py:78-101`); lane `memory_events` (S82).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL emit `OFFLOADED` and `RESTRETCHED` with the block reference,
  kind, tokens, actor (harness or model) and trigger, on the `memory_events` lane.
- AC2: WHEN a block is re-expanded within a set number of steps of its offload THEN
  THE SYSTEM SHALL emit `PREMATURE_EVICTION`.
- AC3: THE SYSTEM SHALL log per model call one structured line: conversation id, view
  tokens (gauge), budget, blocks by zone, placeholders, blind drops.
- AC4: THE SYSTEM SHALL expose the counters of CLM-7 AC3 to one report script.
- AC5: THE SYSTEM SHALL add only LABELS to the event alphabet, never a value.

**Edge Cases:**
- The lane is full: the event is counted as shed (existing lane behavior); the turn is
  never blocked.
- An eval session: events carry the eval marker so they are retired with the eval.

### CLM-9: DCP removal
**User Story:** As the owner I want the old pruner gone, so there is one shrink
mechanism.

**Verified:** callers at `swarm/context_control.py:83-90`,
`mcm_protocol/actions/dcp_prune.py:18-35`; tests `test_der_phase0.py:207-227` (two
copies), `tests/unit/test_write_paths_proven.py`.

**Acceptance Criteria:**
- AC1: WHEN the view owns shrink on the two caller paths THEN THE SYSTEM SHALL delete
  `backend/agent/dcp.py`.
- AC2: THE SYSTEM SHALL keep `der_fan_traces` receiving one row per executed node
  (unchanged writer `_der_emit_fan_trace`).
- AC3: THE SYSTEM SHALL have no import of `dcp` in `backend/`.

**Edge Cases:**
- The swarm path is flag-off: its caller is still migrated or removed, not left
  pointing at a deleted module.
- Tests that pin DCP behavior are removed WITH the module and each removal is stated
  in the commit (owner rule 2026-10-25).

### CLM-10: Edit cost and view layout
**User Story:** As the owner I want view edits to be cheap on the serving backend,
because a mid-context edit forces re-processing of everything after it.

**Verified:** NEW. Brief section 5 item 5: append 1.41e14, mid edit 5.74e14, start
edit 10.81e14 FLOPs on a 20k prompt.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL lay the view out as a stable prefix (system prompt, header),
  an append-mostly body, and a volatile tail, and SHALL keep the prefix byte-stable
  across calls of one run unless its content truly changed.
- AC2: THE SYSTEM SHALL batch edits into one rewrite per boundary.
- AC3: WHERE the provider reports cached prompt tokens THE SYSTEM SHALL record them per
  call, and SHALL report tokens re-processed after an edit against an append.
- AC4: THE SYSTEM SHALL NOT assume suffix-cache reuse.

**Edge Cases:**
- A local llama.cpp server: prefix reuse is measured from its timings, not assumed.
- A volatile value in the prefix (a clock, a counter) is a finding: it is moved to the
  tail or removed.

## Non-Requirements (Out of Scope)

- Reinforcement learning and prompt evolution (brief section 12: reference only).
- The SGLang suffix-cache patch.
- Multi-agent live views and the coordinator tracker (brief section 7.8) - a later
  spec, after CLM-7 is measured.
- The Aperture, Wormhole and NodeChains (`specs/wormhole-aperture`); only the admit
  seam is defined here.
- Any change to the two planes, the codec, the decay law, or recall scoring.
- `backend/agent/mcm.py` (the lite port of the dev tool: compress / recall on the swarm
  path). Not IRIS memory; untouched unless the owner decides Q-A below.
- An Oracle job for "will this block be needed". Candidate only; the Oracle earns jobs
  from measured rows (CLM-8 gives it the rows).

## Owner answers (2026-11-11) - locked

- **Q-A (swarm):** "you can remove dcp for the swarm, the clm will replace it for
  swarms. each swarm agent will be able to edit their own context." So CLM-9 removes
  DCP on the swarm paths too, with no stand-in pruner left behind. Each swarm agent
  gets ITS OWN live view (the multi-agent spec builds that; brief section 7.8). The
  view stays a derived view, not a file on disk (Decisions Locked). Until that spec
  lands, the swarm path is covered by the router cap + the blind_drop alarm.
  `backend/agent/mcm.py` `compress` is not DCP; it stays until the per-agent view
  replaces it.
- **Q-B (model surface):** extend `recall_memory` with `expand` and `set_aside`. No
  new tool.
- **Q-C (order):** offload on the DER node path first. Parity (Wave 1) covers both
  paths; the direct chat path gets offload after TG-2.
- **Order of the two programs:** the kernel split starts first (Stage A guards, then
  moves through M3 context = gate G-KERNEL).

## Open Questions (for the owner)

- None blocking.

## Inherited Ground (must not be rebuilt)

Counts as measured 2026-11-01 (hand-off section 3); re-measure in CLM-0 before citing:
`memory_chain` 13,382 | `context_chunks` 61,018 | `thread_context` 3,168 (19.3x smaller
scan) | `episodes` 232 with `vec_i8` | `mycelium_landmarks` 4,136 | `mycelium_pins` 5.
Also: the chunk codec (int8 + 128 B fingerprint), incidence by `thread_id`, lanes +
`app_write` as the one writer, the `recall_memory` tool, and the recall gate
(memory 3/3, BT-W10-2). The recall@10_live bars are quoted differently in two places
of the recall spec (0.86/0.9442/0.8667 in tasks.md:67); cite tasks.md.
