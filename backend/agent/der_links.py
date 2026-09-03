"""der_links.py — REQ-19 (T20): DER structural links into the SHARED link store.

DER relationships (parent, depends_on, sub-loop containment, failure class)
land in the SAME mycelium link store the pin/landmark system uses
(``mycelium_pin_links`` via ``PinStore``) — one store, no second edge store
(REQ-19 AC4). The vocabulary is pinned by ``pin_store.LINK_VOCABULARY`` and
enforced at the write boundary (out-of-vocabulary predicates are logged and
dropped, never written — AC2b). Canonical directions (ontology.md §3b):

  - ``part_of``      source=child,  target=parent   (sub-loop containment;
                     plan step -> task). ``contains`` is NEVER written by DER
                     (derived as the inverse at query time).
  - ``depends_on``   source=node,   target=prerequisite (plan dependency)
  - ``derives_from`` source=new,    target=frozen parent (forward-only, REQ-24)
  - ``relevant_to``  source=node,   target=surfaced branch (REQ-5 AC1 — a
                     coupling decision is provenance, written ONLY when the
                     branch was actually surfaced to the decision)
  - ``failed_like``  source=failed node, target=prior failed node of the SAME
                     failure class (so AVOID recall is a graph walk, REQ-19 AC3)

The writer is deliberately NON-blocking: every method swallows and logs its
own failure so a link-store problem can never fail a DER step. The kernel
calls it at finalize, off the critical path.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# A bounded in-process index of (step_id -> failure class) so ``failed_like``
# can link a new failure to PRIOR same-class failures without a full store
# scan. Keyed by session id; bounded per session (FIFO eviction) so memory is
# bounded (AGENTS.md quality check). The links themselves persist in the store;
# this index is only the write-time lookup.
_MAX_FAILURE_INDEX = 256


class DerLinkWriter:
    """Writes DER structural links to the shared mycelium link store.

    ``_store`` is the mycelium store object (``memory_interface._mycelium.
    _store``); its ``_conn`` backs the PinStore. The failure-class index is
    per-writer; production wires ONE writer per kernel (no cross-session
    shared mutable state).
    """

    def __init__(self, store: Any):
        self._store = store
        self._pin_store = None
        self._failure_index: dict[str, list[tuple[str, str]]] = {}
        # REQ-20 AC1b (T24): bounded cross-conversation failure index —
        # failure_class -> [(session_id, step_id)]. Lets a failure in a NEW
        # session link failed_like to prior same-class failures in OLDER
        # conversations (the shared store spans threads). FIFO-bounded.
        self._global_failure_index: dict[str, list[tuple[str, str]]] = {}

    # ── internals ─────────────────────────────────────────────────────────

    def _ensure_store(self) -> Any:
        """Lazily build the PinStore on the mycelium connection. Returns None
        (caller logs + skips) when the store is unavailable."""
        if self._pin_store is not None:
            return self._pin_store
        try:
            if self._store is None:
                return None
            conn = getattr(self._store, "_conn", None)
            if conn is None:
                return None
            from backend.memory.pin_store import PinStore

            self._pin_store = PinStore(conn=conn)
            return self._pin_store
        except Exception as exc:
            logger.debug("[der_links] link store unavailable: %s", exc)
            return None

    @staticmethod
    def _node_id(step_id: str) -> str:
        """Stable link-store identifier for a DER node."""
        return f"node:{step_id}"

    # ── structural links ──────────────────────────────────────────────────

    def link_part_of(self, child_step_id: str, parent_step_id: str) -> bool:
        """REQ-19 AC1 (sub-loop containment): child ``part_of`` parent.

        Canonical direction ONLY: source=child, target=parent, predicate
        ``part_of`` (ontology.md §3b rule 1). ``contains`` is derived, never
        written by DER.
        """
        if not child_step_id or not parent_step_id:
            return False
        ps = self._ensure_store()
        if ps is None:
            return False
        try:
            return bool(
                ps.link(
                    self._node_id(child_step_id),
                    self._node_id(parent_step_id),
                    relationship="part_of",
                    source_type="node",
                    target_type="node",
                    weight=1.0,
                )
            )
        except Exception as exc:
            logger.debug("[der_links] part_of link failed: %s", exc)
            return False

    def link_depends_on(self, step_id: str, prereq_id: str) -> bool:
        """REQ-19 AC1 (plan dependency): ``step depends_on prereq``."""
        if not step_id or not prereq_id:
            return False
        ps = self._ensure_store()
        if ps is None:
            return False
        try:
            return bool(
                ps.link(
                    self._node_id(step_id),
                    self._node_id(prereq_id),
                    relationship="depends_on",
                    source_type="node",
                    target_type="node",
                    weight=1.0,
                )
            )
        except Exception as exc:
            logger.debug("[der_links] depends_on link failed: %s", exc)
            return False

    def link_relevant_to(self, node_step_id: str, branch_node_id: str) -> bool:
        """REQ-5 AC1 / REQ-19 AC2b rule 2: a coupling DECISION is provenance.

        Written ONLY when the branch was actually surfaced to the decision —
        never as a similarity guess (that is the scorer's ``related_to``).
        This is the natural home for REQ-18 AC1b's coupling provenance
        ("which decisions were informed by branch X" is a lookup).
        """
        if not node_step_id or not branch_node_id:
            return False
        ps = self._ensure_store()
        if ps is None:
            return False
        try:
            return bool(
                ps.link(
                    self._node_id(node_step_id),
                    branch_node_id,  # branch ids are already store node ids
                    relationship="relevant_to",
                    source_type="node",
                    target_type="node",
                    weight=1.0,
                )
            )
        except Exception as exc:
            logger.debug("[der_links] relevant_to link failed: %s", exc)
            return False

    # ── dispatcher (called by the kernel at finalize) ─────────────────────

    def write_node_links(self, item, record, step_success: bool,
                         step_result: str = "", execution_domain: str = "der",
                         session_id: str = "") -> int:
        """REQ-19 (T20): persist ALL of a finalized node's structural links.

        Called once per node at the finalize point (agent_kernel.py
        ``_der_finalize_step``), off the critical path. Writes, in order:

          part_of       — sub-loop child -> parent (containment, canonical
                          direction only; ``contains`` never written)
          depends_on    — plan dependency (item.depends_on) -> each prereq
          relevant_to   — branches actually SURFACED to a coupling decision
                          (REQ-5 AC1 provenance — only when candidates existed)
          failed_like   — on failure, link to prior same-class failures and
                          index this node's class for later walks

        Returns the number of links written. Never raises.
        """
        written = 0
        try:
            _sid = session_id or getattr(item, "session_id", "") or ""
            _step_id = getattr(item, "step_id", "") or ""
            if not _step_id or record is None:
                return 0

            # ── part_of: sub-loop containment (child -> parent) ─────────
            _parent = getattr(record, "parent_step_id", "") or ""
            if _parent and getattr(item, "is_subloop", False):
                if self.link_part_of(_step_id, _parent):
                    written += 1

            # ── depends_on: explicit plan dependencies ──────────────────
            for _prereq in getattr(item, "depends_on", None) or []:
                if _prereq and self.link_depends_on(_step_id, _prereq):
                    written += 1

            # ── relevant_to: coupling provenance (REQ-5 AC1) ────────────
            _cands = getattr(item, "_coupled_candidates", None) or []
            _chosen = getattr(record, "chosen_branch", "") or ""
            _cand_ids = [
                (c.get("node_id") or c.get("id") or "") for c in _cands
                if isinstance(c, dict)
            ]
            for _cid in _cand_ids:
                if _cid and self.link_relevant_to(_step_id, _cid):
                    written += 1
            if _chosen and _chosen not in _cand_ids:
                if self.link_relevant_to(_step_id, _chosen):
                    written += 1

            # ── failed_like: failure-class graph walk (REQ-19 AC3) ──────
            if not step_success:
                try:
                    from backend.agent.der_execution_ledger import classify_failure

                    _fc = classify_failure(
                        success=False, error=step_result or "", result=step_result
                    )
                except Exception:
                    _fc = "permanent"
                self.record_failure_class(_sid, _step_id, _fc)
                written += self.link_failed_like(_sid, _step_id, _fc)

            return written
        except Exception as exc:
            logger.debug("[der_links] write_node_links failed: %s", exc)
            return written

    # ── failure-class links (REQ-19 AC3) ──────────────────────────────────

    def record_failure_class(self, session_id: str, step_id: str,
                             failure_class: str) -> None:
        """Index (step_id -> failure_class) for later failed_like matching.

        Bounded FIFO per session (memory bound). Never raises."""
        try:
            entries = self._failure_index.setdefault(session_id, [])
            entries.append((step_id, failure_class))
            if len(entries) > _MAX_FAILURE_INDEX:
                del entries[: len(entries) - _MAX_FAILURE_INDEX]
            # Cross-conversation (REQ-20 AC1b): a failure in a NEW session
            # must still link failed_like to prior same-class failures in
            # OLDER sessions — the shared store spans conversations. Bounded
            # global class->[(session, step)] index; FIFO eviction.
            _g = self._global_failure_index.setdefault(failure_class, [])
            _g.append((session_id, step_id))
            if len(_g) > _MAX_FAILURE_INDEX:
                del _g[: len(_g) - _MAX_FAILURE_INDEX]
        except Exception:
            pass

    def link_failed_like(self, session_id: str, step_id: str,
                         failure_class: str) -> int:
        """REQ-19 AC3: link a failed node to PRIOR same-class failures.

        The AVOID recall path becomes a graph walk: ``node failed_like prior``
        for every prior failure sharing the class — from THIS session's index
        AND from other conversations (REQ-20 AC1b: recall spans sessions; a
        failure a month ago in another thread is a legitimate AVOID target if
        it shares the class). Returns the number of links written. Off the
        hot path; never raises.
        """
        written = 0
        ps = self._ensure_store()
        if ps is None:
            return 0
        try:
            _prior: set = set()
            for prior_id, prior_class in self._failure_index.get(
                session_id, []
            ):
                if prior_id == step_id:
                    continue
                if prior_class != failure_class:
                    continue
                _prior.add(prior_id)
            # cross-conversation prior same-class failures
            for _psess, _pid in self._global_failure_index.get(
                failure_class, []
            ):
                if _pid == step_id:
                    continue
                _prior.add(_pid)
            for prior_id in sorted(_prior):
                try:
                    if ps.link(
                        self._node_id(step_id),
                        self._node_id(prior_id),
                        relationship="failed_like",
                        source_type="node",
                        target_type="node",
                        weight=1.0,
                    ):
                        written += 1
                except Exception:
                    continue
            return written
        except Exception as exc:
            logger.debug("[der_links] failed_like walk failed: %s", exc)
            return written
