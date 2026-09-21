"""CT-8 (REQ-6 AC6.1/AC6.2): embedder warm-at-boot contract.

The embedder is lazy-loaded on first encode, so a cold first encode burned the
rerank breaker's 20s budget and the WHOLE semantic layer silently fell back to
BM25 for the cooldown (conv-99 proof). The fix: one background encode("warmup")
on the shared singleton at backend startup.

Contract pinned here:
  * the lifespan defines a background warm task (function present)
  * the task is scheduled fire-and-forget via asyncio.create_task — NOT
    awaited — so startup is never blocked on a model load (AC6.1 / KD-5)
  * `app.state.ready = True` happens OUTSIDE the warm function — readiness
    does not depend on the warm succeeding (AC6.2)
  * the warm call targets the SHARED singleton get_embedding_service() —
    one warm covers rerank + SemanticVerifier + episodic
  * the warm body swallows exceptions — a dead sidecar logs and continues
    (AC6.2), it never re-raises into the lifespan
"""
from __future__ import annotations

import ast
from pathlib import Path

MAIN_PY = Path(__file__).resolve().parents[2] / "main.py"


def _lifespan_tree():
    src = MAIN_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan":
            return node, src
    raise AssertionError("lifespan async function not found in backend/main.py")


def _find_function(lifespan_node, name):
    for node in ast.walk(lifespan_node):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


def test_lifespan_defines_the_warm_task():
    lifespan, _src = _lifespan_tree()
    assert _find_function(lifespan, "_warm_embedding_service") is not None, (
        "lifespan must define _warm_embedding_service (REQ-6 AC6.1)"
    )


def test_warm_task_is_fire_and_forget_not_awaited():
    """KD-5: startup must NOT block on a GPU/CPU model load. The task must be
    scheduled with asyncio.create_task and never awaited inside the lifespan."""
    lifespan, _src = _lifespan_tree()
    warm = _find_function(lifespan, "_warm_embedding_service")
    assert warm is not None
    scheduled = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_task"
        for node in ast.walk(lifespan)
    )
    assert scheduled, "warm task must be scheduled via asyncio.create_task"
    # And never awaited anywhere in the lifespan body.
    for node in ast.walk(lifespan):
        if isinstance(node, ast.Await):
            inner = node.value
            if isinstance(inner, ast.Name) and inner.id == "_warm_embedding_service":
                raise AssertionError(
                    "warm task was awaited — that blocks readiness (KD-5)"
                )


def test_ready_true_is_outside_the_warm_function():
    """AC6.2: readiness must not depend on the warm succeeding. The
    `app.state.ready = True` assignment must live outside the warm function's
    body (which sits after it in the lifespan anyway, but pin the order)."""
    _lifespan, src = _lifespan_tree()
    ready_pos = src.find("app.state.ready = True")
    warm_def_pos = src.find("async def _warm_embedding_service")
    warm_task_pos = src.find("asyncio.create_task(_warm_embedding_service())")
    assert ready_pos != -1 and warm_def_pos != -1 and warm_task_pos != -1
    assert ready_pos < warm_def_pos < warm_task_pos, (
        "app.state.ready = True must be set before the warm task is scheduled "
        "— readiness never waits on the embedder"
    )


def test_warm_targets_the_shared_singleton_and_swallows_failure():
    """AC6.1/AC6.2: one warm on get_embedding_service() covers rerank +
    SemanticVerifier + episodic; the try/except must swallow (log + continue),
    never re-raise into the lifespan."""
    lifespan, _src = _lifespan_tree()
    warm = _find_function(lifespan, "_warm_embedding_service")
    assert warm is not None

    # The encode call must go through get_embedding_service().
    calls = [
        node for node in ast.walk(warm)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "get_embedding_service"
    ]
    assert calls, "warm must call get_embedding_service() (the shared singleton)"

    encodes = [
        node for node in ast.walk(warm)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "encode"
    ]
    assert encodes, "warm must issue an encode('warmup') call"

    # The body must be wrapped in try/except that does NOT re-raise.
    has_swallowing_try = False
    for node in ast.walk(warm):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                # An except clause whose body does not `raise` = swallow.
                if not any(
                    isinstance(n, ast.Raise) for n in ast.walk(handler)
                ):
                    has_swallowing_try = True
    assert has_swallowing_try, (
        "warm body must swallow exceptions (log + continue) — a dead sidecar "
        "must never block or crash startup (AC6.2)"
    )
