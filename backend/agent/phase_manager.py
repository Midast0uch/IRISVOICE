"""Caducean Phase Manager — anti-phase Kuramoto scheduler (Wave 3).

Provides:
  * ``PhaseOscillator`` — per-oscillator state (θ, amplitude, period, quota_id).
  * ``PhaseRegistry`` — thread-safe singleton, re-keyed by **oscillator_id**
    (a string like ``"{session_id}:{call_class}"``); ``quota_id`` is a grouping
    attribute (design D-8 / REQ-11 AC1 — NOT by ``ProviderInstance.id``).
  * ``acquire`` / ``acquire_async`` — the gate every LLM call passes through
    (sync / async twins per ``resilience.py:37/80``).
  * ``advance_all`` — repulsive Kuramoto coupling (``trig_coupling.splay_force``)
    plus amplitude relaxation toward ``1 − load_fraction``, applied atomically
    to every oscillator in a quota group under one registry lock.

**Oscillator-id convention:** ``"{session_id}:{call_class_value}"`` so each
session's DER activity (UserTurn) and its sub-loop children (SubLoop) are
distinct registrants sharing one quota but independently tracked.

**Registry locking rule (T6.5):** All oscillator state mutation
(theta / amplitude / last_advance_at) happens under the registry lock.
Prefer ``advance_all(quota_id)`` which takes the lock once and updates the
whole group from one consistent theta snapshot.

**Firing convention (T6.3):** The oscillator fires at ``theta ~ pi`` (phase
winding past the midpoint).  On admit the oscillator is reset by ``+pi``
(mod 2π) so the same theta cannot admit twice consecutively.  ``_estimate_wait``
is consistent: it returns how long until ``theta + ω*Δt ≈ pi``.

**Contract locks:** The scheduler never calls ``coupled_registry`` (CT-3), never
calls ``iris_ffi`` (CT-4).  Imports are limited to ``math``, ``time``, ``typing``,
``threading``, ``asyncio``, ``logging``, and the project's own
``trig_coupling`` / ``call_context`` / ``rate_meter`` modules.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import threading
import time as _perf_t
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from backend.agent.trig_coupling import splay_force, align_force
from backend.agent.call_context import (
    CallClass,
    call_class,
    is_high_priority,
)
from backend.agent.rate_meter import get_rate_meter

logger = logging.getLogger(__name__)


# ── Tunables (env-overridable) ──────────────────────────────────────────────
def _env_float(name: str, default: float) -> float:
    try:
        _v = os.environ.get(name)
        return float(_v) if _v is not None else default
    except (TypeError, ValueError):
        return default


PHASE_K = _env_float("IRIS_PHASE_K", 0.6)          # K in Kuramoto coupling
PHASE_MAX_WAIT_S = _env_float("IRIS_PHASE_MAX_WAIT_S", 2.0)
TICK_MAX_DT_S = 5.0
MIN_PERIOD_S = 0.05
R_MIN = 0.1
R_GAMMA = 0.25
IDLE_UNREGISTER_S = 300.0
AMP_RELAX_TAU_S = _env_float("IRIS_AMP_RELAX_TAU_S", 10.0)  # τ for amplitude relaxation

# Feature flag (T3.8 / REQ-17)
def _flag_enabled() -> bool:
    _v = os.environ.get("IRIS_PHASE_SCHEDULER", "").strip().lower()
    if _v in ("1", "true", "on", "yes"):
        return True
    if _v in ("", "0", "false", "off", "no"):
        return False
    logger.warning(
        "[phase_manager] unparseable IRIS_PHASE_SCHEDULER=%r — treating as disabled",
        _v,
    )
    return False

_flag_logged = False


def _check_flag() -> bool:
    """Check feature flag; log state once."""
    global _flag_logged
    _ok = _flag_enabled()
    if not _flag_logged:
        logger.info(
            "[phase_manager] phase_scheduler=%s  (IRIS_PHASE_SCHEDULER=%s)",
            "active" if _ok else "inactive",
            os.environ.get("IRIS_PHASE_SCHEDULER", "(unset)"),
        )
        _flag_logged = True
    return _ok


def reset_flag_for_testing() -> None:
    """Clear the flag-logged guard so next _check_flag re-reads the env var."""
    global _flag_logged
    _flag_logged = False


# ── Oscillator ──────────────────────────────────────────────────────────────
@dataclass
class PhaseOscillator:
    """One oscillator in the anti-phase Kuramoto ensemble.

    Keyed by ``oscillator_id`` (a string like ``"{session_id}:{call_class}"``);
    ``quota_id`` groups oscillators that share a rate-limit quota (D-8).
    """

    oscillator_id: str
    quota_id: str
    provider_label: str               # for logs only (not a group key)
    theta: float                      # phase angle [0, 2π)
    amplitude: float                  # r ∈ [R_MIN, 1.0]
    natural_period_s: float           # ω = 1 / natural_period_s (rad/s)
    last_advance_at: float            # wall-clock for dt computation
    is_idle: bool = False
    join_point: Optional[str] = None  # Wave 4: compression seam id (REQ-18)
    independent: bool = False         # Wave 4: safe to batch with siblings


# ── Registry (thread-safe singleton) ────────────────────────────────────────
class PhaseRegistry:
    """Thread-safe singleton that owns all active oscillators.

    Re-keyed by **oscillator_id** (T6.2); ``quota_id`` is a grouping attribute
    (D-8 / REQ-11 AC1).  Widest-gap placement spreads a new oscillator among
    existing ones sharing its quota_id (REQ-11 AC2).  All oscillator state
    mutation happens under ``_lock`` (T6.5).
    """

    def __init__(self) -> None:
        self._oscillators: Dict[str, PhaseOscillator] = {}
        self._lock = threading.Lock()

    # ── registration (T3.2, T6.2) ────────────────────────────────────────
    def register(
        self,
        oscillator_id: str,
        quota_id: str,
        provider_label: str = "",
        natural_period_s: float = 1.0,
        join_point: Optional[str] = None,
        independent: bool = False,
    ) -> PhaseOscillator:
        """Register (or re-register) an oscillator. Returns the oscillator.

        ``oscillator_id`` is the primary key (e.g. ``"{session}:USER_TURN"``).
        ``quota_id`` is the grouping key for coupling and widest-gap placement.
        On **first** registration: places θ at the widest gap across oscillators
        sharing ``quota_id`` (REQ-11 AC2).  On **re**-registration preserves θ
        and amplitude (REQ-11 AC3).
        """
        with self._lock:
            _existing = self._oscillators.get(oscillator_id)
            if _existing is not None:
                _existing.provider_label = provider_label or _existing.provider_label
                _existing.natural_period_s = max(
                    natural_period_s, MIN_PERIOD_S
                )
                _existing.last_advance_at = _perf_t.time()
                _existing.is_idle = False
                _existing.join_point = join_point
                _existing.independent = independent
                return _existing

            _period = max(natural_period_s, MIN_PERIOD_S)
            _theta = self._widest_gap(quota_id)
            _load = self._load_fraction(quota_id)
            _amp = max(1.0 - _load, R_MIN)

            _osc = PhaseOscillator(
                oscillator_id=oscillator_id,
                quota_id=quota_id,
                provider_label=provider_label,
                theta=_theta,
                amplitude=_amp,
                natural_period_s=_period,
                last_advance_at=_perf_t.time(),
                join_point=join_point,
                independent=independent,
            )
            self._oscillators[oscillator_id] = _osc
            return _osc

    def unregister(self, oscillator_id: str) -> None:
        """Remove an oscillator by its id."""
        with self._lock:
            self._oscillators.pop(oscillator_id, None)

    def snapshot(self) -> List[PhaseOscillator]:
        """Thread-safe snapshot of all oscillators (side-effect free)."""
        with self._lock:
            return list(self._oscillators.values())

    def get(self, oscillator_id: str) -> Optional[PhaseOscillator]:
        """Look up an oscillator by oscillator_id."""
        with self._lock:
            return self._oscillators.get(oscillator_id)

    def get_by_quota(self, quota_id: str) -> List[PhaseOscillator]:
        """Return all oscillators sharing the given quota_id (T6.2)."""
        with self._lock:
            return [o for o in self._oscillators.values() if o.quota_id == quota_id]

    def window(self, oscillator_id: str) -> float:
        """Return the current phase angle θ for the oscillator.

        Returns ``0.0`` if the oscillator is unknown (REQ-15 AC1 safe default).
        Side-effect free.
        """
        _o = self.get(oscillator_id)
        return _o.theta if _o is not None else 0.0

    def reset_for_testing(self) -> None:
        """Clear all oscillators (test isolation)."""
        with self._lock:
            self._oscillators.clear()

    # ── advance_all (T6.5) ───────────────────────────────────────────────

    def advance_all(self, quota_id: str) -> None:
        """Advance every oscillator in ``quota_id`` by realistic dt.

        Under one lock: reads the wall-clock once, computes dt for each
        oscillator, applies Kuramoto splay coupling (T6.1) and amplitude
        relaxation toward ``1 − load_fraction``.  Uses the per-oscillator
        primitive ``splay_force`` — **never** ``abs()`` a coupling value.
        """
        with self._lock:
            _now = _perf_t.time()
            _quota_oscs = [
                o for o in self._oscillators.values() if o.quota_id == quota_id
            ]
            if not _quota_oscs:
                return
            _thetas = [o.theta for o in _quota_oscs]
            _load = self._load_fraction(quota_id)
            _target_amp = max(1.0 - _load, R_MIN)

            for _idx, _osc in enumerate(_quota_oscs):
                _dt = _now - _osc.last_advance_at
                if _dt <= 0:
                    _osc.last_advance_at = _now
                    continue
                # REQ-12 AC4 / N5: CLAMP a long idle gap, never skip the advance.
                if _dt > TICK_MAX_DT_S:
                    _dt = TICK_MAX_DT_S

                # REQ-9 AC3 / N1: amplitude modulates the effective angular
                # velocity — omega_eff = omega * r — so a loaded provider makes
                # its registrants fire LESS OFTEN through the same phase
                # mechanism rather than through a separate counter. Uses the
                # amplitude standing at the start of the tick (relaxation below
                # applies to the next one), matching the "react to the position
                # you are standing on" rule.
                _omega = (2.0 * math.pi / _osc.natural_period_s) * _osc.amplitude

                # Per-oscillator signed coupling force (T6.1 — no abs!)
                _coupling = splay_force(_osc.theta, _thetas, k=PHASE_K)

                # Phase advance: natural + coupling
                _osc.theta = (_osc.theta + _omega * _dt + _coupling * _dt) % (
                    2.0 * math.pi
                )

                # Amplitude relaxation: r ← lerp(r, target, dt / tau)
                _tau = AMP_RELAX_TAU_S
                _frac = min(1.0, _dt / _tau)
                _osc.amplitude = _osc.amplitude + (_target_amp - _osc.amplitude) * _frac
                _osc.amplitude = max(R_MIN, min(1.0, _osc.amplitude))
                _osc.last_advance_at = _now

    def admit_and_reset(self, oscillator_id: str) -> None:
        """Atomically reset ``oscillator_id``'s θ by +π (mod 2π) under the lock.

        Called on admit to prevent the same oscillator admitting twice in a
        row.  No-op if the oscillator no longer exists.
        """
        with self._lock:
            _osc = self._oscillators.get(oscillator_id)
            if _osc is None:
                return
            _osc.theta = (_osc.theta + math.pi) % (2.0 * math.pi)

    # ── internals ─────────────────────────────────────────────────────────
    def _widest_gap(self, quota_id: str) -> float:
        """Place θ at the widest gap across oscillators sharing ``quota_id``.

        If no oscillators exist for this quota, return 0.0.
        If only one, place at π (opposite).
        If more, find the largest circular gap and bisect it.
        """
        _thetas = [
            o.theta for o in self._oscillators.values() if o.quota_id == quota_id
        ]
        if not _thetas:
            return 0.0
        if len(_thetas) == 1:
            return (_thetas[0] + math.pi) % (2 * math.pi)

        _thetas.sort()
        _gaps: List[float] = []
        for i in range(len(_thetas)):
            _next = _thetas[(i + 1) % len(_thetas)]
            _gap = (_next - _thetas[i]) % (2 * math.pi)
            _gaps.append(_gap)
        _max_idx = _gaps.index(max(_gaps))
        return (_thetas[_max_idx] + _gaps[_max_idx] / 2) % (2 * math.pi)

    def _load_fraction(self, quota_id: str) -> float:
        """Fraction of the learned ceiling consumed by recent requests (0–1).

        Reads ``rate_meter.draw()`` and ``rate_meter.get_ceiling()``.  An
        unmetered quota or zero ceiling → returns 0.0.  Dead ``_c is None``
        branch (F15) addressed: ``get_ceiling`` now always returns a float,
        so guard is explicit for zero/negative/inf only.
        """
        _d = get_rate_meter().draw(quota_id)
        _c = get_rate_meter().get_ceiling(quota_id)
        if _c <= 0 or math.isinf(_c):
            return 0.0
        _max_req = _c * _d.get("window_s", 60.0) / 60.0
        if _max_req <= 0:
            return 0.0
        return min(1.0, _d.get("requests", 0) / _max_req)


# ── Singleton accessor ─────────────────────────────────────────────────────
_singleton: Optional[PhaseRegistry] = None
_singleton_lock = threading.Lock()


def get_registry() -> PhaseRegistry:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = PhaseRegistry()
        return _singleton


def reset_registry_for_testing() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None


# ── Coupling logic (T3.3 / T3.4) ────────────────────────────────────────────
def _coupling_group(registry: PhaseRegistry, quota_id: str) -> List[PhaseOscillator]:
    """Return all oscillators sharing *quota_id*."""
    return [o for o in registry.snapshot() if o.quota_id == quota_id]


def advance(
    oscillator_id: str,
    quota_id: str,
    registry: Optional[PhaseRegistry] = None,
) -> None:
    """Advance one oscillator per-quota by realistic dt.

    Delegates to ``registry.advance_all(quota_id)`` which takes the registry
    lock once and updates the whole group (T6.5).  Uses the per-oscillator
    primitive ``splay_force`` — never abs() a coupling value (T6.1).

    ``oscillator_id`` is the registrant key; ``quota_id`` is the coupling group.
    """
    if not _check_flag():
        return  # feature disabled — no-op (T3.8)
    if registry is None:
        registry = get_registry()
    registry.advance_all(quota_id)


# ── Gate (T3.5 / T6.3) ──────────────────────────────────────────────────────


def _compute_gate(
    oscillator_id: Optional[str] = None,
    quota_id: Optional[str] = None,
) -> float:
    """Shared gate logic: compute the wait time (0 = admit now).

    ``oscillator_id`` (primary key) and ``quota_id`` (grouping key) are both
    accepted.  For backward compatibility, if ``oscillator_id`` is None,
    ``quota_id`` is used as both.  If ``quota_id`` is None, ``oscillator_id``
    is used as both.

    **T6.3:** On admit (``_wait <= 0``), the oscillator is reset by +π radians
    so the same theta cannot gate-admit twice consecutively.

    **Firing convention:** The oscillator fires at ``theta ~ pi``.  On admit
    the oscillator advances by +π (mod 2π).  ``_estimate_wait`` returns how
    long until ``theta + ω*Δt ≈ pi``.

    Fail-open: returns 0.0 (admit) on any internal exception so the scheduler
    can never prevent a call from reaching the provider (REQ-13 edge / CT-9).
    """
    try:
        if not _check_flag():
            logger.info(
                "[phase_manager] GATE_DECISION osc=%s quota=%s wait=0 reason=flag_off",
                oscillator_id,
                quota_id,
            )
            return 0.0  # feature disabled (T3.8)

        # T6.8: flush expired batch groups from the DER cycle.
        #
        # Isolated in its OWN try/except: this runs before the priority check and
        # before registration, so without it an unrelated batching error would
        # propagate to the outer fail-open handler and take the ENTIRE gate
        # offline — every call admitted with wait=0, no oscillator registered, and
        # nothing but a warning to show for it. Batching is auxiliary; gating is
        # the feature. A batcher fault must never disable the scheduler.
        try:
            from backend.agent.batch_dispatch import get_batcher as _get_batcher

            _get_batcher().flush_expired()
        except Exception as _b_exc:
            logger.debug("[phase_manager] batcher flush_expired skipped: %s", _b_exc)

        _cc = call_class()

        # priority lane (REQ-14 AC2 / T6.4)
        if is_high_priority(_cc):
            logger.info(
                "[phase_manager] GATE_DECISION osc=%s quota=%s wait=0 reason=priority cls=%s",
                oscillator_id,
                quota_id,
                _cc.value if _cc else "none",
            )
            return 0.0  # admitted with zero wait

        _oid = oscillator_id or quota_id or ""
        _qid = quota_id or oscillator_id or ""

        _registry = get_registry()
        _osc = _registry.get(_oid)

        # unmetered provider → admit (REQ-9)
        if _qid and math.isinf(get_rate_meter().get_ceiling(_qid)):
            logger.info(
                "[phase_manager] GATE_DECISION osc=%s quota=%s wait=0 reason=unmetered cls=%s",
                _oid,
                _qid,
                _cc.value if _cc else "none",
            )
            return 0.0

        # advance (may register if first call)
        if _osc is None:
            _osc = _registry.register(
                oscillator_id=_oid,
                quota_id=_qid,
            )
        _registry.advance_all(_qid)
        _osc = _registry.get(_oid)
        if _osc is None:
            return 0.0  # safety: should not happen after register

        # compute wait (firing point at θ ≈ π)
        _wait = _estimate_wait(_osc)
        _wait = min(_wait, PHASE_MAX_WAIT_S)

        if _wait <= 0.0:
            # ON ADMIT: reset θ by +π (mod 2π) atomically under the lock
            # so the same θ cannot admit twice consecutively (T6.3).
            _registry.admit_and_reset(_oid)
            _osc2 = _registry.get(_oid)  # re-read after reset
            _theta_after = _osc2.theta if _osc2 else _osc.theta
            logger.info(
                "[phase_manager] GATE_DECISION osc=%s quota=%s wait=0 reason=admit"
                " theta=%.3f amp=%.3f period=%.3f",
                _oid,
                _qid,
                _theta_after,
                _osc.amplitude,
                _osc.natural_period_s,
            )
            return 0.0

        logger.info(
            "[phase_manager] GATE_DECISION osc=%s quota=%s wait=%.1f reason=gated"
            " theta=%.3f amp=%.3f period=%.3f cls=%s",
            _oid,
            _qid,
            _wait,
            _osc.theta,
            _osc.amplitude,
            _osc.natural_period_s,
            _cc.value if _cc else "none",
        )
        return _wait
    except Exception as _e:
        logger.warning(
            "[phase_manager] GATE_DECISION osc=%s quota=%s wait=0 reason=exception err=%s",
            oscillator_id,
            quota_id,
            _e,
        )
        return 0.0


def acquire(
    oscillator_id: Optional[str] = None,
    quota_id: Optional[str] = None,
) -> float:
    """Synchronous gate.  Blocks the calling thread until the oscillator is
    estimated to be past its firing point.

    Accepts ``oscillator_id`` (primary registry key) and ``quota_id`` (coupling
    group key).  Backward-compatible: pass only the old ``quota_id`` positional
    argument.

    Returns the actual wait time in seconds (0.0 if not blocked).
    Uses ``time.sleep`` (CT-9 sync twin).
    """
    _wait = _compute_gate(oscillator_id, quota_id)
    if _wait > 0:
        _perf_t.sleep(_wait)
    return _wait


async def acquire_async(
    oscillator_id: Optional[str] = None,
    quota_id: Optional[str] = None,
) -> float:
    """Async twin of ``acquire``.  Uses ``asyncio.sleep`` — never
    ``time.sleep`` (CT-9 / REQ-13 AC6).

    Short-poll loop (50ms or 10% of remaining) so the wake-up can adapt to
    oscillations.
    """
    _wait = _compute_gate(oscillator_id, quota_id)
    if _wait <= 0:
        return _wait
    _t0 = _perf_t.time()
    _elapsed = 0.0
    while _elapsed < _wait:
        _remaining = _wait - _elapsed
        _sleeptime = min(max(0.05, _remaining * 0.1), _remaining)
        await asyncio.sleep(_sleeptime)
        _elapsed = _perf_t.time() - _t0
    return _elapsed


def _estimate_wait(osc: PhaseOscillator) -> float:
    """Estimate seconds until *osc* reaches its firing point (θ ≈ π).

    Uses the SAME effective angular velocity as ``advance_all``:
    ``omega_eff = (2π / period) * amplitude`` (REQ-9 AC3). Amplitude therefore
    lengthens the estimated wait when the provider is loaded — that is the
    volume-regulation mechanism, expressed through timing rather than through a
    separate counter. The two functions must agree on velocity or the wait would
    not predict the advance.

    ``amplitude`` is floored at ``R_MIN`` by ``advance_all``, so the velocity can
    never reach zero and the wait is always finite. The caller clamps the result
    to ``PHASE_MAX_WAIT_S`` (REQ-13 AC6).

    If the oscillator is already past π, zero is returned (admit now).
    """
    _omega = (
        2.0 * math.pi / max(osc.natural_period_s, MIN_PERIOD_S)
    ) * max(osc.amplitude, R_MIN)
    if _omega <= 0:
        return 0.0

    # DUE when θ has reached or passed the firing point, i.e. θ ∈ [π, 2π).
    #
    # The earlier form `(π − θ) % 2π` had a cliff: an oscillator that overshot π
    # by any amount between gate checks wrapped to a distance of ~2π and was made
    # to travel a NEARLY FULL REVOLUTION before firing, even though it was already
    # overdue. That penalised drift instead of admitting it, and made any test near
    # the boundary fail on microsecond timing noise.
    #
    # Consistency with `admit_and_reset` (+π): admit at θ≈π → reset to θ≈0 → the
    # oscillator must travel π radians to become due again. So [π, 2π) = due and
    # [0, π) = waiting is exactly one half-cycle of work per admission.
    if osc.theta >= math.pi:
        return 0.0  # at or past the firing point — overdue, admit now

    _dist = math.pi - osc.theta
    if _dist <= 0.01:
        return 0.0  # within the admit window
    return _dist / _omega


def provider_metrics() -> dict:
    """REQ-20 observability snapshot per quota.

    Returns a dict keyed by ``quota_id`` with:
      - oscillator_count
      - oscillators: list of *(oscillator_id, theta, amplitude, period_s)*
      - **gap_stats**: real inter-request gap statistics from the rate meter
        (``count`` / ``mean_gap_s`` / ``stddev_gap_s`` / ``min_gap_s`` /
        ``max_gap_s``) — the quantity the ">=50% stddev reduction" success
        criterion is defined over (REQ-20 AC6 / REQ-22 AC6).
      - advance_staleness_s: list of ``now - last_advance_at`` per oscillator.
        **Diagnostic only.** An earlier version reported this as
        ``inter_request_gap_s``, which was wrong: it measures how long since the
        phase was advanced, not the spacing between requests, so it could not
        feed the criterion above.
      - draw: current window draw (requests / tokens / window_s)
      - ceiling_rpm: effective learned ceiling for the quota
      - coupling_k: current coupling gain (``PHASE_K``)

    Named ``provider_metrics`` (not ``param_metrics``) per reconciliation C6
    to avoid collision with ``param_homeostasis.param_metrics``.
    """
    _reg = get_registry()
    _quota_groups: dict[str, dict] = {}
    for _osc in _reg.snapshot():
        _oid = _osc.oscillator_id
        _qid = _osc.quota_id or _oid
        if _qid not in _quota_groups:
            _meter = get_rate_meter()
            _quota_groups[_qid] = {
                "oscillator_count": 0,
                "oscillators": [],
                # REQ-22 AC6: real inter-request spacing, from the meter.
                "gap_stats": _meter.gap_stats(_qid),
                "draw": _meter.draw(_qid),
                "ceiling_rpm": _meter.get_ceiling(_qid),
                # Diagnostic only — NOT inter-request spacing (see docstring).
                "advance_staleness_s": [],
                "coupling_k": PHASE_K,
            }
        _g = _quota_groups[_qid]
        _g["oscillator_count"] += 1
        _g["oscillators"].append(
            {
                "oscillator_id": _oid,
                "theta": round(_osc.theta, 4),
                "amplitude": round(_osc.amplitude, 4),
                "period_s": _osc.natural_period_s,
            }
        )
        _g["advance_staleness_s"].append(
            round(_perf_t.time() - _osc.last_advance_at, 3)
        )
    return {_qid: dict(v) for _qid, v in _quota_groups.items()}
