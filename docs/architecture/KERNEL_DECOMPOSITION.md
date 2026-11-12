# Kernel Decomposition - blueprint and method

Status: PLAN, 2026-11-11. Nothing is moved yet. Owner: Midas.
Audience: any agent that continues this work. Read this file top to bottom once;
after that the STATUS TABLE (section 9) tells you where to resume.
Sibling: `specs/clm-memory/` (CLM builds in the modules this plan creates).

DONE = `backend/agent/agent_kernel.py` is a facade under 2,300 lines (RES-14); every domain
lives in one module of `backend/agent/kernel/`; guards G1-G4 are green on every
commit of the way; the eval gate shows no regression against the baseline.

NOT THIS = a rewrite; new behavior; a plugin or service layer; renamed methods; a
"cleaner" signature; fixing things met on the way inside a move commit; new tests
that describe the new layout; a compatibility shim that outlives its stage.

---

## 1. Why, in plain terms

The kernel is one room that holds every tool of the workshop. Nothing is broken, but
to change the planner you must walk past the model picker, the document cards and
the speech code, and two agents cannot work in the room at once. The plan is to put
up walls where the work already divides, WITHOUT moving any tool to a different
bench in the same step. First walls (pure moves, provably nothing changes). Then,
one bench at a time, better benches (the changes that give speed and clarity).

## 2. Measured facts (2026-11-11, AST audit; re-run K0 before relying on them)

- `agent_kernel.py`: 23,132 lines, 1.1 MB. `AgentKernel` = lines 1586-22784,
  242 methods (240 sync, 2 async), 132 instance attributes.
- 36 module functions before the class (lines 51-1583). Seven take `self`/`owner` as a
  plain first argument (`_der_start_node`, `_der_take_finished`, `_der_claim`,
  `_der_release`, `_der_claim_lock`, `_der_post_step`, `_der_settle_split`) - this is
  the existing pattern for code that test stand-ins must reach (CLAUDE.md "STAND-INS").
- Largest methods: `_execute_plan_der` 1,559 lines; `_der_finalize_step` 1,445;
  `process_text_message` 1,056; `_der_handle_step_failure` 516; `_plan_task` 463;
  `_der_run_node` 456; `set_model_selection` 453; `_assemble_direct_context` 435.
- Imports: 29 at module level, 430 lazy inside functions (`event_bus` 35 times).
- Coupling: 66 attributes are touched by one cluster only, 42 by two, 8 by five or
  more. The shared core is small: `conversation_id` (14 clusters), `session_id` (13),
  `_memory_interface` (11), `_router` (8), `_tool_bridge` (6), `_mcm_orch` (6).
- Outside users: `AgentKernel` is imported by 194 files; 28 other names are imported
  from the module (list in section 5). Tests bind methods onto stand-ins
  (`AgentKernel.X.__get__(stub)` in 25 files; `AgentKernel.X(stub, ...)` at 37 sites),
  patch module attributes by string path, and about 49 test files read
  `agent_kernel.py` AS TEXT and scan it.
- Five module globals are REBOUND at runtime (`global` statements):
  `_internet_access_enabled`, `_desktop_control_enabled`, `_agent_kernel_instances`
  (two sites), `_session_active_conversation`.
- Findings met during the audit (fix in Stage C, never inside a move):
  F1 four legacy `reasoning_model.generate` calls bypass `InferenceRouter.generate`
  (lines 5547, 10556, 10568, 21856) - the one-chokepoint rule; F2 `dcp.py:51` imports
  a method as a module function, the `except` always fires (removed by CLM-9);
  F3 `AgentKernel._VERIFIER` is assigned at runtime (line 18631) - class-level shared
  state.

## 3. What this plan can and cannot give

- ORGANIZATION: yes, from Stage B. One domain per file, files of 400-3,000 lines,
  two agents can work on two domains at once, a change's blast radius is visible.
- PERFORMANCE: a pure move does not make a turn faster. Stage B must only prove it
  makes nothing SLOWER (import time, reply_s). Speed comes in Stage C, where each
  seam is a measured-loop task: explicit run state (fewer `getattr(self, ...)` probes
  and no cross-turn leakage), the giant loop bodies cut along their phases (so a stall
  is attributable to a phase in a stack dump), hot lazy imports hoisted only where
  measured. Any claim of a speed-up needs a before/after number under the same
  conditions.

