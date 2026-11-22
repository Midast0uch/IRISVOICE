"""The DER execution ledger has a growth budget and is written off the step (2026-11-22).

Measured: data/der_ledger/der_execution_ledger.json was 22.4 MB (31,212 attempts, 9,504
tasks of every conversation) and was rewritten whole, indented, INLINE on every step
finish - the top frame of the step loop in 13 of 33 stack samples of _der_post_step
(c10 / c15 above their reply standards). Guards:
  - the file keeps only the newest _PERSIST_TASKS_MAX tasks (and their attempts);
  - persist() returns without writing on the caller's thread (the der_ledger lane writes);
  - a burst of persists from one instance is ONE write;
  - read-after-write in one process still holds (a new instance waits for the queued write).
"""
from __future__ import annotations

import json
import os
import threading

from backend.agent import der_execution_ledger as led


def _fill(lg, n):
    for i in range(n):
        a = lg.open_attempt(f"task-{i}", "s1", action_key="k", tool="read_file")
        lg.close_attempt(a, led.OUTCOME_SUCCESS, verified_label="VERIFIED")


def _flush():
    from backend.utils.durability_queue import lane

    lane("der_ledger").flush(10.0)


def test_the_file_keeps_only_the_newest_tasks(tmp_path):
    lg = led.ExecutionLedger(conversation_id="c", storage_path=str(tmp_path))
    _fill(lg, led._PERSIST_TASKS_MAX + 200)
    assert lg.persist() is True
    _flush()
    data = json.loads((tmp_path / "der_execution_ledger.json").read_text(encoding="utf-8"))
    assert len(data["tasks"]) == led._PERSIST_TASKS_MAX
    assert "task-0" not in data["tasks"] and f"task-{led._PERSIST_TASKS_MAX + 199}" in data["tasks"]
    assert {a["task_id"] for a in data["attempts"]} <= set(data["tasks"])


def test_persist_does_not_write_on_the_callers_thread(tmp_path, monkeypatch):
    lg = led.ExecutionLedger(conversation_id="c", storage_path=str(tmp_path))
    _fill(lg, 3)
    writers = []
    real = led.ExecutionLedger._write_now

    def spy(self, ev=None):
        writers.append(threading.current_thread().name)
        return real(self, ev)

    monkeypatch.setattr(led.ExecutionLedger, "_write_now", spy)
    caller = threading.current_thread().name
    assert lg.persist() is True
    _flush()
    assert writers and caller not in writers


def test_a_burst_of_persists_is_one_write_and_a_new_instance_reads_it(tmp_path, monkeypatch):
    from backend.utils.durability_queue import lane

    gate = threading.Event()
    lane("der_ledger").submit("hold", gate.wait, 5.0)       # keep the lane busy for the burst
    lg = led.ExecutionLedger(conversation_id="c", storage_path=str(tmp_path))
    n = []
    real = led.ExecutionLedger._write_now
    monkeypatch.setattr(led.ExecutionLedger, "_write_now",
                        lambda self, ev=None: (n.append(1), real(self, ev))[1])
    for i in range(20):
        _fill(lg, 1) if i == 19 else None
        lg.persist()
    gate.set()
    lg2 = led.ExecutionLedger(conversation_id="c", storage_path=str(tmp_path))   # waits for the write
    assert len(n) == 1
    assert lg2.get_task("task-0") is not None
    assert os.path.isfile(tmp_path / "der_execution_ledger.json")
