"""Behavioral (T12, Wave 5): full-loop drives of the four vision-tier
permutations from specs/unified-vision-routing/design.md's Testing Strategy
and REQ-2/REQ-3.

Every test below calls the REAL production entry point,
``InferenceRouter.resolve_vision_provider()`` (REQ-2's hierarchy walk), and —
where the fallback tier fires — lets ``lfm_vl_provider._find_vision_model()``
(REQ-3's size-selection) run its REAL discovery + arithmetic against synthetic
candidates and faked hardware/filesystem, exactly as
``test_vision_fallback_ladder.py`` (T7's own suite) does. ONLY hardware
(``LocalModelManager.get_hardware_info``, ``shutil.which``) and the
filesystem (``os.path.getsize``, temp model directories) are faked — the
hierarchy walk, the ladder arithmetic, the lease-kind rule (Decisions Locked
8) and the VISION_UNAVAILABLE emit (REQ-3 AC6) are all real code, not mocks
that cannot fail.

No GPU, no network, no real model loads, no real user config.
"""
from __future__ import annotations

import subprocess

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.agent.local_model_manager import LocalModelManager
from backend.tools import lfm_vl_provider as vl


# ---------------------------------------------------------------------------
# Shared fixtures / helpers (mirror test_vision_capability_resolution.py and
# test_vision_fallback_ladder.py's house style — this file introduces no new
# faking convention).
# ---------------------------------------------------------------------------


def _router_with(*instances: ProviderInstance) -> InferenceRouter:
    """Build a router bypassing __init__ (no config load, no side effects)."""
    reg = ProviderRegistry()
    for inst in instances:
        reg.add(inst)
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", None)
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


@pytest.fixture(autouse=True)
def _no_real_nvidia_smi(monkeypatch):
    """Block the real nvidia-smi subprocess so hardware faking below is the
    only source of truth for free VRAM (this dev box has a real GPU)."""
    monkeypatch.setattr("shutil.which", lambda _name: None)


@pytest.fixture(autouse=True)
def _clean_event_bus():
    from backend.agent.event_bus import reset_event_bus_for_testing

    reset_event_bus_for_testing()
    yield
    reset_event_bus_for_testing()


def _isolate_search_dirs(monkeypatch, tmp_path):
    """Private MODELS_DIR + home for lfm_vl_provider's discovery, so this dev
    box's real vision models never leak into a selection assertion."""
    models_dir = tmp_path / "models_dir"
    models_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setattr(LocalModelManager, "MODELS_DIR", models_dir)
    monkeypatch.setattr(vl.Path, "home", staticmethod(lambda: home_dir))
    return models_dir, home_dir


def _place_synthetic_candidate(slot_dir, *, model_gb, mmproj_gb, sizes,
                                model_name=None, mmproj_name=None):
    """Write a synthetic (model, mmproj) pair with FAKED sizes registered into
    the shared ``sizes`` dict an ``os.path.getsize`` patch reads from.

    Deliberately generic-content filenames — REQ-10 is explicit that the
    shipped LFM2.5-VL-3B/450M ids are DEFAULTS AND EXAMPLES, not a contract,
    so assertions in this file compare against the PLACED PATH, never
    against a model-name substring.

    INPUT CHANGE (T15, called out per CLAUDE.md): default names now DERIVE
    from ``slot_dir``'s own directory name (every fixed slot already has a
    distinct name) instead of the old fixed placeholder pair "model.gguf" /
    "mmproj-x.gguf". T15 sources `_discover_vision_candidates` from
    `LocalModelManager.scan_models()`'s `has_vision`-tagged entries, which
    requires the base model and its projector to stem-match AND requires
    distinct base filenames across directories (scan_models() dedupes by
    filename stem globally). Every assertion in this file is UNCHANGED.
    """
    slot_dir.mkdir(parents=True, exist_ok=True)
    base_name = slot_dir.name
    if model_name is None:
        model_name = f"{base_name}-Q4_K_M.gguf"
    if mmproj_name is None:
        mmproj_name = f"mmproj-{base_name}-F16.gguf"
    model_path = slot_dir / model_name
    mmproj_path = slot_dir / mmproj_name
    model_path.write_bytes(b"\0")
    mmproj_path.write_bytes(b"\0")
    sizes[str(model_path)] = int(model_gb * 1024 ** 3)
    sizes[str(mmproj_path)] = int(mmproj_gb * 1024 ** 3)
    return model_path, mmproj_path


