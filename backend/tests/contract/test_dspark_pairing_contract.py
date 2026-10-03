"""DSpark guard (HANDOFF 10 D5, owner 2026-10-03: validate + measure).

The three *-DSpark GGUFs are DRAFTERS (general.architecture 'dflash'): they
predict tokens for one base model and are no model alone (llama-server fails
on 'dflash' as a main model). Before: scan_models listed them as loadable
models and nothing ever loaded one with its base.

Now: a drafter is never listed; it is paired with the dense base it names
(general.base_model.0.name) and loads with it as `-md <draft> --spec-type
draft-dspark`. Measured 2026-10-03 (prismml llama-server, RTX 3070, greedy,
3 prompts x 256 tokens): LFM2.5-2.6B 164 -> 259 tok/s, LFM2.5-VL-3B (+mmproj)
150 -> 181 tok/s; LFM2.5-8B-A1B (MoE) 194 -> 182 tok/s, so an MoE base is
not paired.
"""

import asyncio
import os
from pathlib import Path

from backend.agent.local_model_manager import LocalModelManager, PROFILES


def _mgr():
    mgr = LocalModelManager.__new__(LocalModelManager)
    mgr.plan_load = lambda meta, size_gb, mmproj_size_gb=0.0: {"vram_gb": size_gb + mmproj_size_gb}
    return mgr


def _entry(size_gb=1.5):
    return {"size_gb": size_gb, "mmproj_size_gb": 0.0, "draft_path": None, "draft_size_gb": 0.0}


def _attach(bases, metas, base_name):
    st = os.stat(__file__)  # any stat_result; only st_size is read
    _mgr()._attach_drafter(Path("D:/m/X-DSpark-Q4_K_M.gguf"),
                           {"architecture": "dflash", "general.base_model.0.name": base_name},
                           st, bases, metas)


def test_a_drafter_pairs_with_the_dense_base_it_names_only():
    bases = {s: _entry() for s in ("LFM2.5-2.6B-QAD-Q4_0", "LFM2.5-VL-3B-Q4_K_M",
                                   "LFM2.5-VL-450M-Q8_0", "LFM2-350M-Q4_K_M")}
    metas = {"LFM2.5-2.6B-QAD-Q4_0": {"general.name": "LFM2.5-2.6B-QAD-Q4_0"},
             "LFM2.5-VL-3B-Q4_K_M": {"general.name": "LFM2.5-VL-3B"},
             "LFM2.5-VL-450M-Q8_0": {"general.name": "LFM2.5-VL-450M"},
             "LFM2-350M-Q4_K_M": {}}
    _attach(bases, metas, "LFM2.5 VL 3B")
    paired = [s for s, e in bases.items() if e["draft_path"]]
    assert paired == ["LFM2.5-VL-3B-Q4_K_M"]
    # the card's VRAM figure includes the drafter and its buffers
    e = bases["LFM2.5-VL-3B-Q4_K_M"]
    assert e["vram_estimate_gb"] >= 1.5 + LocalModelManager.DRAFT_OVERHEAD_GB


def test_an_moe_base_is_not_paired():
    bases = {"LFM2.5-8B-A1B-UD-Q3_K_M": _entry()}
    metas = {"LFM2.5-8B-A1B-UD-Q3_K_M": {"general.name": "Lfm2.5-8B-A1B", "is_moe": True}}
    _attach(bases, metas, "LFM2.5 8B A1B")
    assert bases["LFM2.5-8B-A1B-UD-Q3_K_M"]["draft_path"] is None


def test_the_server_command_carries_the_drafter():
    mgr = LocalModelManager()
    mgr._select_server_binary = lambda model_path: "C:/fake/llama-server.exe"
    params = dict(PROFILES["balanced"])
    cmd = mgr._build_server_cmd("C:/m/base.gguf", params, purpose="embedding",
                                draft_path="C:/m/base-DSpark.gguf")
    i = cmd.index("-md")
    assert cmd[i + 1] == "C:/m/base-DSpark.gguf"
    assert cmd[cmd.index("--spec-type") + 1] == "draft-dspark"
    assert cmd[cmd.index("--n-gpu-layers-draft") + 1] == "-1"
    assert "-md" not in mgr._build_server_cmd("C:/m/base.gguf", params, purpose="embedding")


def test_a_drafter_never_loads_as_a_main_model(caplog):
    """Refused at the metadata read, before any sizing or spawn (the old code
    walked on into sizing and pre-flight with a model that cannot run)."""
    mgr = LocalModelManager()
    mgr.parse_gguf_metadata = lambda path: {"architecture": "dflash"}
    looked_up = []
    mgr._find_projector_for_model = lambda path: looked_up.append(path) or (None, 0.0)
    with caplog.at_level("ERROR"):
        assert asyncio.run(mgr.load_model("C:/m/LFM2.5-2.6B-DSpark-Q4_K_M.gguf")) is False
    assert looked_up == []
    assert "is a DSpark drafter" in caplog.text
