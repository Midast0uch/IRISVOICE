# Tasks: DAG Node Execution Model

> Every task links to a requirement. Waves group work for parallel execution.
> Read `requirements.md` and `design.md` in full first — the Ripple-Effect Map in
> design.md tells you what each task touches beyond its own file.

## Why this exists

The websearch feature was specified with interchangeable capabilities and delivered with
them behind a fixed funnel. Three symptoms each needed a hand-written branch:

1. a fresh bot-challenge never escalated to vision (`orchestrator._dispatch_one` only
   routed to vision on *prior* recorded domain failure),
2. a planner returning zero URLs dead-ended (`no candidate urls`),
3. the only loop-back re-ran the same planner and failed identically.

One structural gap, three patches. **The acceptance test for this spec is that those three
hand-written branches can be deleted and the behaviour still holds** — because the routes
now come from advertisement instead of code someone remembered to write.

## Wave 0 — Baseline (blocking)

- [ ] T0 (all): Record a green baseline before touching anything. Run the contract and
  behavioral suites and write down which failures are pre-existing.
  KNOWN pre-existing full-suite-only flakes — do NOT chase, and verify any suspect by
  running its file ALONE first: `chain_coordinate_store`, `cross_space_refusal`,
  `event_bus`, `memory_retrieval`, `model_routing` (needs a live server on :8090),
  `porcupine`, `resolver_fallback`, `speak_tool`, `switch_conversation`,
  `voice_command_start`, and `test_crawl_orchestrator_contract::test_process_tree_killed_on_timeout`
  (real-subprocess test, flakes under full-suite CPU contention).
  Command: `python -m pytest backend/tests/contract/ -q -p no:cacheprovider --ignore=backend/tests/contract/test_exa_provider.py`
  (`test_exa_provider.py` needs `pytest_httpx`, which is NOT installed — always ignore it.)
  — RIPPLE: without this, every later wave's red is ambiguous.

## Wave 1 — The contract (blocks everything)

- [ ] T1 (REQ-1): Create `backend/agent/nodes/outcome.py` — `NodeStatus`, `Reason`,
  `NodeOutcome`, `Artifact`. Seed `Reason` from `backend/crawler/usability.py`
  `UsabilityReason`, which is the proven vocabulary.
  — RIPPLE: `Artifact.ref` must exist from the start (design D7) — video/audio pipelines
  are an explicit target and cannot materialise into the graph.

- [ ] T2 (REQ-2): Create `backend/agent/nodes/spec.py` — `NodeSpec` **wrapping**
  `ToolSpec`, not duplicating it.
  — RIPPLE: `tool_registry.py:45` fields stay exactly as they are. `crawler/capabilities.py`
  is the cautionary example of what a parallel registry costs.

- [ ] T3 (REQ-1 AC2, REQ-7 AC1): Create `backend/agent/nodes/runner.py` — invoke a node,
  convert any raise into `NodeOutcome(FAILED, UNEXPECTED)`, and adapt undeclared legacy
  tools so they run exactly as today.
  — RIPPLE: the legacy adapter is what makes strangler-fig possible; without it every tool
  must migrate at once.

- [ ] T4 (REQ-9): Instrumentation — node executions, routing decisions, amendments, and
  refused amendments, each with the task identifier.
  — RIPPLE: off the critical path. Silent selection is how the Exa provider stayed unused
  and undetected; a routing decision with no log line is unanswerable.

## Wave 2 — Routing

- [ ] T5 (REQ-4): Create `backend/agent/nodes/router.py` — match a failure `Reason` against
  nodes advertising `recovers_reasons`, apply the attempt bound, deterministic tie-break by
  `preference`.
  — RIPPLE: this is the edge that does not exist today. No branch may live in the failing
  node's module (REQ-4 AC1 / design D4).

- [ ] T6 (REQ-4 AC4, REQ-8): Terminal-reason and permission guards — `REFUSED`,
  `ROBOTS_REFUSED`, `PERMISSION_DENIED` are never routed around; a recovery node's tier is
  evaluated exactly as a planned node's and may not exceed the approved tier.
  — RIPPLE: **the robots case is not hypothetical.** In the websearch spec, escalating a
  robots.txt refusal to a browser node with no robots gate would have routed around
  compliance for the exact URL just refused. Encode it in the type system so no future node
  author has to remember it.

- [ ] T7 (REQ-2 AC1/AC3): Extend `tool_registry.py` to carry optional node metadata and
  accept a `NodeSpec`; fail loudly on duplicate names.
  — RIPPLE: every existing `register_tool` call must remain valid unchanged (REQ-7 AC3).

- [ ] T8 (REQ-7 AC4/AC5): The kill switch — one setting that disables outcome-driven
  routing and restores today's behaviour.
  — RIPPLE: land this WITH the router, not after. Given `agent_kernel.py` is 12,291 lines
  with 117 tests reaching into it, the rollback path is the precondition for merging.

## Wave 3 — DER integration

- [ ] T9 (REQ-1 AC5, REQ-4): Make `_execute_plan_der` (`agent_kernel.py:5908`) consume
  `NodeOutcome` and consult the router on failure. Smallest possible incision.
  — RIPPLE: `der_loop.py:70 NodeRecord` is a CONTRACT LOCK — the reason lands in the
  existing record, not a parallel structure (CT-3). `tool_decision.py` must record the
  typed reason without regressing the `success=True error_type=permanent` fix the
  websearch spec already landed.

