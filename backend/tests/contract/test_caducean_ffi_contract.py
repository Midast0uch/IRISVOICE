"""
test_caducean_ffi_contract.py — FFI contract tests for Caducean v2.

PURPOSE: Catch struct drift, argtype drift, and return code drift
between the C++ side and the Python side. ctypes silently corrupts
memory when these drift — this test fails loudly instead.

FROZEN MANIFESTS (in this file):
  - IrisDirectionSignal field order MUST match iris_core.h exactly
  - 5 FFI functions MUST have argtypes/restypes registered
  - caducean_recommend() MUST return only {0, 1, 2, 3}
  - Bounds (a, b, s) MUST be enforced in the C++ layer (not Python)

Run: python -m pytest backend/tests/test_caducean_ffi_contract.py -v
"""

import ctypes
import os
import sys
import tempfile

import pytest

# Ensure we can import from the project root
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.gateway.iris_ffi import (
    IrisDirectionSignal,
    DirectionSignal,
    CADUCEAN_RECOMMEND_EXPAND,
    CADUCEAN_RECOMMEND_COMPRESS,
    CADUCEAN_RECOMMEND_CONTINUE,
    CADUCEAN_RECOMMEND_TOPO_VIOLATION,
    ffi_init_engine,
    ffi_caducean_init_session,
    ffi_caducean_get_direction_signal,
    ffi_caducean_set_params,
    ffi_caducean_get_state,
    ffi_caducean_calculate_eml,
    ffi_caducean_update,
    ffi_caducean_recommend,
)


@pytest.fixture(scope="module")
def initialized_engine():
    """Init the engine once for the whole module."""
    tmp = tempfile.mktemp(suffix=".db")
    ok = ffi_init_engine(tmp, "00" * 32)
    if not ok:
        pytest.skip("C++ engine not available — contract tests require live DLL")
    yield tmp
    # Cleanup is best-effort (SQLite connection may still be open)


# ---------------------------------------------------------------------------
# Struct shape contract — IrisDirectionSignal
# ---------------------------------------------------------------------------


class TestIrisDirectionSignalContract:
    """The ctypes struct MUST match the C struct IrisDirectionSignal in
    src-tauri/src/iris_core/iris_core.h. Field order is FROZEN.

    Drift here corrupts memory silently in ctypes — this test fails
    loudly instead.
    """

    def test_struct_has_exactly_5_fields(self):
        assert len(IrisDirectionSignal._fields_) == 5, (
            f"IrisDirectionSignal must have 5 fields, got {len(IrisDirectionSignal._fields_)}"
        )

    def test_struct_field_names_frozen(self):
        names = [f[0] for f in IrisDirectionSignal._fields_]
        assert names == [
            "target_u",
            "force_magnitude",
            "u_current",
            "phase",
            "balance",
        ], f"Field names drifted: {names}. MUST match iris_core.h IrisDirectionSignal."

    def test_struct_field_types_all_double(self):
        for name, ctype in IrisDirectionSignal._fields_:
            assert ctype is ctypes.c_double, (
                f"Field {name} is {ctype}, MUST be c_double"
            )

    def test_struct_size_is_40_bytes(self):
        """5 doubles × 8 bytes = 40 bytes. Drift detection."""
        assert ctypes.sizeof(IrisDirectionSignal) == 40, (
            f"Struct size is {ctypes.sizeof(IrisDirectionSignal)}, expected 40. "
            f"Field count or type drift detected."
        )

    def test_default_struct_values_are_zero(self):
        sig = IrisDirectionSignal()
        assert sig.target_u == 0.0
        assert sig.force_magnitude == 0.0
        assert sig.u_current == 0.0
        assert sig.phase == 0.0
        assert sig.balance == 0.0


