# Requirements: DER DAG-Inversion — Physics-Governed Execution, Memory-Backed DAG, and Integrity Repairs

## Decisions Locked

- **The physics is the machine, not a decoration.** DER shall steer by the continuous Caducean signal (u/ξ), not by binary gates. Non-binary logic: graded verification, graded splitting, graded escalation.
- **The DAG is the memory, and the memory is the DAG.** Every step, split child, and sub-loop is a node that is simultaneously a work unit and a memory record. The execution tree is a traversal over the memory graph.
- **Node landing exists so the context window can FORGET.** This is the purpose of REQ-2/REQ-3, not a side effect. Once a node's record lives in memory, the working context no longer has to carry it: the agent drops the tokens in the short term and re-reads the record when a later step needs it. This is what makes the layer-before-a-split disposable in practice. NOTE the two distinct resources — the DER budget is a CUMULATIVE SPEND cap and pruning cannot refund tokens already spent, but a smaller per-step context means a smaller per-step debit, so more steps fit inside the same budget. Forgetting buys throughput, not a refund.
- **One shared cross-conversation memory, decayed rather than curated.** The store is shared across every conversation; Immortus labels conversation ids, events, and content into a 4D time layer so anything can be recalled months later if it survives Kyudo decay. Low-value nodes are therefore expected to arrive and expected to decay — the design does NOT depend on keeping the store clean at write time. Consequence: REQ-10 (challenge-page detection) is justified by ANSWER QUALITY — a challenge page must not be cited as a source or penalize the wrong domain — NOT by protecting the database.
- **Coupling follows a DECISION, not a threshold.** Relevance retrieval SURFACES the candidate branches; the agent makes an informed choice with both in view; the edge is then written as the consequence of that choice. Which branch "wins" is not the system's business — awareness of both, and a recorded decision, is. This is the concrete meaning of DAG-by-inversion: a builder adding a layer on top of prior layers, rather than a binary gate selecting one.
- **Hardcoded behavior is barred because it CONTAMINATES the signal, not for purity.** A hand-authored rule writes a biased node into shared memory, and that node is later recalled as if it were evidence — so the bias compounds into every downstream decision. The prohibition is about keeping the memory signal trustworthy over months, not about style.
- **Single system of record: `data/memory.db`** (from `data/memory_config.json` → `db_path`). `.mcm/coordinates.db` is BUILD memory (the MCM coordinate graph) and is NEVER migrated or written by the application path — see backend/agent/memory.py:339-342, which states this explicitly. `backend/data/memory.db` is a stray artifact that is not the configured store.
- **The memory signal is all three sources merged into one** — (a) the live feel (u/ξ compressed state), (b) the learned record (mycelium edge scores), (c) the map of branches (coordinate chain) — and that single signal is the steering input.
- **Inversion of governance is emergent and never hardcoded.** Governance alternates between the stateless past (compressed node records) and the stateful present (live Σ) as a function of the signal. No decision path hardcodes which one is authoritative. The alternation is measured and exposed (REQ-6).
- **The goal is a strong signal via structure, not behavior rules.** We complete the structure (nodes land in memory, edges couple, Σ compresses, outer loop judges) so the signal is trustworthy. We are not writing conditionals telling the agent what to do.
- **Narration is ambient audio only.** No UI element, no new WS narration message type without explicit user sign-off (REQ-15 AC4).
- **Physics narration: measure-then-tune.** Empirically test whether task-complete/phase-transition moments naturally coincide with band crossings. If not, the user chooses between retuning bands from the observed |u| distribution OR adding explicit task-complete/phase-transition ambient lines. The choice is recorded back here when made.
- **Rate limiting is a demand-side fix.** Cut calls per turn (layer-batched execution, synthesis diet). DO NOT raise CEILING_MIN_RPM / CEILING_MAX_RPM / PHASE_HARD_MAX_RPM. Keep the Retry-After clamp and single-debit-per-step accounting (REQ-9).
- **der_steps is wired, not deleted.** It is assigned the real per-turn step count (REQ-12 AC3).
- **Execution stays a queue-based traversal; the LAYERING lives in memory.** The parent layer is disposable after split (already true today); the next layer's execution governs. What must exist is the node's memory record so the structure persists.
- **Baseline-first, zero regressions.** The frontend is deeply wired to every step event. All event shapes are contract-locked (CT-IDs below) before behavior changes. Wave 0 establishes and records the honest baseline.
- **The phase manager is NOT enabled as a rate fix.** It only de-correlates timing; it does not cut call count. It stays FLAG-OFF (decision may be revisited separately).
- **The ontology reuses the existing link store, extended, not duplicated.** DER relationships land in the proven mycelium link vocabulary (documents|references|implements|depends_on|contains|related_to) plus derives_from|part_of|relevant_to|failed_like. No second edge store is built (REQ-19).
- **Two domain axes, registry-backed, never free text.** topic_domain (recall axis — mycelium DOMAIN_IDS) and execution_domain (physics axis — request-domain manager: voice|der|research) are separate fields. Unknown values resolve to the registry's general/unknown and are logged, never invented (REQ-18).

## Introduction

DER currently executes a hardcoded Director→Explorer→Reviewer pipeline steered by binary gates (verified/failed, split/not, budget left/not) over a flat queue, while the memory it is supposed to be building — a coordinate-addressed chain of branch nodes — writes zero rows because of a silent schema mismatch. The result: the loop is call-hungry (~15–40 LLM calls per turn), 429-stalls for minutes on a giant final synthesis call, and its own physics narration is provably mute. This spec makes the architecture honest to its own invariant — *compress everything that happened into one honest current position, then react to that position* — by completing the structure: every node lands in memory, edges couple by relevance, Σ compresses it all, gates become graded, the outer loop becomes a live judge, and the frontend contracts are pinned so nothing regresses.

### Success criteria
- Budget line resolves the context window from the ACTIVE reasoning binding; the 8192-default collapse is unreachable when a binding exists.
- After any real task, `memory_chain` contains ≥1 coordinate-addressed row per executed step (zero-row state is a test failure, not a known gap).
- One DER turn's LLM call count drops by ≥30% for a FULL-mode task with splits (layer-batched execution + synthesis diet), measurable via a per-turn call-count log.
- `CRAWLER_PAGE_FETCHED` never duplicates a (job_id, page_number); no challenge page is saved as content; OPEN_TAB carries url/job_id and the frontend never jumps to a blank tab.
- `[LAYERS]` reports a real `der_steps` value; pheromone prediction returns real predictions; legacy caducean DBs migrate idempotently.
- Physics narration fires at least once per task sample after tuning, OR explicit task-complete/phase-transition lines ship (user-gated, recorded above).
- The outer loop runs at real session boundaries and reports live signal relevance/strength.
- After any real task, the memory graph contains typed nodes (type + both domain axes) with typed relationships (parent/depends_on/failed_like) queryable via the link store; per-domain physics aggregates exist per session.
- Full backend suite + frontend jest green modulo the documented stale artifacts (Wave 0 baseline).