- [ ] T10 (REQ-5): Bounded mid-execution amendment — extend or amend the graph between
  steps, preserving completed work, never re-executing satisfied nodes.
  — RIPPLE: planner-driven ONLY (design D6). A node proposing its own successor
  reintroduces the hidden control flow this spec removes. Existing step budget and token
  accounting stay authoritative (REQ-5 AC4).

## Wave 4 — Migration (the proof)

- [ ] T11 (REQ-2 AC4): Express `fetch.crawl` / `fetch.vision` as `NodeSpec`s and retire the
  parallel `crawler/capabilities.py` registry.
  — RIPPLE: `usability.py` needs NO change — map `UsabilityReason` to `Reason` at the
  boundary; the single-judge predicate stays exactly as CT-1 of the websearch spec pins it.

- [ ] T12 (REQ-3 AC5): Express `crawler_query` as the reference composite — sub-node
  outcomes recorded, re-routable at sub-node boundaries, still one callable unit.
  — RIPPLE: REQ-3 AC4 keeps the outer outcome single, so the frontend card and event shapes
  need NO change.

- [ ] T13 (REQ-4): **Delete the three hand-written branches** in
  `backend/crawler/orchestrator.py` — fresh-failure escalation, search-engine discovery
  trigger, and the history-gated race — replacing each with an advertisement on the
  relevant `NodeSpec`.
  — RIPPLE: **this task is the acceptance test for the whole spec.** The websearch spec's
  existing tests (BT-11, BT-12, CT-12 and the escalation/park suites) must still pass
  unchanged afterwards. If deleting a branch breaks them, the node model has not actually
  absorbed it. Do not weaken those tests to make this pass — if they conflict, STOP and
  report.

- [ ] T14 (REQ-6): Register the `vision.*` MCP tools and one audio/parakeet node as
  `NodeSpec`s to prove cross-modal composition.
  — RIPPLE: `vision_mcp_server.py`, `mcp/builtin_servers.py`, `mcp/protocol.py` and
  `vision/browser_session.py` need NO code change — registration alone (REQ-6 AC4).

## Wave 5 — Verification

- [ ] T15 (REQ-1..9): Contract tests CT-1..CT-10 in `backend/tests/contract/`.
  — RIPPLE: CT-4's caller-existence pins are the highest-value item here. This codebase
  produced **19** built-but-never-called mechanisms while delivering the websearch spec,
  four of which were found only because that spec asserted mechanisms are *reached*, not
  merely that they work. Model CT-4 on
  `backend/tests/contract/test_single_judge_and_wiring_contract.py` (`_calls_in`, AST-based).

- [ ] T16 (REQ-1..9): Behavioral tests BT-1..BT-8 in `backend/tests/behavioral/`.
  — RIPPLE: BT-8 shares fixtures with the websearch spec's BT-11/BT-12 so migration is
  proven against already-passing behaviour rather than new assertions. BT-1 is the core
  property: recovery happens with no branch in the failing node's module.

- [ ] T17 (REQ-9): Standing CDD harness `scripts/validate_node_routing.py` — replays
  challenge→vision, no-candidates→discovery, robots→terminal, budget→refused-amendment
  through the real runner and router, asserting both the routes taken and the routes
  correctly NOT taken.
  — RIPPLE: follow the `scripts/validate_der_*.py` and `validate_websearch_trajectory.py`
  family conventions (exit 0 / non-zero, `[PASS]`/`[FAIL]` lines naming the REQ).

- [ ] T18 (all): Live verification — run a real task that exercises a pivot end to end and
  confirm the log reconstructs the executed graph (REQ-9 AC4).
  — RIPPLE: **green tests are not sufficient evidence in this codebase.** Every defect in
  the websearch reference trace passed its unit tests. A live run is the exit criterion.

## Dependency / parallelization notes

- **Wave 1 blocks everything**; T1 in particular — the outcome type is what every other
  task consumes.
- **T5–T8 (Wave 2) can run in parallel** with each other; T8 must merge no later than T5.
- **Wave 3 is a single-threaded incision into `agent_kernel.py`** — do not parallelise T9
  and T10 across agents; they touch the same 1,170-line method.
- **Wave 4 tasks are independently revertable** and each proves a different claim: T11 that
  the parallel registry was redundant, T12 that composites decompose, T13 that routing
  replaces branches, T14 that modalities compose.
- **T13 is the acceptance test.** If the hand-written branches cannot be deleted, this spec
  has not delivered its purpose regardless of how many tests are green.
- **Verified-no-change areas** (do not edit; cite in review if touched):
  `mcp/builtin_servers.py`, `mcp/protocol.py`, `tools/vision_mcp_server.py`,
  `vision/browser_session.py`, `agent/tools/ask_user_tool.py`, `crawler/usability.py`,
  `der_loop.py:70 NodeRecord` (CONTRACT LOCK), permission tier semantics (CONTRACT LOCK),
  and the entire frontend.

## Test rule reminder for the executing agent

Per CLAUDE.md: run the spec's tests against your implementation. Never weaken a test to
make it pass — that includes reducing the load it drives, loosening a tolerance, dropping a
parametrize case, or stubbing a dependency that could fail. If a test and this spec
genuinely conflict, **report it**: name the spec line and the test line, show the proof, and
propose a fix. Do not reconcile it yourself.

Two specific traps in this repo:
- Patching `CrawlerEngine` is a NO-OP for `mode="agent"` — the real path is
  `CrawlOrchestrator.research()` → `SubprocessFetchBackend`. Correct seams are
  `orch._backend_override` or patching `backend.crawler.orchestrator.get_crawl_orchestrator`.
- A stub backend's `fetch` must accept `job_id`, and stub `PageData` must carry `.html`
  plus ≥20 chars of markdown to clear `page_is_usable`.
