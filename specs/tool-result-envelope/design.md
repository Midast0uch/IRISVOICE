# Design: Tool-Result Envelope & Drift-Gated Coordination

## Context
Conv-99 exposed the same root pattern three ways: mechanism-without-consumer. Raw crawl payloads re-enter the loop through four surfaces (working memory append, planning prompt full-thread render, continuation OUTPUT block, user-facing fallback evidence), driving conversation context to 71.5k/64k chars. A prior proposal (render-time caps, "D1–D5") was rejected as surface-level: the user's locked principle is that the ENVELOPE — not the renderer — is the fix. Every tool result must arrive in the loop already shaped: bounded digest, durable raw pointer, and decision-useful wrapper labels in words. The envelope is reporter-only: it NEVER mints hashes, NEVER walks the graph, NEVER scores recall — it stamps joinable identity so `specs/wormhole-aperture/` lands later with zero rework. The Director/Reviewer/Executor structure already exists here (planner = `_plan_task`/`_der_plan_next_step`, reviewer = `Reviewer.review` gate, executor = step dispatch) — what is missing is the wrapper schema and where it plugs in.

Constraints that bound the design:
- One write-time computation; no per-consumer re-derivation; no extra LLM calls anywhere in the envelope or streak-gate path.
- Existing durable stores are REUSED, not duplicated: document store (raw payloads, `_capture_tool_result` agent_kernel.py:4791) and NodeRecord (coordinate/outcome record, der_loop.py:74).
- Reporter-only: no hash minting, no graph walk, no recall scoring, no per-step encodes — coords pass through verbatim; wormhole/aperture owns everything graph-shaped.
- Pre-existing failures untouched; the twins+loop-bounds suite (39 pass / 6 pre-existing `_FakeKernel._router` fails) is the regression baseline.

Session-318 amendment (conv-102 live evidence): the turn memory the envelope testifies against never reaches the two components that decide addresses. `_der_crawled_urls` fills at finalize (agent_kernel.py:13743-13751) but `CrawlPlanner.plan(query: str)` (crawl_planner.py:113) takes only a query, orchestrator dedup is run-scoped (orchestrator.py:~1410), and the guard reads `params["known_urls"|"url"]` (agent_kernel.py:12778-12799) which `crawler_query` never carries. Result: one wiki seed dispatched 3x (~110/90/82s), identical bodies counted fresh 3x, a 404 read 2x — with guard 0, streak 0, gather-filtered 0. The amendment below wires memory INTO choosing (exclusions), INTO prompts (ledger block), INTO identity (exact hash), INTO recovery (VLM in-site lane), and puts every errand on a deadline. Vision substrate exists (`_vision_fetch`, orchestrator.py:1722); progress events exist (`TASK_PROGRESS`, event_bus.py:106) — both reused, none invented.

## Architecture Overview

```mermaid
flowchart LR
    subgraph WRAP["Write time (once)"]
        TR[Tool result] --> CAP[_capture_tool_result: raw → document store, doc_id]
        TR --> ENV[ToolResultEnvelope build]
        CAP -->|doc_id only| ENV
        NR[NodeRecord finalize: outcome, expected_output, fraction, mediator, coords pair, turn memory] --> WRAP[wrapper derive: status/match/novelty/suggestion + criticality confirm — deterministic O(1)]
        WRAP --> ENV
        ENV --> QI[QueueItem.envelope]
        ENV --> WM[Working memory: envelope LINE only, failures included]
    end
    subgraph READ["Role views (read time)"]
        QI -->|status + wrapper + summary| RV[Reviewer gate]
        QI -->|summary + wrapper only| DIR[Continuation Director _der_plan_next_step]
        QI -->|raw_ref on demand| EX[Executor step]
        ENV --> FB[User-facing fallback summaries: envelope lines]
    end
    subgraph GATE["Streak gate (between steps)"]
        QI --> ACC[accumulate wrapper streaks]
        ACC -->|stuck streak / TOPO override| REPLAN[existing replan machinery]
        ACC -->|below threshold| CONT[continue current plan]
    end
    subgraph GUARD["Pre-dispatch guard (before paying for a tool call)"]
        MEM[turn memory + wall ledger] -->|repeat/walled → block + read via raw_ref| DISP[dispatch]
    end
    end
    WARM[main.py lifespan: background encode warmup] -.-> SVC[EmbeddingService singleton]
    TX[transport.py _nonstream: Empty → same-payload retry] -.-> TR
```

## Ledger / recovery / deadline flow (session-318 amendment)

```mermaid
sequenceDiagram
    participant PL as Planner (brain)
    participant LG as Turn ledger
    participant CH as Chooser (crawl planner)
    participant OR as Orchestrator
    participant VL as VLM recovery lane
    participant EN as Envelope testify
    PL->>LG: read VISITED block (<=20 URLs + pivot rule)
    PL->>CH: plan(query, excluded=VISITED)
    CH-->>PL: seeds (none excluded, by construction)
    OR->>LG: queue-time check on resolved seeds (turn scope)
    alt seed known
        OR-->>PL: refused → re-seed or pivot
    else all fresh
        OR->>OR: fetch under deadline + heartbeats
    end
    alt fetch dead (4xx/empty)
        OR->>VL: recovery step (unvisited in-site URLs only, page budget + deadline)
        VL-->>EN: own envelope (recovery_of=parent)
    end
    EN->>LG: stamp sources + body hash + elapsed (ledger grows)
```

The brain never blocks on VL: recovery is async work beside the plan; dependents wait bounded by its deadline while independent steps proceed (AC9.6).

## Sequence / Data Flow

