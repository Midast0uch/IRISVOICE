# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

from backend.agent.kernel.der.finalize import (
    _remember_turn_urls,
)
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import json
import time
from backend.agent.kernel.base import (
    DER_MAX_GRAFTS,
    _der_ledger_storage_path,
    _der_recovery_lock,
    _emit_event,
    _step_calls,
    _step_decisive_call,
    _step_tool,
    debit_work_units,
    logger,
)
from backend.agent.kernel.der.physics import (
    _der_physics_settle,
)


def _plan_steps_open(plan, queue) -> int:
    """How many steps of the ORIGINAL plan are still in the queue and not yet
    settled (pending or running). A steering re-plan removes the steps it
    replaces, so they stop counting. Module level: stand-in kernels."""
    ids = {getattr(s, "step_id", None) for s in (getattr(plan, "steps", None) or [])}
    ids.discard(None)
    if not ids:
        return 0
    settled = set(queue.completed_ids) | set(queue.vetoed_ids) | set(queue.failed_ids)
    present = {getattr(it, "step_id", None) for it in (getattr(queue, "items", None) or [])}
    return len((ids & present) - settled)

def _recovery_candidates(step_result, env_sources, visited):
    """Session-319: shared candidate extraction for the recovery lane.

    Returns ``(dead, hosts, cands)``:

      ``dead``  â€” addresses the step attempted but did not fetch successfully
      ``hosts`` â€” the distinct hosts those dead addresses belong to
      ``cands`` â€” unvisited, same-host recovery targets: the page's outlinks
                  plus the parent directory of each dead address

    PURE: no state, no side effects, no I/O. Extracted deliberately so the
    bespoke lane and the router-driven producer compute the SAME candidate set
    while they converge into one lane. Two copies of this logic would drift, and
    a drift here means one lane recovers pages the other thinks are already done.

    Returns empty values when nothing is recoverable â€” callers must treat that as
    "no recovery", never as an error.
    """
    import re as _re_c
    from urllib.parse import urlparse as _up
    _attempted = []
    for _tail in _re_c.findall(
        r"---\s*Attempted:\s*([^\n]+)", str(step_result or "")
    ):
        for _u in _tail.split():
            _u = _u.strip().rstrip(".,;)]")
            if _u.startswith("http") and _u not in _attempted:
                _attempted.append(_u)
    _fetched = set(env_sources or [])
    _dead = [u for u in _attempted if u not in _fetched]
    if not _dead:
        return [], set(), []
    _outlinks = []
    _m = _re_c.search(
        r"--- Outlinks[^\n]*\n((?:  - [^\n]+\n?)*)", str(step_result or "")
    )
    if _m:
        for _ln in _m.group(1).splitlines():
            _ln = _ln.strip()
            if _ln.startswith("- "):
                _u = _ln[2:].strip()
                if _u.startswith("http") and _u not in _outlinks:
                    _outlinks.append(_u)
    _hosts = set()
    for _d in _dead:
        try:
            _hosts.add(_up(_d).hostname or "")
        except Exception:
            continue
    _hosts.discard("")
    if not _hosts:
        return _dead, set(), []
    _visited = set(visited or [])
    _cands = []
    for _u in _outlinks:
        try:
            _h = _up(_u).hostname or ""
        except Exception:
            continue
        if (_h in _hosts and _u not in _visited
                and _u not in _attempted and _u not in _cands):
            _cands.append(_u)
    for _d in _dead:
        try:
            _p = _up(_d)
            if not _p.netloc:
                continue
            _segs = (_p.path or "/").rstrip("/").rsplit("/", 1)
            _pdir = (_segs[0] or "/") if len(_segs) > 1 else "/"
            _parent = f"{_p.scheme}://{_p.netloc}{_pdir}"
            if (_parent not in _visited and _parent not in _attempted
                    and _parent not in _cands and _parent != _d):
                _cands.append(_parent)
        except Exception:
            continue
    return _dead, _hosts, _cands


