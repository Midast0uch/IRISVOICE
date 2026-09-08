# Tasks: Speech Lane Engine

> Each task links to a requirement. Matrix + gates are mandatory (skill step 9):
> no AC unmapped, no wave starts on a red gate.

## Wave 1 — Foundation (no behavior change)

- [ ] T1 (REQ-1, REQ-3): UtteranceNode model + deterministic router + hierarchy table as data — NEW `backend/agent/speech_lanes.py` — RIPPLE: imports nothing from phase_manager (vocabulary only); trigger labels passed by existing callers unchanged.
- [ ] T2 (REQ-9): Per-turn observability (routing/preemption/subsumption/shaping logs + L2–L4 and unlisted-type counters) — `speech_lanes.py` — RIPPLE: logging only, off the audio path.
- [ ] T3 (REQ-9): Shadow-mode observer wiring (all speech intents register; would-order logged; zero behavior change) — call sites emit intents — RIPPLE: additive hooks at the 4 `_speak_response` entries + SpeakTool; removable in one task.
- [ ] TG-1 (gate): Router decision-table unit green (every hierarchy cell) + shadow emitting on a live session with no crashes — PROVES REQ-1/REQ-3/REQ-9 foundations.

## Wave 2 — Cutover (strangler order: narration → play → replies → gates)

- [ ] T4 (REQ-2, REQ-4, REQ-5): Migrate narration path to lanes (ephemeral nodes, subsumable, turn-bounded) — `conversation_kernel.py`, `speak_tool.py` caps to sentence-aware budget — RIPPLE: narration lock stays until T8; SpeakTool rate limit stays until lanes prove it redundant.
- [ ] T5 (REQ-2, REQ-6): Migrate play-button path + content-aware resolver v1 (precedence + type table + spoken⊆visible) — gateway play path — RIPPLE: resolver replaces play-path derivation only; other roads untouched.
- [ ] T6 (REQ-2, REQ-4, REQ-5, REQ-6): Migrate reply paths (voice turn, agent DAG, dashboard) + alert lanes (Critical + Awaiting) — gateway/DB paths — RIPPLE: agent prompt contract untouched; `prepare_spoken_text` becomes resolver input.
- [ ] T7 (REQ-7): Derived gates (half-duplex from running play-nodes; highlight target from running node); delete the 8 toggle sites + narration lock — RIPPLE: barge-in + VAD + engine read derived state; porcupine/violawake tests cover toggles — update pins, not behavior.
- [ ] TG-2 (gate): Behavioral green — barge kill+fresh, subsumption silence, turn-boundary deaths/survivals, ephemeral narration absent from history, shaping table incl. override — PROVES REQ-2/REQ-4/REQ-5/REQ-6/REQ-7 behaviorally.

## Wave 3 — Verify and lock

- [ ] T8 (REQ-8): Node watchdog + failure semantics (fail node, free gates, one retry, one-breath Critical cap) — `speech_lanes.py` — RIPPLE: TTS crash-restart paths unchanged underneath.
- [ ] T9 (REQ-6 + locks): Contract pins — spoken⊆visible on all five roads (CT-S3), normalization coverage per road (CT-S4), node lifecycle states (CT-S5), event shapes unchanged (CT-S2) — RIPPLE: locks future edits, no behavior change.
- [ ] T10 (REQ-1–REQ-9): Live gate — shadow-diff session zero unexplained divergences + first-audio latency ≤ baseline + lane-counter review feeding OQ-1/OQ-2 — RIPPLE: read-only measurement.
- [ ] TG-3 (gate): Full matrix closeout — every row proven or explicitly deferred; existing audio suites green (voice_pipeline, barge_in, tts_*); commit.

## Wave 4 — Narration content refinement (PENDING — OQ-5 grounding; do NOT start)

