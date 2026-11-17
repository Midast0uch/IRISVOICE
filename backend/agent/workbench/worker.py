"""Workbench child process (protocol v2). STDLIB ONLY.

Shipped as a data file and run by an arbitrary project Python:
    python -I -X utf8 -u worker.py
It must not import backend.*. Frames go to a PRIVATE duplicate of fd 1; fd 1/2 and
sys.stdout/sys.stderr point at capture buffers, so user prints never corrupt a frame.
"""
import ast
import builtins
import collections
import io
import ipaddress
import json
import os
import re
import sys
import tempfile
import threading
import time
import traceback
import types
import uuid
import _thread

PROTOCOL_VERSION = 2
SUPPORTED_VERSIONS = (1, 2)
CALLBACK_BUDGET = 24          # tools.<name>() calls per exec
CHECK_ERROR_CHARS = 200
OUTPUT_CAP = 256_000          # chars per stream
VALUE_CAP = 20_000            # chars of a final-expression repr
PREVIEW_CHARS = 80
MAX_VARS = 50                 # changed-variable entries per reply
TRACE_TAIL_CHARS = 1_500

INCARNATION = uuid.uuid4().hex
WORKDIR = os.path.realpath(os.getcwd())

_OUT_RING = collections.deque(maxlen=50)   # (n, stdout) of the last 50 execs, <= 256k chars each
_out_n = 0
_OUT_REF = re.compile(r"^out(\d+)$")


_HELPERS = frozenset({"tools", "ToolError", "sh"})
NS = {"__name__": "__main__", "__builtins__": builtins}


# --- callbacks: tools.<name>(**args) -> one `call` frame, block for its `result` ----
class ToolError(Exception):
    """A tools.<name>() call was denied, failed, or ran past the budget."""


_IO = {"rd": None, "wr": None}      # set by main(): the private frame pipes
_cb = {"id": None, "seq": 0}        # the running exec's id and its callback count


def _send_frame(frame):
    wr = _IO["wr"]
    wr.write(json.dumps(frame, ensure_ascii=True, separators=(",", ":"), default=str).encode("utf-8") + b"\n")
    wr.flush()


def _call_tool(name, args):
    global _wd_deadline
    if _cb["seq"] >= CALLBACK_BUDGET:
        raise ToolError(f"callback budget: at most {CALLBACK_BUDGET} tool calls per run_python call")
    _cb["seq"] += 1
    seq, eid = _cb["seq"], _cb["id"]
    with _wd_lock:                       # the parent's tool runs on ITS clock: pause ours
        left = None if _wd_deadline is None else max(0.0, _wd_deadline - time.monotonic())
        _wd_deadline = None
    try:
        _send_frame({"v": PROTOCOL_VERSION, "ev": "call", "id": eid, "seq": seq,
                     "tool": name, "args": args})
        while True:
            line = _IO["rd"].readline()
            if not line:
                raise ToolError("the parent closed the pipe")
            try:
                res = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if (isinstance(res, dict) and res.get("op") == "result"
                    and res.get("id") == eid and res.get("seq") == seq):
                break                    # any other frame here is stale: ignored
    finally:
        with _wd_lock:
            if left is not None:
                _wd_deadline = time.monotonic() + left
    if not res.get("ok"):
        raise ToolError(str(res.get("error") or f"{name} failed")[:2000])
    return res.get("value")


class _Tools:
    """`tools.<name>(**args)`; tools.call(name, args) for a name that is not an identifier."""

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda **args: _call_tool(name, args)

    def call(self, name, args=None):
        return _call_tool(name, dict(args or {}))


NS["tools"] = _Tools()
NS["ToolError"] = ToolError


# --- other languages: sh(command) runs any language's command from a script ---------
# Owner (2026-11-16): "i want the agent to able perform all coding languages inside the
# workbench especially javascript". One Python namespace stays the medium; node / npm /
# npx / ruby / go / ... run as child processes in the project folder and their output
# comes back as a value the script can parse.
SH_OUT_CAP = 200_000          # chars kept per stream: the namespace holds data, bounded
SH_KILL_MARGIN_S = 1.5       # sh() returns this long before the run's deadline (tree-kill time)


def _kill_tree(p):
    """End a child and everything it started (npm -> node; a shell -> its command)."""
    try:
        if os.name == "nt":
            import subprocess
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            os.killpg(p.pid, 9)
    except Exception:  # noqa: BLE001 - the child may be gone already
        pass
    try:
        p.kill()
    except Exception:  # noqa: BLE001
        pass


