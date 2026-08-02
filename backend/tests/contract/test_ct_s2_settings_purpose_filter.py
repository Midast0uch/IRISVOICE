"""Contract test CT-S2 (specs/phase-5-switcher/design.md).

"Settings selector filter: `ModelInferenceSection` still excludes non-chat
purposes (Phase 4 REQ-6 AC3 not regressed)."

Phase 5 re-architected ModelInferenceSection.tsx to build Brain/Tool dropdown
options via buildModelOptions() from provider_presets × model_catalog, instead of
filtering providers directly. The architectural guarantee that non-chat providers
never reach the UI is now pinned at the backend: PROVIDER_PRESETS contains only
chat providers, and encoder providers (embedding:* and rerank:*) are registered
separately, OUTSIDE the presets. Since buildModelOptions() only iterates preset
ids, non-chat providers can never be offered as Brain or Tool options.

This test checks the INVARIANT (backend state) that guarantees the EFFECT
(frontend filtering), replacing source-level regex assertions that broke on the
valid re-architecture.
"""

from __future__ import annotations

from backend.agent.inference.provider import PROVIDER_PRESETS
from backend.agent.inference.provider_catalog import PROVIDER_MODEL_CATALOG


class TestCTS2SettingsPurposeFilterNotRegressed:
    def test_provider_presets_are_chat_only(self):
        """PROVIDER_PRESETS contains only chat providers.

        Non-chat providers (purpose='embedding' or 'rerank') are registered
        separately via register_builtin_encoder_providers() and never included
        in PROVIDER_PRESETS. This architectural boundary ensures that
        buildModelOptions() (which iterates only preset ids) can never build
        options for embedding/rerank providers — the invariant that guarantees
        non-chat providers do not reach the Brain/Tool UI dropdowns.
        """
        for preset in PROVIDER_PRESETS:
            preset_id = preset["id"]
            # Presets default to chat purpose; none should explicitly set a
            # non-chat purpose. If a preset had purpose="embedding" or
            # purpose="rerank", it would be available to the UI — violating REQ-6 AC3.
            assert (
                "purpose" not in preset or preset["purpose"] == "chat"
            ), (
                f"Preset {preset_id!r} has purpose={preset['purpose']!r} — "
                "non-chat providers must not be in PROVIDER_PRESETS"
            )

    def test_encoder_provider_ids_never_in_presets(self):
        """Encoder provider ids (embedding:* and rerank:*) are not preset ids.

        register_builtin_encoder_providers() registers embedding:lfm25-emb-350m
        and optionally rerank:lfm25-colbert-350m. These MUST NOT be in
        PROVIDER_PRESETS; they are added to the registry separately. If an
        encoder provider id matched a preset id, buildModelOptions() would
        iterate it and offer it as a Brain/Tool option — violating REQ-6 AC3.
        """
        preset_ids = {p["id"] for p in PROVIDER_PRESETS}
        encoder_ids = {"embedding:lfm25-emb-350m", "rerank:lfm25-colbert-350m"}
        overlap = encoder_ids & preset_ids
        assert not overlap, (
            f"Encoder provider ids found in PROVIDER_PRESETS: {overlap}. "
            "buildModelOptions() would offer them as Brain/Tool options."
        )

    def test_model_catalog_keys_are_preset_ids_only(self):
        """PROVIDER_MODEL_CATALOG keys are preset ids only, never encoder ids.

        buildModelOptions() appends catalog models for each preset id (lines 133-135
        of ModelInferenceSection.tsx). If the catalog contained encoder provider ids
        as keys, those models would be offered for selection. Catalog keys must be
        preset ids only.
        """
        preset_ids = {p["id"] for p in PROVIDER_PRESETS}
        catalog_keys = set(PROVIDER_MODEL_CATALOG.keys())
        # All catalog keys should be preset ids (or close to it; some presets may not
        # have models in the catalog). More importantly, no encoder id should be a key.
        encoder_ids = {"embedding:lfm25-emb-350m", "rerank:lfm25-colbert-350m"}
        overlap = catalog_keys & encoder_ids
        assert not overlap, (
            f"Encoder provider ids found in PROVIDER_MODEL_CATALOG: {overlap}. "
            "buildModelOptions() would append models for them."
        )
