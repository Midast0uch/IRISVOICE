"""
test_coupled_registry_wave4.py — Wave 4 verification for caducean-kernel-unification.

Covers REQ-8 (continuous sine coupling, no threshold gate), REQ-9 (nucleus/
barrier opposite-signed differentiation from a single call), REQ-10 (feature
flag + registration-once + partner cap), REQ-11 (distinct winding numbers,
irrational pair reachable), and REQ-19 AC4 (the opposite-signed nudge is
OBSERVABLE behavior, not merely a computed value).

These tests are ADDITIVE — the locked test_coupled_registry.py is untouched.
"""

import math
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.gateway.iris_ffi import (
    ffi_init_engine,
    ffi_caducean_init_session,
    ffi_caducean_get_state,
)
from backend.agent.coupled_registry import (
    get_coupled_registry,
    reset_coupled_registry,
    domain_windings,
    coupling_enabled,
    _is_rational_ratio,
    _MAX_COUPLED_SESSIONS,
)


def _engine_tmp():
    tmp = tempfile.mktemp(suffix=".db")
    ffi_init_engine(tmp, "00" * 32)
    return tmp


# ---------------------------------------------------------------------------
# REQ-8: continuous coupling — no threshold gate on whether coupling occurs
# ---------------------------------------------------------------------------


def test_continuous_coupling_no_threshold():
    """A pair just outside the OLD 0.1 rad alignment window must still couple.

    The prior discrete implementation gated on abs(xi1 - xi2) < 0.1 rad, so a
    pair 0.15 rad apart got NOTHING. Continuous coupling (align_force) must fire.
    """
    tmp = _engine_tmp()
    try:
        ffi_caducean_init_session("cw_a", 1, 1)
        ffi_caducean_init_session("cw_b", 2, 2)  # rational with (1,1)
        reset_coupled_registry()
        reg = get_coupled_registry()
        reg.register_session("cw_a", 1, 1)
        reg.register_session("cw_b", 2, 2)
        # Phase difference 0.15 rad — OUTSIDE the old 0.1 rad threshold.
        reg.update_session_state("cw_a", xi=1.0, u=0.3)
        reg.update_session_state("cw_b", xi=1.15, u=-0.3)
        events = reg.apply_coupling("cw_a")
        assert events >= 1
    finally:
        reset_coupled_registry()
        try:
            os.unlink(tmp)
        except OSError:
            pass


def test_continuous_coupling_wrap_aware():
    """A pair straddling 2π must be treated as close (wrap-aware)."""
    tmp = _engine_tmp()
    try:
        ffi_caducean_init_session("wa_a", 1, 1)
        ffi_caducean_init_session("wa_b", 2, 2)
        reset_coupled_registry()
        reg = get_coupled_registry()
        reg.register_session("wa_a", 1, 1)
        reg.register_session("wa_b", 2, 2)
        # 0.05 and 6.23 rad are ~0.10 rad apart on the circle (2π - 6.18).
        reg.update_session_state("wa_a", xi=0.05, u=0.3)
        reg.update_session_state("wa_b", xi=6.23, u=-0.3)
        events = reg.apply_coupling("wa_a")
        assert events >= 1
    finally:
        reset_coupled_registry()
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# REQ-9: nucleus/barrier differentiation — opposite-signed nudges (REQ-19 AC4)
# ---------------------------------------------------------------------------


def test_nucleus_barrier_opposite_signed():
    """One call must push the two sessions in OPPOSITE directions.

    Lower-energy session becomes the nucleus (negative nudge on a); the other
    becomes the barrier (positive nudge). Both nudges come from a single
    apply_coupling() call — this is what makes the differentiation emerge.
    """
    tmp = _engine_tmp()
    try:
        ffi_caducean_init_session("nb_a", 1, 1)
        ffi_caducean_init_session("nb_b", 2, 2)
        reset_coupled_registry()
        reg = get_coupled_registry()
        reg.register_session("nb_a", 1, 1)
        reg.register_session("nb_b", 2, 2)
        # Aligned phases; distinct energies so roles are deterministic.
        reg.update_session_state("nb_a", xi=1.0, u=0.3)  # lower energy -> nucleus
        reg.update_session_state("nb_b", xi=1.05, u=-0.3)  # higher -> barrier
        before_a = ffi_caducean_get_state("nb_a")["a"]
        before_b = ffi_caducean_get_state("nb_b")["a"]
        reg.apply_coupling("nb_a")
        after_a = ffi_caducean_get_state("nb_a")["a"]
        after_b = ffi_caducean_get_state("nb_b")["a"]
        da = after_a - before_a
        db = after_b - before_b
        assert da != 0.0 and db != 0.0
        # Opposite signs: one nucleus (negative), one barrier (positive).
        assert (da < 0) != (db < 0)
    finally:
        reset_coupled_registry()
        try:
            os.unlink(tmp)
        except OSError:
            pass