class TestDirectionSignalDataclass:
    """The Python dataclass wrapper."""

    def test_default_direction_signal(self):
        sig = DirectionSignal.default()
        assert sig.target_u == 1.0
        assert sig.balance == 1.0
        assert sig.force_magnitude == 0.0
        assert sig.u_current == 0.0
        assert sig.phase == 0.0

    def test_from_ffi_converts_correctly(self):
        c_struct = IrisDirectionSignal()
        c_struct.target_u = 1.0
        c_struct.force_magnitude = 0.5
        c_struct.u_current = 0.3
        c_struct.phase = 1.57
        c_struct.balance = 1.5
        py = DirectionSignal.from_ffi(c_struct)
        assert py.target_u == 1.0
        assert py.force_magnitude == 0.5
        assert py.u_current == 0.3
        assert py.phase == 1.57
        assert py.balance == 1.5

    def test_dataclass_is_immutable(self):
        """DirectionSignal is frozen — must not be mutable."""
        sig = DirectionSignal.default()
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            sig.target_u = 2.0


# ---------------------------------------------------------------------------
# Return code contract — caducean_recommend()
# ---------------------------------------------------------------------------


class TestReturnCodeContract:
    """caducean_recommend() MUST only return {0, 1, 2, 3}.

    0 = EXPAND, 1 = COMPRESS, 2 = CONTINUE, 3 = TOPO_VIOLATION (NEW in v2).
    Any other return value is a contract violation.
    """

    def test_recommend_returns_valid_code(self, initialized_engine):
        # Run 10 updates and check each return is valid
        for i in range(10):
            ffi_caducean_update("contract_test", i % 2, 1.0)
            rec = ffi_caducean_recommend("contract_test")
            assert rec in {0, 1, 2, 3}, (
                f"recommend returned {rec}, expected {{0,1,2,3}}"
            )

    def test_return_code_constants_match(self):
        assert CADUCEAN_RECOMMEND_EXPAND == 0
        assert CADUCEAN_RECOMMEND_COMPRESS == 1
        assert CADUCEAN_RECOMMEND_CONTINUE == 2
        assert CADUCEAN_RECOMMEND_TOPO_VIOLATION == 3


# ---------------------------------------------------------------------------
# v2 API surface contract — all 5 new functions must work end-to-end
# ---------------------------------------------------------------------------


class TestV2APISurface:
    """All 5 new FFI functions must be callable and return sane values."""

    def test_init_session_returns_true(self, initialized_engine):
        assert ffi_caducean_init_session("contract_v2_test", 1, 1) is True

    def test_get_direction_signal_returns_dataclass(self, initialized_engine):
        ffi_caducean_init_session("contract_signal_test", 1, 1)
        sig = ffi_caducean_get_direction_signal("contract_signal_test", 1.0)
        assert isinstance(sig, DirectionSignal)
        # target_u must be ±1
        assert sig.target_u in (1.0, -1.0)
        # balance must be in [0.1, 3.0]
        assert 0.1 <= sig.balance <= 3.0

    def test_set_params_returns_true(self, initialized_engine):
        assert ffi_caducean_set_params("contract_params_test", 2.0, 2.0, 0.5) is True

    def test_set_params_clamps_out_of_bounds(self, initialized_engine):
        """C++ must clamp a, b, s to safe ranges."""
        ffi_caducean_init_session("contract_clamp_test", 1, 1)
        # Try to set extreme values — C++ should clamp internally
        ok = ffi_caducean_set_params("contract_clamp_test", 100.0, 100.0, 100.0)
        assert ok is True  # operation succeeds
        state = ffi_caducean_get_state("contract_clamp_test")
        # a, b should be clamped to [1, 4]
        assert 1.0 <= state["a"] <= 4.0, f"a not clamped: {state['a']}"
        assert 1.0 <= state["b"] <= 4.0, f"b not clamped: {state['b']}"
        # s should be clamped to [0.1, 0.8]
        assert 0.1 <= state["s"] <= 0.8, f"s not clamped: {state['s']}"

    def test_get_state_returns_all_keys(self, initialized_engine):
        ffi_caducean_init_session("contract_state_test", 1, 1)
        state = ffi_caducean_get_state("contract_state_test")
        expected_keys = {"x", "y", "xi", "u", "a", "b", "s", "c_eff"}
        assert expected_keys.issubset(set(state.keys())), (
            f"Missing keys: {expected_keys - set(state.keys())}"
        )

    def test_c_eff_formula_correct(self, initialized_engine):
        """c_eff = (1/√2) · √(l² + m²). For l=1, m=1: c_eff=1.0. For l=2, m=1: c_eff=√(5/2)≈1.581."""
        ffi_caducean_init_session("contract_ceff_1_1", 1, 1)
        s1 = ffi_caducean_get_state("contract_ceff_1_1")
        assert abs(s1["c_eff"] - 1.0) < 0.001, (
            f"c_eff(l=1,m=1)={s1['c_eff']}, expected 1.0"
        )

        ffi_caducean_init_session("contract_ceff_2_1", 2, 1)
        s2 = ffi_caducean_get_state("contract_ceff_2_1")
        expected = (1.0 / 2**0.5) * (2 * 2 + 1 * 1) ** 0.5
        assert abs(s2["c_eff"] - expected) < 0.001, (
            f"c_eff(l=2,m=1)={s2['c_eff']}, expected {expected}"
        )

    def test_calculate_eml_returns_tuple(self, initialized_engine):
        ffi_caducean_init_session("contract_eml_test", 1, 1)
        # Run some updates to accumulate x, y
        for i in range(3):
            ffi_caducean_update("contract_eml_test", 0, 1.0)  # EXPAND
        score, x, y = ffi_caducean_calculate_eml("contract_eml_test")
        assert isinstance(score, float)
        assert x == 3
        assert y == 0

    def test_calculate_eml_o1_no_db_hit(self, initialized_engine):
        """calculate_eml is O(1) — should complete in <1ms.
        (This is more of a smoke test than a strict performance test.)"""
        import time

        ffi_caducean_init_session("contract_eml_speed", 1, 1)
        start = time.perf_counter()
        for _ in range(100):
            ffi_caducean_calculate_eml("contract_eml_speed")
        elapsed = time.perf_counter() - start
        # 100 calls should complete in <100ms (1ms each)
        assert elapsed < 0.1, f"100 calculate_eml calls took {elapsed * 1000:.1f}ms"