def _patch_hardware(monkeypatch, *, cuda_available=True, vram_free_gb=8.0):
    """Patch AT THE CLASS so the REAL singleton (and therefore its REAL
    estimate_vram_gb / parse_gguf_metadata) still does the weights/KV math —
    only the free-VRAM figure itself is controlled."""
    def _fake(self, force_refresh: bool = False):
        return {"cuda_available": cuda_available, "vram_free_gb": vram_free_gb}

    monkeypatch.setattr(LocalModelManager, "get_hardware_info", _fake)


def _subscribe_vision_unavailable(monkeypatch):
    from backend.agent.event_bus import get_event_bus, IRISStreamEvent

    captured = []
    get_event_bus().subscribe(
        IRISStreamEvent.VISION_UNAVAILABLE, lambda p: captured.append(p.data)
    )
    return captured


# Numbers reused verbatim from test_vision_fallback_ladder.py's own
# already-passing parametrization (T7's suite), so the arithmetic this file
# leans on is independently pinned, not invented here:
#   wide candidate:   2.0GB model + 0.38GB mmproj  -> needs ~2.5GB
#   narrow candidate: 0.4GB model + 0.076GB mmproj -> needs ~0.5GB
_WIDE_MODEL_GB, _WIDE_MMPROJ_GB = 2.0, 0.38
_NARROW_MODEL_GB, _NARROW_MMPROJ_GB = 0.4, 0.076


def _place_wide_and_narrow(monkeypatch, tmp_path):
    models_dir, _home = _isolate_search_dirs(monkeypatch, tmp_path)
    sizes: dict = {}
    wide_path, _ = _place_synthetic_candidate(
        models_dir / "LFM2.5-VL-3B",
        model_gb=_WIDE_MODEL_GB, mmproj_gb=_WIDE_MMPROJ_GB, sizes=sizes,
    )
    narrow_path, _ = _place_synthetic_candidate(
        models_dir / "LFM2.5-VL-450M",
        model_gb=_NARROW_MODEL_GB, mmproj_gb=_NARROW_MMPROJ_GB, sizes=sizes,
    )
    monkeypatch.setattr("os.path.getsize", lambda p: sizes[str(p)])
    return wide_path, narrow_path


# ---------------------------------------------------------------------------
# Permutation 1 — Brain = multimodal API -> NO llama-server spawn.
# ---------------------------------------------------------------------------


def test_tier1_multimodal_api_brain_no_spawn_free_vram_unchanged(monkeypatch):
    """The whole point of the feature: a multimodal API brain answers vision
    itself, and the fallback's discovery/spawn machinery is never reached.

    Modeled concretely through free VRAM: if the spawn spy below were ever
    reached, it would consume VRAM (as a real llama-server load does) — the
    free-VRAM-unchanged assertion therefore fails even if the call-count
    assertion were ever weakened by a future edit, not only when it passes.
    """
    hw_state = {"vram_free_gb": 6.0}

    def _fake_hw(self, force_refresh: bool = False):
        return {"cuda_available": True, "vram_free_gb": hw_state["vram_free_gb"]}

    monkeypatch.setattr(LocalModelManager, "get_hardware_info", _fake_hw)

    def _spawn_spy(*_a, **_kw):
        hw_state["vram_free_gb"] -= 2.36  # models a real vision-server load
        raise AssertionError(
            "llama-server spawn attempted despite a vision-capable brain"
        )

    monkeypatch.setattr(subprocess, "Popen", _spawn_spy)

    find_calls: list = []

    def _find_spy():
        find_calls.append(True)
        raise AssertionError(
            "_find_vision_model called despite the brain answering directly"
        )

    monkeypatch.setattr(vl, "_find_vision_model", _find_spy)

    before_free = hw_state["vram_free_gb"]

    brain = ProviderInstance(
        id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
    )
    router = _router_with(brain)
    router.roles.bind("reasoning", "openai")

    res = router.resolve_vision_provider()

    assert res.tier == "brain"
    assert res.provider_id == "openai"
    assert res.requires_load is False
    assert res.takes_lease is False  # remote API — no local process to lease
    assert find_calls == [], "the fallback's candidate lookup must never run"
    assert hw_state["vram_free_gb"] == before_free, "free VRAM must be unchanged"


