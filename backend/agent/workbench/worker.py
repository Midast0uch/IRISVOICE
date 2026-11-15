"""Workbench child process (protocol v1). STDLIB ONLY.

Shipped as a data file and run by an arbitrary project Python:
    python -I -X utf8 -u worker.py
It must not import backend.*. Frames go to a PRIVATE duplicate of fd 1; fd 1/2 and
sys.stdout/sys.stderr point at capture buffers, so user prints never corrupt a frame.
"""
import ast
import builtins
import io
import json
import os
import sys
import tempfile
import threading
import time
import traceback
import types
import uuid
import _thread

PROTOCOL_VERSION = 1
OUTPUT_CAP = 256_000          # chars per stream
VALUE_CAP = 20_000            # chars of a final-expression repr
PREVIEW_CHARS = 80
MAX_VARS = 50                 # changed-variable entries per reply
TRACE_TAIL_CHARS = 1_500

INCARNATION = uuid.uuid4().hex
WORKDIR = os.path.realpath(os.getcwd())

_kept = []


def keep(name, note=""):
    """Mark a variable as worth remembering. Only records {name, note}."""
    _kept.append({"name": str(name), "note": str(note)})


_HELPERS = frozenset({"keep"})
NS = {"__name__": "__main__", "__builtins__": builtins, "keep": keep}


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


def _install_audit_hook():
    allowed = [os.path.normcase(WORKDIR), os.path.normcase(os.path.realpath(tempfile.gettempdir()))]
    write_flags = (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC)
    devnull = os.path.normcase(os.devnull)

    def inside(path):
        p = os.path.normcase(os.path.realpath(os.path.abspath(path)))
        if p == devnull or p == "nul":
            return True
        for root in allowed:
            try:
                if os.path.commonpath([p, root]) == root:
                    return True
            except ValueError:  # different drives
                continue
        return False

    def hook(event, args):
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
            raise PermissionError(
                f"workbench: writing {os.fsdecode(path)!r} is refused; "
                f"writes are allowed only under {WORKDIR!r} and the temp folder")

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


def _preview(obj):
    try:
        text = repr(obj)
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
    start = time.monotonic()
    del _kept[:]
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
        try:
            exec(body, NS)
            if tail is not None:
                res = eval(tail, NS)
                if res is not None:
                    value = repr(res)[:VALUE_CAP]
        except KeyboardInterrupt as exc:
            error = _error(exc)
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
    stdout, stderr, truncated = cap.drain()
    return {"v": PROTOCOL_VERSION, "re": "exec", "id": req["id"], "ok": error is None,
            "stdout": stdout, "stderr": stderr, "value": value, "error": error,
            "vars": _changed_vars(before), "kept": list(_kept),
            "wall_ms": int((time.monotonic() - start) * 1000),
            "truncated": truncated, "incarnation": INCARNATION}


def op_inspect(req):
    try:
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
    if not isinstance(req, dict) or req.get("v") != PROTOCOL_VERSION:
        raise ValueError("bad or mismatched frame version")
    need = {"hello": (), "exec": ("id", "code", "timeout_s"), "inspect": ("id", "expr", "offset", "limit"),
            "put": ("id", "name", "value"), "shutdown": ()}.get(req.get("op"))
    if need is None:
        raise ValueError(f"unknown op {req.get('op')!r}")
    for k in need:
        if k not in req:
            raise ValueError(f"missing key {k!r}")


def main():
    rd = os.fdopen(os.dup(0), "rb")
    wr = os.fdopen(os.dup(1), "wb")
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)                       # user code never reads the frame pipe
    cap = _Capture()
    cap.install()
    _install_audit_hook()
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
                      "version": PROTOCOL_VERSION, "incarnation": INCARNATION})
            elif op == "exec":
                send(op_exec(req, cap))
            elif op == "inspect":
                send(op_inspect(req))
            elif op == "put":
                send(op_put(req))
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
