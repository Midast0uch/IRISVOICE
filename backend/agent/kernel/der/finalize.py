# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

import re
from backend.agent.mcm_protocol.actions.pacman_fragment import is_external_tool
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
    DER_FOLD_BACK_MAX,
    ExecutionMode,
    _der_fold_envelope,
    _der_ledger_storage_path,
    _der_recall_delivered,
    _memory_events_submit,
    _step_calls,
    _step_decisive_call,
    _step_evidence_cap,
    _step_tool,
    debit_work_units,
    logger,
)
from backend.agent.kernel.der.physics import (
    _der_physics_settle,
    _der_settle_split,
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

def _der_prior_research_delivered(owner, item, step_result, session_id: str) -> None:
    """A PRIOR RESEARCH section at the head of a tool result IS memory delivered to the
    step that ran the tool (research_memory.attach_prior put it there)."""
    try:
        from backend.agent.research_memory import PRIOR_HEADING

        if PRIOR_HEADING in str(step_result or ""):
            _der_recall_delivered(owner, item, "prior_research", [], session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[memory_events] prior research delivery not typed: %s", exc)

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


class DerFinalizeMixin:
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
