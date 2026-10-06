"""Edit diffs: what each agent file edit changed, and the undo for it.

Plain words: when the agent changes a file, a "photo" of the file is taken
before and after. The difference becomes a diff the chat shows (a ``±`` icon,
reviewed hunk by hunk). Undo puts the old lines back, but only when the file
still looks the way the agent left it. If the user (or anything else) changed the
file since, undo says no. It never overwrites newer work. A successful undo also
tells IRIS the change was not wanted (``tell_iris``).

Technical:
  * ONE chokepoint feeds this module: ``AgentToolBridge.execute_mcp_tool`` for
    the ``file_manager`` writers (``write_file``, ``edit_file``). It calls
    ``snapshot_before`` / ``record_after`` and puts the payload in the tool
    result under ``diff``. The kernel moves it into the ``tool:result`` event.
  * Everything is in memory and bounded (ledger: 200 diffs, 64 MB, oldest
    evicted). Nothing here writes a database on the reply path.
  * Pure stdlib. The two callers outside the module (``tell_iris``) import the
    kernel lazily, so this file loads without the agent package.

Bounds (owner brief 2026-10-06):
  * binary files: no diff.
  * one diff payload: 400 lines / 64 KB, then ``truncated: true``.
  * pre-image kept for undo: 2 MB per file; larger -> diff shown, ``undoable: false``.
  * files over 8 MB are not read at all: a stub diff (``truncated``, no hunks).
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import os
import shutil
import stat
import tempfile
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CONTEXT_LINES = 3
MAX_DIFF_LINES = 400          # shown lines per diff payload
MAX_DIFF_BYTES = 64 * 1024    # shown bytes per diff payload
MAX_LINE_CHARS = 2000         # one shown line (a minified file is one huge line)
MAX_PREIMAGE_BYTES = 2 * 1024 * 1024   # pre-image kept for undo, per file
MAX_READ_BYTES = 8 * 1024 * 1024       # above this the file is not even read
MAX_CHANGED_LINES = 5000      # changed region above this -> stub (difflib is quadratic)
LEDGER_MAX_DIFFS = 200
LEDGER_MAX_BYTES = 64 * 1024 * 1024

# The file_manager tools that write a file's text. delete_file / run_command are
# not captured here (no text pair to diff).
DIFF_TOOLS = frozenset({"write_file", "edit_file"})


# ── snapshots ───────────────────────────────────────────────────────────────

@dataclass
class Snapshot:
    path: str
    existed: bool = False
    data: Optional[bytes] = None      # None: missing, too big, or unreadable
    too_big: bool = False
    size: int = 0
    mtime_ns: int = 0
    unreadable: bool = False


def snapshot(path: str) -> Snapshot:
    """The file's bytes now (sync: call it with ``asyncio.to_thread``)."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return Snapshot(path)
    except OSError:
        return Snapshot(path, unreadable=True)
    if not stat.S_ISREG(st.st_mode):
        return Snapshot(path, existed=True, unreadable=True)
    snap = Snapshot(path, existed=True, size=st.st_size, mtime_ns=st.st_mtime_ns)
    if st.st_size > MAX_READ_BYTES:
        snap.too_big = True
        return snap
    try:
        with open(path, "rb") as f:
            snap.data = f.read()
    except OSError:
        snap.unreadable = True
    return snap


# ── the ledger ──────────────────────────────────────────────────────────────

@dataclass
class _Hunk:
    before: List[str]      # exact lines (line endings kept) the file had
    after: List[str]       # exact lines the agent left
    new_start: int         # 0-based start of ``after`` in the post-edit file
    undone: bool = False


@dataclass
class _Entry:
    diff_id: str
    session_id: str
    conversation_id: str
    path: str
    existed: bool
    pre: Optional[bytes]
    expected_sha: Optional[str]    # sha256 of the file as we last left it
    undoable: bool
    hunks: List[_Hunk] = field(default_factory=list)
    undone_whole: bool = False
    size: int = 0


_LOCK = threading.Lock()
_LEDGER: "OrderedDict[str, _Entry]" = OrderedDict()
_LEDGER_BYTES = 0


def _entry_size(e: _Entry) -> int:
    n = 256 + len(e.pre or b"")
    for h in e.hunks:
        n += sum(len(x) for x in h.before) + sum(len(x) for x in h.after)
    return n