## 4. Target layout

`agent_kernel.py` stays the public face. Everything that imports from it today keeps
working without an edit.

```
backend/agent/
  agent_kernel.py          FACADE: class AgentKernel(<mixins>): __init__, lifecycle;
                           module singletons + factories (get_agent_kernel, ...);
                           re-exports of every name in section 5.
  kernel/
    __init__.py            kernel_source() (section 6, G5). Nothing else.
    models.py     PART 1   ModelsMixin     model_config + vps_gateway              (~1,060 lines)
    surface.py    PART 2   SurfaceMixin    documents_cards + narration_tts         (~2,560)
    context.py    PART 3   ContextMixin    context_prompt + tokens_budget          (~1,390)  <- CLM call sites
    turn.py       PART 4   TurnMixin       transport_dispatch + process_text_message + direct reply + tools (~2,700)
    planning.py   PART 5   PlanningMixin   planning_routing + goal_contract + memory_facts (~3,270)
    der/          PART 6   the execution engine (~9,600 lines - too large for one file)
      run.py               DerRunMixin      _execute_plan_der, _der_finalize_step  (~1,820)
      node.py              DerNodeMixin     der_run_node                           (~3,060)
      physics.py           DerPhysicsMixin  der_physics_split                      (~1,640)
      recovery.py          DerRecoveryMixin der_recover + der_steer                (~1,810)
      report.py            DerReportMixin   der_synth_report + der_trace_recall    (~1,300)
```

SIX PARTS, not twelve (owner review, 2026-11-11). The six parts are the six things
the kernel does: pick a model, show and speak, build the prompt, take a turn, plan,
execute. Part 6 alone is about 45 % of the class, so it is one PART kept in five
files; a single 9,600-line file would recreate the problem this plan removes. The
rule for file size: a file holds one job and stays under about 3,300 lines. Small
clusters (tools 700, goal 500) do not get a file of their own; they live with their
main caller. K0 may merge further if the map shows a file with no clear job.

- The module functions at lines 51-1583 move WITH the domain that calls them (the
  K0 map assigns each one). Helpers used by several domains go to the domain that
  owns their data; if there is no owner they stay in the facade. No `utils.py`.
- Line counts come from a name-regex clustering; they are estimates. The
  authoritative assignment is the K0 map (section 7).
- Existing extracted modules stay where they are (`der_loop.py`, `goal_contract.py`,
  `tool_decision.py`, `event_emit.py`, `der_constants.py`, `node_executor.py`,
  `streaming.py`). `kernel/der/run.py` is named so it does not collide with
  `der_loop.py`.
- Why mixins: tests and callers rely on `AgentKernel.<method>` being a real class
  attribute. A mixin base keeps that true with zero call-site change. It is the
  minimum mechanism, not the end state: Stage C replaces shared-everything access with
  explicit state objects where it pays.

## 5. The public surface that must not change

Names imported from `backend.agent.agent_kernel` by other files (keep importable from
the facade for the whole program):
`AgentKernel`, `get_agent_kernel`, `set_global_internet_access`,
`get_global_internet_access`, `_agent_kernel_instances`, `get_active_kernel`,
`set_active_conversation`, `cleanup_agent_kernel`, `peek_active_kernel`,
`get_desktop_control_enabled`, `set_desktop_control_enabled`, `DER_TOKEN_BUDGETS`,
`_session_active_conversation`, `_der_neighbors_block`, `_memory_events_submit`,
`_step_tool`, `_claims_missing`, `_node_failed_after_change`, `_gc_coverage_label`,
`_BROWSER_ACTION_RE`, `_MONITOR_STATEMENT_CHARS`, `_monitor_statement`, `TaskContext`,
`_step_evidence_cap`, `_recent_user_turn_texts`, `_resolve_effective_key`,
`_remember_turn_urls`, `ResolvedWindow`, `resolve_context_window` (dcp only; F2).

String patch targets used by tests: `backend.agent.get_agent_kernel`,
`backend.agent.agent_kernel.get_agent_kernel`, `...peek_active_kernel`,
`..._session_active_conversation`, `...debit_work_units`,
`AgentKernel._get_verifier`, `AgentKernel._card_envelope`.

## 6. The four traps, and the guard for each

