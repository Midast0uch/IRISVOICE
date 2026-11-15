"""CLM Wave 2 part A: the durable record of node tool results (conversation_store.tool_results).

Owner decision 2026-11-12: the EXACT text of a node tool result too long to stay in the window goes
to the chat record (data/conversations.db) so a placeholder can carry its id and the real bytes come
back by id. Pinned here: the round trip is exact; the write is QUEUED on lane("tool_results") and
never runs on the caller's thread; get waits for its own queued write, bounded; a refused enqueue
returns False and is counted; the row size and per-conversation row caps hold (oldest rows go
first); rows leave with their conversation (delete) and with truncated turns (truncate).

Real sqlite store in a temp file, exactly as the other conversation_store tests do it
(IRIS_CONVERSATIONS_DB + importlib.reload).
"""
from __future__ import annotations

import importlib
import threading
import time

import pytest

BIG = "x" * 3000   # above TOOL_RESULT_MIN_CHARS (2,500): shorter results are not recorded


@pytest.fixture()
def cs(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_CONVERSATIONS_DB", str(tmp_path / "conversations.db"))
    import backend.conversation_store as store

    importlib.reload(store)
    yield store
    try:
        _drain(store)                     # no job outlives its test's database
    except AssertionError:
        pass
    try:
        store._conn.close()
    except Exception:  # noqa: BLE001
        pass


def _drain(cs) -> None:
    lane = cs._tr_lane()
    deadline = time.monotonic() + 10.0
    while lane.pending() and time.monotonic() < deadline:     # a full queue cannot take the flush marker
        time.sleep(0.01)
    assert lane.flush(10.0)


def _add(cs, rid=None, conv="conv-1", turn="t1", step="s1", ord_=1, content=BIG, tool="read_file", target="a.txt"):
    rid = rid or cs.new_tool_result_id()
    return rid, cs.add_tool_result(rid, conv, turn, step, ord_, tool, target, content)


def _block_lane(cs):
    """Park the lane worker on a gate so queued jobs stay queued; returns the gate."""
    gate, started = threading.Event(), threading.Event()
    cs._tr_lane().submit("gate", lambda: (started.set(), gate.wait(10.0)))
    assert started.wait(5.0)
    return gate


def test_ids_are_unique_hex_and_need_no_store(cs):
    a, b = cs.new_tool_result_id(), cs.new_tool_result_id()
    assert a != b and len(a) == 32 and int(a, 16) >= 0


def test_round_trip_is_exact_with_unicode(cs):
    text = ("Zażółć gęślą jaźń — café \U0001f600 中文\n" * 200) + "tail"
    rid, ok = _add(cs, content=text, conv="conv-9", turn="turn-7", step="step-2", ord_=4,
                   tool="run_command", target="pytest -q")
    assert ok is True
    _drain(cs)
    row = cs.get_tool_result(rid)
    assert row["content"] == text and row["chars"] == len(text) and row["cut"] == 0
    assert (row["conversation_id"], row["turn_id"], row["step_id"], row["call_ord"], row["tool"],
            row["target"]) == ("conv-9", "turn-7", "step-2", 4, "run_command", "pytest -q")
    assert row["created_at"] and set(row) == {
        "id", "conversation_id", "turn_id", "step_id", "call_ord", "tool", "target",
        "chars", "cut", "content", "created_at"}


def test_100k_chars_are_kept_whole_and_a_longer_text_is_cut_with_its_real_length(cs):
    whole = "a" * 100_000
    rid, _ = _add(cs, content=whole)
    over = "b" * 200_000
    rid2, _ = _add(cs, content=over, ord_=2)
    _drain(cs)
    r1, r2 = cs.get_tool_result(rid), cs.get_tool_result(rid2)
    assert (r1["cut"], r1["chars"], len(r1["content"])) == (0, 100_000, 100_000)
    assert (r2["cut"], r2["chars"], len(r2["content"])) == (1, 200_000, cs.TOOL_RESULT_MAX_CHARS)
    assert cs.tool_result_stats()["cut"] == 1


def test_a_short_result_is_not_recorded_and_is_counted(cs):
    rid, ok = _add(cs, content="y" * cs.TOOL_RESULT_MIN_CHARS)      # not LONGER than the minimum
    assert ok is False and cs.tool_result_stats()["skipped_small"] == 1
    _drain(cs)
    assert cs.get_tool_result(rid, wait_s=0.0) is None


def test_get_waits_for_its_own_queued_write_and_returns_it(cs):
    gate = _block_lane(cs)
    rid, ok = _add(cs, content="queued " * 600)
    assert ok is True
    out = {}
    t = threading.Thread(target=lambda: out.update(row=cs.get_tool_result(rid, wait_s=8.0)))
    t.start()
    time.sleep(0.3)
    assert t.is_alive() and "row" not in out, "get must be waiting for the queued write"
    gate.set()
    t.join(10.0)
    assert out["row"] is not None and out["row"]["content"] == "queued " * 600


def test_get_returns_none_after_the_bound_and_for_an_id_never_queued(cs):
    t0 = time.monotonic()
    assert cs.get_tool_result("no-such-id", wait_s=5.0) is None
    assert time.monotonic() - t0 < 1.0, "an id with no queued write must not wait at all"
    gate = _block_lane(cs)
    rid, _ = _add(cs)
    t0 = time.monotonic()
    assert cs.get_tool_result(rid, wait_s=0.3) is None
    assert 0.25 <= time.monotonic() - t0 < 3.0
    gate.set()
    _drain(cs)
    assert cs.get_tool_result(rid) is not None          # the write still landed


def test_eviction_drops_the_oldest_rows_of_that_conversation_only(cs, monkeypatch):
    monkeypatch.setattr(cs, "TOOL_RESULTS_PER_CONVERSATION", 3)
    ids = [_add(cs, rid=f"r{i}", ord_=i)[0] for i in range(5)]
    other, _ = _add(cs, rid="other", conv="conv-2")
    _drain(cs)
    assert [cs.get_tool_result(i, wait_s=0.0) is not None for i in ids] == [False, False, True, True, True]
    assert cs.get_tool_result(other, wait_s=0.0) is not None
    st = cs.tool_result_stats()
    assert st["evicted"] == 2 and st["written"] == 6


def test_delete_conversation_removes_its_rows_and_its_strands_and_nobody_elses(cs):
    root = cs.create_conversation(title="root")["id"]
    strand = cs.create_conversation(title="strand")["id"]
    cs._get_conn().execute("UPDATE conversations SET parent_id = ? WHERE id = ?", (root, strand))
    keep = cs.create_conversation(title="keep")["id"]
    a, _ = _add(cs, conv=root)
    b, _ = _add(cs, conv=strand)
    c, _ = _add(cs, conv=keep)
    d, _ = _add(cs, conv="eval-no-row")            # a conversation id with no conversations row
    _drain(cs)
    assert cs.delete_conversation(root) is True
    assert cs.get_tool_result(a, wait_s=0.0) is None and cs.get_tool_result(b, wait_s=0.0) is None
    assert cs.get_tool_result(c, wait_s=0.0) is not None and cs.get_tool_result(d, wait_s=0.0) is not None


def test_a_row_for_a_conversation_without_a_conversations_row_is_recorded(cs):
    rid, ok = _add(cs, conv="dev-cli-conv-without-row")
    _drain(cs)
    assert ok and cs.get_tool_result(rid)["conversation_id"] == "dev-cli-conv-without-row"


def test_truncate_removes_the_rows_of_removed_turns_only(cs):
    conv = cs.create_conversation(title="t")["id"]
    for role, turn in (("user", "t1"), ("assistant", "t1"), ("user", "t2"), ("assistant", "t2"),
                       ("user", "t3"), ("assistant", "t3")):
        cs.add_message(conv, role, f"{role} {turn}", turn_id=turn)
    rows = {t: _add(cs, conv=conv, turn=t, rid=f"row-{t}")[0] for t in ("t1", "t2", "t3")}
    nullturn, _ = _add(cs, conv=conv, turn=None, rid="row-none")
    _drain(cs)
    cs.truncate_conversation(conv, "msg-3")        # keeps msg-1..3: t1 whole, t2 half, t3 gone
    assert cs.get_tool_result(rows["t1"], wait_s=0.0) is not None
    assert cs.get_tool_result(rows["t2"], wait_s=0.0) is not None, "a turn cut in the middle keeps its rows"
    assert cs.get_tool_result(rows["t3"], wait_s=0.0) is None
    assert cs.get_tool_result(nullturn, wait_s=0.0) is not None


def test_tool_results_for_turn_lists_without_content_in_step_then_call_order(cs):
    for rid, step, ord_ in (("a", "s2", 1), ("b", "s1", 2), ("c", "s1", 1)):
        _add(cs, rid=rid, step=step, ord_=ord_, turn="T")
    _add(cs, rid="z", turn="other")
    _drain(cs)
    rows = cs.tool_results_for_turn("conv-1", "T")
    assert [r["id"] for r in rows] == ["c", "b", "a"]
    assert all("content" not in r and r["chars"] == len(BIG) for r in rows)
    assert cs.tool_results_for_turn("conv-1", "nothing") == []


def test_a_refused_enqueue_returns_false_and_is_counted(cs):
    gate = _block_lane(cs)
    lane = cs._tr_lane()
    filled = 0
    while lane.submit("fill", lambda: None):          # fill the bounded queue behind the gate
        filled += 1
        assert filled < 10_000
    before = cs.tool_result_stats()
    rid, ok = _add(cs)
    after = cs.tool_result_stats()
    assert ok is False
    assert after["refused"] == before["refused"] + 1 and after["queued"] == before["queued"]
    assert after["pending"] == before["pending"], "a refused write must not leave a waiter behind"
    gate.set()
    _drain(cs)
    assert cs.get_tool_result(rid, wait_s=0.0) is None


def _write_thread_idents(cs, lane_obj=None):
    """Run one add and report (idents of the threads that opened the connection BEFORE the lane was
    released, idents after). With a real lane the first list must be empty."""
    seen = []
    orig = cs._get_conn
    cs._get_conn = lambda: (seen.append(threading.get_ident()), orig())[1]
    try:
        gate = _block_lane(cs) if lane_obj is None else None
        _add(cs)
        inline = list(seen)                       # connection use by the time add returned
        if gate is not None:
            gate.set()
            _drain(cs)
        return inline, list(seen)
    finally:
        cs._get_conn = orig


def test_the_write_never_runs_on_the_callers_thread(cs):
    inline, after = _write_thread_idents(cs)
    assert inline == [], "add_tool_result touched sqlite on the calling thread"
    assert after and all(i != threading.get_ident() for i in after)


def test_the_inline_check_would_catch_an_inline_write(cs):
    """Prove the check above can fail: a lane that runs the job on submit puts it on the caller."""
    class InlineLane:
        def submit(self, label, fn, *a, **k):
            fn(*a, **k)
            return True

        def in_worker(self):
            return False

    real = cs._tr_lane
    cs._tr_lane = lambda: InlineLane()
    try:
        inline, _ = _write_thread_idents(cs, lane_obj=InlineLane())
    finally:
        cs._tr_lane = real
    assert inline and all(i == threading.get_ident() for i in inline)


def test_counters_follow_the_life_of_a_row(cs):
    _add(cs)                                     # queued -> written
    _add(cs, content="s")                        # skipped_small
    _drain(cs)
    st = cs.tool_result_stats()
    assert (st["queued"], st["written"], st["skipped_small"], st["refused"], st["write_failed"]) == (1, 1, 1, 0, 0)


def test_a_failing_write_is_counted_and_releases_the_waiter(cs):
    gate = _block_lane(cs)
    rid = cs.new_tool_result_id()
    # a target sqlite cannot bind: the INSERT fails on the lane thread, after add returned True
    assert cs.add_tool_result(rid, "conv-1", "t1", "s1", 1, "read_file", object(), BIG) is True
    t0 = time.monotonic()
    gate.set()
    assert cs.get_tool_result(rid, wait_s=5.0) is None
    assert time.monotonic() - t0 < 4.0, "the waiter must be released when the write fails"
    _drain(cs)
    st = cs.tool_result_stats()
    assert st["write_failed"] == 1 and st["written"] == 0 and st["pending"] == 0
