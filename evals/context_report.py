"""Per-task context-pressure report for the `context` eval group (CLM T2.7).

    python evals/context_report.py evals/results/<run>.json [--log logs/clm_baseline.jsonl] [--dumps DIR]

Joins a run's results (task id -> conversation_id, pass/fail) with the CLM baseline
rows the backend wrote while IRIS_CLM_BASELINE=1 (one `call` row per model call, one
`direct` row per direct-path assembly; both carry the conversation id) and prints, per task:

  calls, max fill      largest prompt of the conversation / window (real prompt_tokens when the
                       provider reported it, else the router estimate), and which call
  blind drops          router-cap calls that dropped messages, messages, estimated tokens
  direct (history)     branch, history messages sent, recency cut / budget trim / align pop
                       message counts of the direct-path assembly (x05)
  needles in last call (only with --dumps) how many of the task's needle strings are in the
                       text of the conversation's LAST model call - the "fact still in the
                       model's input at the final call" check; needs the per-call dump described
                       in the T2.7 report (IRIS_CLM_DUMP_DIR); without it the column says n/a.

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


def _rows(path: Path) -> dict:
    by_conv: dict = defaultdict(lambda: {"call": [], "direct": []})
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("event") in ("call", "direct") and r.get("conversation_id"):
            by_conv[r["conversation_id"]][r["event"]].append(r)
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


def report(results_path: Path, log_path: Path, dumps: Path | None) -> list:
    results = json.loads(results_path.read_text(encoding="utf-8"))["results"]
    rows = _rows(log_path)
    answers = json.loads(ANSWERS.read_text(encoding="utf-8")) if ANSWERS.is_file() else {}
    out = []
    for res in results:
        if res.get("group") != "context":
            continue
        conv = res.get("conversation_id")
        calls = rows[conv]["call"] if conv in rows else []
        direct = rows[conv]["direct"] if conv in rows else []
        best = (0.0, None)
        blind_calls = blind_msgs = blind_tok = 0
        for c in calls:
            window = c.get("window") or 0
            used = ((c.get("usage") or {}).get("prompt_tokens")
                    or ((c.get("est") or {}).get("router_3_5") or {}).get("tokens") or 0)
            if window and used / window > best[0]:
                best = (used / window, c.get("seq"))
            cap = c.get("cap") or {}
            if cap.get("dropped_messages"):
                blind_calls += 1
                blind_msgs += cap["dropped_messages"]
                blind_tok += cap.get("dropped_tokens_est", 0)
        last_direct = direct[-1] if direct else None
        needles = None
        if dumps is not None:
            text = _last_call_text(dumps, conv)
            wanted = (answers.get(res["id"].split("_")[0]) or {}).get("needles") or []
            if text is not None and wanted:
                needles = f"{sum(1 for n in wanted if n in text)}/{len(wanted)}"
        out.append({
            "id": res["id"], "passed": res.get("passed"), "conversation_id": conv,
            "calls": len(calls), "max_fill": round(best[0], 3), "max_fill_seq": best[1],
            "blind_drop_calls": blind_calls, "blind_drop_messages": blind_msgs, "blind_drop_tokens": blind_tok,
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
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows = report(Path(a.results), Path(a.log), Path(a.dumps) if a.dumps else None)
    if a.json:
        print(json.dumps(rows, indent=2))
        return 0
    for r in rows:
        d = r["direct"]
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['id']:<22} calls={r['calls']:>3} "
              f"max_fill={r['max_fill']:.3f} (call {r['max_fill_seq']})  "
              f"blind_drop calls/msgs/tok={r['blind_drop_calls']}/{r['blind_drop_messages']}/{r['blind_drop_tokens']}  "
              f"needles_in_last_call={r['needles_in_last_call'] or 'n/a'}"
              + (f"  direct[{d['branch']}] history_msgs={d['history_messages_sent']} "
                 f"cut recency/budget/align={d['recency_cut_messages']}/{d['budget_trim_messages']}/{d['align_pop_messages']}"
                 if d else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
