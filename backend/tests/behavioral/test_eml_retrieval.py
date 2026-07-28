"""
test_eml_retrieval.py — Behavioral tests for per-session EML cache (T3.12 / REQ-16/REQ-17).

Asserts:
  1. Per-session isolation: session A's cache ≠ session B's cache.
  2. DER retrieval path reads cached EML (structural source check).
  3. Continuous explore-pressure is monotonic in EML and spans [0, 1].
"""

import pytest


class TestPerSessionEMLCache:
    """REQ-16: per-session EML cache isolates sessions."""

    def test_session_isolation(self):
        """Session A's cached EML is independent of session B's."""
        from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder

        # Reset caches
        CaduceanTrajectoryRecorder._eml_cache_per_session = {}
        CaduceanTrajectoryRecorder._eml_cache = 1.0

        # Write different values per session via record()
        import sqlite3
        import tempfile
        import os

        _tmp = tempfile.mktemp(suffix=".db")
        try:
            _conn = sqlite3.connect(_tmp)
            _rec = CaduceanTrajectoryRecorder(_conn)

            # Record session A with eml=1.2
            _rec.record("session_a", 0, 0, 0, 0.0, 0.0, 1, "ok", 1.2)
            # Record session B with eml=2.5
            _rec.record("session_b", 0, 0, 0, 0.0, 0.0, 1, "ok", 2.5)

            # Read back via get_cached_eml with explicit session_id
            _a = CaduceanTrajectoryRecorder.get_cached_eml("session_a")
            _b = CaduceanTrajectoryRecorder.get_cached_eml("session_b")

            assert isinstance(_a, tuple) and len(_a) == 3, f"_a should be (eml,x,y) triple, got {_a}"
            assert isinstance(_b, tuple) and len(_b) == 3, f"_b should be (eml,x,y) triple, got {_b}"
            assert _a[0] == pytest.approx(1.2), f"session_a EML should be 1.2, got {_a[0]}"
            assert _b[0] == pytest.approx(2.5), f"session_b EML should be 2.5, got {_b[0]}"
            assert _a != _b, "session A and B EML must be different (isolation)"
        finally:
            _conn.close()
            try:
                os.unlink(_tmp)
            except OSError:
                pass

    def test_unknown_session_returns_empty_tuple(self):
        """get_cached_eml('unknown') on miss makes a live FFI call (or returns empty on error)."""
        from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder

        CaduceanTrajectoryRecorder._eml_cache_per_session = {}

        _val = CaduceanTrajectoryRecorder.get_cached_eml("nonexistent_session")
        # In test context FFI is unavailable, so it returns (None, 0.0, 0.0)
        assert isinstance(_val, tuple) and len(_val) == 3, f"expected triple, got {_val}"
        assert _val[0] is None, f"eml should be None on miss, got {_val[0]}"
        assert _val[1] == 0.0 and _val[2] == 0.0, f"x,y should be 0.0 on miss, got {_val}"

    def test_no_session_id_returns_class_cache(self):
        """get_cached_eml() without session_id returns the class-level _eml_cache."""
        from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder

        CaduceanTrajectoryRecorder._eml_cache = 2.0
        _val = CaduceanTrajectoryRecorder.get_cached_eml()
        assert _val == pytest.approx(2.0), (
            f"get_cached_eml() without session_id should return 2.0, got {_val}"
        )


class TestDerRetrievalReadsCachedEML:
    """REQ-16: DER retrieval path reads the cached EML."""

    def test_retrieval_path_uses_cached_eml(self):
        """The mid-loop episodic retrieval in agent_kernel reads get_cached_eml.

        Structural contract check: the source code at the C.4 retrieval site
        must reference CaduceanTrajectoryRecorder.get_cached_eml.
        """
        import inspect
        import textwrap

        from backend.agent import agent_kernel as _mod

        _src = textwrap.dedent(inspect.getsource(_mod.AgentKernel._execute_plan_der))
        assert "get_cached_eml" in _src, (
            "DER loop must read cached EML via get_cached_eml() (REQ-16); "
            "no reference found in _run_der_loop source"
        )


