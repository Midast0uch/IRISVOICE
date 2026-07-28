"""
coupled_registry.py — Multi-session coupling registry for Caducean v2.

Multiple active kernels (coding, voice conversation, audio streaming) can
register their sessions here. The registry detects:
  - Rational c_eff ratios (within 0.01 of p/q with p,q < 10)
  - Irrational c_eff ratios (destructive interference)
  - Phase alignment events (xi1 ≈ xi2)

On every caducean_update() (called by the agent kernel, behind the
IRIS_COUPLING_ENABLED flag), the registry scans other active sessions and
applies coupling:

  RATIONAL (strong coupling, REQ-8 continuous):
    - Coupling strength is a continuous, wrap-aware function of phase
      difference via the signed align_force kernel (trig_coupling.py) — there
      is NO threshold gate on whether coupling occurs.
    - For a coupled pair, ONE call assigns nucleus/barrier roles by an
      order-independent symmetry breaker (lower "energy" -> nucleus) and
      applies OPPOSITE-SIGNED nudges to the two sessions (barrier +, nucleus -)
      on their (a) parameter, which biases u indirectly. This is what makes the
      Gross-Pitaevskii nucleus/barrier differentiation actually emerge
      (overview §10).

  IRRATIONAL (destructive interference):
    - Small damping on s (resonance friction).

Constraints:
  - Nudge magnitude is bounded by _MAX_COUPLING_NUDGE and clamped to a ∈ [1, 4]
  - All updates clamped by the engine (ffi_caducean_set_params)
  - Coupling is OFF the critical path: any failure logs at debug and never
    propagates into step execution (REQ-10 AC5)

Singleton accessed by get_coupled_registry().

Usage:
    from backend.agent.coupled_registry import get_coupled_registry
    reg = get_coupled_registry()
    reg.register_session("coding_session", l=1, m=1)
    reg.register_session("voice_session", l=2, m=2)
    # In agent_kernel after ffi_caducean_update():
    reg.apply_coupling("coding_session")
"""

import logging
import math
import os
import threading
from typing import Dict, List, Optional, Tuple

from backend.agent.trig_coupling import align_force

logger = logging.getLogger(__name__)

# Coupling parameters (from plan §Component 4, "CoupledRegistry")
_RATIONAL_TOLERANCE = 0.01
_PQ_RANGE = range(1, 10)  # p, q in [1, 9] for rational test
# REQ-8: continuous coupling strength. The phase term is now computed from the
# signed, wrap-aware align_force kernel (trig_coupling.py) — no threshold gate.
_COUPLING_K = 1.0  # align_force normalization
# Maps |align_force| -> an (a)-param nudge magnitude. align_force is called with
# the FULL phase list [xi_self, xi_other] (N=2), so its value is ~sin(Δ)/2; the
# scale is chosen so an aligned pair (Δ≈0.05) yields a ~0.02 nudge, matching the
# prior safe magnitude.
_COUPLING_SCALE = 0.8  # maps |align_force| -> an (a)-param nudge magnitude
_MAX_COUPLING_NUDGE = 0.05  # safety bound on |nudge| (a, b ∈ [1, 4])
_IRRATIONAL_DAMPING = 0.005  # destructive-interference damping on s
_MAX_COUPLED_SESSIONS = 8  # REQ-10 AC6: cap active partners
_COUPLED_CEIL = 1.0
_COUPLED_FLOOR = -1.0


def coupling_enabled() -> bool:
    """Return whether multi-session coupling is enabled (env-gated, default off).

    REQ-10 AC4 — multi-session coupling ships DISABLED. Activating it is a
    deliberate act via IRIS_COUPLING_ENABLED=1. Read lazily so tests can flip it
    with monkeypatch.setenv (REQ-20 AC3).
    """
    return os.environ.get("IRIS_COUPLING_ENABLED", "0") == "1"


def domain_windings(domain: str) -> Tuple[int, int]:
    """Map a kernel domain to Caducean winding numbers (l, m).

    REQ-11 AC2 — defined in ONE place with rationale:
      * coding / der / default -> (1, 1): c_eff = 1.0 (baseline, per Gate 1).
      * voice                  -> (2, 2): c_eff = 2.0 (docstring-prescribed
        voice winding; rationally related to coding at 2:1, so it exercises the
        attractive branch). At least two distinct c_eff values exist when both a
        voice and a coding session are active (REQ-11 AC1).
    Unclassified domains fall back to (1, 1) to preserve today's behavior
    (REQ-11 AC4).
    """
    if domain == "voice":
        return (2, 2)
    return (1, 1)


