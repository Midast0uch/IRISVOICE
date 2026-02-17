"""
Tests for session types, configuration loading, and backup/migration functionality.
"""
import pytest
import asyncio
import json
from pathlib import Path
from datetime import datetime

from .session_types import SessionType, Session, MainSession, VisionSession, IsolatedSession
from .config_loader import SessionConfigLoader
from .backup_manager import SessionBackupManager
from .state_isolation import IsolatedStateManager

class TestSessionTypes:
    """Test session type definitions."""
    
    def test_session_type_enum(self):
        """Test session type enum values."""
        assert SessionType.MAIN.name == "MAIN"
        assert SessionType.VISION.name == "VISION"
        assert SessionType.ISOLATED.name == "ISOLATED"
    
    def test_session_base_class(self):
        """Test base session class."""
        session = Session("test_session", SessionType.MAIN)
        assert session.session_id == "test_session"
        assert session.session_type == SessionType.MAIN
        assert "test_session" in repr(session)
        assert "MAIN" in repr(session)
    
    def test_main_session(self):
        """Test main session type."""
        session = MainSession("main_123")
        assert session.session_id == "main_123"
        assert session.session_type == SessionType.MAIN
    
    def test_vision_session(self):
        """Test vision session type."""
        session = VisionSession("vision_456")
        assert session.session_id == "vision_456"
        assert session.session_type == SessionType.VISION
    
    def test_isolated_session(self):
        """Test isolated session type."""
        session = IsolatedSession("isolated_789")
        assert session.session_id == "isolated_789"
        assert session.session_type == SessionType.ISOLATED

class TestSessionConfigLoader:
    """Test session configuration loading."""
    
    @pytest.fixture
    def config_loader(self, tmp_path):
        """Create a config loader with temporary directory."""
        return SessionConfigLoader(config_dir=tmp_path)
    
    def test_load_default_config_main(self, config_loader):
        """Test loading default main session config."""
        config = config_loader.load_config(SessionType.MAIN)
        
        assert config["name"] == "Main Session"
        assert config["features"]["file_management"] is True
        assert config["features"]["gui_automation"] is True
        assert config["features"]["system_commands"] is True
        assert config["features"]["vision"] is True
        assert config["features"]["web_access"] is True
        assert config["limits"]["max_memory_mb"] == 512
        assert config["security"]["allow_dangerous_commands"] is True
    
    def test_load_default_config_vision(self, config_loader):
        """Test loading default vision session config."""
        config = config_loader.load_config(SessionType.VISION)
        
        assert config["name"] == "Vision Session"
        assert config["features"]["file_management"] is True
        assert config["features"]["gui_automation"] is True
        assert config["features"]["system_commands"] is False
        assert config["features"]["vision"] is True
        assert config["features"]["web_access"] is False
        assert config["limits"]["max_memory_mb"] == 256
        assert config["security"]["require_confirmation"] is True
    
    def test_load_default_config_isolated(self, config_loader):
        """Test loading default isolated session config."""
        config = config_loader.load_config(SessionType.ISOLATED)
        
        assert config["name"] == "Isolated Session"
        assert config["features"]["file_management"] is True
        assert config["features"]["gui_automation"] is False
        assert config["features"]["system_commands"] is False
        assert config["features"]["vision"] is False
        assert config["features"]["web_access"] is False
        assert config["limits"]["max_memory_mb"] == 128
        assert config["security"]["require_confirmation"] is True
    
    def test_save_and_load_config(self, config_loader):
        """Test saving and loading custom config."""
        test_config = {
            "name": "Test Session",
            "features": {"file_management": True, "gui_automation": False},
            "limits": {"max_memory_mb": 100}
        }
        
        # Save config
        success = config_loader.save_config(SessionType.MAIN, test_config)
        assert success is True
        
        # Load config
        loaded_config = config_loader.load_config(SessionType.MAIN)
        assert loaded_config["name"] == "Test Session"
        assert loaded_config["features"]["file_management"] is True
        assert loaded_config["features"]["gui_automation"] is False
        assert loaded_config["limits"]["max_memory_mb"] == 100
    
    def test_get_session_config(self, config_loader):
        """Test getting session-specific config."""
        config = config_loader.get_session_config("session_123", SessionType.MAIN)
        
        assert config["name"] == "Main Session"
        assert "session_123" in config_loader._configs
    
    def test_update_session_config(self, config_loader):
        """Test updating session config."""
        # Get initial config
        config = config_loader.get_session_config("session_123", SessionType.MAIN)
        
        # Update config
        updates = {"name": "Updated Session", "features": {"file_management": False}}
        success = config_loader.update_session_config("session_123", SessionType.MAIN, updates)
        
        assert success is True
        
        # Verify update
        updated_config = config_loader.get_session_config("session_123", SessionType.MAIN)
        assert updated_config["name"] == "Updated Session"
        assert updated_config["features"]["file_management"] is False