A move that looks mechanical can still change behavior in exactly four ways. Each
has a guard that is written BEFORE the first move and proven to fail on a seeded
mistake.

**Trap 1 - a body changes while it moves.**
G1 `scripts/kernel_split_check.py manifest`: for every function reachable as
`AgentKernel.<name>` (through the MRO) and every module function, store
`sha256(ast.dump(node))` (decorators included, docstring included). After a move:
the name set is identical, every hash is identical, and no name is defined in two
mixins (an MRO shadow is an error). The baseline manifest is checked in at
`docs/architecture/kernel_manifest.json`.

**Trap 2 - a moved function reads a module global from its NEW module.**
A function looks up globals in the module where it is defined. After a move,
`_internet_access_enabled` or a patched `debit_work_units` would be read from
`kernel/x.py`, not from `agent_kernel` - a test patch silently stops applying, and a
rebound global is read as a stale copy.
G2 `scripts/kernel_split_check.py globals`: for every moved function, every global
name it loads must resolve, in its new module, to THE SAME OBJECT as in
`agent_kernel` (`is`), and must not be one of (a) the five rebound globals or (b) a
string-patch target. Names in (a) and (b) are reached only through an attribute on
the owning module at call time (`_ak.get_global_internet_access()`, or
`import backend.agent.agent_kernel as _ak; _ak.debit_work_units(...)`). That
late-lookup line is the ONE permitted body edit in a move; G1 lists each such edit
explicitly in an allow-list with the before/after hash, reviewed by a human or the
Director.
The better end state for (a) is one owner module for the state with getter functions
(the getters already exist); that is a Stage C task.

**Trap 3 - import order, cycles, and import cost.**
`kernel/*.py` must never import `agent_kernel` at module level (cycle); the facade
imports the mixins. A mixin module imports at top level only what the original file
imported at top level for those functions; every lazy import stays lazy, at its
original place.
G3: `python -X importtime -c "import backend.agent.agent_kernel"` total within +5 %
of the baseline (three runs, warm, quiet machine); `python -c` import in a fresh
interpreter with `-W error` shows no new warning; no ML/GPU module in `sys.modules`
after import (existing rule).

**Trap 4 - behavior that only the running system shows.**
G4 targeted tests + the live gate. Targeted: the 25 method-binding files, the files
with string patches, the contract suite for the moved domain, `test_answer_path_standards`.
Never the full suite. Live: `evals/run_evals.py` on a fixed cohort (coding 8,
memory 3, research 10; detached), same model, same conditions, baseline commit vs
move commit: pass counts equal, `reply_s` medians inside the standards' tolerance.
Baseline any failure on the parent commit before blaming the move.

**The text-scan tests (G5).** About 49 test files read `agent_kernel.py` as text
(for example `test_der_phase0.py:197`, `test_domain2_voice.py:268`,
`test_context_usage_parity.py:25`, `test_lmstudio_integration.py:25`). When code
moves, the text they look for is in another file.
`backend/agent/kernel/__init__.py` provides `kernel_source() -> str`: the facade
text followed by every `kernel/*.py` text, in a fixed order. A scan test changes ONE
thing: the place it reads from. Its patterns and assertions do not change. This is
a test INPUT change, so it is done in its own commit, before the first move (when
`kernel_source()` equals the single file and every scan test must pass unchanged
in result), and every touched test is listed in the commit message (owner rule
2026-10-25). `inspect.getsource(AgentKernel._x)` tests (19 files) need no change.
A scan that depends on LINE NUMBERS or on two patterns being in one file is a
finding: report it, do not adapt it silently.

## 6b. Corrections and resolutions from the K0 map (2026-11-11)

K0 ran (`scripts/kernel_split_check.py`, `kernel_split_map.json`,
`kernel_manifest.json`: 242 methods + 60 module functions + 1 class = 303 entries).
It corrected section 2 and exposed five design points. These resolutions OVERRIDE
any earlier line of this file that disagrees.

Corrected facts:
- 60 module functions (51 before the class, 9 factories/setters after it), not 36.
- 18 module functions take `self` / `owner` / `kernel` first, not 7.
- 4 rebound globals (`_internet_access_enabled`, `_desktop_control_enabled`,
  `_agent_kernel_instances`, `_session_active_conversation`); `_update_counters` has
  a `global` statement but is only mutated.
