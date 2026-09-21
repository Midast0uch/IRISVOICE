"""Session-level probe: what URL does Bing actually land on, and what HTML?

Run:  python _probe_session.py "<query>"
Writes _probe_session.out.json. Never raises.
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback

sys.path.insert(0, ".")


async def main() -> None:
    from urllib.parse import quote_plus

    from backend.vision.browser_session import (
        BrowserSession, SessionBounds, VisionAction,
    )

    query = sys.argv[1] if len(sys.argv) > 1 else "site:ziglang.org download"
    results_url = f"https://www.bing.com/search?q={quote_plus(query)}"
    out: dict = {"query": query, "results_url": results_url}

    bounds = SessionBounds(max_actions=6, max_wall_ms=300_000, max_extractions=2)
    session = BrowserSession("probe-sess", "https://www.bing.com/", query, bounds)
    try:
        await session.open()
        out["available_after_open"] = session.available()
        out["url_after_open"] = getattr(session, "url", None)
        try:
            await session.act(VisionAction(
                kind="type", target="textarea[name='q'], input[name='q']",
                value=query, reason="probe type",
            ))
            out["type_ok"] = True
        except Exception as exc:  # noqa: BLE001
            out["type_ok"] = False
            out["type_err"] = f"{type(exc).__name__}: {exc}"[:300]
        await session.act(VisionAction(
            kind="navigate", target=results_url, reason="probe submit",
        ))
        html = await session.settle()
        out["url_after_settle"] = getattr(session, "url", None)
        out["html_len"] = len(html or "")
        title = ""
        try:
            import re
            m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
            title = (m.group(1).strip() if m else "")[:200]
        except Exception:  # noqa: BLE001
            pass
        out["page_title"] = title
        # first few raw hrefs, unfiltered, to see what the SERP contained
        import re as _re
        hrefs = _re.findall(r'href="(https?://[^"]+)"', html or "", _re.I)[:15]
        out["first_hrefs"] = hrefs
        try:
            img = await session.screenshot()
            if img:
                with open("_probe_session.png", "wb") as fh:
                    fh.write(img)
                out["screenshot_bytes"] = len(img)
        except Exception as exc:  # noqa: BLE001
            out["screenshot_err"] = str(exc)[:200]
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["trace"] = traceback.format_exc()
    finally:
        try:
            await session.close()
        except Exception:  # noqa: BLE001
            pass

    with open("_probe_session.out.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(json.dumps(out, indent=2)[:3000])


if __name__ == "__main__":
    asyncio.run(main())