## Requirements

### REQ-1: Context window resolved from the ACTIVE reasoning binding
**User Story:** As DER I want my execution budget sized from the model I am actually routed to so that my loop is never silently under-funded by a stale field.
**Verified:** agent_kernel.py:240 (sentinel init), :861 (legacy writer), :983–1047 (resolver, default at 1042–1047), :10351 (set_role_binding writes model, never provider); iris_gateway.py:1465 (provider sync only on confirm_card); inference/router.py:429–480 (resolve()/health_check_provider exist); der_constants.py:118, 170–190 (floor 4000 wins at window 8192); agent_kernel.py:5577–5578 (budget from resolve_context_window).
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL resolve the DER budget context window from the InferenceRouter's active reasoning binding (provider + model) whenever one exists, regardless of the legacy `_model_provider` field's value.
- AC2: WHEN role bindings are (re)bound, including at startup, THEN THE SYSTEM SHALL keep the legacy provider/model fields in sync so downstream readers agree with actual routing.
- AC3: IF the active binding's model has no entry in `_KNOWN_CONTEXT_WINDOWS` THEN THE SYSTEM SHALL log a tagged WARN naming provider+model+source and fall back to the conservative default — loudly, not silently.
- AC4: THE SYSTEM SHALL remove the vacuous `"" in profile.id` substring guard that can short-circuit resolution (agent_kernel.py:1037).
**Edge Cases:** unbound role → fall back to default-role binding then conservative default; local model → authoritative n_ctx path unchanged; empty override dict; restart with role-bindings-only routing (the exact 256k→8192 collapse case).

### REQ-2: Node memory landing — every step writes its coordinate record
**User Story:** As the DAG I want every step/split/sub-loop to land as a coordinate-addressed record in shared memory so that the execution structure exists in memory and can be coupled, referenced, and recalled.
**Verified:** agent_kernel.py:9315–9326 (durability_submit immortus append per step); durability_queue.py:62–73, 90–117 (write failure logged + counted). LIVE DB PROBE (re-run — supersedes the earlier single-DB probe): THREE competing schemas across THREE databases —
| DB | table | rows | schema |
|---|---|---|---|
| `data/memory.db` (**the configured app store**, memory_config.json `db_path`) | memory_chain | **1825** | LEGACY: entry_id, thread_id, session_id, sequence, role, content, metadata, session_ts, result, distilled, created_at |
| `data/memory.db` | memory_chain_v2 | 0 | ORPHAN THIRD SHAPE: chain_id, thread_id, sequence, label, role, content, metadata, distilled, created_at |
| `backend/data/memory.db` (**not the configured store**) | memory_chain | 0 | CORRECT COORDINATE SHAPE: chain_id, thread_id, result, coords_from, coords_to, nbl_outcome, insight, file_path, landmark_id, stale, created_at |
| `.mcm/coordinates.db` (**BUILD memory — out of bounds**) | memory_chain / memory_chain_v2 | 4826 / 0 | LEGACY / orphan |
So the coordinate-shaped table already exists but in a database the application does not open, while the app writes into a legacy-shaped table — and an abandoned `memory_chain_v2` is a third shape in two DBs. backend/agent/memory.py:339–342 explicitly forbids the app path from touching `.mcm/coordinates.db`.
**Acceptance Criteria:**
- AC1: WHEN a DER step finalizes THEN THE SYSTEM SHALL append a `memory_chain` row carrying `coords_from`/`coords_to` from the node's pre/post Σ snapshots, with its outcome and insight.
- AC2: THE SYSTEM SHALL resolve the chain store from `memory_config.json` `db_path` and write to that ONE database. Writing to a non-configured path is a defect, not a fallback.
- AC3: THE SYSTEM SHALL migrate the CONFIGURED store's legacy `memory_chain` to the coordinate schema by idempotent ALTER, PRESERVING the existing 1825 rows (coords columns null for legacy rows, which recall must tolerate). `CREATE TABLE IF NOT EXISTS` shall no longer paper over a shape mismatch.
- AC4: THE SYSTEM SHALL resolve the orphan `memory_chain_v2` explicitly — either fold it into `memory_chain` or drop it — and record the choice here. A third empty shape shall not survive this spec.
- AC5: THE SYSTEM SHALL NOT migrate, write, or ALTER `.mcm/coordinates.db` from the application path.
- AC6: IF a chain write fails THEN THE SYSTEM SHALL log the step id and increment a counted drop counter — never a silent swallow.
- AC7: THE SYSTEM SHALL assert in a behavioral test that ≥1 row lands per executed step over a real task, against the CONFIGURED store.
**Edge Cases:** legacy rows with null coords (must not break recall or aggregation); durability queue full (512) → counted drops, order preserved; Python fallback store; FFI unavailable; configured db_path relative vs absolute resolution.

### REQ-2b: Build-memory inheritance parity
**User Story:** As the project I want the BUILD coordinate graph to be inheritable by the application at completion, as promised, so the "same schema, no migration" hand-off is true rather than aspirational.
**Verified:** CLAUDE.md states `.mcm/coordinates.db` transfers to the application's runtime memory store at completion — "Same schema. No migration." The live probe shows this is currently FALSE: `.mcm/coordinates.db :: memory_chain` is legacy-shaped (4826 rows) while the application's coordinate schema differs, and both carry an orphan `memory_chain_v2`.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL document the schema delta between the BUILD store and the application store for every shared table, as data.
- AC2: THE SYSTEM SHALL provide a one-shot, offline, non-destructive inheritance migration (run by a human, never at app start) that brings the BUILD store to the application schema.
- AC3: THE "same schema, no migration" claim SHALL either be made true or corrected in CLAUDE.md — it shall not remain stated-but-false.
**Edge Cases:** BUILD store absent; partial overlap (tables in one and not the other); inheritance run twice → idempotent.

### REQ-3: Per-node compressed record and live state as step input
**User Story:** As DER I want every step to start from the compressed position plus its relevant neighbor nodes so that memory governs the path instead of being consulted on demand.
**Verified:** SubLoopFootprint (der_loop.py:70–106) is write-once and sub-loop-only; agent_kernel.py:7190–7211 (child creation); mid-loop episodic retrieval agent_kernel.py:5826–5931 (opt-in style, not a first-class input).
**Acceptance Criteria:**
- AC1: WHEN a step begins THEN THE SYSTEM SHALL provide its context from the compressed state (Σ) plus the relevant neighbor node records — a first-class input, not an opt-in query.
- AC2: THE SYSTEM SHALL generalize the SubLoopFootprint record (content summary, coordinate, expected output, ruled-out) to ALL nodes, not only sub-loop children.
- AC3: IF the store has no rows for the node's coordinate THEN THE SYSTEM SHALL proceed on the live state alone and mark the step memory-sparse in the observability log.
- AC4 (FORGETTING — the point of the record): ONCE a node's record has landed, THE SYSTEM SHALL DROP that node's raw content from the working context rather than carrying it forward, re-reading the record only when a later step's retrieval selects it. A landed node that is still carried verbatim in the prompt means the record bought nothing.
- AC5: THE SYSTEM SHALL bound the per-step working context and record, per turn, the prompt token count at each step so the reduction is measurable — the same way REQ-7 measures call count. Forgetting must be demonstrated as a NUMBER, not asserted.
- AC6: THE SYSTEM SHALL NOT drop content whose node record failed to land (REQ-2 AC6 drop counter) — a failed write means the context is the only copy, and dropping it would lose the work silently.
**Edge Cases:** empty memory (fresh session); store unreachable; node not found → fall back to live state; memory-sparse flag must not error the step; record landed but retrieval later cannot find it (widen per REQ-20 before assuming absence); chain drop counter non-zero → forgetting disabled for that step.

