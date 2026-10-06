"""Runtime reader of the Oracle calibration map (Stage A, 2026-10-05).

WHAT IT IS
    The Oracle's raw confidence is not a probability of being right. Measured on
    the live ledger, ECE on raw confidences was 0.26-0.40 for most consumers and
    the error-detection AUROC ranged from 0.0 to 0.79. `scripts/fit_oracle_calibration.py`
    fits, OFFLINE, one monotone map per (backend id, consumer) from the row's
    confidence in the CHOSEN answer to P(agrees with the incumbent), plus the
    smallest threshold on the calibrated scale that holds precision. It writes
    `benchmarks/oracle_calibration.json`. This module reads that file.

WHO READS IT (Stage B, 2026-10-05)
    `decision_engine.decides()` / `oracle_acts()` - the ONE enforcement
    chokepoint - read `threshold()` / `calibrated()` and nothing else decides. A
    consumer acts only when the owner switched it on, it earned the hardened bar
    (consumer_bar.derive_status) AND a threshold was fitted for the active engine.

THE INPUT RULE
    ``raw_conf`` is the confidence in the CHOSEN answer (a Noul row's
    max(p, 1-p), never its raw P(true)). A map fitted on one scale applied to
    another is meaningless, so a caller passes the same number a ledger row
    carries in ``confidence``.

Never raises: a missing file, an unreadable file, or an unknown consumer is None
and the caller keeps the legacy (fail-closed) path.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("oracle_calibration")

CALIBRATION_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "benchmarks" / "oracle_calibration.json"
)

# path -> (mtime_ns, parsed). Re-read when the file changes (the fit script
# rewrites it while a backend may be running); one os.stat per call, no parse.
_CACHE: Dict[str, Tuple[int, Dict[str, Any]]] = {}


def _load(path: Optional[Path] = None) -> Dict[str, Any]:
    target = Path(path) if path else CALIBRATION_PATH
    key = str(target)
    try:
        mtime = os.stat(key).st_mtime_ns
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
        _CACHE[key] = (mtime, data)
        return data
    except Exception:  # noqa: BLE001 - absent/unreadable = no calibration
        _CACHE.pop(key, None)
        return {}


def _entry(backend_id: str, consumer: str, path: Optional[Path]) -> Optional[Dict[str, Any]]:
    e = (_load(path).get(str(backend_id)) or {}).get(str(consumer))
    return e if isinstance(e, dict) else None


def apply_knots(knots: Sequence[Sequence[float]], x: float) -> float:
    """Piecewise-linear map through monotone ``(x, y)`` knots, clipped to [0, 1].

    Constant before the first knot and after the last. One knot = a constant.
    """
    xs = [float(k[0]) for k in knots]
    ys = [float(k[1]) for k in knots]
    if x <= xs[0]:
        y = ys[0]
    elif x >= xs[-1]:
        y = ys[-1]
    else:
        i = 1
        while xs[i] < x:
            i += 1
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        y = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return min(1.0, max(0.0, y))


def calibrated(
    backend_id: str, consumer: str, raw_conf: float, path: Optional[Path] = None,
) -> Optional[float]:
    """P(the chosen answer agrees with the incumbent), or None when unknown.

    Rounded to 4 places: the fit picks its threshold on 4-place values, so a
    ``>=`` against ``threshold()`` means the same thing here as it did there.
    """
    try:
        e = _entry(backend_id, consumer, path)
        knots: List[Any] = (e or {}).get("knots") or []
        if not knots:
            return None
        return round(apply_knots(knots, float(raw_conf)), 4)
    except Exception:  # noqa: BLE001 - never raises
        return None


def threshold(
    backend_id: str, consumer: str, path: Optional[Path] = None,
) -> Optional[float]:
    """The calibrated-scale threshold for (backend, consumer), or None."""
    try:
        t = (_entry(backend_id, consumer, path) or {}).get("threshold")
        return None if t is None else float(t)
    except Exception:  # noqa: BLE001 - never raises
        return None


def binary_consumers() -> frozenset:
    """Consumers whose engine answer is a yes/no Noul, from the engine's own specs.

    A Noul consumer registers a fixed ("yes", "no") label set; a Choice consumer
    registers none (the caller's menu supplies the labels). Reading the specs
    means a new yes/no consumer is picked up without editing a list here. The
    registrars are idempotent and load no model.
    """
    try:
        from backend.agent.decision_backend_onnx import CONSUMER_TASKS

        for mod, fn in (("monitor_shadow", "register_monitor_consumers"),
                        ("surface_shadow", "register_surface_consumers"),
                        ("explorer", "register_web_intent_consumer")):
            try:
                m = __import__(f"backend.agent.{mod}", fromlist=[fn])
                getattr(m, fn)()
            except Exception as e:  # noqa: BLE001 - a registrar fault narrows the set
                logger.warning("oracle_calibration: %s registration failed (%r)", mod, e)
        return frozenset(
            cid for cid, spec in CONSUMER_TASKS.items()
            if tuple(spec.labels) == ("yes", "no")
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("oracle_calibration: binary consumers unresolved (%r)", e)
        return frozenset()
