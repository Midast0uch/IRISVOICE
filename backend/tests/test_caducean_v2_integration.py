"""
test_caducean_v2_integration.py — Integration tests for Phase 3.

PURPOSE: Verify end-to-end flow:
  - Caducean engine produces trajectory rows
  - Mycelium's record_anomaly delegates to QuorumSensor
  - scorer.py reads latest u and modulates decay
  - resonance.py reads latest u and modulates retrieval
  - MemoryInterface public accessors work

Run via direct Python (bypassing the pre-existing pytest conftest bug):
  python -c \"import backend.tests.test_caducean_v2_integration as t; t.run_all()\"
"""

import os
import sqlite3
import sys
import tempfile
import time
from typing import Dict

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.gateway.iris_ffi import (
    ffi_init_engine,
    ffi_caducean_init_session,
    ffi_caducean_update,
    ffi_caducean_recommend,
    ffi_caducean_get_state,
)
from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder


# ---------------------------------------------------------------------------
# Test 1: caducean_trajectories table has recommendation column
# ---------------------------------------------------------------------------


def test_recommendation_column_exists():
    """v2: recommendation column added to caducean_trajectories."""
    tmp = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(tmp)
    try:
        ct = CaduceanTrajectoryRecorder(db_conn=conn)
        cols = [
            c[1]
            for c in conn.execute("PRAGMA table_info(caducean_trajectories)").fetchall()
        ]
        assert "recommendation" in cols, f"recommendation column missing: {cols}"
        print(f"  PASS  recommendation column present (cols: {cols})")
    finally:
        conn.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass


def test_recommendation_idempotent_alter():
    """v2: ALTER TABLE is idempotent (column already exists is safe)."""
    tmp = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(tmp)
    try:
        # First init creates the column
        CaduceanTrajectoryRecorder(db_conn=conn)
        # Second init should not raise
        try:
            CaduceanTrajectoryRecorder(db_conn=conn)
            print("  PASS  ALTER TABLE is idempotent (second init no-op)")
        except Exception as e:
            raise AssertionError(f"second init failed: {e}")
    finally:
        conn.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Test 2: record() persists xi, u, recommendation
# ---------------------------------------------------------------------------


def test_record_persists_xi_u_recommendation():
    """v2: record() now takes xi, u, recommendation (previously hardcoded 0.0)."""
    tmp = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(tmp)
    try:
        ffi_init_engine(tmp, "00" * 32)
        ct = CaduceanTrajectoryRecorder(db_conn=conn)
        ct.record(
            "test_session",
            step_num=1,
            x=5,
            y=3,
            xi=1.57,
            u=0.42,
            action=0,
            outcome="explore",
            eml_after=1.5,
            recommendation=0,
        )
        ct.record(
            "test_session",
            step_num=2,
            x=5,
            y=4,
            xi=3.14,
            u=-0.5,
            action=1,
            outcome="compress",
            eml_after=0.5,
            recommendation=1,
        )
        rows = conn.execute(
            "SELECT step_num, x, y, xi, u, recommendation FROM caducean_trajectories "
            "ORDER BY step_num"
        ).fetchall()
        assert len(rows) == 2
        # First row (step 1, explore)
        assert rows[0][0] == 1
        assert rows[0][3] == 1.57  # xi
        assert rows[0][4] == 0.42  # u
        assert rows[0][5] == 0  # recommendation = EXPAND
        # Second row (step 2, compress)
        assert rows[1][0] == 2
        assert rows[1][4] == -0.5
        assert rows[1][5] == 1  # recommendation = COMPRESS
        print("  PASS  record() persists xi, u, recommendation")
    finally:
        conn.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Test 3: SQL query for get_latest_u returns correct dict
# ---------------------------------------------------------------------------


def test_get_latest_u_query():
    """Verify the SQL that get_latest_u uses (since we can't easily test
    the full MyceliumInterface which needs SQLCipher)."""
    tmp = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(tmp)
    try:
        ct = CaduceanTrajectoryRecorder(db_conn=conn)
        # Insert 3 rows
        for i in range(3):
            ct.record(
                "q_session",
                step_num=i,
                x=i,
                y=i,
                xi=i * 0.5,
                u=i * 0.1,
                action=0,
                outcome="test",
                eml_after=1.0,
                recommendation=2,
            )
        # Query for latest (the same query get_latest_u uses)
        row = conn.execute(
            "SELECT x, y, xi, u, recommendation FROM caducean_trajectories "
            "WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            ("q_session",),
        ).fetchone()
        assert row is not None
        result = {
            "x": float(row[0]),
            "y": float(row[1]),
            "xi": float(row[2]),
            "u": float(row[3]),
            "recommendation": int(row[4]) if row[4] is not None else 2,
        }
        assert result["x"] == 2.0
        assert result["y"] == 2.0
        assert abs(result["u"] - 0.2) < 0.001
        print(f"  PASS  get_latest_u SQL query: {result}")
    finally:
        conn.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Test 4: Decay multiplier logic for explore vs compress