### REQ-4: Non-binary steering — gates consume the continuous signal
**User Story:** As the engine I want the loop's decisions to be graded functions of the continuous signal (u/ξ, verified fraction, edge strength) so DER operates as a non-binary instrument instead of a stack of switches.
**Verified:** `_verified_fraction` is continuous (verifier.py:189, agent_kernel.py:8345) but consumed binary; `_growth_width` maps |u| to width 3/1 (agent_kernel.py:7076–7098); reviewer verdicts VETO/REFINE (der_loop.py:620–654); while-loop gates (agent_kernel.py:5757–5763); architecture design rule 2 "prefer a continuous function of the physics signal over a threshold" (CADUCEAN_ARCHITECTURE.md §10).
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL consume the continuous verification fraction and coupling/edge strength as steering inputs at the decision points (split decision, verification verdict, escalation) rather than collapsing them to binary gates.
- AC2: WHEN the signal is mid-band (neither strongly converged nor strongly split) THEN THE SYSTEM SHALL take the graded middle path (bounded probe), not a threshold coin-flip.
- AC3: THE SYSTEM SHALL retain the work-unit resource as the sole termination guarantee (Lyapunov), keeping DER_MAX_CYCLES / DER_EMERGENCY_STOP as safety rails only.
- AC4 (WHAT A SPLIT CHILD IS FOR — split to RESOLVE, not to RETRY): WHEN a step splits after a failure THEN the child's `objective_anchor` SHALL be to resolve the specific thing that blocked the parent, NOT a restatement of the parent's goal. A child that re-attempts the parent's objective with the same information is a retry wearing a new node id: it spends the budget again and lands in the same state, which is what the observed `s2_s0 → s2_s0_s0 → …` cascades were doing. The child folds back as a compressed observation that CHANGES the parent's state, and the parent then re-decides with new information (REQ-3 AC1). A split that cannot name what it is resolving SHALL be recorded as such — an unnamed blocker is a signal the failure was not understood, and it is better read as evidence than hidden behind a fresh id.
**Edge Cases:** signal NaN/unavailable → conservative path, logged; verified fraction exactly mid-band; no mycelium edges yet.

### REQ-5: Coupling — relevance edges form branches
**User Story:** As the memory I want relevance edges to form between any two nodes (across tasks and sessions) driven by compression/expansion, so that related splits connect and seed new branches.
**Verified:** coupled_registry FLAG-OFF (IRIS_COUPLING_ENABLED unset, 359 lines); trig_coupling.py:52–89 (splay/align forces); mycelium per-step edge scoring exists (scorer.py:70–102; agent_kernel.py:9027); coordinate chain empty (REQ-2).
**Acceptance Criteria:**
REWRITTEN: coupling is the CONSEQUENCE OF A DECISION, not a similarity threshold. Retrieval's job is to put the relevant branches in front of the agent; the agent chooses with both in view; the edge records that choice. Which branch "wins" is not the system's business — awareness of the alternatives, and a recorded decision, is. An auto-linker that couples by score alone would write edges nobody decided, which is precisely the biased-node contamination barred in Decisions Locked.
- AC1: WHEN a step's retrieval finds more than one relevant branch THEN THE SYSTEM SHALL surface ALL of them (bounded by a candidate cap) to the deciding step — never silently pre-select one by score.
- AC2: WHEN the step commits to a direction THEN THE SYSTEM SHALL write or strengthen the coupling edge to the branch(es) that informed it, recording the decision as the edge's provenance.
- AC3: THE SYSTEM SHALL rank and retrieve candidates using coordinate proximity, learned scores, and compression/expansion state (u sign/magnitude) — ranking is physics- and evidence-driven; SELECTION is the agent's.
- AC4: THE SYSTEM SHALL record, per coupling decision, how many candidates were surfaced and which were chosen, so "was the agent aware of both branches" is answerable from data rather than assumed.
- AC5 (falsifiability — closes the "this requirement cannot fail" gap): after the measurement wave, THE SYSTEM SHALL state a target for candidate-surfacing coverage (how often a decision saw ≥2 candidates when ≥2 existed) and FAIL below it. The target is set from observed data, not guessed in advance, and recorded in Decisions Locked.
- AC6 (USE THE COUPLING MATH THAT ALREADY EXISTS — do not write a second one): `trig_coupling.py` implements the attractive/repulsive forces (`align_force`, `splay_force`, 157 lines, test-covered). `align_force` is ALREADY wired — called at `coupled_registry.py:287` — but `coupled_registry` is gated by `IRIS_COUPLING_ENABLED`, which DEFAULTS TO "0". So the coupling math is not dead, it is DORMANT: written, wired, and never switched on. Enabling coupling (T17) SHALL activate that path rather than introducing parallel relevance math beside it. If the existing forces prove unsuitable, that is a finding to record with the reason — not a licence to leave a second implementation next to the first. Two competing coupling implementations is precisely the outcome this project keeps producing.
**Edge Cases:** first node ever (no edges); only one candidate → coupled without a choice, recorded as such; coupling disabled by flag → no edges, no error; self-relevance; score ties (surface both — ties are exactly the case AC1 exists for); candidate cap exceeded → record the truncation count; flag flipped on for the first time on a store with existing nodes → edges form from history, which is intended (cross-conversation per REQ-20 AC1b), not a bug.

### REQ-26: The Bayesian update — belief moves with evidence, and the loop CLOSES
**User Story:** As the agent I want my choice of action to come from what the evidence says works in the state I am actually in, so that finding a confounder updates a belief instead of triggering a hardcoded retry rule.
**Verified — AND THIS IS NOT YET A BAYESIAN UPDATE:** `scorer.py:41–45` applies FIXED deltas — `hit +0.05`, `partial +0.02`, `miss −0.08` — plus `HIGHWAY_BONUS +0.01` on crossing 0.85 (:96–100), with time decay and pruning below 0.08 (`apply_decay`, :104+). Three consequences the spec must address rather than inherit:
  (a) **No sample count.** The 100th observation moves the score exactly as much as the 1st, so belief oscillates instead of converging and confidence is unrepresentable — which is the entire thing a posterior gives you.
  (b) **Asymmetric by 1.6×.** A miss (−0.08) outweighs a hit (+0.05); ~2 hits are needed to undo 1 miss. That may be a deliberate pessimism bias, but it is currently implicit.
  (c) **`record_outcome(edge_ids, outcome)` is not region-scoped at the update site.** Region scoping depends ENTIRELY on which edge is passed in. So it is achievable, but only if the caller selects the (coordinate-region, mediator) edge — it cannot be assumed.
