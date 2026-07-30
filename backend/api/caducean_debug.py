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


def _context_window() -> dict[str, Any]:
    """Resolved context window + its source, and provider load state.

    REQ-2 AC4 / REQ-10 AC1+AC5: an unknown window must be VISIBLE (tagged
    ``default``), not silent, and the resolved window + source must be reachable
    from a running app for manual verification. Read-only.
    """
    out: dict[str, Any] = {}
    try:
        from backend.agent import get_active_kernel

        kernel = get_active_kernel("session_iris")
    except Exception as exc:
        return {"error": f"active kernel unavailable: {exc}"[:200]}

    try:
        resolved = kernel.resolve_context_window_with_source()
        out["window_tokens"] = resolved.tokens
        out["window_source"] = resolved.source
        out["model_provider"] = getattr(kernel, "_model_provider", None)
        out["selected_model"] = getattr(kernel, "_selected_reasoning_model", None)
    except Exception as exc:
        out["window_error"] = str(exc)[:200]

    # Provider load state — populated by the Wave 2 process-wide registry
    # (REQ-3 AC2). Reported here once available; gracefully absent before that.
    try:
        from backend.agent.inference.registry import get_provider_registry

        reg = get_provider_registry()
        providers = []
        for pid, inst in reg.all_providers().items():
            providers.append({
                "id": pid,
                "kind": getattr(inst, "kind", None),
                "model": getattr(inst, "model", None),
                "purpose": getattr(inst, "purpose", "chat"),
                "loaded": getattr(inst, "loaded", None),
                "loading": getattr(inst, "loading", None),
            })
        out["providers"] = providers
    except Exception:
        # Registry not yet refactored (Phase 1 Wave 2) — report the gap rather
        # than fabricating load state.
        out["providers"] = "pending (Phase 1 Wave 2 registry)"

    return out


def _empty_domain_gating(reason: str) -> dict[str, Any]:
    """Shared "nothing to evaluate yet" shape for `domain_gating` (P6.2)."""
    return {
        "mode": "no_data",
        "reason": reason,
        "proposal": None,
        "pooled_accepts": None,
        "domains": {},
    }


def _domain_gating_report(
    tuner: Any,
    held_out: list,
    baseline: dict[str, float],
    live: dict[str, bool],
) -> tuple[dict[str, int], dict[str, Any]]:
    """REQ-3 (P6.2) observability: per-domain breakdown WITHOUT ever proposing
    a persisted change.

    Mirrors `OuterTuner.run_once()`'s per-domain iteration exactly — same
    `_domain_groups` / `_evaluate_guards` / `_deciding_guard` calls, same
    "pooled first, domains can only tighten" (D-4) ordering — but stops short
    of `_propose_one` -> `_apply`. `_apply` is the ONLY method on `OuterTuner`
    that persists (writes `params_path`); every method called here
    (`_propose_one`, `_score_proposal`, `_domain_groups`, `_score_with_liveness`,
    `_evaluate_guards`, `_deciding_guard`) is a pure read over already-fetched
    ledger rows. This function must stay that way — the endpoint is
    documented as strictly side-effect free (module docstring) and testers are
    told they can poll it as often as they like.

    Returns (domains_present, domain_gating):
      - domains_present: every domain seen in the held-out set with its
        session count — lets a tester see WHICH domains were even eligible
        for gating, independent of whether gating ran.
      - domain_gating: mode ("no_proposal" | "pooled_rejected" |
        "pooled_fallback" | "per_domain") + a human `reason` a tester can
        read directly, the (unpersisted) proposal considered, whether pooled
        accepted it, and — only when per-domain evaluation actually ran —
        each domain's three guard values, each guard's `live` flag, and
        whether that domain accepted or vetoed.
    """
    groups = tuner._domain_groups(held_out)
    domains_present = {d: len(rows) for d, rows in groups.items()}

    proposal = tuner._propose_one()  # read-only: picks from _PROPOSALS, no mutation
    if proposal is None:
        return domains_present, {
            "mode": "no_proposal",
            "reason": "OuterTuner has no further parameter proposals from "
                      "the current params — nothing to gate per-domain.",
            "proposal": None,
            "pooled_accepts": None,
            "domains": {},
        }

    p_key, p_value = proposal
    proposed = tuner._score_proposal(p_key, p_value, held_out, baseline)
    pooled_guards = tuner._evaluate_guards(proposed, baseline, live)
    pooled_accepts = all(g.passed for g in pooled_guards)
    domain_gating: dict[str, Any] = {
        "mode": None,
        "reason": None,
        "proposal": {"key": p_key, "value": p_value},
        "pooled_accepts": pooled_accepts,
        "domains": {},
    }

    if not pooled_accepts:
        # D-4: per-domain gating only runs when pooled accepts — a domain
        # veto can only ADD a rejection, never rescue a pooled failure. This
        # is the "pooled fallback" a tester must not mistake for real
        # per-domain evaluation never having run.
        domain_gating["mode"] = "pooled_rejected"
        domain_gating["reason"] = (
            "pooled compound gate rejected this proposal; per-domain "
            "evaluation does not run (D-4 ordering: domains can only "
            "tighten a pooled accept, never rescue a pooled reject)."
        )
        return domains_present, domain_gating

    eligible = {d: rows for d, rows in groups.items() if len(rows) >= 2}
    if not eligible:
        domain_gating["mode"] = "pooled_fallback"
        domain_gating["reason"] = (
            "pooled accepted, but no domain has >=2 held-out sessions "
            f"(REQ-3 AC3) — domains_present={domains_present}"
        )
        return domains_present, domain_gating

    domain_gating["mode"] = "per_domain"
    domain_gating["reason"] = (
        f"pooled accepted and {len(eligible)} domain(s) had >=2 held-out "
        "sessions — gate evaluated independently per domain."
    )
    d_domains: dict[str, Any] = {}
    for d, rows in eligible.items():
        d_baseline, d_live = tuner._score_with_liveness(rows)
        d_proposed = tuner._score_proposal(p_key, p_value, rows, d_baseline)
        d_guards = tuner._evaluate_guards(d_proposed, d_baseline, d_live)
        d_domains[d] = {
            "gated": True,
            "passed": all(g.passed for g in d_guards),
            "sessions": len(rows),
            "guards": {
                g.name: {
                    "baseline": g.baseline,
                    "proposed": g.proposed,
                    "live": g.live,
                    "passed": g.passed,
                }
                for g in d_guards
            },
            "deciding_guard": tuner._deciding_guard(d_guards),
        }
    domain_gating["domains"] = d_domains
    return domains_present, domain_gating


