"""
ToolDecisionBox — encapsulated tool resolution + dispatch for DER.

Single interface the DER loop calls for step execution.  Router-agnostic:
all provider selection flows through InferenceRouter role bindings
(reasoning / tool_execution).  Never reads model/swarm snapshots directly.

Spec: specs/der-tool-resolution-blackbox/
  REQ-3 (encapsulated box), REQ-4 (TOOL/REASON/FAIL decisions),
  REQ-5 (structured logging), REQ-6 (failure → DER recovery),
  REQ-7 (per-step failure detection).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Idempotency (REQ-11) ───────────────────────────────────────────────────

_IDEMPOTENCY_TTL = 86400  # seconds (24 hours)


def _make_idempotency_key(turn_id: str, tool_name: str, params: dict) -> str:
    """Deterministic key for retry-safe deduplication."""
    payload = f"{turn_id}:{tool_name}:{json.dumps(params, sort_keys=True, default=str)}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _is_write_tool(tool_name: str) -> bool:
    """Heuristic: tools with write-side-effect prefixes are WRITE."""
    write_prefixes = (
        "create_", "update_", "delete_", "remove_",
        "send_", "write_", "charge_", "cancel_",
    )
    return any(tool_name.startswith(p) for p in write_prefixes)


# ── Propose prompt ──────────────────────────────────────────────────────────

_PROPOSE_PROMPT = """You are the tool-selection policy for one agent step.
GOAL: {goal}

EVIDENCE (memory-conditioned):
{evidence}

AVAILABLE TOOLS (pick the best fit):
{tool_list}

Respond with STRICT JSON only:
{{"kind": "tool"|"reasoning"|"done", "tool": "<tool_name or null>", "params": {{}}, "rationale": "<one line>"}}

Rules:
- If the goal needs an external action, set kind="tool" and pick a tool from AVAILABLE TOOLS.
- If the goal is pure reasoning/text, set kind="reasoning" and tool=null.
- If the goal is fully satisfied, set kind="done".
- params must match the tool's schema. Do not invent tools not in AVAILABLE TOOLS.
"""


# ── Helpers ─────────────────────────────────────────────────────────────────


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Find the first JSON object in *text* and return it."""
    try:
        m = re.search(r"\{[\s\S]+\}", text)
        if not m:
            return None
        return json.loads(m.group())
    except Exception:
        return None


# ── Decision types ──────────────────────────────────────────────────────────


class DecisionKind(Enum):
    """Outcome of a single tool-resolution attempt."""

    TOOL = "tool"  # a tool was chosen (params validated)
    REASON = "reason"  # model decided no tool needed (valid reasoning step)
    FAIL = "fail"  # resolution could not complete (model dead / unparseable / invalid tool)


@dataclass
class Decision:
    """Result of ToolDecisionBox.resolve()."""

    kind: DecisionKind
    tool: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    source: str = ""  # "llm" | "memory" | "fail"
    error: Optional[str] = None  # populated when kind == FAIL


@dataclass
class ToolCallNode:
    """A single tool call in the DER execution tree (REQ-13)."""
    step_id: str = ""
    tool: Optional[str] = None
    args_hash: str = ""
    result_summary: str = ""
    error_type: Optional[str] = None
    source: str = ""  # "llm" | "memory" | "fail"
    split_depth: int = 0
    parent_step_id: Optional[str] = None


@dataclass
class ToolCallTree:
    """Tree of all tool calls across a DER run (REQ-13)."""
    conversation_id: str = ""
    nodes: list[ToolCallNode] = field(default_factory=list)


@dataclass
class DispatchResult:
    """Result of ToolDecisionBox.dispatch().

    ``error_type`` follows REQ-10's structured error envelope:
    - ``transient``      — network blip, 5xx, timeout  → retry with backoff
    - ``rate_limit``     — 429 / explicit rate-limit   → retry with backoff, honour Retry-After
    - ``validation``     — bad params, 400, 422        → re-plan, do NOT retry verbatim
    - ``not_found``      — 404                         → re-plan
    - ``permission``     — 401, 403                    → escalate, do NOT retry
    - ``partial_success`` — some sub-calls failed      → inspect succeeded/failed arrays
    - ``permanent``      — fallback for unknown errors → re-plan
    """

    success: bool
    result: Any = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    duration_ms: int = 0


