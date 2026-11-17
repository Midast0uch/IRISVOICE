"""Workbench parent side: spawn the worker, send one request at a time, bound every wait.

Stdlib only (psutil is imported lazily for the RSS cap). One client owns one child
process; a hard kill starts a fresh incarnation (variables are lost, and the reply says so).
"""
import json
import logging
import os
import queue
import shutil
import subprocess
import tempfile
import sys
import threading
import time
import uuid
from typing import Callable, Optional, Tuple

from .protocol import PROTOCOL_VERSION, ProtocolError, decode, encode

logger = logging.getLogger(__name__)

WORKER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.py")
HARD_KILL_GRACE_S = 3.0        # after the soft stop, before the process is killed
RSS_LIMIT_BYTES = 512 << 20    # 512 MB, over the whole process tree
RSS_POLL_S = 0.25
OP_TIMEOUT_S = 30.0            # hello / inspect / put
RESULT_FRAME_MAX = 2_000_000   # bytes of one callback result sent back to the worker
_CREATE_NO_WINDOW = 0x08000000
CONFINE_ENV = "IRIS_WB_CONFINE"            # worker.py reads it and lowers its own token
# A dead proxy (port 9, "discard", nothing listens) for the worker's child processes.
_DEAD_PROXY = "http://127.0.0.1:9"
NO_NET_ENV = {
    "HTTP_PROXY": _DEAD_PROXY, "HTTPS_PROXY": _DEAD_PROXY, "ALL_PROXY": _DEAD_PROXY,
    "http_proxy": _DEAD_PROXY, "https_proxy": _DEAD_PROXY, "all_proxy": _DEAD_PROXY,
    "NO_PROXY": "", "no_proxy": "",
    "npm_config_proxy": _DEAD_PROXY, "npm_config_https_proxy": _DEAD_PROXY,
    "npm_config_offline": "true", "PIP_NO_INDEX": "1",
}
CONFINE_FAIL_MARK = "workbench_confine_failed"   # what a worker prints to stderr when it cannot
ICACLS_TIMEOUT_S = 120.0       # one label pass; ~3 s measured for a folder of 20,000 files


class ConfineFailed(ProtocolError):
    """Personal mode could not confine the worker (label, temp folder or token lowering).
    The manager turns it into the named case `workbench_confine_failed`."""


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


def low_root() -> str:
    """The Low-integrity folder of the confined workers: <profile>/AppData/LocalLow/iris-workbench."""
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(home, "AppData", "LocalLow", "iris-workbench")


_LABELED: set = set()
_LABEL_LOCK = threading.Lock()


