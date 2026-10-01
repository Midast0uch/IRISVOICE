"""Exit-driven admission in a PhaseDomain ("natural exit", owner 2026-10-01).

Measured (oracle.md 19.6/19.7): the timed gate admits every participant within
max_wait_s, so up to 8 Oracle runs shared 4 cores and reply decisions waited
(p50 398-506 ms). With admission on EXITS (a run slot frees when a decision is
done; slots = the CPU's run capacity), due-time order from each decision's
position on the dial, and right of way for priority classes: reply p50 203 ms,
no starvation (worst 1.7 s). Two earlier shapes failed and are pinned here:
one shared position per consumer (route worst 8.9 s) and ordering by the LIVE
position (a passed firing point sent a waiter a full turn back: 5.4 s).
"""
from __future__ import annotations

import threading
import time

from backend.agent.call_context import CallClass, call_class_scope
from backend.agent.phase_domain import PhaseDomain


def _domain(cap=1):
    return PhaseDomain("test.exit", period_s=0.3, max_wait_s=0.3, k=0.6,
                       capacity_fn=lambda: cap)


def test_a_slot_frees_only_when_a_decision_exits():
    d = _domain(cap=1)
    t1 = d.enter("s:a")
    got = threading.Event()

    def second():
        d.exit(d.enter("s:b"))
        got.set()

    threading.Thread(target=second, daemon=True).start()
    assert not got.wait(0.5), "a second run started while the only slot was busy"
    d.exit(t1)
    assert got.wait(2), "the waiter was not admitted after the exit"


def test_priority_has_right_of_way():
    d = _domain(cap=1)
    t1 = d.enter("s:busy")
    order = []

    def normal():
        d.exit(d.enter("s:norm"))
        order.append("normal")

    def reply():
        with call_class_scope(CallClass.USER_TURN):
            d.exit(d.enter("s:reply"))
        order.append("reply")

    tn = threading.Thread(target=normal, daemon=True)
    tn.start()
    time.sleep(0.2)                       # the normal decision waits first
    tr = threading.Thread(target=reply, daemon=True)
    tr.start()
    time.sleep(0.2)
    d.exit(t1)
    tn.join(3)
    tr.join(3)
    assert order[0] == "reply", f"a reply decision waited behind a background one: {order}"


def test_a_busy_consumer_does_not_starve():
    """Many waiters of ONE consumer among others: each decision holds its own
    position, ordered by due time - none waits much beyond the queue ahead."""
    d = _domain(cap=1)
    lock = threading.Lock()
    done = []

    def work(cid, n):
        for _ in range(n):
            t0 = time.perf_counter()
            tok = d.enter(f"s:{cid}")
            time.sleep(0.01)
            d.exit(tok)
            with lock:
                done.append((cid, time.perf_counter() - t0))

    threads = [threading.Thread(target=work, args=("tool_choice", 12), daemon=True)]
    threads += [threading.Thread(target=work, args=(c, 2), daemon=True)
                for c in ("mode", "done", "review", "narration", "guard", "event")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert len(done) == 24
    worst = max(w for c, w in done if c == "tool_choice")
    # 24 decisions of 10 ms on one slot + at most ~one period of phase spacing.
    assert worst < 1.5, f"the busy consumer starved: worst wait {worst:.2f}s"


def test_capacity_fault_fails_open():
    d = PhaseDomain("test.exit.bad", period_s=0.3, max_wait_s=0.3, k=0.6,
                    capacity_fn=lambda: 1 / 0)
    tok = d.enter("s:x")
    d.exit(tok)
    assert d._in_flight == 0
