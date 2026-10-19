"""Guard (2026-10-19, W9): the domain coordinate is a STABLE ORDINAL.

MEMORY-FOUNDATION-ANALYSIS 5.1: the ``domain`` space's ``domain_id`` axis was
``id / 12`` written as a literal in two places (extractor encode, profile decode).
A new root would have broken it at the 14th key. It is now one pair of functions
in spaces.py over a fixed scale, so a new root takes the next ordinal and no
stored coordinate moves. Each guard FAILS on the code before this change.
"""
import re
import sqlite3
from pathlib import Path

import pytest

from backend.memory.mycelium import spaces
from backend.memory.mycelium.sectors import ensure_sector_tables

MYCELIUM = Path(spaces.__file__).parent

PINNED = {"ai": 0, "web": 1, "data": 2, "devops": 3, "mobile": 4, "systems": 5, "security": 6,
          "finance": 7, "science": 8, "design": 9, "hardware": 10, "gaming": 11, "general": 12}


def test_the_thirteen_ordinals_never_move():
    assert spaces.DOMAIN_IDS == PINNED


def test_encode_keeps_every_stored_coordinate_and_decode_inverts_it():
    for key, ordinal in PINNED.items():
        assert spaces.domain_coordinate(key) == ordinal / 12.0   # what live nodes hold
        assert spaces.domain_from_coordinate(spaces.domain_coordinate(key)) == key


def test_a_new_root_takes_the_next_ordinal_and_shifts_nothing(monkeypatch):
    before = {k: spaces.domain_coordinate(k) for k in PINNED}
    monkeypatch.setitem(spaces.DOMAIN_IDS, "robotics", 13)
    assert {k: spaces.domain_coordinate(k) for k in PINNED} == before
    assert spaces.domain_from_coordinate(spaces.domain_coordinate("robotics")) == "robotics"
    for key, coord in before.items():            # an old coordinate still decodes to its old key
        assert spaces.domain_from_coordinate(coord) == key


def test_no_literal_divisor_is_left_in_the_encoder_or_the_decoder():
    for name in ("extractor.py", "profile.py"):
        src = (MYCELIUM / name).read_text(encoding="utf-8")
        assert not re.search(r"/\s*12(\.0)?\b", src), f"{name} still divides by a literal 12"


def test_the_sector_roots_come_from_the_registry_and_a_new_root_adds_one_row(monkeypatch):
    conn = sqlite3.connect(":memory:")
    ensure_sector_tables(conn)
    roots = {r[0] for r in conn.execute(
        "SELECT sector_key FROM mycelium_sectors WHERE parent_key IS NULL AND status = 'proven'")}
    assert roots == set(PINNED)
    monkeypatch.setitem(spaces.DOMAIN_IDS, "robotics", 13)
    ensure_sector_tables(conn)
    ensure_sector_tables(conn)                   # idempotent
    after = {r[0] for r in conn.execute("SELECT sector_key FROM mycelium_sectors")}
    assert after == set(PINNED) | {"robotics"}
    conn.close()
