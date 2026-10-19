"""Guards (2026-10-19): the Kyudo immune signals and a DURABLE immune memory
(MEMORY-FOUNDATION-ANALYSIS.md §12.2 proposals 1 and 2; Kyudo Layer Guide, Part 4).

What was wrong (code-read):
  - QuorumSensor.threat_level lived only in process memory: a restart erased the
    evidence, so an attacker who spread signals across restarts never reached
    quorum. The docstring's quorum_log table did not exist.
  - The physics TOPO_VIOLATION was filed under the name "update_velocity_anomaly",
    a signal that nothing measured.
  - Velocity and landmark-activation anomalies were never computed.
Each guard below FAILS on the code before this change.
"""
import time
import uuid
from pathlib import Path

import pytest

from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.db import initialise_mycelium_schema
from backend.memory.mycelium import kyudo
from backend.memory.mycelium.interface import MyceliumInterface
from backend.memory.mycelium.kyudo import (
    QUORUM_SIGNAL_DECAY,
    QUORUM_VELOCITY_THRESHOLD,
    QuorumSensor,
    activation_is_anomalous,
)

KERNEL = Path(__file__).resolve().parents[2] / "agent" / "agent_kernel.py"


@pytest.fixture
def conn(mem_conn):
    initialise_mycelium_schema(mem_conn)   # the application store's shape (db.py)
    return mem_conn


def _rows(conn, where="1=1"):
    return conn.execute(
        "SELECT signal_type, weight, threat_after, shadow, session_id, detail "
        f"FROM mycelium_quorum_log WHERE {where} ORDER BY id"
    ).fetchall()


# -- schema -------------------------------------------------------------------

def test_quorum_log_table_and_ts_index_exist(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mycelium_quorum_log)")}
    assert cols == {"id", "ts", "session_id", "signal_type", "weight",
                    "threat_after", "shadow", "detail"}
    idx = {r[1] for r in conn.execute("PRAGMA index_list(mycelium_quorum_log)")}
    assert "idx_quorum_log_ts" in idx


# -- durable threat level -----------------------------------------------------

def test_threat_level_survives_a_new_interface_on_the_same_store(conn):
    mi = MyceliumInterface(conn)
    mi.record_anomaly("sess-a", "channel_trust_violation")       # 0.25
    mi.record_anomaly("sess-a", "topological_violation")         # 0.20
    assert mi._quorum_sensor.threat_level == pytest.approx(0.45)
    restarted = MyceliumInterface(conn)
    assert restarted._quorum_sensor.threat_level == pytest.approx(0.45)


def test_a_reorganization_reset_survives_a_restart(conn):
    mi = MyceliumInterface(conn)
    for _ in range(3):
        mi.record_anomaly("sess-a", "channel_trust_violation")   # 0.75 >= 0.60: fires
    assert mi._quorum_sensor.threat_level == 0.0
    assert MyceliumInterface(conn)._quorum_sensor.threat_level == 0.0


def test_a_clean_session_fade_is_logged_and_survives(conn):
    mi = MyceliumInterface(conn)
    mi.record_anomaly("sess-a", "topological_violation")         # 0.20
    mi.clear_session("sess-a")                                   # signalled: no fade
    assert not _rows(conn, "signal_type = 'clean_session_fade'")
    mi.clear_session("sess-b")                                   # clean: fades
    fade = _rows(conn, "signal_type = 'clean_session_fade'")
    assert len(fade) == 1
    assert fade[0][1] == pytest.approx(-QUORUM_SIGNAL_DECAY)
    assert fade[0][2] == pytest.approx(0.15)
    assert MyceliumInterface(conn)._quorum_sensor.threat_level == pytest.approx(0.15)


def test_a_fade_at_zero_threat_writes_no_row(conn):
    mi = MyceliumInterface(conn)
    mi.clear_session("sess-clean")
    assert _rows(conn) == []


def test_a_store_without_the_table_keeps_working_and_counts(conn):
    conn.execute("DROP TABLE mycelium_quorum_log")
    mi = MyceliumInterface(conn)                                 # restore fails: counted
    assert mi._quorum_log_errors >= 1
    errors = mi._quorum_log_errors
    assert mi.record_anomaly("sess-a", "topological_violation") is True
    assert mi._quorum_sensor.threat_level == pytest.approx(0.20)
    assert mi._quorum_log_errors > errors


# -- the physics violation has its own name ----------------------------------

def test_topological_violation_has_the_same_live_weight():
    w = QuorumSensor._SIGNAL_WEIGHTS
    assert w["topological_violation"] == 0.20 == w["update_velocity_anomaly"]


