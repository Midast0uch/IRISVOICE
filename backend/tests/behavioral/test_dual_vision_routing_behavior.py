"""BT (vision-goal-directed-search T31 / REQ-16 AC16.1-16.2 + REQ-17):
dual vision routing — the Brain picks the cheapest tier that can handle
the work.

Drives the REAL `route_vision_tier` (pure tier logic, no hardware touched:
`local_vision` is passed explicitly) plus the `has_vision_capability`
never-raises pin.
"""
from __future__ import annotations

from backend.inference_router import (
    VisionTier,
    has_vision_capability,
    route_vision_tier,
)


def test_straightforward_dom_stays_on_free_tier():
    assert route_vision_tier() is VisionTier.TIER_0_HTTP


def test_interactive_page_prefers_local_vlm():
    assert (
        route_vision_tier(needs_interaction=True, local_vision=True)
        is VisionTier.TIER_1_LOCAL_VLM
    )


def test_interactive_page_falls_back_to_cloud_without_local_vision():
    assert (
        route_vision_tier(needs_interaction=True, local_vision=False)
        is VisionTier.TIER_2_CLOUD
    )


def test_high_ambiguity_always_goes_cloud():
    assert route_vision_tier(high_ambiguity=True) is VisionTier.TIER_2_CLOUD
    assert (
        route_vision_tier(
            needs_interaction=True, high_ambiguity=True, local_vision=True
        )
        is VisionTier.TIER_2_CLOUD
    )


def test_capability_probe_never_raises():
    assert isinstance(has_vision_capability(), bool)
