"""Shared by every hidden test folder (copied in next to the tests).

Puts the task's workdir on sys.path and offers helpers to read files there and
to compare a file with its original fixture copy.
"""

import os
import subprocess
import sys
from pathlib import Path

WORKDIR = Path(os.environ["EVAL_WORKDIR"])
HIDDEN = Path(__file__).resolve().parent
sys.path.insert(0, str(WORKDIR))


def read(rel: str) -> str:
    return (WORKDIR / rel).read_text(encoding="utf-8")


def unchanged(rel: str) -> bool:
    """True when the workdir file matches the original (newline-insensitive)."""
    original = (HIDDEN / "originals" / rel).read_text(encoding="utf-8")
    current = read(rel)
    norm = lambda s: s.replace("\r\n", "\n").strip()
    return norm(original) == norm(current)


def run_py(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args], cwd=WORKDIR, capture_output=True, text=True, timeout=timeout,
    )


def py_files() -> list:
    return [p for p in WORKDIR.rglob("*.py") if "_eval_hidden" not in p.parts]
