#!/usr/bin/env python3
"""Standalone test for W3 (backend): DOCUMENT_RENDER carries `trust`.

Run:  python backend/tests/test_document_render_trust.py
NOT collected by pytest (no test_ prefix) to avoid the full-backend memory spike.

Covers (T1 contract, backend half):
  - _process_structured_response emits DOCUMENT_RENDER with a `trust` field:
    'untrusted' when the turn touched external/web sources, else 'trusted'.
  - build_reformat_payload forwards an explicit `trust` into the payload so a
    re-rendered document keeps its original trust level.
"""
import sys
import os
import json

REPO_ROOT = r"C:\dev\IRISVOICE"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.agent.agent_kernel import AgentKernel
from backend.agent.structured_response import build_reformat_payload
from backend.agent.event_bus import get_event_bus, IRISStreamEvent

results = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(("PASS" if cond else "FAIL"), name, ("- " + detail) if detail else "")


def make_kernel():
    k = AgentKernel.__new__(AgentKernel)
    k._turn_touched_external = False
    return k


def main():
    bus = get_event_bus()
    captured = {}

    def on_render(payload):
        captured["data"] = payload.data

    bus.subscribe(IRISStreamEvent.DOCUMENT_RENDER, on_render)

    _SHOW = json.dumps({
        "show": {"format": "markdown", "content": "hello", "alternatives": []}
    })

    # ── T1a: trusted turn -> trust == 'trusted' ──────────────────────────
    k = make_kernel()
    captured.clear()
    k._process_structured_response(_SHOW, turn_id="t1")
    d = captured.get("data")
    check("T1a DOCUMENT_RENDER has trust field", d is not None and "trust" in d, str(d))
    check("T1a trusted turn -> trust='trusted'",
          d is not None and d.get("trust") == "trusted", str(d.get("trust")))

    # ── T1b: external turn -> trust == 'untrusted' ──────────────────────
    k2 = make_kernel()
    k2._turn_touched_external = True
    captured.clear()
    k2._process_structured_response(_SHOW, turn_id="t2")
    d2 = captured.get("data")
    check("T1b external turn -> trust='untrusted'",
          d2 is not None and d2.get("trust") == "untrusted", str(d2.get("trust")))

    # ── T1c: build_reformat_payload forwards trust ──────────────────────
    p = build_reformat_payload(
        "reformatted text", "markdown", turn_id="t",
        conversation_id="default", original_format="table", trust="untrusted",
    )
    check("T1c build_reformat_payload includes trust",
          p.get("trust") == "untrusted", str(p.get("trust")))
    # trust must not break the existing payload shape
    check("T1c payload shape intact",
          p.get("format") == "markdown" and p.get("reformatted") is True)

    failed = [r for r in results if not r[1]]
    print("\n=== W3 DOCUMENT_RENDER TRUST SUMMARY ===")
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", [r[0] for r in failed])
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