def sh(command, input=None, timeout=120):
    """Run a command of ANY language in the project folder: sh('node app.js'),
    sh('npm test'), sh('node -', input=js_code), sh(['go', 'run', '.']). A string goes
    through the shell (npm / npx resolve on Windows); a list does not. Returns
    {"code", "stdout", "stderr", "timed_out"} and never raises for a non-zero exit.
    Bounded by `timeout` AND by this run's own deadline (it returns before the run is
    stopped); on a timeout the whole process tree is killed."""
    import subprocess

    global _wd_deadline
    with _wd_lock:
        left = None if _wd_deadline is None else _wd_deadline - time.monotonic()
    # Stop SH_KILL_MARGIN_S before the run's deadline: the tree kill (taskkill /T) needs time,
    # and under load it took longer than the old 0.3 s - the watchdog then interrupted the
    # cleanup and the client restarted the worker (test_the_runs_own_deadline_bounds_sh was
    # flaky with WorkbenchRestarted, 2026-11-17).
    limit = float(timeout) if left is None else max(0.1, min(float(timeout), left - SH_KILL_MARGIN_S))
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    # stdin is never the worker's own: that pipe carries the protocol frames
    p = subprocess.Popen(command, shell=isinstance(command, str), cwd=WORKDIR,
                         stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, **group)
    data = input.encode("utf-8") if isinstance(input, str) else input
    timed_out = False
    try:
        out, err = p.communicate(data, timeout=limit)
    except subprocess.TimeoutExpired:
        timed_out = True
        with _wd_lock:                   # the cleanup runs on no run clock (like a callback)
            _left = None if _wd_deadline is None else max(0.0, _wd_deadline - time.monotonic())
            _wd_deadline = None
        try:
            _kill_tree(p)
            try:
                out, err = p.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                out, err = b"", b""
        finally:
            with _wd_lock:
                if _left is not None:
                    _wd_deadline = time.monotonic() + _left
    except BaseException:            # the run was stopped: never leave the child behind
        _kill_tree(p)
        raise

    def _text(b):
        return (b or b"").decode("utf-8", "replace")[:SH_OUT_CAP]

    return {"code": p.returncode, "stdout": _text(out), "stderr": _text(err),
            "timed_out": timed_out}


NS["sh"] = sh


class _Cap(io.TextIOBase):
    """Python-level stream capture with a hard char cap."""

    def __init__(self):
        self.parts, self.size, self.truncated = [], 0, False

    def writable(self):
        return True

    def write(self, s):
        n = len(s)
        room = OUTPUT_CAP - self.size
        if room <= 0:
            self.truncated = True
        else:
            if n > room:
                s, self.truncated = s[:room], True
            self.parts.append(s)
            self.size += len(s)
        return n

    def flush(self):
        pass

    def take(self):
        text, trunc = "".join(self.parts), self.truncated
        self.parts, self.size, self.truncated = [], 0, False
        return text, trunc


# --- exec state: soft-stop watchdog -----------------------------------------
_wd_lock = threading.Lock()
_wd_deadline = None           # monotonic time, or None when no exec is running
_wd_fired = False


def _watchdog():
    global _wd_deadline, _wd_fired
    while True:
        time.sleep(0.05)
        with _wd_lock:
            if _wd_deadline is not None and time.monotonic() > _wd_deadline:
                _wd_deadline = None
                _wd_fired = True
                _thread.interrupt_main()


# --- network refusal (personal mode, confined worker only) ---------------------------------
# Loopback and private networks hold the owner's own services (IRIS backend, dev servers, a
# router): a confined script reaches the web through tools.browser_open, never through them.
_REFUSED_NETS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "fc00::/7", "fe80::/10", "0.0.0.0/32", "::/128"))


def _refused_address(host):
    """Why a connect to `host` (an address string or a host name) is refused, or None.
    An address is judged as it is; "localhost" is refused by name; any other name is resolved
    and refused when ANY of its addresses is loopback or private. A name that does not resolve
    is allowed (the connect fails by itself)."""
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return None
    name = host.strip().strip("[]").split("%", 1)[0].lower()
    if name == "":
        return "an empty address (this machine)"
    try:
        addrs = [ipaddress.ip_address(name)]
    except ValueError:
        if name == "localhost" or name.endswith(".localhost"):
            return "loopback"
        try:
            import socket
            infos = socket.getaddrinfo(name, None)
        except Exception:
            return None
        addrs = []
        for info in infos:
            try:
                addrs.append(ipaddress.ip_address(info[4][0].split("%", 1)[0]))
            except ValueError:
                continue
    for a in addrs:
        a = getattr(a, "ipv4_mapped", None) or a         # ::ffff:127.0.0.1 is 127.0.0.1
        if any(a in net for net in _REFUSED_NETS if net.version == a.version):
            return "loopback" if a.is_loopback else "a private network"
    return None


