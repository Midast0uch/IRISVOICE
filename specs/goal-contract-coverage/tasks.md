# Tasks: Goal Contract & DAG Coverage

> Each task links to a requirement. Waves are dependency-ordered. Wave 1 is pure and
> independent; Wave 2 wires it into the loop; Wave 3 adds mutation and grade; Wave 4
> pins scheduling orthogonality; Wave 5 verifies. Branch:
> `feat/agent-multi-step-tool-execution`. Backend must be restarted fresh for the live
> gate (a stale process does not carry new code).

## Wave 1 — Contract core (pure, no loop changes)
- [ ] T1 (REQ-1, REQ-2): Create `backend/agent/goal_contract.py` — `Contract`, `Coverage`, `extract_required` (rule-based, zero LLM), `map_to_steps` (returns omitted facts), `mark_coverage` (set-union; VERIFIED + term match), `amend` (floor protection), `add_ceiling` (capped), `is_blocked` (via `nodes/outcome.py`). Pure, deterministic, no I/O — `backend/agent/goal_contract.py` (NEW) — RIPPLE: `der_loop.py` NodeRecord (T2); constants (T3); unit tests (T12)
- [ ] T2 (REQ-1): Add five bounded fields to `NodeRecord` — `required_facts`, `ceiling_facts`, `covered_facts`, `blocked_facts`, `contract_version` — all additive with defaults; `expected_output` and `verified_fraction` unchanged — `backend/agent/der_loop.py:74-189` — RIPPLE: every existing `NodeRecord(...)` constructor stays valid (defaults); CT-GC1 pins the shape
- [ ] T3 (REQ-3, REQ-7): Add constants to `der_constants.py` — `GOAL_REQUIRED_FACTS_CAP`, `GOAL_CEILING_CAP`, `GOAL_STALL_RATE` (retires `GOAL_STALL_N`), `GOAL_FORCING_GAIN` (all UNVERIFIED starting points, tuned from counters) — `backend/agent/der_constants.py` — RIPPLE: T1/T5/T6 read them; no logic change elsewhere

## Wave 2 — Coverage wiring (the loop condition)
- [ ] T4 (REQ-1, REQ-2): Build the contract at plan start — `extract_required` on the request, `map_to_steps` against the plan, validator re-adds omitted facts (log each omission), stamp `required_facts` on the task node — `backend/agent/agent_kernel.py:8116 _execute_plan_der` — RIPPLE: planner prompt gains the fact set in view (no extra inference); CT-GC3 pins the re-add
- [ ] T5 (REQ-2, REQ-3): Mark coverage at finalize — `mark_coverage` from the settled node's outcome + result, stamp `C` onto the task node's `verified_fraction`, log `C`/`g`/covered/required — `backend/agent/agent_kernel.py:14829 _der_finalize_step` — RIPPLE: `_verify_step_result` (`:14405`) supplies the VERIFIED verdict; no new verify path
- [ ] T6 (REQ-3): Drive the loop from the gap — request work while `g > 0` and a fact is open and unblocked; feed `C` into `_der_split_width` (`:11555`) and `_der_verify_strictness` (`:11941`) at the task level; answer `done` from `C` in `_der_plan_next_step` (`:16305`); compute the progress ratio `ρ = ΔC / (g · Δs)` and fire the idling shape when `ρ < GOAL_STALL_RATE` — `backend/agent/agent_kernel.py`, `backend/agent/tool_envelope.py:910`, `backend/agent/goal_contract.py` — RIPPLE: `evaluate_streak` consumes `ρ` (CT-GC5); no new termination authority; `Δs` read from the existing token accounting

## Wave 3 — Mutation, blocked facts, grade
- [ ] T7 (REQ-4): Route user steering through `amend` (source=user) — add/remove/repromote a floor fact in place, preserving task identity — `backend/agent/agent_kernel.py:9883 _der_check_steering`, `:10447 _der_apply_steering` — RIPPLE: `_der_amend_graph` (`:10634`) writes the forward node
- [ ] T8 (REQ-4): Write the forward amendment node with `derives_from` to the prior contract state, carrying who/when/why and version_from/version_to; allow agent ceiling additions (capped), refuse agent floor removals — `backend/agent/agent_kernel.py:10634 _der_amend_graph`, `backend/agent/der_links.py` — RIPPLE: `derives_from` already exists (`der_links.py:14`); CT-GC4 pins the edge
- [ ] T9 (REQ-5): Blocked facts — mark with a typed `Reason`, keep in the denominator, and make the final answer name every blocked fact; the deterministic summary is the floor when the model omits one — `backend/agent/agent_kernel.py:12736 _der_synthesize_success_outcome`, `:12671 _der_synthesize_outcome`, `:12844 _der_deterministic_failure_summary` — RIPPLE: `nodes/outcome.py` `Reason` consumed, not extended; CT-GC7 pins the denominator
- [ ] T10 (REQ-7, REQ-8): Grade from coverage — `evaluate_run_grade` (`tool_envelope.py:969`) accepts `C` + blocked list; `_der_report_run_grade` (`:5679`) reports `done + grade + blocked` on every terminal path; add the REQ-7 counters (facts seeded/mapped/re-added/covered/blocked, amendments by source, stalls, bonus passes) — `backend/agent/agent_kernel.py`, `backend/agent/tool_envelope.py` — RIPPLE: D7's `pass (failure-settled)` becomes capped; BT-GC2 proves it

