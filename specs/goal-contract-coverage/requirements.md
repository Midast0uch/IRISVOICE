# Requirements: Goal Contract & DAG Coverage

## Decisions Locked
- (User, session-327) The goal contract is the **task node's record**, not a new layer, table, or store. It fits the existing DAG DER: required facts are the task node's expected outputs; coverage is the task node's `verified_fraction`.
- (User, session-327) **Determinism in the goal and progress layer. Freedom in the tool and strategy layer.** The model decides *which tool, which URL, which wording*. Code decides *what "done" means and whether we are there*.
- (User, session-327) The contract **starts deterministic and becomes mutable**: the user may steer the live goal, and the agent may discover more. Mutability adjusts scope (larger or smaller) and never loses the goal.
- (User, session-327) The **floor (required facts) is immutable to the agent**. The agent may resolve a fact or block it with evidence; it may never delete one. Only the user may add, remove, or repromote a floor fact.
- (User, session-327) The **ceiling (discovered facts) never blocks completion**. Exceeding expectations is bounded by remaining budget.
- (User, session-327) **Physics over gated logic.** The completion signal must be a continuous function of recorded state, so failures are visible in a formula rather than hidden behind a boolean. This is the repository's own rule: *prefer a continuous function of the physics signal over a threshold* (`specs/der-dag-inversion/design.md` §5, §10.2).
- (User, session-327) The **Caducean phase model is the shared scheduling state**. It governs *when and how much* work is admitted. It must stay orthogonal to the goal state — it SHALL NOT read coverage, required facts, or reasoning state (`docs/CADUCEAN_CONCURRENCY_MODEL.md` §5).
- (User, session-327) `required_facts: list[str]` is a **new bounded field on `NodeRecord`**; `expected_output` stays the human-readable summary. (User confirmed the field choice.)
- (User, session-327) These are **layers that must work together**. Over-build caution does not apply here.
- (User, session-326 prior) The same request may end in different ways because the loop ends when the **step queue empties**, not when the **goal is met**. The gap is the missing detail this spec closes.
- (User, session-327) **Speed becomes accuracy.** The target is coverage gained per unit of work (`dC/ds`), not raw speed. A step that cannot produce progress must fail fast; a step that is slow but still progressing must be allowed to run. The stall signal is a **rate**, not a count — `GOAL_STALL_N` is retired in favour of `GOAL_STALL_RATE`.
- (User, session-327) **A step that cannot run must fail fast with a typed reason, never hang.** The dispatch path must detect an un-attendable approval before it waits. (The permission matrix itself is changed by the decision below.)
- (User, session-327) The domains the agent executes across are **vast**. No requirement may tailor behaviour to a specific tool or a specific task shape; capability advertisement and fail-fast are general properties.
- (User, session-327) **Writes auto-approve in both modes; only destructive and the always-ask terminal/system set stay gated.** The tier matrix changes: `developer` SIDE_EFFECT moves from require-approval to auto-approve. The always-ask set — `run_command` (shell), `read_shell_output`, `gui_automate_*`, `lock_screen`, `shutdown`, `restart` — is a **separate capability gate** and stays gated, because shell is arbitrary code execution. REQ-9 makes a gated step fail fast and reroute, so the agent still progresses.

## Phase-Layer Taxonomy (stated distinction — do not merge these)

The codebase already carries **three distinct phase-bearing layers**. They are the same *kind* of mechanism at different scales. They are **not** the same state, and the scheduler is deliberately decoupled from the others.

| Layer | State it carries | Question it answers | Code | Status |
|---|---|---|---|---|
| **Cognitive** | 4D `(x, y, ξ, u)` | What state is this reasoning in? | `caducean_trajectory.py` recorder; DER reads `U_SPLIT`/`U_CONVERGED` on `|u|` (`backend/agent/der_constants.py:233,246`) | LIVE |
| **Scheduler** | 1D angle `θ` + amplitude `r` | When may this call fire, and how much? | `backend/agent/phase_manager.py` `PhaseOscillator` | LIVE |
| **Cross-session coupling** | per-session `ξ` + params | Are two sessions resonating? | `backend/agent/coupled_registry.py` | OFF |

