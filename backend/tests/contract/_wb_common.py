"""Shared loader for the Workbench contract tests: the package under test is
`backend.agent.workbench` unless WORKBENCH_PKG / WORKBENCH_PKG_PATH name a copy
(the failure demonstrations load a deliberately broken copy under another name)."""
import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

PKG_PATH = os.environ.get("WORKBENCH_PKG_PATH")
if PKG_PATH:
    sys.path.insert(0, PKG_PATH)
PKG = os.environ.get("WORKBENCH_PKG", "backend.agent.workbench")

HERE = Path(__file__).resolve().parent
PYTHON = sys.executable
# Test workdirs live OUTSIDE the test tree (2026-11-17): created and deleted inside
# backend/tests/contract, a concurrent pytest collection lstat()ed a folder another run
# had just deleted -> FileNotFoundError (6 of 6 collections failed under churn). Also
# outside the repo and outside the system temp folder (the worker allows writes to
# temp, so a temp workdir would blur the "outside the workdir" refusals).
WB_WORK = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "iris-wb-tests"
WB_WORK.mkdir(parents=True, exist_ok=True)


def mod(name):
    return importlib.import_module(f"{PKG}.{name}")


def make_workdir():
    # Outside the system temp folder, so workdir and temp allowances stay distinguishable.
    return tempfile.mkdtemp(dir=str(WB_WORK), prefix="_wb_")


def drop(path):
    # Windows can hold a killed process's cwd for a moment: retry before giving up.
    import time

    for _ in range(20):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return
        time.sleep(0.25)