```mermaid
sequenceDiagram
    participant DER as DER loop
    participant TB as Tool dispatch
    participant DS as Document store
    participant ENV as Envelope builder
    participant WM as Working memory (ContextManager)
    participant RV as Reviewer
    participant DG as Drift gate
    participant PL as Continuation Director
    DER->>TB: dispatch step tool
    TB->>DS: _capture_tool_result(raw) → doc_id
    TB-->>DER: raw result (DB-persisted)
    DER->>ENV: build_envelope(result, node_record, doc_id)
    ENV->>ENV: wrapper = derive(status, match, novelty, suggestion) + criticality confirm
    ENV-->>DER: ToolResultEnvelope (bounded)
    DER->>WM: append envelope LINE (status+summary+wrapper+raw_ref, failures included)
    DER->>RV: review(item, completed_steps) — envelope views only
    DER->>DG: evaluate(wrapper streaks)
    alt streak threshold crossed or TOPO_VIOLATION
        DG->>DER: trigger replan (existing boxed machinery, agent_kernel:9488)
    else below threshold
        DG-->>DER: continue current plan (no inference paid)
    end
    DER->>PL: plan_next_step(completed_items) — envelope summaries + wrapper only
    PL-->>DER: {"done": true} or next goal
    Note over DER: fallback summaries (user-facing) render envelope lines — never raw
```

## Data Models

```python
# backend/agent/tool_envelope.py (new, stdlib-only dataclass module)
@dataclass
class ToolResultEnvelope:
    status: str                 # "success" | "error" | "partial"
    summary: str                # ≤300 chars, ≤2 lines — the only text consumers get by default
    raw_ref: dict               # {"doc_id": str} — doc store ONLY (Pacman filing is async;
                                #  chunk ids are never available at wrap time and never waited on)
    match: str                  # "matched" | "mismatched" | "unclear" — vs the step's
                                #  expected_output under that TOOL FAMILY's bar (REQ-3 AC3.1)
    novelty: str                # "new" | "repeat_of_<step_id>" | "empty" — vs turn memory
    suggestion: str             # "proceed" | "retry_same" | "try_different" | "stop"
    stuck_shape: str            # "none" | "circling" | "dry_well" | "wrong_package"
                                # | "flat_tire" | "idling" (REQ-3 AC3.2)
    coords_from: str            # VERBATIM passthrough for future wormhole hashing — never
    coords_to: str              #  arithmetized here (empty + basis "none" when unavailable)
    criticality: str            # "load-bearing" | "supporting" | "cosmetic"
    criticality_source: str     # "declared" (planner) | "confirmed" (consumption, AC1.6)
    card_id: str = ""           # join keys for aperture/chains later (reporter stamps them,
    step_id: str = ""           #  graph layers read them — envelope never scores them)
    session_id: str = ""
    turn_id: str = ""
    error_type: str = ""        # populated when status != success (from tool_errors.py shape)
    recovery_hint: str = ""     # populated when status != success
    created_at: float = field(default_factory=time.time)

    def line(self) -> str:
        """The single bounded sentence that may enter working memory / prompts / cards.
        Words, not numbers: e.g. 'Step 2: success, mismatched (asked Parakeet, got
        whisper.cpp), repeat of Step 1 — try_different, read doc <id> instead.'"""

# QueueItem (der_loop.py:232 area) gains:
    envelope: Optional[ToolResultEnvelope] = None
# PlanStep / planner schema gains: criticality declaration per step (T5).
# NodeRecord unchanged — the envelope STAMPS from it, never replaces it.

# Streak + grade constants (der_constants.py — constants-only tuning per REQ-7):
STUCK_STREAK_N = 2           # consecutive repeat/empty/mismatch before the gate fires
IDLE_STREAK_N = 2            # consecutive success+new+matched with unmoved verified_fraction
LOAD_BEARING_VETO = True     # any load-bearing match!=matched caps the run below full pass
```

Envelope construction functions (pure, deterministic, unit-testable — NO I/O, NO encodes):
```python
def build_envelope(result_text, step_success, expected_output, tool_family, verified_fraction, node_record, raw_ref, coords_from, coords_to, turn_memory, error=None, declared_criticality="supporting") -> ToolResultEnvelope
def derive_wrapper(status, match_inputs, novelty_inputs) -> dict  # stuck shape + suggestion per hierarchy C
def confirm_criticality(declared, consuming_steps) -> tuple[str, str]  # option C
def evaluate_streak(wrappers: list[dict], stuck_n, idle_n) -> tuple[bool, str]  # TOPO rec forces fire
```

Amendment additions (session-318 — same file, still stdlib-only, still zero I/O):
```python
# Envelope gains (REQ-8/9/11):
    sources: List[str]          # URLs actually fetched, max SOURCES_MAX (8), truncation marked
    recovery_of: str = ""      # parent step_id when this envelope is a VLM recovery (AC9.5)
    elapsed_s: float = 0.0      # wall time vs the step deadline (AC11.3/AC12.2)
# Turn ledger (REQ-8): rendered prompt block, max LEDGER_PROMPT_MAX (20) URLs +
# pivot rule; refusal/exclusion logic always uses the FULL in-memory set.
# Identity (REQ-10): sha256(normalized extracted text); dead-address set per turn.
# Deadlines (REQ-11, der_constants.py — UNVERIFIED defaults, tuned from REQ-12):
DEADLINE_CRAWL_S = 240        # RESOLVED 2026-09-26: was 150 ("above conv-102
                              # observed 82-110s max"); two live crawls died at
                              # 157-159s, so 240 covers the realistic wall
DEADLINE_READ_S = 60
DEADLINE_DEFAULT_S = 90
STALL_WARN_S = 30             # heartbeat stall → warning only, never abort
RECOVERY_PAGE_BUDGET = 5      # max pages per recovery step (UNVERIFIED)
RECOVERY_DEPTH = 2            # max in-site depth per recovery step (UNVERIFIED)
LEDGER_PROMPT_MAX = 20
SOURCES_MAX = 8
```