def _install_audit_hook(confined=False):
    """Refuse writes / removals outside the project folder and the temp folder. With `confined`
    (personal mode on Windows) also refuse socket connects to loopback and private networks:
    events hooked are `socket.connect` and `socket.sendto` (their address argument; a host NAME
    is resolved here, a name that resolves to a refused address is refused). Public addresses stay
    allowed. NOT covered: child processes (sh, subprocess, node) open their own sockets; a
    firewall rule or an AppContainer would cover those later."""
    allowed = [os.path.normcase(WORKDIR), os.path.normcase(os.path.realpath(tempfile.gettempdir()))]
    write_flags = (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC)
    devnull = os.path.normcase(os.devnull)

    # the null device under every spelling: realpath() turns "nul" into "\\.\nul" on
    # Windows, so the old check refused os.devnull (subprocess.DEVNULL, 2026-11-16)
    null_names = {devnull, "nul", os.path.normcase("\\\\.\\nul"), "/dev/null"}

    def inside(path):
        try:
            if os.path.normcase(os.fsdecode(path)) in null_names:
                return True
        except (TypeError, ValueError):
            pass
        p = os.path.normcase(os.path.realpath(os.path.abspath(path)))
        if p in null_names:
            return True
        for root in allowed:
            try:
                if os.path.commonpath([p, root]) == root:
                    return True
            except ValueError:  # different drives
                continue
        return False

    # Events that remove, move or replace a path: every path argument must be
    # inside the allowed roots (a rename checks its source AND its target).
    path_events = {
        "os.remove": (0,), "os.rmdir": (0,), "shutil.rmtree": (0,),
        "os.rename": (0, 1), "shutil.move": (0, 1),
    }

    def refuse(path, what):
        raise PermissionError(
            f"workbench: {what} {os.fsdecode(path)!r} is refused; "
            f"changes are allowed only under {WORKDIR!r} and the temp folder")

    def hook(event, args):
        if confined and event in ("socket.connect", "socket.sendto"):
            addr = args[1]
            if isinstance(addr, tuple) and addr:
                why = _refused_address(addr[0])
                if why is not None:
                    raise PermissionError(f"workbench: network address {addr[0]} is refused; "
                                          "use tools.browser_open for the web")
            return
        if event in path_events:
            for i in path_events[event]:
                path = args[i]
                if isinstance(path, int):
                    continue
                try:
                    ok = inside(os.fsdecode(path))
                except Exception:
                    ok = False
                if not ok:
                    refuse(path, event)
            return
        if event != "open":
            return
        path, mode, flags = args[0], args[1], args[2]
        if isinstance(path, int):
            return
        writing = bool(mode and any(c in str(mode) for c in "wax+"))
        if isinstance(flags, int) and flags & write_flags:
            writing = True
        if not writing:
            return
        try:
            ok = inside(os.fsdecode(path))
        except Exception:
            ok = False
        if not ok:
            refuse(path, "writing")

    sys.addaudithook(hook)


# --- variable manifest -------------------------------------------------------
def _size_of(obj):
    try:
        return len(obj)
    except Exception:
        return None


def _fingerprint():
    out = {}
    for name, obj in list(NS.items()):
        if name.startswith("__") or name in _HELPERS or isinstance(obj, types.ModuleType):
            continue
        out[name] = (id(obj), type(obj), _size_of(obj))
    return out


# A BOUNDED repr for the changed-variable previews (2026-11-16): repr() of the WHOLE value
# ran after every script - a 300 MB bytes value briefly took a second 300 MB copy (peak
# 611 MB measured), tripped the 512 MB cap and restarted the workbench, all to show 80
# chars. Strings / bytes are sliced before repr; containers go through reprlib limits.
import reprlib as _reprlib

