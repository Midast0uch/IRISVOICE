# Moved from backend/agent/agent_kernel.py by scripts/kernel_split_check.py move.
# Bodies are byte-identical to the originals (guard: kernel_split_check.py manifest --check).
from __future__ import annotations

import re
import threading
from typing import Any, Dict, Optional, List, Callable, Tuple, Sequence
import time
from backend.utils.observability import (
    TurnMetrics,
    loud_error,
    get_turn_id,
    broadcast_inference_event,
)
from backend.agent.kernel.base import (
    _der_fold_envelope,
    _der_recall_delivered,
    _emit_event,
    _step_tool,
    _update_counters,
    _update_counters_lock,
    logger,
)


def _der_physics_settle(owner, session_id: str) -> None:
    """Fold-back point of the physics side lane.

    Call this right before a DECISION about the next step's shape reads the
    Caducean state (split width, stuck-streak topology override, plan
    expansion under COMPRESS). It waits until this session's newest update
    has moved the integrator (``fold.ready``; FIFO, so every earlier update
    moved it first) â€” not for that job's bookkeeping. Past
    DER_PHYSICS_FOLD_WAIT_S the decision proceeds on the last settled
    position; the update itself is never cancelled.
    """
    pending = getattr(owner, "_der_physics_pending", None)
    fold = pending.get(session_id) if pending else None
    if fold is None or fold.ready.is_set():
        return
    from backend.utils.durability_queue import lane

    if lane("physics").in_worker():
        return  # the lane never waits on work queued behind itself
    from backend.agent.der_constants import DER_PHYSICS_FOLD_WAIT_S

    t0 = time.monotonic()
    landed = fold.ready.wait(DER_PHYSICS_FOLD_WAIT_S)
    waited = time.monotonic() - t0
    if not landed:
        logger.warning(
            "[DER] physics fold-back session=%s step=%s not landed after %.1fs "
            "- deciding on the last settled position",
            session_id, fold.step, waited,
        )
    elif waited >= 0.5:
        logger.info(
            "[DER] physics fold-back session=%s step=%s waited %.2fs",
            session_id, fold.step, waited,
        )

def _der_settle_split(self, item, queue, inflight) -> None:
    """The split race (owner 2026-10-04): when a split child settles, the
    first VERIFIED child completes its parent (the parent's dependents run
    on) and its siblings stop; when every child failed the parent fails and
    its dependents are aborted. Recurses up a nested split."""
    _cur = item
    while _cur is not None and queue.parent_of_split_child(_cur.step_id):
        _parent_id = queue.parent_of_split_child(_cur.step_id)
        _kids = list(queue.split_pending.get(_parent_id, []))
        _rec = getattr(_cur, "node_record", None)
        _verified = (_cur.step_id in queue.completed_ids
                     and getattr(_rec, "outcome", "") == "VERIFIED")
        _closed = queue.settle_split(_cur.step_id, _verified)
        if _closed is None:
            return
        _pid, _outcome, _winner = _closed
        logger.info("[DER] split %s resolved: %s (winner=%s)", _pid, _outcome, _winner)
        for _k in _kids:
            if _k == _winner or _k in queue.completed_ids or _k in queue.failed_ids:
                continue
            _sib = next((it for it in queue.items if it.step_id == _k), None)
            if _sib is None:
                continue
            _sib._race_lost = f"sibling {_winner} resolved the blocker"
            if _k not in inflight:  # not started: it never will
                _sib.result = f"[not needed: {_sib._race_lost}]"
                queue.mark_complete(_k)
        _cur = next((it for it in queue.items if it.step_id == _pid), None)


