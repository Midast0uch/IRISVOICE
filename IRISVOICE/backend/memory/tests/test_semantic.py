"""
Tests for SemanticStore - User Model and Preferences

_Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 10.3, 10.4_
"""

import pytest
import tempfile
import os
from datetime import datetime
from unittest.mock import Mock

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.semantic import SemanticStore, SemanticEntry


@pytest.fixture
def temp_db_path():
    """Create a temporary database path (Windows-safe: SQLite holds file lock on Windows
    so TemporaryDirectory().__exit__ raises PermissionError. Use mkdtemp + explicit
    gc.collect() to flush Python's SQLite connection finalizers before rmtree.)"""
    import gc
    import shutil
    tmpdir = tempfile.mkdtemp()
    yield os.path.join(tmpdir, "test_semantic.db")
    gc.collect()  # flush any lingering sqlite3.Connection finalizers
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def biometric_key():
    """Create a test biometric key."""
    return b"test_key_32_bytes_long_for_testing_"


@pytest.fixture
def sample_entry():
    """Create a sample semantic entry."""
    return SemanticEntry(
        category="user_preferences",
        key="response_length",
        value="concise",
        version=1,
        confidence=1.0,
        source="user_set"
    )


class TestSemanticEntryDataclass:
    """Test SemanticEntry dataclass."""
    
    def test_entry_creation(self):
        """Test creating a SemanticEntry instance."""
        entry = SemanticEntry(
            category="user_preferences",
            key="response_length",
            value="concise"
        )
        
        assert entry.category == "user_preferences"
        assert entry.key == "response_length"
        assert entry.value == "concise"
        assert entry.version == 1
        assert entry.confidence == 1.0
    
    def test_entry_with_all_fields(self):
        """Test creating an entry with all fields."""
        entry = SemanticEntry(
            category="cognitive_model",
            key="work_hours",
            value="9-5",
            version=3,
            confidence=0.8,
            source="distillation"
        )
        
        assert entry.version == 3
        assert entry.confidence == 0.8
        assert entry.source == "distillation"


class TestSemanticStoreInitialization:
    """Test SemanticStore initialization."""
    
    def test_store_initialization(self, temp_db_path, biometric_key):
        """Test that SemanticStore initializes."""
        store = SemanticStore(temp_db_path, biometric_key)
        
        assert store is not None
        assert store.db_path == temp_db_path


class TestUpdate:
    """Test updating semantic entries."""
    
    def test_update_creates_new_entry(self, temp_db_path, biometric_key):
        """Test that update creates a new entry."""
        store = SemanticStore(temp_db_path, biometric_key)

        # Mock the database
        store._db = Mock()
        store._db.execute = Mock()
        store._db.execute.return_value.fetchone.return_value = (1,)
        store._db.commit = Mock()

        store.update("user_preferences", "response_length", "concise")

        store._db.execute.assert_called()
        store._db.commit.assert_called()
    
    def test_update_increments_version(self, temp_db_path, biometric_key):
        """Test that update increments version on conflict."""
        store = SemanticStore(temp_db_path, biometric_key)

        store._db = Mock()
        store._db.execute = Mock()
        store._db.execute.return_value.fetchone.return_value = (2,)
        store._db.commit = Mock()

        # update() auto-increments version via ON CONFLICT upsert — no version kwarg
        store.update("user_preferences", "response_length", "concise")

        # Check that upsert is used (INSERT ... ON CONFLICT)
        call_args = str(store._db.execute.call_args)
        assert "INSERT" in call_args or "upsert" in call_args.lower()


