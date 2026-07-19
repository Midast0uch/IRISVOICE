"""
Test configuration for the tests/ tree (behavioral, contract, unit).

Ensures the project root and the backend package are importable when pytest
is run from the repo root, so behavioral tests can import backend.agent.*
modules without booting the full application.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if os.path.join(_ROOT, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "backend"))
