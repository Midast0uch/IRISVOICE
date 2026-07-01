"""
GPU-gated integration tests for the Parakeet ASR service (STANDALONE MODE).

NOTE: The primary Parakeet ASR path is now in-process via
``ParakeetTranscriber`` in ``voice_command.py``.  This file tests the
standalone FastAPI service in ``parakeet_service.py`` which is kept for
debugging and optional deployment.

These tests require the standalone Parakeet service running on ``localhost:8765``.
They skip gracefully when the service is not running (no GPU, or service
not started).

Usage:
    pytest tests/test_parakeet_integration.py -v
"""

from __future__ import annotations

import pytest

SERVICE_URL = "http://localhost:8765"


def _has_gpu() -> bool:
    """Check whether an NVIDIA GPU is available via torch.cuda."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _service_reachable() -> bool:
    """Quick check — returns True if Parakeet service responds on port 8765."""
    try:
        import socket
        with socket.create_connection(("localhost", 8765), timeout=1.0):
            return True
    except (OSError, ValueError):
        return False


def _request(method: str, path: str, **kwargs):
    import requests
    try:
        return requests.request(method, f"{SERVICE_URL}{path}", timeout=3.0, **kwargs)
    except requests.exceptions.RequestException:
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealthz:
    """Verify the service is alive and responding."""

    def test_healthz_returns_200(self):
        if not _has_gpu():
            pytest.skip("No NVIDIA GPU detected")
        if not _service_reachable():
            pytest.skip("Parakeet service not reachable on localhost:8765")

        resp = _request("GET", "/healthz")
        assert resp is not None and resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "model" in data


class TestMetrics:
    """Verify /metrics returns valid data in both formats."""

    def test_metrics_json_format(self):
        if not _has_gpu():
            pytest.skip("No NVIDIA GPU detected")
        if not _service_reachable():
            pytest.skip("Parakeet service not reachable")

        resp = _request("GET", "/metrics?format=json")
        assert resp is not None and resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "uptime_s" in data
        assert "latency_p50_ms" in data
        assert "latency_p95_ms" in data
        assert "latency_p99_ms" in data

    def test_metrics_prometheus_format(self):
        if not _has_gpu():
            pytest.skip("No NVIDIA GPU detected")
        if not _service_reachable():
            pytest.skip("Parakeet service not reachable")

        resp = _request("GET", "/metrics")
        assert resp is not None and resp.status_code == 200
        text = resp.text
        assert "parakeet_uptime_seconds" in text
        assert "parakeet_decode_latency_p50_ms" in text
        assert "parakeet_decode_latency_p95_ms" in text
        assert "parakeet_decode_latency_p99_ms" in text


class TestTranscribeEndpoint:
    """Verify the REST /transcribe endpoint handles edge cases."""

    def test_transcribe_empty_audio(self):
        if not _has_gpu():
            pytest.skip("No NVIDIA GPU detected")
        if not _service_reachable():
            pytest.skip("Parakeet service not reachable")

        resp = _request(
            "POST",
            "/transcribe",
            json={"audio_base64": "", "encoding": "pcm_s16le", "sample_rate": 16000},
        )
        assert resp is not None and resp.status_code == 200
        data = resp.json()
        assert "text" in data

    def test_transcribe_missing_fields(self):
        if not _has_gpu():
            pytest.skip("No NVIDIA GPU detected")
        if not _service_reachable():
            pytest.skip("Parakeet service not reachable")

        resp = _request("POST", "/transcribe", json={})
        assert resp is not None and resp.status_code == 422
