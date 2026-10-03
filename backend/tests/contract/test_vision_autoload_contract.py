"""P3 auto-provision contract (session-342, owner decision; spec
specs/vision-single-server REQ-4 AC4).

Pins the ONLY lawful auto-load: the shared single-slot server has NO resident
model. A resident model — ours or an externally started one — is never
evicted automatically. Disabled flag honoured. Success routes the call to the
freshly loaded server. Every failure degrades to the loud unavailable path.
"""
from __future__ import annotations

import pytest

import backend.tools.vision_provider as vl


class _MgrEmpty:
    """Shared slot empty: nothing loaded, nothing on the wire."""

    ENDPOINT = "http://127.0.0.1:8082/v1"
    loaded = False

    def is_loaded(self):
        return False

    def scan_models(self):
        return []

    async def load_model(self, *a, **k):  # pragma: no cover - must not run
        raise AssertionError("load_model must not run in this scenario")


class _MgrLoadable(_MgrEmpty):
    """Empty slot with a projector-backed model on disk; records the load."""

    def __init__(self):
        self.loads = []

    def scan_models(self):
        return [
            {"path": r"C:\models\SomeText-Q4.gguf", "filename": "SomeText-Q4.gguf",
             "display_name": "SomeText", "mmproj_path": None, "size_gb": 8.0,
             "has_vision": False},
            {"path": r"C:\models\LFM2.5-VL-3B-Q4_K_M.gguf",
             "filename": "LFM2.5-VL-3B-Q4_K_M.gguf", "display_name": "LFM2.5 VL",
             "mmproj_path": r"C:\models\mmproj-LFM2.5-VL-3B-f16.gguf",
             "size_gb": 3.1, "has_vision": True},
        ]

    async def load_model(self, model_path, profile="balanced", custom_params=None,
                         purpose="chat", progress_cb=None, crash_cb=None,
                         with_projector=True):
        self.loads.append({"path": model_path, "with_projector": with_projector})
        return True


def _no_external_resident(monkeypatch):
    """No server answers on the shared endpoint (slot empty, nothing on the
    wire). Raises like a connection refusal so BOTH the step-1 fast path in
    _ensure_vision_server_running and the wire check in
    _shared_slot_is_resident see 'server down'."""
    import httpx

    def _raise(*a, **k):
        raise httpx.ConnectError("no server (test)")

    monkeypatch.setattr(httpx, "get", _raise)


def _patch_manager(monkeypatch, mgr):
    import backend.agent.local_model_manager as lmm

    monkeypatch.setattr(lmm, "get_local_model_manager", lambda: mgr)


@pytest.fixture(autouse=True)
def _reset_vision_module_state(monkeypatch):
    """The provider module keeps borrow/lifecycle state in module globals;
    a reuse from a previous test would satisfy these tests for free."""
    monkeypatch.setattr(vl, "_reused_vision_base_url", None, raising=False)
    monkeypatch.setattr(vl, "_reused_vision_auth", None, raising=False)
    monkeypatch.setattr(vl, "_reused_vision_model", None, raising=False)
    vl._VISION_CAPABILITY_CACHE.clear()


def test_resident_model_is_never_evicted(monkeypatch):
    """AC4 second clause: ANY resident model blocks autoload — eviction is
    the disruption the owner forbade. Even WITH the pinned model on disk,
    load_model must not run."""

    class _MgrResident(_MgrLoadable):
        def is_loaded(self):
            return True

    mgr = _MgrResident()
    _patch_manager(monkeypatch, mgr)
    _no_external_resident(monkeypatch)
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_HINT", "LFM2.5-VL-3B")
    monkeypatch.setattr(
        vl, "_discover_reusable_vision_server", lambda base_url="": None
    )

    assert vl._ensure_vision_server_running("") is False
    assert mgr.loads == [], "autoload evicted (attempted to replace) a resident model"