def _ledger_put(e: _Entry) -> None:
    """Add, then evict the oldest until both bounds hold. Caller holds _LOCK."""
    global _LEDGER_BYTES
    e.size = _entry_size(e)
    _LEDGER[e.diff_id] = e
    _LEDGER_BYTES += e.size
    while _LEDGER and (len(_LEDGER) > LEDGER_MAX_DIFFS or _LEDGER_BYTES > LEDGER_MAX_BYTES):
        _, old = _LEDGER.popitem(last=False)
        _LEDGER_BYTES -= old.size


def ledger_stats() -> Dict[str, int]:
    with _LOCK:
        return {"diffs": len(_LEDGER), "bytes": _LEDGER_BYTES}


def clear_ledger_for_testing() -> None:
    global _LEDGER_BYTES
    with _LOCK:
        _LEDGER.clear()
        _LEDGER_BYTES = 0


# ── building the diff ───────────────────────────────────────────────────────

def _sha(data: Optional[bytes]) -> Optional[str]:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _split_lines(text: str) -> List[str]:
    """Lines split on "\\n" only, endings kept ("\\r\\n" stays whole)."""
    parts = text.split("\n")
    out = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _range(start: int, stop: int) -> str:
    # difflib's unified range: 1-based start, "n" alone when one line.
    beginning, length = start + 1, stop - start
    if length == 1:
        return str(beginning)
    if length == 0:
        beginning -= 1
    return f"{beginning},{length}"


def _build(pre_text: str, post_text: str):
    """(groups, a, b, added, removed) with line indexes into the full files, or
    None when the changed region is too large to diff."""
    a, b = _split_lines(pre_text), _split_lines(post_text)
    m = min(len(a), len(b))
    p = 0
    while p < m and a[p] == b[p]:
        p += 1
    s = 0
    while s < m - p and a[-1 - s] == b[-1 - s]:
        s += 1
    if max(len(a), len(b)) - p - s > MAX_CHANGED_LINES:
        return None
    lo = max(0, p - CONTEXT_LINES)
    sm = difflib.SequenceMatcher(
        None,
        a[lo:min(len(a), len(a) - s + CONTEXT_LINES)],
        b[lo:min(len(b), len(b) - s + CONTEXT_LINES)],
        autojunk=False,
    )
    groups = [
        [(tag, i1 + lo, i2 + lo, j1 + lo, j2 + lo) for tag, i1, i2, j1, j2 in g]
        for g in sm.get_grouped_opcodes(CONTEXT_LINES)
    ]
    added = removed = 0
    for g in groups:
        for tag, i1, i2, j1, j2 in g:
            if tag in ("replace", "delete"):
                removed += i2 - i1
            if tag in ("replace", "insert"):
                added += j2 - j1
    return groups, a, b, added, removed


def _rows(a: List[str], b: List[str], group) -> List[str]:
    """The unified-diff rows of one hunk: " " context, "-" removed, "+" added."""
    rows: List[str] = []
    for tag, i1, i2, j1, j2 in group:
        if tag == "equal":
            rows += [" " + x.rstrip("\r\n") for x in a[i1:i2]]
            continue
        if tag in ("replace", "delete"):
            rows += ["-" + x.rstrip("\r\n") for x in a[i1:i2]]
        if tag in ("replace", "insert"):
            rows += ["+" + x.rstrip("\r\n") for x in b[j1:j2]]
    return rows


def record_after(
    before: Snapshot, session_id: str = "", conversation_id: str = ""
) -> Optional[Dict[str, Any]]:
    """The diff payload for the edit just made, or None when there is nothing to
    show (no change, binary, unreadable, missing after). Stores the undo data in
    the ledger. Sync (reads the file): call it with ``asyncio.to_thread``.
    Never raises."""
    try:
        return _record_after(before, session_id, conversation_id)
    except Exception:  # noqa: BLE001 - a diff must never fail an edit
        logger.warning("[EditDiff] session=%s capture failed for %s", session_id,
                       getattr(before, "path", "?"), exc_info=True)
        return None


def _stub(path: str, existed: bool) -> Dict[str, Any]:
    return {"diff_id": uuid.uuid4().hex[:16], "path": path, "added": 0, "removed": 0,
            "hunks": [], "truncated": True, "undoable": False, "new_file": not existed}