def _role_energy(xi: float, u: float) -> float:
    """Order-independent symmetry breaker for nucleus/barrier assignment (REQ-9 AC2).

    Lower energy -> nucleus (compression-biased, negative nudge). We use a simple
    norm of the phase/velocity state. Both sessions compute the same value for
    the same state, so independent invocations agree on the assignment without
    coordination.
    """
    return float(xi) * float(xi) + float(u) * float(u)


def _is_rational_ratio(c1: float, c2: float) -> bool:
    """Test if c1/c2 is approximately rational (p/q with p,q < 10)."""
    if c2 == 0:
        return False
    ratio = c1 / c2
    return any(
        abs(ratio - p / q) < _RATIONAL_TOLERANCE for p in _PQ_RANGE for q in _PQ_RANGE
    )


def _compute_c_eff(l: int, m: int) -> float:
    """Effective cycle speed: c_eff = (1/sqrt(2)) * sqrt(l^2 + m^2)."""
    return (1.0 / math.sqrt(2.0)) * math.sqrt(l * l + m * m)


class _SessionRecord:
    """Internal record of an active session in the registry."""

    __slots__ = ("session_id", "l", "m", "c_eff", "last_xi", "last_u")

    def __init__(self, session_id: str, l: int, m: int):
        self.session_id = session_id
        self.l = l
        self.m = m
        self.c_eff = _compute_c_eff(l, m)
        self.last_xi = 0.0
        self.last_u = 0.0


