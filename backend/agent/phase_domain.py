"""Phase domain — one spawnable instance of the Caducean concurrency model.

Design: docs/architecture/PHASE_DOMAINS.md. Model: docs/CADUCEAN_CONCURRENCY_MODEL.md.

A ``PhaseDomain`` is a "black box" any use case instantiates to let MANY
operations run at the same time without clashing and without a race: every
participant holds its own angle, acts when the dial reaches ~pi, then jumps
+pi, and a repulsive coupling (``trig_coupling.splay_force``, sign guarded by
``test_phase_math.py::test_splay_force_opposite_sign_regression``) keeps the
angles apart. It is NOT a budget, a cap or a semaphore: nothing is refused or
killed, a participant only waits (bounded by ``max_wait_s``) for its own
position, and the resource enters as ONE PARAMETER — ``load_fn``, a 0..1 load
that slows the cadence through the amplitude, never a ceiling.

Domains share CODE, never STATE. Each domain owns its own ``PhaseRegistry``
instance and its own tunables, so one resource's load and timescale never couple
to another's. NAME a domain by LAYER + RESOURCE (``"decision.oracle_cpu"``), so a
new use case picks a layer instead of inventing a manager. The router's
``phase_manager`` singleton (provider rate limits) is a different instance and is
NOT touched; the class is shaped so the router could be hosted by a domain later.

Gate rules mirror ``phase_manager._compute_gate``: priority classes
(``call_context.is_high_priority``) bypass with wait 0; a first-time participant
is registered at the widest gap; the group is advanced under one registry lock;
on admit the participant is reset by +pi; ANY internal error admits the call
(fail-open) — a scheduler fault degrades to no scheduling, never to an outage.

**Contract locks (CT-3 / CT-4):** the gate never reads live cognitive state
(``coupled_registry``, ``iris_ffi``). Imports are limited to ``math``, ``time``,
``typing``, ``threading``, ``asyncio``, ``logging`` and the project's own
``phase_manager`` (the shared ``PhaseRegistry`` class and wait estimate),
``trig_coupling`` and ``call_context`` modules.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time as _t
from typing import Callable, Dict, Optional

from backend.agent.call_context import call_class, is_high_priority
from backend.agent.phase_manager import PhaseRegistry, _estimate_wait

logger = logging.getLogger(__name__)

# A participant not seen for this long is forgotten (bounded footprint). The
# sweep runs at most once per ``_SWEEP_EVERY_S``.
_IDLE_FORGET_S = 300.0
_SWEEP_EVERY_S = 60.0


class PhaseDomain:
    """One resource's phase scheduler: its own registry, tunables and load."""

    def __init__(
        self,
        name: str,
        *,
        period_s: float,
        max_wait_s: float,
        k: float,
        amp_relax_tau_s: float = 1.0,
        load_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.name = name
        self.period_s = period_s
        self.max_wait_s = max_wait_s
        self.k = k
        self.registry = PhaseRegistry(
            k=k,
            amp_relax_tau_s=amp_relax_tau_s,
            default_period_s=period_s,
            load_fn=load_fn,
        )
        self._seen: Dict[str, float] = {}
        self._seen_lock = threading.Lock()
        self._last_sweep = _t.time()

    # ── gate ──────────────────────────────────────────────────────────────
    def wait_for(self, oscillator_id: str) -> float:
        """Seconds this participant must wait for its position (0 = go now).

        Never raises: any internal error returns 0.0 (fail-open).
        """
        try:
            _cc = call_class()
            if is_high_priority(_cc):
                return 0.0  # priority lane: hard bypass, before any phase math
            _reg = self.registry
            if _reg.get(oscillator_id) is None:
                _reg.register(
                    oscillator_id=oscillator_id,
                    quota_id=self.name,
                    provider_label=self.name,
                    natural_period_s=self.period_s,
                )
            self._touch(oscillator_id)
            _reg.advance_all(self.name)
            _osc = _reg.get(oscillator_id)
            if _osc is None:
                return 0.0
            _wait = min(_estimate_wait(_osc), self.max_wait_s)
            if _wait <= 0.0:
                _reg.admit_and_reset(oscillator_id)  # +pi: not due twice in a row
                return 0.0
            return _wait
        except Exception as _e:  # noqa: BLE001 — fail-open
            logger.warning(
                "[phase_domain] GATE domain=%s osc=%s wait=0 reason=exception err=%s",
                self.name, oscillator_id, _e,
            )
            return 0.0

    def acquire(self, oscillator_id: str) -> float:
        """Synchronous gate: sleep until the participant's position, return the wait."""
        _wait = self.wait_for(oscillator_id)
        if _wait > 0:
            _t.sleep(_wait)
        return _wait

    async def acquire_async(self, oscillator_id: str) -> float:
        """Async twin of ``acquire`` — ``asyncio.sleep``, never ``time.sleep``."""
        _wait = self.wait_for(oscillator_id)
        if _wait > 0:
            await asyncio.sleep(_wait)
        return _wait

    # ── bookkeeping ───────────────────────────────────────────────────────
    def _touch(self, oscillator_id: str) -> None:
        """Remember when a participant was last seen; forget long-idle ones."""
        _now = _t.time()
        with self._seen_lock:
            self._seen[oscillator_id] = _now
            if _now - self._last_sweep < _SWEEP_EVERY_S:
                return
            self._last_sweep = _now
            _stale = [o for o, s in self._seen.items() if _now - s > _IDLE_FORGET_S]
            for _o in _stale:
                del self._seen[_o]
        for _o in _stale:
            self.registry.unregister(_o)


# ── Factory: one instance per name, spawned on first use ────────────────────
_domains: Dict[str, PhaseDomain] = {}
_domains_lock = threading.Lock()


def get_phase_domain(
    name: str,
    *,
    period_s: float,
    max_wait_s: float,
    k: float,
    amp_relax_tau_s: float = 1.0,
    load_fn: Optional[Callable[[], float]] = None,
) -> PhaseDomain:
    """The ONE domain called ``name`` — created on first use, then reused.

    Later calls return the existing instance; their tunables are ignored (a
    domain's parameters are fixed at spawn).
    """
    with _domains_lock:
        _d = _domains.get(name)
        if _d is None:
            _d = _domains[name] = PhaseDomain(
                name,
                period_s=period_s,
                max_wait_s=max_wait_s,
                k=k,
                amp_relax_tau_s=amp_relax_tau_s,
                load_fn=load_fn,
            )
        return _d


def reset_phase_domains_for_testing() -> None:
    """Forget every domain (test isolation)."""
    with _domains_lock:
        _domains.clear()
