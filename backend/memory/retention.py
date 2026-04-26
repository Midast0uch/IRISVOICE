"""
Data Retention Manager for IRIS Memory.

Manages automatic pruning of old episodes based on retention policy.
Preserves high-value episodes regardless of age.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from backend.memory.interface import MemoryInterface
from backend.memory.config import get_config

logger = logging.getLogger(__name__)


class RetentionManager:
    """
    Background task for data retention management.
    
    Runs periodically to:
    1. Identify episodes older than retention_days
    2. Delete low-score episodes (< min_score_to_preserve)
    3. Preserve high-value episodes (user confirmed, high score)
    4. Log all deletions for audit
    
    Design: Silent operation - never blocks user interactions
    """
    
    def __init__(self, memory_interface: MemoryInterface):
        """
        Initialize RetentionManager.
        
        Args:
            memory_interface: MemoryInterface instance
        """
        self.memory = memory_interface
        self.config = get_config()
        
        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        
        logger.info(
            f"[RetentionManager] Initialized "
            f"(retention_days={self.config.retention.episode_retention_days}, "
            f"min_score={self.config.retention.min_score_to_preserve})"
        )
    
    async def start(self) -> None:
        """Start the background retention task."""
        if self._is_running:
            logger.warning("[RetentionManager] Already running")
            return
        
        if not self.config.retention.enabled:
            logger.info("[RetentionManager] Disabled by configuration")
            return
        
        self._is_running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("[RetentionManager] Started")
    
    async def stop(self) -> None:
        """Stop the background retention task."""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[RetentionManager] Stopped")
    
    async def _run_loop(self) -> None:
        """Main background loop."""
        # Run once at startup (after delay)
        await asyncio.sleep(60)  # Wait 1 minute after startup
        
        while self._is_running:
            try:
                await self._run_retention_cycle()
                
                # Sleep until next run
                hours = self.config.retention.run_interval_hours
                await asyncio.sleep(hours * 3600)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[RetentionManager] Cycle error: {e}")
                await asyncio.sleep(3600)  # Retry in 1 hour
    
    async def _run_retention_cycle(self) -> None:
        """Execute one retention cycle."""
        try:
            logger.info("[RetentionManager] Starting retention cycle")
            
            # Calculate cutoff date
            retention_days = self.config.retention.episode_retention_days
            cutoff = datetime.now() - timedelta(days=retention_days)
            cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
            
            # Get preservation criteria
            min_score = self.config.retention.min_score_to_preserve
            preserve_confirmed = self.config.retention.preserve_user_confirmed
            
            # Build deletion query
            # Delete episodes where:
            # - timestamp < cutoff AND
            # - outcome_score < min_score AND
            # - (NOT user_confirmed OR preserve_confirmed is False)
            
            confirmed_condition = ""
            if preserve_confirmed:
                confirmed_condition = "AND user_confirmed = 0"
            
            query = f"""
                DELETE FROM episodes
                WHERE timestamp < ?
                AND outcome_score < ?
                {confirmed_condition}
                RETURNING id, task_summary, outcome_score, timestamp
            """
            
            # Execute deletion
            cursor = self.memory.episodic.db.execute(
                query,
                (cutoff_str, min_score)
            )
            
            deleted = cursor.fetchall()
            self.memory.episodic.db.commit()
            
            if deleted:
                logger.info(
                    f"[RetentionManager] Deleted {len(deleted)} old episodes "
                    f"(older than {retention_days} days, score < {min_score})"
                )
                
                # Log details at debug level
                for row in deleted[:5]:  # Log first 5
                    logger.debug(
                        f"  - {row[0][:8]}...: '{row[1][:30]}...' "
                        f"(score: {row[2]}, {row[3]})"
                    )
                if len(deleted) > 5:
                    logger.debug(f"  ... and {len(deleted) - 5} more")
            else:
                logger.debug("[RetentionManager] No episodes to delete")
            
            # Log stats after cleanup
            stats = self.memory.episodic.get_stats()
            logger.info(
                f"[RetentionManager] Stats: {stats['total_episodes']} episodes, "
                f"avg score: {stats['avg_score']}"
            )
            
        except Exception as e:
            logger.error(f"[RetentionManager] Retention cycle failed: {e}")
    
    def get_retention_preview(self) -> dict:
        """
        Preview what would be deleted in next retention cycle.
        
        Returns:
            Dictionary with preview information
        """
        try:
            retention_days = self.config.retention.episode_retention_days
            cutoff = datetime.now() - timedelta(days=retention_days)
            cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
            min_score = self.config.retention.min_score_to_preserve
            
            # Count episodes that would be deleted
            cursor = self.memory.episodic.db.execute("""
                SELECT COUNT(*), AVG(outcome_score)
                FROM episodes
                WHERE timestamp < ?
                AND outcome_score < ?
            """, (cutoff_str, min_score))
            
            count, avg_score = cursor.fetchone()
            
            return {
                "retention_days": retention_days,
                "cutoff_date": cutoff_str,
                "min_score_threshold": min_score,
                "episodes_to_delete": count or 0,
                "average_score_of_deletions": round(avg_score or 0, 3),
                "would_delete": count > 0 if count else False
            }
            
        except Exception as e:
            logger.error(f"[RetentionManager] Preview failed: {e}")
            return {
                "error": str(e),
                "would_delete": False
            }
