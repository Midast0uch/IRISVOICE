"""Workbench A/B analysis (Round 4, W0): per arm and per cohort, off / on / change.

Read-only, stdlib only. Usage:

    python evals/wb_ab_analysis.py <blocks.json> [--pairs off:on,A0:A1,B0:B1]
                                   [--baseline logs/clm_baseline.jsonl] [--log logs/iris.log]
                                   [--json out.json]

<blocks.json> is the driver's file: a list of blocks {"arm", "rep", "results": [eval
result files]}. Sources, joined on conversation_id:

  * evals/results/<file>.json   pass, reply_s (NOT `seconds`: it counts the reply being spoken)
  * logs/clm_baseline.jsonl     one row per model call (IRIS_CLM_BASELINE=1): role, call_kind,
                                sends, seconds, usage. Rows from before Round 4 W0 carry no
                                call_kind / sends: they read "other" / 1.
  * logs/iris.log               "[workbench] conv=.. step=.. code node", "falls back",
                                "escalated", and the per-node close line
                                "[workbench] conv=.. step=.. scripts=N exploring=M wait_s=X"

The pass bar (specs/clm-memory/design.md "Round 4") reads these rows per cohort: medians
per task-run unless the row says total.
"""
import argparse
import ast
import json
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Cohorts by task-id prefix (design "Measurement (TG-7 v2)"); x05 is the noise control.
COHORTS = {
    "context": ("x01", "x02", "x03", "x04"),
    "noise": ("x05",),
    "data": ("c46", "c47", "c48", "c49", "c50", "c51", "c52"),
    "config": ("c38", "c39", "c40", "c41", "c42", "c43", "c44", "c45"),
    "run-report": ("c14", "c17", "c18", "c19", "c25", "c26", "c27"),
    "explain": ("c13",),
    "write": ("c01", "c02", "c11"),
}
KINDS = ("label", "plan", "node", "code_node", "wb_repair", "synth", "other")
ROLES = ("reasoning", "tool_execution")

_WB_LINE = re.compile(r"\[workbench\] conv=(\S+) (?:step=(\S+) )?(code node|falls back|escalated)")
_WB_CLOSE = re.compile(r"\[workbench\] conv=(\S+) step=\S+ scripts=(\d+) exploring=(\d+) wait_s=([\d.]+)")


def cohort_of(task_id: str) -> str:
    prefix = str(task_id).split("_")[0].lower()
    for name, ids in COHORTS.items():
        if prefix in ids:
            return name
    return "other"


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 2) if xs else None


def load_runs(blocks_path: Path):
    blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
    runs, conv_arm = [], {}
    for b in blocks:
        for f in b.get("results") or []:
            data = json.loads(Path(f).read_text(encoding="utf-8"))
            for r in data.get("results") or []:
                cid = r.get("conversation_id")
                conv_arm[cid] = b["arm"]
                runs.append({"arm": b["arm"], "rep": b.get("rep"), "task": r.get("id"),
                             "cohort": cohort_of(r.get("id")), "conv": cid,
                             "passed": bool(r.get("passed")), "reply_s": r.get("reply_s")})
    return runs, conv_arm


def load_calls(path: Path, conv_arm):
    calls = defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if '"event": "call"' not in line and '"event":"call"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("conversation_id") in conv_arm:
                calls[row["conversation_id"]].append(row)
    return calls


def load_wb(path: Path, conv_arm):
    wb = defaultdict(lambda: {"code": 0, "fallback": 0, "escalated": 0,
                              "scripts": 0, "exploring": 0, "wait_s": 0.0})
    if not path.exists():
        return wb
    key = {"code node": "code", "falls back": "fallback", "escalated": "escalated"}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "[workbench]" not in line:
                continue
            m = _WB_CLOSE.search(line)
            if m and m.group(1) in conv_arm:
                w = wb[m.group(1)]
                w["scripts"] += int(m.group(2))
                w["exploring"] += int(m.group(3))
                w["wait_s"] += float(m.group(4))
                continue
            m = _WB_LINE.search(line)
            if m and m.group(1) in conv_arm:
                wb[m.group(1)][key[m.group(3)]] += 1
    return wb


def per_run(runs, calls, wb):
    for r in runs:
        rows = calls.get(r["conv"], [])
        usage = [x.get("usage") or {} for x in rows]
        by_role, by_kind = defaultdict(int), defaultdict(int)
        ptok_role, ctok_role = defaultdict(int), defaultdict(int)
        for x, u in zip(rows, usage):
            by_role[x.get("role")] += 1
            by_kind[x.get("call_kind") or "other"] += 1
            ptok_role[x.get("role")] += int(u.get("prompt_tokens") or 0)
            ctok_role[x.get("role")] += int(u.get("completion_tokens") or 0)
        r["calls"] = len(rows)
        r["by_role"], r["by_kind"] = dict(by_role), dict(by_kind)
        r["sends"] = sum(int(x.get("sends") or 1) for x in rows)
        r["prompt_tok"] = sum(int(u.get("prompt_tokens") or 0) for u in usage)
        r["compl_tok"] = sum(int(u.get("completion_tokens") or 0) for u in usage)
        r["ptok_role"], r["ctok_role"] = dict(ptok_role), dict(ctok_role)
        r["max_prompt"] = max([int(u.get("prompt_tokens") or 0) for u in usage] or [0])
        r["repair_s"] = [float(x["seconds"]) for x in rows
                         if x.get("call_kind") == "wb_repair" and x.get("seconds") is not None]
        r["plan_retries"] = max(0, by_kind.get("plan", 0) - 1)
        w = wb[r["conv"]]
        r.update(code_nodes=w["code"], fallbacks=w["fallback"], escalations=w["escalated"],
                 scripts=w["scripts"], exploring=w["exploring"], wb_wait_s=round(w["wait_s"], 1))
    return runs


