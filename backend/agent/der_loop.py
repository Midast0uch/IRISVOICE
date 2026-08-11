"""
DER Loop — Director · Explorer · Reviewer
File: IRISVOICE/backend/agent/der_loop.py

The Reviewer is a membrane, not a gate.
It never blocks on failure — always falls back to PASS.

Phase 3 additions (Agentic Mode):
  - DirectorQueue manages execution mode (QUICK/AGENTIC/FULL)
  - Mode is dynamically decided, can escalate/de-escalate mid-task
  - _decide_mode() considers task_class, confidence, message length, budget

Source: specs/agent_loop_design.md
Gate 1 Step 1.1
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .der_constants import (
    DER_EMERGENCY_STOP,
    DER_MAX_CYCLES,
    DER_MAX_VETO_PER_ITEM,
    DER_TOKEN_BUDGETS,
    ExecutionMode,
    CLASSIFIER_CONFIDENCE_LOW,
    CLASSIFIER_CONFIDENCE_HIGH,
    MESSAGE_LENGTH_SHORT,
    MESSAGE_LENGTH_LONG,
    BUDGET_RATIO_ESCALATE,
    BUDGET_ABSOLUTE_MIN,
    get_token_budget,
)

logger = logging.getLogger(__name__)


class ReviewVerdict(Enum):
    PASS = "pass"  # step approved as-is
    REFINE = "refine"  # step approved with modification
    VETO = "veto"  # step rejected — Director must queue alternative


# ── Mode change record ────────────────────────────────────────────────────


@dataclass
class ModeChange:
    """Record of a mode change decision."""

    previous_mode: Optional[ExecutionMode]
    new_mode: ExecutionMode
    reason: str
    turn_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    token_budget_remaining: int = 0


# ── QueueItem ──────────────────────────────────────────────────────────────


@dataclass
class NodeRecord:
    """REQ-3 (T8): the compressed, memory-addressed record EVERY node carries.

    Generalized from ``SubLoopFootprint`` (which was sub-loop-child-only and
    write-once) to ALL nodes — step, split child, and sub-loop. It is the
    node's memory record: the compressed context (Σ position + what has been
    attempted/ruled-out + coordinate ref) plus the outcome and edges that
    later steps, coupling, and recall consume (design.md Data Models).

    THREE memory parts (design.md:172-187):
      Understanding — ``content_summary`` / ``prior_summary``: what has been
                      attempted/gathered for this goal (bounded, not a truncated
                      sample — coverage stays complete, the bound is on cost).
      Awareness     — ``objective_anchor`` / ``expected_output``: what "done"
                      means.
      Direction     — ``remaining`` / ``ruled_out``: what remains and what has
                      already been closed, so the node does not re-attempt a
                      path already ruled out.
      Coordinate ref — ``coordinate_ref`` / ``coords_from`` / ``coords_to``:
                      memory lookup keys that survive DCP pruning (durable
                      structured data on the queue item, REQ-3 AC3).

    Bounded: ``size_bytes`` enforces the AC2 cost cap. Degradation: if the
    referenced memory entry is pruned or unavailable, the node falls back to
    its inherited text fields rather than failing (REQ-3 Edge Cases).
    """

    step_id: str
    parent_step_id: str
    node_type: str = "step"  # task | step | sub_loop (REQ-18 AC1 — typed in Wave 5 T19)
    objective_anchor: str = ""
    content_summary: str = ""
    prior_summary: str = ""
    expected_output: str = ""
    remaining: str = ""
    ruled_out: str = ""
    coordinate_ref: Optional[str] = None
    coords_from: str = ""
    coords_to: str = ""
    outcome: str = ""  # VERIFIED | UNVERIFIED | FAILED (label, REQ-3)
    verified_fraction: float = 0.0  # continuous, 0..1 (REQ-4)
    # REQ-23 (T37): the MEDIATOR — the resolved tool/action identifier plus a
    # stable hash of its arguments — written at the same finalize point as
    # ``outcome``. The causal triple is (Treatment -> Mediator -> Outcome); the
    # mediator is the ONLY variable the agent controls, so it is the only thing
    # the graph can learn about (design.md "The causal vocabulary").
    # AC5: a node with NO mediator records "none" EXPLICITLY — never empty —
    # so pure decision/synthesis nodes do not rank as failed actions. The
    # '' default here is the dataclass-construction sentinel only; the
    # finalize site writes "none" for mediator-less nodes.
    mediator: str = ""
    # Where the mediator came from: "explicit" | "predictor" | "fallback" |
    # "none". Must be recorded or the learning credits the wrong chooser
    # (REQ-23 edge case: mediator chosen by fallback rather than by the
    # predictor).
    mediator_source: str = ""
    edge_ids: List[str] = field(default_factory=list)  # coupling edges (REQ-5)
    size_bytes: int = 0
    created_at: float = field(default_factory=time.time)
    # REQ-4 AC4 (T16b): the SPECIFIC blocker this split child exists to
    # resolve — NEVER a restatement of the parent goal. A split that cannot
    # name what it is resolving records ``blocker=""`` with
    # ``blocker_named=False``: an unnamed blocker is evidence the failure was
    # not understood, surfaced (never hidden behind a fresh node id).
    blocker: str = ""
    blocker_named: bool = True
    # REQ-4 AC4 (T16b): FOLD-BACK — sub-loop children fold back as compressed
    # observations that CHANGED the parent's state (REQ-3 AC1: the parent's
    # next decision reads node records that now include the children's
    # outcomes). Bounded by DER_FOLD_BACK_MAX — keep the most recent
    # outcomes; never a growing log.
    folded_back: List[str] = field(default_factory=list)
    # REQ-4 AC1/AC2 (T16): GRADED split marker — a mid-band verified fraction
    # at the split decision selects a BOUNDED PROBE (width 1) instead of a
    # full-width re-attempt. The child carries probe=True so the record (and
    # the FOLD-BACK it folds into the parent) distinguishes a probe from a
    # genuine wide split — the graded middle path, never a threshold
    # coin-flip. probe=False does NOT mean "not a probe child" for non-split
    # nodes (top-level steps are not probes by construction).
    probe: bool = False
    # REQ-5 AC4 (T17): coupling-decision provenance. When this step's
    # retrieval surfaced relevant branches, ``candidates_surfaced`` records how
    # many were put in front of the deciding step (never pre-selected), and
    # ``chosen_branch`` records which the step committed to. The coupling edge
    # to the chosen branch carries the decision as its provenance (AC2). 0 / ""
    # means no coupling decision occurred at this node (no branches existed).
    candidates_surfaced: int = 0
    chosen_branch: str = ""
    # REQ-5 AC5 (T17b): how many relevant branches EXISTED (before the cap)
    # when this step's retrieval ran — the DENOMINATOR for candidate-surfacing
    # coverage ("how often a decision saw >=2 candidates when >=2 existed").
    # coverage = candidates_surfaced >= 2 among decisions where
    # candidates_existed >= 2. 0 when no coupling decision occurred.
    candidates_existed: int = 0
    # REQ-5 AC4 (T17): the labels of the branches surfaced to this step
    # (bounded by DER_COUPLING_PROVENANCE_MAX) — "was the agent aware of both
    # branches" is answerable from the record, not assumed.
    surfaced_branches: List[str] = field(default_factory=list)
    # REQ-18 AC2 (T19): the two domain axes — BOTH registry-backed, never free
    # text. topic_domain is a value from the mycelium DOMAIN_IDS registry
    # (spaces.py — 13 canonical topics); execution_domain is one of
    # voice | der | research from the active winding (coupled_registry.py
    # domain_windings). Registry misses resolve to the registry's
    # general/unknown bucket and are LOGGED, never invented (AC3). These
    # default to the general/der sentinels at construction; the finalize site
    # stamps the resolved registry values onto the record.
    topic_domain: str = "general"
    execution_domain: str = "der"
    # REQ-18 AC1b (T19): ROLE marker — True when this node COMMITTED A DECISION
    # (surfaced >=1 candidate branch and chose one, REQ-5 AC2), making it a
    # valid coupling endpoint. {task, step, sub_loop} describes WHERE a node
    # sits in the tree; this describes WHAT it did, so "which decisions were
    # informed by branch X" is a lookup (REQ-20 relationship filters) instead
    # of a table scan.
    committed_decision: bool = False


@dataclass
class SubLoopFootprint(NodeRecord):
    """Backward-compatible alias for the generalized NodeRecord.

    Kept so existing call sites / callers of the old name keep working; new
    code uses NodeRecord (REQ-3 T8).
    """

    pass


@dataclass
class QueueItem:
    """
    One item in the Director's broadcast queue.
    Richer than PlanStep — carries DER-specific orchestration fields.
    """

    step_id: str
    step_number: int
    description: str
    tool: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    critical: bool = True
    parallel_safe: bool = False  # Phase 4: safe to execute concurrently with other ready steps
    objective_anchor: str = ""  # overall task goal — never changes
    coordinate_signal: str = ""  # Mycelium coordinate region targeted
    veto_count: int = 0
    refined_description: Optional[str] = None  # set by Reviewer on REFINE
    depth_layer: int = 1  # trailing crystallizer depth level
    gap_analysis: Optional[str] = None  # trailing Director gap description
    result: Optional[str] = None  # populated after step execution; consumed by TrailingDirector
    expected_output: Optional[str] = None  # DER Phase 0: explicit success criterion; consumed by TrailingDirector.analyze_gaps
    is_subloop: bool = False  # DER Phase 2: child of a growth-width split; collapses to parent as one COMPRESS
    independent: bool = False  # Wave 4 / REQ-18 AC1: safe to batch with siblings
    # REQ-21 (T40): compressed context for sub-loop children — survives DCP
    # pruning, carries Understanding/Awareness/Direction + coordinate_ref.
    # Defaults to None for non-split-created steps (every existing call site
    # is unaffected — the field is only populated by _split_step, T41).
    node_record: Optional[NodeRecord] = None  # REQ-3 T8: EVERY node carries its memory record

    @property
    def footprint(self) -> Optional[NodeRecord]:
        """Backward-compatible alias: footprint == node_record (REQ-3 T8)."""
        return self.node_record

    @footprint.setter
    def footprint(self, value: Optional[NodeRecord]) -> None:
        self.node_record = value


# ── DirectorQueue ──────────────────────────────────────────────────────────


@dataclass
class DirectorQueue:
    """
    The Director's live broadcast queue with mode management.

    Initialized from ExecutionPlan.steps, updated as Explorer feeds back.
    The Director can escalate/de-escalate the execution mode mid-task.

    Phase 3 additions:
      - mode: ExecutionMode (QUICK / AGENTIC / FULL)
      - set_mode() / escalate() / de_escalate()
      - mode_history: List[ModeChange]
      - _decide_mode() static method
    """

    objective: str
    items: List[QueueItem] = field(default_factory=list)
    completed_ids: List[str] = field(default_factory=list)
    vetoed_ids: List[str] = field(default_factory=list)
    failed_ids: List[str] = field(default_factory=list)
    graft_attempts: int = 0
    cycle_count: int = 0
    max_cycles: int = DER_MAX_CYCLES
    max_veto_per_item: int = DER_MAX_VETO_PER_ITEM

    # ── Mode management (Phase 3) ──────────────────────────────────────

    mode: ExecutionMode = ExecutionMode.QUICK
    mode_history: List[ModeChange] = field(default_factory=list)

    def set_mode(
        self,
        new_mode: ExecutionMode,
        reason: str = "",
        turn_id: Optional[str] = None,
        token_budget: int = 0,
    ) -> None:
        """Set the execution mode and record the change."""
        change = ModeChange(
            previous_mode=self.mode,
            new_mode=new_mode,
            reason=reason,
            turn_id=turn_id,
            token_budget_remaining=token_budget,
        )
        self.mode_history.append(change)
        old_mode = self.mode
        self.mode = new_mode
        logger.info(
            "[DirectorQueue] Mode changed: %s → %s (%s) — turn=%s",
            old_mode.value if old_mode else "none",
            new_mode.value,
            reason,
            turn_id or "none",
        )

    def escalate(
        self,
        reason: str = "Task complexity increased",
        turn_id: Optional[str] = None,
        token_budget: int = 0,
    ) -> ExecutionMode:
        """Escalate to the next higher mode. Returns the new mode."""
        new_mode = self.mode.escalate()
        if new_mode != self.mode:
            self.set_mode(new_mode, reason, turn_id, token_budget)
        return self.mode

    def de_escalate(
        self,
        reason: str = "Task simpler than expected",
        turn_id: Optional[str] = None,
        token_budget: int = 0,
    ) -> ExecutionMode:
        """De-escalate to the next lower mode. Returns the new mode."""
        new_mode = self.mode.de_escalate()
        if new_mode != self.mode:
            self.set_mode(new_mode, reason, turn_id, token_budget)
        return self.mode

    # ── Mode decision ──────────────────────────────────────────────────

    @staticmethod
    def _decide_mode(
        task_class: str,
        from_voice: bool = False,
        message_text: str = "",
        token_budget_remaining: int = 30_000,
        confidence: float = 0.5,
        voice_preference: str = "auto",
        user_preference: Optional[str] = None,
    ) -> ExecutionMode:
        """
        Decide the execution mode based on task characteristics.

        The Director considers:
          1. voice_preference (auto → Director decides based on content)
          2. TaskClassifier output + confidence
          3. Message length heuristic (short → QUICK, long → FULL)
          4. Token budget remaining
          5. user_preference override (e.g. from UI setting)

        Returns:
            ExecutionMode.QUICK, .AGENTIC, or .FULL

        This is a heuristic — the Director can always override later
        via escalate()/de_escalate() based on real execution feedback.
        """
        # ── Step 0: user_preference overrides everything ────────────────
        if user_preference:
            parsed = ExecutionMode.from_string(user_preference)
            if parsed:
                return parsed

        msg_len = len(message_text)

        # ── Step 1: voice_preference overrides ──────────────────────────
        if voice_preference == "quick_first" and from_voice:
            return ExecutionMode.QUICK

        # ── Step 2: low budget → QUICK ──────────────────────────────────
        if token_budget_remaining < BUDGET_ABSOLUTE_MIN:
            return ExecutionMode.QUICK

        # ── Step 3: TaskClassifier high confidence → trust it ──────────
        if confidence >= CLASSIFIER_CONFIDENCE_HIGH:
            if task_class in ("question", "greeting", "simple_command"):
                return ExecutionMode.QUICK
            if task_class in ("research", "explore", "investigate"):
                return ExecutionMode.FULL
            if task_class in (
                "tool_request", "multi_step", "complex_command",
            ):
                return ExecutionMode.AGENTIC

        # ── Step 4: message length heuristics (content-based) ──────────
        if msg_len <= MESSAGE_LENGTH_SHORT:
            # Very short message → likely QUICK
            return ExecutionMode.QUICK

        if msg_len >= MESSAGE_LENGTH_LONG:
            # Long message with clear multi-step intent → FULL
            return ExecutionMode.FULL

        # ── Step 5: task_class with low/medium confidence ──────────────
        if task_class in ("research", "explore", "investigate", "complex"):
            return ExecutionMode.FULL if confidence > 0.5 else ExecutionMode.AGENTIC

        if task_class in ("tool_request", "multi_step", "complex_command"):
            return ExecutionMode.AGENTIC

        if task_class == "voice_first":
            # Voice with auto preference — decide by content, not by mode
            return ExecutionMode.AGENTIC if msg_len > MESSAGE_LENGTH_SHORT else ExecutionMode.QUICK

        # ── Step 6: default ────────────────────────────────────────────
        return ExecutionMode.AGENTIC

    # ── Escalation decision (mid-task) ─────────────────────────────────

    def check_escalation(
        self,
        review_verdict: Optional[ReviewVerdict],
        tool_result_summary: str,
        token_budget_remaining: int,
        turn_id: Optional[str] = None,
    ) -> bool:
        """
        Check if the current mode should be escalated.

        Called after each tool execution + review.
        Returns True if mode was escalated.

        Escalation triggers:
          1. Reviewer VETO'd the last step → escalate (current approach failed)
          2. Tool result indicates more work needed → escalate
          3. Token budget has plenty of room and task is complex → escalate
        """
        if self.mode == ExecutionMode.FULL:
            return False  # Already at max

        mode_budget = get_token_budget(self.mode.value)

        # Trigger 1: Budget minimum — never escalate if budget too low
        if token_budget_remaining < BUDGET_ABSOLUTE_MIN:
            return False
            return False
        if token_budget_remaining >= mode_budget:
            # Budget was bumped beyond this mode — don't escalate via budget trigger
            # but still check the other triggers (veto, incomplete)
            pass

        # Trigger 2: Reviewer veto
        if review_verdict == ReviewVerdict.VETO:
            self.escalate(
                reason="Reviewer veto'd step — need higher mode to resolve",
                turn_id=turn_id,
                token_budget=token_budget_remaining,
            )
            return True

        # Trigger 3: Tool result indicates incomplete work
        incomplete_keywords = [
            "more research needed",
            "need more information",
            "need more",
            "more research",
            "multiple files found",
            "found multiple",
            "further investigation",
            "incomplete",
            "partial result",
            "found several",
            "requires additional",
            "more work needed",
        ]
        summary_lower = tool_result_summary.lower()
        if any(kw in summary_lower for kw in incomplete_keywords):
            self.escalate(
                reason=f"Tool result indicates more work: '{tool_result_summary[:80]}'",
                turn_id=turn_id,
                token_budget=token_budget_remaining,
            )
            return True

        # Trigger 4: Significant budget remaining and complex task
        if mode_budget > 0 and token_budget_remaining < mode_budget:
            budget_used = max(0, mode_budget - token_budget_remaining)
            budget_used_ratio = budget_used / mode_budget
            # M1 FIX: only escalate on unused budget if task is complex
            # (has enough steps or tool diversity to warrant escalation)
            _total = len(self.items)
            _is_complex = _total >= 3 or len(set(
                i.tool for i in self.items if i.tool
            )) >= 2
            if budget_used_ratio < BUDGET_RATIO_ESCALATE and _is_complex:
                self.escalate(
                    reason=f"Budget mostly unused ({token_budget_remaining}/{mode_budget}) "
                           f"and task is complex ({_total} steps) — escalating",
                    turn_id=turn_id,
                    token_budget=token_budget_remaining,
                )
                return True

        return False

    # ── Original queue methods (unchanged) ────────────────────────────

    def next_ready(self, session_id: str = "default") -> Optional[QueueItem]:
        """
        Next item whose dependencies are all completed.
        Caducean-modulated: if Caducean signals CONTRACT, reduce queue depth.
        None if none ready.
        """
        completed = set(self.completed_ids)
        ready_items = []
        for item in self.items:
            if item.step_id in self.completed_ids:
                continue
            if item.step_id in self.vetoed_ids:
                continue
            if item.step_id in self.failed_ids:
                continue
            if all(dep in completed for dep in item.depends_on):
                ready_items.append(item)

        if not ready_items:
            return None

        # Caducean modulation: EXPAND=0, CONTRACT=1, MAINTAIN=2, TOPO_VIOLATION=3
        try:
            from backend.gateway.iris_ffi import ffi_caducean_recommend

            rec = ffi_caducean_recommend(session_id)
        except Exception:
            rec = 2  # MAINTAIN on error

        if rec == 3:  # TOPO_VIOLATION — stop the line
            from .exceptions import TopologyViolationException

            raise TopologyViolationException(
                session_id=session_id,
                direction_signal=None,
            )

        if rec == 1:  # CONTRACT — return only critical items
            critical = [i for i in ready_items if i.critical]
            return critical[0] if critical else ready_items[0]

        # EXPAND or MAINTAIN — return first ready
        return ready_items[0]

    def all_ready_items(self, session_id: str = "default") -> List["QueueItem"]:
        """
        Phase 4: return ALL items whose dependencies are satisfied and which
        are not completed/vetoed. Drives concurrent execution of independent
        (parallel_safe) steps in a single loop cycle.

        Caducean modulation (same semantics as next_ready):
          - rec == 3 (TOPO_VIOLATION) → raise TopologyViolationException
          - rec == 1 (CONTRACT) → return only critical items
        """
        completed = set(self.completed_ids)
        ready_items: List["QueueItem"] = []
        for item in self.items:
            if item.step_id in self.completed_ids:
                continue
            if item.step_id in self.vetoed_ids:
                continue
            if item.step_id in self.failed_ids:
                continue
            if all(dep in completed for dep in item.depends_on):
                ready_items.append(item)

        if not ready_items:
            return []

        # Caducean modulation: EXPAND=0, CONTRACT=1, MAINTAIN=2, TOPO_VIOLATION=3
        try:
            from backend.gateway.iris_ffi import ffi_caducean_recommend

            rec = ffi_caducean_recommend(session_id)
        except Exception:
            rec = 2  # MAINTAIN on error

        if rec == 3:  # TOPO_VIOLATION — stop the line
            from .exceptions import TopologyViolationException

            raise TopologyViolationException(
                session_id=session_id,
                direction_signal=None,
            )

        if rec == 1:  # CONTRACT — only critical items are ready
            critical = [i for i in ready_items if i.critical]
            return critical

        return ready_items

    def mark_complete(self, step_id: str) -> None:
        if step_id not in self.completed_ids:
            self.completed_ids.append(step_id)

    def mark_vetoed(self, step_id: str) -> None:
        if step_id not in self.vetoed_ids:
            self.vetoed_ids.append(step_id)

    def mark_failed(self, step_id: str) -> None:
        """Record a step as permanently failed (retry + graft exhausted)."""
        if step_id not in self.failed_ids:
            self.failed_ids.append(step_id)

    def abort_descendants(
        self, failed_step_id: str, reason: str = "[ABORTED: dependency failed]"
    ) -> List[str]:
        """
        Mark every not-yet-completed step that (transitively) depends on
        `failed_step_id` as failed with an abort reason, so the scheduler
        skips them. Returns the list of aborted step_ids.

        A step is aborted if any of its depends_on ids is in the failed set
        (including the originally failed step) and it is not already done.
        Iterates to a fixpoint so multi-level dependency chains collapse.
        """
        aborted: List[str] = []
        failed = set(self.failed_ids)
        failed.add(failed_step_id)
        changed = True
        while changed:
            changed = False
            for item in self.items:
                if item.step_id in self.completed_ids:
                    continue
                if item.step_id in self.vetoed_ids:
                    continue
                if item.step_id in failed:
                    continue
                if any(dep in failed for dep in item.depends_on):
                    failed.add(item.step_id)
                    item.result = reason
                    self.mark_failed(item.step_id)
                    aborted.append(item.step_id)
                    changed = True
        return aborted

    def add_item(self, item: QueueItem) -> None:
        self.items.append(item)

    def resolve_dependent_params(
        self,
        completed_item: "QueueItem",
        result: Optional[str],
        max_result_len: int = 4000,
    ) -> List[str]:
        """
        Phase 3 (Gap 3): propagate a completed step's output into the params of
        pending steps that depend on it, so later steps consume real results
        instead of static/empty params.

        A pending item receives the injection if EITHER:
          1. Explicit: completed_item.step_id is in the pending item's
             depends_on list.
          2. Implicit sequential: the pending item has no explicit depends_on
             and its step_number == completed_item.step_number + 1 (linear plan).

        Injection is non-destructive:
          - Accumulates into item.params["_dependency_results"][step_id] = result
            (a dict the downstream tool/step can read by source step id).
          - Substitutes {{step_id}} / {{step_number}} placeholders found in any
            string param value with the completed result (truncated).

        Returns the list of step_ids that received the injection.
        """
        injected: List[str] = []
        if completed_item is None or not result:
            return injected
        _snippet = result[:max_result_len]
        _ph_id = "{{" + completed_item.step_id + "}}"
        _ph_num = "{{" + str(completed_item.step_number) + "}}"
        for item in self.items:
            if item.step_id in self.completed_ids or item.step_id in self.vetoed_ids:
                continue
            _explicit = completed_item.step_id in item.depends_on
            _sequential = (
                not item.depends_on
                and item.step_number == completed_item.step_number + 1
            )
            if not (_explicit or _sequential):
                continue
            # 1. accumulate by source step id (read-only reference for tools)
            dep = item.params.get("_dependency_results")
            if not isinstance(dep, dict):
                dep = {}
                item.params["_dependency_results"] = dep
            dep[completed_item.step_id] = _snippet
            # 2. placeholder substitution in string params
            for _k, _v in list(item.params.items()):
                if isinstance(_v, str) and (_ph_id in _v or _ph_num in _v):
                    item.params[_k] = _v.replace(_ph_id, _snippet).replace(
                        _ph_num, _snippet
                    )
            injected.append(item.step_id)
        return injected

    def is_complete(self) -> bool:
        active = [
            i
            for i in self.items
            if i.step_id not in self.vetoed_ids
            and i.step_id not in self.failed_ids
        ]
        return all(i.step_id in self.completed_ids for i in active)

    def hit_cycle_limit(self) -> bool:
        return self.cycle_count >= self.max_cycles


# ── Reviewer ────────────────────────────────────────────────────────────────


class Reviewer:
    """
    Validates Director queue items before Explorer executes them.
    Uses the same model as Director and Explorer — one model, three roles.
    Reads from Mycelium graph. Never writes to it.

    The Reviewer is a membrane, not a gate.
    It never blocks on failure — always falls back to PASS.
    """

    REVIEWER_MAX_TOKENS = 200
    REVIEWER_TEMPERATURE = 0.0

    def __init__(self, adapter, memory_interface):
        self.adapter = adapter
        self.memory = memory_interface

    def review(
        self,
        item: QueueItem,
        completed_steps: List[QueueItem],
        context_package,
        is_mature: bool,
    ) -> tuple:
        """
        Returns (ReviewVerdict, output: str | None)
        Never raises. Falls back to (PASS, None) on any error.
        """
        try:
            if not is_mature or not hasattr(context_package, "gradient_warnings"):
                return self._heuristic_review(item, completed_steps)

            prompt = self._build_review_prompt(
                item=item,
                completed_steps=completed_steps,
                gradient_warnings=context_package.gradient_warnings or "",
                active_contracts=context_package.active_contracts or "",
            )

            response = self.adapter.infer(
                prompt,
                role="EXECUTION",
                max_tokens=self.REVIEWER_MAX_TOKENS,
                temperature=self.REVIEWER_TEMPERATURE,
            )

            return self._parse_verdict(response.raw_text)

        except Exception:
            return ReviewVerdict.PASS, None

    def _heuristic_review(
        self,
        item: QueueItem,
        completed_steps: List[QueueItem],
    ) -> tuple:
        try:
            desc_lower = (item.description or "").lower()

            _DESTRUCTIVE = [
                "delete all", "drop table", "drop database", "rm -rf",
                "format disk", "truncate table", "destroy all", "wipe all",
                "overwrite all", "factory reset", "nuke", "purge all",
            ]
            for kw in _DESTRUCTIVE:
                if kw in desc_lower:
                    return ReviewVerdict.VETO, f"Destructive keyword detected: '{kw}'"

            for prev in completed_steps[-5:]:
                if (prev.description or "").lower().strip() == desc_lower.strip():
                    return (
                        ReviewVerdict.REFINE,
                        f"Duplicate of step {prev.step_number} (already completed) — skip or rephrase",
                    )

            return ReviewVerdict.PASS, None

        except Exception:
            return ReviewVerdict.PASS, None

    def _build_review_prompt(self, item, completed_steps, gradient_warnings, active_contracts):
        completed_summary = (
            "\n".join(
                f"- Step {s.step_number}: {s.description} [done]"
                for s in completed_steps[-3:]
            )
            or "None"
        )
        return (
            f"OBJECTIVE: {item.objective_anchor}\n\n"
            f"COMPLETED STEPS (last 3):\n{completed_summary}\n\n"
            f"GRADIENT WARNINGS:\n{gradient_warnings[:200] or 'None'}\n\n"
            f"ACTIVE CONTRACTS:\n{active_contracts[:200] or 'None'}\n\n"
            f"NEXT STEP TO REVIEW:\n"
            f"  Step {item.step_number}: {item.description}\n"
            f"  Tool: {item.tool or 'none'}\n\n"
            "Does this step conflict with a gradient warning or contract?\n"
            "Does it contradict what was already completed?\n\n"
            "Respond with JSON only:\n"
            '{"verdict":"pass|refine|veto",'
            '"reason":"one sentence or empty string",'
            '"refined":"improved step description or empty string"}'
        )

    def _parse_verdict(self, raw: str) -> tuple:
        try:
            m = re.search(r"\{[\s\S]+?\}", raw)
            if not m:
                return ReviewVerdict.PASS, None
            data = json.loads(m.group())
            v = data.get("verdict", "pass").lower()
            reason = data.get("reason", "") or None
            refined = data.get("refined", "") or None

            if v == "veto":
                return ReviewVerdict.VETO, reason
            if v == "refine" and refined:
                return ReviewVerdict.REFINE, refined
            return ReviewVerdict.PASS, None
        except Exception:
            return ReviewVerdict.PASS, None
