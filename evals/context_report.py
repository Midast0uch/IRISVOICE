"""Per-task context-pressure report for the `context` eval group (CLM T2.7).

    python evals/context_report.py evals/results/<run>.json [--log logs/clm_baseline.jsonl]
                                   [--dumps DIR] [--target 1.5] [--json]

Joins a run's results (task id -> conversation_id, pass/fail) with the CLM baseline rows
the backend wrote while IRIS_CLM_BASELINE=1 (one `call` row per model call, one `direct`
row per direct-path assembly; both carry the conversation id) and prints, per task:

  model / window       provider, model and the largest window the cap saw (rows carry both).
                       A run whose model is not the one you meant is visible HERE: the results
                       file's own `models` field reads a config key that is empty.
  declared pressure    the task's declared read volume (tasks.json `pressure.read_chars`, router
                       rule chars/3.5) divided by that window, against --target (default 1.5).
                       Below target the task is UNDER-PRESSURE: a pass says nothing about CLM.
  pre-cap fill         max over calls of cap.est_before / window - what the prompt WOULD have
                       been before the router cap; >= 1.0 means the cap had work to do.
  max fill             largest real prompt (usage.prompt_tokens, else the router estimate) / window.
  blind drops          router-cap calls that dropped messages, messages, estimated tokens.
  offload              set-aside and expand counts, when the backend reports them (see below).
  direct (history)     branch, history messages sent, recency cut / budget trim / align pop
                       message counts of the direct-path assembly (x05).
  needles in last call (only with --dumps) how many of the task's needle strings are in the text
                       of the conversation's LAST model call; needs the per-call dump proposed in
                       the T2.7 report (IRIS_CLM_DUMP_DIR).

Offload counts are read from whatever the backend writes, tolerantly:
  * a `call` row key `offload` = {"offloaded": n, "restretched": n, "model_set_aside": n,
    "model_expand": n} (running totals; the report takes the maximum seen), and/or
  * separate rows with event "offloaded" / "restretched" (one row per event; field `actor`
    = "harness" | "model" when present), counted per conversation.
Neither exists yet (the offload agent adds them); until then the column says n/a.

Read-only; imports nothing from the backend.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

EVALS = Path(__file__).resolve().parent
ROOT = EVALS.parent
ANSWERS = EVALS / "fixtures" / "_context" / "answers.json"
TASKS = EVALS / "tasks.json"
CHARS_PER_TOKEN = 3.5     # the router/gauge rule (context_gauge.estimate_tokens)


def _rows(path: Path) -> dict:
    by_conv: dict = defaultdict(lambda: {"call": [], "direct": [], "event": []})
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        conv = r.get("conversation_id")
        if not conv:
            continue
        kind = r.get("event")
        if kind in ("call", "direct"):
            by_conv[conv][kind].append(r)
        elif kind in ("offloaded", "restretched"):
            by_conv[conv]["event"].append(r)
    return by_conv


def _last_call_text(dumps: Path, conv: str) -> str | None:
    files = sorted(dumps.glob(f"{conv}-*.json"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
    if not files:
        return None
    msgs = json.loads(files[-1].read_text(encoding="utf-8")).get("messages") or []
    out = []
    for m in msgs:
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            out.extend(p.get("text", "") for p in c if isinstance(p, dict))
        if m.get("tool_calls"):
            out.append(json.dumps(m["tool_calls"]))
    return "\n".join(out)


def _offload(calls: list, events: list) -> dict | None:
    """Counts the backend reported, or None when it reported nothing."""
    best = {"offloaded": 0, "restretched": 0, "model_set_aside": 0, "model_expand": 0}
    seen = False
    for c in calls:
        o = c.get("offload")
        if isinstance(o, dict):
            seen = True
            for k in best:
                best[k] = max(best[k], int(o.get(k) or 0))
    for e in events:
        seen = True
        if e.get("event") == "offloaded":
            best["offloaded"] += 1
            if e.get("actor") == "model":
                best["model_set_aside"] += 1
        elif e.get("event") == "restretched":
            best["restretched"] += 1
            if e.get("actor") == "model":
                best["model_expand"] += 1
    return best if seen else None


def report(results_path: Path, log_path: Path, dumps: Path | None, target: float = 1.5) -> list:
    results = json.loads(results_path.read_text(encoding="utf-8"))["results"]
    rows = _rows(log_path)
    answers = json.loads(ANSWERS.read_text(encoding="utf-8")) if ANSWERS.is_file() else {}
    tasks = {t["id"]: t for t in json.loads(TASKS.read_text(encoding="utf-8"))["tasks"]
             if t.get("group") == "context"}
    out = []
    for res in results:
        if res.get("group") != "context":
            continue
        conv = res.get("conversation_id")
        calls = rows[conv]["call"] if conv in rows else []
        direct = rows[conv]["direct"] if conv in rows else []
        events = rows[conv]["event"] if conv in rows else []
        best = (0.0, None)
        pre_cap = 0.0
        window = 0
        blind_calls = blind_msgs = blind_tok = 0
        for c in calls:
            w = c.get("window") or 0
            window = max(window, w)
            used = ((c.get("usage") or {}).get("prompt_tokens")
                    or ((c.get("est") or {}).get("router_3_5") or {}).get("tokens") or 0)
            if w and used / w > best[0]:
                best = (used / w, c.get("seq"))
            cap = c.get("cap") or {}
            if w and cap.get("est_before"):
                pre_cap = max(pre_cap, cap["est_before"] / w)
            if cap.get("dropped_messages"):
                blind_calls += 1
                blind_msgs += cap["dropped_messages"]
                blind_tok += cap.get("dropped_tokens_est", 0)
        last = calls[-1] if calls else {}
        last_direct = direct[-1] if direct else None
        needles = None
        if dumps is not None:
            text = _last_call_text(dumps, conv)
            wanted = (answers.get(res["id"].split("_")[0]) or {}).get("needles") or []
            if text is not None and wanted:
                needles = f"{sum(1 for n in wanted if n in text)}/{len(wanted)}"
        read_chars = ((tasks.get(res["id"]) or {}).get("pressure") or {}).get("read_chars")
        declared = (read_chars / CHARS_PER_TOKEN / window) if (read_chars and window) else None
        out.append({
            "id": res["id"], "passed": res.get("passed"), "conversation_id": conv,
            "provider": last.get("provider"), "model": last.get("model"), "window": window or None,
            "declared_ratio": None if declared is None else round(declared, 2),
            "under_pressure": None if declared is None else declared < target,
            "calls": len(calls), "max_fill": round(best[0], 3), "max_fill_seq": best[1],
            "pre_cap_fill": round(pre_cap, 3),
            "blind_drop_calls": blind_calls, "blind_drop_messages": blind_msgs, "blind_drop_tokens": blind_tok,
            "offload": _offload(calls, events),
            "direct": None if last_direct is None else {
                "branch": last_direct.get("branch"),
                "history_messages_sent": len((last_direct.get("blocks") or {}).get("history") or []),
                "recency_cut_messages": last_direct.get("recency_cut_messages"),
                "budget_trim_messages": last_direct.get("budget_trim_messages"),
                "align_pop_messages": last_direct.get("align_pop_messages"),
                "budget_for_history": last_direct.get("budget_for_history"),
            },
            "needles_in_last_call": needles,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--log", default=str(ROOT / "logs" / "clm_baseline.jsonl"))
    ap.add_argument("--dumps", default=None)
    ap.add_argument("--target", type=float, default=1.5,
                    help="declared pressure ratio a task must reach at the window in use (default 1.5)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows = report(Path(a.results), Path(a.log), Path(a.dumps) if a.dumps else None, a.target)
    if a.json:
        print(json.dumps(rows, indent=2))
        return 0
    for r in rows:
        d, o = r["direct"], r["offload"]
        press = ("n/a" if r["declared_ratio"] is None else
                 f"{r['declared_ratio']:.2f}{' UNDER-PRESSURE' if r['under_pressure'] else ' ok'}")
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['id']:<22} {r['provider']}/{r['model']} window={r['window']}  "
              f"declared={press} (target {a.target})  calls={r['calls']:>3}  pre_cap_fill={r['pre_cap_fill']:.2f} "
              f"max_fill={r['max_fill']:.3f}  blind_drop calls/msgs/tok="
              f"{r['blind_drop_calls']}/{r['blind_drop_messages']}/{r['blind_drop_tokens']}  "
              + ("offload=n/a" if o is None else
                 f"offloaded={o['offloaded']} restretched={o['restretched']} "
                 f"model_set_aside={o['model_set_aside']} model_expand={o['model_expand']}")
              + f"  needles_in_last_call={r['needles_in_last_call'] or 'n/a'}"
              + (f"  direct[{d['branch']}] history_msgs={d['history_messages_sent']} "
                 f"cut recency/budget/align={d['recency_cut_messages']}/{d['budget_trim_messages']}/{d['align_pop_messages']}"
                 if d else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
