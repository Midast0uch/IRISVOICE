"""Per-turn DER call count and timing, measured from the backend log.

Replaces the batcher simulation removed with commits 5a62d45d and a645c2bc
(2026-10-12). That script drove stub routers, so its numbers never came from a
real turn. This script reads the log that the backend wrote during real turns
and prints one row per DER turn:

  wall     text_message -> DER response, seconds (the turn time)
  1st      text_message -> first node start, seconds (planning and routing)
  plan     planner model calls (_plan_task)
  calls    node model calls (run_node)
  tools    tool calls that ran: ok / FAILED
  oracle   tool_choice Oracle decisions: enforced / decided
  other    other Oracle decisions: count / total decision ms
  nodes    nodes finished; zero = nodes that made no tool call
  split    _split_step triggers; recov = critical-failure recoveries
  card     task card suppressed / earned; shown = card rendered
  slowest  slowest "[Timing] DER stage" in the turn

Why: turns must stay fast. These columns show where a slow turn spent its
calls: planning, nodes that did no tool work, or splits. Only the log tail is
read (seek from the end), so the cost stays bounded on a multi-GB log.

Usage:
  python scripts/measure_der_call_count.py [--log logs/iris.log]
         [--tail-mb 40] [--last 10] [--conv conv-1579]
Exit 0 for a measurement run; 2 for bad arguments or a missing log.
"""
import argparse
import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MB = 1024 * 1024
# Cheap substring filter, checked before the regexes below.
KEYS = ("AgentKernel", "[DER", "[run_node]", "Oracle decide", "[Timing] DER stage")

RE_START = re.compile(r"\[Session: session_iris\] Processing message type: text_message")
RE_CARD = re.compile(r"TASK_CARD ts=\S+ conv=(\S+) turn=(\S+) title='(.*)' steps=\d+")
RE_RESPONSE = re.compile(r"\[AgentKernel\] DER response:")
RE_NODE_START = re.compile(r"\[DER\] node start step=")
RE_NODE_DONE = re.compile(r"\[DER\] node done step=")
RE_PLAN_TOK = re.compile(r"\(real, source=_plan_task\)")
RE_NODE_TOK = re.compile(r"\(real, source=run_node\)")
RE_TOOL = re.compile(r"\[run_node\] conv=(\S+) .*? -> (ok|FAILED)\b")
RE_ZERO = re.compile(r"\[run_node\] conv=(\S+) done[^:]*: 0 call\(s\)")
RE_ORACLE = re.compile(r"Oracle decide consumer=(\S+)(?:.*decision_latency_ms=(\d+))?")
RE_ENFORCED = re.compile(r"\[TOOL_DECISION\] Oracle decides tool=\S+ .*route=enforced")
RE_SPLIT = re.compile(r"\[DER\] _split_step trigger=")
RE_RECOV = re.compile(r"Critical-failure recovery -> split")
RE_SUPP = re.compile(r"task card suppressed")
RE_EARN = re.compile(r"task card earned at tool call")
RE_SURF = re.compile(r"surface_decision ")
RE_SHOWN = re.compile(r"surface_decision .*had_show=True")
RE_STAGE = re.compile(r"\[Timing\] DER stage (.+?): ([\d.]+) ms")

COLS = [("conv", 9), ("turn", 8), ("title", 30), ("wall", 6), ("1st", 6),
        ("plan", 4), ("calls", 5), ("tools", 7), ("oracle", 7), ("other", 11),
        ("nodes", 5), ("zero", 4), ("split", 5), ("recov", 5), ("card", 10),
        ("shown", 5), ("slowest", 0)]


class Turn:
    def __init__(self, start):
        self.start = start
        self.conv = None
        self.turn = "-"
        self.title = ""
        self.lines = []  # (timestamp, message) for lines the report reads


def read_turns(path, tail_bytes):
    """Return (turns, parsed_line_count) for the last tail_bytes of the log."""
    turns, cur, parsed = [], None, 0
    with path.open("rb") as f:
        start = max(0, f.seek(0, 2) - tail_bytes)
        f.seek(start)
        if start:
            f.readline()  # the seek landed inside a line; drop that partial line
        for raw in f:
            try:
                obj = json.loads(raw)
                when = datetime.fromisoformat(obj["timestamp"])
                msg = obj["message"]
            except (ValueError, KeyError, TypeError):
                continue  # not a JSON log line
            if not isinstance(msg, str):
                continue
            parsed += 1
            if RE_START.search(msg):
                if cur is not None:
                    turns.append(cur)
                cur = Turn(when)
                continue
            if cur is None or not any(k in msg for k in KEYS):
                continue
            cur.lines.append((when, msg))
            if cur.conv is None:
                m = RE_CARD.search(msg)
                if m:
                    cur.conv, cur.turn, cur.title = m.group(1), m.group(2), m.group(3)
    if cur is not None:
        turns.append(cur)
    return turns, parsed