def test_nucleus_barrier_tie_breaks_by_session_id():
    """Equal ENERGY but distinct phase must still yield a stable, order-independent
    assignment via the session-id tie-breaker (REQ-9 AC2 edge case)."""
    tmp = _engine_tmp()
    try:
        ffi_caducean_init_session("tie_a", 1, 1)
        ffi_caducean_init_session("tie_b", 2, 2)
        reset_coupled_registry()
        reg = get_coupled_registry()
        reg.register_session("tie_a", 1, 1)
        reg.register_session("tie_b", 2, 2)
        # Equal energy (xi^2+u^2 == 1.0 for both) but distinct phase so force != 0.
        reg.update_session_state("tie_a", xi=0.6, u=0.8)  # 0.36 + 0.64 = 1.0
        reg.update_session_state("tie_b", xi=0.8, u=0.6)  # 0.64 + 0.36 = 1.0
        before_a = ffi_caducean_get_state("tie_a")["a"]
        before_b = ffi_caducean_get_state("tie_b")["a"]
        reg.apply_coupling("tie_a")
        after_a = ffi_caducean_get_state("tie_a")["a"]
        after_b = ffi_caducean_get_state("tie_b")["a"]
        da = after_a - before_a
        db = after_b - before_b
        assert da != 0.0 and db != 0.0
        assert (da < 0) != (db < 0)
    finally:
        reset_coupled_registry()
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# REQ-10: feature flag, registration-once, partner cap
# ---------------------------------------------------------------------------


def test_coupling_flag_off_by_default(monkeypatch):
    """Multi-session coupling ships DISABLED (REQ-10 AC4)."""
    monkeypatch.delenv("IRIS_COUPLING_ENABLED", raising=False)
    assert coupling_enabled() is False
    monkeypatch.setenv("IRIS_COUPLING_ENABLED", "1")
    assert coupling_enabled() is True
    monkeypatch.setenv("IRIS_COUPLING_ENABLED", "0")
    assert coupling_enabled() is False


def test_ensure_registered_once():
    """Registration returns True only on first call (REQ-10 AC1)."""
    reset_coupled_registry()
    reg = get_coupled_registry()
    try:
        assert reg.ensure_registered("er_1", 1, 1) is True
        # Idempotent: same session returns False, no re-init.
        assert reg.ensure_registered("er_1", 1, 1) is False
        assert reg.ensure_registered("er_2", 2, 2) is True
    finally:
        reset_coupled_registry()


def test_max_partners_cap():
    """apply_coupling considers at most MAX_COUPLED_SESSIONS partners (REQ-10 AC6)."""
    reset_coupled_registry()
    reg = get_coupled_registry()
    try:
        reg.register_session("cap_self", 1, 1)
        for i in range(_MAX_COUPLED_SESSIONS + 5):
            reg.register_session("cap_p%d" % i, 1, 1)
        for i in range(_MAX_COUPLED_SESSIONS + 5):
            reg.update_session_state("cap_p%d" % i, xi=1.0, u=0.0)
        reg.update_session_state("cap_self", xi=1.0, u=0.0)
        events = reg.apply_coupling("cap_self")
        assert events == _MAX_COUPLED_SESSIONS
    finally:
        reset_coupled_registry()


# ---------------------------------------------------------------------------
# REQ-11: distinct winding numbers per domain; irrational pair reachable
# ---------------------------------------------------------------------------


def test_distinct_windings_and_irrational():
    """Domain mapping yields distinct c_eff; an irrational pair is reachable."""
    reset_coupled_registry()
    reg = get_coupled_registry()
    try:
        # Domain mapping produces at least two distinct c_eff values.
        reg.register_session("voice_sess", *domain_windings("voice"))  # (2,2)->2.0
        reg.register_session("der_sess", *domain_windings("der"))  # (1,1)->1.0
        assert reg.get_session("voice_sess").c_eff != reg.get_session("der_sess").c_eff
        # Force an irrational pair (spec Q3): (2,1) vs (3,3).
        reg.register_session("irr_x", 2, 1)  # c_eff ~1.5811
        reg.register_session("irr_y", 3, 3)  # c_eff 3.0
        assert (
            _is_rational_ratio(
                reg.get_session("irr_x").c_eff, reg.get_session("irr_y").c_eff
            )
            is False
        )
        # Sanity: a rational pair is still detected.
        assert (
            _is_rational_ratio(
                reg.get_session("voice_sess").c_eff,
                reg.get_session("der_sess").c_eff,
            )
            is True
        )
    finally:
        reset_coupled_registry()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