_REPR = _reprlib.Repr()
_REPR.maxstring = _REPR.maxother = PREVIEW_CHARS
_REPR.maxlist = _REPR.maxtuple = _REPR.maxset = _REPR.maxfrozenset = 40
_REPR.maxdeque = _REPR.maxarray = 40
_REPR.maxdict, _REPR.maxlong, _REPR.maxlevel = 20, 60, 3
_SLICEABLE = (str, bytes, bytearray)


def _preview(obj):
    try:
        if isinstance(obj, _SLICEABLE) and len(obj) > PREVIEW_CHARS:
            text = repr(obj[:PREVIEW_CHARS])
        elif isinstance(obj, memoryview) and obj.nbytes > PREVIEW_CHARS:
            text = repr(bytes(obj[:PREVIEW_CHARS]))
        else:
            text = _REPR.repr(obj)
    except Exception as exc:
        text = f"<repr failed: {type(exc).__name__}>"
    text = text.replace("\n", " ")
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS - 3] + "..."


def _changed_vars(before):
    after = _fingerprint()
    rows = []
    for name, fp in after.items():
        if before.get(name) != fp:
            obj = NS[name]
            rows.append({"name": name, "type": type(obj).__name__,
                         "size": _size_of(obj), "preview": _preview(obj)})
    return rows[:MAX_VARS]


# --- ops ---------------------------------------------------------------------
class _Capture:
    """fd-level capture files (for child processes / C writes) plus Python streams."""

    def __init__(self):
        self.out_file = tempfile.TemporaryFile("w+b")
        self.err_file = tempfile.TemporaryFile("w+b")
        self.py_out, self.py_err = _Cap(), _Cap()

    def install(self):
        os.dup2(self.out_file.fileno(), 1)
        os.dup2(self.err_file.fileno(), 2)
        sys.stdout, sys.stderr = self.py_out, self.py_err

    def _drain(self, f, py):
        text, trunc = py.take()
        f.flush()
        size = f.seek(0, os.SEEK_END)
        f.seek(0)
        raw = f.read(OUTPUT_CAP * 4)
        f.seek(0)
        f.truncate()
        if size > OUTPUT_CAP * 4:
            trunc = True
        text += raw.decode("utf-8", errors="replace")
        if len(text) > OUTPUT_CAP:
            text, trunc = text[:OUTPUT_CAP], True
        return text, trunc

    def drain(self):
        o, ot = self._drain(self.out_file, self.py_out)
        e, et = self._drain(self.err_file, self.py_err)
        return o, e, (ot or et)


def _error(exc):
    tb = exc.__traceback__
    if tb is not None and tb.tb_next is not None:
        tb = tb.tb_next                      # drop this worker's own frame
    text = "".join(traceback.format_exception(type(exc), exc, tb))
    return {"type": type(exc).__name__, "message": str(exc)[:2000],
            "trace_tail": text[-TRACE_TAIL_CHARS:]}


def op_exec(req, cap):
    global _wd_deadline, _wd_fired
    code, timeout_s = req["code"], float(req["timeout_s"])
    check = req.get("check")
    check_out = None
    _cb["id"], _cb["seq"] = req["id"], 0
    start = time.monotonic()
    before = _fingerprint()
    value, error = None, None
    try:
        tree = ast.parse(code, "<workbench>", "exec")
        last = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last = ast.Expression(tree.body.pop().value)
        body = compile(tree, "<workbench>", "exec")
        tail = compile(last, "<workbench>", "eval") if last is not None else None
    except BaseException as exc:             # SyntaxError, ValueError (null bytes)
        body = tail = None
        error = _error(exc)
    if error is None:
        with _wd_lock:
            _wd_fired = False
            _wd_deadline = time.monotonic() + timeout_s
        body_ok = False
        try:
            exec(body, NS)
            if tail is not None:
                res = eval(tail, NS)
                if res is not None:
                    value = repr(res)[:VALUE_CAP]
            body_ok = True
            if isinstance(check, str) and check.strip():
                # same namespace, same watchdog; a failing or raising check is a RESULT
                try:
                    check_out = {"ok": bool(eval(compile(check, "<check>", "eval"), NS)), "error": None}
                except Exception as exc:
                    check_out = {"ok": False,
                                 "error": f"{type(exc).__name__}: {exc}"[:CHECK_ERROR_CHARS]}
        except KeyboardInterrupt as exc:
            error = _error(exc)
            if body_ok:
                check_out = {"ok": False, "error": "check timed out"}
            if _wd_fired:
                error["message"] = f"execution exceeded timeout_s={timeout_s:g}; stopped, variables kept"
        except BaseException as exc:         # incl. SystemExit: the namespace must survive
            error = _error(exc)
        finally:
            with _wd_lock:
                _wd_deadline = None
        # An interrupt fired just as the code finished may still be pending.
        try:
            time.sleep(0)
        except KeyboardInterrupt:
            pass
    if check_out is None and isinstance(check, str) and check.strip():
        check_out = {"ok": False, "error": "body raised"}   # raised, timed out or never compiled: no check
    stdout, stderr, truncated = cap.drain()
    global _out_n
    _out_n += 1
    if stdout:
        _OUT_RING.append((_out_n, stdout))
    reply = {"v": PROTOCOL_VERSION, "re": "exec", "id": req["id"], "ok": error is None,
             "stdout": stdout, "stderr": stderr, "value": value, "error": error,
             "vars": _changed_vars(before),
             "wall_ms": int((time.monotonic() - start) * 1000),
             "truncated": truncated, "out_n": _out_n, "incarnation": INCARNATION}
    if check_out is not None:
        reply["check"] = check_out
    return reply


