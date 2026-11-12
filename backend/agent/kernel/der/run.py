# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

import threading
import os
from backend.agent.inference.errors import RateLimitedError
from backend.agent.call_context import (
    CallClass,
    set_call_class,
    restores_call_class,
)
from backend.agent import write_counters as _write_counters
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import time
from backend.utils.observability import (
    TurnMetrics,
    loud_error,
    get_turn_id,
    broadcast_inference_event,
)
from backend.agent.kernel.base import (
    _DER_PARALLEL,
    _der_ledger_storage_path,
    _der_recall_delivered,
    _emit_event,
    _memory_events_submit,
    _step_calls,
    _step_tool,
    derive_work_units_0,
    logger,
    resolve_der_token_budget,
)
from backend.agent.kernel.der.finalize import (
    _der_post_step,
)
from backend.agent.kernel.der.node import (
    _der_start_node,
    _der_take_finished,
)
from backend.agent.kernel.der.report import (
    _der_neighbors_block,
)
from backend.agent.kernel.turn import (
    _developer_mode,
)


def _turn_end_submit(owner, session_id: str, job) -> None:
    """C5: run the turn-end bookkeeping (card footprint, plan stats, episode
    + landmark crystallization, skill capture) on lane("memory_events"), the
    store's ordered writer, instead of before the reply's synthesis (measured
    2-8.5 s per task, 2026-10-01). The next turn of this kernel folds back on
    ``owner._turn_end_pending`` before it reads memory. A dropped submit (lane
    full) runs the job inline: an episode is never lost. Module level on
    purpose (stand-in kernels)."""
    import threading as _th

    done = _th.Event()

    def _run():
        try:
            job()
        except Exception as exc:  # noqa: BLE001 - each part logs its own failure
            logger.warning("[DER] turn-end bookkeeping failed session=%s: %r", session_id, exc)
        finally:
            done.set()

    owner._turn_end_pending = done
    from backend.utils.durability_queue import lane

    if not lane("memory_events").submit("turn_end", _run):
        logger.warning("[DER] turn-end lane full session=%s - bookkeeping inline", session_id)
        _run()

def _der_budget_exit(tokens_used: int, token_budget: int, elapsed_s: float,
                     turn_budget_s: float, queue) -> Optional[str]:
    """Which budget cut the DER loop short: "tokens", "turn_time" or "steps"; None
    when the plan ran to the end. Mirrors the loop condition, so the BUDGET_HIT
    event is typed by the SAME test that stopped the loop. Module level (stand-ins)."""
    if queue.is_complete():
        return None
    if tokens_used >= token_budget:
        return "tokens"
    if elapsed_s >= turn_budget_s:
        return "turn_time"
    if queue.hit_cycle_limit():
        return "steps"
    return None

def _der_topology_halt(owner, session_id: str) -> None:
    """Stop the line on a TOPO_VIOLATION (rec==3) at a step boundary.

    The rec==3 raise inside the physics job never reached the loop: finalize's
    broad except (later the lane job) swallowed it, and every shape-decision
    read sits inside an advisory try â€” so _der_execute_with_recovery's targeted
    recovery never ran in production (MCM pin_22b078571d73, option B). Called
    on the loop thread OUTSIDE any broad except. Reads only a LANDED update â€”
    never waits (S3: the answer path does not wait for its physics); a later
    landing is caught at the next boundary. Raises once per update, so the
    recovery run does not halt again on the same stale state.
    """
    pending = getattr(owner, "_der_physics_pending", None)
    fold = pending.get(session_id) if pending else None
    if fold is None or not fold.ready.is_set() or fold.rec != 3:
        return
    with fold.lock:
        if getattr(fold, "halted", False):
            return
        fold.halted = True
    from backend.agent.exceptions import TopologyViolationException

    logger.warning(
        "[DER] TOPO_VIOLATION landed session=%s step=%s - halting for recovery",
        session_id, getattr(fold, "step", None),
    )
    _emit_event(owner, "HALTED", evidence="verifier", thread_id=session_id,
                step_index=str(getattr(fold, "step", "") or ""),
                payload={"cause": "TOPO_VIOLATION"})
    raise TopologyViolationException(session_id=session_id)

# Session 247: turn wall-clock safety net (seconds). Defined UNCONDITIONALLY
# (outside the der_constants import guard) so it exists on both import paths.
# See the DER main loop â€” last-resort bound only; the sufficiency gate and
# zero-yield cutoff are the rational stops, this catches everything else.
_DER_TURN_BUDGET_S = float(os.environ.get("IRIS_DER_TURN_BUDGET_S", "600"))


