"""Screenshots are documents: stored as blobs in the memory DB, addressed by
document id, and never able to outlive the card that shows them.

The alternative considered and rejected was a screenshots DIRECTORY plus an
endpoint that serves a file by name. These tests pin the properties that made
the DB the better choice, so a later refactor back to files has to break them
deliberately rather than by drift:

  * ADDRESSED BY ID, NOT BY NAME. A filename in a URL is a path to traverse; a
    document id is not. There is no filename anywhere in this path.
  * ONE LIFETIME. The blob is dropped when its document row is evicted, so the
    store cannot accumulate images whose cards are long gone — which is exactly
    what the orphaned-capture bugs in this repo were.
  * NOT IN THE TEXT COLUMN. `content` is truncated on the render path
    (agent_kernel `response[:12000]`) and again in the card at 50k. A base64
    image there would be silently CUT into a broken image with no error raised,
    which is the signature failure this codebase keeps reproducing.
  * NOT AN SSRF. The tool takes a URL from the model and opens a browser at it,
    so the egress guard is load-bearing, not decorative.
"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from backend.agent.document_store import DocumentDataStore


def _store() -> DocumentDataStore:
    return DocumentDataStore(sqlite3.connect(":memory:"))


# ── storage ──────────────────────────────────────────────────────────────────

def test_blob_roundtrips_byte_for_byte():
    """A PNG must come back EXACTLY as stored.

    Pinned because the obvious cheap implementation — base64 into the existing
    TEXT content column — round-trips fine in a unit test and then loses its
    tail to the render path's truncation in production.
    """
    s = _store()
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 40  # non-UTF8 by construction
    assert s.store_blob("doc-a", png) is True

    got = s.get_blob("doc-a")
    assert got is not None
    assert got["data"] == png, "blob did not survive the round trip intact"
    assert got["byte_len"] == len(png)
    assert got["mime"] == "image/png"


def test_a_missing_blob_is_absent_not_empty():
    """None, so the endpoint can 404.

    Returning b"" instead would render as a broken image with a 200 — a
    screenshot that failed must be visibly missing, not silently blank.
    """
    assert _store().get_blob("never-stored") is None


@pytest.mark.parametrize(
    "doc_id,data",
    [("", b"bytes"), ("doc-b", b"")],
)
def test_refuses_to_store_a_meaningless_blob(doc_id, data):
    """An id with no bytes, or bytes with no id, is unaddressable either way."""
    assert _store().store_blob(doc_id, data) is False


def test_the_text_column_never_holds_the_image():
    """The document row points AT the image; it does not contain it.

    `content` must stay a short URL, so that every existing consumer which
    treats `content` as text — truncation, markdown rendering, search — keeps
    working unchanged on an image document.
    """
    s = _store()
    doc_id = "doc-c"
    url = f"/api/documents/{doc_id}/image"
    s.store_blob(doc_id, b"\x89PNG\r\n\x1a\n" + b"\x00" * 200_000)
    s.store(
        document_id=doc_id, conversation_id="conv-1", fmt="image", content=url,
        variants={}, alternatives=[], trust="untrusted",
    )

    row = s.get(doc_id)
    assert row is not None
    assert row["content"] == url
    assert len(row["content"]) < 200, (
        "the image body leaked into the text column; the render path's 12k "
        "truncation would cut it into a broken image"
    )
    # And the bytes are still whole in their own table.
    assert s.get_blob(doc_id)["byte_len"] == 200_008


def test_evicting_a_document_takes_its_image_with_it():
    """Blobs must not be the one thing in this store that grows unbounded.

    SQLite does not enforce foreign keys unless PRAGMA foreign_keys is on (it is
    not), so the cascade is explicit code and therefore worth pinning.
    """
    from backend.agent import document_store as ds

    s = _store()
    s.store_blob("gone", b"\x89PNG\r\n\x1a\nold")
    s.store(
        document_id="gone", conversation_id="c", fmt="image", content="/x",
        variants={}, alternatives=[], trust="untrusted",
    )
    assert s.get_blob("gone") is not None

    # Delete the row the way eviction does, then run the eviction sweep with the
    # bound lowered so the test does not have to create 500 documents.
    s._conn.execute("DELETE FROM document_data WHERE document_id = 'gone'")
    s._conn.commit()
    original = ds._MAX_DOCUMENTS
    try:
        ds._MAX_DOCUMENTS = -1  # force the sweep to run
        s._evict_if_needed()
    finally:
        ds._MAX_DOCUMENTS = original

    assert s.get_blob("gone") is None, (
        "the image outlived its document row — nothing would ever reclaim it"
    )


# ── addressing ───────────────────────────────────────────────────────────────

def test_the_served_url_carries_no_filename():
    """The whole reason this lives in the DB rather than in a directory.

    If the URL ever contains a name or a path segment the caller controls, this
    becomes a traversal surface and the choice made here has been undone.
    """
    from backend.agent.tools import screenshot_page_tool as spt
    import inspect

    src = inspect.getsource(spt)
    assert '/api/documents/{document_id}/image' in src, (
        "the served URL is no longer built from the document id alone"
    )
    # Markers of writing the image to a FILE. `session.open()` is a browser
    # page, not a file handle, so match on the write-mode/path-building idioms
    # rather than on the bare word "open".
    for leak in ('"wb"', "'wb'", "os.makedirs", "os.path.join", "screenshots"):
        assert leak not in src, (
            f"{leak!r} appears in the screenshot tool — the image is being put "
            f"on disk again, which reintroduces the filename/lifetime problems "
            f"the DB blob was chosen to avoid"
        )


# ── the tool is not an SSRF ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8090/api/conversations",  # the app's own backend
        "http://localhost:8090/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.5/",                          # private range
    ],
)
def test_refuses_to_photograph_an_internal_address(url):
    """The URL comes from the MODEL, and this tool opens a real browser at it.

    Without the egress guard, "screenshot this page" is a general-purpose read
    of anything the host can reach — including the app's own API — with the
    result handed back as a picture.
    """
    from backend.agent.tools.screenshot_page_tool import capture_page_screenshot

    result = asyncio.run(capture_page_screenshot(url, kernel=None))
    assert result["success"] is False, f"{url} was not refused"
    # Refused NON-specifically: a precise reason turns this into a network probe.
    assert "not allowed" in result["error"]


def test_an_empty_url_never_reaches_the_browser():
    from backend.agent.tools.screenshot_page_tool import capture_page_screenshot

    result = asyncio.run(capture_page_screenshot("   ", kernel=None))
    assert result["success"] is False
    assert "no url" in result["error"]


# ── the card can render it ───────────────────────────────────────────────────

def test_the_frontend_has_an_image_branch():
    """`format: "image"` must be a real branch, not a fallthrough.

    "json" was absent from RichDocument's union for exactly this reason and fell
    through to the markdown renderer, rendering a 16KB object as run-on prose
    with no type error anywhere. Same shape, so pin it.
    """
    from pathlib import Path

    card = (
        Path(__file__).resolve().parents[3]
        / "components" / "chat" / "RichDocument.tsx"
    ).read_text(encoding="utf-8", errors="replace")

    assert '"image"' in card and 'format === "image"' in card, (
        "RichDocument has no image branch; an image document would fall through "
        "to the markdown renderer and show its URL as text"
    )
