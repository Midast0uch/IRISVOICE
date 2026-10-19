"""Guards (2026-10-19, Kyudo proposal 3): every memory write carries a trust
channel, and IRIS's own bookkeeping is never filed as the user's words.

Measured (live store, read-only):
  - SemanticStore fed EVERY category to the coordinate graph as a user
    statement: 2,775 card-footprint rows (task JSON: steps, tools, outcome) were
    keyword-matched as the user's words, and each task then counted twice (its
    card and its episode summary) - with W6 accumulation that raised confidence;
  - the episode index carried no channel on 2,857 of 2,857 rows, so the
    resonance channel weight (Kyudo Part 3) never applied;
  - three trust vocabularies (PACMAN zones, document trust labels, HyphaChannel)
    with no mapping between them.
Each guard below FAILS on the code before this change (the user-preference case
is the control).
"""
import inspect
import sqlite3
import tempfile
from pathlib import Path

import pytest

from backend.memory.card_footprint import save_card_footprint
from backend.memory.semantic import SemanticStore


class _Recorder:
    def __init__(self):
        self.statements = []

    def ingest_statement(self, text):
        self.statements.append(text)


class _Memory:
    def __init__(self, semantic):
        self.semantic = semantic


@pytest.fixture
def semantic():
    tmp = Path(tempfile.mkdtemp(prefix="iris_test_trust_doors_"))
    store = SemanticStore(str(tmp / "semantic.db"), biometric_key=b"test_key_32_bytes_long_for_testing_")
    store._mycelium = _Recorder()
    yield store
    import gc
    import shutil

    del store
    gc.collect()
    shutil.rmtree(str(tmp), ignore_errors=True)


def test_a_card_footprint_is_not_a_user_statement(semantic):
    save_card_footprint(
        _Memory(semantic), card_id="card_t1", conversation_id="conv_t1",
        objective="Add balance_on method", steps=[{"id": "s1", "verb": "edit"}],
        tools_used=["web_search"], files_touched=[], outcome="converged",
    )
    assert semantic._mycelium.statements == []


def test_a_skill_record_is_not_a_user_statement(semantic):
    semantic.update("named_skills", "skill_x", '{"tool_sequence": ["web_search"]}', source="crystallisation")
    assert semantic._mycelium.statements == []


def test_a_user_preference_is_a_user_statement(semantic):
    semantic.update("user_preferences", "response_length", "concise", source="user_set")
    assert semantic._mycelium.statements == ["user_preferences response_length: concise"]


def test_one_trust_vocabulary_and_unknown_fails_closed():
    from backend.memory.mycelium.kyudo import HyphaChannel, channel_for_trust_label, channel_for_zone

    assert channel_for_zone("trusted") == HyphaChannel.USER
    assert channel_for_zone("tool") == HyphaChannel.VERIFIED
    assert channel_for_zone("reference") == HyphaChannel.EXTERNAL
    assert channel_for_zone("system") == HyphaChannel.SYSTEM
    assert channel_for_zone("made-up") == HyphaChannel.UNTRUSTED
    assert channel_for_zone(None) == HyphaChannel.UNTRUSTED
    assert channel_for_trust_label("trusted") == HyphaChannel.VERIFIED
    assert channel_for_trust_label("untrusted") == HyphaChannel.EXTERNAL
    assert channel_for_trust_label("") == HyphaChannel.UNTRUSTED


def test_legacy_episode_index_rows_get_the_channel_of_what_they_index():
    from backend.memory.mycelium.kyudo import backfill_episode_index_channels

    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE episodes (id TEXT PRIMARY KEY);
        CREATE TABLE context_chunks (id TEXT PRIMARY KEY, zone TEXT);
        CREATE TABLE mycelium_episode_index (episode_id TEXT, source_channel INTEGER);
        INSERT INTO episodes VALUES ('ep1');
        INSERT INTO context_chunks VALUES ('c_user', 'trusted'), ('c_tool', 'tool'),
                                          ('c_web', 'reference'), ('c_odd', 'weird');
        INSERT INTO mycelium_episode_index VALUES ('ep1', NULL), ('c_user', NULL),
            ('c_tool', NULL), ('c_web', NULL), ('c_odd', NULL), ('c_kept', 2), ('orphan', NULL);
    """)
    assert backfill_episode_index_channels(conn) == 5
    got = dict(conn.execute("SELECT episode_id, source_channel FROM mycelium_episode_index"))
    assert got == {"ep1": 3, "c_user": 3, "c_tool": 2, "c_web": 1, "c_odd": 0,
                   "c_kept": 2, "orphan": None}
    assert backfill_episode_index_channels(conn) == 0          # idempotent


def test_new_episode_index_rows_carry_a_channel():
    # Contract on the two production writers in the episodic store: neither may
    # index with an unknown channel again.
    from backend.memory import episodic

    src = inspect.getsource(episodic.EpisodicStore)
    assert "source_channel=None" not in src
    assert "source_channel=3" in src
    assert "channel_for_zone(zone_of.get(chunk_id))" in src


def test_trust_weighted_retrieval_is_measured_in_shadow():
    from backend.agent import write_counters
    from backend.memory.episodic import _shadow_trust_rank

    # web chunk scores 0.80, the user's own note 0.75: weighting (0.7 / 1.2)
    # would put the note first. Shadow: the returned order is unchanged.
    scored = [(0.80, "web text", "w"), (0.75, "user note", "u")]
    before = list(scored)
    n0 = write_counters.get("kyudo.trust_rank.reordered")
    _shadow_trust_rank(scored, {"w": "reference", "u": "trusted"}, limit=1)
    assert scored == before
    assert write_counters.get("kyudo.trust_rank.reordered") == n0 + 1
