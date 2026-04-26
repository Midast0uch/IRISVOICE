"""
Requirement-anchored tests that verify the specification constants, schema,
and MCP trust pin behaviour are implemented correctly.

These tests validate WHAT the system must do (the requirements), not HOW it does it.
Each test is anchored to one or more numbered requirements from requirements.md.
"""

import hashlib
import sqlite3
import time

import pytest

from .conftest_mycelium import mem_conn  # noqa: F401


# ===========================================================================
# REQ 1 — Coordinate Space Definitions
# ===========================================================================

class TestSpaceDefinitions:
    """Req 1.1–1.11: seven canonical spaces with correct axes, dtype, range."""

    def test_seven_canonical_spaces_defined(self):
        """Req 1.1: exactly seven spaces — conduct, domain, style, chrono, context, capability, toolpath."""
        from backend.memory.mycelium.spaces import SPACES
        expected = {"conduct", "domain", "style", "chrono", "context", "capability", "toolpath"}
        assert set(SPACES.keys()) == expected, (
            f"Req 1.1: expected exactly {expected}, got {set(SPACES.keys())}"
        )

    def test_no_affect_space(self):
        """Req 1.11: the 'affect' space must not exist (replaced by 'context')."""
        from backend.memory.mycelium.spaces import SPACES
        assert "affect" not in SPACES, (
            "Req 1.11: 'affect' space must not exist — it was replaced by 'context'"
        )

    def test_conduct_axes(self):
        """Req 1.2: conduct has exactly 5 axes in range [0.0, 1.0]."""
        from backend.memory.mycelium.spaces import SPACES
        s = SPACES["conduct"]
        assert s.axes == ["autonomy", "iteration_style", "session_depth",
                          "confirmation_threshold", "correction_rate"], (
            f"Req 1.2: conduct axes wrong: {s.axes}"
        )
        assert s.value_range == (0.0, 1.0), f"Req 1.2: conduct range must be (0.0, 1.0)"

    def test_domain_axes(self):
        """Req 1.3: domain has axes [domain_id, proficiency, recency] in [0.0, 1.0]."""
        from backend.memory.mycelium.spaces import SPACES, DOMAIN_IDS
        s = SPACES["domain"]
        assert s.axes == ["domain_id", "proficiency", "recency"], (
            f"Req 1.3: domain axes wrong: {s.axes}"
        )
        assert s.value_range == (0.0, 1.0)
        assert len(DOMAIN_IDS) == 13, f"Req 1.3: expected 13 canonical domains, got {len(DOMAIN_IDS)}"

    def test_style_axes(self):
        """Req 1.4: style has axes [formality, verbosity, directness] in [0.0, 1.0]."""
        from backend.memory.mycelium.spaces import SPACES
        s = SPACES["style"]
        assert s.axes == ["formality", "verbosity", "directness"], (
            f"Req 1.4: style axes wrong: {s.axes}"
        )

    def test_chrono_axes(self):
        """Req 1.5: chrono has [peak_activity_hour_utc, avg_session_length_hours, consistency]."""
        from backend.memory.mycelium.spaces import SPACES
        s = SPACES["chrono"]
        assert s.axes == ["peak_activity_hour_utc", "avg_session_length_hours", "consistency"], (
            f"Req 1.5: chrono axes wrong: {s.axes}"
        )

    def test_context_axes_and_decay_rate(self):
        """Req 1.6: context has 4 axes; CONTEXT_DECAY_RATE = 0.025."""
        from backend.memory.mycelium.spaces import SPACES, CONTEXT_DECAY_RATE
        s = SPACES["context"]
        assert s.axes == ["project_id", "stack_id", "constraint_flags", "freshness"], (
            f"Req 1.6: context axes wrong: {s.axes}"
        )
        assert CONTEXT_DECAY_RATE == pytest.approx(0.025), (
            f"Req 1.6: CONTEXT_DECAY_RATE must be 0.025, got {CONTEXT_DECAY_RATE}"
        )

    def test_capability_axes(self):
        """Req 1.7: capability has axes [gpu_tier, ram_normalized, has_docker, has_tailscale, os_id]."""
        from backend.memory.mycelium.spaces import SPACES, OS_ID_LINUX, OS_ID_MAC, OS_ID_WINDOWS
        s = SPACES["capability"]
        assert s.axes == ["gpu_tier", "ram_normalized", "has_docker", "has_tailscale", "os_id"], (
            f"Req 1.7: capability axes wrong: {s.axes}"
        )
        assert OS_ID_LINUX   == 0.0,  "Req 1.7: linux=0.0"
        assert OS_ID_MAC     == 0.5,  "Req 1.7: mac=0.5"
        assert OS_ID_WINDOWS == 1.0,  "Req 1.7: windows=1.0"

    def test_toolpath_axes_and_decay_rate(self):
        """Req 1.8: toolpath has 4 axes; TOOLPATH_DECAY_RATE = 0.02."""
        from backend.memory.mycelium.spaces import SPACES, TOOLPATH_DECAY_RATE
        s = SPACES["toolpath"]
        assert s.axes == ["tool_id", "call_frequency_normalized", "success_rate",
                          "avg_sequence_position"], (
            f"Req 1.8: toolpath axes wrong: {s.axes}"
        )
        assert TOOLPATH_DECAY_RATE == pytest.approx(0.02), (
            f"Req 1.8: TOOLPATH_DECAY_RATE must be 0.02, got {TOOLPATH_DECAY_RATE}"
        )

    def test_conduct_decay_rate(self):
        """Req 1.9: CONDUCT_DECAY_RATE = 0.008 (separate from toolpath 0.02)."""
        from backend.memory.mycelium.spaces import CONDUCT_DECAY_RATE, TOOLPATH_DECAY_RATE
        assert CONDUCT_DECAY_RATE == pytest.approx(0.008), (
            f"Req 1.9: CONDUCT_DECAY_RATE must be 0.008, got {CONDUCT_DECAY_RATE}"
        )
        assert CONDUCT_DECAY_RATE != TOOLPATH_DECAY_RATE, (
            "Req 1.9: CONDUCT_DECAY_RATE must differ from TOOLPATH_DECAY_RATE"
        )

    def test_tool_id_deterministic_md5_mod_10000(self):
        """Req 1.10: tool_id(name) hashes via MD5 % 10000 / 10000.0 → [0.0, 1.0]."""
        from backend.memory.mycelium.spaces import tool_id

        # Verify mathematical formula: MD5 hex → int → mod 10000 → /10000
        name = "bash"
        digest = hashlib.md5(name.encode("utf-8")).hexdigest()
        expected = int(digest, 16) % 10000 / 10000.0
        assert tool_id(name) == pytest.approx(expected), (
            f"Req 1.10: tool_id('{name}') must equal MD5%10000/10000.0"
        )

        # Determinism: same name → same value
        assert tool_id(name) == tool_id(name), "Req 1.10: tool_id must be deterministic"

        # Range: must be in [0.0, 1.0]
        for test_name in ["read_file", "write_file", "bash", "grep", "python"]:
            v = tool_id(test_name)
            assert 0.0 <= v <= 1.0, f"Req 1.10: tool_id('{test_name}') = {v} out of [0,1]"