## Wave 4 — Scheduling orthogonality & fail-fast
- [ ] T11 (REQ-6): AND the two gates — the goal state requests work, the phase gate (`inference/router.py:977-980`) admits it; assert the scheduler path reads no goal symbol; preserve the priority-lane hard bypass and the fail-open degradation — `backend/agent/agent_kernel.py`, `backend/agent/inference/router.py` — RIPPLE: `phase_manager.py` unchanged; CT-GC6 pins orthogonality (extends concurrency CT-3)
- [ ] T15 (REQ-9, REQ-11): Fail fast on un-runnable steps AND make it teach — add `Reason.APPROVAL_UNAVAILABLE` to the closed vocabulary, detect an un-attendable approval before dispatch, settle immediately, emit the FAULTLINE canonical shape at the pre-dispatch site (the short-circuit bypasses `normalize_failure`), register the label via `register_error_label` (DATA edit), and feed `_record_tool_event` + `verified_label`→`task:learning` + `record_region_mediator_outcome` + `link_failed_like` — `backend/agent/nodes/outcome.py`, `backend/agent/tool_bridge.py`, `backend/agent/tool_errors.py` — RIPPLE: the permission-matrix change is T18; planner keeps free tool choice (vast-domain lock); CT-GC12/CT-GC13 pin the shape + hooks
- [ ] T17 (REQ-12): Frontend contracts — verify no new component is needed: `APPROVAL_UNAVAILABLE` renders through the existing `PermissionCard`/failure path; "approval UI attached" uses existing WS presence (`agent_kernel.py:8396`); the `personal`/`developer` toggle stays the matrix authority — `components/chat/PermissionCard.tsx`, `hooks/useIRISWebSocket.ts`, `backend/agent/agent_kernel.py` — RIPPLE: no new event type (CT-GC12); the developer-mode write-approval question is an Open Question, not silently changed
- [ ] T16 (REQ-10): State and pin the phase-layer separation — the goal contract feeds the cognitive layer (`u`) only and adds no new phase layer; assert `goal_contract.py` imports no oscillator/phase module and the scheduler path is unchanged — `backend/agent/goal_contract.py`, `backend/tests/contract/` — RIPPLE: `caducean_trajectory.py` and `coupled_registry.py` unchanged (CT-GC11); the taxonomy is documented in requirements.md and design.md
- [ ] T18 (REQ-9 AC9.4/AC9.6): Consent/capability split — `get_permission_action` takes `auto_approve` instead of `level`; the toggle governs reads/writes/shell/GUI; `_ALWAYS_ASK_TOOLS` shrinks to the DESTRUCTIVE tier; the destructive detector grows deletion/removal command forms — `backend/agent/permissions.py` — RIPPLE: CT-GC10 + CT-GC14 pin it; `capabilities.py` CONTRACT LOCK (capability unchanged); mode governs capability only
- [ ] T19 (REQ-12 AC12.4): Auto-approve toggle in `PermissionsSettingsCard` next to the mode control; show the effective state; destructive tools render gated even when ON — `components/chat/PermissionsSettingsCard.tsx`, config endpoint — RIPPLE: the card already re-fetches `/api/config` (`:84`); no new event type

