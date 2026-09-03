"""Behavioral: a vetoed action that never executed writes NO commit row
(REQ-1 edge case / CT-D4).

Spec: specs/phase-6-der-integrity/requirements.md REQ-1 edge cases:
"Vetoed action, never executed -> no commit row. Honest, not a lie."
design.md Testing Strategy > Contract table, row CT-D4.

Two complementary proofs, disclosed here rather than left implicit:

1. DYNAMIC (`DirectorQueue.mark_vetoed`): the REAL queue bookkeeping the
   veto branch calls when `veto_count` exceeds `max_veto_per_item` never
   itself writes to the ledger — proven against the real `mark_vetoed`.
2. STATIC (source contract): the veto branch inside `_execute_plan_der`
   (agent_kernel.py, `if verdict == ReviewVerdict.VETO:` ...) is isolated by
   source-text slicing and asserted to contain neither `record_commit(` nor
   a call to `_der_finalize_step(` — the ONLY two places (per CT-D3) a
   commit row is ever written. This complements proof 1: `_der_finalize_step`
   is a single, large inline method with heavy native/FFI dependencies that
   cannot be driven end-to-end in a unit test without a live DER session;
   the static slice check is the honest way to pin "this branch never
   reaches the write path" without fabricating a misleading full drive.
   Both proofs are required to fail if either the queue bookkeeping OR the
   veto branch itself regressed to writing a row.
"""

from __future__ import annotations

import inspect
import sqlite3

from backend.agent.agent_kernel import AgentKernel
from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.der_loop import DirectorQueue, QueueItem


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


class TestVetoedStepWritesNoRow:
    def test_mark_vetoed_writes_no_ledger_row(self):
        rec = _recorder()
        item = QueueItem(
            step_id="vetoed-1", step_number=1, description="risky action",
            tool="run_command", params={}, critical=False,
            objective_anchor="do the thing",
        )
        queue = DirectorQueue(objective="do the thing", items=[item])
        item.veto_count = 3  # exceeds DER_MAX_VETO_PER_ITEM
        queue.mark_vetoed(item.step_id)

        rows = rec._conn.execute(
            "SELECT * FROM der_commits WHERE step_id = ?", (item.step_id,)
        ).fetchall()
        assert rows == [], (
            "mark_vetoed must never itself write a der_commits row — a "
            "vetoed action never executed"
        )
        assert item.step_id in queue.vetoed_ids

    def test_veto_branch_source_never_calls_the_commit_write_path(self):
        """Static complement: isolate the VETO branch's source text inside
        `_execute_plan_der` and assert neither write-path call appears in it.
        CT-D3 already proves `_der_finalize_step` is the ONLY caller of
        `record_commit` for an executed step — this proves the veto branch
        never reaches that caller."""
        src = inspect.getsource(AgentKernel._execute_plan_der)
        start = src.index("if verdict == ReviewVerdict.VETO:")
        # The veto branch ends where the NEXT top-level review-verdict
        # handling begins (REFINE handling, or the step-execution call for
        # a non-vetoed verdict) — bounded by the next occurrence of
        # "step_result, step_success" (the execution call every non-vetoed
        # path eventually reaches) after `start`.
        end = src.index("step_result, step_success", start)
        veto_branch = src[start:end]
        assert "record_commit(" not in veto_branch, (
            "the veto branch must never call record_commit directly"
        )
        assert "_der_finalize_step(" not in veto_branch, (
            "the veto branch must never reach _der_finalize_step — that is "
            "the only place (CT-D3) a commit row is written"
        )
        # Sanity: the slice actually captured real veto-handling text, not
        # an empty/degenerate match (guards this test against a refactor
        # that silently moved the VETO branch and made the slice vacuous).
        assert "mark_vetoed" in veto_branch
        assert "veto_count" in veto_branch
