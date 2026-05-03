"""
Regression tests for the PinStore CRUD service and its recall-decoder integration.

Covers:
  - PinStore: add/get/update/delete/link/list/search/checkpoint/linked
  - Markdown body preserved verbatim (no transformation)
  - Search ranking with default weights and tunable overrides
  - Checkpoint creation and chronological retrieval per file
  - on_write callback fires on every mutating operation (cache invalidation hook)
  - RecallDecoder._resolve_pin queries the real pin store via every op form:
      <recall pin="title"/>
      <recall pin query="text"/>
      <recall pin file="path"/>
      <recall pin tags="a,b"/>
"""
from __future__ import annotations

import sqlite3
import time
import unittest
from typing import List

from backend.agent.recall_decoder import RecallDecoder, RecallOp
from backend.memory.pin_store import (
    PinStore, Pin, DEFAULT_SEARCH_WEIGHTS, PIN_TYPES,
)


def _make_pin_db() -> sqlite3.Connection:
    """Create an in-memory DB with the mycelium_pins / mycelium_pin_links schema."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE mycelium_pins (
            pin_id       TEXT PRIMARY KEY,
            title        TEXT NOT NULL,
            pin_type     TEXT DEFAULT 'note',
            content      TEXT,
            tags         TEXT DEFAULT '[]',
            file_refs    TEXT DEFAULT '[]',
            image_refs   TEXT DEFAULT '[]',
            url_refs     TEXT DEFAULT '[]',
            project_id   TEXT,
            origin_id    TEXT,
            created_at   REAL NOT NULL,
            updated_at   REAL NOT NULL,
            is_permanent INTEGER DEFAULT 0
        );
        CREATE TABLE mycelium_pin_links (
            link_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type  TEXT NOT NULL,
            source_id    TEXT NOT NULL,
            target_type  TEXT NOT NULL,
            target_id    TEXT NOT NULL,
            relationship TEXT NOT NULL,
            weight       REAL DEFAULT 1.0,
            created_at   REAL NOT NULL
        );
    """)
    return conn


# ---------------------------------------------------------------------------
# CRUD basics
# ---------------------------------------------------------------------------

class TestPinStoreCrud(unittest.TestCase):

    def setUp(self):
        self.conn = _make_pin_db()
        self.store = PinStore(conn=self.conn, origin_id="iris-local")

    def test_add_returns_uuid_and_persists_row(self):
        pin_id = self.store.add(title="OAuth PKCE notes", content="# PKCE\n\nProof Key for Code Exchange.")
        self.assertTrue(pin_id and isinstance(pin_id, str))
        pin = self.store.get(pin_id)
        self.assertIsNotNone(pin)
        self.assertEqual(pin.title, "OAuth PKCE notes")
        self.assertIn("Proof Key for Code Exchange", pin.content)
        self.assertEqual(pin.origin_id, "iris-local")

    def test_markdown_body_preserved_verbatim(self):
        md = "# Heading\n\n- bullet 1\n- bullet 2\n\n```python\nprint('hi')\n```\n"
        pin_id = self.store.add(title="Test", content=md)
        pin = self.store.get(pin_id)
        self.assertEqual(pin.content, md, "markdown body must round-trip without transformation")

    def test_update_modifies_only_provided_fields(self):
        pin_id = self.store.add(title="A", content="orig", tags=["x"])
        ok = self.store.update(pin_id, content="updated")
        self.assertTrue(ok)
        pin = self.store.get(pin_id)
        self.assertEqual(pin.content, "updated")
        self.assertEqual(pin.tags, ["x"], "tags untouched")
        self.assertEqual(pin.title, "A", "title untouched")

    def test_update_unknown_field_silently_ignored(self):
        pin_id = self.store.add(title="A")
        ok = self.store.update(pin_id, bogus_field="ignored")
        self.assertFalse(ok, "no allowed fields → no update")

    def test_delete_removes_pin_and_links(self):
        a = self.store.add(title="A")
        b = self.store.add(title="B")
        self.store.link(a, b, relationship="related_to")
        self.store.delete(a)
        self.assertIsNone(self.store.get(a))
        # link must also be gone
        rows = self.conn.execute("SELECT COUNT(*) FROM mycelium_pin_links").fetchone()
        self.assertEqual(rows[0], 0, "links involving deleted pin must be removed")

    def test_get_by_title_returns_most_recent(self):
        a = self.store.add(title="OAuth", content="v1")
        time.sleep(0.01)
        b = self.store.add(title="OAuth", content="v2")
        pin = self.store.get_by_title("OAuth")
        self.assertEqual(pin.pin_id, b)
        self.assertEqual(pin.content, "v2")

    def test_list_filters_by_type_and_project(self):
        self.store.add(title="A", pin_type="note", project_id="proj1")
        self.store.add(title="B", pin_type="checkpoint", project_id="proj1")
        self.store.add(title="C", pin_type="note", project_id="proj2")
        notes_p1 = self.store.list(project_id="proj1", pin_type="note")
        self.assertEqual(len(notes_p1), 1)
        self.assertEqual(notes_p1[0].title, "A")
        all_p1 = self.store.list(project_id="proj1")
        self.assertEqual(len(all_p1), 2)


