"""Contract tests: the model pin on calibration rows (REQ-6 AC6.5, T27).

AC6.5 — record `model_id` + file hash on calibration rows and assert identity at
load, so a model swap is DETECTABLE instead of silently invalidating every
threshold measured on the previous model.

This is the guard behind REQ-22 AC22.1 (thresholds are distribution-specific)
and REQ-31 AC31.4 (a moved configuration marks thresholds stale).

Wave 5 (specs/phonon2-d1-model-swap T5.3): re-pointed from the GLiNER ONNX
backend to d1 on the shared llama-server. The INTENT is unchanged — the
identity a calibration row records must be the identity the engine reports,
and it must be VARIANT-DERIVED (the quant IS the identity: AD-Q4_K_M is not
BF16). The sha256-of-weights pin became a served-file fingerprint: d1's
weights live with the shared server, and the backend's truthful identity is
the served GGUF filename + a stable file fingerprint.
"""

from __future__ import annotations

import pytest

from backend.agent.decision_backend_d1 import D1Backend
from backend.agent.decision_engine import (
    DecisionEngine,
    EngineConfig,
    load_engine_config,
)


class TestModelIdentity:
    def test_backend_id_is_variant_derived(self):
        """The identity names the VARIANT (quant token included), so a
        different quant of the same model can never inherit a threshold."""
        bid = D1Backend().backend_id
        assert bid == "d1-3b-ad-q4_k_m", bid
        assert "q4_k_m" in bid, "the quant token IS the identity (AC22.1)"

    def test_model_hash_is_a_stable_file_fingerprint(self):
        """The hash is a stable fingerprint of the served GGUF file —
        a swap (different size or mtime) changes it, so a calibration row
        can detect it. The hash exists only once the backend KNOWS what is
        served (a fresh instance honestly returns None)."""
        b = D1Backend()
        if not b.load():
            pytest.skip("d1 not served on the shared server")
        h1 = b.model_hash
        assert h1, "a loaded backend exposed no model hash"
        b2 = D1Backend()
        assert b2.load()
        assert b2.model_hash == h1, "the fingerprint is not stable"

    def test_engine_reports_the_backend_identity(self, monkeypatch):
        """AC6.5: after a load, the ENGINE's model_id is the BACKEND's
        identity — the same string a calibration row records."""
        eng = DecisionEngine(EngineConfig(**{
            k: getattr(load_engine_config(), k)
            for k in ("candidate_cap", "acquire_timeout_s")
        }))
        fake = type("FakeBackend", (), {
            "backend_id": "d1-3b-ad-q4_k_m",
            "load": lambda self: True,
            "retry_load": False,
        })()
        eng._backend_factory = lambda **kw: fake
        assert eng._load()
        assert eng.model_id == "d1-3b-ad-q4_k_m"
        assert eng._cfg.backend_id == "d1-3b-ad-q4_k_m"