`backend/agent/trig_coupling.py` is the shared pure-math kernel used by the scheduler and coupling layers. It carries no state.

**How this spec relates to the layers:**
- The goal contract adds **no new phase layer**. It adds a **forcing input to the existing cognitive layer** — the gap `g` drives `u`. Coverage `C` is read by the existing DER steering (`_der_split_width`, `_der_verify_strictness`). Both already consume `u`.
- The goal contract **does not touch the scheduler layer** (REQ-6).
- The layers are different dimensional systems, but they are **not all coupled**. The scheduler must not read the cognitive or goal state (`docs/CADUCEAN_CONCURRENCY_MODEL.md` §5; CT-3/CT-4). "Working together" means parallel governance over different questions, never shared state.

## Introduction
The agent's turn currently ends when its step queue is empty, not when the user's request is satisfied. Four independent LLM decision points (plan, tool resolve, URL generation, synthesis) each decide alone, with no shared goal state, so the same prompt produced five different outcomes in live testing (D3 thin, D7 total failure, D8 stub, D9 and D10 good). The tool-result-envelope spec built the substrate — a per-step `match` label and a `verified_fraction`. This spec wires that substrate into a **goal contract on the task node** and makes **coverage a continuous signal** the existing physics already knows how to consume. The agent then drives itself toward the goal using its tools, and stops on convergence rather than on an empty queue.

### Success criteria
- A request with N explicit deliverables produces a required-fact set of N. A planner that omits one is corrected by a deterministic validator; the omitted fact still appears in the set. (Baseline: live D3 dropped 3 of 4 asks, `temp/d3_reply.json`.)
- The same probe that varied 5 ways across D3/D7/D8/D9/D10 produces the **same terminal coverage** — every required fact either covered or explicitly named as blocked. Target: 0 silent omissions on 5 consecutive runs.
- Terminal `C` (coverage) is measurable in the log for every run: `C`, `g = 1 − C`, covered/required counts, blocked facts.
- A run with an uncovered, unblocked required fact does NOT report `pass`. (Baseline: live D7 total failure graded `pass (failure-settled)`, `.iris-logs/backend-20260911-180259.log:1191`.)
- The task node's `verified_fraction` moves when coverage moves; a stalled `C` across N settled nodes is detectable from the log alone.
- The phase manager consumes no goal signal: a contract test proves the scheduler never reads coverage/required facts (extends CT-3 of the concurrency model).
- Mean live turn time does not increase by more than 10% on a non-research task (the contract must not add work to simple turns). Target UNVERIFIED pending live measurement.
- Coverage gained per unit work (`dC/ds`) is measurable in the log for every run, and the idling trigger fires on no-progress (`ρ < GOAL_STALL_RATE`) rather than on a fixed step count.
- A step whose chosen tool cannot run settles within 1 second with a typed reason — no hang. (Baseline: D1/D11 hung 162 s, `.iris-logs/backend-20260911-180259.log:1190`.)

## Requirements

### REQ-1: The task node carries the required-fact set
**User Story:** As the agent I want the user's request decomposed into explicit required facts so that no asked part is silently dropped.

**Verified:** REAL GAP — `NodeRecord` (`backend/agent/der_loop.py:74-189`) carries `expected_output: str` (single string, `der_loop.py:108`) and `verified_fraction` (`der_loop.py:115`) but no fact set. The planner produces `step.expected_output` per step (`backend/agent/agent_kernel.py:8264`); nothing aggregates them to the task. `_der_findings_sufficient` (`agent_kernel.py:12552`) asks a model whether findings suffice, but it is advisory and single-shot.

**Acceptance Criteria:**
- AC1.1: WHEN a task begins THEN THE SYSTEM SHALL derive a required-fact set from the user request by deterministic extraction — explicit deliverables, numeric counts ("three features"), and enumerated asks — with zero LLM calls.
- AC1.2: WHEN the planner produces steps THEN THE SYSTEM SHALL map each deterministically-extracted fact to at least one step's `expected_output`.
- AC1.3: IF the planner omits a deterministically-extracted fact THEN THE SYSTEM SHALL re-add that fact to the required set and log the omission with the fact text.
- AC1.4: THE SYSTEM SHALL store the required set as a bounded `required_facts: list[str]` field on the task node's `NodeRecord`; `expected_output` SHALL remain the human-readable summary.
- AC1.5: THE SYSTEM SHALL cap the required set at a constant (`GOAL_REQUIRED_FACTS_CAP`) and mark truncation explicitly when the cap is hit.
- AC1.6: IF the request contains no deterministically-extractable deliverable THEN THE SYSTEM SHALL fall back to a single required fact equal to the request summary, and log that the fallback fired.

