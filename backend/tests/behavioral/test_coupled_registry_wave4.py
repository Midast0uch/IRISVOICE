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
    """The two sessions end up with OPPOSITE-SIGNED nudges.

    Lower-energy session becomes the nucleus (negative nudge on a); the other
    becomes the barrier (positive nudge). Under the ownership rule each party
    writes only itself, so BOTH apply_coupling calls must run (as production
    does per session) for the bias to emerge — and neither is nudged twice.
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
        # Production calls apply_coupling on EACH session as it updates.
        reg.apply_coupling("nb_a")
        reg.apply_coupling("nb_b")
        after_a = ffi_caducean_get_state("nb_a")["a"]
        after_b = ffi_caducean_get_state("nb_b")["a"]
        da = after_a - before_a
        db = after_b - before_b
        assert da != 0.0 and db != 0.0
        # Opposite signs: one nucleus (negative), one barrier (positive).
        assert (da < 0) != (db < 0)
        # No double-application: each session is nudged by a single configured
        # nudge (<= 0.05), not 2x. A 2x bug would push |da| or |db| toward 0.04+.
        assert abs(da) < 0.05 and abs(db) < 0.05
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
        reg.apply_coupling("tie_b")
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


def test_three_session_accumulates():
    """Self's nudge accumulates across ALL partners and is written ONCE — the
    N>=3 lost-update is fixed (defect 1 from Wave 4 review).

    With 3 rational partners, A's final `a` must reflect BOTH B and C, not just
    the last partner written from a stale base.
    """
    tmp = _engine_tmp()
    try:
        ffi_caducean_init_session("three_a", 1, 1)
        ffi_caducean_init_session("three_b", 2, 2)
        ffi_caducean_init_session("three_c", 3, 3)
        reset_coupled_registry()
        reg = get_coupled_registry()
        reg.register_session("three_a", 1, 1)
        reg.register_session("three_b", 2, 2)
        reg.register_session("three_c", 3, 3)
        # All rational with each other (1:2, 1:3, 2:3). Aligned, distinct phases.
        reg.update_session_state("three_a", xi=1.0, u=0.3)
        reg.update_session_state("three_b", xi=1.05, u=0.3)
        reg.update_session_state("three_c", xi=1.10, u=0.3)
        before_a = ffi_caducean_get_state("three_a")["a"]
        reg.apply_coupling("three_a")
        after_a = ffi_caducean_get_state("three_a")["a"]
        # A is the lowest-energy session, so it is nucleus vs BOTH partners and
        # its nudge is the SUM of both contributions. A single partner's nudge
        # is <= 0.05, so a change > 0.05 proves BOTH partners contributed (the
        # buggy stale-base write would only reflect the last partner).
        assert abs(after_a - before_a) > 0.05
    finally:
        reset_coupled_registry()
        try:
            os.unlink(tmp)
        except OSError:
            pass


def test_each_party_writes_only_itself():
    """Ownership rule: a call writes ONLY self. Calling apply_coupling on A must
    NOT mutate B (no cross-write, so no double-application / 2x nudge — defect 2
    from Wave 4 review)."""
    tmp = _engine_tmp()
    try:
        ffi_caducean_init_session("own_a", 1, 1)
        ffi_caducean_init_session("own_b", 2, 2)
        reset_coupled_registry()
        reg = get_coupled_registry()
        reg.register_session("own_a", 1, 1)
        reg.register_session("own_b", 2, 2)
        reg.update_session_state("own_a", xi=1.0, u=0.3)
        reg.update_session_state("own_b", xi=1.05, u=-0.3)
        before_a = ffi_caducean_get_state("own_a")["a"]
        before_b = ffi_caducean_get_state("own_b")["a"]
        reg.apply_coupling("own_a")  # only A's call
        after_a = ffi_caducean_get_state("own_a")["a"]
        after_b = ffi_caducean_get_state("own_b")["a"]
        assert after_a != before_a  # A wrote itself
        assert after_b == before_b  # A did NOT write B
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
    """Domain map yields distinct c_eff values AND an irrational pair reachable
    using ONLY domain_windings() outputs (no hand-picked windings) — REQ-11 AC5
    (defect 3 from Wave 4 review: the irrational branch was previously only
    reachable by hand-registering (2,1)/(3,3))."""
    reset_coupled_registry()
    reg = get_coupled_registry()
    try:
        # Domain map produces three distinct c_eff values.
        reg.register_session("voice_sess", *domain_windings("voice"))  # (2,1) -> ~1.5811
        reg.register_session("der_sess", *domain_windings("der"))  # (1,1) -> 1.0
        reg.register_session("research_sess", *domain_windings("research"))  # (3,3) -> 3.0
        ce_v = reg.get_session("voice_sess").c_eff
        ce_d = reg.get_session("der_sess").c_eff
        ce_r = reg.get_session("research_sess").c_eff
        assert ce_v != ce_d and ce_v != ce_r and ce_d != ce_r
        # voice(2,1) : research(3,3) is sqrt5 : sqrt18 — the C1 irrational pair,
        # reachable from domain_windings() alone (not hand-registered).
        assert _is_rational_ratio(ce_v, ce_r) is False
        # Sanity: rational pairs are still detected (der:voice, der:research).
        assert _is_rational_ratio(ce_d, ce_v) is True
        assert _is_rational_ratio(ce_d, ce_r) is True
    finally:
        reset_coupled_registry()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
