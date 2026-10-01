"""Switching to developer mode never creates the agent sandbox (owner, 2026-10-01).

Measured: the mode switch ran `git worktree add` of the whole repo - 13-17 minutes of
hard-disk checkout, unbounded, every time - and it ran across eval tasks (c01 351 s,
c04 188 s). Owner rule: ask before every creation; the sandbox becomes a separate repo
(.mcm/GOALS.md 7c).
"""
from __future__ import annotations

import ast
from pathlib import Path

_MAIN = Path(__file__).resolve().parents[2] / "main.py"


def test_mode_endpoint_never_calls_worktree_setup():
    tree = ast.parse(_MAIN.read_text(encoding="utf-8", errors="replace"))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and n.attr == "setup"
        and isinstance(n.value, ast.Name) and n.value.id == "dev_worktree"
    ]
    assert not calls, (
        f"main.py references dev_worktree.setup at lines {[c.lineno for c in calls]} - "
        "the sandbox must never be created without asking the user")
