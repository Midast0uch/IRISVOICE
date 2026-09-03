"""Contract: a loaded local model is visible to every model-picking surface.

Reported 2026-08-13: "when I load a local model it doesn't show in the local
model card as loaded or in the dropdown list, same for model and inference
card" — while GPU memory demonstrably rose on load and fell on unload, so the
model WAS resident. The break was entirely on the reporting path.

Both UI filters that gate a local provider read ``loaded``:

    ModelSwitcher.tsx      isApiKind(p.kind) ? !!p.has_key : !!p.loaded
    ModelInferenceSection  purpose === "chat"  (+ instance must be listed)

so ``loaded`` missing from a payload is indistinguishable from "not loaded".
The load path used to broadcast a hand-picked subset of the provider fields
(id/label/kind/model/api_base_url) which omitted it.

This pins the payload boundary, not the UI: whatever a local provider is
broadcast or snapshotted as, it must carry the field the filters read.
"""

from __future__ import annotations

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.snapshot import build_inference_snapshot


def _loaded_local_instance() -> ProviderInstance:
    """What iris_gateway registers on a successful local load."""
    return ProviderInstance(
        id="local:TwIL-LM3-Q4_K_M",
        label="Local: TwIL-LM3-Q4_K_M.gguf",
        kind=ProviderKind.LOCAL_OPENAI,
        model="TwIL-LM3-Q4_K_M",
        api_base_url="http://127.0.0.1:8091/v1",
        loaded=True,
    )


def _router_with(*instances) -> InferenceRouter:
    reg = ProviderRegistry()
    for inst in instances:
        reg.add(inst)
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


def _switcher_admits(p: dict) -> bool:
    """Port of the ModelSwitcher.tsx `entries` filter (REQ-2 AC2/AC3/AC4)."""
    if p.get("purpose") not in (None, "chat"):
        return False
    if (p.get("kind") or "").lower() == "api":
        return bool(p.get("has_key"))
    return bool(p.get("loaded"))


class TestLocalProviderPayload:
    def test_provider_added_payload_carries_loaded(self):
        """The broadcast payload IS to_dict() — not a hand-picked subset."""
        payload = _loaded_local_instance().to_dict()
        assert "loaded" in payload, (
            "the load broadcast dropped `loaded`; the ModelSwitcher filter reads "
            "it and treats absent as false"
        )
        assert payload["loaded"] is True
        # The other two fields the filters read must ride along too.
        assert payload["purpose"] == "chat"
        assert payload["kind"] == "local_openai"

    def test_a_loaded_local_provider_passes_the_switcher_filter(self):
        assert _switcher_admits(_loaded_local_instance().to_dict()) is True

    def test_a_partial_payload_without_loaded_is_rejected_by_the_filter(self):
        """Why the subset broke it — stated as an executable fact, not prose."""
        subset = {
            "id": "local:TwIL-LM3-Q4_K_M",
            "label": "Local: TwIL-LM3-Q4_K_M.gguf",
            "kind": "local_openai",
            "model": "TwIL-LM3-Q4_K_M",
            "api_base_url": "http://127.0.0.1:8091/v1",
        }
        assert _switcher_admits(subset) is False

    def test_snapshot_exposes_the_loaded_local_provider(self):
        """A full-snapshot re-sync must also show it — that is the resync path."""
        snap = build_inference_snapshot(_router_with(_loaded_local_instance()))
        local = next(
            p for p in snap["providers"] if p["id"] == "local:TwIL-LM3-Q4_K_M"
        )
        assert local["loaded"] is True
        assert _switcher_admits(local) is True

    def test_no_credential_field_survives_on_a_local_provider(self):
        """The scrub still applies — this path must not become a leak."""
        snap = build_inference_snapshot(_router_with(_loaded_local_instance()))
        local = snap["providers"][0]
        for forbidden in ("api_key", "cred_ref", "secret", "key"):
            assert forbidden not in local


class TestLocalProviderRemoval:
    def test_unload_target_ids_are_namespaced_not_the_bare_literal(self):
        """Unload used to remove ``"local"``, which is never what is registered.

        REQ-4 AC1 namespaces local ids as ``local:<stem>``, so removing the bare
        literal was a no-op and an unloaded model stayed in the registry with
        ``loaded=True`` — still offered in every dropdown after its VRAM was
        released.
        """
        router = _router_with(
            _loaded_local_instance(),
            ProviderInstance(id="cerebras", label="Cerebras",
                             kind=ProviderKind.API, model="gemma-4-31b"),
        )
        # The selection the unload handler makes.
        local_ids = [
            i.id for i in router.registry.list()
            if i.id == "local" or i.id.startswith("local:")
        ]
        assert local_ids == ["local:TwIL-LM3-Q4_K_M"], (
            "the unload handler must target the namespaced id it registered"
        )

        for lid in local_ids:
            router.remove_provider(lid)

        remaining = {i.id for i in router.registry.list()}
        assert "local:TwIL-LM3-Q4_K_M" not in remaining
        assert "cerebras" in remaining, "unload must not touch other providers"
