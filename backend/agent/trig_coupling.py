"""Pure-math trig coupling kernels for Caducean oscillators (REQ-7).

**Contract (CT-XX — shared with caducean-phase-scheduler):** All functions in
this module are pure: no I/O, no state, no imports beyond ``math`` and
``typing``. They accept and return only ``float`` and sequences of ``float``.
They are **shared** between the scheduler layer (CaduceanPhaseManager) and the
cognitive layer (CoupledTrajectoryRegistry) but carry no state of their own
(design.md mermaid, top of ``specs/caducean-kernel-unification/design.md``).

Primitives (per-oscillator, signed):

* ``circular_delta(α, β)`` — wrap-aware circular distance on ``[0, 2π)``.
* ``splay_force(theta_i, others, k=1.0)`` — **repulsive** per-oscillator:
  ``(k/N) * Σⱼ sin(θᵢ − θⱼ)``, summed over all j ≠ i in ``others``.
  Positive when θᵢ > θⱼ (leading), pushing it backward toward the group.
  Negative when θᵢ < θⱼ (trailing), pulling it forward.  At the repulsive fixed
  point (phases spread evenly by 2π/N) the force is ~0 for all oscillators.
* ``align_force(theta_i, others, k=1.0)`` — **attractive** per-oscillator:
  ``(k/N) * Σⱼ sin(θⱼ − θᵢ)`` (the standard Kuramoto convention).  A lagging
  oscillator (θᵢ < θⱼ) experiences a positive force that speeds it up to catch
  the field.  Negation of ``splay_force``.

Scalar aggregates (diagnostic only — do NOT use to advance phase):

* ``splay_coupling_magnitude(thetas, k=1.0)`` — mean absolute per-oscillator
  splay force.  Non-negative; zero only at the repulsive fixed point.
* ``align_coupling_magnitude(thetas, k=1.0)`` — mean absolute per-oscillator
  align force.  Non-negative; zero only at the attractive fixed point.

Backward-compatible aliases (same function as the magnitude variants):

* ``splay_coupling(thetas, k=1.0)`` — alias for ``splay_coupling_magnitude``
* ``align_coupling(thetas, k=1.0)`` — alias for ``align_coupling_magnitude``
"""

from __future__ import annotations

import math
from typing import List, Sequence


def circular_delta(α: float, β: float) -> float:
    """Circular (wrap-aware) distance between two angles on ``[0, 2π)``.

    Returns the shorter arc length: ``min(|α - β|, 2π - |α - β|)``.
    Always non-negative and commutative.
    """
    _d = abs(α - β) % (2 * math.pi)
    return min(_d, 2 * math.pi - _d)


def splay_force(
    theta_i: float, others: Sequence[float], k: float = 1.0
) -> float:
    """Per-oscillator repulsive coupling force.

    ``F_i = (k/N) * Σⱼ sin(θᵢ − θⱼ)`` over every j in ``others``.

    **Repulsive convention — the sign is the whole mechanism.** The force is
    ADDED to θᵢ, so a positive force moves the oscillator FORWARD:

    * θᵢ ahead of the group (θᵢ > θⱼ) → ``sin(positive)`` > 0 → pushed further
      **ahead**, i.e. AWAY from the group.
    * θᵢ behind the group (θᵢ < θⱼ) → ``sin(negative)`` < 0 → pushed further
      **behind**, again AWAY.

    Leading and trailing oscillators therefore receive **opposite-signed**
    forces and separate. The fixed point (F_i ≈ 0 for all i) is uniform 2π/N
    spacing — the splay state.

    Contrast the attractive/sync convention, which reverses the subtraction to
    ``sin(θⱼ − θᵢ)`` (see ``align_force``). **Reversing the subtraction here
    turns repulsion into synchronization** — the exact opposite of the intent —
    and is guarded by ``test_phase_math.py::test_splay_force_opposite_sign_regression``.

    ``others`` may include ``theta_i`` itself; that term contributes
    ``sin(0) = 0``, so no explicit j ≠ i skip is needed. ``N = len(others)``,
    which keeps the standard Kuramoto ``k/N`` mean-field normalization.
    """
    N = len(others)
    if N < 2 or k == 0.0:
        return 0.0
    _s = 0.0
    for _t_j in others:
        _s += math.sin(theta_i - _t_j)
    return k * _s / N


def align_force(
    theta_i: float, others: Sequence[float], k: float = 1.0
) -> float:
    """Per-oscillator attractive coupling force (standard Kuramoto).

    ``F_i = (k/N) * Σⱼ sin(θⱼ − θᵢ)``, summed over all j ≠ i.

    This is the **standard Kuramoto** sign convention: a lagging oscillator
    (θᵢ < θⱼ) speeds up; a leading one (θᵢ > θⱼ) slows down.  Equivalent to
    ``-splay_force(theta_i, others, k)``.
    """
    return -splay_force(theta_i, others, k)


def _per_oscillator_forces(
    thetas: Sequence[float], k: float
) -> List[float]:
    """Mean-field Kuramoto REPULSIVE coupling force for each oscillator.

    ``forceᵢ = (k/N) * Σⱼ sin(θᵢ − θⱼ)``, summed over j ≠ i.
    (Repulsive convention — matches ``splay_force``.)
    """
    N = len(thetas)
    if N < 2 or k == 0.0:
        return [0.0] * N
    forces: List[float] = []
    for i in range(N):
        _s = 0.0
        for j in range(N):
            if j == i:
                continue
            _s += math.sin(thetas[i] - thetas[j])
        forces.append(k * _s / N)
    return forces


def splay_coupling_magnitude(thetas: Sequence[float], k: float = 1.0) -> float:
    """Mean absolute per-oscillator repulsive force (diagnostic scalar).

    ``(k/N) * Σᵢ |F_i|``, where F_i is the per-oscillator repulsive force.

    This is the **average magnitude** of the repulsive drive — always
    non-negative.  Zero at the repulsive fixed point (evenly spaced phases).
    Do NOT use this to advance phase — use ``splay_force`` instead.
    """
    N = len(thetas)
    if N < 2 or k == 0.0:
        return 0.0
    _forces = _per_oscillator_forces(thetas, k)
    return sum(abs(f) for f in _forces) / N


def align_coupling_magnitude(thetas: Sequence[float], k: float = 1.0) -> float:
    """Mean absolute per-oscillator attractive force (diagnostic scalar).

    ``(k/N) * Σᵢ |F_i|``, where F_i is the per-oscillator attractive force.

    Non-negative; zero at the attractive fixed point (all phases identical).
    """
    N = len(thetas)
    if N < 2 or k == 0.0:
        return 0.0
    _forces = [align_force(thetas[i], thetas, k) for i in range(N)]
    return sum(abs(f) for f in _forces) / N


# ── Backward-compatible aliases ──────────────────────────────────────────────
splay_coupling = splay_coupling_magnitude
align_coupling = align_coupling_magnitude
