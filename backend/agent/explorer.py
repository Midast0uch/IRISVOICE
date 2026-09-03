"""Phase 1 (D1.2): Single runtime tool-resolution authority (PROPOSE).

``propose`` is the ONE place a tool gets chosen at runtime. It replaces the four
former authorities:
  * planner pre-assign (agent_kernel._plan_task)
  * web-regex override (agent_kernel web-intent regex)
  * queue-exhaustion Explorer
  * recovery graft tool pick

The LLM emits JSON against the live registry tools. Validation uses the existing
``validate_tool_call``. On unparseable/invalid output the resolver falls back to
the pheromone top-1 predicted tool (BehavioralPredictor) — NEVER a stub. A
capability-gated web fallback prefers ``crawler_query`` for research-class goals,
which is safe because the registry already canonicalizes web aliases to
``crawler_query`` (no routing is lost by deleting the regex override).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROPOSE_PROMPT = """You are the tool-selection policy for one agent step.
GOAL: {goal}

EVIDENCE (memory-conditioned):
{evidence}

AVAILABLE TOOLS (name only; pick the best fit):
{tool_list}

Respond with STRICT JSON only:
{{"kind": "tool"|"reasoning"|"done", "tool": "<tool_name or null>", "params": {{}}, "rationale": "<one line>"}}

Rules:
- If the goal needs an external action, set kind="tool" and pick a tool from AVAILABLE TOOLS.
- If the goal is pure reasoning/text, set kind="reasoning" and tool=null.
- If the goal is fully satisfied, set kind="done".
- params must match the tool's schema. Do not invent tools not in AVAILABLE TOOLS.
"""


# Web-intent triggers used by the capability-gated web fallback. Kept in sync
# with AgentKernel._is_web_search_request so propose() can resolve web tools
# without coupling to the kernel instance. The fallback must fire on the GOAL
# text (which carries the user's phrasing) — NOT on task_class, because the
# DER passes the mode name ("full"/"agentic"/"quick") as task_class, never the
# original "research" class. See pin_9e97e21340e7 (root-cause analysis).
_WEB_INTENT_TRIGGERS = (
    "web search",
    "search the web",
    "search on the internet",
    "search online",
    "look up online",
    "look up on the",
    "find on the web",
    "find on the internet",
    "browse the web",
    "do a web search",
    "research ",
    "do research",
    "do some research",
    "find information about",
    "look up information",
)


def _is_web_intent(goal: str) -> bool:
    """Standalone web-intent heuristic (mirrors AgentKernel._is_web_search_request).

    Drives the propose() web fallback so web-research goals resolve to a real
    tool even though task_class arrives as the DER mode name, not "research".
    """
    if not goal:
        return False
    _lower = goal.lower().strip()
    return any(t in _lower for t in _WEB_INTENT_TRIGGERS)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        m = re.search(r"\{[\s\S]+\}", text)
        if not m:
            return None
        return json.loads(m.group())
    except Exception:
        return None


def _pheromone_top1(
    myc: Any,
    session_id: str,
    task_class: str,
    completed_tools: List[str],
) -> Optional[str]:
    """Top-1 predicted next tool via BehavioralPredictor (deterministic backstop)."""
    if myc is None:
        return None
    try:
        from backend.memory.mycelium.interpreter import BehavioralPredictor

        current_node_ids = list(myc._registry.get_active(session_id))
        preds = BehavioralPredictor(myc).predict(
            session_id,
            current_node_ids,
            task_class,
            completed_tools,
            conn=getattr(myc._store, "_conn", None),
        )
        for p in preds or []:
            if p:
                return p
    except Exception as _e:  # pragma: no cover - defensive
        logger.debug("[explorer] pheromone_top1 failed: %s", _e)
    return None


def propose(
    goal: str,
    evidence: str,
    live_tools: List[Dict[str, Any]],
    infer,
    myc: Any = None,
    session_id: str = "unknown",
    task_class: str = "full",
    completed_tools: Optional[List[str]] = None,
    memory_interface: Any = None,
) -> Dict[str, Any]:
    """Choose the next action for a step. Returns a decision dict.

    Returns:
        {"kind": "tool"|"reasoning"|"done",
         "tool": str|None, "params": dict, "rationale": str}

    Guarantees: never returns a stub. On any failure, falls back to the
    pheromone top-1 registry tool (or "reasoning" if none available).
    """
    completed_tools = completed_tools or []
    tool_names = [t.get("name") for t in live_tools if t.get("name")]
    tool_list = "\n".join(f"- {n}" for n in tool_names) or "(none)"

    try:
        prompt = _PROPOSE_PROMPT.format(
            goal=goal, evidence=evidence, tool_list=tool_list
        )
        resp = infer(prompt, role="REASONING", max_tokens=400, temperature=0.2)
        raw = getattr(resp, "raw_text", resp) if resp is not None else ""
        data = _extract_json(raw) if isinstance(raw, str) else None
    except Exception as _e:
        logger.warning("[explorer] propose inference failed: %s", _e)
        data = None

    # ── Parse + validate the LLM proposal ──
    if isinstance(data, dict):
        kind = str(data.get("kind", "tool")).lower()
        tool = data.get("tool")
        params = data.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        rationale = str(data.get("rationale", ""))[:200]

        if kind in ("done", "reasoning") or tool is None:
            return {"kind": kind or "reasoning", "tool": None, "params": {}, "rationale": rationale}

        # Validate against the registry + schema.
        from backend.agent.tool_registry import validate_tool_call

        valid, err = validate_tool_call(tool, params)
        if valid:
            return {"kind": "tool", "tool": tool, "params": params, "rationale": rationale}
        logger.info("[explorer] invalid LLM tool %r: %s — falling back", tool, err)
    else:
        logger.info("[explorer] unparseable proposal — applying fallback")

    # ── Fallback 1: capability-gated web intent ──
    # Trigger on the GOAL text (carries the user's phrasing) OR the original
    # "research" task_class. The DER passes its mode name as task_class, so we
    # must not rely on task_class == "research" alone (see pin_9e97e21340e7).
    if (myc is not None) and (_is_web_intent(goal) or task_class == "research"):
        try:
            from backend.agent.tool_registry import resolve_tool, capability_allowed

            spec = resolve_tool("crawler_query")
            if spec is not None and capability_allowed(spec):
                return {
                    "kind": "tool",
                    "tool": "crawler_query",
                    "params": {"query": goal},
                    "rationale": "web-intent fallback (research class, capability allowed)",
                }
        except Exception as _e:  # pragma: no cover - defensive
            logger.debug("[explorer] web fallback failed: %s", _e)

    # ── Fallback 2: pheromone top-1 (deterministic backstop, never a stub) ──
    top1 = _pheromone_top1(myc, session_id, task_class, completed_tools) if myc else None
    if top1 and top1 in tool_names:
        return {
            "kind": "tool",
            "tool": top1,
            "params": {},
            "rationale": "pheromone top-1 fallback",
        }

    # ── Final: reasoning (no safe tool available) ──
    return {
        "kind": "reasoning",
        "tool": None,
        "params": {},
        "rationale": "no valid tool resolvable — reason instead",
    }