- 29 class-level statements sit between methods (`_VERIFIER`, `_DER_*_TOOLS`,
  `_MODEL_ALIASES`, `_KNOWN_CONTEXT_WINDOWS`, ...).
- `resolve_context_window` is a method; `DER_TOKEN_BUDGETS`, `ResolvedWindow`,
  `debit_work_units` are IMPORTS of the kernel module (re-export = keep the import).
- Measured sizes: models 1,044; surface 2,441; context 1,244; turn 2,737; planning
  2,629; der/node 2,144; der/physics 1,294; der/recovery 2,142; der/report 1,602;
  der/run 3,740; facade 918.

Resolutions:

- **RES-1 `AgentKernel` by name inside moved code (19 functions, ~58 uses).** A moved
  module may not import the facade (R5), and rewriting the uses would break G1.
  Resolution: the facade INJECTS the name. After `class AgentKernel` is defined, the
  facade runs one loop: `for _m in _KERNEL_MODULES: _m.AgentKernel = AgentKernel`.
  A function resolves its globals at call time, so every moved body runs unchanged
  and sees the same class object. No body edit, no cycle. G2 treats `AgentKernel` as
  the one facade-injected name and checks the facade performs the injection for every
  kernel module.
- **RES-2 shared helpers, shared module state, the logger -> one leaf module
  `kernel/base.py`.** It imports nothing from the kernel package or the facade. It
  holds ONLY what the map shows is loaded by three or more parts: the module-level
  locks and registries (`_CLAIM_LOCKS`, `_CLAIM_LOCKS_GUARD`, `_SCREEN_CLAIM`,
  `_DER_NODE_QUOTA`, `_NODE_CLAIMS`, `_update_counters` + its lock,
  `_der_recovery_lock`, `_FILL_NO_TURN`), the shared helpers (`_emit_event`,
  `_step_tool`, `_step_calls`, `_step_decisive_call`, the `_turn_in_flight`
  decorator) and `logger`. Every part and the facade import these BY NAME from
  `base` (same object everywhere; none is rebound). G2 fails if any module defines
  its own copy. This replaces "no utils.py": `base.py` is not a place for new code;
  its content list is generated by the map, and adding to it needs the same
  three-parts evidence.
- **RES-3 the logger name.** `base.py` has
  `logger = logging.getLogger("backend.agent.agent_kernel")`. Log names do not
  change; the three tests that capture that logger need no edit.
- **RES-4 rebound globals and patched names stay with the facade.** The functions
  that read the four rebound globals stay in the facade (they are the factories and
  getters). A moved function that needs one reaches it by a late lookup of the
  facade module inside the function, allow-listed (Trap 2). K0b lists every such function; the expected count
  is small (one known: a models function loading `_agent_kernel_instances` - keep
  that function in the facade instead). The patch-target list is not hand-written:
  the guard SCANS `backend/tests` for `patch("backend.agent.agent_kernel.X")`,
  `monkeypatch.setattr(agent_kernel, "X")` and equal forms, and treats every found
  X as a patched name.
- **RES-5 `der/run` is too large (3,740 lines).** The two giant methods are two
  jobs: run the loop, finish a step. So: `der/run.py` (`_execute_plan_der` and the
  loop plumbing) and `der/finalize.py` (`_der_finalize_step`, `_der_post_step`,
  `_der_plan_next_step`, envelope build if the map agrees). Each is then about
  1,600-2,000 lines. The DER part has SIX files. The 3,300-line rule holds
  everywhere except where one method alone exceeds it - none does.
- **RES-6 class-level statements stay in the facade class** (R4). The mover cuts
  methods around them. A mixin method reaches them through `self` as today.

## 6c. Resolutions from the mover trial (2026-11-11)

The byte mover exists (`kernel_split_check.py move`, `accounting`). Trial on a copy:
`base` + `models` moved; manifest OK (303 match), globals OK, byte accounting OK
(23,132 lines: 23,129 exact, 2 edited, 1 transformed), and the moved copy IMPORTS
through an overlay of the real tree with the same `dir(AgentKernel)` (300 names),
every section-5 name importable, logger name unchanged, all base objects identical.
These resolutions override earlier lines that disagree.

