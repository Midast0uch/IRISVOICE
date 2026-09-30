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
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    # Restored 2026-09-26 (T19 parity): the kernel's copy carried this and
    # explorer's did not — the two lists had drifted. The fold preserves the
    # UNION, so "websearch <query>" (frontend prefix stripped) still matches.
    "websearch ",
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


def _is_web_intent(goal: str, *, engine: Any = None) -> bool:
    """Standalone web-intent heuristic (mirrors AgentKernel._is_web_search_request).

    Drives the propose() web fallback so web-research goals resolve to a real
    tool even though task_class arrives as the DER mode name, not "research".

    REQ-15 AC15.3 (T19): this is now the ONE web-intent consumer. The engine's
    ``web_intent`` judgment wins when it is available; ``_WEB_INTENT_TRIGGERS``
    is retained ONLY as the engine-unavailable fallback (AC15.4) — the two
    duplicate copies that used to live in ``agent_kernel.py`` are gone.
    ``engine=None`` means NO engine (fall through to the keywords); the module
    singleton is never adopted implicitly.
    """
    if not goal:
        return False
    _lower = goal.lower().strip()
    # The keyword answer is computed on BOTH paths (2026-09-27): it is the row's
    # parity reference when the engine answers, and the answer itself when the
    # engine cannot. A substring scan, so it costs nothing worth naming.
    _keyword = any(t in _lower for t in _WEB_INTENT_TRIGGERS)
    _verdict = _engine_web_intent(goal, engine, keyword=_keyword)
    if _verdict is not None:
        return _verdict
    return _keyword


# Filler a web goal carries about HOW to look ("search the web to confirm", "check a
# source online", "look it up") - instructions to the agent, not words of the question.
# Stripped so the quick tier searches the question itself, not the whole goal sentence
# (spec A4 / RC4). Order matters: the longer phrases go first.
_WEB_QUERY_FILLER = re.compile(
    r"\b(?:please\s+)?(?:"
    r"(?:using|use)\s+(?:a|the)\s+web\s*search(?:\s+to)?"
    r"|(?:do\s+a\s+)?web\s*search(?:\s+for)?"
    r"|search\s+(?:the\s+web|the\s+internet|on\s+the\s+internet|online)(?:\s+(?:for|to\s+confirm|and\s+confirm))?"
    r"|check\s+(?:a|the|one)\s+source(?:s)?\s+online"
    r"|check\s+online"
    r"|look\s+(?:it\s+)?up(?:\s+online)?"
    r"|to\s+confirm"
    r"|and\s+confirm"
    r")\b[\s:,;.]*",
    re.IGNORECASE,
)


def _shape_web_query(goal: str) -> str:
    """The question inside a web goal, with the 'how to look' filler removed.

    Deterministic and side-effect free (it runs inside the tool gate, which is
    consulted more than once per step). Returns ``goal`` unchanged when stripping
    would leave fewer than two words - a shaped query must never be emptier than
    the goal it came from.
    """
    text = (goal or "").strip()
    shaped = _WEB_QUERY_FILLER.sub(" ", text)
    shaped = re.sub(r"\s+", " ", shaped).strip(" :;,.-")
    # a trailing sentence fragment with no letters left (e.g. a lone "?") is noise
    if len(re.findall(r"[A-Za-z0-9]+", shaped)) < 2:
        return text
    return shaped


WEB_INTENT_CONSUMER = "web_intent"

# Session 366: the two-sided confidence margin for the JEV cascade (oracle.md
# 17.3). A Noul whose probability sits inside the band is UNSURE and must NOT
# act; the deterministic keyword path decides instead. 0.8 matches
# monitor_shadow.monitor_bool's default and the project's other Noul gates.
_WEB_INTENT_CONFIDENT_TAU = 0.8

# Process-wide row sink for the web_intent consumer (2026-09-27). This consumer
# had its criteria registered and a live call site but NO row path at all: the
# engine scored every web goal and nothing was ever written, so the consumer
# could never accumulate the evidence a Wave 7 flip requires. Same convention as
# surface_shadow.set_row_sink. None = log only, never silently dropped.
_ROW_SINK: Optional[Callable[[dict], None]] = None