# ---------------------------------------------------------------------------
# on_write callback (recall cache invalidation hook)
# ---------------------------------------------------------------------------

class TestOnWriteCallback(unittest.TestCase):

    def test_callback_fires_on_add_update_delete(self):
        calls: List[str] = []
        store = PinStore(conn=_make_pin_db(), on_write=lambda: calls.append("write"))
        pid = store.add(title="A")
        store.update(pid, content="x")
        store.delete(pid)
        self.assertEqual(len(calls), 3, "on_write must fire on each mutating op")

    def test_callback_does_not_fire_on_reads(self):
        calls: List[str] = []
        store = PinStore(conn=_make_pin_db(), on_write=lambda: calls.append("write"))
        pid = store.add(title="A")
        calls.clear()
        store.get(pid)
        store.list()
        store.search("A")
        self.assertEqual(len(calls), 0, "reads must not invalidate cache")


# ---------------------------------------------------------------------------
# Search ranking
# ---------------------------------------------------------------------------

class TestPinStoreSearch(unittest.TestCase):

    def setUp(self):
        self.store = PinStore(conn=_make_pin_db())

    def test_title_match_outranks_content_match(self):
        self.store.add(title="OAuth PKCE", content="unrelated body")
        self.store.add(title="unrelated", content="OAuth PKCE buried in body")
        results = self.store.search("OAuth PKCE")
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0].title, "OAuth PKCE",
                         "title match should rank above content-only match")

    def test_tag_match_contributes_to_score(self):
        self.store.add(title="A", tags=["api", "auth"])
        self.store.add(title="B", tags=["unrelated"])
        results = self.store.search("api")
        # Only the tagged pin should match
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0].title, "A")

    def test_file_refs_match_contributes_to_score(self):
        self.store.add(title="A", file_refs=["src/auth/pkce.py"])
        results = self.store.search("pkce.py")
        self.assertEqual(len(results), 1)
        self.assertGreater(results[0][1], 0)

    def test_tunable_weights_change_ranking(self):
        # With default weights: title > content
        self.store.add(title="alpha-only-title", content="filler")
        self.store.add(title="filler", content="alpha-only-title appears in body")
        default = self.store.search("alpha-only-title")
        self.assertEqual(default[0][0].title, "alpha-only-title")

        # Tune weights so content beats title
        boosted = self.store.search(
            "alpha-only-title",
            weights={"title": 1.0, "content": 100.0, "tags": 0.0, "file_refs": 0.0},
        )
        self.assertEqual(boosted[0][0].title, "filler",
                         "content-heavy weights must flip the ranking")

    def test_empty_query_returns_empty(self):
        self.store.add(title="A")
        self.assertEqual(self.store.search(""), [])

    def test_types_filter_excludes_non_matching(self):
        self.store.add(title="note pin", pin_type="note")
        self.store.add(title="checkpoint pin", pin_type="checkpoint")
        results = self.store.search("pin", types=["checkpoint"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0].pin_type, "checkpoint")


# ---------------------------------------------------------------------------
# Checkpoint mechanism
# ---------------------------------------------------------------------------