def _record_after(before: Snapshot, session_id: str, conversation_id: str):
    if before.unreadable:
        return None
    after = snapshot(before.path)
    if after.unreadable or not after.existed:
        return None
    # Too big to read on either side: say it changed (size/mtime moved), show nothing.
    if before.too_big or after.too_big:
        if before.too_big and after.too_big and (before.size, before.mtime_ns) == (after.size, after.mtime_ns):
            return None
        return _stub(before.path, before.existed)
    if before.data == after.data:
        return None
    pre, post = before.data, after.data
    if (pre is not None and _is_binary(pre)) or _is_binary(post):
        return None
    try:
        pre_text = pre.decode("utf-8") if pre is not None else ""
        post_text = post.decode("utf-8")
    except UnicodeDecodeError:
        return None

    built = _build(pre_text, post_text)
    if built is None:
        return _stub(before.path, before.existed)
    groups, a, b, added, removed = built

    undoable = pre is None or len(pre) <= MAX_PREIMAGE_BYTES
    entry = _Entry(
        diff_id=uuid.uuid4().hex[:16], session_id=session_id or "",
        conversation_id=conversation_id or "", path=before.path,
        existed=before.existed, pre=pre if undoable else None,
        expected_sha=_sha(post), undoable=undoable,
    )
    shown: List[Dict[str, Any]] = []
    used_lines = used_bytes = 0
    truncated = False
    for g in groups:
        a_lo, a_hi, b_lo, b_hi = g[0][1], g[-1][2], g[0][3], g[-1][4]
        entry.hunks.append(_Hunk(before=a[a_lo:a_hi], after=b[b_lo:b_hi], new_start=b_lo))
        if truncated:
            continue
        lines: List[str] = []
        for row in _rows(a, b, g):
            if len(row) > MAX_LINE_CHARS:
                row = row[:MAX_LINE_CHARS] + "…"
                truncated = True
            if used_lines >= MAX_DIFF_LINES or used_bytes + len(row) + 1 > MAX_DIFF_BYTES:
                truncated = True
                break
            lines.append(row)
            used_lines += 1
            used_bytes += len(row) + 1
        if not lines:
            continue
        shown.append({
            "header": f"@@ -{_range(a_lo, a_hi)} +{_range(b_lo, b_hi)} @@",
            "lines": lines,
        })
    with _LOCK:
        _ledger_put(entry)
    return {
        "diff_id": entry.diff_id, "path": before.path, "added": added, "removed": removed,
        "hunks": shown, "truncated": truncated, "undoable": undoable,
        "new_file": not before.existed,
    }


# ── undo ────────────────────────────────────────────────────────────────────

