"""Workbench digest: an exec reply -> the bounded text a model sees, plus `wb` refs.

Pure and stdlib only. A `wb` reference is `wb:<incarnation>/<name>`; as a placeholder
that is Ref(kind="wb", id="<incarnation>/<name>"). `<name>` is a variable, or `out<n>`
for the full stdout of execution n.
"""
import collections
import re
import threading
from typing import List, Optional, Tuple

STDOUT_HEAD = 600
STDOUT_TAIL = 600            # head + tail <= 1,200 chars
VALUE_MAX = 400
MAX_VAR_LINES = 12
OTHER_VAR_LINES = 4          # with declared outputs: the outputs, then at most this many others
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


def _listed(reply: dict, outputs: Optional[List[str]] = None) -> Tuple[list, int]:
    """(the changed variables the digest lists, how many it leaves out). With `outputs` (the
    brief's names, set by the harness): those that changed FIRST in the brief's order, then at
    most OTHER_VAR_LINES others. Without: up to MAX_VAR_LINES in change order."""
    vars_ = reply.get("vars") or []
    if outputs:
        by_name = {v["name"]: v for v in vars_}
        first = [by_name[n] for n in dict.fromkeys(outputs) if n in by_name]
        chosen = {v["name"] for v in first}
        listed = first + [v for v in vars_ if v["name"] not in chosen][:OTHER_VAR_LINES]
    else:
        listed = vars_[:MAX_VAR_LINES]
    return listed, len(vars_) - len(listed)


def refs(reply: dict, outputs: Optional[List[str]] = None) -> List[str]:
    """Every wb ref the digest of `reply` names (changed variables, the cut stdout)."""
    inc = reply.get("incarnation") or ""
    if not inc:
        return []
    out = [make_ref(inc, v["name"]) for v in _listed(reply, outputs)[0]]
    if _stdout_cut(reply):
        out.append(make_ref(inc, f"out{reply.get('out_n')}"))
    return out


def _stdout_cut(reply: dict) -> bool:
    return len(reply.get("stdout") or "") > STDOUT_HEAD + STDOUT_TAIL and reply.get("out_n") is not None


def digest(reply: dict, rss_mb: Optional[float] = None, outputs: Optional[List[str]] = None) -> str:
    """The text of one execution, bounded: stdout <= 1,200 chars, value <= 400,
    <= 12 variable lines (with `outputs`: those first, then <= 4 others), the error type,
    message and a trace tail. `rss_mb` is the memory of the whole worker tree; above 256 MB
    the digest says so."""
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
        listed, more = _listed(reply, outputs)
        for v in listed:
            size = "" if v.get("size") is None else f", size {v['size']}"
            lines.append(f"{v['name']}: {v.get('type')}{size} - {_clip(str(v.get('preview') or ''), 80)}"
                         f"  [{make_ref(inc, v['name'])}]")
        if more > 0:
            lines.append(f"... and {more} more")
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
# The spill set of an incarnation: the brief's output names registered when a check PASSES
# (`declared`), the `out<n>` refs a digest handed out (`outs`), and - for a run with no brief -
# the names of its LAST script only (`last`). Loop temporaries of a brief run never get in.
_named: "collections.OrderedDict[str, dict]" = collections.OrderedDict()


def remember_named(reply: dict, outputs: Optional[List[str]] = None, passed: bool = False) -> None:
    """Record what the spill may write for this execution. `outputs`: the brief's names (a brief
    run); `passed`: its check passed -> those names are declared. A run with no `outputs`
    replaces the incarnation's `last` set with the variables its digest listed."""
    inc = reply.get("incarnation") or ""
    if not inc:
        return
    out_refs = [parse_ref(r) for r in refs(reply, outputs)]
    var_names = [p[1] for p in out_refs if p and not re.fullmatch(r"out\d+", p[1])]
    out_names = [p[1] for p in out_refs if p and re.fullmatch(r"out\d+", p[1])]
    with _origins_lock:
        ent = _named.setdefault(inc, {"declared": [], "outs": [], "last": []})
        _named.move_to_end(inc)
        for n in out_names:
            if n in ent["outs"]:
                ent["outs"].remove(n)
            ent["outs"].append(n)
        if outputs:
            if passed:
                for n in outputs:
                    if isinstance(n, str) and n.isidentifier():
                        if n in ent["declared"]:
                            ent["declared"].remove(n)
                        ent["declared"].append(n)
        else:
            ent["last"] = var_names
        while len(_named) > NAMED_INCARNATIONS:
            _named.popitem(last=False)


def named(incarnation: str) -> List[str]:
    """The names of `incarnation` the spill writes, oldest first, at most NAMED_MAX."""
    with _origins_lock:
        ent = _named.get(incarnation)
        if ent is None:
            return []
        names = list(dict.fromkeys(ent["outs"] + ent["last"] + ent["declared"]))
        return names[-NAMED_MAX:]
