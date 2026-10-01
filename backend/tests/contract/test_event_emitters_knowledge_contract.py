"""KNOWLEDGE rule emitters (docs/Design/EVENT_TAXONOMY.md, build step 2): research cross-check
-> CLAIM_CORROBORATED / CLAIM_UPDATED / BELIEF_STALE, a landed research record -> OBSERVED, a
walled source -> SOURCE_UNRELIABLE; ``links.claim`` is the stable claim id. Each test drives the
real writer (``emit_event``) on a temp store - no stand-in for the record - and pins what lands
in ``memory_events``. The alphabet is never widened: every label here is already registered."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

import backend.gateway.iris_ffi as _ffi
from backend.agent import research_memory as rm
from backend.memory import memory_events as me


@pytest.fixture()
def store(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="mememit-")) / "memory.db"
    eng = _ffi._PythonFallbackEngine(db_path=str(tmp), key_hex="00" * 32)
    monkeypatch.setattr(_ffi, "_engine", eng)
    conn = sqlite3.connect(str(tmp), check_same_thread=False)
    me.ensure_schema(conn)
    yield conn
    conn.close()
    eng._conn.close()


@pytest.fixture()
def inline_lane(store, monkeypatch):
    """memory_events.submit runs its function NOW on the temp store (the lane is
    covered by its own tests); everything else is the real code."""
    monkeypatch.setattr(me, "submit", lambda mi, fn, **kw: bool(getattr(me, fn)(store, **kw)) or True)
    return store


def _rows(conn, label=None):
    cur = conn.execute("SELECT * FROM memory_events" + (" WHERE label = ?" if label else "")
                       + " ORDER BY ts, rowid", (label,) if label else ())
    cols = [d[0] for d in cur.description]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in out:
        for k in ("links", "payload"):
            r[k] = json.loads(r[k]) if r[k] else None
    return out


# ── KNOWLEDGE ───────────────────────────────────────────────────────────────

PRIOR_URL = "https://a.example/old"


COST = {"text": "The Foo Bar rocket costs 50 million dollars", "urls": [PRIOR_URL]}
PRICE = {"text": "The Foo Bar rocket price is 70 dollars", "urls": []}


def _prior(created="2026-09-01T00:00:00Z", claims=(COST,)):
    return {"id": "research_1", "query": "foo bar rocket", "summary": "", "created_at": created,
            "claims": list(claims)}


class _Lookup:
    def __init__(self, records):
        self._records = records

    async def wait(self):
        return self._records


def _attach(records, new_text, thread="s1"):
    result = {"success": True, "content": "body"}
    return asyncio.run(rm.attach_prior(result, _Lookup(records), new_text, thread_id=thread))


def test_claim_id_is_stable_across_a_changed_number_and_differs_by_subject():
    a = rm.claim_id("The Foo Bar rocket costs 50 million dollars")
    assert a == rm.claim_id("the foo bar rocket costs 70 million dollars!")  # same subject
    assert a != rm.claim_id("The Baz Qux satellite costs 50 million dollars")


def test_a_confirmed_claim_from_an_independent_host_is_corroboration(inline_lane):
    new = "--- Source: https://b.example/new ---\nThe Foo Bar rocket costs 50 million dollars per launch."
    _attach([_prior()], new)
    ev = _rows(inline_lane, "CLAIM_CORROBORATED")
    assert len(ev) == 1
    assert (ev[0]["family"], ev[0]["evidence"], ev[0]["valence"]) == ("knowledge", "corroboration", "advances")
    assert ev[0]["links"]["claim"] == rm.claim_id("The Foo Bar rocket costs 50 million dollars")
    assert ev[0]["thread_id"] == "s1" and ev[0]["payload"]["prior_id"] == "research_1"


def test_a_confirmation_from_the_same_host_is_only_the_systems_own_check(inline_lane):
    new = f"--- Source: {PRIOR_URL} ---\nThe Foo Bar rocket costs 50 million dollars per launch."
    _attach([_prior()], new)
    (ev,) = _rows(inline_lane, "CLAIM_CORROBORATED")
    assert ev["evidence"] == "verifier"  # inside evidence: not independent


def test_a_changed_claim_is_claim_updated_and_shares_the_claim_hyperedge(inline_lane):
    new = "--- Source: https://b.example/new ---\nThe Foo Bar rocket price is now 90 dollars."
    _attach([_prior(claims=(PRICE,))], new)
    (ev,) = _rows(inline_lane, "CLAIM_UPDATED")
    assert ev["links"]["claim"] == rm.claim_id("The Foo Bar rocket price is 70 dollars")
    assert ev["evidence"] == "verifier"


def test_an_old_claim_nothing_rechecked_is_belief_stale_a_recent_one_is_not(inline_lane):
    unrelated = "Nothing about the topic here at all, just other words."
    _attach([_prior(created="2020-01-01T00:00:00Z", claims=(COST, PRICE))], unrelated)
    stale = _rows(inline_lane, "BELIEF_STALE")
    assert len(stale) == 2 and stale[0]["payload"]["prior_date"] == "2020-01-01"
    inline_lane.execute("DELETE FROM memory_events")
    today = time.strftime("%Y-%m-%dT00:00:00Z")
    _attach([_prior(created=today, claims=(COST, PRICE))], unrelated)
    assert _rows(inline_lane) == []


def test_no_prior_means_no_knowledge_events(inline_lane):
    _attach([], "anything")
    assert _rows(inline_lane) == []


def test_a_landed_research_record_is_observed_evidence_none(store, monkeypatch):
    monkeypatch.setattr(me, "submit", lambda mi, fn, **kw: bool(getattr(me, fn)(store, **kw)) or True)
    rec = rm._normalize({
        "query": "foo bar rocket", "summary": "s", "session_id": "s1", "job_id": "j1",
        "claims": [{"text": "The Foo Bar rocket costs 50 million dollars", "urls": ["https://a.example/1"]}],
    })
    rm._write_record(rec, mi=type("MI", (), {})())
    (ev,) = _rows(store, "OBSERVED")
    assert (ev["family"], ev["evidence"], ev["thread_id"]) == ("knowledge", "none", "s1")
    assert ev["payload"]["document_id"] == rec["id"]
    assert ev["payload"]["claim_ids"] == [rm.claim_id(rec["claims"][0]["text"])]


def test_one_claim_from_two_independent_hosts_is_corroboration_across_sources(store):
    claims = [{"text": "The Foo Bar rocket costs 50 million dollars", "urls": ["https://a.example/1"]},
              {"text": "Foo Bar rocket costs 50 million dollars", "urls": ["https://www.b.example/2"]}]
    assert rm._corroborated(claims) is True
    same_host = [dict(c, urls=["https://a.example/1"]) for c in claims]
    assert rm._corroborated(same_host) is False
    # Same subject but different numbers is a conflict, not corroboration.
    conflict = [dict(claims[0]), {"text": "The Foo Bar rocket costs 80 million dollars",
                                  "urls": ["https://b.example/2"]}]
    assert rm._corroborated(conflict) is False
    me.record_research_observed(store, thread_id="s1", document_id="d", claim_ids=["c"], sources=2,
                                corroborated=True)
    assert _rows(store, "OBSERVED")[0]["evidence"] == "corroboration"


def test_a_source_turning_walled_is_source_unreliable_once_per_wall(store, monkeypatch):
    from backend.agent import tool_errors

    tool_errors.reset_wall_ledger_for_testing()
    calls = []
    monkeypatch.setattr(me, "submit", lambda mi, fn, **kw: calls.append((fn, kw)) or True)
    import backend.memory as memory_pkg

    monkeypatch.setattr(memory_pkg, "get_memory_interface", lambda: object())
    tool_errors.record_wall("Walled.example")
    tool_errors.record_wall("walled.example")          # inside the TTL: no new fact
    tool_errors.record_wall("other.example")
    tool_errors.reset_wall_ledger_for_testing()
    assert [(fn, kw["domain"]) for fn, kw in calls] == [
        ("record_source_unreliable", "walled.example"), ("record_source_unreliable", "other.example")]
    me.record_source_unreliable(store, domain="walled.example")
    (ev,) = _rows(store, "SOURCE_UNRELIABLE")
    assert (ev["family"], ev["evidence"], ev["cause_key"]) == ("knowledge", "verifier", "no|world|blocked")
    assert ev["payload"] == {"domain": "walled.example", "reason": "wall"}