Also: `BehavioralPredictor` — the component that would supply the prior — is currently broken (REQ-12 AC1, constructor mismatch), so today there is no prior being read at all.
**Acceptance Criteria:**
- AC1 (THE TARGET): the outcome of a finalized node SHALL update the edge for that (coordinate-region, mediator) pair — the mediator recorded per REQ-23 — not a global per-tool score. A tool that works in one region and fails in another must be representable; a single global score cannot express that, and expressing it is the whole point.
- AC2 (EVIDENCE-WEIGHTED — the actual Bayesian part): each edge SHALL carry an observation count, and the magnitude of an update SHALL diminish as that count grows, so early evidence moves belief quickly and established belief resists a single anomaly. A flat delta is a reinforcement rule, not a posterior. The hit/miss asymmetry SHALL be stated as a deliberate prior (pessimism) or removed — not left implicit.
- AC3 (THE LOOP MUST CLOSE — the failure mode this project keeps repeating): the next mediator decision SHALL READ the updated score as its prior. An update nothing reads is a dead write, exactly like `der_steps` and `dispatch_batch`. A contract test SHALL assert read-after-write across a decision boundary: score changes, and the NEXT ranking in that region reflects it.
- AC4 (NO HARDCODED RECOVERY RULE): on failure the system SHALL NOT select the next mediator by a fixed `IF failed THEN retry/next-tool` branch. Selection comes from the ranking; the failure's contribution is the score update. This is REQ-4's non-binary steering applied to action choice, and the concrete reason Decisions Locked bars hardcoded behavior — a fixed rule writes a biased node that is later recalled AS EVIDENCE.
- AC5 (UNSEEN PAIRS): the prior for a (region, mediator) pair with no observations SHALL be explicitly defined and recorded, so first-encounter behavior is a decision rather than an accident of initialization.
- AC6 (DISCRIMINATING TEST — this one catches a fake implementation): repeated failure of a mediator in region A SHALL lower its rank in region A **while leaving its rank in region B materially unchanged**. Global decay alone passes a naive "score went down" test and fails this one. This is the acceptance test for REQ-26.
- AC7 (DECAY IS NOT EVIDENCE): time decay (`apply_decay`, Kyudo) is forgetting, not observation. Decay SHALL NOT be counted as a miss, and the observation count SHALL NOT be inflated by it — otherwise unused-but-good paths are indistinguishable from tried-and-failed ones.
**Edge Cases:** first observation ever (AC5 prior); region boundary — a node whose coordinates sit between regions (record which region was credited); mediator succeeded but the overall step failed for an unrelated reason (do not credit the miss to the mediator — this is the mis-attribution that quietly poisons the graph); batched children (REQ-7) sharing one call, each crediting its own mediator; decayed-then-revisited edge (belief re-strengthens from evidence, not from the decay reset).

### REQ-25: Dormant-capability register — no concept left half-alive
**User Story:** As the project I want every built-but-inactive capability either switched on, or recorded as deliberately off with the condition that would turn it on, so nothing sits in the codebase as an unexplained fragment.
**Verified:** production call-site audit (entry function invoked outside tests): `run_outer_loop` → **0** (REQ-16/T32 activates); `dispatch_batch` → **1**, and that one is the internal wrapper at batch_dispatch.py:314, not the DER loop (REQ-7/T25 activates); `compute_coupling` → **0**; `align_force` → live but only under `IRIS_COUPLING_ENABLED=0` (REQ-5 AC6/T17 activates); `splay_force` → live but only under `IRIS_PHASE_SCHEDULER` unset, which this spec deliberately keeps off (locked decision).
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL carry a register (in `ontology.md` or alongside it) of every capability that is built but not active, each with: where it is invoked from, the flag or wiring that gates it, and the CONDITION under which it should be turned on.
- AC2: A capability that this spec deliberately leaves off SHALL state its exit condition. `splay_force`/`phase_manager` is the worked example: kept off because it de-correlates TIMING and cannot cut CALL COUNT, and because `PHASE_MAX_WAIT_S` defaults to 2.0s against a provider returning `Retry-After: 30` — two orders of magnitude too small to matter. Exit condition: revisit only if 429s persist AFTER the demand-side fixes (REQ-7, REQ-8) have landed and been measured.
- AC3: A capability with NO exit condition and NO activation task SHALL be deleted rather than left dormant. "Might be useful later" is how the fragments accumulate.
- AC4: THE REGISTER SHALL be checked in CI against the call-site audit so a newly-orphaned entry point fails loudly instead of quietly joining the list.
**Edge Cases:** capability behind a flag that is on in dev and off in prod (record both); capability whose only caller is a test (that is the definition of dormant, not of covered); capability activated by this spec (remove from the register when its wave closes).

### REQ-6: Inversion of governance — emergent, measured
**User Story:** As the tuner I want to observe which signal governed each decision so that the inversion between the stateless past and the stateful present is real and measurable, never hardcoded.
**Verified:** no governance-source recording exists today; TurnMetrics (observability.py:95–137) has no such field; [LAYERS] line is the canonical per-turn summary.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL record for each steering decision which signal governed it (past-memory vs live-state vs both) in a tagged log line off the hot path.
- AC2: THE SYSTEM SHALL NOT hardcode authority between memory and live state in any decision path.
- AC3: THE SYSTEM SHALL expose the governance alternation ratio (past-governed vs present-governed per turn) as an observability signal readable by the outer loop.
**Edge Cases:** high-volume turns → governance log batched/lossy-safe; decision with equal signals → record "both".

### REQ-7: Layer-batched execution — sub-loop children run as one call
**User Story:** As DER I want the children of a join point executed as ONE batched LLM call so that a layer executes together and the rate-limit pressure from per-child calls disappears.
**Verified:** batch_dispatch.py:40–42, 176–263 (BATCH_MAX_CHILDREN=3, join_point from id prefix, _compose_batch, parse_batched_response) — built and test-covered but `dispatch_batch` is invoked ONLY in tests; production calls get_batcher().offer() then re-adds children individually (agent_kernel.py:6985–6991, 8914–8920); call arithmetic ≈39 calls for a 5-step FULL task with 2 splits.
**Acceptance Criteria:**
- AC1: WHEN a join point's children are ready THEN THE SYSTEM SHALL execute them as ONE batched LLM call and route each result back to its node (dispatch_batch wired into the DER loop).
- AC2: THE SYSTEM SHALL bound batches at BATCH_MAX_CHILDREN and BATCH_MAX_HOLD_S, falling back to individual execution when the batched response fails to parse.
- AC3: THE SYSTEM SHALL record the per-turn call count so the reduction is measurable against the Wave 0 baseline.
**Edge Cases:** batch parse failure → per-child fallback; join point with one child → direct execution; queue saturation.

