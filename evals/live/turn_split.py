"""Split one live turn: span = time waiting on models/tools (interval union) + IRIS's own time.

Model calls: `[InferenceRouter] call done role=R model=M Xs ok=B` (logged at the end).
Tool calls:  `[TOOL_DISPATCH] ... duration_ms=N` (logged at the end).
Intervals are merged, so overlapping side calls are counted once.
"""
import datetime
import json
import re
import sys


def parse(path):
    rows = []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        rows.append((datetime.datetime.fromisoformat(d["timestamp"][:26]), d["message"]))
    return rows


def union(iv):
    tot, cur_s, cur_e = 0.0, None, None
    for s, e in sorted(iv):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                tot += (cur_e - cur_s).total_seconds()
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        tot += (cur_e - cur_s).total_seconds()
    return tot


def split(path):
    rows = parse(path)
    start = end = None
    for t, m in rows:
        if start is None and re.search(r"Processing message type: (dev_cli|text_message)", m):
            start = t
        if start and re.search(r"\[LAYERS\] turn=", m):
            end = t
    if not (start and end):
        return None
    mi, ti = [], []
    by_role = {}
    stalls = splits = 0
    for t, m in rows:
        if not (start <= t <= end):
            continue
        c = re.search(r"\[InferenceRouter\] call done role=(\w+) model=(\S+) ([\d.]+)s", m)
        if c:
            dur = float(c.group(3))
            mi.append((max(start, t - datetime.timedelta(seconds=dur)), t))
            k = c.group(1)
            n, s = by_role.get(k, (0, 0.0))
            by_role[k] = (n + 1, s + dur)
        d = re.search(r"\[TOOL_DISPATCH\] kind=tool .*duration_ms=(\d+)", m)
        if d:
            ti.append((max(start, t - datetime.timedelta(milliseconds=int(d.group(1)))), t))
        if "[ApiHttpx] stall" in m:
            stalls += 1
        if "_split_step" in m:
            splits += 1
    span = (end - start).total_seconds()
    busy = union(mi + ti)
    return dict(span=span, model=union(mi), tool=union(ti), busy=busy, iris=span - busy,
                by_role=by_role, stalls=stalls, splits=splits, n_tool=len(ti))


print(f"{'run':24s} {'span':>6s} {'model':>6s} {'tool':>6s} {'IRIS':>6s} {'#tool':>5s} {'stall':>5s} {'split':>5s}  model calls by role (n, s)")
for p in sys.argv[1:]:
    r = split(p)
    name = p.replace("\\", "/").split("/")[-1].replace(".log", "")
    if r is None:
        print(f"{name:24s} (no complete turn)")
        continue
    roles = " ".join(f"{k}={n}/{s:.0f}s" for k, (n, s) in sorted(r["by_role"].items()))
    print(f"{name:24s} {r['span']:6.1f} {r['model']:6.1f} {r['tool']:6.1f} {r['iris']:6.1f} "
          f"{r['n_tool']:5d} {r['stalls']:5d} {r['splits']:5d}  {roles}")
