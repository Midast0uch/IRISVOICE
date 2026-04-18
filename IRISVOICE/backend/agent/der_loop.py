"""
DER Loop — Director · Explorer · Reviewer
File: IRISVOICE/backend/agent/der_loop.py

The Reviewer is a membrane, not a gate.
It never blocks on failure — always falls back to PASS.

Source: specs/agent_loop_design.md
Gate 1 Step 1.1
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import re
import json


class ReviewVerdict(Enum):
    PASS   = "pass"    # step approved as-is
    REFINE = "refine"  # step approved with modification
    VETO   = "veto"    # step rejected — Director must queue alternative


@dataclass
class QueueItem:
    """
    One item in the Director's broadcast queue.
    Richer than PlanStep — carries DER-specific orchestration fields.
    """
    step_id: str
    step_number: int
    description: str
    tool: Optional[str]                = None
    params: Dict[str, Any]             = field(default_factory=dict)
    depends_on: List[str]              = field(default_factory=list)
    critical: bool                     = True
    objective_anchor: str              = ""   # overall task goal — never changes
    coordinate_signal: str             = ""   # Mycelium coordinate region targeted
    veto_count: int                    = 0
    refined_description: Optional[str] = None  # set by Reviewer on REFINE
    depth_layer: int                   = 1     # trailing crystallizer depth level
    gap_analysis: Optional[str]        = None  # trailing Director gap description


@dataclass
class DirectorQueue:
    """
    The Director's live broadcast queue.
    Initialized from ExecutionPlan.steps, updated as Explorer feeds back.

    The Director re-reads the Mycelium graph before every cycle and can:
    - Update item descriptions based on new coordinates
    - Add new items when the graph reveals gaps
    - Remove items when the graph shows they're no longer needed
    """
    objective: str
    items: List[QueueItem]   = field(default_factory=list)
    completed_ids: List[str] = field(default_factory=list)
    vetoed_ids: List[str]    = field(default_factory=list)
    cycle_count: int         = 0
    max_cycles: int          = 40   # DER_MAX_CYCLES
    max_veto_per_item: int   = 2    # DER_MAX_VETO_PER_ITEM

    def next_ready(self) -> Optional[QueueItem]:
        """Next item whose dependencies are all completed. None if none ready."""
        completed = set(self.completed_ids)
        for item in self.items:
            if item.step_id in self.completed_ids:
                continue
            if item.step_id in self.vetoed_ids:
                continue
            if all(dep in completed for dep in item.depends_on):
                return item
        return None

    def mark_complete(self, step_id: str) -> None:
        if step_id not in self.completed_ids:
            self.completed_ids.append(step_id)

    def mark_vetoed(self, step_id: str) -> None:
        if step_id not in self.vetoed_ids:
            self.vetoed_ids.append(step_id)

    def add_item(self, item: QueueItem) -> None:
        self.items.append(item)

    def is_complete(self) -> bool:
        active = [i for i in self.items if i.step_id not in self.vetoed_ids]
        return all(i.step_id in self.completed_ids for i in active)

    def hit_cycle_limit(self) -> bool:
        return self.cycle_count >= self.max_cycles


class Reviewer:
    """
    Validates Director queue items before Explorer executes them.
    Uses the same model as Director and Explorer — one model, three roles.
    Reads from Mycelium graph. Never writes to it.

    The Reviewer is a membrane, not a gate.
    It never blocks on failure — always falls back to PASS.

    Verdicts:
        PASS   — step is clean, Explorer proceeds as-is
        REFINE — step has an issue but is fixable,
                 refined_description provided
        VETO   — step conflicts with known gradient danger or contract,
                 Director must replace this item

    Unknown territory (no gradient data) → PASS with no penalty.
    Only known danger (gradient warnings) or rule violations (contracts)
    produce VETO.
    """

    REVIEWER_MAX_TOKENS  = 200
    REVIEWER_TEMPERATURE = 0.0  # deterministic — reviewer must be consistent

    def __init__(self, adapter, memory_interface):
        self.adapter = adapter
        self.memory  = memory_interface

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
            # Fast path: graph immature or no coordinate data →
            # fall back to heuristic checks instead of always-PASS.
            if not is_mature or not hasattr(context_package, 'gradient_warnings'):
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
        """
        Safety checks used when the Mycelium graph is immature (no gradient data).

        Rules (in priority order):
        1. Destructive-operation keywords → VETO immediately
        2. Exact duplicate of a recently completed step → REFINE
        3. Unknown territory → PASS (same behaviour as before, but explicit)

        Never raises. Falls back to PASS on any internal error.
        """
        try:
            desc_lower = (item.description or "").lower()

            # Rule 1: destructive operations — these should never auto-execute
            _DESTRUCTIVE = [
                "delete all", "drop table", "drop database",
                "rm -rf", "format disk", "truncate table",
                "destroy all", "wipe all", "overwrite all",
                "factory reset", "nuke", "purge all",
            ]
            for kw in _DESTRUCTIVE:
                if kw in desc_lower:
                    return ReviewVerdict.VETO, f"Destructive keyword detected: '{kw}'"

            # Rule 2: duplicate of a recent step (last 5) → suggest skipping
            for prev in completed_steps[-5:]:
                if (prev.description or "").lower().strip() == desc_lower.strip():
                    return (
                        ReviewVerdict.REFINE,
                        f"Duplicate of step {prev.step_number} (already completed) — skip or rephrase",
                    )

            # Rule 3: unknown territory — pass through
            return ReviewVerdict.PASS, None

        except Exception:
            return ReviewVerdict.PASS, None

    def _build_review_prompt(
        self,
        item: QueueItem,
        completed_steps: List[QueueItem],
        gradient_warnings: str,
        active_contracts: str,
    ) -> str:
        """
        Compact review prompt — stays under 300 tokens.
        Only needs: current step, last 3 completed, dangers, contracts.
        """
        completed_summary = "\n".join(
            f"- Step {s.step_number}: {s.description} [done]"
            for s in completed_steps[-3:]
        ) or "None"

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
        """Parse model response. Falls back to PASS on any parse failure."""
        try:
            m = re.search(r'\{[\s\S]+?\}', raw)
            if not m:
                return ReviewVerdict.PASS, None
            data = json.loads(m.group())
            v       = data.get("verdict", "pass").lower()
            reason  = data.get("reason", "") or None
            refined = data.get("refined", "") or None

            if v == "veto":
                return ReviewVerdict.VETO, reason
            if v == "refine" and refined:
                return ReviewVerdict.REFINE, refined
            return ReviewVerdict.PASS, None
        except Exception:
            return ReviewVerdict.PASS, None