def op_inspect(req):
    try:
        m = _OUT_REF.match(req["expr"].strip())
        if m:                                  # out<n>: the full stdout of execution n
            hit = [t for n, t in _OUT_RING if n == int(m.group(1))]
            if not hit:
                raise KeyError(f"{req['expr'].strip()} is not kept (only the last {_OUT_RING.maxlen} outputs with text)")
            res = hit[0]
        else:
            res = eval(compile(req["expr"], "<inspect>", "eval"), NS)
        text = res if isinstance(res, str) else repr(res)
    except BaseException as exc:
        return {"v": PROTOCOL_VERSION, "re": "inspect", "id": req["id"], "ok": False,
                "text": "", "total": 0, "error": _error(exc), "incarnation": INCARNATION}
    off, lim = max(0, int(req["offset"])), max(0, int(req["limit"]))
    return {"v": PROTOCOL_VERSION, "re": "inspect", "id": req["id"], "ok": True,
            "text": text[off:off + lim], "total": len(text), "error": None,
            "incarnation": INCARNATION}


def op_put(req):
    name = req["name"]
    if not isinstance(name, str) or not name.isidentifier() or name.startswith("__") or name in _HELPERS:
        err = {"type": "ValueError", "message": f"bad variable name {name!r}", "trace_tail": ""}
        return {"v": PROTOCOL_VERSION, "re": "put", "id": req["id"], "ok": False,
                "error": err, "incarnation": INCARNATION}
    NS[name] = req["value"]
    return {"v": PROTOCOL_VERSION, "re": "put", "id": req["id"], "ok": True,
            "error": None, "incarnation": INCARNATION}


def _validate(req):
    if not isinstance(req, dict) or req.get("v") not in SUPPORTED_VERSIONS:
        raise ValueError("bad or mismatched frame version")
    need = {"hello": (), "exec": ("id", "code", "timeout_s"), "inspect": ("id", "expr", "offset", "limit"),
            "put": ("id", "name", "value"), "shutdown": (),
            "result": ("id", "seq", "ok", "value", "error")}.get(req.get("op"))
    if need is None:
        raise ValueError(f"unknown op {req.get('op')!r}")
    for k in need:
        if k not in req:
            raise ValueError(f"missing key {k!r}")


# --- OS confinement (personal mode): lower this process to LOW integrity ----------------
# The parent sets IRIS_WB_CONFINE=1 for a personal-mode worker. Windows Mandatory Integrity
# Control then refuses every write to an object labelled Medium or higher (the user's
# folders, the IRIS repo) - for this process AND every child it starts (sh(), subprocess,
# npm, ctypes), because a child inherits the token. The parent labelled the project folder
# Low, so that folder stays writable. A process may lower its own level, never raise it.
CONFINE_ENV = "IRIS_WB_CONFINE"
CONFINE_FAIL_MARK = "workbench_confine_failed"
CONFINE_EXIT = 87
LOW_SID = "S-1-16-4096"
_CONFINED = False