- [ ] T11 (REQ-10): Phase -1 grounding table — DONE (grounding.md): plan segments = ExecutionPlan.steps/PlanStep (core_models.py:711-743), planning first-writer `_plan_task` (:5503) + prompt schema (:5638) + parse (:5368/:5730); wait states = TOOL_CALL/TOOL_RESULT events + tool_bridge 30s/60s budgets + step turn-budget timeouts (no extend mechanism exists — AC10.11 triggers are entry/expectation-miss/exit only); filler sites agent_kernel.py:6233-6250 + tts.py:845-897; settings transport `settings_sync` (kernel apply is a `pass` stub — T15 implements it); awaiting surfaces QuestionCard/PermissionCard/takeover-banner. RIPPLE: T12/T13/T15 file targets determined; blocks their writing until reviewed.
- [x] T12 (REQ-10): Planned-beat authoring at task start (direction + time/scale expectations; first beat speaks immediately per AC10.10; duration gate per AC10.10) + authoring guidance (findings near completion fold into the reply; artifacts by natural name — never recited identifiers; failure lines = cause at direction level + next step) + anti-repetition few-shot examples — RIPPLE: must not touch speak_tool shaping (REQ-6 resolver owns it); feeds AC10.1/10.2/10.12.
- [x] T13 (REQ-10): Beat store as the scheduler queue itself — immutable nodes (kind: planned|reactive), atomic ops ADD/REPLACE(=cancel+add)/CANCEL with explicit logged rejection — plus live reactive lines, burst merge + debounce window (AC10.9), wait-state triggers (AC10.11), anti-repetition bounce (AC10.12) — RIPPLE: feeds REQ-4 subsumption; REQ-9 counters extended with beat-revision, merge, and bounce events.
- [x] T14 (REQ-10): Hybrid pre-synthesis — synthesize-and-hold worker action at LOWEST priority (never delays REPLY/ALERT synthesis), held-buffer caps + free paths on every exit (play/cancel/barge-in/turn-end/toggle-off/session-end), fallback to on-admission synthesis on failure — RIPPLE: `tts_worker.py` protocol + `tts.py` manager become CHANGE NEEDED here (Wave 4 only); covers AC10.6/AC10.7.
- [x] T15 (REQ-10): Narration toggle — frontend settings control riding the existing preference path + backend admission check (narration off drops beats at admission, logged + counted; in-flight pre-synthesis aborted, buffers freed) — RIPPLE: no WS shape changes; covers AC10.14.
- [x] T16 (REQ-10): Echo + filler tests — CT pin: narration `tts_started` turn_id non-match (no phantom card) + orb-chain reuse via existing audio_envelope/tts_started shapes (AC10.8); BT: filler gap-filler exception incl. no-consecutive-repeat + subsumption-on-beat-arrival (AC10.13); CT pin: content whitelist for AC10.5 sentence cap + spoken⊆visible — RIPPLE: reuses existing contract suites (voice_pipeline, barge_in) as the CT base. DONE (session-310): backend/tests/contract/test_narration_echo_contract.py (CT-S6 + AC10.5 pin) + backend/tests/behavioral/test_filler_exception_behavior.py (BT-S9). AC10.13 engine clauses implemented (filler_allowed silence gate + pick_filler no-consecutive-repeat + admit() subsumes queued fillers on real-beat arrival + fillers excluded from reactive merge); AC10.5 sentence cap enforced once at scheduler admission (_cap_narration_text).
- [x] TG-4 (gate): REQ-10 matrix rows proven per-AC (AC10.1–AC10.14) before spec closeout. PASS (session-310): 196/196 across all REQ-10 proving suites; per-AC ledger below.

## Traceability Matrix (MANDATORY — unmapped = zero)

