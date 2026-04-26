"""
IRIS Session Manager
Replaces singleton StateManager with session-based design for isolation
"""
import asyncio
import uuid
import logging
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from backend.core_models import IRISState, Category
from backend.sessions.state_isolation import IsolatedStateManager
from backend.sessions.memory_bounds import MemoryBounds, MemoryTracker
from backend.sessions.session_types import SessionType

logger = logging.getLogger(__name__)


@dataclass
class SessionConfig:
    """Configuration for a session."""
    session_id: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    is_persistent: bool = True
    idle_timeout_minutes: int = 60
    max_memory_mb: int = 512
    max_state_size_kb: int = 1024


class IRISession:
    """An active IRIS session with isolated state."""

    def __init__(self, session_id: str, config: Optional[SessionConfig] = None,
                 session_type: SessionType = SessionType.MAIN):
        self.session_id = session_id
        self.session_type = session_type
        self.config = config or SessionConfig(
            session_id=session_id,
            created_at=datetime.now(),
            last_accessed=datetime.now(),
        )
        self.state_manager = IsolatedStateManager(session_id)
        self.memory_tracker = MemoryTracker(session_id)
        self.connected_clients: set = set()
        self.is_active: bool = True
        self.cleanup_scheduled: bool = False
        self.marked_for_cleanup: bool = False
        self.memory_bounds = MemoryBounds(
            max_memory_mb=self.config.max_memory_mb,
            max_state_size_kb=self.config.max_state_size_kb,
        )

    def touch(self) -> None:
        """Update last_accessed timestamp."""
        self.config.last_accessed = datetime.now()

    def is_expired(self) -> bool:
        """True if session has had no clients and is past idle timeout."""
        if self.connected_clients:
            return False
        if self.config.is_persistent:
            return False
        idle_time = datetime.now() - self.config.last_accessed
        return idle_time > timedelta(minutes=self.config.idle_timeout_minutes)

    def get_memory_usage(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "memory_mb": self.memory_tracker.get_total_memory_mb(),
            "state_kb": self.memory_tracker.get_state_size_kb(),
            "object_count": self.memory_tracker.get_object_count(),
            "bounds": self.memory_bounds.check_bounds(
                self.memory_tracker.get_total_memory_mb(),
                self.memory_tracker.get_state_size_kb(),
            ),
        }

    def cleanup(self) -> None:
        """Mark session for cleanup."""
        self.is_active = False
        self.cleanup_scheduled = True


