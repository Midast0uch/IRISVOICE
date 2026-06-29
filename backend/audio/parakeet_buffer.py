"""
Parakeet Streaming Buffer — TDT cache-aware chunked inference wrapper.

Wraps NVIDIA NeMo's `speech_to_text_streaming_infer_rnnt.py` logic behind a
clean per-connection state object. The buffer:

  1. Accepts 80 ms PCM float32 chunks at 16 kHz
  2. Maintains a ring buffer of the last `left_context_secs` seconds
  3. Calls a user-supplied `decoder` function on each push
  4. Returns partial hypotheses (cheap) on every push
  5. Returns a final hypothesis (best, post-flush) on close

This module is **decoupled from NeMo** so we can unit-test it without a
GPU. The real NeMo call lives in `parakeet_service.py`.

Design notes:
- 16 kHz mono is the only supported input.  Anything else is a programmer
  error and raises ValueError at __init__ time.
- The ring buffer is bounded by `left_context_secs` so memory is O(seconds),
  not O(unbounded_session).
- `flush()` returns the last good partial as the final hypothesis — this
  matches NeMo's TDT behaviour where the last hypothesis IS the final one
  once the audio stream ends.
- Thread-safe: the buffer is mutated only on the asyncio event loop that
  owns the WebSocket.  No locks needed.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Optional

import numpy as np

logger = logging.getLogger("parakeet_buffer")

SAMPLE_RATE = 16_000  # Hz — the only supported rate


@dataclass
class Hypothesis:
    """A transcription hypothesis, partial or final."""
    text: str
    confidence: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"text": self.text, "confidence": self.confidence, "ts": self.timestamp}


# Type alias for the decoder callback.  Implementations should be cheap
# enough to run on every push (sub-millisecond on GPU) and return the
# current best hypothesis or None if no speech detected yet.
DecoderFn = Callable[[np.ndarray, bool], Optional[Hypothesis]]


class ParakeetStreamingBuffer:
    """
    Cache-aware streaming buffer for TDT (Token-and-Duration Transducer)
    inference.  Per-connection state.  Not thread-safe — use one buffer per
    WebSocket connection.
    """

    def __init__(
        self,
        decoder: DecoderFn,
        sample_rate: int = SAMPLE_RATE,
        chunk_secs: float = 0.08,
        left_context_secs: float = 5.0,
        right_context_secs: float = 0.5,
    ) -> None:
        if sample_rate != SAMPLE_RATE:
            raise ValueError(
                f"Sample rate must be {SAMPLE_RATE} Hz, got {sample_rate}. "
                f"Resample upstream."
            )
        if chunk_secs <= 0:
            raise ValueError(f"chunk_secs must be > 0, got {chunk_secs}")
        if left_context_secs < 0 or right_context_secs < 0:
            raise ValueError("context seconds must be non-negative")

        self._decoder = decoder
        self._sample_rate = sample_rate
        self._chunk_secs = chunk_secs
        self._left_context_secs = left_context_secs
        self._right_context_secs = right_context_secs

        # Ring buffer of float32 samples, bounded by left_context_secs
        self._ring: Deque[float] = deque(maxlen=int(left_context_secs * sample_rate))
        self._last_hypothesis: Optional[Hypothesis] = None
        self._total_samples = 0

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def push(self, samples: np.ndarray) -> Optional[Hypothesis]:
        """
        Append a chunk of float32 samples in [-1, 1].  Returns the updated
        partial hypothesis, or None if no speech detected yet.

        The chunk may be any length — the buffer does not enforce the
        80 ms cadence (it lets the caller decide when to decode).
        """
        if samples.ndim != 1:
            raise ValueError(f"Expected 1-D array, got shape {samples.shape}")
        if samples.size == 0:
            return None
        if not np.isfinite(samples).all():
            # Reject NaN/inf — the upstream mic should never produce these,
            # but if it does, dropping the chunk is safer than corrupting
            # the hypothesis.
            logger.warning("Non-finite samples in push(), dropping chunk")
            return None

        self._ring.extend(samples.tolist())
        self._total_samples += samples.size

        # Convert ring buffer to a contiguous ndarray (cheap: deque is float)
        context = np.fromiter(self._ring, dtype=np.float32, count=len(self._ring))
        if context.size == 0:
            return None

        hyp = self._decoder(context, is_final=False)
        if hyp is not None:
            self._last_hypothesis = hyp
        return hyp

    def flush(self) -> Optional[Hypothesis]:
        """
        Finalize.  Returns the last good partial hypothesis as the final
        answer, or None if no audio was ever pushed.
        """
        if self._total_samples == 0:
            return None
        # Force a final decode pass with is_final=True so the decoder can
        # emit end-of-sequence tokens.
        context = np.fromiter(self._ring, dtype=np.float32, count=len(self._ring))
        if context.size == 0:
            return self._last_hypothesis
        hyp = self._decoder(context, is_final=True)
        if hyp is not None:
            self._last_hypothesis = hyp
        return self._last_hypothesis

    def reset(self) -> None:
        """Clear all state.  Used when silence is detected."""
        self._ring.clear()
        self._last_hypothesis = None
        self._total_samples = 0

    # ------------------------------------------------------------------ #
    # Properties                                                         #
    # ------------------------------------------------------------------ #

    @property
    def duration_s(self) -> float:
        """Total seconds of audio pushed so far."""
        return self._total_samples / self._sample_rate

    @property
    def context_duration_s(self) -> float:
        """Seconds of audio currently held in the ring buffer."""
        return len(self._ring) / self._sample_rate

    @property
    def last_hypothesis(self) -> Optional[Hypothesis]:
        """The most recent partial hypothesis, or None."""
        return self._last_hypothesis

    def __repr__(self) -> str:
        return (
            f"ParakeetStreamingBuffer("
            f"duration={self.duration_s:.2f}s, "
            f"context={self.context_duration_s:.2f}s, "
            f"last_hyp={'set' if self._last_hypothesis else 'none'})"
        )