## Wave 5 — Verification
- [ ] T12 (REQ-1..REQ-12): Unit tests — `extract_required` determinism, `map_to_steps` omission, `mark_coverage` set-union, `progress_ratio` (no-progress vs slow-progress), `amend` floor protection, `add_ceiling` cap, `is_blocked` vocabulary incl. `APPROVAL_UNAVAILABLE` — `backend/tests/unit/` — RIPPLE: CT-GC2/CT-GC3/CT-GC7/CT-GC9 share fixtures
- [ ] T13 (REQ-1..REQ-12): Contract + behavioral tests — CT-GC1..CT-GC14, BT-GC1..BT-GC9; the caller-existence pin (CT-GC8), the scheduler-orthogonality pin (CT-GC6), the capability/consent pin (CT-GC10), the destructive-detector pin (CT-GC14), and the FAULTLINE-shape/learning pins (CT-GC12/CT-GC13) are mandatory — `backend/tests/contract/`, `backend/tests/behavioral/` — RIPPLE: each behavioral gap decomposes to its contract twin
- [ ] T14 (REQ-1..REQ-8, success criteria): Standing CDD harness + LIVE gate — `scripts/validate_goal_coverage.py` replays the recorded D3/D7/D8/D9/D10 trajectories; then a fresh backend (Config B, `IRIS_PHASE_SCHEDULER=1`) runs the same five probes and must produce the same terminal coverage verdict (every fact covered or named blocked; no `pass` with an open unblocked fact) — `scripts/`, `.iris-logs/` — RIPPLE: screenshots to `screenshots/`; log to `.iris-logs`
- [ ] TG-1 (after Wave 1): CT-GC1 + CT-GC2 green; `py_compile` goal_contract.py + der_loop.py; existing suites unchanged
- [ ] TG-2 (after Wave 2): CT-GC3 + CT-GC5 + CT-GC7 + BT-GC1 + BT-GC3 green; baseline unchanged
- [ ] TG-3 (after Wave 3): CT-GC4 + BT-GC2 + BT-GC4 green; D7 shape now capped
- [ ] TG-4 (after Wave 4): CT-GC6 + CT-GC9 + CT-GC10 + CT-GC11 + CT-GC12 + CT-GC13 + CT-GC14 + BT-GC5 + BT-GC6 + BT-GC8 + BT-GC9 green; priority lane, fail-open, capability/consent separation, the destructive hard stop, and FAULTLINE/learning wiring preserved
- [ ] TG-5 (after Wave 5): T12-T19 green AND the live five-probe replay passes per-AC; no wave starts on red without explicit user override recorded in Decisions Locked

## Traceability Matrix (MANDATORY — every AC accounted for)

| REQ | ACs | Covering tasks | Covering tests | Status |
|---|---|---|---|---|
| REQ-1 | AC1.1–AC1.6 | T1, T2, T4 | CT-GC1, CT-GC2, CT-GC3, BT-GC1 | covered (projected) |
| REQ-2 | AC2.1–AC2.5 | T1, T4, T5 | CT-GC1, CT-GC7, BT-GC1 | covered (projected) |
| REQ-3 | AC3.1–AC3.6 | T3, T5, T6 | CT-GC5, BT-GC2, BT-GC3, BT-GC7 | covered (projected) |
| REQ-4 | AC4.1–AC4.7 | T7, T8 | CT-GC4, BT-GC4 | covered (projected) |
| REQ-5 | AC5.1–AC5.4 | T9 | CT-GC7, BT-GC2 | covered (projected) |
| REQ-6 | AC6.1–AC6.4 | T11 | CT-GC6, BT-GC5 | covered (projected) |
| REQ-7 | AC7.1–AC7.4 | T3, T10 | harness (`validate_goal_coverage.py`), live logs | covered (projected) |
| REQ-8 | AC8.1–AC8.3 | T10 | BT-GC2, live replay | covered (projected) |
| REQ-9 | AC9.1–AC9.6 | T12, T15, T18 | CT-GC9, CT-GC10, CT-GC14, BT-GC6, BT-GC9 | covered (projected) |
| REQ-10 | AC10.1–AC10.3 | T16 | CT-GC11 | covered (projected) |
| REQ-11 | AC11.1–AC11.6 | T15 | CT-GC12, CT-GC13, BT-GC8 | covered (projected) |
| REQ-12 | AC12.1–AC12.4 | T17, T19 | CT-GC10, CT-GC12 | covered (projected) |

AC count: 58. Covered: 58. Deferred: 0. Unmapped: 0. ✅

## Dependency / parallelization notes
- Wave 1 is pure and independent — it can land and gate before any loop edit.
- Wave 2 depends on T1/T2/T3; all edits are in `agent_kernel.py` (sequential, same session).
- Wave 3 depends on T4/T5 (the contract must exist before it can be amended or graded).
- Wave 4 depends on T6 (the loop condition must exist before the gates are ANDed). T15 is independent of T11 (dispatch path vs gate) and may land in parallel.
- T12/T13 can be written in parallel with Wave 3/4 (pure + contract tests), but T14's live gate is last.
- NO-CHANGE-verified areas (`phase_manager.py`, `capabilities.py`) need no tasks — only their CONTRACT LOCK rows hold (CT-GC6, CT-GC10). `nodes/outcome.py` and `tool_errors.py` are CHANGE NEEDED / DATA EDIT (T15); `permissions.py` is CHANGE NEEDED (T18); `PermissionsSettingsCard.tsx` is CHANGE NEEDED (T19, the Auto-approve toggle); the rest of the frontend contract is verified by T17.
- The **capability-advertisement** concern (a tool describing what it can do across vast domains) is OUT OF SCOPE and belongs in its own spec. The **fail-fast on un-runnable steps** concern is IN scope as T15 — the D1/D11 hang was the real defect, not the planner's tool choice.
- RESOLVED (session-327, owner, final): an Auto-approve toggle governs reads/writes/shell/GUI; only DESTRUCTIVE and deletion/removal commands stay gated at all times (T18/T19). Mode governs capability only. CT-GC10 + CT-GC14 pin it.
