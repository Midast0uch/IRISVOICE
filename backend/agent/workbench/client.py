"""Workbench parent side: spawn the worker, send one request at a time, bound every wait.

Stdlib only (psutil is imported lazily for the RSS cap). One client owns one child
process; a hard kill starts a fresh incarnation (variables are lost, and the reply says so).
"""
import logging
import os
import queue
import shutil
import subprocess
import tempfile
import sys
import threading
import time
from typing import Optional

from .protocol import PROTOCOL_VERSION, ProtocolError, decode, encode

logger = logging.getLogger(__name__)

WORKER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.py")
HARD_KILL_GRACE_S = 3.0        # after the soft stop, before the process is killed
RSS_LIMIT_BYTES = 512 << 20    # 512 MB, over the whole process tree
RSS_POLL_S = 0.25
OP_TIMEOUT_S = 30.0            # hello / inspect / put
_CREATE_NO_WINDOW = 0x08000000


def resolve_interpreter(workdir: str) -> Optional[str]:
    """Project venv, then PATH python, then sys.executable (not when frozen); else None."""
    rels = (
        os.path.join(".venv", "Scripts", "python.exe"), os.path.join("venv", "Scripts", "python.exe"),
        os.path.join(".venv", "bin", "python"), os.path.join("venv", "bin", "python"),
    )
    for rel in rels:
        cand = os.path.join(workdir, rel)
        if os.path.isfile(cand):
            return cand
    found = shutil.which("python")
    if found:
        return found
    if not getattr(sys, "frozen", False) and sys.executable:
        return sys.executable
    return None


_BASE_CACHE: dict = {}


def base_launch(python_exe: str):
    """(interpreter, site_dir) to launch. A venv python.exe on Windows is a launcher that
    starts the real interpreter as a CHILD (two processes, double the base memory). When
    `python_exe` sits in a venv, return the venv's base interpreter (pyvenv.cfg `home`) and
    the venv's site-packages for the worker to add; otherwise (python_exe, None)."""
    if python_exe in _BASE_CACHE:
        return _BASE_CACHE[python_exe]
    result = (python_exe, None)
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(python_exe)))
        cfg = os.path.join(root, "pyvenv.cfg")
        if os.path.isfile(cfg):
            home = ""
            with open(cfg, encoding="utf-8") as f:
                for line in f:
                    key, _, val = line.partition("=")
                    if key.strip().lower() == "home":
                        home = val.strip()
            names = ("python.exe",) if os.name == "nt" else ("python3", "python")
            base = next((os.path.join(home, n) for n in names if os.path.isfile(os.path.join(home, n))), None)
            if os.name == "nt":
                site = os.path.join(root, "Lib", "site-packages")
            else:
                lib = os.path.join(root, "lib")
                cands = [d for d in os.listdir(lib) if d.startswith("python")] if os.path.isdir(lib) else []
                site = os.path.join(lib, sorted(cands)[-1], "site-packages") if cands else ""
            if base and os.path.isdir(site):
                result = (base, site)
    except OSError as exc:
        logger.warning("[Workbench] base interpreter lookup failed for %s: %s", python_exe, exc)
    _BASE_CACHE[python_exe] = result
    return result


def _kill_tree(proc: "subprocess.Popen", tag: str) -> None:
    """Kill the process and its children, then reap it."""
    if proc.poll() is None:
        if os.name == "nt":
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=10, creationflags=_CREATE_NO_WINDOW)
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("[Workbench][%s] taskkill failed: %s", tag, exc)
        try:
            proc.kill()                      # posix kill, and a backstop on Windows
        except OSError as exc:
            logger.debug("[Workbench][%s] kill: %s", tag, exc)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        logger.error("[Workbench][%s] process %s did not exit after kill", tag, proc.pid)


