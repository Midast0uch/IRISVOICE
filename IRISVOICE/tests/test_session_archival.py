"""
Unit tests for SessionManager archival functionality
Tests the 24-hour inactivity archival requirement
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from IRISVOICE.backend.sessions.session_manager import SessionManager, SessionConfig, IRISession


class TestSessionArchival:
    """Test session archival after 24 hours of inactivity"""
    
    @pytest.mark.asyncio
    async def test_session_expires_after_24_hours(self):
        """Test that a session expires after 24 hours of inactivity"""
        # Create a session manager
        session_manager = SessionManager()
        await session_manager.start()
        
        try:
            # Create a session
            session_id = await session_manager.create_session()
            session = session_manager.get_session(session_id)
            
            assert session is not None
            assert not session.is_expired()
            
            # Simulate 24 hours of inactivity by setting last_accessed to 24 hours ago
            session.config.last_accessed = datetime.now() - timedelta(hours=24, minutes=1)
            
            # Session should now be expired
            assert session.is_expired()
            
        finally:
            await session_manager.stop()
    
    @pytest.mark.asyncio
    async def test_session_does_not_expire_with_connected_clients(self):
        """Test that a session does not expire if clients are connected"""
        session_manager = SessionManager()
        await session_manager.start()
        
        try:
            # Create a session and associate a client
            session_id = await session_manager.create_session()
            session_manager.associate_client_with_session("client1", session_id)
            
            session = session_manager.get_session(session_id)
            
            # Simulate 24 hours of inactivity
            session.config.last_accessed = datetime.now() - timedelta(hours=24, minutes=1)
            
            # Session should NOT be expired because client is connected
            assert not session.is_expired()
            
        finally:
            await session_manager.stop()
    
    @pytest.mark.asyncio
    async def test_session_does_not_expire_if_persistent(self):
        """Test that a persistent session does not expire"""
        session_manager = SessionManager()
        await session_manager.start()
        
        try:
            # Create a persistent session
            config = SessionConfig(
                session_id="persistent-session",
                created_at=datetime.now(),
                last_accessed=datetime.now(),
                is_persistent=True
            )
            session_id = await session_manager.create_session(config=config)
            session = session_manager.get_session(session_id)
            
            # Simulate 24 hours of inactivity
            session.config.last_accessed = datetime.now() - timedelta(hours=24, minutes=1)
            
            # Session should NOT be expired because it's persistent
            assert not session.is_expired()
            
        finally:
            await session_manager.stop()
    
    @pytest.mark.asyncio
    async def test_archive_inactive_sessions_removes_expired(self):
        """Test that archive_inactive_sessions removes expired sessions"""
        session_manager = SessionManager()
        await session_manager.start()
        
        try:
            # Create multiple sessions
            session_id1 = await session_manager.create_session()
            session_id2 = await session_manager.create_session()
            session_id3 = await session_manager.create_session()
            
            # Make session1 and session2 expired
            session1 = session_manager.get_session(session_id1)
            session1.config.last_accessed = datetime.now() - timedelta(hours=25)
            
            session2 = session_manager.get_session(session_id2)
            session2.config.last_accessed = datetime.now() - timedelta(hours=30)
            
            # session3 is still active
            session3 = session_manager.get_session(session_id3)
            
            # Archive inactive sessions
            archived = await session_manager.archive_inactive_sessions()
            
            # Verify that expired sessions were archived
            assert session_id1 in archived
            assert session_id2 in archived
            assert session_id3 not in archived
            
            # Verify sessions were removed
            assert session_manager.get_session(session_id1) is None
            assert session_manager.get_session(session_id2) is None
            assert session_manager.get_session(session_id3) is not None
            
        finally:
            await session_manager.stop()
    
    @pytest.mark.asyncio
    async def test_session_timeout_default_is_24_hours(self):
        """Test that the default session timeout is 24 hours (1440 minutes)"""
        session_manager = SessionManager()
        
        # Check default config
        assert session_manager.default_config.idle_timeout_minutes == 1440
        
        # Create a session and verify it uses the default
        await session_manager.start()
        try:
            session_id = await session_manager.create_session()
            session = session_manager.get_session(session_id)
            
            assert session.config.idle_timeout_minutes == 1440
        finally:
            await session_manager.stop()
    
    @pytest.mark.asyncio
    async def test_session_persistence_directory_structure(self):
        """Test that sessions are persisted to backend/sessions/{session_id}/"""
        session_manager = SessionManager()
        await session_manager.start()
        
        try:
            # Create a session
            session_id = await session_manager.create_session()
            session = session_manager.get_session(session_id)
            
            # Verify the state manager has the correct persistence directory
            expected_dir = f"backend/sessions/{session_id}"
            
            # The persistence directory should be set during initialization
            # We can verify this by checking if the state manager's persistence_dir is set
            assert session.state_manager._persistence_dir is not None
            assert str(session.state_manager._persistence_dir).endswith(session_id)
            
        finally:
            await session_manager.stop()
    
    @pytest.mark.asyncio
    async def test_touch_updates_last_accessed(self):
        """Test that touch() updates the last_accessed timestamp"""
        session_manager = SessionManager()
        await session_manager.start()
        
        try:
            # Create a session
            session_id = await session_manager.create_session()
            session = session_manager.get_session(session_id)
            
            # Set last_accessed to an old time
            old_time = datetime.now() - timedelta(hours=1)
            session.config.last_accessed = old_time
            
            # Touch the session
            await session.touch()
            
            # Verify last_accessed was updated
            assert session.config.last_accessed > old_time
            
        finally:
            await session_manager.stop()