def label_low(path: str) -> None:
    """Mark `path` writable for Low-integrity processes: an inheritable Low mandatory label
    ((OI)(CI)L). icacls applies it to the files and folders already inside too (measured:
    20,000 files in ~3 s), and new files inherit it. Once per path per process. The label
    stays on the folder; nothing here removes it. Raises ConfineFailed."""
    key = os.path.normcase(os.path.realpath(path))
    with _LABEL_LOCK:
        if key in _LABELED:
            return
        try:
            r = subprocess.run(["icacls", path, "/setintegritylevel", "(OI)(CI)L"], capture_output=True,
                               text=True, timeout=ICACLS_TIMEOUT_S, creationflags=_CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConfineFailed(f"could not label {path!r} for the workbench: {exc}") from exc
        if r.returncode != 0:
            raise ConfineFailed(f"could not label {path!r} for the workbench: "
                                f"icacls exit {r.returncode}: {(r.stdout + r.stderr).strip()[:300]}")
        _LABELED.add(key)
        logger.info("[Workbench] labelled %s Low-integrity (writable by the confined worker)", path)


def confine_env(env: dict) -> Tuple[dict, str]:
    """(env for a confined worker, its private temp folder). TEMP / TMP and npm's cache and prefix
    point into the Low-integrity folder, since a Low process cannot write the normal ones (the
    prefix also keeps npm.cmd from walking %APPDATA%, which a Low process cannot read).
    Raises ConfineFailed."""
    root = low_root()
    tmp = os.path.join(root, uuid.uuid4().hex[:8])
    try:
        os.makedirs(tmp, exist_ok=True)
        label_low(root)
    except OSError as exc:
        raise ConfineFailed(f"could not create the workbench temp folder {tmp!r}: {exc}") from exc
    out = dict(env)
    out.update({CONFINE_ENV: "1", "TEMP": tmp, "TMP": tmp,
                "npm_config_cache": os.path.join(root, "npm-cache"),
                "npm_config_prefix": os.path.join(root, "npm-prefix")})
    return out, tmp


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
    def __init__(self, python_exe: str, workdir: str, env: Optional[dict] = None, confine: bool = False):
        # confine: personal mode on Windows - the worker lowers itself to Low integrity (the
        # manager has labelled `workdir` Low first). A worker that does not say so is refused.
        self._python = python_exe
        self._workdir = workdir
        self._confine = confine
        self._confined = False
        self._tmp = ""
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
    def confined(self) -> bool:
        """True when the live worker reported itself at Low integrity."""
        return self._confined

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
        env = dict(self._env) if self._env is not None else os.environ.copy()
        # Owner 2026-11-17: scripts reach the web only through the app's browser tools. The
        # worker's audit hook refuses Python sockets; CHILD processes (sh / subprocess: curl,
        # npm, pip, python) inherit these dead proxies, which most tools obey. A child that
        # ignores proxy variables is NOT covered - that needs a firewall rule / AppContainer.
        env.update(NO_NET_ENV)
        self._confined = False
        if self._confine:
            env, self._tmp = confine_env(env)
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
            if CONFINE_FAIL_MARK in tail:
                raise ConfineFailed(f"the worker could not lower itself to Low integrity: {tail.strip()[-300:]}")
            raise ProtocolError(f"worker hello failed: {str(rep)[:300]} stderr={tail!r}")
        if self._confine and rep.get("confined") is not True:     # fail closed: never run unconfined
            self._teardown()
            raise ConfineFailed("the worker did not report itself confined")
        self._confined = bool(rep.get("confined"))
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
        if self._tmp:                       # the confined worker's private temp folder
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = ""

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
    @staticmethod
    def _held(mi) -> int:
        """Memory a process HOLDS. Windows: private bytes - the working set (`rss`) is what
        Windows keeps in RAM and it trims an idle process: measured 2026-11-16, a worker
        holding a 300 MB value read rss 1 MB / private 318 MB after a trim, so the caps and
        the "workbench holds" warning missed it exactly under memory pressure. Elsewhere
        rss (no `private` field)."""
        private = getattr(mi, "private", None)
        return int(private) if private else int(mi.rss)

    def rss_bytes(self) -> Optional[int]:
        """Memory held by the whole worker tree (process + all descendants; private bytes
        on Windows, RSS elsewhere - see _held); None when unknown."""
        if not self.alive or not self._load_psutil():
            return None
        ps = self._psutil
        try:
            if self._psutil_proc is None:
                self._psutil_proc = ps.Process(self._proc.pid)
            total = self._held(self._psutil_proc.memory_info())
            for child in self._psutil_proc.children(recursive=True):
                try:
                    total += self._held(child.memory_info())
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

    def _answer_call(self, call: dict, on_call) -> None:
        """Run the handler for one worker `call` frame and send the `result` frame."""
        if on_call is None:
            ok, value, error = False, None, "tools are not available here"
        else:
            try:
                ok, value, error = on_call(str(call["tool"]), call.get("args") or {})
            except Exception as exc:  # noqa: BLE001 - the script sees a ToolError
                logger.warning("[Workbench][%s] callback handler failed: %r", self._tag(), exc)
                ok, value, error = False, None, f"{type(exc).__name__}: {exc}"[:300]
        frame = {"v": PROTOCOL_VERSION, "op": "result", "id": call["id"], "seq": call["seq"],
                 "ok": bool(ok), "value": value if ok else None, "error": None if ok else str(error or "failed")}
        try:
            data = json.dumps(frame, ensure_ascii=True, separators=(",", ":"), default=str).encode("utf-8") + b"\n"
            if len(data) > RESULT_FRAME_MAX:
                frame.update(ok=False, value=None, error="tool result too large for the workbench")
                data = encode(frame)
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            logger.warning("[Workbench][%s] result send failed: %s", self._tag(), exc)

    def _roundtrip(self, frame: dict, wait_s: float, rss: bool = True, on_call=None) -> dict:
        """Send one frame, wait up to wait_s. Returns the reply, or a {"_fail": kind} marker.
        A worker `call` frame of THIS request is answered through `on_call`; the wait
        deadline is paused while the handler runs."""
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
                if rep.get("ev") == "call":
                    if "id" in frame and rep.get("id") == frame["id"]:
                        t0 = time.monotonic()
                        self._answer_call(rep, on_call)
                        deadline += time.monotonic() - t0
                    else:
                        self.counts["stale_frames"] += 1     # a call of another exec: ignored
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

    def _request(self, frame: dict, wait_s: float, on_call=None) -> dict:
        with self._lock:
            if not self.alive:
                return {"ok": False, "incarnation": self._incarnation, "error": {
                    "type": "WorkbenchUnavailable", "message": "workbench is not running", "trace_tail": ""}}
            self._next_id += 1
            frame["id"] = self._next_id
            rep = self._roundtrip(frame, wait_s, on_call=on_call)
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

    def exec(self, code: str, timeout_s: float = 60, check: Optional[str] = None,
             on_call: Optional[Callable[[str, dict], Tuple[bool, object, Optional[str]]]] = None) -> dict:
        """Run `code`. `check` (a Python expression) is evaluated after a clean run; the
        reply then carries "check". `on_call(tool, args) -> (ok, value, error)` answers
        tools.<name>() calls from the script; the lock is held for the whole exec."""
        frame = {"v": PROTOCOL_VERSION, "op": "exec", "code": code, "timeout_s": timeout_s}
        if check:
            frame["check"] = check
        return self._request(frame, timeout_s + HARD_KILL_GRACE_S, on_call=on_call)

    def inspect(self, expr: str, offset: int = 0, limit: int = 4000) -> dict:
        return self._request({"v": PROTOCOL_VERSION, "op": "inspect", "expr": expr,
                              "offset": offset, "limit": limit}, OP_TIMEOUT_S)

    def put(self, name: str, value) -> dict:
        return self._request({"v": PROTOCOL_VERSION, "op": "put", "name": name,
                              "value": value}, OP_TIMEOUT_S)
