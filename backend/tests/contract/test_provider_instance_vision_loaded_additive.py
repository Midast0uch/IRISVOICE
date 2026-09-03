"""Contract: `ProviderInstance.vision_loaded` is additive (specs/unified-
vision-routing T2, REQ-1).

`vision_loaded` records whether a projector was ACTUALLY attached at load
time for a LOCAL_OPENAI/INPROCESS provider — never inferred from a sibling
`mmproj-*.gguf` merely existing on disk (REQ-1 AC3). This field is populated
by T8's loader; T2 only adds the field and its default. These tests pin that
the addition does not widen or break any existing consumer:

- `test_build_inference_snapshot.py` and
  `test_local_provider_visible_when_loaded.py` already guard the payload
  shape and must keep passing UNCHANGED (not re-derived here).
- This file covers what those two do not reach: the field's default, its
  presence/value on `to_dict()`, and that it survives a full
  `build_inference_snapshot()` round trip for both a vision-capable and a
  non-vision local provider.
"""

from __future__ import annotations

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.snapshot import build_inference_snapshot


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


class TestVisionLoadedDefault:
    def test_defaults_to_false_when_unspecified(self):
        inst = ProviderInstance(
            id="local:some-model", label="Local", kind=ProviderKind.LOCAL_OPENAI,
            model="some-model",
        )
        assert inst.vision_loaded is False

    def test_to_dict_carries_vision_loaded_key(self):
        inst = ProviderInstance(
            id="local:some-model", label="Local", kind=ProviderKind.LOCAL_OPENAI,
            model="some-model",
        )
        payload = inst.to_dict()
        assert "vision_loaded" in payload
        assert payload["vision_loaded"] is False

    def test_to_dict_reflects_true_when_projector_was_attached(self):
        inst = ProviderInstance(
            id="local:gemma-4-E4B", label="Local: gemma-4-E4B", kind=ProviderKind.INPROCESS,
            model="gemma-4-E4B", loaded=True, vision_loaded=True,
        )
        payload = inst.to_dict()
        assert payload["vision_loaded"] is True
        # Additive: existing fields still ride along unchanged.
        assert payload["loaded"] is True
        assert payload["kind"] == "inprocess"


class TestVisionLoadedIsAdditiveAcrossExistingConsumers:
    """The two files this task must not modify already pin `to_dict()`'s
    KNOWN keys exist and are correctly typed — they do not assert the KEY
    SET is closed, so a new additive key cannot fail them. These tests prove
    that directly, from THIS file, without touching those two."""

    def test_existing_guarded_keys_are_unaffected_by_the_new_field(self):
        inst = ProviderInstance(
            id="local:TwIL-LM3-Q4_K_M", label="Local: TwIL-LM3-Q4_K_M.gguf",
            kind=ProviderKind.LOCAL_OPENAI, model="TwIL-LM3-Q4_K_M",
            api_base_url="http://127.0.0.1:8091/v1", loaded=True,
        )
        payload = inst.to_dict()
        assert payload["loaded"] is True
        assert payload["purpose"] == "chat"
        assert payload["kind"] == "local_openai"
        assert payload["vision_loaded"] is False

    def test_no_credential_field_survives_alongside_the_new_field(self):
        """The scrub chokepoint must still hold even with the new key present."""
        inst = ProviderInstance(
            id="cerebras", label="Cerebras", kind=ProviderKind.API,
            model="gemma-4-31b", api_key="FAKETESTCRED-live-abcdef0123456789",
        )
        payload = inst.to_dict()
        assert payload["vision_loaded"] is False
        for forbidden in ("api_key", "cred_ref", "secret"):
            assert forbidden not in payload

    def test_snapshot_round_trip_carries_vision_loaded_for_a_vision_capable_local_provider(self):
        inst = ProviderInstance(
            id="local:gemma-4-E4B", label="Local: gemma-4-E4B",
            kind=ProviderKind.LOCAL_OPENAI, model="gemma-4-E4B",
            api_base_url="http://127.0.0.1:8082/v1", loaded=True, vision_loaded=True,
        )
        snap = build_inference_snapshot(_router_with(inst))
        provider = next(p for p in snap["providers"] if p["id"] == "local:gemma-4-E4B")
        assert provider["vision_loaded"] is True
        assert provider["loaded"] is True

    def test_snapshot_round_trip_defaults_false_for_a_text_only_local_provider(self):
        inst = ProviderInstance(
            id="local:TwIL-LM3-Q4_K_M", label="Local: TwIL-LM3-Q4_K_M.gguf",
            kind=ProviderKind.LOCAL_OPENAI, model="TwIL-LM3-Q4_K_M",
            api_base_url="http://127.0.0.1:8091/v1", loaded=True,
        )
        snap = build_inference_snapshot(_router_with(inst))
        provider = next(p for p in snap["providers"] if p["id"] == "local:TwIL-LM3-Q4_K_M")
        assert provider["vision_loaded"] is False
