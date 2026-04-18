Requirements — Agent Loop Upgrade + DER Loop
Mycelium + Kyudo + Pacman Integration · Director · Explorer · Reviewer
March 2026 · IRISVOICE / IRIS / Torus Network
Introduction
This spec covers two things built together:

Mycelium/Kyudo/Pacman integration into the existing agent execution pipeline — structured context, task classification, live behavioral signals, compounding cost reduction.
DER Loop — the existing brain model becomes the Director, the existing tool agent becomes the Explorer, a new Reviewer is added as a validation membrane. One model. One graph. Three roles.
All changes are additive. No existing behavior is removed.
No existing method signature is changed.

Success criteria:

Agent completes tasks normally with Mycelium unavailable
Director re-reads graph after every Explorer step
Reviewer never blocks Explorer on its own failure
All Mycelium calls are non-blocking
Existing test suite passes with zero regressions
Requirements
Requirement 1: ContextPackage Dataclass
THE SYSTEM SHALL define ContextPackage as a dataclass in IRISVOICE/backend/memory/mycelium/interface.py above MyceliumInterface
SHALL have all fields: mycelium_path, topology_path, manifest, tier1_directives, tier2_predictions, tier3_failures, active_contracts, gradient_warnings, causal_context, ambient_signals, topology_position, task_class, _registered_addresses
SHALL implement get_system_zone_content() returning SYSTEM_ZONE content in biological priority order: contracts → gradient warnings → causal → directives → MYCELIUM path → TOPOLOGY → ambient
SHALL implement get_tier2_predictions() returning self.tier2_predictions or ""
SHALL implement get_tier3_failures() returning self.tier3_failures or ""
SHALL implement register_address(url, token_count, summary) writing to self.manifest and appending to self._registered_addresses
SHALL implement topology_primitive as a @property parsing primitives:[{name}] from self.topology_path, returning "unknown" if absent
Requirement 2: get_task_context_package()
THE SYSTEM SHALL add get_task_context_package(task, session_id, space_subset=None) to MemoryInterface — new method, does not change get_task_context()
get_task_context() SHALL remain completely unchanged
WHEN self._mycelium is None OR is_mature() is False, SHALL return (self.get_task_context(task, session_id), False)
WHEN mature, SHALL call self._mycelium.get_context_path() with task_text=task, session_id=session_id, space_subset=space_subset
WHEN get_context_path() returns a string or raises, SHALL return (prose_str, False) — never propagating the exception
SHALL never raise under any circumstances
Requirement 3: Task Classification Before Context Assembly
THE SYSTEM SHALL instantiate TaskClassifier once in AgentKernel.__init__() as self._task_classifier = TaskClassifier()
IN handle(), classification SHALL occur BEFORE get_task_context_package()
WHEN classify() returns empty/unknown, SHALL default task_class = "full" and space_subset to all six non-toolpath spaces
space_subset SHALL be passed into get_task_context_package()
Requirement 4: _plan_task() Safe Defaults
SHALL add is_mature: bool = False with safe default
SHALL add task_class: str = "full" with safe default
SHALL add context_package = None with safe default
All existing callers passing only text and context SHALL work unchanged
Requirement 5: Maturity-Aware Planning Temperature
WHEN is_mature=True, SHALL use temperature=0.1
WHEN is_mature=False, SHALL use temperature=0.25
Requirement 6: _build_planning_prompt()
THE SYSTEM SHALL create _build_planning_prompt() on AgentKernel
SHALL inject sections in this order: tier1_directives → BEHAVIORAL PREDICTIONS → AVAILABLE SKILLS → AVAILABLE PERMISSIONS → FAILURE WARNINGS → task divider block → RULES + JSON instruction
SHALL inject failure_warnings exactly once — never duplicated
WHEN tier1_directives is empty, SHALL skip that section
Requirement 7: Task Class Strategy Hints
SHALL define TASK_CLASS_STRATEGY_HINTS inside _plan_task() with entries for quick_edit, code_task, research_task, planning_task, full
SHALL select hint matching task_class, defaulting to "full" for unknowns
Hints are suggestions — model may override
Requirement 8: Topology-Aware Strategy Guidance
SHALL define TOPOLOGY_STRATEGY_HINTS inside _plan_task() with entries for core, acquisition, exploration, transfer, orbit, evolution
WHEN is_mature=True and context_package not None, SHALL append topology hint to strategy_hint based on context_package.topology_primitive
WHEN primitive is "unknown", SHALL append nothing
Requirement 9: Structured Context in Planning Prompt
WHEN is_mature=True and context_package not None, SHALL use get_system_zone_content(), get_tier2_predictions(), get_tier3_failures()
WHEN get_tier3_failures() returns empty, SHALL fall back to _get_failure_warnings(safe_task)
WHEN immature, SHALL use prose string as tier1_directives, empty behavior_preds, and _get_failure_warnings() for failures
Requirement 10: ResolutionEncoder
THE SYSTEM SHALL create ResolutionEncoder in IRISVOICE/backend/memory/mycelium/interpreter.py
encode_with_resolution(failure, conn=None) SHALL produce structured format with resolution when available
SHALL use "unknown" for missing keys — never raise KeyError
SHALL return prose fallback on any exception — never raise
Same file SHALL contain CoordinateInterpreter and BehavioralPredictor as stubs
Requirement 11: _get_failure_warnings() Uses ResolutionEncoder
SHALL import ResolutionEncoder from backend.memory.mycelium.interpreter
SHALL retrieve up to 2 past failures via retrieve_failures(task, limit=2)
SHALL pass self.memory.episodic.db as conn
SHALL return "None" string when no failures or on any exception
Requirement 12: Plan HZA Address Headers
to_context_string() SHALL have [system://plan/{plan_id[:8]}] as first line
Each step SHALL have [system://plan/{plan_id[:8]}/step/{step_id}] before description
SHALL use ASCII markers only: [ ] [~] [+] [x] [s] [b]
All existing content SHALL be preserved
Requirement 13: Plan Address Registration
AFTER plan injection AND when is_mature=True, SHALL call context_package.register_address() with plan URL, token count, summary
SHALL guard with hasattr(context_package, 'register_address')
SHALL wrap in try/except with silent pass
Requirement 14: Strategy Signal Ingestion
AFTER _plan_task() returns, SHALL call mycelium_ingest_statement() with statement=f"task required {plan.strategy}: {plan.reasoning}"
SHALL wrap in try/except Exception: pass
Requirement 15: Tool Call Signal Ingestion
SHALL use proxy method mycelium_ingest_tool_call() — never direct _mycelium
SHALL ingest after every step (success and failure)
SHALL ingest on reflection failure with success=False
Both ingest blocks SHALL be in try/except Exception: pass
Requirement 16: Outcome Recording in Causal Order
SHALL compute score using len(plan.steps) — NOT plan.total_steps
SHALL guard against zero division: score = len(c) / total if total > 0 else 0.0
SHALL call record_outcome() FIRST, crystallize_landmark() SECOND, clear_session() THIRD
ALL THREE in separate try/except Exception: pass blocks
Requirement 17: Plan Statistics Recording
SHALL call mycelium_record_plan_stats() after outcome calls
SHALL wrap in try/except Exception: pass
record_plan_stats() SHALL have complete SQL INSERT with self._conn.commit()
Requirement 18: mycelium_plan_stats Table
SHALL add CREATE TABLE IF NOT EXISTS mycelium_plan_stats to db.py
SHALL have all 11 columns including graph_mature INTEGER DEFAULT 0
SHALL create three indexes: session, task_class, outcome
_ensure_tables() in MyceliumInterface SHALL create same table for existing databases
Requirement 19: Proxy Methods on MemoryInterface
SHALL add all seven proxy methods: get_task_context_package, mycelium_ingest_tool_call, mycelium_record_outcome, mycelium_crystallize_landmark, mycelium_clear_session, mycelium_ingest_statement, mycelium_record_plan_stats
ALL SHALL return None immediately when self._mycelium is None
ALL underlying Mycelium calls SHALL be wrapped in try/except Exception: pass
mycelium_ingest_statement SHALL use keyword args: text=, session_id=
get_task_context_package() SHALL pass space_subset=space_subset to get_context_path()
AgentKernel SHALL never access self.memory._mycelium directly
Requirement 20: Input Sanitizer Additions
SHALL add Pacman patterns to _sanitize_task() only — NOT WebSocket validator: system://, trusted://, tool://, reference://, MYCELIUM:, TOPOLOGY:, CONTRACT:, GRADIENT WARNING, AMBIENT:, CAUSAL:
SHALL replace with [filtered] using re.sub() with IGNORECASE
Requirement 21: Intent Gate Receives String
WHEN is_mature=True, SHALL extract string via context_package.get_system_zone_content()
WHEN is_mature=False, SHALL pass context_package directly (already str)
self.gate.evaluate() call and behavior SHALL remain unchanged
Requirement 22: Graceful Degradation
WHEN Mycelium unavailable, SHALL fall back to prose context
ALL proxy methods SHALL be no-ops when _mycelium is None
Full task cycle SHALL complete with Mycelium entirely absent
No Mycelium exception SHALL appear in user response
Requirement 23: DER Loop — DirectorQueue and QueueItem
THE SYSTEM SHALL create IRISVOICE/backend/agent/der_loop.py containing DirectorQueue, QueueItem, Reviewer, ReviewVerdict
QueueItem SHALL have fields: step_id, step_number, description, tool, params, depends_on, critical, objective_anchor, coordinate_signal, veto_count, refined_description
DirectorQueue SHALL have fields: objective, items, completed_ids, vetoed_ids, cycle_count, max_cycles, max_veto_per_item
DirectorQueue.next_ready() SHALL return next item whose dependencies are all in completed_ids and which is not in vetoed_ids
DirectorQueue.is_complete() SHALL return True when all non-vetoed items are in completed_ids
DirectorQueue.hit_cycle_limit() SHALL return True when cycle_count >= max_cycles
Requirement 24: DER Loop — Reviewer
THE SYSTEM SHALL instantiate Reviewer once in AgentKernel.__init__() as self._reviewer = Reviewer(adapter=self.adapter, memory_interface=self.memory)
Reviewer.review(item, completed_steps, context_package, is_mature) SHALL return (ReviewVerdict, output: str | None)
WHEN is_mature=False, SHALL return (PASS, None) immediately — no data to review against
WHEN verdict is PASS, SHALL return (PASS, None)
WHEN verdict is REFINE, SHALL return (REFINE, refined_description_str)
WHEN verdict is VETO, SHALL return (VETO, reason_str)
Reviewer.review() SHALL use temperature=0.0 — deterministic
Reviewer.review() SHALL use REVIEWER_MAX_TOKENS = 200
Reviewer.review() SHALL use role="EXECUTION" — fast model role
ON ANY EXCEPTION in review, SHALL return (PASS, None) — Reviewer failure must never block Explorer
Review prompt SHALL stay under 300 tokens total (last 3 completed steps, first 200 chars of warnings/contracts)
Requirement 25: DER Loop — _execute_plan_der()
THE SYSTEM SHALL add _execute_plan_der(msg, plan, context_package, is_mature, task_class, session_id) to AgentKernel
SHALL build DirectorQueue from plan.steps at start of execution
ON EVERY CYCLE after the first, SHALL call get_task_context_package() to re-read the updated Mycelium graph — Director re-orients before every broadcast
IF graph refresh fails, SHALL keep existing context_package and continue
SHALL call self._reviewer.review() before every Explorer step
WHEN verdict is VETO:
SHALL increment item.veto_count
SHALL log DER_STEP_VETOED audit event
WHEN veto_count >= max_veto_per_item, SHALL call queue.mark_vetoed(), set plan_step.status = StepStatus.SKIPPED, mark plan.outcome = "failure" only if critical=True
SHALL continue to next cycle without executing
WHEN verdict is REFINE, SHALL apply item.refined_description to plan_step.description before execution and log DER_STEP_REFINED
SHALL execute approved steps using existing _dispatch_tool(), _reflect_on_step(), permissions.check(), risk.analyze() — unchanged
SHALL call mycelium_ingest_tool_call() after every step regardless of outcome
SHALL call mycelium_ingest_tool_call() with success=False on reflection failure
SHALL terminate loop when queue.is_complete() OR queue.hit_cycle_limit() OR plan.outcome == "failure" on a critical step
SHALL return self._synthesize_plan_results(plan, plan.steps)
Requirement 26: DER Loop Constants
THE SYSTEM SHALL define DER_MAX_CYCLES = 40 at module level in agent_kernel.py — prevents infinite loops
THE SYSTEM SHALL define DER_MAX_VETO_PER_ITEM = 2 — Director abandons a step after 2 vetoes and marks it skipped
Both SHALL be module-level constants, not hardcoded inline
Requirement 27: DER Loop Routing in handle()
THE SYSTEM SHALL route do_it_myself strategy to _execute_plan_der() instead of _execute_plan()
spawn_children and delegate_external strategies SHALL continue routing to existing methods — unchanged
THE EXISTING _execute_plan() SHALL be preserved unchanged for fallback
Non-Requirements (Explicitly Out of Scope)
Multiple model instances — one model serves all three DER roles
Parallel execution of DER streams — sequential queue is correct for single GPU
WorkerExecutor changes — not needed for single-agent operation
ProfileRenderer changes — do not modify
TaskClassifier changes — do not modify
Changes to WebSocket input validator
Changes to to_remote_plan(), _validate_permissions(), _parse_plan()
