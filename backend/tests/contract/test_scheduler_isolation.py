"""
Contract test: scheduler module isolation (CT-3 / CT-4).

The scheduler modules (phase_manager.py, rate_meter.py, trig_coupling.py,
call_context.py, batch_dispatch.py) must NEVER:
  - Call ``coupled_registry`` methods (apply_coupling, register_session, etc.)
  - Call ``iris_ffi`` functions (ffi_caducean_get_xi, get_state, etc.)
  - Import anything beyond ``math``, ``typing``, ``time``, ``asyncio``,
    ``threading``, ``logging`` and project-internal scheduler modules.

``trig_coupling.py`` must stay import-pure: only ``math`` and ``typing``
from stdlib.

This test patches the forbidden modules at import time and fails if any
scheduler module triggers a call to them.
"""
import builtins
import importlib
import sys
from unittest.mock import patch

import pytest


# ── Forbidden function names per contract lock ─────────────────────────────
_FORBIDDEN_COUPLED_REGISTRY = {
    "apply_coupling",
    "register_session",
    "update_session_state",
    "get_session_state",
}
_FORBIDDEN_FFI = {
    "ffi_caducean_get_xi",
    "get_state",
    "set_params",
    "recommend",
}

_SCHEDULER_MODULES = [
    "backend.agent.phase_manager",
    "backend.agent.rate_meter",
    "backend.agent.trig_coupling",
    "backend.agent.call_context",
    "backend.agent.batch_dispatch",
]


@pytest.fixture(autouse=True)
def _restore_scheduler_modules():
    """Put the ORIGINAL scheduler module objects back into ``sys.modules``.

    These tests probe imports by deleting a module from ``sys.modules`` and
    re-importing it under a patched ``__import__``. That leaves a **second,
    distinct module object** installed — with its own ``_singleton`` registry,
    its own ``_flag_logged``, and its own function objects.

    Any test that imported ``acquire`` / ``get_registry`` earlier is still bound
    to the ORIGINAL objects, so it then registers into one registry and reads
    from another. That is what made
    ``test_flag_off_is_identical::test_flag_on_creates_oscillator`` fail only
    when this file ran first, while passing in isolation.

    Snapshotting and restoring keeps the contract probes while leaving the
    process's module identity exactly as it was found.

    DEBT FIX (pin_fd5b312e69bf / c01534199cdb): restoring ``sys.modules``
    entries alone was NOT enough. A re-imported submodule also REBINDS the
    parent package's attribute (``setattr(backend.agent, 'phase_manager',
    <second object>)``), and stray second copies of OTHER ``backend.*``
    modules can linger. Both leave the package graph inconsistent, which
    later surfaced as ``AttributeError: 'module' object at backend.agent has
    no attribute ...`` in every ``monkeypatch.setattr("backend.agent.…")``
    downstream (provider-switch, display-text, speak-envelope,
    task-start-revision suites). Now we restore parent attributes too and
    evict any stray backend.* second copies so the graph is exactly as found.
    """
    _saved = {
        _m: sys.modules[_m] for _m in _SCHEDULER_MODULES if _m in sys.modules
    }
    _saved_backend = {
        _m: _mod for _m, _mod in sys.modules.items()
        if _m == "backend" or _m.startswith("backend.")
    }
    try:
        yield
    finally:
        # 1. Evict stray second copies of ANY backend.* module that was not
        #    in the snapshot (they are re-importable on demand).
        for _m in list(sys.modules):
            if (_m == "backend" or _m.startswith("backend.")) and _m not in _saved_backend:
                del sys.modules[_m]
        # 2. Restore the original module objects.
        for _m, _mod in _saved.items():
            sys.modules[_m] = _mod
        # 3. Rebind parent-package attributes to the ORIGINAL objects.
        for _m, _mod in _saved.items():
            _parent, _, _leaf = _m.rpartition(".")
            if _leaf:
                _parent_mod = sys.modules.get(_parent)
                if _parent_mod is not None:
                    try:
                        setattr(_parent_mod, _leaf, _mod)
                    except Exception:
                        pass  # frozen/namespace parent — nothing to rebind


def _check_and_unpatch(mod_name, forbidden, label):
    """Re-import the module and check for forbidden imports."""
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    with patch.object(builtins, "__import__") as _mock_import:
        _mock_import.side_effect = _import_hook(forbidden, label)
        try:
            importlib.import_module(mod_name)
        except RuntimeError as _e:
            pytest.fail(str(_e))
        finally:
            _mock_import.side_effect = builtins.__import__


def _import_hook(forbidden_set, label):
    """Return an import hook that raises RuntimeError if a forbidden
    module/function is accessed."""
    _orig_import = builtins.__import__

    def _hook(name, *args, **kwargs):
        _top_level = name.split(".")[0]
        # Check if any forbidden name is in the module path
        for _fn in forbidden_set:
            if _fn in (name.split(".")[-1] if "." in name else name):
                raise RuntimeError(
                    "CONTRACT BREACH (CT-%s): scheduler module cannot import "
                    "'%s' (%s)" % (label, name, _fn)
                )
        if _top_level in ("coupled_registry",):
            raise RuntimeError(
                "CONTRACT BREACH (CT-3): scheduler module cannot import "
                "'%s' (coupled_registry)" % name
            )
        if _top_level in ("iris_ffi",):
            raise RuntimeError(
                "CONTRACT BREACH (CT-4): scheduler module cannot import "
                "'%s' (iris_ffi)" % name
            )
        return _orig_import(name, *args, **kwargs)

    return _hook


@pytest.mark.parametrize("mod_name", _SCHEDULER_MODULES)
def test_scheduler_no_coupled_registry_import(mod_name):
    """CT-3: No scheduler module imports coupled_registry."""
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    orig_import = builtins.__import__

    def _hook(name, *args, **kwargs):
        if "coupled_registry" in name:
            raise RuntimeError(
                "CONTRACT BREACH (CT-3): %s attempted to import '%s'"
                % (mod_name, name)
            )
        return orig_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", _hook):
        try:
            importlib.import_module(mod_name)
        except RuntimeError as _e:
            pytest.fail(str(_e))
        finally:
            builtins.__import__ = orig_import


@pytest.mark.parametrize("mod_name", _SCHEDULER_MODULES)
def test_scheduler_no_ffi_import(mod_name):
    """CT-4: No scheduler module imports iris_ffi."""
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    orig_import = builtins.__import__

    def _hook(name, *args, **kwargs):
        if "iris_ffi" in name:
            raise RuntimeError(
                "CONTRACT BREACH (CT-4): %s attempted to import '%s'"
                % (mod_name, name)
            )
        return orig_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", _hook):
        try:
            importlib.import_module(mod_name)
        except RuntimeError as _e:
            pytest.fail(str(_e))
        finally:
            builtins.__import__ = orig_import


def test_trig_coupling_import_pure():
    """trig_coupling.py must import only math and typing from stdlib."""
    if "backend.agent.trig_coupling" in sys.modules:
        del sys.modules["backend.agent.trig_coupling"]

    _forbidden = {"os", "sys", "json", "pickle", "collections", "functools"}
    orig_import = builtins.__import__

    def _hook(name, *args, **kwargs):
        _top = name.split(".")[0]
        if _top in _forbidden:
            raise RuntimeError(
                "trig_coupling imported forbidden module: '%s'" % name
            )
        return orig_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", _hook):
        try:
            importlib.import_module("backend.agent.trig_coupling")
        except RuntimeError as _e:
            pytest.fail(str(_e))
        finally:
            builtins.__import__ = orig_import
