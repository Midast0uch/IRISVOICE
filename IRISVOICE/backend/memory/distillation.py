"""
Distillation Process - Background learning daemon for IRIS.

Runs every 4 hours of idle time to extract patterns from recent episodes
and store them in semantic memory for future use.

Design Principles:
1. Silent failures - never block user interactions
2. Idle detection - only runs when system is quiet
3. Confidence scoring - auto-learned entries have confidence < 1.0
"""

import asyncio
import json
import logging
import time
from typing import Optional, Any, List, Dict
from dataclasses import dataclass

from backend.memory.interface import MemoryInterface

logger = logging.getLogger(__name__)


@dataclass
class DistillationConfig:
    """Configuration for distillation process."""
    interval_hours: float = 4.0          # Minimum hours between distillations
    idle_threshold_minutes: float = 10.0  # Idle time to consider "quiet"
    min_episodes: int = 5                # Minimum episodes to distill
    check_interval_seconds: float = 300.0  # Check every 5 minutes
    confidence_threshold: float = 0.7     # Confidence for learned patterns


class DistillationProcess:
    """
    Background daemon that extracts patterns from episodic memory.
    
    Runs on a 4-hour idle cycle to:
    1. Fetch recent episodes
    2. Extract patterns using the model
    3. Store insights in semantic memory
    4. Trigger skill crystallisation
    
    SILENT FAILURE: All errors are logged but never raised.
    """
    
    def __init__(
        self,
        memory_interface: MemoryInterface,
        adapter: Any,
        config: Optional[DistillationConfig] = None
    ):
        """
        Initialize DistillationProcess.
        
        Args:
            memory_interface: MemoryInterface instance
            adapter: Model adapter for pattern extraction
            config: Distillation configuration
        """
        self.memory = memory_interface
        self.adapter = adapter
        self.config = config or DistillationConfig()
        
        # Activity tracking
        self._last_activity = time.time()
        self._last_distillation = 0.0
        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        
        logger.info(
            f"[DistillationProcess] Initialized "
            f"(interval={self.config.interval_hours}h, "
            f"idle_threshold={self.config.idle_threshold_minutes}min)"
        )
    
    def record_activity(self) -> None:
        """Record user activity to reset idle timer."""
        self._last_activity = time.time()
        logger.debug("[DistillationProcess] Activity recorded")
    
    @property
    def idle_minutes(self) -> float:
        """Get current idle time in minutes."""
        return (time.time() - self._last_activity) / 60.0
    
    @property
    def hours_since_distillation(self) -> float:
        """Get hours since last distillation."""
        if self._last_distillation == 0:
            return float('inf')
        return (time.time() - self._last_distillation) / 3600.0
    
    def _should_distill(self) -> bool:
        """
        Check if distillation should run.
        
        Conditions:
        - System idle for >= threshold minutes
        - Hours since last distillation >= interval
        - Enough episodes to analyze
        
        Returns:
            True if distillation should run
        """
        # Check idle time
        if self.idle_minutes < self.config.idle_threshold_minutes:
            return False
        
        # Check interval
        if self.hours_since_distillation < self.config.interval_hours:
            return False
        
        # Check episode count
        recent = self.memory.episodic.get_recent_for_distillation(
            hours=int(self.config.interval_hours),
            min_episodes=self.config.min_episodes
        )
        
        return recent is not None
    
    async def start(self) -> None:
        """Start the background distillation loop."""
        if self._is_running:
            logger.warning("[DistillationProcess] Already running")
            return
        
        self._is_running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("[DistillationProcess] Started")
    
    async def stop(self) -> None:
        """Stop the background distillation loop."""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[DistillationProcess] Stopped")
    
    async def _run_loop(self) -> None:
        """Main background loop."""
        while self._is_running:
            try:
                if self._should_distill():
                    await self._run_distillation()
                
                # Wait before next check
                await asyncio.sleep(self.config.check_interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                # SILENT FAILURE: Log but don't crash
                logger.error(f"[DistillationProcess] Loop error: {e}")
                await asyncio.sleep(self.config.check_interval_seconds)
    
    async def _run_distillation(self) -> None:
        """
        Execute one distillation cycle.
        
        SILENT FAILURE: All errors are caught and logged.
        """
        try:
            logger.info("[DistillationProcess] Starting distillation cycle")
            
            # Fetch recent episodes
            episodes = self.memory.episodic.get_recent_for_distillation(
                hours=int(self.config.interval_hours),
                min_episodes=self.config.min_episodes
            )
            
            if not episodes:
                logger.debug("[DistillationProcess] No episodes to distill")
                return
            
            logger.info(f"[DistillationProcess] Distilling {len(episodes)} episodes")
            
            # Extract patterns using model
            patterns = await self._extract_patterns(episodes)
            
            if patterns:
                # Store patterns in semantic memory
                await self._store_patterns(patterns)
                logger.info(f"[DistillationProcess] Stored {len(patterns)} patterns")
            
            # Update timestamp
            self._last_distillation = time.time()
            
            # Trigger skill crystallisation
            await self._run_skill_crystallisation()
            
        except Exception as e:
            # SILENT FAILURE: Log but don't crash
            logger.error(f"[DistillationProcess] Distillation failed: {e}")
    
    async def _extract_patterns(
        self,
        episodes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract patterns from episodes using the model.
        
        Args:
            episodes: List of recent episodes
        
        Returns:
            List of extracted patterns
        """
        try:
            # Build prompt for pattern extraction
            episode_texts = []
            for i, ep in enumerate(episodes[:10], 1):  # Limit to 10 episodes
                text = f"{i}. Task: {ep['task_summary']}\n"
                text += f"   Outcome: {ep['outcome_type']} (score: {ep['outcome_score']})"
                episode_texts.append(text)
            
            prompt = (
                "Analyze the following task episodes and extract patterns about the user:\n\n"
                + "\n\n".join(episode_texts)
                + "\n\nExtract insights in JSON format:\n"
                + '{"patterns": [{'
                + '"category": "user_preferences|cognitive_model|tool_proficiency|domain_knowledge", '
                + '"key": "descriptive_key", '
                + '"value": "observed_pattern", '
                + '"confidence": 0.7-0.9}]}'
            )
            
            # Query model
            if hasattr(self.adapter, 'infer'):
                result = self.adapter.infer(prompt, max_tokens=800)
                response = result.raw_text if hasattr(result, 'raw_text') else str(result)
                
                # Parse JSON response
                try:
                    # Extract JSON from response
                    json_start = response.find('{')
                    json_end = response.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        data = json.loads(response[json_start:json_end])
                        return data.get('patterns', [])
                except json.JSONDecodeError:
                    logger.warning("[DistillationProcess] Failed to parse model response as JSON")
            
            return []
            
        except Exception as e:
            logger.error(f"[DistillationProcess] Pattern extraction failed: {e}")
            return []
    
    async def _store_patterns(self, patterns: List[Dict[str, Any]]) -> None:
        """
        Store extracted patterns in semantic memory.
        
        Args:
            patterns: List of pattern dictionaries
        """
        for pattern in patterns:
            try:
                category = pattern.get('category', 'user_preferences')
                key = pattern.get('key', 'unknown')
                value = pattern.get('value', '')
                confidence = pattern.get('confidence', self.config.confidence_threshold)
                
                # Validate category
                valid_categories = [
                    'user_preferences',
                    'cognitive_model',
                    'tool_proficiency',
                    'domain_knowledge'
                ]
                if category not in valid_categories:
                    category = 'user_preferences'
                
                # Store with auto-learned source
                self.memory.semantic.update(
                    category=category,
                    key=key,
                    value=value,
                    confidence=confidence,
                    source='distillation'
                )
                
                # Also update display memory
                display_name = f"{key.replace('_', ' ').title()}: {value[:50]}"
                self.memory.semantic.update_user_display(
                    key=f"{category}.{key}",
                    display_name=display_name,
                    source='auto_learned'
                )
                
            except Exception as e:
                logger.error(f"[DistillationProcess] Failed to store pattern: {e}")
    
    async def _run_skill_crystallisation(self) -> None:
        """Trigger skill crystallisation after distillation."""
        try:
            # Import here to avoid circular dependency
            from backend.memory.skills import SkillCrystalliser
            
            crystalliser = SkillCrystalliser(self.memory, self.adapter)
            count = await crystalliser.scan_and_crystallise()
            
            if count > 0:
                logger.info(f"[DistillationProcess] Crystallised {count} skills")
                
        except Exception as e:
            logger.error(f"[DistillationProcess] Skill crystallisation failed: {e}")
