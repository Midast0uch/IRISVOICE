"""
Contract tests for PhaseManager (T3.9 / CT-3, CT-4).

Pins the boundary contract:
  * PhaseManager never calls coupled_registry (CT-3)
  * PhaseManager never calls iris_ffi (CT-4)
  * acquire / acquire_async exist as sync/async twins (CT-9)
"""
import inspect

from backend.agent.phase_manager import (
    acquire,
    acquire_async,
    advance,
)

# Import the module source to verify no banned imports
import backend.agent.phase_manager as pm


def test_acquire_is_sync():
    """acquire() must be sync (CT-9 twin)."""
    assert inspect.iscoroutinefunction(acquire) is False


def test_acquire_async_is_async():
    """acquire_async() must be async (CT-9 twin)."""
    assert inspect.iscoroutinefunction(acquire_async) is True


def test_no_banned_imports():
    """PhaseManager must NOT import coupled_registry (CT-3) or iris_ffi (CT-4)."""
    import ast, os

    _path = os.path.join(
        os.path.dirname(pm.__file__), "phase_manager.py"
    )
    with open(_path, encoding="utf-8") as f:
        _tree = ast.parse(f.read())
    _imports = set()
    for _node in ast.walk(_tree):
        if isinstance(_node, ast.Import):
            for _a in _node.names:
                _imports.add(_a.name)
        elif isinstance(_node, ast.ImportFrom):
            if _node.module:
                _imports.add(_node.module)
    assert "backend.agent.coupled_registry" not in _imports, "CT-3 violation"
    assert "backend.gateway.iris_ffi" not in _imports, "CT-4 violation"
