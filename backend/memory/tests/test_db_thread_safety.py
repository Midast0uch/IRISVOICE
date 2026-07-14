"""RC9 — sqlcipher3 thread-safety (Phase 0.4 of the hardening plan).

``open_encrypted_memory`` must open the connection with
``check_same_thread=False`` so DER (which runs in a thread-pool executor) can
access the shared encrypted connection from worker threads without raising
``sqlite3.ProgrammingError``.
"""
import threading

import pytest


def test_open_encrypted_memory_thread_safe(tmp_path):
    from backend.memory.db import open_encrypted_memory

    db_path = str(tmp_path / "enc.db")
    key = b"test_key_32_bytes_long_for_testing_"
    conn = open_encrypted_memory(db_path, key)

    errors = []

    def worker():
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER)")
            conn.commit()
        except Exception as e:  # pragma: no cover - exercised in thread
            errors.append(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert errors == [], f"Thread-safe open failed: {errors}"
    conn.close()


def test_sqlcipher3_connect_uses_check_same_thread(tmp_path):
    """The production sqlcipher3 path must pass check_same_thread=False."""
    db_path = str(tmp_path / "raw.db")
    try:
        import sqlcipher3 as _sqlcipher3
    except ImportError:
        pytest.skip("sqlcipher3 not installed in this environment")

    conn = _sqlcipher3.connect(str(db_path), check_same_thread=False)
    errors = []

    def worker():
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER)")
            conn.commit()
        except Exception as e:  # pragma: no cover
            errors.append(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert errors == [], f"sqlcipher3 thread access failed: {errors}"
    conn.close()