def _val(v):
    return "-" if v is None else (f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))


def _change(off, on):
    if not isinstance(off, (int, float)) or not isinstance(on, (int, float)):
        return "-"
    if off == 0:
        return "-" if on == 0 else f"+{_val(on)}"
    return f"x{on / off:.2f}"


def metrics(rs):
    """name -> value for one arm over one cohort's runs ([] -> all None)."""
    if not rs:
        return {}
    out = {}
    out["runs"] = len(rs)
    out["pass"] = f"{sum(r['passed'] for r in rs)}/{len(rs)}"
    out["reply_s median"] = med([r["reply_s"] for r in rs])
    out["calls median"] = med([r["calls"] for r in rs])
    for role in ROLES:
        out[f"calls {role} median"] = med([r["by_role"].get(role, 0) for r in rs])
    for kind in KINDS:
        out[f"calls kind={kind} median"] = med([r["by_kind"].get(kind, 0) for r in rs])
    out["sends total"] = sum(r["sends"] for r in rs)
    out["sends per call"] = round(sum(r["sends"] for r in rs) / max(1, sum(r["calls"] for r in rs)), 3)
    out["prompt tok median"] = med([r["prompt_tok"] for r in rs])
    out["completion tok median"] = med([r["compl_tok"] for r in rs])
    for role in ROLES:
        out[f"prompt tok total {role}"] = sum(r["ptok_role"].get(role, 0) for r in rs)
        out[f"completion tok total {role}"] = sum(r["ctok_role"].get(role, 0) for r in rs)
    out["prompt tok total"] = sum(r["prompt_tok"] for r in rs)
    out["completion tok total"] = sum(r["compl_tok"] for r in rs)
    out["max prompt tok"] = max(r["max_prompt"] for r in rs)
    nodes = sum(r["code_nodes"] for r in rs)
    out["code nodes total"] = nodes
    out["fallbacks total"] = sum(r["fallbacks"] for r in rs)
    out["scripts per code node"] = round(sum(r["scripts"] for r in rs) / nodes, 2) if nodes else None
    out["exploring scripts total"] = sum(r["exploring"] for r in rs)
    out["escalations total"] = sum(r["escalations"] for r in rs)
    out["escalations % of code nodes"] = round(100.0 * sum(r["escalations"] for r in rs) / nodes, 1) if nodes else None
    out["escalation seconds median"] = med([s for r in rs for s in r["repair_s"]])
    out["planner retries total"] = sum(r["plan_retries"] for r in rs)
    out["wb_wait_s total"] = round(sum(r["wb_wait_s"] for r in rs), 1)
    return out


def table(title, off_rs, on_rs, off_name, on_name):
    a, b = metrics(off_rs), metrics(on_rs)
    lines = [f"\n== {title}  ({off_name} {len(off_rs)} runs, {on_name} {len(on_rs)} runs)",
             f"{'metric':36} {off_name:>14} {on_name:>14} {'change':>9}"]
    for name in dict.fromkeys(list(a) + list(b)):
        if name == "runs":
            continue
        lines.append(f"{name:36} {_val(a.get(name)):>14} {_val(b.get(name)):>14} "
                     f"{_change(a.get(name), b.get(name)):>9}")
    return "\n".join(lines), {"off": a, "on": b}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("blocks")
    ap.add_argument("--pairs", default="off:on,A0:A1,B0:B1")
    ap.add_argument("--baseline", default=str(ROOT / "logs" / "clm_baseline.jsonl"))
    ap.add_argument("--log", default=str(ROOT / "logs" / "iris.log"))
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    runs, conv_arm = load_runs(Path(args.blocks))
    runs = per_run(runs, load_calls(Path(args.baseline), conv_arm), load_wb(Path(args.log), conv_arm))
    arms = {r["arm"] for r in runs}
    summary = {}
    for pair in args.pairs.split(","):
        off_name, _, on_name = pair.partition(":")
        if off_name not in arms or on_name not in arms:
            continue
        for cohort in ["all"] + [c for c in list(COHORTS) + ["other"]
                                 if any(r["cohort"] == c for r in runs)]:
            sel = (lambda arm: [r for r in runs if r["arm"] == arm
                                and (cohort == "all" or r["cohort"] == cohort)])
            text, data = table(f"{pair} cohort={cohort}", sel(off_name), sel(on_name), off_name, on_name)
            print(text)
            summary[f"{pair}/{cohort}"] = data
    if not summary:
        print(f"no pair of {args.pairs} found among arms {sorted(arms)}", file=sys.stderr)
        return 1
    if args.json:
        Path(args.json).write_text(json.dumps({"runs": runs, "summary": summary}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
