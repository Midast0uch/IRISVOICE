"""Wave 2 unit tests: d1 vision pairing + tool model server + role bindings.

specs/phonon2-d1-model-swap T2.1/T2.2/T2.5. Pins:
  * The d1 + mmproj pair attaches via the scan's same-folder fallback
    (CT-D1-1 precondition: a future matcher change cannot silently orphan
    the projector).
  * The tool model server resolves the real 2.6B on disk and fails soft
    without a binary.
  * kill_orphan_servers spares the tool server's port (source contract —
    the sweep kills by image name; an unspared port dies on every load).
  * The live config binds tool_execution to the local 2.6B, reasoning to
    Mercury, and the pinned vision model to d1.

Run: python -m pytest backend/tests/unit/test_wave2_d1_tool_server.py -q
"""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "data" / "iris_config.json"


def _write_fake_gguf(path: Path) -> None:
    """A minimal file with a valid GGUF magic header (same trick as
    test_scan_models_baseline.py — parse_gguf_metadata reads the header and
    tolerates truncated metadata)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"GGUF" + struct.pack("<III", 3, 1, 0))


# ── T2.1/CT-D1-1: the d1 + mmproj pairing ────────────────────────────────────
class TestD1ProjectorPairing:

    def test_d1_projector_pairs_via_same_folder_fallback(self, tmp_path, monkeypatch):
        """d1-3B-AD-Q4_K_M base + mmproj-d1-3B-BF16 projector: the stems do
        NOT match directly (the AD variant token breaks the key), so the
        same-folder fallback is what attaches the projector. Pin it: a
        matcher change that drops the fallback orphans d1's vision."""
        from backend.agent.local_model_manager import LocalModelManager

        d = tmp_path / "AtomicChat" / "d1-3B-GGUF"
        _write_fake_gguf(d / "d1-3B-AD-Q4_K_M.gguf")
        _write_fake_gguf(d / "mmproj-d1-3B-BF16.gguf")

        mgr = LocalModelManager()
        mgr.set_models_directory(str(tmp_path))
        models = mgr.scan_models()
        d1 = [m for m in models if "d1-3b-ad" in m["filename"].lower()]
        assert d1, f"d1 not discovered: {[m['filename'] for m in models]}"
        assert d1[0]["has_vision"] is True, "projector did not attach"
        assert d1[0]["mmproj_path"] and d1[0]["mmproj_path"].endswith(
            "mmproj-d1-3B-BF16.gguf"
        )
        # The projector itself is never a loadable brain.
        assert not any(
            m["filename"].lower().startswith("mmproj") for m in models
        )


# ── T2.5: the tool model server ──────────────────────────────────────────────
class TestToolModelServer:

    def test_model_path_resolves_the_real_26b(self):
        """The only 2.6B build on disk is QAD-Q4_0 (verified 2026-10-08);
        the server must find it through the models dir scan."""
        from backend.agent import tool_model_server as tms

        path = tms._model_path()
        assert path is not None, "tool model GGUF not found on disk"
        assert "LFM2.5-2.6B" in Path(path).name
        assert Path(path).exists()

    def test_fail_soft_without_binary(self, monkeypatch):
        """No llama-server binary -> ensure_running returns False, never raises."""
        from backend.agent import tool_model_server as tms

        monkeypatch.setattr(tms, "_binary", lambda: None)
        monkeypatch.setattr(tms, "_health_ok", lambda *a, **k: False)
        assert tms.ensure_running() is False

    def test_orphan_sweep_spares_the_tool_port(self):
        """Source contract: kill_orphan_servers kills llama-server.exe by
        image name; the tool server IS one. The spare-rule must name the
        tool port or every chat-model load silently kills it (the exact
        failure mode that took out the embedding sidecar, 2026-09-28)."""
        src = (REPO / "backend" / "agent" / "local_model_manager.py").read_text(
            encoding="utf-8"
        )
        assert "_tool_port" in src, "the sweep has no tool-port spare-rule"
        i = src.index("def kill_orphan_servers")
        body = src[i:]
        assert 'f"--port {_tool_port}"' in body, "spare rule must match the port flag"


# ── T2.3/T2.5: the live config bindings ──────────────────────────────────────
class TestConfigBindings:

    def test_tool_execution_binds_mercury_after_live_falsification(self):
        """T2.5 LIVE FINDING (2026-10-08, VERIFY.md): the owner's 2.6B tool
        binding was routed correctly (server warm, calls reached :8091) but
        the MODEL failed the c10 standard — it invented paths ('C:\\home\\user'
        as a workdir) and the eval regressed (FAIL, reply 100.1s vs the
        15.9s standard). Reverted to mercury-2 with the evidence recorded;
        the iris_tool_local instance stays configured (dormant) so the owner
        can re-bind after tuning or accepting the trade-off."""
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        bindings = {
            b["role"]: b for b in cfg["inference"]["role_bindings"]
        }
        assert bindings["tool_execution"]["instance_id"] == "inceptionlabs"
        assert bindings["tool_execution"]["model_override"] == "mercury-2"
        assert bindings["reasoning"]["instance_id"] == "inceptionlabs"
        assert bindings["reasoning"]["model_override"] == "mercury-2.5"
        # The dormant local instance stays ready for a future re-bind.
        assert "iris_tool_local" in cfg["inference"]["providers"]

    def test_tool_provider_instance_points_at_the_tool_server(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        inst = cfg["inference"]["providers"]["iris_tool_local"]
        assert inst["kind"] == "LOCAL_OPENAI"
        assert ":8091" in inst["endpoint"]
        assert "LFM2.5-2.6B" in inst["model"]
        # The LOCAL_OPENAI transport appends /v1/chat/completions itself
        # (transport.py:1250) — a trailing /v1 doubles the path and every
        # tool call 404s ("File Not Found", found live in eval c10 2026-10-08).
        assert not inst["endpoint"].rstrip("/").endswith("/v1"), inst["endpoint"]

    def test_vision_model_points_to_d1(self):
        """T2.3: the pinned VLM is d1; the old LFM2.5-VL-3B is off the live
        path (its registry retirement is T5.2, its file deletion T5.3)."""
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        vm = cfg["field_values"]["vision"]["vision_model"]
        assert "d1-3B-AD-Q4_K_M.gguf" in vm, vm
        assert "LFM2.5-VL-3B" not in vm

    def test_d1_registry_entry_exists(self):
        """T2.1: d1 is selectable in the model registry with a modest ctx
        (8192) so the VRAM plan stays inside the owner's budget."""
        reg = json.loads(
            (REPO / "models" / "gguf" / ".iris_model_settings.json").read_text(
                encoding="utf-8"
            )
        )
        assert "d1-3B-AD-Q4_K_M.gguf" in reg
        assert reg["d1-3B-AD-Q4_K_M.gguf"]["last_ctx"] <= 8192
