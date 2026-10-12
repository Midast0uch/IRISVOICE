#!/usr/bin/env python3
"""Export outcome-checked tool decisions as d1 fine-tuning examples (2026-10-11).

Each example is EXACTLY the prompt d1 reads (the reference shape: manual
im_start markup, the state, QUESTION, coded options with the tools' decision
lines, "Reply with the option code only.") and the target option CODE of a
tool call that WORKED:

  * an Oracle-decided row (criteria_version tc-decide-*) whose call held
    (outside_label True) -> target = d1's own pick;
  * a shadow row (tc-frame-v6+) whose model call worked (brain_ok True)
    -> target = the model's tool.

A call that failed, was overridden or never happened is NOT a target (a failed
call is not evidence of the right tool). Rows without the replay `state` key
cannot be rendered and are skipped. Read-only on the store; writes one JSONL.

Usage:
    python scripts/export_tool_choice_training.py --out data/training/tool_choice.jsonl
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for p in (str(_REPO), str(_REPO / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _app_store import app_store_path  # noqa: E402

from backend.agent.decision_backend_d1 import D1Backend, _option_codes  # noqa: E402
from backend.agent.tool_registry import oracle_hint, resolve_tool  # noqa: E402

INSTRUCTION = "Which tool should handle this request?"


def _hint(name: str) -> str:
    spec = resolve_tool(name)
    return oracle_hint(name, getattr(spec, "description", "") if spec else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/training/tool_choice.jsonl")
    args = ap.parse_args()
    c = sqlite3.connect(f"file:{app_store_path()}?mode=ro", uri=True)
    seen, kept, why = set(), [], collections.Counter()
    for (p,) in c.execute("SELECT interaction_payload FROM system_events "
                          "WHERE event_type='tool_execution'"):
        try:
            d = json.loads(p or "{}").get("decision")
        except Exception:
            continue
        if not isinstance(d, dict) or d.get("consumer_id") != "tool_choice":
            continue
        cv = str(d.get("criteria_version") or "")
        state = d.get("state")
        cands = d.get("candidates")
        # older rows store `candidates` as a COUNT, not the menu: unrenderable
        menu = [x["name"] for x in cands if isinstance(x, dict) and x.get("name")] \
            if isinstance(cands, list) else []
        if not state or not menu:
            why["no_state"] += 1
            continue
        if cv.startswith("tc-decide"):
            target = d.get("chosen") if d.get("outside_label") is True else None
        elif cv >= "tc-frame-v6":
            target = d.get("brain_choice") if d.get("brain_ok") is True else None
        else:
            target = None
        if not target or target not in menu:
            why["not_a_verified_call"] += 1
            continue
        key = (state, target)
        if key in seen:
            why["duplicate"] += 1
            continue
        seen.add(key)
        codes = _option_codes(menu)
        text = D1Backend._question_choice(state, INSTRUCTION,
                                          {n: _hint(n) for n in menu}, menu)
        kept.append({"prompt": D1Backend._decision_prompt(text),
                     "completion": codes[menu.index(target)],
                     "tool": target, "source": cv, "menu_fp": d.get("menu_fp")})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for ex in kept:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"examples: {len(kept)} -> {out}")
    print("by tool:", dict(collections.Counter(e["tool"] for e in kept)))
    print("skipped:", dict(why))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