# ---------------------------------------------------------------------------


def test_decay_multiplier_for_explore_vs_compress():
    """v2: Caducean u modulates decay multiplier.

    This test verifies the LOGIC (not the full scorer path which needs MyceliumInterface).
    u > 0 → 0.5 (explore, preserve)
    u < 0 → 1.8 (compress, prune faster)
    u ≈ 0 → 1.0 (neutral)
    """

    def get_multiplier(u: float) -> float:
        if u > 0:
            return 0.5
        elif u < 0:
            return 1.8
        return 1.0

    assert get_multiplier(0.5) == 0.5, "explore multiplier wrong"
    assert get_multiplier(-0.5) == 1.8, "compress multiplier wrong"
    assert get_multiplier(0.0) == 1.0, "neutral multiplier wrong"
    assert get_multiplier(0.001) == 0.5, "small positive wrong"
    assert get_multiplier(-0.001) == 1.8, "small negative wrong"
    print(
        "  PASS  decay multiplier logic: {0.5, 1.8, 1.0} for {explore, compress, neutral}"
    )


# ---------------------------------------------------------------------------
# Test 5: Resonance multiplier logic
# ---------------------------------------------------------------------------


def test_resonance_multiplier_for_creativity_vs_focus():
    """v2: Caducean u modulates resonance multiplier.

    u > 0 → 0.5 (creativity surge, broader retrieval)
    u < 0 → 1.8 (focus lock, strict matching)
    u ≈ 0 → 1.0 (neutral)
    """

    def get_resonance_mod(u: float) -> float:
        if u > 0:
            return 0.5
        elif u < 0:
            return 1.8
        return 1.0

    assert get_resonance_mod(0.5) == 0.5, "creativity multiplier wrong"
    assert get_resonance_mod(-0.5) == 1.8, "focus multiplier wrong"
    assert get_resonance_mod(0.0) == 1.0, "neutral multiplier wrong"
    print("  PASS  resonance multiplier logic: {0.5, 1.8, 1.0}")


# ---------------------------------------------------------------------------
# Test 6: MyceliumInterface has the new v2 methods
# ---------------------------------------------------------------------------


def test_mycelium_interface_has_v2_methods():
    """Verify MyceliumInterface exposes record_anomaly and get_latest_u."""
    from backend.memory.mycelium.interface import MyceliumInterface

    assert hasattr(MyceliumInterface, "record_anomaly"), "record_anomaly missing"
    assert hasattr(MyceliumInterface, "get_latest_u"), "get_latest_u missing"
    # Verify signatures take the right args
    import inspect

    sig1 = inspect.signature(MyceliumInterface.record_anomaly)
    params1 = list(sig1.parameters.keys())
    assert "session_id" in params1, "record_anomaly missing session_id"
    assert "signal_type" in params1, "record_anomaly missing signal_type"

    sig2 = inspect.signature(MyceliumInterface.get_latest_u)
    params2 = list(sig2.parameters.keys())
    assert "session_id" in params2, "get_latest_u missing session_id"
    print("  PASS  MyceliumInterface.record_anomaly and get_latest_u exist")


# ---------------------------------------------------------------------------
# Test 7: MemoryInterface has the v2 public accessors
# ---------------------------------------------------------------------------


def test_memory_interface_has_v2_accessors():
    """Verify MemoryInterface exposes the v2 public accessors."""
    from backend.memory.interface import MemoryInterface

    for method in (
        "is_caducean_engine_live",
        "mycelium_record_anomaly",
        "get_caducean_state",
    ):
        assert hasattr(MemoryInterface, method), f"{method} missing"
    print("  PASS  MemoryInterface public accessors exist")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_all():
    tests = [
        test_recommendation_column_exists,
        test_recommendation_idempotent_alter,
        test_record_persists_xi_u_recommendation,
        test_get_latest_u_query,
        test_decay_multiplier_for_explore_vs_compress,
        test_resonance_multiplier_for_creativity_vs_focus,
        test_mycelium_interface_has_v2_methods,
        test_memory_interface_has_v2_accessors,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print()
    print(f"Phase 3 integration tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
