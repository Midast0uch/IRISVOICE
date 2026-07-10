#!/usr/bin/env python3
"""Standalone E2E smoke test for the document render + reformat flow (Issue 8).

Run directly:  python backend/tests/smoke_document_flow.py
NOT collected by pytest (no test_ prefix) to avoid the full-backend memory spike.

Covers the backend integration path WITHOUT a live LLM:
  A. agent_kernel.reformat_document -> DOCUMENT_RENDER event (correct payload)
  B. iris_gateway._handle_reformat_document -> reformat_document_ack + reformat call
  C. ws_event_bridge -> WS 'document:render' message delivery

Frontend wiring (useIRISWebSocket -> chat-view RichDocument/DocumentPanel) is
covered separately by `npx tsc --noEmit` (exit 0, verified in D.3 commit).
"""
import importlib.util
import os
import sys
import json
import time
import asyncio
import threading
import logging

BACKEND = r"C:\dev\IRISVOICE\backend"
REPO_ROOT = os.path.dirname(BACKEND)  # C:\dev\IRISVOICE — insert this on path,
                                       # NOT BACKEND itself (there is a nested
                                       # backend/backend dir that would shadow
                                       # the real package as a namespace pkg).

results = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(("PASS" if cond else "FAIL"), name, ("- " + detail) if detail else "")


def load(modname, path=None):
    # Use import_module so relative imports (.model_conversation etc.) resolve
    # against the real backend.agent package. backend/__init__.py is stubbed
    # (light) so the package imports without the heavy top-level side effects.
    return importlib.import_module(modname)


def main():
    # Insert the REPO ROOT so `import backend` resolves to the real package
    # (C:\dev\IRISVOICE\backend). Do NOT insert BACKEND itself — there is a
    # nested backend/backend dir that would shadow it as a namespace package.
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

        # ── Test A: reformat_document -> DOCUMENT_RENDER ──────────────────
        ak = load("backend.agent.agent_kernel",
                  os.path.join(BACKEND, "agent", "agent_kernel.py"))
        AgentKernel = ak.AgentKernel
        kernel = AgentKernel.__new__(AgentKernel)

        canned = json.dumps({
            "show": {
                "format": "table",
                "content": "| Name | Val |\n|------|-----|\n| A | 1 |",
                "alternatives": ["markdown", "html"],
            }
        })

        def fake_respond_direct(self, text, context=None,
                                chunk_callback=None, reasoning_callback=None):
            return canned

        ak.AgentKernel._respond_direct = fake_respond_direct

        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
        bus = get_event_bus()
        captured = {}

        def on_render(payload):
            captured["data"] = payload.data
            captured["turn_id"] = payload.turn_id

        bus.subscribe(IRISStreamEvent.DOCUMENT_RENDER, on_render)

        out = kernel.reformat_document(
            content="| a | b |\n| 1 | 2 |",
            target_format="table",
            conversation_id="default",
            turn_id="t1",
            original_format="markdown",
        )
        d = captured.get("data")
        check("A1 reformat_document returns content", out is not None and "Name" in out)
        check("A2 DOCUMENT_RENDER emitted", d is not None)
        if d:
            check("A3 format == table", d.get("format") == "table", str(d.get("format")))
            check("A4 content present", bool(d.get("content")))
            check("A5 original format in alternatives",
                  "markdown" in d.get("alternatives", []), str(d.get("alternatives")))
            check("A6 reformatted flag True", d.get("reformatted") is True)
            check("A7 turn_id propagated", captured.get("turn_id") == "t1")

        # ── Test C: ws_event_bridge -> WS document:render ─────────────────
        bridge_mod = load("backend.agent.ws_event_bridge",
                          os.path.join(BACKEND, "agent", "ws_event_bridge.py"))
        sent = []

        class FakeWS:
            # Production ws_manager.broadcast is `async def` (backend/ws_manager.py:311),
            # so the bridge's `await` branch is the real path. Match it here.
            async def broadcast(self, msg):
                sent.append(msg)

            async def broadcast_to_session(self, sid, msg):
                sent.append(msg)

        loop_c = asyncio.new_event_loop()
        bridge = bridge_mod.WSEventBridge(FakeWS())
        bridge.set_main_loop(loop_c)
        threading.Thread(target=loop_c.run_forever, daemon=True).start()
        bridge.start()
        bus.emit(IRISStreamEvent.DOCUMENT_RENDER,
                 data={"format": "html", "content": "<b>x</b>",
                       "alternatives": ["markdown"], "reformatted": True},
                 turn_id="t9", conversation_id="default")
        time.sleep(0.3)
        loop_c.call_soon_threadsafe(loop_c.stop)
        time.sleep(0.1)

        docs = [m for m in sent if m.get("type") == "document:render"]
        check("C1 bridge delivered document:render", len(docs) >= 1)
        if docs:
            check("C2 payload shape",
                  docs[0].get("payload", {}).get("format") == "html",
                  str(docs[0].get("payload", {}).get("format")))

        # ── Test B: iris_gateway._handle_reformat_document ────────────────
        try:
            ig = load("backend.iris_gateway",
                      os.path.join(BACKEND, "iris_gateway.py"))
            IRISGateway = ig.IRISGateway
            gw = IRISGateway.__new__(IRISGateway)
            gw._logger = logging.getLogger("smoke")
            gw_sent = []

            class FakeWS2:
                def send_to_client(self, client_id, msg):
                    gw_sent.append(msg)

                def broadcast(self, msg):
                    pass

            gw._ws_manager = FakeWS2()

            class FakeKernel:
                def __init__(self):
                    self.called = {}

                def reformat_document(self, content, target_format,
                                      conversation_id="default", turn_id=None,
                                      original_format=None):
                    self.called = dict(content=content, target_format=target_format,
                                       turn_id=turn_id, original_format=original_format)
                    get_event_bus().emit(
                        IRISStreamEvent.DOCUMENT_RENDER,
                        data={"format": target_format, "content": "REFORMATTED",
                              "alternatives": [original_format or "markdown"],
                              "reformatted": True},
                        turn_id=turn_id, conversation_id=conversation_id)
                    return "REFORMATTED"

            fk = FakeKernel()
            ig.get_agent_kernel = lambda cid, sid: fk

            async def run():
                await gw._handle_reformat_document(
                    "sess", "client",
                    {"payload": {"content": "orig", "format": "html",
                                 "turn_id": "t2", "original_format": "markdown"}})

            loop_b = asyncio.new_event_loop()
            asyncio.set_event_loop(loop_b)
            loop_b.run_until_complete(run())
            loop_b.run_until_complete(asyncio.sleep(0.3))

            acks = [m for m in gw_sent if m.get("type") == "reformat_document_ack"]
            check("B1 reformat_document_ack sent", len(acks) >= 1)
            check("B2 kernel.reformat_document called", bool(fk.called))
            if fk.called:
                check("B3 target_format passed",
                      fk.called.get("target_format") == "html")
                check("B4 original_format passed",
                      fk.called.get("original_format") == "markdown")
        except Exception as e:
            check("B0 iris_gateway handler", False, f"{type(e).__name__}: {e}")

    failed = [r for r in results if not r[1]]
    print("\n=== SMOKE SUMMARY ===")
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", [r[0] for r in failed])
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
