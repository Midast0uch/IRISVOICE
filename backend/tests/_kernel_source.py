"""Read the kernel's source as TEXT, whichever files it lives in.

`backend/agent/agent_kernel.py` is being split into `backend/agent/kernel/`
(docs/architecture/KERNEL_DECOMPOSITION.md). A test or script that scans the kernel
source for a pattern reads it through `kernel_source()`: the facade text followed by
every `kernel/**/*.py` text. Before any code moves that is exactly the text of
agent_kernel.py.

The generator lives in `backend/agent/kernel/__init__.py` (written by
`scripts/kernel_split_check.py init-package`). This helper loads that ONE file by path.
It must not import the `backend.agent` package: that imports the heavy facade, and
several scan tests exist precisely to avoid that import.

Decoding follows the reader being replaced: pass the same `encoding` / `errors` its
`read_text(...)` / `open(...)` used (`encoding=None` = the locale default, like a bare
`read_text()`).
"""
import importlib.util
import os
import sys

_INIT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "backend", "agent", "kernel", "__init__.py",
)


def kernel_source(encoding="utf-8", errors="replace"):
    spec = importlib.util.spec_from_file_location("_iris_kernel_source_loader", _INIT)
    mod = importlib.util.module_from_spec(spec)
    flag = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # no __pycache__ in the package for a text helper
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = flag
    return mod.kernel_source(encoding=encoding, errors=errors)