class SessionManager:
    """
    Manages the lifecycle of all active IRIS sessions.
    Provides session creation, lookup, client association,
    and periodic cleanup of expired sessions.
    """

    def __init__(self):
        self.sessions: Dict[str, IRISession] = {}
        self.client_to_session: Dict[str, str] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown: bool = False
        self.default_config = SessionConfig(
            session_id="default",
            created_at=datetime.now(),
            last_accessed=datetime.now(),
        )

    async def start(self) -> None:
        """Start the session manager and periodic cleanup task."""
        self._shutdown = False
        self._cleanup_task = asyncio.create_task(self._cleanup_inactive_sessions())
        logger.info("[SessionManager] Started")

    async def stop(self) -> None:
        """Stop session manager and clean up all sessions."""
        self._shutdown = True
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        cleanup_tasks = []
        for session in self.sessions.values():
            session.cleanup()
            cleanup_tasks.append(session.state_manager.cleanup())
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        self.sessions.clear()
        self.client_to_session.clear()
        logger.info("[SessionManager] Stopped")

    async def shutdown(self) -> None:
        await self.stop()

    def archive_inactive_sessions(self) -> List[str]:
        """Archive (schedule cleanup for) expired sessions."""
        archived_sessions = []
        for session_id, session in list(self.sessions.items()):
            if session.is_expired() and not session.cleanup_scheduled:
                session.cleanup_scheduled = True
                archived_sessions.append(session_id)
                self._cleanup_session(session_id)
        return archived_sessions

    def create_session(self, session_id: Optional[str] = None,
                       config: Optional[SessionConfig] = None) -> IRISession:
        """Create a new session."""
        if not session_id:
            session_id = str(uuid.uuid4())
        if session_id in self.sessions:
            return self.sessions[session_id]

        cfg = config or SessionConfig(
            session_id=session_id,
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            max_memory_mb=self.default_config.max_memory_mb,
            max_state_size_kb=self.default_config.max_state_size_kb,
        )
        session = IRISession(session_id=session_id, config=cfg)
        self.sessions[session_id] = session

        # Initialize state persistence
        from pathlib import Path
        persistence_dir = Path(__file__).parent / session_id
        asyncio.create_task(session.state_manager.initialize(persistence_dir))

        logger.debug(f"[SessionManager] Created session: {session_id}")
        return session

    def get_session(self, session_id: str) -> Optional[IRISession]:
        """Get session by ID, updating last_accessed."""
        session = self.sessions.get(session_id)
        if session:
            session.touch()
        return session

    def _get_current_time(self) -> datetime:
        return datetime.now()

    def get_session_by_client_id(self, client_id: str) -> Optional[IRISession]:
        """Get the session associated with a client."""
        session_id = self.client_to_session.get(client_id)
        if session_id:
            return self.sessions.get(session_id)
        return None

    def associate_client_with_session(self, client_id: str, session_id: str) -> None:
        """Associate a client WebSocket connection with a session."""
        session = self.sessions.get(session_id)
        if not session:
            session = self.create_session(session_id)
        self._remove_client_from_sessions(client_id)
        self.client_to_session[client_id] = session_id
        session.connected_clients.add(client_id)
        session.touch()

    async def update_app_state_for_all_sessions(self, app_state: Any) -> None:
        """Push app_state update to all active sessions."""
        update_tasks = []
        for session in self.sessions.values():
            update_tasks.append(session.state_manager.update_app_state(app_state))
        if update_tasks:
            await asyncio.gather(*update_tasks, return_exceptions=True)

    def dissociate_client(self, client_id: str) -> None:
        """Remove client from its associated session."""
        session_id = self.client_to_session.pop(client_id, None)
        if session_id:
            session = self.sessions.get(session_id)
            if session:
                session.connected_clients.discard(client_id)
                if not session.connected_clients and not session.config.is_persistent:
                    session.cleanup_scheduled = True

    def _remove_client_from_sessions(self, client_id: str) -> None:
        """Remove client_id from any session it was previously in."""
        for session in self.sessions.values():
            session.connected_clients.discard(client_id)

    async def _cleanup_inactive_sessions(self) -> None:
        """Periodic task: archive expired sessions."""
        while not self._shutdown:
            try:
                await asyncio.sleep(300)  # check every 5 minutes
                expired_sessions = []
                for session_id, session in list(self.sessions.items()):
                    if session.is_expired() and not session.cleanup_scheduled:
                        if hasattr(session, 'marked_for_cleanup'):
                            pass
                        expired_sessions.append(session_id)
                for session_id in expired_sessions:
                    self._cleanup_session(session_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[SessionManager] Cleanup error: {e}")

    def _cleanup_session(self, session_id: str) -> None:
        """Remove and cleanup a session."""
        session = self.sessions.pop(session_id, None)
        if session:
            try:
                session.cleanup()
                asyncio.create_task(session.state_manager.cleanup())
            except Exception as e:
                logger.debug(f"[SessionManager] Session cleanup error for {session_id}: {e}")

            # Try to cleanup associated agent kernel
            try:
                from backend.agent import agent_kernel as ak_module
                cleanup_agent_kernel = getattr(ak_module, 'cleanup_agent_kernel', None)
                if cleanup_agent_kernel:
                    cleanup_agent_kernel(session_id)
            except Exception:
                pass

            # Remove all client associations for this session
            clients_to_remove = [
                client_id for client_id, sid in self.client_to_session.items()
                if sid == session_id
            ]
            for client_id in clients_to_remove:
                self.client_to_session.pop(client_id, None)

    def get_session_stats(self) -> Dict[str, Any]:
        total_memory = sum(s.memory_tracker.get_total_memory_mb() for s in self.sessions.values())
        return {
            "total_sessions": len(self.sessions),
            "active_clients": len(self.client_to_session),
            "total_memory_mb": total_memory,
            "sessions": {
                sid: {
                    "clients": len(s.connected_clients),
                    "memory_mb": s.memory_tracker.get_total_memory_mb(),
                    "config": {
                        "is_persistent": s.config.is_persistent,
                        "idle_timeout_minutes": s.config.idle_timeout_minutes,
                    },
                }
                for sid, s in self.sessions.items()
            },
        }

    def get_memory_usage_report(self) -> Dict[str, Any]:
        return {
            "session_count": len(self.sessions),
            "total_memory_mb": sum(s.memory_tracker.get_total_memory_mb() for s in self.sessions.values()),
            "sessions": {
                sid: s.get_memory_usage()
                for sid, s in self.sessions.items()
            },
        }

    def remove_session(self, session_id: str) -> None:
        """Explicitly remove a session."""
        session = self.sessions.pop(session_id, None)
        if session:
            session.cleanup()
            clients_to_remove = [
                cid for cid, sid in self.client_to_session.items()
                if sid == session_id
            ]
            for client_id in clients_to_remove:
                self.client_to_session.pop(client_id, None)


_session_manager_instance: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _session_manager_instance
    if _session_manager_instance is None:
        _session_manager_instance = SessionManager()
    return _session_manager_instance


def create_session_manager() -> SessionManager:
    return SessionManager()
