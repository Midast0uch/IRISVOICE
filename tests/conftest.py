"""
Test configuration for the tests/ tree (behavioral, contract, unit).

Ensures the project root and the backend package are importable when pytest
is run from the repo root, so behavioral tests can import backend.agent.*
modules without booting the full application.
"""
import os
import tempfile as _tempfile

# The API transport persists a per-model call-time profile (stall bound, C6).
# Tests write it too: point it at a temp file so no test result lands in the
# app's data/model_call_times.json (it did once, 2026-10-02).
os.environ.setdefault(
    "IRIS_MODEL_CALL_PROFILE",
    os.path.join(_tempfile.gettempdir(), "iris-tests-model_call_times.json"),
)
# The chat store: never the app's (backend/tests/conftest.py has the same rule since 2026-11-16; this folder did not, and
# 2026-11-23 the app's store held ~800 "Fork Parent" / "Lifecycle Test" conversations from older test runs).
os.environ.setdefault("IRIS_CONVERSATIONS_DB", os.path.join(_tempfile.gettempdir(), f"iris-tests-conversations-{os.getpid()}.db"))
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if os.path.join(_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "backend"))