class DerRunMixin:
    def _maybe_trigger_skill_creation(
        self,
        tool_sequence: list,
        task_summary: str,
    ) -> None:
        """
        After each task, capture a *verified* reusable skill when the run used
        >= 3 distinct tools and the sequence is not already a known skill.

        Phase 5.1 (research D1): replaces the old count-based heuristic that
        merely prompted the LLM to write a SKILL.md.  The new pipeline is
        deterministic and verified:
          1. Trigger iff >= 3 DISTINCT tools AND similarity to existing skills
             < 0.85 (workflow_capture.should_capture).
          2. Self-test: every step names a tool registered in tool_registry
             (no unknown tools) â€” a safe structural replay, no real execution
             (workflow_capture.self_test_skill).
          3. Register the verified skill in semantic memory
             (workflow_capture.register_verified_skill), mirroring
             SkillCrystalliser's storage so the skill UI / AutoResearchRunner
             pick it up for continuous refinement (MIN_IMPROVEMENT = 0.05).

        tool_sequence is the list of tool-call dicts recorded by the DER loop.
        """
        import json

        if not tool_sequence or len(tool_sequence) < 2:
            return

        # Only capture from successful runs.
        successful = [
            s for s in tool_sequence
            if isinstance(s, dict) and s.get("success", False)
        ]
        if len(successful) < 2:
            return

        # In-session dedupe so we don't re-trigger for the same pattern.
        names = []
        for tc in successful:
            name = (
                tc.get("name")
                or tc.get("tool")
                or tc.get("function", {}).get("name", "")
            )
            if name:
                names.append(name)
        pattern_key = " â†’ ".join(names)
        if pattern_key in self._prompted_skill_patterns:
            return
        self._prompted_skill_patterns.add(pattern_key)

        try:
            from backend.agent.workflow_capture import capture_workflow
            from backend.agent.tool_registry import resolve_tool

            memory = self._memory_interface
            if memory is None or not hasattr(memory, "semantic"):
                return

            # Existing skills (for similarity de-dup).
            existing_skills = []
            try:
                for entry in memory.semantic.get_by_category("named_skills"):
                    try:
                        existing_skills.append(json.loads(entry.value))
                    except Exception:
                        continue
            except Exception:
                existing_skills = []

            # Recurrence (owner 2026-10-01): a skill is a recipe that repeats.
            # Count successful episodes of similar tasks with the SAME call
            # shape (tools in first-use order); this run's own episode was
            # stored just before, so it counts once. A rerun of the same task
            # updates its episode instead of adding one, so reruns do not count.
            from backend.agent.workflow_capture import distinct_tool_names

            _shape = distinct_tool_names(successful)
            _recurrences = 0
            try:
                for _ep in memory.episodic.retrieve_similar(task_summary, limit=10) or []:
                    _seq = _ep.get("tool_sequence") or []
                    if isinstance(_seq, str):
                        _seq = json.loads(_seq)
                    _ok = [s for s in _seq if isinstance(s, dict) and s.get("success", False)]
                    if distinct_tool_names(_ok) == _shape:
                        _recurrences += 1
            except Exception as _rec_exc:  # noqa: BLE001 - no count, no capture
                logger.debug("[AgentKernel] skill recurrence count failed: %r", _rec_exc)
                _recurrences = 0

            key = capture_workflow(
                tool_sequence=successful,
                memory=memory,
                existing_skills=existing_skills,
                is_registered=lambda n: resolve_tool(n) is not None,
                recurrences=_recurrences,
            )
            if key:
                logger.info(
                    "[AgentKernel] Verified skill captured: %s (pattern: %s)",
                    key, pattern_key,
                )
                note = (
                    f"I captured a verified skill from this run "
                    f"({pattern_key}). It will be reused automatically."
                )
                try:
                    if hasattr(self, "_pending_follow_ups"):
                        self._pending_follow_ups.append(note)
                    else:
                        self._pending_follow_ups = [note]
                except Exception:
                    pass
            else:
                logger.debug(
                    "[AgentKernel] Skill capture skipped for pattern: %s", pattern_key
                )
        except Exception as e:
            logger.error("[AgentKernel] Skill capture failed: %s", e, exc_info=True)

    def _note_tool_wait(
        self, *, tool_name: str, wait_id: str, turn_id=None, session_id=None
    ) -> None:
        """Open a narratable tool wait (REQ-10 AC10.11, T13). Never raises.

        Entry lines speak only for known-long waits; every wait carries its
        stated budget so an expectation-miss line fires if crossed with no
        result. Exit (TOOL_RESULT/ERROR site) stays silent â€” results voice
        via the reply path.
        """
        try:
            from backend.agent.conversation_kernel import get_conversation_kernel

            kernel = get_conversation_kernel()
            scheduler = getattr(kernel, "scheduler", None) if kernel else None
            if scheduler is None:
                return
            name = (tool_name or "").lower()
            # Budgets mirror tool_bridge.py:933 (60s vision/gui_automation,
            # else 30s). Entry lines are for known-long waits: the 60s class
            # plus crawl (multi-fetch runs long in practice).
            long_wait = ("vision" in name) or ("gui" in name) or ("crawl" in name)
            budget = 60.0 if (("vision" in name) or ("gui" in name)) else 30.0
            scheduler.note_wait(
                wait_id,
                turn_id=turn_id or "unknown",
                session_id=session_id or "unknown",
                budget_s=budget,
                long_wait=long_wait,
            )
        except Exception:  # noqa: BLE001 â€” narration never blocks tool runs
            pass

    def _end_tool_wait(self, wait_id: str) -> None:
        """Close a narratable tool wait (REQ-10 AC10.11, T13). Never raises."""
        try:
            from backend.agent.conversation_kernel import get_conversation_kernel

            kernel = get_conversation_kernel()
            scheduler = getattr(kernel, "scheduler", None) if kernel else None
            if scheduler is not None and wait_id:
                scheduler.end_wait(wait_id)
        except Exception:  # noqa: BLE001
            pass

    def _session_has_client_for(self, session: Optional[str]) -> bool:
        """WS disconnect check for *session* - True if at least one live
        client, or on any failure (fail-open, "connected"). Wedge fix
        (session 363): extracted from the closure inside _execute_plan_der so
        _turn_choke_check (a method, which cannot see that closure) runs the
        same check inside the transport retry ladders.
        """
        try:
            from backend.ws_manager import get_websocket_manager

            ws = get_websocket_manager()
            if ws is None:
                return True  # no WS manager: non-WS path, keep running
            # Conversation / thread IDs used as kernel sessions:
            # The WS handler (iris_gateway.py:4450) passes the WS client ID
            # as session_id and the conversation/thread ID as conversation_id,
            # so thread IDs never appear as the kernel session there.
            # The REST handler (chat.py:305) uses the thread/conversation ID
            # as the kernel session_id - these sessions have no WS client and
            # must keep running (their output is returned synchronously).
            if isinstance(session, str) and (
                session.startswith("immortus:") or session.startswith("conv_")
            ):
                return True
            # The prefix list above is a NAMING check, and it silently
            # stopped matching: chat.py mints thread ids as "conv-1"
            # (hyphen) while this only ever accepted "conv_" (underscore).
            # Every REST search therefore hit the disconnect branch and the
            # DER loop broke before executing step 1 - surfacing to the user
            # as "no usable sources found", a network failure that never
            # happened. e2e was ~536 ms with no crawl in the log.
            #
            # Test the STRUCTURE instead of the spelling. chat.py:308 passes
            # session_id=thread_id=conversation_id, whereas the WS handler
            # passes the client id as session_id and the thread id as
            # conversation_id (see the comment above), so the two are equal
            # only on the REST path. That holds regardless of how ids are
            # spelled, so renaming them cannot silently re-break this.
            if isinstance(session, str) and session == getattr(
                self, "conversation_id", None
            ):
                return True
            return len(ws.get_clients_for_session(session)) > 0
        except Exception:
            return True

    def _turn_choke_check(self) -> None:
        """Wedge fix (session 363, pin_35af67d07c5f): choke-point check called
        at every model-dispatch entry (InferenceRouter.generate) and inside
        the transport retry ladders and stream chunk loops. The DER loop
        condition only evaluates BETWEEN cycles, so a turn blocked inside ONE
        operation never re-evaluated it and the 600 s budget never fired
        (chain client w1 ran 19+ min; the backend logged nothing for 18).
        Latches _der_stop_requested BEFORE raising so the loop exits to
        synthesis over completed steps even if a caller catches the error -
        the same contract the loop condition already assumes. Inert unless a
        DER turn is active (_der_turn_active), so a stale start time from a
        finished turn can never raise on a healthy non-DER call.
        """
        if not getattr(self, "_der_turn_active", False):
            return
        start = getattr(self, "_der_start_time", None)
        if start is not None and (time.perf_counter() - start) >= _DER_TURN_BUDGET_S:
            self._der_stop_requested = True
            raise RuntimeError(
                f"[DER] turn budget ({_DER_TURN_BUDGET_S:.0f}s) exhausted - "
                "aborting to synthesis over completed steps"
            )
        session = getattr(self, "_der_session", None)
        if session is None:
            return
        # The client check is throttled: the stream chunk loops call this per
        # SSE line, so the WS lookup must not run per line. Re-check at most
        # every 5 s; the budget half above is nanoseconds-cheap and always
        # runs.
        now = time.perf_counter()
        if now - getattr(self, "_der_last_client_check", 0.0) < 5.0:
            return
        self._der_last_client_check = now
        if not self._session_has_client_for(session):
            self._der_stop_requested = True
            raise RuntimeError(
                "[DER] session has no connected clients - aborting to "
                "synthesis over completed steps"
            )

    def _execute_plan_der(
        self,
        plan,
        context_package=None,
        is_mature: bool = False,
        task_class: str = "full",
        session_id: Optional[str] = None,
        from_voice: bool = False,
        confidence: float = 0.50,
        turn_id: Optional[str] = None,
        budget_class: Optional[str] = None,
    ) -> str:
        """
        DER execution cycle: Director â†’ Reviewer â†’ Explorer â†’ repeat until complete.

        The Director re-reads Mycelium each cycle via ContextPackage.
        The Reviewer gates each step (PASS / REFINE / VETO).
        The Explorer executes via _tool_bridge or direct model call.
        Mycelium signal hooks fire after every step and at outcome.

        Never raises â€” wraps failures as step error text so the response
        always reaches the user.
        """
        # Trust-routing W2: a plan run is one turn â€” start unmarked.
        self.clear_turn_trust_flag()
        # REQ-5 AC3: the amendment bound is PER TASK. _der_amendment_count lives
        # on the kernel, which is cached per CONVERSATION â€” leaving it to
        # accumulate would permanently refuse every graft after the third
        # recovery in a conversation, silently killing DER's existing recovery
        # path. One plan run is one task, so the counter resets here.
        self._der_amendment_count = 0
        # T6.4: mark the call class as USER_TURN at the real turn entry so the
        # phase gate admits it immediately (high-priority lane).
        set_call_class(CallClass.USER_TURN)
        from backend.agent.der_loop import (
            DirectorQueue,
            NodeRecord,
            QueueItem,
            Reviewer,
            ReviewVerdict,
        )
        from backend.agent.der_constants import ExecutionMode
        import uuid as _uuid

        _session = session_id or self.session_id
        # _turn_id threads the request turn id through EventBus emits and
        # escalation calls. It was previously referenced throughout this
        # method but never defined â€” that NameError broke the DER escalation
        # path and forced the "[step N completed]" fallback. See Issue E fix.
        _turn_id = turn_id
        completed_items: List[Any] = []
        step_outputs: List[str] = []
        _der_start_time = time.perf_counter()
        # Wedge fix (session 363, pin_35af67d07c5f): the turn start lives on
        # the INSTANCE too â€” _turn_choke_check is reached from the router and
        # the transports, which cannot see this local. _der_session and
        # _der_turn_active scope the check to THIS turn: without the active
        # flag a stale start time from a FINISHED turn would raise on a
        # healthy non-DER call that runs more than the budget after the turn
        # ended. _der_last_client_check throttles the WS lookup in
        # _turn_choke_check â€” the stream chunk loops call it per SSE line.
        self._der_start_time = _der_start_time
        self._der_session = _session
        self._der_turn_id = _turn_id
        self._der_turn_active = True
        self._der_last_client_check = 0.0

        # Token budget â€” spec [1.2]: enforce DER_TOKEN_BUDGETS[task_class]
        # Tokens are estimated from step result length (4 chars â‰ˆ 1 token).
        # Budget is a ceiling; the loop exits early if exceeded.
        # DER budget is derived from the MODEL'S ACTUAL CONTEXT WINDOW, not a
        # hardcoded per-mode cap. DER exists to execute tasks in alignment with
        # memory (Pacman filters tokens into the context window that then feeds
        # coordinate memory.db) â€” so each model should be allowed to use its full
        # window for reasoning across steps. The flat DER_TOKEN_BUDGETS values
        # are kept only as a SAFETY FLOOR (never go below a sane minimum), never
        # as a ceiling. No upper cap: a 256k model gets ~230k of step budget, a
        # 32k local model gets ~29k â€” each uses its real capacity.
        # Sized by the SMALLEST window among the roles this turn will actually
        # spend against â€” DER issues both reasoning calls and tool_execution
        # calls, and a Brain/Tool split can put them on very different models.
        # Using the reasoning window alone budgeted ~230k for a turn whose tool
        # steps ran on an 8k model (2026-08-16).
        _model_window = self.resolve_turn_context_window()
        # Session 247: budget sizing uses budget_class (the planner MODE name,
        # e.g. "implement") while task_class stays the classifier's label for
        # every decision. See the call site in the DER entry path.
        _token_budget: int = resolve_der_token_budget(
            _model_window, budget_class or task_class
        )
        _tokens_used: int = 0
        logger.info(
            "[DER] budget=%d from window=%d class=%s (work_units=%d)",
            _token_budget,
            _model_window,
            task_class,
            derive_work_units_0(_model_window),
        )

        # â”€â”€ REQ-1: pre-flight â€” is the reasoning provider usable? â”€â”€â”€â”€â”€â”€â”€â”€
        if not getattr(self, "_router", None):
            logger.warning("[DER] pre-flight FAILED â€” no router configured")
            return "[DER unavailable] No inference router configured"
        try:
            _hc = self._router.health_check_provider("reasoning")
        except Exception as _hc_err:
            _hc = {"ok": False, "error": str(_hc_err)[:200]}
        if not _hc.get("ok"):
            _reason = _hc.get("error", "no reason")
            logger.warning(
                "[DER] pre-flight FAILED â€” reasoning provider unavailable: %s",
                _reason,
            )
            return f"[DER unavailable] {_reason}"

        # Build Director queue from ExecutionPlan steps
        # Phase 4b: derive parallel_safe from the tool registry (authoritative
        # source of truth) so concurrency fires for read-only/independent tools
        # without trusting the LLM planner to emit the flag.
        from backend.agent.tool_registry import is_parallel_safe

        items = [
            QueueItem(
                step_id=step.step_id,
                step_number=step.step_number,
                description=step.description,
                tool=step.tool,
                params=step.params if step.params else {},
                critical=step.critical,
                depends_on=list(step.depends_on or []),
                parallel_safe=is_parallel_safe(step.tool),
                objective_anchor=plan.original_task,
                # T5 (specs/tool-result-envelope): planner-declared
                # criticality rides the queue item â€” intent only until the
                # finalize site confirms it (AC1.6).
                declared_criticality=getattr(step, "criticality", "supporting") or "supporting",
                # 2026-10-19: carry the planner's declared product onto the node.
                # It was dropped here, so every node item had expected_output=None
                # (the verifier had nothing to check; the needs_action Oracle saw
                # a goal with no artifact).
                expected_output=getattr(step, "expected_output", None) or None,
                coordinate_signal=(
                    getattr(context_package, "topology_position", "") or ""
                    if context_package
                    else ""
                ),
                # REQ-3 (T8): EVERY node carries its compressed memory record â€”
                # top-level plan steps included, not just split children. The
                # record's Understanding/Awareness/Direction fields are derived
                # from the plan step itself (the node's initial position), and
                # the finalize site stamps outcome/fraction/mediator/coords_to
                # onto it. Without this, plan steps were always memory-sparse
                # and the node record existed only for sub-loop children.
                node_record=NodeRecord(
                    step_id=step.step_id,
                    parent_step_id="",
                    node_type="step",
                    objective_anchor=plan.original_task,
                    content_summary=(step.description or "")[:300],
                    prior_summary="",  # no prior attempts on first landing
                    expected_output=step.expected_output or "",
                    remaining=step.description or "",
                    ruled_out="",
                    coordinate_ref=None,
                    coords_from="",
                    # REQ-18 (T19): both domain axes resolved at construction â€”
                    # topic from the step's own text via the mycelium registry,
                    # execution from the active winding. Registry-backed, never
                    # free text (AC2/AC3). The finalize site re-stamps with the
                    # full step result text so later steps carry the richer
                    # signal; this seed keeps the record typed even if the
                    # step never finalizes.
                    topic_domain=self._der_topic_domain(step.description or ""),
                    execution_domain=self._der_execution_domain(from_voice),
                    committed_decision=False,
                    size_bytes=len((step.description or "").encode("utf-8", "replace")),
                ),
            )
            for step in plan.steps
        ]
        queue = DirectorQueue(objective=plan.original_task, items=items)
        # Taxonomy CONTROL: the plan is accepted. Episode id = Wave E's task id.
        self._event_episode_id = f"{_session}:{_turn_id or ''}"
        _plan_rec = getattr(items[0], "node_record", None) if items else None
        _emit_event(
            self, "PLAN_MADE", thread_id=_session,
            exec_domain=getattr(_plan_rec, "execution_domain", None),
            topic_domain=getattr(_plan_rec, "topic_domain", None),
            payload={"steps": len(items), "strategy": getattr(plan, "strategy", None),
                     "task_class": task_class},
        )

        # â”€â”€ Goal contract T4 (specs/goal-contract-coverage, REQ-1) â”€â”€
        # Build the deterministic required-fact set once per turn, validate
        # the plan against it (an omission is re-added by construction â€” the
        # deterministic set stands alone â€” and logged with the fact text),
        # and stamp required_facts on every step's node record. Advisory:
        # never break plan start on a contract failure.
        self._goal_contract_state = None
        try:
            from backend.agent import goal_contract as _gc_mod

            _gc_facts = _gc_mod.extract_required(plan.original_task or "")
            _gc_omitted = _gc_mod.map_to_steps(_gc_facts, list(plan.steps))
            for _om_fact in _gc_omitted:
                logger.info(
                    "[goal-contract] planner omitted fact, re-added: %r",
                    str(_om_fact)[:160],
                )
            _gc_task_rec = NodeRecord(
                step_id=f"task:{(_turn_id or _session or 'turn')}",
                parent_step_id="",
                node_type="task",
                objective_anchor=plan.original_task or "",
                expected_output=plan.original_task or "",
                required_facts=list(_gc_facts),
                contract_version=1,
            )
            for _gc_item in items:
                try:
                    if getattr(_gc_item, "node_record", None) is not None:
                        _gc_item.node_record.required_facts = list(_gc_facts)
                except Exception:
                    pass
            self._goal_contract_state = {
                "turn_id": _turn_id,
                "contract": _gc_mod.Contract(
                    required=tuple(_gc_facts), ceiling=(), version=1
                ),
                "task_record": _gc_task_rec,
                "covered": [],
                "outcomes": [],
                "results": [],
                "C": 0.0,
                "g": 1.0,
                "prev_c": 0.0,
                "prev_tokens": 0,
                "unmoved": 0,
                "stall_cycles": 0,
                "stalled": False,
                "rho": 0.0,
                # Wave 3 (T7/T8/T9/T10): amendment log, blocked list, REQ-7
                # counters. All advisory â€” absent = legacy behavior.
                "blocked": [],
                "amendments": [],
                "counters": {
                    "facts_seeded": len(_gc_facts),
                    "facts_mapped": len(_gc_facts) - len(_gc_omitted),
                    "facts_readded": len(_gc_omitted),
                    "facts_covered": 0,
                    "facts_blocked": 0,
                    "amendments_user": 0,
                    "amendments_agent": 0,
                    "stalls": 0,
                    "bonus_passes": 0,
                },
            }
            logger.info(
                "[goal-contract] contract built: %d required facts (%d "
                "omitted by planner, re-added)",
                len(_gc_facts), len(_gc_omitted),
            )
        except Exception as _gc_exc:
            logger.debug("[goal-contract] build skipped: %s", _gc_exc)
            self._goal_contract_state = None

        # Force a real tool for web-search steps the planner left tool-less.
        # Without this, web-intent steps fall through to _run_step_direct and the
        # LLM returns empty ("[step N completed]") instead of actually searching.
        # Also catches mode names (agentic / quick / full) that the LLM planner
        # sometimes assigns instead of the actual tool name.
        # Phase 1 (D1.4): web-intent regex override DELETED. Tool selection is
        # now a single runtime authority (explorer.propose), which routes web
        # intent to crawler_query via the registry's alias + capability system
        # (capability-gated fallback for research-class goals). No routing is
        # lost â€” the registry already canonicalizes web aliases to crawler_query.

        # â”€â”€ Phase 3: initialize execution mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Director decides mode dynamically based on task characteristics.
        # Voice no longer caps to 1 step â€” Director decides based on content.
        voice_preference = getattr(self, "_voice_preference", "auto")
        initial_mode = DirectorQueue._decide_mode(
            task_class=task_class,
            from_voice=from_voice,
            message_text=plan.original_task or "",
            token_budget_remaining=_token_budget,
            confidence=confidence,
            voice_preference=voice_preference,
        )
        queue.set_mode(initial_mode, reason=f"Task class: {task_class}")
        logger.info(
            "[DER] Mode selected: %s (voice=%s, class=%s, budget=%d)",
            initial_mode.value, from_voice, task_class, _token_budget,
        )

        # â”€â”€ Card gate (owner bound, 2026-09-25) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # A card is for MORE THAN THREE tool steps, and never for an artifact ask
        # (the artifact IS the visible result). Below the bound the turn still
        # runs through DER, the tools still fire and a real artifact still
        # renders â€” only card-lifecycle events are withheld, by the WS bridge
        # and by _persist_card_snapshot, both keyed on artifact_policy's gate.
        try:
            from backend.agent.artifact_policy import (
                MIN_TOOL_STEPS_FOR_CARD,
                card_warranted,
                clear_card_free_conversation,
                is_artifact_ask,
                suppress_card_for_conversation,
                tool_step_count,
            )

            _artifact_ask = is_artifact_ask(plan.original_task or "")
            self._current_task_text = plan.original_task or ""
            # The card bound is a personal-mode rule (see _developer_mode).
            self._der_card_hold = None
            if card_warranted(items, plan.original_task or "") or _developer_mode(self):
                # This turn may have a card â€” clear the conversation-scoped
                # marker a previous short turn left behind.
                self._suppressed_card_turn = None
                clear_card_free_conversation(self.conversation_id)
            else:
                suppress_card_for_conversation(self.conversation_id, _turn_id)
                self._suppressed_card_turn = _turn_id
                # A plan step is a NODE now (up to 12 tool calls), so a short
                # plan can still be long work: the card is released at the
                # turn's MIN_TOOL_STEPS_FOR_CARD-th real tool call
                # (_der_count_tool_call). Live 2026-10-12: 3-step plans with
                # 5 real calls (author lookup, pizza form) showed no card.
                if not _artifact_ask:
                    self._der_card_hold = {
                        "turn": _turn_id, "queue": queue, "plan": plan,
                        "session": _session, "calls": 0,
                        "lock": threading.Lock(),
                    }
                logger.info(
                    "[AgentKernel] task card suppressed: tool_steps=%d (bound "
                    ">=%d) artifact_ask=%s turn=%s â€” the turn runs, the artifact "
                    "still renders",
                    tool_step_count(items),
                    MIN_TOOL_STEPS_FOR_CARD,
                    _artifact_ask,
                    _turn_id,
                )
        except Exception as _gate_exc:  # never block the turn on the gate
            logger.debug("[AgentKernel] card gate skipped: %s", _gate_exc)

        # â”€â”€ EventBus: emit task:start â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            bus = get_event_bus()
            _card_task_id = _turn_id or plan.original_task[:40]
            _card_id, _card_relation = self._resolve_card_identity(
                _card_task_id, "initial"
            )
            # T16 (REQ-12 AC4): card-lifecycle observability â€” relation decision
            # is logged here, off the inference hot path (this block only emits
            # an event; a log line can never block the user response).
            logger.info(
                "[AgentKernel] CARD_LIFECYCLE relation=%s card_id=%s task_id=%s conv=%s turn=%s",
                _card_relation, _card_id, _card_task_id, self.conversation_id, _turn_id,
            )
            _start_steps = [
                {
                    "id": it.step_id,
                    "description": it.description,
                    "status": "pending",
                    # Session 247: semantic order for the frontend row sort.
                    "stepNumber": it.step_number,
                    "toolName": _step_tool(it),
                }
                for it in items
            ]
            bus.emit(
                IRISStreamEvent.TASK_START,
                data=self._task_start_payload(
                    task_id=_card_task_id,
                    description=plan.original_task[:200],
                    plan_title=self._effective_plan_title(plan),
                    mode=initial_mode.value,
                    steps=_start_steps,
                    total_steps=len(items),
                    # REQ-14 (T23): execution-start announcement â€” still the
                    # INITIAL plan; revisions re-emit with a distinct origin.
                    origin="initial",
                    # REQ-3 (T2): backend-declared card identity.
                    card_id=_card_id,
                    card_relation=_card_relation,
                    conversation_id=self.conversation_id,
                        turn_id=getattr(self, "_current_turn_id", None),
                    **self._multiagent_tags(),
                ),
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
            # T4a (REQ-4 AC1): persist the card at task:start.
            self._persist_card_snapshot(
                card_id=_card_id,
                conversation_id=self.conversation_id,
                card_relation=_card_relation,
                plan_title=self._effective_plan_title(plan),
                mode=initial_mode.value,
                steps=_start_steps,
                total_steps=len(items),
                terminal_state="running",
            )
        except Exception:
            pass  # EventBus is optional â€” no crash if it fails

        # C.1 LiveContextPackage â€” refreshes ContextPackage mid-loop so the
        # Director always reads current gradient_warnings + tier2_predictions.
        try:
            from backend.memory.live_context import LiveContextPackage

            _live_ctx = LiveContextPackage(
                initial_package=context_package,
                memory_interface=self._memory_interface,
                session_id=_session,
            )
        except Exception:
            _live_ctx = None  # graceful no-op if import fails

        # Reviewer â€” falls back to PASS on any failure (membrane, not gate)
        reviewer = self._reviewer

        # WS disconnect helper - checks if the originating session still has
        # at least one live client. Never raises; defaults to "connected".
        # Wedge fix (session 363): the body moved to _session_has_client_for
        # so _turn_choke_check - a METHOD, which cannot see this closure -
        # runs the same check inside the transport retry ladders. This
        # delegate keeps the loop call site unchanged.
        def _session_has_client() -> bool:
            return self._session_has_client_for(_session)

        # â”€â”€ REQ-15 (T25/T26): per-task steering state reset â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        self._der_stop_requested = False
        self._der_pause_requested = False
        self._der_resume_requested = False

        # dev-cli-ide REQ-25 edge case: the inbox outlives the loop that reads
        # it. Records are drained ONLY inside this loop, so anything queued
        # while no DER task was running would be applied to the NEXT task --
        # a steer aimed at one job silently revising another. Nothing sent to
        # the channel before REQ-25, so this was latent; the UI sender makes it
        # reachable. Drop pre-task records here and acknowledge them, rather
        # than letting them leak forward.
        try:
            from backend.agent.steering import get_steering_inbox as _gsi

            _stale = _gsi().drain(_session)
            for _rec in _stale:
                self._emit_steering_ack(
                    _rec.channel, _rec.message_id, "considered", _session
                )
            if _stale:
                logger.info(
                    "[AgentKernel][%s] dropped %d steering record(s) queued "
                    "before this task started", _session, len(_stale),
                )
        except Exception as _st_exc:
            logger.debug("[AgentKernel] stale-steering sweep skipped: %s", _st_exc)

        # â”€â”€ Parallel nodes (owner 2026-10-04): ONE scheduler for every node -
        # plan steps, split children, grafts, batch children. The DAG decides
        # WHAT is ready (depends_on); the "execution.der_nodes" phase domain
        # decides WHEN a ready node starts; the node's work runs on its own
        # thread while the bookkeeping before and after it stays on this
        # thread, in order. Independent nodes overlap; a dependent node is
        # never ready before its dependencies complete.
        import queue as _queue_mod

        _inflight: Dict[str, dict] = {}
        _finished = _queue_mod.Queue()
        # Bound before the loop: a turn whose loop exits before its first pass
        # (a stop latched at the first boundary, a budget already spent) reached
        # the grading line with `item` unassigned - UnboundLocalError, and the
        # reply became "[IRIS error: cannot access local variable 'item' ...]"
        # (live 2026-10-06, a strand turn). The grading line handles None.
        item = None

        while (
            not queue.is_complete()
            and not queue.hit_cycle_limit()
            and _tokens_used < _token_budget
            # Session 247: TURN WALL-CLOCK â€” the last-resort safety net. The
            # sufficiency gate and zero-yield cutoff stop the *rational*
            # churn; this bounds the total so no future bug can ever again
            # hold a turn open for 30+ minutes (conv-41 ran 18 dispatch
            # rounds unbounded). Generous by design: 10 min of wall time is
            # far beyond any healthy websearch turn, so this only fires on
            # genuine pathology. When it trips, the loop exits to synthesis
            # over completed steps â€” partial results reach the user.
            and (time.perf_counter() - _der_start_time) < _DER_TURN_BUDGET_S
            # REQ-15 AC3: an explicit stop aborts at the next step boundary.
            and not self._der_stop_requested
        ):
            # â”€â”€ DISCONNECT CHECK: stop early if client is gone â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if not _session_has_client():
                logger.info(
                    f"[DER] Session {_session} has no connected clients â€” "
                    "recording partial outcome and stopping"
                )
                break

            # â”€â”€ DOMAIN 19: Caducean phase read â”€â”€
            import math as _math

            _xi = 0.0
            try:
                from backend.gateway.iris_ffi import ffi_caducean_get_xi

                _xi = ffi_caducean_get_xi(_session)
            except Exception as _ffi_exc:
                loud_error(_ffi_exc, "ffi_caducean_get_xi")
            _phase = 0  # 0=[0,Ï€/2], 1=[Ï€/2,Ï€], 2=[Ï€,3Ï€/2], 3=[3Ï€/2,2Ï€]
            if _xi >= 3.0 * _math.pi / 2.0:
                _phase = 3
            elif _xi >= _math.pi:
                _phase = 2
            elif _xi >= _math.pi / 2.0:
                _phase = 1

            # â”€â”€ Parallel nodes: settle a finished node first (in finish order,
            # on this thread), else start the next ready one; with nothing to
            # start, wait for a node in flight to finish. â”€â”€
            _fin = _der_take_finished(self, _finished, _inflight, block=False)
            if _fin is None:
                # IRIS_DER_PARALLEL=0: one node at a time (the off switch and
                # the A/B baseline); default on.
                item = (None if (_inflight and not _DER_PARALLEL)
                        else queue.next_ready(_session, exclude=_inflight))
                if item is None:
                    if not _inflight:
                        break  # dependency deadlock guard
                    # Wait in short slices: a stop, a disconnect or the turn
                    # budget is seen at the loop top, not after a slow node.
                    _fin = _der_take_finished(
                        self, _finished, _inflight, block=True, timeout=0.5,
                    )
                    if _fin is None:
                        continue
            if _fin is not None:
                _tokens_used = _der_post_step(self, 
                    *_fin, queue=queue, plan=plan, _session=_session, _turn_id=_turn_id,
                    context_package=context_package, completed_items=completed_items,
                    step_outputs=step_outputs, _tokens_used=_tokens_used,
                    _token_budget=_token_budget, is_mature=is_mature, _live_ctx=_live_ctx,
                    from_voice=from_voice, inflight=_inflight,
                )
                continue
            queue.cycle_count += 1
            verdict = None

            # â”€â”€ REQ-15 (T25/T26): consume mid-task steering at the NEXT step
            # boundary (AC1 â€” never mid-step). A steering revision replaces
            # the remaining plan (AC2); a stop aborts here (AC3); a pause
            # suspends here until resume/stop (AC4). budget_deadline bounds
            # the re-plan's LLM call by the turn budget (pin_ced7b0dc3b8f).
            # Before it: a landed TOPO_VIOLATION halts the loop into
            # _der_execute_with_recovery (never waits on the physics lane).
            _der_topology_halt(self, _session)
            _steer = self._der_check_steering(
                _session, plan, queue,
                budget_deadline=_der_start_time + _DER_TURN_BUDGET_S,
            )
            if _steer:
                if _steer.get("stop"):
                    break
                if _steer.get("revised"):
                    # The pulled item belongs to the dropped plan â€” re-pull
                    # from the revised queue on the next iteration. Nodes of
                    # the dropped plan still in flight stop at their next call.
                    for _rec in _inflight.values():
                        _rec["item"]._node_cancelled = "plan revised"
                    continue
                if _steer.get("pause"):
                    _suspend = self._der_suspend_task(
                        _session, plan, queue, _turn_id
                    )
                    if _suspend == "stop":
                        break
                    # resumed: the pulled item was never executed â€” re-pull
                    # it from the (unchanged) queue.
                    continue

            # â”€â”€ C.1 LIVE CONTEXT REFRESH â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Re-read Mycelium coordinate signals for the current sub-step.
            # Updates gradient_warnings + tier2_predictions on context_package.
            # < 50ms SLA; silently no-ops on any error.
            if _live_ctx is not None:
                _live_ctx.refresh(item, completed_items)
                context_package = _live_ctx.package  # always valid

            # â”€â”€ C.4 MID-LOOP EPISODIC RETRIEVAL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Query the episodic store for the *current sub-task*, not the
            # parent task.  Injects a hint into item.coordinate_signal so the
            # Reviewer and Explorer both see "I solved this sub-problem before
            # this way".  <50ms: uses cached embeddings after first query.
            try:
                if self._memory_interface and item.description:
                    _retrieval_limit = 2
                    _retrieval_score = 0.55
                    try:
                        from backend.agent.caducean_trajectory import (
                            CaduceanTrajectoryRecorder,
                        )
                        # REQ-16: read per-session cached (eml, x, y) triple
                        _triple = CaduceanTrajectoryRecorder.get_cached_eml(
                            _session
                        )
                        if isinstance(_triple, tuple):
                            _cached_eml = float(
                                _triple[0] if _triple[0] is not None else 1.0
                            )
                            _cached_x = float(_triple[1]) if _triple[1] else 0.0
                            _cached_y = float(_triple[2]) if _triple[2] else 0.0
                        elif isinstance(_triple, (int, float)):
                            _cached_eml = float(_triple)
                            _cached_x = _cached_y = 0.0
                        else:
                            _cached_eml, _cached_x, _cached_y = 1.0, 0.0, 0.0

                        # REQ-17: V-shaped explore pressure, AC1: x/y directional term.
                        # Three anchors (AC3):
                        #   consolidate (eml=0.90, x-dominant): limit=3,  score=0.65
                        #   neutral     (eml=1.20):              limit=2,  score=0.55
                        #   explore     (eml=1.60, y-dominant):  limit=5,  score=0.40
                        _EC, _EN, _EE = 0.90, 1.20, 1.60
                        _LC, _LN, _LE = 3, 2, 5
                        _SC, _SN, _SE = 0.65, 0.55, 0.40
                        _e = max(0.0, _cached_eml)
                        _norm = (_cached_x**2 + _cached_y**2) ** 0.5
                        _dir = _cached_y / _norm if _norm > 1e-9 else 0.0
                        if _e <= _EN:
                            _p = max(0.0, min(1.0, (_e - _EC) / (_EN - _EC)))
                            _retrieval_limit = _LC + (_LN - _LC) * _p
                            _retrieval_score = _SC + (_SN - _SC) * _p
                            _bias = min(1.0, abs(_dir))
                            if _dir < 0:  # consolidate-dominant
                                _retrieval_limit += _bias * (_LC - _retrieval_limit)
                                _retrieval_score += _bias * (_SC - _retrieval_score)
                            elif _dir > 0:  # explore-dominant at low EML
                                _retrieval_limit += _bias * (_LE - _retrieval_limit)
                                _retrieval_score += _bias * (_SE - _retrieval_score)
                        else:
                            _p = max(0.0, min(1.0, (_e - _EN) / (_EE - _EN)))
                            _retrieval_limit = _LN + (_LE - _LN) * _p
                            _retrieval_score = _SN + (_SE - _SN) * _p
                            _bias = min(1.0, abs(_dir))
                            if _dir > 0:  # explore-dominant
                                _retrieval_limit += _bias * (_LE - _retrieval_limit)
                                _retrieval_score += _bias * (_SE - _retrieval_score)
                            elif _dir < 0:  # consolidate-dominant at high EML
                                _retrieval_limit += _bias * (_LC - _retrieval_limit)
                                _retrieval_score += _bias * (_SC - _retrieval_score)
                        _retrieval_limit = max(2, min(5, int(round(_retrieval_limit))))
                        _retrieval_score = max(0.40, min(0.65, _retrieval_score))
                    except Exception as _eml_exc:
                        loud_error(_eml_exc, "caducean_eml_retrieval")
                    _sub_eps = self._memory_interface.episodic.retrieve_similar(
                        task=item.description,
                        limit=_retrieval_limit,
                        min_score=_retrieval_score,
                    )
                    if _sub_eps:
                        _hint_parts = []
                        for ep in _sub_eps:
                            _ts = ep.get("task_summary", "")[:80]
                            if _ts:
                                _hint_parts.append(_ts)
                            # A2 FIX: surface the proven tool_sequence, not just
                            # the summary, so the Explorer repeats a known-good path.
                            _seq = ep.get("tool_sequence", [])
                            if _seq:
                                _approach = " â†’ ".join(
                                    s.get("tool", "?") for s in _seq[:5]
                                )
                                _hint_parts.append(f"PROVEN APPROACH: {_approach}")
                        _hints = "; ".join(_hint_parts)
                        if _hints:
                            _prior = getattr(item, "coordinate_signal", "") or ""
                            item.coordinate_signal = (
                                _prior + f"\nSUB-TASK HINT: {_hints}"
                            ).strip()
                    # â”€â”€ REQ-20 AC3 (T21): the filtered ontology neighborhood
                    # is a first-class step input. Query the DER chain with
                    # THIS node's type + both domain axes and surface the
                    # relevant neighbor records into the step context â€” the
                    # relevant neighborhood, not the whole graph. Zero-hit
                    # widens (relationship -> type -> domain, logged) and
                    # falls back to the live-state-only step (never an error).
                    try:
                        # K2: only rows that passed the relevance gate reach
                        # here; no row -> no block (nothing injected).
                        _nb_rows = self._der_recall_neighborhood(item, _session)
                        _nb_block = _der_neighbors_block(_nb_rows)
                        if _nb_block:
                            _prior = getattr(item, "coordinate_signal", "") or ""
                            item.coordinate_signal = (
                                _prior + "\nRELEVANT NEIGHBORS: " + _nb_block
                            ).strip()
                            _der_recall_delivered(
                                self, item, "neighbors",
                                [r.get("chain_id") for r in _nb_rows[:3]], _session,
                            )
                    except Exception as _nb_exc:
                        loud_error(_nb_exc, "ontology_recall_neighborhood")

                    # REQ-12 AC3 (T48, 2026-10-29): the step's own CHUNK memory.
                    # The neighborhood above is chain rows typed by node_type +
                    # domain, and an episode is not a fact: neither carries a
                    # taught USER statement. That lives in a context_fragment
                    # chunk (the turn pair), so the step that must answer recalls
                    # it HERE, on the node that needs it - not in the planner.
                    # Bounded to 3 x 300 chars, trusted only, cross-conversation.
                    try:
                        _ep_store = getattr(self._memory_interface, "episodic", None)
                        _step_goal = getattr(item, "description", "") or ""
                        if _ep_store is not None and _step_goal:
                            _ch_rows = _ep_store.retrieve_context_chunks(
                                _step_goal,
                                session_id=None,
                                limit=3,
                                min_similarity=0.35,
                                chunk_types=["context_fragment"],
                                zones=["trusted"],
                                with_meta=True,
                            ) or []
                            # REQ-12 AC2 (T48): `trusted` only means "not outside
                            # content". Each row carries its PRODUCER, so the step
                            # can weigh the user's statement above this agent's
                            # own earlier answer instead of treating them alike.
                            _LABELS = {
                                "user_statement": "the user stated",
                                "agent_step": "your earlier answer",
                            }
                            _ch_rows = sorted(
                                _ch_rows,
                                key=lambda r: 0 if r.get("producer") == "user_statement" else 1,
                            )
                            _ch_txt = "\n- ".join(
                                "[{}] {}".format(
                                    _LABELS.get(
                                        r.get("producer"),
                                        str(r.get("producer") or "memory").replace("tool:", "tool "),
                                    ),
                                    str(r.get("content") or "").strip()[:300].replace("\n", " "),
                                )
                                for r in _ch_rows if str(r.get("content") or "").strip()
                            )
                            if _ch_txt:
                                _prior_ch = getattr(item, "coordinate_signal", "") or ""
                                item.coordinate_signal = (
                                    _prior_ch + "\nRELEVANT MEMORY:\n- " + _ch_txt
                                ).strip()
                    except Exception as _ch_exc:
                        loud_error(_ch_exc, "step_chunk_recall")

                    # â”€â”€ REQ-3 T8 AC1/AC3: the node's compressed memory record is
                    # a FIRST-CLASS step input (not opt-in). If this item carries
                    # a NodeRecord (every node does from split/creation on), its
                    # Understanding/Awareness/Direction + the compressed Î£
                    # position are injected into the step input alongside the
                    # episodic hints. When the store has no record for the
                    # node's coordinate, the step proceeds on the live state
                    # alone and is marked memory-sparse in the observability log
                    # (AC3) â€” never an error.
                    try:
                        _rec = getattr(item, "node_record", None) or getattr(
                            item, "footprint", None
                        )
                        # REQ-6 AC1 (T18): OBSERVE which signal governed this
                        # step's steering â€” past-memory (compressed node
                        # record present) vs live-state (memory-sparse: no
                        # record, the decision runs on the live Î£ alone). A
                        # record present AND live Î£ consumed is the "both"
                        # (equal-signals) edge. No hardcoded authority (AC2).
                        try:
                            self._der_record_governance(
                                "both" if _rec is not None else "live"
                            )
                        except Exception:
                            pass
                        if _rec is not None:
                            _rec_parts = []
                            if getattr(_rec, "prior_summary", ""):
                                _rec_parts.append(
                                    # 300 as before; 1600 only for a replan-
                                    # after-failure child whose summary carries
                                    # the bounded case trail (<= 400, D9) and
                                    # chain block (<= 900, K3) - no other node
                                    # grows (owner: no context debt).
                                    "UNDERSTANDING: " + _rec.prior_summary[
                                        :1600 if (
                                            "CHAIN TIMELINE" in _rec.prior_summary
                                            or "MEDIATORS TRIED" in _rec.prior_summary
                                            or "KNOWN CASE" in _rec.prior_summary
                                        ) else 300
                                    ]
                                )
                            if getattr(_rec, "ruled_out", ""):
                                _rec_parts.append(f"RULED OUT: {_rec.ruled_out[:200]}")
                            if getattr(_rec, "expected_output", ""):
                                _rec_parts.append(
                                    f"EXPECTED: {_rec.expected_output[:200]}"
                                )
                            if getattr(_rec, "coords_from", ""):
                                _rec_parts.append(f"BRANCH COORDS: {_rec.coords_from}")
                            # REQ-4 AC4 (T16b): the fold-back observations from
                            # this node's sub-loop children are first-class
                            # step context (REQ-3 AC1) â€” the parent's next
                            # decision reads what the children resolved.
                            if getattr(_rec, "folded_back", None):
                                _rec_parts.append(
                                    "FOLDED-BACK: " + "; ".join(_rec.folded_back[-3:])
                                )
                            if _rec_parts:
                                _prior = getattr(item, "coordinate_signal", "") or ""
                                item.coordinate_signal = (
                                    _prior + "\nNODE RECORD: " + "; ".join(_rec_parts)
                                ).strip()

                            # â”€â”€ REQ-5 AC1/AC3 (T17): SURFACE the branch
                            # candidates to the deciding step. Retrieval ranks
                            # the relevant branches (physics + evidence) and
                            # puts ALL of them in front of the step â€” never
                            # pre-selecting one by score. The step decides with
                            # both branches in view; the chosen one is recorded
                            # at commit (_der_record_coupling_decision).
                            try:
                                _cands = self._der_surface_branch_candidates(item)
                                if _cands:
                                    _cand_parts = [
                                        f"{i+1}. {c.get('label','')}"
                                        for i, c in enumerate(_cands)
                                    ]
                                    _prior = (
                                        getattr(item, "coordinate_signal", "") or ""
                                    )
                                    item.coordinate_signal = (
                                        _prior
                                        + "\nBRANCH CANDIDATES: "
                                        + " | ".join(_cand_parts)
                                    ).strip()
                                    # remember for the commit-time decision
                                    # record (AC2/AC4) â€” bounded provenance.
                                    try:
                                        item._coupled_candidates = list(_cands)
                                    except Exception:
                                        pass
                            except Exception as _surf_exc:
                                logger.debug(
                                    "[DER] branch surfacing failed: %s", _surf_exc
                                )

                            # â”€â”€ REQ-3 T8b AC4/AC5/AC6: wire the FORGETTING. The
                            # step's working context (coordinate_signal) is bounded
                            # to a fraction of the REQ-1 resolved window (OQ-6:
                            # derived, never a literal) â€” content beyond the bound is
                            # DROPPED from the working context and re-read later
                            # only when retrieval selects the node record. The
                            # per-step prompt token count is recorded so the
                            # reduction is a measured number (AC5). AC6: if the
                            # node's chain write FAILED (durability drop counter),
                            # the working context is the ONLY copy â€” do NOT bound
                            # (forget) it. Extracted to _der_bound_step_context so
                            # the contract test drives the REAL code (T8b).
                            self._der_bound_step_context(item)
                        else:
                            # AC3: memory-sparse â€” no record, proceed on live state.
                            logger.info(
                                "[DER] step memory-sparse step_id=%s (no node record "
                                "for this coordinate) â€” proceeding on live state",
                                getattr(item, "step_id", "?"),
                            )
                    except Exception as _rec_exc:
                        loud_error(_rec_exc, "node_record_step_input")
            except Exception as _explore_exc:
                loud_error(_explore_exc, "explorer_sub_episodes")

            # â”€â”€ REVIEWER PHASE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if reviewer is not None:
                # Bind the step id into the measurement scope from here on
                # (first added for review_verdict, retired 2026-11-10; the bind
                # stays because every later row of this step reads its step_id
                # from the scope). Measured live: 2877 of 2877 rows carried an
                # EMPTY step_id - the loop binds turn_id at turn entry but never
                # the step. scope_now() reads these as VALUES at row-build time,
                # so a lane thread still gets them. try/except: measurement must
                # never block a review.
                try:
                    from backend.agent import decision_engine as _de

                    _de.set_scope(
                        step_id=getattr(item, "step_id", None) or None,
                    )
                except Exception:  # noqa: BLE001 â€” measurement never blocks
                    logger.debug("[DER] review scope bind failed")
                try:
                    verdict, feedback = reviewer.review(
                        item=item,
                        completed_steps=completed_items,
                        context_package=context_package,
                        is_mature=is_mature,
                    )
                except Exception:
                    verdict, feedback = ReviewVerdict.PASS, None

                if verdict == ReviewVerdict.VETO:
                    item.veto_count += 1
                    # the next attempt's node sees why (2026-10-02 audit)
                    item.review_feedback = str(feedback or "")[:300]
                    logger.info(
                        f"[DER] Step {item.step_number} VETOED "
                        f"(count={item.veto_count}, reason={feedback})"
                    )
                    # DER Phase 0 (D0.2): a VETO means the action was NEVER executed.
                    # Do NOT emit a tool-outcome record (that would be a lie â€” a
                    # success=False edge for a tool that never ran). The veto decision is
                    # logged for audit only; it is not a tool outcome.
                    logger.debug(
                        f"[DER] veto audit: step {item.step_number} not executed "
                        f"(reason={feedback})"
                    )

                    if item.veto_count <= queue.max_veto_per_item:
                        # Keep in queue for Director to reroute next cycle
                        continue
                    else:
                        queue.mark_vetoed(item.step_id)
                        # â”€â”€ REQ-8 AC3: emit learning signal for avoided step â”€â”€
                        try:
                            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                            get_event_bus().emit(
                                IRISStreamEvent.TASK_LEARNING,
                                data={
                                    "signal": "avoided",
                                    "step_number": item.step_number,
                                    "step_id": item.step_id,
                                    "session_id": _session,
                                },
                            )
                        except Exception:
                            pass
                        continue

                if verdict == ReviewVerdict.REFINE and feedback:
                    item.refined_description = feedback
                    item.description = feedback
                    logger.info(f"[DER] Step {item.step_number} REFINED")
                    # Session-321 (Reviewer claim-coverage): a REFINE whose
                    # text steers to read/compose sets the read tool
                    # directly â€” the same reroute shape the T6B guard uses.
                    # Clearing the tool and hoping the resolver picks read
                    # is words-only; an explicit tool set is enforcement.
                    # get_rendered_documents is idempotent and side-effect
                    # free, so it cannot recrawl by construction.
                    _fb = str(feedback or "").lower()
                    if "do not dispatch another crawl" in _fb or (
                        "read the gathered" in _fb
                        and (item.tool or "") in ("crawler_query", "web_search",
                                                  "search", "search_discovery")
                    ):
                        item.tool = "get_rendered_documents"
                        item.params = {
                            "conversation_id": self.conversation_id or "",
                        }
                        logger.info(
                            f"[DER] Step {item.step_number} rerouted by "
                            f"Reviewer REFINE to get_rendered_documents",
                        )

            # â”€â”€ EXPLORER PHASE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Emit TOOL_CALL event for the frontend / TaskKernel
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                _lifecycle_task_id = _turn_id or item.step_id
                get_event_bus().emit(
                    IRISStreamEvent.TOOL_CALL,
                    data={
                        "task_id": _lifecycle_task_id,
                        "tool_name": item.tool or "direct",
                        "description": item.description[:200],
                        "params": item.params,
                        "step_number": item.step_number,
                        # REQ-3 AC6 (T2): card_id stays stable across every
                        # event of a card's lifetime, not just task:start.
                        **self._card_envelope(_lifecycle_task_id),
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                )
            except Exception:
                pass
            # T13 (REQ-10 AC10.11): the tool started â€” open its narratable
            # wait (entry line only for known-long waits; miss fires from
            # the scheduler worker if the stated budget is crossed).
            try:
                self._note_tool_wait(
                    tool_name=item.tool or "direct",
                    wait_id=_lifecycle_task_id,
                    turn_id=_turn_id,
                    session_id=_session,
                )
            except Exception:
                pass

            # â”€â”€ RC1 FIX: pre-execution validation (catches tool:null / missing
            # params before runtime). Invalid steps route to graft with the
            # REQ-6 (soft-cancel): if the user switched away from this conversation,
            # stop issuing further steps. An in-flight tool subprocess is allowed to
            # finish once (SOFT cancel) but no subsequent step or recovery narrative
            # is produced for this thread. We check here, at the top of each item
            # iteration, so the loop exits cleanly without emitting further events.
            if self._cancel_requested.is_set():
                self._logger.info(
                    f"[DER] Cancel requested for conversation {self.conversation_id}; "
                    f"halting DER loop after current step."
                )
                break

            # validation error instead of executing-and-failing. â”€â”€
            if item.tool:
                from backend.agent.tool_registry import validate_tool_call
                _valid, _val_err = validate_tool_call(item.tool, item.params or {})
                if not _valid:
                    item.result = f"[VALIDATION] {_val_err}"
                    try:
                        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                        get_event_bus().emit(
                            IRISStreamEvent.VALIDATION_FAILED,
                            data={
                                "tool_name": item.tool,
                                "error": _val_err,
                                "step_id": item.step_id,
                                "step_number": item.step_number,
                            },
                            session_id=_session,
                            turn_id=_turn_id,
                        )
                    except Exception:
                        pass
                    self._der_handle_step_failure(
                        item, queue, plan, _session, _turn_id, context_package
                    )
                    continue

            # â”€â”€ EXPLORER PHASE: execute primary step with resilience (Phase 1.1) â”€â”€
            # retry_with_backoff_sync retries transient errors (ConnectionError /
            # TimeoutError / OSError) with exponential backoff and fails fast on
            # permanent errors (ValueError / PermissionError / etc). _der_run_step
            # returns (result, success) rather than raising, so _run_step re-raises
            # a classified exception to drive the retry decision. The sync twin is
            # used because _der_run_step_execution calls asyncio.run() internally â€”
            # nesting asyncio.run would raise RuntimeError in the executor thread.
            from backend.agent.resilience import retry_with_backoff_sync

            def _run_step(item=item):
                _res, _ok = self._der_run_step_execution(
                    item, context_package, _session, _turn_id, plan, queue=queue
                )
                if _ok:
                    return _res, _ok
                # RateLimitedError is raised (not returned) by
                # _der_run_step_execution when the transport exhausted its own
                # 429 retries. It must NOT be retried at the DER layer (REQ-4
                # AC1) â€” re-raise so retry_with_backoff_sync's NO_RETRY_ERRORS
                # check surfaces it immediately.
                if isinstance(_res, RateLimitedError):
                    raise _res
                _err = _res or ""
                if AgentKernel._der_step_error_is_retryable(_err):
                    raise ConnectionError(_err)  # transient -> retry
                raise ValueError(_err)  # permanent -> fail fast

            # â”€â”€ Parallel nodes (owner 2026-10-04): the node's work runs on its
            # own thread (it always did - a bounded daemon thread, session 269);
            # the loop no longer joins it here but goes on to the next ready
            # node. _der_post_step settles each node when it finishes. â”€â”€
            _der_start_node(self, item, _run_step, _inflight, _finished,
                                 verdict=verdict, phase=_phase)
            continue

        # Nodes still in flight when the loop ended (budget, stop, cancel,
        # disconnect, cycle limit) stop at their next call; their late results
        # are dropped and they are recorded as not finished (the old bounded
        # join failed the step on the budget the same way).
        for _sid, _rec in list(_inflight.items()):
            _rec["item"]._node_cancelled = "turn ended"
            _rec["item"].result = "[STEP TIMEOUT: the turn ended before this node finished]"
            queue.mark_failed(_sid)
            logger.warning("[DER] node %s still running at the turn end - stopped, not settled", _sid)
        _inflight.clear()

        # Taxonomy CONTROL: a budget (tokens, turn time, steps) cut the loop short.
        _budget_kind = _der_budget_exit(
            _tokens_used, _token_budget, time.perf_counter() - _der_start_time,
            _DER_TURN_BUDGET_S, queue,
        )
        if _budget_kind:
            _emit_event(
                self, "BUDGET_HIT", evidence="verifier", thread_id=_session,
                trigger="budget_exceeded",  # nodes/outcome.Reason.BUDGET_EXCEEDED
                cost={"ms": int((time.perf_counter() - _der_start_time) * 1000)},
                payload={"budget": _budget_kind, "tokens_used": int(_tokens_used),
                         "token_budget": int(_token_budget),
                         "steps_done": len(completed_items)},
            )

        # â”€â”€ OUTCOME RECORDING (ordered per spec: clear â†’ stats â†’ episode)
        # NOTE: _store_task_episode internally calls mycelium_record_outcome
        # and mycelium_crystallize_landmark, so we do NOT duplicate them here.
        # DER Phase 0 (D0.6): coarsen outcome from verified_fraction, not a binary
        # "[STEP ERROR" substring. hit (>=0.8) / partial (0.3-0.8) / miss (<0.3).
        _joined = "\n".join(step_outputs)
        # The loop variable `item` is whatever the LAST pass set - after a
        # re-plan it can be None (live 2026-10-02 run A6: the reply became
        # "[IRIS error: 'NoneType' object has no attribute 'expected_output']").
        # Grade against the last step that completed.
        _last_item = completed_items[-1] if completed_items else item
        _frac = (
            self._verified_fraction(getattr(_last_item, "expected_output", "") or "", _joined)
            if step_outputs else 0.0
        )
        # Session-326: verdict from the FINAL ANSWER, not step colors. A
        # failed step used to force "failure" even when the answer carried
        # verified content (7-min stall: partial answer, red-X card).
        # success = clean run plus verified answer; partial = the answer
        # carries verified content despite failed steps; failure = nothing
        # verified. failed_steps still ride the terminal event, so per-step
        # honesty never moves â€” only the run verdict does.
        if _frac >= 0.8 and not queue.failed_ids:
            outcome = "success"
        elif _frac >= 0.3:
            outcome = "partial"
        else:
            outcome = "failure"

        # â”€â”€ REQ-15 AC3 (T25): an explicit stop persists the lifecycle as
        # `cancelled` (REQ-9 LIFECYCLE_CANCELLED) and reports honestly â€”
        # never a fabricated success or failure.
        if getattr(self, "_der_stop_requested", False):
            outcome = "cancelled"

        # â”€â”€ T6 (REQ-5 / D8): task lifecycle reaches its terminal state HERE,
        # derived from the same honest queue state as the outcome label, and is
        # persisted BEFORE the terminal task:done/task:fail event. completed /
        # partial / failed are decided by execution state (queue terminals +
        # verified fraction), never by physics convergence. A persistence
        # failure is exposed honestly and does not silently claim durable
        # completion.
        try:
            from backend.agent.der_execution_ledger import ExecutionLedger

            _ledger = getattr(self, "_der_ledger", None)
            if _ledger is None:
                _ledger = ExecutionLedger(
                    conversation_id=self.conversation_id or self.session_id or "",
                    storage_path=_der_ledger_storage_path(),  # GROUND TRUTH T9 (REQ-14 AC1)
                )
                self._der_ledger = _ledger
            _task_id = self.conversation_id or self.session_id or "unknown"
            _term = {
                "success": "completed",
                "partial": "partial",
                "failure": "failed",
                "cancelled": "cancelled",
            }.get(outcome, "failed")
            _t = _ledger.transition(_task_id, _term)
            if not _ledger.persist():
                logger.warning(
                    "[DER] task lifecycle persistence FAILED (state=%s) â€” durable completion not claimed",
                    _term,
                )
        except Exception as _lc_exc:  # noqa: BLE001 â€” lifecycle must never block the user response
            _write_counters.bump("ledger.lifecycle_write_failed")
            logger.warning("[DER] task lifecycle write FAILED: %s", _lc_exc)

        # GROUND TRUTH T6 (REQ-3): persist the CARD FOOTPRINT here, at the same
        # honest terminal state the ledger just recorded.
        #
        # backend/memory/card_footprint.py was implemented for
        # specs/task-card-v2-liquid-ink REQ-11 and then never called: the module
        # has ZERO production importers, and save_card_footprint /
        # get_card_footprint appear in exactly one file - their own. So
        # semantic_entries holds 0 rows and no card has ever been addressable
        # by id across conversations. This is the call site it was waiting for,
        # and it unblocks specs/wormhole-aperture REQ-34, which reads footprints
        # as a chain-extraction source.
        # C5: written by the turn-end job on the memory lane (below); the card
        # id is captured now because the next turn may change it.
        _te_card_id = getattr(self, "_active_card_id", None)

        # â”€â”€ EventBus: emit task:done / task:fail â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # T11 (REQ-12): record the completed-step count on the kernel so the
        # caller's TurnMetrics block (metrics.der_steps) reads a real number.
        # len(completed_items) is authoritative here â€” it is appended only in
        # _der_finalize_step, one per actually-completed step.
        self._der_step_count = len(completed_items)
        #
        # Session 247 (live conv-44): this emit used to run HERE, BEFORE
        # synthesis. The card flipped to done while the answer did not exist
        # yet, and the "Synthesizing answer" progress frame arrived ~43s
        # AFTER task:done with no working card to attach to - the frontend
        # fabricated a phantom second card (LEGACY_UNKNOWN, THK, timer
        # running). Done must mean "the answer was delivered": the emit is
        # now a closure fired by every outcome branch BELOW, right before
        # it returns its synthesized response.
        def _emit_terminal_event() -> None:
            # Never raises; EventBus failures must not block the user response.
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                _lifecycle_task_id = _turn_id or plan.original_task[:40]
                get_event_bus().emit(
                    IRISStreamEvent.TASK_DONE if outcome in ("success", "partial") else IRISStreamEvent.TASK_FAIL,
                    data={
                        "task_id": _lifecycle_task_id,
                        "outcome": outcome,
                        # REQ-15 AC3 (T25): a stop is explicit â€” the user sees it.
                        "cancelled": outcome == "cancelled",
                        "steps_completed": len(completed_items),
                        "total_steps": len(plan.steps),
                        "failed_steps": [
                            {
                                "step_id": _fi,
                                "description": next(
                                    (_it.description for _it in queue.items
                                     if _it.step_id == _fi),
                                    _fi,
                                ),
                                "reason": next(
                                    (_it.result for _it in queue.items
                                     if _it.step_id == _fi),
                                    "",
                                ) or "",
                            }
                            for _fi in queue.failed_ids
                        ],
                        # REQ-3 AC6 (T2): card_id stays stable across every
                        # event of a card's lifetime, not just task:start.
                        **self._card_envelope(_lifecycle_task_id),
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                    session_id=_session,
                )
                # T4a (REQ-4 AC1): persist the terminal state. Mirrors the same
                # outcome == "success" condition used to pick TASK_DONE vs
                # TASK_FAIL above â€” no separate terminal-state taxonomy invented.
                _envelope = self._card_envelope(_lifecycle_task_id)
                self._persist_card_snapshot(
                    card_id=_envelope.get("card_id"),
                    conversation_id=self.conversation_id,
                    card_relation="continues",
                    plan_title=self._effective_plan_title(plan),
                    mode=queue.mode.value if getattr(queue, "mode", None) else None,
                    steps=self._queue_steps_snapshot(queue),
                    total_steps=len(queue.items),
                    terminal_state="done" if outcome == "success" else "fail",
                )
            except Exception:
                pass  # EventBus is optional â€” no crash if it fails

        try:
            if self._memory_interface:
                self._memory_interface.mycelium_clear_session(
                    session_id=_session,
                )
        except Exception as _exc:
            loud_error(_exc, "mycelium_clear_session")

        # â”€â”€ C5: turn-end bookkeeping on the memory lane (2026-10-01) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Card footprint, plan stats, the episode (+ Mycelium outcome and
        # landmark crystallization) and skill capture ran HERE, before the
        # reply's synthesis: 2-8.5 s per coding task (stack dumps: inside
        # crystallize_landmark -> _auto_connect). The reply does not need any
        # of it, so it runs as ONE ordered job on lane("memory_events") after
        # record_task_end (same lane, same order as before). The next turn
        # folds back on it before planning recalls episodes (_turn_end_settle).
        # Everything the job reads is captured now: the next turn changes
        # kernel state.
        if self._memory_interface:
            _der_duration_ms = int((time.perf_counter() - _der_start_time) * 1000)
            _te_items = list(completed_items)
            _avg_step_ms = _der_duration_ms / len(_te_items) if _te_items else 0.0
            _te_stats = dict(
                session_id=_session,
                task_class=task_class,
                strategy=plan.strategy,
                total_steps=len(plan.steps),
                steps_completed=len(_te_items),
                tokens_used=_tokens_used,
                avg_step_duration_ms=_avg_step_ms,
                outcome=outcome,
                graph_mature=is_mature,
            )
            # One entry per call the steps ACTUALLY made (_step_calls): a node
            # step used to record {"tool": "none"}, so episodes held no tools
            # and skill capture (needs successful calls) could never fire.
            _tool_seq = [
                {
                    "tool": c.get("tool") or "none",
                    "params": dict(c.get("args") or {}),
                    "target": c.get("target", ""),
                    "success": bool(c.get("ok", True)),
                    "step": ci.step_number,
                    "description": ci.description,
                }
                for ci in _te_items
                for c in _step_calls(ci)
            ]
            _full_content = "\n".join(
                f"[Step {i + 1}] {o}" for i, o in enumerate(step_outputs) if o
            )
            _te_task = plan.original_task
            # Spec D9: task completion is outside evidence for this task's
            # FIXes (-> VERIFIED_FIX + LESSON candidate); closes its cases.
            _memory_events_submit(
                self, "record_task_end",
                thread_id=_session,
                task_id=f"{_session}:{_turn_id or ''}",
                success=(outcome == "success"),
            )

            def _turn_end_job():
                self._save_card_footprint(plan, _te_items, outcome, card_id=_te_card_id)
                try:
                    self._memory_interface.mycelium_record_plan_stats(**_te_stats)
                except Exception as _exc:
                    loud_error(_exc, "mycelium_record_plan_stats")
                # EPISODIC STORAGE closes the read/write loop:
                # assemble_episodic_context() reads these episodes.
                try:
                    self._store_task_episode(
                        task_summary=_te_task,
                        full_content=_full_content,
                        outcome_type=outcome,
                        tool_sequence=_tool_seq,
                        session_id=_session,
                        duration_ms=_der_duration_ms,
                    )
                except Exception as _exc:
                    loud_error(_exc, "store_task_episode")
                # Skill capture. It never fired while node steps recorded tool
                # "none"; with real calls it saved one task's call list per run
                # (5 in one eval). It now needs the call shape to RECUR in >= 3
                # successful similar episodes (workflow_capture.MIN_RECURRENCES).
                try:
                    self._maybe_trigger_skill_creation(
                        tool_sequence=_tool_seq,
                        task_summary=_te_task,
                    )
                except Exception as _exc:
                    loud_error(_exc, "skill_creation_trigger")

            _turn_end_submit(self, _session, _turn_end_job)

        # â”€â”€ EventBus: emit der:done â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            get_event_bus().emit(
                IRISStreamEvent.DER_DONE,
                data={
                    "task_id": _turn_id or plan.original_task[:40],
                    "outcome": outcome,
                    "mode": queue.mode.value,
                    "total_steps": len(queue.items),
                    "completed": len(completed_items),
                    "tokens_used": _tokens_used,
                    "mode_history": [
                        {
                            "previous": c.previous_mode.value if c.previous_mode else None,
                            "new": c.new_mode.value,
                            "reason": c.reason,
                            "turn_id": c.turn_id,
                        }
                        for c in queue.mode_history
                    ],
                    # ToolCallTree (REQ-13): structured snapshot of all tool calls
                    "tool_call_tree": (
                        self._get_tool_box().get_tool_call_tree(
                            conversation_id=self.conversation_id
                        )
                    ),
                },
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
            )
        except Exception:
            pass

        # REQ-12 (Wave 9): emit final context usage for the DER task.
        # Covers the "zero steps executed" case (plan rejected before any
        # step ran) where the per-step emit never fired. Uses the real
        # per-thread self._context_fill (how full the window is) â€” never 0 for an active thread.
        # All return paths below are preceded by this single emit.
        self._emit_context_usage(
            step_number=len(completed_items),
            total_steps=len(queue.items),
        )

        # Phase 1.5: if any step failed, synthesize a user-facing summary
        # that explains what worked, what failed, and what to do next.
        # Unless the OBJECTIVE is met: a failed intermediate attempt whose facts
        # a later step found is not a failed task (live 2026-10-02 run A7: run
        # grade pass, C=1.000, one failed search step -> "I couldn't complete
        # that task. 3/5 steps finished" with the answer in hand). An open or
        # blocked fact keeps this failure path.
        if queue.failed_ids and not (step_outputs and AgentKernel._goal_contract_met(self)):
            # REQ-16 AC2 (T32): a task with failed steps did NOT exit naturally.
            self._der_stamp_session_exit(False)
            _synthesis = self._der_synthesize_outcome(
                plan, completed_items, queue, _session
            )
            # REQ-18 AC2 (T31): correlate which synthesis path ran.
            try:
                from backend.agent.der_trace import get_der_trace

                get_der_trace(self._der_trace_task_id()).record(
                    "synthesis",
                    path="failure" if _synthesis else "deterministic_failure",
                    ran=bool(_synthesis),
                )
            except Exception:
                pass
            if _synthesis:
                _emit_terminal_event()
                return self._goal_contract_name_blocked(_synthesis)
            # LLM synthesis unavailable (e.g. model rate-limited â€” the very
            # failure that broke the step) -> deterministic fallback so the user
            # is NEVER left with silence (Part B).
            _emit_terminal_event()
            return self._goal_contract_name_blocked(
                AgentKernel._der_deterministic_failure_summary(
                    plan, completed_items, queue
                )
            )

        if step_outputs:
            # REQ-16 AC2 (T32): a task that ran steps to completion exited
            # naturally.
            self._der_stamp_session_exit(True)
            # AC3.6 defense-in-depth (session-334, live T3): the loop-level
            # continuation gate in _der_plan_next_step is bypassable â€” COMPRESS
            # (rec==1) skips it, a non-AGENTIC/FULL mode skips it, and a planner
            # JSON-parse failure returns None. Measured 2026-09-17: grade=capped
            # with 1 open unblocked required fact still produced "I've completed
            # the task. 1/1 steps finished." The spec says the turn SHALL NOT
            # terminate while a required fact is open and unblocked. Guard the
            # FINALIZE boundary itself so a false success claim is impossible no
            # matter which bypass fired.
            try:
                _gc_open_final = list(self._goal_contract_open_facts() or [])
            except Exception:
                _gc_open_final = []
            # Test the COUNT, never truthiness: a non-sequence (or any object
            # with a permissive __bool__) would otherwise trip this branch with
            # zero open facts and suppress a legitimate success claim.
            #
            # Item 2 (2026-09-24, owner-approved): this guard must not narrate a
            # FAILURE for a turn that succeeded. Live conv-145 ("create a file
            # eyes_note3.md ... then read it back to me"): write_file and
            # read_file both returned success, the file on disk matched the
            # request, no step failed â€” and the contract still reported one open
            # required fact (counters: seeded=1 mapped=0 readded=1 covered=0), so
            # this branch appended "I couldn't fully complete the task â€” still
            # open: ..." to a correct, successful answer. A success claim is only
            # FALSE when a step failed, so the suppression now also requires
            # that. The mismatch is still recorded (WARNING above) and the fact
            # stays in the contract â€” nothing is hidden, and no false success
            # can slip through, because any failed or missing step keeps the
            # original suppression.
            _open_ok = bool(completed_items) and not list(
                getattr(queue, "failed_ids", None) or []
            )
            if len(_gc_open_final) > 0 and not _open_ok:
                logger.warning(
                    "[goal-contract] finalize with %d open unblocked fact(s) â€” "
                    "suppressing success claim: %r",
                    len(_gc_open_final), str(_gc_open_final[0])[:160],
                )
                _emit_terminal_event()
                _open_facts_txt = "; ".join(
                    str(_f)[:200] for _f in _gc_open_final[:5]
                )
                # Session-345 (live, conv-135): suppression must not hide what
                # WAS gathered. With completed steps on record, synthesize the
                # partial answer and append the open fact line â€” the fixed
                # string alone told the user nothing about the data the crawl
                # actually found. The failure path takes over if synthesis
                # itself is unavailable (deterministic close).
                _partial = None
                if completed_items:
                    try:
                        _partial = self._der_synthesize_outcome(
                            plan, completed_items, queue, _session
                        )
                    except Exception as _ps_err:
                        logger.warning(
                            "[goal-contract] partial synthesis failed: %s", _ps_err,
                        )
                if _partial:
                    return (
                        _partial.strip()
                        + "\n\nI couldn't fully complete the task â€” still open: "
                        + _open_facts_txt
                        + "\nWhat would you like me to do next?"
                    )
                return (
                    "I couldn't fully complete the task â€” required work is "
                    f"still open: {_open_facts_txt}\n"
                    "What would you like me to do next?"
                )
            # REQ-12 (AC1/AC2/AC3): synthesize the gathered evidence into a
            # final answer instead of raw-concatenating step outputs. Consumes
            # the same evidence the failure path consumes (plan.original_task
            # + completed step descriptions/results) and wires the previously-
            # dead _synthesize_response brain synthesis.
            _synthesis = self._der_synthesize_success_outcome(
                plan, completed_items, queue, _session
            )
            # REQ-18 AC2 (T31): correlate which synthesis path ran.
            try:
                from backend.agent.der_trace import get_der_trace

                get_der_trace(self._der_trace_task_id()).record(
                    "synthesis",
                    path="success" if _synthesis else "deterministic_success",
                    ran=bool(_synthesis),
                )
            except Exception:
                pass
            if _synthesis:
                _emit_terminal_event()
                return self._goal_contract_name_blocked(_synthesis)
            # REQ-12 (AC4): synthesis unavailable (e.g. reasoning provider
            # down) -> deterministic success summary mirroring
            # _der_deterministic_failure_summary so the user is never left
            # with raw concatenation (Part B symmetry).
            _emit_terminal_event()
            return self._goal_contract_name_blocked(
                AgentKernel._der_deterministic_success_summary(
                    plan, completed_items, queue
                )
            )
        # â”€â”€ Zero steps (or zero usable outputs) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # The crawl plan produced no executable URLs (all blocked/filtered
        # by BOT_BLOCKED_DOMAINS, or the LLM couldn't generate any). Return
        # a descriptive message so _plan_task's post-processing can surface
        # an actionable explanation instead of the generic "couldn't generate".
        # REQ-16 AC2 (T32): zero usable steps is NOT a natural exit.
        self._der_stamp_session_exit(False)
        _emit_terminal_event()
        return (
            f"[DER] {plan.strategy} â€” "
            f"{len(completed_items)}/{len(plan.steps)} steps completed.  "
            f"error: no usable sources found for '{getattr(plan, 'title', '') or getattr(plan, 'plan_title', '') or plan.original_task[:40]}'.  "
            + self._build_crawl_failure_explanation(plan)
        )

    def _der_stamp_session_exit(self, natural_exit: bool) -> None:
        """REQ-16 AC2 (T32): stamp the session's exit nature on the
        conversation memory so ``archive_on_session_end`` records an HONEST
        ``natural_exit`` when the session ends (the DER loop is the source of
        truth for whether the task completed).

        Success path -> natural_exit=True (task ran to completion); failure /
        zero-step path -> natural_exit=False (task did NOT complete). Best-
        effort, off the hot path, never raises â€” a missing conversation memory
        is simply skipped.
        """
        try:
            _mem = getattr(self, "_conversation_memory", None)
            if _mem is not None:
                _mem.natural_exit = bool(natural_exit)
        except Exception:
            pass
