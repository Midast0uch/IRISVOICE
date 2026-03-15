"""
MemoryInterface - Single Access Boundary for IRIS Memory System.

This is the ONLY class the rest of the application calls.
All memory reads and writes flow through this boundary.

Design Principles:
1. Nothing outside this class touches memory.db or ContextManager directly
2. Privacy boundary: get_task_context_for_remote() returns NO personal data
3. Torus-ready: All storage has node_id and origin fields for P2P sync
"""

import hashlib
import json
import logging
from typing import Optional, List, Dict, Any

from backend.memory.working import ContextManager
from backend.memory.episodic import EpisodicStore, Episode
from backend.memory.semantic import SemanticStore
from backend.memory.embedding import EmbeddingService

logger = logging.getLogger(__name__)

# Default source channel level before kyudo.py is wired (Phase 9).
# HyphaChannel.EXTERNAL — overridden when kyudo.py is wired in Phase 9.
_DEFAULT_PRE_KYUDO_CHANNEL: int = 1

# Episode dataclass is imported from episodic.py - single source of truth


class MemoryInterface:
    """
    Single access boundary for all memory operations.
    
    This class is the ONLY entry point for:
    - Task context assembly (local and remote)
    - Episode storage
    - Semantic memory updates
    - Session management
    
    Nothing else in the codebase touches memory storage directly.
    """
    
    def __init__(
        self,
        adapter: Any,
        db_path: str,
        biometric_key: bytes
    ):
        """
        Initialize MemoryInterface with all storage components.
        
        Args:
            adapter: Model adapter for compression and inference
            db_path: Path to the encrypted SQLite database
            biometric_key: 32-byte encryption key
        """
        self.episodic = EpisodicStore(db_path, biometric_key)
        self.semantic = SemanticStore(db_path, biometric_key)
        self.context = ContextManager(adapter)
        self.embed = EmbeddingService()
        self.adapter = adapter

        # Mycelium coordinate memory layer (Req 13.1–13.5)
        # Opens a dedicated connection to the same encrypted DB for the coordinate graph.
        # WAL mode allows concurrent readers — no contention with episodic/semantic.
        self._mycelium = None
        try:
            from backend.memory.db import open_encrypted_memory, initialise_mycelium_schema
            from backend.memory.mycelium import MyceliumInterface
            _mycelium_conn = open_encrypted_memory(db_path, biometric_key)
            initialise_mycelium_schema(_mycelium_conn)
            self._mycelium = MyceliumInterface(_mycelium_conn)
            self._mycelium.ingest_hardware()
            # Share Mycelium reference with EpisodicStore for resonance indexing (Req 13.6)
            self.episodic._mycelium = self._mycelium
            # Share with SemanticStore for coordinate ingestion on every fact write (Task 8.4)
            self.semantic._mycelium = self._mycelium
            logger.info("[MemoryInterface] Mycelium coordinate layer initialised")
        except Exception as _myc_err:
            logger.warning("[MemoryInterface] Mycelium init failed (non-fatal): %s", _myc_err)

        logger.info("[MemoryInterface] Initialized with encrypted storage")
    
    # ═══════════════════════════════════════════════════════════════════════
    # Task Context Assembly (Called before every task)
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_task_context(self, task: str, session_id: str) -> str:
        """
        Assemble full context for a local task.
        
        Includes:
        - Semantic header (user profile)
        - Episodic context (similar past tasks)
        - Working history (conversation)
        
        Args:
            task: Task description
            session_id: Session identifier
        
        Returns:
            Context string ready for model prompt
        """
        # Mycelium coordinate path — replaces prose header when graph is mature (Req 13.3)
        coordinate_path = ""
        if self._mycelium is not None:
            try:
                coordinate_path = self._mycelium.get_context_path(task, session_id)
            except Exception as _cp_err:
                logger.debug("[MemoryInterface] get_context_path failed: %s", _cp_err)

        if coordinate_path:
            # Inject compact coordinate path in place of prose header
            header = coordinate_path
        else:
            # Fallback: existing semantic prose header (new installs / immature graph)
            header = self.semantic.get_startup_header()

        episodic = self.episodic.assemble_episodic_context(task)

        context = self.context.assemble_for_task(
            session_id, task, header, episodic
        )

        logger.debug(f"[MemoryInterface] Assembled context ({len(context)} chars)")
        return context
    
    def get_task_context_for_remote(
        self,
        task_summary: str,
        tool_sequence: List[Dict[str, Any]]
    ) -> str:
        """
        Assemble context for a Torus peer worker.
        
        PRIVACY CRITICAL: Returns ONLY task-relevant data.
        NO semantic header (personal data stays local).
        NO user preferences.
        NO episodic memory with personal details.
        
        TORUS: This is the ONLY context method callable with a remote TaskMessage.
        
        Args:
            task_summary: Task description
            tool_sequence: Current tool sequence
        
        Returns:
            Privacy-safe context string
        """
        # Find similar tool patterns (not full episodes)
        similar = self.episodic.retrieve_similar(task_summary, limit=2, min_score=0.6)
        
        # Extract only tool hints (no personal data)
        tool_hints = []
        for ep in similar:
            if ep.get('tool_sequence'):
                tool_hints.append(f"- Approach: {ep['tool_sequence']}")
        
        # Build privacy-safe context
        context_parts = [f"TASK: {task_summary}"]
        
        if tool_hints:
            context_parts.append("\nRELEVANT TOOL PATTERNS:")
            context_parts.extend(tool_hints)
        
        context = "\n".join(context_parts)
        
        # Log for audit trail (content hash only for privacy)
        content_hash = hashlib.sha256(context.encode()).hexdigest()[:16]
        logger.info(f"[MemoryInterface] Remote context generated (hash: {content_hash})")
        
        return context
    
    # ═══════════════════════════════════════════════════════════════════════
    # Session Management (Called during task execution)
    # ═══════════════════════════════════════════════════════════════════════
    
    def append_to_session(
        self,
        session_id: str,
        content: str,
        zone: str = "working_history"
    ) -> None:
        """
        Append content to working memory.
        
        Triggers compression if working_history exceeds threshold.
        
        Args:
            session_id: Session identifier
            content: Content to append
            zone: Target zone (default: working_history)
        """
        self.context.append(session_id, content, zone)
    
    def update_tool_state(self, session_id: str, tool_output: str) -> None:
        """
        Update the live tool output zone.
        
        Does not trigger compression.
        
        Args:
            session_id: Session identifier
            tool_output: Current tool output
        """
        self.context.append(session_id, tool_output, zone="active_tool_state")
    
    def get_assembled_context(self, session_id: str) -> str:
        """
        Get current rendered context for a session.
        
        Args:
            session_id: Session identifier
        
        Returns:
            Current context string
        """
        return self.context.render(session_id)
    
    def clear_session(self, session_id: str) -> None:
        """
        Clear working memory for a session after completion.
        
        Args:
            session_id: Session identifier
        """
        self.context.clear_session(session_id)
        # Mycelium session cleanup (Req 13.5)
        if self._mycelium is not None:
            try:
                self._mycelium.clear_session(session_id)
            except Exception as _myc_err:
                logger.debug("[MemoryInterface] Mycelium clear_session failed: %s", _myc_err)
        logger.debug(f"[MemoryInterface] Cleared session {session_id[:8]}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # Episode Storage (Called after task completion)
    # ═══════════════════════════════════════════════════════════════════════
    
    def store_episode(self, episode: Episode) -> str:
        """
        Persist a completed task episode with embedding.
        
        Called by AgentKernel after every task completion.
        
        Args:
            episode: Episode to store
        
        Returns:
            Episode ID
        """
        score = self._score_outcome(episode)
        episode_id = self.episodic.store(episode, score)

        # Mycelium: record outcome → crystallise landmark → clear session (Req 13.4)
        if self._mycelium is not None:
            try:
                from backend.memory.mycelium.store import MemoryPath
                # Retrieve the current session's path for outcome recording
                # (empty path is safe — record_path_outcome handles empty node list)
                empty_path = MemoryPath(
                    nodes=[], cumulative_score=score,
                    token_encoding="", spaces_covered=[],
                    traversal_id=""
                )
                myc_outcome = (
                    "hit" if score >= 0.8
                    else "partial" if score >= 0.5
                    else "miss"
                )
                self._mycelium.record_outcome(
                    empty_path, myc_outcome,
                    episode.session_id, episode.task_summary
                )
                self._mycelium.crystallize_landmark(
                    session_id=episode.session_id,
                    cumulative_score=score,
                    outcome=myc_outcome,
                    task_entry_label=episode.task_summary,
                )
            except Exception as _myc_err:
                logger.debug("[MemoryInterface] Mycelium episode wiring failed: %s", _myc_err)

        logger.info(
            f"[MemoryInterface] Stored episode {episode_id[:8]}... "
            f"(score: {score}, type: {episode.outcome_type})"
        )
        return episode_id
    
    def _score_outcome(self, ep: Episode) -> float:
        """
        Calculate outcome score for an episode.
        
        Formula:
        - 0.50 base for success
        - +0.30 if user confirmed
        - +0.10 if not user corrected
        - +0.10 if fast (<5s)
        
        Args:
            ep: Episode to score
        
        Returns:
            Score from 0.0 to 1.0
        """
        score = 0.50 if ep.outcome_type == "success" else 0.0
        score += 0.30 if ep.user_confirmed else 0.0
        score += 0.10 if not ep.user_corrected else 0.0
        score += 0.10 if ep.duration_ms < 5000 else 0.0
        
        return min(round(score, 2), 1.0)
    
    # ═══════════════════════════════════════════════════════════════════════
    # Semantic Memory Updates (Called by distillation/UI)
    # ═══════════════════════════════════════════════════════════════════════
    
    def update_preference(
        self,
        key: str,
        value: str,
        source: str = "user_set"
    ) -> int:
        """
        Update a user preference in semantic memory.
        
        Args:
            key: Preference key
            value: Preference value
            source: 'user_set' for UI-driven, 'auto_learned' for distillation
        
        Returns:
            New version number
        """
        version = self.semantic.update(
            "user_preferences",
            key,
            value,
            confidence=1.0 if source == "user_set" else 0.7,
            source=source
        )
        
        # Also update display memory for UI
        display_name = key.replace('_', ' ').title()
        self.semantic.update_user_display(
            f"user_preferences.{key}",
            display_name,
            source=source
        )
        
        logger.debug(f"[MemoryInterface] Updated preference {key} -> v{version}")
        return version
    
    def get_user_profile_display(self) -> List[Dict[str, Any]]:
        """
        Get user-facing memory entries for UI display.
        
        Non-technical users see and can edit these.
        
        Returns:
            List of display entry dictionaries
        """
        return self.semantic.get_display_entries()
    
    def forget_preference(self, key: str) -> bool:
        """
        Remove a user-facing memory entry.
        
        Called from UI 'forget' action.
        
        Args:
            key: Preference key
        
        Returns:
            True if deleted, False if not found
        """
        # Delete from display memory
        self.semantic.delete_display_entry(f"user_preferences.{key}")
        
        # Delete from semantic storage
        deleted = self.semantic.delete("user_preferences", key)
        
        if deleted:
            logger.info(f"[MemoryInterface] Forgot preference: {key}")
        
        return deleted
    
    # ═══════════════════════════════════════════════════════════════════════
    # Statistics & Health
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive memory system statistics.
        
        Returns:
            Dictionary with episodic and semantic stats
        """
        return {
            "episodic": self.episodic.get_stats(),
            "semantic": self.semantic.get_stats()
        }
    
    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """
        Get working memory statistics for a session.
        
        Args:
            session_id: Session identifier
        
        Returns:
            Session statistics
        """
        return self.context.get_session_stats(session_id)
