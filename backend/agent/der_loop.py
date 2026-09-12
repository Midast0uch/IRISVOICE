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

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:  # pragma: no cover — typing only, zero runtime cost
    from backend.core_models import BatchOutcome, BatchToolCall
    from backend.agent.tool_envelope import ToolResultEnvelope

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
    # Goal contract (specs/goal-contract-coverage, T2) — the task node's
    # required-fact set. required_facts is the FLOOR (immutable to the agent);
    # ceiling_facts are agent discoveries (never blocking); covered_facts is
    # the VERIFIED subset of required; blocked_facts carries
    # {"fact", "reason", "evidence"} dicts; contract_version increments on
    # every amendment. expected_output stays the human summary;
    # verified_fraction carries coverage C. All additive with defaults.
    required_facts: List[str] = field(default_factory=list)
    ceiling_facts: List[str] = field(default_factory=list)
    covered_facts: List[str] = field(default_factory=list)
    blocked_facts: List[Dict[str, str]] = field(default_factory=list)
    contract_version: int = 1


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
    batch: Optional["BatchToolCall"] = None  # REQ-24 (T37): composite batch node this item carries; materialized by expand_batch_nodes()
    # REQ-21 (T40): compressed context for sub-loop children — survives DCP
    # pruning, carries Understanding/Awareness/Direction + coordinate_ref.
    # Defaults to None for non-split-created steps (every existing call site
    # is unaffected — the field is only populated by _split_step, T41).
    node_record: Optional[NodeRecord] = None  # REQ-3 T8: EVERY node carries its memory record
    # specs/tool-result-envelope T5: the write-time envelope (REQ-1 AC1.2).
    # Stays Optional so pre-envelope items in flight degrade per AC2.1's edge
    # case (fall back to existing bounded evidence). Stamped ONCE at the
    # finalize site — never re-derived per consumer.
    envelope: Optional["ToolResultEnvelope"] = None
    # T5/T6: the doc-store id captured at execution time (_capture_tool_result
    # returns it; the finalize site reads it for the envelope's raw_ref —
    # AC1.3 doc-id-only, Pacman chunk ids never waited on).
    captured_doc_id: Optional[str] = None
    # T5 (KD-9): planner-DECLARED criticality (load-bearing|supporting|
    # cosmetic) — intent only until the finalize site confirms it (AC1.6).
    declared_criticality: str = "supporting"
    # Session-318 T16 (REQ-9 AC9.5/AC9.6): VLM in-site recovery lane.
    # recovery_of = parent step_id ("" = not a recovery); recovery_seeds =
    # exact unvisited in-site URLs resolved at trigger time. The resolver
    # keeps full tool authority; post-resolve enrichment attaches the seeds
    # only when it independently chooses a crawl.
    recovery_of: str = ""
    recovery_seeds: List[str] = field(default_factory=list)
    # Session-318 T18 (REQ-11): execution accounting. timed_out marks a
    # deadline expiry (envelope status=timeout); dispatch_started_at
    # (monotonic) feeds elapsed_s and the stall warning at finalize.
    timed_out: bool = False
    dispatch_started_at: float = 0.0

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
        # Session 247 FIX: the TaskClassifier emits SUFFIXED labels
        # ("research_task", "code_task", "planning_task" — see
        # TASK_CLASS_SPACE_MAP in kyudo.py), but this matcher compared bare
        # "research"/"explore"/… — labels the classifier NEVER emits. Every
        # classified task therefore fell through to the AGENTIC default
        # (legacy card-less execution: no card_id on events, no terminal
        # task:done, frozen verbs). Normalize the suffix before matching.
        _tc = (
            task_class[:-5]
            if isinstance(task_class, str) and task_class.endswith("_task")
            else task_class
        )
        if _tc in ("research", "explore", "investigate", "complex"):
            return ExecutionMode.FULL if confidence > 0.5 else ExecutionMode.AGENTIC

        if _tc in ("tool_request", "multi_step", "complex_command"):
            return ExecutionMode.AGENTIC

        if _tc == "voice_first":
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

    def expand_batch_nodes(self) -> int:
        """REQ-24 AC24.1 (T37): materialize READY batch-carrying nodes into children.

        Only nodes whose deps are satisfied expand (a batch behind a dep waits).
        Parents are marked complete — they are groupings, not work — so this is
        idempotent (completed parents never re-expand) and children flow through
        all_ready_items like any other item. Returns children materialized.
        """
        completed = set(self.completed_ids)
        materialized = 0
        for item in list(self.items):
            if getattr(item, "batch", None) is None:
                continue
            if item.step_id in self.completed_ids:
                continue
            if item.step_id in self.vetoed_ids or item.step_id in self.failed_ids:
                continue
            if not all(dep in completed for dep in item.depends_on):
                continue
            children = expand_batch_node(item)
            self.items.extend(children)
            materialized += len(children)
            self.mark_complete(item.step_id)
            logger.debug(
                "[DER] batch expand batch_id=%s children=%d parallel=%s",
                getattr(item.batch, "batch_id", "?"), len(children),
                bool(getattr(item.batch, "parallel_safe", False)
                     and getattr(item.batch, "independent", False)),
            )
        return materialized

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