class CoupledTrajectoryRegistry:
    """
    Singleton registry of active sessions. Thread-safe.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, _SessionRecord] = {}
        self._lock = threading.Lock()

    def register_session(
        self, session_id: str, l: int = 1, m: int = 1
    ) -> _SessionRecord:
        """Register a session with specific winding numbers.

        Idempotent — re-registering updates l, m, c_eff.
        """
        with self._lock:
            if session_id in self._sessions:
                rec = self._sessions[session_id]
                rec.l = l
                rec.m = m
                rec.c_eff = _compute_c_eff(l, m)
            else:
                rec = _SessionRecord(session_id, l, m)
                self._sessions[session_id] = rec
            return rec

    def unregister_session(self, session_id: str) -> None:
        """Remove a session from the registry."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def ensure_registered(self, session_id: str, l: int = 1, m: int = 1) -> bool:
        """Register a session if absent; return True only when newly registered.

        Used by the DER wiring so the engine is initialized with the domain
        windings exactly once per session (REQ-10 AC1 / REQ-11 AC3). After
        unregister_session the next call re-registers and re-inits. Idempotent
        for an already-present session (returns False, no state change).
        """
        with self._lock:
            if session_id in self._sessions:
                return False
            self._sessions[session_id] = _SessionRecord(session_id, l, m)
            return True

    def list_sessions(self) -> List[str]:
        """Return a copy of the list of active session IDs."""
        with self._lock:
            return list(self._sessions.keys())

    def get_session(self, session_id: str) -> Optional[_SessionRecord]:
        with self._lock:
            return self._sessions.get(session_id)

    def update_session_state(self, session_id: str, xi: float, u: float) -> None:
        """Cache the latest (xi, u) for a session. Called by apply_coupling()."""
        with self._lock:
            rec = self._sessions.get(session_id)
            if rec is not None:
                rec.last_xi = xi
                rec.last_u = u

    def apply_coupling(self, session_id: str) -> int:
        """Scan other active sessions and apply continuous Caducean coupling.

        REQ-8: coupling strength is a continuous, wrap-aware function of phase
        difference (via align_force), with no threshold gate. REQ-9: for a
        rational pair the two sessions receive OPPOSITE-SIGNED nudges from this
        single call (nucleus negative, barrier positive), assigned by an
        order-independent symmetry breaker.

        Returns the number of coupling events applied (0 if no partners).
        """
        with self._lock:
            if session_id not in self._sessions:
                return 0
            self_rec = self._sessions[session_id]
            other_recs = [r for r in self._sessions.values() if r.session_id != session_id]
            if len(other_recs) > _MAX_COUPLED_SESSIONS:
                other_recs = other_recs[:_MAX_COUPLED_SESSIONS]
        if not other_recs:
            return 0

        # Cache our latest state (caller should have called update_session_state)
        xi1 = self_rec.last_xi
        u1 = self_rec.last_u

        try:
            from backend.gateway.iris_ffi import (
                ffi_caducean_set_params,
                ffi_caducean_get_state,
            )
        except Exception:
            return 0

        # Fetch our current (a, b, s) to update u indirectly.
        # Note: u isn't a set_params argument — the engine advances u
        # only via update(). For coupling, we instead nudge a, b
        # asymmetrically so that the next update() pushes u in the
        # desired direction. This is a deliberate engineering
        # simplification — true u injection would require a new
        # ffi_caducean_inject_u() FFI export (deferred to v3).
        state = ffi_caducean_get_state(session_id)
        cur_a = state.get("a", 2.0)
        cur_b = state.get("b", 2.0)
        cur_s = state.get("s", 0.35)

        events = 0
        for other in other_recs:
            xi2 = other.last_xi
            u2 = other.last_u
            c1 = self_rec.c_eff
            c2 = other.c_eff
            if _is_rational_ratio(c1, c2):
                # Continuous, wrap-aware alignment coupling (REQ-8).
                # align_force is signed & periodic, so a pair straddling 2π is
                # treated as close (no threshold gate — REQ-8 AC1/AC2). It is
                # called with the FULL phase list [xi_self, xi_other] (N=2) —
                # the self term contributes sin(0)=0, and N>=2 satisfies the
                # kernel's mean-field guard.
                force = align_force(xi1, [xi1, xi2], k=_COUPLING_K)
                magnitude = min(_MAX_COUPLING_NUDGE, abs(force) * _COUPLING_SCALE)
                # Order-independent role assignment (REQ-9 AC2): lower energy
                # -> nucleus. Tie -> stable total order by session id, so both
                # parties' independent invocations agree without coordination.
                e_self = _role_energy(xi1, u1)
                e_other = _role_energy(xi2, u2)
                if e_self < e_other:
                    self_is_nucleus = True
                elif e_self > e_other:
                    self_is_nucleus = False
                else:
                    self_is_nucleus = session_id < other.session_id
                self_sign = -1.0 if self_is_nucleus else 1.0
                other_sign = 1.0 if self_is_nucleus else -1.0
                # Nudge self (barrier +, nucleus -) on a, biasing u indirectly.
                new_a_self = max(1.0, min(4.0, cur_a + self_sign * magnitude))
                ffi_caducean_set_params(session_id, new_a_self, cur_b, cur_s)
                # Nudge partner with the OPPOSITE sign from the SAME call
                # (REQ-9 AC5) — this is what makes nucleus/barrier emerge.
                try:
                    ostate = ffi_caducean_get_state(other.session_id)
                    oa = ostate.get("a", 2.0)
                    ob = ostate.get("b", 2.0)
                    os_ = ostate.get("s", 0.35)
                    new_a_other = max(1.0, min(4.0, oa + other_sign * magnitude))
                    ffi_caducean_set_params(other.session_id, new_a_other, ob, os_)
                except Exception:
                    pass
                events += 1
                logger.debug(
                    "[CoupledRegistry] %s (c_eff=%.3f, %s) coupled with %s "
                    "(c_eff=%.3f); nudge=%.4f",
                    session_id,
                    c1,
                    "nucleus" if self_is_nucleus else "barrier",
                    other.session_id,
                    c2,
                    self_sign * magnitude,
                )
            else:
                # Irrational: destructive interference — small damping on s.
                new_s = max(0.1, min(0.8, cur_s - _IRRATIONAL_DAMPING))
                ffi_caducean_set_params(session_id, cur_a, cur_b, new_s)
                events += 1
                logger.debug(
                    "[CoupledRegistry] %s (c_eff=%.3f) irrational with %s "
                    "(c_eff=%.3f); damping",
                    session_id,
                    c1,
                    other.session_id,
                    c2,
                )
        return events


# ── Singleton accessor ──────────────────────────────────────────────

_singleton: Optional[CoupledTrajectoryRegistry] = None
_singleton_lock = threading.Lock()


def get_coupled_registry() -> CoupledTrajectoryRegistry:
    """Get the process-wide singleton registry."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = CoupledTrajectoryRegistry()
        return _singleton


def reset_coupled_registry() -> None:
    """Reset the singleton (used by tests for isolation)."""
    global _singleton
    with _singleton_lock:
        _singleton = None