def _outer_loop() -> dict[str, Any]:
    """Outer-loop (AIDE^2) compound gate — shows WHICH guards are actually live.

    REQ-6: reports the LIVE count from ``GuardResult.live`` (Phase 6
    ``OuterTuner._score_with_liveness`` / ``_evaluate_guards``), not a
    diagnosis that infers deadness from a suspicious-looking constant. Before
    Phase 6 landed, ``verified_fraction`` traced to a literal (`1.0` on both
    ternary branches) and ``tokens_per_verified`` traced to an unpopulated
    argument (`tokens_total` defaulted to `0.0`) — both reported `live=True`
    while contributing no real signal. A guard is now DEAD (``live=False``)
    exactly when its input could not be computed for this batch, never
    inferred after the fact from what value it happened to produce.

    REQ-3 (P6.2): also reports `domains_present` and `domain_gating` — the
    per-domain breakdown a tester needs to tell a real per-domain veto apart
    from a pooled fallback. See `_domain_gating_report` for how this stays
    read-only: it never calls `OuterTuner._apply`, so polling this endpoint
    cannot write a learned parameter to `params_path`.
    """
    try:
        from backend.agent.outer_loop import OuterTuner
    except Exception as exc:
        return {"error": f"outer_loop unavailable: {exc}"[:200]}

    try:
        tuner = OuterTuner()
        exits = tuner.recorder.get_session_exits(limit=200)
        held_out = tuner._heldout_batch(exits)
        if not held_out:
            return {
                "session_exit_rows": len(exits),
                "held_out_count": 0,
                "held_out_score": {},
                "params": dict(tuner.params),
                # AC1: no proposals yet -> report metrics computed on the
                # current baseline, not as an absent/unknown section (REQ-6
                # edge case: "No proposals yet -> report the metrics as
                # computed on the current baseline, not as absent").
                "live_guards": 0,
                "dead_guards": ["natural_exit_rate", "verified_fraction", "tokens_per_verified"],
                "note": "Drive at least one session to completion so a "
                        "session-exit row is written, then re-read.",
                "domains_present": {},
                "domain_gating": _empty_domain_gating(
                    "no held-out sessions yet"
                ),
            }

        score, live = tuner._score_with_liveness(held_out)
        # REQ-6 AC5: a guard is dead when its INPUT is unavailable (live=False),
        # never inferred from the value it computed to.
        dead_guards = [name for name, is_live in live.items() if not is_live]
        domains_present, domain_gating = _domain_gating_report(
            tuner, held_out, score, live
        )
        return {
            "session_exit_rows": len(exits),
            "held_out_count": len(held_out),
            # AC2: each metric's computed VALUE, not just pass/fail.
            "held_out_score": score,
            "live_by_metric": live,
            "params": dict(tuner.params),
            # CT-D6 / AC1: live_guards must be 3 with no dead guards once all
            # three inputs are computable from real ledger data.
            "live_guards": sum(1 for is_live in live.values() if is_live),
            "dead_guards": dead_guards,
            "note": None,
            # REQ-3 / P6.2: which domains were present + how many sessions
            # each contributed, and whether gating actually ran per-domain
            # or fell back to pooled (and why).
            "domains_present": domains_present,
            "domain_gating": domain_gating,
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}


