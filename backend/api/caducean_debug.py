"""Read-only Caducean introspection endpoint — for live manual verification.

Exists because the phase scheduler and multi-session coupling both ship DISABLED
(`IRIS_PHASE_SCHEDULER`, `IRIS_COUPLING_ENABLED`), so a default app run verifies
nothing about them, and `provider_metrics()` / the phase registry are otherwise
in-process only — unreachable from a running app without a debugger.

`GET /api/debug/caducean` returns flag states, the oscillator registry, per-quota
rate-meter draw + learned ceilings + **inter-request gap statistics**, the coupled
registry with each session's assigned winding numbers, and the pending Sub-Loop
batch groups.

Strictly read-only and side-effect free: every accessor used here is documented as
such (`provider_metrics`, `draw`, `gap_stats`, `snapshot`, `list_sessions`). It
advances no phase, records no request, and mutates no state — polling it cannot
perturb the very behavior you are measuring.

Never raises: any subsystem that is unavailable reports `{"error": ...}` in its own
section rather than failing the whole response, so a partial system still yields a
usable picture.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()


def _flags() -> dict[str, Any]:
    """Feature-flag states, with the effective boolean the code actually uses."""
    _ps_raw = os.environ.get("IRIS_PHASE_SCHEDULER", "(unset)")
    _cp_raw = os.environ.get("IRIS_COUPLING_ENABLED", "(unset)")
    out: dict[str, Any] = {
        "IRIS_PHASE_SCHEDULER": {"raw": _ps_raw, "effective": None},
        "IRIS_COUPLING_ENABLED": {"raw": _cp_raw, "effective": None},
    }
    try:
        from backend.agent.phase_manager import _flag_enabled

        out["IRIS_PHASE_SCHEDULER"]["effective"] = bool(_flag_enabled())
    except Exception as exc:  # pragma: no cover - import guard
        out["IRIS_PHASE_SCHEDULER"]["error"] = str(exc)[:200]
    try:
        from backend.agent.coupled_registry import coupling_enabled

        out["IRIS_COUPLING_ENABLED"]["effective"] = bool(coupling_enabled())
    except Exception as exc:  # pragma: no cover - import guard
        out["IRIS_COUPLING_ENABLED"]["error"] = str(exc)[:200]
    return out


def _scheduler() -> dict[str, Any]:
    """Oscillator registry + per-quota meter, ceiling, and gap statistics."""
    try:
        from backend.agent.phase_manager import get_registry, provider_metrics
        from backend.agent.rate_meter import get_rate_meter
    except Exception as exc:
        return {"error": f"scheduler modules unavailable: {exc}"[:200]}

    try:
        metrics = provider_metrics()  # side-effect free
        meter = get_rate_meter()
        for _qid, _grp in metrics.items():
            # gap_stats is the "stream, not a firework" measurement: stddev of
            # deltas between successive REQUESTS (not advance staleness).
            _grp.setdefault("gap_stats", meter.gap_stats(_qid))
        return {
            "oscillator_count": len(get_registry().snapshot()),
            "quotas": metrics,
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}


def _coupling() -> dict[str, Any]:
    """Coupled sessions with winding numbers and effective cycle speed."""
    try:
        from backend.agent.coupled_registry import get_coupled_registry
    except Exception as exc:
        return {"error": f"coupled_registry unavailable: {exc}"[:200]}

    try:
        reg = get_coupled_registry()
        sessions = []
        for sid in reg.list_sessions():
            rec = reg.get_session(sid)
            if rec is None:
                continue
            sessions.append({
                "session_id": sid,
                "l": rec.l,
                "m": rec.m,
                "c_eff": round(rec.c_eff, 6),
                "last_xi": round(rec.last_xi, 4),
                "last_u": round(rec.last_u, 4),
            })
        distinct = sorted({s["c_eff"] for s in sessions})
        return {
            "session_count": len(sessions),
            "sessions": sessions,
            "distinct_c_eff": distinct,
            # Coupling only differentiates roles when >=2 sessions share the
            # registry; a single session produces no nucleus/barrier pair.
            "differentiation_possible": len(sessions) >= 2,
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}


def _batching() -> dict[str, Any]:
    """Pending Sub-Loop batch groups (Wave 4)."""
    try:
        from backend.agent.batch_dispatch import get_batcher
    except Exception as exc:
        return {"error": f"batch_dispatch unavailable: {exc}"[:200]}

    try:
        batcher = get_batcher()
        groups = []
        with batcher._lock:  # read-only snapshot under the batcher's own lock
            for _jp, _g in batcher._groups.items():
                groups.append({
                    "join_point": _jp,
                    "children": [
                        getattr(c, "step_id", "?") for c in _g.children
                    ],
                    "quota_id": _g.quota_id,
                })
        return {"pending_group_count": len(groups), "pending_groups": groups}
    except Exception as exc:
        return {"error": str(exc)[:200]}


def _memory() -> dict[str, Any]:
    """Coordinate-addressed recall: is `coords_from` actually being written?

    This is the UNEXERCISED item. The plumbing was repaired (one lookup key, one
    chain identity, canonical format) but a repo-wide scan found ZERO populated
    `coords_from` rows — so trajectory-proximity recall has never returned a
    result. `populated_coords_from` going from 0 to non-zero during a live run is
    the single measurement that moves it from UNEXERCISED to PROVEN.
    """
    try:
        from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder

        rec = CaduceanTrajectoryRecorder()
        conn = rec._conn
    except Exception as exc:
        return {"error": f"recorder unavailable: {exc}"[:200]}

    out: dict[str, Any] = {}
    try:
        out["trajectory_rows"] = conn.execute(
            "SELECT COUNT(*) FROM caducean_trajectories"
        ).fetchone()[0]
    except Exception as exc:
        out["trajectory_rows"] = f"error: {exc}"[:120]

    # Every table carrying coords_from, and how many rows actually have one.
    tables: list[dict[str, Any]] = []
    try:
        for (tname,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall():
            try:
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({tname})")]
                if "coords_from" not in cols:
                    continue
                total = conn.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
                populated = conn.execute(
                    f"SELECT COUNT(*) FROM {tname} "
                    "WHERE coords_from IS NOT NULL AND coords_from != ''"
                ).fetchone()[0]
                sample = [
                    r[0] for r in conn.execute(
                        f"SELECT coords_from FROM {tname} "
                        "WHERE coords_from IS NOT NULL AND coords_from != '' LIMIT 3"
                    )
                ]
                tables.append({
                    "table": tname,
                    "rows": total,
                    "populated_coords_from": populated,
                    "sample": sample,
                })
            except Exception:
                continue
    except Exception as exc:
        out["tables_error"] = str(exc)[:200]

    out["coordinate_tables"] = tables
    _pop = sum(t.get("populated_coords_from", 0) for t in tables)
    out["total_populated_coords_from"] = _pop
    out["status"] = "PROVEN" if _pop > 0 else "UNEXERCISED (no coords_from written yet)"
    return out


def _outer_loop() -> dict[str, Any]:
    """Outer-loop (AIDE^2) compound gate — shows WHICH guards are actually live.

    The gate is specified with three signals but only one is functional:
    `verified_fraction` is a hardcoded constant and `tokens_per_verified` reads a
    column no production caller populates. Rather than assert that, this reports
    the computed values so a constant 1.0 and a constant 0.0 are visible directly.
    Repair is specs/der-loop-integrity-display/ REQ-13 / Wave 10.
    """
    try:
        from backend.agent.outer_loop import OuterTuner
    except Exception as exc:
        return {"error": f"outer_loop unavailable: {exc}"[:200]}

    try:
        tuner = OuterTuner()
        exits = tuner.recorder.get_session_exits(limit=200)
        held_out = tuner._heldout_batch(exits)
        score = tuner._score(held_out) if held_out else {}
        diagnosis = []
        if score:
            if score.get("verified_fraction") == 1.0:
                diagnosis.append(
                    "verified_fraction == 1.0 — hardcoded constant, guard cannot fire"
                )
            if score.get("tokens_per_verified") == 0.0:
                diagnosis.append(
                    "tokens_per_verified == 0.0 — tokens_total never populated, "
                    "guard cannot fire"
                )
        return {
            "session_exit_rows": len(exits),
            "held_out_count": len(held_out),
            "held_out_score": score,
            "params": dict(tuner.params),
            # With no session-exit rows the metrics cannot be computed, so the
            # guards cannot be diagnosed either. Report that honestly rather than
            # defaulting to "3 live", which would read as all-clear.
            "live_guards": (3 - len(diagnosis)) if score else "unknown (no session-exit rows yet)",
            "dead_guards": diagnosis,
            "note": (
                "Drive at least one session to completion so a session-exit row is "
                "written, then re-read. Expect verified_fraction == 1.0 and "
                "tokens_per_verified == 0.0 — two of three guards dead until "
                "der-loop-integrity-display REQ-13 / Wave 10 lands."
            ) if not score else None,
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}


@router.get("/api/debug/caducean")
async def caducean_debug() -> dict[str, Any]:
    """Live Caducean state for manual verification. Read-only.

    Poll this while driving the app by hand to confirm the flag-off components
    actually engage when enabled. See `docs/CADUCEAN_LIVE_TEST_PLAN.md`.
    """
    return {
        "flags": _flags(),
        "scheduler": _scheduler(),
        "coupling": _coupling(),
        "batching": _batching(),
        "memory": _memory(),
        "outer_loop": _outer_loop(),
    }
