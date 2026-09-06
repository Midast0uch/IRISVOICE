"""Unit tests for vision capability + cost tiering (REQ-16/REQ-17, T6)."""

from backend.inference_router import (
    VISION_TIER_LATENCY_MS,
    VisionTier,
    has_vision_capability,
    route_vision_tier,
)


def test_clean_dom_routes_tier_0():
    """AC16.2: straightforward structures stay on free headless HTTP."""
    assert route_vision_tier() is VisionTier.TIER_0_HTTP
    assert route_vision_tier(needs_interaction=False,
                             high_ambiguity=False) is VisionTier.TIER_0_HTTP


def test_interactive_pages_route_tier_1_when_local_available():
    assert route_vision_tier(needs_interaction=True,
                             local_vision=True) is VisionTier.TIER_1_LOCAL_VLM


def test_interactive_pages_fall_back_to_tier_2_without_local_vision():
    assert route_vision_tier(needs_interaction=True,
                             local_vision=False) is VisionTier.TIER_2_CLOUD


def test_high_ambiguity_routes_tier_2_regardless():
    """AC16.1: cloud multimodal only for high-ambiguity visual reasoning."""
    assert route_vision_tier(high_ambiguity=True,
                             local_vision=True) is VisionTier.TIER_2_CLOUD
    assert route_vision_tier(needs_interaction=True, high_ambiguity=True,
                             local_vision=True) is VisionTier.TIER_2_CLOUD


def test_tier_latency_budgets_match_spec():
    assert VISION_TIER_LATENCY_MS[VisionTier.TIER_0_HTTP] == 100
    assert VISION_TIER_LATENCY_MS[VisionTier.TIER_1_LOCAL_VLM] == 400
    assert VISION_TIER_LATENCY_MS[VisionTier.TIER_2_CLOUD] == 1500


def test_has_vision_capability_never_raises():
    """REQ-17: detection is a safe probe (bool in any environment)."""
    assert isinstance(has_vision_capability(), bool)