# ---------------------------------------------------------------------------
# Permutation 2 — Brain = no vision (Cohere), Tool = no vision, LOCAL and
# resident (e.g. LFM2.5-8B-A1B) -> fallback fires, size-selects the SMALLER
# model because the resident local model holds the VRAM.
# ---------------------------------------------------------------------------


def test_tier2_local_resident_holds_vram_fallback_selects_smaller(monkeypatch, tmp_path):
    wide_path, narrow_path = _place_wide_and_narrow(monkeypatch, tmp_path)

    brain = ProviderInstance(
        id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
    )
    # "local and resident": an INPROCESS provider already loaded, no vision.
    tool = ProviderInstance(
        id="local:lfm25-8b-a1b", label="LFM2.5-8B-A1B (local)",
        kind=ProviderKind.INPROCESS, model="LFM2.5-8B-A1B",
        loaded=True, vision_loaded=False,
    )
    router = _router_with(brain, tool)
    router.roles.bind("reasoning", "cohere")
    router.roles.bind("tool_execution", "local:lfm25-8b-a1b")

    # A resident local model holds VRAM -> little is free for vision.
    # headroom = 1.8 - 1.0(reserve) = 0.8 -> wide (~2.5GB) rejected,
    # narrow (~0.5GB) fits. Numbers pinned by T7's own passing parametrization.
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=1.8)

    res = router.resolve_vision_provider()

    assert res.tier == "fallback", "neither brain nor tool can see -> fallback"
    assert res.model_path == str(narrow_path), (
        "low free VRAM (a resident local model) must size-select the SMALLER candidate"
    )
    assert res.takes_lease is True  # fallback is always a local llama-server


def test_local_tool_takes_lease_at_tier2(monkeypatch):
    """Decisions Locked 8: a LOCAL provider takes a lease at ANY tier, tier 2
    included — not only when the fallback fires."""
    hw = {"vram_free_gb": 4.0}
    monkeypatch.setattr(
        LocalModelManager, "get_hardware_info",
        lambda self, force_refresh=False: {"cuda_available": True, "vram_free_gb": hw["vram_free_gb"]},
    )
    brain = ProviderInstance(
        id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
    )
    tool = ProviderInstance(
        id="local:gemma", label="local", kind=ProviderKind.LOCAL_OPENAI,
        model="gemma-4-E4B", vision_loaded=True,
    )
    router = _router_with(brain, tool)
    router.roles.bind("reasoning", "cohere")
    router.roles.bind("tool_execution", "local:gemma")

    res = router.resolve_vision_provider()

    assert res.tier == "tool"
    assert res.provider_id == "local:gemma"
    assert res.takes_lease is True, "a LOCAL tool serving vision must take a lease"


# ---------------------------------------------------------------------------
# Permutation 3 — Both roles remote -> nothing resident -> fallback selects
# the LARGER model.
# ---------------------------------------------------------------------------


def test_tier3_both_roles_remote_fallback_selects_larger(monkeypatch, tmp_path):
    wide_path, narrow_path = _place_wide_and_narrow(monkeypatch, tmp_path)

    brain = ProviderInstance(
        id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
    )
    tool = ProviderInstance(
        id="deepseek", label="DeepSeek", kind=ProviderKind.API, model="deepseek-chat"
    )
    router = _router_with(brain, tool)
    router.roles.bind("reasoning", "cohere")
    router.roles.bind("tool_execution", "deepseek")

    # Nothing local resident -> plenty of free VRAM.
    # headroom = 10.0 - 1.0(reserve) = 9.0 -> wide (~2.5GB) fits.
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=10.0)

    res = router.resolve_vision_provider()

    assert res.tier == "fallback"
    assert res.model_path == str(wide_path), (
        "with nothing resident, high free VRAM must size-select the LARGER candidate"
    )
    assert res.takes_lease is True


