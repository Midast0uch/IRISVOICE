"""Read the kernel's source as TEXT or as an AST, whichever files it lives in.

`backend/agent/agent_kernel.py` is being split into `backend/agent/kernel/`
(docs/architecture/KERNEL_DECOMPOSITION.md). A test or script that scans the kernel
source reads it through one of three functions. Before any code moves each returns
exactly what reading / parsing agent_kernel.py returns.

  kernel_source(encoding, errors)  facade text followed by every kernel/**/*.py text
  kernel_tree()                    one ast.Module for the whole kernel (Mixin class bodies
                                   merged into `class AgentKernel`; linenos are those of the
                                   node's own file, so compare them only inside one function)
  kernel_function_source(name)     get_source_segment text of the ONE def called `name`

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


def _load():
    spec = importlib.util.spec_from_file_location("_iris_kernel_source_loader", _INIT)
    mod = importlib.util.module_from_spec(spec)
    flag = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # no __pycache__ in the package for a text helper
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = flag
    return mod


def kernel_source(encoding="utf-8", errors="replace"):
    return _load().kernel_source(encoding=encoding, errors=errors)


def kernel_tree():
    return _load().kernel_tree()


def kernel_function_source(name):
    return _load().kernel_function_source(name)
