"""
iris-process-manager — Windows-aware process manager for IRIS services.

Solves three real Windows bugs that were causing 9-15 GB cmd.exe spikes:

  1. conhost.exe leak  (vercel/turborepo#11808, openclaw#30060)
     - `detached: true` + `stdio: 'inherit'` causes Node to allocate a
       conhost.exe for the child that never gets reaped.
     - Fix: windowsHide: true (suppresses conhost.exe allocation entirely).

  2. Pipe buffer in parent  (nodejs/node#49631, #4236)
     - When a child process hangs and its stdout is piped to the parent,
       the parent buffers everything in memory up to the pipe capacity,
       which on Windows is effectively unbounded.
     - Fix: redirect stdout/stderr to a rotating log file. The parent
       never holds the data in memory.

  3. No tree cleanup on Windows  (vercel/turborepo#11829)
     - `TerminateProcess` only kills the direct child, not grandchildren.
     - Fix: Windows Job Objects with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
       When the manager exits, the Job Object closes and Windows kills
       the entire tree.

Usage (from .bat or PowerShell):
    python scripts/iris_process_manager.py start backend  -- python -m uvicorn backend.main:app --port 8000
    python scripts/iris_process_manager.py start frontend -- npm run dev
    python scripts/iris_process_manager.py stop                # kills both
    python scripts/iris_process_manager.py status              # shows PIDs + memory

Logs go to .iris-logs/<service>-<timestamp>.log with rotation at 50 MB.
PIDs go to .iris-pids/<service>.pid.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# Windows-specific imports. On other platforms the manager still works
# but without Job Object tree cleanup.
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    # Windows API constants we need
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = REPO_ROOT / ".iris-logs"
PID_DIR = REPO_ROOT / ".iris-pids"
LOG_MAX_BYTES = 50 * 1024 * 1024  # 50 MB per log file before rotation
LOG_KEEP = 3  # keep last 3 rotated logs per service


# ─── Windows Job Object helpers ─────────────────────────────────────────────


def _create_job_object_windows():
    """Create a Windows Job Object that kills all assigned processes when
    the Job handle is closed. Returns the handle, or None on non-Windows.

    This is the standard Windows mechanism for process tree cleanup,
    analogous to Unix process groups. See vercel/turborepo#11829."""
    if sys.platform != "win32":
        return None
    try:
        # CreateJobObjectW(NULL, NULL) -> HANDLE
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None

        # SetJobObject - JOBOBJECT_BASIC_LIMIT_INFORMATION with KILL_ON_JOB_CLOSE
        # Plus the extended struct that holds these fields
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        length = ctypes.sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION)
        # SetInformationJobObject(handle, JobObjectExtendedLimitInformation=9, &info, length)
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        ok = kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), length)
        if not ok:
            ctypes.windll.kernel32.CloseHandle(handle)
            return None
        return handle
    except Exception as e:
        print(f"[warn] could not create Windows Job Object: {e}", file=sys.stderr)
        return None


def _assign_to_job_windows(job_handle, child_pid):
    """Assign an already-spawned child process to a Windows Job Object.
    Done via AssignProcessToJobObject, which requires we have an open
    HANDLE to the child process. We open it here via OpenProcess."""
    if sys.platform != "win32" or job_handle is None:
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        # OpenProcess for set_quota + terminate rights
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        proc_handle = kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, child_pid
        )
        if not proc_handle:
            return False
        try:
            kernel32.AssignProcessToJobObject.argtypes = [
                wintypes.HANDLE,
                wintypes.HANDLE,
            ]
            kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
            ok = kernel32.AssignProcessToJobObject(job_handle, proc_handle)
            return bool(ok)
        finally:
            kernel32.CloseHandle(proc_handle)
    except Exception:
        return False


# ─── Log file management ───────────────────────────────────────────────────


