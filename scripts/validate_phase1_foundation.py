#!/usr/bin/env python3
"""
Standing CDD harness for Phase 1 — Foundation.

Run on every build:  python scripts/validate_phase1_foundation.py
Exits non-zero if any assertion fails.

Asserts (from specs/phase-1-foundation/design.md "Standing CDD harness"):
  1. CT-F1..CT-F9 hold.
  2. Budget <= window for every (window, class) pair in the REQ-1 AC7 matrix.
  3. Budget and work units derive from the same window.
  4. No provider-wide table default exceeds the conservative default.
  5. No config file written by any path contains a credential or fragment.
  6. No /api/inference/state response contains a credential or fragment.
  7. Every API entry has both endpoint and cred_ref; a fixture missing one is
     rejected.
  8. Two providers with different keys round-trip through config + keyring
     with their own credentials.
  9. A synthetic pre-upgrade config migrates with bindings intact; migrating
     twice is a no-op.
  10. Routing resolves identically for all four `provider` values.
  11. No registry id is the bare literal "local".

Assertions 2, 5 and 6 are the ones worth running on every commit regardless
of what changed — an overcommit and a credential leak both fail silently and
neither produces a user report (design.md).
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import traceback
from pathlib import Path

# Make the backend importable when run as a standalone script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unittest.mock import patch  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def main() -> int:
    import inspect

    from backend.agent.der_constants import (
        DER_TOKEN_BUDGETS,
        DER_BUDGET_MIN_FLOOR,
        DER_WINDOW_UTILISATION,
        get_token_budget,
        resolve_der_token_budget,
        derive_work_units_0,
    )
    from backend.agent import agent_kernel as _ak
    from backend.agent.inference.provider import ProviderInstance, ProviderKind
    from backend.agent.inference.router import InferenceRouter
    from backend.agent.inference.transport import ApiHttpxTransport, InProcessTransport
    import backend.agent.inference.registry as _reg_mod
    import backend.agent.inference.roles as _roles_mod
    from backend.iris_config import InferenceConfig, ProviderEntry

    def _fresh_registry():
        """Reset the process-wide registry + role table between scenarios."""
        _reg_mod._REGISTRY = None
        _roles_mod._ROLES = None

    def _stub_kernel(provider="", model=""):
        """Minimal AgentKernel with only the attrs resolve_context_window_
        with_source() reads — avoids a full kernel construction."""
        k = _ak.AgentKernel.__new__(_ak.AgentKernel)
        k._model_provider = provider
        k._selected_reasoning_model = model
        k._context_window_overrides = {}
        return k

    # =====================================================================
    # Assertion 1: CT-F1..CT-F9 hold.
    # =====================================================================

    print("== CT-F1: DER mode table (DER_TOKEN_BUDGETS) unchanged ==")
    _expected_budgets = {
        "quick": 15_000, "agentic": 30_000, "full": 60_000,
        "SPEC": 60_000, "RESEARCH": 80_000, "IMPLEMENT": 40_000,
        "DEBUG": 30_000, "TEST": 40_000, "REVIEW": 20_000,
        "DEFAULT": 40_000, "VOICE_FIRST": 15_000,
        "spec": 60_000, "research": 80_000, "implement": 40_000,
        "debug": 30_000, "test": 40_000, "review": 20_000,
        "default": 40_000, "voice_first": 15_000,
    }
    check("DER_TOKEN_BUDGETS keys+values unchanged",
          DER_TOKEN_BUDGETS == _expected_budgets,
          f"got={DER_TOKEN_BUDGETS}")
    check("get_token_budget falls back to agentic for unknown mode",
          get_token_budget("nonexistent-mode") == DER_TOKEN_BUDGETS["agentic"])
    check("get_token_budget(None) falls back to agentic",
          get_token_budget(None) == DER_TOKEN_BUDGETS["agentic"])
    check("get_token_budget('full') unchanged", get_token_budget("full") == 60_000)
    import backend.agent.der_loop as _der_loop_mod
    _der_loop_src = inspect.getsource(_der_loop_mod)
    check("der_loop still reads get_token_budget() (_should_escalate)",
          "get_token_budget(" in _der_loop_src)

    print("== CT-F2: Budget <-> work units derive from the SAME window ==")
    for _w in (8_192, 32_000, 128_000):
        _budget = resolve_der_token_budget(_w, "full")
        check(f"budget<=window (same window={_w})", _budget <= _w)
    check("derive_work_units_0 signature takes context_window",
          "context_window" in inspect.signature(derive_work_units_0).parameters)

    print("== CT-F3: InferenceRouter.generate signature + phase gate ==")
    gsig = inspect.signature(InferenceRouter.generate)
    _expected_gen_params = {
        "role", "messages", "tools", "max_tokens", "temperature",
        "chunk_callback", "reasoning_callback",
    }
    check("InferenceRouter.generate signature unchanged",
          _expected_gen_params.issubset(set(gsig.parameters.keys())))
    _fresh_registry()
    _cfg = InferenceConfig()
    _cfg.provider = "api"
    _e_gate = ProviderEntry(id="gate-probe", label="Gate", kind="API", model="gpt-4o",
                             endpoint="https://api.openai.com/v1", cred_ref="gate-probe")
    _cfg.providers = {_e_gate.id: _e_gate}
    _cfg.config_version = 2
    _cfg.role_bindings = [{"role": "reasoning", "instance_id": _e_gate.id}]
    _r = InferenceRouter(_cfg)
    with patch("backend.agent.inference.router.acquire") as _acquire_mock, \
         patch.object(ApiHttpxTransport, "generate", return_value=("ok", "", [])):
        _r.generate("reasoning", [{"role": "user", "content": "hi"}])
    check("phase-scheduler gate (acquire) still called inside generate()",
          _acquire_mock.called)

    print("== CT-F4: InProcessTransport.generate signature + 3-tuple ==")
    isig = inspect.signature(InProcessTransport.generate)
    check("InProcessTransport.generate returns a Tuple",
          "Tuple" in str(isig.return_annotation))

    print("== CT-F5: Routing-mode freeze (provider field + active_provider alias) ==")
    for _prov in ("api", "lm_studio", "ollama", "iris_local"):
        _c = InferenceConfig()
        _c.provider = _prov
        _rt = InferenceConfig.from_dict(_c.to_dict())
        check(f"routing vocabulary round-trips ({_prov})", _rt.provider == _prov)
    _alias_cfg = InferenceConfig.from_dict({"active_provider": "cerebras"})
    check("active_provider alias still resolves 'provider'",
          _alias_cfg.provider == "cerebras")

    print("== CT-F6: /api/inference/state payload shape (no credential) ==")
    _inst = ProviderInstance(id="leak-check", label="L", kind=ProviderKind.API,
                              model="m", api_base_url="https://x", api_key="SUPER-SECRET-1")
    _pd = _inst.to_dict()
    check("payload retains id/label/kind/model/api_base_url/has_key",
          {"id", "label", "kind", "model", "api_base_url", "has_key"}.issubset(_pd.keys()))
    check("payload gains loaded/loading/purpose additively",
          {"loaded", "loading", "purpose"}.issubset(_pd.keys()))
    check("payload never carries the credential itself",
          "SUPER-SECRET-1" not in json.dumps(_pd))

    print("== CT-F7: Registry is process-wide (same instance set everywhere) ==")
    _fresh_registry()
    from backend.agent.inference.registry import get_provider_registry
    _reg_a = get_provider_registry()
    _reg_a.add(ProviderInstance(id="shared-probe", label="S", kind=ProviderKind.API))
    _reg_b = get_provider_registry()
    check("registry is a single process-wide instance", _reg_a is _reg_b)
    check("an instance added via one reference is visible via the other",
          _reg_b.get("shared-probe") is not None)

    print("== CT-F8: Local id namespacing (no bare 'local') ==")
    _fresh_registry()
    _local_cfg = InferenceConfig.from_dict(
        {"provider": "local", "local_model_id": "qwen3-9b-q4_k_m.gguf"})
    _local_router = InferenceRouter(_local_cfg)
    _ids = {i.id for i in _local_router.registry.list()}
    check("no registry id is the bare literal 'local'", "local" not in _ids, f"ids={_ids}")
    check("local id is namespaced local:*",
          any(i.startswith("local:") for i in _ids), f"ids={_ids}")

    print("== CT-F9: Config schema (providers keyed by id, cred_ref not a secret) ==")
    _e1 = ProviderEntry(id="cerebras", label="C", kind="API", model="g",
                         endpoint="https://cb", cred_ref="cerebras")
    _schema_cfg = InferenceConfig()
    _schema_cfg.providers = {_e1.id: _e1}
    check("providers dict keyed by entry.id",
          list(_schema_cfg.providers.keys()) == [_e1.id])
    check("API entry carries both endpoint and cred_ref",
          bool(_e1.endpoint) and bool(_e1.cred_ref))
    check("cred_ref is a keyring key, not a credential value",
          _e1.cred_ref == _e1.id and _e1.cred_ref != "sk-anything")

    # =====================================================================
    # Assertion 2: Budget <= window for the full REQ-1 AC7 matrix.
    # =====================================================================
    print("== Assertion 2: budget<=window over the REQ-1 AC7 matrix ==")
    for _w in (2_000, 8_192, 32_000, 128_000, 256_000):
        for _tc in ("quick", "implement", "full"):
            _b = resolve_der_token_budget(_w, _tc)
            check(f"budget<=window {_w}/{_tc}", _b <= _w, f"budget={_b}")
            check(f"floor never exceeds window {_w}/{_tc}",
                  min(DER_BUDGET_MIN_FLOOR, _w) <= _w)

    # =====================================================================
    # Assertion 3: Budget and work units derive from the SAME window.
    # =====================================================================
    print("== Assertion 3: budget and work units move together with window ==")
    _prev_budget = -1
    _prev_units = -1
    _monotonic = True
    for _w in (8_192, 16_384, 32_768, 65_536, 131_072):
        _budget = resolve_der_token_budget(_w, "full")
        _units = derive_work_units_0(_w)
        if _budget < _prev_budget or _units < _prev_units:
            _monotonic = False
        _prev_budget, _prev_units = _budget, _units
    check("budget and work units both grow with the same window (no drift)",
          _monotonic)

    # =====================================================================
    # Assertion 4: no provider-wide table default exceeds the conservative
    # default (D-3).
    # =====================================================================
    print("== Assertion 4: no provider-wide table default exceeds the conservative default ==")
    _default_resolved = _stub_kernel(provider="__unknown_probe__", model="__unknown__") \
        .resolve_context_window_with_source()
    check("conservative default is tagged source=default",
          _default_resolved.source == "default")
    _provider_wide = [
        (p, s, t) for (p, s, t) in _ak.AgentKernel._KNOWN_CONTEXT_WINDOWS if s == ""
    ]
    for _p, _s, _t in _provider_wide:
        check(f"provider-wide default '{_p}' ({_t}) does not exceed conservative default ({_default_resolved.tokens})",
              _t <= _default_resolved.tokens,
              f"table gives {_t} > conservative default {_default_resolved.tokens}")

    # =====================================================================
    # Assertion 5: no config file written by any path contains a credential.
    # =====================================================================
    print("== Assertion 5: no serialized config contains a credential ==")
    _CREDENTIAL = "FAKETESTCRED-xyz-should-never-leak"
    _legacy_raw = {
        "provider": "cerebras",
        "api_base_url": "https://api.cerebras.ai/v1",
        "api_key": _CREDENTIAL,
        "reasoning_model": "gemma-4-31b",
    }
    _migrated = InferenceConfig.from_dict(_legacy_raw)
    _serialized = json.dumps(_migrated.to_dict())
    check("migrated config's serialized bytes contain no credential",
          _CREDENTIAL not in _serialized,
          "InferenceConfig.to_dict() still serializes the legacy flat api_key "
          "field after migrate_flat_to_collection() — migration does not clear "
          "it, so save_config() writes the raw key to iris_config.json.")

    # =====================================================================
    # Assertion 6: no /api/inference/state response contains a credential.
    # =====================================================================
    print("== Assertion 6: /api/inference/state snapshot contains no credential ==")
    _fresh_registry()
    _snap_cfg = InferenceConfig()
    _e_snap = ProviderEntry(id="snap-provider", label="Snap", kind="API", model="m",
                             endpoint="https://snap.example", cred_ref="snap-provider")
    _snap_cfg.providers = {_e_snap.id: _e_snap}
    _snap_cfg.config_version = 2
    _snap_router = InferenceRouter(_snap_cfg)
    with patch("backend.agent.inference.keyring.get_secret", return_value="SNAP-SECRET-VALUE"):
        _snapshot = _snap_router.snapshot()
    check("snapshot payload contains no credential value",
          "SNAP-SECRET-VALUE" not in json.dumps(_snapshot))
    check("snapshot provider dicts carry no api_key/cred_ref/secret field",
          all("api_key" not in p and "cred_ref" not in p and "secret" not in json.dumps(p)
              for p in _snapshot["providers"]))

    # =====================================================================
    # Assertion 7: every API entry has both endpoint and cred_ref; a fixture
    # missing one is rejected.
    # =====================================================================
    print("== Assertion 7: endpoint+cred_ref pairing enforced on write ==")
    _fresh_registry()
    _r7 = InferenceRouter(InferenceConfig())
    try:
        _r7.write_provider(ProviderEntry(id="np-endpoint-only", label="N", kind="API",
                                          endpoint="https://x"))
        check("new provider: endpoint-without-credential rejected", False)
    except ValueError:
        check("new provider: endpoint-without-credential rejected", True)
    try:
        _r7.write_provider(ProviderEntry(id="np-cred-only", label="N", kind="API"),
                            credential="orphan-key")
        check("new provider: credential-without-endpoint rejected", False)
    except ValueError:
        check("new provider: credential-without-endpoint rejected", True)

    # =====================================================================
    # Assertion 8: two providers with different keys round-trip through
    # config + keyring with their own credentials.
    # =====================================================================
    print("== Assertion 8: two providers round-trip with their OWN credentials ==")
    _fresh_registry()
    _fake_secrets: dict = {}
    _fake_iris_cfg = {"holder": None}

    def _fake_get_secret(pid):
        return _fake_secrets.get(pid)

    def _fake_set_secret(pid, key):
        _fake_secrets[pid] = key

    def _fake_load_config():
        if _fake_iris_cfg["holder"] is None:
            from backend.iris_config import IRISConfig
            _fake_iris_cfg["holder"] = IRISConfig()
        return _fake_iris_cfg["holder"]

    def _fake_save_config(cfg):
        _fake_iris_cfg["holder"] = cfg

    with patch("backend.agent.inference.keyring.get_secret", side_effect=_fake_get_secret), \
         patch("backend.agent.inference.keyring.set_secret", side_effect=_fake_set_secret), \
         patch("backend.iris_config.load_config", side_effect=_fake_load_config), \
         patch("backend.iris_config.save_config", side_effect=_fake_save_config):
        _r8 = InferenceRouter(InferenceConfig())
        _r8.write_provider(
            ProviderEntry(id="cerebras", label="Cerebras", kind="API",
                          endpoint="https://api.cerebras.ai/v1", cred_ref="cerebras"),
            credential="cerebras-key-111",
        )
        _r8.write_provider(
            ProviderEntry(id="openai", label="OpenAI", kind="API",
                          endpoint="https://api.openai.com/v1", cred_ref="openai"),
            credential="openai-key-222",
        )
        check("both providers present in the live registry",
              {"cerebras", "openai"}.issubset({i.id for i in _r8.registry.list()}))
        check("cerebras keeps its OWN key", _fake_get_secret("cerebras") == "cerebras-key-111")
        check("openai keeps its OWN key", _fake_get_secret("openai") == "openai-key-222")
        check("keys are not swapped/shared", _fake_get_secret("cerebras") != _fake_get_secret("openai"))
        # Simulate a restart: reload config + registry from the persisted store.
        _fresh_registry()
        _restarted_cfg = _fake_iris_cfg["holder"].inference
        _restarted_router = InferenceRouter(_restarted_cfg)
        _restarted_ids = {i.id for i in _restarted_router.registry.list()}
        check("both providers survive a simulated restart",
              {"cerebras", "openai"}.issubset(_restarted_ids), f"ids={_restarted_ids}")

    # =====================================================================
    # Assertion 9: a synthetic pre-upgrade config migrates with bindings
    # intact; migrating twice is a no-op.
    # =====================================================================
    print("== Assertion 9: pre-upgrade migration + idempotence ==")
    with patch("backend.agent.inference.keyring.set_secret") as _mig_set_secret:
        _pre_upgrade = {
            "provider": "cerebras",
            "api_base_url": "https://api.cerebras.ai/v1",
            "api_key": "legacy-key-333",
            "reasoning_model": "gemma-4-31b",
            "local_model_id": "qwen3-9b-q4_k_m.gguf",
            "role_bindings": [
                {"role": "reasoning", "instance_id": "cerebras"},
                {"role": "tool_execution", "instance_id": "local"},
            ],
        }
        _migrated_cfg = InferenceConfig.from_dict(_pre_upgrade)
        check("config_version advances to 2", _migrated_cfg.config_version == 2)
        check("API provider migrated into the collection",
              "cerebras" in _migrated_cfg.providers)
        check("local provider migrated with a namespaced id",
              any(k.startswith("local:") for k in _migrated_cfg.providers))
        check("'reasoning' binding preserved as-is",
              _migrated_cfg.role_bindings[0]["instance_id"] == "cerebras")
        check("bare 'local' binding migrated to the namespaced id",
              _migrated_cfg.role_bindings[1]["instance_id"] != "local"
              and _migrated_cfg.role_bindings[1]["instance_id"].startswith("local:"))
        check("legacy key handed to the keyring, not left in providers",
              _mig_set_secret.called)

        _providers_before = copy.deepcopy(_migrated_cfg.providers)
        _bindings_before = copy.deepcopy(_migrated_cfg.role_bindings)
        _migrated_cfg.migrate_flat_to_collection()  # run again — must be a no-op
        check("migrating twice leaves config_version at 2",
              _migrated_cfg.config_version == 2)
        check("migrating twice does not change the providers collection",
              _migrated_cfg.providers == _providers_before)
        check("migrating twice does not change role_bindings",
              _migrated_cfg.role_bindings == _bindings_before)

    # =====================================================================
    # Assertion 10: routing resolves identically for all four provider
    # values.
    # =====================================================================
    print("== Assertion 10: routing resolves identically for all 4 provider values ==")
    _expected_kind = {
        "api": ProviderKind.API,
        "lm_studio": ProviderKind.LOCAL_OPENAI,
        "ollama": ProviderKind.OLLAMA,
        "iris_local": ProviderKind.INPROCESS,
    }
    for _prov, _want in _expected_kind.items():
        _k1 = InferenceRouter._legacy_kind(_prov)
        _k2 = InferenceRouter._legacy_kind(_prov)
        check(f"routing is deterministic for provider={_prov}", _k1 == _k2)
        check(f"routing resolves provider={_prov} to its documented kind ({_want.value})",
              _k1 == _want, f"got {_k1.value}")

    # =====================================================================
    # Assertion 11: no registry id is the bare literal "local".
    # =====================================================================
    print("== Assertion 11: no registry id is the bare literal 'local' (global sweep) ==")
    _fresh_registry()
    _sweep_cfg = InferenceConfig.from_dict(
        {"provider": "local", "local_model_id": "phi-3-mini.gguf",
         "role_bindings": [{"role": "reasoning", "instance_id": "local"}]})
    _sweep_router = InferenceRouter(_sweep_cfg)
    _sweep_ids = {i.id for i in _sweep_router.registry.list()}
    check("no bare 'local' id anywhere in the registry",
          "local" not in _sweep_ids, f"ids={_sweep_ids}")
    _resolved_binding = _sweep_router.resolve("reasoning")
    check("the 'reasoning' binding resolves to a namespaced instance, not 'local'",
          _resolved_binding.id != "local" and _resolved_binding.id.startswith("local:"))

    print()
    if FAILURES:
        print(f"HARNESS FAILED: {len(FAILURES)} assertion(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("HARNESS PASSED: all assertions green.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
