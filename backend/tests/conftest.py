"""
Test configuration for backend tests.

History:
  - Previously this conftest monkey-patched `backend.conversation_store`
    to use a test SQLite path under project root, assuming the store
    was a SQLite-backed module.
  - In 2026, conversation_store was refactored to an in-memory store
    (pure Python dict). The old monkeypatch tried to set `_DB_PATH` and
    `_CONN` attributes that no longer exist, causing all pytest
    collection in backend/tests/ to fail with AttributeError.

Current behavior:
  - conversation_store is in-memory; no patching is required.
  - This conftest is intentionally a no-op. It exists for the sys.path
    setup and as a placeholder for any future test fixtures.
  - If conversation_store ever needs to be mocked or redirected in
    tests, add the fixture here.

Usage:
  python -m pytest backend/tests/ -v
"""

import os
import sys

# Ensure project root is on sys.path (so `from backend.X import Y` works)
_project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