## Key Decisions

**KD-1: Envelope at write time, not caps at render time.**
Default (rejected): cap every render site (my prior D1–D5). Why rejected (user-locked): render-time shaping leaves the raw blob as the source of truth in the loop, caps each of 4+ sites independently, and every future consumer re-invents the bound. Write-time envelope = one computation, four consumers, bounded by construction. Alternatives considered: (a) DCP text-zone pruner on ContextManager — rejected: treats symptoms in the store, still ships raw to it, DCP's dict-shape passes no-op on text zones; (b) keep raw inline + trust provider windows — rejected: 71.5k/64k live evidence, provider-empty disease correlates with bloated prompts (conv-98/99).

**KD-2: raw_ref rides the EXISTING document store id; no second store.**
`_capture_tool_result` already persists raw and returns doc_id (agent_kernel.py:4791-4840). The envelope references it. Alternative rejected: a new "raw payload table" — duplicates a durable store that already exists with trust-routing and HAR provenance.

**KD-3: The wrapper speaks in words — the 4D physics delta is REJECTED.**
Default (rejected, user-locked session-316): component-wise 4D phase-space delta with vector-norm magnitude. Why rejected: magnitude is in Duffing wobble-space, not goal-progress units, and an LLM decider cannot feel 0.83 — a precise-looking number that steers nothing is worse than a coarse label that steers correctly. The coords stamped at finalize are still carried VERBATIM (future wormhole hashing needs them), but nothing here subtracts them. Inputs to the words: outcome + `expected_output` under the tool-family bar + `verified_fraction` transition (already continuous 0..1, der_loop.py:114) + turn memory (crawled URLs, tool+params, output overlap) + optional Caducean recommendation (der_loop.py:528-536 — TOPO_VIOLATION forces `suggestion`=stop per AC3.4). Alternatives rejected: (a) LLM-judged wrapper — violates zero-token-cost and determinism; (b) new embedding-space distance — adds the model dependency the user excluded AND duplicates Pacman's stored vectors; (c) 4D arithmetic delta — the rejected default above. Trade-off surfaced: words are coarser than geometry — accepted deliberately, because the graph layers (wormhole/aperture) own precision later and the reporter owns clarity now; tuning rides REQ-7 counters (UNVERIFIED until live).

**KD-7: The fingerprint is CUT entirely — zero encodes, zero vectors, zero counters.**
Session-316 lock (user: "I don't think we need the fingerprint at all"). Pacman ALREADY persists every DER step result as embedded chunks in `context_chunks` (fragment_and_store at agent_kernel.py:13261-13316, async serialized worker) — any per-step encode would pay ~100ms for information the store already holds durably. Timing fact that kills the middle options: Pacman's worker queue is async (pacman_fragment.py:173-208), so chunk vectors are NOT ready at wrap time and `raw_ref` is doc-id-only (AC1.3). Semantic ranking of past findings (ex-OQ-3) is CUT from this spec and lives in `specs/wormhole-aperture/` Tier-1/Tier-2 where scoring belongs. Alternatives rejected: (a) in-memory fingerprint per envelope — rent with no tenant (no consumer until a deferred experiment); (b) persist via context_chunks — double-storage, user-rejected twice; (c) pool Pacman embeddings at wrap — couples the hot path to queue lag.

**KD-4: Replan gate reuses existing machinery; Caducean recs override streaks.**
The streak gate is a THIN predicate in front of the existing replan entry (`_replan`, agent_kernel.py:9488, already budget-boxed). Where a phase recommendation exists (TOPO_VIOLATION = rec 3 already "stops the line", der_loop.py:536), it forces the gate regardless of streak arithmetic. Anything graph-scoring shaped (hyperedge posteriors, aperture policy arms) belongs to wormhole/aperture, never here. Alternatives rejected: (a) replan every iteration — user-locked against, noisy + expensive; (b) timer-based replan — user-locked against; (c) new physics detector — violates reuse-the-existing-detection principle.

**KD-8: Hierarchy C — two hard rules, everything else suggests (locked session-316).**
WALLED + CIRCLING block deterministically: the pre-dispatch guard (T6B) refuses to re-execute a repeat (reroutes to read the original `doc_id`) and refuses walled retries — no LLM override, because re-paying a known-dead call is harm, not judgment. All other shapes SUGGEST; the Director may override with a logged reason, and override-rate is itself a counter (a suggestion overridden 90% of the time is a miscalibrated suggestion). Alternative rejected: all-hard (brittle — a mislabeled mismatch would deadlock the run) and all-soft (the conv-99 repeat would recur with better handwriting).

**KD-9: Expectation is per-family, weight is declared-then-proven (option C, locked session-316).**
One bar cannot judge a crawl and a file read: each tool family carries its own "good looks like this" inside `match` (REQ-3 AC3.1), so the grade generalizes beyond websearch to every tool call. Criticality is planner-DECLARED (intent) and consumption-CONFIRMED at finalize (proof — later steps reading my `doc_id` promote me to load-bearing); the divergence itself is logged as a tuning signal. Cost: one short field in the existing planning call + O(1) counter lookups at finalize — microseconds in, minutes back (every prevented 50s re-crawl). Alternatives rejected: (a) planner-only — intent without proof drifts; (b) derived-only — the planner never states what mattered, so nothing is auditable against; (c) LLM judge per step — a second inference bill on every step to grade the first.

**KD-10: Prevention decides, envelope testifies; aperture receives.**
The bouncer (pre-dispatch guard over turn memory + wall ledger, T6B) and the incident report (envelope line, T7) are deliberately split: the guard must work even for steps whose envelope never gets built, and the label must exist even when the guard somehow missed. The aperture contract is one-directional — envelope stamps identity, graph layers read it. If a future aperture needs a field the envelope lacks, THAT is a wormhole-side amendment with its own triplet, never a silent envelope widening.

