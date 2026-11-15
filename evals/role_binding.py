"""Show or set a role binding through the app's own channel (CLM T2.8 operator helper).

    python evals/role_binding.py show
    python evals/role_binding.py set tool_execution iris_tool_local [--model NAME]

`show` reads GET /api/inference/state (providers + role bindings; read-only).
`set` sends the WebSocket message the UI sends, `set_role_binding` (iris_gateway.py
`_handle_set_role_binding`): the router rebinds at once for every session and the gateway persists
the binding the way a UI action does, so nobody edits data/iris_config.json by hand. Put the old
binding back with the same command and the old instance id (read it with `show` first).

The harness (run_evals.py) restores only the launcher mode and the project list, never role bindings.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request

HTTP = "http://127.0.0.1:8090"
WS = "ws://127.0.0.1:8090/ws/eval-role-binding?session_id=eval-role-binding"


def show() -> int:
    with urllib.request.urlopen(HTTP + "/api/inference/state", timeout=20) as r:
        snap = json.loads(r.read())
    providers = snap.get("providers")
    print("role_bindings:", json.dumps(snap.get("role_bindings"), indent=2))
    items = providers.items() if isinstance(providers, dict) else enumerate(providers or [])
    for key, p in items:
        if isinstance(p, dict):
            print("provider:", p.get("id", key), p.get("kind"), p.get("model"), p.get("api_base_url") or p.get("endpoint"))
    return 0


async def set_binding(role: str, instance_id: str, model: str | None) -> int:
    import websockets

    async with websockets.connect(WS, max_size=16 * 1024 * 1024, ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "set_role_binding", "payload": {
            "role": role, "instance_id": instance_id, "model_override": model}}))
        for _ in range(40):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if msg.get("type") == "ping":
                await ws.send(json.dumps({"type": "pong", "payload": {}}))
            elif msg.get("type") in ("role_binding_updated", "role_binding_error"):
                p = msg.get("payload") or {}
                print(msg["type"], json.dumps({k: p.get(k) for k in ("role", "instance_id", "model_override", "status", "error")}))
                return 0 if msg["type"] == "role_binding_updated" else 1
    print("no answer to set_role_binding")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    s = sub.add_parser("set")
    s.add_argument("role")
    s.add_argument("instance_id")
    s.add_argument("--model", default=None)
    a = ap.parse_args()
    return show() if a.cmd == "show" else asyncio.run(set_binding(a.role, a.instance_id, a.model))


if __name__ == "__main__":
    sys.exit(main())