class TestCheckpoint(unittest.TestCase):

    def setUp(self):
        self.store = PinStore(conn=_make_pin_db(), origin_id="iris")

    def test_checkpoint_creates_typed_pin(self):
        pid = self.store.checkpoint(
            file_path="src/auth.py",
            offset=1500,
            summary_md="Wrote login flow up to MFA step.",
        )
        pin = self.store.get(pid)
        self.assertEqual(pin.pin_type, "checkpoint")
        self.assertIn("auth.py", pin.title)
        self.assertIn("Wrote login flow", pin.content)
        self.assertIn("src/auth.py", pin.file_refs)
        self.assertIn("checkpoint", pin.tags)

    def test_checkpoint_with_snapshot_truncates_to_2kb_tail(self):
        snap = "x" * 5000  # 5KB content
        pid = self.store.checkpoint(
            file_path="big.txt", offset=5000,
            summary_md="big", content_snapshot=snap,
        )
        pin = self.store.get(pid)
        # Content has summary + fenced snapshot; snapshot portion should be truncated
        self.assertIn("```", pin.content)
        # Bound check: total content much less than 5KB + summary overhead
        self.assertLess(len(pin.content), 3000,
                        "snapshot must be truncated to a manageable tail")

    def test_list_checkpoints_for_file_chronological(self):
        for offset in (100, 200, 300):
            self.store.checkpoint(
                file_path="long.md", offset=offset,
                summary_md=f"checkpoint at {offset}",
            )
            time.sleep(0.005)
        pins = self.store.list_checkpoints_for_file("long.md")
        self.assertEqual(len(pins), 3)
        offsets = [int(p.title.split("@")[1]) for p in pins]
        self.assertEqual(offsets, sorted(offsets), "checkpoints must be chronological")

    def test_list_checkpoints_filters_by_file(self):
        self.store.checkpoint(file_path="A.md", offset=0, summary_md="x")
        self.store.checkpoint(file_path="B.md", offset=0, summary_md="y")
        self.assertEqual(len(self.store.list_checkpoints_for_file("A.md")), 1)
        self.assertEqual(len(self.store.list_checkpoints_for_file("B.md")), 1)


# ---------------------------------------------------------------------------
# Pin links (wiki graph)
# ---------------------------------------------------------------------------

class TestPinLinks(unittest.TestCase):

    def setUp(self):
        self.store = PinStore(conn=_make_pin_db())

    def test_link_returns_id(self):
        a = self.store.add(title="A")
        b = self.store.add(title="B")
        link_id = self.store.link(a, b, relationship="documents")
        self.assertGreater(link_id, 0)

    def test_linked_returns_neighbours(self):
        a = self.store.add(title="A")
        b = self.store.add(title="B")
        c = self.store.add(title="C")
        self.store.link(a, b)
        self.store.link(a, c)
        neighbours = self.store.linked(a, depth=1)
        self.assertEqual({n.title for n in neighbours}, {"B", "C"})

    def test_linked_traverses_at_depth(self):
        a = self.store.add(title="A")
        b = self.store.add(title="B")
        c = self.store.add(title="C")
        self.store.link(a, b)
        self.store.link(b, c)
        d1 = self.store.linked(a, depth=1)
        self.assertEqual({n.title for n in d1}, {"B"})
        d2 = self.store.linked(a, depth=2)
        self.assertEqual({n.title for n in d2}, {"B", "C"})

    def test_linked_filters_by_relationship(self):
        a = self.store.add(title="A")
        b = self.store.add(title="B")
        c = self.store.add(title="C")
        self.store.link(a, b, relationship="documents")
        self.store.link(a, c, relationship="related_to")
        docs_only = self.store.linked(a, relationship="documents")
        self.assertEqual({n.title for n in docs_only}, {"B"})


# ---------------------------------------------------------------------------
# Pin.to_markdown rendering
# ---------------------------------------------------------------------------

class TestPinMarkdownRender(unittest.TestCase):

    def test_simple_note_renders_title_and_body(self):
        pin = Pin(pin_id="x", title="My Note", content="Body text")
        md = pin.to_markdown()
        self.assertIn("## My Note", md)
        self.assertIn("Body text", md)

    def test_metadata_appears_when_present(self):
        pin = Pin(
            pin_id="x", title="T", pin_type="decision",
            tags=["api"], file_refs=["src/x.py"], content="why",
        )
        md = pin.to_markdown()
        self.assertIn("decision", md)
        self.assertIn("api", md)
        self.assertIn("src/x.py", md)
        self.assertIn("why", md)


# ---------------------------------------------------------------------------
# RecallDecoder._resolve_pin integration with PinStore
# ---------------------------------------------------------------------------

