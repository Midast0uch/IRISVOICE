"""Provider-agnostic streaming infrastructure for AgentKernel.

Extracted from agent_kernel.py to keep the god-file focused on orchestration.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional, Tuple

logger = logging.getLogger(__name__)


def chunk_batcher(
    callback: Optional[Callable[[str], None]],
    interval: float = 0.05,
) -> Callable[[str], None]:
    """Return a batched chunk callback that flushes every *interval* seconds.

    Accumulates string tokens and sends them as a single WS message every
    ``interval`` seconds.  The very first token is sent immediately so the
    UI shows something right away.
    """
    _buf: list[str] = []
    _timer: list[Optional[threading.Timer]] = [None]
    _lock = threading.Lock()
    _first = True

    def _flush() -> None:
        nonlocal _first
        with _lock:
            if _buf:
                payload = "".join(_buf)
                _buf.clear()
                if callback:
                    callback(payload)
            _timer[0] = None

    def _batcher(token: str) -> None:
        nonlocal _first
        with _lock:
            _buf.append(token)
            if _first:
                _first = False
                # First token immediate — no wait
                _flush()
            elif _timer[0] is None:
                t = threading.Timer(interval, _flush)
                t.daemon = True
                t.start()
                _timer[0] = t

    return _batcher


def extract_chunk_text(chunk: Any) -> Tuple[str, str]:
    """Extract (content, reasoning) from a streaming chunk.

    Handles multiple provider shapes:
      - OpenAI / LiteLLM: chunk.choices[0].delta.{content,reasoning_content}
      - Plain-string fallback (defensive)
      - Missing .choices (yield empty, don't crash)
    """
    # Fast path: OpenAI / LiteLLM shape
    try:
        _choices = getattr(chunk, "choices", None)
        if _choices is not None and len(_choices) > 0:
            _delta = getattr(_choices[0], "delta", None)
            if _delta is not None:
                _content = getattr(_delta, "content", None) or ""
                _reasoning = getattr(_delta, "reasoning_content", None) or ""
                return (_content, _reasoning)
    except Exception:
        pass

    # Defensive: if chunk itself is a string
    if isinstance(chunk, str):
        return (chunk, "")

    # Unknown shape — log once, return empty
    logger.debug("[streaming] Unrecognised chunk shape: %s", type(chunk))
    return ("", "")


def safe_stream(
    resp: Any,
    silence_timeout: float = 3.0,
    total_timeout: float = 30.0,
    on_first_token: Optional[Callable[[], None]] = None,
):
    """Wrap a streaming response iterator with silence and total timeouts.

    If no new chunk arrives within *silence_timeout* seconds, OR the
    total elapsed time exceeds *total_timeout* seconds, the iterator
    is abandoned.  This prevents the UI from hanging when a provider
    stalls mid-stream or fails to close the SSE stream.

    Args:
        on_first_token: Optional callback invoked exactly once when the
                        first contentful chunk is yielded (for TTFT).
    """
    _buffer: list = []
    _done = threading.Event()
    _ex: list[Optional[Exception]] = [None]
    _first = True

    def _reader():
        try:
            for chunk in resp:
                _buffer.append(chunk)
                _done.set()
        except Exception as exc:
            _ex[0] = exc
            _done.set()

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    _start = time.monotonic()
    _last_content_ts = _start  # wall-time of last CONTENTFUL yield
    _SILENCE_TOTAL = 3.0  # wall-time silence (s) after the last content chunk
    while True:
        elapsed = time.monotonic() - _start
        remaining = total_timeout - elapsed
        if remaining <= 0:
            logger.warning(
                "[streaming] stream total timeout (%.0fs) — abandoning response",
                total_timeout,
            )
            return
        # Use a short wait (0.1s) so we can check wall-time silence
        # even when litellm emits empty/done chunks every second.
        _done.wait(timeout=0.1)
        if _buffer:
            # Drain ALL buffered at once
            _had_content = False
            while _buffer:
                chunk = _buffer.pop(0)
                _content, _reasoning = extract_chunk_text(chunk)
                _has = bool(_content or _reasoning)
                if _has:
                    if _first and on_first_token:
                        on_first_token()
                        _first = False
                    yield chunk
                    _had_content = True
            _done.clear()
            if _had_content:
                _last_content_ts = time.monotonic()
                continue  # fresh content → keep going
            # Empty chunks only — drop through to silence check below
        if not t.is_alive():
            # Stream finished
            while _buffer:
                _buffer.pop(0)
            if _ex[0] is not None:
                logger.warning("[streaming] stream error: %s", _ex[0])
            return
        # Wall-time silence check — independent of empty-chunk spam
        _wall_silence = time.monotonic() - _last_content_ts
        if _wall_silence >= _SILENCE_TOTAL:
            logger.warning(
                "[streaming] stream wall-silence (%.1fs) — abandoning response",
                _wall_silence,
            )
            return


def stream_and_collect(
    resp: Any,
    chunk_callback: Optional[Callable[[str], None]],
    reasoning_callback: Optional[Callable[[str], None]] = None,
    on_first_token: Optional[Callable[[], None]] = None,
) -> tuple[str, str]:
    """Drain a streaming response, collecting the full reply text.

    Uses safe_stream for timeout protection and extract_chunk_text
    for provider-agnostic chunk parsing.  The on_first_token callback
    is invoked exactly once on the first contentful chunk (TTFT).

    Returns (content, reasoning) — the reasoning string is populated when
    the model returns reasoning_content but empty content (common with
    reasoning models like MiniMax-M2.5-TEE on Chutes).
    """
    full_reply = ""
    _reasoning_buf: list[str] = []
    _batched_cb = chunk_batcher(chunk_callback) if chunk_callback else None

    for chunk in safe_stream(resp, on_first_token=on_first_token):
        _content, _reasoning = extract_chunk_text(chunk)

        if _reasoning and reasoning_callback:
            reasoning_callback(_reasoning)
            _reasoning_buf.append(_reasoning)

        if _content and _batched_cb:
            full_reply += _content
            _batched_cb(_content)

    if _reasoning_buf and reasoning_callback:
        reasoning_callback("")  # end-of-reasoning marker
    if _batched_cb:
        _batched_cb("")  # force-flush

    return full_reply, "".join(_reasoning_buf)