- **RES-7 patched names reach moved code by PROPAGATION, not by body edits.** Tests
  patch `agent_kernel.TurnMetrics`, `.debit_work_units`, `._emit_event`,
  `._agent_kernel_instances`, `._session_active_conversation`; moved functions would
  read their own module's binding and go blind. Late lookups would mean about ten
  body edits inside the most sensitive functions (`_execute_plan_der`,
  `_der_finalize_step`, `process_text_message`). Instead the facade module gets a
  `ModuleType` subclass whose `__setattr__` forwards an assignment of a name in the
  generated `_PROPAGATE` table to every kernel module that binds that name (so
  `mock.patch`, `monkeypatch.setattr` and plain assignment all reach the moved code,
  and the restore does too). The import-time injection of `AgentKernel` (RES-1) uses
  the same table. Zero body edits, zero test edits. Limits, stated: a
  `global X; X = v` STORE inside facade code and `patch.dict` on the module dict do
  not pass through `__setattr__` - so functions that STORE a rebound global stay in
  the facade, and G2 fails if a moved function loads a name that facade code stores
  via `global`. This shim is transitional; C4 (one owner for the state) removes it.
- **RES-8 single-part constants move with their part** (`--own-constants` is the
  default). The facade re-exports them.
- **RES-9 the three `__file__` readers stay in the facade**
  (`_get_developer_context`, `_bound_external_project`, `_log_route_shadow`): one
  directory deeper their path arithmetic would change silently. Stage C may move
  them with an explicit path.
- **RES-10 lazy relative imports become absolute** in the four moved functions that
  have them. Same module object, different spelling; each is an allow-listed edit
  written by the mover.
- **RES-11 the DER try/except import block lives once, in `base.py`.** Every part
  imports those names from `base`; no duplicate fallback definitions.
- **RES-12 the full split is rehearsed on a copy first.** All moves run in order on
  an overlay, guards after each move, import test at the end. The real moves are
  then a replay of a rehearsed script, one commit each.

## 6d. Result of the full rehearsal (K5, 2026-11-11)

All 12 moves ran one at a time on an overlay copy (order: base, models, surface,
context, der/report, der/physics, der/recovery, planning, turn, der/node,
der/finalize, der/run). After EVERY move: manifest OK, globals OK, byte accounting
OK, all files compile, a fresh-process import gives the same `dir(AgentKernel)`
(300 names), all 30 section-5 names import, logger name unchanged. The tool needed
three fixes on the way (an except-only name re-exported; a bare `global` taken for a
store; modules that only BIND a patched name missing from the propagation table);
each was a tool fix, never a hand edit of the output.

- Bytes: 23,132 original lines -> 23,126 exact, 5 edited (the class line + 4
  relative imports made absolute), 1 transformed (the logger name).
- Allow-list: 3 methods (`_local_openai_base`, `resolve_context_window_with_source`,
  `_der_physics_step`), relative import made absolute.
- Final sizes: facade 2,275; base 249; models 1,085; surface 2,472; context 1,253;
  turn 2,789; planning 2,320; der/run 1,959; der/finalize 2,464; der/node 1,858;
  der/physics 1,336; der/recovery 2,195; der/report 1,682.
- Propagation: `mock.patch`, `patch.object`, `monkeypatch` (attribute and string) and
  plain assignment on the facade reach every kernel module that binds the name, and
  the restore does too (5 patched names).
- Binding: `AgentKernel.X.__get__(object())` works and `inspect.getsource` of the
  method equals the original text for 12 methods across the parts.
- G3 import time, warm, median of 3: real 1.158 s, split 1.201 s (+3.7 %, limit +5 %).
- Tests, real vs split copy: five of six files equal (53 tests). ONE difference, in
  `test_goal_met_skips_consult_contract.py::test_the_continuation_gate_reads_it`:
  it calls `inspect.getsource(AgentKernel)` (the whole CLASS) and searches the text;
  after the split the class text is only the facade.

Resolutions:

- **RES-13 class-level and module-level source reads join K2.** Six test sites read
  the whole class or module through `inspect.getsource`:
  `test_goal_contract_own_terms_contract.py:164`,
  `test_goal_met_skips_consult_contract.py:40`,
  `test_node_evidence_every_call_contract.py:67` (class);
  `test_browser_module_optional.py:47`, `test_partial_artifacts_contract.py:51`,
  `test_der_forward_only_contract.py:138` (module). K2 switches each to
  `kernel_source()`, like the file-path scans: the read location changes, the
  searched patterns and assertions do not. Stated per test in the K2 commit.
  `inspect.getsource(AgentKernel._method)` reads need no change (proven).
