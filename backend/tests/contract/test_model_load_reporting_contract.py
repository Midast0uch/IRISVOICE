"""What the UI is told about local models is the truth (UI load, live 2026-10-03).

Found by loading LFM2.5-2.6B from the dashboard's Local Models panel:
  1. The % went 18 -> 5 -> 12 (the server's own log stage restarted low).
  2. A suffix-named vision projector ("Ternary-Bonsai-2-27B-mmproj-BF16") was
     listed as a model with a Load button.
  3. The status tick carried nothing about the local slot, so a load the panel
     did not start (the VL-3B vision autoload) stayed invisible until a
     manual rescan.
"""

import asyncio
from pathlib import Path

from backend.agent.local_model_manager import LocalModelManager


def test_one_load_reports_one_rising_percent():
    from backend.agent.local_model_manager import _rising_progress

    got = []

    async def cb(e):
        got.append(e.get("pct"))

    rising = _rising_progress(cb)

    async def run():
        for e in ({"pct": 5}, {"pct": 18}, {"pct": 5}, {"pct": 12}, {"pct": 21},
                  {"phase": "error", "pct": 15, "msg": "x"}, {"pct": 100}):
            await rising(e)

    asyncio.run(run())
    assert got == [5, 18, 21, 15, 100]  # an error always passes


def test_a_clip_projector_is_never_a_model_and_serves_its_folder(tmp_path):
    folder = tmp_path / "Ternary-Bonsai-2-27B-gguf"
    folder.mkdir()
    for n in ("Ternary-Bonsai-2-27B-PTQ1_0.gguf", "Ternary-Bonsai-2-27B-mmproj-BF16.gguf"):
        (folder / n).write_bytes(b"x" * 64)
    mgr = LocalModelManager()
    mgr.set_models_directory(str(tmp_path))
    mgr.parse_gguf_metadata = lambda p: (
        {"architecture": "clip"} if "mmproj" in Path(p).name else {"architecture": "qwen3"})
    models = {m["filename"]: m for m in mgr.scan_models()}
    assert "Ternary-Bonsai-2-27B-mmproj-BF16.gguf" not in models
    base = models["Ternary-Bonsai-2-27B-PTQ1_0.gguf"]
    assert base["has_vision"] is True
    assert Path(base["mmproj_path"]).name == "Ternary-Bonsai-2-27B-mmproj-BF16.gguf"


def test_the_status_tick_carries_the_local_slot(monkeypatch):
    from backend.api import status_snapshot

    class _Mgr:
        def get_status(self):
            return {"loaded": True, "model_path": "C:/m/VL-3B.gguf", "n_ctx": 8192,
                    "vision_loaded": True, "draft_loaded": True, "pid": 1}

    monkeypatch.setattr("backend.agent.local_model_manager.get_local_model_manager", lambda: _Mgr())
    monkeypatch.setattr(status_snapshot, "_cached_git_status", lambda: {})
    snap = asyncio.run(status_snapshot.build_snapshot())
    assert snap["local_model"] == {"loaded": True, "model_path": "C:/m/VL-3B.gguf", "n_ctx": 8192,
                                   "vision_loaded": True, "draft_loaded": True}


def _planner(monkeypatch, free_gb, loaded_path=None, resident_gb=0.0):
    mgr = LocalModelManager()
    monkeypatch.setattr(mgr, "get_hardware_info", lambda *a, **k: {
        "cuda_available": True, "vram_free_gb": free_gb})
    monkeypatch.setattr(mgr, "recommend_profile", lambda *a, **k: "balanced")
    monkeypatch.setattr(mgr, "get_profile_params", lambda p, c: {"n_ctx": 32768, "cache_type_k": "q8_0"})
    monkeypatch.setattr(mgr, "derive_config", lambda *a, **k: {"n_ctx": 8192})
    # 1.5 GB of weights + 0.1 GB per 1k ctx: 32k -> 4.7 GB, 8k -> 2.3 GB
    monkeypatch.setattr(mgr, "estimate_vram_gb", lambda meta, n_ctx=8192, **k: 1.5 + 0.1 * n_ctx / 1024)
    monkeypatch.setattr(mgr, "is_loaded", lambda: loaded_path is not None)
    mgr._current_model_path = loaded_path
    if loaded_path:
        mgr._vram_ledger[loaded_path] = resident_gb
    return mgr


def test_the_card_plans_the_context_the_load_will_use(monkeypatch):
    """The card read "8k ctx" (the deriver's conservative cap) for a model the UI
    then loaded at the profile's 32768."""
    plan = _planner(monkeypatch, free_gb=7.0).plan_load({"context_length": 128000}, 1.5)
    assert plan["n_ctx"] == 32768 and plan["fits"] is True
    tight = _planner(monkeypatch, free_gb=4.0).plan_load({"context_length": 128000}, 1.5)
    assert tight["n_ctx"] == 8192  # only a card that cannot hold the profile is cut


def test_a_resident_model_counts_as_free_memory_for_the_next_load(monkeypatch):
    plan = _planner(monkeypatch, free_gb=3.0, loaded_path="C:/m/resident.gguf",
                    resident_gb=2.5).plan_load({"context_length": 128000}, 1.5)
    assert plan["n_ctx"] == 32768 and plan["fits"] is True