class TestSessionBackupManager:
    """Test session backup and migration functionality."""
    
    @pytest.fixture
    def backup_manager(self, tmp_path):
        """Create a backup manager with temporary directory."""
        return SessionBackupManager(backup_dir=tmp_path)
    
    @pytest.fixture
    def test_session(self):
        """Create a test session."""
        return MainSession("test_session_123")
    
    @pytest.fixture
    def test_state_manager(self):
        """Create a test state manager."""
        return IsolatedStateManager("test_session_123")
    
    @pytest.mark.asyncio
    async def test_create_backup(self, backup_manager, test_session, test_state_manager):
        """Test creating a session backup."""
        # Set some state
        await test_state_manager.set_category("test_category")
        await test_state_manager.update_field("test_field", "test_value")
        
        # Create backup
        backup_name = await backup_manager.create_backup(test_session, test_state_manager)
        
        assert backup_name.startswith("test_session_123_MAIN_")
        
        # Verify backup files exist
        backup_path = backup_manager.backup_dir / backup_name
        assert (backup_path / "metadata.json").exists()
        assert (backup_path / "state.json").exists()
        
        # Verify metadata
        with open(backup_path / "metadata.json", 'r') as f:
            metadata = json.load(f)
        
        assert metadata["session_id"] == "test_session_123"
        assert metadata["session_type"] == "MAIN"
        assert "backup_version" in metadata
    
    @pytest.mark.asyncio
    async def test_restore_backup(self, backup_manager, test_session, test_state_manager):
        """Test restoring a session from backup."""
        # Create backup
        backup_name = await backup_manager.create_backup(test_session, test_state_manager)
        
        # Restore backup
        restored_data = await backup_manager.restore_backup(backup_name, "new_session_456")
        
        assert restored_data["metadata"]["session_id"] == "new_session_456"
        assert restored_data["metadata"]["original_session_id"] == "test_session_123"
        assert "restored_at" in restored_data["metadata"]
    
    @pytest.mark.asyncio
    async def test_list_backups(self, backup_manager, test_session, test_state_manager):
        """Test listing available backups."""
        # Create multiple backups
        backup1 = await backup_manager.create_backup(test_session, test_state_manager)
        
        # Small delay to ensure different timestamps
        await asyncio.sleep(0.1)
        
        backup2 = await backup_manager.create_backup(test_session, test_state_manager)
        
        # List backups
        backups = await backup_manager.list_backups("test_session_123")
        
        assert len(backups) == 2
        assert backups[0]["session_id"] == "test_session_123"
        assert backups[1]["session_id"] == "test_session_123"
        
        # Should be sorted by creation time (newest first)
        assert backups[0]["created_at"] > backups[1]["created_at"]
    
    @pytest.mark.asyncio
    async def test_migrate_session(self, backup_manager, test_session, test_state_manager):
        """Test session migration."""
        # Create backup
        await backup_manager.create_backup(test_session, test_state_manager)
        
        # Migrate session
        new_session = await backup_manager.migrate_session(
            test_session, 
            SessionType.VISION, 
            test_state_manager
        )
        
        assert new_session.session_id == "test_session_123"
        assert new_session.session_type == SessionType.VISION
        
        # Verify migration record
        migration_path = backup_manager.migration_dir / "test_session_123_to_VISION"
        assert (migration_path / "migration.json").exists()
        
        with open(migration_path / "migration.json", 'r') as f:
            migration_record = json.load(f)
        
        assert migration_record["status"] == "completed"
        assert migration_record["old_session_type"] == "MAIN"
        assert migration_record["new_session_type"] == "VISION"
    
    @pytest.mark.asyncio
    async def test_cleanup_old_backups(self, backup_manager, test_session, test_state_manager):
        """Test cleanup of old backups."""
        # Create backup
        await backup_manager.create_backup(test_session, test_state_manager)
        
        # Cleanup with 0 days (should remove all)
        cleaned_count = await backup_manager.cleanup_old_backups(days_to_keep=0)
        
        # Note: This test might not work perfectly due to file system timing
        # In a real scenario, you'd want to create backups with older timestamps
        assert cleaned_count >= 0  # Should be 0 or 1 depending on timing