class TestRecallDecoderPinIntegration(unittest.TestCase):

    def setUp(self):
        self.store = PinStore(conn=_make_pin_db(), origin_id="iris")
        self.decoder = RecallDecoder(pin_store=self.store)

    def test_pin_by_exact_title(self):
        self.store.add(title="OAuth PKCE", content="# Notes\n\nbody")
        op = RecallOp("pin", {"pin": "OAuth PKCE"}, '<recall pin="OAuth PKCE"/>')
        span = self.decoder.resolve(op)
        self.assertEqual(span.status, "ok")
        self.assertIn("Notes", span.content)
        self.assertIn("pin_store/title", span.source)

    def test_pin_query_returns_ranked_results(self):
        self.store.add(title="OAuth PKCE", content="The PKCE flow")
        self.store.add(title="OAuth Basics", content="Token exchange")
        op = RecallOp("pin", {"query": "PKCE"}, '<recall pin query="PKCE"/>')
        span = self.decoder.resolve(op)
        self.assertEqual(span.status, "ok")
        self.assertIn("OAuth PKCE", span.content)
        self.assertIn("pin_store/query", span.source)

    def test_pin_file_returns_checkpoints_in_order(self):
        for offset in (100, 200, 300):
            self.store.checkpoint(
                file_path="src/auth.py", offset=offset,
                summary_md=f"checkpoint @ {offset}",
            )
            time.sleep(0.005)
        op = RecallOp("pin", {"file": "src/auth.py"}, '<recall pin file="src/auth.py"/>')
        span = self.decoder.resolve(op)
        self.assertEqual(span.status, "ok")
        for offset in (100, 200, 300):
            self.assertIn(f"checkpoint @ {offset}", span.content)
        # Order: 100 must appear before 300
        self.assertLess(span.content.index("checkpoint @ 100"),
                        span.content.index("checkpoint @ 300"))

    def test_pin_tags_returns_matching_pins(self):
        self.store.add(title="A", tags=["api", "auth"])
        self.store.add(title="B", tags=["api"])
        self.store.add(title="C", tags=["unrelated"])
        op = RecallOp("pin", {"tags": "api"}, '<recall pin tags="api"/>')
        span = self.decoder.resolve(op)
        self.assertEqual(span.status, "ok")
        self.assertIn("A", span.content)
        self.assertIn("B", span.content)
        self.assertNotIn("## C", span.content)

    def test_pin_query_no_results_returns_empty_status(self):
        op = RecallOp("pin", {"query": "missing"}, '<recall pin query="missing"/>')
        span = self.decoder.resolve(op)
        self.assertEqual(span.status, "empty")

    def test_pin_no_args_returns_empty_status(self):
        op = RecallOp("pin", {}, "<recall pin/>")
        span = self.decoder.resolve(op)
        self.assertEqual(span.status, "empty")

    def test_decoder_cache_clears_on_pin_write(self):
        # Wire decoder to invalidate on write
        self.store._on_write = self.decoder.invalidate_cache
        op = RecallOp("pin", {"query": "X"}, '<recall pin query="X"/>')

        # First resolve: empty
        span1 = self.decoder.resolve(op)
        self.assertEqual(span1.status, "empty")

        # Add a pin matching the query
        self.store.add(title="X marks", content="found")

        # Resolve again — must re-evaluate, not return cached empty
        span2 = self.decoder.resolve(op)
        self.assertEqual(span2.status, "ok",
                         "decoder cache must invalidate after pin write")

    def test_pin_legacy_semantic_fallback_when_no_pin_store(self):
        """Decoder without a PinStore falls back to the old semantic-store path."""
        from unittest.mock import MagicMock
        mem = MagicMock()
        mem.semantic.get.return_value = MagicMock(value="legacy", confidence=0.5)
        decoder = RecallDecoder(memory_interface=mem, pin_store=None)
        op = RecallOp("pin", {"pin": "Skill1"}, '<recall pin="Skill1"/>')
        span = decoder.resolve(op)
        self.assertEqual(span.status, "ok")
        self.assertIn("legacy", span.content)


# ---------------------------------------------------------------------------
# Pin types vocabulary (documented set, not enforced)
# ---------------------------------------------------------------------------

class TestPinTypes(unittest.TestCase):

    def test_all_documented_types_accepted(self):
        store = PinStore(conn=_make_pin_db())
        for t in PIN_TYPES:
            pid = store.add(title=f"x-{t}", pin_type=t)
            pin = store.get(pid)
            self.assertEqual(pin.pin_type, t)


if __name__ == "__main__":
    unittest.main()
