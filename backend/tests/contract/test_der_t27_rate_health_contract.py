"""CT-ON6 — REQ-9 (T27): rate-limit honesty — read-only rate-health surface.

Pins the T27 contract on the THREE seams REQ-9 names, against the REAL
``ProviderRateMeter`` singleton:

  AC1 — single-debit-per-step token accounting and the Retry-After clamp are
        retained. The clamp is already pinned by ``test_retry_after_parse``
        (9999s -> 30.0); here we pin the meter side: ``observe_429`` changes
        ONLY the learned ceiling — it never touches the sample/request window
        (no double-counting of demand), and ``rate_health``/``draw`` are
        strictly read-only (side-effect free, REQ-6 AC1 discipline).
  AC2 — CEILING_MIN_RPM / CEILING_MAX_RPM / PHASE_HARD_MAX_RPM are NOT raised
        (locked decision). We pin the exact values so a future "fix" that
        bumps them fails loudly here.
  AC3 — per-quota 429 frequency AND ceiling trajectory are exposed as a
        read-only signal: ``rate_health(quota_id)`` returns
        count_429_in_window, 429_per_min, last_429_at, ceiling_rpm,
        ceiling_trajectory (change points, oldest first), ceiling_trend.
        ``provider_metrics()`` surfaces it per quota for the outer loop.
  Edge — unmetered quotas (local/Ollama) report metered=False with 0 429
         count and infinite ceiling — never fabricated as saturated; a quota
         with no window reports the same shape, never an error.
"""
import time

from backend.agent.rate_meter import (
    CEILING_MAX_RPM,
    CEILING_INIT_RPM,
    CEILING_MIN_RPM,
    CEILING_PROBE_S,
    PHASE_HARD_MAX_RPM,
    clear_ceilings_for_testing,
    get_rate_meter,
    reset_rate_meter_for_testing,
)


def _meter():
    reset_rate_meter_for_testing()
    clear_ceilings_for_testing()
    return get_rate_meter()


# ── AC2: locked constants — never raised ─────────────────────────────────────


def test_ac2_ceiling_constants_not_raised():
    """REQ-9 AC2: the locked ceiling constants keep their exact values.

    These are the numbers REQ-9 forbids raising. Any change to them is a
    rate-ceiling change, not a demand-side fix, and must fail here.
    """
    assert CEILING_MIN_RPM == 15.0
    assert CEILING_MAX_RPM == 600.0
    assert PHASE_HARD_MAX_RPM == 120.0


# ── AC1: observe_429 does not touch the demand window ────────────────────────


def test_ac1_429_observation_never_double_counts_demand():
    """REQ-9 AC1: a 429 adjusts the ceiling but NOT the request window.

    A 429 is a rejection of a request already counted at send time
    (_record_attempt). If observe_429 also recorded a sample, one logical call
    would appear twice in the window (demand inflation) and the gate would
    throttle based on phantom headroom. The window must stay untouched.
    """
    _m = _meter()
    _m.ensure_window("quotaA", metered_flag=True)
    # Two real requests land in the window...
    _m.record_request("quotaA", tokens=100, priority=0, estimated=True)
    _m.record_request("quotaA", tokens=100, priority=0, estimated=True)
    _draw_before = _m.draw("quotaA")
    assert _draw_before["requests"] == 2
    # ...then three 429s arrive. Demand must NOT grow.
    for _ in range(3):
        _m.observe_429("quotaA", retry_after=1.0)
    _draw_after = _m.draw("quotaA")
    assert _draw_after["requests"] == 2, (
        "observe_429 must not add demand samples (single-debit, REQ-9 AC1)"
    )
    # But the ceiling DID decay — the 429 was observed where it belongs.
    assert _m.get_ceiling("quotaA") < CEILING_MAX_RPM


# ── AC3: read-only rate-health surface ───────────────────────────────────────


def test_ac3_rate_health_exposes_429_frequency_and_trajectory():
    """REQ-9 AC3: rate_health reports 429 count/frequency, last 429, the
    ceiling trajectory (decay + recovery change points), and the trend."""
    _m = _meter()
    _m.ensure_window("quotaA", metered_flag=True)
    _init = _m.get_ceiling("quotaA")

    # Two 429s -> two decay change points, count=2 within the window.
    _m.observe_429("quotaA", retry_after=1.0)
    _m.observe_429("quotaA", retry_after=1.0)
    _h = _m.rate_health("quotaA")

    assert _h["metered"] is True
    assert _h["count_429_in_window"] == 2
    # 2 429s in a 60s window = 2.0 per minute.
    assert _h["429_per_min"] == 2.0
    assert _h["last_429_at"] is not None
    assert _h["ceiling_rpm"] < _init  # decayed
    # Trajectory: seeded initial ceiling + two decay change points, oldest
    # first. First 429 floors 30 -> 15; the second (at the floor) still
    # appends a pressure point so the trend stays "falling".
    _traj = _h["ceiling_trajectory"]
    assert len(_traj) == 3
    assert _traj[0][0] <= _traj[1][0] <= _traj[2][0]
    assert _traj[0][1] == _init  # seeded starting ceiling
    assert _traj[2][1] < _traj[0][1]
    assert _h["ceiling_trend"] == "falling"

    # Recovery: after the probe period, additive increase appends an UP
    # change point and the trend turns rising.
    _w = _m._windows["quotaA"]
    _w.last_429_at = time.time() - (CEILING_PROBE_S + 1)
    _m.record_request("quotaA", tokens=100, priority=0, estimated=True)
    _h2 = _m.rate_health("quotaA")
    assert len(_h2["ceiling_trajectory"]) == 4
    assert _h2["ceiling_trajectory"][-1][1] > _h2["ceiling_trajectory"][-2][1]
    assert _h2["ceiling_trend"] == "rising"