- **RES-14 the facade target is 2,300 lines, not 1,500.** What stays is by rule:
  `__init__` + lifecycle methods, the factories and state after the class, the three
  `__file__` readers, 29 class-level statements, imports, and the generated blocks.
  The DONE line of this file reads "under 2,300 lines". Stage C may shrink it
  (`__init__` and `_initialize_components` are the bulk).
- **RES-15 a `global X` that is never stored is not a rebind.** Only
  `_internet_access_enabled` and `_desktop_control_enabled` are truly rebound, each by
  its facade setter; their readers stay in the facade. `set_model_selection` moves to
  models.
- **Known limit, accepted:** propagation covers `setattr`-style patches only.
  `patch.dict(agent_kernel.__dict__)` and module reload are not forwarded; the scan
  found no such use but cannot prove there is none. G4 (the targeted tests on the
  real move) is the check.

## 7. Method - three stages

### Stage A - guards and map (no production code moves)

- **K0 map.** Check in `scripts/kernel_split_check.py` with sub-commands `map`,
  `manifest`, `globals`. `map` writes `docs/architecture/kernel_split_map.json`:
  for every method and module function - target module, line span, attributes read
  and written, globals loaded, methods called. A human-readable table is generated
  from it into section 10 of this file. Assignment rule: a method goes to the domain
  of the DATA it mainly writes; ties go to the domain of its main caller. Every
  method has exactly one target.
  DONE = the map covers 242 methods + 36 functions, zero unassigned.
- **K1 guards.** G1-G3 in the script; prove each fails on a seeded mistake (change
  one character in a copied body; shadow one global; add a module-level cycle).
  DONE = three recorded failures, then green on the untouched tree.
- **K2 scan tests.** `kernel/__init__.py` with `kernel_source()`; switch the scan
  tests to it (G5).
  DONE = every switched test has the same result as on the parent commit.
- **K3 baseline.** Record G3 import time and the G4 cohort on the commit that Stage B
  starts from. File: `evals/results/kernel-split-baseline-<date>.json`.
- **K4 text encoding.** The file contains repaired mojibake regions (PROGRESS B17) and
  some still-garbled comment lines. Moves are done by a script that copies BYTES by
  line span (never by an editor round-trip, never PowerShell `Get-Content -Raw`).
  DONE = the mover reproduces the original file byte-for-byte when asked to move
  nothing.

### Stage B - move only, one domain per commit

Order (least coupled first; the two mutually calling DER domains last):

| Move | Domain | Why here |
|---|---|---|
| M1 | models | self-contained (calls mostly itself) |
| M2 | surface | called by many, calls few |
| M3 | context | unblocks CLM (gate G-KERNEL) |
| M4 | der/report | leaf of the DER part |
| M5 | der/physics | called by node + run; calls few |
| M6 | der/recovery | |
| M7 | planning (+ goal) | large, self-contained |
| M8 | turn (+ tools) | the entry path |
| M9 | der/node | mutual calls with der/run |
| M10 | der/run | last |

Per-move checklist (the whole procedure; do not improvise):

1. Rebase on `main`. Confirm nobody else has the kernel open (rule R9).
2. Run the mover for this domain from the K0 map: creates `kernel/<domain>.py` with
   `class <Domain>Mixin:` and the spans; removes the spans from the facade; adds the
   mixin to `AgentKernel`'s bases; copies the needed top-level imports.
3. Apply the allow-listed late-lookup edits for Trap 2, if any, and record them.
4. G1, G2, G3.
5. G4 targeted tests for this domain.
6. G4 live cohort (detached). Compare with K3.
7. Commit: `refactor(kernel): move <domain> to kernel/<domain>.py (move-only)` with
   the manifest diff summary (N functions moved, 0 hashes changed, late-lookups: list).
8. Tick the status table; `record_edit`; one pin per move with the numbers.
9. If any guard is red: revert the move commit. Do not fix forward inside a move.

Rules for every agent:

