"""Phase B1 guards (audit addendum 2026-10-02, faults V2-V7): vision discovery
must find the LOCAL vision server, prove sight with a real image question, never
scan a paid catalog, and let the router reach the autoload of the user's chosen
model (ladder first, then the vision card pin).

Every test here FAILED on the code before the fix (proved by running this file
against the committed lfm_vl_provider.py / router.py). No network, no model load.
"""

from __future__ import annotations

import httpx
import pytest

import backend.tools.lfm_vl_provider as vl


class _Resp:
    def __init__(self, status_code: int = 200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json


class _Server:
    """Fake OpenAI-compatible server. `sees` = model ids that really see the
    image; every other model answers 200 + "ok" (drops the image - the
    live NVIDIA gpt-oss-20b shape)."""

    def __init__(self, models, sees=(), meta=None):
        self.models = models
        self.sees = set(sees)
        self.meta = meta or {}
        self.posted: list = []

    def get(self, url, timeout=1.0, headers=None):
        if url.endswith("/models"):
            data = [dict({"id": m}, **self.meta.get(m, {})) for m in self.models]
            return _Resp(200, {"data": data})
        return _Resp(200)

    def post(self, url, json=None, timeout=1.0, headers=None):
        model = (json or {}).get("model")
        self.posted.append(model)
        text = "red, blue" if model in self.sees else "ok"
        return _Resp(200, {"choices": [{"message": {"content": text}}]})


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(vl, "_reused_vision_base_url", None)
    monkeypatch.setattr(vl, "_reused_vision_auth", None)
    monkeypatch.setattr(vl, "_reused_vision_model", None)
    monkeypatch.setattr(vl, "_VISION_CAPABILITY_CACHE", {})
    monkeypatch.setattr(vl, "_EXTRA_VISION_ENDPOINTS", [])
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_ENABLED", False)
    monkeypatch.setattr(vl, "_lifecycle_callback", None)


def _install(monkeypatch, server):
    monkeypatch.setattr(httpx, "get", server.get)
    monkeypatch.setattr(httpx, "post", server.post)


# ── V2: the local server on 8082 is a candidate, and local goes first ───────


def test_v2_shared_server_on_8082_is_probed(monkeypatch):
    monkeypatch.setattr(
        vl, "_load_candidate_endpoints_from_config",
        lambda: [("http://127.0.0.1:8082/v1", None, "")],
    )
    specs = vl._candidate_vision_specs("")
    assert [s[0] for s in specs] == ["http://127.0.0.1:8082/v1"]


def test_v4_local_candidates_come_before_paid_api(monkeypatch):
    monkeypatch.setattr(
        vl, "_load_candidate_endpoints_from_config",
        lambda: [
            ("https://integrate.api.nvidia.com/v1", "nvidia", "deepseek"),
            ("http://127.0.0.1:8082", None, ""),
        ],
    )
    specs = vl._candidate_vision_specs("")
    assert specs[0][0] == "http://127.0.0.1:8082/v1"


# ── V3: sight is proved by naming the probe colours, not by a 200 ──────────


def test_v3_text_only_model_that_answers_200_is_rejected(monkeypatch):
    server = _Server(["gpt-oss-20b"])  # answers "ok", never sees
    _install(monkeypatch, server)
    assert vl._probe_vision_capability("http://127.0.0.1:8082/v1") is None
    assert server.posted == ["gpt-oss-20b"]


def test_v3_model_that_names_the_colours_is_accepted(monkeypatch):
    _install(monkeypatch, _Server(["lfm2.5-vl-3b"], sees={"lfm2.5-vl-3b"}))
    assert vl._probe_vision_capability("http://127.0.0.1:8082/v1") == "lfm2.5-vl-3b"


def test_v3_fast_path_and_health_never_trust_an_unverified_8082(monkeypatch):
    """8082 answers /models with a TEXT-ONLY model: no fast-path 'ready', no
    healthy vision."""
    monkeypatch.setattr(vl, "_load_candidate_endpoints_from_config", lambda: [])
    _install(monkeypatch, _Server(["text-tool-model"]))
    assert vl._ensure_vision_server_running("") is False
    assert vl.LFMVLProvider().health_check() is False


# ── V4: never scan a paid catalog; metadata first; verdicts expire ──────────


def test_v4_remote_endpoint_probes_only_its_configured_model(monkeypatch):
    server = _Server(["a-text", "gpt-oss-20b", "m-config", "z-vlm"], sees={"z-vlm"})
    _install(monkeypatch, server)
    got = vl._probe_vision_capability(
        "https://integrate.api.nvidia.com/v1", preferred_model="m-config"
    )
    assert got is None
    assert server.posted == ["m-config"]


def test_v4_published_text_only_metadata_sends_no_image(monkeypatch):
    server = _Server(
        ["m-config"],
        meta={"m-config": {"architecture": {"input_modalities": ["text"]}}},
    )
    _install(monkeypatch, server)
    assert vl._probe_vision_capability(
        "https://openrouter.ai/api/v1", preferred_model="m-config"
    ) is None
    assert server.posted == []


def test_v4_published_image_metadata_is_trusted_without_a_paid_probe(monkeypatch):
    server = _Server(
        ["m-config"],
        meta={"m-config": {"architecture": {"input_modalities": ["text", "image"]}}},
    )
    _install(monkeypatch, server)
    assert vl._probe_vision_capability(
        "https://openrouter.ai/api/v1", preferred_model="m-config"
    ) == "m-config"
    assert server.posted == []


def test_v4_local_probe_round_trips_are_bounded(monkeypatch):
    server = _Server([f"text-{i}" for i in range(20)])
    _install(monkeypatch, server)
    assert vl._probe_vision_capability("http://localhost:11434/v1") is None
    assert len(server.posted) == vl._LOCAL_PROBE_CAP


def test_v4_negative_verdict_expires(monkeypatch):
    server = _Server(["m"])
    _install(monkeypatch, server)
    assert vl._is_verified_vision_capable("http://127.0.0.1:8082/v1") is None
    assert vl._is_verified_vision_capable("http://127.0.0.1:8082/v1") is None
    assert server.posted == ["m"]  # cached inside the window
    monkeypatch.setattr(vl, "_CAPABILITY_TTL_S", 0.0)
    server.sees.add("m")  # the server loaded a projector meanwhile
    assert vl._is_verified_vision_capable("http://127.0.0.1:8082/v1") == "m"


# ── V5: the router's tier 3 reaches the autoload ────────────────────────────


def test_v5_router_tier3_answers_requires_load_when_autoload_can_serve(monkeypatch):
    from backend.agent.inference.router import InferenceRouter

    monkeypatch.setattr("backend.agent.inference.router._free_vram_gb", lambda: 4.0)
    monkeypatch.setattr(vl, "_discover_reusable_vision_server", lambda base_url="": None)
    monkeypatch.setattr(vl, "vision_autoload_possible", lambda: True)
    router = InferenceRouter.__new__(InferenceRouter)
    router.resolve = lambda role: (_ for _ in ()).throw(KeyError(role))
    res = router.resolve_vision_provider()
    assert res.tier == "fallback"
    assert res.requires_load is True


# ── V6 + V7: autoload matches by file name / real path; the ladder leads ───


class _Mgr:
    def __init__(self, entries):
        self._entries = entries

    def scan_models(self):
        return self._entries


def _entry(path):
    import ntpath

    return {"path": path, "filename": ntpath.basename(path), "mmproj_path": path + ".mmproj"}


def _patch_scan(monkeypatch, entries):
    import backend.agent.local_model_manager as lmm

    monkeypatch.setattr(lmm, "get_local_model_manager", lambda: _Mgr(entries))


def test_v6_pin_through_a_junction_matches_by_file_name(monkeypatch):
    scanned = r"C:\Users\u\.lmstudio\models\LiquidAI\LFM2.5-VL-3B-GGUF\LFM2.5-VL-3B-Q4_K_M.gguf"
    _patch_scan(monkeypatch, [_entry(scanned)])
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_HINT", "")
    monkeypatch.setattr(vl, "_read_vision_fallback_ladder", lambda: [])
    monkeypatch.setattr(
        vl, "_read_global_vision_model_pin",
        lambda: r"D:\lmstudio\models\LiquidAI\LFM2.5-VL-3B-GGUF\LFM2.5-VL-3B-Q4_K_M.gguf",
    )
    assert vl._find_autoload_vision_model() == scanned


def test_v7_ladder_orders_the_autoload_and_outranks_the_pin(monkeypatch):
    a = r"C:\m\Ternary-Bonsai-2-27B-PTQ1_0.gguf"
    b = r"C:\m\LFM2.5-VL-3B-Q4_K_M.gguf"
    _patch_scan(monkeypatch, [_entry(b), _entry(a)])
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_HINT", "")
    monkeypatch.setattr(vl, "_read_vision_fallback_ladder", lambda: [a, b])
    monkeypatch.setattr(vl, "_read_global_vision_model_pin", lambda: b)
    assert vl._find_autoload_vision_models() == [a, b]
    monkeypatch.setattr(vl, "_read_vision_fallback_ladder", lambda: [])
    assert vl._find_autoload_vision_models() == [b]


def test_v4_remote_model_id_is_never_cut_to_its_basename(monkeypatch):
    """Live 2026-10-02: the file-name bridge also posted "kimi-k3" for the
    configured "cline-pass/kimi-k3" - a second paid probe of another id."""
    server = _Server(["cline-pass/kimi-k3"])
    _install(monkeypatch, server)
    vl._probe_vision_capability("https://api.cline.bot/api/v1", preferred_model="cline-pass/kimi-k3")
    assert server.posted == ["cline-pass/kimi-k3"]


def test_v4_ollama_cloud_models_are_not_local_fallbacks(monkeypatch):
    server = _Server(["gpt-oss:120b-cloud", "deepseek-v4-flash:preview-cloud", "llava:7b"],
                     sees={"llava:7b"})
    _install(monkeypatch, server)
    assert vl._probe_vision_capability("http://localhost:11434/v1") == "llava:7b"
    assert server.posted == ["llava:7b"]


# ── V9: an API Brain/tool that PUBLISHES image input serves vision itself ───


def test_v9_published_image_input_makes_an_api_model_see(monkeypatch):
    import backend.agent.inference.provider_catalog as pc
    from backend.agent.inference.provider import ProviderInstance, ProviderKind
    from backend.agent.inference.router import supports_vision

    monkeypatch.setattr(pc, "_API_WINDOWS", {})
    monkeypatch.setattr(pc, "_API_VISION", {})

    def _get(url, timeout=10.0, verify=None, headers=None):
        return _Resp(200, {"data": [
            {"id": "qwen/qwen3-vl-30b", "context_length": 131072,
             "architecture": {"input_modalities": ["text", "image"]}},
            {"id": "poolside/laguna-xs-2.1:free", "context_length": 65536,
             "architecture": {"input_modalities": ["text"]}},
        ]})

    monkeypatch.setattr(httpx, "get", _get)
    pc._fetch_api_windows("openrouter", "https://openrouter.ai/api/v1", "")

    def _inst(model):
        return ProviderInstance(id="openrouter", label="OpenRouter", kind=ProviderKind.API,
                                model=model, api_base_url="https://openrouter.ai/api/v1")

    assert supports_vision(_inst("qwen/qwen3-vl-30b")) is True
    assert supports_vision(_inst("poolside/laguna-xs-2.1:free")) is False
    assert supports_vision(_inst("never-published")) is False
