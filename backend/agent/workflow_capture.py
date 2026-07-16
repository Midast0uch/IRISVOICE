"""Verified skill capture (Phase 5.1 / research D1).

Replaces the old heuristic "prompt the LLM to write a SKILL.md once a pattern
recurs N times" trigger with a *deterministic, verified* pipeline:

  1. Trigger only when a successful run used >= 3 DISTINCT tools AND the
     sequence is not already a known skill (similarity < 0.85).
  2. Self-test: structurally validate the tool_sequence — every step names a
     tool registered in tool_registry and carries a dict of params.  This is
     the safe stand-in for "replay on a toy input": we prove the sequence is
     internally consistent and executable (no unknown tools) WITHOUT actually
     running anything (real replay would be unsafe + non-deterministic).
  3. Register the verified skill in semantic memory (mirroring
     SkillCrystalliser's storage shape) so the skill UI / AutoResearchRunner
     pick it up for continuous refinement (MIN_IMPROVEMENT = 0.05).

The module is side-effect-free except for two injectable I/O boundaries
(semantic store write, AutoResearchRunner hand-off), so the logic is fully
unit-testable without a live model or database.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

MIN_DISTINCT_TOOLS = 3
SIMILARITY_THRESHOLD = 0.85


def _step_tool(step: Any) -> Optional[str]:
    """Extract the tool name from a tool-call dict (or a bare string)."""
    if isinstance(step, dict):
        return step.get("tool") or step.get("name") or step.get("function", {}).get("name")
    if isinstance(step, str):
        return step
    return None


def distinct_tool_names(tool_sequence: Sequence[Dict[str, Any]]) -> List[str]:
    """Ordered list of distinct tool names used in a sequence."""
    seen: List[str] = []
    for step in tool_sequence:
        name = _step_tool(step)
        if name and name not in seen:
            seen.append(name)
    return seen


def sequence_similarity(a: Sequence[str], b: Sequence[str]) -> float:
    """Jaccard similarity between two tool-name sequences (order-insensitive)."""
    set_a, set_b = set(a), set(b)
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def should_capture(
    tool_sequence: Sequence[Dict[str, Any]],
    existing_skills: Sequence[Dict[str, Any]],
    min_distinct: int = MIN_DISTINCT_TOOLS,
    threshold: float = SIMILARITY_THRESHOLD,
) -> bool:
    """Deterministic trigger for skill capture.

    Returns True iff the run used >= ``min_distinct`` distinct tools AND no
    existing skill is >= ``threshold`` similar to this sequence.
    """
    distinct = distinct_tool_names(tool_sequence)
    if len(distinct) < min_distinct:
        return False
    for skill in existing_skills:
        skill_seq = skill.get("tool_sequence") or []
        skill_tools = [_step_tool(s) for s in skill_seq]
        skill_tools = [t for t in skill_tools if t]
        if sequence_similarity(distinct, skill_tools) >= threshold:
            return False
    return True


def self_test_skill(
    tool_sequence: Sequence[Dict[str, Any]],
    is_registered: Callable[[str], bool],
) -> bool:
    """Structural self-test: every step names a registered tool with dict params.

    Safe stand-in for "replay on a toy input" — proves the sequence is
    executable (no unknown tools) without running anything.
    """
    if not tool_sequence:
        return False
    for step in tool_sequence:
        name = _step_tool(step)
        if not name:
            return False
        if not is_registered(name):
            logger.warning("[workflow_capture] self-test failed: unknown tool '%s'", name)
            return False
        params = step.get("params") or step.get("arguments") or {}
        if not isinstance(params, dict):
            logger.warning("[workflow_capture] self-test failed: bad params for '%s'", name)
            return False
    return True


def build_skill_stub(
    tool_sequence: Sequence[Dict[str, Any]],
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a skill record (name + tool_sequence + description)."""
    distinct = distinct_tool_names(tool_sequence)
    if name is None:
        name = _default_name(distinct)
    description = (
        f"Automated workflow using: {' → '.join(distinct)}. "
        f"Captured by verified skill capture after a successful run."
    )
    return {
        "name": name,
        "description": description,
        "tool_sequence": [dict(s) for s in tool_sequence],
        "verified": True,
    }


def _default_name(tools: Sequence[str]) -> str:
    if not tools:
        return "Automated Skill"
    return f"{tools[0].replace('_', ' ').title()} Workflow"


def register_verified_skill(
    stub: Dict[str, Any],
    memory: Any,
    confidence: float = 0.9,
) -> str:
    """Persist a verified skill to semantic memory.

    Mirrors SkillCrystalliser's storage shape (category="named_skills") so the
    existing skill UI / AutoResearchRunner pick it up.  Returns the skill key.

    DER Phase 3 (D3.3 G4): HARD GATE. A skill is only registered when the step
    actually reached the VERIFIED state (rubric pass). If ``stub["verified"]``
    is falsy, registration is refused — no skill is written. This is what stops
    unverified work from being silently memorized as a "verified" skill.
    """
    if not stub.get("verified", False):
        logger.info(
            "[workflow_capture] refusing skill '%s' — not VERIFIED",
            stub.get("name", "?"),
        )
        return ""
    skill_key = f"skill_{stub['name'].lower().replace(' ', '_')}"
    memory.semantic.update(
        category="named_skills",
        key=skill_key,
        value=json.dumps({
            "name": stub["name"],
            "description": stub["description"],
            "tool_sequence": stub["tool_sequence"],
            "verified": stub.get("verified", True),
            "uses": 1,
            "avg_score": 1.0,
        }),
        confidence=confidence,
        source="verified_capture",
    )
    try:
        memory.semantic.update_user_display(
            key=f"named_skills.{skill_key}",
            display_name=f"Skill: {stub['name']} (verified)",
            source="auto_learned",
        )
    except Exception:
        pass
    logger.info("[workflow_capture] Registered verified skill '%s'", stub["name"])
    return skill_key


def capture_workflow(
    tool_sequence: Sequence[Dict[str, Any]],
    memory: Any,
    existing_skills: Sequence[Dict[str, Any]],
    is_registered: Callable[[str], bool],
    name: Optional[str] = None,
) -> Optional[str]:
    """End-to-end: trigger -> self-test -> register.  Returns skill key or None.

    Returns None (and registers nothing) when the sequence should not be
    captured or fails the structural self-test.
    """
    if not should_capture(tool_sequence, existing_skills):
        return None
    if not self_test_skill(tool_sequence, is_registered):
        logger.info("[workflow_capture] self-test failed — not registering")
        return None
    stub = build_skill_stub(tool_sequence, name=name)
    return register_verified_skill(stub, memory)