def test_empty_slot_loads_projector_model_and_borrows_it(monkeypatch):
    """AC4 first clause: empty slot -> load_model(path, with_projector=True)
    -> capability cache cleared -> discovery re-proves and the call succeeds."""
    mgr = _MgrLoadable()
    _patch_manager(monkeypatch, mgr)
    _no_external_resident(monkeypatch)
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_HINT", "LFM2.5-VL-3B")

    probes = []

    def _discover(base_url=""):
        probes.append(base_url)
        # Before load: nothing to borrow. After load: the fresh server proves.
        return "http://127.0.0.1:8082/v1" if mgr.loads else None

    monkeypatch.setattr(vl, "_discover_reusable_vision_server", _discover)

    assert vl._ensure_vision_server_running("") is True
    assert len(mgr.loads) == 1
    assert mgr.loads[0]["with_projector"] is True, (
        "the autoloaded model MUST carry its projector — a text-only load "
        "would leave vision unavailable while reporting warm"
    )
    assert mgr.loads[0]["path"].endswith("LFM2.5-VL-3B-Q4_K_M.gguf")
    assert len(probes) == 2, "discovery must re-run after the load"


def test_no_pin_no_autoload(monkeypatch):
    """Consent anchor: with no vision pin and no env hint, autoload NEVER
    picks a model on its own — even with a projector-backed model on disk.
    This is what keeps a fresh install (and a test machine) untouched."""
    mgr = _MgrLoadable()
    _patch_manager(monkeypatch, mgr)
    _no_external_resident(monkeypatch)
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_HINT", "")
    monkeypatch.setattr(vl, "_read_global_vision_model_pin", lambda: "")
    monkeypatch.setattr(
        vl, "_discover_reusable_vision_server", lambda base_url="": None
    )

    assert vl._ensure_vision_server_running("") is False
    assert mgr.loads == [], "autoload chose a model with no recorded user choice"


def test_empty_slot_without_projector_model_degrades_loudly(monkeypatch):
    """No projector-backed model on disk -> no load attempt, loud False."""

    class _MgrNoVL(_MgrEmpty):
        def scan_models(self):
            return [
                {"path": r"C:\models\TextOnly.gguf", "filename": "TextOnly.gguf",
                 "display_name": "TextOnly", "mmproj_path": None, "size_gb": 4.0},
            ]

    mgr = _MgrNoVL()
    _patch_manager(monkeypatch, mgr)
    _no_external_resident(monkeypatch)
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_HINT", "TextOnly")
    monkeypatch.setattr(
        vl, "_discover_reusable_vision_server", lambda base_url="": None
    )
    assert vl._ensure_vision_server_running("") is False


def test_autoload_disabled_flag_is_honoured(monkeypatch):
    """IRIS_VISION_AUTOLOAD=0 restores the pre-P3 behavior exactly."""
    mgr = _MgrLoadable()
    _patch_manager(monkeypatch, mgr)
    _no_external_resident(monkeypatch)
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_HINT", "LFM2.5-VL-3B")
    monkeypatch.setattr(
        vl, "_discover_reusable_vision_server", lambda base_url="": None
    )
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_ENABLED", False)

    assert vl._ensure_vision_server_running("") is False
    assert mgr.loads == []


def test_autoload_model_hint_pins_the_choice(monkeypatch):
    """IRIS_VISION_AUTOLOAD_MODEL selects among projector-backed candidates."""
    mgr = _MgrLoadable()
    _patch_manager(monkeypatch, mgr)
    # With no loadable path found the hint gate decides selection; simulate a
    # second candidate so the hint has something to choose between.
    mgr.scan_models = lambda: [
        {"path": r"C:\models\Bonsai-VL-27B-Q4.gguf",
         "filename": "Bonsai-VL-27B-Q4.gguf", "display_name": "Bonsai VL",
         "mmproj_path": r"C:\models\mmproj-bonsai.gguf", "size_gb": 16.0,
         "has_vision": True},
        {"path": r"C:\models\LFM2.5-VL-3B-Q4_K_M.gguf",
         "filename": "LFM2.5-VL-3B-Q4_K_M.gguf", "display_name": "LFM2.5 VL",
         "mmproj_path": r"C:\models\mmproj-lfm.gguf", "size_gb": 3.1,
         "has_vision": True},
    ]
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_HINT", "bonsai")
    chosen = vl._find_autoload_vision_model()
    assert chosen.endswith("Bonsai-VL-27B-Q4.gguf")
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_HINT", "nomatch-nothing")
    assert vl._find_autoload_vision_model() is None