def _lower_integrity():
    """Set this process token to Low integrity and read it back. Raises on any failure."""
    if os.name != "nt":
        raise OSError("OS confinement is Windows-only")
    import ctypes
    import ctypes.wintypes as wt

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32.GetCurrentProcess.restype = wt.HANDLE
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    adv.GetLengthSid.argtypes = [ctypes.c_void_p]
    adv.GetLengthSid.restype = wt.DWORD
    adv.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    adv.ConvertStringSidToSidW.argtypes = [wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    adv.SetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    adv.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
                                        ctypes.POINTER(wt.DWORD)]
    adv.OpenProcessToken.restype = adv.ConvertStringSidToSidW.restype = wt.BOOL
    adv.ConvertSidToStringSidW.restype = adv.SetTokenInformation.restype = wt.BOOL
    adv.GetTokenInformation.restype = wt.BOOL

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]

    TOKEN_ADJUST_DEFAULT, TOKEN_QUERY, TOKEN_INTEGRITY_LEVEL, SE_GROUP_INTEGRITY = 0x80, 0x08, 25, 0x20
    tok, sid = wt.HANDLE(), ctypes.c_void_p()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_ADJUST_DEFAULT | TOKEN_QUERY, ctypes.byref(tok)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not adv.ConvertStringSidToSidW(LOW_SID, ctypes.byref(sid)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            label = SidAndAttributes(sid, SE_GROUP_INTEGRITY)
            if not adv.SetTokenInformation(tok, TOKEN_INTEGRITY_LEVEL, ctypes.byref(label),
                                       ctypes.sizeof(label) + adv.GetLengthSid(sid)):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            k32.LocalFree(sid)
        need = wt.DWORD(0)
        adv.GetTokenInformation(tok, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(need))
        buf = ctypes.create_string_buffer(need.value or 64)
        if not adv.GetTokenInformation(tok, TOKEN_INTEGRITY_LEVEL, buf, len(buf), ctypes.byref(need)):
            raise ctypes.WinError(ctypes.get_last_error())
        text = ctypes.c_wchar_p()
        if not adv.ConvertSidToStringSidW(SidAndAttributes.from_buffer(buf).Sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        got = text.value
        k32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        if got != LOW_SID:
            raise OSError(f"token integrity is {got}, expected {LOW_SID}")
    finally:
        k32.CloseHandle(tok)


def main():
    global _CONFINED
    if os.environ.get(CONFINE_ENV) == "1":      # before any user code, any import of project code
        try:
            _lower_integrity()
            _CONFINED = True
        except BaseException as exc:            # fail closed: never run unconfined when asked to
            sys.stderr.write(f"{CONFINE_FAIL_MARK}: {type(exc).__name__}: {exc}\n")
            sys.stderr.flush()
            return CONFINE_EXIT
    if "--site" in sys.argv:             # the project venv's site-packages (see client.py)
        import site
        site.addsitedir(sys.argv[sys.argv.index("--site") + 1])
    # `python -I` leaves the project folder off sys.path; APPEND it (never insert) so the
    # standard library still wins over a project file named like a stdlib module.
    if WORKDIR not in sys.path:
        sys.path.append(WORKDIR)
    rd = os.fdopen(os.dup(0), "rb")
    wr = os.fdopen(os.dup(1), "wb")
    _IO["rd"], _IO["wr"] = rd, wr
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)                       # user code never reads the frame pipe
    cap = _Capture()
    cap.install()
    _install_audit_hook(confined=_CONFINED)
    threading.Thread(target=_watchdog, name="wb-watchdog", daemon=True).start()

    def send(frame):
        wr.write(json.dumps(frame, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n")
        wr.flush()

    while True:
        try:
            line = rd.readline()
        except KeyboardInterrupt:             # a late soft-stop landing between execs
            continue
        if not line:
            return 0                          # stdin EOF
        try:
            req = json.loads(line.decode("utf-8"))
            _validate(req)
            op = req["op"]
            if op == "hello":
                send({"v": PROTOCOL_VERSION, "re": "hello", "ok": True,
                      "version": PROTOCOL_VERSION, "incarnation": INCARNATION,
                      "confined": _CONFINED})
            elif op == "exec":
                send(op_exec(req, cap))
            elif op == "inspect":
                send(op_inspect(req))
            elif op == "put":
                send(op_put(req))
            elif op == "result":
                continue                      # a late answer to a call that is over: ignored
            else:
                send({"v": PROTOCOL_VERSION, "re": "shutdown", "ok": True})
                return 0
        except KeyboardInterrupt:
            continue
        except BaseException as exc:          # a bad frame must not end the worker
            try:
                send({"v": PROTOCOL_VERSION, "re": "error", "ok": False, "error": _error(exc)})
            except BaseException:
                pass


if __name__ == "__main__":
    sys.exit(main())
