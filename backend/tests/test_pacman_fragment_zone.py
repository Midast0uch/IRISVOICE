#!/usr/bin/env python3
"""Standalone test for W1: web/crawler tool outputs routed to 'reference' zone.

Run:  python backend/tests/test_pacman_fragment_zone.py
NOT collected by pytest (no test_ prefix) to avoid the full-backend memory spike.

Covers:
  T2 (behavioral): web_search / crawler_query -> 'reference' zone; local tools and
                   conversation turns keep their default zone (never 'reference').
  T3 (invariant):  external/web content NEVER lands in the 'trusted' zone
                   (cellwall-style boundary at the pacman_fragment action).
"""
import sys
import os

REPO_ROOT = r"C:\dev\IRISVOICE"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.agent.mcm_protocol.actions import pacman_fragment

results = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(("PASS" if cond else "FAIL"), name, ("- " + detail) if detail else "")


class FakeEpisodic:
    """Records every fragment_and_store call so we can assert the zone.

    Mirrors EpisodicStore's effective-zone resolution: an explicit ``zone``
    wins, otherwise it defaults from chunk_type (context_fragment -> trusted,
    der_output -> tool), exactly like episodic.py:_CHUNK_TYPE_ZONE.
    """

    _CHUNK_TYPE_ZONE = {"context_fragment": "trusted", "der_output": "tool"}

    def __init__(self):
        self.calls = []

    def fragment_and_store(self, content, session_id,
                           chunk_type="context_fragment", zone=None,
                           tool_name=None, **kwargs):
        # Production `mi.episodic` is a proxy that forwards **kwargs
        # (pacman_fragment passes tool_name=...); the real EpisodicStore
        # ignores it. Mirror that here.
        effective_zone = zone or self._CHUNK_TYPE_ZONE.get(chunk_type, "trusted")
        self.calls.append({
            "content": content,
            "session_id": session_id,
            "chunk_type": chunk_type,
            "zone": effective_zone,
            "tool_name": tool_name,
        })
        return ["fake-chunk-id"]


def make_mi(episodic):
    class FakeMI:
        pass
    mi = FakeMI()
    mi.episodic = episodic
    return mi


# Long enough + contains DER signals ("result", "output") to pass
# _is_fragment_candidate in pacman_fragment.
_SAMPLE = (
    "The tool produced a result and the output was stored successfully. "
    "This fragment is long enough to clear the minimum character threshold "
    "and contains the keywords the candidate check looks for."
)


def run_fragment(tool_name):
    ep = FakeEpisodic()
    mi = make_mi(ep)
    ctx = {
        "mi": mi,
        "session_id": "s1",
        "response_text": _SAMPLE,
        "tool_name": tool_name,
    }
    pacman_fragment.execute(ctx, {})
    return ep


def main():
    # ── T2: external tools -> 'reference' zone ───────────────────────────
    for tool in ("web_search", "crawler_query"):
        ep = run_fragment(tool)
        zones = [c["zone"] for c in ep.calls]
        check(f"T2a {tool} -> reference zone",
              len(ep.calls) == 1 and zones == ["reference"],
              str(zones))

    # ── T2: local tool keeps its default zone (NOT reference) ───────────
    ep = run_fragment("file_read")
    zones = [c["zone"] for c in ep.calls]
    check("T2b local tool not reference",
          len(ep.calls) == 1 and "reference" not in zones,
          str(zones))

    # ── T2: conversation turn (no tool) -> 'trusted' default ────────────
    ep = run_fragment("")
    zones = [c["zone"] for c in ep.calls]
    check("T2c no tool -> trusted default",
          len(ep.calls) == 1 and zones == ["trusted"],
          str(zones))

    # ── T3: invariant — external content never in 'trusted' ─────────────
    ep = run_fragment("web_search")
    zones = [c["zone"] for c in ep.calls]
    check("T3 external never trusted",
          all(z != "trusted" for z in zones),
          str(zones))

    failed = [r for r in results if not r[1]]
    print("\n=== W1 ZONE ROUTING SUMMARY ===")
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", [r[0] for r in failed])
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
