#!/usr/bin/env python
"""CLM-0 baseline report (specs/clm-memory T0.1).

Reads the rows the backend writes with IRIS_CLM_BASELINE=1
(backend/agent/inference/clm_baseline.py -> logs/clm_baseline.jsonl), prints the
T0.1 table and writes evals/results/clm-baseline-<date>.json:

  1. blind cuts per task / conversation (router cap + direct-path trims)
  2. estimator error vs server usage.prompt_tokens per (provider, model)
  3. block-size distribution per kind (unit named per row)
  4. instrument integrity: seq gaps, counted failures, lane drops

Usage:
  python scripts/clm_baseline_report.py [--in logs/clm_baseline.jsonl]
      [--since 2026-11-12T10:00] [--evals evals/results/<cohort>.json] [--out PATH]

--evals maps conversation_id -> task id and group from an eval results file.
Stdlib only; read-only on its input.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ESTIMATORS = ("chars4", "router_3_5", "mcm")


def _q(sorted_vals: List[float], p: float) -> Optional[float]:
    """Nearest-rank percentile on a sorted list."""
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, int(round(p * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def _since(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return _dt.datetime.fromisoformat(value).timestamp()


def load(path: str, since: float) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    bad = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if float(row.get("t") or 0) >= since:
                rows.append(row)
    return {"rows": rows, "unparsable_lines": bad}


def task_map(evals_path: Optional[str]) -> Dict[str, Dict[str, Any]]:
    if not evals_path:
        return {}
    with open(evals_path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = {}
    for r in data.get("results", []):
        if r.get("conversation_id"):
            out[str(r["conversation_id"])] = {"task": r.get("id"), "group": r.get("group"),
                                              "passed": r.get("passed")}
    return out


def cuts(rows: List[Dict[str, Any]], tasks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    per: Dict[str, Dict[str, Any]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        conv = str(r.get("conversation_id"))
        d = per[conv]
        if r.get("event") == "call":
            d["calls"] += 1
            cap = r.get("cap") or {}
            n = int(cap.get("dropped_messages") or 0)
            if n:
                d["cap_calls_with_drop"] += 1
                d["cap_dropped_messages"] += n
                d["cap_dropped_tokens_est"] += int(cap.get("dropped_tokens_est") or 0)
                for k, v in (cap.get("dropped_by_kind") or {}).items():
                    d[f"cap_dropped_{k}"] += int(v)
        elif r.get("event") == "direct":
            d["direct_assemblies"] += 1
            for name in ("budget_trim", "recency_cut", "align_pop", "memory_suppressed"):
                d[f"direct_{name}_messages"] += int(r.get(f"{name}_messages") or 0)
                d[f"direct_{name}_tokens"] += int(r.get(f"{name}_tokens") or 0)
            before, after = r.get("dcp_before"), r.get("dcp_after")
            if isinstance(before, int) and isinstance(after, int) and after >= 0:
                d["direct_dcp_removed_messages"] += max(0, before - after)
    out = {}
    for conv, d in per.items():
        meta = tasks.get(conv, {})
        out[conv] = {"task": meta.get("task"), "group": meta.get("group"), **dict(d)}
    return out


def estimator_error(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"n_calls": 0, "n_usage": 0, "err": defaultdict(list), "mcm_method": set()})
    for r in rows:
        if r.get("event") != "call":
            continue
        g = by[f"{r.get('provider')}|{r.get('model')}"]
        g["n_calls"] += 1
        g["mcm_method"].add(((r.get("est") or {}).get("mcm") or {}).get("method"))
        err = r.get("err")
        if not err:
            continue
        g["n_usage"] += 1
        for k in ESTIMATORS:
            if err.get(k) is not None:
                g["err"][k].append(float(err[k]))
    out = {}
    for key, g in sorted(by.items()):
        entry: Dict[str, Any] = {"n_calls": g["n_calls"], "n_with_usage": g["n_usage"],
                                 "mcm_method": sorted(m for m in g["mcm_method"] if m)}
        if g["n_usage"] == 0:
            entry["status"] = "no ground truth"
        else:
            for k in ESTIMATORS:
                vals = sorted(g["err"][k])
                absv = sorted(abs(v) for v in vals)
                entry[k] = {"n": len(vals), "median": _q(vals, 0.5), "p90": _q(vals, 0.9),
                            "max": vals[-1] if vals else None, "min": vals[0] if vals else None,
                            "abs_median": _q(absv, 0.5), "abs_p90": _q(absv, 0.9),
                            "abs_max": absv[-1] if absv else None}
        out[key] = entry
    return out


def block_sizes(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by: Dict[str, List[int]] = defaultdict(list)
    for r in rows:
        unit = r.get("blocks_unit") or "?"
        for kind, sizes in (r.get("blocks") or {}).items():
            by[f"{r.get('event')}:{kind}|{unit}"].extend(int(s) for s in sizes)
    out = {}
    for key, vals in sorted(by.items()):
        vals.sort()
        out[key] = {"n": len(vals), "min": vals[0] if vals else None, "median": _q(vals, 0.5),
                    "p95": _q(vals, 0.95), "max": vals[-1] if vals else None}
    return out


def integrity(rows: List[Dict[str, Any]], unparsable: int) -> Dict[str, Any]:
    seqs = sorted(int(r["seq"]) for r in rows if isinstance(r.get("seq"), int))
    gaps = 0
    restarts = 0
    for a, b in zip(seqs, seqs[1:]):
        if b > a + 1:
            gaps += b - a - 1
    # seq restarts at 1 with each backend process; a restart is not a loss.
    restarts = sum(1 for r in rows if r.get("seq") == 1)
    inst = [r.get("instrument") or {} for r in rows]
    return {
        "rows": len(rows),
        "unparsable_lines": unparsable,
        "process_starts": restarts,
        "seq_missing": gaps if restarts <= 1 else "n/a (more than one process: gaps not comparable)",
        "instrument_failures_max": max((int(i.get("failures") or 0) for i in inst), default=0),
        "lane_dropped_max": max((int(i.get("lane_dropped") or 0) for i in inst), default=0),
        "failed_calls": sum(1 for r in rows if r.get("event") == "call" and not r.get("ok")),
    }


def edit_cost(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """CLM-10 AC1/AC3 (T5.3): prefix stability per node, and tokens re-processed after an
    edit vs after an append, per (provider, model) that reports cached prompt tokens.

    A node = the calls sharing a ``node_key`` (its system + step message). Its prefix
    (system + tool menu) is UNSTABLE when ``prefix_hash`` changes between its calls - a
    finding (CLM-10 edge case: a volatile value belongs in the tail). A call is an EDIT
    when its ``asides`` count grew since the node's previous call, else an APPEND; its
    re-processed tokens = prompt_tokens - cached_tokens (only where cached_tokens exists).
    """
    nodes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("event") == "call" and r.get("node_key"):
            nodes[r["node_key"]].append(r)
    multi = {k: sorted(v, key=lambda r: r.get("seq") or 0) for k, v in nodes.items() if len(v) > 1}
    unstable = {k: v for k, v in multi.items() if len({r.get("prefix_hash") for r in v}) > 1}
    per_pair: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: {"edit": [], "append": []})
    reporting = Counter()
    for calls in multi.values():
        for prev, cur in zip(calls, calls[1:]):
            usage = cur.get("usage") or {}
            pair = f"{cur.get('provider')}/{cur.get('model')}"
            if "cached_tokens" not in usage:
                reporting[pair + " (no cached field)"] += 1
                continue
            reporting[pair] += 1
            kind = "edit" if int(cur.get("asides") or 0) > int(prev.get("asides") or 0) else "append"
            per_pair[pair][kind].append(int(usage.get("prompt_tokens") or 0) - int(usage["cached_tokens"]))
    reproc = {pair: {k: {"n": len(v), "median": _q(sorted(v), 0.5), "p95": _q(sorted(v), 0.95)}
                     for k, v in d.items()} for pair, d in per_pair.items()}
    by_part = Counter()
    for v in unstable.values():
        if len({r.get("sys_hash") for r in v}) > 1:
            by_part["system"] += 1
        if len({r.get("tools_hash") for r in v}) > 1:
            by_part["tools"] += 1
    return {"nodes_with_2plus_calls": len(multi), "prefix_unstable_nodes": len(unstable),
            "prefix_unstable_by_part": dict(by_part),
            "prefix_unstable_examples": [
                {"node": k, "calls": len(v), "distinct_prefixes": len({r.get('prefix_hash') for r in v})}
                for k, v in list(unstable.items())[:5]],
            "calls_by_reporting": dict(reporting), "reprocessed_tokens": reproc}


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:+.3f}"
    return str(v)


def print_table(rep: Dict[str, Any]) -> None:
    print("== CLM-0 baseline (T0.1) ==")
    print("integrity:", json.dumps(rep["integrity"]))
    print("\n-- 1. blind cuts per conversation --")
    print(f"{'conversation':38} {'task':18} calls capDrop capMsgs capTok "
          f"dirTrim dirTok recCut align memSup dcp")
    for conv, d in rep["cuts"].items():
        print(f"{conv[:38]:38} {str(d.get('task') or '-')[:18]:18} "
              f"{d.get('calls', 0):5} {d.get('cap_calls_with_drop', 0):7} "
              f"{d.get('cap_dropped_messages', 0):7} {d.get('cap_dropped_tokens_est', 0):6} "
              f"{d.get('direct_budget_trim_messages', 0):7} {d.get('direct_budget_trim_tokens', 0):6} "
              f"{d.get('direct_recency_cut_messages', 0):6} {d.get('direct_align_pop_messages', 0):5} "
              f"{d.get('direct_memory_suppressed_messages', 0):6} "
              f"{d.get('direct_dcp_removed_messages', 0):3}")
    print("\n-- 2. estimator relative error (est - real) / real, per (provider, model) --")
    for key, e in rep["estimators"].items():
        if e.get("status"):
            print(f"{key}: calls={e['n_calls']} {e['status']}")
            continue
        print(f"{key}: calls={e['n_calls']} with_usage={e['n_with_usage']} mcm={e['mcm_method']}")
        for k in ESTIMATORS:
            s = e[k]
            print(f"   {k:10} n={s['n']:4} median={_fmt(s['median'])} p90={_fmt(s['p90'])} "
                  f"max={_fmt(s['max'])} |p90|={_fmt(s['abs_p90'])} |max|={_fmt(s['abs_max'])}")
    print("\n-- 3. block sizes per kind (tokens, unit after |) --")
    for key, s in rep["blocks"].items():
        print(f"   {key:42} n={s['n']:5} min={s['min']} median={s['median']} "
              f"p95={s['p95']} max={s['max']}")
    e = rep.get("edit_cost") or {}
    print("\n-- 4. edit cost (CLM-10, T5.3) --")
    print(f"   nodes with 2+ calls {e.get('nodes_with_2plus_calls')}  prefix UNSTABLE {e.get('prefix_unstable_nodes')}"
          f"  {e.get('prefix_unstable_examples') or ''}")
    print(f"   calls by cached-token reporting: {e.get('calls_by_reporting')}")
    for pair, d in (e.get("reprocessed_tokens") or {}).items():
        print(f"   {pair}: re-processed after edit {d.get('edit')}  after append {d.get('append')}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="inp", default=os.path.join(ROOT, "logs", "clm_baseline.jsonl"))
    ap.add_argument("--since", default=None, help="epoch seconds or ISO time; older rows skipped")
    ap.add_argument("--evals", default=None, help="eval results JSON (conversation -> task)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    if not os.path.exists(args.inp):
        print(f"no input at {args.inp} (was the backend run with IRIS_CLM_BASELINE=1?)")
        return 1
    loaded = load(args.inp, _since(args.since))
    rows = loaded["rows"]
    rep = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "input": os.path.abspath(args.inp),
        "since": args.since,
        "evals": args.evals,
        "integrity": integrity(rows, loaded["unparsable_lines"]),
        "cuts": cuts(rows, task_map(args.evals)),
        "estimators": estimator_error(rows),
        "blocks": block_sizes(rows),
        "edit_cost": edit_cost(rows),
        "not_knowable_at_router": [
            "recalled chunk vs user turn (both role=user at the router; sized per kind "
            "only on the direct path, event=direct)",
            "step digest (enters node messages as user/system text; no marker at the router)",
        ],
    }
    print_table(rep)
    out = args.out or os.path.join(
        ROOT, "evals", "results", f"clm-baseline-{_dt.date.today().isoformat()}.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