**Edge Cases:**
- Empty request → the fallback fact is the empty summary; the task node records it and the answer is a direct reply.
- Planner unavailable/timeout → the deterministic set stands alone; no fact is lost.
- Duplicate extracted facts → deduplicated by normalized text before the cap.

### REQ-2: Coverage is the task node's verified_fraction
**User Story:** As the loop I want one continuous number for "how much of the goal is covered" so that steering reads a formula, not a boolean.

**Verified:** Substrate exists — `_verified_fraction` (`agent_kernel.py:14381`) already returns a continuous 0..1; `NodeRecord.verified_fraction` (`der_loop.py:115`) already carries it; `_verify_step_result` (`agent_kernel.py:14405`) already performs goal-subject alignment and returns UNVERIFIED on a goal miss (`:14472-14479`).

**Acceptance Criteria:**
- AC2.1: THE SYSTEM SHALL compute coverage `C = |covered required facts| / |required facts|`, a continuous value in [0, 1].
- AC2.2: WHEN a child node settles THEN THE SYSTEM SHALL mark a required fact covered only if the child's outcome is VERIFIED AND the fact's distinctive terms appear in the child's result — a deterministic check reusing the existing goal-subject alignment path.
- AC2.3: THE SYSTEM SHALL stamp `C` onto the task node's `verified_fraction`.
- AC2.4: THE SYSTEM SHALL compute `C` deterministically — O(required facts), zero LLM calls, no new encode, no new DB write.
- AC2.5: IF a fact is covered by more than one child THEN THE SYSTEM SHALL count it exactly once (set union, not sum).

**Edge Cases:**
- Required set empty → `C = 1.0` (nothing asked, nothing open); logged as a degenerate contract.
- A child VERIFIED with an empty result → the fact is NOT covered (the deterministic term check fails).
- A required fact with no distinctive terms → covered by VERIFIED status alone, logged as a weak check.

### REQ-3: The gap drives the loop; termination is convergence
**User Story:** As the owner I want the agent to keep working while a required fact is open and stop when the physics converges — not when the queue happens to empty.

**Verified:** REAL GAP — the loop terminates on queue exhaustion. `_der_plan_next_step` (`agent_kernel.py:16305`) answers bare `done true/false`; `_der_check_full_progress` (`agent_kernel.py:16433`) logs drift but explicitly "not automatically applied" (`:16481-16482`). The graded-steering consumers exist but read a per-step fraction only: `_der_split_width` (`:11555`), `_der_verify_strictness` (`:11941`), `_growth_width` (`:11531`).

**Acceptance Criteria:**
- AC3.1: THE SYSTEM SHALL compute the goal gap `g = 1 − C`.
- AC3.2: WHILE `g > 0` AND a required fact is open AND work is admissible THEN THE SYSTEM SHALL request further work (graft, recovery, or replan) rather than finalize.
- AC3.3: THE SYSTEM SHALL feed `C` into the existing graded-steering functions at the task level, so the split width and verification strictness are continuous functions of coverage as well as `|u|`.
- AC3.4: THE SYSTEM SHALL compute a dimensionless progress ratio `ρ = ΔC / (g · Δs)` (ΔC = coverage gained this cycle, Δs = work spent this cycle) and SHALL classify the run as idling WHEN `ρ < GOAL_STALL_RATE`, then trigger `try_different`/replan; the existing idling shape in `evaluate_streak` (`backend/agent/tool_envelope.py:910`) consumes this signal. Patience therefore shrinks as the gap grows — fail on no-progress, never on slowness.
- AC3.5: WHEN `C` reaches 1.0 THEN THE SYSTEM SHALL permit one bounded bonus pass over ceiling facts, then terminate.
- AC3.6: THE SYSTEM SHALL NOT terminate a turn while a required fact is open and unblocked AND work remains admissible.

