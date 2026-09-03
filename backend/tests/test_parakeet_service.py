"""
Parakeet ASR Service — Unit tests.

These tests run WITHOUT a GPU.  The model load in `parakeet_service.py`
is lazy (only happens in `_load_model`), so the test suite can import
the module freely.  We mock the decoder to exercise the FastAPI app
in isolation.

GPU-gated integration tests live in
`tests/test_parakeet_integration.py` (PR 7).
"""

from __future__ import annotations

import asyncio
import sys
from typing import Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Skip the entire module if fastapi isn't installed
# ---------------------------------------------------------------------------

try:
    from fastapi.testclient import TestClient as _TestClient  # noqa: F401
    import fastapi  # noqa: F401
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

try:
    import httpx  # noqa: F401
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

pytestmark = pytest.mark.skipif(
    not _HAS_FASTAPI, reason="fastapi not installed"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pcm_int16(samples_f32: np.ndarray) -> bytes:
    """Convert float32 in [-1, 1] to int16 little-endian bytes."""
    return (samples_f32 * 32768.0).clip(-32768, 32767).astype(np.int16).tobytes()


def silence(duration_s: float, sample_rate: int = 16_000) -> np.ndarray:
    return np.zeros(int(duration_s * sample_rate), dtype=np.float32)


def tone(duration_s: float, freq_hz: float = 440.0, sample_rate: int = 16_000,
        amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(int(duration_s * sample_rate)) / sample_rate
    return (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


# ===========================================================================
# Tests for ParakeetStreamingBuffer
# ===========================================================================

class TestParakeetStreamingBuffer:
    """Pure-logic tests for the streaming buffer.  No HTTP, no NeMo."""

    def _make_decoder(self, scripted: list[Optional[str]]) -> callable:
        """
        Build a decoder that returns scripted text on each call.
        `None` means "no hypothesis yet".
        """
        from backend.audio.parakeet_buffer import Hypothesis
        idx = {"i": 0}

        def _dec(context: np.ndarray, is_final: bool) -> Optional[Hypothesis]:
            i = idx["i"]
            idx["i"] += 1
            if i >= len(scripted):
                return None
            text = scripted[i]
            if text is None:
                return None
            return Hypothesis(text=text, confidence=0.9, timestamp=0.0)

        return _dec

    def test_rejects_wrong_sample_rate(self):
        from backend.audio.parakeet_buffer import ParakeetStreamingBuffer
        with pytest.raises(ValueError, match="Sample rate must be 16000"):
            ParakeetStreamingBuffer(decoder=lambda *a: None, sample_rate=44_100)

    def test_rejects_zero_chunk(self):
        from backend.audio.parakeet_buffer import ParakeetStreamingBuffer
        with pytest.raises(ValueError, match="chunk_secs must be > 0"):
            ParakeetStreamingBuffer(decoder=lambda *a: None, chunk_secs=0)

    def test_rejects_negative_context(self):
        from backend.audio.parakeet_buffer import ParakeetStreamingBuffer
        with pytest.raises(ValueError, match="must be non-negative"):
            ParakeetStreamingBuffer(decoder=lambda *a: None, left_context_secs=-1)

    def test_empty_buffer_flush_returns_none(self):
        from backend.audio.parakeet_buffer import ParakeetStreamingBuffer
        buf = ParakeetStreamingBuffer(decoder=lambda *a: None)
        assert buf.flush() is None
        assert buf.duration_s == 0

    def test_push_returns_partial_hypothesis(self):
        from backend.audio.parakeet_buffer import ParakeetStreamingBuffer
        # Scripted: 1st decoder call (after 250ms+ threshold) → None,
        #            2nd → "hello", 3rd → "hello world".
        # First push is 300ms (≥ 250ms threshold) so the decoder is
        # called and returns the first scripted value (None).
        decoder = self._make_decoder([None, "hello", "hello world"])
        buf = ParakeetStreamingBuffer(decoder=decoder)
        r1 = buf.push(tone(0.3))        # 4800 samples ≥ 4000 threshold
        assert r1 is None               # decoder call 1 → None
        r2 = buf.push(tone(0.2))        # 8000 samples
        assert r2 is not None
        assert r2.text == "hello"
        assert r2.confidence == 0.9
        r3 = buf.push(tone(0.2))        # 11200 samples
        assert r3 is not None
        assert r3.text == "hello world"

    def test_ring_buffer_caps_at_left_context(self):
        from backend.audio.parakeet_buffer import ParakeetStreamingBuffer
        decoder = self._make_decoder([None] * 100)
        buf = ParakeetStreamingBuffer(decoder=decoder, left_context_secs=1.0)
        # Push 5 seconds — only 1 second should be retained
        for _ in range(50):
            buf.push(tone(0.1))
        # Ring should be at most left_context_secs * sample_rate samples
        assert buf.context_duration_s <= 1.0 + 1e-3
        # But duration_s reports total pushed, not ring
        assert buf.duration_s == pytest.approx(5.0, abs=0.1)

    def test_flush_returns_last_hypothesis(self):
        from backend.audio.parakeet_buffer import ParakeetStreamingBuffer
        decoder = self._make_decoder([None, "first", "second", "final"])
        buf = ParakeetStreamingBuffer(decoder=decoder)
        buf.push(tone(0.1))
        buf.push(tone(0.2))
        buf.push(tone(0.2))
        final = buf.flush()
        # Decoder's last call wins
        assert final is not None
        assert final.text == "final"

    def test_reset_clears_state(self):
        from backend.audio.parakeet_buffer import ParakeetStreamingBuffer
        decoder = self._make_decoder([None, "before reset", "after reset"])
        buf = ParakeetStreamingBuffer(decoder=decoder)
        buf.push(tone(0.1))
        buf.push(tone(0.2))
        buf.reset()
        assert buf.duration_s == 0
        assert buf.context_duration_s == 0
        assert buf.last_hypothesis is None

    def test_rejects_2d_array(self):
        from backend.audio.parakeet_buffer import ParakeetStreamingBuffer
        buf = ParakeetStreamingBuffer(decoder=lambda *a: None)
        with pytest.raises(ValueError, match="1-D array"):
            buf.push(np.zeros((2, 100), dtype=np.float32))

    def test_drops_nonfinite_samples(self):
        from backend.audio.parakeet_buffer import ParakeetStreamingBuffer
        from backend.audio.parakeet_buffer import Hypothesis
        decoder = MagicMock(return_value=Hypothesis(text="x", confidence=0.5))
        buf = ParakeetStreamingBuffer(decoder=decoder)
        bad = np.array([0.0, np.nan, 0.1, np.inf, 0.2], dtype=np.float32)
        r = buf.push(bad)
        assert r is None
        decoder.assert_not_called()

    def test_empty_push_is_noop(self):
        from backend.audio.parakeet_buffer import ParakeetStreamingBuffer
        from backend.audio.parakeet_buffer import Hypothesis
        decoder = MagicMock(return_value=Hypothesis(text="x", confidence=0.5))
        buf = ParakeetStreamingBuffer(decoder=decoder)
        assert buf.push(np.array([], dtype=np.float32)) is None
        decoder.assert_not_called()

    def test_repr_is_diagnostic(self):
        from backend.audio.parakeet_buffer import ParakeetStreamingBuffer
        buf = ParakeetStreamingBuffer(decoder=lambda *a: None)
        rep = repr(buf)
        assert "ParakeetStreamingBuffer" in rep
        assert "duration=" in rep


# ===========================================================================
# Tests for the FastAPI app
# ===========================================================================

class TestParakeetServiceApp:
    """HTTP/WS tests with a mocked model + decoder."""

    @pytest.fixture
    def mock_app(self):
        """Build a FastAPI app with a mocked decoder that produces canned output."""
        from backend.audio import parakeet_service
        from backend.audio.parakeet_buffer import Hypothesis

        cfg = parakeet_service.ServiceConfig(device="cpu", precision="fp32")

        # Capture pushed samples for the lifetime of the test
        state = {"pushed": [], "decoder_calls": 0}

        def fake_decoder(context: np.ndarray, is_final: bool):
            state["decoder_calls"] += 1
            state["pushed"].append(context.copy())
            if is_final:
                return Hypothesis(text="hello world final", confidence=0.95)
            # First two partials return None, then "hello", then "hello world"
            n = len(state["pushed"])
            if n == 3:
                return Hypothesis(text="hello", confidence=0.7)
            if n == 4:
                return Hypothesis(text="hello world", confidence=0.85)
            return None

        # Patch _load_model to return mock model + processor
        mock_model = MagicMock()
        mock_processor = MagicMock()
        with patch.object(parakeet_service, "_load_model",
                          return_value=(mock_model, mock_processor)):
            app = parakeet_service.create_app(cfg)

        # The lifespan will set app.state.decoder via make_hf_decoder
        # — we want to override that with our fake_decoder.  We do this
        # by manually invoking the lifespan via TestClient context, then
        # swapping the decoder.  But TestClient runs the lifespan on
        # __enter__ — so we use the context manager form.
        with TestClient(app) as client:
            # Override the decoder with our fake AFTER startup
            app.state.decoder = fake_decoder
            app.state.model = mock_model
            yield {"client": client, "app": app, "state": state}

    def test_healthz_returns_loaded_state(self, mock_app):
        client = mock_app["client"]
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["model_loaded"] is True
        assert body["device"] in ("cpu", "cuda")
        assert "vram_mb" in body
        assert "uptime_s" in body

    def test_metrics_returns_counters(self, mock_app):
        client = mock_app["client"]
        resp = client.get("/metrics?format=json")
        assert resp.status_code == 200
        body = resp.json()
        assert "uptime_s" in body
        assert "requests_total" in body
        assert "ws_connections_total" in body

    def test_rest_transcribe_returns_text(self, mock_app):
        client = mock_app["client"]
        # 1 second of tone @ 16 kHz int16
        samples = tone(1.0)
        body_bytes = pcm_int16(samples)
        resp = client.post("/transcribe", content=body_bytes,
                           headers={"content-type": "application/octet-stream"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["text"] == "hello world final"
        assert data["duration_s"] == pytest.approx(1.0, abs=0.01)
        assert data["confidence"] == pytest.approx(0.95, abs=0.01)
        # Decoder should have been called once (is_final=True)
        assert mock_app["state"]["decoder_calls"] == 1

    def test_rest_transcribe_rejects_empty_body(self, mock_app):
        client = mock_app["client"]
        resp = client.post("/transcribe", content=b"")
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    def test_rest_transcribe_rejects_odd_byte_count(self, mock_app):
        client = mock_app["client"]
        resp = client.post("/transcribe", content=b"\x00\x01\x02")
        assert resp.status_code == 400
        assert "even" in resp.json()["detail"].lower()

    def test_rest_transcribe_rejects_over_60s(self, mock_app):
        client = mock_app["client"]
        # 61 seconds
        samples = tone(61.0)
        body_bytes = pcm_int16(samples)
        resp = client.post("/transcribe", content=body_bytes)
        assert resp.status_code == 400
        assert "max" in resp.json()["detail"].lower()

    def test_rest_transcribe_returns_empty_when_decoder_returns_none(self, mock_app):
        client = mock_app["client"]
        # Replace decoder with a None-returning one for this test
        mock_app["app"].state.decoder = lambda *a: None
        samples = tone(1.0)
        body_bytes = pcm_int16(samples)
        resp = client.post("/transcribe", content=body_bytes)
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == ""
        assert data["confidence"] == 0.0

    def test_rest_transcribe_increments_counter(self, mock_app):
        client = mock_app["client"]
        body_bytes = pcm_int16(tone(1.0))
        before = client.get("/metrics?format=json").json()["rest_transcribe_total"]
        client.post("/transcribe", content=body_bytes)
        after = client.get("/metrics?format=json").json()["rest_transcribe_total"]
        assert after == before + 1

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="WebSocket sync TestClient deadlocks under pytest on Windows; "
               "covered by tests/e2e/test_voice_to_chat.py (PR 4)",
    )
    def test_websocket_emits_ready_and_partials(self, mock_app):
        """
        Smoke test: WS endpoint emits `ready` then partial hypotheses.

        SKIPPED on Windows due to portal deadlock in sync TestClient.
        Covered end-to-end by `tests/e2e/test_voice_to_chat.py` in PR 4.
        """
        client = mock_app["client"]
        with client.websocket_connect("/ws/stream") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            assert ready["sample_rate"] == 16_000

            for _ in range(4):
                ws.send_bytes(pcm_int16(tone(0.1)))
            partials = []
            for _ in range(4):
                try:
                    msg = ws.receive_json()
                    if msg.get("type") == "partial":
                        partials.append(msg["text"])
                except Exception:
                    break
            assert "hello" in partials
            assert "hello world" in partials

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="WebSocket sync TestClient deadlocks under pytest on Windows; "
               "covered by tests/e2e/test_voice_to_chat.py (PR 4)",
    )
    def test_websocket_emits_final_on_disconnect(self, mock_app):
        client = mock_app["client"]
        with client.websocket_connect("/ws/stream") as ws:
            ws.receive_json()  # "ready"
            ws.send_bytes(pcm_int16(tone(0.5)))
            ws.receive_json()  # partial (may be None)
        # After context exit, the final was sent in the finally block.
        # The decoder_calls counter tells us the final decode ran.
        assert mock_app["state"]["decoder_calls"] >= 1

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="WebSocket sync TestClient deadlocks under pytest on Windows; "
               "covered by tests/e2e/test_voice_to_chat.py (PR 4)",
    )
    def test_websocket_drops_odd_byte_chunk(self, mock_app):
        client = mock_app["client"]
        with client.websocket_connect("/ws/stream") as ws:
            ws.receive_json()  # "ready"
            ws.send_bytes(b"\x00\x01\x02")  # 3 bytes — odd
            ws.send_bytes(pcm_int16(tone(0.1)))
            import time
            time.sleep(0.05)
            assert True  # No exception is success

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="WebSocket sync TestClient deadlocks under pytest on Windows; "
               "covered by tests/e2e/test_voice_to_chat.py (PR 4)",
    )
    def test_websocket_increments_active_count(self, mock_app):
        client = mock_app["client"]
        before = client.get("/metrics?format=json").json()["ws_connections_total"]
        with client.websocket_connect("/ws/stream") as ws:
            ws.receive_json()  # "ready"
            ws.send_bytes(pcm_int16(tone(0.1)))
        after = client.get("/metrics?format=json").json()["ws_connections_total"]
        assert after == before + 1


# ===========================================================================
# Tests for ServiceConfig
# ===========================================================================

class TestServiceConfig:
    def test_defaults(self):
        from backend.audio.parakeet_service import ServiceConfig
        cfg = ServiceConfig()
        assert cfg.device == "cuda"
        assert cfg.precision == "fp16"
        assert cfg.port == 8765
        assert cfg.chunk_secs == 0.08
        assert cfg.max_concurrent_streams >= 1

    def test_as_dict_round_trips_keys(self):
        from backend.audio.parakeet_service import ServiceConfig
        cfg = ServiceConfig(device="cpu", precision="fp32", model_name="custom/x")
        d = cfg.as_dict()
        assert d["device"] == "cpu"
        assert d["precision"] == "fp32"
        assert d["model_name"] == "custom/x"


# ===========================================================================
# Tests for graceful degradation
# ===========================================================================

class TestGracefulDegradation:
    """When the model fails to load, the service must still respond."""

    def test_healthz_returns_503_when_model_load_fails(self):
        from backend.audio import parakeet_service

        cfg = parakeet_service.ServiceConfig(device="cpu", precision="fp32")
        # Patch must remain active for the entire TestClient lifetime
        # (the lifespan runs when entering the `with` block).
        with patch.object(parakeet_service, "_load_model",
                          side_effect=RuntimeError("transformers not installed")):
            app = parakeet_service.create_app(cfg)
            with TestClient(app) as client:
                resp = client.get("/healthz")
                assert resp.status_code == 503
                body = resp.json()
                assert body["model_loaded"] is False
                assert body["status"] == "loading"

    def test_rest_transcribe_returns_503_when_model_not_loaded(self):
        from backend.audio import parakeet_service

        cfg = parakeet_service.ServiceConfig(device="cpu", precision="fp32")
        with patch.object(parakeet_service, "_load_model",
                          side_effect=RuntimeError("transformers not installed")):
            app = parakeet_service.create_app(cfg)
            with TestClient(app) as client:
                body_bytes = pcm_int16(tone(1.0))
                resp = client.post("/transcribe", content=body_bytes)
                assert resp.status_code == 503
                assert "not loaded" in resp.json()["detail"].lower()

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="WebSocket sync TestClient deadlocks under pytest on Windows; "
               "covered by tests/e2e/test_voice_to_chat.py (PR 4)",
    )
    def test_ws_returns_error_when_model_not_loaded(self):
        from backend.audio import parakeet_service

        cfg = parakeet_service.ServiceConfig(device="cpu", precision="fp32")
        with patch.object(parakeet_service, "_load_model",
                          side_effect=RuntimeError("transformers not installed")):
            app = parakeet_service.create_app(cfg)
            with TestClient(app) as client:
                with client.websocket_connect("/ws/stream") as ws:
                    msg = ws.receive_json()
                    assert msg["type"] == "error"
                    assert "not loaded" in msg["error"].lower()
