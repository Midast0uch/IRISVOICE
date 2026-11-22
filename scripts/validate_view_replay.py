"""Replay recorded node conversations through the REAL node loop + CLM view, offline
(specs/clm-memory design.md "Standing harness": the TG-2 first step; CLAUDE.md
hidden-failures rule 2 - replay before you switch).

    python scripts/validate_view_replay.py logs/clm_dumps_w2_off [more dump dirs]
           [--windows 8192 32768 131072] [--json out.json]

Input: the per-call message dumps the backend writes with IRIS_CLM_BASELINE=1 and
IRIS_CLM_DUMP_DIR=<dir> (one JSON file per model call: {"messages": [...]}).
A NODE is a run of calls with the same system + step message; its longest
recorded list holds every tool call and result it made. For each node and each
window the script drives ``node_executor.run_node`` with:
  generate  -> the recorded assistant tool calls, in order, then a STATUS line
  execute   -> the recorded tool results, in order
  CLM hooks -> an in-memory record (every result readable), events captured
and once with NO hooks (window 0 = today's flag-off node) as the "before".

It prints, per window: calls, input tokens per call as a share of the router
budget (window - reserve; the router cuts blind above 1.0), calls over the
budget, set-aside units per node, gate refusals by reason, OFFLOADED events.

FAILS (exit 1) on: no node replayed; a value with zero variance across >= 10
nodes; every set-aside node at the same count (a clamp); any call over the
router budget WITH the hooks (the guarantee BT-2 states); an OFFLOADED count
that differs from the set-aside count. Read-only: touches no store.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _nodes(dirs: List[Path]) -> List[List[Dict[str, Any]]]:
    """The longest recorded message list of each node, across the dump dirs."""
    best: Dict[str, List[Dict[str, Any]]] = {}
    for d in dirs:
        for f in sorted(d.glob("*.json")):
            try:
                msgs = json.loads(f.read_text(encoding="utf-8")).get("messages") or []
            except (OSError, ValueError):
                continue
            if len(msgs) < 3 or msgs[0].get("role") != "system" or msgs[1].get("role") != "user":
                continue
            if not any(m.get("role") == "assistant" and m.get("tool_calls") for m in msgs):
                continue   # a planner / synthesis / direct call, not a node
            key = hashlib.sha1((str(msgs[0].get("content")) + "\x00"
                                + str(msgs[1].get("content"))).encode("utf-8", "replace")).hexdigest()
            if len(msgs) > len(best.get(key, [])):
                best[key] = msgs
    return list(best.values())


def _script(msgs: List[Dict[str, Any]]):
    """(model turns [(text, tool_calls)], results in call order, tool names)."""
    turns, results, names = [], [], []
    by_id = {m.get("tool_call_id"): m for m in msgs if m.get("role") == "tool"}
    for m in msgs[2:]:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            calls = m["tool_calls"]
            turns.append((str(m.get("content") or ""), calls))
            for c in calls:
                names.append((c.get("function") or {}).get("name") or "tool")
                hit = by_id.get(c.get("id"))
                results.append(str((hit or {}).get("content") or ""))
    return turns, results, names


def _replay(msgs, window: int) -> Dict[str, Any]:
    import copy

    from backend.agent import node_executor as ne
    from backend.agent.context_gauge import estimate_tokens
    from backend.agent.context_view import offload_refusal_counts

    turns, results, names = _script(msgs)
    tools = [{"type": "function", "function": {"name": n, "description": n,
                                               "parameters": {"type": "object"}}}
             for n in sorted(set(names))]
    queue, script = list(results), list(turns)
    calls: List[float] = []
    events: List[str] = []
    store: Dict[str, str] = {}
    max_tokens = 1024
    reserve = min(max(256, max_tokens), window // 2) + 256 if window else 0
    budget = (window - reserve) if window else 0

    def generate(role, messages, tools=None, **kw):
        if budget:
            calls.append(estimate_tokens(messages, tools) / budget)
        else:
            calls.append(float(estimate_tokens(messages, tools)))
        if script:
            text, tc = script.pop(0)
            return text, "", copy.deepcopy(tc)
        return "Done.\nSTATUS: done", "", []

    def execute(name, params):
        return {"success": True, "content": queue.pop(0) if queue else ""}

    def record_result(name, params, text, call_ord):
        rid = f"{len(store) + 1:032x}"
        store[rid] = text
        return rid

    hooks: Dict[str, Any] = {}
    if window:
        hooks = {"record_result": record_result, "ref_readable": lambda rid: rid in store,
                 "on_clm_event": lambda label, payload: events.append(label), "window": window}
    before = ne.clm_node_stats()
    refused_before = offload_refusal_counts()
    # The recorded step message is passed as the TASK, so the loop clips it to its
    # window share (_step_clip) as it clips a real step; the goal is its STEP line.
    step_text = str(msgs[1].get("content") or "")
    goal = step_text.split("STEP: ", 1)[1].split("\n\n", 1)[0] if "STEP: " in step_text else step_text[:300]
    ne.run_node(goal, ne.NodeContext(
        generate=generate, execute=execute,
        format_result=lambda name, raw: str((raw or {}).get("content") or ""),
        tools=tools, conv_id="replay", max_calls=max(len(turns) + 1, 2),
        max_tokens=max_tokens, task=step_text, **hooks))
    after = ne.clm_node_stats()
    refused_after = offload_refusal_counts()
    return {"calls": calls,
            "set_aside": after["set_aside_units"] - before["set_aside_units"],
            "boundaries": after["shrink_boundaries"] - before["shrink_boundaries"],
            "failures": after["shrink_failures"] - before["shrink_failures"],
            "refused": {k: refused_after.get(k, 0) - refused_before.get(k, 0)
                        for k in refused_after if refused_after.get(k, 0) - refused_before.get(k, 0)},
            "offloaded_events": events.count("OFFLOADED")}


def _q(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(p * len(s)))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--windows", nargs="+", type=int, default=[8192, 32768, 131072])
    ap.add_argument("--json")
    a = ap.parse_args()
    import logging

    logging.disable(logging.WARNING)
    nodes = _nodes([Path(d) for d in a.dirs])
    print(f"nodes replayed: {len(nodes)} (from {', '.join(a.dirs)})")
    problems: List[str] = []
    if not nodes:
        print("FAIL: no node conversation in the dumps")
        return 1
    report: Dict[str, Any] = {"nodes": len(nodes), "windows": {}}
    for window in [0] + list(a.windows):
        rows = [_replay(m, window) for m in nodes]
        calls = [c for r in rows for c in r["calls"]]
        aside = [r["set_aside"] for r in rows]
        refused: Counter = Counter()
        for r in rows:
            refused.update(r["refused"])
        events = sum(r["offloaded_events"] for r in rows)
        tag = "hooks OFF (tokens per call)" if not window else f"window {window} (share of router budget)"
        print(f"\n== {tag}")
        print(f"  model calls {len(calls)}  p50 {_q(calls, .5):.3f}  p95 {_q(calls, .95):.3f}  "
              f"max {max(calls) if calls else 0:.3f}")
        rep = {"calls": len(calls), "p50": _q(calls, .5), "p95": _q(calls, .95),
               "max": max(calls) if calls else 0.0}
        if window:
            over = sum(1 for c in calls if c > 1.0)
            print(f"  calls over the router budget: {over}  (blind drops the router would make)")
            print(f"  set-aside units per node: total {sum(aside)}  nodes with any "
                  f"{sum(1 for x in aside if x)}  max {max(aside)}")
            print(f"  shrink boundaries {sum(r['boundaries'] for r in rows)}  failures "
                  f"{sum(r['failures'] for r in rows)}  OFFLOADED events {events}")
            print(f"  gate refusals: {dict(refused) or 'none'}")
            rep.update(over=over, set_aside=sum(aside), events=events, refused=dict(refused),
                       failures=sum(r["failures"] for r in rows))
            if over:
                problems.append(f"window {window}: {over} calls over the router budget with the hooks on")
            if events != sum(aside):
                problems.append(f"window {window}: OFFLOADED events {events} != set-aside units {sum(aside)}")
            hit = [x for x in aside if x]
            if len(hit) >= 10 and len(set(hit)) == 1:
                problems.append(f"window {window}: every set-aside node at {hit[0]} (a clamp)")
        if len(nodes) >= 10 and len(calls) >= 10 and statistics.pvariance(calls) == 0:
            problems.append(f"window {window}: zero variance in call size")
        report["windows"][str(window)] = rep
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    if problems:
        for p in problems:
            print("FAIL:", p)
        return 1
    print("OK: distributions sane")
    return 0


if __name__ == "__main__":
    sys.exit(main())
