"""
IRIS Session Manager
Replaces singleton StateManager with session-based design for isolation
"""
import asyncio
import uuid
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import weakref

from ..models import IRISState, Category
from .state_isolation import IsolatedStateManager
from .memory_bounds import MemoryBounds, MemoryTracker
from .session_types import SessionType


@dataclass
class SessionConfig:
    """Configuration for a session"""
    session_id: str
    created_at: datetime
    last_accessed: datetime
    max_memory_mb: int = 100  # Default 100MB per session
    max_state_size_kb: int = 1024  # Default 1MB state size
    idle_timeout_minutes: int = 30  # Session timeout
    is_persistent: bool = False  # Whether to persist after disconnect


class IRISession:
    """Individual session with isolated state and memory tracking"""
    
    def __init__(self, session_id: str, config: Optional[SessionConfig] = None, session_type: SessionType = SessionType.MAIN):
        self.session_id = session_id
        self.session_type = session_type
        self.config = config or SessionConfig(
            session_id=session_id,
            created_at=datetime.now(),
            last_accessed=datetime.now()
        )
        
        # Isolated state manager for this session
        self.state_manager = IsolatedStateManager(session_id)
        
        # Memory tracking and bounds
        self.memory_tracker = MemoryTracker(session_id)
        self.memory_bounds = MemoryBounds(
            max_memory_mb=self.config.max_memory_mb,
            max_state_size_kb=self.config.max_state_size_kb
        )
        
        # Session metadata
        self.connected_clients: set = set()  # WebSocket client IDs
        self.is_active = True
        self.cleanup_scheduled = False
        
        # Track memory usage
        self.memory_tracker.track_object_creation(self.state_manager)
    
    async def touch(self):
        """Update last accessed time"""
        self.config.last_accessed = datetime.now()
    
    def is_expired(self) -> bool:
        """Check if session has expired due to inactivity"""
        if not self.connected_clients and not self.config.is_persistent:
            idle_time = datetime.now() - self.config.last_accessed
            return idle_time > timedelta(minutes=self.config.idle_timeout_minutes)
        return False
    
    def get_memory_usage(self) -> Dict[str, Any]:
        """Get current memory usage statistics"""
        return {
            "session_id": self.session_id,
            "memory_mb": self.memory_tracker.get_total_memory_mb(),
            "state_size_kb": self.memory_tracker.get_state_size_kb(),
            "object_count": self.memory_tracker.get_object_count(),
            "within_bounds": self.memory_bounds.check_bounds(
                self.memory_tracker.get_total_memory_mb(),
                self.memory_tracker.get_state_size_kb()
            )
        }
    
    async def cleanup(self):
        """Clean up session resources"""
        if self.cleanup_scheduled:
            return
        
        self.cleanup_scheduled = True
        self.is_active = False
        
        # Clean up state manager
        await self.state_manager.cleanup()
        
        # Clean up memory tracker
        self.memory_tracker.cleanup()
        
        # Clear references
        self.state_manager = None
        self.memory_tracker = None


