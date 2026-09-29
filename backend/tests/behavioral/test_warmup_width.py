"""Behavioural tests: warm-up at the effective cap width (REQ-30 AC30.4, T41).

AC30.4 — THE WARM-UP SHALL exercise a representative menu width (the effective
`candidate_cap`), not a 2-option menu.

Before T41 the startup warm-up called `decide("tool_choice", ["NONE",
"DELEGATE"], …)` while real menus are 6+. The encoder's structure grows with
the label set, so the first REAL menu paid the build the warm-up existed to
absorb.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from backend.agent.decision_backend_onnx import build_task

_REPO = Path(__file__).resolve().parents[3]
_MAIN = _REPO / "backend" / "main.py"


def _main_src() -> str:
    return _MAIN.read_text(encoding="utf-8", errors="replace")


class TestWarmupAtEffectiveCap:
    def test_warmup_at_effective_cap(self):
        """AC30.4: the warm-up sizes its menu from `candidate_cap`."""
        src = _main_src()
        assert "candidate_cap" in src, (
            "the warm-up does not consult the effective candidate_cap — it "
            "cannot be warming at a representative width (AC30.4)"
        )
        # The warm-up must still warm `tool_choice` (the enforced consumer).
        assert re.search(r'decide\(\s*"tool_choice"', src), (
            "the warm-up no longer exercises the tool_choice consumer"
        )
        # ...and the control labels are still supplied, so the menu it warms
        # has the same shape as a production menu.
        assert '"NONE", "DELEGATE"' in src, (
            "the warm-up menu lost the NONE/DELEGATE control labels"
        )

    def test_warmup_menu_is_built_not_hardcoded(self):
        """The menu is COMPUTED from the cap, so a config change moves it."""
        tree = ast.parse(_main_src())
        # Find the warm-up call: decide("tool_choice", <menu>, {"goal": "warm"})
        menus = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "decide"):
                continue
            if len(node.args) < 2:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and first.value == "tool_choice"):
                continue
            if len(node.args) >= 3 and isinstance(node.args[2], ast.Dict):
                keys = [k.value for k in node.args[2].keys
                        if isinstance(k, ast.Constant)]
                if "goal" in keys:
                    menus.append(node.args[1])
        assert menus, "no warm-up decide('tool_choice', …) call found in main.py"
        assert all(not isinstance(m, ast.List) for m in menus), (
            "the warm-up menu is a hardcoded list literal — it must be sized "
            "from the effective candidate_cap (AC30.4)"
        )

    def test_a_cap_width_menu_is_longer_than_two_options(self, onnx_runner):
        """Why the width matters: the encoder's structure grows with the label
        set, which is exactly what a 2-option warm-up failed to exercise."""
        two = build_task("tool_choice", ["NONE", "DELEGATE"])
        six = build_task("tool_choice", [
            "WARM_LABEL_0", "WARM_LABEL_1", "WARM_LABEL_2", "WARM_LABEL_3",
            "NONE", "DELEGATE",
        ])
        assert two is not None and six is not None

        ids_two, _ = onnx_runner._structure(two)
        ids_six, _ = onnx_runner._structure(six)

        assert len(ids_six) > len(ids_two), (
            "a 6-label menu did not produce a longer structure than a 2-label "
            "one — the warm-up width would not matter and AC30.4 is moot"
        )
