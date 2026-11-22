"""CLM-0 baseline instrument (specs/clm-memory T0.1): measure, never change.

WHAT IT RECORDS
---------------
With ``IRIS_CLM_BASELINE=1`` every model call through ``InferenceRouter.generate``
and every direct-context assembly appends ONE JSON line to
``logs/clm_baseline.jsonl``:

  * ``event="call"``  - the router cap's cut (what ``_cap_messages_to_window``
    dropped, from the same pops its warning counts), the three existing token
    estimators run on the messages that were SENT, the server's
    ``usage.prompt_tokens`` beside them, and the size of each message by role.
  * ``event="direct"`` - the chars/4 trim inside ``_assemble_direct_context``
    and the size of each block kind that path assembles.

``scripts/clm_baseline_report.py`` turns the file into the T0.1 table.

HOW IT STAYS OFF THE ANSWER PATH
--------------------------------
Unset, the call sites pay one ``os.environ`` lookup. Set, the call site binds
VALUES (a shallow copy of the message list, ids, the cap report) and submits
one job to lane("clm_baseline"); the estimators, the JSON encoding and the file
append all run on that lane's single writer, in submission order. A full lane
drops the row and counts it (lane.dropped()); every other failure of the
instrument is counted here. Both counters ride on every row, and ``seq`` is
assigned at submit time, so the report sees a lost row as a gap.

Not a metrics framework: the gauge (T1.4) replaces this module.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.agent.context_gauge import blind_drop_snapshot as _blind_drop_snapshot
from backend.agent.context_view import view_fallback_count as _view_fallback_count

logger = logging.getLogger(__name__)

ENV = "IRIS_CLM_BASELINE"
_LANE = "clm_baseline"
# backend/agent/inference/clm_baseline.py -> repo root is parents[3].
_PATH = Path(__file__).resolve().parents[3] / "logs" / "clm_baseline.jsonl"

_lock = threading.Lock()
_seq = 0
_failures = 0
# Written by the lane thread only (one writer); "" = not probed yet.
_mcm_method = ""


def enabled() -> bool:
    """The one check on the call path."""
    return os.environ.get(ENV) == "1"


def _next_seq() -> int:
    global _seq
    with _lock:
        _seq += 1
        return _seq


def _count_failure(where: str, exc: BaseException) -> None:
    global _failures
    with _lock:
        _failures += 1
        n = _failures
    logger.warning("[clm_baseline] instrument failure where=%s n=%d: %r", where, n, exc)


def _counters() -> Dict[str, int]:
    try:
        from backend.utils.durability_queue import lane

        dropped = lane(_LANE).dropped()
    except Exception:  # noqa: BLE001 - counted below as "unknown"
        dropped = -1
    with _lock:
        return {"failures": _failures, "lane_dropped": dropped}


def _submit(label: str, fn: Any, *args: Any) -> None:
    try:
        from backend.utils.durability_queue import lane

        lane(_LANE).submit(label, fn, *args)  # a full lane counts its own drop
    except Exception as exc:  # noqa: BLE001 - never reaches the caller
        _count_failure(f"submit:{label}", exc)


def _append(row: Dict[str, Any]) -> None:
    """Runs on the lane. One line per row."""
    row["instrument"] = _counters()
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def record_event(conversation_id: str, event: str, **fields: Any) -> None:
    """CLM-8 AC4 / T5.2: one ``event`` row per view decision, for evals/context_report.py.

    ``event`` in {offloaded, restretched, premature_eviction, landmark_header}; ``fields``
    are VALUES only (actor harness|model, trigger, tokens, chars, n, stale) - never
    content. Off unless IRIS_CLM_BASELINE=1; the write runs on the instrument lane.
    """
    if not enabled():
        return
    row = {"event": event, "conversation_id": conversation_id or "", "seq": _next_seq(),
           "ts": time.time(), **{k: v for k, v in fields.items() if isinstance(v, (int, float, str, bool))}}
    _submit("clm_event", _append, row)


def _owner_of(resolver: Any) -> Any:
    """The kernel behind the router's window resolver (a bound method), or None."""
    return getattr(resolver, "__self__", None)


# -- router calls ----------------------------------------------------------


def _router_tokens(messages: List[Dict[str, Any]], tools: Any = None) -> int:
    from backend.agent.inference.router import InferenceRouter

    return InferenceRouter._estimate_prompt_tokens(messages, tools)