class DerPhysicsMixin:
    def _growth_width(self, u: float) -> int:
        """Map live |u| to a split width (MorphoHDL athlete rule).

        REQ-19 vocabulary: this is STEP EXPANSION â€” the DER sub-loop split
        operator (_growth_width -> _split_step). It is NOT Node Expansion
        (scorer.expand, the mycelium coordinate-graph mechanism), NOT DER
        "COMPRESS" (a physics recommendation code, int 1), NOT DCP message
        pruning, and NOT mcm_compress (external build tooling). See the REQ-19
        vocabulary table in specs/long-horizon-der-execution/design.md.

        Bands (reconciles D2.3 with the split decision):
          |u| < U_SPLIT (0.5)   -> unresolved/oscillating -> split WIDE (3)
          U_SPLIT <= |u| < 0.85 -> mid-band: atomic step, needs LLM rubric (D2.3)
          |u| >= 0.85           -> converged: atomic, deterministic verify only
        """
        from backend.agent.der_constants import U_SPLIT, U_CONVERGED

        au = abs(u)
        if au < U_SPLIT:
            return 3
        if au < U_CONVERGED:
            return 1  # atomic; verification strictness handled by D2.3
        return 1

    def _der_split_width(self, u: float, verified_fraction: float) -> int:
        """REQ-4 AC1/AC2 (T16): GRADED split width â€” a continuous function of
        BOTH |u| and the verified fraction, not a |u|-only gate.

        The pre-T16 split width was binary in the verification dimension:
        ``_growth_width(u)`` returned 3 (wide) or 1 (atomic) purely from |u|,
        while ``verified_fraction`` was computed and then thrown away at the
        split decision. REQ-4 AC1 requires the continuous fraction to be a
        steering input; AC2 requires the graded middle path when the signal is
        mid-band â€” never a threshold coin-flip.

        Bands:
          verified_fraction <= 0.25            -> strong failure: |u| governs
                                                  (delegate to _growth_width)
          0.25 < verified_fraction < 0.75      -> MID-BAND (AC2): bounded probe
                                                  (width 1, probe=True) â€” the
                                                  step produced meaningful but
                                                  insufficient content; a wide
                                                  split would be a retry wearing
                                                  a split costume. The child
                                                  resolves the specific blocker
                                                  (REQ-4 AC4/T16b) at width 1.
          verified_fraction >= 0.75            -> near-pass: atomic (1) â€” the
                                                  result satisfied most of the
                                                  expected output; a wide split
                                                  spends budget re-attempting a
                                                  step that nearly passed.

        The caller marks the child ``probe=True`` when this method returns a
        width-1 mid-band probe (see _split_step).
        """
        if verified_fraction > 0.25:
            if verified_fraction < 0.75:
                return 1  # AC2 graded middle path: bounded probe, not a flip
            return 1  # near-pass: atomic
        return self._growth_width(u)  # strong failure: |u| bands govern

    def _der_surface_branch_candidates(
        self, item, cad: Optional[Dict[str, float]] = None, max_candidates: int = 0
    ) -> List[dict]:
        """REQ-5 AC1/AC3 (T17): rank relevant branch candidates and return ALL
        of them (bounded by the candidate cap) â€” never one, never pre-selected.

        Ranking is physics- and evidence-driven (AC3):
          - coordinate proximity to the step's live Î£ position,
          - learned score of the region->candidate edge (if one exists),
          - compression/expansion state via the EXISTING coupling kernel
            ``trig_coupling.align_force`` (AC6 â€” reuse, do not write a second
            implementation): the u term biases candidates whose phase aligns
            with the step's current direction.

        SELECTION is NOT made here â€” the step decides with all candidates in
        view; the chosen one is recorded at commit (see
        ``_der_record_coupling_decision``).

        Returns a list of dicts ``{"node_id", "label", "score"}`` capped at
        ``max_candidates`` (0 -> DER_COUPLING_CANDIDATE_CAP). Never raises:
        any failure returns [] so coupling can never block a step (REQ-10 AC5).
        """
        from backend.agent.der_constants import DER_COUPLING_CANDIDATE_CAP
        from backend.agent.trig_coupling import align_force

        cap = max_candidates or DER_COUPLING_CANDIDATE_CAP
        if cap < 1:
            return []
        if not getattr(self, "_memory_interface", None):
            return []
        try:
            _cad = cad if cad is not None else self._der_live_cad_state(
                self.session_id or ""
            )
            _vec = [
                _cad.get("x", 0.0), _cad.get("y", 0.0),
                _cad.get("xi", 0.0), _cad.get("u", 0.0),
            ]
            _u = _cad.get("u", 0.0)
            # AC6: the EXISTING coupling kernel â€” the u-term in the ranking is
            # align_force as WIRED at coupled_registry.py:287 (full phase list
            # [self, other], N=2 satisfies the mean-field guard; the self term
            # contributes sin(0)=0). The u-term is the signed attraction of the
            # step's phase toward the converged phase 0.0 â€” NOT a new formula.
            _align = align_force(_u, [_u, 0.0], k=1.0)
            # physics term normalized to [0, 1]: aligned (u>0, expanding toward
            # convergence) scores higher; anti-aligned (u<0, compressing) lower.
            _phys = 0.5 + 0.5 * max(-1.0, min(1.0, _align))
            _session = self.session_id or ""
            myc = getattr(self._memory_interface, "_mycelium", None)
            if myc is None:
                return []
            _store = getattr(myc, "_store", None)
            _nav = getattr(myc, "_navigator", None)
            _nodes = []
            # Primary candidate source: the highest-confidence node from each
            # space (navigate_all_spaces) â€” the relevant BRANCHES, one per
            # space. Fallback: active registry nodes.
            try:
                if _nav is not None and hasattr(_nav, "navigate_all_spaces"):
                    _nodes = list(_nav.navigate_all_spaces(_session))
            except Exception:
                _nodes = []
            if not _nodes:
                try:
                    _reg = getattr(myc, "_registry", None)
                    _nids = list(getattr(_reg, "get_active", lambda s: [])(_session))
                    if _nids and _store is not None:
                        _nodes = [
                            _store.get_node_by_id(_nid)
                            for _nid in _nids
                            if _store.get_node_by_id(_nid) is not None
                        ]
                except Exception:
                    _nodes = []
            _nodes = [_c for _c in (_nodes or []) if getattr(_c, "coordinates", None)]
            if not _nodes:
                return []

            _scored = []
            for _n in _nodes:
                try:
                    _coords = list(getattr(_n, "coordinates", None) or [])
                    if len(_coords) < 4:
                        continue
                    _d = sum((a - b) ** 2 for a, b in zip(_vec, _coords[:4])) ** 0.5
                    _prox = max(0.0, 1.0 - _d / 4.0)  # normalized proximity
                    _learned = 0.0
                    _nid = getattr(_n, "node_id", "") or getattr(_n, "id", "") or ""
                    # learned edge score from the region node -> candidate, if
                    # the edge exists (evidence-driven ranking).
                    try:
                        _reg_nid = self._der_region_node_id(_session)
                        if _reg_nid and _nid:
                            _edge = _store.get_edge_by_id(
                                f"{_reg_nid}:{_nid}"
                            ) if hasattr(_store, "get_edge_by_id") else None
                            if _edge is not None:
                                _learned = float(getattr(_edge, "score", 0.0) or 0.0)
                    except Exception:
                        _learned = 0.0
                    _score = _prox * 0.6 + _learned * 0.3 + _phys * 0.1
                    _scored.append({
                        "node_id": _nid,
                        "label": (getattr(_n, "label", None) or _nid)[:120],
                        "score": _score,
                    })
                except Exception:
                    continue
            _scored.sort(key=lambda c: c["score"], reverse=True)
            # REQ-5 AC5 (T17b): record the TOTAL number of relevant branches
            # found (BEFORE the cap) on the item â€” the coverage DENOMINATOR
            # for candidate-surfacing coverage ("how often a decision saw >=2
            # candidates when >=2 EXISTED"). candidates_surfaced is the capped
            # return; candidates_existed is the uncapped count. Both are needed
            # or the coverage metric cannot be measured.
            try:
                item._coupled_candidates_existed = len(_scored)
            except Exception:
                pass
            return _scored[:cap]
        except Exception as _cp_exc:  # noqa: BLE001 â€” coupling never blocks
            logger.debug("[DER] branch-candidate surfacing failed: %s", _cp_exc)
            return []

    def _der_region_node_id(self, session_id: str) -> str:
        """The mycelium node_id of the session's CURRENT region node (the ONE
        active node nearest the live Î£ position â€” REQ-26 AC1 region scoping).
        Empty string if none resolvable. Never raises."""
        try:
            myc = getattr(self._memory_interface, "_mycelium", None)
            if myc is None:
                return ""
            _reg = getattr(myc, "_registry", None)
            if _reg is None:
                return ""
            _nids = list(getattr(_reg, "get_active", lambda s: [])(session_id))
            if not _nids:
                return ""
            _store = getattr(myc, "_store", None)
            if _store is None or not hasattr(_store, "get_node_by_id"):
                return ""
            _cad = self._der_live_cad_state(session_id)
            _vec = [
                _cad.get("x", 0.0), _cad.get("y", 0.0),
                _cad.get("xi", 0.0), _cad.get("u", 0.0),
            ]
            _best, _best_d = "", None
            for _nid in _nids:
                try:
                    _n = _store.get_node_by_id(_nid)
                    if _n is None:
                        continue
                    _c = list(getattr(_n, "coordinates", None) or [])
                    if len(_c) < 4:
                        continue
                    _d = sum((a - b) ** 2 for a, b in zip(_vec, _c[:4])) ** 0.5
                    if _best_d is None or _d < _best_d:
                        _best, _best_d = _nid, _d
                except Exception:
                    continue
            return _best
        except Exception as _reg_exc:  # noqa: BLE001
            logger.debug("[DER] region-node resolve failed: %s", _reg_exc)
            return ""

    def _der_record_governance(self, source: str) -> None:
        """REQ-6 AC1/AC3 (T18): record WHICH signal governed a steering
        decision â€” past-memory | live-state | both.

        Increments the per-turn governance counter on the kernel (read by the
        caller's TurnMetrics block into the [LAYERS] line). Off the hot path
        and lossy-safe: any failure is logged at debug and never raises, and a
        missing counter silently re-initializes (AC1 edge: high-volume turns).
        The alternation ratio (AC3) is derived in TurnMetrics.to_log_line from
        the same counts.

        No decision path hardcodes which signal is authoritative (AC2): the
        recorded source is OBSERVED at the decision point â€” a step whose
        context carried a compressed node record (past-memory) AND live Î£ is
        "both"; memory-sparse (no record) is "live"; record present but no
        live signal is "past".
        """
        try:
            _gov = getattr(self, "_der_governance_counts", None)
            if _gov is None:
                _gov = {"past": 0, "live": 0, "both": 0}
            if source == "past":
                _gov["past"] = _gov.get("past", 0) + 1
            elif source == "live":
                _gov["live"] = _gov.get("live", 0) + 1
            else:  # "both" (and any unknown -> both, the equal-signals edge)
                _gov["both"] = _gov.get("both", 0) + 1
            self._der_governance_counts = _gov
        except Exception as _gov_exc:  # noqa: BLE001
            logger.debug("[DER] governance record failed: %s", _gov_exc)

    def _der_choose_coupling_branch(
        self, item, candidates: List[dict]
    ) -> str:
        """REQ-5 AC4 (T17): determine which surfaced branch the step CHOSE.

        Selection is the step's, not the system's (the rewritten REQ-5 story:
        "awareness of the alternatives, and a recorded decision, is [the
        system's business]"). The step's choice is observed from the outcome:
        the chosen branch is the candidate whose coordinates are nearest the
        step's final Î£ position (``coords_to``), i.e. the branch the step's
        result actually moved toward. Empty string when no candidate is
        nearest (no branches existed / no coords). Never raises.
        """
        from backend.agent.der_constants import DER_COUPLING_CANDIDATE_CAP

        if not candidates:
            return ""
        try:
            _coords_to = getattr(item, "coords_to", "") or ""
            _session = self.session_id or ""
            myc = getattr(self._memory_interface, "_mycelium", None)
            _store = getattr(myc, "_store", None) if myc else None
            if _coords_to and _store is not None and hasattr(
                _store, "get_node_by_id"
            ):
                _v = []
                for _part in _coords_to.strip("()").split(","):
                    try:
                        _v.append(float(_part))
                    except Exception:
                        break
                if len(_v) >= 4:
                    _best, _best_d = "", None
                    for _c in candidates[:DER_COUPLING_CANDIDATE_CAP]:
                        _nid = _c.get("node_id", "")
                        if not _nid:
                            continue
                        try:
                            _n = _store.get_node_by_id(_nid)
                            _cvec = list(getattr(_n, "coordinates", None) or [])
                            if len(_cvec) < 4:
                                continue
                            _d = sum(
                                (a - b) ** 2 for a, b in zip(_v, _cvec[:4])
                            ) ** 0.5
                            if _best_d is None or _d < _best_d:
                                _best, _best_d = _nid, _d
                        except Exception:
                            continue
                    return _best
            # No resolvable coordinates: fall back to the top-ranked candidate
            # (the ranking is physics- and evidence-driven, AC3) so a decision
            # is still RECORDED â€” an empty choice would be an unrecorded one.
            return (candidates[0].get("node_id", "") if candidates else "")
        except Exception as _ch_exc:  # noqa: BLE001
            logger.debug("[DER] coupling-branch choice failed: %s", _ch_exc)
            return ""

    def _der_record_coupling_decision(
        self,
        item,
        candidates: List[dict],
        chosen_node_id: str = "",
        record: Optional["NodeRecord"] = None,
    ) -> None:
        """REQ-5 AC2/AC4 (T17): record a coupling decision AFTER the step
        commits. ``candidates`` is the surfaced list (all of them, capped);
        ``chosen_node_id`` is the branch the step actually committed to.

        AC2: write/strengthen the coupling edge from the step's region node to
        the chosen branch â€” the decision IS the edge's provenance. Uses the
        SAME edge store/scorer as the region->mediator learning (one store,
        one scorer â€” REQ-19 AC4); a decision is a strengthenable observation,
        not a new edge kind.
        AC4: candidates_surfaced / chosen_branch / surfaced_branches are
        stamped on the node record so "was the agent aware of both branches"
        is answerable from data. Never raises: coupling is off the critical
        path (REQ-10 AC5).
        """
        from backend.agent.der_constants import DER_COUPLING_PROVENANCE_MAX

        try:
            _count = len(candidates or [])
            _chosen = chosen_node_id or ""
            if not _count and not _chosen:
                return  # no coupling decision at this node
            _rec = record or getattr(item, "node_record", None)
            if _rec is not None:
                _rec.candidates_surfaced = _count
                _rec.chosen_branch = _chosen
                # REQ-18 AC1b (T19): a node that SURFACED >=1 candidate and
                # CHOSE one is a node that COMMITTED A DECISION â€” a valid
                # coupling endpoint. This is the ROLE marker that makes
                # "which decisions were informed by branch X" a relationship
                # lookup (REQ-20) instead of a table scan. Set only here, at
                # the coupling-decision site, so gathering/executing nodes
                # stay unmarked.
                if _count > 0:
                    _rec.committed_decision = True
                _rec.surfaced_branches = [
                    c.get("label", "") for c in (candidates or [])
                ][:DER_COUPLING_PROVENANCE_MAX]
                # REQ-5 AC5 (T17b): the DENOMINATOR for candidate-surfacing
                # coverage â€” how many relevant branches EXISTED before the cap.
                # candidates_surfaced / candidates_existed is the coverage ratio
                # ("saw >=2 when >=2 existed").
                try:
                    _rec.candidates_existed = int(
                        getattr(item, "_coupled_candidates_existed", _count) or _count
                    )
                except Exception:
                    _rec.candidates_existed = _count
            if _chosen:
                try:
                    _session = self.session_id or ""
                    _reg_nid = self._der_region_node_id(_session)
                    if _reg_nid:
                        myc = getattr(self._memory_interface, "_mycelium", None)
                        _store = getattr(myc, "_store", None) if myc else None
                        if _store is not None and hasattr(
                            _store, "record_observation"
                        ) and hasattr(_store, "get_edge_by_id"):
                            _edge_id = f"{_reg_nid}:{_chosen}"
                            _existing = _store.get_edge_by_id(_edge_id)
                            if _existing is not None:
                                # decision PROVENANCE: the informed-branch edge
                                # is strengthened by a decision observation
                                # (REQ-5 AC2) â€” delta positive, modest.
                                _store.record_observation(_edge_id, 0.1)
                            elif hasattr(_store, "upsert_edge"):
                                _new_eid = _store.upsert_edge(
                                    _reg_nid, _chosen, "informed", 0.5
                                )
                                if _new_eid:
                                    _store.record_observation(
                                        _new_eid or _edge_id, 0.1
                                    )
                except Exception as _edge_exc:  # noqa: BLE001
                    logger.debug(
                        "[DER] coupling-edge write failed: %s", _edge_exc
                    )
        except Exception as _cd_exc:  # noqa: BLE001
            logger.debug("[DER] coupling-decision record failed: %s", _cd_exc)

    def _der_verify_strictness(
        self, u: float, coverage: Optional[float] = None
    ) -> str:
        """Adaptive verification strictness by |u| band (D2.3).

        |u| < U_SPLIT  -> "wide"   : step was split; children verified individually,
                                   parent collapses on child consensus (no LLM rubric).
        U_SPLIT..0.85  -> "rubric" : atomic step, mid-band -> deterministic stub-kill
                                   PLUS LLM rubric verdict (tier-3 empowered check).
        >= 0.85        -> "atomic" : converged -> deterministic verify only (no LLM
                                   rubric; cheap, deterministic).

        Goal contract T6 (REQ-3 AC3.3): task-level coverage C is an optional
        second input. When supplied, the gap g = 1 - C acts as a forcing term
        on the effective magnitude â€” an open goal makes the state read less
        converged (stricter verification), a covered goal lets it settle.
        ``coverage=None`` preserves the exact legacy bands. The parameter is
        optional so every existing (u)-only caller keeps working unchanged.
        """
        from backend.agent.der_constants import U_SPLIT, U_CONVERGED

        au = abs(u)
        if coverage is not None:
            try:
                from backend.agent.der_constants import (
                    GOAL_FORCING_GAIN as _GOAL_GAIN,
                )

                _g = 1.0 - max(0.0, min(1.0, float(coverage)))
                au = au * max(0.0, 1.0 - float(_GOAL_GAIN) * _g)
            except Exception:
                pass
        if au < U_SPLIT:
            return "wide"
        if au < U_CONVERGED:
            return "rubric"
        return "atomic"

    def _der_split_blocker(
        self,
        item: "QueueItem",
        trigger: str,
        step_result: str = "",
    ) -> str:
        """REQ-4 AC4 (T16b): name the SPECIFIC blocker this split resolves.

        Deterministic extraction from the failure evidence (no LLM call on the
        split hot path â€” the blocker is derived, not generated):

          1. error-prefixed step_result  -> the tool failure itself
          2. verify_failed               -> the acceptance criterion that was
             NOT satisfied (expected_output, else the produced result) â€” names
             the specific gap, never the parent goal
          3. unresolved_u (physics)      -> the oscillating state itself
             (decomposition, not a failure â€” still names WHAT it resolves)
          4. empty evidence AND no expected_output -> "" (UNNAMED blocker) â€”
             the split cannot name what it resolves; recorded as such via
             blocker_named=False, surfaced as evidence the failure was not
             understood.

        Returns the blocker text, or "" when nothing can be named.
        """
        _res = (step_result or "").strip()
        _low = _res.lower()
        if _low.startswith("error") or _low.startswith("[step error") or _low.startswith(
            "duplicate"
        ):
            return f"the tool reported: {_res[:200]}"
        if _low.startswith("ratelimited") or _low.startswith("timeout") or _low.startswith(
            "connection"
        ):
            return f"transient infrastructure failure: {_res[:200]}"
        # A node's result opens with the model's summary and ends with the
        # reason it stopped (NodeResult.as_step_result). That reason IS the
        # blocker: "step call limit reached (12 calls)", "no screenshot was
        # taken". Without this line every failed node was named by its
        # expected output, so the child was told only what the parent had
        # been told.
        _node_err = re.search(r"\[node error: ([^\]\n]+)\]", _res)
        if _node_err:
            return f"the step stopped before it was done: {_node_err.group(1)[:200]}"
        if trigger == "verify_failed":
            _exp = (item.expected_output or "").strip()
            if _exp:
                return f"result did not satisfy expected output: {_exp[:200]}"
            if _res:
                return f"result was not verified against the expected output: {_res[:200]}"
            return ""  # UNNAMED â€” no expected output AND no evidence
        if trigger == "unresolved_u":
            return "unresolved oscillating state (|u| below the split threshold)"
        if _res:
            return f"the produced result was judged insufficient: {_res[:200]}"
        return ""

    def _split_step(
        self,
        item: "QueueItem",
        trigger: str,
        cad: Dict[str, float],
        work_units: int,
        step_result: str = "",
        verified_fraction: float = 0.0,
    ) -> List["QueueItem"]:
        """Stateful, physics-driven split operator (D2.1).

        Args:
            item:       step being split.
            trigger:    "unresolved_u" | "verify_failed".
            cad:        live Caducean state {x, y, xi, u, ...}.
            work_units: remaining unified termination budget (DER_WORK_UNITS_0
                        minus what has been prepaid). Split is PERMITTED only if
                        work_units >= width; split PREPAYS ``width`` units up
                        front (this is what makes the Lyapunov potential Phi
                        strictly decrease â€” see Appendix B).
            step_result: the failure evidence (produced result / error text).
                        REQ-4 AC4 (T16b): used to name the SPECIFIC blocker the
                        children exist to resolve â€” the child's objective_anchor
                        is NEVER a restatement of the parent goal.
            verified_fraction: REQ-4 AC1/AC2 (T16): the continuous verification
                        fraction of this step (0..1), consumed as a GRADED
                        steering input at the split decision. Mid-band
                        (0.25 < vf < 0.75) selects the bounded probe path
                        (width 1, probe=True) instead of a full-width
                        re-attempt; strong failure (< 0.25) lets |u| govern.
                        Default 0.0 preserves the pre-T16 binary behavior for
                        callers that do not have the fraction.

        Returns:
            List of child QueueItems (Sub-Loops that collapse back to the parent
            as one COMPRESS). Empty list => split refused, step forced atomic.
        """
        from backend.agent.der_constants import (
            DER_MAX_GRAFTS,
            MAX_DEPTH,
        )

        u = cad.get("u", 0.0)
        # REQ-4 AC1/AC2 (T16): the width is now a GRADED function of BOTH |u|
        # and the verified fraction â€” the continuous signal is a steering
        # input, not a post-hoc label. Mid-band -> bounded probe (width 1).
        # Goal contract T6 (REQ-3 AC3.3): feed task-level coverage C when the
        # per-step fraction is degenerate (0.0 default) so the split width is
        # a continuous function of coverage as well as |u|. Advisory â€” falls
        # back to the per-step fraction exactly when no contract exists.
        _gcov_state = getattr(self, "_goal_contract_state", None)
        _steer_frac = verified_fraction
        if _gcov_state is not None and not (0.0 < verified_fraction < 1.0):
            try:
                _gcov_c = float(_gcov_state.get("C", 0.0))
                if 0.0 < _gcov_c < 1.0:
                    _steer_frac = _gcov_c
            except Exception:
                pass
        width = self._der_split_width(u, _steer_frac)
        # Cap at DER_MAX_GRAFTS AND bounded by remaining work units.
        width = min(width, DER_MAX_GRAFTS, max(0, work_units))
        if width < 1 or item.depth_layer >= MAX_DEPTH:
            return []  # refused -> step forced atomic

        from backend.agent.der_loop import QueueItem, NodeRecord

        # REQ-4 AC2 (T16): a mid-band verified fraction selects the graded
        # middle path â€” a BOUNDED PROBE (width 1, probe=True), not a threshold
        # coin-flip. The child resolves the specific blocker at width 1.
        _probe = 0.25 < verified_fraction < 0.75 and trigger == "verify_failed"

        from backend.agent.der_loop import QueueItem, NodeRecord

        # REQ-4 AC4 (T16b): name the SPECIFIC blocker the split exists to
        # resolve â€” deterministically extracted from the failure evidence (no
        # LLM call on the split hot path). A split that cannot name what it
        # resolves records an UNNAMED blocker (blocker_named=False) â€” surfaced
        # as evidence the failure was not understood, never hidden behind a
        # fresh node id.
        _blocker = self._der_split_blocker(item, trigger, step_result)
        if _blocker:
            _child_anchor = f"RESOLVE: {_blocker}"
            _blocker_named = True
        else:
            _child_anchor = f"[UNNAMED_BLOCKER] {item.description[:160]}"
            _blocker_named = False
            logger.warning(
                "[DER] _split_step trigger=%s step=%s produced an UNNAMED "
                "blocker â€” the split cannot name what it resolves; recorded "
                "as evidence (REQ-4 AC4)",
                trigger, item.step_id,
            )

        # REQ-21 (T41): the compressed footprint each child carries â€”
        # Understanding (what has been attempted/gathered for this goal across
        # ALL prior attempts, bounded â€” never a truncated sample), Awareness
        # (the goal itself), Direction (remaining vs ruled-out), and a
        # coordinate_ref into the ledger/memory for the full prior evidence.
        # Bounded by construction: prior attempts are a deduplicated key set
        # (not per-tool-call transcripts), so cost does NOT grow linearly with
        # tool calls (AC2). Survives DCP pruning because it is durable
        # structured data on the child QueueItem (AC3).
        try:
            _prior_keys = sorted(
                set(getattr(self, "_der_crawl_attempts", {}).get(
                    self.conversation_id or self.session_id or "", set()
                ))
            )
            _prior_summary = (
                f"{len(_prior_keys)} prior gather attempt(s) committed for "
                f"this goal: {', '.join(_prior_keys[:5])}"
                + ("â€¦" if len(_prior_keys) > 5 else "")
            )
            _coordinate_ref = None
            try:
                _ledger = getattr(self, "_der_ledger", None)
                if _ledger is not None:
                    _coordinate_ref = getattr(_ledger, "conversation_id", None)
            except Exception:
                _coordinate_ref = None
        except Exception:
            _prior_summary = ""
            _prior_keys = []
            _coordinate_ref = None

        # REQ-4 AC4.3 (K3): a replan AFTER A FAILURE is a decision point where
        # the Immortus chain changes the decision - this task's own timeline
        # (what was tried, in order) plus the mediators tried near the current
        # state ride in the children's Understanding. ONLY here: a physics
        # split ("unresolved_u") or a normal step carries none of it (owner
        # rule 2026-09-30: no chain data per turn/step). Bounded (<= 900 chars)
        # and never raises; rows the physics lane has not landed yet are simply
        # absent (no wait: the replan is not worth stalling the answer path).
        _recall_sources: List[str] = []
        if trigger == "verify_failed":
            try:
                from backend.agent.caducean_trajectory import latest_coords_str
                from backend.agent.ontology_recall import (
                    replan_chain_context,
                    resolve_mycelium_conn,
                )

                _chain_sid = (
                    getattr(self, "_der_session", None) or self.session_id or ""
                )
                _chain_conn = resolve_mycelium_conn(self._memory_interface)
                if _chain_conn is not None and _chain_sid:
                    _chain_ctx = replan_chain_context(
                        _chain_conn,
                        _chain_sid,
                        latest_coords_str(self._memory_interface, _chain_sid),
                    )
                    # Spec D9 / E3: when this failure matches a KNOWN CASE, its
                    # trail (the verified fix, dead ends to avoid, dependency
                    # status) rides first - the most actionable line (<= 400).
                    from backend.memory.memory_events import case_trail

                    _trail = case_trail(
                        # the same decisive tool record_step writes the case under
                        _chain_conn, _step_tool(item),
                        step_result or str(getattr(item, "result", "") or ""),
                    )
                    if _chain_ctx or _trail:
                        _prior_summary = " ".join(
                            p for p in ((_prior_summary or "")[:300], _trail, _chain_ctx) if p
                        ).strip()
                        _recall_sources = [
                            s for s, t in (("known_case", _trail), ("chain_timeline", _chain_ctx)) if t
                        ]
            except Exception as _chain_exc:  # noqa: BLE001 â€” advisory context
                logger.debug("[DER] replan chain context skipped: %s", _chain_exc)

        children: List["QueueItem"] = []
        # REQ-3 T8: capture the pre-split compressed position so every child's
        # NodeRecord carries the SAME coords_from (the branch point) and each
        # lands a distinct coords_to when it finalizes (REQ-2 chain append).
        _coords_before = ""
        try:
            _live = self._der_live_cad_state(self.session_id or "")
            if _live:
                _coords_before = f"({_live.get('x', 0.0):.4f},{_live.get('y', 0.0):.4f}," \
                                 f"{_live.get('xi', 0.0):.4f},{_live.get('u', 0.0):.4f})"
        except Exception:
            pass
        for i in range(width):
            child = QueueItem(
                step_id=f"{item.step_id}_s{i}",
                step_number=item.step_number,
                # REQ-4 AC4 (T16b): the child's description/objective names the
                # SPECIFIC blocker it resolves â€” NOT a restatement of the
                # parent goal. This is what makes a split a RESOLVE, not a
                # retry wearing a new node id.
                description=f"{_child_anchor} (sub {i + 1})",
                objective_anchor=_child_anchor,
                # the parent's plain text, for the spoken "part done" line
                # (the child's own description is a machine anchor)
                parent_description=item.description or "",
                depth_layer=item.depth_layer + 1,
                expected_output=item.expected_output,
                is_subloop=True,  # collapses back to parent as one COMPRESS
                critical=item.critical,
                independent=True,  # T6.8: subloop children are independent per REQ-18 AC1
                # REQ-3 T8: EVERY node carries its memory record â€” the
                # generalized NodeRecord (was SubLoopFootprint, sub-loop-only).
                node_record=NodeRecord(
                    step_id=f"{item.step_id}_s{i}",
                    parent_step_id=item.step_id,
                    node_type="sub_loop",
                    objective_anchor=_child_anchor,
                    content_summary=_prior_summary,
                    prior_summary=_prior_summary,
                    expected_output=item.expected_output,
                    remaining=_child_anchor,
                    ruled_out="",  # no path is closed until a child proves it
                    coordinate_ref=_coordinate_ref,
                    coords_from=_coords_before,
                    blocker=_blocker,
                    blocker_named=_blocker_named,
                    probe=_probe,
                    # REQ-18 (T19): children INHERIT the parent's two domain
                    # axes â€” they are the same task (topic) run in the same
                    # winding (execution). Registry values by construction.
                    topic_domain=getattr(
                        getattr(item, "node_record", None), "topic_domain", "general"
                    ) or "general",
                    execution_domain=getattr(
                        getattr(item, "node_record", None),
                        "execution_domain",
                        "der",
                    ) or "der",
                    size_bytes=len(_prior_summary.encode("utf-8", "replace")),
                ),
            )
            children.append(child)
        logger.info(
            "[DER] _split_step trigger=%s u=%.2f width=%d depth=%d",
            trigger, u, width, item.depth_layer,
        )
        # Taxonomy v1: the replan recalls were delivered to EVERY child (each carries them).
        for _src in _recall_sources:
            for _child in children:
                _der_recall_delivered(
                    self, _child, _src, [],
                    getattr(self, "_der_session", None) or self.session_id or "",
                )
        # Taxonomy CONTROL: a failed verification changes the plan (REPLAN) by
        # fanning the step out (SPLIT); a physics split is only the SPLIT.
        _ev_rec = getattr(item, "node_record", None)
        _ev = dict(
            evidence="verifier", thread_id=getattr(self, "_der_session", None),
            step_index=str(getattr(item, "step_id", "") or ""),
            exec_domain=getattr(_ev_rec, "execution_domain", None),
            topic_domain=getattr(_ev_rec, "topic_domain", None),
            payload={"trigger": trigger, "width": width, "depth": item.depth_layer,
                     "probe": _probe, "blocker_named": _blocker_named},
        )
        if trigger == "verify_failed":
            _emit_event(self, "REPLAN", **_ev)
        _emit_event(self, "SPLIT", **_ev)
        # Reset failure counters so Sub-Loops aren't penalized as parent continuation (REQ-12 AC3)
        try:
            if hasattr(self, "_get_tool_box"):
                self._get_tool_box().reset_failure_counters()
        except Exception:
            pass
        return children

    def _der_route_subloop_children(
        self, _children: List["QueueItem"], queue, _session: str, _turn_id: str
    ) -> None:
        """Queue split children as NODES: each runs its own tool loop.

        A split child resolves a step that failed - a browser step that hit
        its call limit, a read that came back wrong. That is tool work. The
        REQ-7 batcher answered every child with ONE tool-less text call and
        pre-seeded the answer, so no recovery child ever opened a page or
        read a file: measured 2026-10-12, 7 of 7 grafts in logs/iris.log were
        BATCH_ROUTED, 0 ran a node, and the written guess became the parent's
        result (conv-1573 s2: 12 browser calls -> call limit -> a 272-char
        text answer stood in for the page). The batcher is removed; split
        children are queued here and nothing else answers for them.
        """
        for _c in _children:
            queue.add_item(_c)

    def _der_live_cad_state(self, session_id: str) -> Dict[str, float]:
        """Live Caducean state for the split decision (D2.2).

        Primary: ffi_caducean_get_state (live engine). Fallback: the trajectory
        recorder's last recorded coordinate (so a split can still be decided if
        the engine is unavailable). Never raises â€” returns zeros on total
        failure.
        """
        try:
            from backend.gateway.iris_ffi import ffi_caducean_get_state

            st = ffi_caducean_get_state(session_id) or {}
            if st:
                return {
                    "x": float(st.get("x", 0.0)),
                    "y": float(st.get("y", 0.0)),
                    "xi": float(st.get("xi", 0.0)),
                    "u": float(st.get("u", 0.0)),
                }
        except Exception as _e:
            logger.debug("[DER] live cad state unavailable: %s", _e)
        # Fallback: trajectory recorder's latest coordinate.
        try:
            from backend.agent.caducean_trajectory import (
                get_trajectory_recorder,
            )

            # REQ-20: bind to the APPLICATION store via MemoryInterface, never
            # to the BUILD-memory .mcm/coordinates.db fallback.
            rec = get_trajectory_recorder(self._memory_interface)
            coord = rec.get_latest_coordinate(session_id) or {}
            return {
                "x": float(coord.get("x", 0.0)),
                "y": float(coord.get("y", 0.0)),
                "xi": float(coord.get("xi", 0.0)),
                "u": float(coord.get("u", 0.0)),
            }
        except Exception:
            return {"x": 0.0, "y": 0.0, "xi": 0.0, "u": 0.0}

    def _der_submit_physics(
        self,
        item: "QueueItem",
        *,
        node_record,
        step_success: bool,
        verified: str,
        session: str,
        from_voice: bool,
        n_children: int,
        mediator: str,
        mediator_source: str,
    ):
        """Queue this step's physics on the side lane; return its fold handle.

        Every value the job needs is bound HERE: the job runs later, and the
        step object must not be read from another thread after the loop moved
        on. ``node_record`` (coords_to) and ``item.envelope`` (coords, topology
        stop) are the two places the job writes back, both under ``fold.lock``.
        """
        from types import SimpleNamespace

        from backend.utils.durability_queue import lane as _durability_lane

        # Its own lane: a ledger or durability backlog must never delay the
        # integrator a shape decision folds back on.
        _lane_submit = _durability_lane("physics").submit

        # ready: the integrator state (u, xi, rec) is updated â€” what a shape
        #        decision reads. done: the whole job, bookkeeping included.
        fold = SimpleNamespace(
            ready=threading.Event(), done=threading.Event(), lock=threading.Lock(),
            coords_from=None, coords_to=None, rec=None,
            step=getattr(item, "step_number", None),
        )
        vals = {
            "session": session,
            "step_number": item.step_number,
            "step_id": item.step_id,
            "tool": item.tool,
            # (tool, ok) for every call a NODE step made (set in _der_run_node);
            # the physics action reads what the step did, not item.tool (None).
            "node_calls": list(getattr(item, "node_calls", None) or []),
            "success": bool(step_success),
            "verified": verified,
            "from_voice": bool(from_voice),
            "n_children": int(n_children),
            "is_subloop": bool(getattr(item, "is_subloop", False)),
            # spoken split lines name the step in plain words
            "step_description": item.description or "",
            "parent_description": getattr(item, "parent_description", "") or "",
            "parent_step_id": getattr(getattr(item, "node_record", None), "parent_step_id", "") or "",
            "execution_domain": getattr(item, "execution_domain", None)
            or ("voice" if from_voice else "der"),
            # The sector lives on the NodeRecord (stamped in _der_finalize_step before the
            # physics submit); QueueItem has no topic_domain, so reading the item alone
            # wrote "general" on every caducean_trajectories row (7,089 of 7,089, 2026-10-18).
            "topic_domain": getattr(node_record, "topic_domain", None)
            or getattr(item, "topic_domain", None) or "general",
            "insight": (item.description or "")[:120],
            "file_path": item.params.get("path", "") if item.params else "",
            "mediator": mediator,
            "mediator_source": mediator_source,
            "node_type": getattr(node_record, "node_type", "step") or "step",
            "rec_topic_domain": getattr(node_record, "topic_domain", "general") or "general",
            "rec_execution_domain": getattr(node_record, "execution_domain", "der") or "der",
            "conversation_id": self.conversation_id,
        }

        def _job() -> None:
            t0 = time.monotonic()
            try:
                self._der_physics_step(fold, vals, node_record, item)
            finally:
                fold.ready.set()
                fold.done.set()
                dt = time.monotonic() - t0
                (logger.info if dt >= 1.0 else logger.debug)(
                    "[DER] physics lane session=%s step=%s landed in %.2fs",
                    session, vals["step_number"], dt,
                )

        pending = getattr(self, "_der_physics_pending", None)
        if pending is None:
            pending = {}
            self._der_physics_pending = pending
        # Bounded: only sessions with an update in flight are kept.
        for _sid in [s for s, f in pending.items() if f.done.is_set()]:
            pending.pop(_sid, None)
        pending[session] = fold
        if not _lane_submit(f"der-physics:{session}:step_{vals['step_number']}", _job):
            fold.ready.set()
            fold.done.set()
            logger.warning(
                "[DER] physics lane full - step %s physics dropped (session=%s)",
                vals["step_number"], session,
            )
        return fold

    def _der_physics_step(self, fold, vals: dict, node_record, item) -> None:
        """One step's Caducean physics. Runs on the side lane only.

        Body moved from _der_finalize_step unchanged in effect; it reads the
        bound ``vals``, never the live step object (``item`` is used only to
        reach its envelope under fold.lock).
        """
        _session = vals["session"]
        step_success = vals["success"]
        from_voice = vals["from_voice"]
        # pin_42ddd255162d: physics reads bound BEFORE the try below â€” any early
        # exception must not leave _u/_xi unbound for the narration hook
        # (CADUCEAN_ARCHITECTURE.md Â§10 rule 7).
        _u = 0.0
        _xi = 0.0

        # â”€â”€ CADUCEAN UPDATE + IMMORTUS + TRAJECTORY RECORD â”€â”€
        try:
            from backend.gateway.iris_ffi import (
                ffi_caducean_calculate_eml,
                ffi_caducean_update,
                ffi_immortus_chain_append,
            )
            from backend.agent.caducean_trajectory import (
                format_coords,
                get_trajectory_recorder,
            )

            # REQ-5/REQ-6: capture the coordinate BEFORE this step for
            # coords_from in the Immortus chain append (below).
            _before_coord = get_trajectory_recorder(
                self._memory_interface
            ).get_latest_coordinate(_session)

            # REQ-8 redo (backend/agent/physics_action.py): the action comes from
            # what the step DID - for a node step, the tools it actually called -
            # and the balance from the v2 state EML over the design divisor. The
            # old inputs were constants (action 0, EML 12.51 -> balance 3.0), so
            # Sigma was a step counter; replayed before going live
            # (scripts/replay_sigma.py).
            from backend.agent.physics_action import balance_from_eml, step_action

            _action = step_action(vals["tool"], step_success, vals.get("node_calls"))
            _eml_score, _ex, _ey = ffi_caducean_calculate_eml(_session)
            _balance = balance_from_eml(_eml_score)
            ffi_caducean_update(_session, _action, _balance)

            # v2: fetch recommendation code AFTER the update so we can
            # detect TOPO_VIOLATION (3) and persist the new column.
            from backend.gateway.iris_ffi import (
                ffi_caducean_recommend,
                ffi_caducean_get_state,
            )

            _rec = ffi_caducean_recommend(_session)
            fold.rec = _rec
            _state_snapshot = ffi_caducean_get_state(_session)
            _xi = _state_snapshot.get("xi", 0.0)
            _u = _state_snapshot.get("u", 0.0)
            # Fold-back point: the state a shape decision reads is now
            # current. The bookkeeping below (row, homeostasis, refit, chain,
            # narration) no longer holds any decision up.
            fold.ready.set()
            # â”€â”€ REQ-10 / REQ-11: multi-session coupling (feature-flagged).
            # Register the session once with its domain windings, push live
            # (Î¾, u) into the registry, and apply coupling. The engine is
            # (re)initialized with the domain windings on first registration
            # so engine c_eff and registry c_eff agree (REQ-11 AC3). Any
            # failure logs at debug and never blocks the step (REQ-10 AC5). â”€â”€
            try:
                from backend.agent.coupled_registry import (
                    coupling_enabled,
                    get_coupled_registry,
                    domain_windings,
                )
                from backend.gateway.iris_ffi import ffi_caducean_init_session

                if coupling_enabled():
                    _domain = "voice" if from_voice else "der"
                    _l, _m = domain_windings(_domain)
                    _reg = get_coupled_registry()
                    if _reg.ensure_registered(_session, _l, _m):
                        ffi_caducean_init_session(_session, _l, _m)
                    _reg.update_session_state(_session, _xi, _u)
                    _reg.apply_coupling(_session)
            except Exception as _coupling_exc:
                logger.debug("[DER] coupling wiring skipped: %s", _coupling_exc)

            get_trajectory_recorder(self._memory_interface).record(
                session_id=_session,
                step_num=vals["step_number"],
                # One coherent position AFTER the step (same as the chain's coords_to):
                # x, y from the EML read were taken BEFORE the update while xi, u come
                # from after it, so a row mixed two moments.
                x=_state_snapshot.get("x", _ex),
                y=_state_snapshot.get("y", _ey),
                xi=_xi,
                u=_u,
                action=_action,
                outcome="success" if step_success else "failure",
                eml_after=_eml_score,
                recommendation=_rec,
                # REQ-21 (T22): carry the two ontology axes on the trajectory
                # row so per-domain physics aggregation keys on how the step
                # RAN (execution_domain) and what it was ABOUT (topic_domain).
                execution_domain=vals["execution_domain"],
                topic_domain=vals["topic_domain"],
            )

            # v2: handle TOPO_VIOLATION (rec=3) by recording the anomaly
            # to the Mycelium QuorumSensor and halting the loop.
            if _rec == 3:
                with fold.lock:
                    _der_fold_envelope(item, fold)
                # Phase 5: adapt the Duffing controller on a topological
                # violation so the engine self-corrects instead of repeatedly
                # violating the same boundary.
                try:
                    from backend.agent.trajectory_controller import TrajectoryController

                    _conn = getattr(
                        getattr(self._memory_interface, "episodic", None), "db", None
                    )
                    if _conn is not None:
                        TrajectoryController(_conn).tune_dffing_params(_session)
                except Exception as _tune_exc:
                    logger.warning(
                        "[agent_kernel] tune_dffing_params failed: %s", _tune_exc
                    )
                try:
                    self._memory_interface.mycelium_record_anomaly(
                        _session, "topological_violation"
                    )
                except Exception as _anom_exc:  # never block on this
                    logger.warning(
                        "[agent_kernel] mycelium_record_anomaly failed: %s",
                        _anom_exc,
                    )
                from backend.agent.exceptions import TopologyViolationException

                # This raise ends THIS update (the lane job) only; it never
                # reaches the loop. The loop halts via _der_topology_halt at
                # the next step boundary, reading fold.rec set above.
                raise TopologyViolationException(
                    session_id=_session,
                    direction_signal=None,  # full signal in DebugPanel
                )

            # â”€â”€ Homeostatic relaxation (REQ-1 AC2) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Fire after every RELAX_EVERY_N_UPDATES (10) updates, or every
            # RELAX_MAX_INTERVAL_S (60 s) wall-clock, whichever first. A
            # relaxation failure cannot abort the trajectory record or chain
            # append below.
            try:
                global _update_counters
                with _update_counters_lock:
                    _update_counters[_session] = (
                        _update_counters.get(_session, 0) + 1
                    )
                    _uc = _update_counters[_session]
                from backend.agent.param_homeostasis import get_param_homeostasis

                get_param_homeostasis().maybe_relax(_session, _uc)
            except Exception as _relax_exc:
                logger.debug(
                    "[agent_kernel] maybe_relax failed: %s", _relax_exc
                )

            # â”€â”€ TrajectoryController refit on DER cadence (REQ-13) â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Calls TrajectoryController.fit() which refits only at milestones
            # (100, 500, 1000 records), in its own try/except so a refit
            # failure cannot abort the record or chain append.
            try:
                from backend.agent.trajectory_controller import TrajectoryController

                _tc_conn = getattr(
                    getattr(self._memory_interface, "episodic", None), "db", None
                )
                if _tc_conn is not None:
                    TrajectoryController(_tc_conn).fit()
            except Exception as _refit_exc:
                logger.debug(
                    "[agent_kernel] maybe_refit failed: %s", _refit_exc
                )

            # REQ-5/REQ-6: coords_from / coords_to in canonical format_coords.
            if _before_coord is not None:
                _coords_from = format_coords(
                    _before_coord["x"], _before_coord["y"],
                    _before_coord["xi"], _before_coord["u"],
                )
            else:
                # REQ-4 AC4.1: no prior coordinate is UNKNOWN -> NULL on the
                # row; "0.00,0.00,0.00,0.00" is a real point in the state space.
                _coords_from = None
            _coords_to = format_coords(
                _state_snapshot.get("x", _ex),
                _state_snapshot.get("y", _ey),
                _state_snapshot.get("xi", 0.0),
                _state_snapshot.get("u", 0.0),
            )
            # REQ-3 AC2 (T37): the landing coordinate on the node's memory
            # record, and on the envelope (whichever of this lane and the
            # envelope build finishes second applies it).
            with fold.lock:
                fold.coords_from = _coords_from
                fold.coords_to = _coords_to
                if node_record is not None:
                    node_record.coords_to = _coords_to
                _der_fold_envelope(item, fold)

            # The Immortus chain is a trajectory (coords_from -> coords_to):
            # appended here, on the single-consumer lane, so appends land in
            # step order.
            ffi_immortus_chain_append(
                thread_id=_session,
                result="success" if step_success else "failure",
                coords_from=_coords_from,
                coords_to=_coords_to,
                nbl_outcome=f"step_{vals['step_number']}",
                insight=vals["insight"],
                file_path=vals["file_path"],
                landmark_id="",
                # REQ-23 AC2: mediator + source ride the same chain row as the
                # Î£ coords, so (Treatment -> Mediator -> Outcome) is queryable
                # together with the coordinates that were in force.
                mediator=vals["mediator"],
                mediator_source=vals["mediator_source"],
                # REQ-18 AC4 (T19): node type + both domain axes ride the
                # chain row so recall (REQ-20) and aggregation (REQ-21) can
                # key on them without a join back to the in-memory record.
                node_type=vals["node_type"],
                topic_domain=vals["rec_topic_domain"],
                execution_domain=vals["rec_execution_domain"],
            )
        except Exception as _cad_exc:
            loud_error(_cad_exc, "caducean_trajectory_immortus")

        # â”€â”€ REQ-7: agent-driven PHYSICS-EVENT narration (post-step hook) â”€â”€
        # The agent speaks ONLY on a physics event â€” a |u| transition
        # (oscillating -> converged) or a structural event (split into
        # Sub-Loops, or a Sub-Loop collapsing). Funneled through SpeakTool
        # (narration lock) so it never conflicts with web-search progress or
        # the final answer. It reads the u/xi this update just produced, so it
        # runs here, on the lane, right after the update.
        # Invariant: spoken âŠ† visible â€” every spoken line is a real transition.
        _n_children = vals["n_children"]
        _is_subloop = vals["is_subloop"]
        _verified = vals["verified"]
        try:
            from backend.agent.der_constants import detect_physics_narration

            _u_mag = abs(float(_u)) if _u is not None else 0.0
            _narrate = detect_physics_narration(
                self._der_last_u_mag, _u_mag, _n_children, _is_subloop,
                step_description=vals.get("step_description", ""),
                parent_description=vals.get("parent_description", ""),
            )
            # "One part done" is spoken once per split, not once per child (a
            # 3-way split spoke the same line three times). A new split of the
            # step allows it again. This job runs on the ordered physics lane.
            _narrated = getattr(self, "_der_part_done_spoken", None)
            if _narrated is None or len(_narrated) > 500:
                _narrated = self._der_part_done_spoken = set()
            if _n_children:
                _narrated.discard((vals.get("session"), vals.get("step_id", "")))
            elif _is_subloop and _narrate:
                _pkey = (vals.get("session"), vals.get("parent_step_id", ""))
                if _pkey in _narrated:
                    _narrate = None
                else:
                    _narrated.add(_pkey)
            _tts_played = False
            if _narrate:
                from backend.agent.tools.speak_tool import get_speak_tool

                get_speak_tool().speak(_narrate, priority="low")
                _tts_played = True
            self._der_last_u_mag = _u_mag
            # REQ-9: record the narration decision (incl. SILENCE) to the
            # conversation-scoped observability log. u/xi carried on
            # split/collapse.
            try:
                from backend.agent.narration import NarrationLog

                _nlog = NarrationLog(vals["conversation_id"])
                _decision = "brief" if _narrate else "silence"
                # u/xi only meaningful on a structural event.
                _has_struct = bool(_n_children) or _is_subloop
                # pin_42ddd255162d: direct sync write (a small JSONL append).
                _nlog._write(
                    {
                        "ts": time.time(),
                        "conversation_id": vals["conversation_id"],
                        "step_id": vals["step_id"],
                        "decision": _decision,
                        "signal": (
                            "retried"
                            if _n_children
                            else (
                                "crystallized"
                                if _verified == "VERIFIED"
                                else "avoided"
                            )
                        )
                        if _has_struct
                        else None,
                        "u": float(_u) if _u is not None else None,
                        "xi": float(_xi) if _xi is not None else None,
                        "text": _narrate or "",
                        "tts_played": _tts_played,
                    },
                )
            except Exception as _nlog_exc:
                logger.debug("[DER] narration log skipped: %s", _nlog_exc)
        except Exception as _narr_exc:
            logger.debug("[DER] physics-event narration skipped: %s", _narr_exc)
            try:
                self._der_last_u_mag = (
                    abs(float(_u)) if _u is not None else 0.0
                )
            except Exception:
                pass
