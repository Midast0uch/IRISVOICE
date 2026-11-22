"""Guard (2026-11-22): a child sector is named by a real topic word, never by noise.

Measured on the live app store (read-only): the proven/candidate children included
data/https, data/https/https, data/look/look, data/year/year, web/look, general/iris,
general/project, finance/iris, hardware/list. Three causes in the birth rule:

  1. Eval prompts carry their working directory ("the project is in
     c:\\users\\...\\appdata\\local\\temp\\iris-evals\\..."), so path segments became
     sector words (appdata, local, evals, iris).
  2. Recurrence counted SESSIONS: one eval task repeated in 25 sessions read as a
     topic (hardware/https: 25 sessions, 1 distinct task text).
  3. A child's own members all hold its word, so the word won again one level down
     (data/https -> data/https/https).

Plus words that sit in every root (look, project, name, search, year: 5-7 roots).
Each birth test FAILS on the rule before this change; a real topic word is still born
(the quokka tests in test_mycelium_sectors_shadow.py).
"""
import sqlite3

import pytest

from backend.memory.db import initialise_mycelium_schema
from backend.memory.mycelium import sectors as sx
from backend.memory.tests.test_mycelium_sectors_shadow import T0, _lm, _run, _sectors
from backend.utils.durability_queue import lane


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    initialise_mycelium_schema(c)
    yield c
    lane("memory_events").flush(10.0)
    c.close()


def _member(c, lid, key, weight):
    c.execute("INSERT OR REPLACE INTO mycelium_landmark_sectors VALUES (?, ?, ?, 'cluster', ?)",
              (lid, key, weight, T0))
    c.commit()


def _child(c, key, parent, status="proven"):
    c.execute("INSERT INTO mycelium_sectors (sector_key, parent_key, depth, status, created_at, updated_at)"
              " VALUES (?, ?, ?, ?, ?, ?)", (key, parent, key.count("/"), status, T0, T0))
    c.commit()


def test_path_segments_of_an_eval_prompt_are_not_sector_words(conn):
    for i in range(5):
        _lm(conn, f"the c:\\users\\me\\appdata\\local\\temp\\iris-evals\\2026111{i}\\c10 "
                  f"quokka {['alpha', 'beta', 'gamma', 'delta', 'sigma'][i]}", f"s{i}")
    born = _run(conn, now=T0)["born"]
    assert not {"general/appdata", "general/local", "general/evals", "general/iris",
                "general/temp", "general/users"} & set(born), born
    assert born == ["general/quokka"]   # the real recurring word is still born


def test_one_task_repeated_in_many_sessions_is_not_a_topic(conn):
    for i in range(6):
        _lm(conn, "on https://quotes.toscrape.com, count the quotes on pages one and two", f"s{i}")
    assert _run(conn, now=T0)["born"] == []


def test_a_child_never_repeats_its_parents_word(conn):
    _child(conn, "general/quokka", "general")
    for i, w in enumerate(["alpha", "beta", "gamma", "delta"]):
        lid = _lm(conn, f"quokka {w} burrow", f"s{i}")
        _member(conn, lid, "general", 0.5)
        _member(conn, lid, "general/quokka", 1.0)   # the child is the primary sector
    born = _run(conn, now=T0)["born"]
    assert "general/quokka/quokka" not in born, born
    assert "general/quokka/burrow" in born          # a word that narrows the child is fine


def test_a_word_of_four_or_more_roots_names_no_child(conn):
    for root in ("ai", "data", "web", "design"):
        for i in range(3):
            lid = _lm(conn, f"look up the {root} wombat case {['one', 'two', 'six'][i]}", f"{root}{i}")
            _member(conn, lid, root, 1.0)
    born = _run(conn, now=T0)["born"]
    assert not [k for k in born if k.endswith(("/look", "/wombat", "/case"))], born


def test_the_repair_folds_noise_children_into_their_parent_and_is_idempotent(conn):
    _child(conn, "general/quokka", "general")
    _child(conn, "general/quokka/quokka", "general/quokka")
    _child(conn, "general/https", "general", status="candidate")
    for i, w in enumerate(["alpha", "beta", "gamma"]):
        lid = _lm(conn, f"quokka {w}", f"s{i}")
        for key in ("general", "general/quokka", "general/quokka/quokka"):
            _member(conn, lid, key, 1.0)
    for i in range(4):
        _member(conn, _lm(conn, "open https://x.example/page", f"h{i}"), "general/https", 1.0)

    plan = sx.fold_noise_children(conn, dry_run=True)
    assert [p["sector"] for p in plan] == ["general/quokka/quokka", "general/https"]
    assert _sectors(conn)["general/https"][0] == "candidate"        # a dry run writes nothing

    sx.fold_noise_children(conn, dry_run=False, now=T0)
    rows = _sectors(conn)
    assert rows["general/quokka/quokka"][:2] == ("dissolved", "general/quokka")
    assert rows["general/https"][:2] == ("dissolved", "general")
    assert rows["general/quokka"][0] == "proven"                    # a real word stays
    assert sx.resolve_sector_key(conn, "general/quokka/quokka") == "general/quokka"
    assert sx.fold_noise_children(conn, dry_run=True) == []