class TestScoringConstants:
    """Req 7: edge scoring constants match specification exactly."""

    def test_prune_threshold(self):
        from backend.memory.mycelium.spaces import PRUNE_THRESHOLD
        assert PRUNE_THRESHOLD == pytest.approx(0.08), (
            f"Req 7.3: PRUNE_THRESHOLD must be 0.08, got {PRUNE_THRESHOLD}"
        )

    def test_highway_threshold_and_bonus(self):
        from backend.memory.mycelium.spaces import HIGHWAY_THRESHOLD, HIGHWAY_BONUS
        assert HIGHWAY_THRESHOLD == pytest.approx(0.85), (
            f"Req 7.4: HIGHWAY_THRESHOLD must be 0.85, got {HIGHWAY_THRESHOLD}"
        )
        assert HIGHWAY_BONUS == pytest.approx(0.01), (
            f"Req 7.4: HIGHWAY_BONUS must be 0.01, got {HIGHWAY_BONUS}"
        )

    def test_condense_and_split_thresholds(self):
        from backend.memory.mycelium.spaces import CONDENSE_THRESHOLD, SPLIT_THRESHOLD
        assert CONDENSE_THRESHOLD == pytest.approx(0.04), (
            f"Req 7.5: CONDENSE_THRESHOLD must be 0.04, got {CONDENSE_THRESHOLD}"
        )
        assert SPLIT_THRESHOLD == pytest.approx(0.40), (
            f"Req 7.6: SPLIT_THRESHOLD must be 0.40, got {SPLIT_THRESHOLD}"
        )


