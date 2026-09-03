"""Standing CDD harness — card lifecycle replay (REQ-3 / REQ-4).

Replays start -> continue -> branch -> switch -> rehydrate through the REAL
card-identity resolution (`AgentKernel._resolve_card_identity`) and the REAL
card persistence path (`ConversationContextStore.save_card` /
`get_cards_for_conversation`, plus the kernel's own `_persist_card_snapshot`
through the background write queue) on EVERY run. This is the gap-finding
instrument from design.md Verification Strategy Tier 4: if we test correctly,
we find the gaps. Runs head-less (no live web, no TTS) and exits non-zero on
any contract/behavior break.

Coverage:
  - start:     a task:start creates exactly one card.
  - continue:  a follow-up with relation "continues" reuses the SAME card
               (no second card) — REQ-3.
  - branch:    a follow-up with relation "new" creates a DISTINCT second card.
  - switch:    switching conversation context does not lose the first
               conversation's card.
  - rehydrate: after a simulated reload/switch-back, the card is restored
               from persistence.

Run:  python scripts/validate_der_card_lifecycle.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

# Make the backend importable when run from repo root or backend/.
# backend is a package under the REPO ROOT (C:\dev\IRISVOICE), so the
# repo root (not backend/) must be on sys.path.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if os.path.isdir(os.path.join(_REPO, "backend")):
    sys.path.insert(0, _REPO)


class _Failures:
    def __init__(self):
        self.items = []

    def check(self, name, cond):
        if cond:
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name}")
            self.items.append(name)


def _make_card(card_id: str, conversation_id: str) -> "CardState":
    from backend.agent.conversation_context_store import CardState, CardStepSnapshot

    return CardState(
        card_id=card_id,
        conversation_id=conversation_id,
        card_relation="new",
        plan_title="Research the weather",
        mode="agentic",
        steps=[
            CardStepSnapshot(id="s1", description="Search", status="done", tool_name="web_search"),
            CardStepSnapshot(id="s2", description="Summarize", status="done"),
        ],
        current_step=2,
        total_steps=2,
        terminal_state="done",
    )


def _bare_kernel(session_id: str):
    """A REAL AgentKernel object carrying only the state `_resolve_card_identity`
    needs — constructed via `__new__` so the heavy `__init__` side effects
    (LFM model warm-up thread, ModelRouter, etc.) never run in the harness.
    The method under test is the real production code, called on a
    minimal-but-real instance (mirrors validate_der_integrity.py's pattern of
    calling real kernel methods on a minimal object)."""
    from backend.agent.agent_kernel import AgentKernel

    kern = AgentKernel.__new__(AgentKernel)
    kern.conversation_id = session_id
    kern._card_by_task = {}
    kern._active_card_id = None
    kern._CARD_REGISTRY_CAP = 200
    return kern


def validate_start_creates_one_card(fail):
    print("start: a task:start creates exactly one card")
    kernel = _bare_kernel("harness-start")
    card_id, relation = kernel._resolve_card_identity("task_start", "initial")
    fail.check("start resolves relation 'new'", relation == "new")
    fail.check("start mints card_task_start", card_id == "card_task_start")
    fail.check("exactly one card registered", len(kernel._card_by_task) == 1)


def validate_continue_reuses_same_card(fail):
    print("continue: a follow-up with relation 'continues' reuses the SAME "
          "card (no second card) — REQ-3")
    kernel = _bare_kernel("harness-continue")
    # First task:start — relation "initial" -> mints the card.
    first_id, first_rel = kernel._resolve_card_identity("task_c", "initial")
    # Second task:start for the SAME task_id -> resolves "continues".
    second_id, second_rel = kernel._resolve_card_identity("task_c", "initial")
    fail.check("first start is 'new'", first_rel == "new")
    fail.check("follow-up resolves 'continues'", second_rel == "continues")
    fail.check("SAME card reused (no second card)", second_id == first_id)
    fail.check("registry holds exactly one card",
               len(set(kernel._card_by_task.values())) == 1)
    # A follow-up with a non-initial origin also continues the active card
    # (a branch WITHIN a card, never a second card — REQ-3 edge case).
    child_id, child_rel = kernel._resolve_card_identity("task_c_child", "sub_loop_split")
    fail.check("non-initial origin continues active card",
               child_rel == "continues" and child_id == first_id)


def validate_branch_creates_distinct_card(fail):
    print("branch: a follow-up with relation 'new' creates a DISTINCT second card")
    kernel = _bare_kernel("harness-branch")
    first_id, first_rel = kernel._resolve_card_identity("task_a", "initial")
    second_id, second_rel = kernel._resolve_card_identity("task_b", "initial")
    fail.check("first start is 'new'", first_rel == "new")
    fail.check("second start is 'new'", second_rel == "new")
    fail.check("DISTINCT second card", second_id != first_id)
    fail.check("registry holds two cards", len(set(kernel._card_by_task.values())) == 2)


def validate_switch_keeps_first_card(fail):
    print("switch: switching conversation context does not lose the first "
          "conversation's card")
    from backend.agent.conversation_context_store import ConversationContextStore

    tmp_dir = Path(tempfile.mkdtemp(prefix="iris_harness_switch_"))
    try:
        store = ConversationContextStore(db_path=tmp_dir / "cards.db")
        store.save_card(_make_card("card_a", "conv_a"))
        store.save_card(_make_card("card_b", "conv_b"))

        # Switch to conv B — A's card is not visible there.
        fail.check("conv B empty of A's card",
                   [c.card_id for c in store.get_cards_for_conversation("conv_b")] == ["card_b"])
        # Switch back to conv A — the card is not lost.
        fail.check("conv A card not lost",
                   [c.card_id for c in store.get_cards_for_conversation("conv_a")] == ["card_a"])
        store.close()
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


def validate_rehydrate_restores_card(fail):
    print("rehydrate: after a simulated reload/switch-back, the card is "
          "restored from persistence")
    from backend.agent.conversation_context_store import ConversationContextStore

    tmp_dir = Path(tempfile.mkdtemp(prefix="iris_harness_rehydrate_"))
    try:
        db_path = tmp_dir / "cards.db"
        store = ConversationContextStore(db_path=db_path)
        store.save_card(_make_card("card_a", "conv_a"))
        store.close()

        # Simulated reload: a BRAND-NEW store instance on the same DB file
        # (fresh connection, reads from disk — a real reload, not a cache).
        store2 = ConversationContextStore(db_path=db_path)
        restored = store2.get_cards_for_conversation("conv_a")
        fail.check("card restored from persistence", len(restored) == 1)
        fail.check("restored card_id matches", restored[0].card_id == "card_a")
        fail.check("restored card content intact", restored[0].plan_title == "Research the weather")
        fail.check("restored steps intact", [s.id for s in restored[0].steps] == ["s1", "s2"])
        store2.close()
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


def validate_kernel_persist_snapshot_rehydrates(fail):
    """The kernel's OWN persistence helper (`_persist_card_snapshot` ->
    `enqueue_card_write` -> CardWriteQueue background thread ->
    `store.save_card`) lands the card in the store, and a switch-away/back
    rehydrates it — the same path the DER emit sites use at task:start."""
    print("kernel persistence path: _persist_card_snapshot lands + rehydrates")
    import backend.agent.conversation_context_store as _ccs

    tmp_dir = Path(tempfile.mkdtemp(prefix="iris_harness_kernel_persist_"))
    _orig_store = _ccs._store_instance
    tmp_store = None
    try:
        tmp_store = _ccs.ConversationContextStore(db_path=tmp_dir / "cards.db")
        _ccs._store_instance = tmp_store
        _ccs.reset_card_write_queue_for_testing()

        kernel = _bare_kernel("harness-kernel-persist")
        kernel.conversation_id = "conv_a"
        kernel._persist_card_snapshot(
            card_id="card_a",
            conversation_id="conv_a",
            card_relation="new",
            plan_title="Research the weather",
            mode="agentic",
            steps=[
                {"id": "s1", "description": "Search", "status": "done", "toolName": "web_search"},
                {"id": "s2", "description": "Summarize", "status": "done"},
            ],
            total_steps=2,
            terminal_state="done",
        )
        drained = _ccs.get_card_write_queue().wait_idle(timeout=3.0)
        fail.check("card write queue drained", drained)
        # Switch to conv B (empty), switch back to A -> rehydrates.
        fail.check("conv B empty after switch",
                   tmp_store.get_cards_for_conversation("conv_b") == [])
        restored = tmp_store.get_cards_for_conversation("conv_a")
        fail.check("kernel-persisted card rehydrates",
                   len(restored) == 1 and restored[0].card_id == "card_a")
        fail.check("kernel-persisted card content intact",
                   restored[0].plan_title == "Research the weather")
    finally:
        _ccs._store_instance = _orig_store
        _ccs.reset_card_write_queue_for_testing()
        if tmp_store is not None:
            tmp_store.close()
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


def main() -> int:
    print("=" * 64)
    print("CARD LIFECYCLE REPLAY — STANDING CDD HARNESS (REQ-3 / REQ-4)")
    print("=" * 64)
    fail = _Failures()

    validate_start_creates_one_card(fail)
    validate_continue_reuses_same_card(fail)
    validate_branch_creates_distinct_card(fail)
    validate_switch_keeps_first_card(fail)
    validate_rehydrate_restores_card(fail)
    validate_kernel_persist_snapshot_rehydrates(fail)

    print("-" * 64)
    if fail.items:
        print(f"HARNESS FAILED: {len(fail.items)} check(s) broken")
        for name in fail.items:
            print(f"  - {name}")
        return 1
    print("HARNESS PASSED: all card-lifecycle contracts hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())