- R1 One domain per commit. A move commit contains no other change.
- R2 No body edit except allow-listed late lookups.
- R3 No rename, no signature change, no reordering inside a function.
- R4 A mixin has no `__init__`, no class attributes of its own, no state.
- R5 `kernel/*.py` never imports `agent_kernel` at module level.
- R6 Lazy imports stay lazy and stay where they are.
- R7 The facade re-exports every section 5 name until Stage C says otherwise.
- R8 Never modify a test to make a move pass. The only test edits are the G5 read
  location (K2) - stated in the commit.
- R9 The kernel is edited almost every session. A move is short-lived: start from
  fresh `main`, land the same day, and no feature branch edits the moved spans
  meanwhile. Announce the move in PROGRESS "START HERE" before starting.
- R10 A finding met during a move goes to the findings list (section 8), not into
  the commit.

### Stage C - seams (behavior-sensitive; each is its own measured-loop task)

Only after Stage B is complete for the domain concerned. Each item: DONE = / NOT
THIS =, baseline, cause, change, same-cohort proof, a guard that fails on the old
state, a Standards row.

| Seam | What | Why it pays |
|---|---|---|
| C1 run state | The per-run DER counters and scratch attributes on `self` (`_der_*`; the K0 map lists which are written per run) become one `DerRunState` object created per run and passed/held explicitly | Removes shared mutable state across turns (quality-check rule), removes defensive `getattr(self, "...", default)` probes on the hot path, makes stand-ins trivial (pass a state, not a kernel) |
| C2 phase cuts | `_execute_plan_der` (1,559), `_der_finalize_step` (1,445), `process_text_message` (1,056) are cut along their existing phase comments into named functions of the same module, same order, same locals passed explicitly | A stall is attributable to a phase in a stack dump; each phase becomes testable; no behavior change intended, proven by the replay harness (`scripts/validate_der_*.py`) and the cohort |
| C3 one chokepoint | F1: route the four legacy `reasoning_model.generate` sites through `InferenceRouter.generate`, or delete them if dead | Phase gate and priority lane apply to every model call |
| C4 global state owner | The five rebound globals move to one owner with getters; the late-lookup lines from Trap 2 disappear | Ends the patch-target fragility |
| C5 hot lazy imports | Measure (stack dumps, `importtime`) which of the 430 in-function imports run on the answer path per call; hoist only those that are cheap at import and hot at run | Measured only; otherwise leave |
| C6 `_VERIFIER` | F3: class-level runtime assignment becomes instance or module owned | Shared state across kernels |
| C7 collaborators | Where a domain's attributes are private to it (66 attributes are single-cluster), the mixin MAY become a plain object held by the kernel (`self.models`, `self.surface`) with thin delegating methods kept on `AgentKernel` | The real end state for self-contained domains. Do it per domain, only when a concrete change needs it. Not a program-wide goal |

## 8. Findings list (append; never fix inside a move)

| # | Finding | Evidence | Planned in |
|---|---|---|---|
| F1 | 4 model calls bypass the router chokepoint | `agent_kernel.py` 5547, 10556, 10568, 21856 | C3 |
| F2 | `dcp.py` silent fallback (method imported as function) | `dcp.py:51-54` | CLM-9 |
| F3 | `AgentKernel._VERIFIER` assigned at runtime on the class | `agent_kernel.py:18631` | C6 |
| F4 | Three token estimators, no authority | CLM requirements U4 | CLM-4 |
| F5 | `behavioral/test_envelope_loop_behavior.py` is flaky on the unsplit code (`OSError: Bad file descriptor`, about half the runs) - shared state, not the split | K2 runs 2026-11-11 | own fix; never re-run to green |
| F6 | The two `test_lmstudio_integration.py` alias fixtures parse the class-level `_MODEL_ALIASES`; valid only while class-level statements stay in the facade (RES-6) | K2b | switch to `kernel_tree()` if Stage C moves them |
| F7 | No test isolation of `data/iris_config.json`: a test that saves the config wrote the real file (17:35, eight providers lost, provider without key, every eval 401) | K3 first run 0/21 | FIXED: `iris_config._test_run_config_path` (private copy under pytest). Residual: `main.py:1640` has its own writer |
| F8 | On the unsplit code six coding tasks are 2-7x slower than `evals/standards.json` (for example c10 100 s vs 15.9 s) with the present provider | K3 | not the split; own investigation (provider speed or a fixed ~30 s offset) |