def measure(t):
    def hits(rx):
        return [m for m in (rx.search(msg) for _, msg in t.lines) if m]

    end = next((w for w, msg in t.lines if RE_RESPONSE.search(msg)), None)
    first = next((w for w, msg in t.lines if RE_NODE_START.search(msg)), None)
    tools = [m.group(2) for m in hits(RE_TOOL) if m.group(1) == t.conv]
    oracle = hits(RE_ORACLE)
    tool_dec = [m for m in oracle if m.group(1) == "tool_choice"]
    other = [m for m in oracle if m.group(1) != "tool_choice"]
    stages = [(float(m.group(2)), m.group(1)) for m in hits(RE_STAGE)]
    if hits(RE_SUPP):
        card = "suppressed"
    elif hits(RE_EARN):
        card = "earned"
    else:
        card = "-"
    if hits(RE_SHOWN):
        shown = "yes"
    elif hits(RE_SURF):
        shown = "no"
    else:
        shown = "-"
    return {
        "conv": t.conv, "turn": t.turn, "title": t.title,
        "wall": (end - t.start).total_seconds() if end else None,
        "first": (first - t.start).total_seconds() if first else None,
        "plan": len(hits(RE_PLAN_TOK)),
        "calls": len(hits(RE_NODE_TOK)),
        "tool_n": len(tools), "ok": tools.count("ok"), "failed": tools.count("FAILED"),
        "enforced": len(hits(RE_ENFORCED)), "decided": len(tool_dec),
        "other_n": len(other),
        "other_ms": sum(int(m.group(2)) for m in other if m.group(2)),
        "nodes": len(hits(RE_NODE_DONE)),
        "zero": sum(1 for m in hits(RE_ZERO) if m.group(1) == t.conv),
        "split": len(hits(RE_SPLIT)), "recov": len(hits(RE_RECOV)),
        "card": card, "shown": shown,
        "slowest": max(stages, default=(0.0, "-")),
    }


def _num(v, fmt):
    return "-" if v is None else fmt.format(v)


def _cells(r):
    return [
        r["conv"], r["turn"][:8], r["title"].encode("ascii", "replace").decode()[:30],
        _num(r["wall"], "{:.1f}"), _num(r["first"], "{:.1f}"),
        r["plan"], r["calls"], f"{r['ok']}/{r['failed']}",
        f"{r['enforced']}/{r['decided']}", f"{r['other_n']}/{r['other_ms']}ms",
        r["nodes"], r["zero"], r["split"], r["recov"], r["card"], r["shown"],
        f"{r['slowest'][1]} {r['slowest'][0]:.0f}ms",
    ]


def _line(cells):
    return " ".join(f"{str(v):<{w}}" for (_, w), v in zip(COLS, cells)).rstrip()


def _median(rows, key):
    vals = [r[key] for r in rows if r[key] is not None]
    return statistics.median(vals) if vals else None


def _report(rows):
    tot = {k: sum(r[k] for r in rows) for k in
           ("ok", "failed", "enforced", "decided", "other_n", "other_ms",
            "calls", "plan", "nodes", "zero", "split", "recov")}
    print()
    print(_line([name for name, _ in COLS]))
    print(_line(["-" * w for _, w in COLS]))
    for r in rows:
        print(_line(_cells(r)))
    print()
    print(f"TOTALS over {len(rows)} turn(s): tools ok={tot['ok']} failed={tot['failed']}"
          f" | oracle enforced={tot['enforced']}/decided={tot['decided']}"
          f" | other={tot['other_n']} ({tot['other_ms']} ms)"
          f" | planner={tot['plan']} node calls={tot['calls']}"
          f" | nodes={tot['nodes']} zero-call={tot['zero']}"
          f" | splits={tot['split']} recov={tot['recov']}"
          f" | card suppressed={sum(r['card'] == 'suppressed' for r in rows)}"
          f" earned={sum(r['card'] == 'earned' for r in rows)}"
          f" shown={sum(r['shown'] == 'yes' for r in rows)}")
    med = {k: _median(rows, k) for k in ("wall", "first", "plan", "calls", "tool_n", "nodes", "zero", "split")}
    print("MEDIANS: wall={} s | 1st node={} s | planner={} | node calls={} | tools={}"
          " | nodes={} | zero-call={} | splits={}".format(
              *[_num(med[k], "{:.1f}") for k in ("wall", "first", "plan", "calls", "tool_n", "nodes", "zero", "split")]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Per-turn DER call count and timing from the backend log.")
    ap.add_argument("--log", type=Path, default=REPO / "logs" / "iris.log")
    ap.add_argument("--tail-mb", type=float, default=40.0, help="log tail to read, in MB")
    ap.add_argument("--last", type=int, default=10, help="show the last N DER turns")
    ap.add_argument("--conv", default=None, help="show only this conversation id")
    args = ap.parse_args(argv)
    if not args.log.is_file():
        print(f"missing log: {args.log}", file=sys.stderr)
        return 2
    if args.tail_mb <= 0 or args.last <= 0:
        print("--tail-mb and --last must be positive", file=sys.stderr)
        return 2

    turns, parsed = read_turns(args.log, int(args.tail_mb * MB))
    all_rows = [measure(t) for t in turns if t.conv]
    rows = [r for r in all_rows if args.conv in (None, r["conv"])][-args.last:]
    print(f"log: {args.log}  tail: {args.tail_mb:g} MB  json lines: {parsed}"
          f"  text turns: {len(turns)}  DER turns: {len(all_rows)}")
    print("legend: wall/1st seconds; plan = planner calls; calls = node model calls;"
          " tools = ok/FAILED; oracle = tool_choice enforced/decided;"
          " other = other Oracle decisions count/ms; zero = nodes with 0 tool calls;"
          " recov = critical-failure recoveries; shown = card rendered")
    if not rows:
        print("no DER turns found in the tail (try a larger --tail-mb)")
        return 0
    _report(rows)
    print(f"no task card (not DER): {len(turns) - len(all_rows)}"
          f"  no DER response (cut off): {sum(r['wall'] is None for r in rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
