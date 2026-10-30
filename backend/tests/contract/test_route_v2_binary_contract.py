"""Contract pin: route_v2 must ask the question the kernel ACTUALLY asks.

DEFECT (2026-10-30, measured): the consumer was declared with four options
(direct / der / memory_recall / memory_write) while the kernel has no memory
branches any more. `_log_route_shadow` records the live fork as
``"der" if planned else "direct"``, and memory_write and memory_recall both
land on the direct path. Two menu entries that lead to the same behaviour
cannot be calibrated: the report's precision pools them, so the engine can
score well on an option that changes nothing. CADUCEAN_ARCHITECTURE section 10:
a computed signal must change behaviour.

The live fork is binary. This test FAILS on the four-option declaration and
passes only when the menu is the live one.
"""

from backend.agent import decision_engine as de


def test_route_v2_menu_is_the_live_binary_fork():
    criteria = de.CONSUMER_DECLARATIONS["route_v2"].criteria
    assert set(criteria) == {"direct", "der"}, (
        "route_v2 must offer only the two routes the kernel can take; "
        f"got {sorted(criteria)}"
    )


def test_route_v2_is_declared_and_shadow_only():
    assert "route_v2" in de.CONSUMERS
    assert de.CONSUMER_JOBS["route_v2"] == "route"