**Edge Cases:**
- Budget exhausted with facts open → terminate with those facts named (REQ-5), never a silent stop.
- Phase gate denies all work → the turn settles on the current `C` and names what is open; scheduling failure never becomes a false pass.
- Required set degenerate (`C=1.0` at start) → no work requested; direct reply.

### REQ-4: Mutation protocol — floor protected, ceiling free, forward-only
**User Story:** As the user I want to steer the live goal and have the agent find more, without either of us losing the original goal or silently lowering the bar.

**Verified:** Substrate exists — user steering is handled by `_der_check_steering` (`agent_kernel.py:9883`) and `_der_apply_steering` (`:10447`); graph amendment by `_der_amend_graph` (`:10634`); forward-only edges are written by `DerLinkWriter` (`backend/agent/der_links.py:41`, `derives_from` at `:14`). The mutation protocol is NOT wired to a goal contract because none exists.

**Acceptance Criteria:**
- AC4.1: WHEN the user sends a steering prompt mid-run THEN THE SYSTEM SHALL amend the task node's required set in place — add, remove, or repromote a floor fact — without creating a second task.
- AC4.2: THE SYSTEM SHALL allow the agent to ADD ceiling facts, bounded by `GOAL_CEILING_CAP`.
- AC4.3: THE SYSTEM SHALL NOT allow the agent to remove or demote a floor fact.
- AC4.4: WHEN scope shrinks THEN THE SYSTEM SHALL recompute `C` against the new denominator, so `C` rises.
- AC4.5: WHEN scope grows THEN THE SYSTEM SHALL recompute `C` against the new denominator, so `C` drops.
- AC4.6: THE SYSTEM SHALL record every amendment as a forward node with `derives_from` to the prior contract state, carrying who, when, and why.
- AC4.7: THE SYSTEM SHALL preserve the task node's identity across amendments — the goal is amended, never lost.

**Edge Cases:**
- User removes the last floor fact → `C` becomes 1.0 (degenerate), logged; the turn finalizes on the current findings.
- Agent proposes a ceiling fact identical to a floor fact → deduplicated, no double count.
- Amendment arrives after the turn finalized → recorded as a new turn; never applied retroactively.

### REQ-5: Blocked facts carry a typed reason and are named
**User Story:** As the user I want every part of my request either answered or named as blocked, never silently dropped.

**Verified:** Substrate exists — typed reasons in `backend/agent/nodes/outcome.py:40-76` (`Reason`, `TERMINAL_REASONS`); the failure explanation path `_der_deterministic_failure_summary` (`agent_kernel.py:12844`). But blocking does not currently feed a coverage denominator, and the stub guard is a character count (`:12812`, `:12723`), not a fact check.

**Acceptance Criteria:**
- AC5.1: WHEN a required fact cannot be covered (tool exhausted, terminal `Reason`, budget) THEN THE SYSTEM SHALL mark it blocked with a typed `Reason` from the closed vocabulary.
- AC5.2: THE SYSTEM SHALL keep a blocked fact in the denominator — blocking SHALL NOT raise `C`.
- AC5.3: WHEN the final answer is produced THEN THE SYSTEM SHALL name every blocked fact explicitly.
- AC5.4: IF the synthesized answer omits a blocked fact THEN THE SYSTEM SHALL replace it with the deterministic summary that names every blocked fact.

**Edge Cases:**
- All facts blocked → the answer is the deterministic blocked-fact summary; grade is capped, never pass.
- A terminal `Reason` (ROBOTS_REFUSED, PERMISSION_DENIED) → blocked and never retried.

### REQ-6: Caducean phase model as the shared scheduling state
**User Story:** As the system I want one shared scheduling state for all model calls so that concurrent work does not collide or exceed the provider, without the scheduler reading the goal.

**Verified:** Substrate exists — the phase gate is live at `backend/agent/inference/router.py:977-980` (`acquire(...)`, imported `:45` from `phase_manager`); status documented in `docs/CADUCEAN_CONCURRENCY_MODEL.md` §4, §6 (`IRIS_PHASE_SCHEDULER=1`); the one-rule contract in §5 forbids the scheduler reading correlated reasoning state, pinned by CT-3/CT-4/CU-1.

