"""The one token gauge (CLM-4, specs/clm-memory).

Plain picture: a ruler that is a little wrong, plus a habit of checking it
against the server's own count after every call. The ruler is the router's
conservative chars/3.5 rule. The habit is one ratio per (provider, model), an
exponential moving average of ``usage.prompt_tokens / estimate``.

Pure module: no I/O, no tokenizer, no persistence, nothing heavy at import.
State is one small dict guarded by a lock; it holds at most ``MAX_ENTRIES``
(provider, model) pairs and never carries a ratio from one model to another.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# The router's per-image constant stays until measured (CLM-4 edge case).
IMAGE_CHARS = 3500
# Role, name and JSON scaffolding per message.
MESSAGE_OVERHEAD_CHARS = 16
CHARS_PER_TOKEN = 3.5

# EMA weight of the newest observation. 0.3 reaches 90 % of a step change in
# about six calls; a lower weight lags a changing prompt mix, a higher one
# chases the per-call noise of the chars rule.
EMA_ALPHA = 0.3
# A ratio outside this range means a bad pair (a cached-prefix count, a failed
# call), not a property of the model; the observation is clamped, not trusted.
RATIO_MIN = 0.25
RATIO_MAX = 4.0
# One entry per (provider, model); the least recently used pair leaves first.
MAX_ENTRIES = 64


def estimate_tokens(
    messages: Optional[List[Dict[str, Any]]],
    tools: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Cheap, deliberately CONSERVATIVE token estimate (the raw ruler).

    Moved from ``InferenceRouter._estimate_prompt_tokens`` with the same
    arithmetic: text chars + 16 per message + ``str(tool_calls)`` + ``str(tools)``,
    over 3.5. 3.5 and not 4, because under-estimating overruns the window.
    """
    chars = 0
    for message in messages or []:
        content = message.get("content")
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chars += len(part["text"])
                elif isinstance(part, dict) and part.get("type") == "image_url":
                    chars += IMAGE_CHARS
        chars += MESSAGE_OVERHEAD_CHARS
        if message.get("tool_calls"):
            chars += len(str(message["tool_calls"]))
    if tools:
        chars += len(str(tools))
    return int(chars / CHARS_PER_TOKEN) + 1


@dataclass(frozen=True)
class GaugeReading:
    tokens: int          # calibrated count (equals ``raw`` when uncalibrated)
    raw: int             # the uncalibrated ruler
    calibrated: bool     # True once a real usage was observed for this pair
    ratio: float         # applied ratio, 1.0 when uncalibrated


class ContextGauge:
    """Per-(provider, model) calibration over :func:`estimate_tokens`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ratios: "OrderedDict[Tuple[str, str], float]" = OrderedDict()

    @staticmethod
    def _key(provider: Any, model: Any) -> Tuple[str, str]:
        return (str(provider or ""), str(model or ""))

    def observe(self, provider: Any, model: Any, estimated: int, real: int) -> bool:
        """Learn from one real call. Returns False for an unusable pair.

        The first observation seeds the ratio directly: starting from 1.0
        would carry the known bias of the raw ruler for several calls.
        """
        try:
            est, act = int(estimated), int(real)
        except (TypeError, ValueError):
            return False
        if est <= 0 or act <= 0:
            return False
        sample = min(RATIO_MAX, max(RATIO_MIN, act / est))
        key = self._key(provider, model)
        with self._lock:
            prev = self._ratios.pop(key, None)
            self._ratios[key] = (
                sample if prev is None else prev + EMA_ALPHA * (sample - prev)
            )
            while len(self._ratios) > MAX_ENTRIES:
                self._ratios.popitem(last=False)
        return True

    def ratio(self, provider: Any, model: Any) -> Optional[float]:
        """The learned ratio, or None when nothing was observed."""
        with self._lock:
            return self._ratios.get(self._key(provider, model))

    def estimate(
        self,
        provider: Any,
        model: Any,
        messages: Optional[List[Dict[str, Any]]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> GaugeReading:
        """Calibrated count for a prompt, marked uncalibrated when never observed."""
        raw = estimate_tokens(messages, tools)
        ratio = self.ratio(provider, model)
        if ratio is None:
            return GaugeReading(tokens=raw, raw=raw, calibrated=False, ratio=1.0)
        return GaugeReading(
            tokens=max(1, round(raw * ratio)), raw=raw, calibrated=True, ratio=ratio
        )


# The process-wide gauge the call sites share (the one count function).
GAUGE = ContextGauge()


# -- blind drops (CLM-2 AC6, CLM-8 AC3) ----------------------------------------
# The router cap drops the oldest messages without a record. Until the view
# owns shrink, each drop is COUNTED here so the alarm is proven live first:
# calls that dropped, messages dropped, estimated tokens dropped. Three ints
# under one lock; nothing is prevented by counting.
_blind_lock = threading.Lock()
_blind = {"calls": 0, "messages": 0, "tokens": 0}


def record_blind_drop(messages: int, tokens: int) -> Dict[str, int]:
    """One router-cap call that dropped ``messages`` (>0). Returns the totals."""
    with _blind_lock:
        _blind["calls"] += 1
        _blind["messages"] += max(0, int(messages))
        _blind["tokens"] += max(0, int(tokens))
        return dict(_blind)


def blind_drop_snapshot() -> Dict[str, int]:
    with _blind_lock:
        return dict(_blind)