def test_remote_brain_and_remote_tool_take_no_lease(monkeypatch):
    """Decisions Locked 8, negative case for tiers 1 and 2: a REMOTE provider
    serving vision (API/OLLAMA) takes NO lease, at either tier — driven
    through the real hierarchy, not asserted in isolation."""
    hw = {"vram_free_gb": 4.0}
    monkeypatch.setattr(
        LocalModelManager, "get_hardware_info",
        lambda self, force_refresh=False: {"cuda_available": True, "vram_free_gb": hw["vram_free_gb"]},
    )
    brain = ProviderInstance(
        id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
    )
    tool = ProviderInstance(
        id="ollama", label="Ollama", kind=ProviderKind.OLLAMA, model="llama3.2-vision",
        api_base_url="http://localhost:11434",
    )
    monkeypatch.setattr(
        "backend.agent.inference.router._supports_vision_ollama", lambda inst: True
    )
    router = _router_with(brain, tool)
    router.roles.bind("reasoning", "cohere")
    router.roles.bind("tool_execution", "ollama")

    res = router.resolve_vision_provider()

    assert res.tier == "tool"
    assert res.provider_id == "ollama"
    assert res.takes_lease is False, "a REMOTE tool serving vision must take no lease"


# ---------------------------------------------------------------------------
# Permutation 4 — Local model loaded WITH its projector -> tier 1 answers
# directly, no fallback spawns.
# ---------------------------------------------------------------------------


def test_tier4_local_brain_with_projector_answers_directly_no_fallback(monkeypatch):
    hw_state = {"vram_free_gb": 5.0}

    def _fake_hw(self, force_refresh: bool = False):
        return {"cuda_available": True, "vram_free_gb": hw_state["vram_free_gb"]}

    monkeypatch.setattr(LocalModelManager, "get_hardware_info", _fake_hw)

    def _spawn_spy(*_a, **_kw):
        hw_state["vram_free_gb"] -= 0.70  # models a real 450M-class vision load
        raise AssertionError(
            "llama-server spawn attempted despite a locally-loaded vision brain"
        )

    monkeypatch.setattr(subprocess, "Popen", _spawn_spy)

    find_calls: list = []

    def _find_spy():
        find_calls.append(True)
        raise AssertionError(
            "_find_vision_model called despite tier 1 answering directly"
        )

    monkeypatch.setattr(vl, "_find_vision_model", _find_spy)

    before_free = hw_state["vram_free_gb"]

    # Local brain, loaded WITH its projector — vision_loaded=True is set by
    # the loader (T8) exactly when the running server was launched with
    # --mmproj (REQ-1 AC3). Disk presence alone is never the signal.
    brain = ProviderInstance(
        id="local:gemma", label="Gemma 4 E4B (local)", kind=ProviderKind.LOCAL_OPENAI,
        model="gemma-4-E4B", loaded=True, vision_loaded=True,
    )
    router = _router_with(brain)
    router.roles.bind("reasoning", "local:gemma")

    res = router.resolve_vision_provider()

    assert res.tier == "brain"
    assert res.provider_id == "local:gemma"
    assert res.requires_load is False
    assert res.takes_lease is True, (
        "a LOCAL provider serving vision takes a lease at ANY tier (Decisions Locked 8), "
        "tier 1 included"
    )
    assert find_calls == [], "the fallback's candidate lookup must never run"
    assert hw_state["vram_free_gb"] == before_free, "free VRAM must be unchanged"


# ---------------------------------------------------------------------------
# REQ-3 AC4/AC6 — fail loudly + VISION_UNAVAILABLE, driven end to end.
# ---------------------------------------------------------------------------


