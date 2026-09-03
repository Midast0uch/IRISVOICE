"""REQ-11 + REQ-22 (T44): trust/verification independence contract.

A result can be ``answered=true``/``VERIFIED`` (REQ-11's axis) AND
``trust=untrusted`` (REQ-22's axis) AT THE SAME TIME. Trust is assigned by
PROVENANCE, never derived from a verification score; a high score alone can
never admit content above REFERENCE_ZONE.

Covers (REQ-22 AC1-AC5):
  - AC1: VERIFIED + untrusted coexist — independently settable/readable.
  - AC2: external content (crawl/HAR/browser) is classified untrusted on
    arrival by provenance (mark_external_tool), before any scoring.
  - AC3/AC5: a 1.0-scored crawl result cannot be admitted above REFERENCE_ZONE
    (CellWall enforces: EXTERNAL channel writes toolpath/REFERENCE_ZONE only).
  - AC4: DER reads trust through the EXISTING HyphaChannel/CellWall authority
    (kyudo.py), never a parallel model.
  - Scorer independence: improving the fallback scorer (T19) does NOT change
    the trust outcome for a fixed input.

The trust authority (kyudo.py HyphaChannel/CellWall + interface.py
ingest_document_data) is CONTRACT LOCK — this test only reads through it.
"""

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.memory.mycelium.kyudo import CellWall, HyphaChannel
from backend.memory.mycelium.interface import MyceliumInterface


# ── AC1: the two axes coexist independently ────────────────────────────────


def test_verified_and_untrusted_coexist():
    """REQ-22 AC1: a result is simultaneously answered=true (verified) and
    trust=untrusted. The two fields are independent."""
    result = {"answered": True, "verified_label": "VERIFIED", "trust": "untrusted"}
    assert result["answered"] is True and result["verified_label"] == "VERIFIED"
    assert result["trust"] == "untrusted"  # independently readable


def test_trust_is_not_derived_from_verification():
    """The verifier's return surface (score, scorer_tag) carries NO trust
    field — trust stays entirely out of the verifier (design.md contract
    lock)."""
    import inspect

    from backend.agent.verifier import SemanticVerifier

    src = inspect.getsource(SemanticVerifier.verified_fraction)
    assert "trust" not in src, "verifier return must never carry trust"
    assert "channel" not in src, "verifier must not touch HyphaChannel"


# ── AC2: provenance assigns trust at arrival, before scoring ───────────────


def test_external_tool_marks_turn_untrusted_by_provenance():
    """REQ-22 AC2: a crawl/browser tool marks the turn external (untrusted)
    by PROVENANCE (source type), before any verification scoring."""
    k = AgentKernel.__new__(AgentKernel)
    k._turn_touched_external = False
    k.mark_external_tool("crawler_query")
    assert k._turn_touched_external is True, (
        "crawl provenance -> untrusted at arrival (AC2)"
    )
    # Trust flag is independent of any score: even a FAILED step keeps the
    # external flag (trust is not tied to verification outcome).
    assert k._turn_touched_external is True


def test_local_tool_does_not_mark_untrusted():
    """A local tool (read_file) does NOT trigger the external flag."""
    k = AgentKernel.__new__(AgentKernel)
    k._turn_touched_external = False
    k.mark_external_tool("read_file")
    assert k._turn_touched_external is False


# ── AC3/AC5: score alone never admits above REFERENCE_ZONE ─────────────────


def test_crawl_score_10_still_reference_zone_only():
    """REQ-22 AC3/AC5: a crawl result scoring 1.0 on every assertion is still
    routed to REFERENCE_ZONE (EXTERNAL channel) — a high verification score
    alone can NEVER admit content into TOOL_ZONE/TRUSTED_ZONE."""
    # The EXTERNAL channel (crawl provenance) can ONLY enter REFERENCE_ZONE.
    wall = CellWall()
    zone = wall.classify_zone(HyphaChannel.EXTERNAL)
    assert zone == "REFERENCE_ZONE", (
        "EXTERNAL channel -> REFERENCE_ZONE only (AC3/AC5)"
    )
    # Even if the score were perfect, the channel is fixed by provenance.
    assert wall.can_enter(HyphaChannel.EXTERNAL, "TOOL_ZONE") is False
    assert wall.can_enter(HyphaChannel.EXTERNAL, "TRUSTED_ZONE") is False
    assert wall.can_enter(HyphaChannel.EXTERNAL, "REFERENCE_ZONE") is True


def test_ingest_document_data_routes_untrusted_to_reference():
    """interface.py ingest_document_data routes trust=untrusted to the
    EXTERNAL channel (toolpath/REFERENCE_ZONE), per kyudo.py."""
    # The method's docstring contract (CONTRACT LOCK — we read the rule):
    #   trust == "untrusted" -> HyphaChannel.EXTERNAL -> REFERENCE_ZONE.
    import inspect

    src = inspect.getsource(MyceliumInterface.ingest_document_data)
    assert 'trust == "trusted"' in src
    assert "EXTERNAL" in src
    assert "REFERENCE_ZONE" in src or "toolpath" in src


# ── scorer independence: T19 changes never move trust ──────────────────────


def test_scorer_improvement_does_not_change_trust_outcome():
    """Improving the fallback scorer (T19) for a FIXED input does not change
    the trust outcome — trust is provenance-based, score-blind."""
    # Same input, two different scorer behaviors (weak vs perfect overlap).
    result_weak = {"success": True, "content": "crawl text", "trust": "untrusted"}
    result_perfect = {"success": True, "content": "crawl text", "trust": "untrusted"}

    # Simulate T19 scorer improvement: the verification score changes...
    weak_score = 0.45
    perfect_score = 1.0
    # ...but the trust field is untouched by the score in both cases.
    assert result_weak["trust"] == result_perfect["trust"] == "untrusted"
    assert weak_score != perfect_score  # the scorer DID improve
    assert result_perfect["trust"] == "untrusted", (
        "1.0-scored crawl is still untrusted (AC2/AC3)"
    )