def set_row_sink(sink: Optional[Callable[[dict], None]]) -> None:
    """Install (or clear) the web_intent row sink. Kernel wiring / test seam."""
    global _ROW_SINK
    _ROW_SINK = sink


def _emit_row(row: Optional[dict]) -> None:
    """Hand a web_intent shadow row to the sink, else log it. Never raises."""
    if not row:
        return
    sink = _ROW_SINK
    if callable(sink):
        try:
            sink(row)
            return
        except Exception as e:  # noqa: BLE001 — an observer never blocks
            logger.debug("[web_intent] row sink failed: %r", e)
    logger.info(
        "[web_intent] shadow row chosen=%s brain=%s conf=%s",
        row.get("chosen"), row.get("brain_choice"), row.get("confidence"),
    )


def register_web_intent_consumer() -> bool:
    """Register the web_intent consumer's criteria (REQ-15 AC15.3). Idempotent."""
    try:
        from backend.agent.decision_backend_onnx import (
            ConsumerSpec,
            get_consumer_spec,
            register_consumer_spec,
        )
        if get_consumer_spec(WEB_INTENT_CONSUMER) is not None:
            return False
        register_consumer_spec(ConsumerSpec(
            consumer_id=WEB_INTENT_CONSUMER,
            task_name=WEB_INTENT_CONSUMER,
            instruction=(
                "Does this request require fetching information from the web?"
            ),
            labels=("yes", "no"),
        ))
        return True
    except Exception as e:  # noqa: BLE001 — criteria are best-effort
        logger.debug("[web_intent] consumer spec unavailable: %s", e)
        return False


# Sentinel: adopt the module-level engine singleton. `engine=None` means NO
# ENGINE (fail-safe) and never "resolve the singleton" — a shadow scorer must
# not silently load the model. A CALLER that wants the engine passes this
# explicitly. Same convention as surface_shadow.AUTO_ENGINE (2026-09-27): the
# kernel's web-intent check passed no engine at all, so `_engine_web_intent`
# returned None on every call, the consumer wrote no row, and it could never
# reach the Wave 7 bar however much traffic ran.
AUTO_ENGINE = object()


def _default_engine():
    """The process-wide decision engine, or None. Never raises."""
    try:
        from backend.agent.decision_engine import get_decision_engine

        return get_decision_engine()
    except Exception:  # noqa: BLE001 — a missing engine is simply no verdict
        return None


def _engine_web_intent(
    goal: str, engine: Any = None, keyword: Optional[bool] = None
) -> Optional[bool]:
    """The engine's web-intent verdict, or None when it cannot answer.

    ``keyword`` is the keyword heuristic's OWN answer, supplied by the caller so
    the row can carry it as the PARITY REFERENCE (2026-09-27). The engine's
    verdict steers; the row records what the keyword path would have decided
    alongside it. Without that reference the row has no label, so this consumer
    could never be scored however many times it ran.
    """
    if engine is AUTO_ENGINE:
        engine = _default_engine()
    if engine is None:
        return None
    try:
        register_web_intent_consumer()
        noul = engine.noul(
            WEB_INTENT_CONSUMER, goal, {"goal": goal},
            true_label="yes", false_label="no",
        )
        if noul is None:
            return None
        verdict = bool(noul.true(0.5))
        if keyword is not None:
            _emit_row({
                "consumer_id": WEB_INTENT_CONSUMER,
                "engine": getattr(engine, "model_id", None) or "decision-engine",
                # Labels, not bools: the report compares like with like, and
                # collapsing a name to a bool would manufacture agreement.
                "chosen": "yes" if verdict else "no",
                "brain_choice": "yes" if bool(keyword) else "no",
                "confidence": round(float(noul.probability), 4),
                "engine_latency_ms": getattr(noul, "engine_latency_ms", None),
                "shadow": True,
            })
        # SESSION 366: THE JEV CASCADE (oracle.md 17.3). `true(0.5)` turns an
        # UNSURE belief into a verdict, and this consumer is unsure on most goals.
        # MEASURED 2026-09-29: 303 rows, 289 "yes" (95%), 216/303 with
        # 0.2 < p < 0.8 (many at p == 0.5014, a literal coin flip). `_mem_lookup`
        # uses this verdict to HARD-return crawler_query, so a coin flip was
        # dispatching a web crawl for local file reads - live: "box resolved
        # tool='crawler_query' for step 2 (source=memory)" on the goal "Read the
        # contents of backend/agent/der_constants.py to find the value of
        # DER_BUDGET_MIN_FLOOR". An UNSURE Noul must not act: return None so the
        # caller falls back to the deterministic keyword. This does NOT block the
        # web (the tools stay on the menu); it only stops a WEAK verdict from
        # PRE-COMMITTING the web through the memory hint. The row above still
        # records the RAW verdict, so the report keeps showing this consumer as
        # the non-fit it is (oracle.md 9's tier0_classify precedent).
        if not noul.confident(_WEB_INTENT_CONFIDENT_TAU):
            return None
        return verdict
    except Exception as e:  # noqa: BLE001 — fall back to the keywords
        logger.debug("[web_intent] engine scoring failed: %r", e)
        return None


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


