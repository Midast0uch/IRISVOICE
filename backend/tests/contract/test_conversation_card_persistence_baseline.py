"""BASELINE — Wave 0, specs/task-card-v2-liquid-ink.

Pinned behavior as of 2026-08-19. Originally asserted that NO card state was
persisted anywhere. INVERTED BY T4 (REQ-4 AC1, landed 2026-08-19): card
state now persists — but ALONGSIDE messages, not by changing
`ConversationMessage`. See design note below.

Inverted by: T4 — landed. T4's design keeps `ConversationMessage` and
`ConversationContext.add_message()` EXACTLY as they were (a dedicated
`conversation_cards` table + `ConversationContextStore.save_card()` /
`get_cards_for_conversation()` carries card state instead — mirrors the
shape `document_store.py` already uses for rich documents). Consequently:
  - `TestExactMessageFieldSet` and the `ConversationMessage`/`add_message`
    assertions in `TestNoCardStatePersisted` STILL HOLD, unchanged, and are
    kept below as a live regression guard — the field set genuinely did not
    change, so weakening them would misrepresent what T4 did.
  - `TestRoundTripLoss` is renamed `TestCardStatePersistsSeparately` and its
    assertions are INVERTED: the old claim was "nothing about a card
    survives a round trip because nothing about a card was ever written";
    it is now false — a card written via `save_card()` DOES survive a real
    save/reload round trip, scoped to its conversation, without touching the
    message stream at all.
  - New classes below cover AC3 (conversation scoping), AC5 (mid-execution
    restore), and the "failed write never raises" rule — see T4's report.
"""

import dataclasses
import inspect
import sqlite3
import tempfile
from pathlib import Path

import pytest

from backend.agent.conversation_context_store import (
    CardState,
    CardStepSnapshot,
    ConversationContext,
    ConversationContextStore,
    ConversationMessage,
)

# The handoff pin said a stored message is "{role, content, turn_id}". Reading
# the dataclass shows a fourth field, `timestamp`, that the pin omitted — pin
# the ACTUAL field set, not the summarized one.
ACTUAL_MESSAGE_FIELDS = {"role", "content", "timestamp", "turn_id"}

FORBIDDEN_CARD_NAMES = {"card_id", "card_relation", "cards", "task_id", "card_state"}