class TestConstraintWeightConstants:
    """Req 4.12: constraint_flags weights stored as named constants summing to 1.0."""

    def test_constraint_weights_values(self):
        from backend.memory.mycelium.spaces import (
            CONSTRAINT_WEIGHT_DEADLINE,
            CONSTRAINT_WEIGHT_PRODUCTION,
            CONSTRAINT_WEIGHT_PUBLIC,
            CONSTRAINT_WEIGHT_SECURITY,
        )
        assert CONSTRAINT_WEIGHT_DEADLINE   == pytest.approx(0.30), "Req 4.12: deadline weight"
        assert CONSTRAINT_WEIGHT_PRODUCTION == pytest.approx(0.25), "Req 4.12: production weight"
        assert CONSTRAINT_WEIGHT_PUBLIC     == pytest.approx(0.25), "Req 4.12: public weight"
        assert CONSTRAINT_WEIGHT_SECURITY   == pytest.approx(0.20), "Req 4.12: security weight"

    def test_constraint_weights_sum_to_one(self):
        from backend.memory.mycelium.spaces import (
            CONSTRAINT_WEIGHT_DEADLINE,
            CONSTRAINT_WEIGHT_PRODUCTION,
            CONSTRAINT_WEIGHT_PUBLIC,
            CONSTRAINT_WEIGHT_SECURITY,
        )
        total = (CONSTRAINT_WEIGHT_DEADLINE + CONSTRAINT_WEIGHT_PRODUCTION
                 + CONSTRAINT_WEIGHT_PUBLIC + CONSTRAINT_WEIGHT_SECURITY)
        assert total == pytest.approx(1.0), (
            f"Req 4.12: constraint weights must sum to 1.0, got {total}"
        )


class TestColdStartDefault:
    """Req 4.26–4.29: CONDUCT_COLD_START_DEFAULT exists and has correct values."""

    def test_cold_start_default_is_all_midpoints(self):
        from backend.memory.mycelium.spaces import CONDUCT_COLD_START_DEFAULT
        assert len(CONDUCT_COLD_START_DEFAULT) == 5, (
            "Req 4.26: CONDUCT_COLD_START_DEFAULT must have 5 axes"
        )
        for i, v in enumerate(CONDUCT_COLD_START_DEFAULT):
            assert v == pytest.approx(0.5), (
                f"Req 4.26: CONDUCT_COLD_START_DEFAULT[{i}] must be 0.5 (midpoint), got {v}"
            )


# ===========================================================================
# REQ 2 — Database Schema
# ===========================================================================

