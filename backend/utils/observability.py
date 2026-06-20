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
    pacman_store: int = 0
    pacman_recall: int = 0
    xi: float = 0.0
    traj_rows: int = 0
    map_events: int = 0
    ttft_ms: Optional[float] = None
    e2e_ms: Optional[float] = None
    _start_ts: float = field(default_factory=time.perf_counter)
    _ttft_marked: bool = field(default=False, repr=False)

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
        return (
            f"[LAYERS] turn={self.turn_id} "
            f"engine={self.engine} path={self.path} "
            f"der_steps={self.der_steps} pacman_store={self.pacman_store} "
            f"pacman_recall={self.pacman_recall} xi={self.xi:.2f} "
            f"traj_rows={self.traj_rows} map_events={self.map_events} "
            f"ttft_ms={self.ttft_ms} e2e_ms={self.e2e_ms}"
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
