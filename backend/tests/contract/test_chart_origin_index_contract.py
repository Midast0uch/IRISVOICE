"""Guard (2026-10-19): the chart-origin query on the answer path never scans landmarks.

The memory context package (MemoryInterface.get_task_context_package ->
MyceliumInterface.build_context_package -> TopologyLayer.get_topology_context ->
ChartRegistry.get_chart_origins) runs on the answer path. Its query scanned every
mycelium_landmarks row: 73 s on the first turn after a backend start (cold pages on
a hard disk; live gate, 2026-10-19). The structural guard: on the real schema the
query plan has no SCAN.
"""
import inspect
import sqlite3

from backend.memory.db import initialise_mycelium_schema
from backend.memory.mycelium.topology import ChartRegistry


def _chart_origin_sql() -> str:
    src = inspect.getsource(ChartRegistry.get_chart_origins)
    start = src.index('"""', src.index("execute(")) + 3
    return src[start:src.index('"""', start)].strip()


def test_the_chart_origin_query_reads_an_index_not_the_table():
    conn = sqlite3.connect(":memory:")
    initialise_mycelium_schema(conn)
    plan = conn.execute("EXPLAIN QUERY PLAN " + _chart_origin_sql(), (12,)).fetchall()
    details = " | ".join(row[-1] for row in plan)
    assert "SCAN" not in details, details
    assert "idx_landmarks_chart_origin" in details, details
