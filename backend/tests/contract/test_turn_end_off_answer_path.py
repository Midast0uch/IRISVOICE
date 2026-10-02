"""C5 (HANDOFF 7, 2026-10-01): turn-end bookkeeping never holds the reply.

Measured before: card footprint + plan stats + episode (+ landmark
crystallization, _auto_connect) + skill capture ran before the reply's
synthesis, 2-8.5 s per coding task (stack dumps, eval 20261001-213633). They
now run as one ordered job on lane("memory_events"); the next turn folds back
on it before planning recalls episodes.
"""

import ast
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from backend.agent import agent_kernel as ak

_KERNEL = Path("backend/agent/agent_kernel.py")
_BOOKKEEPING = (
    "_store_task_episode", "_maybe_trigger_skill_creation",
    "_save_card_footprint", "mycelium_record_plan_stats",
)


def _enclosing_functions(tree):
    """Map each Call node to the names of the functions that enclose it."""
    out = {}

    def walk(node, stack):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, stack + [child.name])
            else:
                if isinstance(child, ast.Call):
                    out[child] = stack
                walk(child, stack)

    walk(tree, [])
    return out


def test_turn_end_bookkeeping_is_called_only_from_the_lane_job():
    tree = ast.parse(_KERNEL.read_text(encoding="utf-8", errors="replace"))
    inline = []
    for call, stack in _enclosing_functions(tree).items():
        fn = call.func
        if isinstance(fn, ast.Attribute) and fn.attr in _BOOKKEEPING:
            if "_execute_plan_der" in stack and "_turn_end_job" not in stack:
                inline.append(f"{fn.attr} at line {call.lineno}")
    assert not inline, f"turn-end bookkeeping back on the reply path: {inline}"


def _skill_kernel(similar_episodes):
    """A stand-in kernel with the REAL _maybe_trigger_skill_creation."""
    import json as _json

    class _Semantic:
        def __init__(self):
            self.store = {}

        def get_by_category(self, category):
            return []

        def update(self, category, key, value, confidence=0.9, source=""):
            self.store[(category, key)] = value

        def update_user_display(self, **kw):
            pass

    class _Episodic:
        def retrieve_similar(self, task, limit=3, **kw):
            return [{"tool_sequence": _json.dumps(s)} for s in similar_episodes]

    k = SimpleNamespace(_prompted_skill_patterns=set(),
                        _memory_interface=SimpleNamespace(semantic=_Semantic(),
                                                          episodic=_Episodic()))
    k.capture = ak.AgentKernel._maybe_trigger_skill_creation.__get__(k)
    return k


_RUN = [{"tool": t, "params": {}, "success": True}
        for t in ("read_file", "edit_file", "run_command")]


def test_a_one_off_call_list_is_not_a_skill():
    """Owner 2026-10-01: every coding run has >= 3 distinct tools, so capture
    saved one task's call list per run (5 in one eval). Only this run's own
    episode has the shape -> no skill."""
    k = _skill_kernel([_RUN])
    k.capture(tool_sequence=_RUN, task_summary="fix the bug in m.py")
    assert k._memory_interface.semantic.store == {}


def test_a_shape_that_recurs_in_three_similar_runs_is_a_skill():
    k = _skill_kernel([_RUN, _RUN, _RUN])
    k.capture(tool_sequence=_RUN, task_summary="fix the bug in m.py")
    keys = [key for (_cat, key) in k._memory_interface.semantic.store]
    # named by the whole shape, so two recipes never share a key
    assert keys == ["skill_read_file_edit_file_run_command_workflow"]


def test_submit_returns_while_the_job_runs_and_settle_folds_back():
    owner = SimpleNamespace()
    release = threading.Event()
    ran = []

    def job():
        release.wait(5)
        ran.append(True)

    t0 = time.monotonic()
    ak._turn_end_submit(owner, "sess-c5", job)
    assert time.monotonic() - t0 < 0.5, "the reply path waited for the bookkeeping"
    assert not owner._turn_end_pending.is_set()

    threading.Timer(0.3, release.set).start()
    ak._turn_end_settle(owner)  # the next turn waits for the episode
    assert ran == [True] and owner._turn_end_pending.is_set()


def test_a_full_lane_runs_the_job_inline(monkeypatch):
    import backend.utils.durability_queue as dq

    class _Full:
        def submit(self, *a, **k):
            return False

        def in_worker(self):
            return False

    monkeypatch.setattr(dq, "lane", lambda name: _Full())
    owner = SimpleNamespace()
    ran = []
    ak._turn_end_submit(owner, "sess-c5", lambda: ran.append(True))
    assert ran == [True], "a dropped submit must not lose the episode"
    assert owner._turn_end_pending.is_set()
