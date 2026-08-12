"""`screenshot_page` — capture a web page and show it in the chat.

Why this exists as an explicit tool rather than as part of the crawl: the vision
capability is registered as a RECOVERY node (crawler/capabilities.py) advertising
only EMPTY/TOO_SHORT, so on a page the crawl reads successfully it is never
invoked at all. A user asking "show me that page" was therefore asking for
something no code path could produce, however complete the pieces underneath
were. A tool the agent calls deliberately gives that a predictable cost and a
predictable trigger, without putting a browser session on every page's hot path.

WHERE THE IMAGE LIVES. The PNG goes into the memory DB as a BLOB keyed by the
document's own id (document_store.store_blob), not onto disk:
  * the chat card addresses it by an opaque document id, so the serving endpoint
    has no filename and therefore no path to traverse;
  * its lifetime is the document's — store eviction drops the blob with the row,
    so an image cannot outlive the card that shows it, and there is no directory
    of orphaned captures to reap;
  * it is NOT base64'd into the document's TEXT `content`, which is truncated at
    12k on the render path and 50k in the card — an inlined image would be cut
    into a broken one with no error raised anywhere.
`content` carries the URL of that blob instead.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# A page screenshot is a picture of a viewport, not a print of the whole
# document. Full-page capture of a long article produces multi-megabyte PNGs
# that are unreadable in a chat card anyway, and the point here is "show me what
# the page looks like", which the viewport answers.
_FULL_PAGE = False

# Refuse to store anything larger than this. A pathological page (an enormous
# canvas, a print stylesheet) must not be able to push an arbitrary number of
# megabytes into the memory DB on a single tool call.
_MAX_IMAGE_BYTES = 8 * 1024 * 1024


async def capture_page_screenshot(
    url: str,
    kernel: Any,
    conversation_id: str = "default",
    turn_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Screenshot ``url`` and render it as an image card in the chat.

    Returns a result dict for the agent: ``{"success", "document_id", "url",
    "bytes"}`` on success, ``{"success": False, "error": ...}`` otherwise. Never
    raises — a failed screenshot must cost the user a picture, never the turn.
    """
    if not url or not str(url).strip():
        return {"success": False, "error": "no url given"}
    url = str(url).strip()

    # The egress guard owns which hosts may be reached. Going around it here
    # would make this tool a way to fetch anything the crawler is forbidden.
    try:
        from backend.proxy.egress_guard import EgressRefused, acheck_url

        try:
            await acheck_url(url)
        except EgressRefused as refused:
            # Logged specifically, surfaced NON-specifically — the same posture
            # the proxy endpoint uses (REQ-5 AC5). Telling a caller exactly why
            # an address was refused turns this into a network probe.
            logger.info("[screenshot_page] egress refused %s: %s", url, refused)
            return {"success": False, "error": "that address is not allowed"}
    except ImportError:
        # No guard in this build — degrade like the crawler path rather than
        # blocking outright.
        pass
    except Exception as exc:  # noqa: BLE001 — a guard error must not open the gate
        logger.warning("[screenshot_page] egress guard errored for %s: %s", url, exc)
        return {"success": False, "error": "could not verify that address"}

    png: Optional[bytes] = None
    session = None
    try:
        from backend.vision.browser_session import BrowserSession, SessionBounds

        job_id = f"shot-{uuid.uuid4().hex[:12]}"
        # No actions: this session exists to open the page and photograph it.
        # A short wall bound because a user is waiting on a single picture, not
        # on a reading pass.
        session = BrowserSession(
            job_id=job_id,
            url=url,
            goal="capture a screenshot of this page",
            bounds=SessionBounds(max_actions=0, max_wall_ms=25_000),
        )
        await session.open()
        if not session.available():
            return {
                "success": False,
                "error": "the browser could not open that page",
            }
        png = await session.screenshot()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[screenshot_page] capture failed url=%s: %s", url, exc)
        return {"success": False, "error": "the page could not be captured"}
    finally:
        if session is not None:
            try:
                await session.close()
            except Exception:  # noqa: BLE001 — a leaked page must not fail the tool
                logger.debug("[screenshot_page] session close failed", exc_info=True)

    if not png:
        return {"success": False, "error": "the page produced no image"}
    if len(png) > _MAX_IMAGE_BYTES:
        logger.info(
            "[screenshot_page] image too large url=%s bytes=%d", url, len(png)
        )
        return {"success": False, "error": "that page's image was too large to keep"}

    document_id = str(uuid.uuid4())
    image_url = f"/api/documents/{document_id}/image"

    store = None
    try:
        store = kernel._get_document_store() if kernel is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[screenshot_page] document store unavailable: %s", exc)

    if store is None:
        return {"success": False, "error": "nowhere to store the screenshot"}

    # Blob FIRST, then the row that points at it. The other order can publish a
    # card whose image does not exist yet, which renders as the broken-image
    # state for however long the write takes.
    if not store.store_blob(document_id, png, "image/png"):
        return {"success": False, "error": "the screenshot could not be stored"}

    try:
        store.store(
            document_id=document_id,
            conversation_id=conversation_id,
            fmt="image",
            content=image_url,
            variants={},
            alternatives=[],
            trust="untrusted",  # a picture of the open web
            turn_id=turn_id,
            sources=[{"url": url, "title": url}],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[screenshot_page] document row failed: %s", exc)

    try:
        from backend.agent.event_bus import get_event_bus, IRISStreamEvent

        get_event_bus().emit(
            IRISStreamEvent.DOCUMENT_RENDER,
            data={
                "format": "image",
                "content": image_url,
                "alternatives": [],
                "trust": "untrusted",
                "document_id": document_id,
                "turn_id": turn_id,
                "conversation_id": conversation_id,
                "sources": [{"url": url, "title": url}],
                "har_path": None,
            },
            turn_id=turn_id,
            conversation_id=conversation_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[screenshot_page] DOCUMENT_RENDER emit failed: %s", exc)
        return {
            "success": False,
            "error": "the screenshot was taken but could not be shown",
            "document_id": document_id,
        }

    logger.info(
        "[screenshot_page] captured url=%s doc=%s bytes=%d conv=%s",
        url, document_id, len(png), conversation_id,
    )
    return {
        "success": True,
        "document_id": document_id,
        "url": url,
        "bytes": len(png),
        # The agent should TALK about the page, not re-describe the card. Saying
        # so here keeps it from narrating "I have displayed an image" as if that
        # were the answer.
        "note": "The screenshot is now shown in the chat. Describe what it shows.",
    }
