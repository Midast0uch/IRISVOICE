#!/usr/bin/env python3
"""Standalone test for W2: per-turn external flag -> 'reference' zone.

Run:  python backend/tests/test_agent_kernel_turn_zone.py
NOT collected by pytest (no test_ prefix) to avoid the full-backend memory spike.

Covers:
  T2 (behavioral): a turn that touched external/web sources stores its
    turn-pair fragment in the 'reference' zone; a normal turn keeps the
    default 'trusted' zone. Verified via the kernel's zone-decision helpers
    (_pacman_zone_for_turn / mark_external_tool) and is_external_tool.
  Contract: orchestrator.post_turn accepts a non-breaking `zone` kwarg so the
    MCM conversation path can propagate the turn's zone to pacman_fragment.
"""
import sys
import os
import inspect

REPO_ROOT = r"C:\dev\IRISVOICE"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.agent.agent_kernel import AgentKernel
from backend.agent.mcm_protocol.actions.pacman_fragment import is_external_tool
from backend.agent.mcm_protocol.orchestrator import MCMOrchestrator

results = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(("PASS" if cond else "FAIL"), name, ("- " + detail) if detail else "")


def make_kernel():
    """Build an AgentKernel without running __init__ (avoids heavy setup)."""
    k = AgentKernel.__new__(AgentKernel)
    k._turn_touched_external = False
    return k


def main():
    # ── T2: per-turn external flag drives the zone decision ───────────────
    k = make_kernel()
    check("T2a normal turn -> no zone override (None)",
          k._pacman_zone_for_turn() is None)

    k._turn_touched_external = True
    check("T2b external turn -> 'reference' zone",
          k._pacman_zone_for_turn() == "reference",
          str(k._pacman_zone_for_turn()))

    # ── mark_external_tool sets the flag for external tools only ──────────
    k2 = make_kernel()
    k2.mark_external_tool("web_search")
    check("T2c mark_external_tool(web_search) sets flag",
          k2._turn_touched_external is True)
    # Once external, a later local tool must NOT clear it (whole-turn stays external)
    k2.mark_external_tool("file_read")
    check("T2c local tool does not clear flag",
          k2._turn_touched_external is True)
    k2.mark_external_tool("")
    check("T2c empty tool does not clear flag",
          k2._turn_touched_external is True)

    # ── is_external_tool contract (shared with W1 routing) ───────────────
    check("T2d is_external_tool web_search", is_external_tool("web_search") is True)
    check("T2d is_external_tool crawler_query", is_external_tool("crawler_query") is True)
    check("T2d is_external_tool file_read", is_external_tool("file_read") is False)
    check("T2d is_external_tool ''", is_external_tool("") is False)

    # ── post_turn accepts a non-breaking zone kwarg ──────────────────────
    sig = inspect.signature(MCMOrchestrator.post_turn)
    check("T2e post_turn accepts zone kwarg",
          "zone" in sig.parameters,
          str(list(sig.parameters)))

    failed = [r for r in results if not r[1]]
    print("\n=== W2 TURN ZONE SUMMARY ===")
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", [r[0] for r in failed])
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