def test_topological_violation_is_recorded_as_such_and_adds_its_weight(conn):
    mi = MyceliumInterface(conn)
    assert mi.record_anomaly("sess-a", "topological_violation") is True
    assert mi._quorum_sensor.threat_level == pytest.approx(0.20)
    assert _rows(conn)[0][:2] == ("topological_violation", pytest.approx(0.20))
    assert _rows(conn)[0][3] == 0                                # a live row


def test_the_kernel_topo_path_records_topological_violation():
    src = KERNEL.read_text(encoding="utf-8", errors="replace")
    call = "mycelium_record_anomaly("
    at = src.index(call, src.index("tune_dffing_params(_session)"))
    window = src[at:at + 120]
    assert '"topological_violation"' in window
    assert "update_velocity_anomaly" not in window


# -- SHADOW signals: logged with shadow=1, never counted ---------------------

def test_velocity_shadow_logs_once_and_never_changes_threat(conn):
    mi = MyceliumInterface(conn)
    # The 3rd call of one tool is the 1st upsert; each later call is another.
    for i in range(QUORUM_VELOCITY_THRESHOLD + 2 + 10):
        mi.ingest_tool_call("bash", True, i + 1, 40, "sess-fast")
    rows = _rows(conn, "signal_type = 'update_velocity_anomaly'")
    assert len(rows) == 1                                        # at most once per session
    assert rows[0][3] == 1                                       # shadow
    assert rows[0][1] == pytest.approx(0.20)                     # the weight it would add
    assert mi._quorum_sensor.threat_level == 0.0
    assert MyceliumInterface(conn)._quorum_sensor.threat_level == 0.0


def test_velocity_shadow_is_silent_below_the_threshold(conn):
    mi = MyceliumInterface(conn)
    for i in range(QUORUM_VELOCITY_THRESHOLD + 2):               # 11 upserts: not above
        mi.ingest_tool_call("bash", True, i + 1, 40, "sess-calm")
    assert _rows(conn) == []


def _landmark(conn, task_class, count=0):
    lid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster,"
        " activation_count, created_at) VALUES (?, 'x', ?, '[]', ?, ?)",
        (lid, task_class, count, time.time()),
    )
    conn.commit()
    return lid


def test_landmark_activation_shadow_logs_and_never_changes_threat(conn):
    mi = MyceliumInterface(conn)
    for _ in range(5):
        _landmark(conn, "cls")                                   # 5 quiet siblings
    target = _landmark(conn, "cls")
    for _ in range(3):                                           # 3 <= mean 0 + 3 * sigma(floor 1)
        mi._lm_index.activate(target)
    assert _rows(conn) == []
    mi._lm_index.activate(target)                                # 4 > 3
    rows = _rows(conn)
    assert [(r[0], r[3]) for r in rows] == [("landmark_activation_anomaly", 1)]
    assert rows[0][1] == pytest.approx(0.30)
    assert target in rows[0][5]
    assert mi._quorum_sensor.threat_level == 0.0


def test_activation_anomaly_needs_a_class_with_a_normal():
    assert activation_is_anomalous([0, 0, 0, 0], 99) is False    # 4 siblings: no normal
    assert activation_is_anomalous([0] * 5, 4) is True
    assert activation_is_anomalous([0] * 5, 3) is False
    assert activation_is_anomalous([3] * 30, 6) is False         # sigma floor 1.0
    assert activation_is_anomalous([3] * 30, 7) is True


def test_record_shadow_leaves_the_threat_level_alone():
    s = QuorumSensor()
    assert s.record_shadow("landmark_activation_anomaly") == pytest.approx(0.30)
    assert s.threat_level == 0.0


# -- retention ---------------------------------------------------------------

def test_retention_bounds_the_log_to_the_newest_rows(conn, monkeypatch):
    monkeypatch.setattr(kyudo, "QUORUM_LOG_RETAIN", 20)
    monkeypatch.setattr(kyudo, "QUORUM_LOG_PRUNE_EVERY", 5)
    mi = MyceliumInterface(conn)
    for i in range(200):
        mi._log_quorum(f"s{i}", "channel_trust_violation", 0.25)
    n = conn.execute("SELECT COUNT(*) FROM mycelium_quorum_log").fetchone()[0]
    assert 20 <= n <= 20 + 5                                     # RETAIN .. RETAIN + PRUNE_EVERY
    newest = conn.execute(
        "SELECT session_id FROM mycelium_quorum_log ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    assert newest == "s199"
    oldest = conn.execute(
        "SELECT session_id FROM mycelium_quorum_log ORDER BY id LIMIT 1"
    ).fetchone()[0]
    assert int(oldest[1:]) >= 200 - 25