## 9. STATUS TABLE (the resume point)

| Step | State | Commit | Date | Evidence (guards, cohort numbers) |
|---|---|---|---|---|
| K0 map | DONE (first pass; K0b revises targets per 6b) | uncommitted | 2026-11-11 | 303 entries, 0 unassigned |
| K1 guards | DONE (G1 manifest, G2 globals proven on seeded mistakes: body change, shadow, missing global, by-name rebound import; G3 not yet run) | uncommitted | 2026-11-11 | `manifest --check OK: 303 entries match` on the real tree |
| K0b revise per 6b | DONE (12 targets + facade 1,394 lines; patched-names scan) | uncommitted | 2026-11-11 | map regenerated |
| K4 byte mover | DONE; trial base+models on a copy: guards green, overlay import equal | uncommitted | 2026-11-11 | section 6c |
| K5 full rehearsal on a copy (RES-12) | DONE: 12 moves green on a copy; 1 test difference (RES-13) | uncommitted | 2026-11-11 | section 6d |
| K2 scan tests -> `kernel_source()` | DONE: 29 test files, read location only | ab8ed2bf | 2026-11-11 | before = after per file |
| K2b AST / order / line readers -> `kernel_tree()`, `kernel_function_source()` | DONE: 22 test files + `scripts/validate_switcher.py`; baseline = after = full-split overlay; wider binding set 60 files 479 pass / 13 fail on both trees, same names | 66363913 | 2026-11-11 | `ast.dump(kernel_tree())` equals the single-file parse |
| K3 baseline | DONE: cohort 21/21 pass (coding 8/8 c01 c03 c05 c08 c10 c11 c12 c15; research 10/10 r01-r10; memory 3/3), provider opencodego / deepseek-v4.1-flash, warm. reply_s coding 72-168 s (median 100), research 23-137 s, memory 54-70 s. Import time with the backend up: 1.94-1.96 s (3 runs). Compare later runs with THIS file under the same conditions, never with evals/standards.json (see F8) | (this commit) | 2026-11-11 | `evals/results/kernel-split-baseline-2026-11-11.json` |
| M0 base | not started | | | |
| M1 models | not started | | | |
| M2 surface | not started | | | |
| M3 context | not started | | | |
| M4 der/report | not started | | | |
| M5 der/physics | not started | | | |
| M6 der/recovery | not started | | | |
| M7 planning | not started | | | |
| M8 turn | not started | | | |
| M9 der/node | not started | | | |
| M10 der/finalize | not started | | | |
| M11 der/run | not started | | | |
| C1-C7 | not started (each gets its own row when begun) | | | |

## 10. Domain map (generated by K0 - empty until K0 runs)

The 2026-11-11 audit clusters (name-regex, class methods only; methods / lines):
der_run_node 11 / 3,059; planning_routing 26 / 2,768; der_loop_steps 5 / 1,820;
der_physics_split 18 / 1,644; documents_cards 27 / 1,549; der_recover 7 / 1,109;
model_config 29 / 1,031; context_prompt 16 / 1,022; transport_dispatch 11 / 1,015;
narration_tts 11 / 1,008; der_synth_report 18 / 966; lifecycle 12 / 753; tools
9 / 702; der_steer 6 / 701; goal_contract 11 / 382; tokens_budget 12 / 366;
der_trace_recall 8 / 338; memory_facts 3 / 122; vps_gateway 2 / 32.
Heaviest cross-domain call edges: der_steer -> documents_cards 21; der_run_node ->
documents_cards 21; der_loop_steps -> documents_cards 13; transport -> context 12;
der_run_node -> der_physics 8; narration -> tokens 8.

## 11. How this joins the CLM spec

- M3 (context) is the gate G-KERNEL of `specs/clm-memory/tasks.md`. Stage A + M1-M3
  is the shortest path that lets CLM start in a small file.
- CLM adds its logic in `backend/agent/context_view.py` and `context_gauge.py`
  (not in `kernel/`): the kernel holds call sites only. CLM-4 deletes
  `_count_tokens` / `_DIRECT_CTX_BUDGET` - that is a CLM task commit, never a move
  commit (R1).
- No CLM task that touches kernel call sites runs during a move commit (R9).
