#!/usr/bin/env python3
"""Wave 1 unit tests — T2 (agent_kernel._store_document_data provenance linkage).

Run:  pytest backend/tests/unit/test_document_rehydration_wave1b.py -q
"""
import sqlite3
import sys
from unittest.mock import patch

REPO_ROOT = r"C:\dev\IRISVOICE"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.agent.document_store import DocumentDataStore
from backend.agent.agent_kernel import AgentKernel


def _make_kernel():
    conn = sqlite3.connect(":memory:")

    class FakeEpisodic:
        def __init__(self, c):
            self.db = c

        def fragment_and_store(self, *a, **k):
            pass

    class FakeMI:
        def __init__(self, c):
            self.episodic = FakeEpisodic(c)

    mi = FakeMI(conn)
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = mi
    return k, DocumentDataStore.get_for(mi)


def _patched(kernel_fn):
    with patch("backend.agent.caducean_trajectory.get_trajectory_recorder") as gtr, \
         patch("backend.gateway.iris_ffi.ffi_immortus_chain_append") as ffi:
        gtr.return_value.get_latest_coordinate.return_value = None
        result = kernel_fn()
        return result


def test_t2_raw_crawler_row_extracts_sources_and_har():
    k, store = _make_kernel()
    show = {
        "format": "json",
        "content": "--- Source: http://x.com/a ---\ntext\n--- Source: http://x.com/b ---\nmore",
        "variants": {"json": "..."},
        "source_tool": "crawler_query",
        "har_path": "data/har/job1.har",
    }

    def run():
        k._store_document_data("raw1", show, "untrusted", "t1", "c1")

    _patched(run)
    row = store.get("raw1")
    assert row["source_document_id"] is None
    assert row["har_path"] == "data/har/job1.har"
    assert row["sources"] == [
        {"url": "http://x.com/a", "title": "http://x.com/a"},
        {"url": "http://x.com/b", "title": "http://x.com/b"},
    ]


def test_t2_synthesized_show_links_to_raw_row():
    k, store = _make_kernel()
    raw_show = {
        "format": "json",
        "content": "--- Source: http://x.com/a ---\ntext",
        "variants": {"json": "..."},
        "source_tool": "crawler_query",
        "har_path": "data/har/job1.har",
    }
    syn_show = {
        "format": "markdown",
        "content": "# Summary of the crawl",
        "variants": {"markdown": "# Summary of the crawl"},
        "source_tool": "crawler_query",
    }

    def run():
        k._store_document_data("raw1", raw_show, "untrusted", "t1", "c1")
        k._store_document_data("syn1", syn_show, "untrusted", "t2", "c1")

    _patched(run)
    raw = store.get("raw1")
    syn = store.get("syn1")
    assert raw["source_document_id"] is None
    assert syn["source_document_id"] == "raw1"
    assert syn["sources"] == [{"url": "http://x.com/a", "title": "http://x.com/a"}]
    assert syn["har_path"] == "data/har/job1.har"


def test_t2_explicit_provenance_respected():
    k, store = _make_kernel()
    show = {
        "format": "markdown",
        "content": "rendered",
        "variants": {"markdown": "rendered"},
        "source_tool": "crawler_query",
        "source_document_id": "explicit_parent",
        "sources": [{"url": "http://explicit.com", "title": "E"}],
        "har_path": "data/har/explicit.har",
    }

    def run():
        k._store_document_data("d1", show, "untrusted", "t1", "c1")

    _patched(run)
    row = store.get("d1")
    assert row["source_document_id"] == "explicit_parent"
    assert row["sources"] == [{"url": "http://explicit.com", "title": "E"}]
    assert row["har_path"] == "data/har/explicit.har"


def test_t2_capture_tool_result_threads_har_path():
    k, store = _make_kernel()
    crawl_result = {
        "url": "http://x.com/a",
        "markdown": "# page",
        "har_path": "data/har/job9.har",
    }

    def run():
        return k._capture_tool_result("crawler_query", crawl_result, "t1", "c1")

    doc_id = _patched(run)
    assert doc_id is not None
    row = store.get(doc_id)
    assert row["har_path"] == "data/har/job9.har"
    assert row["format"] == "json"