**Acceptance Criteria:**
- AC6.1: THE SYSTEM SHALL use the Caducean phase manager as the single shared scheduling state for all model calls, reached only through the `InferenceRouter.generate()` chokepoint.
- AC6.2: THE SYSTEM SHALL keep the phase manager orthogonal to goal state — it SHALL NOT read coverage, required facts, blocked facts, or reasoning state.
- AC6.3: THE SYSTEM SHALL AND the two gates: the goal state requests work; the phase gate admits work. Neither gate SHALL imply the other.
- AC6.4: IF the phase manager fails THEN THE SYSTEM SHALL degrade to admitting the call (no scheduling), never to an outage, and log the degradation.

**Edge Cases:**
- Phase manager absent (flag off) → behavior identical to today; goal coverage still enforced.
- Priority lane (USER_TURN, SPEAK) → hard bypass preserved (`wait = 0`); the goal contract does not affect it.

### REQ-7: Observability
**User Story:** As the tuner I want `C`, `g`, stalls, blocked facts, and amendments in the log so I can tune the contract from measurement.

**Verified:** NEW — extends the counters convention (tool-result-envelope REQ-7/REQ-12).

**Acceptance Criteria:**
- AC7.1: THE SYSTEM SHALL log per settled node: `C`, `g`, covered count, required count, and the blocked-fact list.
- AC7.2: THE SYSTEM SHALL count: facts seeded, facts mapped by planner, facts re-added by the validator, facts covered, facts blocked, amendments by source (user | agent), coverage stalls, bonus passes.
- AC7.3: THE SYSTEM SHALL log each amendment with who, when, and why.
- AC7.4: Every counter this spec introduces SHALL name its reader, or it SHALL be dropped.

**Edge Cases:**
- High-volume logging → per-node lines at debug, coverage/stall/blocked at info; never inside the dispatch critical section.
- Log failure → never propagates; the turn is unaffected.

### REQ-8: Run grade from coverage
**User Story:** As the owner I want the run grade to reflect whether the goal was covered, so a failed run cannot report pass.

**Verified:** DEFECT — `evaluate_run_grade` (`tool_envelope.py:969`) reads step envelopes; a failed step produces no envelope, so D7's total failure graded `pass (failure-settled)` (`.iris-logs/backend-20260911-180259.log:1191`). `_der_report_run_grade` (`agent_kernel.py:5679`) filters `None` envelopes (`:5692-5698`).

**Acceptance Criteria:**
- AC8.1: WHEN the run completes THEN THE SYSTEM SHALL compute the grade from coverage: `C = 1.0` with no blocked fact → pass; `C < 1.0` with every open fact blocked and named → partial/capped; any required fact open and unblocked → capped below pass.
- AC8.2: THE SYSTEM SHALL report `done + grade + blocked-fact list` on every terminal path.
- AC8.3: THE SYSTEM SHALL NOT report pass when a required fact is open and unblocked.

**Edge Cases:**
- Coverage computation fails → grade is `unavailable`, logged, never silently pass.
- Degenerate contract (`C=1.0` at start) → pass is legitimate; logged as degenerate.

### REQ-9: Fail fast on un-runnable steps
**User Story:** As the owner I want a step that cannot run to settle immediately with a typed reason, so budget is never burned on a hang and the loop can reroute or name the gap.

**Verified:** REAL GAP — D1/D11: `run_command` (tier `side_effect`, `backend/agent/permissions.py:160`) required approval, no approval UI was attached, and the step hung 162 s then crashed with `error=''` (`.iris-logs/backend-20260911-180259.log:1190`). The permission matrix is `get_permission_action` (`permissions.py:348-369`); the wait is `PERMISSION_TIMEOUT_SIDE_EFFECT = 120` (`permissions.py:44`). The typed vocabulary exists in `backend/agent/nodes/outcome.py:40-76` but has no member for "no one was there to approve."

