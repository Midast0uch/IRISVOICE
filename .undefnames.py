"""Undefined-name finder — the check `py_compile` cannot do.

`python -m py_compile` only PARSES. A name that is referenced but never bound
is a RUNTIME NameError that compiles cleanly, and in this codebase such a name
is usually sitting inside a `try/except Exception: pass` — so it silently
disables whatever fix it was written for. Session 365 found five of them in
agent_kernel.py alone, one of which had killed the whole `depth_met`
enforcement path and another the `sufficient` gate.

This reads `symtable` (the same CPython table pyflakes uses) and reports every
name that is referenced but not bound in its own scope, the module, or
builtins.

Usage:
    .venv/Scripts/python.exe .undefnames.py backend          # whole tree
    .venv/Scripts/python.exe .undefnames.py path/to/file.py
Exit: 0 = clean, 1 = findings.
"""
import builtins
import os
import symtable
import sys

# Module dunders the import machinery injects at runtime; never statically
# bound, so symtable cannot see them.
_MODULE_DUNDERS = {
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__path__", "__cached__", "__annotations__",
}
_SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git"}


def _module_bound(top):
    """Names bound at module level (assignments, imports, def/class)."""
    out = set()
    for s in top.get_symbols():
        if s.is_assigned() or s.is_imported() or s.is_namespace():
            out.add(s.get_name())
    return out


def _walk(table, module_bound, scope_path, findings):
    for sym in table.get_symbols():
        name = sym.get_name()
        if not sym.is_referenced():
            continue
        # Local / parameter / free (bound by an enclosing function) are fine;
        # anything else is a global lookup that must exist at module or
        # builtins level.
        if sym.is_local() or sym.is_parameter() or sym.is_free():
            continue
        if name in module_bound or name in _MODULE_DUNDERS:
            continue
        if hasattr(builtins, name):
            continue
        findings.append((table.get_lineno(), scope_path, name))
    for child in table.get_children():
        _walk(child, module_bound, scope_path + "/" + child.get_name(), findings)


def check(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    # CPython's tokenizer accepts a UTF-8 BOM; symtable() does not, so strip it
    # or every BOM'd file reports a bogus SyntaxError.
    if src.startswith("\ufeff"):
        src = src[1:]
    try:
        top = symtable.symtable(src, path, "exec")
    except SyntaxError as exc:
        print(f"{path}: SYNTAX ERROR {exc}")
        return 1
    findings = []
    _walk(top, _module_bound(top), "<module>", findings)
    for lineno, scope, name in findings:
        print(f"{path}:{lineno}: undefined name '{name}' (in {scope})")
    return 1 if findings else 0


def _iter_files(target):
    if os.path.isfile(target):
        yield target
        return
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in sorted(files):
            if f.endswith(".py"):
                yield os.path.join(root, f)


def main(argv):
    rc = 0
    for target in argv:
        for path in _iter_files(target):
            rc |= check(path)
    return rc


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
