"""Per-provider adaptive rate meter (Wave 2 of caducean-phase-scheduler).

Keyed by **quota identity** ``quota_key(inst) = api_base_url|sha256(credential)[:12]``
(D-9), NOT by ``ProviderInstance.id`` (over-partitions) and NOT by ``api_base_url``
alone (under-partitions). The transport cache is left untouched (D-9).

Thread-safe singleton (same discipline as ``coupled_registry.py``). Samples are
evicted by age (``METER_WINDOW_S``) and bounded by count (``METER_MAX_SAMPLES``).
``draw()`` is strictly side-effect free (REQ-6 AC1). The learned ceiling uses
AIMD: multiplicative decrease on 429, additive increase after a probe period
without 429. A hard rail ``PHASE_HARD_MAX_RPM`` is never raised by learning
(T2.6). Learned ceilings persist to ``.mcm/provider_ceilings.json`` (T2.4) with
the same corrupt-file tolerance as ``outer_loop._load_params``.

Only ``ProviderKind.API`` is metered; LOCAL_OPENAI / OLLAMA / INPROCESS are
unmetered and never gated (D-9 / provider.py:16-22).
"""

from __future__ import annotations

import collections
import hashlib
import json
import logging
import os
import threading
import time as _perf_t
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.keyring import get_secret

logger = logging.getLogger(__name__)


# ── Tunables (env-overridable) ──────────────────────────────────────────────
def _env_float(name: str, default: float) -> float:
    try:
        _v = os.environ.get(name)
        return float(_v) if _v is not None else default
    except (TypeError, ValueError):
        return default


METER_WINDOW_S = _env_float("IRIS_METER_WINDOW_S", 60.0)
METER_MAX_SAMPLES = 512

CEILING_INIT_RPM = _env_float("IRIS_CEILING_INIT_RPM", 30.0)
CEILING_INIT_TPM = _env_float("IRIS_CEILING_INIT_TPM", 60000.0)
CEILING_MD = 0.5
CEILING_AI_RPM = _env_float("IRIS_CEILING_AI_RPM", 2.0)
CEILING_PROBE_S = _env_float("IRIS_CEILING_PROBE_S", 120.0)
# AIMD floor. This is NOT a per-caller budget: the quota is keyed on the
# transport (_quota_id), so every reasoning-role call in the app shares it —
# planning, tool decisions, synthesis, gap-filling, data extraction, topic
# extraction. A single user question legitimately spends ~10+ calls, so a
# floor of 3.0 could not fund even one task: after a few 429s the ceiling
# halved to the floor and every subsequent crawl returned an empty plan,
# surfacing as "no usable sources" — a quota problem wearing a bug's face.
# 15 keeps meaningful back-off headroom below CEILING_INIT_RPM (30) while
# still funding one complete task.
CEILING_MIN_RPM = _env_float("IRIS_CEILING_MIN_RPM", 15.0)
CEILING_MAX_RPM = _env_float("IRIS_CEILING_MAX_RPM", 600.0)
PHASE_HARD_MAX_RPM = _env_float("IRIS_PHASE_HARD_MAX_RPM", 120.0)

_CEILINGS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", ".mcm", "provider_ceilings.json"
)


@dataclass(frozen=True)
class Sample:
    """One observed request. Frozen — appended to a deque, never mutated."""

    ts: float
    tokens: int
    estimated: bool
    priority: int


@dataclass
class ProviderWindow:
    """Per-quota sliding window + learned ceiling."""

    quota_id: str
    metered: bool
    samples: Deque[Sample] = field(default_factory=lambda: collections.deque(maxlen=METER_MAX_SAMPLES))
    label_ids: List[str] = field(default_factory=list)
    ceiling_rpm: float = CEILING_INIT_RPM
    ceiling_tpm: float = CEILING_INIT_TPM
    hard_max_rpm: float = PHASE_HARD_MAX_RPM
    last_429_at: Optional[float] = None
    count_429_in_window: int = 0
    configured_max_rpm: Optional[float] = None
    # REQ-9 AC3 (T27): read-only rate-health inputs. 429 observation timestamps
    # feed the windowed 429 frequency; ceiling_trajectory records (ts, rpm)
    # change points (each 429 decay + each post-probe recovery) so the outer
    # loop can see the trajectory, not just the current value. Both bounded —
    # memory footprint is capped regardless of session length.
    _429_ts: Deque[float] = field(
        default_factory=lambda: collections.deque(maxlen=METER_MAX_SAMPLES)
    )
    ceiling_trajectory: Deque[tuple] = field(
        default_factory=lambda: collections.deque(maxlen=128)
    )


