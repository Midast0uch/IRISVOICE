# Spec: Oracle decisions under the Caducean phase model (rev 1, 2026-10-01)

Owner decisions (2026-10-01): keep Parakeet; keep the Oracle on the CPU; use the phase model of
`docs/CADUCEAN_CONCURRENCY_MODEL.md` so the Oracle processes many decisions at the same time -
"they start at different angles of their own phase" - and TEST that quality does not drop.

## Facts (re-verify before editing)
- `DecisionEngine.decide` (`backend/agent/decision_engine.py` ~728) holds `self._lock` for the whole
  decision (`acquire(timeout=acquire_timeout_s=2.0)`, ~765; timeout -> `lock_timeouts += 1`,
  returns None = the decision is LOST). That is the "Lock / mutex: forbids overlap" row of
  CONCURRENCY_MODEL §1. Measured 2026-09-29: one long input held it 28.6 s and six consumers gave
  up at their 9 s budget (`decision_backend_onnx.py` `_MAX_INPUT_IDS` comment).
- The ORT session runs one question per call (`_OnnxRunner.logits`, batch dim 1),
  `intra_op_num_threads = cpu//2` = 4 of 8 logical threads, `inter_op = 1`, CPU provider only.
- Batched multi-question scoring is REMOVED by owner decision (oracle.md §9: a shared pass changed
  a verdict). Guard: `backend/tests/behavioral/test_batch_single_encode.py`. NOTHING here may share a
  pass between questions.
- The live phase gate: `backend/agent/phase_manager.acquire(oscillator_id, quota_id)` (+ async
  twin), repulsive Kuramoto `advance_all` (`trig_coupling.splay_force`, sign guard
  `test_phase_math.py::test_splay_force_opposite_sign_regression`), fires at theta ~ pi then
  +pi, amplitude relaxes toward 1 - load_fraction, fail-open, CT-3/CT-4 (never reads live
  cognitive state). Priority: `call_context.call_class()` / `is_high_priority` (USER_TURN, SPEAK).

## Requirements
- REQ-0 (owner, 2026-10-01) The Oracle has its OWN phase manager: its own registry instance, its
  own tunables (`IRIS_ORACLE_PHASE_PERIOD_S` / `_MAX_WAIT_S` / `_K`, sized to measured decision
  durations) and its own load signal. It never registers in the router's `phase_manager`
  singleton and never reads `rate_meter`: the router paces provider rate limits (calls of seconds,
  period 0.5 s); the Oracle paces the local CPU (decisions of ms-s). One shared instance would
  couple two unrelated resources. Only the shared maths (`trig_coupling`, firing convention,
  repulsion sign) is reused. Guard: Oracle oscillators never appear in `phase_manager.get_registry()`
  and router oscillators never appear in the Oracle registry.
- REQ-1 Each decision source is a phase PARTICIPANT: oscillator id
  `"{session}:{consumer_id}"` (one per consumer per session), quota group `"oracle"` (the CPU the
  Oracle runs on). Distinct oscillators start at distinct angles and are kept apart by the existing
  repulsion. The resource is a PARAMETER of the group (load fraction = Oracle runs in flight vs the
  CPU's run capacity = logical cores / intra_op threads), never a cap or a semaphore.
- REQ-2 The engine lock no longer serializes decisions: a decision passes the phase gate (the
  priority classes bypass it with wait 0, exactly as the router does), then runs its OWN single-
  question session run; several runs may be in flight at once on the one loaded session
  (onnxruntime `InferenceSession.run` is thread-safe). Shared mutable engine state (counters,
  gates, load/unload, pool) keeps its own small locks; load/unload must not race a run.
- REQ-3 QUALITY - identical decisions: for the same (consumer, options, text) the probability
  distribution is IDENTICAL (bitwise, or the tolerance is stated with its physical reason) whether
  the decision runs alone or while other decisions run. Precision/ECE on the stored calibration
  rows are unchanged. intra_op per run stays fixed (the numerics depend on it).
- REQ-4 MEASURED, classical vs phase (CONCURRENCY_MODEL §7 open thread 3): one contended
  resource (the Oracle CPU), the same decision workload (a burst of mixed consumers from several
  threads, including one long input), measured for both: completed decisions, wasted decisions
  (lock timeouts / given up), collisions (per-decision latency inflation vs alone), answer-path
  decision wait, decisions per second. Recorded in `benchmarks/` and PROGRESS; the phase version
  ships only if completed work rises, wasted work falls, and REQ-3 holds.
- REQ-5 No regression on the answer path: live evals (coding + research subsets) reply_s within
  the standards tolerance (`evals/standards.json`).

## Tasks
- [ ] P1 Benchmark harness (classical baseline first): `benchmarks/oracle_phase_bench.py` drives
  the REAL engine + model with the workload of REQ-4; writes JSON. Run it on the committed code.
  DONE = baseline JSON exists with all REQ-4 numbers.
- [ ] P2 Phase participation (REQ-1, REQ-2) behind a flag `IRIS_ORACLE_PHASE` (default on only
  after P3 passes). DONE = contract tests: distinct oscillators per consumer register in quota
  "oracle"; a priority-class decision does not wait; two decisions overlap in time (both in flight);
  load/unload never races a run; CT-3/CT-4 still hold; the batch guard still passes.
- [ ] P3 Quality + measurement (REQ-3, REQ-4): identical-distribution test over the stored
  calibration inputs alone vs concurrent; bench on the new code. DONE = numbers recorded; decision
  to default the flag on is the Director's after reading them.
- [ ] P4 Live gate (REQ-5) - Director.

NOT THIS: a shared pass between questions; a cap, semaphore or budget on concurrent runs; moving
the Oracle to the GPU; reading u/xi or any cognitive state in the gate; changing intra_op per run.