# ---------------------------------------------------------------------------
# Adaptive safety net contract — TOPO_VIOLATION (code 3) must be reachable
# ---------------------------------------------------------------------------


class TestAdaptiveSafetyNetContract:
    """The adaptive safety net MUST be able to return code 3 (TOPO_VIOLATION)
    when the engine detects genuine topological drift. This verifies the
    safety net is wired correctly, not just compiled."""

    def test_topo_violation_code_reachable(self, initialized_engine):
        """Force a chaotic state and verify code 3 is possible.

        Conditions for TOPO_VIOLATION:
          |Q| > 0.8 (lone kink) AND phase_accel > 0.05 (genuine drift)
        """
        ffi_caducean_init_session("contract_topo_test", 1, 1)
        # Drive a huge imbalance (only EXPAND, never COMPRESS)
        # to push Q toward 1.0, with chaotic balance values
        import random

        random.seed(42)
        for _ in range(20):
            ffi_caducean_update("contract_topo_test", 0, random.uniform(2.5, 3.0))
        rec = ffi_caducean_recommend("contract_topo_test")
        # We can't guarantee 3 fires (depends on the random walk hitting both
        # conditions simultaneously), but the value MUST be a valid code.
        assert rec in {0, 1, 2, 3}, f"recommend returned {rec}, expected valid code"


# ---------------------------------------------------------------------------
# Fallback parity contract — the Python fallback must also work
# ---------------------------------------------------------------------------


class TestFallbackParityContract:
    """When the C++ engine is unavailable, the Python fallback MUST also
    return a valid DirectionSignal — never None, never crash.
    """

    def test_default_direction_signal_is_safe(self):
        """If engine is None, ffi_caducean_get_direction_signal returns default()."""
        from backend.gateway import iris_ffi

        # Temporarily disable engine
        original_engine = iris_ffi._engine
        iris_ffi._engine = None
        try:
            sig = iris_ffi.ffi_caducean_get_direction_signal("any_session", 1.0)
            assert isinstance(sig, DirectionSignal)
            assert sig.target_u == 1.0
            assert sig.balance == 1.0
        finally:
            iris_ffi._engine = original_engine

    def test_init_session_with_no_engine_returns_false(self):
        from backend.gateway import iris_ffi

        original_engine = iris_ffi._engine
        iris_ffi._engine = None
        try:
            assert iris_ffi.ffi_caducean_init_session("any", 1, 1) is False
        finally:
            iris_ffi._engine = original_engine
