"""CT-E7 — Provider registration for the LFM2.5 encoders (REQ-6 AC1/AC2/AC4).

Both encoders register as CPU, non-chat local providers and are NOT bindable to
reasoning / tool_execution roles.
"""
import os

import pytest


def test_embedding_provider_registered_with_purpose():
    from backend.agent.inference.provider import register_builtin_encoder_providers
    from backend.agent.inference.registry import get_provider_registry
    from backend.agent.local_model_manager import resolve_device_policy

    register_builtin_encoder_providers()
    reg = get_provider_registry()

    emb = reg.get("embedding:lfm25-emb-350m")
    assert emb is not None, "Embedding-350M provider must be registered"
    assert emb.purpose == "embedding"

    # Device policy resolves to CPU, empty ladder, no VRAM accounting (Phase 3).
    pol = resolve_device_policy("embedding")
    assert pol.device == "cpu"
    assert pol.counts_against_vram is False
    assert pol.throughput_target is None
    assert pol.ladder == ()


def test_encoder_provider_not_bindable_to_chat_roles():
    from backend.agent.inference.provider import register_builtin_encoder_providers
    from backend.agent.inference.roles import get_role_binding_table

    register_builtin_encoder_providers()
    roles = get_role_binding_table()
    bound_ids = {b.instance_id for b in roles.list()}
    assert "embedding:lfm25-emb-350m" not in bound_ids


def test_colbert_registration_gated():
    from backend.agent.inference.provider import register_builtin_encoder_providers
    from backend.agent.inference.registry import get_provider_registry

    # Default: ColBERT NOT registered (deferred behind quality gate, REQ-7 AC6).
    os.environ.pop("IRIS_ENABLE_COLBERT", None)
    register_builtin_encoder_providers()
    reg = get_provider_registry()
    assert reg.get("rerank:lfm25-colbert-350m") is None

    # Enabled: registered with purpose=rerank.
    os.environ["IRIS_ENABLE_COLBERT"] = "1"
    try:
        register_builtin_encoder_providers()
        colbert = reg.get("rerank:lfm25-colbert-350m")
        assert colbert is not None
        assert colbert.purpose == "rerank"
    finally:
        os.environ.pop("IRIS_ENABLE_COLBERT", None)
