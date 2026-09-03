"""Standing CDD harness — vision-routing replay (T13, REQ-9).

Sibling of scripts/validate_der_integrity.py, validate_der_telemetry.py and
validate_der_tool_resolution.py. Replays the four vision-tier permutations
from specs/unified-vision-routing/design.md's Testing Strategy through the
FULL stack on every run, so a future edit cannot silently collapse the
hierarchy back to "always spawn the server".

THIS IS NOT HYPOTHETICAL. During this feature's build the hierarchy was
fully implemented, fully unit- and behavior-tested (63+ tests green), and
yet completely UNWIRED in production — five separate consumers constructed
``LFMVLProvider()`` directly, bypassing ``resolve_vision_provider()``
entirely. Two rounds of discovery were needed to find them all (T16, T17).
Every unit and behavioral test passed the whole time, because none of them
drove a real production entry point. This harness's wiring check
(``validate_production_consumer_reaches_resolver``) is the one assertion in
this file aimed squarely at THAT class of regression — see its docstring.

Only hardware (``LocalModelManager.get_hardware_info``, ``shutil.which``)
and the filesystem (``os.path.getsize``, temp model directories) are faked.
The hierarchy walk, the ladder arithmetic, the lease-kind rule (Decisions
Locked 8) and the VISION_UNAVAILABLE emit (REQ-3 AC4/AC6) are all REAL
production code — nothing here is mocked until it cannot fail. Selection is
asserted by free-VRAM ARITHMETIC against a synthetic candidate set, never by
model name (REQ-10 makes the shipped model ids examples, not contract).

No GPU, no network, no real model loads, no real user config.

Coverage:
  - Permutation 1 (REQ-2 AC2): multimodal API brain -> vision resolves at
    tier 1, NO llama-server spawn, free VRAM unchanged.
  - Permutation 2 (REQ-2 AC3, REQ-3 AC1): brain + tool both non-vision, a
    local model resident (little free VRAM) -> fallback fires and
    size-selects the NARROWER candidate.
  - Permutation 3 (REQ-2 AC4, REQ-3 AC1): both roles remote, nothing
    resident -> fallback selects the WIDER candidate.
  - Permutation 4 (REQ-2 AC2, REQ-4): local brain loaded WITH its projector
    -> tier 1 answers directly, no fallback spawn.
  - Decisions Locked 8: a LOCAL provider serving vision takes a lease at ANY
    tier (1, 2 or 3); a REMOTE provider takes none.
  - REQ-3 AC4/AC6: when nothing fits, the path RAISES
    ``VisionModelUnavailable`` AND emits ``VISION_UNAVAILABLE`` carrying free
    VRAM, the smallest requirement and the rejected ladder.
  - REQ-9 AC1/AC2: the per-resolution log carries tier, provider id, whether
    a load was required, and free VRAM at decision time; the fallback path
    logs the candidate ladder and each rejection's reason.
  - WIRING REGRESSION GUARD: a real production consumer
    (``VisionGuidedOperator.find_element``) reaches
    ``InferenceRouter.resolve_vision_provider()`` through
    ``resolve_vision_client()`` — proven by spying on the REAL method, not a
    stand-in, so a future revert to a bare ``LFMVLProvider()`` construction
    makes this fail.

Run:  python scripts/validate_der_vision_routing.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Make the backend importable when run from repo root or backend/.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if os.path.isdir(os.path.join(_REPO, "backend")):
    sys.path.insert(0, _REPO)

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.agent.local_model_manager import LocalModelManager
from backend.tools import lfm_vl_provider as vl


class _Failures:
    def __init__(self):
        self.items = []

    def check(self, name, cond):
        if cond:
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name}")
            self.items.append(name)


class _Patch:
    """Minimal manual monkeypatch (no pytest dependency) — records the
    original value of every attribute it sets and restores it on ``undo()``,
    even mid-failure, via the caller's own try/finally."""

    _MISSING = object()

    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        old = getattr(target, name, self._MISSING)
        self._undo.append((target, name, old))
        setattr(target, name, value)

    def undo(self):
        for target, name, old in reversed(self._undo):
            if old is self._MISSING:
                try:
                    delattr(target, name)
                except AttributeError:
                    pass
            else:
                setattr(target, name, old)
        self._undo.clear()


