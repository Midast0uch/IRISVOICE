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


def mod(name):
    return importlib.import_module(f"{PKG}.{name}")


def make_workdir():
    # Outside the system temp folder, so workdir and temp allowances stay distinguishable.
    return tempfile.mkdtemp(dir=str(HERE), prefix="_wb_")


def drop(path):
    # Windows can hold a killed process's cwd for a moment: retry before giving up.
    import time

    for _ in range(20):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return
        time.sleep(0.25)
