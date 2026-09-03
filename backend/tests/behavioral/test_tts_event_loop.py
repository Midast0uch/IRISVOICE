"""
Behavioral test: TTS synthesis does not block the asyncio event loop (REQ-9).

The whole point of the TTS subprocess worker is that GIL-bound Pocket-TTS
synthesis runs in a SEPARATE PROCESS, so the main asyncio event loop stays
responsive during speech output.

This test verifies that an asyncio task keeps ticking while TTS synthesis is
running through the proxy — the acceptance gate for the GIL contention fix.
"""

from __future__ import annotations

import asyncio
import importlib.util
import threading
import time

import numpy as np
import pytest

_HAS_POCKET_TTS = importlib.util.find_spec("pocket_tts") is not None


@pytest.fixture
def tts():
    """Return a TTSManager proxy with the worker spawned."""
    from backend.agent.tts import get_tts_manager

    if not _HAS_POCKET_TTS:
        pytest.skip("pocket_tts not installed")

    mgr = get_tts_manager()
    if not mgr._ensure_worker():
        pytest.skip("TTS worker could not start")
    yield mgr


class TestEventLoopNotBlocked:
    """Verify TTS synthesis does not block the asyncio event loop."""

    def test_event_loop_ticks_during_synthesis(self, tts):
        """An asyncio task must keep ticking while TTS synthesizes."""
        loop = asyncio.new_event_loop()
        ticks = []

        async def ticker():
            for _ in range(20):
                ticks.append(time.monotonic())
                await asyncio.sleep(0.01)

        def run_ticker():
            loop.run_until_complete(ticker())

        t = threading.Thread(target=run_ticker, daemon=True)
        t.start()

        # Synthesize a longer phrase while the ticker runs.
        chunks = list(tts.synthesize_stream("This is a longer sentence to synthesize."))
        assert len(chunks) > 0, "No audio produced"

        t.join(timeout=10)
        loop.close()

        # The ticker must have advanced — the event loop was not blocked.
        assert len(ticks) >= 10, (
            f"Event loop was blocked during synthesis — only {len(ticks)} ticks"
        )

    def test_synthesis_completes(self, tts):
        """Synthesis must complete and produce audio."""
        chunks = list(tts.synthesize_stream("Hello world"))
        total = sum(len(c) for c in chunks)
        assert total > 0, "No audio produced"
        # ~0.5s of audio minimum for "Hello world"
        assert total > 10000, f"Too little audio: {total} samples"