# ── REQ-16 AC16.1 (T20): engine-first tool choice ───────────────────────────

TOOL_CHOICE_CONSUMER = "tool_choice"
_PROPOSE_DELEGATE = "DELEGATE"
_PROPOSE_NONE = "NONE"
# The deployed tool_choice operating point (REQ-22 AC22.1: the ONNX backend's
# measured 0.40). Callers may override; the engine's own config is consulted
# only for the menu width.
_PROPOSE_DEFAULT_THRESHOLD = 0.40


def _tool_schema(live_tools: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    for t in live_tools or ():
        if t.get("name") == name:
            return t.get("parameters") or {}
    return {}


def _engine_tool_choice(
    goal: str,
    live_tools: List[Dict[str, Any]],
    *,
    engine: Any,
    threshold: float,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Score the engine's Choice over ``live_tools`` BEFORE the Brain call.

    REQ-16 AC16.1: returns ``(decision, row)``. ``decision`` is non-None only
    when the engine picked a REAL tool at/above ``threshold`` AND its args
    validated — the one case where the Brain single-shot is skipped (AC16.3
    measures that share). DELEGATE, NONE, below-threshold, an unavailable
    engine, or un-fillable args all mean "decline", and the caller then runs the
    Brain exactly as before.

    ``row`` is the CT-DEI-6-shaped ledger row for the engine's verdict:
    ``shadow=False`` when the engine settled the step, ``shadow=True`` when the
    Brain's pick is what actually runs. Never raises.
    """
    if engine is None:
        return None, None
    try:
        names = [t.get("name") for t in (live_tools or []) if t.get("name")]
        if not names:
            return None, None
        # The menu is composed by the box's own helper so propose() cannot drift
        # from the production composition (AC21.8: control labels reserved
        # inside the cap, no duplicate labels).
        from backend.agent.tool_decision import ToolDecisionBox

        _cap = getattr(getattr(engine, "_cfg", None), "candidate_cap", 6)
        menu = ToolDecisionBox._compose_engine_menu(
            names, _PROPOSE_DELEGATE, _PROPOSE_NONE, _cap)
        frame = {
            "goal": (goal or "")[:200],
            "n_candidates": len(menu),
            "source": "propose",
        }
        ds = engine.decide(TOOL_CHOICE_CONSUMER, menu, frame)
        if ds is None:
            return None, None
        row: Dict[str, Any] = {
            "consumer_id": TOOL_CHOICE_CONSUMER,
            "engine": getattr(engine, "model_id", None) or "decision-engine",
            "chosen": ds.chosen,
            "confidence": round(float(ds.confidence), 4),
            "candidates": [
                {"name": c.name, "prob": round(c.prob, 4)}
                for c in (ds.distribution or ())
            ],
            "threshold": float(threshold),
            "engine_latency_ms": ds.engine_latency_ms,
            "source": "propose",
            "shadow": True,
            "brain_choice": None,
        }
        if (ds.chosen in (_PROPOSE_DELEGATE, _PROPOSE_NONE)
                or ds.confidence < threshold):
            return None, row          # decline → the Brain single-shot runs
        # A confident real tool still needs valid args, or the step cannot be
        # dispatched and the Brain must fill them (AC2.4's ladder).
        schema = _tool_schema(live_tools, ds.chosen)
        args = None
        for _resolve in (
            lambda: engine.fast_path_args(ds.chosen, schema, frame),
            lambda: engine.generate_args(
                TOOL_CHOICE_CONSUMER, ds.chosen, schema, frame),
        ):
            try:
                _ar = _resolve()
            except Exception:  # noqa: BLE001 — the ladder degrades, never raises
                _ar = None
            if _ar is not None and getattr(_ar, "args", None):
                args = _ar.args
                break
        if not args:
            return None, row          # args unfillable → the Brain fills them
        from backend.agent.tool_registry import validate_tool_call

        valid, _err = validate_tool_call(ds.chosen, args)
        if not valid:
            return None, row
        row["shadow"] = False
        row["brain_choice"] = ds.chosen
        return (
            {
                "kind": "tool",
                "tool": ds.chosen,
                "params": args,
                "rationale": f"engine choice {ds.chosen}@{ds.confidence:.3f}",
            },
            row,
        )
    except Exception as e:  # noqa: BLE001 — the engine is an optimisation
        logger.debug("[explorer] engine tool-choice failed: %r", e)
        return None, None


def _emit_propose_row(row: Optional[Dict[str, Any]], row_sink: Any) -> None:
    """Hand a propose() engine row to the caller's ledger sink, if any.

    The sink is how this path reaches the ledger: propose() has no bridge of its
    own, so the caller (the kernel) supplies the writer. Without a sink the row
    is logged only — never silently dropped.
    """
    if row is None:
        return
    if callable(row_sink):
        try:
            row_sink(row)
        except Exception as e:  # noqa: BLE001 — a row is an observer
            logger.debug("[explorer] propose row sink failed: %r", e)
        return
    logger.info(
        "[explorer] tool_choice row source=propose chosen=%s conf=%s shadow=%s",
        row.get("chosen"), row.get("confidence"), row.get("shadow"),
    )


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
    engine: Any = None,
    decision_threshold: float = _PROPOSE_DEFAULT_THRESHOLD,
    row_sink: Optional[Callable[[dict], None]] = None,
) -> Dict[str, Any]:
    """Choose the next action for a step. Returns a decision dict.

    REQ-16 AC16.1 (T20): when an ``engine`` is supplied it is scored FIRST over
    ``live_tools``; a confident real-tool pick with valid args settles the step
    with NO Brain spend. DELEGATE, NONE, below-threshold, un-fillable args, or
    no engine at all fall through to the Brain single-shot exactly as before —
    ``engine=None`` is byte-identical to the pre-T20 behaviour.

    Returns:
        {"kind": "tool"|"reasoning"|"done",
         "tool": str|None, "params": dict, "rationale": str}

    Guarantees: never returns a stub. On any failure, falls back to the
    pheromone top-1 registry tool (or "reasoning" if none available).
    """
    _decision, _row = _engine_tool_choice(
        goal, live_tools, engine=engine, threshold=decision_threshold,
    )
    if _decision is not None:
        _emit_propose_row(_row, row_sink)
        return _decision

    result = _propose_brain(
        goal, evidence, live_tools, infer, myc=myc, session_id=session_id,
        task_class=task_class, completed_tools=completed_tools,
        memory_interface=memory_interface,
    )
    if _row is not None:
        # The engine declined, so the Brain's pick is what runs — record the
        # shadow PAIR, so this path is never a blind spot (CT-DEI-7).
        _row = dict(_row)
        _row["brain_choice"] = result.get("tool") or result.get("kind")
        _emit_propose_row(_row, row_sink)
    return result


def _propose_brain(
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
    """The Brain single-shot + fallback ladder (the pre-T20 body, unchanged).

    Split out so ``propose()`` can record the engine's decline row without
    touching any of the ladder's several return points.
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
    if (myc is not None) and (_is_web_intent(goal, engine=AUTO_ENGINE) or task_class == "research"):
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


# ── REQ-12 (T16): off-thread, budgeted SourceRegistry lookup ────────────────
#
# The DER resolves a step's memory hint synchronously, and that hint used to
# call `asyncio.run(sr.resolve(goal, quick=True))` ON THE DER THREAD — creating
# and tearing down a fresh event loop, inside the step that is already holding
# the engine's start-up budget. Measured cost: 50-200ms per step, paid before
# the engine can even begin. Three rules replace it:
#
#   AC12.1  never `asyncio.run` on the DER thread — submit to the gateway's
#           MAIN loop with `run_coroutine_threadsafe` (the pattern every other
#           cross-thread WS send in this repo uses).
#   AC12.2  a TTL cache hit answers immediately; a miss waits at most
#           `miss_budget_s` (default 100ms) and then gives up.
#   AC12.3  over budget, the caller proceeds with an empty hint; the in-flight
#           lookup keeps running and its result is cached for the NEXT step —
#           a late attach, never a stalled decision.

_SR_HINT_TTL_S = 60.0
_SR_HINT_MAX = 128
_sr_hint_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_sr_hint_pending: Dict[str, Any] = {}


def _sr_hint_put(goal: str, payload: dict) -> None:
    """Bounded insert (LRU eviction past _SR_HINT_MAX)."""
    import time as _t

    try:
        _sr_hint_cache[goal] = (_t.monotonic(), payload)
        _sr_hint_cache.move_to_end(goal)
        while len(_sr_hint_cache) > _SR_HINT_MAX:
            _sr_hint_cache.popitem(last=False)
    except Exception:  # noqa: BLE001 — a cache write must never raise
        pass


def clear_source_hint_cache() -> None:
    """Drop the cache + pending futures (tests / config changes)."""
    _sr_hint_cache.clear()
    _sr_hint_pending.clear()


def source_hint(
    goal: str,
    *,
    loop: Any = None,
    miss_budget_s: float = 0.10,
    allow_sync: bool = False,
) -> Dict[str, Any]:
    """A bounded SourceRegistry hint for *goal* (REQ-12 AC12.1-AC12.3).

    ``loop`` is the gateway's main event loop. ``allow_sync=True`` is the
    EXPLICIT unit-test/shutdown escape hatch (AC12 edge): with no loop it runs
    the coroutine directly. Production never sets it — the DER thread must
    never own an event loop. Never raises; returns ``{}`` on any failure.
    """
    import asyncio as _asyncio
    import time as _t
    from concurrent.futures import TimeoutError as _FutTimeout

    if not goal:
        return {}

    _hit = _sr_hint_cache.get(goal)
    if _hit is not None:
        _ts, _payload = _hit
        if _t.monotonic() - _ts <= _SR_HINT_TTL_S:
            _sr_hint_cache.move_to_end(goal)
            return _payload
        _sr_hint_cache.pop(goal, None)

    _fut = _sr_hint_pending.get(goal)
    if _fut is not None:
        if not _fut.done():
            # Still in flight from an earlier step: do NOT block again.
            return {}
        _sr_hint_pending.pop(goal, None)
        try:
            _payload = _fut.result() or {}
        except Exception:  # noqa: BLE001
            _payload = {}
        _sr_hint_put(goal, _payload)
        return _payload

    # AC12.1: decide the THREADING first. Building the registry/coroutine and
    # then discovering there is no loop would pay the construction cost outside
    # the budget and leak an un-awaited coroutine.
    _has_loop = bool(
        loop is not None and getattr(loop, "is_running", lambda: False)()
    )
    if not _has_loop and not allow_sync:
        return {}  # no main loop → never start one on this thread

    try:
        from backend.crawler.source_registry import get_source_registry

        _coro = get_source_registry().resolve(goal, quick=True)
    except Exception as _e:  # noqa: BLE001 — no registry → empty hint
        logger.debug("[mem-hint] source registry unavailable: %s", _e)
        return {}

    if not _has_loop:
        # The explicit allow_sync escape hatch (unit tests / shutdown).
        try:
            _payload = _asyncio.run(_coro) or {}
        except Exception:  # noqa: BLE001
            return {}
        _sr_hint_put(goal, _payload)
        return _payload

    try:
        _fut = _asyncio.run_coroutine_threadsafe(_coro, loop)
    except Exception as _e:  # noqa: BLE001
        logger.debug("[mem-hint] submit failed: %s", _e)
        return {}
    _sr_hint_pending[goal] = _fut
    try:
        _payload = _fut.result(timeout=miss_budget_s) or {}
    except _FutTimeout:
        # AC12.3: late attach — leave the future pending; the next step for
        # this goal picks the result up from the cache.
        return {}
    except Exception:  # noqa: BLE001
        _payload = {}
    _sr_hint_pending.pop(goal, None)
    _sr_hint_put(goal, _payload)
    return _payload