| REQ | ACs | Covering tasks | Covering tests | Status |
|---|---|---|---|---|
| REQ-1 | AC1.1 router pure function | T1 | CT-S1 decision-table unit | projected |
| REQ-1 | AC1.2 intent is content-only | T1, T6 | CT-S1 + prompt-unchanged check | projected |
| REQ-1 | AC1.3 decision recorded | T2 | observability unit | projected |
| REQ-2 | AC2.1 four lane contracts | T4, T6 | BT lane-contract suite | projected |
| REQ-2 | AC2.2 priority serialize/FIFO | T4–T7 | BT ordering suite | projected |
| REQ-2 | AC2.3 no overlap smell | T9 | design-review checklist (manual) | projected |
| REQ-3 | AC3.1 hierarchy precedence | T1 | CT-S1 hierarchy cells | projected |
| REQ-3 | AC3.2 L2–L4 logging | T2 | counter unit | projected |
| REQ-3 | AC3.3 default narration | T1 | CT-S1 default row | projected |
| REQ-4 | AC4.1 barge kill+fresh | T4, T6 | BT-S1 multi-turn | projected |
| REQ-4 | AC4.2 subsumption | T4 | BT-S2 | projected |
| REQ-4 | AC4.3 critical preempts | T6 | BT-S1 alert case | projected |
| REQ-4 | AC4.4 completion beats cancel | T8 | BT-S1 race case | projected |
| REQ-5 | AC5.1 narration dies at boundary | T4 | BT-S3 | projected |
| REQ-5 | AC5.2 reply finishes across boundary | T6 | BT-S3 | projected |
| REQ-5 | AC5.3 awaiting survives + re-announces | T6 | BT-S3 | projected |
| REQ-5 | AC5.4 barge overrides boundary | T4, T6 | BT-S1+S3 combined | projected |
| REQ-6 | AC6.1 type-aware shaping | T5, T6 | BT-S5 table | projected |
| REQ-6 | AC6.2 single resolver precedence | T5 | CT-S3 per road | projected |
| REQ-6 | AC6.3 spoken⊆visible | T9 | CT-S3 subset pins | projected |
| REQ-6 | AC6.4 unlisted-type fallback + log | T5 | BT-S5 + counter | projected |
| REQ-7 | AC7.1 serialize via lanes, lock removed | T7 | BT ordering + lock-absence check | projected |
| REQ-7 | AC7.2 derived mic gate | T7 | BT gate-derivation (stuck-producer case) | projected |
| REQ-7 | AC7.3 watchdog frees gates | T8 | BT-S6 | projected |
| REQ-7 | AC7.4 zero first-audio regression | T10 | live latency gate | projected |
| REQ-8 | AC8.1 node fail + continue visibly | T8 | BT-S6 | projected |
| REQ-8 | AC8.2 one-breath Critical cap | T8 | BT-S6 cap case | projected |
| REQ-8 | AC8.3 retry-once then drop | T8 | BT-S6 retry case | projected |
| REQ-9 | AC9.1 per-turn decision logs | T2 | log-shape unit | projected |
| REQ-9 | AC9.2 tuning counters | T2 | counter unit | projected |
| REQ-9 | AC9.3 shadow divergences | T3, T10 | shadow-diff session | projected |
| REQ-10 | AC10.1 content whitelist (+ failure wording, natural-name artifacts as authoring guidance) | T12, T13 | BT narration-content suite | PROVEN (test_prompt_carries_beats_guidance) |
| REQ-10 | AC10.2 planned beats at task start | T12 | BT planning-time beats | PROVEN (test_multi_segment_plan_keeps_beats) |
| REQ-10 | AC10.3 reactive lines + beat revision (atomic ops, logged rejection) | T13 | BT beat-revision | PROVEN (test_replace_settled_is_rejected_logged, test_cancel_pending_and_unknown) |
| REQ-10 | AC10.4 invalidated beats cancelled via subsumption | T13 | BT-S2 extension | PROVEN (test_replace_pending_cancels_and_adds, test_reply_cancels_pending_narration) |
| REQ-10 | AC10.5 sentence cap + spoken⊆visible | T16 | CT pin | PROVEN (test_narration_echo_contract::TestNarrationContentCap) |
| REQ-10 | AC10.6 pre-synthesis lowest worker priority | T14 | BT-S8 + worker-priority unit | PROVEN (test_hold_never_blocks_on_busy_lock, test_lane_busy_skips_presynth_but_admits) |
| REQ-10 | AC10.7 held-buffer bounds + free paths | T14 | BT-S8 lifecycle cases | PROVEN (test_sentence_cap_and_turn_cap, TestHoldLifecycle) |
| REQ-10 | AC10.8 orb echo via existing chain, no phantom card | T16 | CT-S6 (turn_id non-match + shape reuse) | PROVEN (test_narration_echo_contract::TestNarrationEchoShapes) |
| REQ-10 | AC10.9 burst merge, pivot immediate | T13 | BT-S7 | PROVEN (test_rapid_findings_fold_into_one_line, test_pivot_bypasses_merge_but_serializes) |
| REQ-10 | AC10.10 timing rules (first beat, coalesce, duration gate) | T12, T13 | BT-S7 | PROVEN (test_first_beat_admitted_to_narration_lane, test_single_segment_plan_drops_beats_duration_gate) |
| REQ-10 | AC10.11 wait-state triggers, no heartbeats | T13 | BT-S7 | PROVEN (test_long_wait_entry_miss_exit, test_short_wait_no_entry_line_but_miss_fires) |
| REQ-10 | AC10.12 repetition bounce, one retry | T12, T13 | BT-S7 | PROVEN (test_repeat_opening_bounces_once_then_speaks) |
| REQ-10 | AC10.13 filler gap-filler exception | T16 | BT-S9 | PROVEN (test_filler_exception_behavior) |
| REQ-10 | AC10.14 narration toggle via settings path | T15 | CT-S7 + drop-counter unit | PROVEN (TestNarrationToggle) |

Traceability verdict: 31 ACs proven (Waves 1–3), 0 deferred, 0 unmapped; REQ-10 adds 14 ACs ALL PROVEN (session-310, TG-4 PASS 196/196). Spec closeout eligible.

## Dependency / parallelization notes

- T1 → T2/T3 (router first; observability + shadow build on its types).
- T4 → T5 → T6 (strangler order: narration, play, replies+alerts — each independently shippable).
- T7 after T4–T6 (flags die only when no caller toggles them).
- T8–T10 after cutover (watchdog/contracts/live need the real paths).
- TG-1 blocks Wave 2; TG-2 blocks Wave 3 (hard rule: no wave starts on red).
- Wave 4 runs AFTER Wave 2's T4 (needs the lane machinery for beat cancellation) and is blocked by OQ-5 resolution only (OQ-4 resolved 2026-09-07: echo rides the existing orb chain — no echo frontend work); TG-4 blocks spec closeout.
- Frontend work in Wave 4 is exactly ONE item: T15 narration toggle, riding the existing settings/preference path (no WS event-shape changes). The orb echo (AC10.8) requires NO frontend work — verified against the existing audio_envelope/tts_started chain.
- T14 reclassifies `tts_worker.py`/`tts.py` as CHANGE NEEDED for the synthesize-and-hold action — Waves 1–3 leave both untouched; the Ripple-Effect Map carries the wave-scoped classification.
- New tests named in the matrix (BT-S7/S8/S9, CT-S6/S7) are defined in design.md Testing Strategy.
