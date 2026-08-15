"""
IRIS Observability — loud-in-dev errors, per-turn trace IDs, and the [LAYERS] line.

Usage:
    from backend.utils.observability import get_turn_id, TurnMetrics, loud_error, safe_call

    turn_id = get_turn_id()
    metrics = TurnMetrics(turn_id=turn_id)
    ...
    logger.info(metrics.to_log_line())  # emits [LAYERS] summary
"""

import os
import logging
import uuid
import time
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field

logger = logging.getLogger("iris.observability")

# ---------------------------------------------------------------------------
# Environment flag
# ---------------------------------------------------------------------------

_IRIS_DEV = os.environ.get("IRIS_DEV", "").lower() in ("1", "true", "yes", "on")


def is_dev() -> bool:
    """Return True when IRIS_DEV is set to a truthy value."""
    return _IRIS_DEV


# ---------------------------------------------------------------------------
# Loud-in-dev error helper
# ---------------------------------------------------------------------------

def loud_error(
    exc: Exception,
    ctx: str,
    *,
    extra: Optional[Dict[str, Any]] = None,
    level_dev: str = "warning",
) -> None:
    """
    Log an exception. In dev mode: loud (warning + traceback).
    In prod: quiet (debug only, no traceback).

    Use this to replace silent ``except Exception: pass`` on the critical path.
    The fallback *behaviour* does not change — only its visibility.
    """
    _extra = extra or {}
    if _IRIS_DEV:
        getattr(logger, level_dev)(
            f"[DEV] {ctx} failed: {exc}",
            exc_info=True,
            extra=_extra,
        )
    else:
        logger.debug(f"{ctx} failed: {exc}", extra=_extra)


def safe_call(
    func: Callable,
    *args,
    fallback=None,
    ctx: str = "",
    **kwargs,
):
    """
    Call *func* safely. In dev mode, log full traceback on failure.

    Replaces patterns like::

        try:
            something()
        except Exception:
            pass

    With::

        safe_call(something, ctx="something")
    """
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        loud_error(exc, ctx or func.__name__)
        return fallback


# ---------------------------------------------------------------------------
# Per-turn metrics collector
# ---------------------------------------------------------------------------