class DerRecoveryMixin:
    def _der_maybe_open_recovery(self, item, step_result, completed_items, queue):
        """Session-318 T16 (REQ-9 AC9.5): open a VLM in-site recovery step
        when a gather step's fetch died but unvisited same-site candidates
        exist. Returns a QueueItem or None. Rules: parent must carry an
        envelope with ZERO stamped sources (nothing usable came back);
        parent must not itself be a recovery (no chains); one recovery per
        dead host per turn; candidates = same-host outlinks + parent-dir of
        dead URLs, minus visited and minus dead, capped by
        RECOVERY_PAGE_BUDGET. Never raises."""
        try:
            from backend.agent.tool_envelope import tool_family
            from backend.agent.der_loop import QueueItem
            try:
                from backend.agent.der_constants import RECOVERY_PAGE_BUDGET
                _budget = max(int(RECOVERY_PAGE_BUDGET), 1)
            except Exception:
                _budget = 5
            if getattr(item, "recovery_of", ""):
                return None  # no chains
            if tool_family(getattr(item, "tool", None)) != "gather":
                return None
            _env = getattr(item, "envelope", None)
            if _env is None or list(getattr(_env, "sources", []) or []):
                return None  # something usable came back â€” no recovery
            _conv = self.conversation_id or ""
            _visited = set(
                getattr(self, "_der_crawled_urls", {}).get(_conv, set())
            )
            # Session-319: candidate extraction is now SHARED with the
            # router-driven producer (_recovery_candidates), so the two lanes
            # cannot drift apart while they converge into one.
            #
            # Do NOT claim the per-host budget here: the claim is made ATOMICALLY
            # below, after candidates are computed, so a concurrent step cannot
            # also pass this check. Claiming early and then returning None (no
            # candidates) would wrongly burn the host's one recovery for the turn.
            _dead, _hosts, _cands = _recovery_candidates(
                step_result, getattr(_env, "sources", []), _visited
            )
            if not _dead or not _hosts:
                return None
            _cands = _cands[:_budget]
            if not _cands:
                return None
            # Session-319: ATOMIC check-and-claim of the per-host-per-turn
            # budget. The old code read this ledger near the top of this method
            # and wrote it here, with no lock in between â€” so under concurrent
            # parallel_safe steps two of them could both see "not yet opened"
            # and each enqueue a recovery for the SAME host. Owner decision
            # (session-319): ONE CREW PER BUILDING. The claim happens only now,
            # when we know an item will be returned, so a no-candidate path
            # never burns the host's recovery for the turn.
            try:
                with _der_recovery_lock:
                    _ro = dict(getattr(self, "_der_recovery_opened", {}))
                    _opened = set(_ro.get(_conv, set()))
                    _claim = {h for h in _hosts if h not in _opened}
                    if not _claim:
                        # Another step claimed every host first â€” this step must
                        # not open a second crew for the same building.
                        return None
                    _ro[_conv] = _opened | _claim
                    self._der_recovery_opened = _ro
                    _hosts = _claim
            except Exception:
                pass
            _host0 = sorted(_hosts)[0]
            _rec = QueueItem(
                step_id=f"recovery_{getattr(item, 'step_id', 's')}",
                step_number=len(completed_items or []) + 1,
                description=(
                    f"Recover dead fetch from {_host0}: crawl "
                    f"{len(_cands)} unvisited in-site page(s) instead "
                    f"({', '.join(sorted(_hosts))})."
                ),
                tool=None,  # resolver keeps authority (F6); seeds enrich post-resolve
                params={},
                parallel_safe=False,
                objective_anchor=getattr(item, "objective_anchor", "") or "",
                expected_output=(
                    f"Usable content from {_host0} covering: "
                    f"{(getattr(item, 'expected_output', '') or '')[:120]}"
                ),
                declared_criticality=(
                    getattr(item, "declared_criticality", "supporting")
                    or "supporting"
                ),
                recovery_of=getattr(item, "step_id", ""),
                recovery_seeds=_cands,
            )
            logger.info(
                "[DER:recovery] trigger: parent=%s dead=%d host=%s seeds=%d",
                getattr(item, "step_id", "?"), len(_dead), _host0, len(_cands),
            )
            return _rec
        except Exception as _rec_exc:
            logger.debug("[DER] recovery trigger failed: %s", _rec_exc)
            return None

    @staticmethod
    def _der_step_error_is_retryable(err: str) -> bool:
        """Whether a failed step's error text is worth another attempt.

        Connection-level errors are. A STEP TIMEOUT is not (execution audit B6,
        2026-09-29): the step already spent its whole deadline, and the
        abandoned worker may still be running the command - a retry starts it
        a second and third time in parallel.
        """
        if not err or err.lstrip().startswith("[STEP TIMEOUT"):
            return False
        return any(
            _k in err
            for _k in ("ConnectionError", "TimeoutError", "timed out",
                       "Connection refused", "timeout")
        )

    def _der_execute_with_recovery(
        self,
        _plan,
        _context_package,
        _is_mature,
        _der_task_class,
        _session: str,
        from_voice: bool,
        _confidence,
        task_id,
        _der_budget_class: Optional[str] = None,
    ):
        """
        Run the DER plan, catching TopologyViolationException (N.4 + O.6 + RC11)
        with a targeted recovery instead of the blanket ReAct fallback.

        On a topology violation we reset the Caducean session and retry once.
        If the retry also fails, returns None so the caller falls through to
        the agentic (ReAct) loop.
        """
        from backend.agent.exceptions import TopologyViolationException

        # Phase 1 (D1.6): expose task_class so the runtime resolver
        # (explorer.propose) can apply the capability-gated web fallback.
        self._der_task_class = _der_task_class

        # REQ-19 (T20): one DerLinkWriter per DER run â€” writes structural
        # links (part_of / depends_on / relevant_to / failed_like) into the
        # SHARED mycelium link store at finalize. Wired here so it exists for
        # the whole plan; bound to this run's kernel (no cross-session shared
        # mutable state).
        try:
            from backend.agent.der_links import DerLinkWriter

            _mi = getattr(self, "_memory_interface", None)
            _myc = getattr(_mi, "_mycelium", None) if _mi is not None else None
            _store = getattr(_myc, "_store", None)
            self._der_links = DerLinkWriter(_store) if _store is not None else None
        except Exception as _dl_exc:
            logger.debug("[DER] link-writer init failed: %s", _dl_exc)
            self._der_links = None

        # Phase 2 (D2.4): unified termination resource DER_WORK_UNITS_0 derived
        # from the LIVE context window (System Invariant: work units and context
        # window are the SAME resource). Split prepays width; complete/fail/veto
        # consumes 1. This is what makes the Lyapunov potential strictly decrease.
        try:
            from backend.agent.der_constants import derive_work_units_0

            _cw = self.resolve_context_window()
            self._der_work_units = derive_work_units_0(_cw)
        except Exception as _wu_err:
            logger.warning("[DER] work_units derive failed: %s", _wu_err)
            self._der_work_units = 0
        # REQ-7: previous step's |u| magnitude, for physics-event narration
        # transition detection (oscillating -> converged). None until first step.
        self._der_last_u_mag = None

        try:
            return self._execute_plan_der(
                plan=_plan,
                context_package=_context_package,
                is_mature=_is_mature,
                task_class=_der_task_class,
                session_id=_session,
                from_voice=from_voice,
                confidence=_confidence,
                turn_id=task_id,
                budget_class=_der_budget_class,
            )
        except TopologyViolationException:
            logger.warning(
                "[AgentKernel] TopologyViolation â€” attempting targeted recovery"
            )
            try:
                # RC11 FIX: reset Caducean session state before recovery
                from backend.gateway.iris_ffi import ffi_caducean_init_session
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                from backend.agent.coupled_registry import domain_windings

                # REQ-11 AC3: re-init with the domain windings so the engine's
                # c_eff matches what the registry holds after recovery.
                _l, _m = domain_windings("voice" if from_voice else "der")
                ffi_caducean_init_session(_session, _l, _m)
                get_event_bus().emit(
                    IRISStreamEvent.MODE_CHANGED,
                    data={
                        "from_mode": "DER",
                        "to_mode": "DER_RECOVERY",
                        "reason": "Topological violation â€” recovering",
                    },
                    session_id=_session,
                )
                get_event_bus().emit(
                    IRISStreamEvent.TOPOLOGY_RECOVERY,
                    data={
                        "from_mode": "DER",
                        "to_mode": "DER_RECOVERY",
                        "reason": "Topological violation â€” recovering",
                    },
                    session_id=_session,
                )
                return self._execute_plan_der(
                    plan=_plan,
                    context_package=_context_package,
                    is_mature=_is_mature,
                    task_class=_der_task_class,
                    session_id=_session,
                    from_voice=from_voice,
                    confidence=_confidence,
                    turn_id=task_id,
                )
            except Exception as _recovery_err:
                logger.warning(
                    f"[AgentKernel] Recovery failed, falling back to ReAct: {_recovery_err}"
                )
                return None
        finally:
            # Wedge fix (session 363, pin_35af67d07c5f): the turn is over -
            # deactivate the choke check so a stale _der_start_time from this
            # finished turn can never raise on a healthy non-DER call (a
            # simple chat) that runs later. If the turn WEDGED (never
            # returned), this finally never runs and the check stays active -
            # which is the correct direction.
            self._der_turn_active = False

    def _der_check_steering(self, _session, plan, queue, budget_deadline: Optional[float] = None) -> Optional[dict]:
        """REQ-15 AC1/AC2/AC3/AC6 (T25): consume pending steering at the NEXT
        step boundary â€” never mid-step.

        Drains every record queued for the session since the last boundary
        and applies, in order:
          - stop   -> latch ``_der_stop_requested`` (AC3: the loop aborts
                      here and persists `cancelled`);
          - pause  -> latch ``_der_pause_requested`` (AC4: the loop
                      suspends via ``_der_suspend_task``);
          - resume -> latch ``_der_resume_requested`` (harmless when the
                      task is not suspended; consumed and acked either way);
          - steer  -> revise the remaining plan via REQ-14's revision channel
                      (AC2); the LAST non-empty steering text wins.

        AC6 (channel independence): stop/pause flags are latched BEFORE any
        (potentially slow) revision is applied, and a stop suppresses the
        revision entirely â€” a stop is never delayed behind steering work.

        AC5 (acknowledgement): every consumed record emits ``steering:ack``
        status="considered".

        The stuck-streak gate runs at EVERY boundary, steering or not (owner,
        2026-10-01: c06 pushed 36 times with no brake).

        Returns ``None`` when nothing was queued and the gate did not fire,
        else a dict ``{"stop", "pause", "resume": bool, "steer": str|None,
        "revised": bool}``.
        """
        try:
            from backend.agent.steering import get_steering_inbox
        except Exception:
            get_steering_inbox = None
        records = get_steering_inbox().drain(_session) if get_steering_inbox else []
        if not records:
            if not getattr(self, "_der_stop_requested", False) and self._der_streak_gate(
                plan, queue, _session, budget_deadline=budget_deadline
            ):
                return {"stop": False, "pause": False, "resume": False,
                        "steer": None, "revised": True}
            return None

        stop = False
        pause = False
        resume = False
        steer_text = None
        for rec in records:
            if rec.channel == "stop":
                stop = True
            elif rec.channel == "pause":
                pause = True
            elif rec.channel == "resume":
                resume = True
            elif rec.channel == "steer" and rec.text and rec.text.strip():
                steer_text = rec.text.strip()  # last non-empty steering wins

        # AC6: latch the control flags BEFORE applying any revision so a stop
        # is never delayed behind a slow re-plan.
        if stop:
            self._der_stop_requested = True
        if pause:
            self._der_pause_requested = True
        if resume:
            self._der_resume_requested = True

        revised = False
        if steer_text is not None and not stop:
            revised = self._der_apply_steering(
                steer_text, _session, plan, queue,
                budget_deadline=budget_deadline,
            )
        # â”€â”€ Goal contract T7 (REQ-4 AC4.1): route user steering through
        # amend â€” add/remove/repromote a floor fact in place, preserving task
        # identity. Advisory: runs even when the replan above did nothing.
        try:
            if steer_text and not stop:
                if self._goal_contract_apply_steering(steer_text):
                    revised = True
        except Exception:
            pass

        # â”€â”€ T9 (specs/tool-result-envelope REQ-5): stuck-streak gate at the
        # step boundary, in front of the same replan machinery. Skipped when
        # the user just steered (a fresh revision replaced the plan â€” the
        # gate re-evaluates at the NEXT boundary) or when stopping.
        if not stop and not revised:
            if self._der_streak_gate(
                plan, queue, _session, budget_deadline=budget_deadline
            ):
                revised = True

        # AC5: every consumed record is acknowledged as "considered".
        for rec in records:
            self._emit_steering_ack(rec.channel, rec.message_id, "considered", _session)

        # REQ-18 AC4 (T31): correlate every steering message received â€” channel,
        # acknowledged status, and the step boundary at which it was applied.
        try:
            from backend.agent.der_trace import get_der_trace

            _trace = get_der_trace(self._der_trace_task_id())
            for rec in records:
                _trace.record(
                    "steering",
                    channel=rec.channel,
                    message_id=rec.message_id,
                    ack="considered",
                    boundary_step=getattr(queue, "_last_step_number", None),
                )
        except Exception:
            pass

        return {
            "stop": stop,
            "pause": pause,
            "resume": resume,
            "steer": steer_text,
            "revised": revised,
        }

    def _der_streak_gate(
        self,
        plan,
        queue,
        _session: str,
        budget_deadline: Optional[float] = None,
    ) -> bool:
        """T9 (specs/tool-result-envelope REQ-5 AC5.1â€“AC5.5): the stuck-streak
        gate, evaluated at the step boundary IN FRONT of the existing replan
        machinery. O(envelope count) arithmetic (AC5.5) â€” the LLM replan
        inside ``_der_apply_steering`` is paid ONLY when the gate fires.

        Detector: pure evaluate_streak over the settled envelopes' wrappers
        (consecutive repeat/empty/mismatch, or an idling run), with the
        existing Caducean TOPO_VIOLATION recommendation as the authoritative
        override (AC5.3 â€” reuse the existing physics detection, KD-4).

        Advisory-gate principle: any failure in here is treated as
        "below threshold" â€” a broken gate must not change loop semantics.

        Returns True when a replan revision was applied.
        """
        # A met objective is not stuck: every required fact is covered, so a
        # re-plan can only add work (live 2026-10-02 run A6: C=1.000 at
        # 00:17:42, the gate fired at 00:18:00, the re-plan ran a step and the
        # turn then crashed).
        if AgentKernel._goal_contract_met(self):  # class call: stand-in kernels
            return False
        try:
            from backend.agent.tool_envelope import evaluate_streak
            from backend.agent.der_constants import (
                STUCK_STREAK_N, IDLE_STREAK_N,
            )

            _counters = getattr(self, "_envelope_counters", None)
            if _counters is None:
                _counters = {
                    "written": 0, "raw_ref_fetches": 0,
                    "crit_confirmed": 0, "gate_fired": 0,
                    "gate_blocked": 0, "hard_blocks": 0,
                    "suggest_overrides": 0,
                }
                self._envelope_counters = _counters

            # Settled envelopes for THIS run: completed (+vetoed) queue items.
            _done_ids = set(queue.completed_ids) | set(queue.vetoed_ids)
            # Decide again only after a new step settles: right after a
            # replan the same tail would fire again, a replan per boundary.
            _settled = len(_done_ids | set(queue.failed_ids))
            if _settled == queue.streak_gate_settled:
                return False
            queue.streak_gate_settled = _settled
            _envs = [
                getattr(_it, "envelope", None)
                for _it in getattr(queue, "items", [])
                if getattr(_it, "step_id", "") in _done_ids
            ]
            _wrappers = [e.wrapper_dict() for e in _envs if e is not None]

            # AC5.3: TOPO_VIOLATION rec forces the gate regardless of
            # streak arithmetic (existing physics detection, zero new code
            # on the detection side).
            _topo = False
            try:
                from backend.gateway.iris_ffi import ffi_caducean_recommend

                # Fold-back: the finished steps' physics must have landed
                # before the topology override decides (side lane).
                _der_physics_settle(self, _session)
                _topo = ffi_caducean_recommend(_session) == 3
            except Exception:
                _topo = False

            # Goal contract T6 (REQ-3 AC3.4): feed the stall-rate signal
            # into the idling shape alongside the streak arithmetic. Advisory
            # â€” a missing contract preserves the legacy streak behavior.
            _gcov_state = getattr(self, "_goal_contract_state", None)
            _gcov_c = None
            _gcov_unmoved = 0
            _gcov_rho = None
            _gcov_stall = 0.0
            if _gcov_state is not None:
                try:
                    from backend.agent.der_constants import (
                        GOAL_STALL_RATE as _GOAL_STALL_RATE,
                    )

                    _gcov_c = float(_gcov_state.get("C", 0.0))
                    _gcov_unmoved = int(_gcov_state.get("unmoved", 0))
                    _gcov_rho = float(_gcov_state.get("rho", 0.0))
                    _gcov_stall = float(_GOAL_STALL_RATE)
                except Exception:
                    _gcov_state = None
            # The coverage arms judge "no progress toward the facts". While a
            # step of the ORIGINAL plan has not settled, the plan has not had
            # its chance: live 2026-10-06 two reads settled at C=0.667 with the
            # planned summary step still pending, the rate arm fired, and two
            # re-plans tripled the work (10 steps for 3 goals). The streak arms
            # (repeat / empty / mismatch / topology) still fire at any time.
            _plan_open = _plan_steps_open(plan, queue)
            if _gcov_c is not None and _plan_open:
                logger.debug(
                    "[DER:streak-gate] coverage arms wait: %d planned step(s) "
                    "not settled (C=%.3f)", _plan_open, _gcov_c,
                )
                _gcov_c = None
            fire, reason = evaluate_streak(
                _wrappers, STUCK_STREAK_N, IDLE_STREAK_N,
                topo_violation=_topo,
                coverage=_gcov_c,
                coverage_unmoved_n=_gcov_unmoved,
                coverage_rho=_gcov_rho,
                stall_rate=_gcov_stall,
            )
            if fire and str(reason).startswith("idle_streak"):
                # Shadow only (owner 2026-10-01): the idle arm fired on 5 of 15
                # healthy coding runs (reads and a first red test run verify
                # nothing yet) and its replan dropped c15's fix step. Logged and
                # counted until a measured true positive exists.
                _counters["idle_shadow"] = _counters.get("idle_shadow", 0) + 1
                logger.info(
                    "[DER:streak-gate] SHADOW would fire (%s) - idle arm is "
                    "shadow-only, plan continues", reason,
                )
                return False
            if not fire:
                _counters["gate_blocked"] += 1
                # AC3.3/AC7.2: a stop-suggestion the loop does NOT act on is
                # a suggestion override â€” logged with its reason, counted.
                if _wrappers and _wrappers[-1].get("suggestion") == "stop":
                    _counters["suggest_overrides"] += 1
                    logger.info(
                        "[DER:streak-gate] suggestion override: step %s "
                        "suggested stop but streak arithmetic is below "
                        "threshold â€” continuing current plan",
                        _wrappers[-1].get("step_id", "?"),
                    )
                return False

            # A coverage stall on change facts whose change a step already made is
            # not "stuck": what is missing is one passing run, and the cover push
            # asks for exactly that (goal_contract.cover_goal). A re-plan from the
            # request redid read/edit/check (live c05 2026-10-27: 3 steps, 51 s).
            # If the check fails, C stays open and the gate fires on the next settle.
            if str(reason or "").startswith("coverage_"):
                try:
                    from backend.agent import goal_contract as _gc_gate

                    _gate_open = AgentKernel._goal_contract_open_facts(self)
                    _gate_res = (getattr(self, "_goal_contract_state", None) or {}).get("results") or ()
                    if _gate_open and all(_gc_gate.change_awaits_check(_f, _gate_res) for _f in _gate_open):
                        _counters["gate_check_only"] = _counters.get("gate_check_only", 0) + 1
                        logger.info(
                            "[DER:streak-gate] %s on a change already made - one check "
                            "step instead of a re-plan conv=%s", reason,
                            getattr(self, "conversation_id", ""),
                        )
                        return False
                except Exception as _gco_exc:  # noqa: BLE001 - doubt keeps the re-plan
                    logger.debug("[DER:streak-gate] check-only test failed: %r", _gco_exc)

            from backend.agent.der_constants import STREAK_GATE_MAX_FIRES

            if queue.streak_gate_fires >= STREAK_GATE_MAX_FIRES:
                _counters["gate_capped"] = _counters.get("gate_capped", 0) + 1
                logger.info(
                    "[DER:streak-gate] would fire (%s) but the run already "
                    "replanned %d time(s) - plan continues", reason,
                    queue.streak_gate_fires,
                )
                return False
            queue.streak_gate_fires += 1
            _counters["gate_fired"] += 1
            # Goal contract (REQ-7 AC7.2): a coverage-stall fire is a
            # coverage stall â€” count it on the contract so the stall rate
            # is tunable from measurement. Advisory, never raises.
            try:
                _gc_stall = getattr(self, "_goal_contract_state", None)
                if _gc_stall is not None and str(reason or "").startswith(
                    "coverage_"
                ):
                    _gc_c = _gc_stall.get("counters") or {}
                    _gc_c["stalls"] = int(_gc_c.get("stalls", 0)) + 1
                    _gc_stall["counters"] = _gc_c
            except Exception:
                pass
            # AC5.4: audit â€” the triggering envelopes (step ids + wrapper
            # labels) are logged so the trigger is auditable post-run.
            _tail = _wrappers[-max(STUCK_STREAK_N, IDLE_STREAK_N, 1):]
            _audit = "; ".join(
                f"{w.get('step_id', '?')}: novelty={w.get('novelty')} "
                f"match={w.get('match')} shape={w.get('stuck_shape')}"
                for w in _tail
            )
            logger.info(
                "[DER:streak-gate] FIRED (%s) â€” triggering envelopes: %s",
                reason, _audit,
            )
            _directive = (
                f"Replan required: the run is stuck ({reason}). "
                f"Triggering steps: {_audit}. Revise the remaining plan to "
                "break the streak â€” do NOT repeat a completed step; read "
                "the already-gathered documents instead."
            )
            return self._der_apply_steering(
                _directive, _session, plan, queue,
                budget_deadline=budget_deadline,
            )
        except Exception as _gate_exc:
            logger.debug(
                "[DER:streak-gate] evaluation failed â€” treated as below "
                "threshold (advisory gate): %s", _gate_exc,
            )
            return False

    def _der_apply_steering(
        self, text, _session, plan, queue, budget_deadline: Optional[float] = None
    ) -> bool:
        """REQ-15 AC2: revise the remaining plan via REQ-14's revision
        channel without aborting the task.

        Re-plans from the steering text (single-step fallback on failure),
        REMOVES every not-yet-terminal queue item (they are REPLACED, not
        failed â€” ``queue.failed_ids`` stays honest), appends the revised steps
        as fresh items, and re-emits ``task:start`` with
        ``origin="user_steering"`` carrying the revised step list (REQ-14 AC1
        revision signal; REQ-18 AC3 origin).

        ``budget_deadline`` (session 269, pin_ced7b0dc3b8f): the re-plan is
        an UNBOUNDED LLM call made INSIDE the loop body â€” the turn budget's
        while-condition can never reach a hang here. conv-81's last event was
        the steering ack, then silence for 29 minutes. When a deadline is
        supplied, the re-plan runs on a daemon thread bounded by it; a
        timeout keeps the CURRENT plan (the revision is advisory â€” skipping
        it degrades the turn, it never kills it).

        Returns True when a revision was actually applied.
        """
        try:
            from backend.agent.der_loop import QueueItem
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            _mode = queue.mode.value if getattr(queue, "mode", None) else "full"
            # V12 (2026-10-02 live): the re-plan saw ONLY the directive ("Replan
            # required: the run is stuck ...") - no user request - and recall
            # searched with that header, so other stuck runs' episodes ("Read
            # the existing notes file") became the new plan of a Wikipedia
            # task. The planner gets the request + the directive; recall
            # searches with the request alone.
            _orig = str(getattr(plan, "original_task", "") or "") if plan else ""
            _plan_text = (
                _orig + "\n\n" + text if _orig and _orig not in (text or "") else text
            )
            _recall = _orig or text
            if budget_deadline is not None:
                _timeout_s = budget_deadline - time.perf_counter()
                if _timeout_s <= 0:
                    logger.warning(
                        "[DER] Session %s steering skipped â€” turn budget "
                        "already exhausted", _session,
                    )
                    return False
                _box: dict = {}

                def _replan() -> None:
                    try:
                        _box["plan"] = self._plan_task(
                            _plan_text, session_id=_session, mode=_mode,
                            recall_query=_recall,
                        )
                    except BaseException as _exc:  # noqa: BLE001 â€” boxed, re-raised below
                        _box["exc"] = _exc

                import threading as _threading

                _t = _threading.Thread(
                    target=_replan, daemon=True,
                    name=f"der-steer-replan-{_session}",
                )
                _t.start()
                _t.join(timeout=_timeout_s)
                if _t.is_alive():
                    logger.warning(
                        "[DER] Session %s steering re-plan exceeded the "
                        "remaining turn budget (%.0fs) â€” keeping the current "
                        "plan", _session, _timeout_s,
                    )
                    return False
                if "exc" in _box:
                    raise _box["exc"]
                _rev = _box.get("plan")
            else:
                _rev = self._plan_task(
                    _plan_text,
                    session_id=_session,
                    mode=_mode,
                    recall_query=_recall,
                )
            if _rev is None or not getattr(_rev, "steps", None):
                logger.info(
                    "[DER] Session %s steering produced no plan â€” keeping "
                    "the current plan", _session,
                )
                return False

            _done = (
                set(queue.completed_ids)
                | set(queue.vetoed_ids)
                | set(queue.failed_ids)
            )
            # Replace remaining pending steps: remove them (not failures),
            # then append the revised steps fresh.
            queue.items[:] = [it for it in queue.items if it.step_id in _done]

            _fresh: List["QueueItem"] = []
            _base = len(queue.items) + 1
            for _i, _s in enumerate(_rev.steps):
                # Neutralize dependencies that point at dropped ids so the
                # revised steps are immediately ready.
                _deps = [
                    d for d in (getattr(_s, "depends_on", None) or [])
                    if d in _done
                ]
                _fresh.append(
                    QueueItem(
                        step_id=f"steer-{_base + _i}",
                        step_number=_base + _i,
                        description=_s.description,
                        tool=getattr(_s, "tool", None),
                        params=dict(getattr(_s, "params", None) or {}),
                        depends_on=_deps,
                        critical=getattr(_s, "critical", True),
                        objective_anchor=(
                            getattr(plan, "original_task", "") if plan else ""
                        ),
                    )
                )
            queue.items.extend(_fresh)

            # REQ-14 revision signal with the user_steering origin.
            _card_task_id = self.conversation_id or _session
            _card_id, _card_relation = self._resolve_card_identity(
                _card_task_id, "user_steering"
            )
            get_event_bus().emit(
                IRISStreamEvent.TASK_START,
                data=self._task_start_payload(
                    task_id=_card_task_id,
                    description=text,
                    plan_title=self._effective_plan_title(plan),
                    mode=_mode,
                    steps=[
                        {
                            "id": it.step_id,
                            "description": it.description,
                            "status": "pending",
                            "toolName": _step_tool(it),
                        }
                        for it in _fresh
                    ],
                    total_steps=len(_fresh),
                    origin="user_steering",
                    # REQ-3 (T2): backend-declared card identity.
                    card_id=_card_id,
                    card_relation=_card_relation,
                    conversation_id=self.conversation_id,
                        turn_id=getattr(self, "_current_turn_id", None),
                    **self._multiagent_tags(),
                ),
                turn_id=self.conversation_id or _session,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
            # T4a (REQ-4 AC1): persist the revised card. The WIRE payload
            # above intentionally carries only `_fresh` (the delta the
            # frontend merges) â€” the STORED snapshot must stay the FULL
            # cumulative step list (queue.items, already extended with
            # _fresh), or a restore would show only the newest steps.
            self._persist_card_snapshot(
                card_id=_card_id,
                conversation_id=self.conversation_id,
                card_relation=_card_relation,
                plan_title=self._effective_plan_title(plan),
                mode=_mode,
                steps=self._queue_steps_snapshot(queue),
                total_steps=len(queue.items),
                terminal_state="running",
            )
            # REQ-18 AC3 (T31): correlate the user-steering revision.
            try:
                from backend.agent.der_trace import get_der_trace

                get_der_trace(self._der_trace_task_id()).record(
                    "revision",
                    origin="user_steering",
                    boundary_step=getattr(queue, "_last_step_number", None),
                )
            except Exception:
                pass
            return True
        except Exception as _steer_exc:
            logger.debug("[DER] steering revision failed: %s", _steer_exc)
            return False

    def _der_amend_graph(
        self,
        new_steps,
        _session: str,
        plan,
        queue,
        _token_budget: int = 0,
        _tokens_used: int = 0,
        _turn_id: str = "",
    ) -> bool:
        """Extend the executing graph with *new_steps* (REQ-5).

        Returns True when the amendment was applied. Refused amendments are
        recorded with their cause (REQ-5 AC5, REQ-9 AC3) and execution
        continues on the existing graph â€” never a hang, never a silent skip.
        """
        from backend.agent.nodes.telemetry import log_amendment

        # getattr, not attribute access: these run on the graft/recovery paths,
        # and a kernel built via __new__ (as the DER test doubles and some
        # recovery paths do) has no conversation_id. A bare access raised
        # AttributeError inside the graft's try/except, silently turning
        # "amend the graph" into "recovery failed" â€” telemetry must never be
        # able to cost a graft.
        _task_id = getattr(self, "conversation_id", None) or _session
        try:
            if not new_steps:
                return False
            # REQ-19 (T34): a turn whose card already reached its terminal state
            # is CLOSED â€” recovery must not extend the graph after the answer is
            # public. The settle emitter (_der_emit_card_settle) marks that
            # moment in _der_card_terminal_emitted; without this guard the graft
            # loop kept crawling long after the reply (live conv-139/141: ~40
            # minutes of activity the user read as a second agent). Refusal is
            # the documented safe path: the cause is recorded and the existing
            # graph keeps running â€” never a hang, never a silent skip.
            _settled = getattr(self, "_der_card_terminal_emitted", None) or ()
            if _settled and (
                (_turn_id and _turn_id in _settled)
                or getattr(self, "_current_turn_id", None) in _settled
            ):
                log_amendment(
                    task_id=_task_id, kind="refused",
                    cause="recovery_stopped_turn_finalized",
                    detail=f"turn={_turn_id or getattr(self, '_current_turn_id', '')}",
                )
                return False
            # AC3: per-task bound on amendments.
            _used = getattr(self, "_der_amendment_count", 0)
            if _used >= self._AMENDMENT_BOUND:
                log_amendment(
                    task_id=_task_id, kind="refused",
                    cause="amendment_bound",
                    detail=f"used={_used} bound={self._AMENDMENT_BOUND}",
                )
                return False
            # AC4: the task budget is authoritative â€” an amendment cannot
            # exceed it. (Amendments add steps; if the budget is already
            # exhausted, adding work would violate the ceiling.)
            if _token_budget > 0 and _tokens_used >= _token_budget:
                log_amendment(
                    task_id=_task_id, kind="refused",
                    cause="budget_exceeded",
                    detail=f"used={_tokens_used} budget={_token_budget}",
                )
                return False

            # AC2: satisfied nodes are preserved. New steps may only depend on
            # already-terminal ids (completed/vetoed/failed); a dependency on a
            # pending node that may never run would stall the graph â€” refuse
            # (REQ-5 edge: amendment that removes/consumes a live node is
            # rejected, recorded, execution unchanged).
            from backend.agent.der_loop import QueueItem

            _done = (
                set(queue.completed_ids)
                | set(queue.vetoed_ids)
                | set(queue.failed_ids)
            )
            _pending = {it.step_id for it in queue.items if it.step_id not in _done}
            for _s in new_steps:
                _deps = list(getattr(_s, "depends_on", None) or [])
                _bad = [d for d in _deps if d in _pending]
                if _bad:
                    log_amendment(
                        task_id=_task_id, kind="refused",
                        cause="invalid_dependency",
                        detail=f"step={getattr(_s, 'description', '')[:60]} deps={_bad}",
                    )
                    return False

            # Append the fresh steps â€” completed work is untouched (AC2).
            _base = len(queue.items) + 1
            _fresh: List["QueueItem"] = []
            for _i, _s in enumerate(new_steps):
                # A graft's split child joins the graph AS ITSELF: its id is
                # what settle_split waits on, and it carries its parent link,
                # depth and node record. A copy ran beside it as "amend-N"
                # (live conv-1574, 2026-10-12: amend-3 and s1_s0 queued for
                # the same browser page, s1_s0 waited 36 s) and its result
                # never settled the failed parent.
                if isinstance(_s, QueueItem) and getattr(_s, "is_subloop", False):
                    _fresh.append(_s)
                    continue
                _fresh.append(
                    QueueItem(
                        step_id=f"amend-{_base + _i}",
                        step_number=_base + _i,
                        description=getattr(_s, "description", ""),
                        tool=getattr(_s, "tool", None),
                        params=dict(getattr(_s, "params", None) or {}),
                        depends_on=[
                            d for d in (getattr(_s, "depends_on", None) or [])
                            if d in _done
                        ],
                        critical=getattr(_s, "critical", True),
                        objective_anchor=(
                            getattr(plan, "original_task", "") if plan else ""
                        ),
                    )
                )
            queue.items.extend(_fresh)
            self._der_amendment_count = _used + 1
            log_amendment(
                task_id=_task_id, kind="amend",
                cause="planner_driven",
                detail=f"steps={len(_fresh)} count={_used + 1}",
            )
            logger.info(
                "[DER] amendment applied: +%d step(s) (count=%d) task=%s",
                len(_fresh), _used + 1, _task_id,
            )

            # Revision signal so the frontend card reflects the extended plan â€”
            # SAME payload shape as steering (no new event types; REQ-3 AC4).
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                _mode = queue.mode.value if getattr(queue, "mode", None) else "full"
                # REQ-3 (T2): "amendment" is a fourth, undocumented origin â€”
                # handled generically by the "not initial" rule in
                # _resolve_card_identity rather than special-cased here.
                _card_id, _card_relation = self._resolve_card_identity(
                    _task_id, "amendment"
                )
                get_event_bus().emit(
                    IRISStreamEvent.TASK_START,
                    data=self._task_start_payload(
                        task_id=_task_id,
                        description=(
                            getattr(plan, "original_task", "") or ""
                        )[:120],
                        plan_title=self._effective_plan_title(plan),
                        mode=_mode,
                        steps=[
                            {
                                "id": it.step_id,
                                "description": it.description,
                                "status": (
                                    "done"
                                    if it.step_id in set(queue.completed_ids)
                                    else "failed"
                                    if it.step_id in set(queue.failed_ids)
                                    else "pending"
                                ),
                                "toolName": _step_tool(it),
                            }
                            for it in list(queue.items)
                        ],
                        total_steps=len(queue.items),
                        origin="amendment",
                        # REQ-3 (T2): backend-declared card identity.
                        card_id=_card_id,
                        card_relation=_card_relation,
                        conversation_id=self.conversation_id,
                            turn_id=getattr(self, "_current_turn_id", None),
                        **self._multiagent_tags(),
                    ),
                    turn_id=_task_id,
                    conversation_id=self.conversation_id,
                    session_id=_session,
                )
                # T4a (REQ-4 AC1): persist the amended card â€” full
                # cumulative queue.items (already extended with _fresh
                # above), not the wire delta (same reasoning as the
                # user_steering site).
                self._persist_card_snapshot(
                    card_id=_card_id,
                    conversation_id=self.conversation_id,
                    card_relation=_card_relation,
                    plan_title=self._effective_plan_title(plan),
                    mode=_mode,
                    steps=self._queue_steps_snapshot(queue),
                    total_steps=len(queue.items),
                    terminal_state="running",
                )
            except Exception:
                pass  # never block an amendment on an emit failure
            return True
        except Exception as _amend_exc:  # noqa: BLE001 â€” refusal, never a crash
            log_amendment(
                task_id=_task_id, kind="refused",
                cause="error", detail=str(_amend_exc)[:200],
            )
            return False

    def _emit_steering_ack(self, channel, message_id, status, _session) -> None:
        """REQ-15 AC5 (T26): visible acknowledgement that a steering message
        landed ("queued") or was considered at a step boundary ("considered").
        Best-effort â€” never blocks or breaks the loop."""
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            get_event_bus().emit(
                IRISStreamEvent.STEERING_ACK,
                data={
                    "channel": channel,
                    "message_id": message_id,
                    "status": status,
                },
                turn_id=self.conversation_id or _session,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
        except Exception:
            pass

    def _der_suspend_task(self, _session, plan, queue, _turn_id) -> str:
        """REQ-15 AC4 (T26): suspend execution at the next step boundary.

        Persists the in-progress state (ledger lifecycle ``paused`` + a
        ``task:paused`` event), then waits for a ``resume`` or ``stop``
        record. Steer records arriving while suspended STAY queued and are
        applied at the next boundary after resume â€” they are never dropped.
        Idempotent resume: ``completed_ids``/``vetoed_ids``/``failed_ids``
        ARE the persisted in-progress state; ``next_ready`` skips them, so
        no completed side effect is duplicated on resume.

        Returns "resume" or "stop". Runs on the DER worker thread â€” the
        bounded poll (time.sleep) never blocks the event loop.
        """
        from backend.agent.der_execution_ledger import ExecutionLedger
        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
        from backend.agent.steering import get_steering_inbox
        import time as _time

        # getattr, not attribute access: these run on the graft/recovery paths,
        # and a kernel built via __new__ (as the DER test doubles and some
        # recovery paths do) has no conversation_id. A bare access raised
        # AttributeError inside the graft's try/except, silently turning
        # "amend the graph" into "recovery failed" â€” telemetry must never be
        # able to cost a graft.
        _task_id = getattr(self, "conversation_id", None) or _session
        try:
            _ledger = getattr(self, "_der_ledger", None)
            if _ledger is None:
                _ledger = ExecutionLedger(
                    conversation_id=_task_id,
                    storage_path=_der_ledger_storage_path(),  # T9 (REQ-14 AC1)
                )
                self._der_ledger = _ledger
            _ledger.transition(_task_id, "paused")
            _ledger.persist()
        except Exception as _pe:
            logger.debug("[DER] pause lifecycle persist failed: %s", _pe)

        try:
            get_event_bus().emit(
                IRISStreamEvent.TASK_PAUSED,
                data={"task_id": _task_id, "state": "paused"},
                turn_id=_turn_id,
                conversation_id=self.conversation_id,
                session_id=_session,
            )
        except Exception:
            pass  # EventBus optional â€” never block the loop

        inbox = get_steering_inbox()
        self._der_resume_requested = False
        while not self._der_stop_requested:
            if inbox.pending_channel(_session, "stop"):
                for _rec in inbox.drain_channel(_session, "stop"):
                    self._emit_steering_ack(
                        _rec.channel, _rec.message_id, "considered", _session
                    )
                self._der_stop_requested = True
                return "stop"
            if inbox.pending_channel(_session, "resume"):
                for _rec in inbox.drain_channel(_session, "resume"):
                    self._emit_steering_ack(
                        _rec.channel, _rec.message_id, "considered", _session
                    )
                self._der_resume_requested = True
                try:
                    _ledger = getattr(self, "_der_ledger", None)
                    if _ledger is not None:
                        _ledger.transition(_task_id, "running")
                        _ledger.persist()
                except Exception:
                    pass
                try:
                    get_event_bus().emit(
                        IRISStreamEvent.TASK_RESUMED,
                        data={"task_id": _task_id, "state": "running"},
                        turn_id=_turn_id,
                        conversation_id=self.conversation_id,
                        session_id=_session,
                    )
                except Exception:
                    pass
                return "resume"
            try:
                _time.sleep(0.2)  # poll â€” DER runs on a worker thread
            except Exception:
                break
        return "stop"

    # â”€â”€ REQ-4 (specs/dag-node-execution-model): outcome-driven routing â”€â”€â”€â”€â”€
    # The DER seam the node model adds: when a step fails with a typed reason,
    # consult the router BEFORE the graft/split handler. A recovery node that
    # advertises the reason runs in place of the failing node â€” no branch is
    # written in the failing node's module (design D4). Returns the recovered
    # step result on success, None when routing is disabled / declined / no
    # candidate â€” in which case the caller proceeds exactly as today (REQ-7
    # AC4/AC5 kill-switch parity).
    def _der_enqueue_recovery(
        self, item, recovery, step_result, _session, _turn_id, outcome, tool, queue,
    ) -> Optional[str]:
        """Session-319 (owner decision: "the job board"): enqueue a recovery step
        instead of running it inline.

        Returns ``None`` ALWAYS. The failing step must settle honestly â€” it really
        did fail â€” and the recovery then runs later as its OWN step, carrying its
        own envelope. That is what AC9.5/AC9.6 require: recovery is a separate
        step, and the brain never waits on it.

        Why this replaced the inline form: inline blocked the failing step for the
        whole recovery (including a measured ~33 s Chromium cold start) and built
        no envelope, so the recovery was invisible to the ledger.

        Never raises: a recovery that cannot be queued degrades to the normal
        failure path rather than breaking the DER loop.
        """
        try:
            from backend.agent.der_loop import QueueItem
            from backend.agent.nodes.telemetry import log_routing_decision

            try:
                from backend.agent.der_constants import RECOVERY_PAGE_BUDGET
                _budget = max(int(RECOVERY_PAGE_BUDGET), 1)
            except Exception:
                _budget = 25

            _env = getattr(item, "envelope", None)
            _conv = self.conversation_id or ""
            _visited = set(
                getattr(self, "_der_crawled_urls", {}).get(_conv, set())
            )
            _dead, _hosts, _cands = _recovery_candidates(
                step_result, list(getattr(_env, "sources", []) or []), _visited,
            )
            if not _hosts:
                return None

            # ONE CREW PER BUILDING (owner, session-319): claim the host
            # ATOMICALLY. Same budget the bespoke lane uses, so the two lanes can
            # never both open a crew for one host.
            with _der_recovery_lock:
                _ro = dict(getattr(self, "_der_recovery_opened", {}))
                _opened = set(_ro.get(_conv, set()))
                _claim = {h for h in _hosts if h not in _opened}
                if not _claim:
                    return None
                _ro[_conv] = _opened | _claim
                self._der_recovery_opened = _ro

            _host0 = sorted(_claim)[0]
            _rec_item = QueueItem(
                step_id=f"recovery_{getattr(item, 'step_id', 's')}",
                step_number=int(getattr(item, "step_number", 1) or 1) + 1,
                description=(
                    f"Recover dead fetch from {_host0}: crawl "
                    f"{len(_cands)} unvisited in-site page(s) via "
                    f"{recovery.name} ({', '.join(sorted(_claim))})."
                ),
                # The ROUTER chose the node, so no resolver pass is needed and
                # `tool` is known at build time.
                tool=recovery.name,
                params={
                    "seed_urls": list(_cands)[:_budget],
                    "max_pages": _budget,
                    "recovery_of": getattr(item, "step_id", ""),
                },
                parallel_safe=False,
                objective_anchor=getattr(item, "objective_anchor", "") or "",
                expected_output=(
                    f"Usable content from {_host0} covering: "
                    f"{(getattr(item, 'expected_output', '') or '')[:120]}"
                ),
                declared_criticality=(
                    getattr(item, "declared_criticality", "supporting")
                    or "supporting"
                ),
                recovery_of=getattr(item, "step_id", ""),
                recovery_seeds=list(_cands),
            )
            queue.add_item(_rec_item)
            # Taxonomy CONTROL: the router chose another way after a node failure;
            # trigger = the NodeOutcome Reason (closed lattice).
            _emit_event(
                self, "PIVOT", evidence="verifier", thread_id=_session,
                trigger=outcome.reason.value, step_index=str(getattr(item, "step_id", "") or ""),
                action_signature=f"{recovery.name}:{_host0}",
                payload={"from_tool": tool, "to_tool": recovery.name,
                         "recovery_step": _rec_item.step_id},
            )
            logger.info(
                "[DER:recovery] ENQUEUED (job board): parent=%s node=%s dead=%d "
                "host=%s seeds=%d",
                getattr(item, "step_id", "?"), recovery.name,
                len(_dead), _host0, len(_cands),
            )
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
                        "tool_name": recovery.name,
                        **self._card_envelope(_turn_id),
                    },
                    turn_id=_turn_id,
                    conversation_id=self.conversation_id,
                )
            except Exception:
                pass
            log_routing_decision(
                task_id=self.conversation_id or _session,
                step_id=item.step_id, node=tool,
                reason=outcome.reason.value,
                candidates=[recovery.name],
                selected=recovery.name,
            )
        except Exception as _enq_exc:  # noqa: BLE001 â€” must never break the loop
            logger.warning(
                "[DER:recovery] enqueue failed for %s: %s",
                getattr(item, "step_id", "?"), _enq_exc,
            )
        return None

    def _der_route_step_failure(
        self,
        item: "QueueItem",
        step_result: str,
        _session: str,
        _turn_id: Optional[str],
        plan,
        queue=None,
    ) -> Optional[str]:
        try:
            from backend.agent.nodes.router import (
                RouteRequest,
                get_node_router,
                routing_enabled,
            )
            from backend.agent.nodes.runner import outcome_from_crawler_error
            from backend.agent.tool_registry import get_node_spec, resolve_tool

            if not routing_enabled():
                return None  # kill switch â€” today's path (REQ-7 AC4/AC5)
            tool = getattr(item, "tool", None)
            if not tool:
                # A node step has no item.tool: route on the call that failed
                # it (its decisive call, only when that call did fail). Before,
                # every node failure skipped the node router (DER_DAG.md seam 2).
                _dc = _step_decisive_call(item)
                tool = _dc.get("tool") if _dc and not _dc.get("ok", True) else None
            if not tool:
                return None  # reasoning steps have no tool to route on
            spec = resolve_tool(tool)
            if spec is None:
                return None  # undeclared legacy tool â€” adapter path (REQ-7 AC1)
            node_spec = get_node_spec(tool)
            if node_spec is None:
                return None  # tool exists but never declared node metadata

            # Map the free-form failure text to a typed reason (REQ-1 AC3).
            outcome = outcome_from_crawler_error(step_result or "", time.time())
            # CT-3 (REQ-1 AC5): the typed reason reaches the EXISTING
            # node-record/error_type machinery, not a parallel structure.
            item.error_type = outcome.reason.value

            req = RouteRequest(
                task_id=self.conversation_id or _session,
                step_id=item.step_id,
                node=tool,
                outcome=outcome,
                # REQ-8 AC1/AC2: a recovery node may not exceed the tier the
                # user approved for THIS step â€” the failing node's own tier.
                approved_tier=node_spec.permission_tier,
            )
            decision = get_node_router().route(req)
            if decision is None or decision.selected is None:
                return None  # honest no-candidate (REQ-4 AC6) or blocked
            if decision.blocked_by in ("permission", "terminal", "bound"):
                # REQ-8 edge: a permission-blocked route is surfaced, never
                # taken silently â€” the caller proceeds on today's path and the
                # normal failure handling (graft / ask) applies.
                return None

            recovery = decision.selected
            # â”€â”€ Session-319 (owner decision: "the job board") â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # ENQUEUE the recovery as its OWN STEP instead of running it inline.
            #
            # WHY: the inline form below blocks the failing step for the whole
            # recovery â€” including a measured ~33 s Chromium cold start â€” which
            # violates AC9.6 ("the brain never waits on the recovery lane"), and
            # it builds no envelope of its own, so the recovery is invisible to
            # the ledger. Queuing fixes both: the failing step settles honestly
            # and the recovery runs as its own step with its own envelope.
            # The old inline form (run the recovery node here, blocking the
            # loop) was removed 2026-10-12: every production caller passes the
            # queue, so it only ran for callers that did not exist.
            if queue is None:
                return None
            return self._der_enqueue_recovery(
                item, recovery, step_result, _session, _turn_id,
                outcome, tool, queue,
            )
        except Exception as _route_err:  # noqa: BLE001 â€” routing must never break the loop
            logger.warning("[DER] routing consultation failed: %s", _route_err)
            return None

    def _der_handle_step_failure(
        self,
        item: "QueueItem",
        queue,
        plan,
        _session: str,
        _turn_id: Optional[str],
        context_package,
        step_result: Optional[str] = None,
    ) -> None:
        """
        Handle a step that failed after its single retry.

        Always marks the step failed and aborts any downstream steps that
        depend on it (so the scheduler skips them). If the step was critical
        and we haven't exhausted the graft budget, asks the LLM to design a
        recovery sub-graph and injects those steps into the queue.
        """
        queue.mark_failed(item.step_id)
        aborted = queue.abort_descendants(item.step_id)
        # â”€â”€ REQ-17 AC17.1 + REQ-11 AC11.1/AC11.2 (T21/T14 wiring) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # This is the ONE failure-triage seam: a step that failed after its
        # retry lands here from both loop sites (the main step loop and the
        # extra-step loop). BEFORE the recovery sub-graph is planned below it
        # consults the `recovery_strategy` triage consumer (AC17.1). The T14
        # graft failure veto that was also seeded here is RETIRED (2026-11-09,
        # tool_decision.resolve docstring has the measurement). The consult is
        #       SHADOW: the row is recorded and the counters / the existing
        #       graft path still decide (AC17.2), so a confident `retry_same`
        #       can never route a repeat the counters would have escalated.
        # Best-effort â€” an advisory triage must never block a recovery.
        try:
            _triage_box = self._get_tool_box()
            _triage_tool = str(_step_tool(item) or "")
            _triage_obj = (
                getattr(item, "objective_anchor", "")
                or getattr(item, "description", "")
                or ""
            )
            _triage_box.recovery_strategy(
                failed_tool=_triage_tool,
                error_snippet=str(step_result or "")[:200],
                objective=_triage_obj,
            )
        except Exception as _triage_err:  # noqa: BLE001 â€” advisory only
            logger.debug("[DER] failure triage consult failed: %r", _triage_err)
        # AC2.1/AC9.3 (session-319 fix): a failed step must still teach turn
        # memory the addresses it touched. Finalize (which used to be the only
        # writer) is skipped on this path, so without this call a partially
        # successful crawl that was then judged FAILED contributed nothing and
        # the next step re-fetched the same URLs â€” the owner's reported symptom.
        try:
            _n_urls = _remember_turn_urls(self, step_result, "step-failure")
            if _n_urls:
                logger.info(
                    "[DER] failure path recorded URLs for %s "
                    "(turn memory now holds %d address(es))",
                    item.step_id, _n_urls,
                )
        except Exception:
            pass
        # Goal contract T9 (REQ-5 AC5.1): the failure path SKIPS finalize, so
        # the finalize-site blocking twin never runs here. A FAILED settle
        # with a terminal typed reason blocks the facts it was working on â€”
        # same helper, same denominator semantics. Advisory, never raises.
        try:
            _gc_reason = str(getattr(item, "error_type", "") or "")
            if _gc_reason:
                self._goal_contract_block_facts(
                    item, _gc_reason, str(step_result or ""),
                )
        except Exception:
            pass
        # Goal contract T15 / REQ-11 AC11.3-AC11.5: a fail-fast or blocked
        # step must TEACH â€” the failure path skips finalize, so none of its
        # learning hooks run here. Gated on blocked reasons only (fail-fast +
        # blocked steps, never ordinary retries): verified_label FAILED feeds
        # the causal scorer (_der_score_step_outcome â†’ edge scoring + AVOID
        # episode), task:learning emits the reviewer's signal, and the
        # failure-class graph walk gets its link. All best-effort, never
        # blocking; a fail-fast with no mediator records "none" via the
        # existing _der_mediator_for path (AC11 edge).
        try:
            _gc_learn_reason = str(getattr(item, "error_type", "") or "")
            _gc_learn = False
            if _gc_learn_reason:
                try:
                    from backend.agent import goal_contract as _gc_learn_mod

                    _gc_learn = bool(
                        _gc_learn_mod.is_blocked(_gc_learn_reason)
                    )
                except Exception:
                    _gc_learn = False
            if _gc_learn:
                try:
                    self._der_score_step_outcome(
                        item, "FAILED", _session, str(step_result or "")
                    )
                except Exception:
                    pass
                try:
                    from backend.agent.event_bus import (
                        get_event_bus as _gleb,
                        IRISStreamEvent as _gl_ev,
                    )

                    _gleb().emit(
                        _gl_ev.TASK_LEARNING,
                        {
                            "session_id": _session,
                            "step_id": getattr(item, "step_id", ""),
                            "step_number": getattr(item, "step_number", 0),
                            "signal": "avoided",
                            "verified_label": "FAILED",
                            "description": getattr(item, "description", "") or "",
                            "is_subloop": bool(
                                getattr(item, "is_subloop", False)
                            ),
                            "reason": _gc_learn_reason,
                        },
                    )
                except Exception:
                    pass
                try:
                    _gc_links = getattr(self, "_der_links", None)
                    _gc_rec = getattr(item, "node_record", None)
                    if _gc_links is not None and _gc_rec is not None:
                        # D1: on the memory lane, never the answer path.
                        from backend.utils.durability_queue import lane as _durability_lane

                        _durability_lane("memory_events").submit(
                            "der_node_links", _gc_links.write_node_links,
                            item,
                            _gc_rec,
                            step_success=False,
                            step_result=str(step_result or ""),
                            execution_domain=getattr(
                                _gc_rec, "execution_domain", "der"
                            ),
                            session_id=_session or "",
                        )
                except Exception:
                    pass
        except Exception:
            pass
        if aborted:
            logger.info(
                "[DER] Aborted %d downstream step(s) after failure of %s: %s",
                len(aborted), item.step_id, aborted,
            )
        # Phase 2 (D2.1) + Spec D1.2: critical failure recovery uses the SAME
        # unified _split_step operator as the physics trigger â€” NOT a separate
        # graft path that assigns tools directly. Children carry tool=None and
        # resolve via the single resolver (explorer.propose) when executed, so
        # there is exactly ONE tool-assignment authority (F6 / System Invariant).
        # D4/REQ-4 (specs/long-horizon-der-execution): classify the failure
        # BEFORE recursive fan-out at the FAILURE site too. The finalize site
        # classifies, but this handler previously split on ANY critical
        # failure â€” a rate-limited crawl (transient) or an empty URL list
        # (empty/permanent) recursively spawned graft children that re-ran the
        # same failing tool until the graft budget was exhausted (observed
        # live: 23-minute websearch loop under a saturated provider window).
        # Only a genuine semantic failure (tool produced content but
        # verification judged it wrong) splits: the step_result then carries
        # real content, not an error prefix. Mirror the finalize site: classify
        # only when the result LOOKS like an error (classify_failure never
        # returns semantic â€” it falls through to permanent), and broaden the
        # error prefixes for failure-site shapes ("RateLimitedError(...)" /
        # "ConnectionError(...)" do not start with "error").
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
                or _res_low.startswith("ratelimitederror")
                or _res_low.startswith("connectionerror")
                or _res_low.startswith("timeouterror")
                or _res_low.startswith("[step error")
                or _res_low.startswith("duplicate call")
                # Session-331: the crawler's terminal park/failure shapes were
                # MISSING here, so they fell through _tool_errored=False and the
                # step was treated as a SEMANTIC failure -> grafted a retry that
                # deterministically failed the same way (live T2: crawler_query
                # "no candidate urls" grafted 3x on a search-engine wall). These
                # are environmental/terminal, never semantic.
                or _res_low.startswith("no candidate")
                or _res_low.startswith("no usable")
                or "sources parked" in _res_low
                or "wall=" in _res_low
                or _res_low.startswith("permission")
                or _res_low.startswith("denied")
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
        # Item 3 (2026-09-24, owner-approved): an UNRECOVERABLE failure is not
        # grafted. Live conv-144: a read step failed with "[Errno 2] No such
        # file or directory" and the loop grafted THREE times â€” every sub-loop
        # failed the same way â€” because no retry can create a missing file. One
        # honest failure is the correct outcome; the failure stays recorded and
        # shown (never hidden). Any error here falls through to the graft,
        # preserving the pre-existing behaviour exactly.
        try:
            from backend.agent.tool_decision import _goal_records_terminal_failure

            _terminal_failure = _goal_records_terminal_failure(_res_text)
        except Exception:  # noqa: BLE001 â€” classification must never break recovery
            _terminal_failure = False
        if _terminal_failure:
            logger.info(
                "[DER] critical step %s failed with an unrecoverable cause â€” "
                "no graft, finalizing honestly: %s",
                item.step_id, (_res_text or "")[:120],
            )
            # â”€â”€ FEED recovery_strategy ON THE TERMINAL PATH TOO (2026-09-27) â”€â”€
            # The triage consult lives ONLY on the graft path above, so a
            # terminal failure recorded NO row for recovery_strategy. Measured
            # live: [WinError 3] on an invented path -> "unrecoverable cause -
            # no graft" -> zero recovery rows while TTS announced "I couldn't
            # complete that task. 0/1 steps finished". The consumer was blind to
            # exactly the failures it exists to triage.
            # Safe to consult here: the triage is SHADOW (AC17.1/AC17.2/The
            # documented contract at the graft seam) - it records a row and its
            # verdict decides nothing - so a terminal failure still finalizes
            # honestly, unchanged. A failure that happened is a failure that
            # gets triaged.
            try:
                _tt_box = self._get_tool_box()
                _tt_tool = str(getattr(item, "tool", "") or "")
                _tt_obj = (
                    getattr(item, "objective_anchor", "")
                    or getattr(item, "description", "")
                    or ""
                )
                _tt_box.recovery_strategy(
                    failed_tool=_tt_tool,
                    error_snippet=str(_res_text or "")[:200],
                    objective=_tt_obj,
                )
            except Exception as _tt_err:  # noqa: BLE001 â€” advisory only
                logger.debug(
                    "[DER] terminal-failure triage consult failed: %r", _tt_err
                )
        # ONE repair per failure: the node router may already have queued a
        # recovery step for it (_der_enqueue_recovery, the dead-fetch crawl).
        # The graft split ran beside it with no check - two crews on one
        # failure (ripple map, 2026-10-12).
        _recovery_queued = any(
            getattr(_qi, "recovery_of", "") == item.step_id
            for _qi in (getattr(queue, "items", None) or ())
        )
        if _recovery_queued:
            logger.info("[DER] %s failed - a recovery step is queued; no graft split",
                        item.step_id)
        if (
            _split_ok
            and item.critical
            and not _terminal_failure
            and not _recovery_queued
            and queue.graft_attempts < DER_MAX_GRAFTS
        ):
            # â”€â”€ Session 247: GOAL-SUFFICIENCY GATE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Before grafting another round of gather children, ask the one
            # question the loop never asked: do the findings ALREADY collected
            # satisfy the objective? Live evidence (conv-41, session 247): a
            # websearch task ran 18 dispatch rounds over 30+ minutes because
            # every verify_failed grafted more search steps even after the
            # crawls had returned plenty of usable content â€” per-step
            # verification could see each step in isolation, but nothing ever
            # assessed goal-level sufficiency of the accumulated whole. When
            # the gate says sufficient, skip the graft: the loop proceeds to
            # synthesis over what it has (the failed step stays recorded as a
            # failure â€” failure recorded AND shown, never hidden).
            # Advisory on failure: any gate error falls through to the graft,
            # preserving the pre-existing behavior exactly.
            # What the step DID (_step_calls), not item.tool: a node step has
            # no tool (since 2026-09-29), so this gate - and the `sufficient`
            # consumer behind it - never ran again (last row 2026-09-29;
            # found 2026-11-10).
            if any(str(c.get("tool") or "").lower() in self._DER_GATHER_TOOLS
                   for c in _step_calls(item)):
                try:
                    # Session 248 FIX (live conv-53): the gate digested only
                    # COMPLETED steps - but the failed step ITSELF may carry
                    # the findings (a crawler_query that fetched 3 usable
                    # pages yet failed verification). Excluding it made the
                    # gate judge an empty evidence set, graft a full re-crawl
                    # of the SAME query, and double the search time. The
                    # failing step's own result is appended to the digest so
                    # the gate sees everything the loop has actually seen.
                    # Session 365 FIX: `completed_items` is NOT a parameter of
                    # this method â€” it is a local of `_execute_plan_der` â€” so
                    # this line raised NameError on EVERY failed gather step.
                    # The bare `except` below swallowed it, so the gate
                    # silently returned False forever: `_der_findings_sufficient`
                    # was never actually called and the `sufficient` consumer
                    # could never emit a row, no matter how much gather traffic
                    # was driven at it. Reconstruct the completed items from the
                    # queue, exactly as the rest of this file does
                    # (`step_id in queue.completed_ids`, cf. the step-status
                    # derivation and the budget-exhausted remaining count).
                    _completed_ids = set(
                        getattr(queue, "completed_ids", None) or ()
                    )
                    _gate_items = [
                        _gi for _gi in (getattr(queue, "items", None) or ())
                        if getattr(_gi, "step_id", None) in _completed_ids
                    ] + [item]
                    _suff, _missing = self._der_findings_sufficient(
                        plan.original_task or "", _gate_items
                    )
                except Exception:
                    _suff, _missing = False, ""
                if _suff:
                    logger.info(
                        "[DER] sufficiency gate TRIPPED for %s â€” accumulated "
                        "findings satisfy the objective; graft skipped "
                        "(missing: %s)", item.step_id, (_missing or "none")[:120],
                    )
                    return aborted
                logger.debug(
                    "[DER] sufficiency gate open for %s (missing: %s)",
                    item.step_id, (_missing or "unassessed")[:120],
                )
            try:
                # Fold-back: split width is a shape decision (side lane).
                _der_physics_settle(self, _session)
                _cad = self._der_live_cad_state(_session)
                _wu = getattr(self, "_der_work_units", 0)
                # REQ-4 AC1 (T16): continuous verified fraction as a GRADED
                # steering input at the split decision (mid-band -> bounded
                # probe). Never crash the split on fraction failure.
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
                    _cad,
                    _wu,
                    step_result=step_result,
                    verified_fraction=_vf_split,
                )
                if _children:
                    # REQ-5 (dag-node-execution-model): grafted recovery steps
                    # ARE an amendment of the executing graph, so they go
                    # through the amendment gate rather than around it. This is
                    # _der_amend_graph's production caller â€” without one the
                    # mechanism was built, tested and unreachable.
                    #
                    # Behaviour is unchanged by construction: _AMENDMENT_BOUND
                    # and DER_MAX_GRAFTS are both 3, so the gate admits exactly
                    # the grafts that already ran. What it adds is REQ-5's
                    # guarantees on a path that previously had none â€” validity
                    # checking, the per-task bound, and telemetry for every
                    # applied AND refused amendment (REQ-5 AC5, REQ-9 AC3).
                    if not self._der_amend_graph(
                        _children, _session, plan, queue, _turn_id=_turn_id,
                    ):
                        logger.info(
                            "[DER] amendment refused for failed %s â€” continuing "
                            "on the existing graph (REQ-5 AC5)", item.step_id,
                        )
                        return aborted
                    queue.graft_attempts += 1
                    # The gate queued the children themselves; they run as
                    # nodes (their own tool loops). Routing them again here
                    # queued each child twice.
                    # Fold-back (parallel nodes, 2026-10-04): the failed step
                    # waits for its children instead of failing, and the
                    # dependents its failure aborted wait again - the first
                    # VERIFIED child completes it (_der_settle_split).
                    queue.hold_split_parent(
                        item.step_id, [c.step_id for c in _children], aborted,
                    )
                    aborted = []
                    # REQ-3: debit measured tokens, not a flat child count.
                    _result_len = len(step_result) if step_result else 0
                    _measured = max(200, _result_len // 4)
                    self._der_work_units = debit_work_units(_wu, _measured)
                    try:
                        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
                        get_event_bus().emit(
                            IRISStreamEvent.RECOVERY_START,
                            data={
                                "failed_step": item.step_id,
                                "graft_attempts": queue.graft_attempts,
                                "num_grafted": len(_children),
                                "critical": item.critical,
                            },
                            session_id=_session,
                        )
                    except Exception:
                        pass
                    logger.info(
                        "[DER] Critical-failure recovery -> split into %d sub-loop(s) "
                        "for failed %s (graft_attempts=%d, work_units=%d)",
                        len(_children), item.step_id, queue.graft_attempts,
                        self._der_work_units,
                    )
            except Exception as _graft_exc:
                logger.warning("[DER] critical-failure split failed: %s", _graft_exc)
        # â”€â”€ REQ-5 (specs/long-horizon-der-execution): honest partial finalization â”€â”€
        # When the recovery budget is exhausted, the task does NOT block on a
        # TASK_BLOCKED card / ask_user QuestionCard (that escalation came from
        # the deleted der-loop-integrity-display REQ-10; the long-horizon spec
        # supersedes it: "IF budget ends before completion THEN emit remaining
        # nodes and their last failure class"). The step is already marked
        # failed, descendants already aborted, failure evidence already
        # recorded â€” the DER loop's final summary carries the remaining nodes
        # with their failure classes and the honest incomplete result.
        # Not when THIS failure just spent the last graft: the step waits on
        # its children then (live amend-7, 2026-10-12: this line said
        # "finalizing honestly" in the same second the third graft ran).
        if (item.critical and queue.graft_attempts >= DER_MAX_GRAFTS
                and item.step_id not in (getattr(queue, "split_pending", None) or {})):
            logger.info(
                "[DER] REQ-5: critical step %s failed after %d grafts â€” "
                "finalizing honestly with remaining nodes + failure class",
                item.step_id, queue.graft_attempts,
            )
        # M2 FIX: record non-critical failures to memory and signal Caducean
        # so drift detection accounts for them (otherwise Q never rises on
        # repeated non-critical failures and TOPO_VIOLATION never fires).
        # PACMAN alignment: a failure pattern is the user's own hard-won lesson
        # (corrective action encoded) -> it belongs in the TRUSTED membrane
        # (PACMAN.md: trusted://episodic/failures, Tier 3), NOT an off-membrane
        # "der_failure" zone the router cannot navigate/tier. chunk_type stays
        # "der_failure" as the content-type discriminator; zone is the membrane.
        if not item.critical:
            try:
                if self._memory_interface and item.result:
                    _ep = self._memory_interface.episodic
                    if hasattr(_ep, "fragment_and_store"):
                        # D1: on the memory lane, never the answer path.
                        from backend.utils.durability_queue import lane as _durability_lane

                        _durability_lane("memory_events").submit(
                            "der_failure_fragment", _ep.fragment_and_store,
                            content=f"[NON-CRITICAL FAIL Step {item.step_number}: "
                                    f"{item.description[:80]}]\n{item.result[:500]}",
                            session_id=_session,
                            chunk_type="der_failure",
                            zone="trusted",
                        )
            except Exception as _frag_exc:  # noqa: BLE001 - a note never blocks the loop
                logger.warning("[DER] non-critical der_failure note for %s failed: %r",
                               item.step_id, _frag_exc)
            try:
                from backend.gateway.iris_ffi import ffi_caducean_update

                # REQ-19 vocabulary: this "COMPRESS" (action=1) is the COMPRESS
                # RECOMMENDATION â€” a physics action code that increments the
                # failure accumulator y. It COMPACTS NOTHING. See the REQ-19
                # canonical-vocabulary table in
                # specs/long-horizon-der-execution/design.md (row 3) â€” it is
                # NOT Node Condense, NOT DCP message pruning, NOT mcm_compress.
                ffi_caducean_update(_session, 1, 1.0)
            except Exception:
                pass

    def _der_findings_sufficient(
        self, objective: str, completed_items: List[Any]
    ) -> tuple:
        """
        Session 247: goal-level sufficiency check â€” the mindful-search gate.

        DER's per-step verifier grades each step in isolation; nothing ever
        asked whether the ACCUMULATED findings already answer the user's
        question. This method does exactly that, once, at the graft decision:
        a bounded digest of completed step results plus the objective goes to
        one cheap reasoning call, which answers
              {"sufficient": bool, "missing": "..."}
        True  -> the caller skips grafting more gather rounds and lets the
                 loop finalize over what it has.
        False -> graft proceeds (missing aspects are logged for targeting).

        NEVER raises. On any inference/parse failure returns (False, "") so
        the gate is advisory and pre-existing behavior is preserved â€” a broken
        gate must not change loop semantics, only a working one may.
        """
        import re as _re2

        if not completed_items:
            return False, ""
        # Bounded digest: head+tail excerpt per result, newest last, capped so
        # the prompt stays small regardless of how many steps completed.
        _parts: List[str] = []
        for _idx, _it in enumerate(completed_items[-6:]):
            _txt = (getattr(_it, "result", "") or "")[:1200]
            if not _txt:
                continue
            _parts.append(f"[{_idx + 1}] {self._smart_excerpt(_txt, 600)}")
        if not _parts:
            return False, ""
        _digest = "\n".join(_parts)
        _prompt = (
            f"OBJECTIVE: {objective[:500]}\n\n"
            f"FINDINGS COLLECTED SO FAR:\n{_digest}\n\n"
            "Do the findings above contain enough information to satisfy the "
            "objective on their own? Judge as a strict editor: sufficient means "
            "the objective could be answered NOW without any further searching.\n"
            'Reply with JSON only: {"sufficient": true or false, "missing": '
            '"what is still missing, or empty string"}'
        )
        try:
            _raw = self.infer(_prompt, role="reasoning", max_tokens=100, temperature=0.0)
            _m = _re2.search(r"\{[\s\S]+\}", _raw.raw_text or "")
            if not _m:
                return False, ""
            _data = json.loads(_m.group())
            _brain_sufficient = bool(_data.get("sufficient"))
            _brain_missing = str(_data.get("missing", ""))[:300]
        except Exception as _gate_exc:
            logger.debug("[DER] sufficiency gate inference failed: %s", _gate_exc)
            return False, ""

        # REQ-14 AC14.1 (T18): shadow-score the `sufficient` consumer and emit
        # the row. The BRAIN's answer still decides, and the gate stays
        # advisory-FAIL-CLOSED (AC14.4): `sufficiency_gate` returns (False, "")
        # on any failure, exactly the shape this method already had. The engine
        # never writes the `missing` text (AC14.2).
        try:
            from backend.agent import monitor_shadow as _ms
            from backend.agent.decision_engine import decides, oracle_acts

            # Stage B: only the chokepoint lets the Oracle replace the Brain's
            # bit; otherwise the score runs on the lane (off the reply path).
            _dec = decides("sufficient") is not None
            _value, _missing = _ms.sufficiency_gate(
                _prompt,
                brain_bool_fn=lambda: _brain_sufficient,
                brain_text_fn=lambda: _brain_missing,
                engine=_ms.AUTO_ENGINE,
                # defer is ignored once enforced: a deciding consumer is waited for.
                enforced=_dec, defer=True,
                acts=lambda c: oracle_acts("sufficient", c),
            )
            return _value, _missing
        except Exception:  # noqa: BLE001 â€” the gate is advisory
            return _brain_sufficient, _brain_missing

    @classmethod
    def _declared_file_names(cls, text: str) -> list:
        """File names named in the text â€” ordered, deduped, bounded to 8.

        Pure: the caller decides which of them are actually missing.
        """
        out: list = []
        seen: set = set()
        for match in cls._ARTIFACT_NAME_RE.finditer(text or ""):
            name = match.group(0)
            low = name.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append(name)
        return out[:8]

    @staticmethod
    def _artifact_missing(name: str, base: str = "") -> bool:
        """True when the named artifact is absent, or present but empty. A
        relative name is resolved against ``base`` (the session's project
        folder, where node steps write) when one is given."""
        try:
            from pathlib import Path

            p = Path(name)
            if base and not p.is_absolute():
                p = Path(base) / p
            return not (p.exists() and p.stat().st_size > 0)
        except OSError:
            return True

    def _der_graft_missing_artifacts(
        self,
        item,
        plan,
        queue,
        _session: str,
        _turn_id: str,
        _token_budget: int = 0,
        _tokens_used: int = 0,
    ) -> int:
        """Graft a step per artifact the task named but nothing wrote.

        Called after a FILE-WRITING step finalizes. Bounded three ways: only for
        file-writing tools, at most DER_MAX_GRAFTS steps per run, and each file
        name is attempted at most once (``_artifact_graft_attempted``). Never
        raises — a missed graft must not break the turn.

        Returns the number of steps grafted. A non-zero count means this step's
        tool choice did not finish the job, so its tool_choice rows are labelled
        as a retry (tc-decide-v7).
        """
        try:
            # What the step DID (_step_calls), not item.tool: a node step has no
            # tool, so this graft never ran on node work (DER_DAG.md seam 2).
            if not any(
                str(c.get("tool") or "").lower()
                in ("write_file", "create_directory", "edit_file", "append_file")
                and c.get("ok", True)
                for c in _step_calls(item)
            ):
                return 0
            from backend.agent.der_constants import DER_MAX_GRAFTS

            # Node steps write in the session's project folder, not the
            # backend's working directory.
            _base_dir = str(
                (getattr(getattr(self, "_tool_bridge", None), "_session_workdirs", None) or {})
                .get(_session, "") or ""
            )

            _attempted = getattr(self, "_artifact_graft_attempted", None)
            if _attempted is None:
                _attempted = set()
                self._artifact_graft_attempted = _attempted
            if len(_attempted) >= DER_MAX_GRAFTS:
                return 0
            _task_text = str(getattr(plan, "original_task", "") or "")
            _text = " ".join([_task_text, str(getattr(item, "description", "") or "")])
            _done = set(getattr(queue, "completed_ids", ()) or ()) | set(
                getattr(queue, "failed_ids", ()) or ())
            _queued_text = " ".join(
                str(getattr(_it, "description", "") or "")
                for _it in (getattr(queue, "items", []) or [])
                if getattr(_it, "step_id", None) not in _done
                and getattr(_it, "step_id", None) != getattr(item, "step_id", None)
            )
            _missing = [
                n for n in self._declared_file_names(_text)
                if n not in _attempted and self._artifact_missing(n, _base_dir)
                # a step still in the queue names it: that step will write it
                and n not in _queued_text
            ][: max(DER_MAX_GRAFTS - len(_attempted), 0)]
            if not _missing:
                return 0
            # A template helps the model produce the same shape the user asked for
            # ("each with one bullet about tea") and guarantees a body is written.
            _template = ""
            for _n in self._declared_file_names(_text):
                if not self._artifact_missing(_n, _base_dir):
                    try:
                        from pathlib import Path

                        _template = (Path(_base_dir) / _n if _base_dir else Path(_n)).read_text(
                            encoding="utf-8", errors="replace"
                        )[:200]
                    except OSError:
                        _template = ""
                    if _template:
                        _sibling = _n
                        break
            else:
                _sibling = ""

            from backend.agent.der_loop import QueueItem

            _base = len(getattr(queue, "items", []) or [])
            _new_steps = [
                QueueItem(
                    step_id="%s_art%d" % (item.step_id, _i),
                    step_number=_base + _i,
                    # tool stays UNSET: ToolDecisionBox.resolve is
                    # description-driven (tool_decision.resolve reads
                    # step["description"] as its goal). A preset tool with no
                    # params produced no call at all in the first live attempt.
                    description=(
                        "Create the file {name} with the content the user asked for "
                        "in this task: {task}{like}".format(
                            name=_name,
                            task=_task_text[:300],
                            like=(
                                ". Write the same style of content as {sib}, which "
                                "contains: {tpl}".format(sib=_sibling, tpl=_template)
                                if _template else ""
                            ),
                        )
                    ),
                    depends_on=[item.step_id],
                    critical=False,
                    objective_anchor=_task_text[:200],
                    # Mirror the PARENT step's expected output: the run grade
                    # reads each step's expected_output against its result, and a
                    # bespoke claim here ("X exists and is not empty") matched
                    # neither the result nor the parent's, capping the whole run
                    # and telling the user the task had failed when the files
                    # were on disk. Same claim shape, same verdict.
                    expected_output=getattr(item, "expected_output", None),
                    declared_criticality="supporting",
                    node_record=getattr(item, "node_record", None),
                )
                for _i, _name in enumerate(_missing, start=1)
            ]
            if not self._der_amend_graph(
                _new_steps, _session, plan, queue,
                _token_budget=_token_budget, _tokens_used=_tokens_used,
                _turn_id=_turn_id,
            ):
                return 0
            _attempted.update(_missing)
            try:
                queue.graft_attempts += 1
            except Exception:
                pass
            logger.info(
                "[DER] partial artifacts: grafted %d step(s) for %s "
                "(one step = one tool call, so a multi-file step needs the rest)",
                len(_missing), _missing,
            )
            return len(_missing)
        except Exception as _graft_exc:
            logger.warning("[DER] artifact graft skipped: %s", _graft_exc)
        return 0