def _mcm_tokens(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """U4's third estimator, MCM.count_tokens (tiktoken cl100k, else chars/4),
    with the branch it takes on this machine (probed once, on the lane)."""
    global _mcm_method
    from backend.agent.mcm import MCM

    if not _mcm_method:
        try:
            import tiktoken

            tiktoken.get_encoding("cl100k_base")
            _mcm_method = "tiktoken_cl100k"
        except Exception:  # noqa: BLE001 - the estimator's own fallback
            _mcm_method = "chars4"
    return {"tokens": MCM.count_tokens(messages), "method": _mcm_method}


def _chars4_tokens(owner: Any, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The kernel's own ``_count_tokens`` (chars/4), called on the real kernel."""
    counter = getattr(owner, "_count_tokens", None)
    if callable(counter):
        return {"tokens": int(counter(messages)), "source": "kernel"}
    from types import SimpleNamespace

    from backend.agent.kernel.context import ContextMixin

    return {
        "tokens": int(ContextMixin._count_tokens(SimpleNamespace(_CHARS_PER_TOKEN=4), messages)),
        "source": "ContextMixin",
    }


def _kind_of(message: Dict[str, Any]) -> str:
    """The message's role; the only kind the router can know without a classifier."""
    role = str(message.get("role") or "unknown")
    if role == "assistant" and message.get("tool_calls"):
        return "assistant_tool_calls"
    return role


def _write_call(row: Dict[str, Any], messages: List[Dict[str, Any]], tools: Any,
                owner: Any, cap: Optional[Dict[str, Any]]) -> None:
    try:
        blocks: Dict[str, List[int]] = {}
        for m in messages:
            blocks.setdefault(_kind_of(m), []).append(_router_tokens([m]))
        if tools:
            blocks["tools_schema"] = [int(len(str(tools)) / 3.5) + 1]
        row["blocks"] = blocks
        row["blocks_unit"] = "router_3_5"
        # CLM-10 (T5.3): the prefix (system + tool menu) must stay byte-stable across a
        # node's calls; a node is keyed by its step message. `asides` = set-aside slips in
        # the input, so the report can tell an edit call (count grew) from an append.
        import hashlib as _hl

        _sys = next((str(m.get("content") or "") for m in messages if m.get("role") == "system"), "")
        _step = next((str(m.get("content") or "") for m in messages if m.get("role") == "user"), "")
        row["prefix_hash"] = _hl.sha1((_sys + "\x00" + json.dumps(tools, sort_keys=True, default=str)
                                       ).encode("utf-8", "replace")).hexdigest()[:16]
        row["node_key"] = _hl.sha1((_sys[:2000] + "\x00" + _step).encode("utf-8", "replace")).hexdigest()[:16]
        # the two prefix parts apart, so an unstable prefix names its cause
        row["sys_hash"] = _hl.sha1(_sys.encode("utf-8", "replace")).hexdigest()[:12]
        row["tools_hash"] = _hl.sha1(json.dumps(tools, sort_keys=True, default=str)
                                     .encode("utf-8", "replace")).hexdigest()[:12]
        row["asides"] = sum(str(m.get("content") or "").count("[[SET ASIDE") for m in messages)

        # The messages themselves, for "was the needed fact still in the model's
        # input?" (evals/context_report.py --dumps). Off unless a dump dir is
        # named; on this lane thread, never on the call path.
        _dump = os.environ.get("IRIS_CLM_DUMP_DIR")
        # Bounded: an eval-only capture. One file per call; stops at 4,000 files.
        if _dump and int(row.get("seq") or 0) <= 4000:
            from pathlib import Path as _P
            _P(_dump).mkdir(parents=True, exist_ok=True)
            (_P(_dump) / f"{row.get('conversation_id')}-{row['seq']}.json").write_text(
                json.dumps({"messages": messages}, default=str), encoding="utf-8")

        est = {
            "chars4": _chars4_tokens(owner, messages),
            "router_3_5": {"tokens": _router_tokens(messages, tools)},
            "mcm": _mcm_tokens(messages),
        }
        row["est"] = est
        usage = row.get("usage") or None
        real = int((usage or {}).get("prompt_tokens") or 0)
        row["err"] = (
            {k: round((v["tokens"] - real) / real, 4) for k, v in est.items()}
            if real > 0 else None
        )

        if cap is not None:
            dropped = cap.pop("dropped_messages_list", [])
            by_role: Dict[str, int] = {}
            tok_by_role: Dict[str, int] = {}
            for m in dropped:
                k = _kind_of(m)
                by_role[k] = by_role.get(k, 0) + 1
                tok_by_role[k] = tok_by_role.get(k, 0) + _router_tokens([m])
            cap["dropped_by_kind"] = by_role
            cap["dropped_tokens_by_kind"] = tok_by_role
            cap["dropped_tokens_est"] = sum(tok_by_role.values())
        row["cap"] = cap
        _append(row)
    except Exception as exc:  # noqa: BLE001 - counted, visible on the next row
        _count_failure("write_call", exc)


def record_call(
    *,
    role: str,
    provider: str,
    provider_kind: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: Any,
    usage: Optional[Dict[str, int]],
    ok: bool,
    window: Optional[int],
    max_tokens: int,
    cap: Optional[Dict[str, Any]],
    resolver: Any,
    call_kind: str = "other",
    sends: int = 1,
    seconds: Optional[float] = None,
) -> None:
    """Call path (flag on only): bind values, queue the row. Never raises.

    Round 4 W0: ``call_kind`` (what the call is for), ``sends`` (HTTP requests the call
    made, >= 1: resends after a cut answer and hedge duplicates count) and ``seconds``
    (wall time of the call, failed ones included) ride on the row for wb_ab_analysis."""
    try:
        owner = _owner_of(resolver)
        row = {
            "v": 1,
            "event": "call",
            "seq": _next_seq(),
            "t": time.time(),
            "conversation_id": getattr(owner, "conversation_id", None),
            "session_id": getattr(owner, "session_id", None),
            "role": role,
            "provider": provider,
            "provider_kind": provider_kind,
            "model": model,
            "call_kind": str(call_kind or "other"),
            "sends": max(1, int(sends or 1)),
            "seconds": round(float(seconds), 3) if seconds is not None else None,
            "ok": bool(ok),
            "window": window,
            "max_tokens": max_tokens,
            "n_messages": len(messages or []),
            "usage": dict(usage) if usage else None,
            # T1.5: running totals of router-cap drops (calls, messages, tokens).
            "blind_drop": _blind_drop_snapshot(),
        }
        _submit("call", _write_call, row, list(messages or []), tools, owner,
                dict(cap) if cap is not None else None)
    except Exception as exc:  # noqa: BLE001
        _count_failure("record_call", exc)


# -- direct-context assembly -----------------------------------------------


def _write_direct(row: Dict[str, Any], parts: Dict[str, List[Dict[str, Any]]],
                  cuts: Dict[str, List[Dict[str, Any]]], cpt: int) -> None:
    try:
        def size(m: Dict[str, Any]) -> int:
            # The path's own unit: len(content) // _CHARS_PER_TOKEN, per message.
            return len(m.get("content") or "") // cpt

        row["blocks"] = {k: [size(m) for m in v] for k, v in parts.items()}
        row["blocks_unit"] = f"chars{cpt}"
        for name, msgs in cuts.items():
            row[f"{name}_messages"] = len(msgs)
            row[f"{name}_tokens"] = sum(size(m) for m in msgs)
        _append(row)
    except Exception as exc:  # noqa: BLE001
        _count_failure("write_direct", exc)


def record_direct(
    *,
    conversation_id: Optional[str],
    session_id: Optional[str],
    branch: str,
    budget_for_history: int,
    chars_per_token: int,
    parts: Dict[str, List[Dict[str, Any]]],
    cuts: Dict[str, List[Dict[str, Any]]],
    dcp_before: int,
    dcp_after: int,
) -> None:
    """Direct path (flag on only): bind values, queue the row. Never raises."""
    try:
        row = {
            "v": 1,
            "event": "direct",
            "seq": _next_seq(),
            "t": time.time(),
            "conversation_id": conversation_id,
            "session_id": session_id,
            "branch": branch,
            "budget_for_history": int(budget_for_history),
            "dcp_before": dcp_before,
            "dcp_after": dcp_after,
            # T1.1: direct-path assemblies that fell back to the old list; the
            # live gate asserts 0.
            "view_fallback": _view_fallback_count(),
        }
        _submit(
            "direct", _write_direct, row,
            {k: list(v) for k, v in parts.items()},
            {k: list(v) for k, v in cuts.items()},
            int(chars_per_token or 4),
        )
    except Exception as exc:  # noqa: BLE001
        _count_failure("record_direct", exc)
