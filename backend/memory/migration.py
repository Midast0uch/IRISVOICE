"""
Data Migration for IRIS Memory.

Migrates existing conversation.json data to the new episodic memory system.
Runs on first startup after memory system installation.
Preserves original files for safety.
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from backend.memory.interface import MemoryInterface, Episode
from backend.memory.config import get_config

logger = logging.getLogger(__name__)

# Marker file to indicate migration has run
MIGRATION_MARKER = ".migration_complete"


class DataMigration:
    """
    Handles one-time migration from session-based conversation storage
to the new episodic memory system.
    
    Process:
    1. Scan for existing session directories with conversation.json
    2. Parse conversations into episode format
    3. Store in episodic memory
    4. Create marker file to prevent re-running
    5. Preserve originals (don't delete)
    """
    
    def __init__(self, memory_interface: MemoryInterface):
        """
        Initialize DataMigration.
        
        Args:
            memory_interface: MemoryInterface instance
        """
        self.memory = memory_interface
        self.config = get_config()
        
        # Migration marker path
        self.marker_path = Path(self.config.db_path).parent / MIGRATION_MARKER
        
        logger.info("[DataMigration] Initialized")
    
    def has_run(self) -> bool:
        """Check if migration has already been run."""
        return self.marker_path.exists()
    
    def mark_complete(self) -> None:
        """Mark migration as complete."""
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        self.marker_path.touch()
        logger.info("[DataMigration] Marked as complete")
    
    async def run_migration(self, sessions_dir: str = "backend/sessions") -> Dict[str, Any]:
        """
        Run migration from conversation.json files.
        
        Args:
            sessions_dir: Root directory containing session folders
        
        Returns:
            Migration statistics
        """
        if self.has_run():
            logger.info("[DataMigration] Already completed, skipping")
            return {"status": "already_complete", "episodes_migrated": 0}
        
        sessions_path = Path(sessions_dir)
        if not sessions_path.exists():
            logger.info(f"[DataMigration] Sessions directory not found: {sessions_dir}")
            self.mark_complete()
            return {"status": "no_sessions_dir", "episodes_migrated": 0}
        
        logger.info(f"[DataMigration] Starting migration from {sessions_dir}")
        
        stats = {
            "sessions_scanned": 0,
            "conversations_found": 0,
            "episodes_migrated": 0,
            "episodes_failed": 0,
            "errors": []
        }
        
        try:
            # Find all conversation.json files
            for session_dir in sessions_path.iterdir():
                if not session_dir.is_dir():
                    continue
                
                stats["sessions_scanned"] += 1
                
                # Check for conversation.json
                conv_file = session_dir / "conversation.json"
                if not conv_file.exists():
                    continue
                
                stats["conversations_found"] += 1
                
                try:
                    # Parse and migrate
                    count = await self._migrate_conversation(
                        conv_file,
                        session_dir.name
                    )
                    stats["episodes_migrated"] += count
                    
                except Exception as e:
                    stats["episodes_failed"] += 1
                    stats["errors"].append(f"{session_dir.name}: {str(e)}")
                    logger.error(f"[DataMigration] Failed to migrate {session_dir.name}: {e}")
            
            # Mark complete
            self.mark_complete()
            
            logger.info(
                f"[DataMigration] Complete: {stats['episodes_migrated']} episodes "
                f"from {stats['conversations_found']} conversations"
            )
            
            return {
                "status": "success",
                **stats
            }
            
        except Exception as e:
            logger.error(f"[DataMigration] Migration failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                **stats
            }
    
    async def _migrate_conversation(
        self,
        conv_file: Path,
        session_id: str
    ) -> int:
        """
        Migrate a single conversation file.
        
        Args:
            conv_file: Path to conversation.json
            session_id: Session identifier
        
        Returns:
            Number of episodes created
        """
        try:
            with open(conv_file, 'r') as f:
                data = json.load(f)
            
            # Handle different conversation formats
            messages = data.get('messages', data.get('history', []))
            
            if not messages:
                return 0
            
            # Group messages into episodes (simple heuristic: by turns)
            episodes_created = 0
            current_task = []
            
            for msg in messages:
                role = msg.get('role', msg.get('speaker', ''))
                content = msg.get('content', msg.get('text', ''))
                
                if role in ('user', 'human'):
                    # Start new task
                    if current_task:
                        # Store previous episode
                        await self._store_episode(session_id, current_task)
                        episodes_created += 1
                    
                    current_task = [msg]
                else:
                    current_task.append(msg)
            
            # Store final episode
            if current_task:
                await self._store_episode(session_id, current_task)
                episodes_created += 1
            
            return episodes_created
            
        except json.JSONDecodeError as e:
            logger.warning(f"[DataMigration] Invalid JSON in {conv_file}: {e}")
            return 0
        except Exception as e:
            logger.error(f"[DataMigration] Error processing {conv_file}: {e}")
            raise
    
    async def _store_episode(
        self,
        session_id: str,
        messages: List[Dict[str, Any]]
    ) -> None:
        """
        Store messages as an episode.
        
        Args:
            session_id: Session identifier
            messages: List of messages
        """
        if not messages:
            return
        
        # Extract task summary from first user message
        first_user = None
        for msg in messages:
            role = msg.get('role', msg.get('speaker', ''))
            if role in ('user', 'human'):
                first_user = msg
                break
        
        if not first_user:
            return
        
        task_summary = first_user.get('content', first_user.get('text', 'Unknown task'))
        if len(task_summary) > 100:
            task_summary = task_summary[:100] + "..."
        
        # Build full content
        full_content = "\n\n".join(
            f"{m.get('role', m.get('speaker', 'unknown'))}: "
            f"{m.get('content', m.get('text', ''))}"
            for m in messages
        )
        
        # Create episode
        episode = Episode(
            session_id=session_id,
            task_summary=task_summary,
            full_content=full_content,
            tool_sequence=[],  # Can't extract from old format
            outcome_type="success",  # Assume success for migrated
            user_corrected=False,
            user_confirmed=False,
            source_channel="websocket",
            node_id="local",
            origin="local"
        )
        
        # Store with default score
        self.memory.store_episode(episode)
    
    def get_migration_status(self) -> Dict[str, Any]:
        """Get current migration status."""
        return {
            "has_run": self.has_run(),
            "marker_path": str(self.marker_path),
            "db_path": self.config.db_path
        }