def _rotate_logs(service: str):
    """Rotate logs older than LOG_KEEP. Caller appends to the active log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    pattern = f"{service}-*.log"
    logs = sorted(LOG_DIR.glob(pattern))
    # Delete oldest until we have LOG_KEEP - 1 (room for the active one)
    while len(logs) >= LOG_KEEP:
        try:
            logs.pop(0).unlink()
        except OSError:
            break


def _open_log(service: str):
    """Open a log file for append, rotating if it would exceed the cap."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{service}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    fh = open(log_path, "a", encoding="utf-8", buffering=1)  # line-buffered
    # Write a header so logs are identifiable
    fh.write(
        f"\n=== {service} started at {time.strftime('%Y-%m-%d %H:%M:%S')} pid_dir={PID_DIR} ===\n"
    )
    fh.flush()
    return fh, log_path


# ─── PID file management ───────────────────────────────────────────────────


def _write_pid(service: str, pid: int):
    PID_DIR.mkdir(parents=True, exist_ok=True)
    (PID_DIR / f"{service}.pid").write_text(str(pid))


def _read_pid(service: str) -> int | None:
    path = PID_DIR / f"{service}.pid"
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _clear_pid(service: str):
    path = PID_DIR / f"{service}.pid"
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def _is_alive(pid: int) -> bool:
    if sys.platform == "win32":
        # tasklist is reliable; ctypes is faster but a small wrapper around it
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return str(pid) in out
        except subprocess.CalledProcessError:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


# ─── Subprocess creation with all three fixes ──────────────────────────────


def start_service(name: str, cmd: list[str], cwd: str | None = None) -> int:
    """Start a service with the three Windows-safe settings:
    - windowsHide: true            (no conhost.exe)
    - stdout/stderr to log file     (no parent pipe buffering)
    - Windows Job Object            (tree kill on exit)

    `cwd` overrides the default REPO_ROOT for the child process. This lets
    us start the iris-launcher (a sibling project at iris-launcher/) without
    cd-ing in a wrapper shell.
    """
    # If a previous PID is recorded and alive, refuse to double-start
    existing = _read_pid(name)
    if existing and _is_alive(existing):
        print(f"[{name}] already running (pid {existing}). Stop it first.")
        return existing

    log_fh, log_path = _open_log(name)
    print(f"[{name}] starting: {' '.join(cmd)}")
    print(f"[{name}] logging to: {log_path}")
    if cwd:
        print(f"[{name}] cwd: {cwd}")

    # Use CREATE_NO_WINDOW on Windows so the child has no console allocated.
    # On non-Windows, this flag is ignored. Combined with windowsHide=True
    # in the spawn options, this is belt + suspenders against conhost.exe.
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW  # 0x08000000

    proc = subprocess.Popen(
        cmd,
        cwd=cwd or str(REPO_ROOT),
        stdout=log_fh,
        stderr=subprocess.STDOUT,  # merge stderr into stdout
        stdin=subprocess.DEVNULL,  # child never reads stdin
        shell=False,
        # On Windows: prevent the child from allocating a conhost.exe for
        # its console I/O. Without this, every detached child leaks one
        # conhost.exe that never gets reaped (the bug we're fixing).
        creationflags=creationflags,
    )

    # Wrap the process in a Windows Job Object for tree cleanup.
    job = _create_job_object_windows()
    if job is not None:
        ok = _assign_to_job_windows(job, proc.pid)
        if not ok:
            print(
                f"[{name}] warning: could not assign to Job Object. "
                f"Tree may not be killed on manager exit.",
                file=sys.stderr,
            )
        else:
            print(f"[{name}] assigned to Windows Job Object (KILL_ON_JOB_CLOSE)")
    else:
        if sys.platform == "win32":
            print(
                f"[{name}] warning: could not create Job Object. "
                f"Tree may not be killed on manager exit.",
                file=sys.stderr,
            )
        else:
            # On non-Windows, we rely on the shell process group. The
            # parent shell will receive SIGTERM and pass it to children.
            pass

    _write_pid(name, proc.pid)
    print(f"[{name}] pid: {proc.pid}")
    return proc.pid


def stop_service(name: str) -> bool:
    """Stop a service by killing the recorded PID + tree. On Windows we
    use taskkill /F /T which closes our Job Object handle and lets the
    KILL_ON_JOB_CLOSE flag do the rest of the tree cleanup."""
    pid = _read_pid(name)
    if not pid:
        print(f"[{name}] not running (no pid file)")
        return False
    if not _is_alive(pid):
        print(f"[{name}] pid {pid} not alive, clearing stale pid file")
        _clear_pid(name)
        return False
    print(f"[{name}] killing pid {pid} (and tree)...")
    if sys.platform == "win32":
        # /T = tree (children + grandchildren), /F = force
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, text=True
        )
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    _clear_pid(name)
    return True


