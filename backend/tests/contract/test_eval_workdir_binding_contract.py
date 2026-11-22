"""An eval task never runs a developer-mode agent without its own work folder (2026-11-22).

Found in the commit review: `evals/fixtures/cal_bb16_multi_largest/repo/calculator.py`
(a TRACKED fixture) held the task's answer. 32 calibration tasks had path
"calibration" or "evals/fixtures/_calibration/repo"; only the dev_cli path binds a
workdir, so `{workdir}` became "" ("Work in the project directory . Add a function
largest(a, b)..."), and the developer-mode agent found calculator.py inside the IRIS
repo and edited it. The leak check ran only when a workdir was bound, so nothing saw it.

Each test FAILS on the runner and tasks.json before this change.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _runner():
    spec = importlib.util.spec_from_file_location("_run_evals_under_test", ROOT / "evals" / "run_evals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tasks():
    data = json.loads((ROOT / "evals" / "tasks.json").read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("tasks", data)


def _needs_workdir(t):
    return any("{workdir}" in str(x) for x in [t.get("prompt")] + list(t.get("seed_prompts") or []))


def test_every_task_that_names_a_workdir_runs_where_one_is_bound():
    bad = [(t["id"], t.get("path")) for t in _tasks() if _needs_workdir(t) and t.get("path") != "dev_cli"]
    assert bad == [], f"{len(bad)} task(s) would run with an empty project path: {bad[:5]}"


def test_the_runner_names_the_problem():
    run = _runner()
    assert run._workdir_problem({"id": "x", "path": "calibration", "prompt": "Work in {workdir}."})
    assert run._workdir_problem({"id": "x", "path": "dev_cli", "prompt": "Work in {workdir}."}) is None
    assert run._workdir_problem({"id": "x", "path": "text_message", "prompt": "Hello."}) is None


def test_the_turn_refuses_an_empty_project_path():
    run = _runner()
    task = {"id": "cal_x", "group": "calibration", "mode": "developer", "path": "calibration",
            "prompt": "Work in the project directory {workdir}. Add a function."}
    with pytest.raises(ValueError):
        asyncio.run(run._run_turn(task, "conv-x", None, 5.0))   # refused before any connection


def test_the_leak_check_covers_developer_mode_without_a_workdir():
    src = (ROOT / "evals" / "run_evals.py").read_text(encoding="utf-8")
    assert 'check_leaks = workdir is not None or task.get("mode") == "developer"' in src
    assert '"repo_leaks": leaks' in src