def test_ac3_rate_health_windowed_count_expires():
    """REQ-9 AC3: the 429 FREQUENCY is windowed — old 429s age out of
    count_429_in_window once outside METER_WINDOW_S (persistent saturation is
    counted while current, then reported as healed, never silent)."""
    _m = _meter()
    _m.ensure_window("quotaA", metered_flag=True)
    _m.observe_429("quotaA", retry_after=1.0)
    assert _m.rate_health("quotaA")["count_429_in_window"] == 1
    # Age the 429 observation beyond the window.
    _w = _m._windows["quotaA"]
    _w._429_ts[0] = time.time() - 10_000.0
    assert _m.rate_health("quotaA")["count_429_in_window"] == 0
    assert _m.rate_health("quotaA")["429_per_min"] == 0.0
    # last_429_at still reported (never silent) — the event happened.
    assert _m.rate_health("quotaA")["last_429_at"] is not None


def test_ac3_rate_health_is_read_only():
    """REQ-9 AC3 + REQ-6 AC1: polling rate_health mutates nothing — the
    trajectory, samples and 429 timestamps are identical before and after."""
    _m = _meter()
    _m.ensure_window("quotaA", metered_flag=True)
    for _ in range(3):
        _m.observe_429("quotaA", retry_after=1.0)
    _traj_before = list(_m._windows["quotaA"].ceiling_trajectory)
    _ts_before = list(_m._windows["quotaA"]._429_ts)
    _draw_before = _m.draw("quotaA")

    for _ in range(5):
        _m.rate_health("quotaA")

    assert list(_m._windows["quotaA"].ceiling_trajectory) == _traj_before
    assert list(_m._windows["quotaA"]._429_ts) == _ts_before
    assert _m.draw("quotaA") == _draw_before


# ── Edge cases ───────────────────────────────────────────────────────────────


def test_edge_unmetered_quota_never_fabricated_saturated():
    """REQ-9 edge case: local/Ollama quotas are unmetered — rate_health reports
    metered=False with zero 429s and an infinite ceiling, never a fabricated
    saturation signal that would make the outer loop throttle a free provider."""
    _m = _meter()
    _m.ensure_window("quota_local", metered_flag=False)
    # Even if a 429 somehow arrives, an unmetered quota ignores it.
    _m.observe_429("quota_local", retry_after=1.0)
    _h = _m.rate_health("quota_local")
    assert _h["metered"] is False
    assert _h["count_429_in_window"] == 0
    assert _h["429_per_min"] == 0.0
    assert _h["ceiling_rpm"] == float("inf")
    assert _h["ceiling_trajectory"] == []
    assert _h["ceiling_trend"] == "stable"


def test_edge_unknown_quota_returns_shape_never_error():
    """REQ-9 edge case: a quota with no window returns the same read-only
    shape (unmetered, zeroed) — polling an unknown quota never raises."""
    _m = _meter()
    _h = _m.rate_health("quota_never_seen")
    assert _h["metered"] is False
    assert _h["count_429_in_window"] == 0
    assert _h["429_per_min"] == 0.0
    assert _h["ceiling_rpm"] == float("inf")
    assert _h["ceiling_trajectory"] == []


def test_edge_persistent_saturation_counted_not_silent():
    """REQ-9 edge case: persistent saturation is COUNTED (each 429 observed),
    and the decayed ceiling is always visible — the signal never vanishes."""
    _m = _meter()
    _m.ensure_window("quotaA", metered_flag=True)
    for _ in range(20):
        _m.observe_429("quotaA", retry_after=1.0)
    _h = _m.rate_health("quotaA")
    assert _h["count_429_in_window"] == 20
    assert _h["ceiling_rpm"] == CEILING_MIN_RPM  # floored, but reported
    assert _h["ceiling_trend"] == "falling"
    # Seeded initial ceiling + one pressure point per 429 (20), even at the
    # floor — the trajectory never stops recording pressure.
    assert len(_h["ceiling_trajectory"]) == 21
    assert _h["ceiling_trajectory"][0][1] == CEILING_INIT_RPM
    assert _h["ceiling_trajectory"][-1][1] == CEILING_MIN_RPM