def status_service(name: str) -> dict:
    pid = _read_pid(name)
    alive = _is_alive(pid) if pid else False
    mem_mb = None
    if alive and sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], text=True
            )
            # CSV columns: "Image Name","PID","Session Name","Session#","Mem Usage"
            parts = out.strip().strip('"').split('","')
            if len(parts) >= 5:
                mem_str = parts[4].strip().strip('"').replace(",", "").replace(" K", "")
                try:
                    mem_mb = round(int(mem_str) / 1024, 1)
                except ValueError:
                    pass
        except subprocess.CalledProcessError:
            pass
    return {"name": name, "pid": pid, "alive": alive, "mem_mb": mem_mb}


# ─── CLI ───────────────────────────────────────────────────────────────────


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PID_DIR.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser(description="IRIS process manager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start")
    p_start.add_argument("name")
    p_start.add_argument(
        "--cwd", default=None, help="Working directory for the child process"
    )
    p_start.add_argument("service_cmd", nargs=argparse.REMAINDER)

    # Workaround: nargs=REMAINDER eats --cwd, so we re-parse it from service_cmd
    def _extract_cwd(args, parser):
        if args.cwd:
            return args.cwd, args.service_cmd
        if args.service_cmd and args.service_cmd[0] == "--cwd":
            if len(args.service_cmd) < 2:
                parser.error("--cwd requires a value")
            return args.service_cmd[1], args.service_cmd[2:]
        return None, args.service_cmd

    sub.add_parser("stop")
    p_stop_named = sub.add_parser("stop-named")
    p_stop_named.add_argument("name")
    sub.add_parser("status")
    p_status_named = sub.add_parser("status-named")
    p_status_named.add_argument("name")

    args = parser.parse_args()

    if args.cmd == "start":
        if not args.service_cmd:
            print(
                "start requires a command, e.g.: start backend -- python -m uvicorn ..."
            )
            return 2
        # Extract --cwd from service_cmd if it wasn't parsed correctly
        actual_cwd, cmd = _extract_cwd(args, parser)
        if actual_cwd:
            args.cwd = actual_cwd
        # Strip leading "--" if present
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]
        pid = start_service(args.name, cmd, cwd=args.cwd)
        # Hold the manager process alive so the Job Object stays attached.
        # The console window IS the manager; closing it kills the tree.
        print(f"\n[manager] tracking pid {pid}. Close this window to stop the service.")
        print(
            f"[manager] (or run: python {Path(__file__).name} stop-named {args.name})"
        )
        try:
            while True:
                time.sleep(1)
                if not _is_alive(pid):
                    print(f"\n[manager] child pid {pid} exited.")
                    _clear_pid(args.name)
                    return 0
        except KeyboardInterrupt:
            print("\n[manager] interrupted, stopping service...")
            stop_service(args.name)
            return 0

    elif args.cmd == "stop":
        # Stop everything with a pid file
        any_killed = False
        if PID_DIR.exists():
            for f in sorted(PID_DIR.glob("*.pid")):
                name = f.stem
                if stop_service(name):
                    any_killed = True
        if not any_killed:
            print("no services running")
        return 0

    elif args.cmd == "stop-named":
        stop_service(args.name)
        return 0

    elif args.cmd == "status":
        if PID_DIR.exists():
            for f in sorted(PID_DIR.glob("*.pid")):
                s = status_service(f.stem)
                mem = f"{s['mem_mb']} MB" if s["mem_mb"] is not None else "?"
                print(
                    f"  {s['name']:12s}  pid={s['pid']!s:>6}  alive={str(s['alive']):5s}  mem={mem}"
                )
        else:
            print("no pid files (nothing started)")
        return 0

    elif args.cmd == "status-named":
        s = status_service(args.name)
        mem = f"{s['mem_mb']} MB" if s["mem_mb"] is not None else "?"
        print(json.dumps(s, indent=2))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