def test_no_fit_fails_loudly_and_emits_full_payload_through_full_hierarchy(monkeypatch, tmp_path):
    """Neither role can see, and NOTHING fits free VRAM.

    Drives the WHOLE no-fit path through the real hierarchy walk
    (resolve_vision_provider -> tier 3 -> _find_vision_model) and asserts
    both halves of REQ-3 AC4/AC6: the underlying selector RAISES (never
    silently degrades to CPU), and the VISION_UNAVAILABLE event carries free
    VRAM, the smallest candidate's requirement, and the full rejected ladder.
    """
    models_dir, _home = _isolate_search_dirs(monkeypatch, tmp_path)
    sizes: dict = {}
    _place_synthetic_candidate(
        models_dir / "LFM2.5-VL-3B",
        model_gb=1.5, mmproj_gb=0.3, sizes=sizes,
    )
    _place_synthetic_candidate(
        models_dir / "LFM2.5-VL-450M",
        model_gb=0.8, mmproj_gb=0.15, sizes=sizes,
    )
    monkeypatch.setattr("os.path.getsize", lambda p: sizes[str(p)])
    # free=0.5, reserve=1.0 -> headroom negative: nothing can ever fit.
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=0.5)

    brain = ProviderInstance(
        id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
    )
    tool = ProviderInstance(
        id="deepseek", label="DeepSeek", kind=ProviderKind.API, model="deepseek-chat"
    )
    router = _router_with(brain, tool)
    router.roles.bind("reasoning", "cohere")
    router.roles.bind("tool_execution", "deepseek")
    captured = _subscribe_vision_unavailable(monkeypatch)

    # Half 1 — the event + the raise, driven through the FULL hierarchy walk.
    # T16 UPDATE (2026-08-18): resolve_vision_provider()'s tier-3 try/except
    # used to catch VisionModelUnavailable and return a clean
    # VisionResolution(model_path=None) — silently defeating REQ-3 AC4 the
    # moment a real production caller existed (T16 wired the first ones up).
    # T16 re-raises it here instead; this is the GUARD this test's own T16
    # entry in tasks.md pre-authorized extending once that happened. The
    # VISION_UNAVAILABLE emit still fires before the raise either way (it
    # lives inside _find_vision_model's _fail_vision_unavailable), so the
    # event assertions below are unchanged.
    with pytest.raises(vl.VisionModelUnavailable) as exc_info:
        router.resolve_vision_provider()
    assert exc_info.value.free_gb == 0.5
    assert exc_info.value.smallest_requirement_gb > 0
    assert len(exc_info.value.ladder) == 2

    assert len(captured) == 1, "VISION_UNAVAILABLE must be emitted exactly once"
    payload = captured[0]
    assert payload["message"]
    assert payload["free_vram_gb"] == 0.5
    assert payload["smallest_requirement_gb"] > 0
    assert len(payload["ladder"]) == 2
    for entry in payload["ladder"]:
        assert "model_path" in entry and "needed_gb" in entry and "reason" in entry

    # Half 2 — the raise also reaches _find_vision_model()'s own caller
    # directly, under the SAME faked hardware/filesystem (this was the ONLY
    # place the raise was observable before T16; kept as a second,
    # independent check now that both callers see it).
    with pytest.raises(vl.VisionModelUnavailable) as exc_info2:
        vl._find_vision_model()
    assert exc_info2.value.free_gb == 0.5
    assert exc_info2.value.smallest_requirement_gb > 0
    assert len(exc_info2.value.ladder) == 2


# ---------------------------------------------------------------------------
# REQ-2 edge cases as BEHAVIOR: real dangling/unbound roles, not stubs.
# ---------------------------------------------------------------------------


def test_dangling_role_binding_raises_for_real_and_hierarchy_continues(monkeypatch):
    """``resolve()`` raising must never propagate — driven with a REAL
    dangling binding (an instance id that was never registered), so
    ``RoleBindingTable.resolve`` raises a genuine ``RuntimeError`` from
    production code, not a monkeypatched stand-in for one."""
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=4.0)
    tool = ProviderInstance(
        id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
    )
    router = _router_with(tool)  # "cerebras-ghost" deliberately never added
    router.roles.bind("reasoning", "cerebras-ghost")
    router.roles.bind("tool_execution", "openai")

    with pytest.raises(RuntimeError):
        router.resolve("reasoning")  # sanity: the dangling binding really does raise

    res = router.resolve_vision_provider()

    assert res.tier == "tool"
    assert res.provider_id == "openai"


def test_never_bound_role_continues_all_the_way_to_real_fallback_selection(monkeypatch, tmp_path):
    """Reasoning was never bound at all (not merely unbound-then-stubbed) and
    the tool role also cannot see -> the hierarchy must continue for real,
    all the way through to the fallback's genuine candidate selection."""
    wide_path, _narrow_path = _place_wide_and_narrow(monkeypatch, tmp_path)
    tool = ProviderInstance(
        id="deepseek", label="DeepSeek", kind=ProviderKind.API, model="deepseek-chat"
    )
    router = _router_with(tool)
    router.roles.bind("tool_execution", "deepseek")
    # reasoning is never bound, and _default_role stays None (see _router_with).
    _patch_hardware(monkeypatch, cuda_available=True, vram_free_gb=10.0)

    res = router.resolve_vision_provider()

    assert res.tier == "fallback"
    assert res.model_path == str(wide_path)