def _loader_state() -> dict[str, Any]:
    """Local model loader state + active config (Phase 3, REQ-7 AC4).

    Read-only introspection of the LocalModelManager: current load status, the
    active derived/degraded/cached config, the resolved device policy, and the
    ConfigCache corrections (the closed-loop learning state). Never raises.
    """
    out: dict[str, Any] = {}
    try:
        from backend.agent.local_model_manager import (
            get_local_model_manager,
            resolve_device_policy,
        )
        mgr = get_local_model_manager()
    except Exception as exc:
        return {"error": f"local model manager unavailable: {exc}"[:200]}

    try:
        out["status"] = mgr.get_status()
    except Exception as exc:
        out["status_error"] = str(exc)[:200]

    try:
        out["active_config"] = dict(getattr(mgr, "_current_params", {}))
        out["current_purpose"] = getattr(mgr, "_current_purpose", None)
    except Exception as exc:
        out["active_config_error"] = str(exc)[:200]

    try:
        purpose = getattr(mgr, "_current_purpose", "chat")
        policy = resolve_device_policy(purpose)
        out["device_policy"] = {
            "device": policy.device,
            "ladder": list(policy.ladder),
            "counts_against_vram": policy.counts_against_vram,
            "throughput_target": policy.throughput_target,
        }
    except Exception as exc:
        out["device_policy_error"] = str(exc)[:200]

    try:
        cache = getattr(mgr, "_config_cache", None)
        if cache is not None:
            out["config_cache"] = {
                k: {
                    "config": v.get("config"),
                    "measured_tps": v.get("measured_tps"),
                    "hw_fingerprint": v.get("hw_fingerprint"),
                    "updated_at": v.get("updated_at"),
                }
                for k, v in cache._data.items()
            }
        else:
            out["config_cache"] = "unavailable"
    except Exception as exc:
        out["config_cache_error"] = str(exc)[:200]

    return out


def _encoder_state() -> dict[str, Any]:
    """Encoder-service state + re-index progress (Phase 4, REQ-9 AC3).

    Read-only introspection of the embedding backend (backed by
    ``embedding.EmbeddingService``), the list of available backends,
    re-index progress, and the Encoder-350M load state. Never raises —
    any unavailable subsystem reports its own error entry.
    """
    out: dict[str, Any] = {}

    # Core embedding service state (always available via hash fallback).
    try:
        from backend.memory.embedding import get_embedding_service

        svc = get_embedding_service()
        out["embedding_backend"] = svc.backend
        out["embedding_available_backends"] = svc.available_backends()
    except Exception as exc:
        out["error"] = f"embedding_service unavailable: {exc}"[:200]
        return out  # nothing else depends on this surviving

    # Re-index progress — module being built by another agent; may not exist.
    try:
        from backend.memory.reindex import get_reindex_manager  # type: ignore[import-untyped]  # noqa: F811

        mgr = get_reindex_manager()
        out["reindex"] = mgr.progress()
    except ImportError:
        out["reindex"] = {"state": "unknown", "reason": "module not yet present"}
    except Exception as exc:
        out["reindex"] = {"state": "error", "detail": str(exc)[:200]}

    # Encoder-350M load state — verifier module may not exist yet.
    try:
        from backend.agent.verifier import encoder_350m_loaded  # type: ignore[import-untyped]  # noqa: F811

        out["encoder_350m_loaded"] = bool(encoder_350m_loaded)
    except ImportError:
        out["encoder_350m_loaded"] = False
    except Exception as exc:
        out["encoder_350m_loaded"] = f"error: {exc}"[:120]

    return out


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
        "context_window": _context_window(),
        "loader_state": _loader_state(),
        "encoder_state": _encoder_state(),
        "outer_loop": _outer_loop(),
    }