### REQ-8: Synthesis diet + spoken-text normalization
**User Story:** As the user I want the final answer built from the compressed node records and spoken in companion style so that the giant full-history call and the verbatim markdown reading both disappear.
**Verified:** final synthesis prompt concatenates ALL tool results (agent_kernel.py:9827–9834; 7417–7463) with max_tokens=4096 and three fallback chains (9862–9900) — the 429-stall culprit; prepare_spoken_text (agent_kernel.py:2974–3040) computed then discarded (iris_gateway.py:2786–2849); raw response streams un-normalized (iris_gateway.py:2714–2737).
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL build the final synthesis from the compressed node records (REQ-3) instead of the raw full step history.
- AC2: THE SYSTEM SHALL apply spoken-text normalization/truncation at the sentence-flush point so the streaming TTS path reads companion-style text, not raw markdown.
- AC3: IF synthesis fails at the primary provider THEN THE SYSTEM SHALL degrade to the compressed-summary fallback without replaying the giant prompt through the whole fallback chain.
**Edge Cases:** no node records (empty memory) → fall back to raw summary; very long task → truncated spoken text, full text in chat (display unchanged).

### REQ-9: Rate-limit honesty — demand-side fix, ceiling unchanged
**User Story:** As the operator I want the rate-limit system to keep its verified semantics (single debit, Retry-After clamp) while the demand side is fixed at the source.
**Verified:** transport.py:39–41 (RETRY_AFTER_MAX_S=30), :99–137 (clamp+sleep); token debit is once per step, not per attempt (agent_kernel.py:8690 — F3 resolved); rate_meter.py:49–65 (CEILING_INIT_RPM=30, CEILING_MIN_RPM=15, CEILING_MD=0.5, PHASE_HARD_MAX_RPM=120).
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL retain single-debit-per-step token accounting and the Retry-After clamp — no changes to either.
- AC2: THE SYSTEM SHALL NOT raise CEILING_MIN_RPM, CEILING_MAX_RPM, or PHASE_HARD_MAX_RPM (locked decision).
- AC3: THE SYSTEM SHALL expose per-quota 429 frequency and ceiling trajectory as a read-only signal the outer loop can consume.
**Edge Cases:** local/Ollama providers (unmetered, inf) — unchanged; persistent saturation → counted, reported, never silent.

### REQ-10: Interstitial detection and source penalize
**User Story:** As the crawler I want bot-challenge pages detected before they are saved so that challenge interstitials never masquerade as content.
**Verified:** zero challenge detection repo-wide (grep "Just a moment|cloudflare|turnstile" → 0 hits); capture saves raw HTML (crawler_engine.py:370–381, 399–405; crawl_runner.py:374–482 incl. _plain_http_fetch 434–439); penalize only fires on 403/404/timeout (orchestrator.py:426–453; source_registry.py:122–142).
**Acceptance Criteria:**
- AC1: WHEN fetched HTML matches a challenge-page signature THEN THE SYSTEM SHALL NOT save it as content and SHALL mark the page challenged.
- AC2: WHEN a page is challenged THEN THE SYSTEM SHALL penalize the source (halve credibility, last_error="challenge") as a failed crawl.
- AC3: THE SYSTEM SHALL log the challenge with url and matched signature so false positives are tunable.
**Edge Cases:** HTTP 200 challenge (the common case); challenge signature false positive → tunable list; challenged page with real content behind it → marked, not penalized twice.

### REQ-11: Crawler event contract integrity — OPEN_TAB payload and single emission
**User Story:** As the frontend I want crawler events that are complete and non-duplicated so the panel never jumps to a blank tab and pages never render twice.
**Verified:** OPEN_TAB emitted once at crawl end with tab_type=dashboard and NO url/job_id (orchestrator.py:270–273); frontend openTab() calls setActiveTabId(msg.id) unconditionally (dark-glass-dashboard.tsx:572–592, :591); two CRAWLER_PAGE_FETCHED paths (crawler_engine.py:399–405 and crawl_runner.py:448–455) with no dedup; WS relays drop fields (iris_gateway.py:8917–8932; tool_bridge.py:2569–2605).
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL emit OPEN_TAB with url and job_id when opening a crawl dashboard tab, and the frontend SHALL NOT switch the active tab to a tab with no url unless dashboard data is present.
- AC2: THE SYSTEM SHALL emit each CRAWLER_PAGE_FETCHED at most once per (job_id, page_number) across both fetch paths.
- AC3: CONTRACT LOCK — the WS relay field sets (iris_gateway, tool_bridge) SHALL be pinned by contract tests (CT-C1, CT-C2, CT-C3) before and after the change.
**Edge Cases:** dashboard open with empty data → stays on current tab; fallback path re-fetch after worker already reported → suppressed; SSE replay (api/crawl_stream.py) unchanged.

### REQ-12: Repair dead memory components
**User Story:** As the memory I want my silent failures audible: pheromone prediction working, legacy schemas migrated, and the step counter honest.
**Verified:** BehavioralPredictor has no __init__ (interpreter.py:205) and 3 call sites pass myc → TypeError swallowed (explorer.py:107/118, evidence.py:69/79, live_context.py:127); working site recall_decoder.py:464; caducean_trajectories domain exists in current schema (caducean_trajectory.py:55) but no ALTER migration (only recommendation has one, :117–119); legacy fixture at tests/behavioral/test_param_ratchet_recovery.py:168–172; der_steps declared (observability.py:107), read (:137, agent_kernel.py:4883), never assigned; real count exists as len(completed_items) (agent_kernel.py:6290, 6339, 8726).
**Acceptance Criteria:**
- AC1: BehavioralPredictor SHALL accept the constructor argument (or the three call sites SHALL stop passing it) so pheromone_top1/predicted_next return real predictions and the "pheromone_top1 failed" / "predicted_next failed" logs disappear.
- AC2: THE SYSTEM SHALL provide an idempotent ALTER migration adding caducean_trajectories.domain for legacy databases, and a test that creates the table via the current _SQL_CREATE and asserts the column exists.
- AC3: TurnMetrics.der_steps SHALL be assigned the real per-turn step count so the [LAYERS] line reports truth.
**Edge Cases:** legacy table without domain → migrated idempotently; recorder bound to unopenable store → Noop recorder path unchanged; zero-step turn → der_steps=0 is now an honest 0.

