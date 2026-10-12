"""The boot critical path stays short (2026-10-11).

Measured on this machine (C: is a hard disk): /health 200 took 237-578 s while
(1) the wake-word detector initialised SYNCHRONOUSLY on the event loop (41 s
warm, 381 s under contention) with d1's boot load queued behind it, (2) the
dormant local tool server loaded a GGUF + scanned the model dirs at every
boot, and (3) the Phonon-2 STT server spawned beside the TTS worker - both big
Python imports from the same disk (TTS imports 169 s; Phonon-2 missed its own
300 s deadline at every boot). After the fixes: /health 200 at 36 s, d1 at
30 s (warm boot). These pins fail on the old structure.
"""

from __future__ import annotations

import ast
from pathlib import Path

MAIN = Path(__file__).resolve().parents[2] / "main.py"


def _lifespan() -> ast.AsyncFunctionDef:
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan":
            return node
    raise AssertionError("lifespan() not found in backend/main.py")


def _enclosing_functions(root: ast.AST, target_attr: str):
    """Names of the innermost functions that contain a call to *.target_attr()."""
    out = []

    def visit(node, fn):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and child.func.attr == target_attr):
                out.append(fn)
            visit(child, fn)

    visit(root, root.name)
    return out


def test_wake_word_init_never_runs_on_the_startup_path():
    """initialize_detector() is called only inside the background thread's
    target - never directly in lifespan(), where it blocked the event loop."""
    where = _enclosing_functions(_lifespan(), "initialize_detector")
    assert where, "initialize_detector() is no longer called at boot"
    assert all(fn == "_init_wake_and_audio" for fn in where), (
        f"initialize_detector() runs on the startup path: {where}")


def test_d1_boot_load_is_scheduled_before_the_wake_word_section():
    src = MAIN.read_text(encoding="utf-8")
    d1 = src.index("asyncio.create_task(_boot_load_d1())")
    wake = src.index("WAKE WORD MODEL DISCOVERY")
    assert d1 < wake, "d1's boot load is queued behind the wake-word section again"


def test_the_tool_server_warms_only_when_a_role_is_bound_to_it():
    src = MAIN.read_text(encoding="utf-8")
    body = src[src.index("def _tool_server_boot_warm"):]
    body = body[:body.index("_threading.Thread(")]
    assert "_tms.role_bound()" in body, "the dormant tool server warms at every boot again"
    assert body.index("_tms.role_bound()") < body.index("_tms.ensure_running()")


def test_phonon2_warms_after_the_tts_worker():
    src = MAIN.read_text(encoding="utf-8")
    body = src[src.index("def _phonon2_boot_warm"):]
    body = body[:body.index("_threading.Thread(")]
    assert "readiness()" in body, "Phonon-2 spawns beside the TTS worker again"
    assert body.index("readiness()") < body.index("_phonon2_warm_up()")


def test_the_tts_worker_starts_before_anything_else_in_the_lifespan():
    """2026-10-12: the port check (config + 2,316 stored conversations) and the
    cleanups ran first; the worker - the load /health waits for - spawned 12 s
    into startup."""
    body = ast.unparse(_lifespan())
    assert "prewarm()" in body, "the TTS boot load is gone from the lifespan"
    assert body.index("prewarm()") < body.index("resolve_ports"), (
        "the TTS worker spawns after the port check again")
    assert body.index("kill_orphan_tts_workers") < body.index("prewarm()"), (
        "the orphan kill must run before the spawn - it would kill the new worker")


START = MAIN.parents[1] / "start-backend.py"


def test_boot_keeps_hash_checked_bytecode_instead_of_recompiling_everything():
    """2026-10-12: purging every __pycache__ made each boot compile ~1,330
    backend modules (import backend.main: 37 s without a cache, 3.3 s with it).
    A CHECKED-HASH .pyc is validated against the source's hash on every import,
    so the no-stale-bytecode guarantee holds."""
    src = START.read_text(encoding="utf-8")
    assert "sys.dont_write_bytecode = True" in src, "import must still never write bytecode"
    assert "CHECKED_HASH" in src, "the warm-up must write hash-checked .pyc only"
    assert "_is_checked_hash_pyc" in src
    assert 'rglob("__pycache__")' not in src, "the boot purges every cache again"
