"""Every sampled (outcome-labelled) Oracle row stores the question it asked.

Found 2026-11-09 (oracle.md section 12): the sampled rung's rows are the ones
the turn outcome labels - the evidence the bar needs - and none of the three
writers stored `state`. escalate_incomplete had 202 outcome-labelled rows on
d1-2B and not one could be replayed, so no question change could be measured
on its real labels. Pinned structurally (the call sites sit inside large
methods): each sampled_row(...) call passes state=.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SITES = (
    "backend/agent/der_loop.py",
    "backend/agent/tool_decision.py",
    "backend/agent/tools/browser_tools.py",
)


def _calls(src: str):
    out, i = [], 0
    while True:
        i = src.find("sampled_row(", i)
        if i < 0:
            return out
        if not re.search(r"def\s+$", src[max(0, i - 8):i]):
            depth, j = 0, i + len("sampled_row")
            for j in range(i + len("sampled_row"), len(src)):
                if src[j] == "(":
                    depth += 1
                elif src[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
            out.append(src[i:j + 1])
        i += 1


def test_every_sampled_row_call_stores_state():
    seen = 0
    for rel in _SITES:
        for call in _calls((_ROOT / rel).read_text(encoding="utf-8", errors="replace")):
            seen += 1
            assert "state=" in call, f"{rel}: a sampled row without its question:\n{call}"
    assert seen >= 3, "the three sampled writers moved; re-pin them"