class TestGet:
    """Test getting semantic entries."""
    
    def test_get_returns_entry(self, temp_db_path, biometric_key):
        """Test that get returns an entry."""
        store = SemanticStore(temp_db_path, biometric_key)
        
        store._db = Mock()
        store._db.execute.return_value.fetchone.return_value = (
            "user_preferences", "response_length", "concise", 1, 1.0, "user_set", "2024-01-01"
        )
        
        entry = store.get("user_preferences", "response_length")
        
        assert entry is not None
        assert entry.value == "concise"
    
    def test_get_returns_none_for_missing(self, temp_db_path, biometric_key):
        """Test that get returns None for missing entry."""
        store = SemanticStore(temp_db_path, biometric_key)
        
        store._db = Mock()
        store._db.execute.return_value.fetchone.return_value = None
        
        entry = store.get("user_preferences", "nonexistent")
        
        assert entry is None


class TestDelete:
    """Test deleting semantic entries."""
    
    def test_delete_removes_entry(self, temp_db_path, biometric_key):
        """Test that delete removes an entry."""
        store = SemanticStore(temp_db_path, biometric_key)

        store._db = Mock()
        store._db.execute = Mock()
        store._db.execute.return_value.rowcount = 1  # delete() checks cursor.rowcount > 0
        store._db.commit = Mock()

        store.delete("user_preferences", "response_length")

        store._db.execute.assert_called()
        store._db.commit.assert_called()


class TestGetByCategory:
    """Test getting entries by category."""
    
    def test_get_by_category_returns_list(self, temp_db_path, biometric_key):
        """Test that get_by_category returns a list."""
        store = SemanticStore(temp_db_path, biometric_key)
        
        store._db = Mock()
        store._db.execute.return_value.fetchall.return_value = [
            ("user_preferences", "response_length", "concise", 1, 1.0, "user_set", "2024-01-01"),
            ("user_preferences", "tone", "friendly", 1, 0.9, "distillation", "2024-01-01"),
        ]
        
        entries = store.get_by_category("user_preferences")
        
        assert isinstance(entries, list)
        assert len(entries) == 2


class TestGetStartupHeader:
    """Test assembling startup header."""
    
    def test_get_startup_header_includes_preferences(self, temp_db_path, biometric_key):
        """Test that header includes user preferences."""
        store = SemanticStore(temp_db_path, biometric_key)

        store._db = Mock()
        # get_by_category() selects: category, key, value, version, confidence, source, updated
        store._db.execute.return_value.fetchall.return_value = [
            ("user_preferences", "response_length", "concise", 1, 1.0, "user_set", "2024-01-01"),
            ("user_preferences", "tone", "friendly", 1, 0.9, "user_set", "2024-01-01"),
        ]

        header = store.get_startup_header()

        assert "concise" in header
        assert "friendly" in header
    
    def test_get_startup_header_filters_by_categories(self, temp_db_path, biometric_key):
        """Test that header filters by HEADER_CATEGORIES."""
        store = SemanticStore(temp_db_path, biometric_key)
        
        store._db = Mock()
        store._db.execute.return_value.fetchall.return_value = []
        
        store.get_startup_header()
        
        # Verify query includes category filter
        call_args = str(store._db.execute.call_args)
        assert "category" in call_args.lower()


class TestDeltaSync:
    """Test Torus delta synchronization."""
    
    def test_get_delta_since_version(self, temp_db_path, biometric_key):
        """Test getting entries changed since version."""
        store = SemanticStore(temp_db_path, biometric_key)
        
        store._db = Mock()
        store._db.execute.return_value.fetchall.return_value = [
            ("user_preferences", "response_length", "concise", 5, 1.0, "user_set", "2024-01-01"),
        ]
        
        entries = store.get_delta_since_version(since_version=3)

        # Should only return entries with version > 3
        # get_delta_since_version returns list of dicts keyed by field name
        assert len(entries) == 1
        assert entries[0]["version"] > 3
    
    def test_get_delta_orders_by_version(self, temp_db_path, biometric_key):
        """Test that delta entries are ordered by version."""
        store = SemanticStore(temp_db_path, biometric_key)
        
        store._db = Mock()
        store._db.execute.return_value.fetchall.return_value = [
            ("cat1", "key1", "val1", 4, 1.0, "user_set", "2024-01-01"),
            ("cat1", "key2", "val2", 5, 1.0, "user_set", "2024-01-01"),
        ]
        
        entries = store.get_delta_since_version(since_version=3)

        # Verify ordering — returns list of dicts keyed by field name
        versions = [e["version"] for e in entries]
        assert versions == sorted(versions)
    
    def test_get_max_version(self, temp_db_path, biometric_key):
        """Test getting maximum version."""
        store = SemanticStore(temp_db_path, biometric_key)
        
        store._db = Mock()
        store._db.execute.return_value.fetchone.return_value = (42,)
        
        max_version = store.get_max_version()
        
        assert max_version == 42