# ── REQ-24 (T37): DER-native batch expansion & per-resource governance ─────

BRAIN_VIS_TOOL = "brain.vis"  # DER batch tool key for direct Brain-vision batches
BRAIN_VIS_MAX_CONCURRENCY = 4  # AC24.2: DER-owned Brain-Vis cap (Crawl reuses the orchestrator caps; VLM reuses the lease)

_brain_vis_sem: Optional["asyncio.Semaphore"] = None


def brain_vis_semaphore() -> "asyncio.Semaphore":
    """Process-wide DER-owned Brain-Vis semaphore (AC24.2). Lazy: no loop binding at import."""
    global _brain_vis_sem
    if _brain_vis_sem is None:
        _brain_vis_sem = asyncio.Semaphore(BRAIN_VIS_MAX_CONCURRENCY)
    return _brain_vis_sem


def reset_brain_vis_semaphore_for_testing() -> None:
    """Drop the cached semaphore so tests start from a clean permit pool."""
    global _brain_vis_sem
    _brain_vis_sem = None


def expand_batch_node(item: "QueueItem") -> List["QueueItem"]:
    """REQ-24 AC24.1/AC24.4 (T37): expand a batch-carrying node into releasable items.

    - No batch → [item] unchanged.
    - parallel_safe + independent → one child per batch item, all sharing the
      parent's deps (released together through all_ready_items).
    - Otherwise (AC24.4) → children chained in declared order (child[i] depends
      on child[i-1]) so existing readiness releases them sequentially; children
      are NOT parallel_safe so the concurrent filter skips them.
    - Empty items → [] (parent completes immediately; the fold yields an empty outcome).
    Pure: never touches the queue.
    """
    batch = getattr(item, "batch", None)
    if batch is None:
        return [item]
    payloads = list(getattr(batch, "items", None) or [])
    if not payloads:
        return []
    parallel = bool(getattr(batch, "parallel_safe", False)) and bool(
        getattr(batch, "independent", False)
    )
    children: List["QueueItem"] = []
    prev: Optional[str] = None
    for i, payload in enumerate(payloads):
        params = dict(payload) if isinstance(payload, dict) else {"value": payload}
        params.setdefault("_batch_id", getattr(batch, "batch_id", ""))
        params.setdefault("_batch_index", i)
        deps = list(getattr(item, "depends_on", None) or [])
        if not parallel and prev is not None:
            deps = deps + [prev]
        children.append(QueueItem(
            step_id=f"{item.step_id}#{i}",
            step_number=item.step_number,
            description=f"{item.description} [batch {i + 1}/{len(payloads)}]",
            tool=getattr(batch, "tool", None) or item.tool,
            params=params,
            depends_on=deps,
            critical=item.critical,
            parallel_safe=parallel,
            objective_anchor=item.objective_anchor,
            coordinate_signal=item.coordinate_signal,
            independent=parallel,
            node_record=item.node_record,
        ))
        prev = children[-1].step_id
    return children


