"""
Unit tests for backend/agent/inference/provider_catalog.py
"""

from backend.agent.inference.provider_catalog import (
    PROVIDER_MODEL_CATALOG,
    get_catalog_for_provider,
)
from backend.agent.inference.provider import PROVIDER_PRESETS


def test_provider_catalog_contains_expected_providers():
    assert "venice" in PROVIDER_MODEL_CATALOG
    assert "opencodego" in PROVIDER_MODEL_CATALOG
    assert "deepseek" in PROVIDER_MODEL_CATALOG
    assert "cerebras" in PROVIDER_MODEL_CATALOG
    assert "openai" in PROVIDER_MODEL_CATALOG


def test_venice_catalog_models_includes_inkling_and_terra():
    venice_models = get_catalog_for_provider("venice")
    model_ids = [m["id"] for m in venice_models]
    assert "inkling" in model_ids
    assert "gpt-5.6-terra-pro" in model_ids
    assert "terra" in model_ids
    assert "deepseek-r1-671b" in model_ids


def test_opencodego_catalog_models_includes_luna_and_kimi_k3():
    oc_models = get_catalog_for_provider("opencodego")
    model_ids = [m["id"] for m in oc_models]
    assert "gpt-5.6-luna" in model_ids
    assert "luna" in model_ids
    assert "kimi-k3" in model_ids
    assert "deepseek-v4-pro" in model_ids


def test_deepseek_catalog_models_includes_v4():
    ds_models = get_catalog_for_provider("deepseek")
    model_ids = [m["id"] for m in ds_models]
    assert "deepseek-v4" in model_ids
    assert "deepseek-v4-flash" in model_ids
    assert "deepseek-v4-pro" in model_ids
    assert "deepseek-reasoner" in model_ids


def test_get_catalog_for_unknown_provider():
    assert get_catalog_for_provider("nonexistent_provider_123") == []
    assert get_catalog_for_provider(None) == []


def test_provider_presets_includes_venice():
    venice_preset = next((p for p in PROVIDER_PRESETS if p["id"] == "venice"), None)
    assert venice_preset is not None
    assert venice_preset["label"] == "Venice AI"
    assert venice_preset["api_base_url"] == "https://api.venice.ai/api/v1"