class SessionManager:
    """Manages multiple IRIS sessions with isolation and cleanup"""
    
    def __init__(self):
        self.sessions: Dict[str, IRISession] = {}
        self.client_to_session: Dict[str, str] = {}  # Map client IDs to session IDs
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown = False
        
        # Default session configuration
        self.default_config = SessionConfig(
            session_id="default",
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            max_memory_mb=100,
            max_state_size_kb=1024,
            idle_timeout_minutes=30,
            is_persistent=False
        )
    
    async def start(self):
        """Start the session manager and cleanup task"""
        self._shutdown = False
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
    
    async def stop(self):
        """Stop the session manager and clean up all sessions"""
        self._shutdown = True
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Clean up all sessions
        cleanup_tasks = []
        for session in self.sessions.values():
            cleanup_tasks.append(session.cleanup())
        
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        
        self.sessions.clear()
        self.client_to_session.clear()
    
    async def shutdown(self):
        """Gracefully shutdown the session manager and its background tasks."""
        await self.stop()
    
    async def create_session(self, session_id: Optional[str] = None, config: Optional[SessionConfig] = None) -> str:
        """Create a new session with optional custom configuration"""
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        if session_id in self.sessions:
            return session_id  # Session already exists
        
        # Use provided config or default
        if config is None:
            config = SessionConfig(
                session_id=session_id,
                created_at=datetime.now(),
                last_accessed=datetime.now(),
                max_memory_mb=self.default_config.max_memory_mb,
                max_state_size_kb=self.default_config.max_state_size_kb,
                idle_timeout_minutes=self.default_config.idle_timeout_minutes,
                is_persistent=self.default_config.is_persistent
            )
        
        session = IRISession(session_id, config)
        self.sessions[session_id] = session
        
        # Initialize the session's state manager
        await session.state_manager.initialize()
        
        return session_id
    
    def get_session(self, session_id: str) -> Optional[IRISession]:
        """Get a session by ID"""
        return self.sessions.get(session_id)
    
    def _get_current_time(self):
        return datetime.now()

    def get_session_by_client_id(self, client_id: str) -> Optional[IRISession]:
        """Get the session associated with a client"""
        session_id = self.client_to_session.get(client_id)
        if session_id:
            return self.sessions.get(session_id)
        return None
    
    def associate_client_with_session(self, client_id: str, session_id: str) -> bool:
        """Associate a WebSocket client with a session"""
        session = self.sessions.get(session_id)
        if not session:
            return False
        
        # Remove client from any existing session
        self._remove_client_from_sessions(client_id)
        
        # Associate with new session
        self.client_to_session[client_id] = session_id
        session.connected_clients.add(client_id)
        
        return True
    
    def dissociate_client(self, client_id: str) -> Optional[str]:
        """Remove a client from its session"""
        session_id = self.client_to_session.pop(client_id, None)
        if session_id:
            session = self.sessions.get(session_id)
            if session:
                session.connected_clients.discard(client_id)
                # Mark session for cleanup if no clients and not persistent
                if not session.connected_clients and not session.config.is_persistent:
                    session.cleanup_scheduled = True
        
        return session_id
    
    def _remove_client_from_sessions(self, client_id: str):
        """Remove a client from all sessions"""
        for session in self.sessions.values():
            session.connected_clients.discard(client_id)
    
    async def _cleanup_inactive_sessions(self):
        """Periodically clean up expired sessions"""
        while not self._shutdown:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                expired_sessions = []
                for session_id, session in self.sessions.items():
                    if session.is_expired() or session.cleanup_scheduled or hasattr(session, 'marked_for_cleanup') and session.marked_for_cleanup:
                        expired_sessions.append(session_id)
                
                # Clean up expired sessions
                for session_id in expired_sessions:
                    await self._cleanup_session(session_id)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in session cleanup: {e}")
    
    async def _cleanup_session(self, session_id: str):
        """Clean up a specific session"""
        session = self.sessions.pop(session_id, None)
        if session:
            await session.cleanup()
            
            # Remove client associations
            clients_to_remove = [
                client_id for client_id, sid in self.client_to_session.items()
                if sid == session_id
            ]
            for client_id in clients_to_remove:
                self.client_to_session.pop(client_id, None)
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics about all sessions"""
        total_memory = sum(
            session.memory_tracker.get_total_memory_mb()
            for session in self.sessions.values()
        )
        
        return {
            "active_sessions": len(self.sessions),
            "connected_clients": len(self.client_to_session),
            "total_memory_mb": total_memory,
            "sessions": [
                {
                    "session_id": sid,
                    "clients": len(session.connected_clients),
                    "memory_mb": session.memory_tracker.get_total_memory_mb(),
                    "created_at": session.config.created_at.isoformat(),
                    "last_accessed": session.config.last_accessed.isoformat(),
                    "expired": session.is_expired()
                }
                for sid, session in self.sessions.items()
            ]
        }
    
    def get_memory_usage_report(self) -> Dict[str, Any]:
        """Get detailed memory usage report"""
        return {
            "total_sessions": len(self.sessions),
            "total_memory_mb": sum(
                session.memory_tracker.get_total_memory_mb()
                for session in self.sessions.values()
            ),
            "sessions_over_limit": [
                session.get_memory_usage()
                for session in self.sessions.values()
                if not session.memory_bounds.check_bounds(
                    session.memory_tracker.get_total_memory_mb(),
                    session.memory_tracker.get_state_size_kb()
                )
            ],
            "memory_bounds": {
                "max_per_session_mb": self.default_config.max_memory_mb,
                "max_state_size_kb": self.default_config.max_state_size_kb
            }
        }

    async def remove_session(self, session_id: str) -> bool:
        """Remove a session and clean up its resources"""
        session = self.sessions.pop(session_id, None)
        if session:
            await session.cleanup()
            
            # Remove client associations
            clients_to_remove = [
                client_id for client_id, sid in self.client_to_session.items()
                if sid == session_id
            ]
            for client_id in clients_to_remove:
                self.client_to_session.pop(client_id, None)
            
            return True
        return False


# Global session manager instance
_session_manager_instance: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get the global session manager instance"""
    global _session_manager_instance
    if _session_manager_instance is None:
        _session_manager_instance = SessionManager()
    return _session_manager_instance


def create_session_manager() -> SessionManager:
    """Create a new session manager instance (for testing)"""
    return SessionManager()