**Acceptance Criteria:**
- AC9.1: WHEN a chosen tool cannot run (approval unavailable, missing capability, or terminal reason) THEN THE SYSTEM SHALL settle the step immediately with a typed `Reason`, without waiting for the permission timeout.
- AC9.2: THE SYSTEM SHALL add `APPROVAL_UNAVAILABLE` to the closed `Reason` vocabulary, distinct from `PERMISSION_DENIED` (policy refused) and `UNAVAILABLE` (backing service absent).
- AC9.3: WHEN a step settles `APPROVAL_UNAVAILABLE` THEN THE SYSTEM SHALL reroute to an available alternative or mark the required fact blocked — never hang.
- AC9.4: THE SYSTEM SHALL change the tier matrix so read and write tools (READ_ONLY, SIDE_EFFECT) auto-approve in BOTH modes; DESTRUCTIVE tools stay gated. The always-ask terminal/system set (`run_command`, `read_shell_output`, `gui_automate_*`, `lock_screen`, `shutdown`, `restart`) SHALL remain gated as a separate capability boundary.
- AC9.5: WHEN no approval UI is attached to the session THEN THE SYSTEM SHALL detect it before dispatch (using the existing live WebSocket client presence for the session) and fail fast; WHEN an approval UI is attached THEN THE SYSTEM SHALL keep the existing approval flow unchanged.

**Edge Cases:**
- Approval UI attached → normal approval flow, unchanged.
- Backing service absent (MCP down) → `UNAVAILABLE` status, not `APPROVAL_UNAVAILABLE`.
- Tool is destructive and the user denies → `PERMISSION_DENIED`, terminal, never retried.

### REQ-10: Phase-layer separation
**User Story:** As the system I want the goal contract to use the existing cognitive layer and add no new phase layer, so the three phase systems stay distinct and the scheduler stays de-correlated.

**Verified:** REAL DISTINCTION — three layers exist: cognitive 4D `(x,y,ξ,u)` (`backend/agent/caducean_trajectory.py:1-14`), scheduler `θ`+amplitude (`backend/agent/phase_manager.py:1-30`), cross-session coupling (`backend/agent/coupled_registry.py:1-40`). The scheduler's contract locks forbid reading the cognitive layer: CT-3 (never calls `coupled_registry`), CT-4 (never calls `iris_ffi`) — `phase_manager.py:24-27`.

**Acceptance Criteria:**
- AC10.1: THE SYSTEM SHALL feed the goal gap `g` into the existing cognitive layer (`u`) and SHALL NOT introduce a new phase layer, state variable, or oscillator.
- AC10.2: THE SYSTEM SHALL NOT feed the goal state into the scheduler layer (`θ`/`r`); the scheduler SHALL remain de-correlated from the cognitive and goal state.
- AC10.3: THE SYSTEM SHALL keep the three layers named, distinct, and separately testable — a change to one SHALL NOT require a change to another's state.

**Edge Cases:**
- Scheduler flag off → the goal contract still works; coverage is enforced without scheduling.
- Coupling flag off (current) → no effect on the goal contract.
- A future layer is added → it must declare which question it answers and must not read a layer it is meant to de-correlate.

### REQ-11: Failure feeds the taxonomy and the learning loop
**User Story:** As the system I want every fail-fast and blocked step to teach the taxonomy and the learning loop, so a failure is never silent and the agent learns from it.

**Verified:** REAL GAP — FAULTLINE's choke point is `normalize_failure` at `ToolBridge.execute_tool()` (`backend/agent/tool_bridge.py:1183-1184`); the learning record is `_record_tool_event` (`tool_bridge.py:1799`, learning payload at `:1860`); the label registry is `register_error_label` (`backend/agent/tool_errors.py:92`); the causal scorer is `_der_score_step_outcome` (`agent_kernel.py:14607`) called from finalize (`:15406`) into `record_region_mediator_outcome` (`:14751`); failure-class links are `DerLinkWriter.link_failed_like` (`backend/agent/der_links.py:258`). A PRE-dispatch fail-fast short-circuits before `execute_tool`, so it bypasses all of these today. FAULTLINE §11: "a taxonomy without a consumer is decoration."

