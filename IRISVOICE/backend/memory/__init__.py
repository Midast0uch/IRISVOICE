"""
IRIS Memory Foundation — Three-tier memory architecture

Provides persistent, encrypted memory storage with:
- Working Memory: Zone-based in-process context
- Episodic Memory: Vector-searchable task history
- Semantic Memory: Distilled user model and preferences

This module is the single access boundary for all memory operations.
Nothing outside this module should touch memory storage directly.
"""

__version__ = "1.0.0"

import logging
from typing import Optional, Any

from backend.memory.interface import MemoryInterface, Episode
from backend.memory.episodic import EpisodicStore
from backend.memory.semantic import SemanticStore, SemanticEntry
from backend.memory.working import ContextManager
from backend.memory.embedding import EmbeddingService
from backend.memory.config import MemoryConfig, get_config, load_config
from backend.memory.distillation import DistillationProcess
from backend.memory.skills import SkillCrystalliser
from backend.memory.retention import RetentionManager
from backend.memory.migration import DataMigration

logger = logging.getLogger(__name__)

# Global memory interface instance
_memory_interface: Optional[MemoryInterface] = None


def get_memory_interface() -> Optional[MemoryInterface]:
    """Get the global memory interface instance."""
    global _memory_interface
    return _memory_interface


async def initialise_memory(
    adapter: Any,
    config_path: str = "data/memory_config.json",
    db_path: Optional[str] = None
) -> MemoryInterface:
    """
    Initialize the memory system.
    
    This is the main entry point for memory initialization.
    It:
    1. Loads configuration
    2. Derives encryption key
    3. Creates MemoryInterface
    4. Runs data migration (if needed)
    5. Starts background processes (distillation, retention)
    
    Args:
        adapter: Model adapter for compression and inference
        config_path: Path to memory configuration file
        db_path: Override database path (optional)
    
    Returns:
        Initialized MemoryInterface
    """
    global _memory_interface
    
    logger.info("[Memory] Initializing memory system...")
    
    # Load configuration
    try:
        config = load_config(config_path)
        logger.info(f"[Memory] Loaded configuration from {config_path}")
    except Exception as e:
        logger.warning(f"[Memory] Failed to load config: {e}, using defaults")
        config = MemoryConfig()
    
    # Determine database path
    if db_path is None:
        db_path = config.db_path
    
    # Derive encryption key
    try:
        from backend.core.biometric import initialize_memory_encryption
        key = initialize_memory_encryption(db_path=db_path, config_path=config_path)
        logger.info("[Memory] Encryption key derived successfully")
    except Exception as e:
        logger.error(f"[Memory] Failed to derive encryption key: {e}")
        raise RuntimeError(f"Memory encryption initialization failed: {e}") from e
    
    # Create memory interface
    _memory_interface = MemoryInterface(
        adapter=adapter,
        db_path=db_path,
        biometric_key=key
    )
    
    # Run data migration (if needed)
    try:
        migration = DataMigration(_memory_interface)
        if not migration.has_run():
            logger.info("[Memory] Running data migration...")
            result = await migration.run_migration("backend/sessions")
            logger.info(f"[Memory] Migration complete: {result}")
    except Exception as e:
        logger.warning(f"[Memory] Data migration failed: {e}")
    
    # Start background processes
    try:
        if config.distillation.enabled:
            from backend.memory.distillation import DistillationConfig
            dist_config = DistillationConfig(
                interval_hours=config.distillation.interval_hours,
                idle_threshold_minutes=config.distillation.idle_threshold_minutes,
                min_episodes=config.distillation.min_episodes
            )
            distillation = DistillationProcess(
                memory_interface=_memory_interface,
                adapter=adapter,
                config=dist_config
            )
            await distillation.start()
            logger.info("[Memory] Distillation process started")
    except Exception as e:
        logger.warning(f"[Memory] Failed to start distillation: {e}")
    
    try:
        if config.retention.enabled:
            retention = RetentionManager(_memory_interface)
            await retention.start()
            logger.info("[Memory] Retention manager started")
    except Exception as e:
        logger.warning(f"[Memory] Failed to start retention: {e}")
    
    logger.info("[Memory] Memory system initialization complete")
    return _memory_interface


__all__ = [
    "MemoryInterface",
    "Episode",
    "EpisodicStore",
    "SemanticStore",
    "SemanticEntry",
    "ContextManager",
    "EmbeddingService",
    "MemoryConfig",
    "get_config",
    "load_config",
    "DistillationProcess",
    "SkillCrystalliser",
    "RetentionManager",
    "DataMigration",
    "initialise_memory",
    "get_memory_interface",
]
