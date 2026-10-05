# Phase Domains - one Caducean phase model, one dimension per application layer

Status: architecture (design direction from the owner, 2026-10-01 (session 64237209). NOT built beyond the first
instance (the Oracle domain, `specs/oracle-phase-concurrency/`)). Read with
`docs/CADUCEAN_CONCURRENCY_MODEL.md` (the model) and `docs/CADUCEAN_ARCHITECTURE.md` (the boundary).

## The idea (owner)

There is ONE phase model - "many operations run at the same time without clashing, because each
holds a distinct position" (CONCURRENCY_MODEL §0). Each place the application uses it is a
DIMENSION of that model, defined by the LAYER it addresses - not a separate, hand-built manager per
use case. A use case SPAWNS a domain from one black-box implementation that carries the
principles; the domains never conflict because they never share state.

## The principles every domain carries (the black box)

1. Every participant holds its own angle; acts at ~180 degrees, then jumps 180 (`trig_coupling`).
2. Repulsion keeps the angles apart (the sign guard `test_splay_force_opposite_sign_regression`).
3. Overlap is allowed and cannot collide - NO lock, cap, semaphore or timeout as the mechanism.
4. The resource is a PARAMETER (a load signal), never a ceiling.
5. Priority classes (`call_context`: USER_TURN, SPEAK) bypass with wait 0.
6. Fail-open: an internal error admits the work and logs; it never blocks the product.
7. A scheduling domain never reads live cognitive state (CT-3 / CT-4, CONCURRENCY_MODEL §5).
8. Domains share CODE (the class + the maths), never STATE (registry, tunables, load).

## The layers (the dimensions) - what exists today

| Layer | Dimension (resource it de-correlates) | Today | Load signal | Notes |
|---|---|---|---|---|
| Cognitive | the agent's reasoning state per session: Sigma = (x, y, xi, u) | LIVE - C++ `caducean.cpp`, kernel `_der_physics_step` | the step's own expand/compress - REQ-8 fix REVERTED 2026-10-01 (ebeea6ce): node steps carry no tool, so every coding step read COMPRESS; redo by NodeResult.calls | the ONLY layer that reads/writes reasoning state; recall breadth / split width may read it |
| Cognitive (multi-session) | coupling between sessions' phases (windings l, m) | OFF - `coupled_registry.py` (`IRIS_COUPLING_ENABLED`). Gate run 2026-10-01 (`evals/run_pairs.py`, 3+3 runs): T4 PASS (nucleus/barrier), T8 INCONCLUSIVE (no measurable effect) -> stays off (oracle.md §0) | - | stays in the cognitive layer; the scheduler must never call it (CT-3) |
| Scheduling (model calls) | provider quota / rate limit | LIVE - `phase_manager.py` singleton at `InferenceRouter.generate` (`IRIS_PHASE_SCHEDULER=1`) | `rate_meter` | first deployment of the model; also paces LOCAL models (saturation froze the PC when removed, 2026-09-27) |
| Scheduling (batched dispatch) | grouped provider calls | OFF / untuned - `batch_dispatch.py` | - | |
| Decision | the Oracle's local CPU | LIVE 2026-10-01 - `IRIS_ORACLE_PHASE=1` in `.env` (code default stays off; the unset-means-off tests pin the lock path). Bench P3: 273/273 identical, 5.2 -> 7.9 decisions/s; live gate P4 passed: coding 15/15 + research 8/8, no standard regression. EXIT-DRIVEN admission LIVE 2026-10-01 (`IRIS_ORACLE_PHASE_EXIT=1`, `PhaseDomain.enter/exit`, `capacity_fn`): a run starts when one exits, due-time order from the dial, reply right of way (oracle.md 19.7) | runs in flight / (cores / intra_op) | ONE domain for every Oracle JOB (oracle.md §19): jobs are participants on this dial, never domains of their own (one CPU = one resource); each run stays ONE question (oracle.md §9) |
| Execution | DER node starts | PHASE DOMAIN `execution.der_nodes` (period 0.5 s, k 0.6, load from the provider rate meter, never live u/xi; S47) - the DAG decides WHAT is ready, the domain WHEN | `IRIS_DER_PARALLEL=0` (one node at a time) | live since 2026-10-04; the old semaphore executor (`DER_MAX_CONCURRENT_STEPS = 3`) had no caller and was deleted 2026-10-05 |
| Delivery | speech playback / narration | `speech_lanes.py` (lanes, not phase) | - | candidate; spoken order matters - check before converting |
| Memory (side lanes) | ordered writers per resource | `durability_queue.lane(name)` - FIFO single writer | - | NOT a phase candidate: one writer per resource IS the correctness rule (memory_events fix 17edf6f2) |
| Recall | `recall_phases.py` | (name only - recall stages, not the phase model) | - | do not confuse |

## The structure to build toward

- `backend/agent/phase_domain.py`: `class PhaseDomain` (own registry, tunables, load fn, gate
  sync/async) + `get_phase_domain(name, ...)` (one instance per name, spawned on first use) - built
  first for the Oracle.
- Later, ONE change each, each measured: the router's `phase_manager` becomes the
  `"model_calls"` domain instance (byte-for-byte behaviour, the existing phase tests as proof); the
  DER fan-out becomes an `"execution"` domain only if the classical-vs-phase test shows more
  completed work and less wasted work.
- One read-only listing of live domains (name, layer, participants, load) for observability -
  not a framework, not a registry of registries.
- Domains are named by LAYER + RESOURCE (e.g. `decision.oracle_cpu`, `scheduling.provider:<id>`),
  so a new use case picks its layer instead of inventing a manager.

## Rules that keep the dimensions from conflicting

- Only the cognitive layer reads Sigma. Every other domain keeps its own angle (two phase variables
  on purpose, CONCURRENCY_MODEL §5).
- A participant belongs to exactly one domain; work that touches two resources passes two gates in
  layer order (scheduling before decision), never one shared gate.
- Domains do not couple to each other. Coupling exists only inside the cognitive layer
  (`coupled_registry`).
