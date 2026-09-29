"""Unit test: the LFM machinery is deleted, not dormant (REQ-21 AC21.6).

T29's deletion list, verified against the live source by AST — no symbol
survives in backend/agent/decision_engine.py, and no other module references
them by attribute either.
"""

from __future__ import annotations

import ast
from pathlib import Path

ENGINE = Path("backend/agent/decision_engine.py").read_text(encoding="utf-8")

# The deleted LFM machinery (AC21.6, amended).
DELETED_SYMBOLS = (
    "_score_options_one_pass",
    "_letter_token_ids",
    "_warm_head_state",
    "softmax_tau",
    "decide_tree",
    "hierarchy_trigger",
    "max_answer_tokens",
    "n_gpu_layers",
    "IRIS_DECISION_GPU_LAYERS",
    "_GLOB_PATTERNS",
    "_build_prompt_parts",
    "_build_prompt",
)

# What MUST survive (callers depend on both).
KEPT_SYMBOLS = ("DecisionScore", "ArgsResult", "gate", "decide", "generate_args")


def _defined_names(src: str) -> set:
    tree = ast.parse(src)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


class TestNoLfmSymbolsRemain:
    def test_no_lfm_symbols_remain(self):
        """AC21.6: none of the deleted LFM symbols is defined in the engine."""
        defined = _defined_names(ENGINE)
        for sym in DELETED_SYMBOLS:
            assert sym not in defined, f"deleted LFM symbol survived: {sym}"

    def test_no_lfm_symbols_referenced(self):
        """AC21.6 trap 3: no other module references the removed symbols by
        ATTRIBUTE as well as by name (the two scripts were attribute callers).
        Comment-only mentions are documentation, not references — stripped."""
        for rel in ("backend/agent/tool_decision.py",
                    "scripts/run_engine_calibration.py",
                    "scripts/bench_decision_models.py"):
            src = Path(rel).read_text(encoding="utf-8")
            code_only = "\n".join(
                line.split("#", 1)[0] for line in src.splitlines()
            )
            for sym in ("decide_tree", "_score_options_one_pass",
                        "_letter_token_ids", "_warm_head_state"):
                assert sym not in code_only, f"{rel} still references {sym}"

    def test_kept_symbols_survive(self):
        """The DecisionScore/ArgsResult envelope and gate() survive (T29)."""
        defined = _defined_names(ENGINE)
        for sym in KEPT_SYMBOLS:
            assert sym in defined, f"kept symbol missing: {sym}"

    def test_llama_cpp_import_removed(self):
        """TG-8: the llama_cpp import is removed from decision_engine.py."""
        assert "llama_cpp" not in ENGINE
