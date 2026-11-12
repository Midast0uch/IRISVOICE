#!/usr/bin/env python3
"""
Agent Kernel

Orchestrates the dual-LLM system with:
- lfm2-8b for reasoning and planning
- lfm2.5-1.2b-instruct for tool execution
- Inter-model communication and state management
- Model failure fallback to single-model mode
"""

from __future__ import annotations

import re
import hashlib
import threading
import os

from .model_conversation import ModelConversation
from .inter_model_communication import InterModelCommunicator
from .vps_gateway import VPSGateway, VPSConfig
from .personality import PersonalityManager
from .memory import ConversationMemory, TaskRecord
from .model_router import ModelRouter
from .tool_bridge import AgentToolBridge
from .mcm_protocol.actions.pacman_fragment import is_external_tool
# REMOVED 2026-08-26 (session 260): `from backend.llm_service import llm as _llm`.
# MEASURED with `python -X importtime`: that import pulled in litellm, which was
# 6.26s of a 9.63s total -- 65% of the cost of importing this module -- and
# `_llm` was NEVER USED. Its only remaining mention is the docstring below at
# _dispatch_api: "Uses httpx directly instead of _llm.complete() to avoid
# thread-pool hangs." The code was deliberately moved onto httpx and the import
# was left behind. Nothing imports `_llm` from this module (checked).
#
# This is not only a test-suite problem. backend startup imports this module, so
# the same 6.26s was paid on every launch.
from . import streaming as _streaming
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.errors import RateLimitedError
from backend.agent.call_context import (
    CallClass,
    set_call_class,
    restores_call_class,
)
# GROUND TRUTH REQ-13: named counters for swallowed write-path failures.
# Pure in-process tally (threading only) - safe at module scope.
from backend.agent import write_counters as _write_counters
from backend.agent import row_sequence as _row_sequence






from backend.agent.tool_decision import ToolDecisionBox, Decision, DecisionKind, DispatchResult
from backend.iris_config import load_config
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import json
import asyncio
import logging
import time
from dataclasses import dataclass, field
from backend.utils.observability import (
    TurnMetrics,
    loud_error,
    get_turn_id,
    broadcast_inference_event,
)







_MONITOR_STATEMENT_CHARS = 900


def _monitor_statement(objective: str, completed_items, n: int = 4) -> str:
    """The Oracle's input for the `done` / `on_track` monitors: the objective
    and one bounded status line per recent step (~150-250 tokens).

    They used to score the Brain's whole continuation prompt, cut at the
    engine's 512-id cap: the instructions plus raw step outputs, so every
    call ran the longest input the model takes - `done` p50 2.3 s, max 4.3 s
    over 69 calls of one coding eval (2026-10-01), against ~0.2 s for a short
    input. The question needs the goal and what each step returned, nothing
    more. Shape change = new calibrated identity: rows carry criteria v2.
    """
    # Newest step first: the engine cuts the text at the job's budget (Oracle
    # jobs, judge_goal = 128 ids), and the cut must drop the OLDEST step.
    lines = [f"OBJECTIVE: {str(objective or '')[:200]}", "STEPS (newest first):"]
    for it in reversed(list(completed_items or [])[-n:]):
        env = getattr(it, "envelope", None)
        try:
            state = env.line() if env is not None else (
                str(getattr(it, "result", "") or "")[:160])
        except Exception:  # noqa: BLE001 - a status line is best-effort
            state = ""
        lines.append(
            f"[{getattr(it, 'step_number', '?')}] "
            f"{str(getattr(it, 'description', '') or '')[:80]}: {state[:200]}"
        )
    return "\n".join(lines)[:_MONITOR_STATEMENT_CHARS]























def _mycelium_ingest_step_tools(memory, item, step_success: bool, total_steps: int, session_id: str) -> None:
    """Tell the toolpath space which tools a settled step ACTUALLY called: one
    ingest per call, in order, all at the step number. ``item.tool`` is only the
    PLANNED tool and is empty for a node step (the tool model picks its tools
    while the step runs) - recording it stored "tool_none" for 73 of 154 live
    toolpath nodes. A step that made no call still records "none": that is the
    truth. Module level on purpose (stand-in kernels)."""
    if not memory:
        return
    calls = _step_calls(item)
    # (name, success) per call; the call's own ok only ever lowers the step's verdict
    signals = [(str(c.get("tool") or "none"), bool(step_success) and bool(c.get("ok", True)))
               for c in calls] or [("none", step_success)]
    for name, ok in signals:
        memory.mycelium_ingest_tool_call(
            tool_name=name,
            success=ok,
            sequence_position=item.step_number,
            total_steps=total_steps,
            session_id=session_id,
        )




def _step_tool_name(item) -> str:
    """The tool a settled step really used, for its tool:result / tool:error.

    A DER-DAG node has no item.tool (the planner writes goals; the node picks
    its tools), so the old ``item.tool or "direct"`` labelled every node
    "direct": the matrix verb read DIRECT and the frontend counted the settled
    card as tool-less and dropped it (live 2026-10-06). The node's decisive
    call names the tool; "direct" stays only for a node that made no call."""
    tool = getattr(item, "tool", None)
    if tool:
        return str(tool)
    call = _step_decisive_call(item)
    return str(call.get("tool")) if call and call.get("tool") else "direct"










def _node_failed_after_change(item) -> bool:
    """True when a node step changed files and the LAST command it ran after
    its last change failed. A planner step carries no expected_output (the
    planner emits goals only), so a node step was VERIFIED whenever its tool
    calls ran - also when the tests it ran on its own edit failed. A step that
    only OBSERVES failing tests (no change, eval c14) is not affected. Outside
    evidence only: the call log, not text. Module level (stand-in kernels)."""
    from backend.agent.node_executor import _CHANGE_TOOLS

    log = getattr(item, "node_call_log", None)
    if not isinstance(log, list):
        return False
    changes = [i for i, c in enumerate(log) if c.get("tool") in _CHANGE_TOOLS and c.get("ok", True)]
    if not changes:
        return False
    runs = [c for c in log[changes[-1] + 1:] if c.get("tool") == "run_command"]
    return bool(runs) and not runs[-1].get("ok", True)




def _step_digest(item) -> str:
    """Repeat-detection key of a settled step: a node step is the calls it
    made (``node_digest``, set by ``_der_run_node``); a direct tool step is
    its tool + params. Module level on purpose (stand-in kernels)."""
    _nd = getattr(item, "node_digest", None)
    if isinstance(_nd, str) and _nd:
        return _nd
    from backend.agent.tool_envelope import params_digest

    return params_digest(getattr(item, "tool", None), getattr(item, "params", None))




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














def _gc_coverage_label(verified: str, item, step_result) -> str:
    """The label a settled node gives the goal contract's coverage (goal_contract.mark_coverage).

    A DIRECT node (no tool: the node mode rule decided so) has
    nothing outside that could verify it, so a real answer commits UNVERIFIED for ever -
    and a fact it answered could never be covered: the turn pushed "cover the open fact"
    with more tool-less steps, BLOCKED the fact after 2 pushes and told the user it "could
    not cover" what it had just answered. Live 2026-10-27: "Pack sunscreen to protect your
    skin from the sun." for "in one short sentence, name one thing to pack for a beach
    trip" - 3 steps and a false "could not cover" note. Such an answer is ANSWERED: it
    covers a fact under the same own-terms / names rule as a verified result. Coverage
    is "addressed", not evidence - the evidence ladder never sees this label.
    Module level on purpose (stand-in kernels bind only some methods).
    """
    try:
        from backend.agent.external_reference import DIRECT

        if (verified == "UNVERIFIED" and getattr(item, "mode", None) == DIRECT
                and str(step_result or "").strip()):
            return "ANSWERED"
    except Exception as exc:  # noqa: BLE001 - the plain label stands
        logger.debug("[goal-contract] coverage label fell back: %r", exc)
    return verified










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




