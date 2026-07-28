"""
param_homeostasis.py — Homeostatic relaxation of Caducean Duffing parameters (REQ-1, REQ-2).

Provides a thread-safe singleton that:
  - Stores per-session baselines (default: (2.0, 2.0, 0.35), the Gate 1 baseline
    documented at trajectory_controller.py:196-200).
  - Relaxes (a, b, s) toward baseline in proportional steps (RELAX_STEP = 0.25; raised from
    0.10 after REQ-21 made tune_dffing_params idempotent — verified worst drift 0.070 on the
    exact 200/10/5 REQ-1 load, margin +0.080; 0.30 holds a 2x load),
    triggered every RELAX_EVERY_N_UPDATES updates or RELAX_MAX_INTERVAL_S seconds.
  - Tracks perturbation counts by writer name for observability (REQ-15).
  - Bounds baseline storage to MAX_BASELINES (64), evicting oldest last-touched.

Usage:
    from backend.agent.param_homeostasis import get_param_homeostasis

    homeostat = get_param_homeostasis()
    homeostat.set_baseline("session_1", 2.5, 2.0, 0.4)
    homeostat.relax_params("session_1")
    homeostat.maybe_relax("session_1", update_count=20)

Testing:
    from backend.agent.param_homeostasis import reset_param_homeostasis
    reset_param_homeostasis()  # clears singleton between tests
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# FFI functions are imported at module level for testability — the lazy import
# inside relax_params() can deadlock with unittest.mock.patch (which also
# imports the module during __enter__).  Module-level import is safe because
# param_homeostasis has no circular dependency on iris_ffi.
from backend.gateway.iris_ffi import (
    ffi_caducean_get_state as _ffi_get_state,
    ffi_caducean_set_params as _ffi_set_params,
)

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────

# Safe ranges for Duffing parameters (trajectory_controller.py:196-200).
SAFE_A: Tuple[float, float] = (1.0, 4.0)
SAFE_B: Tuple[float, float] = (1.0, 4.0)
SAFE_S: Tuple[float, float] = (0.1, 0.8)

# Relaxation cadence: fire every N updates OR every N seconds (whichever first).
RELAX_EVERY_N_UPDATES: int = 10
RELAX_MAX_INTERVAL_S: float = 60.0

# Fraction of distance to baseline per relaxation invocation (proportional step).
RELAX_STEP: float = 0.25

# Deadband: if a parameter is within this distance of baseline, skip (avoid
# perpetual no-op FFI writes).
RELAX_DEADBAND: float = 0.02

# Maximum number of concurrent session baselines. Evict by oldest last_touched.
MAX_BASELINES: int = 64


# ── Data model ───────────────────────────────────────────────────────────

@dataclass
class ParamBaseline:
    """Per-session baseline record for Duffing parameter homeostasis.

    The default (2.0, 2.0, 0.35) is the Gate 1 baseline from
    trajectory_controller.py:196-200 ("a,b ∈ [1, 4]: below 1 flattens wells
    (no attractors); above 4 creates chaotic deep wells (instability). Gate 1
    baseline = 2.0. s ∈ [0.1, 0.8]: below 0.1 essentially static; above 0.8
    chaotic exploration. Gate 1 baseline = 0.35").
    """

    session_id: str
    a: float = 2.0
    b: float = 2.0
    s: float = 0.35
    last_touched: float = 0.0
    perturbations: Dict[str, int] = field(default_factory=dict)
    relaxations: int = 0


# ── Homeostat singleton ──────────────────────────────────────────────────

class ParamHomeostasis:
    """Thread-safe singleton managing per-session baselines and relaxation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._baselines: Dict[str, ParamBaseline] = {}
        # Per-session counters for the update-based cadence.
        self._last_relax_update: Dict[str, int] = {}
        self._last_relax_time: Dict[str, float] = {}

    # ── Baseline management ─────────────────────────────────────────────

    def get_baseline(self, session_id: str) -> ParamBaseline:
        """Return the baseline for *session_id*, creating a default if absent."""
        with self._lock:
            if session_id not in self._baselines:
                self._baselines[session_id] = ParamBaseline(
                    session_id=session_id,
                    last_touched=time.time(),
                )
                now = time.time()
                self._last_relax_time[session_id] = now
            return self._baselines[session_id]

    def set_baseline(self, session_id: str, a: float, b: float, s: float) -> None:
        """Record a new baseline for *session_id*.

        The values are clamped to the established safe ranges so the homeostat
        always targets a reachable point.
        """
        with self._lock:
            clamped_a = max(SAFE_A[0], min(SAFE_A[1], a))
            clamped_b = max(SAFE_B[0], min(SAFE_B[1], b))
            clamped_s = max(SAFE_S[0], min(SAFE_S[1], s))
            if session_id not in self._baselines:
                self._baselines[session_id] = ParamBaseline(
                    session_id=session_id,
                    a=clamped_a,
                    b=clamped_b,
                    s=clamped_s,
                    last_touched=time.time(),
                )
                # Also seed the time-based trigger so it doesn't fire
                # immediately on the first maybe_relax call (REQ-1 AC2b).
                now = time.time()
                self._last_relax_time[session_id] = now
            else:
                rec = self._baselines[session_id]
                rec.a = clamped_a
                rec.b = clamped_b
                rec.s = clamped_s
                rec.last_touched = time.time()
            self.evict_if_needed()

    # ── Perturbation tracking (REQ-15 AC1) ──────────────────────────────

    def register_perturbation(self, session_id: str, writer: str) -> None:
        """Increment the perturbation counter for *writer* on *session_id*."""
        with self._lock:
            if session_id not in self._baselines:
                self._baselines[session_id] = ParamBaseline(
                    session_id=session_id,
                    last_touched=time.time(),
                )
                now = time.time()
                self._last_relax_time[session_id] = now
            rec = self._baselines[session_id]
            rec.perturbations[writer] = rec.perturbations.get(writer, 0) + 1
            rec.last_touched = time.time()

    def record_relaxation(self, session_id: str) -> None:
        """Increment the relaxation counter for *session_id*.

        NOTE: accesses _baselines directly instead of going through
        get_baseline() to avoid a reentrant-lock deadlock (threading.Lock
        is NOT reentrant).
        """
        with self._lock:
            if session_id not in self._baselines:
                self._baselines[session_id] = ParamBaseline(
                    session_id=session_id,
                    last_touched=time.time(),
                )
            rec = self._baselines[session_id]
            rec.relaxations += 1
            rec.last_touched = time.time()

    # ── Metrics / snapshot (REQ-15 AC2) ─────────────────────────────────

    def metrics(self, session_id: str) -> dict:
        """Return a snapshot dict for observability.

        Keys: current (a, b, s) (from FFI if available, else baseline),
        baseline (a, b, s), perturbation counts by writer, relaxation count.
        """
        rec = self.get_baseline(session_id)
        # Try to read current values from the FFI for a live snapshot.
        try:
            state = _ffi_get_state(session_id)
            cur_a = state.get("a", rec.a)
            cur_b = state.get("b", rec.b)
            cur_s = state.get("s", rec.s)
        except Exception:
            cur_a = rec.a
            cur_b = rec.b
            cur_s = rec.s
        return {
            "current_a": cur_a,
            "current_b": cur_b,
            "current_s": cur_s,
            "baseline_a": rec.a,
            "baseline_b": rec.b,
            "baseline_s": rec.s,
            "perturbations": dict(rec.perturbations),
            "relaxations": rec.relaxations,
        }

    # ── Eviction (REQ-2 AC4) ────────────────────────────────────────────

    def evict_if_needed(self) -> None:
        """Evict sessions by oldest last_touched if over MAX_BASELINES."""
        if len(self._baselines) <= MAX_BASELINES:
            return
        # Sort by last_touched ascending, keep newest MAX_BASELINES.
        sorted_sessions = sorted(
            self._baselines.keys(),
            key=lambda sid: self._baselines[sid].last_touched,
        )
        to_evict = len(self._baselines) - MAX_BASELINES
        for sid in sorted_sessions[:to_evict]:
            del self._baselines[sid]
            self._last_relax_update.pop(sid, None)
            self._last_relax_time.pop(sid, None)

    # ── Relaxation (REQ-1) ──────────────────────────────────────────────

    def relax_params(self, session_id: str) -> None:
        """Move (a, b, s) a bounded step toward the session's baseline.

        Reads current values from the FFI, computes a proportional step
        (RELAX_STEP fraction of distance to baseline), skips parameters within
        RELAX_DEADBAND, clamps to safe ranges, and writes via the FFI.

        If the FFI is unavailable, logs at debug and returns — never raises
        into the DER step path (REQ-1 AC6).
        """
        try:
            current = _ffi_get_state(session_id)
            if not current:
                # Engine unavailable — FFI returns empty dict.
                logger.debug(
                    "[ParamHomeostasis] relax_params skipped for %s (FFI unavailable)",
                    session_id,
                )
                return

            cur_a = current.get("a", 2.0)
            cur_b = current.get("b", 2.0)
            cur_s = current.get("s", 0.35)

            rec = self.get_baseline(session_id)
            base_a = rec.a
            base_b = rec.b
            base_s = rec.s

            # Proportional step: move RELAX_STEP fraction of the way toward
            # baseline. Since RELAX_STEP < 1.0, this never overshoots.
            new_a = cur_a + RELAX_STEP * (base_a - cur_a)
            new_b = cur_b + RELAX_STEP * (base_b - cur_b)
            new_s = cur_s + RELAX_STEP * (base_s - cur_s)

            # Deadband: skip parameters already near baseline.
            if abs(new_a - base_a) < RELAX_DEADBAND:
                new_a = base_a
            if abs(new_b - base_b) < RELAX_DEADBAND:
                new_b = base_b
            if abs(new_s - base_s) < RELAX_DEADBAND:
                new_s = base_s

            # Clamp to safe ranges (REQ-1 AC4).
            new_a = max(SAFE_A[0], min(SAFE_A[1], new_a))
            new_b = max(SAFE_B[0], min(SAFE_B[1], new_b))
            new_s = max(SAFE_S[0], min(SAFE_S[1], new_s))

            # Write back.
            ok = _ffi_set_params(session_id, new_a, new_b, new_s)
            if not ok:
                logger.debug(
                    "[ParamHomeostasis] relax_params set_params returned False for %s",
                    session_id,
                )
                return

            self.record_relaxation(session_id)

            logger.debug(
                "[ParamHomeostasis] relaxed %s: "
                "a=%.3f->%.3f b=%.3f->%.3f s=%.3f->%.3f "
                "(baseline a=%.3f b=%.3f s=%.3f)",
                session_id,
                cur_a,
                new_a,
                cur_b,
                new_b,
                cur_s,
                new_s,
                base_a,
                base_b,
                base_s,
            )
        except Exception as exc:
            logger.debug(
                "[ParamHomeostasis] relax_params failed for %s: %s",
                session_id,
                exc,
            )

    def maybe_relax(self, session_id: str, update_count: int) -> None:
        """Fire relaxation when update cadence OR wall-clock interval triggers.

        Uses per-session tracking of last-relax update count and last-relax
        wall-clock timestamp. Fires when:
          - update_count - last_relax_update >= RELAX_EVERY_N_UPDATES, OR
          - now - last_relax_time >= RELAX_MAX_INTERVAL_S (whichever first).

        The wall-clock floor (REQ-1 AC2b) exists because the phase scheduler's
        amplitude coupling can throttle background step rate under provider
        load, which would throttle an update-count-only cadence at exactly the
        wrong time.
        """
        now = time.time()
        with self._lock:
            last_update = self._last_relax_update.get(session_id, 0)
            last_time = self._last_relax_time.get(session_id, 0.0)

            update_trigger = (update_count - last_update) >= RELAX_EVERY_N_UPDATES
            time_trigger = (now - last_time) >= RELAX_MAX_INTERVAL_S

            if not update_trigger and not time_trigger:
                return

            # Update tracking BEFORE releasing lock (avoid race).
            self._last_relax_update[session_id] = update_count
            self._last_relax_time[session_id] = now

        # Relax outside the lock (FFI may block briefly).
        self.relax_params(session_id)


# ── Singleton accessors ──────────────────────────────────────────────────

_singleton: Optional[ParamHomeostasis] = None
_singleton_lock = threading.Lock()


def get_param_homeostasis() -> ParamHomeostasis:
    """Get the process-wide singleton homeostat."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = ParamHomeostasis()
        return _singleton


def reset_param_homeostasis() -> None:
    """Reset the singleton (used by tests for isolation)."""
    global _singleton
    with _singleton_lock:
        _singleton = None