def quota_key(inst: ProviderInstance) -> str:
    """Quota identity (D-9): api_base_url | sha256(credential)[:12].

    The credential is SHA-256'd and truncated to 12 hex chars — never persisted,
    never logged (REQ-7 AC5, D-9 security note).
    """
    _cred = get_secret(inst.id) or getattr(inst, "api_key", "") or ""
    if _cred:
        _h = hashlib.sha256(_cred.encode("utf-8")).hexdigest()[:12]
    else:
        _h = "nocred"
    return f"{inst.api_base_url}|{_h}"


def metered(inst: ProviderInstance) -> bool:
    """Only API providers are metered; local/open-weight providers are not."""
    return inst.kind == ProviderKind.API


class ProviderRateMeter:
    """Process-wide rate meter, keyed by quota identity. Thread-safe."""

    def __init__(self) -> None:
        self._windows: Dict[str, ProviderWindow] = {}
        self._lock = threading.Lock()
        self._rail_logged: set = set()
        self._ceilings_path = _CEILINGS_PATH
        self._load_ceilings()

    # ── window lifecycle ──────────────────────────────────────────────────
    def ensure_window(self, quota_id: str, metered_flag: bool) -> None:
        """Create the window if absent and set its metered flag.

        Called by the transport at construction (router._build_transport), where
        ``inst`` is in scope, so the meter learns whether this quota is metered
        without needing the ProviderInstance at record time.
        """
        with self._lock:
            _w = self._windows.get(quota_id)
            if _w is None:
                _w = self._new_window(quota_id)
                self._windows[quota_id] = _w
            _w.metered = metered_flag

    def _new_window(self, quota_id: str) -> ProviderWindow:
        _now = _perf_t.time()
        return ProviderWindow(
            quota_id=quota_id,
            metered=True,  # overridden by ensure_window when known
            samples=collections.deque(maxlen=METER_MAX_SAMPLES),
            label_ids=[],
            ceiling_rpm=CEILING_INIT_RPM,
            ceiling_tpm=CEILING_INIT_TPM,
            hard_max_rpm=PHASE_HARD_MAX_RPM,
            last_429_at=None,
            count_429_in_window=0,
            configured_max_rpm=None,
            _429_ts=collections.deque(maxlen=METER_MAX_SAMPLES),
            # REQ-9 AC3 (T27): seed the trajectory with the starting ceiling so
            # the trend has a reference. With CEILING_MD=0.5 and a MIN floor of
            # 15, the FIRST 429 already floors the ceiling (30 -> 15); without
            # the seed, a quota pinned at the floor under continued pressure
            # would read "stable" instead of "falling".
            ceiling_trajectory=collections.deque([(_now, CEILING_INIT_RPM)], maxlen=128),
        )

    # ── recording (T2.2) ─────────────────────────────────────────────────
    def record_request(
        self,
        quota_id: str,
        tokens: int,
        priority: int,
        estimated: bool,
        label: Optional[str] = None,
    ) -> None:
        """Record a completed request against the quota.

        Keyed by quota identity (REQ-6 AC1). ``label`` is the instance id, kept
        for logs only (REQ-6 AC1b). Unmetered quotas are not tracked.
        """
        with self._lock:
            _w = self._windows.get(quota_id)
            if _w is None:
                _w = self._new_window(quota_id)
                self._windows[quota_id] = _w
            if not _w.metered:
                return  # local/open-weight provider: no metering needed
            # AIMD additive increase after a probe period without 429 (T2.3)
            _now = _perf_t.time()
            if _w.last_429_at is not None and (_now - _w.last_429_at) > CEILING_PROBE_S:
                _cap = min(CEILING_MAX_RPM, _w.configured_max_rpm or CEILING_MAX_RPM)
                _before = _w.ceiling_rpm
                _w.ceiling_rpm = min(_w.ceiling_rpm + CEILING_AI_RPM, _cap)
                _w.last_429_at = None  # probe succeeded; arm again on next 429
                # REQ-9 AC3 (T27): trajectory change point for the recovery
                # half of the AIMD cycle.
                if _w.ceiling_rpm != _before:
                    _w.ceiling_trajectory.append((_now, _w.ceiling_rpm))
            self._evict(_w, _now)
            _w.samples.append(Sample(_now, int(tokens), bool(estimated), int(priority)))
            if label and label not in _w.label_ids:
                _w.label_ids.append(label)

    def gap_stats(self, quota_id: str) -> Dict[str, float]:
        """REQ-20 AC6 / REQ-22 AC6: inter-request gap statistics for a quota.

        The gaps are the wall-clock deltas between **successive recorded
        requests** — the quantity the ">=50% stddev reduction" success criterion
        is defined over. This is NOT ``now - last_advance_at`` (advance staleness),
        which the earlier ``provider_metrics`` reported by mistake and which cannot
        show whether requests are evenly spread.

        Returns ``{count, mean_gap_s, stddev_gap_s, min_gap_s, max_gap_s}``.
        A quota with fewer than 2 samples in the window has no measurable gap and
        returns zeros with its real ``count``. Side-effect free.
        """
        with self._lock:
            _w = self._windows.get(quota_id)
            if _w is None:
                return {
                    "count": 0, "mean_gap_s": 0.0, "stddev_gap_s": 0.0,
                    "min_gap_s": 0.0, "max_gap_s": 0.0,
                }
            _cutoff = _perf_t.time() - METER_WINDOW_S
            _ts = sorted(_s.ts for _s in _w.samples if _s.ts >= _cutoff)
        if len(_ts) < 2:
            return {
                "count": len(_ts), "mean_gap_s": 0.0, "stddev_gap_s": 0.0,
                "min_gap_s": 0.0, "max_gap_s": 0.0,
            }
        _gaps = [_ts[i + 1] - _ts[i] for i in range(len(_ts) - 1)]
        _mean = sum(_gaps) / len(_gaps)
        _var = sum((_g - _mean) ** 2 for _g in _gaps) / len(_gaps)
        return {
            "count": len(_ts),
            "mean_gap_s": _mean,
            "stddev_gap_s": _var ** 0.5,
            "min_gap_s": min(_gaps),
            "max_gap_s": max(_gaps),
        }

    def draw(self, quota_id: str) -> Dict[str, float]:
        """Return {requests, tokens, window_s} for the quota. Side-effect free.

        Does NOT evict or mutate samples (REQ-6 AC1). Callers use this to decide
        whether to gate a pending call.
        """
        with self._lock:
            _w = self._windows.get(quota_id)
            if _w is None:
                return {"requests": 0, "tokens": 0, "window_s": METER_WINDOW_S}
            _now = _perf_t.time()
            _cutoff = _now - METER_WINDOW_S
            _req = 0
            _tok = 0
            for _s in _w.samples:
                if _s.ts >= _cutoff:
                    _req += 1
                    _tok += _s.tokens
            return {"requests": _req, "tokens": _tok, "window_s": METER_WINDOW_S}

    # ── rate-health surface (REQ-9 AC3 / T27) ───────────────────────────────
    def rate_health(self, quota_id: str) -> Dict[str, Any]:
        """REQ-9 AC3: read-only per-quota rate-health signal for the outer loop.

        Exposes the two quantities REQ-9 AC3 names — 429 frequency and ceiling
        trajectory — plus the current effective ceiling, for the outer loop to
        consume WITHOUT changing rate-limit semantics (AC1: single-debit + the
        Retry-After clamp are untouched; AC2: no ceiling constant is raised).

        Returns:
          - metered            : whether this quota is gated (unmetered local /
                                 Ollama quotas report metered=False and are
                                 never fabricated as saturated — REQ-9 edge
                                 case).
          - count_429_in_window: 429 observations within METER_WINDOW_S.
          - 429_per_min        : frequency = count_429_in_window / window
                                 minutes (0.0 for unmetered).
          - last_429_at        : epoch of the most recent 429 (None if never).
          - ceiling_rpm        : effective ceiling (same min-with-rail /
                                 configured-max logic as get_ceiling).
          - ceiling_trajectory : [(ts, ceiling_rpm)] change points, oldest
                                 first — each AIMD decay and recovery. Bounded.
          - ceiling_trend      : "falling" | "rising" | "stable" — direction of
                                 the last trajectory movement.
          - window_s           : the metering window.

        Side-effect free (strictly read-only): samples, timestamps and
        trajectory are never evicted or mutated here — polling this cannot
        perturb the behavior being measured.
        """
        with self._lock:
            _w = self._windows.get(quota_id)
            if _w is None or not _w.metered:
                return {
                    "metered": False,
                    "count_429_in_window": 0,
                    "429_per_min": 0.0,
                    "last_429_at": None,
                    "ceiling_rpm": float("inf"),
                    "ceiling_trajectory": [],
                    "ceiling_trend": "stable",
                    "window_s": METER_WINDOW_S,
                }
            _now = _perf_t.time()
            _cutoff = _now - METER_WINDOW_S
            _c429 = sum(1 for _ts in _w._429_ts if _ts >= _cutoff)
            _eff = min(_w.ceiling_rpm, PHASE_HARD_MAX_RPM)
            if _w.configured_max_rpm is not None:
                _eff = min(_eff, _w.configured_max_rpm)
            _traj = list(_w.ceiling_trajectory)
            _trend = "stable"
            # Direction of the LAST NON-FLAT movement. Floor-pinned pressure
            # points (repeated 429s at CEILING_MIN_RPM append 15 -> 15) are
            # skipped so a saturated quota still reads "falling"; a recovery
            # spike (15 -> 17 after the probe) reads "rising" even though it
            # is still below the seeded initial ceiling.
            for _i in range(len(_traj) - 1, 0, -1):
                _prev_rpm = _traj[_i - 1][1]
                _cur_rpm = _traj[_i][1]
                if abs(_cur_rpm - _prev_rpm) > 1e-9:
                    _trend = (
                        "falling" if _cur_rpm < _prev_rpm else "rising"
                    )
                    break
            return {
                "metered": True,
                "count_429_in_window": _c429,
                "429_per_min": round(
                    _c429 / max(METER_WINDOW_S, 1e-9) * 60.0, 4
                ),
                "last_429_at": _w.last_429_at,
                "ceiling_rpm": _eff,
                "ceiling_trajectory": [
                    (round(ts, 3), round(rpm, 3)) for ts, rpm in _traj
                ],
                "ceiling_trend": _trend,
                "window_s": METER_WINDOW_S,
            }

    # ── 429 observation (T2.3 / T2.5) ───────────────────────────────────────
    def observe_429(self, quota_id: str, retry_after: Optional[float] = None) -> None:
        """Multiplicative-decrease the ceiling on a 429 (T2.3).

        Floored at CEILING_MIN_RPM. Persists the learned ceiling. Unmetered
        quotas ignore 429 (they never emit one, but be safe).
        """
        with self._lock:
            _w = self._windows.get(quota_id)
            if _w is None:
                _w = self._new_window(quota_id)
                self._windows[quota_id] = _w
            if not _w.metered:
                return
            _w.ceiling_rpm = max(CEILING_MIN_RPM, _w.ceiling_rpm * CEILING_MD)
            _w.last_429_at = _perf_t.time()
            _w.count_429_in_window += 1
            # REQ-9 AC3 (T27): timestamp + trajectory change point for the
            # read-only rate-health surface.
            _w._429_ts.append(_w.last_429_at)
            _w.ceiling_trajectory.append((_w.last_429_at, _w.ceiling_rpm))
            self._save_ceilings()

    # ── ceiling read (T2.3 / T2.6) ──────────────────────────────────────────
    def get_ceiling(self, quota_id: str) -> float:
        """Effective RPM ceiling: min(learned, hard rail, configured max).

        The hard rail (PHASE_HARD_MAX_RPM) is never raised by learning (T2.6).
        Unmetered quotas return inf (never gated).
        """
        with self._lock:
            _w = self._windows.get(quota_id)
            if _w is None or not _w.metered:
                return float("inf")
            _eff = min(_w.ceiling_rpm, PHASE_HARD_MAX_RPM)
            if _w.configured_max_rpm is not None:
                _eff = min(_eff, _w.configured_max_rpm)
            # APPLY THE FLOOR ON READ, not only on decay.
            # _record_429 clamps with max(CEILING_MIN_RPM, ...) when it halves,
            # but the ceiling is PERSISTED (see _load) and restored verbatim on
            # the next start. A ceiling learned under an older, lower floor
            # therefore survived a restart and was returned unchanged — raising
            # CEILING_MIN_RPM had NO effect on an existing window, which is
            # exactly how a 3.0 rpm ceiling kept starving every crawl after the
            # floor was raised to 15. The floor must never exceed the rails
            # above it, so clamp it by them first.
            _floor = min(CEILING_MIN_RPM, PHASE_HARD_MAX_RPM)
            if _w.configured_max_rpm is not None:
                _floor = min(_floor, _w.configured_max_rpm)
            _eff = max(_eff, _floor)
            # Log once per provider when the rail is the binding constraint
            if _w.ceiling_rpm > PHASE_HARD_MAX_RPM and _w.quota_id not in self._rail_logged:
                logger.warning(
                    "[rate_meter] hard rail PHASE_HARD_MAX_RPM=%.1f binding for %s "
                    "(learned ceiling %.1f)",
                    PHASE_HARD_MAX_RPM, _w.quota_id, _w.ceiling_rpm,
                )
                self._rail_logged.add(_w.quota_id)
            return _eff

    def set_configured_max(self, quota_id: str, max_rpm: Optional[float]) -> None:
        """Set the provider-configured max RPM (from InferenceConfig)."""
        with self._lock:
            _w = self._windows.get(quota_id)
            if _w is None:
                _w = self._new_window(quota_id)
                self._windows[quota_id] = _w
            _w.configured_max_rpm = max_rpm

    # ── internals ──────────────────────────────────────────────────────────
    def _evict(self, _w: ProviderWindow, _now: float) -> None:
        _cutoff = _now - METER_WINDOW_S
        while _w.samples and _w.samples[0].ts < _cutoff:
            _w.samples.popleft()

    def _save_ceilings(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._ceilings_path), exist_ok=True)
            _data = {
                _qid: {
                    "ceiling_rpm": _w.ceiling_rpm,
                    "ceiling_tpm": _w.ceiling_tpm,
                }
                for _qid, _w in self._windows.items()
                if _w.metered
            }
            with open(self._ceilings_path, "w", encoding="utf-8") as f:
                json.dump(_data, f, indent=2)
        except Exception as _e:  # pragma: no cover — best-effort persistence
            logger.warning("[rate_meter] ceilings save failed: %s", _e)

    def _load_ceilings(self) -> None:
        try:
            if os.path.exists(self._ceilings_path):
                with open(self._ceilings_path, "r", encoding="utf-8") as f:
                    _data = json.load(f)
                if isinstance(_data, dict):
                    for _qid, _v in _data.items():
                        # Ignore unknown keys (T2.4 corrupt-file tolerance)
                        if not isinstance(_qid, str) or not isinstance(_v, dict):
                            continue
                        _w = self._new_window(_qid)
                        _w.ceiling_rpm = float(_v.get("ceiling_rpm", CEILING_INIT_RPM))
                        _w.ceiling_tpm = float(_v.get("ceiling_tpm", CEILING_INIT_TPM))
                        self._windows[_qid] = _w
        except Exception as _e:  # pragma: no cover — corrupt file tolerated
            logger.debug("[rate_meter] ceilings load failed: %s", _e)

    def reset_for_testing(self) -> None:
        """Clear all windows and rail-log state (test isolation)."""
        with self._lock:
            self._windows.clear()
            self._rail_logged.clear()


# ── Singleton accessor (mirrors coupled_registry.py:225-238) ────────────────
_singleton: Optional[ProviderRateMeter] = None
_singleton_lock = threading.Lock()


def get_rate_meter() -> ProviderRateMeter:
    """Get the process-wide singleton meter."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = ProviderRateMeter()
        return _singleton


def reset_rate_meter_for_testing() -> None:
    """Reset the singleton (used by tests for isolation)."""
    global _singleton
    with _singleton_lock:
        _singleton = None


def clear_ceilings_for_testing() -> None:
    """Delete the persisted ceilings file (used by tests for isolation).

    ``reset_rate_meter_for_testing`` clears the in-memory singleton, but the
    next ``get_rate_meter()`` reloads from ``.mcm/provider_ceilings.json``. This
    helper removes that file so tests start from a clean learned state.
    """
    try:
        if os.path.exists(_CEILINGS_PATH):
            os.remove(_CEILINGS_PATH)
    except OSError:
        pass