### REQ-13: Narration policy surface and unified gating
**User Story:** As the tuner I want narration policy in config and every source behind one gate so tuning is a config change and no source bypasses the cadence.
**Verified:** all policy hardcoded — 18s gate (narration.py:212), 25s heartbeat (:105), 25s page cooldown (tool_bridge.py:1893), 5s SpeakTool cooldown + 3-per-10s (speak_tool.py:29–31, 106–107), 500-char cap; thinking filler ungated by may_narrate (agent_kernel.py:4591–4608).
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL load narration policy (gate intervals, cooldowns, caps) from config, not module literals.
- AC2: THE SYSTEM SHALL route ALL narration sources through the shared gate so no source (including the thinking filler) bypasses it.
- AC3: THE SYSTEM SHALL content-dedupe page narration (same snippet twice → spoken once).
**Edge Cases:** config missing → defaults; zero-config deployment; filler + heartbeat collision → last-writer within gate.

### REQ-14: Narration and decision logs off the DER hot path
**User Story:** As DER I want narration logging to never block a step finalize.
**Verified:** sync JSONL write with os.makedirs per call (narration.py:53–59) inside _der_finalize_step (agent_kernel.py:9493–9529) on every step including silence.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL write narration/decision logs asynchronously (or batched), with makedirs hoisted to init.
- AC2: THE SYSTEM SHALL keep the log lossy-safe — dropped lines are acceptable, never blocking or raising.
**Edge Cases:** disk full → dropped lines, no step failure; process exit mid-flush → bounded loss.

