"""Tests for C++ trajectory simulator FFI."""
import os

import pytest

from backend.gateway.iris_ffi import ffi_init_engine, ffi_simulate_trajectories, ffi_shutdown

# Same key as smoke tests
_TEST_KEY_HEX = "0" * 64


class TestIrisCoreSimulate:
    @pytest.fixture(scope="class")
    def engine(self):
        db_path = os.path.join(os.path.dirname(__file__), "..", "..", "test_sim.db")
        db_path = os.path.abspath(db_path)
        rc = ffi_init_engine(db_path, _TEST_KEY_HEX)
        yield rc
        ffi_shutdown()
        try:
            os.remove(db_path)
        except Exception:
            pass

    def test_simulate_small(self, engine):
        rows = ffi_simulate_trajectories(n=10, steps=5)
        assert rows == 50  # 10 × 5

    def test_simulate_medium(self, engine):
        rows = ffi_simulate_trajectories(n=50, steps=20)
        assert rows == 1000