def _classify_error(error: Optional[str], result: Any = None) -> str:
    """Classify a tool failure into an ``error_type`` (REQ-10).

    Uses heuristic matching on the error message / result structure.
    """
    if not error:
        return "permanent"
    err_lower = error.lower()
    # Transient / rate-limit
    if any(kw in err_lower for kw in ("timeout", "timed out", "connection reset", "5")):
        return "transient"
    if any(kw in err_lower for kw in ("rate limit", "429", "too many requests")):
        return "rate_limit"
    # Re-plan (not worth retrying)
    if any(kw in err_lower for kw in ("not found", "404")):
        return "not_found"
    if any(kw in err_lower for kw in ("permission", "unauthorized", "401", "403", "forbidden")):
        return "permission"
    if any(kw in err_lower for kw in ("validation", "bad request", "400", "422", "invalid")):
        return "validation"
    # Partial success marker
    if isinstance(result, dict) and "succeeded" in result and "failed" in result:
        return "partial_success"
    return "permanent"


# ── ToolDecisionBox ─────────────────────────────────────────────────────────


class ToolDecisionBox:
    """Encapsulated tool decision + dispatch for DER steps.

    Constructor injects all dependencies (never reads global snapshots), so the
    box is fully testable and swarm-refactor-friendly.
    """

    def __init__(
        self,
        router: Any,
        tool_bridge: Any,
        get_available_tools: Callable[[], list[dict]],
        validate_tool_call: Callable[[str, dict], tuple[bool, Optional[str]]],
        infer_fn: Optional[Callable[..., str]] = None,
        memory_lookup_fn: Optional[Callable[[str], Optional[dict]]] = None,
    ):
        """
        Args:
            router:     InferenceRouter instance (or anything with ``generate(role, …)``).
            tool_bridge: AgentToolBridge instance (or anything with
                         ``execute_tool(name, params) -> dict``).
            get_available_tools: Zero-arg callable returning the current tool
                                 registry as ``[{name, description, params}, …]``.
            validate_tool_call:  ``(tool_name, params) -> (is_valid, error_msg)``.
            infer_fn:            Optional callable for REASON dispatch
                                 ``(prompt, role, …) -> str``.
            memory_lookup_fn:    Optional callable ``(goal_description) -> {tool, rationale} |
                                 None`` for memory-based resolution (pheromone / mycelium /
                                 SourceRegistry).
        """
        self._router = router
        self._tool_bridge = tool_bridge
        self._get_available_tools = get_available_tools
        self._validate_tool_call = validate_tool_call
        self._infer = infer_fn
        self._memory_lookup = memory_lookup_fn or (lambda _goal: None)
        self._idem_cache: Dict[str, tuple[Any, float]] = {}  # key -> (result, expiry_ts) REQ-11
        self._tool_fails: Dict[str, int] = {}  # tool_name -> consecutive failures REQ-12
        self._last_call: Dict[str, tuple[str, bool, int]] = {}  # tool -> (args_hash, success, repeat_count) REQ-12
        self._tool_call_nodes: list[ToolCallNode] = []  # REQ-13

    @staticmethod
    def _run_async(coro):
        """
        Run an async tool coroutine to completion from (possibly) sync context.

        Tool implementations are async (execute_tool is a coroutine).  When this
        dispatch method is called from a thread with NO running event loop,
        asyncio.run() is correct.  When called from inside the DER async loop
        (a loop is already running on this thread), asyncio.run() would raise
        "cannot be called from a running event loop" — so we schedule the
        coroutine on a fresh loop in a worker thread via run_coroutine_threadsafe.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = asyncio.run_coroutine_threadsafe(coro, asyncio.new_event_loop())
                    return future.result(timeout=120)
        except RuntimeError:
            pass
        return asyncio.run(coro)

    # ── Public API ──────────────────────────────────────────────────────────

    def resolve(
        self,
        step: dict,
        evidence: Optional[dict] = None,
        session_id: str = "",
        conversation_id: str = "",
    ) -> Decision:
        """Resolve a DER step to a tool (or reason / fail).

        Two-phase *retrieve-then-decide* (REQ-4 AC6):
          1. Narrow candidate toolset via memory (pheromone / mycelium).
          2. Let the model (via ``router.generate("reasoning", …)``) decide.
          3. If the model is dead / unparseable, consult memory again.
          4. Only if memory also yields nothing → ``FAIL``.

        Never silently substitutes "reason" when resolution fails
        (REQ-4 AC5).
        """
        _start = time.perf_counter()
        goal = step.get("description", "") or ""
        _ev = evidence or {}
        _ev_str = json.dumps(_ev, ensure_ascii=False)
        log_extra: dict[str, Any] = {"session_id": session_id, "conversation_id": conversation_id}

        # ── 1. Get available tools ─────────────────────────────────────
        all_tools: list[dict] = self._get_available_tools() or []

        # ── 2. Memory pre-filter (REQ-4 AC6) ───────────────────────────
        memory_hint = self._memory_lookup(goal) if callable(self._memory_lookup) else None
        pre_filtered = self._apply_pre_filter(all_tools, memory_hint, goal)

        # ── 3. Build propose prompt and call router ────────────────────
        tool_list = "\n".join(
            f"- {t.get('name', '?')}: {t.get('description', '')[:200]}"
            for t in pre_filtered
        ) or "(none available)"

        propose_prompt = _PROPOSE_PROMPT.format(
            goal=goal,
            evidence=_ev_str,
            tool_list=tool_list,
        )
        messages = [
            {"role": "system", "content": "You are a precise tool-selection assistant."},
            {"role": "user", "content": propose_prompt},
        ]

        try:
            text, _thinking, tool_calls = self._router.generate(
                "reasoning",
                messages,
                tools=pre_filtered if pre_filtered else None,
                temperature=0.2,
                max_tokens=500,
            )

            # ── 4. Parse response ──────────────────────────────────────
            # Prefer provider-native tool_calls when available
            if tool_calls and isinstance(tool_calls, list) and len(tool_calls) > 0:
                tc = tool_calls[0]
                if isinstance(tc, dict):
                    tc_tool = tc.get("function", {}).get("name") or tc.get("name")
                    tc_args = (
                        tc.get("function", {}).get("arguments", {})
                        or tc.get("input", {})
                    )
                    if isinstance(tc_args, str):
                        try:
                            tc_args = json.loads(tc_args)
                        except Exception:
                            tc_args = {}
                    if tc_tool and tc_tool in {t.get("name") for t in all_tools}:
                        return self._validate_as_tool(tc_tool, tc_args, "llm",
                                                       conversation_id, _start, log_extra)

            # Parse text output as JSON
            data = _extract_json(text) if text else None
            if data:
                kind = str(data.get("kind", "")).lower()
                tool_name = data.get("tool")
                params = data.get("params", {})
                rationale = data.get("rationale", "")

                if kind in ("reasoning", "done") and not tool_name:
                    ms = int((time.perf_counter() - _start) * 1000)
                    logger.info(
                        "[TOOL_DECISION] kind=REASON source=llm tool=null "
                        "rationale=%s resolve_ms=%d conv=%s",
                        rationale[:120], ms, conversation_id,
                    )
                    return Decision(kind=DecisionKind.REASON, source="llm",
                                    rationale=rationale)

                if kind == "tool" and tool_name:
                    if tool_name not in {t.get("name") for t in all_tools}:
                        ms = int((time.perf_counter() - _start) * 1000)
                        logger.warning(
                            "[TOOL_DECISION] kind=FAIL source=llm "
                            "tool=%s — not in registry resolve_ms=%d conv=%s",
                            tool_name, ms, conversation_id,
                        )
                        return Decision(
                            kind=DecisionKind.FAIL, source="llm",
                            error=f"Tool '{tool_name}' not in available tool registry",
                        )
                    return self._validate_as_tool(tool_name, params, "llm",
                                                   conversation_id, _start, log_extra)

            # ── 5. Model failure → consult memory (REQ-4 AC3) ──────────
            memory_result = self._memory_lookup(goal) if callable(self._memory_lookup) else None
            if memory_result and isinstance(memory_result, dict):
                mtool = memory_result.get("tool")
                mparams = memory_result.get("params", {})
                mrationale = memory_result.get("rationale", "")
                if mtool and mtool in {t.get("name") for t in all_tools}:
                    is_valid, verr = self._validate_tool_call(mtool, mparams)
                    if is_valid:
                        ms = int((time.perf_counter() - _start) * 1000)
                        logger.info(
                            "[TOOL_DECISION] kind=TOOL source=memory tool=%s "
                            "resolve_ms=%d conv=%s",
                            mtool, ms, conversation_id,
                        )
                        return Decision(
                            kind=DecisionKind.TOOL, tool=mtool, params=mparams,
                            source="memory", rationale=mrationale,
                        )

            # ── 6. Memory also empty → FAIL (REQ-4 AC4) ────────────────
            err_msg = "Model unavailable and memory yielded no usable tool suggestion."
            ms = int((time.perf_counter() - _start) * 1000)
            logger.warning(
                "[TOOL_DECISION_FAIL] kind=FAIL source=fail "
                "error=%s resolve_ms=%d conv=%s",
                err_msg, ms, conversation_id,
            )
            return Decision(kind=DecisionKind.FAIL, source="fail", error=err_msg)

        except Exception as exc:
            # Exception during LLM call → consult memory before FAIL
            memory_result = self._memory_lookup(goal) if callable(self._memory_lookup) else None
            if memory_result and isinstance(memory_result, dict):
                mtool = memory_result.get("tool")
                mparams = memory_result.get("params", {})
                mrationale = memory_result.get("rationale", "")
                if mtool and mtool in {t.get("name") for t in all_tools}:
                    is_valid, verr = self._validate_tool_call(mtool, mparams)
                    if is_valid:
                        ms = int((time.perf_counter() - _start) * 1000)
                        logger.info(
                            "[TOOL_DECISION] kind=TOOL source=memory tool=%s "
                            "resolve_ms=%d conv=%s (after exception)",
                            mtool, ms, conversation_id,
                        )
                        return Decision(
                            kind=DecisionKind.TOOL, tool=mtool, params=mparams,
                            source="memory", rationale=mrationale,
                        )
            ms = int((time.perf_counter() - _start) * 1000)
            logger.warning(
                "[TOOL_DECISION_FAIL] kind=FAIL source=fail "
                "error='%s' resolve_ms=%d conv=%s",
                str(exc)[:200], ms, conversation_id,
            )
            return Decision(kind=DecisionKind.FAIL, source="fail", error=str(exc)[:500])

    def dispatch(
        self,
        decision: Decision,
        session_id: str = "",
        conversation_id: str = "",
        reasoning_prompt: str = "",
        turn_id: str = "",  # for idempotency (REQ-11)
    ) -> DispatchResult:
        """Execute a resolved decision.

        - ``TOOL``:   calls ``tool_bridge.execute_tool`` (REQ-6 AC3).
        - ``REASON``: calls ``infer_fn`` for direct reasoning.
        - ``FAIL``:   **never dispatched** — callers route to DER recovery
                      (REQ-6 AC2).  Raises ``ValueError`` as a safety net.

        ``turn_id`` enables idempotency-key generation (REQ-11): if provided
        and the tool is a ``write`` tool, the result is cached so a retry
        with the same key returns the cached result (no duplicate side-effect).
        """
        if decision.kind == DecisionKind.FAIL:
            raise ValueError(
                "dispatch() called with FAIL decision — callers must route "
                "FAIL to DER recovery (_der_handle_step_failure), not dispatch."
            )

        start = time.perf_counter()
        log_extra: dict[str, Any] = {
            "session_id": session_id,
            "conversation_id": conversation_id,
        }

        try:
            if decision.kind == DecisionKind.TOOL:
                if not self._tool_bridge:
                    raise RuntimeError("ToolDecisionBox has no tool_bridge injected")

                # ── Duplicate-call detection (REQ-12 AC2) — before execute ──
                _args_hash = hashlib.md5(
                    json.dumps(decision.params, sort_keys=True, default=str).encode()
                ).hexdigest()[:12]
                _prev = self._last_call.get(decision.tool)  # (args_hash, success)
                # Duplicate: same args, last was success, AND we've already
                # allowed one silent repeat (idempotency-safe retry).
                # Third+ identical call → loop signal.
                _repeat = 0
                _prev = self._last_call.get(decision.tool)  # (args_hash, success, repeat_count)
                if decision.tool and _prev and _prev[0] == _args_hash and _prev[1]:
                    _repeat = _prev[2]
                    if _repeat >= 1:  # second+ consecutive repeat → loop
                        logger.warning(
                            "[TOOL_DISPATCH] DUPLICATE CALL tool=%s args=%s repeat=%d conv=%s",
                            decision.tool, _args_hash, _repeat, conversation_id,
                        )
                        dr = DispatchResult(
                            success=False,
                            error=f"Duplicate call to '{decision.tool}' with identical args ({_repeat+1}x) — loop detected",
                            error_type="permanent", duration_ms=0,
                        )
                        dr.duration_ms = int((time.perf_counter() - start) * 1000)
                        return dr

                # ── Update _last_call repeat counter BEFORE idempotency ──
                # (so cache hits still increment the repeat counter)
                if decision.tool:
                    _prev = self._last_call.get(decision.tool)
                    if _prev and _prev[0] == _args_hash and _prev[1]:
                        # Same args, previous was successful → increment repeat
                        self._last_call[decision.tool] = (_args_hash, False, _prev[2] + 1)
                    elif _prev and _prev[0] == _args_hash:
                        # Same args but previous failed → repeat without success
                        self._last_call[decision.tool] = (_args_hash, False, _prev[2])
                    else:
                        # Different args or new tool → start fresh
                        self._last_call[decision.tool] = (_args_hash, False, 0)

                # ── Idempotency check (REQ-11) ──────────────────────────
                _ik = ""
                if turn_id and decision.tool:
                    _ik = _make_idempotency_key(turn_id, decision.tool, decision.params)
                    _now = time.time()
                    if _ik in self._idem_cache and self._idem_cache[_ik][1] < _now:
                        del self._idem_cache[_ik]
                    if _ik in self._idem_cache:
                        _cached_result, _cached_expiry = self._idem_cache[_ik]
                        logger.info(
                            "[TOOL_DISPATCH] idempotency cache HIT key=%s tool=%s conv=%s",
                            _ik, decision.tool, conversation_id,
                        )
                        dr = DispatchResult(
                            success=True,
                            result=_cached_result,
                            duration_ms=0,
                            error_type=None,
                        )
                        dr.duration_ms = int((time.perf_counter() - start) * 1000)
                        # Update _last_call success (cache hit = previous succeeded)
                        if decision.tool and _args_hash:
                            _prev = self._last_call.get(decision.tool)
                            if _prev and _prev[0] == _args_hash:
                                self._last_call[decision.tool] = (_args_hash, True, _prev[2])
                        return dr

                # ── Per-tool failure budget (REQ-12 AC1) — before execute ──
                _budget = 3
                if decision.tool and self._tool_fails.get(decision.tool, 0) >= _budget:
                    logger.warning(
                        "[TOOL_DISPATCH] BUDGET EXCEEDED tool=%s fails=%d conv=%s",
                        decision.tool, _budget, conversation_id,
                    )
                    dr = DispatchResult(
                        success=False,
                        error=f"Tool '{decision.tool}' exceeded consecutive failure budget ({_budget}). Do not call again.",
                        error_type="permanent", duration_ms=0,
                    )
                    dr.duration_ms = int((time.perf_counter() - start) * 1000)
                    return dr

                # execute_tool is a coroutine — it MUST be awaited, not called
                # bare (a bare call returns a coroutine object, which previously
                # surfaced as "Unexpected tool result type: <class 'coroutine'>"
                # and failed every tool dispatch instantly).  Run it
                # loop-aware: asyncio.run() when no loop is active in this
                # thread, otherwise run it in a worker thread via
                # run_coroutine_threadsafe so we don't clash with the DER loop
                # already driving this call.
                result = self._run_async(
                    self._tool_bridge.execute_tool(decision.tool, decision.params)
                )

                if not isinstance(result, dict):
                    result = {"success": False, "error": f"Unexpected tool result type: {type(result)}"}
                success = result.get("success", False)
                error = result.get("error")

                # ── Track consecutive failures (REQ-12 AC1) ────────────────
                if decision.tool:
                    if success:
                        self._tool_fails.pop(decision.tool, None)
                    else:
                        self._tool_fails[decision.tool] = self._tool_fails.get(decision.tool, 0) + 1

                # REQ-10 AC1: prefer an explicit error_type from the tool's
                # structured envelope; fall back to heuristic classification only
                # when the tool didn't supply one.
                _explicit_et = result.get("error_type") if isinstance(result, dict) else None
                dr = DispatchResult(success=success, result=result.get("result"),
                                    error=error, duration_ms=0,
                                    error_type=_explicit_et or _classify_error(error, result))

                # ── Idempotency store (REQ-11) ──────────────────────────
                if _ik and _is_write_tool(decision.tool):
                    self._idem_cache[_ik] = (result, time.time() + _IDEMPOTENCY_TTL)
                    logger.info(
                        "[TOOL_DISPATCH] idempotency cache STORE key=%s tool=%s ttl=%ds conv=%s",
                        _ik, decision.tool, _IDEMPOTENCY_TTL, conversation_id,
                    )

                # Update _last_call success flag from actual result
                if decision.tool and _args_hash:
                    _prev = self._last_call.get(decision.tool)
                    if _prev and _prev[0] == _args_hash:
                        self._last_call[decision.tool] = (_args_hash, success, _prev[2])

            elif decision.kind == DecisionKind.REASON:
                prompt = reasoning_prompt or decision.rationale or ""
                if not prompt:
                    raise ValueError("REASON dispatch requires a reasoning_prompt or decision.rationale")
                text = self._run_reason_step(prompt)
                dr = DispatchResult(success=True, result=text, duration_ms=0, error_type=None)

            else:
                dr = DispatchResult(success=False, error=f"Unknown decision kind: {decision.kind}",
                                    error_type="permanent")

            dr.duration_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "[TOOL_DISPATCH] kind=%s tool=%s success=%s error_type=%s duration_ms=%d conv=%s",
                decision.kind.value,
                decision.tool or "null",
                dr.success,
                dr.error_type or "none",
                dr.duration_ms,
                conversation_id,
            )
            if not dr.success and dr.error:
                logger.warning(
                    "[TOOL_DISPATCH] failure tool=%s error_type=%s error='%s' duration_ms=%d conv=%s",
                    decision.tool or "null",
                    dr.error_type or "?",
                    dr.error[:200],
                    dr.duration_ms,
                    conversation_id,
                )
            return dr

        except Exception as exc:
            ms = int((time.perf_counter() - start) * 1000)
            logger.error(
                "[TOOL_DISPATCH] kind=%s tool=%s CRASHED error='%s' duration_ms=%d conv=%s",
                decision.kind.value,
                decision.tool or "null",
                str(exc)[:200],
                ms,
                conversation_id,
            )
            _err = str(exc)[:500]
            return DispatchResult(success=False, error=_err, duration_ms=ms,
                                  error_type=_classify_error(_err))

    # ── Internal helpers ──────────────────────────────────────────────────

    def reset_failure_counters(self) -> None:
        """Reset per-tool failure counters and dedup state (REQ-12 AC3).

        Called by the DER loop when a ``_split_step`` Sub-Loop is created,
        so the graft is not penalized as a continuation of the parent step.
        """
        self._tool_fails.clear()
        self._last_call.clear()
        self._tool_call_nodes.clear()

    def record_tool_call(
        self,
        step_id: str,
        tool: Optional[str],
        args_hash: str,
        result_summary: str,
        error_type: Optional[str],
        source: str,
        split_depth: int = 0,
        parent_step_id: Optional[str] = None,
    ) -> None:
        """Record a single tool call for the ToolCallTree (REQ-13)."""
        self._tool_call_nodes.append(ToolCallNode(
            step_id=step_id,
            tool=tool,
            args_hash=args_hash,
            result_summary=result_summary[:200],
            error_type=error_type,
            source=source,
            split_depth=split_depth,
            parent_step_id=parent_step_id,
        ))

    def get_tool_call_tree(self, conversation_id: str = "") -> ToolCallTree:
        """Return the accumulated ToolCallTree and reset."""
        tree = ToolCallTree(
            conversation_id=conversation_id,
            nodes=list(self._tool_call_nodes),
        )
        self._tool_call_nodes.clear()
        return tree

    def _validate_as_tool(
        self,
        tool_name: str,
        params: dict,
        source: str,
        conversation_id: str,
        start: float,
        log_extra: dict,
    ) -> Decision:
        """Validate *tool_name* + *params* via RC1 and return TOOL or FAIL."""
        is_valid, err = self._validate_tool_call(tool_name, params)
        ms = int((time.perf_counter() - start) * 1000)
        if is_valid:
            logger.info(
                "[TOOL_DECISION] kind=TOOL source=%s tool=%s "
                "resolve_ms=%d conv=%s",
                source, tool_name, ms, conversation_id,
            )
            return Decision(
                kind=DecisionKind.TOOL, tool=tool_name, params=params,
                source=source,
            )
        logger.warning(
            "[TOOL_DECISION_FAIL] kind=FAIL source=%s tool=%s "
            "error='RC1: %s' resolve_ms=%d conv=%s",
            source, tool_name, err, ms, conversation_id,
        )
        return Decision(
            kind=DecisionKind.FAIL, source=source,
            error=f"RC1 validation failed for '{tool_name}': {err}",
        )

    def _apply_pre_filter(
        self,
        all_tools: list[dict],
        memory_hint: Optional[dict],
        goal: str,
    ) -> list[dict]:
        """Narrow candidate tools via memory hint (REQ-4 AC6).

        Keeps the memory-suggested tool (if any) plus generic utility tools
        so the model still has a choice.  Returns the full list unchanged
        when there is no memory hint.
        """
        if not memory_hint:
            return all_tools  # no pre-filter
        suggested = memory_hint.get("tool")
        if not suggested:
            return all_tools
        # Keep: the suggested tool + any generic utilities
        generic = {"speak", "tts", "ask_user", "respond"}
        keep = []
        for t in all_tools:
            name = t.get("name", "")
            if name == suggested or name in generic:
                keep.append(t)
        return keep if keep else all_tools

    def _run_reason_step(self, prompt: str, role: str = "REASONING") -> str:
        """Direct reasoning: used when the model decided no tool is needed."""
        if self._infer is None:
            raise RuntimeError(
                "ToolDecisionBox cannot dispatch REASON: no infer_fn was injected"
            )
        return self._infer(prompt, role=role)