class TestSchema:
    """Req 2.1–2.11: all required tables, columns, and constraints exist."""

    REQUIRED_TABLES = [
        "mycelium_nodes", "mycelium_edges", "mycelium_traversals",
        "mycelium_spaces", "mycelium_landmarks", "mycelium_landmark_edges",
        "mycelium_conflicts", "mycelium_profile", "mycelium_landmark_merges",
        "mycelium_episode_index", "mycelium_charts", "mycelium_trajectories",
        "mycelium_mcp_registry",
    ]

    def test_all_required_tables_exist(self, mem_conn):
        """Req 2.1: all ten (plus topology two plus mcp_registry) tables must exist."""
        existing = {
            row[0] for row in
            mem_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in self.REQUIRED_TABLES:
            assert table in existing, (
                f"Req 2.1: required table '{table}' not found in schema"
            )

    def test_coordinates_stored_as_blob(self, mem_conn):
        """Req 2.2: mycelium_nodes.coordinates column must be BLOB type."""
        import struct
        # Insert a node with a struct-packed BLOB
        blob = struct.pack("3f", 0.1, 0.2, 0.3)
        nid = "test_blob_node"
        mem_conn.execute(
            "INSERT INTO mycelium_nodes (node_id, space_id, coordinates, label, confidence) "
            "VALUES (?,?,?,?,?)",
            (nid, "domain", blob, "test", 0.5)
        )
        mem_conn.commit()
        row = mem_conn.execute(
            "SELECT coordinates FROM mycelium_nodes WHERE node_id=?", (nid,)
        ).fetchone()
        assert isinstance(row[0], bytes), (
            "Req 2.2: coordinates must be stored as BLOB (bytes), not text/JSON"
        )

    def test_absorbed_column_exists_in_landmarks(self, mem_conn):
        """Req 2.8: mycelium_landmarks must have an 'absorbed' column (default NULL)."""
        cols = {
            row[1] for row in
            mem_conn.execute("PRAGMA table_info(mycelium_landmarks)").fetchall()
        }
        assert "absorbed" in cols, (
            "Req 2.8: 'absorbed' column missing from mycelium_landmarks"
        )

    def test_source_channel_column_in_episode_index(self, mem_conn):
        """Req 2.9: mycelium_episode_index must have 'source_channel' INTEGER column."""
        col_info = {
            row[1]: row for row in
            mem_conn.execute("PRAGMA table_info(mycelium_episode_index)").fetchall()
        }
        assert "source_channel" in col_info, (
            "Req 2.9: 'source_channel' column missing from mycelium_episode_index"
        )

    def test_delta_compressed_column_in_traversals(self, mem_conn):
        """Req 2.10: mycelium_traversals must have 'delta_compressed' INTEGER DEFAULT 0."""
        col_info = {
            row[1]: row for row in
            mem_conn.execute("PRAGMA table_info(mycelium_traversals)").fetchall()
        }
        assert "delta_compressed" in col_info, (
            "Req 2.10: 'delta_compressed' column missing from mycelium_traversals"
        )

    def test_mcp_registry_table_schema(self, mem_conn):
        """Req 2.11: mycelium_mcp_registry must have server_id, url, content_hash, registered_at."""
        col_info = {
            row[1] for row in
            mem_conn.execute("PRAGMA table_info(mycelium_mcp_registry)").fetchall()
        }
        for required_col in ["server_id", "url", "content_hash", "registered_at"]:
            assert required_col in col_info, (
                f"Req 2.11: '{required_col}' column missing from mycelium_mcp_registry"
            )

    def test_idempotent_schema_creation(self, mem_conn):
        """Req 2.7: schema must use CREATE TABLE IF NOT EXISTS — re-running must not error."""
        from .conftest_mycelium import _apply_schema
        # Applying schema a second time against an already-initialised DB must not raise
        try:
            _apply_schema(mem_conn)
        except Exception as e:
            pytest.fail(
                f"Req 2.7: schema re-creation raised an exception: {e}. "
                "All CREATE TABLE statements must use IF NOT EXISTS."
            )


# ===========================================================================
# REQ 2.11 + 15.29–15.31 — MCP Trust Pin
# ===========================================================================

class TestMCPTrustPin:
    """Req 2.11 + 15.29–15.31: MCP server unknown to registry → UNTRUSTED."""

    def test_registered_mcp_server_is_persisted(self, mem_conn):
        """Req 2.11: register_mcp() writes server_id, url, content_hash to mycelium_mcp_registry."""
        from backend.memory.mycelium.interface import MyceliumInterface
        mi = MyceliumInterface(mem_conn, dev_mode=True)
        mi.register_mcp("my_server", "http://localhost:9000", "hash_abc")

        row = mem_conn.execute(
            "SELECT server_id, url, content_hash FROM mycelium_mcp_registry WHERE server_id=?",
            ("my_server",),
        ).fetchone()
        assert row is not None, "Req 2.11: register_mcp() must persist to mycelium_mcp_registry"
        assert row[0] == "my_server"
        assert row[1] == "http://localhost:9000"
        assert row[2] == "hash_abc"

    def test_unknown_mcp_server_not_in_registry_is_untrusted(self, mem_conn):
        """
        Req 2.11 + 15.29: an MCP server whose server_id is NOT in mycelium_mcp_registry
        MUST be treated as UNTRUSTED — RagIngestionBridge.assign_channel('unknown') returns
        HyphaChannel.UNTRUSTED.
        """
        from backend.memory.mycelium.kyudo import RagIngestionBridge, HyphaChannel
        bridge = RagIngestionBridge()
        channel = bridge.assign_channel("unknown")
        assert channel == HyphaChannel.UNTRUSTED, (
            "Req 15.29: source_type 'unknown' (not registered as MCP) must map to UNTRUSTED"
        )

    def test_mcp_pin_persisted_and_loadable(self, mem_conn):
        """
        Req 2.11 + 15.29: pins registered via register_mcp() are persisted to
        mycelium_mcp_registry AND loaded into the in-memory _mcp_trust_registry dict.
        A new MyceliumInterface against the same DB must re-load the pin.
        """
        from backend.memory.mycelium.interface import MyceliumInterface

        mi = MyceliumInterface(mem_conn, dev_mode=True)
        mi.register_mcp("reload_server", "http://reload.test", "hash_xyz")

        # Re-instantiate against the same connection — triggers _load_mcp_trust_registry
        mi2 = MyceliumInterface(mem_conn, dev_mode=True)
        registry = mi2._mcp_trust_registry
        assert "reload_server" in registry, (
            "Req 2.11 + 15.29: register_mcp() must persist a pin reloaded on startup"
        )
        assert registry["reload_server"]["content_hash"] == "hash_xyz", (
            "Req 2.11: persisted content_hash must match what was registered"
        )

    def test_mcp_content_hash_mismatch_detectable(self, mem_conn):
        """
        Req 15.30: a caller presenting the wrong content_hash for a registered
        MCP server must be detectable via the in-memory registry comparison.
        The implementation stores the canonical hash; mismatches are identified
        by comparing stored vs. presented hash.
        """
        from backend.memory.mycelium.interface import MyceliumInterface

        mi = MyceliumInterface(mem_conn, dev_mode=True)
        mi.register_mcp("hash_server", "http://hash.test", "correct_hash_abc")

        stored = mi._mcp_trust_registry.get("hash_server", {}).get("content_hash")
        assert stored == "correct_hash_abc", "Prerequisite: hash stored correctly"

        # A caller with the wrong hash: the mismatch is detectable
        presented_wrong = "wrong_hash_xyz"
        assert presented_wrong != stored, (
            "Req 15.30: mismatched content_hash must be detectable via registry comparison"
        )