async def run_batch_children(batch, children: List["QueueItem"], executor) -> "BatchOutcome":
    """REQ-24 AC24.2/AC24.3 (T37): execute expanded children under per-tool caps; fold ONE BatchOutcome.

    - brain.vis children run under the DER-owned semaphore(4); every other tool
      is governed by its own layer (orchestrator caps, VLM lease) — DER adds nothing.
    - executor(child) returns an (item_key, ok, result, error) tuple or a
      BatchItemResult (both shapes collect_batch_outcome accepts). An executor
      raise becomes THAT item's failure only — the node still completes
      (DAG abort rules unchanged).
    - Outcomes fold via collect_batch_outcome (AC24.3; lazy import keeps this
      module's import graph unchanged).
    """
    from backend.agent.query_synthesizer import collect_batch_outcome

    async def _guarded(child):
        try:
            return await executor(child)
        except Exception as exc:  # noqa: BLE001 — one item's death is that item's failure
            return (getattr(child, "step_id", "?"), False, None,
                    f"{type(exc).__name__}: {exc}")

    if children and (getattr(children[0], "tool", None) == BRAIN_VIS_TOOL):
        sem = brain_vis_semaphore()

        async def _gated(child):
            async with sem:
                return await _guarded(child)

        results = await asyncio.gather(*(_gated(c) for c in children))
    else:
        results = await asyncio.gather(*(_guarded(c) for c in children))
    return collect_batch_outcome(batch, list(results))


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

            # Claim-coverage review (session-321): repeats by claim, not by
            # words. Returns a REFINE-to-read description or None.
            _claim_refine = self._claim_coverage_refine(item, completed_steps)
            if _claim_refine is not None:
                return ReviewVerdict.REFINE, _claim_refine

            return ReviewVerdict.PASS, None

        except Exception:
            return ReviewVerdict.PASS, None

    def _claim_coverage_refine(
        self,
        item: QueueItem,
        completed_steps: List[QueueItem],
    ) -> Optional[str]:
        """REFINE a candidate whose claims are all already covered into a
        read/compose step — never into another gather.

        Claims are per-family (gather: normalized target URLs; the envelope's
        stamped sources are the completed-claims side). The refined text names
        a READ of the gathered documents, so the post-review resolver picks
        ``get_rendered_documents`` (idempotent, side-effect free) instead of
        paying for another crawl. A read cannot recrawl by construction.

        Rule 2 reads the envelope's own semantic labels (novelty/stuck_shape),
        not addresses: two consecutive circling envelopes mean the loop is
        re-gathering known bodies whatever the next step's words say.

        Deterministic, zero LLM, zero encodes. Fail-open to None (PASS).
        VETO is never returned here — repeats are rerouted, not blocked.
        """
        try:
            from backend.agent.tool_envelope import normalize_url, tool_family
        except Exception:
            return None
        try:
            _fam = tool_family(getattr(item, "tool", None))
            _p = getattr(item, "params", None) or {}
            _cand: List[str] = []
            try:
                _raw_urls = list(_p.get("known_urls") or [])
                if _p.get("url"):
                    _raw_urls.append(_p["url"])
                for _u in _raw_urls:
                    _n = normalize_url(str(_u))
                    if _n and _n not in _cand:
                        _cand.append(_n)
            except Exception:
                _cand = []
            _done_urls: set = set()
            _done_ids: List[str] = []
            for _prev in completed_steps[-8:]:
                _env = getattr(_prev, "envelope", None)
                if _env is None:
                    continue
                try:
                    for _s in (getattr(_env, "sources", None) or []):
                        _n = normalize_url(str(_s))
                        if _n:
                            _done_urls.add(_n)
                except Exception:
                    pass
                _done_ids.append(str(getattr(_prev, "step_number", "?")))
            # Rule 1: every claimed address already gathered → read instead.
            if _cand and _done_urls and all(u in _done_urls for u in _cand):
                _ids = ",".join(_done_ids[-3:] or ["?"])
                return (
                    f"All {len(_cand)} fetch target(s) already gathered "
                    f"(steps {_ids}) — read the gathered documents and "
                    f"compose the answer from them; do not dispatch "
                    f"another crawl."
                )
            # Rule 2: the loop is circling — last two settled envelopes both
            # repeat known bodies. Steer an unresolved or gather candidate to
            # read/compose. Explicit non-gather tools pass through untouched.
            if _fam in ("gather", "direct") and (
                getattr(item, "tool", None) is None or _fam == "gather"
            ):
                _circling = 0
                for _prev in completed_steps[-2:]:
                    _env = getattr(_prev, "envelope", None)
                    if _env is None:
                        break
                    _nov = str(getattr(_env, "novelty", "") or "")
                    _shape = str(getattr(_env, "stuck_shape", "") or "")
                    if _nov.startswith("repeat_of_") or _shape == "circling":
                        _circling += 1
                    else:
                        break
                if _circling >= 2:
                    # Session-322 (owner correction): REFINE-to-read fires
                    # ONLY on fruitful search — completed envelopes hold
                    # sources/doc_ids and match != empty/mismatched. An empty
                    # search must PASS so the Director can try_different
                    # (retry_same only for transient/rate_limited).
                    try:
                        _fruitful = False
                        for _prev in completed_steps[-2:]:
                            _env = getattr(_prev, "envelope", None)
                            if _env is None:
                                continue
                            _srcs = list(getattr(_env, "sources", None) or [])
                            _match = str(getattr(_env, "match", "") or "")
                            _doc = ""
                            try:
                                _doc = str((getattr(_env, "raw_ref", None) or {}).get("doc_id") or "")
                            except Exception:
                                _doc = ""
                            if (_srcs or _doc) and _match not in ("", "empty", "mismatched"):
                                _fruitful = True
                                break
                        if not _fruitful:
                            return None
                    except Exception:
                        return None
                    return (
                        f"Last {_circling} gather steps circled "
                        f"already-known sources — read the gathered "
                        f"documents and compose the answer from them; do "
                        f"not dispatch another crawl."
                    )
            return None
        except Exception:
            return None

    def _build_review_prompt(self, item, completed_steps, gradient_warnings, active_contracts):
        # T8 (specs/tool-result-envelope REQ-4 AC1.1): completed steps render
        # their envelope LINE (status + wrapper + summary) when one exists —
        # the Reviewer's INPUTS are envelope views, never the raw result.
        # ReviewVerdict semantics are LOCKED unchanged (AC4.4).
        completed_summary = (
            "\n".join(
                (
                    f"- Step {s.step_number}: {s.description} [done] "
                    f"{s.envelope.line()}"
                    if getattr(s, "envelope", None) is not None
                    else f"- Step {s.step_number}: {s.description} [done]"
                )
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


# ─────────────────────────────────────────────────────────────────────────────
# T14 (REQ-8 + REQ-11): StepFindingsAccumulator — per-run strict projection
# with semantic cross-source verification.
# ─────────────────────────────────────────────────────────────────────────────
def _values_equivalent(a, b) -> bool:
    """REQ-11 AC3 semantic reconciliation for the discrepancy gate.

    Numerics reconcile within a tolerance — pinned by the T14 unit suite
    (899 vs 900 is ONE claim: USD-only, fx reconciliation deferred) while a
    real spread (1999 vs 2499) is FALSE. The boundary is deliberately simple:
    1.0 absolute OR 1% relative, whichever is larger, so cent drift and
    rounding noise never fabricate a discrepancy and a scalper's price never
    disguises as the MSRP. Non-numerics compare by equality; object payloads
    are never "equivalent" when they differ in identity.
    """
    if a is b:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= max(1.0, 0.01 * max(abs(a), abs(b)))
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return a == b
    return a == b


class StepFindingsAccumulator:
    """Bounded aggregator for what the crawl actually LEARNED.

    REQ-8: every page is projected down to the goal's declared fields. Raw
    HTML, boilerplate or anything not declared is dropped at the gate.

    REQ-11: any field marked "critical" by the task spec must appear on
    >=2 independent hostnames before it counts as a proof. Condition-aware
    (refurbished vs new) and bundle-vs-standalone aware so two "different
    prices" for the same product don't merge into a falsely-verified finding.
    Parked/walled sources NEVER corroborate.

    Not thread-safe; concurrency is owned by the call sites (the
    orchestrator dispatches under asyncio semaphores — the accumulator is
    read/written only by the synthesis path).
    """

    def __init__(self, goal_fields: Optional[set] = None):
        self._goal_fields: set = {str(f) for f in (goal_fields or set()) if str(f).strip()}
        self._instance: dict = {}
        self._field_votes: dict = {}
        self._pages_seen: list = []
        self._total_bytes = 0

    def add(self, url: str, payload: dict, parked: bool = False) -> None:
        if not isinstance(payload, dict):
            return
        host = ""
        try:
            from urllib.parse import urlparse
            host = (urlparse(url).netloc or url).lower()
        except Exception:  # noqa: BLE001 — tolerate malformed URLs
            pass
        self._pages_seen.append({"url": url, "host": host, "parked": parked})
        # REQ-8 AC1: PROJECT to goal fields only — nothing outside the schema
        # is persisted anywhere.
        projection: dict = {}
        for field_name in self._goal_fields:
            v = payload.get(field_name)
            if v is not None:
                projection[field_name] = v
        _bytes = sum(len(str(v).encode("utf-8", "ignore")) for v in projection.values())

        # Per-source account of votes is what REQ-11 needs to verify.
        # A parked source contributes no corroboration and no content — it is
        # tracked only as seen (pages_seen) so review knows it was attempted.
        # A parked source never corroborates: it is attached to pages_seen so
        # reviews see it was attempted, but it is invisible to every
        # verification vote. (Otherwise a walled-but-claimed page would mutate
        # the quorum count.)
        if parked:
            return

        cond = str(payload.get("_condition") or "").strip().lower() or "unspecified"
        bundle = str(payload.get("_bundle") or payload.get("_bundle_kind") or "").strip().lower() or "unspecified"
        for field_name, v in projection.items():
            entry = self._field_votes.setdefault(field_name, {"sources": set(), "conditions": {}})
            entry["sources"].add(host)
            # Condition key is the discriminating axis: new vs refurbished must
            # NOT merge (two different prices for one SKU are two data points).
            entry["conditions"][cond] = entry["conditions"].get(cond, 0) + 1
            entry["bundles"] = entry.get("bundles", {})
            entry["bundles"][bundle] = entry["bundles"].get(bundle, 0) + 1
            # REQ-11 AC11.4 (T27): keep the CLAIMS — field value per source —
            # so an irreconcilable spread (official 1999 vs scalper 2499 in
            # the SAME condition) surfaces as a recorded discrepancy instead
            # of silently reducing to the last write. A source re-voting for
            # the same field REPLACES its prior claim (idempotent re-add).
            claims = entry.setdefault("claims", [])
            claims[:] = [c for c in claims if c.get("host") != host]
            claims.append({
                "host": host, "value": v, "condition": cond, "bundle": bundle,
            })
        for k, v in projection.items():
            self._instance[k] = v
        self._total_bytes += _bytes

        # REQ-8 AC3 (hierarchical summarization): anything over the bound
        # gets a compressed view of the repr; we never store raw dumps.
        if self._total_bytes > 32_000:
            for k, v in list(self._instance.items()):
                self._instance[k] = self._collapse(str(v), limit=256)
            self._total_bytes = sum(len(str(x)) for x in self._instance.values())

    def _collapse(self, s: str, limit: int = 256) -> str:
        if len(s) <= limit:
            return s
        return s[: limit - 64] + "…" + s[-64:]

    def snapshot(self) -> dict:
        verified = {}
        for field, votes in self._field_votes.items():
            conditions = votes.get("conditions", {}) or {}
            bundles = votes.get("bundles", {}) or {}
            sources = votes.get("sources", set()) or set()
            claims = votes.get("claims", []) or []
            # REQ-11 AC11.4: within ONE (condition, bundle) bucket, two
            # semantically DISTINCT values = an irreconcilable spread —
            # flagged with all claims kept. SEMANTIC NORMALIZATION (AC11.3):
            # numerics reconcile within a tolerance (USD-only here — fx
            # reconciliation is deferred per the REQ-11 note), so $899 vs
            # $900 is ONE claim while $1999 vs $2499 is a discrepancy.
            bucket_values: dict[tuple, list] = {}
            for c in claims:
                bucket_values.setdefault(
                    (c.get("condition") or "", c.get("bundle") or ""), []
                ).append(c.get("value"))
            discrepancy = False
            for vals in bucket_values.values():
                for i in range(1, len(vals)):
                    if not _values_equivalent(vals[0], vals[i]):
                        discrepancy = True
                        break
                if discrepancy:
                    break
            verified[field] = {
                "verified": (
                    len(sources) >= 2
                    and len(conditions) <= 1
                    and len(bundles) <= 1
                    and not discrepancy
                ),
                "discrepancy": discrepancy,
                "claims": claims,
                "corroborations": len(sources),
                "unit_count": sum(conditions.values()) if conditions else 0,
                "condition_distribution": dict(conditions),
                "bundle_distribution": dict(bundles),
            }
        return {
            "instance": self._instance,
            "verified": verified,
            "total_bytes": self._total_bytes,
        }

    def total_bytes(self) -> int:
        return self._total_bytes

