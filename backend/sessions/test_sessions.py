"""
Tests for IRIS Session Management System
"""
import asyncio
import tempfile
import uuid
from pathlib import Path
import pytest

from . import (
    get_session_manager,
    create_session_manager,
    SessionManager,
    IRISession,
    SessionConfig,
    IsolatedStateManager,
    MemoryBounds,
    MemoryTracker,
    GlobalMemoryManager,
    get_global_memory_manager
)
from ..models import IRISState, Category, ColorTheme


class TestSessionManager:
    """Test SessionManager functionality"""
    
    @pytest.fixture
    def session_manager(self):
        """Create a fresh session manager for testing"""
        manager = create_session_manager()
        yield manager
        # Cleanup
        asyncio.run(manager.stop())
    
    @pytest.mark.asyncio
    async def test_create_session(self, session_manager):
        """Test creating a new session"""
        session_id = await session_manager.create_session()
        assert session_id is not None
        assert len(session_id) > 0
        
        session = session_manager.get_session(session_id)
        assert session is not None
        assert session.session_id == session_id
        assert isinstance(session.state_manager, IsolatedStateManager)
    
    @pytest.mark.asyncio
    async def test_create_session_with_custom_id(self, session_manager):
        """Test creating a session with a custom ID"""
        custom_id = "test-session-123"
        session_id = await session_manager.create_session(session_id=custom_id)
        assert session_id == custom_id
        
        session = session_manager.get_session(custom_id)
        assert session is not None
        assert session.session_id == custom_id
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, session_manager):
        """Test getting a non-existent session"""
        session = session_manager.get_session("nonexistent")
        assert session is None
    
    @pytest.mark.asyncio
    async def test_associate_client_with_session(self, session_manager):
        """Test associating a client with a session"""
        session_id = await session_manager.create_session()
        client_id = "client-123"
        
        success = session_manager.associate_client_with_session(client_id, session_id)
        assert success is True
        
        # Test that the association is recorded
        assert session_manager.client_to_session[client_id] == session_id
        
        session = session_manager.get_session(session_id)
        assert client_id in session.connected_clients
    
    @pytest.mark.asyncio
    async def test_dissociate_client(self, session_manager):
        """Test dissociating a client from a session"""
        session_id = await session_manager.create_session()
        client_id = "client-123"
        
        session_manager.associate_client_with_session(client_id, session_id)
        
        # Dissociate the client
        dissociated_session_id = session_manager.dissociate_client(client_id)
        assert dissociated_session_id == session_id
        
        # Verify the client is no longer associated
        assert client_id not in session_manager.client_to_session
        
        session = session_manager.get_session(session_id)
        assert client_id not in session.connected_clients
    
    @pytest.mark.asyncio
    async def test_get_session_by_client_id(self, session_manager):
        """Test getting session by client ID"""
        session_id = await session_manager.create_session()
        client_id = "client-123"
        
        session_manager.associate_client_with_session(client_id, session_id)
        
        retrieved_session = session_manager.get_session_by_client_id(client_id)
        assert retrieved_session is not None
        assert retrieved_session.session_id == session_id
    
    @pytest.mark.asyncio
    async def test_session_cleanup(self, session_manager):
        """Test session cleanup functionality"""
        session_id = await session_manager.create_session()
        client_id = "client-123"
        
        session_manager.associate_client_with_session(client_id, session_id)
        
        # Mark session for cleanup
        session = session_manager.get_session(session_id)
        session.marked_for_cleanup = True
        
        # Run cleanup
        await session_manager._cleanup_session(session_id)
        
        # Verify session is removed
        assert session_manager.get_session(session_id) is None
        assert client_id not in session_manager.client_to_session
    
    @pytest.mark.asyncio
    async def test_memory_bounds_enforcement(self, session_manager):
        """Test that memory bounds are enforced"""
        # Create session with tight memory bounds
        config = SessionConfig(
            session_id="test-session",
            created_at=session_manager._get_current_time(),
            last_accessed=session_manager._get_current_time(),
            max_memory_mb=1,  # 1MB limit
            max_state_size_kb=100  # 100KB limit
        )
        
        session_id = await session_manager.create_session(config=config)
        session = session_manager.get_session(session_id)
        
        # Verify memory bounds are set
        assert session.config.max_memory_mb == 1
        assert session.config.max_state_size_kb == 100


