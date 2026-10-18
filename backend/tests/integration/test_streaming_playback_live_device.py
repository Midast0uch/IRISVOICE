"""Live-device proof: the REAL streaming TTS path never opens two PortAudio
streams at once (the 2026-10-13 access-violation condition).

This test goes past the mock boundary of
``test_streaming_playback_exclusive_contract.py``: it drives the REAL
``IRISGateway._speak_response`` playback path from concurrent threads against a
REAL sounddevice device and counts concurrently-open real ``OutputStream``
objects.

It runs ``scripts/playback_singleton_probe.py`` in a SUBPROCESS, so a native
access violation (the original bug) surfaces as an exit code instead of killing
the test run.

Evidence this pins (measured 2026-10-16, device "CABLE Input" MME #11):
  * pre-fix  : 3/3 runs -> max_concurrent_streams=2 (exit 2) - two real
               PortAudio streams alive at once, the crash condition.
  * fixed    : max_concurrent_streams=1 (exit 0) - the second utterance waits
               for the process-wide lock (~1.52 s) before it opens its stream.

Skips when no output device can be opened (headless CI).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PROBE = ROOT / "scripts" / "playback_singleton_probe.py"

# Windows access violation, as a process exit code.
ACCESS_VIOLATION = 0xC0000005


def _run_probe(iterations: int, concurrency: int) -> tuple[int, dict, str]:
    proc = subprocess.run(
        [
            sys.executable,
            str(PROBE),
            "--iterations",
            str(iterations),
            "--concurrency",
            str(concurrency),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    lines = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()]
    summary = {}
    if lines:
        try:
            summary = json.loads(lines[-1])
        except json.JSONDecodeError:
            summary = {}
    return proc.returncode, summary, (proc.stderr or "")


def test_real_streaming_playback_never_overlaps_on_a_real_device():
    returncode, summary, stderr = _run_probe(iterations=3, concurrency=2)

    if returncode == 3:
        pytest.skip("no usable output device on this machine")

    assert returncode != ACCESS_VIOLATION, (
        "the backend process died with a native access violation "
        f"(0x{ACCESS_VIOLATION:08X}) while two streaming playbacks ran - the "
        f"original bug is back. stderr tail: {stderr[-800:]}"
    )
    assert returncode == 0, (
        f"probe exited {returncode}; summary={summary}; stderr tail={stderr[-800:]}"
    )
    assert summary.get("stream_opens", 0) >= 1, (
        f"the probe opened no real stream - it did not exercise PortAudio. "
        f"summary={summary}"
    )
    assert summary.get("max_concurrent_streams") == 1, (
        "two real PortAudio output streams were open at once - the access-"
        f"violation condition. summary={summary}"
    )