**KD-5: Warm-at-boot is a fire-and-forget background task, not a startup barrier.**
Lifespan currently does heavy init inline (main.py:169-249). Embedding warm must NOT delay readiness (sidecar cold-load can take seconds). Alternative rejected: synchronous warm before `app.state.ready = True` — couples backend readiness to a GPU/CPU model load; rejected on latency layer. Timing note: warm lands async; if first real traffic arrives before warm completes, that first encode may still pay budget once — acceptable, and the breaker remains the safety net (existing behavior).

**KD-6: Transport Empty-retry lives INSIDE `_nonstream`'s existing attempt loop.**
The loop (transport.py:773-824) already retries 3× for HTTP exceptions and 429s; the Empty check (:839) simply sits after it. Moving the extraction+empty check into the loop = one retry site covers all four downstream Empty call sites (step-result processing, final synthesis, decision box, sub-loop). Alternative rejected: retry at each downstream call site — four patches instead of one, and downstream lacks the payload to retry with.

**KD-11: The ledger is a prompt block + envelope field — never a wm-line suffix, never a new store.**
Default: append visited URLs to every working-memory line. Why rejected: line bloat multiplies by step count and duplicates the ledger in every line. Alternative rejected: a fourth store table for visits — duplicates `_der_crawled_urls` which already exists and is already correct. Chosen: `envelope.sources` carries the data (for guard/novelty/ledger), a bounded VISITED block carries the view (for the decider). One write path, one read path, zero new stores — the same pointer-layer philosophy as KD-2. Cost layers: context (bounded ≤20 lines, evicted oldest-first), complexity (one render site), latency (O(ledger) string join off the hot path).