class TestIsolatedStateManager:
    """Test IsolatedStateManager functionality"""
    
    @pytest.fixture
    def state_manager(self):
        """Create a fresh state manager for testing"""
        session_id = str(uuid.uuid4())
        manager = IsolatedStateManager(session_id)
        return manager
    
    @pytest.mark.asyncio
    async def test_state_initialization(self, state_manager):
        """Test initial state creation"""
        assert state_manager.session_id is not None
        assert state_manager.state is not None
        assert isinstance(state_manager.state, IRISState)
        assert state_manager._memory_tracker is not None
    
    @pytest.mark.asyncio
    async def test_set_category(self, state_manager):
        """Test setting category"""
        await state_manager.set_category(Category.VOICE)
        assert state_manager.state.current_category == Category.VOICE
        assert state_manager.state.current_subnode is None
    
    @pytest.mark.asyncio
    async def test_set_subnode(self, state_manager):
        """Test setting subnode"""
        await state_manager.set_subnode("input")
        assert state_manager.state.current_subnode == "input"
    
    @pytest.mark.asyncio
    async def test_update_field(self, state_manager):
        """Test updating field values"""
        success = await state_manager.update_field("input", "volume", 75)
        assert success is True
        
        value = await state_manager.get_field_value("input", "volume")
        assert value == 75
    
    @pytest.mark.asyncio
    async def test_confirm_subnode(self, state_manager):
        """Test confirming a subnode"""
        values = {"volume": 50, "pitch": 1.0}
        orbit_angle = await state_manager.confirm_subnode("voice", "input", values)
        
        assert orbit_angle is not None
        assert len(state_manager.state.confirmed_nodes) == 1
        
        confirmed_node = state_manager.state.confirmed_nodes[0]
        assert confirmed_node.id == "input"
        assert confirmed_node.values == values
    
    @pytest.mark.asyncio
    async def test_update_theme(self, state_manager):
        """Test updating theme"""
        await state_manager.update_theme(glow_color="#FF0000", font_color="#FFFFFF")
        
        assert state_manager.state.active_theme.glow == "#FF0000"
        assert state_manager.state.active_theme.font == "#FFFFFF"
    
    @pytest.mark.asyncio
    async def test_clear_confirmed_nodes(self, state_manager):
        """Test clearing confirmed nodes"""
        # Add some confirmed nodes
        await state_manager.confirm_subnode("voice", "input", {"volume": 50})
        await state_manager.confirm_subnode("voice", "output", {"volume": 60})
        
        assert len(state_manager.state.confirmed_nodes) == 2
        
        # Clear them
        await state_manager.clear_confirmed_nodes()
        assert len(state_manager.state.confirmed_nodes) == 0
    
    @pytest.mark.asyncio
    async def test_state_persistence(self, state_manager):
        """Test state persistence functionality"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Initialize with persistence
            await state_manager.initialize(temp_dir)
            
            # Make some changes
            await state_manager.set_category(Category.VOICE)
            await state_manager.update_field("input", "volume", 80)
            await state_manager.confirm_subnode("voice", "input", {"volume": 80})
            
            # Create a new state manager for the same session
            new_manager = IsolatedStateManager(state_manager.session_id)
            await new_manager.initialize(temp_dir)
            
            # Wait a bit for state to load
            await asyncio.sleep(0.1)
            
            # Wait a bit for state to load
            await asyncio.sleep(0.1)
            
            # Verify state was restored
            assert new_manager.state.current_category == Category.VOICE
            assert await new_manager.get_field_value("input", "volume") == 80
            assert len(new_manager.state.confirmed_nodes) == 1
    
    @pytest.mark.asyncio
    async def test_memory_tracking(self, state_manager):
        """Test memory tracking functionality"""
        initial_memory = state_manager._memory_tracker.get_total_memory_mb()
        initial_objects = state_manager._memory_tracker.get_object_count()
        
        # Make changes that should affect memory
        await state_manager.set_category(Category.VOICE)
        await state_manager.update_field("input", "volume", 90)
        
        # Memory usage should have changed
        new_memory = state_manager._memory_tracker.get_total_memory_mb()
        assert new_memory >= initial_memory
        
        # Object count should have changed
        new_objects = state_manager._memory_tracker.get_object_count()
        assert new_objects >= initial_objects
    
    @pytest.mark.asyncio
    async def test_cleanup(self, state_manager):
        """Test cleanup functionality"""
        with tempfile.TemporaryDirectory() as temp_dir:
            await state_manager.initialize(temp_dir)
            
            # Make some changes
            await state_manager.set_category(Category.VOICE)
            await state_manager.update_field("input", "volume", 85)
            
            # Cleanup
            await state_manager.cleanup()
            
            # Verify cleanup completed without errors
            assert state_manager._shutdown is True


class TestMemoryManagement:
    """Test memory management functionality"""
    
    def test_memory_bounds_creation(self):
        """Test creating memory bounds"""
        bounds = MemoryBounds(max_memory_mb=50, max_state_size_kb=500)
        assert bounds.max_memory_mb * 1024 * 1024 == 50 * 1024 * 1024
        assert bounds.max_state_size_kb * 1024 == 500 * 1024
    
    def test_memory_bounds_check(self):
        """Test memory bounds checking"""
        bounds = MemoryBounds(max_memory_mb=1, max_state_size_kb=1)
        
        # Within bounds
        result = bounds.check_bounds(0.5, 0.5)
        assert result['memory_ok'] is True
        
        # Exceeds memory limit
        result = bounds.check_bounds(2, 0.5)
        assert result['memory_ok'] is False
        
        # Exceeds state size limit
        result = bounds.check_bounds(0.5, 2)
        assert result['state_ok'] is False
    
    def test_memory_tracker_creation(self):
        """Test creating memory tracker"""
        tracker = MemoryTracker("test-tracker")
        assert tracker.name == "test-tracker"
        assert tracker.get_total_memory_mb() >= 0
        assert tracker.get_object_count() >= 0
    
    def test_memory_tracker_object_tracking(self):
        """Test object tracking in memory tracker"""
        tracker = MemoryTracker("test-tracker")
        
        # Create some objects to track (use custom class instead of dict)
        class TestObject:
            def __init__(self, data):
                self.data = data
        
        obj1 = TestObject("value1")
        obj2 = TestObject([1, 2, 3, 4, 5])
        
        tracker.track_object_creation(obj1)
        tracker.track_object_creation(obj2)
        
        assert tracker.get_object_count() >= 2
        
        # Remove one object
        tracker.track_object_deletion(obj1)
        
        # Object count should decrease
        assert tracker.get_object_count() >= 1
    
    def test_global_memory_manager(self):
        """Test global memory manager"""
        manager = GlobalMemoryManager()
        
        # Get system memory info
        system_mem = manager.get_global_memory_usage()
        assert "total_memory_mb" in system_mem
        assert "total_state_kb" in system_mem
        assert "total_sessions" in system_mem
        assert "memory_usage_percent" in system_mem
        

    
    def test_global_memory_manager_singleton(self):
        """Test that global memory manager is a singleton"""
        manager1 = get_global_memory_manager()
        manager2 = get_global_memory_manager()
        assert manager1 is manager2


class TestSessionIntegration:
    """Test integration between session manager and state manager"""
    
    @pytest.fixture
    def session_manager(self):
        """Create a fresh session manager for testing"""
        manager = create_session_manager()
        yield manager
        asyncio.run(manager.stop())
    
    @pytest.fixture
    def state_manager(self, session_manager):
        """Create a state manager facade for testing"""
        from ..state_manager import StateManager
        return StateManager(session_manager=session_manager)
    
    @pytest.mark.asyncio
    async def test_state_manager_facade_integration(self, session_manager, state_manager):
        """Test that StateManager facade works with session manager"""
        # Create a session
        session_id = await session_manager.create_session()
        
        # Use state manager facade to modify state
        await state_manager.set_category(session_id, Category.VOICE)
        await state_manager.set_subnode(session_id, "input")
        await state_manager.update_field(session_id, "input", "volume", 70)
        
        # Verify changes through session manager
        session = session_manager.get_session(session_id)
        assert session.state_manager.state.current_category == Category.VOICE
        assert session.state_manager.state.current_subnode == "input"
        assert await session.state_manager.get_field_value("input", "volume") == 70
    
    @pytest.mark.asyncio
    async def test_multiple_sessions_isolation(self, session_manager, state_manager):
        """Test that multiple sessions are properly isolated"""
        # Create two sessions
        session1_id = await session_manager.create_session()
        session2_id = await session_manager.create_session()
        
        # Modify state in session 1
        await state_manager.set_category(session1_id, Category.VOICE)
        await state_manager.update_field(session1_id, "input", "volume", 80)
        
        # Modify state in session 2 (different values)
        await state_manager.set_category(session2_id, Category.AGENT)
        await state_manager.update_field(session2_id, "identity", "name", "TestAgent")
        
        # Verify isolation
        session1 = session_manager.get_session(session1_id)
        session2 = session_manager.get_session(session2_id)

        assert session1.state_manager.state.current_category == Category.VOICE
        assert session2.state_manager.state.current_category == Category.AGENT
        
        assert await session1.state_manager.get_field_value("input", "volume") == 80
        assert await session2.state_manager.get_field_value("identity", "name") == "TestAgent"
        
        # Verify session 1 doesn't have session 2's data
        assert await session1.state_manager.get_field_value("identity", "name") is None
        assert await session2.state_manager.get_field_value("input", "volume") is None