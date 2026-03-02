"""
Memory Configuration for IRIS.

Centralized configuration management for the memory system.
Supports validation, defaults, and hot-reload for non-critical settings.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class CompressionConfig:
    """Configuration for context compression."""
    threshold: float = 0.80  # Usage ratio that triggers compression
    keep_ratio: float = 0.60  # Keep newest N% verbatim
    summary_max_tokens: int = 300
    min_lines: int = 10  # Minimum history lines to compress


@dataclass
class DistillationConfig:
    """Configuration for background distillation."""
    enabled: bool = True
    interval_hours: float = 4.0
    idle_threshold_minutes: float = 10.0
    min_episodes: int = 5
    check_interval_seconds: float = 300.0
    confidence_threshold: float = 0.7


@dataclass
class RetentionConfig:
    """Configuration for data retention."""
    enabled: bool = True
    episode_retention_days: int = 90
    min_score_to_preserve: float = 0.8
    run_interval_hours: int = 24
    preserve_user_confirmed: bool = True


@dataclass
class SkillConfig:
    """Configuration for skill crystallisation."""
    enabled: bool = True
    min_uses: int = 5
    min_avg_score: float = 0.7
    confidence: float = 0.9


@dataclass
class PrivacyConfig:
    """Configuration for privacy features."""
    audit_logging: bool = True
    audit_retention_days: int = 30
    audit_rotation_size_mb: int = 10
    content_hash_salt: Optional[str] = None


@dataclass
class VectorSearchConfig:
    """Configuration for vector search."""
    model_name: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    similarity_threshold: float = 0.6
    max_results: int = 5
    fallback_to_keyword: bool = True


@dataclass
class MemoryConfig:
    """
    Centralized configuration for IRIS Memory Foundation.
    
    All tunable parameters are defined here with sensible defaults.
    Critical settings require restart; non-critical settings support hot-reload.
    """
    
    # Database settings (CRITICAL - requires restart)
    db_path: str = "data/memory.db"
    encryption_enabled: bool = True
    cipher_page_size: int = 4096
    kdf_iterations: int = 64000
    wal_mode: bool = True
    
    # Embedding settings (CRITICAL - requires restart)
    embedding: VectorSearchConfig = field(default_factory=VectorSearchConfig)
    
    # Working memory settings (NON-CRITICAL - hot-reload)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    
    # Learning settings (NON-CRITICAL - hot-reload)
    distillation: DistillationConfig = field(default_factory=DistillationConfig)
    skills: SkillConfig = field(default_factory=SkillConfig)
    
    # Data retention (NON-CRITICAL - hot-reload)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    
    # Privacy settings (NON-CRITICAL - hot-reload)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    
    # Performance settings
    max_context_size: int = 8192
    context_warning_threshold: float = 0.75
    
    # Torus settings (for Phase 6)
    node_id: str = "local"  # Will be Dilithium3 pubkey
    enable_remote_context: bool = False
    
    def validate(self) -> bool:
        """
        Validate configuration values.
        
        Returns:
            True if valid, raises ValueError otherwise
        """
        errors = []
        
        # Validate compression settings
        if not 0.5 <= self.compression.threshold <= 0.95:
            errors.append(f"compression.threshold must be 0.5-0.95, got {self.compression.threshold}")
        
        # Validate distillation settings
        if self.distillation.interval_hours < 1:
            errors.append(f"distillation.interval_hours must be >= 1, got {self.distillation.interval_hours}")
        
        # Validate retention settings
        if self.retention.episode_retention_days < 7:
            errors.append(f"retention.episode_retention_days must be >= 7, got {self.retention.episode_retention_days}")
        
        # Validate skill settings
        if self.skills.min_uses < 3:
            errors.append(f"skills.min_uses must be >= 3, got {self.skills.min_uses}")
        
        # Validate embedding settings
        if self.embedding.similarity_threshold < 0.3 or self.embedding.similarity_threshold > 0.95:
            errors.append(f"embedding.similarity_threshold must be 0.3-0.95, got {self.embedding.similarity_threshold}")
        
        if errors:
            raise ValueError("Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return asdict(self)
    
    def to_json(self, indent: int = 2) -> str:
        """Convert configuration to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryConfig":
        """Load configuration from dictionary."""
        # Handle nested dataclasses
        if "compression" in data:
            data["compression"] = CompressionConfig(**data["compression"])
        if "distillation" in data:
            data["distillation"] = DistillationConfig(**data["distillation"])
        if "retention" in data:
            data["retention"] = RetentionConfig(**data["retention"])
        if "skills" in data:
            data["skills"] = SkillConfig(**data["skills"])
        if "privacy" in data:
            data["privacy"] = PrivacyConfig(**data["privacy"])
        if "embedding" in data:
            data["embedding"] = VectorSearchConfig(**data["embedding"])
        
        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> "MemoryConfig":
        """Load configuration from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    @classmethod
    def from_file(cls, path: str) -> "MemoryConfig":
        """Load configuration from JSON file."""
        path = Path(path)
        if not path.exists():
            logger.warning(f"[MemoryConfig] Config file not found: {path}")
            return cls()  # Return defaults
        
        with open(path, 'r') as f:
            return cls.from_json(f.read())
    
    def save_to_file(self, path: str) -> None:
        """Save configuration to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w') as f:
            f.write(self.to_json())
        
        logger.info(f"[MemoryConfig] Saved to {path}")
    
    def reload_non_critical(self, path: str) -> bool:
        """
        Reload non-critical settings from file (hot-reload).
        
        Args:
            path: Path to configuration file
        
        Returns:
            True if reload was successful
        """
        try:
            new_config = self.from_file(path)
            
            # Only update non-critical settings
            self.compression = new_config.compression
            self.distillation = new_config.distillation
            self.retention = new_config.retention
            self.skills = new_config.skills
            self.privacy = new_config.privacy
            
            logger.info("[MemoryConfig] Hot-reloaded non-critical settings")
            return True
            
        except Exception as e:
            logger.error(f"[MemoryConfig] Hot-reload failed: {e}")
            return False


# Global configuration instance
_config: Optional[MemoryConfig] = None


def get_config() -> MemoryConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = MemoryConfig()
    return _config


def set_config(config: MemoryConfig) -> None:
    """Set the global configuration instance."""
    global _config
    _config = config
    logger.info("[MemoryConfig] Global configuration updated")


def load_config(path: str) -> MemoryConfig:
    """Load configuration from file and set as global."""
    config = MemoryConfig.from_file(path)
    config.validate()
    set_config(config)
    return config
