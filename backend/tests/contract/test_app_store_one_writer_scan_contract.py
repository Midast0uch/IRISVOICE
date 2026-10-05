"""ONE WRITER scan (2026-10-04) - no production code writes the app store
outside backend/memory/db.py app_write.

data/memory.db is SQLite WAL: one writer at a time. Every Python connection
that wrote it directly waited on the others' lock (busy_timeout 5 s) and
failed: live 2026-10-04, 8 lost rows and a 22 s gap in one 42 s reply. The
native core's writer thread now owns the file; app_write queues on it.

This test parses every production module under backend/ and fails on any
execute / executemany / executescript call whose SQL (a literal, an f-string,
a concatenation, a .format(), or a local variable assigned one of those in the
same function) starts with INSERT / UPDATE / DELETE / REPLACE - unless the file
writes ANOTHER database (FILES_OTHER_STORES) or the site is a reviewed,
written-down exception (SITES_LEFT_DIRECT). Schema DDL (CREATE / ALTER / DROP)
is not a row write and is not flagged.

Blind spot, stated: SQL built in another function and passed in is not seen.
"""
from __future__ import annotations

import ast
import os
import re

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_DML = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.I)

# Files whose writes go to a DIFFERENT sqlite file than the app store.
FILES_OTHER_STORES = {
    "conversation_store.py": "data/conversations.db",
    "agent/conversation_context_store.py": "conversation_contexts.db",
    "monitor/store.py": "data/monitor.db",
}

# (file, enclosing function) -> why the write stays direct. Every entry is a
# reviewed decision, not a convenience: a new write must use app_write.
SITES_LEFT_DIRECT: dict = {
    ("memory/card_footprint.py", "save_batch_footprint"):
        "two INSERTs in ONE transaction - test_batch_write_is_atomic_on_mid_failure "
        "requires the whole batch to roll back; the queue commits per statement",
    ("memory/episodic.py", "fragment_and_store"):
        "the else-branch for a store the native writer does NOT own (owns_store "
        "False: tests, an encrypted store) - one executemany with locked retry",
    ("memory/episodic.py", "_batch326"): "same fallback branch as fragment_and_store",
    ("memory/episodic.py", "_row326"): "same fallback branch as fragment_and_store",
    ("memory/pin_store.py", "link"):
        "the branch for a store the native writer does NOT own: it needs lastrowid",
}


def _sql_head(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if isinstance(node, ast.BinOp):
        return _sql_head(node.left)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"):
        return _sql_head(node.func.value)
    return None


def _violations():
    found = []
    root = os.path.abspath(_BACKEND)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("tests", "__pycache__")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if rel in FILES_OTHER_STORES:
                continue
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except SyntaxError:
                continue
            funcs = [n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for fn in funcs:
                dml_names = set()
                for n in ast.walk(fn):
                    if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                            and isinstance(n.targets[0], ast.Name):
                        head = _sql_head(n.value)
                        if head and _DML.match(head):
                            dml_names.add(n.targets[0].id)
                for n in ast.walk(fn):
                    if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                            and n.func.attr in ("execute", "executemany", "executescript")
                            and n.args):
                        continue
                    arg = n.args[0]
                    head = _sql_head(arg)
                    is_dml = bool(head and _DML.match(head)) or (
                        isinstance(arg, ast.Name) and arg.id in dml_names)
                    if is_dml and (rel, fn.name) not in SITES_LEFT_DIRECT:
                        found.append(f"{rel}:{n.lineno} in {fn.name}()")
    return sorted(set(found))


def test_no_direct_writes_to_the_app_store():
    bad = _violations()
    assert not bad, (
        f"{len(bad)} direct write(s) to the app store - use "
        "backend.memory.db.app_write (or list the file/site with its reason):\n"
        + "\n".join(bad))


def test_the_scan_sees_a_direct_write():
    """The scan itself must catch the old shape (a guard that cannot fail is
    not a guard)."""
    src = ('def f(conn):\n    sql = "INSERT INTO t VALUES (?)"\n'
           '    conn.execute(sql, (1,))\n    conn.execute("UPDATE t SET x = 1")\n')
    tree = ast.parse(src)
    fn = tree.body[0]
    names = {n.targets[0].id for n in ast.walk(fn)
             if isinstance(n, ast.Assign) and _DML.match(_sql_head(n.value) or "")}
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "execute"]
    hits = [c for c in calls if (_DML.match(_sql_head(c.args[0]) or "")
                                 or (isinstance(c.args[0], ast.Name) and c.args[0].id in names))]
    assert len(hits) == 2