class WorkbenchClient:
    def __init__(self, python_exe: str, workdir: str, env: Optional[dict] = None):
        self._python = python_exe
        self._workdir = workdir
        self._env = dict(env) if env is not None else None
        self._lock = threading.Lock()          # one request at a time
        self._proc: Optional[subprocess.Popen] = None
        self._q: "queue.Queue" = queue.Queue(maxsize=2)   # one pending reply + EOF
        self._reader: Optional[threading.Thread] = None
        self._errfile = None
        self._incarnation = ""
        self._next_id = 0
        self._psutil = None
        self._psutil_proc = None
        self.counts = {"restarts": 0, "stale_frames": 0, "queue_drops": 0, "bad_frames": 0,
                       "rss_cap_skipped": 0, "rss_errors": 0, "error_replies": 0}

    # --- state ---------------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def incarnation(self) -> str:
        return self._incarnation

    @property
    def busy(self) -> bool:
        """True while a request is in flight."""
        return self._lock.locked()

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None else None

    def _tag(self) -> str:
        return self._incarnation[:8] or "-"

    # --- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            self._spawn()

    def _spawn(self) -> None:
        self._q = queue.Queue(maxsize=2)
        self._errfile = tempfile.TemporaryFile("w+b")
        flags = _CREATE_NO_WINDOW if os.name == "nt" else 0
        env = self._env if self._env is not None else os.environ.copy()
        exe, site = base_launch(self._python)
        argv = [exe, "-I", "-X", "utf8", "-u", WORKER_PATH] + (["--site", site] if site else [])
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._errfile,
            cwd=self._workdir, env=env, creationflags=flags, close_fds=True,
        )
        self._psutil_proc = None
        proc, q = self._proc, self._q
        self._reader = threading.Thread(target=self._read_loop, args=(proc, q),
                                        name="wb-reader", daemon=True)
        self._reader.start()
        self._incarnation = ""
        rep = self._roundtrip({"v": PROTOCOL_VERSION, "op": "hello"}, OP_TIMEOUT_S, rss=False)
        if rep.get("ok") is False or rep.get("re") != "hello" or rep.get("version") != PROTOCOL_VERSION:
            tail = self._stderr_tail()
            self._teardown()
            raise ProtocolError(f"worker hello failed: {str(rep)[:300]} stderr={tail!r}")
        self._incarnation = rep["incarnation"]
        logger.info("[Workbench][%s] started pid=%s python=%s", self._tag(), proc.pid, self._python)

    def _read_loop(self, proc, q) -> None:
        try:
            for line in iter(proc.stdout.readline, b""):
                try:
                    q.put_nowait(line)
                except queue.Full:
                    self.counts["queue_drops"] += 1
                    logger.warning("[Workbench][%s] reply queue full; frame dropped", self._tag())
        except (OSError, ValueError) as exc:
            logger.debug("[Workbench][%s] reader ended: %s", self._tag(), exc)
        finally:
            try:
                q.put_nowait(None)               # EOF marker
            except queue.Full:
                pass                              # the waiter also polls proc.poll()

    def _stderr_tail(self) -> str:
        try:
            self._errfile.seek(0)
            return self._errfile.read()[-600:].decode("utf-8", "replace")
        except (OSError, ValueError):
            return ""

    def _teardown(self) -> None:
        proc = self._proc
        if proc is not None:
            _kill_tree(proc, self._tag())
            for f in (proc.stdin, proc.stdout):
                try:
                    if f:
                        f.close()
                except (OSError, ValueError):
                    pass
        if self._reader is not None:
            self._reader.join(timeout=5)
        if self._errfile is not None:
            try:
                self._errfile.close()
            except OSError:
                pass
        self._proc = None
        self._reader = None
        self._errfile = None

    def _restart(self, err_type: str, message: str) -> dict:
        """Hard-kill and start a fresh incarnation. Caller holds the lock."""
        old = self._tag()
        self.counts["restarts"] += 1
        logger.warning("[Workbench][%s] %s; restarting", old, err_type)
        self._teardown()
        try:
            self._spawn()
        except Exception as exc:                  # noqa: BLE001 - reported in the reply
            logger.error("[Workbench][%s] restart failed: %s", old, exc)
            return {"ok": False, "incarnation": "", "error": {
                "type": "WorkbenchUnavailable", "message": f"restart failed: {exc}", "trace_tail": ""}}
        return {"ok": False, "incarnation": self._incarnation,
                "error": {"type": err_type, "message": message, "trace_tail": ""}}

    def close(self) -> None:
        with self._lock:
            proc = self._proc
            if proc is None:
                return
            # No graceful shutdown frame: a worker that exits first would leave the
            # processes its code started behind; the tree kill takes them with it.
            self._teardown()
            logger.info("[Workbench][%s] closed", self._tag())

    # --- requests ------------------------------------------------------------
    def rss_bytes(self) -> Optional[int]:
        """RSS of the whole worker tree (process + all descendants); None when unknown."""
        if not self.alive or not self._load_psutil():
            return None
        ps = self._psutil
        try:
            if self._psutil_proc is None:
                self._psutil_proc = ps.Process(self._proc.pid)
            total = self._psutil_proc.memory_info().rss
            for child in self._psutil_proc.children(recursive=True):
                try:
                    total += child.memory_info().rss
                except ps.Error:
                    pass
            return total
        except ps.Error as exc:
            self.counts["rss_errors"] += 1
            logger.debug("[Workbench][%s] rss poll: %s", self._tag(), exc)
            return None

    def rss_mb(self) -> Optional[float]:
        b = self.rss_bytes()
        return None if b is None else b / (1 << 20)

    def _load_psutil(self) -> bool:
        if self._psutil is None:
            try:
                import psutil
                self._psutil = psutil
            except ImportError:
                self._psutil = False
                logger.warning("[Workbench][%s] psutil missing; RSS cap skipped", self._tag())
        return bool(self._psutil)

    def _rss_over_limit(self) -> bool:
        if not self._load_psutil():
            self.counts["rss_cap_skipped"] += 1
            return False
        total = self.rss_bytes()
        return total is not None and total > RSS_LIMIT_BYTES

    def _roundtrip(self, frame: dict, wait_s: float, rss: bool = True) -> dict:
        """Send one frame, wait up to wait_s. Returns the reply, or a {"_fail": kind} marker."""
        proc = self._proc
        try:
            proc.stdin.write(encode(frame))
            proc.stdin.flush()
        except (OSError, ValueError) as exc:
            logger.warning("[Workbench][%s] send failed: %s", self._tag(), exc)
            return {"_fail": "crash"}
        deadline = time.monotonic() + wait_s
        next_rss = time.monotonic() + RSS_POLL_S
        while True:
            try:
                line = self._q.get(timeout=0.1)
            except queue.Empty:
                line = b""
            if line is None:
                return {"_fail": "crash"}
            if line:
                try:
                    rep = decode(line)
                except ProtocolError as exc:
                    self.counts["bad_frames"] += 1
                    logger.warning("[Workbench][%s] bad reply frame: %s", self._tag(), exc)
                    continue
                if rep.get("re") == "error":      # the worker refused the frame; it still runs
                    return {"_fail": "error_reply", "error": rep["error"]}
                if "id" in frame and rep.get("id") != frame["id"]:
                    self.counts["stale_frames"] += 1
                    continue
                return rep
            if proc.poll() is not None:
                return {"_fail": "crash"}
            now = time.monotonic()
            if rss and now >= next_rss:
                next_rss = now + RSS_POLL_S
                if self._rss_over_limit():
                    return {"_fail": "memory"}
            if now > deadline:
                return {"_fail": "timeout"}

    def _request(self, frame: dict, wait_s: float) -> dict:
        with self._lock:
            if not self.alive:
                return {"ok": False, "incarnation": self._incarnation, "error": {
                    "type": "WorkbenchUnavailable", "message": "workbench is not running", "trace_tail": ""}}
            self._next_id += 1
            frame["id"] = self._next_id
            rep = self._roundtrip(frame, wait_s)
            fail = rep.get("_fail")
            if fail is None:
                return rep
            if fail == "error_reply":
                err = rep["error"]
                self.counts["error_replies"] += 1
                logger.warning("[Workbench][%s] worker error reply: %s", self._tag(), err.get("type"))
                return {"ok": False, "incarnation": self._incarnation, "error": {
                    "type": "WorkbenchErrorReply",
                    "message": f"{err.get('type')}: {err.get('message')}",
                    "trace_tail": err.get("trace_tail", "")}}
            if fail == "memory":
                return self._restart("WorkbenchMemoryLimit",
                                     "workbench exceeded 512 MB memory, restarted, variables lost")
            if fail == "timeout":
                return self._restart("WorkbenchRestarted", "workbench restarted, variables lost")
            return self._restart("WorkbenchCrashed", "workbench process ended, restarted, variables lost")

    def exec(self, code: str, timeout_s: float = 60) -> dict:
        return self._request({"v": PROTOCOL_VERSION, "op": "exec", "code": code,
                              "timeout_s": timeout_s}, timeout_s + HARD_KILL_GRACE_S)

    def inspect(self, expr: str, offset: int = 0, limit: int = 4000) -> dict:
        return self._request({"v": PROTOCOL_VERSION, "op": "inspect", "expr": expr,
                              "offset": offset, "limit": limit}, OP_TIMEOUT_S)

    def put(self, name: str, value) -> dict:
        return self._request({"v": PROTOCOL_VERSION, "op": "put", "name": name,
                              "value": value}, OP_TIMEOUT_S)