@pytest.fixture
def store():
    """Isolated store backed by a tmp_path SQLite DB — never touches
    data/databases/conversation_contexts.db."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="iris_test_card_baseline_"))
    db_path = tmp_dir / "test_contexts.db"
    s = ConversationContextStore(db_path=db_path)
    yield s
    s.close()
    import shutil

    shutil.rmtree(str(tmp_dir), ignore_errors=True)


class TestExactMessageFieldSet:
    def test_conversation_message_field_set(self):
        """Pin the EXACT field set of a stored message via dataclasses.fields
        — this absence (no card_id/card_relation) is the root cause of
        vanishing cards, so it must be pinned exactly, not loosely."""
        field_names = {f.name for f in dataclasses.fields(ConversationMessage)}
        assert field_names == ACTUAL_MESSAGE_FIELDS


class TestNoCardStatePersisted:
    """STILL TRUE after T4 — by design, not by omission. T4 added card
    persistence as a SEPARATE table/methods (`save_card`,
    `get_cards_for_conversation`) rather than by touching
    `ConversationMessage` or `add_message`, so these three assertions did
    not need to change. Kept as a live regression guard: if a future change
    folds card fields into the message record instead of keeping them
    separate, this is the test that should catch it."""

    def test_message_dataclass_has_no_card_fields(self):
        field_names = {f.name for f in dataclasses.fields(ConversationMessage)}
        for forbidden in FORBIDDEN_CARD_NAMES:
            assert forbidden not in field_names, (
                f"ConversationMessage unexpectedly carries a '{forbidden}' "
                "field today — the baseline is stale or T4 has landed."
            )

    def test_add_message_signature_has_no_card_parameter(self):
        """add_message(role, content, turn_id=None) today — no card
        argument of any kind."""
        sig = inspect.signature(ConversationContext.add_message)
        param_names = set(sig.parameters.keys()) - {"self"}
        assert param_names == {"role", "content", "turn_id"}
        for forbidden in FORBIDDEN_CARD_NAMES:
            assert forbidden not in param_names, (
                f"add_message unexpectedly accepts a '{forbidden}' parameter "
                "today — the baseline is stale or T4 has landed."
            )

    def test_add_message_rejects_unknown_card_kwarg(self):
        """add_message has no **kwargs catch-all, so passing a card_id
        keyword today raises TypeError rather than being silently accepted."""
        ctx = ConversationContext(conversation_id="conv_card_baseline")
        with pytest.raises(TypeError):
            ctx.add_message(role="user", content="hi", card_id="card_1")


class TestRoundTripLoss:
    """STILL TRUE after T4, for the same reason as TestNoCardStatePersisted:
    the MESSAGE round trip (save()/get_or_restore()) never touches card
    state — cards round-trip through save_card()/get_cards_for_conversation()
    instead, exercised in TestCardStatePersistsSeparately below."""

    def test_round_trip_through_real_save_load_drops_any_card_notion(self, store):
        """Round-trip a message through the store's real save()/get_or_restore()
        path (SQLite, tmp_path-isolated). After the round trip, the recovered
        message carries only role/content/timestamp/turn_id — nothing about a
        card survives, because nothing about a card was ever written INTO A
        MESSAGE (card state now lives in its own table — see below)."""
        ctx = ConversationContext(conversation_id="conv_roundtrip")
        ctx.add_message(role="user", content="What's the weather?", turn_id="turn_1")
        ctx.add_message(role="assistant", content="Sunny.", turn_id="turn_1")

        assert store.save("conv_roundtrip", ctx) is True

        restored = store.get_or_restore("conv_roundtrip")
        assert restored is not None
        assert len(restored.messages) == 2

        for msg in restored.messages:
            field_names = {f.name for f in dataclasses.fields(msg)}
            assert field_names == ACTUAL_MESSAGE_FIELDS
            for forbidden in FORBIDDEN_CARD_NAMES:
                assert not hasattr(msg, forbidden), (
                    f"Recovered message unexpectedly carries '{forbidden}' "
                    "after round-trip — the baseline is stale or T4 has landed."
                )

        # And the raw serialized form (what actually hits disk) is equally
        # innocent of card state — asserted via to_dict(), the exact shape
        # save() persists.
        serialized = ctx.to_dict()
        for msg_dict in serialized["messages"]:
            assert set(msg_dict.keys()) == ACTUAL_MESSAGE_FIELDS

    def test_message_cap_deterministic_for_round_trip(self, store):
        """Pin MAX_MESSAGES_PER_CONV eviction only insofar as it is needed to
        make the round-trip test above deterministic — i.e. that a small,
        well-under-cap message count round-trips without truncation."""
        from backend.agent.conversation_context_store import MAX_MESSAGES_PER_CONV

        ctx = ConversationContext(conversation_id="conv_cap_check")
        ctx.add_message(role="user", content="one")
        ctx.add_message(role="assistant", content="two")
        assert len(ctx.messages) == 2 < MAX_MESSAGES_PER_CONV

        store.save("conv_cap_check", ctx)
        restored = store.get_or_restore("conv_cap_check")
        assert restored is not None
        assert len(restored.messages) == 2


# ── T4 inversion: card state now persists — via save_card()/            ──
# ── get_cards_for_conversation(), never via ConversationMessage.        ──


def _make_card(card_id: str, conversation_id: str, terminal_state: str = "done") -> CardState:
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
        terminal_state=terminal_state,
    )


class TestCardStatePersistsSeparately:
    """INVERTS the old baseline claim. Card state now round-trips through a
    real save/reload — just not through ConversationMessage/add_message
    (those stay exactly as pinned above)."""

    def test_card_round_trips_through_real_save_and_reload(self, store):
        card = _make_card("card_1", "conv_card_rt")
        assert store.save_card(card) is True

        restored = store.get_cards_for_conversation("conv_card_rt")
        assert len(restored) == 1
        got = restored[0]
        assert got.card_id == "card_1"
        assert got.conversation_id == "conv_card_rt"
        assert got.plan_title == "Research the weather"
        assert got.mode == "agentic"
        assert got.current_step == 2
        assert got.total_steps == 2
        assert [s.id for s in got.steps] == ["s1", "s2"]
        assert [s.status for s in got.steps] == ["done", "done"]
        assert got.terminal_state == "done"

    def test_duplicate_card_id_updates_rather_than_duplicates(self, store):
        card = _make_card("card_dup", "conv_dup")
        assert store.save_card(card) is True
        card.plan_title = "Revised plan"
        card.current_step = 3
        assert store.save_card(card) is True

        restored = store.get_cards_for_conversation("conv_dup")
        assert len(restored) == 1
        assert restored[0].plan_title == "Revised plan"
        assert restored[0].current_step == 3


class TestCardScopedToConversation:
    """REQ-4 AC3: a card must never appear in a conversation it was not
    created in."""

    def test_card_in_conversation_a_never_appears_in_b(self, store):
        store.save_card(_make_card("card_a", "conv_a"))
        store.save_card(_make_card("card_b", "conv_b"))

        cards_a = store.get_cards_for_conversation("conv_a")
        cards_b = store.get_cards_for_conversation("conv_b")

        assert [c.card_id for c in cards_a] == ["card_a"]
        assert [c.card_id for c in cards_b] == ["card_b"]

    def test_unknown_conversation_returns_no_cards(self, store):
        store.save_card(_make_card("card_x", "conv_x"))
        assert store.get_cards_for_conversation("conv_never_seen") == []


class TestMidExecutionCardRestoresUnknown:
    """REQ-4 AC5: a card that was mid-execution (never reached a terminal
    write) restores as terminated-unknown, never as perpetually running.
    Resolved on READ (get_cards_for_conversation), not on write/shutdown —
    a crash never gets a turn to run a shutdown-time write path, so read-time
    is the only place this transform is guaranteed to run."""

    def test_running_card_restores_as_terminated_unknown(self, store):
        card = _make_card("card_mid", "conv_mid", terminal_state="running")
        store.save_card(card)

        restored = store.get_cards_for_conversation("conv_mid")
        assert len(restored) == 1
        assert restored[0].terminal_state == "terminated_unknown"

    def test_already_terminal_card_is_left_alone(self, store):
        card = _make_card("card_done", "conv_done", terminal_state="fail")
        store.save_card(card)

        restored = store.get_cards_for_conversation("conv_done")
        assert restored[0].terminal_state == "fail"


class TestFailedCardWriteNeverBlocks:
    """A failed card write must never raise into the caller (T4/T5 shared
    rule) — a broken store degrades gracefully instead of blocking a user
    response."""

    def test_save_card_returns_false_on_write_failure(self, store, monkeypatch):
        def _boom(*args, **kwargs):
            raise sqlite3.OperationalError("simulated disk failure")

        monkeypatch.setattr(store, "_get_connection", _boom)
        card = _make_card("card_boom", "conv_boom")

        # Must not raise.
        result = store.save_card(card)
        assert result is False

    def test_get_cards_for_conversation_returns_empty_on_read_failure(self, store, monkeypatch):
        def _boom(*args, **kwargs):
            raise sqlite3.OperationalError("simulated disk failure")

        monkeypatch.setattr(store, "_fetch_all", _boom)

        # Must not raise.
        result = store.get_cards_for_conversation("conv_anything")
        assert result == []