def _der_prior_research_delivered(owner, item, step_result, session_id: str) -> None:
    """A PRIOR RESEARCH section at the head of a tool result IS memory delivered to the
    step that ran the tool (research_memory.attach_prior put it there)."""
    try:
        from backend.agent.research_memory import PRIOR_HEADING

        if PRIOR_HEADING in str(step_result or ""):
            _der_recall_delivered(owner, item, "prior_research", [], session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[memory_events] prior research delivery not typed: %s", exc)


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

# REQ-1 AC8 (T2b, Decision 13 â€” revised 2026-08-19): the user-facing copy for
# the child steps of a sub-loop split. `branchLabel` is free text on the
# wire â€” CardChassis's ChassisBranchBadge renders whatever string arrives
# here, so the wording is owned in this ONE constant, not inlined at each
# emit site. NEVER "Sub-Loop" / "Detour" â€” those remain internal identifiers
# (sub_loop_split / is_subloop) and are UNCHANGED; this is the user-facing
# label only.
DER_SUBLOOP_BRANCH_LABEL = "Diving Deeper"









def _edit_diff_fields(item) -> dict:
    """The ``diff`` / ``diffs`` fields of a step's tool:result data ({} when the
    step edited no file). Module level: stand-in kernels in tests bind only some
    methods."""
    eds = getattr(item, "edit_diffs", None)
    if not isinstance(eds, list) or not eds:
        return {}
    return {"diff": eds[-1], **({"diffs": list(eds)} if len(eds) > 1 else {})}












def _remember_turn_urls(kernel, step_result, _where: str = "") -> int:
    """AC2.1 / AC9.3 / AC10.2 (session-319 fix): harvest every URL a step
    touched into turn memory, on ANY path.

    Turn URL memory used to be written ONLY inside `_der_finalize_step`, which
    the step loop skips entirely for a failed step (the loop branches to
    `_der_handle_step_failure` and `continue`s before finalize). So a crawl that
    came back with partial results and was then judged FAILED recorded nothing,
    and the next step re-fetched the same addresses -- the owner's "it still
    recrawls the same URLs if there's an error" report. Calling this from the
    failure path as well closes that hole: the refusal set learns from failures,
    not just successes.

    Deliberately MODULE-LEVEL, not a method: `_der_finalize_step` is driven by
    hand-rolled kernel doubles in the behavioral suite, and a new method on the
    instance would not exist on those doubles. Taking the kernel as an argument
    keeps one implementation usable from both call sites without touching tests.

    NOTE (honest limit): a TOTAL crash whose result text carries no
    `--- Source:`/`--- Attempted:`/`--- Dead:` lines yields nothing here -- the
    addresses are simply not knowable, because `crawler_query` resolves its seeds
    inside the crawler. That residual case can only be closed by recording the
    dispatch itself; tracked separately.

    Best-effort: URL memory is advisory and must never break the loop.
    Returns the number of addresses now held for this conversation.
    """
    try:
        import re as _re_urls
        from backend.agent.tool_envelope import normalize_url as _norm_url
        _conv = getattr(kernel, "conversation_id", None) or ""
        _fetched = set(getattr(kernel, "_der_crawled_urls", {}).get(_conv, set()))
        _text = str(step_result or "")
        for _m in _re_urls.findall(
            r"---\s*Source:\s*(https?://[^\s]+)", _text
        ):
            _n = _norm_url(_m.strip().rstrip(".,;)]"))
            if _n:
                _fetched.add(_n)
        # Attempted seeds count too: re-paying a parked/failed fetch in-turn is
        # exactly the futile-retry loop we are closing (AC9.3).
        for _tail in _re_urls.findall(r"---\s*Attempted:\s*([^\n]+)", _text):
            for _u in _tail.split():
                _u = _u.strip().rstrip(".,;)]")
                if _u.startswith("http"):
                    _n = _norm_url(_u)
                    if _n:
                        _fetched.add(_n)
        # Explicit dead-address memory (AC10.2): zero-page deaths the Attempted
        # line cannot see. Dead joins the refusal set AND its own set.
        for _tail in _re_urls.findall(r"---\s*Dead:\s*([^\n]+)", _text):
            for _u in _tail.split():
                _u = _u.strip().rstrip(".,;)]")
                if not _u.startswith("http"):
                    continue
                _n = _norm_url(_u)
                if not _n:
                    continue
                _fetched.add(_n)
                try:
                    from backend.agent.write_counters import bump as _bump_dead
                    _bump_dead("envelope.dead_hits")
                except Exception:
                    pass
                try:
                    _du = dict(getattr(kernel, "_der_dead_urls", {}))
                    _dub = set(_du.get(_conv, set()))
                    _dub.add(_n)
                    while len(_dub) > 500:
                        _dub.pop()
                    _du[_conv] = _dub
                    kernel._der_dead_urls = _du
                except Exception:
                    pass
        if _fetched:
            _cu = dict(getattr(kernel, "_der_crawled_urls", {}))
            _cu[_conv] = _fetched
            kernel._der_crawled_urls = _cu
        return len(_fetched)
    except Exception:
        return 0  # URL memory is advisory â€” never block the loop




# â”€â”€ Parallel-node scheduler helpers (module level on purpose: stand-in
# kernels bind only some methods - a helper on the class would be auto-stubbed
# and the loop would silently skip the real code). `self` is the kernel. â”€â”€







def _der_post_step(self, item, step_result, step_success, verdict, _phase, *,
                   queue, plan, _session, _turn_id, context_package, completed_items,
                   step_outputs, _tokens_used, _token_budget, is_mature, _live_ctx,
                   from_voice, inflight) -> int:
    """Settle ONE finished node on the loop thread: failure routing / split /
    graft, finalize, missing-artifact grafts, and the split race. Moved out
    of the loop unchanged (parallel nodes, 2026-10-04); returns the tokens
    used so far."""
    # A node that lost its split race, or whose plan or turn was dropped,
    # did work nobody needs: it settles as not needed - no graft, no row.
    _why = getattr(item, "_race_lost", "") or getattr(item, "_node_cancelled", "")
    if _why:
        item.result = f"[not needed: {_why}]"
        queue.mark_complete(item.step_id)
        logger.info("[DER] node %s settled as not needed (%s)", item.step_id, _why)
        return _tokens_used
    if not step_success:
        # tc-decide-v7 (2026-11-07): the step FAILED, so every tool_choice row
        # held for it is a wrong pick - including a recovered step: the pick
        # that failed is what the retry had to replace. Stamp BEFORE routing so
        # the rows are written once even when the recovery finalizes normally.
        try:
            from backend.agent import tool_choice_outcome_label as _tcol

            _tcol.stamp(getattr(item, "step_id", None), _turn_id, False)
        except Exception:  # noqa: BLE001 - a label never blocks a settle
            logger.debug("[DER] tool_choice retry stamp failed")
        # REQ-4 (specs/dag-node-execution-model): before the graft
        # handler runs, consult the node router. A recovery node that
        # advertises this failure's reason executes in place of the
        # failing node; a recovered step finalizes normally below
        # (no branch was written in the failing node's module).
        _recovered = self._der_route_step_failure(
            item, step_result, _session, _turn_id, plan, queue=queue,
        )
        if _recovered is not None:
            step_result = _recovered
            step_success = True
        else:
            # C1 FIX: preserve the real error so the graft recovery prompt
            # receives it (item.result is otherwise only set on success).
            item.result = step_result
            # A3 FIX: fragment the failed output here (the shared
            # _der_finalize_step helper is only reached for successful
            # steps, so failures would otherwise never be stored).
            # D1: on lane("memory_events"), never inline - the recovery waits
            # on nothing this note decides (it embeds, dedups and writes; it
            # held the loop 56 s before s2's graft, conv-1573 2026-10-12).
            try:
                if self._memory_interface and step_result:
                    _ep = self._memory_interface.episodic
                    if hasattr(_ep, "fragment_and_store"):
                        from backend.utils.durability_queue import lane as _durability_lane

                        if not _durability_lane("memory_events").submit(
                            "der_failure_fragment", _ep.fragment_and_store,
                            content=f"[DER FAIL Step {item.step_number}: "
                                    f"{item.description[:80]}]\n{step_result[:500]}",
                            session_id=_session,
                            chunk_type="der_failure",
                            zone="tool",
                        ):
                            logger.warning("[DER] der_failure note for %s not queued "
                                           "(memory_events lane full)", item.step_id)
            except Exception as _frag_exc:  # noqa: BLE001 - a note never blocks recovery
                logger.warning("[DER] der_failure note for %s failed: %r",
                               item.step_id, _frag_exc)
            # Step failed after retry â€” mark, abort downstream, graft.
            self._der_handle_step_failure(
                item, queue, plan, _session, _turn_id, context_package,
                step_result=step_result,
            )
            # A failed split child settles its parent too. Only the success
            # path below called _der_settle_split, so when every child of a
            # graft failed the parent sat in split_pending - neither complete
            # nor failed - and the dependents hold_split_parent revived waited
            # on it. A child that split again is a parent now: its own
            # children settle it.
            try:
                if item.step_id not in (getattr(queue, "split_pending", None) or {}):
                    _der_settle_split(self, item, queue, inflight)
            except Exception as _settle_exc:  # noqa: BLE001 - never block the turn
                logger.warning("[DER] split settle after failure of %s failed: %r",
                               item.step_id, _settle_exc)
            # AC5.6 (session-319 fix): the failure/abort path never
            # reached the completion grade site â€” `_der_report_run_grade`
            # is only called from finalize-complete (which needs
            # queue.is_complete()) and continuation-done, so a run that
            # died on a failed step reported NO grade at all (conv-102
            # and the T21 probe both logged zero "run grade" lines).
            # Grade here when no PENDING work remains: failed, aborted
            # and vetoed steps all count as settled â€” that is the honest
            # reading of "this run is over". Deduped by turn inside the
            # helper, so the normal completion path cannot double-report.
            try:
                _pending_after_fail = [
                    _pi for _pi in (getattr(queue, "items", []) or [])
                    if _pi.step_id not in queue.completed_ids
                    and _pi.step_id not in queue.failed_ids
                    and _pi.step_id not in queue.vetoed_ids
                ]
                if (
                    not _pending_after_fail
                    and (getattr(queue, "items", []) or [])
                ):
                    self._der_report_run_grade(
                        completed_items, _turn_id, "failure-settled"
                    )
            except Exception:
                pass
            return _tokens_used  # grafted steps are now in the queue

    # â”€â”€ Phase 4: finalize this step via the shared helper â”€â”€
    _tokens_used = self._der_finalize_step(
        item,
        step_result,
        step_success,
        step_outputs,
        completed_items,
        _tokens_used,
        _token_budget,
        _session,
        _turn_id,
        _phase,
        is_mature,
        _live_ctx,
        plan,
        context_package,
        queue,
        verdict,
        from_voice,
    )

    # â”€â”€ Partial-artifact completion (live 2026-09-25) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # A step is ONE tool call, so a step naming several files writes only
    # one. Detect the remainder and graft a step per missing file BEFORE
    # the loop settles, so the user gets the files that were asked for.
    _grafted = self._der_graft_missing_artifacts(
        item, plan, queue, _session, _turn_id,
        _token_budget=_token_budget, _tokens_used=_tokens_used,
    )
    # tc-decide-v7 (2026-11-07): a post-finalize artifact graft is a RETRY of
    # this step - the pick wrote only part of the files the step named. The
    # step's tool_choice rows are stamped HERE, after the graft count exists,
    # so "completed" means "no failure, no graft, and the step really is in
    # completed_ids" (a split parent is held, not completed).
    _der_settle_split(self, item, queue, inflight)
    try:
        from backend.agent import tool_choice_outcome_label as _tcol

        _tc_step_ok = (
            not int(_grafted or 0)
            and item.step_id in getattr(queue, "completed_ids", ())
        )
        _tcol.stamp(getattr(item, "step_id", None), _turn_id, _tc_step_ok)
    except Exception:  # noqa: BLE001 - a label never blocks a settle
        logger.debug("[DER] tool_choice completion stamp failed")
    return _tokens_used












# <kernel-split:imports> generated by scripts/kernel_split_check.py move; do not edit by hand
from backend.agent.kernel.base import (
    AVG_STEP_COST,
    DER_EMERGENCY_STOP,
    DER_FOLD_BACK_MAX,
    DER_MAX_CYCLES,
    DER_MAX_GRAFTS,
    DER_MAX_UNVERIFIED_REPROPOSE,
    DER_MAX_VETO_PER_ITEM,
    DER_TOKEN_BUDGETS,
    ExecutionMode,
    ResolvedWindow,
    _CLAIM_LOCKS,
    _CLAIM_LOCKS_GUARD,
    _DER_NODE_QUOTA,
    _DER_PARALLEL,
    _FILL_NO_TURN,
    _NODE_CLAIMS,
    _SCREEN_CLAIM,
    _STEP_ID_KEYS,
    _der_fold_envelope,
    _der_ledger_storage_path,
    _der_recall_delivered,
    _der_recovery_lock,
    _emit_event,
    _memory_events_submit,
    _step_calls,
    _step_decisive_call,
    _step_evidence_cap,
    _step_tool,
    _turn_in_flight,
    _update_counters,
    _update_counters_lock,
    debit_work_units,
    derive_work_units_0,
    logger,
    resolve_der_token_budget,
)
import backend.agent.kernel.base as _k_base
from backend.agent.kernel.models import (
    _resolve_effective_key,
    ModelsMixin,
)
import backend.agent.kernel.models as _k_models
from backend.agent.kernel.surface import (
    _stamp_row_seq,
    SurfaceMixin,
)
import backend.agent.kernel.surface as _k_surface
from backend.agent.kernel.context import (
    _dedupe_fact_lines,
    _dedupe_fact_rows,
    _fact_line,
    _recent_user_turn_texts,
    _same_fact_unit,
    ContextMixin,
)
import backend.agent.kernel.context as _k_context
from backend.agent.kernel.turn import (
    _BROWSER_ACTION_RE,
    _LIVE_BROWSER_RE,
    _TURN_END_FOLD_WAIT_S,
    _developer_mode,
    _turn_end_settle,
    TurnMixin,
)
import backend.agent.kernel.turn as _k_turn
from backend.agent.kernel.planning import (
    _VOICE_TURN_NOTE,
    _plan_step_deps,
    _voice_turn_note,
    PlanningMixin,
)
import backend.agent.kernel.planning as _k_planning
from backend.agent.kernel.der.node import (
    _NODE_CORE_TOOLS,
    _der_claim,
    _der_claim_lock,
    _der_node_domain,
    _der_node_load,
    _der_release,
    _der_start_node,
    _der_take_finished,
    _narrow_node_tools,
    _node_call_parallel_ok,
    _node_claim_of,
    DerNodeMixin,
)
import backend.agent.kernel.der.node as _k_der_node
from backend.agent.kernel.der.physics import (
    _der_physics_settle,
    _der_settle_split,
    DerPhysicsMixin,
)
import backend.agent.kernel.der.physics as _k_der_physics
from backend.agent.kernel.der.recovery import (
    _plan_steps_open,
    _recovery_candidates,
    DerRecoveryMixin,
)
import backend.agent.kernel.der.recovery as _k_der_recovery
from backend.agent.kernel.der.report import (
    TaskContext,
    _CLAIMS_MISSING_RE,
    _READABLE_FORMAT_RULES,
    _STUB_STOPWORDS,
    _claims_missing,
    _der_neighbors_block,
    _short_reply_carries_results,
    DerReportMixin,
)
import backend.agent.kernel.der.report as _k_der_report
# </kernel-split:imports>

class AgentKernel(ModelsMixin, SurfaceMixin, ContextMixin, TurnMixin, PlanningMixin, DerNodeMixin, DerPhysicsMixin, DerRecoveryMixin, DerReportMixin):
    """
    Central orchestrator for the dual-LLM agent system.

    Coordinates:
    - lfm2-8b (reasoning model) for planning and analysis
    - lfm2.5-1.2b-instruct (execution model) for tool execution
    - Inter-model communication and state management
    - Model failure fallback to single-model mode
    """

    def __init__(
        self,
        config_path: str = "./backend/agent/agent_config.yaml",
        session_id: str = "default",
        conversation_id: Optional[str] = None,
    ):
        """
        Initialize AgentKernel with dual-LLM coordination.

        Args:
            config_path: Path to agent configuration YAML
            session_id: Session identifier for WebSocket routing and Mycelium
            conversation_id: Conversation identifier for per-thread context.
                             If None, falls back to session_id.
        """
        self.config_path = config_path
        self.session_id = session_id
        self.conversation_id = conversation_id or session_id

        # REQ-6: per-conversation soft-cancel flag. Set by the gateway when the
        # user switches away from this thread (switch_conversation / sync_state /
        # new_conversation / clear_chat). The DER loop polls this between steps and
        # exits cleanly without emitting further events for this conversation.
        self._cancel_requested = threading.Event()

        # W6 (T27-T29): per-conversation DER lock â€” prevents concurrent DER
        # execution on the same conversation. Accessed via _conversation_der_locks
        # class-level dict keyed by conversation_id.
        self._der_active = False

        # Structured logger (module-level logger bound to the instance so the
        # DER soft-cancel path and any other self._logger call sites work).
        self._logger = logging.getLogger(__name__)

        # Core components
        self._model_router: Optional[ModelRouter] = None
        self._vps_gateway: Optional[VPSGateway] = None
        self._conversation_memory: Optional[ConversationMemory] = None
        self._personality: Optional[PersonalityManager] = None
        self._tool_bridge: Optional[AgentToolBridge] = (
            None  # Will be initialized lazily
        )
        # For brainâ†”executor logging
        self._inter_model_communicator: Optional[InterModelCommunicator] = None

        # State management
        self._single_model_mode = False
        self._available_model_id: Optional[str] = None
        self._initialization_error: Optional[str] = None

        # Model selection (user-configurable dual-LLM)
        # NOTE (2026-08-16): `_model_provider`, `_selected_reasoning_model` and
        # `_selected_tool_execution_model` used to be assigned here and kept in
        # sync by hand from half a dozen call sites. They are now READ-ONLY
        # PROPERTIES derived from the process-wide role-binding table â€” see
        # their definitions below. A stale copy of the user's model choice is
        # not a bug that can be fixed here; it is a bug that can only be made
        # impossible, by there being no copy.

        # OpenAI-compatible endpoint â€” covers lmstudio, llamafile, vllm, or any custom server.
        # Set via configure_lmstudio() (legacy name kept) or configure_openai_compat().
        # Defaults to LM Studio's default port; overridden when the user saves settings.
        self._lmstudio_endpoint: str = "http://localhost:1234"

        # In-process `LocalModelManager` binding â€” non-None when iris_gateway
        # has loaded a model via the in-process path. `_get_lmstudio_client()`
        # checks this before creating a real HTTP client; when set AND the
        # provider is `iris_local`, inference goes through the manager's
        # `InProcessOpenAIAdapter` with zero network hops.
        # In-process `LocalModelManager` binding â€” non-None when iris_gateway
        # has loaded a model via the in-process path. `_get_lmstudio_client()`
        # checks this before creating a real HTTP client; when set AND the
        # provider is `iris_local`, inference goes through the manager's
        # `InProcessOpenAIAdapter` with zero network hops.
        self._inprocess_local_mgr: Any = None

        # T17 (REQ-1 AC1.3): in-flight goal references, keyed by conversation
        # id. Set at plan start; follow-up voice turns mutate the live goal
        # through this â€” never fork into a new plan. Initialized lazily so
        # test doubles built via `__new__` (which never call __init__) still
        # find the attribute.
        self._active_goals = getattr(self, "_active_goals", None) or {}

        # Ollama native API endpoint (used when provider == "local").
        self._ollama_endpoint: str = "http://localhost:11434"

        # Cloud/remote API credentials (used when provider == "api").
        # Supports any OpenAI-compatible remote API: OpenAI, Groq, Together, OpenRouter, etc.
        self._api_key: str = ""
        # Provider id the kernel's _api_key belongs to. `_api_key` is a single
        # shared field; without this, a provider switch reuses the previous
        # provider's key (e.g. a Cerebras key attached to a Cohere instance).
        self._api_key_provider: str = ""
        self._api_base_url: str = "https://api.openai.com/v1"

        # Thinking extracted from the most recent _respond_direct call.
        # Set before returning so iris_gateway can include it in the text_response payload.
        self._pending_thinking: str = ""

        # VPS configuration (loaded from settings)
        self._vps_config: Optional[VPSConfig] = None

        # Internet access is now a global app-wide flag (see
        # set_global_internet_access / get_global_internet_access below).

        # Swarm compound collaboration (default: False â€” enabled via UI toggle)
        self._swarm_enabled: bool = False
        self._swarm_coordinator = None
        self._context_control_handler = None

        # â”€â”€ Inference behaviour fields (wired from inference_mode card) â”€â”€
        self._thinking_style: str = "balanced"  # concise | balanced | thorough
        self._response_length: str = "medium"  # short | medium | long
        self._reasoning_effort: str = "balanced"  # fast | balanced | accurate
        self._tool_mode: str = "auto"  # auto | ask_first | disabled

        # Launcher mode: "personal" (default) or "developer"
        # Developer mode injects PROJECT.md into every system prompt so the
        # local agent has full codebase context and can modify source files.
        self._launcher_mode: str = "personal"
        # cached PROJECT.md content
        self._developer_context: Optional[str] = None

        # â”€â”€ Model context window registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Maps (provider, model_name_substring) â†’ context window in tokens.
        # Used by resolve_context_window() so memory, conversation history,
        # and MCM budgets are never hardcoded â€” they adapt to the model.
        self._context_window_overrides: dict[str, int] = {}

        # â”€â”€ REQ-3 (T2): backend-declared task-card identity registry â”€â”€â”€â”€â”€â”€â”€â”€
        # Maps DER task_id -> card_id so the SAME task's early-skeleton and
        # DER-queue task:start emits (and every lifecycle event after it)
        # resolve to one Liquid Ink card instead of two. Bounded â€” this is a
        # per-kernel-lifetime dict, not per-turn, so it must not grow forever
        # (see _register_card's eviction).
        self._card_by_task: dict[str, str] = {}
        self._active_card_id: Optional[str] = None
        self._CARD_REGISTRY_CAP: int = 200

        # Domain 4.5 â€” proactive skill creation.
        # Tracks how many times each normalized tool-name sequence (joined with "â†’")
        # has been used this session.  When a pattern hits the threshold, the agent
        # is prompted to codify it as a SKILL.md.
        self._session_tool_patterns: dict[str, int] = {}
        self._skill_trigger_threshold: int = 3
        # Patterns already prompted this session â€” avoid repeating the prompt.
        self._prompted_skill_patterns: set[str] = set()

        # Cached OpenAI client for LM Studio â€” created once, reused on every call.
        # Rebuilding _OpenAI() per-call recreates the full httpx connection pool,
        # adding unnecessary overhead on every message.  Invalidated in
        # configure_lmstudio() whenever the endpoint URL changes.
        self._lmstudio_client: Optional[Any] = None

        # Main event loop â€” captured during startup so background threads can
        # dispatch coroutines via run_coroutine_threadsafe.
        self._broadcast_loop: Optional[Any] = None

        # Initialize components
        self._initialize_components()

        # Auto-apply a provider configured in iris_config.json so the agentic /
        # DER loop does not silently fall back to a local OpenAI-compatible model
        # when a cloud provider is already configured.  Local-only setups (no
        # provider / no key) are left uninitialized â€” the existing wait-for-user
        # (Models-card APPLY / model_selection confirm_card) behaviour is preserved.
        self._router = InferenceRouter(load_config())
        # Context window (2026-09-27): the router asks us for the window of the
        # role it is about to call, so it can (a) offer it to a provider that is
        # able to set one - Ollama, as options.num_ctx - and (b) cap the prompt
        # for the providers that cannot, where the window is fixed and the only
        # thing we control is how much we send. The resolver is our own method
        # on purpose: the window table lives in THIS class, and a copy inside
        # the router would drift away from it. Router-side failures degrade to
        # "no window known" and never break a turn.
        self._router.set_window_resolver(self.resolve_context_window)
        # Wedge fix (session 363, pin_35af67d07c5f): the router calls us back
        # at every model-dispatch entry and inside the transport retry
        # ladders, so the turn budget + client check run INSIDE the blocking
        # paths. The DER loop condition only evaluates BETWEEN cycles, so a
        # turn blocked inside ONE operation never re-evaluated it and the
        # 600 s budget never fired (chain client w1 ran 19+ min while the
        # backend logged nothing for 18). The check is a bound method of THIS
        # kernel â€” the router is per-kernel (not a singleton), so there is no
        # cross-session leakage â€” and it reads per-turn state set in
        # _execute_plan_der. Modeled on set_window_resolver directly above.
        self._router.set_turn_budget_check(self._turn_choke_check)
        # In-process local models (2026-09-27). The gateway attaches the local
        # model manager to the routers that EXIST when a model is loaded, so a
        # kernel created LATER (a new WS session) starts with
        # `_inprocess_mgr = None` and every `local:<model>` planning call dies:
        #   [AgentKernel._plan_task] router planning failed:
        #     No local model loaded for in-process inference
        # No plan means no DER, so the step consumers (review_verdict,
        # sufficient, done, on_track, has_gaps, needs_action,
        # recovery_strategy) never ran and could never reach the Wave 7 bar no
        # matter how much traffic was driven. The manager is a process-wide
        # singleton, so attach it here instead of depending on load-time fan-out
        # reaching every future kernel. get_local_model_manager() constructs the
        # manager object only; it loads no weights.
        try:
            from .local_model_manager import get_local_model_manager

            self._router.set_inprocess_manager(get_local_model_manager())
        except Exception as _mgr_err:  # noqa: BLE001 â€” a missing manager is not fatal
            logger.debug(
                "[AgentKernel] in-process manager attach skipped: %s", _mgr_err
            )

    def _initialize_components(self):
        """Initialize all core components with error handling."""
        try:
            # Initialize Model Router with UNINITIALIZED mode (lazy loading)
            logger.info(
                "[AgentKernel] Initializing Model Router in UNINITIALIZED mode (lazy loading)..."
            )
            from .model_router import InferenceMode

            self._model_router = ModelRouter(
                self.config_path, inference_mode=InferenceMode.UNINITIALIZED
            )
            logger.info(
                "[AgentKernel] Model Router initialized - models will NOT be loaded automatically"
            )
            logger.info(
                "[AgentKernel] Models will be loaded only when user selects Local Model inference mode"
            )

            # In UNINITIALIZED mode, we don't have models yet
            logger.info(
                "[AgentKernel] Waiting for user to configure inference mode (Local/VPS/OpenAI)"
            )
            self._single_model_mode = False

        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Model Router: {e}")
            self._initialization_error = f"Model Router initialization failed: {e}"
            self._model_router = None

        # VPS Gateway is lazy: only created when the user explicitly enables VPS mode
        # via configure_vps(). Creating it per-session at startup is wasteful and triggers
        # health-check loops for every WebSocket reconnect even when VPS is disabled.
        self._vps_config = VPSConfig(enabled=False)
        self._vps_gateway = None
        logger.info(
            "[AgentKernel] VPS Gateway deferred (lazy init â€” awaiting user VPS configuration)"
        )

        try:
            # Initialize Conversation Memory
            logger.info(
                f"[AgentKernel] Initializing Conversation Memory for session {self.session_id}..."
            )
            self._conversation_memory = ConversationMemory(
                session_id=self.session_id,
                conversation_id=self.conversation_id,
                max_messages=10,  # Default from requirements
            )
            logger.info("[AgentKernel] Conversation Memory initialized")

        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Conversation Memory: {e}")
            self._initialization_error = (
                f"Conversation Memory initialization failed: {e}"
            )
            self._conversation_memory = None

        try:
            # Initialize Personality Manager
            logger.info("[AgentKernel] Initializing Personality Manager...")
            self._personality = PersonalityManager()
            logger.info("[AgentKernel] Personality Manager initialized")

        except Exception as e:
            logger.error(f"[AgentKernel] Failed to initialize Personality Manager: {e}")
            self._initialization_error = (
                f"Personality Manager initialization failed: {e}"
            )
            self._personality = None

        try:
            # Initialize Inter-Model Communicator for brainâ†”executor logging (Bug 5 fix)
            logger.info("[AgentKernel] Initializing Inter-Model Communicator...")
            if self._model_router:
                model_conversation = ModelConversation()
                self._inter_model_communicator = InterModelCommunicator(
                    model_router=self._model_router, conversation=model_conversation
                )
                logger.info("[AgentKernel] Inter-Model Communicator initialized")
            else:
                logger.warning(
                    "[AgentKernel] Inter-Model Communicator not initialized: Model Router unavailable"
                )
        except Exception as e:
            logger.error(
                f"[AgentKernel] Failed to initialize Inter-Model Communicator: {e}"
            )
            self._inter_model_communicator = None

        # Tool Bridge will be initialized lazily when needed

        # Memory Foundation integration
        self._memory_interface: Optional[Any] = None

        # MCM Protocol Orchestrator â€” wired after set_memory_interface()
        self._mcm_orch = None

        # Trust-routing (plan W2): whether the current turn touched external/
        # web sources (web_search / crawler_query). When True, turn-pair
        # fragments are stored in the 'reference' zone instead of 'trusted'.
        # Reset at the start of each turn (process_text_message /
        # _execute_plan_der) and set when an external tool runs.
        self._turn_touched_external: bool = False
        # D3 (2026-10-31): set at the top of every turn (process_text_message).
        self._turn_started_monotonic: float = 0.0

        # â”€â”€ DER Loop components â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # DER_MAX_CYCLES / DER_MAX_VETO_PER_ITEM re-exported at module level
        # for spec compliance (Gap 11). Canonical values live in der_constants.
        self._task_classifier = None
        self._reviewer = None
        self._mode_detector = None
        self._der_tokens_used: int = 0

        try:
            from backend.memory.mycelium.kyudo import TaskClassifier as _TC

            self._task_classifier = _TC()
            logger.info("[AgentKernel] TaskClassifier initialized (DER)")
        except Exception as _tc_err:
            logger.warning(f"[AgentKernel] TaskClassifier unavailable: {_tc_err}")

        try:
            from backend.agent.der_loop import Reviewer as _Reviewer

            # memory_interface wired later via set_memory_interface()
            self._reviewer = _Reviewer(adapter=self, memory_interface=None)
            logger.info("[AgentKernel] Reviewer initialized (DER)")
        except Exception as _rv_err:
            logger.warning(f"[AgentKernel] Reviewer unavailable: {_rv_err}")

        try:
            from backend.agent.mode_detector import ModeDetector as _MD

            self._mode_detector = _MD()
            # The `mode` Oracle consumer was REMOVED 2026-10-10 (owner): the
            # detector keeps its keyword classifier only â€” no engine wiring, no
            # row sink (see mode_detector.py).
            logger.info("[AgentKernel] ModeDetector initialized (DER)")
        except Exception as _md_err:
            logger.warning(f"[AgentKernel] ModeDetector unavailable: {_md_err}")

        # REQ-6 AC2 (T9): fire the bounded, latched, background LFM warm-up so
        # the first user turn runs at warm latency. Non-blocking â€” a daemon
        # thread does the load; a failure leaves the normal cold path intact.
        try:
            from backend.agent.semantic_gate import ensure_warm_start

            ensure_warm_start()
        except Exception as _wu_err:
            logger.debug("[AgentKernel] LFM warm-up kick failed: %s", _wu_err)

        # REQ-14 AC14.1 / REQ-29 (T18, T46-T49): install the shadow-row sink.
        # The monitor and surface consumer modules emit their rows to a
        # module-level sink, and NOTHING installed one in production â€” every
        # row fell through to a log line, so no calibration row ever persisted
        # and TG-6's parity clause plus Wave 7's >=100-row flip bar were
        # structurally unreachable. The sink is the SAME single-writer ledger
        # the dispatched decisions use, so one reader sees every consumer.
        try:
            from backend.agent import explorer as _ex_rows
            from backend.agent import monitor_shadow as _ms_rows

            _shadow_sink = self._shadow_row_sink
            _ms_rows.set_row_sink(_shadow_sink)
            # web_intent (2026-09-27): this consumer had criteria and a live call
            # site but no row path at all, so it could never be scored however
            # often it ran. Same single-writer sink as the other two.
            _ex_rows.set_row_sink(_shadow_sink)
            # click_safety (W2): the browser click gate's Oracle shadow rows.
            from backend.agent import click_safety_shadow as _cs_rows

            _cs_rows.set_row_sink(_shadow_sink)
            # event taxonomy step 3: user_feedback / event_family / event_type:*.
            from backend.agent import event_oracle as _eo_rows

            _eo_rows.set_row_sink(_shadow_sink)
            # tool_approval (safety, 2026-11-10): rows from the user's answers
            # to permission prompts. Same single-writer sink.
            from backend.agent import tool_approval_shadow as _ta_rows

            _ta_rows.set_row_sink(_shadow_sink)
            # browser_next (2026-10-11): the element-choice consumer.
            from backend.agent import browser_next_shadow as _bn_rows

            _bn_rows.set_row_sink(_shadow_sink)
            # page_relevance / page_blocked (2026-11-10): the research-path
            # page questions (crawler shadow consults). Same sink.
            from backend.agent import page_shadow as _ps_rows

            _ps_rows.set_row_sink(_shadow_sink)
            # REQ-14 (Wave 5): resolved OUTCOME-labelled rows (the deferred
            # registry) land on the SAME single-writer sink.
            from backend.agent import decision_engine as _de_rows

            _de_rows.set_outcome_sink(_shadow_sink)
            logger.info(
                "[AgentKernel] shadow row sink installed "
                "(monitor + web_intent + the other consumers)"
            )
        except Exception as _sink_err:  # noqa: BLE001 â€” advisory
            logger.warning(
                f"[AgentKernel] shadow row sink install failed: {_sink_err}"
            )

        logger.info("[AgentKernel] Initialization complete")


    def set_main_loop(self, loop: Any) -> None:
        """Capture the running event loop so background threads can dispatch broadcasts."""
        self._broadcast_loop = loop

    def set_memory_interface(self, memory_interface: Any) -> None:
        """
        Set the memory interface for the agent kernel.

        This is called after AgentKernel initialization to wire in
        the Memory Foundation system.

        Args:
            memory_interface: MemoryInterface instance from backend.memory
        """
        self._memory_interface = memory_interface
        # Wire Reviewer's memory reference now that it's available
        if self._reviewer is not None:
            self._reviewer.memory = memory_interface
        logger.info("[AgentKernel] Memory interface connected")
        try:
            from backend.agent.mcm_protocol import MCMOrchestrator

            self._mcm_orch = MCMOrchestrator(
                memory_interface=memory_interface,
                session_id=self.session_id,
                thread_id=getattr(self, "_thread_id", None),
            )
            logger.info("[AgentKernel] MCMOrchestrator initialized")
        except Exception as _mcm_err:
            logger.warning(f"[AgentKernel] MCMOrchestrator unavailable: {_mcm_err}")
            self._mcm_orch = None




    def clear_conversation(self, conversation_id: Optional[str] = None) -> None:
        """
        Clear the agent context for a conversation â€” both the in-memory
        conversation history and the persistent store.  Called on 'new
        conversation' or thread switch cleanup so the next turn starts blank.

        Never raises â€” logs warning on failure.
        """
        _cid = conversation_id or getattr(self, "conversation_id", None)
        # Reset in-memory history immediately so a reused kernel instance
        # cannot leak the previous thread's messages into the new one.
        if self._conversation_memory is not None:
            try:
                self._conversation_memory.clear()
            except Exception as _mem_exc:
                logger.warning(
                    f"[AgentKernel] in-memory clear failed for {_cid}: {_mem_exc}"
                )
        try:
            from backend.agent.conversation_context_store import get_context_store

            store = get_context_store()
            store.clear(_cid)
            logger.info(
                f"[AgentKernel] Cleared context for conversation {_cid}"
            )
        except Exception as exc:
            logger.warning(
                f"[AgentKernel] clear_conversation({_cid}) failed: {exc}"
            )

    # â”€â”€ T17 (REQ-1 AC1.3): follow-up mutation wiring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # A voice/text interruption lands on the LIVE GoalAnatomy â€” never a side
    # plan. Each mutation is logged in memory_anchors so the audit trail
    # shows who changed what.


















    # â”€â”€ Context window resolution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Every model has a maximum context window.  Memory, conversation history,
    # and MCM budgets should be derived from it â€” never hardcoded.


    # Known context windows (tokens).  Keyed by (provider, model_substring).
    # Substring match is case-insensitive; first match wins.
    _KNOWN_CONTEXT_WINDOWS: list[tuple[str, str, int]] = [
        # Cohere
        ("cohere", "command-r-plus", 128_000),
        ("cohere", "command-r", 128_000),
        ("cohere", "command-a", 256_000),
        ("cohere", "command", 8_192),
        # OpenAI
        ("openai", "gpt-4o", 128_000),
        ("openai", "gpt-4o-mini", 128_000),
        ("openai", "gpt-4-turbo", 128_000),
        ("openai", "gpt-4", 8_192),
        ("openai", "gpt-3.5", 16_385),
        # Groq
        ("groq", "llama-3.3-70b", 128_000),
        ("groq", "llama-3.1-70b", 128_000),
        ("groq", "llama-3.1-8b", 128_000),
        ("groq", "llama3-70b", 8_192),
        ("groq", "llama3-8b", 8_192),
        ("groq", "mixtral-8x7b", 32_768),
        ("groq", "gemma2-9b", 8_192),
        # DeepSeek
        ("deepseek", "deepseek-chat", 65_536),
        ("deepseek", "deepseek-coder", 16_384),
        # Mistral
        ("mistral", "mistral-large", 128_000),
        ("mistral", "mistral-medium", 32_000),
        ("mistral", "mistral-small", 32_000),
        ("mistral", "mixtral", 32_000),
        # Cerebras â€” value confirmed by the user 2026-07-28.
        # NOTE: no provider-wide ("cerebras", "", N) fallback on purpose. An
        # unlisted model must fall through to the conservative 8k default rather
        # than inherit 256k: the budget is sized at window*0.9, so a default that
        # is too HIGH re-creates the overcommit this table's default exists to
        # prevent. Under-sizing is safe; over-sizing is the bug.
        ("cerebras", "gemma-4-31b", 256_000),
        # Qwen 3.8 27B replaces gemma as the Cerebras offering 2026-09-04.
        # Catalog context is 64k free / 128k paid.
        # CORRECTED 2026-09-05: this is 64_000, not the 128_000 paid tier.
        # Evidence, not an assumption â€” api.cerebras.ai answers every request
        # with 402 "Payment required to access this resource. Visit your
        # billing tab." (type=payment_required_error), i.e. no paid plan is
        # active, so only the 64k free-tier window is actually served.
        # Direction of error matters: the budget is sized at window*0.9, so
        # 128_000 provisions 115.2k against a 64k window and the overage is
        # silently truncated mid-conversation. Under-sizing is safe;
        # over-sizing is the bug (same rule as the gemma row above).
        # Revert to 128_000 only if Cerebras billing is actually enabled.
        # The gemma row above stays: still-true model fact, pinned by the
        # ctx-budget contract tests. ClinePass models stay unlisted on
        # purpose (windows unverified) and take the safe 8k default.
        ("cerebras", "qwen-3.8-27b", 64_000),
        # Inception mercury-2.5: 260_000 is the window Inception itself published in
        # its /models list (logged 2026-10-02 and 2026-10-25, "budget=26000 from
        # window=260000"). On 2026-10-26 /models listed only mercury-3 and
        # mercury-decide - mercury-2.5 still answers but is no longer listed - so
        # the API lookup (case 2b) found nothing, every thread fell to the 8_192
        # default and the chat's context pill went red after one prompt. Evidence,
        # not a guess; case 2b still wins whenever the provider lists the model.
        ("inceptionlabs", "mercury-2.5", 260_000),
        # mercury-3: Inception's /models published context_length 1000000 (2026-10-26).
        ("inceptionlabs", "mercury-3", 1_000_000),
        # OpenRouter: REMOVED 2026-07-29. ("openrouter", "", 32_000) was a
        # bare-substring provider-wide fallback â€” it matched EVERY model from
        # OpenRouter, which fronts models from 4k to 2M windows. A blanket
        # 32_000 meant an 8k-window model got a budget sized for 32k, so DER
        # kept issuing steps while every call silently truncated (REQ-2 AC6,
        # the exact case row 1 of the silent-failure table in specs/PHASES.md
        # describes). This was briefly grandfathered into an allow-list in
        # test_no_raised_provider_default; that was wrong and has been
        # reverted â€” the guard now admits no exceptions. An unlisted
        # openrouter model now falls through to the conservative 8_192
        # default (case 4 below), tagged source="default" per REQ-2 AC4:
        # under-provisioning is safe, over-provisioning truncates silently.
        # Escape hatch: a real window can still be supplied per-model via
        # _context_window_overrides (highest precedence, REQ-2 AC3).
        # Open question: the correct long-term fix is resolving OpenRouter's
        # window from its API metadata (authoritative, REQ-2 AC2) rather than
        # any table guess â€” see specs/phase-1-foundation/requirements.md OQ.
        # LM Studio / IRIS Local â€” common local models
        ("lmstudio", "lfm-2-8b", 32_768),
        ("lmstudio", "llama-3", 8_192),
        ("lmstudio", "llama-3.1", 128_000),
        ("lmstudio", "llama-3.2", 128_000),
        ("lmstudio", "mistral", 32_768),
        ("lmstudio", "qwen2.5", 32_768),
        ("lmstudio", "phi-3", 128_000),
        ("iris_local", "lfm-2-8b", 32_768),
        ("iris_local", "llama-3", 8_192),
        ("iris_local", "llama-3.1", 128_000),
        # Ollama â€” common local models
        ("local", "llama3.1", 128_000),
        ("local", "llama3", 8_192),
        ("local", "mistral", 32_768),
        ("local", "qwen2.5", 32_768),
        ("local", "phi3", 128_000),
        ("local", "gemma2", 8_192),
        # Ollama CLOUD models. Every value below was read from the running
        # Ollama server's own /api/show `context_length` on 2026-08-16 â€” not
        # from a model card, a blog post, or memory. The catalog above this
        # file was once ~80% fabricated, so anything unverifiable is simply
        # absent here rather than guessed.
        #
        # Why these were missing and what it cost: an OLLAMA-kind provider maps
        # to the provider string "local" (see _provider_string_for_instance),
        # and no "local" entry matched any cloud id â€” so gpt-oss:120b-cloud
        # resolved to the conservative 8192 default and DER got a 4000-token
        # budget against a real 131072 window. Observed live: a 3-step task
        # stopped after step 2 with "Token budget exhausted (6091/4000)" while
        # the model had ~32x the headroom it was being given.
        #
        # Deliberately NOT listed: kimi-k2.5:cloud and kimi-k2-thinking:cloud.
        # Ollama's own /api/show returns an error for both, so no authoritative
        # window exists to record. They fall through to the 8192 default, which
        # under-provisions rather than truncates â€” the safe direction, per the
        # cerebras note above.
        ("local", "gpt-oss", 131_072),
        ("local", "nemotron-3-nano", 262_144),
        ("local", "glm-5.1", 202_752),
        # ADDED 2026-09-27. Value read from the running Ollama server's own
        # /api/show on 2026-09-27: gemma4.context_length = 262144 -- same method
        # and same rule as the rows above (the server is the authority, not a
        # model card or memory).
        #
        # What it cost while missing: this is the model the reasoning role is
        # bound to, and no "local" row matched it, so both roles logged
        # "WARN source=default: no context window known for provider=local
        # model=gemma4:31b-cloud -- falling back to 8192" and a 262144-token
        # window was budgeted as 8192, a 32x under-provision. Under-sizing does
        # not truncate, but it ends a long task early with "Token budget
        # exhausted" -- the same failure the gpt-oss note above describes at the
        # same ratio, which is the evidence that this row is worth having.
        #
        # Row order: "gemma2" (above) and "gemma4" do not collide -- first match
        # wins on a substring test, and neither string contains the other.
        ("local", "gemma4", 262_144),
        # OpenCode Zen (opencodego). The live /models endpoint 403s, so the
        # window was MEASURED instead of guessed: deepseek-v4.1-flash accepted
        # a 720k-token prompt (2026-11-03) and OpenRouter lists 1048576 for
        # the same model id. 128k is the value recorded here on purpose: the
        # rule of this table is "under-sizing is safe, over-sizing is the
        # bug" (the budget is window*0.75, so a too-high window over-commits
        # the prompt). 128k is 15x the 8192 default that every opencodego
        # model fell through to before this row, and it ends the message
        # dropping that the 8192 budget caused ("prompt over the window:
        # window=8192 budget=3840 dropped_messages=6").
        ("opencodego", "", 128_000),
    ]

    # Known vision-capable API models. Keyed (provider_id, model_substring),
    # mirroring _KNOWN_CONTEXT_WINDOWS's shape and matching rule directly
    # above: substring match is case-insensitive, first match wins. Sibling
    # table for specs/unified-vision-routing REQ-1 AC2 â€” this is DATA only,
    # not a raise site. A model id that matches no row here is simply absent
    # from the table; the "unknown -> False" behaviour of REQ-1 AC5 is owned
    # by supports_vision() (backend/agent/inference/router.py), which must
    # treat "no row matched" as False rather than erroring.
    #
    # provider_id follows the same vocabulary as _KNOWN_CONTEXT_WINDOWS: the
    # literal instance id registered for an API ProviderInstance (e.g.
    # "openai", "anthropic" â€” see PROVIDER_PRESETS in
    # backend/agent/inference/provider.py), not the ProviderKind enum value.
    _KNOWN_VISION_MODELS: list[tuple[str, str]] = [
        # OpenAI â€” the GPT-4o family and later multimodal generations accept
        # image input natively.
        ("openai", "gpt-4o"),
        ("openai", "gpt-4-turbo"),
        ("openai", "gpt-4.5"),
        # Anthropic â€” every Claude 3 and later model accepts image input.
        ("anthropic", "claude-3"),
        ("anthropic", "claude-opus"),
        ("anthropic", "claude-sonnet"),
        ("anthropic", "claude-haiku"),
        # Gemini â€” multimodal since 1.5. No "gemini" id exists in
        # PROVIDER_PRESETS today (no dedicated Google preset is registered
        # yet); this row is forward-compatible with a directly-configured
        # Gemini-compatible API provider registered under instance id
        # "gemini", and the substring also matches vendor-prefixed ids such
        # as an aggregator's "google/gemini-2.0-flash-001" once such a
        # provider exists. Deliberately NOT guessing at a provider id that
        # is not yet a real preset beyond this one forward-compatible row.
        ("gemini", "gemini"),
    ]

    # â”€â”€ Active-model state: DERIVED from the router, never stored â”€â”€â”€â”€â”€â”€â”€â”€â”€
    #
    # These three read like plain attributes because ~120 call sites across the
    # backend read them that way, and that is fine â€” reading is safe. What is
    # not safe is STORING them, which is what they used to do.
    #
    # The role-binding table and the provider registry are process-wide
    # singletons (REQ-5): one table, shared by every kernel's router. The user's
    # live choice lives there and nowhere else. Every recurring "I picked cohere
    # and it went back to cerebras" report traced to some path re-applying a
    # stored copy of that choice â€” startup config replay, peer inheritance, a
    # module-global snapshot, persisted session field_values. Each was fixed
    # individually and the bug came back through the next copy.
    #
    # Deriving them removes the category. There is no copy to go stale, no sync
    # to forget, and a new conversation kernel â€” or a subagent, or a swarm
    # worker â€” sees the live binding at construction because it shares the
    # table rather than inheriting a snapshot of it.
    #
    # To CHANGE the active model, bind the role: `kernel.set_role_binding(...)`.















    # Providers that speak the OpenAI-compatible chat completions API.
    # When the user picks any of these, inference routes through _get_lmstudio_client()
    # using whatever endpoint they configured (LM Studio, llamafile, vllm, etc.).
    _OPENAI_COMPAT_PROVIDERS = frozenset(
        {
            "lmstudio",
            "openai_compatible",
            "llamafile",
            "vllm",
            "llamacpp_server",
            "koboldcpp",
            "textgen_webui",
            "ollama_openai",
            # IRIS-native local model server (llama-cpp-python / ik_llama.cpp on port 8082)
            "iris_local",
        }
    )










    def _get_developer_context(self) -> str:
        """Load and cache the PROJECT.md developer context string.

        Returns empty string if the file cannot be found (non-fatal).
        """
        if self._developer_context is not None:
            return self._developer_context
        import pathlib

        # Walk up from this file's location to find PROJECT.md
        here = pathlib.Path(__file__).parent
        for _ in range(6):
            candidate = here / "PROJECT.md"
            if candidate.exists():
                self._developer_context = candidate.read_text(encoding="utf-8")
                logger.info(f"[AgentKernel] Loaded developer context from {candidate}")
                return self._developer_context
            here = here.parent
        logger.warning(
            "[AgentKernel] PROJECT.md not found â€” developer context unavailable"
        )
        self._developer_context = ""
        return ""

    def _bound_external_project(self) -> str:
        """The turn's bound workdir when it is outside the IRIS repo, else ""."""
        try:
            _sess = getattr(self, "_turn_session_id", None) or self.session_id
            _wd = (getattr(self._tool_bridge, "_session_workdirs", None) or {}).get(_sess) or ""
            if not _wd:
                return ""
            _repo = os.path.normcase(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            _norm = os.path.normcase(os.path.abspath(_wd))
            return "" if _norm == _repo or _norm.startswith(_repo + os.sep) else _wd
        except Exception:
            return ""


    # ------------------------------------------------------------------
    # Domain 4.5 â€” Proactive skill creation
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Helpers: thinking-token stripping, planning gate, direct response
    # ------------------------------------------------------------------

    # Endpoints observed to reject the thinking hint. Populated at runtime so a
    # strict provider is asked exactly once and never again this process.
    _THINKING_HINT_REFUSED: set = set()






    # Action/tool intent markers â€” prompts containing these need the DER
    # planning/tool loop. Everything else (simple questions, factual lookups,
    # conversation) takes the fast direct-response path (1 Cerebras call, no
    # "Working on it" filler, no rate-limit burst).
    _ACTION_VERBS = (
        "search", "google", "lookup", "find", "open", "launch", "start",
        "create", "make", "build", "generate", "write", "send", "email",
        "message", "text", "call", "schedule", "remind", "set", "add",
        "delete", "remove", "update", "edit", "change", "list", "play", "show me",
        "book", "order", "buy", "download", "upload", "post", "tweet",
        "run", "execute", "deploy", "install", "configure", "toggle",
        "turn on", "turn off", "switch", "navigate", "go to", "browse",
        "scrape", "fetch", "pull", "sync", "backup", "translate", "summarize",
        "analyze", "compare", "calculate", "convert",
    )

    # Follow-up / anaphora markers â€” these signal the user is continuing a
    # PRIOR task ("now do it for the sales team", "yes, schedule that",
    # "what about the other one"). They carry no action verb of their own but
    # are clearly NOT standalone questions, so they must route to DER (the safe
    # fallback) rather than the dumb direct path. This is the "inertia" the
    # field's routing systems use to avoid misrouting mid-conversation.
    _FOLLOWUP_MARKERS = (
        "now", "then", "also", "too", "as well", "instead", "again",
        "what about", "how about", "and the", "for the", "with the",
        "yes", "yeah", "yep", "sure", "ok", "okay", "do it", "go ahead",
        "proceed", "confirm", "that one", "the other one", "the same",
    )
    _ANAPHORA_PRONOUNS = ("it", "that", "this", "them", "they", "those", "these", "him", "her")









    # â”€â”€ Token estimation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Rough but fast: 1 token â‰ˆ 4 chars. Real tokenizer adds <5% accuracy gain
    # but costs 10-50ms per call â€” not worth it for windowing decisions.
    _CHARS_PER_TOKEN: int = 4

    # Context budget for direct responses. Keeps the most recent history
    # within the model's 32k window, leaving ~8k for system prompt + response.
    # With episodic injection headroom this sits at ~20k chat tokens max.
    _DIRECT_CTX_BUDGET: int = (
        24_000  # tokens (supports 12k context + system + response)
    )







    # ------------------------------------------------------------------ #
    # Dispatch methods
    # ------------------------------------------------------------------ #




    # Word count above which we consider a reply "long" for TTS purposes.
    # Only applied to DOCUMENT-like content; conversational replies are always spoken in full.
    _SPOKEN_WORD_LIMIT: int = 40
    # Maximum spoken word count for document summaries (hard cap).
    _SPOKEN_MAX_WORDS: int = 80


    # â”€â”€ Tool definitions for OpenAI-compatible function calling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€



    # â”€â”€ ReAct agentic loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    # REQ-28: threshold above which the first-sentence rule below stops being
    # an acceptable spoken form. Same number prepare_spoken_text already uses
    # for its ">120 words" branch, named once so the two cannot drift.
    SPOKEN_BRIEF_WORD_THRESHOLD = 120




    # ------------------------------------------------------------------
    # Issue C.1 â€” structured speak/show response contract
    # ------------------------------------------------------------------












    # â”€â”€ W9 (O3): proactive structured-data capture from ANY tool result â”€â”€â”€â”€â”€â”€
    # Plan W9: extend capture beyond `show` payloads to any tool result
    # (web_search, crawler_query, read_file, ...) so everything the agent
    # touches becomes reformat-able via the same DocumentDataStore. Scoped by a
    # relevance/structure threshold so trivial results are not embedded.

    _MIN_CAPTURE_CHARS = 50       # below this, a result is "trivial"
    _RELEVANCE_THRESHOLD = 0.30   # results carrying a score below this are skipped





    # â”€â”€ W10 (O4): pheromone-reinforced reformat + cross-modal synergy â”€â”€â”€â”€â”€â”€â”€â”€
    # Plan W10: reinforce the reformat action's pheromone edge when used, so
    # frequently-reformatted doc types become "sticky" (the agent can proactively
    # offer a reformat), and expose cross-modal views (vocalize / diagram) that
    # reuse existing channels (SpeakTool, reformat_document's diagram format).

























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

    # â”€â”€ Phase 1.4: failure handling + plan grafting â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€









    # â”€â”€ REQ-15 (T25): mid-task steering channel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


    def _der_build_step_envelope(
        self,
        item: "QueueItem",
        step_result: str,
        step_success: bool,
        outcome: str,
        completed_items: list,
        _session: str,
        _turn_id: Optional[str],
        coords_from: Optional[str],
        coords_to: Optional[str],
    ) -> None:
        """specs/tool-result-envelope T6 (REQ-1 AC1.2): build the envelope
        ONCE at the finalize site, alongside the node-record stamping
        (outcome/expected_output/fraction/coords all in scope). raw_ref =
        doc-store id ONLY (AC1.3 â€” Pacman chunk ids are async and never
        waited on); criticality confirmed from consumption (AC1.6); coords
        pass through VERBATIM (AC1.5); per-envelope debug log (AC7.1).
        Never raises into the caller: any failure degrades to the minimal
        envelope (AC1.4)."""
        _coords_from = coords_from
        _coords_to = coords_to
        try:
            from backend.agent.tool_envelope import (
                build_envelope, minimal_envelope, params_digest,
                classify_exception_from_message, extract_sources,
                body_hashes_of,
            )
            from backend.agent.tool_errors import resolve_label

            _raw_doc_id = getattr(item, "captured_doc_id", None) or ""
            _env_frac = getattr(
                getattr(item, "node_record", None), "verified_fraction", None
            )
            _prev_frac = None
            if completed_items:
                _prev_rec = getattr(
                    completed_items[-1], "node_record", None
                )
                if _prev_rec is not None:
                    _prev_frac = getattr(
                        _prev_rec, "verified_fraction", None
                    )
            # Turn memory (AC3.1): envelopes + tool/params digests of
            # PRIOR completed steps this run â€” derived from in-scope
            # state, no new store.
            _seen_params: Dict[str, str] = {}
            _step_summaries: List[str] = []
            for _pit in completed_items:
                _pd = _step_digest(_pit)
                if _pd:
                    _seen_params.setdefault(_pd, getattr(_pit, "step_id", ""))
                _pe = getattr(_pit, "envelope", None)
                if _pe is not None:
                    _step_summaries.append(_pe.summary)
            # Session-323: exclude THIS step's own URLs from the novelty
            # comparison. _remember_turn_urls ran earlier in finalize (and at
            # dispatch for seeds), so _der_crawled_urls already holds the
            # current step's addresses â€” comparing the result against a set
            # containing itself makes every first gather read as
            # "repeat_of_gather" (live b323_web1 s1: fresh crawl, zero priors,
            # envelope still stamped repeat/circling). Novelty is vs PRIOR
            # steps only; the step's own URLs rejoin the refusal set after.
            _own_urls323: set = set()
            try:
                import re as _re_own323
                from backend.agent.tool_envelope import normalize_url as _norm_own323
                for _m323 in _re_own323.findall(r"https?://[^\s\"')\]]+", str(step_result or "")):
                    try:
                        _n323 = _norm_own323(str(_m323).rstrip(".,;)]"))
                    except Exception:
                        _n323 = ""
                    if _n323:
                        _own_urls323.add(_n323)
            except Exception:
                _own_urls323 = set()
            _turn_memory = {
                "crawled_urls": set(
                    getattr(self, "_der_crawled_urls", {}).get(
                        self.conversation_id or "", set()
                    )
                ) - _own_urls323,
                "tool_params": _seen_params,
                "step_summaries": _step_summaries,
                "last_gather_step_id": (
                    completed_items[-1].step_id if completed_items else ""
                ),
            }
            # Session-318 T17 (REQ-10 AC10.1): exact body-identity vs turn.
            # Prior hashes ride turn_memory; current hashes join the map
            # after the build (same order as seen-dispatches). A hit is
            # logged here (T19 counts it) and derive_novelty independently
            # reaches the same repeat_of verdict from the same map.
            _turn_memory["body_hashes"] = dict(
                getattr(self, "_der_body_hashes", {}).get(
                    self.conversation_id or "", {}
                )
            )
            _cur_hashes = body_hashes_of(str(step_result or ""))
            _hash_hit = next(
                (_h for _h in _cur_hashes
                 if _h in _turn_memory["body_hashes"]),
                "",
            )
            if _hash_hit:
                logger.info(
                    "[envelope] content-hash hit: step %s repeats %s "
                    "(identical body)",
                    item.step_id,
                    _turn_memory["body_hashes"][_hash_hit],
                )
                try:
                    from backend.agent.write_counters import bump as _bump_hash
                    _bump_hash("envelope.hash_hits")
                except Exception:
                    pass
            # Structured error shape (CT-4 lock): error_type from the
            # tool_errors taxonomy when the step failed.
            _env_error = None
            if not step_success:
                _etype = classify_exception_from_message(
                    str(step_result or "")
                )
                _label = resolve_label(_etype)
                _env_error = {
                    "error_type": _etype,
                    "recovery_hint": (
                        _label.description[:120] if _label else ""
                    ),
                }
            # AC3.4: the Caducean recommendation is read at the SAME
            # finalize point so a TOPO_VIOLATION (rec==3) forces
            # suggestion=stop on the envelope (physics first, KD-4).
            _topo_rec = 2
            try:
                from backend.gateway.iris_ffi import ffi_caducean_recommend

                _topo_rec = ffi_caducean_recommend(_session)
            except Exception:
                _topo_rec = 2
            # REQ-8 AC8.1: the step->URL map for VISITED join keys. The
            # envelope stamps its own (capped, marked) copy inside
            # build_envelope; refusal/exclusion logic always uses the FULL
            # in-memory crawled set â€” caps bound views, never decisions.
            _sources: List[str] = []
            try:
                _sources, _ = extract_sources(str(step_result or ""))
            except Exception:
                _sources = []
            # Session-318 T18 (REQ-11 AC11.2/AC12.2): elapsed vs deadline.
            # Slow completion logs a stall warning (advisory only â€” the
            # deadline alone aborts). In-flight visibility rides the tools'
            # own progress emissions (e.g. crawl phases); this closes the
            # accounting side so every slow step is undeniable in logs.
            _elapsed = 0.0
            try:
                _t0 = float(getattr(item, "dispatch_started_at", 0.0) or 0.0)
                if _t0 > 0:
                    import time as _time_elapsed
                    _elapsed = max(0.0, _time_elapsed.monotonic() - _t0)
                from backend.agent.der_constants import STALL_WARN_S
                if _elapsed > max(float(STALL_WARN_S), 1.0):
                    logger.warning(
                        "[DER] step %s slow: %.1fs elapsed (stall threshold "
                        "%.0fs) â€” advisory; deadline aborts, not this line",
                        getattr(item, "step_id", "?"), _elapsed,
                        float(STALL_WARN_S),
                    )
                    try:
                        from backend.agent.write_counters import bump as _bump_stall
                        _bump_stall("envelope.stalls")
                    except Exception:
                        pass
            except Exception:
                _elapsed = 0.0
            item.envelope = build_envelope(
                result_text=str(step_result or ""),
                step_success=step_success,
                outcome=outcome,
                expected_output=str(
                    getattr(item, "expected_output", None)
                    or item.description
                    or ""
                ),
                tool=getattr(item, "tool", None),
                params_digest=_step_digest(item),
                verified_fraction=_env_frac,
                prev_verified_fraction=_prev_frac,
                raw_doc_id=_raw_doc_id,
                coords_from=_coords_from,
                coords_to=_coords_to,
                turn_memory=_turn_memory,
                error=_env_error,
                recovery_of=getattr(item, "recovery_of", "") or "",
                elapsed_s=_elapsed,
                timeout=bool(getattr(item, "timed_out", False)),
                declared_criticality=getattr(
                    item, "declared_criticality", "supporting"
                )
                or "supporting",
                capture_skipped=bool(getattr(item, "tool", None))
                and not _raw_doc_id,
                topo_violation=(_topo_rec == 3),
                card_id=self._card_envelope(
                    _turn_id or item.step_id
                ).get("card_id", ""),
                step_id=item.step_id,
                session_id=_session or "",
                turn_id=_turn_id or "",
            )
            # AC7.1: scoped per-envelope log line â€” enough to
            # reconstruct a run's stuck trajectory from logs alone.
            logger.debug(
                "[envelope] conv=%s step=%s status=%s match=%s "
                "novelty=%s suggestion=%s shape=%s crit=%s/%s "
                "summary_len=%d",
                self.conversation_id or "?",
                item.step_id,
                item.envelope.status,
                item.envelope.match,
                item.envelope.novelty,
                item.envelope.suggestion,
                item.envelope.stuck_shape,
                item.envelope.criticality,
                item.envelope.criticality_source,
                len(item.envelope.summary),
            )
            if getattr(item.envelope, "criticality_source", "") == "confirmed":
                logger.info(
                    "[envelope] criticality divergence: step %s declared "
                    "%s but consumption confirmed load-bearing (tuning "
                    "signal)",
                    item.step_id,
                    getattr(item, "declared_criticality", "supporting"),
                )
            # AC7.2 counters â€” bounded, per-kernel, advisory.
            try:
                _counters = getattr(self, "_envelope_counters", None)
                if _counters is None:
                    _counters = {
                        "written": 0, "raw_ref_fetches": 0,
                        "crit_confirmed": 0, "gate_fired": 0,
                        "gate_blocked": 0, "hard_blocks": 0,
                        "suggest_overrides": 0,
                    }
                    self._envelope_counters = _counters
                _counters["written"] += 1
                if item.envelope.criticality_source == "confirmed":
                    _counters["crit_confirmed"] += 1
            except Exception:
                pass
            # Session-318 T19 (REQ-12): recovery outcome on the envelope
            # that just settled (recovered = brought usable sources home).
            try:
                if getattr(item, "recovery_of", ""):
                    from backend.agent.write_counters import bump as _bump_rec
                    if list(getattr(item.envelope, "sources", []) or []):
                        _bump_rec("envelope.recovery_recovered")
                    else:
                        _bump_rec("envelope.recovery_empty")
            except Exception:
                pass
            # Join registry for the retroactive criticality confirm and
            # pre-dispatch reroute reads (KD-10: reporter stamps, graph
            # layers read). FIFO-capped â€” memory bounded.
            try:
                _reg = dict(
                    getattr(self, "_der_envelope_registry", {})
                )
                _conv = self.conversation_id or ""
                _bucket = dict(_reg.get(_conv, {}))
                _bucket[item.envelope.raw_ref.get("doc_id") or f"noref:{item.step_id}"] = item.envelope
                while len(_bucket) > 200:
                    _bucket.pop(next(iter(_bucket)))
                _reg[_conv] = _bucket
                self._der_envelope_registry = _reg
                # Turn dispatch memory for the T6B repeat guard: digest
                # -> first step that ran it. FIFO-capped likewise.
                _sd = dict(getattr(self, "_der_seen_dispatches", {}))
                _sdb = dict(_sd.get(_conv, {}))
                _pd_self = _step_digest(item)
                _sdb.setdefault(_pd_self, item.step_id)
                while len(_sdb) > 200:
                    _sdb.pop(next(iter(_sdb)))
                _sd[_conv] = _sdb
                self._der_seen_dispatches = _sd
                # Session-318 T17 (REQ-10 AC10.1): turn body-hash map for
                # exact-identity detection (hash -> first step). FIFO-capped.
                try:
                    _bh = dict(getattr(self, "_der_body_hashes", {}))
                    _bhb = dict(_bh.get(_conv, {}))
                    for _h in _cur_hashes:
                        _bhb.setdefault(_h, item.step_id)
                    while len(_bhb) > 500:
                        _bhb.pop(next(iter(_bhb)))
                    _bh[_conv] = _bhb
                    self._der_body_hashes = _bh
                except Exception:
                    pass
                # REQ-8 AC8.2 join keys: url -> step that fetched it.
                # Additive only â€” `_der_crawled_urls` stays the refusal
                # authority and is never reshaped here. FIFO-capped.
                try:
                    _csm = dict(getattr(self, "_der_crawled_steps", {}))
                    _csb = dict(_csm.get(_conv, {}))
                    for _u in _sources:
                        _csb.setdefault(_u, item.step_id)
                    while len(_csb) > 500:
                        _csb.pop(next(iter(_csb)))
                    _csm[_conv] = _csb
                    self._der_crawled_steps = _csm
                except Exception:
                    pass
            except Exception:
                pass
        except Exception as _env_exc:
            # AC1.4: degrade to the minimal envelope â€” never break the
            # DER loop for shaping.
            logger.warning(
                "[envelope] build failed for step %s: %s",
                getattr(item, "step_id", "?"), _env_exc,
            )
            try:
                item.envelope = minimal_envelope(
                    outcome=outcome,
                    content_summary=str(
                        getattr(
                            getattr(item, "node_record", None),
                            "content_summary",
                            "",
                        )
                        or step_result
                        or ""
                    ),
                    raw_doc_id=getattr(item, "captured_doc_id", None) or "",
                    coords_from=_coords_from if "_coords_from" in dir() else None,
                    coords_to=_coords_to if "_coords_to" in dir() else None,
                    step_id=getattr(item, "step_id", ""),
                    session_id=_session or "",
                    turn_id=_turn_id or "",
                )
            except Exception:
                pass





    # â”€â”€ REQ-5 (specs/dag-node-execution-model): bounded mid-execution
    # amendment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # The executing graph may be EXTENDED between steps based on outcomes
    # already observed (AC1). Planner-driven ONLY (design D6) â€” a node
    # proposing its own successor would reintroduce hidden control flow.
    # Amendments append fresh steps; they never re-execute satisfied nodes
    # (AC2) and the existing step budget / token accounting stays
    # authoritative (AC4). Bounded per task (AC3) and every amendment /
    # refused amendment is recorded (REQ-9 AC3).
    _AMENDMENT_BOUND = int(os.environ.get("IRIS_NODE_AMENDMENT_BOUND", "3"))









    # â”€â”€ Phase 2: Emergent Shape â€” growth-width split/execute operator â”€â”€â”€â”€â”€â”€
    # This is the ONE recursive operator that decides execution-tree *shape*
    # from the live Caducean state (u,xi). It replaces the former mode-driven
    # fan-out AND the separate recovery-graft path: both physics-triggered
    # ("unresolved_u") and verification-failed ("verify_failed") splits use it.
    # MorphoHDL break: the decision is STATEFUL â€” width depends on live |u|,
    # never a fixed stateless predicate.



    # â”€â”€ REQ-5 (T17): coupling as decision-provenance â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Retrieval RANKS relevant branches (physics- and evidence-driven, AC3) and
    # SURFACES ALL of them (bounded by the candidate cap) to the deciding step
    # (AC1) â€” never silently pre-selecting one by score. When the step commits,
    # the edge to the branch that informed it is written/strengthened with the
    # decision as provenance (AC2), and the per-decision record (how many
    # candidates surfaced, which was chosen) is stored on the node record (AC4).











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

    # Session 245 (synthesis starvation fix, conv-36 live finding): gather
    # tools whose ENTIRE purpose is delivering content (crawl / search /
    # read) need far larger evidence windows than generic tools. A 3-page
    # crawl compressed to 300-400 chars starves every downstream consumer â€”
    # the tool-decision model then honestly reports "unable to access the
    # search results" because no fragment it sees can answer the goal.
    _DER_GATHER_TOOLS = {
        "crawler_query", "web_search", "search", "fetch_url",
        "read_file", "browser_read",
    }

    # REQ-18 added grep_files / glob_files as the codebase-search surface, but
    # they were never given an evidence window to match. They are not in
    # _DER_GATHER_TOOLS, so their results fell to the 400-char NON-gather cap
    # -- and a search tool exists precisely to return a LIST. Measured live
    # 2026-08-26 (conv-63): "how many backend files mention Porcupine" returned
    # 18 matches; at ~21 chars per entry that is ~420 chars of paths before the
    # JSON envelope, so the agent could not physically see them all and
    # answered "at least six". Truthful, correctly hedged, and wrong.
    #
    # Deliberately a SEPARATE set rather than adding them to _DER_GATHER_TOOLS:
    # that set also drives the sufficiency gate (:9391) and the graft decision
    # (:10623). This changes the evidence WINDOW only, which is the defect.
    _DER_SEARCH_TOOLS = {"grep_files", "glob_files"}

    # Session-323: stored-read tools deliver the SAME gathered bytes through
    # the document store instead of a fresh fetch. A rerouted read that keeps
    # the 400-char generic cap starves every downstream consumer â€” live
    # B3-repeat: guard rerouted to get_rendered_documents, step result held
    # only "1 document(s) retrieved", synthesis honestly reported IDs-only.
    # Kept as a SEPARATE set (same reason as _DER_SEARCH_TOOLS): this set
    # widens the evidence WINDOW only and must not alter the sufficiency
    # gate or graft decision that key off _DER_GATHER_TOOLS.
    _DER_READ_TOOLS = {
        "get_rendered_documents", "get_document", "read_document",
        "get_rendered_document", "recall_research",
    }

    # Tools whose result is a command's output: exit code + stdout/stderr.
    _SHELL_RESULT_TOOLS = {"run_command", "read_shell_output", "read_command_output", "stop_command"}



    @staticmethod
    def _smart_excerpt(text: str, cap: int) -> str:
        """Head+tail excerpt with an explicit truncation marker â€” never a
        silent amputation, never an unbounded dump."""
        t = (text or "").strip()
        if len(t) <= cap:
            return t
        _head = t[: int(cap * 0.7)]
        _tail = t[-int(cap * 0.3):]
        return f"{_head}\n[...excerpt: {len(t) - cap} chars truncated...]\n{_tail}"




    # â”€â”€ Partial-artifact completion (live 2026-09-25) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # One step is ONE tool call (ToolDecisionBox.resolve is single-shot), so a
    # step that names several files can only ever write one of them. Measured:
    # "create three files ... each with one bullet" wrote ONE file, the other two
    # were silently missing, and the user was told the files had been created.
    # The folder stays on the name: "tests/test_geometry.py" read as "test_geometry.py",
    # was "missing" in the project root, and the graft overwrote the real test file
    # (live c11 2026-10-27: "Create the file test_geometry.py ..." -> hidden test failed).
    _ARTIFACT_NAME_RE = re.compile(
        r"\b[\w][\w.\-/\\]*\.(?:md|markdown|txt|json|csv|tsv|ya?ml|py|js|ts|tsx|html|log|rst|tex)\b",
        re.IGNORECASE,
    )





    _SOURCE_HEADER_RE = re.compile(r"---\s*Source:\s*(\S+)\s*---")





    # â”€â”€ Phase 2.2: context-aware query refinement â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€








    def _log_route_shadow(
        self,
        *,
        turn_id: Optional[str],
        text: Optional[str],
        planned: bool,
        web_mode: bool,
        oracle_acted: bool = False,
    ) -> None:
        """Route shadow (REQ-18 AC1, task T30) â€” one JSONL row per turn.

        This is the EVIDENCE for the unified-routing flip (T33): every turn
        records which branch ran and whether the gate judged it trivial, so
        direct-vs-DER parity is measured before the direct branch is deleted.
        The classification itself is the semantic gate's answer already
        computed at the fork â€” zero extra work on the reply path. A write
        failure here must never cost a reply.
        """
        try:
            import json as _json
            import time as _time
            from pathlib import Path as _Path

            row = {
                "ts": _time.time(),
                "turn_id": turn_id or "unknown",
                "route_taken": "der" if planned else "direct",
                "would_be_trivial": not planned,
                "chars": len(text or ""),
                "web_mode": bool(web_mode),
            }
            path = (
                _Path(__file__).resolve().parents[2]
                / "data" / "route_shadow.jsonl"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(row, ensure_ascii=False) + "\n")

            # ORACLE ROUTE SHADOW (2026-10-30, reworked 2026-10-30): the
            # Oracle's pick on the ONE fork the kernel actually takes -
            # `"der" if planned else "direct"`. It NEVER acts.
            #
            # BINARY ON PURPOSE. The first cut asked a four-way question
            # (direct/der/memory_recall/memory_write) while the kernel has no
            # memory branches: memory_write and memory_recall both land on the
            # direct path. Two options that produce the same behaviour cannot
            # be calibrated - the report's precision pools them, so the engine
            # could look right on an option that changes nothing.
            #
            # `eng.shadow()` is the standard path: the row goes to
            # `_shadow_row_sink` -> the one ledger, so
            # scripts/consumer_enforcement_report.py can score it. The first
            # cut used `decide()` + a private jsonl and wrote ZERO ledger rows
            # (measured 2026-10-30: 0 route_v2 rows among 115,517 decision
            # rows). A private file is not evidence.
            #
            # The reference is what the rules did, in the same vocabulary, so
            # the row carries a parity label. It is NOT truth: the rules call
            # every memory ask "direct" because the direct path is where those
            # answers are assembled. A flip needs an OUTCOME label (did the
            # turn run a tool?), not this parity number.
            try:
                from backend.agent.decision_engine import get_decision_engine

                _eng = get_decision_engine()
                # A turn the Oracle's route drove has its own sampled row.
                if _eng is not None and not oracle_acted:
                    _incumbent = "der" if planned else "direct"
                    _frame = self._route_v2_frame(text, web_mode)
                    # input_key: the report's honest dedupe key. Without it the
                    # same goal rescored counts as NEW evidence (confidence
                    # jitters on every rescore), so "distinct rows" overstates
                    # the sample. Measured 2026-10-30: 157 route_v2 rows, 0 with
                    # an input_key, 60 distinct (chosen, confidence) pairs.
                    _key = None
                    try:
                        from backend.agent.surface_shadow import (
                            input_key as _input_key,
                        )

                        _key = _input_key("route_v2", (text or "")[:200], _frame)
                    except Exception:  # noqa: BLE001 - a missing key is not fatal
                        _key = None
                    _eng.shadow(
                        "route_v2",
                        ["direct", "der"],
                        _frame,
                        sink=self._shadow_row_sink,
                        reference={"brain_choice": _incumbent,
                                   "criteria_version": "route_v2/binary-v1",
                                   **({"input_key": _key} if _key else {})},
                    )
            except Exception as _route_err:  # noqa: BLE001 - a shadow never blocks
                logger.debug(
                    "[AgentKernel] route_v2 shadow failed: %r", _route_err
                )
        except Exception:  # noqa: BLE001 — shadow logging never blocks a reply
            pass






    # â”€â”€ ToolDecisionBox lazy factory â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # pin_517dfcbda150 â€” physics-driven web-gather sanction:
    #   _MAX_CRAWLS_PER_TASK  hard budget of DISTINCT queries per task; the
    #                         agent may gather more only by refining the query
    #                         (new hash = new job). Same-query repeats resolve
    #                         to the JobRegistry cache (tool_bridge dedupe).
    #   _GATHER_MIN_AMP       phase-manager amplitude floor: when oscillators
    #                         have collapsed (provider under load, amp relaxes
    #                         toward 1 - load_fraction) new crawls are denied
    #                         and web intent resolves to synthesis (REASON).
    _MAX_CRAWLS_PER_TASK = 3
    _GATHER_MIN_AMP = 0.35



    # â”€â”€ Phase 4: concurrent step execution helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€







    # â”€â”€ DER Phase 0: verification (stub-kill + coarsened outcome) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # SemanticVerifier instance â€” lazy-init so import at module level is safe.
    _VERIFIER: Optional["SemanticVerifier"] = None
    _STUB_RE = re.compile(r"\[step\s+\d+\s+completed\]", re.IGNORECASE)
    # pin_517dfcbda150: web/crawl steps verify by CONTENT SUFFICIENCY â€” the
    # tool itself already proved it fetched real content (zero pages returns
    # an error at the tool boundary in tool_bridge). Assertion matching against
    # crawl output is meaningless under the hash/substring fallback while the
    # Encoder-350M is absent, and false FAILED verdicts drove the step-1
    # re-crawl loop (verify_failed -> split -> children re-crawl same query).
    _WEB_CONTENT_TOOLS = frozenset(
        {"crawler_query", "web_search", "search", "google_search", "exa_search"}
    )
    # Tools the conversation-wide REPEAT rule applies to: web fetches, whose
    # repeat returns the same page. Local tools are re-runnable (audit B3).
    # The live browser tools are NOT here (nor in _WEB_CONTENT_TOOLS): a
    # repeated click or open is a new action on a changed page, and a crawl
    # budget would cut a multi-step browser task short (S39 exempts them from
    # the dispatcher's loop guard for the same reason).
    _REPEAT_GUARDED_TOOLS = _WEB_CONTENT_TOOLS | {"fetch_url", "open_url"}
    # pin_42ddd255162d: display/render tools complete by SUCCESS, not by content
    # volume â€” a rendered-card confirmation is a legit completion, never a
    # candidate for a verify-failure split (which is what made the task card
    # say "rendering documents" while the backend re-searched).
    _TRUSTED_RESULT_TOOLS = frozenset({"get_rendered_documents"})










    # â”€â”€ Phase 4: shared per-step finalize (extracted from _execute_plan_der)


    # â”€â”€ Physics side lane (execution audit, 2026-09-29) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # A step's Caducean update (EML observation -> integrator update -> coupling
    # -> trajectory row -> homeostasis -> controller refit -> Immortus chain ->
    # physics-event narration) is bookkeeping for the NEXT step's shape, not
    # part of this step's answer. It used to run inline in _der_finalize_step:
    # coding eval c10 spent 16-20 s of a 63 s turn inside ffi_calculate_eml on
    # the DER thread while the reply waited (logs/stackdump.log, 21:06:31-47).
    #
    # Now it runs on the ordered durability lane (one consumer, FIFO â€” the
    # physics is a sequential integrator and the chain is order-sensitive, so
    # order is preserved by construction). The CADUCEAN fold-back rule decides
    # who waits: only a DECISION about the next step's shape reads the pending
    # update (_der_physics_settle). Everything else â€” synthesis, scoring,
    # modulation â€” reads the last settled position and never waits.



    def _der_finalize_step(
        self,
        item: "QueueItem",
        step_result: str,
        step_success: bool,
        step_outputs: list,
        completed_items: list,
        _tokens_used: int,
        _token_budget: int,
        _session: str,
        _turn_id: Optional[str],
        _phase: int,
        is_mature: bool,
        _live_ctx,
        plan,
        context_package,
        queue,
        verdict,
        from_voice: bool = False,
    ) -> int:
        """
        Phase 4: full post-processing for one completed DER step.
        Faithful extraction of the inline finalize block from _execute_plan_der
        so both the serial path and concurrently-executed parallel_safe steps
        share identical post-processing. Returns the updated _tokens_used.

        ``from_voice`` (pin_517dfcbda150): threaded from the turn entry so the
        multi-session coupling wiring inside this method can classify the
        session domain ("voice" vs "der") instead of raising NameError.
        """
        # Session 312 (Pacman-only context flow, user-directed): the raw step
        # result used to enter the inline flow UNBOUNDED â€” three crawls put
        # 71.5k chars of page text into a 64k window (conv-99). The DB keeps
        # the full text (Pacman fragments + document store); the context
        # window gets the SAME bounded excerpt the evidence path uses
        # (gather tools 8000, others 400). Raw text lives in memory, not in
        # the window.
        # The SAME bounded text the window receives is what the budget must bill
        # (session-366 track C): keep it in a local so the token meter below
        # charges the excerpt, not the raw result.
        _window_evidence = self._smart_excerpt(
            step_result, _step_evidence_cap(item)
        )
        step_outputs.append(_window_evidence)
        # Session 312 / Session-318 / Session-319: turn URL memory is harvested
        # by ONE shared helper so the FAILURE path records addresses too (that
        # path skips this function entirely â€” see _der_handle_step_failure).
        # Behaviour here is unchanged; the body simply moved.
        _remember_turn_urls(self, step_result, "finalize")

        # â”€â”€ EventBus: emit tool:result or tool:error â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            _lifecycle_task_id = _turn_id or item.step_id
            if step_success:
                get_event_bus().emit(
                    IRISStreamEvent.TOOL_RESULT,
                    data={
                        "task_id": _lifecycle_task_id,
                        "result_summary": step_result[:200],
                        "tool_name": _step_tool_name(item),
                        "step_number": item.step_number,
                        # REQ-3 AC6 (T2): card_id stays stable across every
                        # event of a card's lifetime.
                        **self._card_envelope(_lifecycle_task_id),
                        # Edit diffs: `diff` = the step's latest edit; `diffs` =
                        # every edit when the step made more than one.
                        **_edit_diff_fields(item),
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                    session_id=_session,
                )
            else:
                get_event_bus().emit(
                    IRISStreamEvent.TOOL_ERROR,
                    data={
                        "task_id": _turn_id or item.step_id,
                        "error": step_result[:200],
                        "tool_name": _step_tool_name(item),
                        "step_number": item.step_number,
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                    session_id=_session,
                )
        except Exception:
            pass
        # T13 (REQ-10 AC10.11): the tool finished â€” close its narratable wait.
        # Results voice via the reply path; exit itself stays silent.
        try:
            self._end_tool_wait(_lifecycle_task_id)
        except Exception:
            pass

        # Option B / Pacman: fragment DER step output into vector DB so it can be
        # retrieved as context in later steps or future sessions.
        # MCM orchestrator handles fragmentation + compression check when available.
        try:
            if step_result and step_success:
                _der_text = (
                    f"[Step {item.step_number}: {item.description[:120]}]"
                    f"\n{step_result}"
                )
                # Trust-routing W2: a DER step that used an external/web
                # tool stores its output in 'reference', not 'tool'.
                _der_zone = (
                    "reference" if is_external_tool(getattr(item, "tool", "")) else None
                )
                if self._mcm_orch is not None:
                    # REQ-22: forward untrusted web scoring into the pacman
                    # fragment so credibility_map / citation_index persist in
                    # the 'reference' zone (only when the step used a web tool).
                    _cm = None
                    _ci = None
                    if isinstance(step_result, dict):
                        _cm = step_result.get("credibility_map")
                        _ci = step_result.get("citation_index")
                    self._mcm_orch.post_turn(
                        [{"role": "assistant", "content": _der_text}],
                        response_text=_der_text,
                        tool_name=getattr(item, "tool_name", ""),
                        zone=_der_zone,
                        credibility_map=_cm,
                        citation_index=_ci,
                    )
                elif (
                    self._memory_interface is not None
                    and hasattr(self._memory_interface, "episodic")
                    and hasattr(
                        self._memory_interface.episodic, "fragment_and_store"
                    )
                ):
                    # Background, same writer as every other fragment path â€”
                    # see the note at the document_data store above.
                    from backend.agent.mcm_protocol.actions.pacman_fragment import (
                        _submit_fragment_job,
                    )

                    _ep = self._memory_interface.episodic
                    _submit_fragment_job(
                        lambda: _ep.fragment_and_store(
                            _der_text,
                            session_id=_session,
                            chunk_type="der_output",
                            zone=_der_zone,
                        ),
                        f"der_output/step{getattr(item, 'step_number', '?')} "
                        f"({len(_der_text)} chars)",
                    )
        except Exception as _frag_exc:
            loud_error(_frag_exc, "der_pacman_fragment")

        # A3 FIX: also fragment FAILED outputs so failures are remembered and can
        # steer future recovery (the success path above skips them). Stored in the
        # 'tool' zone with chunk_type 'der_failure' for later recall.
        try:
            if step_result and not step_success:
                _fail_text = (
                    f"[FAILED Step {item.step_number}: {item.description[:120]}]"
                    f"\n{step_result}"
                )
                if (
                    self._memory_interface is not None
                    and hasattr(self._memory_interface, "episodic")
                    and hasattr(
                        self._memory_interface.episodic, "fragment_and_store"
                    )
                ):
                    from backend.agent.mcm_protocol.actions.pacman_fragment import (
                        _submit_fragment_job,
                    )

                    _ep_f = self._memory_interface.episodic
                    _submit_fragment_job(
                        lambda: _ep_f.fragment_and_store(
                            _fail_text,
                            session_id=_session,
                            chunk_type="der_failure",
                            zone="tool",
                        ),
                        f"der_failure/step{getattr(item, 'step_number', '?')} "
                        f"({len(_fail_text)} chars)",
                    )
        except Exception as _fail_frag_exc:
            loud_error(_fail_frag_exc, "der_pacman_fragment_failure")

        # â”€â”€ TOKEN BUDGET: accumulate estimated tokens from step result â”€â”€
        # 4 chars â‰ˆ 1 token; also count prompt overhead per step (~200 tok)
        # Session 366 (track C): bill the BOUNDED evidence the window actually
        # receives, not the raw tool result. MEASURED: a 16384-token window
        # yields a 13270-token budget; one crawl's RAW result charged ~12k
        # tokens and exhausted the turn after 6 of 10 steps
        # (`plan:budget_exhausted`, 15138/13270) while the window only ever got
        # the bounded excerpt (_window_evidence: gather tools 8000 chars, others
        # 400 - see the note above). Raw text lives in durable memory, not in the
        # window, so metering raw charged the model for tokens it never reads and
        # one large result killed the chain. 4 chars ~= 1 token, + ~200 prompt
        # overhead per step.
        _tokens_used += max(200, len(_window_evidence) // 4)
        # â”€â”€ EventBus: emit context:usage (token budget progress) â”€â”€â”€â”€â”€â”€
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            get_event_bus().emit(
                IRISStreamEvent.CONTEXT_USAGE,
                data={
                    "used_tokens": int(_tokens_used),
                    "max_tokens": int(self.resolve_context_window()),
                    "step_number": item.step_number,
                    "total_steps": len(queue.items),
                },
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
        except Exception:
            pass  # EventBus is optional â€” no crash if it fails
        if _tokens_used >= _token_budget:
            logger.info(
                f"[DER] Token budget exhausted ({_tokens_used}/{_token_budget}) "
                f"after step {item.step_number} â€” stopping early"
            )
            # RC6 FIX: emit explicit event instead of silent stop
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                _remaining = len([
                    i for i in queue.items
                    if i.step_id not in queue.completed_ids
                    and i.step_id not in queue.failed_ids
                ])
                get_event_bus().emit(
                    IRISStreamEvent.BUDGET_EXHAUSTED,
                    data={
                        "task_id": _turn_id,
                        "steps_completed": len(completed_items),
                        "steps_remaining": _remaining,
                        "tokens_used": _tokens_used,
                        "token_budget": _token_budget,
                        "message": f"Task incomplete: {_remaining} steps remaining "
                                   f"(budget {_tokens_used}/{_token_budget} exhausted)",
                    },
                    turn_id=_turn_id,
                    session_id=_session,
                )
            except Exception:
                pass  # EventBus is optional â€” no crash if it fails

        # â”€â”€ MYCELIUM SIGNAL: tool call â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            _mycelium_ingest_step_tools(
                self._memory_interface, item, step_success,
                len(queue.items), _session,
            )
        except Exception as _wm_exc:
            loud_error(_wm_exc, "mycelium_working_memory")

        # Phase 0 fix (Gap 5): populate step result on the QueueItem so
        # downstream consumers (reviewer, trace) read real output instead of
        # "no result".
        item.result = step_result

        # DER Phase 0 (D0.1): verify the result. A stub pattern with no real output
        # is FAILED -> step_success forced False so it cannot be marked complete as a
        # success (no silent success edge). This is the honest-signal fix.
        # pin_517dfcbda150: pass the resolved tool so web/crawl steps verify by
        # content sufficiency instead of assertion matching. A node step has
        # no item.tool; its decisive call is the tool (_step_calls chokepoint).
        _verified = self._verify_step_result(
            item.description, item.expected_output, step_result,
            tool=_step_tool(item),
            success=step_success,
        )
        if _verified == "VERIFIED" and _node_failed_after_change(item):
            _verified = "UNVERIFIED"
            logger.info(
                "[DER] step %s UNVERIFIED: it changed files and its last run after "
                "the change failed", getattr(item, "step_id", "?"),
            )
        if _verified == "FAILED":
            step_success = False

        # REQ-18 AC1 (T31): the verified LABEL for this step is only known here
        # (after full classification). Attach it to the verify trace entries
        # recorded by _verified_fraction above, then add the label record.
        try:
            from backend.agent.der_trace import get_der_trace

            get_der_trace(self._der_trace_task_id()).record(
                "verify_label",
                verified_label=_verified,
                step_id=getattr(item, "step_id", ""),
                step_number=getattr(item, "step_number", 0),
                tool=getattr(item, "tool", None),
            )
        except Exception:
            pass

        _der_prior_research_delivered(self, item, step_result, _session)

        # Spec D9 (Wave E): the step becomes a typed event (BUG / ATTEMPT /
        # DEAD_END / FIX ...) with the label the verifier gave it - event-level
        # credit. Values are bound now; the write runs on its own lane.
        _memory_events_submit(
            self, "record_step",
            thread_id=_session,
            task_id=f"{_session}:{_turn_id or ''}",
            step_id=str(getattr(item, "step_id", "") or ""),
            # The decisive call (the last failed one, else the last): a node
            # step has no item.tool, so record_step saw "none" and a coding
            # node's test run never counted as a test command.
            tool=(_step_decisive_call(item) or {}).get("tool") or getattr(item, "tool", None),
            params=(dict((_step_decisive_call(item) or {}).get("args") or {})
                    or (dict(item.params) if isinstance(getattr(item, "params", None), dict) else None)),
            success=bool(step_success),
            verified=str(_verified or ""),
            error_text=(str(step_result or "")[:2000] if not step_success else ""),
            description=str(getattr(item, "description", "") or "")[:300],
            recall_trace_ids=list(getattr(item, "recall_trace_ids", None) or []),
        )

        # â”€â”€ Phase 2 (D2.1): unified recovery â€” verification FAILED uses the
        # SAME _split_step operator as the physics trigger. No separate graft
        # code path remains. Split prepays work units up front (Lyapunov Phi
        # strictly decreases). Children are Sub-Loops (is_subloop=True) that
        # collapse back to this step as ONE COMPRESS. â”€â”€
        # BUGFIX (REQ-8 AC3): this block used to run at the very end of the
        # function (right before `return _tokens_used`), but `_children` is
        # READ much earlier â€” by the REQ-8 task:learning emit below and by the
        # REQ-7 physics-narration hook â€” while it is only ASSIGNED here. Since
        # a name assigned anywhere in a Python function is local for the whole
        # function, every earlier read raised `UnboundLocalError: cannot
        # access local variable '_children' where it is not associated with a
        # value`, silently caught by each call site's own try/except so the
        # task:learning event (and the physics narration) never fired. Moved
        # up so `_children` is a real, already-computed value at every read
        # site. `_children` defaults to `[]` (no split) so the success path â€”
        # which never enters the split branch â€” still has a bound, honestly
        # falsy value instead of leaving the name unbound.
        _children = []
        # REQ-13 (fold forward, not back): only a FAILED verification may enter
        # the split gate. A weak (UNVERIFIED) graded score after evidence
        # gathering folds forward to an honest low-confidence answer instead of
        # spawning another round of gathering the same evidence (AC1). The
        # guard is EXPLICIT, not incidental: an execution-layer `success=False`
        # envelope that still carried content (REQ-1 informational-fallback
        # edge) would otherwise reach _split_step untouched by the D4 taxonomy
        # below (non-errored content skips classification). The D4/REQ-4
        # classes remain the ONLY no-split path for classified
        # transport/provider failures (AC2); _split_step stays reachable for
        # genuine unclassified semantic failure (AC3).
        if not step_success and not item.is_subloop and _verified == "FAILED":
            # D4/REQ-4 (specs/long-horizon-der-execution): classify the failure
            # BEFORE recursive fan-out. Transport/provider/envelope failures
            # (timeout, rate-limit, unavailable tool, bad args, empty result,
            # auth) are recorded as failure evidence and must NOT split the
            # task into children â€” the old `not step_success -> split` rule
            # turned a single transient error into a recursive fan-out. Only a
            # genuine semantic failure (tool produced content but verification
            # judged it wrong) splits: the step_result then carries real
            # content, not an error prefix.
            _split_ok = True
            try:
                from backend.agent.der_execution_ledger import (
                    classify_failure,
                    ExecutionLedger,
                    OUTCOME_TRANSIENT,
                    OUTCOME_UNAVAILABLE,
                    OUTCOME_INVALID_ARGS,
                    OUTCOME_EMPTY,
                    OUTCOME_PERMANENT,
                )

                _res_text = (step_result or "").strip()
                _res_low = _res_text.lower()
                _tool_errored = (
                    not _res_text
                    or _res_low.startswith("error")
                    or _res_low.startswith("[step error")
                    or _res_low.startswith("duplicate call")
                )
                if _tool_errored:
                    _fail_class = classify_failure(
                        False,
                        error=_res_text[:400],
                        error_type=getattr(item, "error_type", None),
                        result=step_result,
                    )
                    if _fail_class in (
                        OUTCOME_TRANSIENT,
                        OUTCOME_UNAVAILABLE,
                        OUTCOME_INVALID_ARGS,
                        OUTCOME_EMPTY,
                        OUTCOME_PERMANENT,
                    ):
                        _split_ok = False
                        logger.info(
                            "[DER] step %s failure classified=%s â€” recorded, NOT split (D4)",
                            item.step_id, _fail_class,
                        )
                        try:
                            _ledger = getattr(self, "_der_ledger", None)
                            if _ledger is None:
                                _ledger = ExecutionLedger(
                                    conversation_id=self.conversation_id or "",
                                    storage_path=_der_ledger_storage_path(),  # GROUND TRUTH T9 (REQ-14 AC1)
                                )
                                self._der_ledger = _ledger
                            _ledger.record_failure(
                                task_id=self.conversation_id or self.session_id or "unknown",
                                step_id=item.step_id,
                                attempt_id=getattr(item, "attempt_id", "") or item.step_id,
                                failure_class=_fail_class,
                                input_summary=(item.description or "")[:200],
                                tool=_step_tool(item),
                                error_type=getattr(item, "error_type", None),
                                error_summary=_res_text[:300],
                                recovered=False,
                            )
                        except Exception as _led_exc:  # noqa: BLE001
                            logger.debug("[DER] failure-evidence record failed: %s", _led_exc)
            except Exception:  # noqa: BLE001 â€” classification must never break recovery
                _split_ok = True
            if _split_ok:
                try:
                    # Fold-back: split width is a shape decision (side lane).
                    _der_physics_settle(self, _session)
                    _cad_split = self._der_live_cad_state(_session)
                    _wu = getattr(self, "_der_work_units", 0)
                    # REQ-4 AC1 (T16): the continuous verified fraction is a
                    # GRADED steering input at the split decision â€” mid-band
                    # selects a bounded probe (width 1) instead of a full-width
                    # re-attempt. Never crash the split on fraction failure.
                    try:
                        _vf_split = self._verified_fraction(
                            getattr(item, "expected_output", None),
                            str(step_result or ""),
                        )
                    except Exception:
                        _vf_split = 0.0
                    _children = self._split_step(
                        item,
                        "verify_failed",
                        _cad_split,
                        _wu,
                        step_result=step_result,
                        verified_fraction=_vf_split,
                    )
                    # REQ-3: debit measured tokens, not a flat child count.
                    # _measured must be bound for the debit even when no child was
                    # created (empty split) â€” a NameError here was silently swallowed
                    # by the broad except, disabling the work-unit debit entirely
                    # (NORTHSTAR defect-shape #1).
                    _measured = 0
                    if _children:
                        # The children run as nodes (their own tool loops).
                        self._der_route_subloop_children(
                            _children, queue, _session, _turn_id
                        )
                        # REQ-3: debit measured tokens, not a flat child count.
                        _measured = max(200, len(step_result) // 4)
                        # REQ-14 (AC1/AC5, T23): a sub-loop split REVISES the
                        # plan mid-task â€” re-emit task:start through the SAME
                        # merge-by-id channel (useTaskProgress.ts:210-227) with
                        # the revision origin so the frontend refreshes
                        # description/tool for new steps without clobbering live
                        # status, and REQ-18's trace can attribute the origin.
                        # The payload keeps the contract keys unchanged
                        # (task_id/description/plan_title/mode/steps/total_steps)
                        # plus `origin`.
                        try:
                            from backend.agent.event_bus import (
                                get_event_bus,
                                IRISStreamEvent,
                            )

                            _rev_mode = (
                                queue.mode.value
                                if getattr(queue, "mode", None)
                                else str(_phase)
                            )
                            # REQ-3 (T2) edge case: a sub-loop split CONTINUES
                            # the parent card â€” it is a branch WITHIN a card,
                            # never a second card. Handled generically by the
                            # "not initial" rule in _resolve_card_identity.
                            _card_task_id = _turn_id or getattr(
                                plan, "original_task", ""
                            )[:40]
                            _card_id, _card_relation = self._resolve_card_identity(
                                _card_task_id, "sub_loop_split"
                            )
                            # T2b (REQ-1 AC8): the badge marks the nested row,
                            # so the label is set on the CHILD steps this
                            # split just produced â€” never on the parent or
                            # any sibling already in the queue. A step
                            # outside `_children` carries no `branchLabel`
                            # key at all (not an empty string), so
                            # ChassisBranchBadge renders on branch rows only.
                            _branch_child_ids = {c.step_id for c in _children}
                            get_event_bus().emit(
                                IRISStreamEvent.TASK_START,
                                data=self._task_start_payload(
                                    task_id=_card_task_id,
                                    description=getattr(
                                        plan, "original_task", ""
                                    )[:200],
                                    plan_title=self._effective_plan_title(plan),
                                    mode=_rev_mode,
                                    steps=[
                                        {
                                            "id": it.step_id,
                                            "description": it.description,
                                            "status": "pending",
                                            "toolName": _step_tool(it),
                                            **(
                                                {"branchLabel": DER_SUBLOOP_BRANCH_LABEL}
                                                if it.step_id in _branch_child_ids
                                                else {}
                                            ),
                                        }
                                        for it in queue.items
                                    ],
                                    total_steps=len(queue.items),
                                    origin="sub_loop_split",
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
                            # T4a (REQ-4 AC1): persist the split card. Uses
                            # _queue_steps_snapshot (derives done/failed from
                            # queue state) rather than the wire payload's
                            # blanket "pending" â€” a mid-run restore should
                            # show already-finished steps as finished.
                            self._persist_card_snapshot(
                                card_id=_card_id,
                                conversation_id=self.conversation_id,
                                card_relation=_card_relation,
                                plan_title=self._effective_plan_title(plan),
                                mode=_rev_mode,
                                steps=self._queue_steps_snapshot(queue),
                                total_steps=len(queue.items),
                                terminal_state="running",
                            )
                            # REQ-18 AC3 (T31): correlate the sub-loop-split
                            # revision (REQ-4/REQ-13).
                            try:
                                from backend.agent.der_trace import get_der_trace

                                get_der_trace(self._der_trace_task_id()).record(
                                    "revision",
                                    origin="sub_loop_split",
                                    children=len(_children),
                                    boundary_step=getattr(
                                        queue, "_last_step_number", None
                                    ),
                                )
                            except Exception:
                                pass
                        except Exception:
                            pass  # EventBus is optional â€” never break recovery
                    self._der_work_units = debit_work_units(_wu, _measured)
                    logger.info(
                        "[DER] verify_failed -> split into %d sub-loops (work_units=%d)",
                        len(_children), self._der_work_units,
                    )
                except Exception as _split_exc:
                    logger.warning("[DER] split-on-failure failed: %s", _split_exc)

        # â”€â”€ Phase 3 (D3.3 G5): honest commit ledger â”€â”€
        # REQ-1: a commit is recorded for EVERY executed action with its true label
        # (VERIFIED / UNVERIFIED / FAILED) â€” not only VERIFIED. This is the learning
        # signal the outer loop and the AVOID/edge-miss path consume; gating it on
        # VERIFIED starves failure learning. Store write â€” never injected into a
        # prompt.
        # D1 (HANDOFF 11): the write runs on lane("memory_events"), never on
        # the answer path - inline it waited on "database is locked" (live
        # 2026-10-04 r06: a 22 s gap in a 42 s reply). No reader decides on
        # der_commits in the same turn (the outer loop reads it between
        # sessions). The state is read NOW; only the row lands later.
        try:
            from backend.agent.caducean_trajectory import (
                get_trajectory_recorder,
            )
            from backend.utils.durability_queue import lane as _durability_lane

            _cad = self._der_live_cad_state(_session)
            _commit_step = getattr(item, "step_id", "?")
            _commit_kw = dict(
                session_id=_session,
                step_id=item.step_id,
                commit_hash="",
                message=f"{_verified} step {item.step_number}: {item.description[:80]}",
                u=_cad.get("u"),
                xi=_cad.get("xi"),
                verified_label=_verified,
            )
            _commit_mi = self._memory_interface

            def _commit_job():
                try:
                    # REQ-20: DER commits land in the APPLICATION store
                    # (memory_interface episodic db), not .mcm/coordinates.db.
                    get_trajectory_recorder(_commit_mi).record_commit(**_commit_kw)
                    # GROUND TRUTH T5 (REQ-2 AC1/AC4): count commits BY LABEL
                    # at the write, so a failing write and a missing one differ.
                    _write_counters.bump("commit.written")
                    _write_counters.bump(
                        "commit.label.%s" % str(_verified or "UNKNOWN").lower())
                except Exception as _commit_exc:
                    # GROUND TRUTH T5/T10: a swallowed commit write must stay
                    # visible as a number and a warning.
                    _write_counters.bump("commit.write_failed")
                    logger.warning(
                        "[DER] record_commit FAILED (session=%s step=%s label=%s): %s",
                        _session, _commit_step, _verified, _commit_exc,
                    )

            if not _durability_lane("memory_events").submit("der_commit", _commit_job):
                _write_counters.bump("commit.write_failed")
        except Exception as _commit_exc:
            _write_counters.bump("commit.write_failed")
            logger.warning(
                "[DER] record_commit FAILED (session=%s step=%s label=%s): %s",
                _session, getattr(item, "step_id", "?"), _verified, _commit_exc,
            )

        # â”€â”€ REQ-1 AC2/AC3/AC4: per-step edge-score consequence of verified_label.
        # VERIFIED hit-scores (+0.05), UNVERIFIED partial-credits (+0.02, capped â€”
        # AC3) and never crystallizes, FAILED miss-scores (-0.08) and feeds the
        # AVOID header (AC4). Never raises. INLINE on purpose: the next step of
        # this turn decides on what it writes (explorer tool choice reads the
        # tool_choice edges, the AVOID header and the recovery graft read the
        # miss episode), so a lane would hand them a stale view. Node steps
        # score here since S54; a slow run is logged so a cost shows up.
        # tc-decide-v7: the decided tool_choice rows are stamped in
        # _der_post_step, after the post-finalize artifact graft decides whether
        # this step was retried. A stamp here would run before the graft and
        # call a grafted step "completed".

        try:
            _score_t0 = time.monotonic()
            self._der_score_step_outcome(item, _verified, _session, step_result)
            _score_s = time.monotonic() - _score_t0
            if _score_s > 0.25:
                logger.warning(
                    "[DER] slow step scoring %.2fs (step=%s label=%s)",
                    _score_s, getattr(item, "step_id", "?"), _verified,
                )
        except Exception as _score_exc:
            _write_counters.bump("step_outcome.scoring_failed")
            logger.warning(
                "[DER] per-step edge scoring FAILED (step=%s): %s",
                getattr(item, "step_id", "?"), _score_exc,
            )

        if _children and not getattr(item, "is_subloop", False):
            # Fold-back (parallel nodes, 2026-10-04): the step's verification
            # FAILED and it split - it waits for its children (the race)
            # instead of completing, so its dependents wait for the resolution.
            queue.hold_split_parent(item.step_id, [c.step_id for c in _children], [])
        else:
            queue.mark_complete(item.step_id)

        # â”€â”€ T6/T8/T10 (specs/long-horizon-der-execution REQ-5/REQ-9) â”€â”€â”€â”€â”€â”€
        # D8: persistence gates terminal state. Close the execution-attempt in
        # the ledger and persist BEFORE emitting the terminal task:learning
        # event. A persistence failure is exposed honestly (warning) and the
        # event still fires â€” but the durable record is flagged, never silently
        # claimed.
        try:
            from backend.agent.der_execution_ledger import ExecutionLedger

            _ledger = getattr(self, "_der_ledger", None)
            if _ledger is None:
                _ledger = ExecutionLedger(
                    conversation_id=self.conversation_id or self.session_id or "",
                    storage_path=_der_ledger_storage_path(),  # GROUND TRUTH T9 (REQ-14 AC1)
                )
                self._der_ledger = _ledger
            _att = _ledger.open_attempt(
                task_id=self.conversation_id or self.session_id or "unknown",
                step_id=item.step_id,
                parent_step_id=getattr(item, "parent_step_id", None),
                action_key=(item.description or item.tool or "")[:80],
                tool=_step_tool(item),
            )
            _ledger.close_attempt(
                _att,
                outcome=_verified if _verified in ("VERIFIED", "UNVERIFIED", "FAILED") else "permanent",
                verified_label=_verified,
                error_type=getattr(item, "error_type", None),
            )
            if not _ledger.persist():
                logger.warning(
                    "[DER] attempt persistence FAILED for step %s â€” durable completion not claimed",
                    item.step_id,
                )
        except Exception as _att_exc:  # noqa: BLE001 â€” ledger must never block the step
            logger.debug("[DER] attempt-ledger write failed: %s", _att_exc)

        # â”€â”€ REQ-8: honest learning signal (task:learning) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Emited (never injected into a prompt) so the frontend can show the real
        # card state + Pacman OrbCanvas particles on the border. Three signals:
        #   avoided    â€” FAILED step (no children, not a subloop) -> AVOID
        #   retried    â€” verify_failed -> split into Sub-Loops
        #   crystallizedâ€” VERIFIED step -> skill captured
        # Off the critical path; a bus failure must never block the step result.
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            if _verified == "VERIFIED":
                _signal = "crystallized"
            elif _children:
                _signal = "retried"
            else:
                _signal = "avoided"
            get_event_bus().emit(
                IRISStreamEvent.TASK_LEARNING,
                {
                    "session_id": _session,
                    "step_id": item.step_id,
                    "step_number": item.step_number,
                    "signal": _signal,
                    "verified_label": _verified,
                    "description": item.description or "",
                    "is_subloop": bool(getattr(item, "is_subloop", False)),
                },
            )
        except Exception as _learn_exc:
            logger.debug("[DER] task:learning emit failed: %s", _learn_exc)

        # â”€â”€ Phase 3 (Gap 3): propagate this step's output into dependent
        # pending steps so later steps consume real results, not static
        # params. Non-blocking â€” never fails the step. â”€â”€
        try:
            queue.resolve_dependent_params(item, step_result)
        except Exception as _dep_exc:
            logger.warning(
                "[DER] resolve_dependent_params failed: %s", _dep_exc
            )

        # â”€â”€ Caducean physics -> ordered side lane (_der_submit_physics) â”€â”€
        # The node record is stamped HERE, inline: synthesis and the
        # continuation consult read it. The physics update (EML, integrator,
        # trajectory row, homeostasis, refit, Immortus chain, physics-event
        # narration) is queued right after and lands off the answer path; the
        # next shape decision folds back on it (_der_physics_settle).
        _mediator, _mediator_source = "none", "none"
        _phys = None
        try:
            # REQ-23 (T37): the causal triple â€” resolve the MEDIATOR once and
            # bind it to a VALUE (the write runs later; `item` must not be
            # read from another thread after the loop moves on). AC1: written
            # at the same finalize point as the outcome; AC5: "none" is the
            # explicit value for mediator-less (decision/synthesis) nodes,
            # never empty â€” so they do not rank as failed actions.
            _mediator, _mediator_source = self._der_mediator_for(item)
            # REQ-3 AC2 (T37 completion): stamp the node's memory record at
            # finalize â€” outcome, continuous fraction, mediator, and the
            # landing coordinate â€” so the record is complete for the causal
            # vocabulary (Treatment -> Mediator -> Outcome) and for the
            # REQ-26 posterior reader. Off the critical path; never fails the
            # step.
            try:
                _rec = getattr(item, "node_record", None) or getattr(
                    item, "footprint", None
                )
                if _rec is None:
                    # Every node carries its record (REQ-3 T8), and this is
                    # where outcome, goal coverage and mediator land. Steps
                    # added after planning (continuation, recovery, steering
                    # and revise replans, recovery grafts) were built without
                    # one, so their results never counted: a "cover the open
                    # fact" step searched the fact, it stayed open, was pushed
                    # again and blocked (eval r09 conv-836, 2026-10-05).
                    from backend.agent.der_loop import NodeRecord

                    _rec = NodeRecord(
                        step_id=str(getattr(item, "step_id", "") or ""),
                        parent_step_id="",
                        objective_anchor=str(getattr(item, "objective_anchor", "") or ""),
                        expected_output=str(getattr(item, "expected_output", "") or ""),
                        remaining=str(getattr(item, "description", "") or ""),
                    )
                    item.node_record = _rec
                if _rec is not None:
                    _rec.outcome = _verified
                    # REQ-18 (T19): stamp the two domain axes at the same
                    # finalize point as the outcome â€” topic re-resolved from
                    # the FULL step result text (richer signal than the seed
                    # description; registry-backed, general + logged on miss),
                    # execution from the active winding. AC4: these ride the
                    # node record AND the chain row.
                    _rec.topic_domain = self._der_topic_domain(
                        f"{item.description or ''} {step_result or ''}"
                    ) or "general"
                    _rec.execution_domain = (
                        self._der_execution_domain(from_voice) or "der"
                    )
                    # T36-FIX (content_summary): the L6014 construction comment
                    # promised "the finalize site re-stamps with the full step
                    # result text" â€” but content_summary was NEVER re-stamped, so
                    # _der_node_record_evidence fed the synthesis LLM only the
                    # step DESCRIPTION (plan sentence), not the actual tool output.
                    # Live T36 smoke: crawl stored 17 chunks + rendered the prism
                    # card, yet synthesis said "search tool did not return any
                    # actual results" (synthesis prompt was ~111 tokens). Re-stamp
                    # here with the real step result so the synthesis evidence is
                    # the actual crawl content, not the plan text. Bounded to 300
                    # chars to keep the record bounded (same as the seed).
                    _rec.content_summary = (step_result or "")[:300]
                    # REQ-4: continuous verified fraction, recomputed at the
                    # finalize point (the verifier's decisive fraction is not
                    # otherwise surfaced here). Fallback: the label's canonical
                    # continuous value so the record is never NaN/0.0 for a
                    # VERIFIED step.
                    try:
                        _vf = self._verified_fraction(
                            item.expected_output, str(step_result or "")
                        )
                    except Exception:
                        _vf = {"VERIFIED": 1.0, "UNVERIFIED": 0.5, "FAILED": 0.0}.get(
                            _verified, 0.0
                        )
                    _rec.verified_fraction = _vf
                    # â”€â”€ Goal contract T5 (specs/goal-contract-coverage,
                    # REQ-2/REQ-3) â”€â”€ mark coverage from the settled node's
                    # outcome + result (VERIFIED + term match, set union),
                    # stamp C onto the task node's verified_fraction, log
                    # C/g/covered/required. Advisory: never break finalize.
                    try:
                        _gc_state = getattr(self, "_goal_contract_state", None)
                        if _gc_state is not None:
                            from backend.agent import goal_contract as _gc_mod2

                            _gc_state["outcomes"].append(
                                _gc_coverage_label(_verified, item, step_result)
                            )
                            _gc_state["results"].append(str(step_result or ""))
                            _gc_cov = _gc_mod2.mark_coverage(
                                _gc_state["contract"],
                                list(_gc_state["outcomes"]),
                                list(_gc_state["results"]),
                            )
                            _gc_prev = float(_gc_state.get("C", 0.0))
                            _gc_state["prev_c"] = _gc_prev
                            _gc_state["C"] = float(_gc_cov.C)
                            _gc_state["g"] = float(_gc_cov.g)
                            _gc_state["covered"] = list(_gc_cov.covered)
                            try:
                                _gc_counters = _gc_state.get("counters") or {}
                                _gc_counters["facts_covered"] = len(_gc_cov.covered)
                                _gc_state["counters"] = _gc_counters
                            except Exception:
                                pass
                            # REQ-3 AC3.4: track consecutive settled nodes with
                            # unmoved C so the stall signal (rho/idling) can
                            # fire downstream. Never raises, never blocks.
                            try:
                                if abs(float(_gc_cov.C) - _gc_prev) < 1e-9:
                                    _gc_state["unmoved"] = int(
                                        _gc_state.get("unmoved", 0)
                                    ) + 1
                                else:
                                    _gc_state["unmoved"] = 0
                                # rho = dC/(g*ds): ds = measured tokens spent
                                # this cycle (4 chars ~= 1 token on the step
                                # result). Advisory â€” computed best-effort.
                                _gc_ds = max(
                                    1.0, len(str(step_result or "")) / 4.0
                                )
                                _gc_state["rho"] = _gc_mod2.progress_ratio(
                                    _gc_prev, float(_gc_cov.C),
                                    float(_gc_cov.g), _gc_ds,
                                )
                            except Exception:
                                _gc_state["unmoved"] = 0
                            _gc_task_rec = _gc_state.get("task_record")
                            if _gc_task_rec is not None:
                                _gc_task_rec.verified_fraction = float(_gc_cov.C)
                                _gc_task_rec.covered_facts = list(_gc_cov.covered)
                            # REQ-4 AC4.2: agent ceiling discovery â€” a VERIFIED
                            # step whose result carries deliverables BEYOND the
                            # required floor proposes them as ceiling facts
                            # (surplus extraction via the same deterministic
                            # extractor; floor-deduped, capped, never
                            # blocking). Bounded to 2 per step so one rich
                            # result cannot fill the ceiling alone. Advisory.
                            try:
                                # Session 326 (live bug): a step can be VERIFIED
                                # while its result is an ERROR envelope. Probe 3
                                # logged
                                #   agent ceiling +2 ({"success": true,
                                #   "stdout": "wc : The term 'wc' is not
                                #   recognized..."})
                                # â€” shell error text became "discovered facts".
                                # Only discover from a result that carries
                                # actual output.
                                if (
                                    str(_verified or "").upper() == "VERIFIED"
                                    and str(step_result or "").strip()
                                    and not self._gc_result_is_error(step_result)
                                ):
                                    _gc_req_norms = {
                                        _gc_mod2._norm(_f)
                                        for _f in _gc_state["contract"].required
                                    }
                                    _gc_surplus = [
                                        _f for _f in _gc_mod2.extract_required(
                                            str(step_result or "")
                                        )
                                        if _gc_mod2._norm(_f)
                                        not in _gc_req_norms
                                    ][:2]
                                    if _gc_surplus:
                                        _gc_new = _gc_mod2.add_ceiling(
                                            _gc_state["contract"], _gc_surplus
                                        )
                                        if _gc_new is not _gc_state["contract"]:
                                            _gc_state["contract"] = _gc_new
                                            _gc_state["task_record"].ceiling_facts = (
                                                list(_gc_new.ceiling)
                                            )
                                            _gc_state[
                                                "task_record"
                                            ].contract_version = int(
                                                _gc_new.version
                                            )
                                            _gc_c2 = _gc_state.get("counters") or {}
                                            _gc_c2["amendments_agent"] = int(
                                                _gc_c2.get("amendments_agent", 0)
                                            ) + 1
                                            _gc_state["counters"] = _gc_c2
                                            logger.info(
                                                "[goal-contract] agent ceiling "
                                                "+%d (%s)",
                                                len(_gc_surplus),
                                                str(_gc_surplus[0])[:120],
                                            )
                            except Exception:
                                pass
                            logger.info(
                                "[goal-contract] node settled: C=%.3f g=%.3f "
                                "covered=%d required=%d blocked=%s",
                                float(_gc_cov.C), float(_gc_cov.g),
                                len(_gc_cov.covered), int(_gc_cov.required_n),
                                [b for b in _gc_cov.blocked] or [],
                            )
                    except Exception as _gc_cov_exc:
                        logger.debug(
                            "[goal-contract] coverage mark skipped: %s",
                            _gc_cov_exc,
                        )
                    # â”€â”€ Goal contract T9 (REQ-5 AC5.1): a FAILED settle with
                    # a terminal typed reason blocks the facts it was working
                    # on. Advisory â€” non-terminal failures retry, never block.
                    try:
                        if str(_verified or "").upper() == "FAILED":
                            _gc_reason = str(
                                getattr(item, "error_type", "") or ""
                            )
                            if _gc_reason:
                                self._goal_contract_block_facts(
                                    item, _gc_reason, str(step_result or ""),
                                )
                    except Exception:
                        pass
                    _rec.mediator = _mediator
                    _rec.mediator_source = _mediator_source
                    _rec.edge_ids = _rec.edge_ids or []
                    # â”€â”€ REQ-5 AC2/AC4 (T17): record the COUPLING DECISION at
                    # commit. The branches surfaced to this step (all of them,
                    # capped â€” AC1) plus the one it chose are stamped on the
                    # node record, and the edge to the chosen branch is
                    # written/strengthened with the decision as provenance.
                    # Off the critical path; never raises.
                    try:
                        _cands = getattr(item, "_coupled_candidates", None) or []
                        if _cands:
                            _chosen = self._der_choose_coupling_branch(item, _cands)
                            self._der_record_coupling_decision(
                                item, _cands, chosen_node_id=_chosen, record=_rec
                            )
                    except Exception as _cc_exc:
                        logger.debug(
                            "[DER] coupling-decision record failed: %s", _cc_exc
                        )
                    # â”€â”€ REQ-19 (T20): persist the DER structural links into
                    # the SHARED link store at the same finalize point â€” the
                    # node's memory record AND its edges land together (DAG =
                    # memory = DAG). part_of (sub-loop containment, child ->
                    # parent), depends_on (plan dependency), relevant_to
                    # (branches actually surfaced to a decision â€” provenance,
                    # not affinity), failed_like (same failure class, so AVOID
                    # recall is a graph walk). Off the critical path; the
                    # writer itself never raises.
                    # D1: on lane("memory_events") - inline, pin_store.link
                    # waited on "database is locked" in the answer path.
                    try:
                        if self._der_links is not None:
                            from backend.utils.durability_queue import lane as _durability_lane

                            _durability_lane("memory_events").submit(
                                "der_node_links", self._der_links.write_node_links,
                                item,
                                _rec,
                                step_success=step_success,
                                step_result=str(step_result or ""),
                                execution_domain=_rec.execution_domain,
                                session_id=_session or "",
                            )
                    except Exception as _dl_exc:
                        logger.debug(
                            "[DER] structural link write failed: %s", _dl_exc
                        )
            except Exception as _rec_exc:
                logger.debug(
                    "[DER] node_record finalize stamp failed: %s", _rec_exc
                )
            # â”€â”€ REQ-4 AC4 (T16b): FOLD-BACK â€” a sub-loop child folds back as
            # a compressed observation that CHANGES the parent's state: the
            # parent's node_record gains the child's verified outcome (REQ-3
            # AC1: the parent's next decision reads node records that now
            # include what the children resolved). Bounded (DER_FOLD_BACK_MAX);
            # off the critical path; never raises.
            if getattr(item, "is_subloop", False):
                try:
                    _parent_step_id = getattr(
                        getattr(item, "node_record", None), "parent_step_id", ""
                    ) or ""
                    if _parent_step_id:
                        for _qi in getattr(queue, "items", None) or []:
                            if getattr(_qi, "step_id", "") == _parent_step_id:
                                _prec = getattr(_qi, "node_record", None)
                                if _prec is not None:
                                    _fbs = list(
                                        getattr(_prec, "folded_back", None) or []
                                    )
                                    _fbs.append(
                                        f"[{item.step_id}] {_verified}: "
                                        f"{item.description[:160]}"
                                    )
                                    _prec.folded_back = _fbs[-DER_FOLD_BACK_MAX:]
                                break
                except Exception as _fb_exc:  # noqa: BLE001
                    logger.debug("[DER] fold-back write failed: %s", _fb_exc)

        except Exception as _cad_exc:
            loud_error(_cad_exc, "der_node_record_finalize")
        try:
            _phys = self._der_submit_physics(
                item,
                node_record=getattr(item, "node_record", None)
                or getattr(item, "footprint", None),
                step_success=step_success,
                verified=_verified,
                session=_session,
                from_voice=from_voice,
                n_children=len(_children),
                mediator=_mediator,
                mediator_source=_mediator_source,
            )
        except Exception as _lane_exc:
            loud_error(_lane_exc, "der_physics_submit")
        # â”€â”€ specs/tool-result-envelope T6 (REQ-1 AC1.2): build the
        # envelope ONCE at the finalize site. Extracted into its own
        # method so an upstream caducean failure can never skip
        # envelope construction (AC1.4: the envelope ALWAYS exists â€”
        # full or minimal â€” never a silent legacy item).
        try:
            self._der_build_step_envelope(
                item=item,
                step_result=step_result,
                step_success=step_success,
                outcome=_verified,
                completed_items=completed_items,
                _session=_session,
                _turn_id=_turn_id,
                coords_from=None,
                coords_to=None,
            )
            if _phys is not None:
                with _phys.lock:
                    _der_fold_envelope(item, _phys)
        except Exception as _env_call_exc:
            logger.warning(
                "[envelope] finalize call failed for step %s: %s",
                getattr(item, "step_id", "?"), _env_call_exc,
            )

        # â”€â”€ WORKING MEMORY: accumulate findings for later steps â”€â”€
        # T7 (specs/tool-result-envelope REQ-2 AC2.1): append the envelope
        # LINE (status + summary + wrapper labels + raw_ref doc id) for EVERY
        # settled step INCLUDING failures â€” the old site appended a raw
        # _smart_excerpt for successes only, silently skipping failures,
        # which guaranteed the next step could not see the flat tire it just
        # hit. Raw payloads no longer enter working memory by construction;
        # _run_step_direct's 6000-cap stays as defense-in-depth. Pre-envelope
        # items (legacy edge) degrade to the old bounded excerpt.
        try:
            _env = getattr(item, "envelope", None)
            if self._memory_interface:
                if _env is not None:
                    _wm_note = (
                        f"[Step {item.step_number}: {item.description[:80]}] "
                        f"{_env.line()}"
                    )
                elif step_result:
                    _wm_note = (
                        f"[Step {item.step_number}: {item.description[:80]}]"
                        f" {self._smart_excerpt(step_result, _step_evidence_cap(item))}"
                    )
                else:
                    _wm_note = ""
                if _wm_note:
                    self._memory_interface.append_to_session(
                        _session, _wm_note, zone="working_history"
                    )
                # Session 245 (live memory footer): surface the memory WRITE
                # on the card's footer while execution happens â€” previously
                # memory:event only fired once at recall time (before the
                # card existed), so the footer sat on "Active Execution" for
                # whole runs. Same registry kind ("episodic"), outcome_type
                # distinguishes store from recall.
                try:
                    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                    get_event_bus().emit(
                        IRISStreamEvent.MEMORY_EVENT,
                        data={
                            "kind": "episodic",
                            "task_summary": f"[Step {item.step_number}] {item.description[:80]}",
                            "outcome_type": "store",
                            "duration_ms": 0,
                        },
                        session_id=_session,
                        conversation_id=self.conversation_id,
                    )
                except Exception:
                    pass  # never block the DER loop on an emit failure
        except Exception as _wm2_exc:
            loud_error(_wm2_exc, "append_working_history")

        completed_items.append(item)

        # Session-318 T16 (REQ-9 AC9.5/AC9.6): VLM in-site recovery trigger.
        # Dead fetch + unvisited same-site candidates + budget remaining â†’
        # a recovery QueueItem joins via add_item (the card-visible path).
        # Dependents order after it; independents ahead proceed first â€” the
        # lane never blocks the loop (no new locks, no waits). One recovery
        # per dead host per turn; chains forbidden in the helper.
        try:
            _rec_item = self._der_maybe_open_recovery(
                item, step_result, completed_items, queue,
            )
            if _rec_item is not None:
                queue.add_item(_rec_item)
                try:
                    from backend.agent.write_counters import bump as _bump_ropen
                    _bump_ropen("envelope.recovery_opens")
                except Exception:
                    pass
                try:
                    from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                    get_event_bus().emit(
                        IRISStreamEvent.TASK_PROGRESS,
                        data={
                            "add_step": True,
                            "step_id": _rec_item.step_id,
                            "step_number": _rec_item.step_number,
                            "description": _rec_item.description[:200],
                            "tool_name": "crawler_query",
                            **self._card_envelope(_turn_id),
                        },
                    )
                except Exception:
                    pass  # never block the DER loop on an emit failure
        except Exception as _rec_open_exc:
            logger.debug("[DER] recovery open failed: %s", _rec_open_exc)

        # â”€â”€ Phase 3: escalation + explorer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # After each step, check if mode escalation is warranted.
        # If queue is complete but more work is needed in AGENTIC/FULL
        # mode, re-plan with the LLM.
        try:
            _result_summary = (step_outputs[-1] if step_outputs else "")[:200]
            queue.check_escalation(
                review_verdict=verdict,
                tool_result_summary=_result_summary,
                token_budget_remaining=_token_budget - _tokens_used,
                turn_id=_turn_id,
            )

            # If queue is complete but mode is AGENTIC or FULL,
            # ask the LLM if more tools are needed.
            # Phase 5: rec-int termination â€” during COMPRESS (rec==1) the field
            # is condensing, so do NOT expand the plan with new explorer steps.
            # (next_ready already defers non-critical steps during COMPRESS; this
            # stops adding NEW ones, integrating the recommendation into loop
            # termination.)
            # Session 366: make the continuation gate VISIBLE. It was one compound
            # condition, so a skipped consult left no trace at all - the same
            # silent-skip class that hid seven consumers for a session. Logging the
            # values lets "depth_route/done did not score" be told apart from "the
            # consult never ran".
            _cont_complete = queue.is_complete()
            _cont_mode_ok = queue.mode in (
                ExecutionMode.AGENTIC, ExecutionMode.FULL,
            )
            _cont_run = _cont_mode_ok and _cont_complete
            _cover_push = None
            logger.info(
                "[DER] continuation gate: mode=%s complete=%s -> %s",
                getattr(queue.mode, "value", queue.mode),
                _cont_complete, "RUN" if _cont_run else "SKIP",
            )
            # `rec == 1` (caducean COMPRESS) forbids growing the plan, so under
            # COMPRESS the consult can change nothing: a "not done" answer was
            # discarded and a "done" answer ends a queue that is already
            # complete. Owner 2026-10-01: skip its Brain call (13 of 18 consults
            # in one coding run were discarded; they ran only to give the paused
            # Oracle `done`/`depth_route` rows - Session 366's reason). Fold-back:
            # rec decides whether the consult runs, so it is read first.
            if _cont_run:
                _der_physics_settle(self, _session)
                try:
                    from backend.gateway.iris_ffi import ffi_caducean_recommend

                    _rec_now = ffi_caducean_recommend(_session)
                except Exception:
                    _rec_now = 2
                if _rec_now == 1:
                    _cont_run = False
                    logger.info(
                        "[DER] continuation consult skipped during COMPRESS "
                        "(rec=1) - the plan cannot expand"
                    )
                    # COMPRESS condenses the work done; it cannot end a task
                    # whose required fact nobody worked on. Eval r09
                    # (2026-10-04, conv-733): one search of three facts, then
                    # rec=1 skipped the consult and the reply missed two. The
                    # push for an open fact is fixed text - no consult needed.
                    _cover_push = AgentKernel._goal_contract_cover_step(self)
                    if _cover_push is not None:
                        _cont_run = True
            # The objective is MET: every required fact of the goal contract is
            # covered and none is blocked. The consult can only add steps that
            # chase the agent's own action lines as "ceiling facts" - live
            # 2026-10-02 run A5: C=1.000 at 23:56:37, then a consult + 2 added
            # steps + a bonus pass over "Opened Wikipedia homepage"-style facts,
            # 46 s before the same answer. No contract / open facts -> unchanged.
            if _cont_run and AgentKernel._goal_contract_met(self):
                _cont_run = False
                logger.info(
                    "[DER] continuation consult skipped - the goal contract is met "
                    "(all required facts covered)"
                )
            if _cont_run:
                _next_tool = _cover_push or self._der_plan_next_step(
                    plan.original_task,
                    completed_items,
                    queue.mode,
                    _turn_id,
                    step_outputs=step_outputs,
                )
                if _next_tool:
                    # GOAL ONLY: the continuation step carries no tool/params.
                    # _der_run_step_execution resolves it via the single resolver
                    # (explorer.propose) â€” F6 / System Invariant. We never take a
                    # tool from the Explorer's continuation dict.
                    # Session 312 (live conv-99): QueueItem was referenced here
                    # without an import â€” the one at the DER-loop function is a
                    # LOCAL binding, invisible here. Explorer escalation died
                    # with NameError at 18:05:09, exactly when result-aware
                    # steering was needed.
                    from backend.agent.der_loop import QueueItem
                    _next_item = QueueItem(
                        step_id=f"explorer_{len(completed_items) + 1}",
                        step_number=len(completed_items) + 1,
                        description=_next_tool.get("description", ""),
                        tool=None,
                        params={},
                        parallel_safe=False,
                        objective_anchor=plan.original_task,
                    )
                    queue.add_item(_next_item)
                    logger.info(
                        "[DER] Explorer added step %d: %s",
                        _next_item.step_number,
                        _next_item.description,
                    )
                    # Surface the newly-planned step to the frontend so the
                    # inline plan card shows the agent's live search/action
                    # steps as they are discovered â€” not just the upfront
                    # planner plan.  Frontend appends it to the to-do list.
                    # No session_id -> broadcast to all (single-user IRIS).
                    try:
                        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                        get_event_bus().emit(
                            IRISStreamEvent.TASK_PROGRESS,
                            data={
                                "add_step": True,
                                "step_id": _next_item.step_id,  # pin_517dfcbda150: unique id so split/sub-loop children each append
                                "step_number": _next_item.step_number,
                                "description": _next_item.description[:200],
                                "tool_name": _next_item.tool,
                                # REQ-3 AC6 (T2): card_id stays stable across
                                # every event of a card's lifetime.
                                **self._card_envelope(_turn_id),
                            },
                        )
                        # T4a (REQ-4 AC5): persist the step addition so a
                        # card interrupted mid-run restores with the
                        # explorer-discovered step included.
                        _add_step_envelope = self._card_envelope(_turn_id)
                        self._persist_card_snapshot(
                            card_id=_add_step_envelope.get("card_id"),
                            conversation_id=self.conversation_id,
                            card_relation="continues",
                            # save_card upserts the WHOLE row â€” plan_title/mode
                            # must be re-sent every write or a step-transition
                            # snapshot would null out what task:start set.
                            plan_title=self._effective_plan_title(plan),
                            mode=queue.mode.value if getattr(queue, "mode", None) else None,
                            steps=self._queue_steps_snapshot(queue),
                            total_steps=len(queue.items),
                            terminal_state="running",
                        )
                    except Exception:
                        pass  # never block the DER loop on an emit failure

            # The FULL-mode progress check (_der_check_full_progress) was
            # REMOVED 2026-10-01 (owner): one Brain call after every step from
            # step 3 on, and the caller ignored its answer (16 calls in one
            # coding run, 1 "drift", logged only).
        except Exception as _explorer_exc:
            logger.warning(
                "[DER] Explorer escalation failed: %s", _explorer_exc
            )
        # Session-318 T19 (AC5.6 defect fix): grade at completion on EVERY
        # terminal path â€” the continuation-done branch alone never runs on
        # queue-exhaustion ends (conv-102: zero grade lines). Deduped by turn.
        # Non-vacuous only: an EMPTY queue is trivially "complete" and must
        # never stamp a premature PASS mid-run (caught by BT-4).
        try:
            if queue.is_complete() and len(getattr(queue, "items", []) or []) > 0:
                self._der_report_run_grade(
                    completed_items, _turn_id, "finalize-complete"
                )
        except Exception:
            pass

        # â”€â”€ EventBus: emit der:step â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            get_event_bus().emit(
                IRISStreamEvent.DER_STEP,
                data={
                    "task_id": _turn_id or item.step_id,
                    "step_number": item.step_number,
                    "step_description": item.description[:200],
                    "tool": item.tool,
                    "success": step_success,
                    "total_steps": len(queue.items),
                    "completed": len(completed_items),
                    "mode": queue.mode.value,
                },
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
            )
        except Exception:
            pass

        # Surface step completion to the frontend plan card so the to-do
        # list checks the step off as it finishes.  Reuses the bridged
        # TASK_PROGRESS channel (no new event type needed).
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            get_event_bus().emit(
                IRISStreamEvent.TASK_PROGRESS,
                data={
                    "step_done": True,
                    # pin_517dfcbda150: carry the unique step id so the frontend
                    # can check off BOTH plan steps (ids like r1/step_1) and
                    # DER-discovered steps (der-N / explorer_N) â€” previously it
                    # only matched der-N, so plan steps never visually completed.
                    "step_id": item.step_id,
                    "step_number": item.step_number,
                    "description": item.description[:200],
                    "success": step_success,
                    # REQ-3 AC6 (T2): card_id stays stable across every
                    # event of a card's lifetime.
                    **self._card_envelope(_turn_id),
                },
            )
            # T4a (REQ-4 AC5): persist the step transition so a card
            # interrupted mid-run restores with current step statuses â€”
            # the whole point of AC5, since a crash never reaches task:done.
            _step_done_envelope = self._card_envelope(_turn_id)
            self._persist_card_snapshot(
                card_id=_step_done_envelope.get("card_id"),
                conversation_id=self.conversation_id,
                card_relation="continues",
                plan_title=self._effective_plan_title(plan),
                mode=queue.mode.value if getattr(queue, "mode", None) else None,
                steps=self._queue_steps_snapshot(queue),
                total_steps=len(queue.items),
                terminal_state="running",
            )
        except Exception:
            pass

        # â”€â”€ TRAILING DIRECTOR gap-fill REMOVED (2026-08-06) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # The gap-fill ran SEQUENTIALLY after the user's task: it was invoked
        # synchronously in _der_finalize_step and its gap items were queued
        # into the SAME turn, re-executing completed steps' work after the plan
        # finished (live turn 95cbe698-342: 5 planned steps then gap-s2-*
        # extended the turn; turn fc2a1a48-ddf looped unbounded on gap-on-gap).
        # It never ran in parallel with the task, so it only added latency and
        # unsolicited steps. Decision: remove the gap-fill entirely.
        # SESSION 364: the module itself is now DELETED
        # (backend/agent/trailing_director.py, with its dedicated tests) - it had
        # been unreachable since this decision and the attribute is gone from
        # __init__. Its two jobs are covered elsewhere or were already retired:
        # gap analysis lives in _goal_contract_open_facts() (the goal contract's
        # required-but-uncovered facts, which drives the run grade and the
        # finalize/partial-answer text), and the REQ-5 AC1 shallow-verified check
        # was dropped with it because it only fed gap analysis.

        # NOTE: the verify_failed -> split-into-sub-loops step (Phase 2 D2.1)
        # used to live here. It computed `_children`, which the REQ-8
        # task:learning emit and the REQ-7 physics-narration hook above both
        # read â€” but those reads ran *before* this block, every time, so
        # `_children` was always unbound at read time (UnboundLocalError,
        # silently swallowed). Moved up to right after `_verified` is known,
        # before its first reader. See the bugfix note there.

        return _tokens_used


    # â”€â”€ Phase 3: explorer methods â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€






    # â”€â”€ Goal contract Wave 3 (T7/T8/T9/T10) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Advisory helpers: every path degrades to legacy behavior when no
    # contract exists. Never raise, never block the turn.






    def _der_plan_next_step(
        self,
        task_objective: str,
        completed_items: List,
        mode: "ExecutionMode",
        turn_id: Optional[str] = None,
        step_outputs: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """
        After all planned steps are done, ask the LLM if more work is
        needed to satisfy the original objective.

        Returns a dict with 'description' (a GOAL) if more work is needed,
        or None if done. It MUST NOT return a 'tool'/'params' â€” tool
        selection is the single resolver's job (explorer.propose), fired
        when the continuation step executes (F6 / System Invariant). This
        is the key method for AGENTIC mode â€” it enables the multi-step tool
        loop without a hardcoded limit, while keeping one tool authority.
        """
        try:
            if not completed_items:
                return None

            from backend.agent.der_constants import ExecutionMode

            # Build a summary of what was done â€” T8 (specs/tool-result-envelope
            # REQ-2 AC2.2 / REQ-4 AC4.2): BOTH halves render envelope views
            # only. The old done_summary half appended the FULL raw i.result
            # for the last 10 steps (the conv-99 leak); it is now capped to
            # the envelope line exactly like the outputs block. Legacy edge
            # (no envelope): bounded excerpt, never raw.
            done_summary = "\n".join(
                f"  Step {i.step_number}: {i.description}"
                + (
                    f"\n    {i.envelope.line()}"
                    if getattr(i, "envelope", None) is not None
                    else (
                        # Legacy edge (pre-envelope item): bounded excerpt via
                        # the class static â€” fake/test kernels may not carry
                        # the instance method.
                        f"\n    OUTPUT: {AgentKernel._smart_excerpt(i.result, 400)}"
                        if i.result
                        else ""
                    )
                )
                for i in completed_items[-10:]
            )

            # Phase 3 (Gap 4): surface what each completed step actually
            # returned â€” now as ENVELOPE lines (status + wrapper + summary +
            # doc pointer), not bounded raw excerpts. Bounded by construction.
            _env_lines = [
                f"  [{i.step_number}] {i.envelope.line()}"
                for i in completed_items[-10:]
                if getattr(i, "envelope", None) is not None
            ]
            outputs_block = (
                "\n".join(_env_lines)
                if _env_lines
                else (
                    "\n".join(
                        f"  [{idx + 1}] {out[:600]}"
                        for idx, out in enumerate(step_outputs)
                    )
                    if step_outputs
                    else "  (none captured)"
                )
            )

            # REQ-8 AC8.2: visited ledger â€” pointers only, omit when empty.
            try:
                _visited_next = self._der_visited_block()
            except Exception:
                _visited_next = ""
            _visited_tail = f"{_visited_next}\n\n" if _visited_next else ""
            # Goal contract T6 (REQ-3 AC3.2/AC3.6): the deterministic gap
            # check rides with the replan hook. Open (uncovered, unblocked)
            # required facts go into the prompt so the planner sees them, and
            # an LLM "done" with open facts still requests work instead of
            # finalizing. Advisory â€” absent contract = legacy behavior.
            _gc_open: List[str] = []
            try:
                _gc_open = self._goal_contract_open_facts()
            except Exception:
                _gc_open = []
            _gc_open_block = ""
            if _gc_open:
                _gc_open_block = (
                    "OPEN REQUIRED FACTS (uncovered, unblocked â€” the turn "
                    "must not end while any remains and work is admissible):\n"
                    + "\n".join(f"  - {_f[:200]}" for _f in _gc_open[:8])
                    + "\n\n"
                )
            prompt = (
                "You are the Explorer. Your job is to decide if more work is needed.\n\n"
                f"OBJECTIVE: {task_objective}\n\n"
                f"{_gc_open_block}"
                f"STEPS COMPLETED ({len(completed_items)} total):\n{done_summary}\n\n"
                f"ACTUAL STEP OUTPUTS (what each completed step returned):\n"
                f"{outputs_block}\n\n"
                f"{_visited_tail}"
                f"Current mode: {mode.value if isinstance(mode, (str, ExecutionMode)) else 'agentic'}\n\n"
                "Is the objective fully met? If yes, respond with {\"done\": true}.\n"
                "If no, describe the SINGLE next goal to make progress (do NOT name a\n"
                'tool). Respond with:\n'
                '{"done": false, "description": "what goal to pursue next"}\n'
                "Be specific about the outcome the next step should achieve.\n\n"
                "Respond with JSON only."
            )

            response = self.infer(
                prompt, role="reasoning", max_tokens=400, temperature=0.1
            )
            raw = response.raw_text or ""

            # Parse JSON from response
            import json as _json

            m = re.search(r"\{[\s\S]+\}", raw)
            if not m:
                # FALLBACK EXTRACTION (2026-09-27). This used to end the turn
                # here, silently, and that one line had two faults:
                #  1. `return None` is the SAME value the caller gets for "no
                #     next step wanted", so a prose reply silently ENDED the task
                #     with no way to tell the two apart.
                #  2. It skips the `done` shadow consult below entirely â€” no row,
                #     no log line, a consumer that looks unwired.
                # Recover the done-bit from the common non-JSON shapes first. A
                # recovered bit keeps the row PAIRABLE (an unpaired row carries
                # brain_bool=None and is not scorable), which is worth more than
                # merely recording a row.
                _bit_m = re.search(
                    r'"done"\s*:\s*(true|false)', raw, re.IGNORECASE
                ) or re.search(
                    r"^\s*(true|false|yes|no)\s*$", raw,
                    re.IGNORECASE | re.MULTILINE,
                )
                if not _bit_m:
                    logger.warning(
                        "[DER] _der_plan_next_step: planner reply had no JSON and "
                        "no recoverable done-bit â€” returning None (which is "
                        "indistinguishable from 'no next step') and SKIPPING the "
                        "`done` shadow consult. raw[:120]=%r",
                        raw[:120],
                    )
                    return None
                data = {"done": _bit_m.group(1).lower() in ("true", "yes")}
            else:
                data = _json.loads(m.group())
            # REQ-14 AC14.1 (T18): shadow-score the `done` consumer and emit
            # the row. The Brain's bit still decides â€” the goal-contract
            # override below is PRESERVED (AC14.1) â€” and the engine only ever
            # supplies the bool, never the next-goal text (AC14.2).
            try:
                from backend.agent import monitor_shadow as _ms
                from backend.agent.decision_engine import decides, oracle_acts

                _done_dec = decides("done") is not None
                # 3-TUPLE, not 2 (2026-09-27). monitor_bool returns
                # (value, text, shadow_row). Unpacking two names raised
                #   ValueError: too many values to unpack (expected 2, got 3)
                # BEFORE emit_row below, so the `done` row was never written -
                # silently, because this block used to end in a bare `pass`.
                # That one character is why the consumer read "0 rows" all
                # session and looked unwired. Caught the moment the bare `pass`
                # became a logged warning.
                _done_value, _done_text, _done_row = _ms.monitor_bool(
                    "done", _monitor_statement(task_objective, completed_items),
                    # v3 (2026-11-06): the instruction moved from "Is the
                    # objective complete?" to one that names what complete means
                    # ("every required fact covered... nothing required is still
                    # missing"). MEASURED on the 63 distinct parity rows: the same
                    # 61.9% agreement with the Brain's done-bit at AUROC 0.7019
                    # against 0.6549 - a strict improvement, no trade-off. A
                    # question change is a new calibrated identity, so the stamp
                    # moves and the v2 cohort is never blended in.
                    # v4 (2026-11-10): the declared question reaches the
                    # model for the first time (monitor registrar fix); the
                    # v3 rows were asked the generic AUTO_INSTRUCTION.
                    criteria_version="done/v4",
                    brain_bool_fn=lambda: data.get("done") is True,
                    brain_text_fn=lambda: str(data.get("description", "") or ""),
                    engine=_ms.AUTO_ENGINE,
                    # shadow score off the reply path (4.3 s at turn end,
                    # eval c04 2026-10-01); the row is emitted from the lane.
                    # Stage B: deferral applies only while `done` does not
                    # decide (monitor_bool ignores defer once enforced) - a
                    # deciding consumer must be waited for.
                    defer=True,
                    enforced=_done_dec,
                    acts=lambda c: oracle_acts("done", c),
                )
                _ms.emit_row(_done_row)
                if _done_dec:
                    # The value is the final decision (the Oracle's when it was
                    # confident, else the Brain's own bit): make it the one the
                    # loop reads below. The Brain's next-goal text stays.
                    data["done"] = bool(_done_value)
            except Exception as _mon_err:  # noqa: BLE001 â€” advisory observer
                # VISIBLE, but still ADVISORY (2026-09-27). This was a bare
                # `pass`, so a failing monitor consult lost its calibration row
                # in total silence â€” the exact class of silence that made seven
                # consumers look unwired for a whole session. A skipped consumer
                # must leave a trace. Warning, not debug: losing a row is a real
                # calibration event, and the observed failure mode was NO row
                # with NO log line at all.
                logger.warning(
                    "[monitor] done shadow consult failed (row NOT recorded): %r",
                    _mon_err,
                )
            if data.get("done") is True:
                # Goal contract T6 (REQ-3 AC3.6): the turn SHALL NOT end while
                # a required fact is open and unblocked â€” request work on the
                # first open fact instead of honoring the LLM's done.
                _gc_push = AgentKernel._goal_contract_cover_step(self)
                if _gc_push is not None:
                    return _gc_push
                # REQ-3 AC3.5: C reached 1.0 â€” permit ONE bounded bonus pass
                # over ceiling facts, then terminate (helper owns the
                # counter so every increment has exactly one writer).
                try:
                    _gc_bonus = self._goal_contract_bonus_pass()
                except Exception:
                    _gc_bonus = None
                if _gc_bonus is not None:
                    return _gc_bonus
                # AC5.6: done+GRADE via the shared helper (deduped by turn â€”
                # the finalize-complete site may have reported first, T19).
                try:
                    self._der_report_run_grade(
                        completed_items, turn_id, "continuation-done"
                    )
                except Exception:
                    pass
                return None

            _desc = data.get("description")
            if not _desc or not str(_desc).strip():
                # Not done, but the Brain named no next step, so the loop STOPS.
                return None

            # GOAL ONLY â€” no tool/params. The resolver picks the tool on exec.
            return {"description": str(_desc).strip()}

        except Exception as exc:
            logger.warning(
                "[DER] _der_plan_next_step failed: %s", exc
            )
            return None



    def get_status(self) -> Dict[str, Any]:
        """
        Get agent status information.

        Returns:
            Status dictionary with:
            - ready: bool - if agent is ready to process requests
            - models_loaded: int - number of loaded models
            - total_models: int - total number of models
            - tool_bridge_available: bool - if tool bridge is available
            - model_status: dict - individual model status
            - single_model_mode: bool - if in fallback mode
            - error: str - initialization error if any
            - vps_gateway: dict - VPS Gateway status (enabled, available endpoints, health)
        """
        status = {
            "ready": False,
            "models_loaded": 0,
            "total_models": 0,
            "tool_bridge_available": False,
            "model_status": {},
            "single_model_mode": self._single_model_mode,
            "error": self._initialization_error,
        }

        # Check model router status
        if self._model_router:
            all_status = self._model_router.get_all_models_status()
            status["model_status"] = all_status
            status["total_models"] = len(all_status)
            status["models_loaded"] = len(self._model_router.get_loaded_models())

            # Agent is ready if at least one model is available
            reasoning_model = self._model_router.get_reasoning_model()
            execution_model = self._model_router.get_execution_model()
            status["ready"] = reasoning_model is not None or execution_model is not None

        # Check tool bridge status
        if self._tool_bridge:
            try:
                bridge_status = self._tool_bridge.get_status()
                status["tool_bridge_available"] = bridge_status.get("available", False)
            except Exception as e:
                logger.warning(f"[AgentKernel] Failed to get tool bridge status: {e}")

        # Add VPS Gateway status
        if self._vps_gateway:
            try:
                vps_status = self._vps_gateway.get_status()
                status["vps_gateway"] = vps_status
                logger.debug(f"[AgentKernel] VPS Gateway status: {vps_status}")
            except Exception as e:
                logger.warning(f"[AgentKernel] Failed to get VPS Gateway status: {e}")
                status["vps_gateway"] = {"enabled": False, "error": str(e)}
        else:
            status["vps_gateway"] = {"enabled": False, "available_endpoints": 0}

        return status

    # NOTE (session 247): a second, arg-less `clear_conversation` used to be
    # defined HERE and silently SHADOWED the real one near the top of this
    # class (line ~590). Python class bodies keep the LAST def, so every
    # `clear_conversation(conversation_id)` call from iris_gateway raised
    # "takes 1 positional argument but 2 were given" â€” logged as
    # "[Chat] Failed to clear previous conversation ..." on every new-thread
    # switch, meaning the previous thread's kernel context was never cleared
    # and could leak into the new thread. The duplicate is removed; the real
    # definition handles both call shapes (conversation_id optional, defaulting
    # to the kernel's current thread).

    def get_conversation_context(
        self, max_messages: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get conversation context.

        Args:
            max_messages: Optional limit on number of messages

        Returns:
            List of message dictionaries
        """
        if self._conversation_memory:
            return self._conversation_memory.get_context(max_messages=max_messages)
        return []

    def update_personality(self, config: Dict[str, Any]) -> None:
        """
        Update personality configuration.

        Args:
            config: Dictionary containing identity fields
        """
        if self._personality:
            self._personality.load_from_config(config)
            logger.info("[AgentKernel] Personality configuration updated")

    # Maps legacy/local model names to their canonical VPS/API identifiers.
    # This allows saved settings that used local model path names to resolve
    # correctly against VPS available-model IDs without requiring a migration.
    _MODEL_ALIASES: Dict[str, str] = {
        # Legacy local model directory name â†’ canonical ID (executor only; brain removed)
        "LFM2.5-1.2B-Instruct": "lfm2.5-1.2b-instruct",
        "executor": "lfm2.5-1.2b-instruct",
        # NOTE: LFM2-8B-A1B / "brain" / "lfm2-8b" aliases are intentionally absent.
        # That model is not in use â€” removing the aliases prevents accidental routing.
    }





    def set_internet_access(self, enabled: bool) -> None:
        """
        Enable or disable agent internet access.

        Delegates to the app-wide global flag (set_global_internet_access) so that
        internet access is a single switch for all conversations, not per-kernel.
        The UI web-mode toggle flips this via iris_gateway.set_web_mode.

        Args:
            enabled: True to enable internet access, False to disable
        """
        set_global_internet_access(enabled)

    def get_internet_access(self) -> bool:
        """
        Get current internet access setting (app-wide global).

        Returns:
            True if internet access is enabled, False otherwise
        """
        return get_global_internet_access()

    def set_swarm_enabled(self, enabled: bool) -> None:
        """
        Enable or disable multi-agent swarm compound collaboration.
        Initialises SwarmCoordinator and ContextControlHandler lazily on first enable.
        """
        self._swarm_enabled = enabled
        if (
            enabled
            and self._memory_interface is not None
            and self._swarm_coordinator is None
        ):
            try:
                from backend.agent.swarm import SwarmCoordinator, ContextControlHandler
                from backend.agent.mcm import MCM

                _mcm = MCM(self._memory_interface, self.session_id)
                _protocol = self._mcm_orch._protocol if self._mcm_orch else None
                self._swarm_coordinator = SwarmCoordinator(
                    memory_interface=self._memory_interface,
                    session_id=self.session_id,
                    agent_id=self.session_id,
                    protocol=_protocol,
                )
                self._context_control_handler = ContextControlHandler(
                    memory_interface=self._memory_interface,
                    mcm_instance=_mcm,
                    session_id=self.session_id,
                )
                logger.info(
                    "[AgentKernel] SwarmCoordinator + ContextControlHandler initialized"
                )
            except Exception as _swarm_err:
                logger.warning("[AgentKernel] Swarm init failed: %s", _swarm_err)
        logger.info("[AgentKernel] Swarm %s", "enabled" if enabled else "disabled")

    def get_swarm_enabled(self) -> bool:
        """Return current swarm enabled state."""
        return self._swarm_enabled

    def _handle_control_codes(self, response_text: str, messages: list) -> list:
        """
        Scan response for MCM: control codes (MCM:999/998/997/996) and execute.
        Called after every agent response when swarm is enabled.
        Never raises. Returns messages (potentially modified by MCM:999 prune).
        """
        if not self._swarm_enabled or self._context_control_handler is None:
            return messages
        try:
            self._context_control_handler.scan_and_execute(
                response_text,
                messages,
                self._current_task if hasattr(self, "_current_task") else "",
            )
        except Exception:
            pass
        return messages


# Singleton instance management
_agent_kernel_instances: Dict[str, AgentKernel] = {}

# â”€â”€ Global internet-access gate (app-wide) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Web mode is a single app-level switch, not per-conversation.  Kernels are
# created per conversation (_agent_kernel_instances), but internet access must
# apply to every kernel at once when the user toggles web mode in the UI.
# set_web_mode in iris_gateway flips this; tool_bridge gates web tools on it.
_internet_access_enabled: bool = False


def set_global_internet_access(enabled: bool) -> None:
    """Flip the app-wide internet-access gate (UI web-mode toggle)."""
    global _internet_access_enabled
    _internet_access_enabled = bool(enabled)
    logger.info(
        f"[AgentKernel] Global internet access {'enabled' if enabled else 'disabled'}"
    )


def get_global_internet_access() -> bool:
    """Return the app-wide internet-access gate state."""
    return _internet_access_enabled


# â”€â”€ Global desktop-control gate (app-wide) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Desktop control = launching the user's real browser/apps, opening files with
# their default application, locking the screen, GUI/screen automation, etc.
# Everything that reaches OUTSIDE the app sandbox.  It is OFF by default and
# only enabled when the user explicitly grants permission via the
# desktop_control dashboard card (confirm_card â†’ set_desktop_control_enabled).
# tool_bridge gates every desktop-control tool on this flag so the agent can
# NEVER reach the desktop unless the user opted in.
_desktop_control_enabled: bool = False


def set_desktop_control_enabled(enabled: bool) -> None:
    """Flip the app-wide desktop-control gate (UI desktop_control card)."""
    global _desktop_control_enabled
    _desktop_control_enabled = bool(enabled)
    logger.info(
        f"[AgentKernel] Desktop control {'enabled' if enabled else 'disabled'}"
    )


def get_desktop_control_enabled() -> bool:
    """Return the app-wide desktop-control gate state."""
    return _desktop_control_enabled


# Last-known-good swarm configuration snapshot.
# When a new session's kernel is created after swarm mode has already been
# configured, it reads from this snapshot instead of relying on peer
# inheritance (which fails if all peers were also created post-swarm).
_swarm_config_snapshot: Optional[dict] = None

# REMOVED 2026-08-16: `_model_config_snapshot`. It was a module-global copy of
# the persisted model config, stashed at startup so lazily-created kernels could
# hydrate from it. It is gone because the thing it hydrated is gone: kernels now
# read the process-wide role-binding table, which already holds the live choice.
#
# It was also the third of the five competing sources of truth for "which model
# is active", and the one that made the others hard to reason about â€” it was
# written by set_model_selection under one key spelling ("tool_execution_model")
# and read under another ("tool_model"), and its reader had been raising
# TypeError on every call since the day set_model_selection's signature changed.
# Startup seeding now happens once, in InferenceRouter._apply_config.


def get_agent_kernel(
    conversation_id: str = "default",
    session_id: Optional[str] = None,
) -> AgentKernel:
    """
    Get or create an AgentKernel instance for a conversation.
    Auto-wires the memory interface (Pillar 4) when a new kernel is created.

    Re-keyed from session_id to conversation_id for multi-thread context.
    session_id is preserved for WS routing and Mycelium ingestion.

    Args:
        conversation_id: Primary key â€” one kernel per conversation thread.
        session_id: Transport label for WS routing and Mycelium.
                    If None, falls back to conversation_id.

    Returns:
        AgentKernel instance for the conversation
    """
    global _agent_kernel_instances

    _sid = session_id or conversation_id

    if conversation_id not in _agent_kernel_instances:
        # DIAGNOSTIC: kernels are cached BY conversation_id, so a conversation
        # id that drifts mid-turn silently constructs a SECOND kernel and
        # orphans the first one's in-turn state (tokens, node records, DER
        # bookkeeping). That was observed live: a fresh kernel for conv-1 was
        # initialised AFTER turn 1 had already completed, while the turn itself
        # ran under session_iris. Log every construction with BOTH ids and the
        # existing keys so a mid-turn rebuild is visible instead of inferred.
        # Note some keys are pseudo-conversations by design (crawl_planner,
        # data_extractor, default) â€” those are expected; a real thread id
        # appearing twice, or appearing late, is not.
        logger.info(
            "[AgentKernel] CONSTRUCTING kernel conv=%r session=%r "
            "(existing keys: %s)",
            conversation_id,
            _sid,
            sorted(_agent_kernel_instances.keys()),
        )
        kernel = AgentKernel(
            session_id=_sid,
            conversation_id=conversation_id,
        )

        # Auto-wire Pillar 4 (Memory) â€” connects episodic/semantic memory to every session
        try:
            from backend.memory import get_memory_interface

            memory = get_memory_interface()
            if memory is not None:
                kernel.set_memory_interface(memory)
                logger.info(
                    f"[AgentKernel] Memory interface wired for conv={conversation_id}"
                )
        except Exception as e:
            logger.warning(
                f"[AgentKernel] Memory interface not available for conv={conversation_id}: {e}"
            )

        # Inherit inference BEHAVIOUR settings from any already-configured peer.
        #
        # Context: the user configures things once (in session_iris / the main UI
        # session).  Secondary sessions â€” such as session_iris_integration which is
        # created when the wake-word fires â€” are spun up lazily.  Without this,
        # a wake-word-triggered response ran with default behaviour settings.
        #
        # WHICH MODEL SERVES WHICH ROLE IS NOT COPIED HERE (2026-08-16). It used
        # to be: this block called ``set_model_selection(model_provider=peer.
        # _model_provider, ...)`` without ``preserve_bindings``, which fell
        # through to ``bind_role`` and REBOUND the process-wide role table from
        # the peer's LEGACY fields. Those fields are not updated by the gateway's
        # role-binding path, so they held the startup provider â€” and every new
        # conversation therefore reverted the user's live pick (the recurring
        # "picked cohere, sent a message, back to cerebras" bug).
        #
        # There is nothing to copy: the role table and the provider registry are
        # process-wide singletons (REQ-5), so this kernel's router already sees
        # the user's live choice the moment it is constructed. Model/provider
        # state is READ from the router (see the ``_model_provider`` /
        # ``_selected_*_model`` properties), never stored per kernel.
        #
        # Credentials likewise live on the ProviderInstance in the shared
        # registry; ``_api_key`` / ``_api_base_url`` are copied only as a
        # compatibility convenience for the remaining direct readers.
        for peer_key, peer_kernel in _agent_kernel_instances.items():
            if peer_kernel is kernel:
                continue
            if peer_kernel._model_provider in (None, "uninitialized"):
                continue
            kernel._lmstudio_endpoint = peer_kernel._lmstudio_endpoint
            if peer_kernel._api_key:
                kernel._api_key = peer_kernel._api_key
                kernel._api_key_provider = peer_kernel._api_key_provider
            if peer_kernel._api_base_url:
                kernel._api_base_url = peer_kernel._api_base_url
            kernel._thinking_style = peer_kernel._thinking_style
            kernel._response_length = peer_kernel._response_length
            kernel._reasoning_effort = peer_kernel._reasoning_effort
            kernel._tool_mode = peer_kernel._tool_mode
            logger.info(
                f"[AgentKernel] Conv '{conversation_id}' inherited inference "
                f"behaviour from '{peer_key}' "
                f"(active model comes from the shared router: "
                f"provider={kernel._model_provider!r}, "
                f"model={kernel._selected_reasoning_model!r})"
            )
            break

        if kernel._model_provider == "uninitialized":
            # If no role is bound yet and a global swarm snapshot exists,
            # auto-hydrate this kernel so it doesn't stay "uninitialized".
            if _swarm_config_snapshot is not None:
                # SLICE 5: wire the router (not the legacy compat client) so
                # DER/Pacman inference paths actually use the swarm endpoint.
                try:
                    from backend.agent.inference.provider import (
                        ProviderInstance,
                        ProviderKind,
                    )

                    _ep = _swarm_config_snapshot.get("endpoint") or ""
                    _r_model = _swarm_config_snapshot.get("reasoning_model")
                    _t_model = _swarm_config_snapshot.get("tool_model")
                    _inst = ProviderInstance(
                        id="swarm_director",
                        label="Swarm (auto-hydrated)",
                        kind=ProviderKind.LOCAL_OPENAI,
                        model=_r_model or "local-model",
                        api_base_url=_ep,
                    )
                    _router = getattr(kernel, "_router", None)
                    if _router is not None:
                        _router.add_provider(_inst)
                        _router.bind_role("reasoning", "swarm_director")
                        _router.bind_role(
                            "tool_execution", "swarm_director", model_override=_t_model
                        )
                except Exception as _sw_err:
                    logger.warning(
                        f"[AgentKernel] Swarm auto-hydrate router wire failed: {_sw_err}"
                    )
                kernel._swarm_enabled = True
                logger.info(
                    f"[AgentKernel] Conv '{conversation_id}' auto-hydrated from "
                    f"swarm snapshot (provider='iris_local', "
                    f"endpoint={_swarm_config_snapshot.get('endpoint')!r})"
                )

            # NOTE (2026-08-16): a "persisted model config snapshot" hydrate
            # used to live here, replaying `_model_config_snapshot` through
            # set_model_selection. It was removed for two reasons. First, it
            # had never run: it passed `provider=`, `thinking_style=`,
            # `response_length=` and `tool_mode=`, none of which are parameters
            # of set_model_selection, so every call raised TypeError straight
            # into the handler below it and logged "model snapshot hydrate
            # failed". Second, even working it would have been wrong â€” it
            # replayed a STORED copy of the user's choice over the live
            # process-wide role table, which is the same class of bug as the
            # peer-inheritance rebind above. Startup seeding belongs in
            # InferenceRouter._apply_config, which now binds only unbound roles.

        _agent_kernel_instances[conversation_id] = kernel

    return _agent_kernel_instances[conversation_id]


# â”€â”€ Session â†’ active conversation registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Wave 5 (session-conversation-switching spec): eliminates the phantom
# "default" kernel.  Callers that only knew a session_id (e.g. a wake-word
# voice path, a reconnect, a REST chat request) were calling
# get_agent_kernel(session_id=...) which fell back to conversation_id="default",
# creating a kernel the active thread never used.  The gateway owns the
# authoritative sessionâ†’active-conversation binding (_active_conversation_id);
# it mirrors that binding here (module-level, no circular import) so any
# caller can resolve the *real* active kernel for a session via
# get_active_kernel(session_id) instead of spawning a "default" ghost.
_session_active_conversation: dict = {}


def set_active_conversation(
    session_id: str, conversation_id: Optional[str]
) -> None:
    """Mirror the gateway's sessionâ†’active-conversation binding into this
    module-level registry.  Called by the gateway whenever it (re)points a
    session at a conversation (new_conversation / switch_conversation /
    sync_state / voice_command_start / connect).

    ``conversation_id=None`` UNBINDS the session â€” the state "the user left a
    thread and has not started the next one yet".  Leaving a stale binding in
    place is what let a wake word or a reconnect resolve back into the thread
    the user had just walked away from, so the absence of a thread has to be
    representable, not approximated by the session id."""
    global _session_active_conversation
    if not session_id:
        return
    if conversation_id:
        _session_active_conversation[session_id] = conversation_id
    else:
        _session_active_conversation.pop(session_id, None)


def get_active_kernel(session_id: str) -> "AgentKernel":
    """Resolve the kernel for a session's *currently active* conversation.

    Falls back to conversation_id="default" only when no active conversation
    has been registered for the session (e.g. a brand-new session before the
    first new_conversation / sync_state).  This is the correct replacement for
    the old get_agent_kernel(session_id=...) pattern that silently created a
    phantom "default" kernel disconnected from the active thread.
    """
    conv_id = _session_active_conversation.get(session_id) or "default"
    return get_agent_kernel(conversation_id=conv_id, session_id=session_id)


def peek_active_kernel(session_id: str) -> "Optional[AgentKernel]":
    """Non-constructing variant of ``get_active_kernel``: return the kernel
    for a session's currently active conversation IF one already exists,
    else ``None``.

    Never constructs a kernel.  ``get_agent_kernel`` builds a full
    ``AgentKernel`` when absent (measured 71.81s cold on 2026-08-12), which
    made read-only paths (``/api/inference/state``, ``request_state``) time
    out on page loads racing backend startup.  Callers that only read router
    state (inference snapshot, status broadcast) MUST use this instead so a
    read can never pay kernel-construction cost.  ``build_inference_snapshot``
    already accepts ``None`` and returns the full key set with empty
    providers, so a missing kernel degrades gracefully, never errors.
    """
    conv_id = _session_active_conversation.get(session_id) or "default"
    return _agent_kernel_instances.get(conv_id)


def cleanup_agent_kernel(
    conversation_id: str,
    session_id: Optional[str] = None,
) -> None:
    """
    Remove the AgentKernel instance for a conversation and release its resources.

    Call this when a conversation expires or is deleted.
    Keyed by conversation_id (re-keyed from session_id).

    Args:
        conversation_id: Conversation whose kernel should be cleaned up
        session_id: Optional session label for logging
    """
    global _agent_kernel_instances
    kernel = _agent_kernel_instances.pop(conversation_id, None)
    _log_id = session_id or conversation_id
    if kernel is not None:
        try:
            # Save any pending context to the store
            try:
                kernel.save_context_to_store()
            except Exception:
                pass
            # Shut down VPS Gateway if it was active
            if kernel._vps_gateway is not None:
                import asyncio

                try:
                    # Prefer the already-running loop (cleanup called from async context).
                    # Fall back to a fresh asyncio.run() if called from a sync context.
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(kernel.shutdown_vps_gateway())
                    except RuntimeError:
                        asyncio.run(kernel.shutdown_vps_gateway())
                except Exception:
                    pass
        except Exception as e:
            logger.warning(
                f"[AgentKernel] Error during cleanup for conv {_log_id}: {e}"
            )
        logger.info(f"[AgentKernel] Kernel cleaned up for conv {_log_id}")










# <kernel-split:propagate> generated by scripts/kernel_split_check.py move; do not edit by hand
# RES-7: an assignment to one of these module attributes (mock.patch, monkeypatch.setattr,
# plain `agent_kernel.X = v`) is forwarded to every kernel module that binds the name.
# A `global X; X = v` store inside this file does NOT pass through __setattr__.
import sys as _sys
import types as _types
_PROPAGATE = {
    'backend.agent.kernel.base': ('AgentKernel', '_emit_event', 'debit_work_units', ),
    'backend.agent.kernel.context': ('TurnMetrics', ),
    'backend.agent.kernel.der.node': ('AgentKernel', ),
    'backend.agent.kernel.der.physics': ('TurnMetrics', '_emit_event', ),
    'backend.agent.kernel.der.recovery': ('AgentKernel', '_emit_event', '_remember_turn_urls', 'debit_work_units', ),
    'backend.agent.kernel.der.report': ('AgentKernel', ),
    'backend.agent.kernel.models': ('_agent_kernel_instances', ),
    'backend.agent.kernel.planning': ('AgentKernel', ),
    'backend.agent.kernel.surface': ('AgentKernel', '_emit_event', ),
    'backend.agent.kernel.turn': ('AgentKernel', 'TurnMetrics', 'get_global_internet_access', ),
}


class _KernelModule(_types.ModuleType):
    def __setattr__(self, name, value):
        _types.ModuleType.__setattr__(self, name, value)
        for _mod_name, _names in _PROPAGATE.items():
            if name in _names:
                _target = _sys.modules.get(_mod_name)
                if _target is not None:
                    setattr(_target, name, value)


_sys.modules[__name__].__class__ = _KernelModule
for _mod_name, _names in _PROPAGATE.items():
    for _name in _names:
        setattr(_sys.modules[_mod_name], _name, globals()[_name])
# </kernel-split:propagate>