class TestUserDisplay:
    """Test user-facing display methods."""
    
    def test_get_display_entries_returns_list(self, temp_db_path, biometric_key):
        """Test that get_display_entries returns a list."""
        store = SemanticStore(temp_db_path, biometric_key)
        
        store._db = Mock()
        # get_display_entries selects: display_key, display_name, internal_ref, source,
        #                              confidence, editable, created  (7 columns)
        store._db.execute.return_value.fetchall.return_value = [
            ("pref_1", "Prefers concise answers", "user_preferences.response_length", "user_set", 1.0, 1, "2024-01-01"),
        ]

        entries = store.get_display_entries()

        assert isinstance(entries, list)
        assert len(entries) == 1
    
    def test_update_user_display_creates_entry(self, temp_db_path, biometric_key):
        """Test that update_user_display creates display entry."""
        store = SemanticStore(temp_db_path, biometric_key)
        
        store._db = Mock()
        store._db.execute = Mock()
        store._db.commit = Mock()
        
        # update_user_display signature: (key, display_name, source, editable)
        store.update_user_display(
            key="pref_1",
            display_name="Prefers concise answers"
        )
        
        store._db.execute.assert_called()
        store._db.commit.assert_called()
    
    def test_delete_display_entry_removes_entry(self, temp_db_path, biometric_key):
        """Test that delete_display_entry removes display entry."""
        store = SemanticStore(temp_db_path, biometric_key)

        store._db = Mock()
        store._db.execute = Mock()
        store._db.execute.return_value.rowcount = 1  # delete_display_entry() checks cursor.rowcount > 0
        store._db.commit = Mock()

        store.delete_display_entry("pref_1")

        store._db.execute.assert_called()
        store._db.commit.assert_called()


class TestVersioning:
    """Test entry versioning for Torus sync."""
    
    def test_new_entry_has_version_one(self):
        """Test that new entries start at version 1."""
        entry = SemanticEntry(
            category="user_preferences",
            key="test",
            value="value"
        )
        
        assert entry.version == 1
    
    def test_update_increments_version(self, temp_db_path, biometric_key):
        """Test that updates increment version."""
        store = SemanticStore(temp_db_path, biometric_key)

        store._db = Mock()
        store._db.execute = Mock()
        store._db.execute.return_value.fetchone.return_value = (5,)
        store._db.commit = Mock()

        # update() auto-increments version via ON CONFLICT upsert — no version kwarg
        store.update("user_preferences", "key", "value")

        # Verify version increment is encoded in the upsert SQL
        call_args = str(store._db.execute.call_args)
        assert "version" in call_args.lower()


class TestConfidenceAndSource:
    """Test confidence and source tracking."""
    
    def test_user_set_has_confidence_one(self):
        """Test that user-set entries have confidence 1.0."""
        entry = SemanticEntry(
            category="user_preferences",
            key="response_length",
            value="concise",
            source="user_set"
        )
        
        assert entry.confidence == 1.0
    
    def test_distillation_has_lower_confidence(self):
        """Test that distillation entries have confidence < 1.0."""
        entry = SemanticEntry(
            category="cognitive_model",
            key="work_hours",
            value="9-5",
            confidence=0.7,
            source="distillation"
        )
        
        assert entry.confidence < 1.0
        assert entry.source == "distillation"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
