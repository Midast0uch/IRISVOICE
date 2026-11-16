"""Workbench digest: an exec reply -> the bounded text a model sees, plus `wb` refs.

Pure and stdlib only. A `wb` reference is `wb:<incarnation>/<name>`; as a placeholder
that is Ref(kind="wb", id="<incarnation>/<name>"). `<name>` is a variable, or `out<n>`
for the full stdout of execution n.
"""
import collections
import threading
from typing import List, Optional, Tuple

STDOUT_HEAD = 600
STDOUT_TAIL = 600            # head + tail <= 1,200 chars
VALUE_MAX = 400
MAX_VAR_LINES = 12
ERROR_MESSAGE_MAX = 300
TRACE_TAIL_MAX = 600
MEMORY_NOTE_MB = 256         # the digest warns above this worker-tree size
ORIGIN_MAX = 1000            # remembered (incarnation, name) -> purpose entries
NAMED_MAX = 24               # names kept per incarnation for the spill (newest last)
NAMED_INCARNATIONS = 64      # incarnations remembered

_origins: "collections.OrderedDict[Tuple[str, str], str]" = collections.OrderedDict()
_origins_lock = threading.Lock()


def make_ref(incarnation: str, name: str) -> str:
    return f"wb:{incarnation}/{name}"


def parse_ref(ref: str) -> Optional[Tuple[str, str]]:
    """(incarnation, name) of `wb:<incarnation>/<name>`, else None."""
    kind, _, rest = (ref or "").strip().partition(":")
    inc, sep, name = rest.partition("/")
    if kind != "wb" or not sep or not inc or not name or any(c.isspace() for c in rest):
        return None
    return inc, name


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:max(0, limit - 3)] + "..."


def refs(reply: dict) -> List[str]:
    """Every wb ref the digest of `reply` names (changed variables, the cut stdout)."""
    inc = reply.get("incarnation") or ""
    if not inc:
        return []
    out = [make_ref(inc, v["name"]) for v in (reply.get("vars") or [])[:MAX_VAR_LINES]]
    if _stdout_cut(reply):
        out.append(make_ref(inc, f"out{reply.get('out_n')}"))
    return out


def _stdout_cut(reply: dict) -> bool:
    return len(reply.get("stdout") or "") > STDOUT_HEAD + STDOUT_TAIL and reply.get("out_n") is not None


def digest(reply: dict, rss_mb: Optional[float] = None) -> str:
    """The text of one execution, bounded: stdout <= 1,200 chars, value <= 400,
    <= 12 variable lines, the error type, message and a trace tail. `rss_mb` is the
    memory of the whole worker tree; above 256 MB the digest says so."""
    inc = reply.get("incarnation") or ""
    lines = [f"run_python {'ok' if reply.get('ok') else 'error'} ({reply.get('wall_ms', 0)} ms)"]
    stdout = reply.get("stdout") or ""
    if stdout:
        if _stdout_cut(reply):
            gap = len(stdout) - STDOUT_HEAD - STDOUT_TAIL
            lines.append("stdout:\n" + stdout[:STDOUT_HEAD] + f"\n... [{gap} chars cut] ...\n"
                         + stdout[-STDOUT_TAIL:])
            lines.append(f"full output: [wb out:{inc}/out{reply['out_n']}] "
                         f"(recall_memory expand=\"{make_ref(inc, 'out%d' % reply['out_n'])}\")")
        else:
            lines.append("stdout:\n" + stdout[:STDOUT_HEAD + STDOUT_TAIL])
    stderr = reply.get("stderr") or ""
    if stderr:
        lines.append("stderr:\n" + _clip(stderr, 400))
    if reply.get("value") is not None:
        lines.append("value: " + _clip(str(reply["value"]), VALUE_MAX))
    err = reply.get("error")
    if err:
        lines.append(f"error: {err.get('type')}: {_clip(str(err.get('message') or ''), ERROR_MESSAGE_MAX)}")
        tail = str(err.get("trace_tail") or "")
        if tail:
            lines.append(tail[-TRACE_TAIL_MAX:])
    vars_ = reply.get("vars") or []
    if vars_:
        lines.append("changed variables:")
        for v in vars_[:MAX_VAR_LINES]:
            size = "" if v.get("size") is None else f", size {v['size']}"
            lines.append(f"{v['name']}: {v.get('type')}{size} - {_clip(str(v.get('preview') or ''), 80)}"
                         f"  [{make_ref(inc, v['name'])}]")
        if len(vars_) > MAX_VAR_LINES:
            lines.append(f"... and {len(vars_) - MAX_VAR_LINES} more")
    if rss_mb is not None and rss_mb > MEMORY_NOTE_MB:
        lines.append(f"[workbench holds {int(rss_mb)} MB - del what you no longer need]")
    if reply.get("truncated"):
        lines.append("note: output was cut at 256,000 chars")
    return "\n".join(lines)


# --- where a value came from (for the `workbench_gone` answer) -------------------
def remember_origin(reply: dict, purpose: str) -> None:
    """Record the purpose of an execution against the refs it created."""
    inc = reply.get("incarnation") or ""
    if not inc or not purpose:
        return
    names = [v["name"] for v in (reply.get("vars") or [])]
    if reply.get("out_n") is not None:
        names.append(f"out{reply['out_n']}")
    with _origins_lock:
        for n in names:
            _origins[(inc, n)] = purpose[:200]
            _origins.move_to_end((inc, n))
        while len(_origins) > ORIGIN_MAX:
            _origins.popitem(last=False)


def origin_of(incarnation: str, name: str) -> Optional[str]:
    with _origins_lock:
        return _origins.get((incarnation, name))


# --- which values a digest named (what the spill writes) -------------------------
_named: "collections.OrderedDict[str, List[str]]" = collections.OrderedDict()


def remember_named(reply: dict) -> None:
    """Record the names `refs(reply)` handed to a model: the values a step result or a
    live `wb:` placeholder can point at. The spill writes exactly these, never the namespace."""
    with _origins_lock:
        for ref in refs(reply):
            parsed = parse_ref(ref)
            if parsed is None:
                continue
            inc, name = parsed
            names = _named.setdefault(inc, [])
            if name in names:
                names.remove(name)
            names.append(name)
            del names[:-NAMED_MAX]
            _named.move_to_end(inc)
        while len(_named) > NAMED_INCARNATIONS:
            _named.popitem(last=False)


def named(incarnation: str) -> List[str]:
    """The names of `incarnation` a digest handed out, oldest first."""
    with _origins_lock:
        return list(_named.get(incarnation, ()))
