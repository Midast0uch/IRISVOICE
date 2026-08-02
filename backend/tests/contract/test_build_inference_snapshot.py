"""Contract test for `backend.agent.inference.snapshot.build_inference_snapshot`.

Pins the FULL payload shape every emission site (REST `/api/inference/state`
and both WS `role_bindings_updated` broadcasts) must now share: providers,
role_bindings, default_role, provider_presets, model_catalog. Asserts the
KEYS and that `model_catalog` is genuinely non-empty when
`PROVIDER_MODEL_CATALOG` is non-empty — not merely that the function ran —
and that the credential-scrub chokepoint (`has_key` crosses as a bool ONLY)
holds even if an upstream `ProviderInstance.to_dict()` were to regress.
"""

from __future__ import annotations

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.provider_catalog import PROVIDER_MODEL_CATALOG
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.snapshot import build_inference_snapshot


def _make_router() -> InferenceRouter:
    reg = ProviderRegistry()
    reg.add(ProviderInstance(id="cerebras", label="Cerebras", kind=ProviderKind.API,
                              model="gemma-4-31b", api_base_url="https://api.cerebras.ai/v1",
                              api_key="FAKETESTCRED-live-abcdef0123456789"))
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


class TestBuildInferenceSnapshot:
    def test_returns_all_required_top_level_keys(self):
        snap = build_inference_snapshot(_make_router())
        for key in ("providers", "role_bindings", "default_role",
                    "provider_presets", "model_catalog"):
            assert key in snap, f"build_inference_snapshot missing key: {key}"

    def test_model_catalog_is_non_empty_when_the_real_catalog_is_non_empty(self):
        assert PROVIDER_MODEL_CATALOG, "test precondition: real catalog must be non-empty"
        snap = build_inference_snapshot(_make_router())
        assert snap["model_catalog"], "model_catalog must not be empty/blank"
        assert snap["model_catalog"] == PROVIDER_MODEL_CATALOG

    def test_provider_presets_is_the_real_presets_list(self):
        from backend.agent.inference.provider import PROVIDER_PRESETS

        snap = build_inference_snapshot(_make_router())
        assert snap["provider_presets"] == PROVIDER_PRESETS
        assert len(snap["provider_presets"]) > 0

    def test_router_snapshot_shape_is_unwidened(self):
        """CT-F6 (test_phase1_foundation_contracts.py::test_snapshot_payload_shape)
        pins InferenceRouter.snapshot()'s OWN return shape. This builder must
        WRAP that call, not grow it — router.snapshot() must still return
        exactly {providers, role_bindings, default_role} with nothing else."""
        router = _make_router()
        raw = router.snapshot()
        assert set(raw.keys()) == {"providers", "role_bindings", "default_role"}, (
            f"InferenceRouter.snapshot() shape changed: {sorted(raw.keys())} — "
            f"this must stay narrow; build_inference_snapshot is where new "
            f"fields belong"
        )

    def test_no_credential_or_fragment_reaches_the_wrapped_payload(self):
        """Single chokepoint for the has_key-crosses-as-boolean-only invariant
        (scripts/validate_switcher.py assertion 2, CT-S4)."""
        snap = build_inference_snapshot(_make_router())
        cerebras = next(p for p in snap["providers"] if p["id"] == "cerebras")
        assert isinstance(cerebras["has_key"], bool)
        assert cerebras["has_key"] is True
        assert "api_key" not in cerebras
        assert "cred_ref" not in cerebras
        assert "FAKETESTCRED" not in str(snap)

    def test_none_router_still_returns_the_full_key_set(self):
        """The REST endpoint calls this with router=None when no kernel/router
        exists yet — it must still return the full shape (empty collections),
        not a partial/narrower dict, so the frontend's field-wise merge never
        sees an inconsistent shape depending on startup timing."""
        snap = build_inference_snapshot(None)
        for key in ("providers", "role_bindings", "default_role",
                    "provider_presets", "model_catalog"):
            assert key in snap
        assert snap["providers"] == []
        assert snap["role_bindings"] == []