@dataclass
class TurnMetrics:
    """
    Collect per-turn metrics for the ``[LAYERS]`` summary line.

    Thread one instance through a single turn and call ``to_log_line()``
    before the response is returned.
    """

    turn_id: str = ""
    engine: str = "unknown"          # native | fallback | unknown
    path: str = "unknown"            # direct | der | unknown
    der_steps: int = 0
    der_calls: int = 0  # REQ-7 AC3: DER LLM calls this turn (batched groups count once)
    # REQ-6 (T18): governance-source counts per steering decision —
    # gov_past  = decisions governed by past-memory (compressed node records),
    # gov_live  = decisions governed by live-state (current Σ),
    # gov_both  = decisions where BOTH governed (equal signals — REQ-6 edge).
    # gov_ratio = the per-turn alternation ratio (past-governed share of all
    #             recorded steering decisions) exposed for the outer loop (AC3).
    gov_past: int = 0
    gov_live: int = 0
    gov_both: int = 0
    gov_ratio: float = 0.0
    # REQ-17 AC1 (T34): the remaining per-turn telemetry the tuner needs —
    # budget source (override|authoritative|table|default — the REAL source
    # that won in resolve_context_window_with_source, never a silent 8192),
    # chain-drop count (memory chain rows dropped this turn), 429 count
    # (provider rate-limit observations this turn), narration decision count
    # (silence|brief|full decisions this turn). Each defaults to absent/0 and
    # is populated off the hot path at the [LAYERS] emit.
    budget_source: str = "default"
    chain_drop_count: int = 0
    count_429: int = 0
    narration_decisions: int = 0
    pacman_store: int = 0
    pacman_recall: int = 0
    xi: float = 0.0
    traj_rows: int = 0
    map_events: int = 0
    step_prompt_tokens: int = 0  # REQ-3 AC5: total prompt tokens across DER steps
    ttft_ms: Optional[float] = None
    e2e_ms: Optional[float] = None
    # REQ-5 AC1 (T8): semantic-gate telemetry rides the [LAYERS] line —
    # gate_domain (winning IntentDomain), gate_lanes (comma-joined capability
    # lanes), gate_latency_ms (Tier0+Tier2+compose), gate_widen_scope
    # (winning ontology widen scope from record_widening_telemetry). The
    # centroid fields were removed with Tier 1. Populated off the hot path at
    # the emit via record_gate(); the gate itself never touches metrics.
    gate_domain: str = ""
    gate_lanes: str = ""
    gate_latency_ms: Optional[float] = None
    gate_widen_scope: str = ""
    _start_ts: float = field(default_factory=time.perf_counter)
    _ttft_marked: bool = field(default=False, repr=False)

    def record_gate(
        self,
        *,
        domain: str = "",
        lanes: str = "",
        latency_ms: Optional[float] = None,
        widen_scope: str = "",
        warn_threshold_ms: float = 35.0,
    ) -> None:
        """Populate gate telemetry fields (REQ-5 AC1) and emit the > threshold
        performance warning (AC3) dev-loud via loud_error. Fire-and-forget:
        never raises, adds zero latency to the response."""
        self.gate_domain = domain
        self.gate_lanes = lanes
        self.gate_latency_ms = latency_ms
        self.gate_widen_scope = widen_scope
        if latency_ms is not None and latency_ms > warn_threshold_ms:
            loud_error(
                RuntimeError(
                    f"gate classification {latency_ms:.1f}ms > {warn_threshold_ms:.0f}ms budget"
                ),
                "gate.classification",
                level_dev="warning",
            )

    def mark_first_token(self) -> None:
        """Call when the first contentful chunk arrives."""
        if not self._ttft_marked:
            self.ttft_ms = round((time.perf_counter() - self._start_ts) * 1000, 1)
            self._ttft_marked = True

    def finalize(self) -> None:
        """Compute e2e_ms (and ttft_ms if streaming never happened)."""
        if self.e2e_ms is None:
            self.e2e_ms = round((time.perf_counter() - self._start_ts) * 1000, 1)
        if self.ttft_ms is None:
            self.ttft_ms = self.e2e_ms

    def to_log_line(self) -> str:
        """Emit the single-line summary the benchmark asserts against."""
        self.finalize()
        # REQ-6 AC3 (T18): the governance alternation ratio — the share of
        # steering decisions governed by PAST-memory (past or both) among all
        # recorded decisions this turn. 0.0 when nothing was recorded.
        _gov_total = self.gov_past + self.gov_live + self.gov_both
        _gov_ratio = (
            round((self.gov_past + self.gov_both) / _gov_total, 3)
            if _gov_total > 0
            else 0.0
        )
        self.gov_ratio = _gov_ratio
        # REQ-5 AC1 (T8): gate fields appended AFTER the existing fields —
        # additive only; test_der_t18_governance_contract.py and
        # test_der_t11_step_count_contract.py assert the original fields
        # survive (design.md Ripple, observability.py:226).
        _gate_lat = (
            f"{self.gate_latency_ms:.1f}" if self.gate_latency_ms is not None else "-"
        )
        return (
            f"[LAYERS] turn={self.turn_id} "
            f"engine={self.engine} path={self.path} "
            f"der_steps={self.der_steps} der_calls={self.der_calls} "
            f"budget_source={self.budget_source} "
            f"chain_drops={self.chain_drop_count} "
            f"429s={self.count_429} "
            f"narration={self.narration_decisions} "
            f"pacman_store={self.pacman_store} "
            f"pacman_recall={self.pacman_recall} xi={self.xi:.2f} "
            f"traj_rows={self.traj_rows} map_events={self.map_events} "
            f"step_tokens={self.step_prompt_tokens} "
            f"gov_past={self.gov_past} gov_live={self.gov_live} "
            f"gov_both={self.gov_both} gov_ratio={_gov_ratio} "
            f"ttft_ms={self.ttft_ms} e2e_ms={self.e2e_ms} "
            f"gate_domain={self.gate_domain} gate_lanes={self.gate_lanes} "
            f"gate_latency_ms={_gate_lat} gate_widen_scope={self.gate_widen_scope}"
        )


# ---------------------------------------------------------------------------
# Turn ID generator
# ---------------------------------------------------------------------------

def get_turn_id() -> str:
    """Generate a short unique turn identifier (12 hex chars)."""
    return str(uuid.uuid4())[:12]


def broadcast_inference_event(
    session_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    elapsed_s: float,
    broadcast_loop=None,
) -> None:
    """Fire-and-forget inference_event broadcast to this session's WS clients.

    Called after every LLM completion so InferenceConsolePanel can display
    live tokens/sec, token counts, and latency.  Never raises.
    """
    try:
        import asyncio
        from backend.ws_manager import get_websocket_manager

        ws = get_websocket_manager()
        if not ws:
            return
        tps = round(completion_tokens / max(0.001, elapsed_s), 2)
        payload = {
            "type": "inference_event",
            "payload": {
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "tps": tps,
                "time_ms": round(elapsed_s * 1000),
                "timestamp": time.time(),
            },
        }
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(ws.broadcast_to_session(session_id, payload))
        except RuntimeError:
            captured = broadcast_loop
            if captured is not None and captured.is_running():
                asyncio.run_coroutine_threadsafe(
                    ws.broadcast_to_session(session_id, payload),
                    captured,
                )

        # [10.10] Feed TPS into LocalModelManager's rolling window for gradient warnings
        try:
            from backend.agent.local_model_manager import get_local_model_manager

            mgr = get_local_model_manager()
            if mgr.is_loaded():
                hw = mgr.get_hardware_info()
                gpu_active = hw.get("cuda_available", False)
                mgr.record_tps(tps, gpu_active=gpu_active)
        except Exception:
            pass  # never block the response

        # [Monitor] Record usage in the analytics store (data/monitor.db)
        # Completely isolated from agent memory — separate SQLite file.
        try:
            from backend.monitor.analytics import get_analytics_manager

            analytics = get_analytics_manager()
            analytics.record_usage(
                session_id=session_id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=round(elapsed_s * 1000),
                mode="conversation",
            )
        except Exception:
            pass  # never block the response
    except Exception:
        pass  # never block the response