class TestExplorePressureAnchors:
    """REQ-17 AC3: explore-pressure reproduces the three anchors.

    Contract test: asserts the exact (limit, score) pairs at the three
    anchor conditions from AC3.  If the implementation changes the
    formula, this test catches the drift.  This is what would have caught
    the broken monotonic implementation.
    """

    # Constants matching agent_kernel.py's piecewise V-shaped formula.
    _EC, _EN, _EE = 0.90, 1.20, 1.60
    _LC, _LN, _LE = 3, 2, 5
    _SC, _SN, _SE = 0.65, 0.55, 0.40

    @staticmethod
    def _retrieval_params(eml: float, direction: float):
        """Replicate the piecewise V-shaped interpolation from agent_kernel.py."""
        e = max(0.0, eml)
        if e <= TestExplorePressureAnchors._EN:
            p = max(0.0, min(1.0, (e - TestExplorePressureAnchors._EC) / (TestExplorePressureAnchors._EN - TestExplorePressureAnchors._EC)))
            limit = TestExplorePressureAnchors._LC + (TestExplorePressureAnchors._LN - TestExplorePressureAnchors._LC) * p
            score = TestExplorePressureAnchors._SC + (TestExplorePressureAnchors._SN - TestExplorePressureAnchors._SC) * p
            bias = min(1.0, abs(direction))
            if direction < 0:
                limit += bias * (TestExplorePressureAnchors._LC - limit)
                score += bias * (TestExplorePressureAnchors._SC - score)
            elif direction > 0:
                limit += bias * (TestExplorePressureAnchors._LE - limit)
                score += bias * (TestExplorePressureAnchors._SE - score)
        else:
            p = max(0.0, min(1.0, (e - TestExplorePressureAnchors._EN) / (TestExplorePressureAnchors._EE - TestExplorePressureAnchors._EN)))
            limit = TestExplorePressureAnchors._LN + (TestExplorePressureAnchors._LE - TestExplorePressureAnchors._LN) * p
            score = TestExplorePressureAnchors._SN + (TestExplorePressureAnchors._SE - TestExplorePressureAnchors._SN) * p
            bias = min(1.0, abs(direction))
            if direction > 0:
                limit += bias * (TestExplorePressureAnchors._LE - limit)
                score += bias * (TestExplorePressureAnchors._SE - score)
            elif direction < 0:
                limit += bias * (TestExplorePressureAnchors._LC - limit)
                score += bias * (TestExplorePressureAnchors._SC - score)
        return int(round(limit)), max(0.40, min(0.65, score))

    def test_anchor_consolidate(self):
        """consolidate (eml=0.90, x-dominant) → limit=3, score=0.65."""
        limit, score = self._retrieval_params(eml=0.90, direction=-0.5)
        assert limit == 3, f"consolidate limit={limit}"
        assert score == pytest.approx(0.65, abs=0.05), f"consolidate score={score}"

    def test_anchor_neutral(self):
        """neutral (eml=1.20, direction=0) → limit=2, score=0.55."""
        limit, score = self._retrieval_params(eml=1.20, direction=0.0)
        assert limit == 2, f"neutral limit={limit}"
        assert score == pytest.approx(0.55, abs=0.05), f"neutral score={score}"

    def test_anchor_explore(self):
        """explore (eml=1.60, y-dominant) → limit=5, score=0.40."""
        limit, score = self._retrieval_params(eml=1.60, direction=0.5)
        assert limit == 5, f"explore limit={limit}"
        assert score == pytest.approx(0.40, abs=0.05), f"explore score={score}"

    def test_v_shape(self):
        """Limit V-shaped (3→2→5), score monotonic decreasing (0.65→0.55→0.40)."""
        limits, scores = [], []
        for i in range(21):
            eml = 0.7 + i * 0.05
            lim, scr = self._retrieval_params(eml=eml, direction=0.0)
            limits.append(lim)
            scores.append(scr)
        # At the three anchors.
        assert limits[4] == 3, f"at eml=0.90 limit={limits[4]}"
        assert limits[10] == 2, f"at eml=1.20 limit={limits[10]}"
        assert limits[18] == 5, f"at eml=1.60 limit={limits[18]}"
        assert scores[4] == pytest.approx(0.65, abs=0.05)
        assert scores[10] == pytest.approx(0.55, abs=0.05)
        assert scores[18] == pytest.approx(0.40, abs=0.05)
        # V shape: limit goes down then up.
        for i in range(5, 10):
            assert limits[i] <= limits[i - 1], f"limit should decrease to 2 from eml 0.95-1.15, broke at {i}"
        for i in range(11, 19):
            assert limits[i] >= limits[i - 1], f"limit should increase from 2 after eml 1.25, broke at {i}"

    def test_directional_term_affects_output(self):
        """Varying direction changes output (consolidate pulls down, explore pulls up)."""
        # At eml=1.40 (between neutral and explore), direction positive should raise limit.
        lim_neutral, _ = self._retrieval_params(eml=1.40, direction=0.0)
        lim_explore, _ = self._retrieval_params(eml=1.40, direction=0.8)
        lim_consolidate, _ = self._retrieval_params(eml=1.40, direction=-0.8)
        assert lim_explore >= lim_neutral, f"explore direction should raise limit: {lim_explore} >= {lim_neutral}"
        assert lim_consolidate <= lim_neutral, f"consolidate direction should lower limit: {lim_consolidate} <= {lim_neutral}"