def _write_bytes(path: str, data: bytes) -> None:
    """Temp file + os.replace: a crash leaves the old file, never half of one."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)),
                               prefix=".iris-undo-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            shutil.copymode(path, tmp)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _no(reason: str) -> Dict[str, Any]:
    return {"ok": False, "reason": reason}


def undo(diff_id: str, hunk_index: Optional[int] = None) -> Dict[str, Any]:
    """Undo a whole edit (``hunk_index`` None) or one hunk. Returns
    ``{"ok": True, "path", "hunk_index", ...}`` or ``{"ok": False, "reason"}``.
    Refuses, never clobbers: the file must still be as the agent left it (whole
    file) or the hunk's lines must still match (one hunk). Sync file I/O: call
    it with ``asyncio.to_thread``. Never raises."""
    try:
        with _LOCK:
            e = _LEDGER.get(diff_id)
            if e is None:
                return _no("this change is no longer tracked (it is old, or IRIS restarted)")
            _LEDGER.move_to_end(diff_id)
            return _undo_locked(e, hunk_index)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[EditDiff] undo %s failed: %s", diff_id, exc, exc_info=True)
        return _no(f"undo failed: {exc}")


def _undo_locked(e: _Entry, hunk_index: Optional[int]) -> Dict[str, Any]:
    if not e.undoable:
        return _no("this file was too large to keep a copy for undo")
    if e.undone_whole:
        return _no("this change was already undone")
    if hunk_index is not None:
        if not isinstance(hunk_index, int) or isinstance(hunk_index, bool) or not 0 <= hunk_index < len(e.hunks):
            return _no("there is no such change in this edit")
        if e.hunks[hunk_index].undone:
            return _no("this change was already undone")
    cur = snapshot(e.path)
    if cur.unreadable or cur.too_big:
        return _no("the file cannot be read")
    if not cur.existed:
        return _no("the file no longer exists")

    if hunk_index is None:
        if _sha(cur.data) != e.expected_sha:
            return _no("the file changed after this edit, so undo would overwrite newer work")
        if e.existed:
            _write_bytes(e.path, e.pre if e.pre is not None else b"")
            e.expected_sha = _sha(e.pre)
        else:
            os.remove(e.path)
            e.expected_sha = None
        e.undone_whole = True
        for h in e.hunks:
            h.undone = True
        return {"ok": True, "path": e.path, "hunk_index": None, "conversation_id": e.conversation_id,
                "session_id": e.session_id, "scope": "file"}

    h = e.hunks[hunk_index]
    try:
        cur_text = (cur.data or b"").decode("utf-8")
    except UnicodeDecodeError:
        return _no("the file is no longer text")
    lines = _split_lines(cur_text)
    # Earlier hunks that were undone moved this one's position.
    nominal = h.new_start + sum(
        len(x.before) - len(x.after) for x in e.hunks[:hunk_index] if x.undone
    )
    k = len(h.after)
    if k == 0:
        if lines:
            return _no("the lines around this change no longer match the file")
        pos = 0
    else:
        hits = [i for i in range(len(lines) - k + 1)
                if lines[i] == h.after[0] and lines[i:i + k] == h.after]
        if not hits:
            return _no("the lines around this change no longer match the file")
        pos = min(hits, key=lambda i: abs(i - nominal))
    new_lines = lines[:pos] + h.before + lines[pos + k:]
    new_data = "".join(new_lines).encode("utf-8")
    if not e.existed and not new_data:
        os.remove(e.path)
        e.expected_sha = None
    else:
        _write_bytes(e.path, new_data)
        e.expected_sha = _sha(new_data)
    h.undone = True
    lead = 0  # context lines before the first changed line
    while lead < min(len(h.before), len(h.after)) and h.before[lead] == h.after[lead]:
        lead += 1
    return {"ok": True, "path": e.path, "hunk_index": hunk_index, "conversation_id": e.conversation_id,
            "session_id": e.session_id, "scope": "hunk", "line": pos + lead + 1}


# ── telling IRIS ────────────────────────────────────────────────────────────

def tell_iris(result: Dict[str, Any], session_id: str = "", conversation_id: str = "") -> bool:
    """Record that the user did not want this change, where the agent reads it
    on its next turn: a system line in the conversation's own memory
    (``_conversation_memory.get_context()``, which planning and the answer read).
    Also writes a ``CORRECTION`` (evidence: user) row on lane("memory_events"),
    the taxonomy label for "the user corrects the agent". Returns True when the
    context line was recorded. Never raises."""
    conv = conversation_id or result.get("conversation_id") or ""
    sess = session_id or result.get("session_id") or ""
    path = result.get("path") or "a file"
    if result.get("scope") == "hunk":
        what = f"one change near line {result.get('line')} in {path}"
    else:
        what = f"your whole edit to {path}"
    note = (
        f"[Edit undone by the user] The user undid {what}. They did not want it. "
        "The file is back to how it was. Do not make this change again unless they ask for it."
    )
    told = False
    try:
        from backend.agent.event_emit import emit, peek_kernel

        kernel = peek_kernel(conv or None, sess or None)
        memory = getattr(kernel, "_conversation_memory", None)
        if memory is not None:
            memory.add_message("system", note)
            told = True
        else:
            logger.warning("[EditDiff] session=%s conv=%s: no live conversation to tell about the undo of %s",
                           sess, conv, path)
        emit(kernel, "CORRECTION", evidence="user", thread_id=sess or None,
             conversation_id=conv or None,
             payload={"kind": "diff_undo", "path": path, "scope": result.get("scope"),
                      "hunk_index": result.get("hunk_index")})
    except Exception:  # noqa: BLE001 - telling never blocks the undo
        logger.warning("[EditDiff] session=%s tell_iris failed", sess, exc_info=True)
    return told
