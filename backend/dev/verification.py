"""
Verification gate (Gate 3 T4b, REQ-15).

After a dev turn that wrote files, run the TARGETED test command for the
touched paths and attach the result. Targeted only — a slow gate is a
skipped gate (REQ-15 AC2). Never reports success on failure (AC3) and says
"no covering test" explicitly when nothing maps (AC4).

Test discovery is name-convention based: for a touched source file, look
for tests/test_<stem>.py, <dir>/test_<stem>.py, or <stem>_test.py nearby.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

TEST_STEM_PREFIXES = ("test_",)
TEST_STEM_SUFFIXES = ("_test",)


def _candidate_test_files(touched: str) -> list[str]:
    """Name-convention candidates for one touched file."""
    directory, filename = os.path.split(touched)
    stem, ext = os.path.splitext(filename)
    if ext != ".py" or stem.startswith("__"):
        return []
    candidates: list[str] = []
    if stem.startswith("test_") or stem.endswith("_test"):
        candidates.append(touched)  # the touched file IS a test
    for prefix in TEST_STEM_PREFIXES:
        candidates.append(os.path.join(directory, "tests", f"{prefix}{stem}.py"))
        candidates.append(os.path.join(os.path.dirname(directory),
                                       "tests", f"{prefix}{stem}.py"))
        candidates.append(os.path.join(directory, f"{prefix}{stem}.py"))
    for suffix in TEST_STEM_SUFFIXES:
        candidates.append(os.path.join(directory, "tests", f"{stem}{suffix}.py"))
        candidates.append(os.path.join(directory, f"{stem}{suffix}.py"))
    # dedupe preserving order
    seen: set[str] = set()
    unique = []
    for c in candidates:
        norm = os.path.normpath(c)
        if norm not in seen:
            seen.add(norm)
            unique.append(norm)
    return unique


def map_tests_for_files(written: list[str]) -> tuple[list[str], list[str]]:
    """Split written files into (covered_by_test_files, uncovered).

    Returns the EXISTING test-file paths to run and the touched files with
    no covering test.
    """
    test_files: list[str] = []
    uncovered: list[str] = []
    for path in written:
        candidates = _candidate_test_files(path)
        existing = [c for c in candidates if os.path.isfile(c)]
        if existing:
            test_files.extend(existing)
        elif _candidate_test_files(path):  # it's python but nothing maps
            uncovered.append(path)
        else:
            uncovered.append(path)
    # dedupe test files
    seen: set[str] = set()
    unique_tests = []
    for t in test_files:
        if t not in seen:
            seen.add(t)
            unique_tests.append(t)
    return unique_tests, uncovered


async def run_verification_async(workdir: str, written: list[str],
                                 execute_fn=None) -> str:
    """Async form of run_verification (await from the orchestrator)."""
    test_files, uncovered = map_tests_for_files(written)

    lines: list[str] = ["[verification]"]
    py_touched = [w for w in written
                  if os.path.splitext(w)[1].lower() == ".py"]
    if not py_touched:
        lines.append("non-code files changed — verification skipped")
        return "\n".join(lines)

    if not test_files:
        if uncovered:
            lines.append("no covering test — turn reported UNVERIFIED "
                         f"({len(uncovered)} file(s) without a mapped test)")
        else:
            lines.append("no covering test — turn reported UNVERIFIED")
        return "\n".join(lines)

    quoted = " ".join(f'"{t}"' for t in test_files)
    cmd = f"python -m pytest -q {quoted}"

    if execute_fn is not None:
        result = await execute_fn(cmd, 120)
    else:
        import asyncio as _aio

        proc = await _aio.create_subprocess_shell(
            cmd, cwd=workdir, stdout=_aio.subprocess.PIPE,
            stderr=_aio.subprocess.STDOUT,
        )
        try:
            out, _ = await _aio.wait_for(proc.communicate(), timeout=120)
        except _aio.TimeoutError:
            proc.kill()
            result = {"success": False, "error": "verification timed out"}
        else:
            text = out.decode("utf-8", errors="replace")
            tail = "\n".join(text.strip().splitlines()[-8:])
            result = {"success": proc.returncode == 0,
                      "exit_code": proc.returncode, "output": tail}

    if result.get("success"):
        lines.append(f"targeted tests PASSED ({len(test_files)} test file(s))")
    else:
        failing = [
            l for l in str(result.get("output", "")).splitlines()
            if l.startswith("FAILED") or l.startswith("ERROR")
        ]
        detail = "; ".join(failing[:5]) if failing else \
            str(result.get("error") or result.get("output", ""))[-300:]
        lines.append(f"turn UNVERIFIED — targeted tests FAILED "
                     f"(exit={result.get('exit_code')}): {detail}")
    return "\n".join(lines)
