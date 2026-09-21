"""Live probe: does vision-driven search discovery actually return URLs?

Run:  python _probe_discovery.py "<query>"
Writes a JSON result to _probe_discovery.out.json. Never raises.
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback

sys.path.insert(0, ".")


async def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "site:ziglang.org download"
    out: dict = {"query": query, "steps": []}

    def emit(kind, payload):
        out["steps"].append({"event": kind, **{k: payload.get(k) for k in ("kind", "reason", "action_index", "total")}})

    try:
        from backend.vision.search_discovery import discover_urls_via_vision

        result = await discover_urls_via_vision(query, "probe-job", emit)
        out["urls"] = result.urls
        out["used_vision_fallback"] = result.used_vision_fallback
        out["wall"] = result.wall
        out["unavailable"] = result.unavailable
        out["engine_url"] = result.engine_url
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["trace"] = traceback.format_exc()

    with open("_probe_discovery.out.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
