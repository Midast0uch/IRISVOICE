"""Keep the backend alive: restart it when the process dies OR hangs.

WHY (measured 2026-11-02/03): the backend dies with a native access violation
(0xC0000005, exit code 3221225477) under heavy write traffic. The crash has
no Python traceback: the faulting thread is native (the writer thread inside
iris_core.dll), so the only recovery is a restart. Five deaths cost five
traffic batches.

WHAT IT DOES: it watches the pid file that iris_process_manager.py writes and
restarts the service when the process is gone.

THE HANG CASE (added 2026-11-05, measured the same day). A dead pid is not the
only failure. Under a long paced traffic run the backend stopped answering
while its process stayed ALIVE: /health returned 503 (the TTS readiness gate)
and never recovered, so the eval harness's preflight failed every task with
"backend is not answering on http://127.0.0.1:8090". 36 of 52 tasks were lost
that way, and this watchdog did nothing because the pid was alive. The TTS
worker normally reloads itself after its own crash and the backend stays
healthy (measured 2026-11-03 03:52-03:56), so a TRANSIENT 503 must still be
tolerated - restarting on one would kill healthy cold boots, which measured
12.4s to 292.4s to reach /health 200.

So the rule is PERSISTENCE, not the status code: a non-200 health answer for
PERSISTENT_POLLS consecutive polls (default 12 x 30s = 360s, deliberately
longer than the slowest cold boot ever measured here) restarts the service.
Any 200 resets the streak. The streak is logged on every change so a hang is
visible in the log instead of inferred.

USAGE:
    python scripts/backend_watchdog.py            # run in the foreground
    python scripts/backend_watchdog.py --once     # one check, then exit
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PID_DIR = REPO_ROOT / ".iris-pids"
BACKEND_PID = PID_DIR / "backend.pid"
MANAGER = REPO_ROOT / "scripts" / "iris_process_manager.py"
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
POLL_S = 30.0
# Consecutive non-200 health polls before a restart. 12 x 30s = 360s. The
# slowest cold boot measured on this machine reached /health 200 in 292.4s, so
# 360s leaves ~68s of margin over a legitimate boot while still cutting a hang
# off in six minutes instead of never.
PERSISTENT_POLLS = int(os.environ.get("IRIS_WATCHDOG_PERSISTENT_POLLS", "12"))
HEALTH_URL = os.environ.get(
    "IRIS_WATCHDOG_HEALTH_URL", "http://127.0.0.1:8090/health")


def _pid_alive(pid: int) -> bool:
    """True when the pid exists (Windows: the process must answer a query)."""
    if pid <= 0:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return False
    return str(pid) in out


def _read_pid() -> int:
    try:
        return int(BACKEND_PID.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _restart(reason: str) -> bool:
    """Restart the backend through the manager (it owns the pid file)."""
    env = dict(os.environ)
    # The Oracle sample fraction must survive the restart: the calibration
    # traffic needs the sampled consumers to record rows.
    env.setdefault("IRIS_ORACLE_SAMPLE_FRACTION", "0.5")
    cmd = [str(PYTHON), str(MANAGER), "start", "--detach", "backend", "--",
           "python", "start-backend.py"]
    print(f"[watchdog] restarting the backend ({reason})", flush=True)
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env,
                              capture_output=True, text=True, timeout=180)
    except Exception as exc:  # noqa: BLE001 - a failed restart must not kill the watchdog
        print(f"[watchdog] restart failed: {exc!r}", flush=True)
        return False
    if proc.returncode != 0:
        print(f"[watchdog] restart returned {proc.returncode}: "
              f"{(proc.stderr or proc.stdout or '')[-300:]}", flush=True)
        return False
    print("[watchdog] restart requested", flush=True)
    return True


def _health() -> str:
    """The backend's health answer: "ok", "starting" (503) or "down" (no
    answer at all). Never raises - a watchdog that can crash is not a
    watchdog."""
    try:
        import json
        import urllib.request

        with urllib.request.urlopen(HEALTH_URL, timeout=10) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            body = resp.read(4096).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - any failure is "down"
        text = str(exc)
        if "503" in text or "Service Unavailable" in text:
            return "starting"
        return "down"
    if code == 200:
        return "ok"
    # A 503 body carries {"status":"starting","tts":{"status":"loading"}}; any
    # other non-200 is still "not ready", which the persistence rule treats the
    # same way.
    try:
        if json.loads(body).get("status") == "starting":
            return "starting"
    except Exception:  # noqa: BLE001 - an unreadable body is still non-200
        pass
    return "starting"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true",
                    help="check once, restart if the backend is gone, then exit")
    args = ap.parse_args()

    streak = 0
    last = ""
    # Pids this watchdog already health-restarted. A pid that hangs again
    # immediately after its own restart would otherwise be restarted every
    # PERSISTENT_POLLS forever; one health-restart per pid is the honest
    # bound, and the log says so rather than looping silently.
    health_restarted: set = set()
    while True:
        pid = _read_pid()
        if pid and not _pid_alive(pid):
            _restart(f"pid {pid} is gone")
            streak = 0
        elif not pid:
            print("[watchdog] no backend pid file yet", flush=True)
        elif pid:
            # The pid is alive: is it actually SERVING? A live process that
            # answers 503 forever is the hang this branch exists for.
            state = _health()
            if state == "ok":
                if streak:
                    print(f"[watchdog] health recovered after {streak} "
                          f"non-200 polls", flush=True)
                streak = 0
            else:
                streak += 1
                if state != last or streak in (1, PERSISTENT_POLLS):
                    print(f"[watchdog] health={state} streak={streak}"
                          f"/{PERSISTENT_POLLS} (pid {pid} alive)", flush=True)
                if streak >= PERSISTENT_POLLS:
                    if pid in health_restarted:
                        print(f"[watchdog] pid {pid} still health={state} "
                              f"after its own restart - NOT restarting again "
                              f"(one health-restart per pid); a human should "
                              f"look at this", flush=True)
                    else:
                        health_restarted.add(pid)
                        _restart(f"pid {pid} alive but health={state} for "
                                 f"{streak} polls (~{streak * POLL_S:.0f}s)")
                    streak = 0
            last = state
        if args.once:
            return 0
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
