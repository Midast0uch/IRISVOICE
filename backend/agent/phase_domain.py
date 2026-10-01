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
        capacity_fn: Optional[Callable[[], int]] = None,
    ) -> None:
        self.name = name
        self.period_s = period_s
        self.max_wait_s = max_wait_s
        self.k = k
        # Completion-driven admission ("natural exit", owner 2026-10-01): when
        # set, enter()/exit() admit a participant when a run EXITS, ordered by
        # its position on the dial. None = the timed gate (wait_for) only.
        self._capacity_fn = capacity_fn
        self._exit_cv = threading.Condition()
        self._in_flight = 0
        self._prio_waiting = 0
        self._waiting: Dict[str, int] = {}
        self._entry_seq = 0
        self._due_at: Dict[str, float] = {}
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

    # ── completion-driven admission ("natural exit") ──────────────────────
    # Measured why (oracle.md 19.6): the timed gate admits every participant
    # within max_wait_s, so up to 8 Oracle runs shared 4 cores and a reply
    # decision - which skips the gate - still landed in a crowded CPU (reply
    # p50 506 ms vs 258 ms under a bench-only semaphore). Here WHEN comes from
    # exits: a participant starts only when a run slot is free (a decision has
    # finished), the slot count being the resource's own capacity. WHO comes
    # from the physics: among waiters, the one nearest its firing point on the
    # dial goes first (each waiting decision holds its own position, placed at
    # the widest gap); priority classes have right of way. Fail-open: an internal error or a wait past safety_s admits.
    def enter(self, oscillator_id: str, safety_s: float = 30.0) -> str:
        """Block until this participant may run; pair every call with exit()."""
        cap = None
        try:
            if self._capacity_fn is not None:
                cap = max(1, int(self._capacity_fn()))
        except Exception as _e:  # noqa: BLE001 — fail-open to the timed gate
            logger.warning("[phase_domain] capacity unreadable domain=%s err=%s",
                           self.name, _e)
        if cap is None:
            self.acquire(oscillator_id)
            with self._exit_cv:
                self._in_flight += 1
            return f"{oscillator_id}#timed"  # exit() must not remove the consumer's position
        high = is_high_priority(call_class())
        deadline = _t.monotonic() + safety_s
        with self._exit_cv:
            # One position PER DECISION, placed at the widest gap and removed at
            # exit. Measured: one shared position per consumer starved the
            # busiest one (tool_choice, ~45% of the bench burst: worst wait
            # 8.9 s) - after each run its single position jumped to the back.
            self._entry_seq += 1
            oscillator_id = f"{oscillator_id}#{self._entry_seq}"
            if not high:
                # The decision's DUE TIME is fixed at arrival from its position:
                # registered at the widest gap, due when it reaches its firing
                # point. Measured: ordering by the LIVE position starved a waiter
                # whose firing point passed while no slot was free (it jumped a
                # full turn back; route worst wait 5.4 s).
                self._due_at[oscillator_id] = _t.monotonic() + self._arrival_wait(oscillator_id)
            if high:
                self._prio_waiting += 1
            else:
                self._waiting[oscillator_id] = self._waiting.get(oscillator_id, 0) + 1
            try:
                while True:
                    if self._in_flight < cap and (
                        high or (self._prio_waiting == 0
                                 and self._most_due(oscillator_id))):
                        break
                    remaining = deadline - _t.monotonic()
                    if remaining <= 0:
                        logger.warning(
                            "[phase_domain] ADMIT domain=%s osc=%s reason=safety_timeout "
                            "in_flight=%d cap=%d", self.name, oscillator_id,
                            self._in_flight, cap)
                        break
                    self._exit_cv.wait(remaining)
            finally:
                if high:
                    self._prio_waiting -= 1
                else:
                    n = self._waiting.get(oscillator_id, 1) - 1
                    if n > 0:
                        self._waiting[oscillator_id] = n
                    else:
                        self._waiting.pop(oscillator_id, None)
                    self._due_at.pop(oscillator_id, None)
            self._in_flight += 1
            self._exit_cv.notify_all()
        return oscillator_id

    def exit(self, token: str) -> None:
        """The participant's run finished: free its slot and wake the waiters."""
        with self._exit_cv:
            self._in_flight = max(0, self._in_flight - 1)
            self._exit_cv.notify_all()
        try:
            self.registry.unregister(token)  # the decision's position leaves the dial
        except Exception:  # noqa: BLE001 — bookkeeping never blocks a run
            pass
        with self._seen_lock:
            self._seen.pop(token, None)

    def _arrival_wait(self, entry_id: str) -> float:
        """Seconds from arrival to this decision's firing point on the dial.
        Called under _exit_cv. Fail-open: 0.0 (due now)."""
        try:
            _reg = self.registry
            _reg.register(oscillator_id=entry_id, quota_id=self.name,
                          provider_label=self.name, natural_period_s=self.period_s)
            self._touch(entry_id)
            _reg.advance_all(self.name)
            return max(0.0, float(_estimate_wait(_reg.get(entry_id))))
        except Exception as _e:  # noqa: BLE001 — fail-open
            logger.warning("[phase_domain] arrival position failed domain=%s err=%s",
                           self.name, _e)
            return 0.0

    def _most_due(self, oscillator_id: str) -> bool:
        """True when this waiter has the earliest due time among all waiters.
        Called under _exit_cv. Fail-open: any error answers True."""
        try:
            mine = self._due_at.get(oscillator_id, 0.0)
            return all(mine <= self._due_at.get(o, 0.0)
                       for o in self._waiting if o != oscillator_id)
        except Exception as _e:  # noqa: BLE001 — fail-open
            logger.warning("[phase_domain] order failed domain=%s err=%s", self.name, _e)
            return True

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
    capacity_fn: Optional[Callable[[], int]] = None,
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
                capacity_fn=capacity_fn,
            )
        return _d


def reset_phase_domains_for_testing() -> None:
    """Forget every domain (test isolation)."""
    with _domains_lock:
        _domains.clear()
