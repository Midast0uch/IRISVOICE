"""
Trailing Director — Director B for the trailing crystallizer DER loop
File: IRISVOICE/backend/agent/trailing_director.py

Reads completed step results and finds depth gaps.
Never races with the leading loop — always stays at gap distance.

Source: specs/IRIS_Swarm_PRD_v9.md (Section 8)
Gate 1 Step 1.6
"""

import re
import json
from typing import List

from backend.agent.der_loop import QueueItem


class TrailingDirector:
    """
    Director B for the trailing crystallizer DER loop.
    Reads completed step results and finds depth gaps.
    Never races with the leading loop — always stays at gap distance.

    For each completed step in the leading loop's wake, asks:
    "Is this actually done to the depth it needs to be?"

    Returns gap-filling QueueItems. Gap items are NEVER critical.
    Never raises — returns [] on any failure.
    """

    GAP_ANALYSIS_PROMPT = (
        "OBJECTIVE: {objective}\n\n"
        "COMPLETED STEP:\n"
        "  Step {step_number}: {description}\n"
        "  Expected output: {expected_output}\n"
        "  Actual result: {actual_result}\n\n"
        "GRAPH STATE (coordinate confidence after this step):\n"
        "{graph_state}\n\n"
        "KNOWN FAILURE PATTERNS:\n"
        "{gradient_warnings}\n\n"
        "DEPTH ANALYSIS:\n"
        "Look at the gap between what was planned and what was actually built.\n"
        "What detail layers exist beneath the surface that were not addressed?\n"
        "Consider: edge cases, error handling, integration coherence with adjacent steps,\n"
        "missing validation, incomplete state management, untested paths.\n\n"
        "If nothing is missing: return empty gap_items list.\n"
        "If gaps exist: return specific, actionable gap-filling steps.\n"
        "Maximum 3 gap-filling steps per completed step -- focus on highest impact.\n\n"
        "JSON only:\n"
        '{{"has_gaps": true|false, "confidence": 0.0-1.0, "gap_items": ['
        '{{"description": "specific gap-filling action", "tool": "tool_name or null", '
        '"params": {{}}, "depth_layer": 1}}'
        "]}}"
    )

    def __init__(self, adapter, memory_interface):
        self.adapter = adapter
        self.memory  = memory_interface

    def analyze_gaps(
        self,
        completed_step,
        plan,
        context_package,
        is_mature: bool,
    ) -> List[QueueItem]:
        """
        Analyze a completed step for depth gaps.
        Returns list of gap-filling QueueItems (may be empty).
        Never raises.
        """
        try:
            graph_state        = ""
            gradient_warnings  = ""

            if is_mature and context_package is not None:
                try:
                    graph_state       = context_package.mycelium_path or ""
                except Exception:
                    pass
                try:
                    gradient_warnings = context_package.gradient_warnings or ""
                except Exception:
                    pass

            prompt = self.GAP_ANALYSIS_PROMPT.format(
                objective=plan.original_task,
                step_number=completed_step.step_number,
                description=completed_step.description,
                expected_output=completed_step.expected_output or "not specified",
                actual_result=(
                    str(completed_step.result)[:300]
                    if completed_step.result else "no result"
                ),
                graph_state=graph_state[:300],
                gradient_warnings=gradient_warnings[:200] or "None",
            )

            response = self.adapter.infer(
                prompt,
                role="REASONING",
                max_tokens=800,
                temperature=0.1,
            )

            return self._parse_gap_items(
                response.raw_text,
                completed_step,
                plan.original_task,
            )

        except Exception:
            return []   # trailing loop advances without action

    def _parse_gap_items(
        self, raw: str, step, objective: str
    ) -> List[QueueItem]:
        """
        Parse model response into gap-filling QueueItems.
        Returns [] on any failure or when no gaps found.
        Hard-caps at 3 items.
        """
        try:
            m = re.search(r'\{[\s\S]+\}', raw)
            if not m:
                return []

            data = json.loads(m.group())
            if not data.get("has_gaps", False):
                return []

            items = []
            for i, g in enumerate(data.get("gap_items", [])[:3]):
                items.append(QueueItem(
                    step_id=f"gap-{step.step_id}-{i}",
                    step_number=step.step_number,
                    description=g.get("description", ""),
                    tool=g.get("tool"),
                    params=g.get("params", {}),
                    critical=False,          # gap items are NEVER critical
                    objective_anchor=objective,
                    depth_layer=g.get("depth_layer", 1),
                    gap_analysis=f"Gap in step {step.step_number}",
                ))

            return items

        except Exception:
            return []