**KD-12: Exclusions are HARD at the chooser — the miss must be impossible, not discouraged.**
Default: pass visited URLs as a soft hint the crawl-planner LLM "should consider". Why rejected: an LLM hint is advice the planner pays for and may ignore — conv-102 proves untrusted planners re-pick. Alternative rejected: post-hoc filtering only (fetch, then discard known pages) — pays discovery + dispatch + render before refusing. Chosen: exclusions enforced where seeds become known — planner output and crawler-resolved seeds filtered against the turn visited set at queue time (reusing `_der_crawled_urls`: the gather-gate shape agent_kernel.py:12573-12591 plus guard branch-2 :12778-12799), plus turn-scope dedup — HARD like CIRCLING (KD-8): the same address cannot be re-fetched in-turn, period — EXCEPT the recovery lane (KD-14), whose targets are unvisited by construction. (Correction, session-318: the owner correctly noted per-URL exclusion mostly exists — gather gate for registry URLs, guard branch-2, run-scoped orchestrator dedup ~:1410/:2017. All three guard other roads; conv-102 traveled fresh-discovery, which none of them see. This KD wires that road into the same rulebook; whether `plan()` also takes an exclusions parameter is implementer's choice.) Necessity check: without hardness on the discovery road, every other instrument stays advisory and the 3x110s repeat recurs with better handwriting.

**KD-13: Identity is exact hashing — the fingerprint CUT stands untouched.**
Default: similarity scoring of page bodies. Why rejected: needs vectors/encodes — precisely what session-316 cut, twice. Alternative rejected: URL-only identity — misses identical bodies under different addresses (the conv-102 README-under-redirect case). Chosen: stdlib hash of normalized text, exact-match only. Known limit, accepted deliberately: near-identical bodies with changed chrome count as new — catching paraphrases belongs to wormhole scoring, not to a turn-local bouncer. Zero model cost, zero timing risk (pure function on text already in scope).

**KD-14: The never-recrawl ban is per-address; the VLM recovery lane explores unvisited rooms (user-locked caveat, session-318).**
Default: ban the whole site after one dead fetch. Why rejected: a 404 on one path says nothing about its siblings — banning the domain burns the recovery the user explicitly wants (404 → sibling pages). Alternative rejected: allow recovery to re-fetch anything (ban becomes advisory the moment it matters). Chosen: the ban keys on addresses; recovery is a first-class step type constrained to unvisited in-site URLs with its own page+depth budget, deadline, and envelope (`recovery_of`). It cannot re-fetch — not even the address that triggered it — and an empty-handed return is an honest dry-well that streak-counts. The brain never blocks on it (AC9.6): recovery is a lane of websearch, not a pause button.

**KD-15: Deadlines kill honestly; heartbeats only whisper.**
Default: silent kill + auto-retry on expiry. Why rejected: hides hangs and invites retry storms that look like progress. Alternative rejected: progress-monitoring with no deadline (the user's exact fear — watched forever, stopped never). Chosen: the deadline is the single abort authority; expiry mints a `timeout` envelope (status honest, partial results preserved via `raw_ref`, streak-counted like an empty). Heartbeats (`TASK_PROGRESS`, event_bus.py:106 — reused, CT-5 lock holds, no new event types) produce stall warnings only. Operational cost: one timer per dispatch; measurement: REQ-12 counters tune every duration from the first re-probe.

## Ripple-Effect Map (MANDATORY)

| Area / File | Change? | Classification | Why / Evidence (file:line) |
|---|---|---|---|
| `backend/agent/tool_envelope.py` | Yes — NEW | CHANGE NEEDED | Envelope dataclass + builder + wrapper derive + stuck-shape classify + criticality confirm + streak evaluate (pure functions, zero I/O, zero encodes, zero LLM) |
| `backend/agent/der_loop.py` | Yes | CHANGE NEEDED | QueueItem gains `envelope` field (der_loop.py:232 area); NodeRecord untouched |
| `backend/agent/agent_kernel.py` — planner step schema | Yes | CHANGE NEEDED | PlanStep/`_plan_task` declares `criticality` (load-bearing\|supporting\|cosmetic) per step at plan time — one short field inside the existing planning call, no extra inference (T5; KD-9) |
| `backend/agent/agent_kernel.py` — pre-dispatch guard | Yes | CHANGE NEEDED | NEW hard-rule block before dispatch (T6B): repeat (tool+params+URLs ⊆ turn memory) → reroute to read original `doc_id`; walled (via existing `is_walled`) → refuse retry. Reads turn memory + wall ledger only; CT-10 |
| `backend/agent/agent_kernel.py` — tool result site | Yes | CHANGE NEEDED | Build envelope once at the finalize site alongside node-record stamping (:14054-14100 — outcome/expected_output/fraction/mediator/coords all in scope there); raw_ref = doc_id from `_capture_tool_result` (:4791) ONLY (Pacman chunk ids async-unavailable, never waited on); criticality confirmed from `raw_ref` consumption (AC1.6) |
| `backend/agent/agent_kernel.py` — working memory append | Yes | CHANGE NEEDED | :13382-13396 append envelope LINE (status+summary+wrapper+raw_ref) for EVERY settled step INCLUDING failures (fixes the :13387 silent-skip that guarantees repeats) instead of `_smart_excerpt(step_result, cap)` |
| `backend/agent/agent_kernel.py` — `_der_plan_next_step` | Yes | CHANGE NEEDED | :14557-14572 OUTPUT block renders envelope summaries + wrapper labels with BOTH halves bounded (the full-`i.result` done_summary half capped to envelope lines like the outputs block); reports `done + grade` per AC5.6, never bare `done` (Director view) |
| `backend/agent/agent_kernel.py` — deterministic fallback summaries | Yes | CHANGE NEEDED | :11626-11692 render envelope lines (fix 7; kill the 8000-char gather window in user-facing output, :11463-11468) |
| `backend/agent/agent_kernel.py` — `_der_node_record_evidence` | No | NO CHANGE (deferred OQ-2) | :11463-11468 keeps its 8000-char gather window for the SYNTHESIS prompt only; user-facing/loop surfaces are envelope lines. Verified present; change deferred to live evidence |
| `backend/agent/agent_kernel.py` — reviewer gate | Yes | CHANGE NEEDED | :8319-8326 pass envelope views (status+wrapper+summary) into review inputs; ReviewVerdict semantics LOCKED (AC4.4) |
| `backend/agent/agent_kernel.py` — streak gate | Yes | CHANGE NEEDED | New gate call between steps, in front of existing `_replan` (:9488); TOPO_VIOLATION forces fire per AC3.4; hard rules live pre-dispatch (T6B), this gate is streak-only |
| `backend/agent/agent_kernel.py` — `_build_planning_prompt` | No | NO CHANGE (verified) | :5239-5249 renders ConversationMemory messages; those messages will now CONTAIN envelope lines (via working-memory append change) — planning code itself needs no edit. Contract test CT-2 pins no-raw-in-history |
| `backend/agent/agent_kernel.py` — `_run_step_direct` | No | NO CHANGE (verified) | :11943 wm cap 6000 already applied; wm content becomes envelope lines via the append change; P3 shrunk-retry (:11996-12010) untouched |
| `backend/agent/der_constants.py` | Yes | CHANGE NEEDED | Streak + grade constants (see Data Models: STUCK_STREAK_N, IDLE_STREAK_N, LOAD_BEARING_VETO) — constants-only tuning per REQ-7 |
| `backend/agent/inference/transport.py` | Yes | CHANGE NEEDED | `_nonstream` :773-843: move extraction+empty check inside attempt loop (fix 6b) |
| `backend/main.py` | Yes | CHANGE NEEDED | lifespan :169+: background embed warm task (fix 6a) |
| `backend/crawler/rerank.py` | No | NO CHANGE (verified) | Breaker logic :160-182 unchanged — warm-at-boot prevents the cold-budget burn upstream; breaker stays as safety net |
| `backend/memory/embedding.py` | No | NO CHANGE (verified) | `get_embedding_service()` singleton :957 + lazy load :791-793 already support warm-up; the envelope performs NO encodes (fingerprint cut) — warm-at-boot is the only consumer |
| `backend/memory/working.py` (ContextManager) | No | NO CHANGE (verified) | append() :99-139 zone mechanics unchanged — the CONTENT appended becomes envelope lines incl. failures (caller-side change only) |
| `backend/memory/episodic.py` (Pacman store) | No | NO CHANGE (verified) | fragment_and_store :750-879 + retrieve_context_chunks :881+ unchanged — Pacman keeps filing exactly as today; the envelope references doc ids only, reads NO chunk ids, waits on NO queue (`pacman_fragment.py:173-208` async worker — envelope never blocks on it). ex-OQ-3 (semantic selection) CUT to wormhole-aperture |
| `backend/agent/dcp.py` | No | NO CHANGE (verified) | Envelope supersedes (KD-1); existing call sites untouched per Non-Requirements |
| `backend/agent/tool_errors.py` | No | CONTRACT LOCK | Structured error shape feeds `error_type`/`recovery_hint` — shape must not drift; CT-4 |
| Frontend (hooks/useIRISWebSocket.ts, useTaskProgress.ts, cards) | No | NO CHANGE (verified) | Envelope is backend-internal; result_summary/resultPreview hydration (session-312) already renders bounded summaries; no event-shape change |
| `IRISStreamEvent` shapes (event_bus.py) | No | CONTRACT LOCK | No new/changed event types; envelope observability rides existing log stream, not new events |
| Task cards + der_execution_ledger (application memory) | No | NO CHANGE (verified) | Cards hold structured step state (UI + recall), ledger holds execution records — envelope adds no fourth store; it is the pointer layer connecting doc store + chunks + cards. CT-6 guards the gather gate they depend on |
| Twins + loop-bounds suite (backend/tests) | Yes | CHANGE NEEDED | Existing suites must stay green (39/6 baseline); envelope units added to existing contract/behavioral layout per Testing Strategy — NO new root-level twin files |
| Gather gate + URL turn memory (session-312) | No | CONTRACT LOCK | :12151 gate + `_der_crawled_urls` must survive refactor untouched; CT-6 |
| `backend/agent/tool_envelope.py` — sources/hash/timeout | Yes | CHANGE NEEDED | `sources` field + `recovery_of` + `elapsed_s` (REQ-8/9/11); exact body-hash helper + dead-address check (REQ-10); `timeout` status path (REQ-11); still pure, still zero I/O/encodes (KD-13) |
| `backend/agent/agent_kernel.py` — finalize stamp | Yes | CHANGE NEEDED | Stamp `sources`/hash/elapsed at the finalize site (:14054-14100 area); update `_der_crawled_urls` with RESOLVED seeds incl. crawler-resolved (AC9.3); dead-address set update (AC10.2) |
| `backend/agent/agent_kernel.py` — prompt ledger | Yes | CHANGE NEEDED | Render bounded VISITED block + pivot rule in planning + continuation prompts (AC8.2); pointers only (AC8.3); omit-when-empty + truncate-with-marker edges |
| `backend/agent/agent_kernel.py` — guard resolved-seed | Yes | CHANGE NEEDED | Guard URL check judges resolved seeds incl. crawler-resolved (AC9.3); refusal path unchanged (reroute to read); CT-13 |
| `backend/agent/agent_kernel.py` — dispatch deadline | Yes | CHANGE NEEDED | Attach per-family deadline + heartbeat watch at dispatch; expiry → `timeout` envelope (AC11.3); streak-count timeouts (AC11.4); bound every wait (AC11.5) |
| `backend/agent/agent_kernel.py` — run-grade log | Yes | CHANGE NEEDED | Defect fix: `run grade` logged ZERO times on the conv-102 live path — trace and repair the AC5.6 reporting path (completes existing AC, not new scope) |
| `backend/agent/agent_kernel.py` — recovery join | Yes | CHANGE NEEDED | VLM recovery as async step type: own budget/deadline, dependents bounded-wait, independents proceed, envelope joins ledger on return (AC9.5/9.6) |
| `backend/crawler/crawl_planner.py` — exclusions | Yes | CHANGE NEEDED | Planner-returned seeds filtered against visited set (inside `plan()` or at queue time — behavior locked by CT-12); empty-after-exclusion → no-seeds + pivot (edge) |
| `backend/crawler/orchestrator.py` — turn dedup + outlinks + recovery | Yes | CHANGE NEEDED | Dedup widened run→turn scope at queue time (AC9.2); extraction returns bounded outlink set with crawled marking (AC9.4); recovery drives `_vision_fetch` (orchestrator.py:1722, reuse — no new fetch path) within page/depth budget (AC9.5) |
| `backend/agent/der_constants.py` — budgets | Yes | CHANGE NEEDED | Deadline/stall/ledger/recovery constants (UNVERIFIED defaults — REQ-12 tunes them); constants-only tuning preserved |
| `backend/agent/event_bus.py` | No | NO CHANGE (verified) | `TASK_PROGRESS` exists (event_bus.py:106); heartbeats reuse it — CT-5 (no new event types) already locks this interface |
| `backend/crawler/crawl_runner.py` | No | NO CHANGE (verified) | Worker-level ceiling (`wait_for` at crawl_runner.py:555-556, `_DEFAULT_TIMEOUT_S` :55) stays as defense-in-depth under the new DER-layer deadlines; T18 does not alter it |
| Frontend (progress display) | No | CONTRACT LOCK | Recovery/deadline ride existing `task:progress` + `tool:result` shapes (CT-5); no new UI contract — new envelope fields are backend-internal |

### Wave 6 ripple map — recovery-lane convergence (session-319)

**Rule this section obeys** (FAULTLINE.md §11/§12): *a taxonomy — or any signal — without a
CONSUMER is decoration.* Removing the bespoke T16 lane is therefore NOT "delete a method":
every signal it produces must either move to the router path or be explicitly retired.

**CORRECTED ROWS (the session-316 "No frontend changes" Non-Requirement was LIFTED in session-319, so two rows above are now stale):**
| Area / File | Change? | Classification | Why / Evidence |
|---|---|---|---|
| Frontend (hooks/useIRISWebSocket.ts, useTaskProgress.ts, cards) | **Yes** | **CHANGE NEEDED (was NO CHANGE)** | REQ-13: stream the final answer progressively (AC13.1/13.2) + prism-card legibility (AC13.3/13.4). The envelope stays backend-internal; what changes is how the answer is PRESENTED. |
| Frontend (progress display) | No | CONTRACT LOCK (unchanged) | Recovery/deadline still ride existing `task:progress` + `tool:result` shapes — the streaming change adds progressive content to the existing answer channel, not a new event type. |

**NEW ROWS:**
| Area / File | Change? | Classification | Why / Evidence (file:line) |
|---|---|---|---|
| `agent_kernel.py` — `_der_maybe_open_recovery` (:5390) | **Yes — REMOVED** | **CHANGE NEEDED** | The bespoke lane bypasses the DAG router and duplicates it. Dead addresses instead emit a typed `Reason` and route through `NodeRouter`. Net code DELETION. |
| `agent_kernel.py` — call site :15478 | **Yes — REMOVED** | **CHANGE NEEDED** | The trigger currently lives inside `_der_finalize_step`, i.e. the success-only path, so a FAILED step is never even considered. Routing moves to the failure/step boundary where `_der_route_step_failure` (:10774) already runs. |
| `agent_kernel.py` — `_der_warm_vision_browser` (:5542) + dispatch hook (:13576) | Yes — DONE | CHANGE NEEDED | Session-319: warm Chromium at web-tool dispatch so the measured ~33s cold start overlaps the crawl. Fire-and-forget via `_broadcast_loop`. |
| `agent_kernel.py` — `_remember_turn_urls` (module level) | Yes — DONE | CHANGE NEEDED | Session-319: turn URL memory harvested on BOTH the finalize and failure paths (was finalize-only, so a failed crawl taught memory nothing). Module-level so the behavioral suite's `_Kernel` double keeps working. |
| `nodes/capabilities.py` — `fetch.vision` advertisement (:673) | Yes | CHANGE NEEDED | Must advertise the dead-address reason to be routable. NOTE the deliberate CHALLENGE exclusion (measured 0/3, 240s+188s+243s) — do NOT re-add CHALLENGE. |
| `agent/tool_errors.py` | Yes | CHANGE NEEDED | Register the dead-address failure label via `register_error_label(...)` — a DATA edit per FAULTLINE Layer 2, never a loop rewrite. |
| `agent/tool_envelope.py` — `derive_match` | Yes | CHANGE NEEDED | Becomes registry-driven (FAULTLINE's three layers: dimensions + data registry + unclassified bucket) instead of hardcoded per-family branches. New tool = data edit, no envelope change. |
| `agent/tool_envelope.py` — `recovery_of` on the ENVELOPE (:186, written :446/:538, stamped :10047) | **Retire or wire** | **DECORATION (already violating the rule)** | **No reader exists.** All `recovery_of` reads are on the QUEUE ITEM (`getattr(item, "recovery_of")` at :5408/:10108/:13476) — nothing reads `envelope.recovery_of`. Either name a consumer or drop the field. |
| `agent/tool_envelope.py` — expectation Layer 3 | Yes — NEW | CHANGE NEEDED | Unclassified bucket + counter for tools with no registered expectation, so a new tool is never silently judged matched. Mirrors `unknown_label_counts()` / `promote_unknown()`. |
| `agent/tts.py` — `_ensure_worker` (:446) | Yes — DONE | CHANGE NEEDED | Session-319: adopt a worker that became ready AFTER its startup deadline (was: respawn, discarding the late "ready" line, spawning another ~238s cold worker). |
| `agent/inference/transport.py` + `router.py` | Yes — DONE | CHANGE NEEDED | Session-319 AC11.6: `timeout_s` threaded through router → all five transports → `_nonstream`/`_stream`. Transports do NOT accept `**kwargs` — the router-side change alone would have raised `TypeError` on every call. |

**CONSUMER AUDIT — what happens to each T16 signal on removal:**

| Signal | Written at | Reader today | Disposition on removal |
|---|---|---|---|
| `_der_recovery_opened` (one recovery per host per turn) | :5485 | :5454 (the guard itself) | **LOAD-BEARING — must be re-homed** on the router path or the per-host budget is lost and one host can be recovered repeatedly. |
| `QueueItem.recovery_of` (parent link) | :5511 | :5408 (no-chains), :10108 (counter gate), :13476 (enrichment gate) | **LOAD-BEARING — re-home** as the node's parent reference. |
| `QueueItem.recovery_seeds` (pre-resolved unvisited seeds) | :5512 | :13477 — **only if the resolver picked `crawler_query`** | **FRAGILE — fix, do not port as-is.** Otherwise the seeds are silently discarded and only a log line remains; that is a signal with no consumer. |
| `envelope.recovery_of` | :10047 | **NONE** | **RETIRE (or wire).** Currently pure decoration. |
| `envelope.recovery_opens` | :15485 | none in code — read only by the T13 counter review | **INSTRUMENTATION — name T13 explicitly as the consumer** or it is decoration by the same rule. |
| `envelope.recovery_recovered` / `recovery_empty` | :10111 / :10113 | none in code — T13 only | Same as above. |

**Verdict:** two load-bearing signals (`_der_recovery_opened`, `QueueItem.recovery_of`), one
fragile signal that must be repaired rather than ported (`recovery_seeds`), one field that is
already decoration (`envelope.recovery_of`), and three counters whose only consumer is the T13
review. **The removal is therefore a re-homing exercise, not a deletion** — which is exactly
what the failure-is-a-signal requirement demands.

## Error Handling
- Envelope build failure → minimal envelope (AC1.4), loud_error logged, loop proceeds (never crash a step for shaping).
- Streak-gate failure → treated as "below threshold" (continue plan) + warning log — a broken gate must not change loop semantics (same advisory-gate principle as `_der_findings_sufficient`, agent_kernel.py:11398-11400).
- Suggestion override → logged with reason (AC3.3); hard-rule block (repeat/walled) → logged + rerouted, never overridable in-run.
- raw_ref resolution failure → "[source unavailable]" bounded marker (AC2.5 edge).
- Embed warm failure → log + continue (AC6.2); breaker path unchanged.
- Transport retry exhaustion → existing error, existing downstream handling (AC6.3/6.4).
- Deadline expiry → `timeout` envelope (AC11.3) with elapsed-vs-deadline cause; partial results preserved via `raw_ref` when available; streak-counted (AC11.4). Completion at the boundary wins — timeout never retro-fires.
- Recovery budget exhaustion → honest dry-well return, parent suggestion becomes try_different; same-address re-fetch stays blocked inside recovery (AC9.5 edge).
- Heartbeat stall → warning log only; abort authority is the deadline alone (AC11.2 edge).
- Ledger render failure → prompts assemble without the VISITED block + warning log (degrade, never block the loop).

## Testing Strategy
Organized per the standing CDD standard:
```
tests/unit/         build_envelope (wrapper labels per tool family; stuck-shape classification
                    incl. all 5 shapes; criticality confirm incl. declared-vs-consumed divergence;
                    minimal-degrade per AC1.4),
                    evaluate_streak (repeat/empty/mismatch streaks, idling streak, nominal
                    run blocks; TOPO_VIOLATION-rec override fires regardless — AC3.4;
                    hard-rule predicate: repeat/walled ALWAYS blocks — AC3.3).
                    Zero I/O, zero encodes, zero LLM — the gate's O(n) arithmetic pinned here.
tests/contract/     CT-1 envelope shape on QueueItem (fields + bounds: summary ≤300, ≤2 lines,
                    NO fingerprint field anywhere, raw_ref = {doc_id} only, coords verbatim,
                    criticality + source present, step identity present)
                    CT-2 no-raw-in-prompt: planning + step + continuation prompts contain no raw
                    gather payload text (assembles real prompts from recorded conv-99-shaped
                    fixtures and asserts absence — BOTH continuation halves, incl. the
                    full-`i.result` done_summary half)
                    CT-3 ReviewVerdict semantics unchanged (reviewer input change, output contract
                    locked — PASS/REFINE/VETO mapping identical on fixed fixtures)
                    CT-4 tool_errors.py shape → error_type/recovery_hint mapping locked
                    CT-5 no new IRISStreamEvent types; envelope observability rides logs only
                    CT-6 gather gate + _der_crawled_urls behavior unchanged post-refactor
                    (prevention guard EXTENDS the gate path — it never weakens the filter)
                    CT-7 transport: empty-then-content retries same payload; exhaustion raises
                    "Empty response from API"; RateLimitedError path untouched
                    CT-8 warm-at-boot: lifespan calls background warm; failure never blocks ready
                    CT-9 no-new-persistence: envelope construction performs NO DB writes
                    and reads NO chunk stores (Pacman filing count/rows unchanged by envelope
                    build — asserts against a recording episodic store)
                    CT-10 hard rules hold: a repeat step is NEVER re-dispatched (blocked
                    pre-dispatch + rerouted to read), a walled tool is NEVER retried in-run;
                    suggestion overrides are logged with reasons (fixtures: repeat crawl,
                    walled domain, mismatch override)
tests/behavioral/   BT-1 full 3-step research-shaped task through the real loop: working memory,
                    continuation prompt, and fallback report contain ONLY envelope lines
                    (failure lines included); run reports done + grade; a seeded
                    load-bearing mismatch caps the grade below pass (emergent property:
                    no 71.5k possible, no low-bar pass possible)
                    BT-2 streak gate: repeat/empty/mismatch streaks fire the gate
                    (TOPO_VIOLATION rec forces fire regardless of streaks); nominal run
                    blocks it (counter-verified); replan machinery invoked exactly at threshold,
                    never before; hard-rule blocks need NO gate (proven in CT-10)
                    BT-3 embed warm: cold sidecar → warm task runs, breaker stays closed through
                    a rerank-bearing step
scripts/            live gate rides the standing comparison probe (session-312 handoff pin):
                    context pill <50% window, no URL re-crawl, honest UNVERIFIED, <4min,
                    breaker closed, zero Empty failures
```
Intertwined: every behavioral gap found decomposes into the contract test that would have caught it (e.g. BT-1 finding raw in the continuation prompt's done_summary half → CT-2 extension; a repeat re-dispatched → CT-10 extension). Physics-aware: BT-2 injects Caducean rec states (TOPO_VIOLATION forces gate fire regardless of streak arithmetic — KD-4). Baseline to hold: twins+loop-bounds 39 pass / 6 pre-existing fails; contract 1478-1485 pass / 30 pre-existing (session-310-verified).

**Live-verification gate:** the success-criteria targets (context <50% window, breaker closed, zero Empty, <4min turn) are validated ONLY by the live comparison probe on the restarted backend — unit/contract green is not done.

Session-318 extension (Wave 5 proving tests):
```
tests/contract/     CT-11 envelope sources: fields bounded (≤8, truncation marked), ledger
                    pointers-only (no bodies in prompts — fixtures with bodies assert absence)
                    CT-12 chooser exclusions: conv-102 replay fixtures (one seed, three queries)
                    → 2nd/3rd pick refused or re-seeded; empty-after-exclusion → pivot, never force
                    CT-13 guard on resolved seeds: crawler-resolved URLs fed back → repeat
                    blocked even when params["known_urls"] was empty at dispatch
                    CT-14 identity: identical bodies dedup to raw_ref read + hash-hit log;
                    dead addresses (4xx/empty/known-404) never re-fetched in-turn
                    CT-15 deadlines: fake-clock expiry → timeout envelope (cause + elapsed),
                    streak-counted; completion-at-boundary wins; every wait bounded
                    CT-16 recovery lane: 404 → sibling navigation allowed with own envelope +
                    budget; same-address re-fetch inside recovery still blocked; budget
                    exhaustion → honest dry-well; brain-side dependents bounded-wait
tests/behavioral/   BT-4 conv-102 trajectory replay through the FULL stack: zero same-address
                    re-fetch, VISITED block rendered in planning prompts, honest single-source
                    answer preserved (no hallucinated citations), grade capped per AC5.6
                    BT-5 hanging-tool drive: deadline fires → timeout streaks → gate fires →
                    run grade capped; no unbounded wait (fails closed on a stuck clock)
scripts/            live re-probe (T21): comparison probe with a seeded 404 — bars: zero
                    same-address re-fetch (log-proven), ledger lines in logs, turn <4min,
                    honest citations, breaker closed, zero Empty, recovery envelope present
```
Intertwined (extension): each new behavioral gap decomposes to its contract twin (e.g. BT-4 finding a re-seeded duplicate → CT-12 extension; a silent hang → CT-15 extension).