# ---------------------------------------------------------------------------
# Shared helpers — mirror the house style already pinned by
# backend/tests/behavioral/test_vision_routing_tier_permutations.py and
# test_vision_fallback_ladder.py, translated to the pytest-free harness form.
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


def _block_real_nvidia_smi(patch: _Patch) -> None:
    """This harness runs on a dev box with a real GPU — block the real
    ``nvidia-smi`` subprocess so faked hardware below is the only source of
    truth for free VRAM."""
    patch.setattr(shutil, "which", lambda _name: None)


def _isolate_search_dirs(patch: _Patch, tmp_dir: Path):
    """Private MODELS_DIR + home for lfm_vl_provider's discovery, so this
    machine's real vision models (if any) never leak into a selection
    assertion — filesystem is FAKED, the discovery/arithmetic code is real."""
    models_dir = tmp_dir / "models_dir"
    models_dir.mkdir(parents=True, exist_ok=True)
    home_dir = tmp_dir / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    patch.setattr(LocalModelManager, "MODELS_DIR", models_dir)
    patch.setattr(vl.Path, "home", staticmethod(lambda: home_dir))
    return models_dir, home_dir


def _place_synthetic_candidate(slot_dir, *, model_gb, mmproj_gb, sizes,
                                model_name=None, mmproj_name=None):
    """Write a synthetic (model, mmproj) pair with FAKED sizes registered
    into the shared ``sizes`` dict an ``os.path.getsize`` patch reads from.

    Deliberately generic-content filenames — REQ-10 is explicit that the
    shipped LFM2.5-VL-3B/450M ids are DEFAULTS AND EXAMPLES, not a contract,
    so assertions below compare against the PLACED PATH, never a model-name
    substring.

    T13b (fixture-staging fix, called out per CLAUDE.md): default names now
    DERIVE from ``slot_dir``'s own directory name instead of the old fixed
    placeholder pair "model.gguf" / "mmproj-x.gguf" reused across every slot.
    T15 sources discovery from ``LocalModelManager.scan_models()``, which
    dedupes candidates by filename STEM *globally* across the whole models
    directory (its split-shard grouping) — two slots both writing
    "model.gguf" collapsed into a single scanned entry, so only one of the
    two synthetic candidates was ever discoverable and the harness died with
    ``VisionModelUnavailable``. This mirrors the identical, already-passing
    fix in ``test_vision_fallback_ladder.py`` and
    ``test_vision_routing_tier_permutations.py`` verbatim. No assertion in
    this file changed — every check still compares the PLACED PATH/size,
    never a model-name substring.
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


def _patch_hardware(patch: _Patch, *, cuda_available=True, vram_free_gb=8.0):
    """Patch AT THE CLASS so the REAL singleton (and therefore its REAL
    estimate_vram_gb / parse_gguf_metadata) still does the weights/KV math —
    only the free-VRAM figure itself is controlled."""
    def _fake(self, force_refresh: bool = False):
        return {"cuda_available": cuda_available, "vram_free_gb": vram_free_gb}

    patch.setattr(LocalModelManager, "get_hardware_info", _fake)


# Numbers reused verbatim from test_vision_fallback_ladder.py's own
# already-passing parametrization (T7's suite), so the arithmetic this file
# leans on is independently pinned, not invented here:
#   wide candidate:   2.0GB model + 0.38GB mmproj  -> needs ~2.5GB
#   narrow candidate: 0.4GB model + 0.076GB mmproj -> needs ~0.5GB
_WIDE_MODEL_GB, _WIDE_MMPROJ_GB = 2.0, 0.38
_NARROW_MODEL_GB, _NARROW_MMPROJ_GB = 0.4, 0.076


def _place_wide_and_narrow(patch: _Patch, tmp_dir: Path):
    """Place two synthetic candidates for discovery.

    T15 (REQ-10 AC1/AC7) replaced ``_discover_vision_candidates``'s old
    hardcoded directory-name walk with discovery sourced from
    ``LocalModelManager.scan_models()``'s ``has_vision``-tagged entries —
    the SAME recursive *.gguf walk of ``LocalModelManager.MODELS_DIR`` the
    model browser already relies on. The two directory names below
    ("LFM2.5-VL-3B" / "LFM2.5-VL-450M") are therefore ordinary, arbitrary
    subdirectory names now — nothing reads them as hints — kept only for
    readability and parity with
    ``test_vision_routing_tier_permutations.py``/``test_vision_fallback_ladder.py``,
    which stage candidates the identical way. The FILE names inside are
    generic and slot-derived (see ``_place_synthetic_candidate``) and every
    assertion below compares the PLACED PATH and its FAKED SIZE, never a
    model-name substring — REQ-10's "not a contract" requirement is honored
    at the selection layer, which is the layer this harness is actually
    verifying.
    """
    models_dir, _home = _isolate_search_dirs(patch, tmp_dir)
    sizes: dict = {}
    wide_path, _ = _place_synthetic_candidate(
        models_dir / "LFM2.5-VL-3B",
        model_gb=_WIDE_MODEL_GB, mmproj_gb=_WIDE_MMPROJ_GB, sizes=sizes,
    )
    narrow_path, _ = _place_synthetic_candidate(
        models_dir / "LFM2.5-VL-450M",
        model_gb=_NARROW_MODEL_GB, mmproj_gb=_NARROW_MMPROJ_GB, sizes=sizes,
    )
    patch.setattr(os.path, "getsize", lambda p: sizes[str(p)])
    return wide_path, narrow_path


# ---------------------------------------------------------------------------
# Permutation 1 — multimodal API brain -> tier 1, NO spawn, free VRAM
# unchanged.
# ---------------------------------------------------------------------------


def validate_permutation_1_multimodal_brain_no_spawn(fail: _Failures) -> None:
    print("Permutation 1 (REQ-2 AC2): multimodal API brain -> vision resolves "
          "at tier 1, NO llama-server spawn, free VRAM unchanged")
    patch = _Patch()
    try:
        _block_real_nvidia_smi(patch)
        hw_state = {"vram_free_gb": 6.0}

        def _fake_hw(self, force_refresh: bool = False):
            return {"cuda_available": True, "vram_free_gb": hw_state["vram_free_gb"]}

        patch.setattr(LocalModelManager, "get_hardware_info", _fake_hw)

        def _spawn_spy(*_a, **_kw):
            hw_state["vram_free_gb"] -= 2.36  # models a real vision-server load
            raise AssertionError(
                "llama-server spawn attempted despite a vision-capable brain"
            )

        patch.setattr(subprocess, "Popen", _spawn_spy)

        find_calls: list = []

        def _find_spy():
            find_calls.append(True)
            raise AssertionError(
                "_find_vision_model called despite the brain answering directly"
            )

        patch.setattr(vl, "_find_vision_model", _find_spy)

        before_free = hw_state["vram_free_gb"]

        brain = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
        )
        router = _router_with(brain)
        router.roles.bind("reasoning", "openai")

        res = router.resolve_vision_provider()

        fail.check("tier == brain", res.tier == "brain")
        fail.check("provider_id == openai", res.provider_id == "openai")
        fail.check("requires_load is False", res.requires_load is False)
        fail.check("remote brain takes no lease (Decisions Locked 8)", res.takes_lease is False)
        fail.check("fallback candidate lookup never ran", find_calls == [])
        fail.check("free VRAM unchanged", hw_state["vram_free_gb"] == before_free)
    finally:
        patch.undo()


# ---------------------------------------------------------------------------
# Permutation 2 — brain + tool non-vision, local model resident -> fallback
# fires, size-selects the NARROWER candidate.
# ---------------------------------------------------------------------------


def validate_permutation_2_local_resident_selects_narrower(fail: _Failures) -> None:
    print("Permutation 2 (REQ-2 AC3, REQ-3 AC1): brain+tool non-vision, a "
          "local model resident (little free VRAM) -> fallback size-selects "
          "the NARROWER candidate")
    patch = _Patch()
    tmp_dir = Path(tempfile.mkdtemp(prefix="vision_harness_p2_"))
    try:
        _block_real_nvidia_smi(patch)
        wide_path, narrow_path = _place_wide_and_narrow(patch, tmp_dir)

        brain = ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
        )
        # "local and resident": an INPROCESS provider already loaded, no vision.
        tool = ProviderInstance(
            id="local:resident-a", label="Resident local model",
            kind=ProviderKind.INPROCESS, model="resident-model",
            loaded=True, vision_loaded=False,
        )
        router = _router_with(brain, tool)
        router.roles.bind("reasoning", "cohere")
        router.roles.bind("tool_execution", "local:resident-a")

        # A resident local model holds VRAM -> little is free for vision.
        # headroom = 1.8 - 1.0(reserve) = 0.8 -> wide (~2.5GB) rejected,
        # narrow (~0.5GB) fits. Numbers pinned by T7's own passing parametrization.
        _patch_hardware(patch, cuda_available=True, vram_free_gb=1.8)

        res = router.resolve_vision_provider()

        fail.check("tier == fallback (neither brain nor tool can see)", res.tier == "fallback")
        fail.check(
            "low free VRAM (resident local model) selects the NARROWER candidate",
            res.model_path == str(narrow_path),
        )
        fail.check("fallback always takes a lease (local llama-server)", res.takes_lease is True)

        # Decisions Locked 8, tier-2 positive case: the LOCAL tool itself
        # (were it the one serving vision) also takes a lease — driven as a
        # second, independent resolution.
        tool_vision = ProviderInstance(
            id="local:vision-tool", label="local vision tool",
            kind=ProviderKind.LOCAL_OPENAI, model="local-vl", vision_loaded=True,
        )
        router2 = _router_with(brain, tool_vision)
        router2.roles.bind("reasoning", "cohere")
        router2.roles.bind("tool_execution", "local:vision-tool")
        res2 = router2.resolve_vision_provider()
        fail.check("tier 2 resolved to the tool", res2.tier == "tool")
        fail.check(
            "a LOCAL tool serving vision takes a lease at tier 2 (Decisions Locked 8)",
            res2.takes_lease is True,
        )
    finally:
        patch.undo()
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Permutation 3 — both roles remote -> nothing resident -> fallback selects
# the WIDER candidate.
# ---------------------------------------------------------------------------


def validate_permutation_3_both_remote_selects_wider(fail: _Failures) -> None:
    print("Permutation 3 (REQ-2 AC4, REQ-3 AC1): both roles remote, nothing "
          "resident -> fallback size-selects the WIDER candidate")
    patch = _Patch()
    tmp_dir = Path(tempfile.mkdtemp(prefix="vision_harness_p3_"))
    try:
        _block_real_nvidia_smi(patch)
        wide_path, narrow_path = _place_wide_and_narrow(patch, tmp_dir)

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
        _patch_hardware(patch, cuda_available=True, vram_free_gb=10.0)

        res = router.resolve_vision_provider()

        fail.check("tier == fallback", res.tier == "fallback")
        fail.check(
            "high free VRAM (nothing resident) selects the WIDER candidate",
            res.model_path == str(wide_path),
        )
        fail.check("fallback takes a lease", res.takes_lease is True)

        # Decisions Locked 8, tier-2 negative case: a REMOTE tool serving
        # vision takes NO lease — driven through the real hierarchy.
        remote_vision_tool = ProviderInstance(
            id="ollama", label="Ollama", kind=ProviderKind.OLLAMA, model="llama3.2-vision",
            api_base_url="http://localhost:11434",
        )
        import backend.agent.inference.router as _router_mod
        patch.setattr(_router_mod, "_supports_vision_ollama", lambda inst: True)
        router2 = _router_with(brain, remote_vision_tool)
        router2.roles.bind("reasoning", "cohere")
        router2.roles.bind("tool_execution", "ollama")
        res2 = router2.resolve_vision_provider()
        fail.check("tier 2 resolved to the remote tool", res2.tier == "tool")
        fail.check(
            "a REMOTE tool serving vision takes NO lease (Decisions Locked 8)",
            res2.takes_lease is False,
        )
    finally:
        patch.undo()
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Permutation 4 — local brain loaded WITH its projector -> tier 1 answers
# directly, no fallback spawn.
# ---------------------------------------------------------------------------


def validate_permutation_4_local_brain_with_projector_no_fallback(fail: _Failures) -> None:
    print("Permutation 4 (REQ-2 AC2, REQ-4): local brain loaded WITH its "
          "projector -> tier 1 answers directly, no fallback spawn")
    patch = _Patch()
    try:
        _block_real_nvidia_smi(patch)
        hw_state = {"vram_free_gb": 5.0}

        def _fake_hw(self, force_refresh: bool = False):
            return {"cuda_available": True, "vram_free_gb": hw_state["vram_free_gb"]}

        patch.setattr(LocalModelManager, "get_hardware_info", _fake_hw)

        def _spawn_spy(*_a, **_kw):
            hw_state["vram_free_gb"] -= 0.70  # models a real small vision load
            raise AssertionError(
                "llama-server spawn attempted despite a locally-loaded vision brain"
            )

        patch.setattr(subprocess, "Popen", _spawn_spy)

        find_calls: list = []

        def _find_spy():
            find_calls.append(True)
            raise AssertionError(
                "_find_vision_model called despite tier 1 answering directly"
            )

        patch.setattr(vl, "_find_vision_model", _find_spy)

        before_free = hw_state["vram_free_gb"]

        # Local brain, loaded WITH its projector — vision_loaded=True is set
        # by the loader (T8) exactly when the running server was launched
        # with --mmproj (REQ-1 AC3). Disk presence alone is never the signal.
        brain = ProviderInstance(
            id="local:brain-with-projector", label="local vision brain",
            kind=ProviderKind.LOCAL_OPENAI, model="local-vl-brain",
            loaded=True, vision_loaded=True,
        )
        router = _router_with(brain)
        router.roles.bind("reasoning", "local:brain-with-projector")

        res = router.resolve_vision_provider()

        fail.check("tier == brain", res.tier == "brain")
        fail.check("provider_id == local:brain-with-projector", res.provider_id == "local:brain-with-projector")
        fail.check("requires_load is False", res.requires_load is False)
        fail.check(
            "a LOCAL provider serving vision takes a lease at ANY tier "
            "(Decisions Locked 8), tier 1 included",
            res.takes_lease is True,
        )
        fail.check("fallback candidate lookup never ran", find_calls == [])
        fail.check("free VRAM unchanged", hw_state["vram_free_gb"] == before_free)
    finally:
        patch.undo()


# ---------------------------------------------------------------------------
# REQ-3 AC4/AC6 — fail loudly + VISION_UNAVAILABLE, driven end to end.
# ---------------------------------------------------------------------------


def validate_req3_fail_loudly_and_emits_full_payload(fail: _Failures) -> None:
    print("REQ-3 AC4/AC6: no-fit path RAISES VisionModelUnavailable AND "
          "emits VISION_UNAVAILABLE carrying free VRAM, the smallest "
          "requirement and the rejected ladder")
    from backend.agent.event_bus import get_event_bus, reset_event_bus_for_testing, IRISStreamEvent

    reset_event_bus_for_testing()
    patch = _Patch()
    tmp_dir = Path(tempfile.mkdtemp(prefix="vision_harness_nofit_"))
    lfm_logger = logging.getLogger("backend.tools.lfm_vl_provider")
    records: list = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Capture()
    prior_level = lfm_logger.level
    lfm_logger.addHandler(handler)
    lfm_logger.setLevel(logging.INFO)
    try:
        _block_real_nvidia_smi(patch)
        models_dir, _home = _isolate_search_dirs(patch, tmp_dir)
        sizes: dict = {}
        # Same note as _place_wide_and_narrow above: directory NAMES here are
        # arbitrary post-T15 (scan_models()-sourced discovery); the file
        # names and every assertion below are generic/arithmetic.
        _place_synthetic_candidate(
            models_dir / "LFM2.5-VL-3B", model_gb=1.5, mmproj_gb=0.3, sizes=sizes,
        )
        _place_synthetic_candidate(
            models_dir / "LFM2.5-VL-450M", model_gb=0.8, mmproj_gb=0.15, sizes=sizes,
        )
        patch.setattr(os.path, "getsize", lambda p: sizes[str(p)])
        # free=0.5, reserve=1.0 -> headroom negative: nothing can ever fit.
        _patch_hardware(patch, cuda_available=True, vram_free_gb=0.5)

        brain = ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
        )
        tool = ProviderInstance(
            id="deepseek", label="DeepSeek", kind=ProviderKind.API, model="deepseek-chat"
        )
        router = _router_with(brain, tool)
        router.roles.bind("reasoning", "cohere")
        router.roles.bind("tool_execution", "deepseek")

        captured: list = []
        get_event_bus().subscribe(
            IRISStreamEvent.VISION_UNAVAILABLE, lambda p: captured.append(p.data)
        )

        raised = None
        try:
            router.resolve_vision_provider()
        except vl.VisionModelUnavailable as exc:
            raised = exc

        fail.check(
            "VisionModelUnavailable RAISES through the full hierarchy walk "
            "(resolve_vision_provider -> tier 3 -> _find_vision_model)",
            raised is not None,
        )
        if raised is not None:
            fail.check("raise carries free_gb == 0.5", raised.free_gb == 0.5)
            fail.check("raise carries smallest_requirement_gb > 0", raised.smallest_requirement_gb > 0)
            fail.check("raise carries the full rejected ladder (2 candidates)", len(raised.ladder) == 2)

        fail.check("VISION_UNAVAILABLE emitted exactly once", len(captured) == 1)
        if captured:
            payload = captured[0]
            fail.check("payload carries a message", bool(payload.get("message")))
            fail.check("payload free_vram_gb == 0.5", payload.get("free_vram_gb") == 0.5)
            fail.check(
                "payload smallest_requirement_gb > 0",
                payload.get("smallest_requirement_gb", 0) > 0,
            )
            ladder = payload.get("ladder") or []
            fail.check("payload ladder has 2 rejected candidates", len(ladder) == 2)
            fail.check(
                "every ladder entry names model_path/needed_gb/reason",
                all("model_path" in e and "needed_gb" in e and "reason" in e for e in ladder),
            )

        # REQ-9 AC2: the fallback path logs the candidate ladder and why
        # each rejected candidate did not fit.
        rejected_lines = [r for r in records if "vision candidate REJECTED" in r]
        fail.check(
            "REQ-9 AC2: candidate ladder rejections are logged (2 candidates)",
            len(rejected_lines) == 2,
        )
        fail.check(
            "REQ-9 AC2: each rejection log line names a reason",
            all("needs" in r and "available after" in r for r in rejected_lines),
        )
    finally:
        lfm_logger.removeHandler(handler)
        lfm_logger.setLevel(prior_level)
        patch.undo()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        reset_event_bus_for_testing()


# ---------------------------------------------------------------------------
# REQ-9 AC1 — the per-resolution log carries tier, provider id, whether a
# load was required, and free VRAM at decision time.
# ---------------------------------------------------------------------------


def validate_req9_observability_log(fail: _Failures) -> None:
    print("REQ-9 AC1: per-resolution log carries tier, provider id, whether "
          "a load was required, and free VRAM at decision time")
    patch = _Patch()
    router_logger = logging.getLogger("backend.agent.inference.router")
    records: list = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Capture()
    prior_level = router_logger.level
    router_logger.addHandler(handler)
    router_logger.setLevel(logging.INFO)
    try:
        _block_real_nvidia_smi(patch)
        _patch_hardware(patch, cuda_available=True, vram_free_gb=6.0)

        brain = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
        )
        router = _router_with(brain)
        router.roles.bind("reasoning", "openai")
        router.resolve_vision_provider()

        line = next(
            (r for r in records if "[resolve_vision_provider]" in r and "tier=brain" in r),
            None,
        )
        fail.check("a [resolve_vision_provider] log line was emitted", line is not None)
        if line:
            fail.check("log line carries the provider id", "provider=openai" in line)
            fail.check("log line carries requires_load", "requires_load=False" in line)
            fail.check("log line carries free_vram_gb", "free_vram_gb=" in line)
    finally:
        router_logger.removeHandler(handler)
        router_logger.setLevel(prior_level)
        patch.undo()


# ---------------------------------------------------------------------------
# WIRING REGRESSION GUARD — a real production consumer reaches
# resolve_vision_provider() through resolve_vision_client(), not a bare
# LFMVLProvider() construction. THIS is the check aimed at the class of bug
# that actually shipped: the hierarchy existed, was fully tested, and was
# never called from production code.
# ---------------------------------------------------------------------------


def validate_production_consumer_reaches_resolver(fail: _Failures) -> None:
    print("WIRING REGRESSION GUARD: VisionGuidedOperator.find_element (a "
          "real production consumer) reaches "
          "InferenceRouter.resolve_vision_provider() through "
          "resolve_vision_client() rather than constructing LFMVLProvider() "
          "directly — the exact gap that hid the whole feature")
    patch = _Patch()
    try:
        _block_real_nvidia_smi(patch)
        _patch_hardware(patch, cuda_available=True, vram_free_gb=6.0)

        brain = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o",
            api_base_url="https://api.openai.com/v1",
        )
        router = _router_with(brain)
        router.roles.bind("reasoning", "openai")

        class _FakeKernel:
            def __init__(self, router):
                self._router = router

        import backend.agent.agent_kernel as _ak

        patch.setattr(_ak, "get_active_kernel", lambda session_id: _FakeKernel(router))
        patch.setattr(vl, "screenshot_to_bytes", lambda region=None: b"\x89PNG-fake")

        calls: list = []
        real_resolve = InferenceRouter.resolve_vision_provider

        def _spy(self):
            calls.append(True)
            return real_resolve(self)

        patch.setattr(InferenceRouter, "resolve_vision_provider", _spy)

        class _FakeHttpResponse:
            def __init__(self, content):
                self._content = content

            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": self._content}}]}

        import httpx

        patch.setattr(httpx, "post", lambda *a, **kw: _FakeHttpResponse("x=42 y=99"))

        from backend.agent.vision_guided_operator import VisionGuidedOperator

        operator = VisionGuidedOperator(vision_server=object(), native_operator=None)
        coords = asyncio.run(operator.find_element("the submit button"))

        fail.check(
            "resolve_vision_provider() was reached from a production consumer "
            "(VisionGuidedOperator.find_element)",
            bool(calls),
        )
        fail.check(
            "the vision answer returned through the resolved client",
            coords == (42, 99),
        )
    finally:
        patch.undo()


def main() -> int:
    print("=" * 72)
    print("VISION ROUTING — STANDING CDD HARNESS (T13, REQ-9)")
    print("=" * 72)
    fail = _Failures()

    validate_permutation_1_multimodal_brain_no_spawn(fail)
    validate_permutation_2_local_resident_selects_narrower(fail)
    validate_permutation_3_both_remote_selects_wider(fail)
    validate_permutation_4_local_brain_with_projector_no_fallback(fail)
    validate_req3_fail_loudly_and_emits_full_payload(fail)
    validate_req9_observability_log(fail)
    validate_production_consumer_reaches_resolver(fail)

    print("-" * 72)
    if fail.items:
        print(f"HARNESS FAILED: {len(fail.items)} check(s) broken")
        for name in fail.items:
            print(f"  - {name}")
        return 1
    print("HARNESS PASSED: all vision-routing tier permutations and contracts hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