### REQ-15: Physics narration reachability — measure, retune, trigger test
**User Story:** As the user I want the physics narration to actually be heard, tuned from real data, and honestly tested against task-complete/phase-transition moments.
**Verified:** detect_physics_narration (der_constants.py:341–395); bands U_SPLIT=0.5 / U_CONVERGED=0.85 (:233, :246); every production narration_logs entry is decision=silence (|u| observed 0.03–0.63); log schema exists for measurement (REQ-9/REQ-22 of prior phase).
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL report the observed |u| distribution, band-crossing rate, and split/collapse rate over a fixed task sample BEFORE any threshold change (measurement gate).
- AC2: THE SYSTEM SHALL test empirically whether task-complete and phase-transition moments coincide with band crossings; the result SHALL be recorded as data, not asserted as an expectation.
- AC3: WHEN the measurement shows no natural coincidence THEN THE SYSTEM SHALL either retune the bands from the observed distribution OR add explicit task-complete/phase-transition ambient lines — user-gated; the choice SHALL be recorded in Decisions Locked.
- AC4: Narration SHALL remain ambient audio only — no UI element and no new WS narration message type without explicit user sign-off.
**Edge Cases:** insufficient samples → measurement gate refuses to retune (report, don't guess); all-silence task → explicit trigger path; band retune makes split width change → cross-checked against REQ-4 graded steering.

### REQ-16: Outer loop as live relevance judge
**User Story:** As the agent I want the outer loop running at real session boundaries, feeding real observations and learning whether a memory signal is relevant or strong enough — in real time, not offline.
**Verified:** run_outer_loop has ZERO production call sites (test-only); its input producer record_session_exit (caducean_trajectory.py:402–463) is called only from archive_on_session_end (memory.py:342) which has no production caller; _score_with_liveness (outer_loop.py:150–234) already separates live from dead guards.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL invoke the outer loop at real session boundaries (session end / pre-compress) — a production call site, not test-only.
- AC2: THE SYSTEM SHALL feed record_session_exit from real session ends so the outer loop's observations are live.
- AC3: THE SYSTEM SHALL expose signal relevance/strength (from REQ-6 governance ratio, REQ-9 rate health, and REQ-21 per-domain physics aggregates) as tunable inputs so the agent learns in real time whether a memory signal is relevant or strong enough.
**Edge Cases:** session end without archive → still records exit; guard inputs unavailable → GuardResult.live=False (dead, not passing) per existing semantics; rate health absent → relevance from governance ratio only.

### REQ-17: Observability / tuning instrumentation
**User Story:** As the tuner I want one per-turn telemetry line covering the new signals so the next iteration can tune from data.
**Verified:** TurnMetrics (observability.py:95–137) is the canonical per-turn summary; [LAYERS] is asserted by benchmarks.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log per-turn: budget source, call count, governance ratio, chain rows landed, chain drop count, 429 count, narration decision count — timestamped and session-scoped.
- AC2: Every new signal SHALL be off the hot path (batched/lossy-safe where high-volume).
**Edge Cases:** zero-step turn; no chain rows (memory empty); missing metric → logged as 0/absent, never raises.

### REQ-18: Node ontology — typed nodes, two domain axes
**User Story:** As the memory I want every node typed (task|step|sub-loop) and tagged on two domain axes — topic (what it is about) and execution (how it runs) — so recall and physics parsing are exact, not free-text guesswork.
**Verified:** NodeRecord (REQ-3) has no type/domain fields; `domain` is free text and every production row is "general" (caducean_trajectory.py:55, 101); a controlled topic registry already exists (mycelium DOMAIN_IDS, spaces.py — 13 topics); the request-domain manager (der_constants.py) already distinguishes voice|der|research windings but nothing records which one actually ran.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL assign every DER node a `node_type` from {task, step, sub_loop}.
- AC1b (GAP CREATED BY THE REQ-5 REWRITE — a node's ROLE, not just its structure): {task, step, sub_loop} describes where a node sits in the tree, not what it did. A failed step and a decision that chose between two branches are both `step`. Now that coupling is decision-provenance (REQ-5 AC2), "which decisions were informed by branch X" must be a lookup, not a table scan. THE SYSTEM SHALL therefore additionally mark each node's ROLE — at minimum distinguishing a node that COMMITTED A DECISION (and is thus a valid coupling endpoint) from one that only gathered or executed. Without this marker the coupling provenance has no natural home and REQ-20's relationship filters cannot find decisions.
- AC1c (DISCRIMINATION, not just registry-backing): registry-backing prevents free text but does NOT guarantee the axis carries information. Today every production row is "general"; moving to a registry value of `general` would be the same failure wearing a controlled vocabulary. THE SYSTEM SHALL report, per session, the DISTRIBUTION of `topic_domain` across nodes and FAIL a coverage check if the modal domain exceeds a threshold set from observed data (same falsifiability pattern as REQ-5 AC5). If 13 registry buckets prove too coarse to discriminate, that is a finding to record — not a reason to widen to free text.
- AC2: THE SYSTEM SHALL record two domain axes per node — `topic_domain` (registry value from mycelium DOMAIN_IDS) and `execution_domain` (voice|der|research from the active winding) — both registry-backed, never free text.
- AC3: WHEN a domain value does not resolve to the registry THEN THE SYSTEM SHALL record the registry's general/unknown value and log the mismatch — never invent free text.
- AC4: THE SYSTEM SHALL expose node type + both domains on the node record and the chain row so recall (REQ-20) and aggregation (REQ-21) can key on them.
**Edge Cases:** registry miss → general + logged; legacy rows with free text → left as-is, normalized at query time; unknown winding → execution_domain from the session default.

### REQ-19: Typed relationships — DER structure into the shared link store
**User Story:** As the memory I want parent/depends_on/sub-loop/failure-class links stored as typed relationships in the same link store the graph already uses, so "in reference to all other nodes" is a traversal, not a schema guess.
**Verified:** the mycelium pin_links mechanism exists with a controlled vocabulary (documents|references|implements|depends_on|contains|related_to over pin|landmark|episode|node) and is BFS-queried; the DER DAG shape lives only in RAM (QueueItem parent_step_id/depends_on/is_subloop) and never persists; no failure-class links exist.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL persist each DER node's structural relationships (parent / depends_on / sub-loop containment) as typed links in the shared link store.
- AC2: THE SYSTEM SHALL extend the link vocabulary with derives_from | part_of | relevant_to | failed_like for DER-specific structure.
- AC2b (VOCABULARY HYGIENE — ambiguity is how a link store rots): the extended set collides with the existing one in two places and MUST be disambiguated in the REQ-22 ontology doc BEFORE first write, with one-line rules an implementer cannot misread:
  * `related_to` (existing) vs `relevant_to` (new) — near-synonyms that different call sites will otherwise use interchangeably. Either define a hard distinction (recommend: `related_to` = semantic similarity discovered by scoring; `relevant_to` = surfaced as a candidate to a decision per REQ-5 AC1) or drop one. Two words for one idea guarantees drift.
  * `contains` (existing) vs `part_of` (new) are INVERSES. THE SYSTEM SHALL declare ONE canonical direction and write only that direction, deriving the inverse at query time. Writing both doubles the edges and lets the two disagree.
  THE SYSTEM SHALL reject (log + drop) any link whose predicate is outside the declared vocabulary, so drift fails loudly rather than accumulating.
- AC3: WHEN a node finalizes FAILED THEN THE SYSTEM SHALL link it via failed_like to prior failed nodes sharing the failure class so AVOID recall is a graph walk.
- AC4: REQ-5 coupling edges SHALL land in the same store — no second edge store.
**Edge Cases:** empty store; root node (no parent) → no parent link; link target missing → drop the link, keep the node write, log once; failed_like with no prior failure → skipped.

### REQ-20: Ontology-aware recall — domain/type/relationship filters
**User Story:** As DER I want every recall path filterable by node type, domain, and relationship so memory returns the relevant neighborhood instead of the whole graph.
**Verified:** no filter exists on any recall query — mid-loop episodic hints (agent_kernel.py:5826–5931), AVOID/proven-path, recall_decoder top1/predicted-next (interface.py:464); ranking is vector-similarity only.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL apply node-type, domain (both axes), and relationship filters to episodic hint, AVOID, proven-path, and chain recall.
- AC1b (CROSS-CONVERSATION BY DEFAULT — resolves OQ-2): recall SHALL span conversations and sessions, not just the current thread. The store is one shared cross-conversation memory keyed into Immortus's 4D time layer; a node written months ago is a legitimate candidate if it survives Kyudo decay. Thread/session are RANKING inputs (recency, provenance), never a hard pre-filter that hides older branches — hiding them would defeat REQ-5 AC1, which requires the agent to SEE the alternatives.
- AC2: WHEN a filtered query returns zero rows THEN THE SYSTEM SHALL widen the scope one level at a time (drop relationship, then type, then domain) and log the scope that succeeded — never silently return zero.
- AC2b (AGE IS A RANKING INPUT — the 4D axis must actually be used): recall spans months by design, and Kyudo decay (not write-time curation) is what removes what stops earning its place. Ranking SHALL therefore include node age and the node's current decay/score standing alongside similarity — a year-old node that survived decay has EARNED its rank and must be reachable, while a recent node is not automatically better. Age SHALL NOT be a hard cutoff (that would hide the older branches REQ-5 AC1 requires the agent to see). Without this the ontology stores time but never reads it, and the 4D layer becomes decoration.
- AC3: THE SYSTEM SHALL feed the filtered neighborhood into the step context (REQ-3) as the relevant neighbor records.
**Edge Cases:** no filter → all-scope query (today's behavior preserved); filter over empty memory → widened to the live-state fallback; unknown relationship value → treated as no relationship (widen).

### REQ-21: Per-domain physics aggregation — the signal gains a semantic axis
**User Story:** As the tuner I want avg |u|, oscillation/convergence rate, and split/collapse counts per domain so I can read which domains oscillate and which converge — the physics becomes parseable, not noise.
**Verified:** no aggregation exists anywhere; caducean_trajectory rows are flat with free-text domain; detect_physics_narration reads only the current u/ξ (der_constants.py:341–395); outer_loop per-domain gating is half-dormant (no production call sites).
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL aggregate avg |u|, oscillation rate, convergence rate, and split/collapse counts per execution_domain (and per topic_domain) per session.
- AC2: THE SYSTEM SHALL expose the aggregates as a read-only signal consumed by the outer loop (REQ-16) and the narration tuning gate (REQ-15).
- AC3: THE SYSTEM SHALL compute the aggregation off the hot path (batched/lossy-safe), consistent with REQ-14/REQ-17.
**Edge Cases:** one-sample domain → reported with n=1; no rows → absent, not zero; aggregation failure → skipped, never errors the turn.

### REQ-22: Ontology doc + read-only schema surface
**User Story:** As any agent using this application I want a stable ontology reference (node types, domain registries, relationship vocabulary, recall filters) that is version-checked against the live schema, so memory is trustworthy without reading source.
**Verified:** no agent-facing schema doc or query surface exists; the ontology lives implicitly in code (spaces.py DOMAIN_IDS, pin_links schema, extractor.py:187–193 keyword patterns).
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL ship an ontology document (specs/der-dag-inversion/ontology.md) listing node types, both domain registries, the link vocabulary, and the recall filters — the canonical reference for any agent.
- AC2: THE SYSTEM SHALL version-check the doc against the live schema in CI so drift fails loudly, never silently.
- AC3: THE SYSTEM SHALL (follow-on, OQ-4) expose a read-only query surface (endpoints or MCP tool) for node, relationship, and aggregate queries.
**Edge Cases:** schema drift → CI flag with file:line; doc stale → flagged, not corrected silently; surface absent (OQ-4) → doc remains the canonical reference.

### REQ-23: The causal triple — record the MEDIATOR, not just the state and the outcome
**User Story:** As the memory I want every node to record WHAT THE AGENT DID alongside where it was and what happened, so the graph can learn which action works in which state instead of only that something worked.
**Verified:** `NodeRecord` (der_loop.py, built in Wave 1 T8) carries objective_anchor (Treatment), outcome + verified_fraction (Outcome), and coords_from/coords_to (Confounder state Σ) — but has NO field for the tool/action chosen. The causal chain is therefore incomplete: the store can answer "was I converging when this succeeded" but NOT "which action succeeded here". Meanwhile the mechanism that would consume it ALREADY EXISTS and is coordinate-aware: mycelium `scorer.py` splits a node when outbound hit/miss variance crosses threshold, moving the halves toward `hit_center` / `miss_center` COORDINATES (:326–342), and condenses by coordinate distance (:246–300). DER's tool choices never reach it.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL record on every node the MEDIATOR it used — the resolved tool/action identifier plus a stable hash of its arguments — as a first-class field, written at the same finalize point as `outcome`.
- AC2: THE SYSTEM SHALL carry the mediator onto the `memory_chain` row so the causal triple (Treatment → Mediator → Outcome) is queryable together with the Σ coordinates that were in force.
- AC3: THE SYSTEM SHALL feed mediator hit/miss outcomes into the EXISTING coordinate-scoped mycelium scorer rather than building a parallel scoring path — the same edge whose score is being updated must be the one recall later reads (REQ-19 AC4: one store).
- AC4: THE SYSTEM SHALL make "which mediators were tried for this objective, and how did each fare by coordinate region" answerable as a query, so a repeated mediator failure becomes visible as evidence instead of being rediscovered.
- AC5: A node with NO mediator (a pure decision or synthesis node) SHALL record that explicitly rather than leaving the field empty — absent and "none" must be distinguishable, or the ranking silently treats decisions as failed actions.
**Edge Cases:** tool resolved but never executed (record the attempt with an explicit not-executed outcome); the same mediator with materially different arguments (the args hash is what separates them); mediator chosen by fallback rather than by the predictor (record which, or the learning credits the wrong chooser); batched children sharing one call (REQ-7) → each child records its own mediator.
**WHY THIS IS URGENT AND NOT A WAVE-5 ITEM:** `NodeRecord` was created in Wave 1 and nodes are landing NOW. Adding a field before history accumulates is trivial; back-filling a mediator onto months of rows is impossible — the information was never captured. This is the same asymmetry that decided OQ-7.

### REQ-24: Execution steps forward, memory couples outward — contract-locked
**User Story:** As the loop I want the forward-only property that already holds to be pinned, so a future "recovery" change cannot quietly reintroduce reverse-looping.
**Verified:** no reset-to-PENDING exists anywhere in der_loop.py or agent_kernel.py (grep returns nothing) — recovery already spawns FORWARD children with nested ids (observed live: `s2_s0`, `s2_s1`, then `s2_s0_s0`, `s2_s1_s2`). The property is TRUE TODAY; it is simply unprotected.
**Acceptance Criteria:**
- AC1: A node that reaches a terminal state (VERIFIED / UNVERIFIED / FAILED) SHALL be immutable — recovery creates a NEW node with an edge from the frozen one, never mutates or re-queues the original.
- AC2: A contract test SHALL assert this, so the guarantee survives future recovery work.
- AC3: THE SYSTEM SHALL NOT add cycle-detection machinery or a redesign for this — the property holds; this requirement locks it.
**Edge Cases:** graft/split recovery (already forward); steering resume after pause (must resume the queue, not revive a terminal node); replay harnesses that reconstruct historical nodes (read-only, not a mutation).
**NOTE — DIAGNOSTIC CORRECTION:** the framing that infinite splitting was caused by "the execution DAG trying to do the memory DAG's job" is NOT what was measured on this system. The observed cause of `Token budget exhausted (4054/4000)` was the context window collapsing 256k→8192 (REQ-1), which set the budget to the 4000 floor; splitting then AMPLIFIED a budget that was already 23x too small. REQ-1 is the fix; this requirement is a guard, not a repair.

## Non-Requirements (Out of Scope)
- No UI changes for narration (ambient audio only — locked).
- No AIMD ceiling changes (REQ-9 AC2 — locked).
- No enabling of the phase manager as a rate fix (timing-only; locked — may be revisited separately).
- No new ML models or embeddings; no new dependencies.
- No rewrite of the frontend app shell or the TTS playback path (word-highlight, orb, envelope unchanged).
- No change to structured_response speak/show contract semantics (the response-path spoken ⊆ visible invariant stays).
- No removal of the work-unit resource or the split caps (DER_MAX_GRAFTS=3, MAX_DEPTH=3) — D6 is verified already capped; it becomes a contract-lock, not a redesign.
- No new edge store — DER relationships reuse the existing mycelium link store, extended (REQ-19).
- No free-text domains — both domain axes are registry-backed; unknown resolves to general/unknown, logged (REQ-18).

## Open Questions
- **OQ-1 (REQ-15 gate):** After the measurement wave, retune bands from observed |u| OR add explicit task-complete/phase-transition ambient lines? (User decides; recorded in Decisions Locked.)
- **OQ-2 (REQ-5): RESOLVED — cross-conversation from the start.** The store is one shared memory across every conversation; Immortus labels conversation ids, events, and content into a 4D time layer so recall reaches back months, and Kyudo decay (not write-time curation) removes what stops earning its place. Within-session-first was the wrong recommendation: it would hide exactly the older branches REQ-5 AC1 requires the agent to see. Recorded in Decisions Locked; REQ-20 AC1b carries the requirement.
- **OQ-5 (REQ-2 AC4): RESOLVED — DROP `memory_chain_v2`.** User decision. 0 rows in every database, no writer anywhere; a third empty shape only guarantees a future agent writes to the wrong table. The drop is recorded in T6 and is non-destructive (no data exists to lose).
- **OQ-6 (REQ-3 AC5): RESOLVED — derive the per-step working-context bound from the REQ-1 resolved window.** User decision: no literal constant. A hardcoded bound here would re-create exactly the failure REQ-1 exists to fix (the 8192 default that collapsed the budget to 4000). The bound scales with the model actually bound.
- **OQ-7 (REQ-18 AC1b): RESOLVED — boolean flag for now.** User decision: mark whether a node COMMITTED A DECISION (a valid coupling endpoint per REQ-5 AC2); do not introduce a role enum in this pass. Rationale recorded for the future agent: a richer role vocabulary (decide | retrieve | execute | synthesize) is a known follow-on that will need addressing once REQ-20's filters are exercised against real recall — the boolean is deliberately the extensible floor, NOT a judgement that roles do not matter. Adding a value later is cheap; re-typing months of historical nodes is not, which is why the narrow choice is the safe one to write first.
- **OQ-8 (REQ-18 AC1c / REQ-19 AC2b) NEW:** if the 13-domain registry proves too coarse (modal domain dominates), do we subdivide the registry or accept low topic discrimination and lean on coordinate proximity instead? (Recommend: measure first per AC1c; do NOT pre-emptively expand the registry — a wider vocabulary nobody populates correctly is worse than a narrow one.)
- **OQ-3 (REQ-7):** Should layer-batched execution replace the per-child ToolDecisionBox resolve for sub-loop children only, or also for independent sibling steps of the main plan? (Recommend: sub-loop children first — bounded, same join-point semantics.)
- **OQ-4 (REQ-22):** Should the read-only agent-facing query surface (endpoints / MCP tool for node, relationship, and aggregate queries) ship in this pass or follow once the doc proves stable? (Recommend: follow-on — doc + CI version check first.)