**Acceptance Criteria:**
- AC11.1: WHEN a step fails fast or is blocked THEN THE SYSTEM SHALL emit the FAULTLINE canonical shape (`success`, `error`, `error_type`, `retryable`, `blame`, `info_state`, `details.raw`, `ts`) even though it short-circuits before `execute_tool`.
- AC11.2: THE SYSTEM SHALL register `APPROVAL_UNAVAILABLE` as a FAULTLINE Layer-2 label via `register_error_label` (a DATA edit, never a new branch), seeded with dimensions (retryable=maybe, blame=world, info_state=blocked).
- AC11.3: WHEN a step fails fast or is blocked THEN THE SYSTEM SHALL feed `_record_tool_event` so the failure is recallable by cause.
- AC11.4: WHEN a step fails fast or is blocked THEN THE SYSTEM SHALL feed the DER reviewer's `verified_label` path → `task:learning` → memoryRegistry, and the causal scorer (`record_region_mediator_outcome`).
- AC11.5: WHEN a step fails fast or is blocked THEN THE SYSTEM SHALL feed `DerLinkWriter.link_failed_like` so the failure-class graph walk works.
- AC11.6: Every FAULTLINE dimension this spec adds SHALL name the dispatch/planning site that reads it (FAULTLINE §11).

**Edge Cases:**
- FAULTLINE registry unavailable → the failure still settles; the learning hook is best-effort and logged, never blocking.
- A blocked fact later covered → the learning record keeps the failure; coverage rises independently.
- A fail-fast with no mediator (pre-dispatch) → the mediator records "none" explicitly, never empty.

### REQ-12: Frontend contracts
**User Story:** As the user I want the approval UI and the mode toggle to keep working, and a fail-fast to show honestly, without a new frontend component.

**Verified:** Substrate exists — `components/chat/PermissionCard.tsx` (inline approval UI), `components/chat/PermissionsSettingsCard.tsx` (`PermissionMode = "personal" | "developer"`, `:9`), `hooks/useIRISWebSocket.ts:1705-1719` (forwards `permission:request/granted/denied`). The backend already tracks live WS clients (`agent_kernel.py:8396 _session_has_client`).

**Acceptance Criteria:**
- AC12.1: THE SYSTEM SHALL derive "approval UI attached" from the existing live WebSocket client presence for the session; no new frontend signal SHALL be introduced.
- AC12.2: THE frontend SHALL render `Reason.APPROVAL_UNAVAILABLE` as an honest permission condition through the existing `PermissionCard` / failure rendering path, not as a generic error.
- AC12.3: The existing `personal`/`developer` mode toggle SHALL remain the authority for capability (terminal/repo access); no new toggle SHALL be introduced. The toggle no longer gates simple writes (AC9.4).

**Edge Cases:**
- WS client disconnects mid-approval → the step settles `APPROVAL_UNAVAILABLE`; the card clears.
- Mode toggled mid-run → the next dispatch uses the new effective mode; in-flight steps are unchanged.

## Non-Requirements (Out of Scope)
- No new database, table, or store. The scoreboard is a read of the DAG; memory.db remains the durable record.
- No change to the tool-selection authority (`explorer.propose` stays the single resolver).
- No change to the Reviewer's verdict contract (PASS/REFINE/VETO semantics unchanged).
- No change to `expected_output`'s existing meaning; `required_facts` is additive.
- No re-implementation of the DAG node model, `NodeOutcome`, or `Reason` — this spec consumes them.
- No new frontend component. The frontend contracts (REQ-12) reuse the existing `PermissionCard` and the `personal`/`developer` mode toggle.
- No touching pre-existing test failures.
- No commit/push without explicit user approval.

## Open Questions
- (non-blocking) `GOAL_REQUIRED_FACTS_CAP`, `GOAL_CEILING_CAP`, `GOAL_STALL_RATE` start as constants in `der_constants.py` and are tuned from REQ-7 counters after the first live run.
- (non-blocking) The phase model's cycle rate and `GOAL_STALL_RATE` are tuned together: the objective is `dC/ds` (coverage per unit work), so the phase timing and the stall rate are one tuning problem, measured from the same counters.
- (non-blocking) Whether the deterministic extractor uses a rule list or a small grammar; decide from the first live run's extraction precision/recall.
- (non-blocking) Whether coverage should also gate the per-step split decision or only the task-level loop; tune from live `C` trajectories.
- (deferred) Card display of coverage (a progress bar or per-fact checkmarks) — separate presentation spec.
