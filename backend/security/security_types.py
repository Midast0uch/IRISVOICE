"""
Shared security types and classes to avoid circular imports
"""
from typing import Any, Dict, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime


class SecurityLevel(Enum):
    """Security classification levels for MCP operations"""
    SAFE = "safe"
    RESTRICTED = "restricted"
    DANGEROUS = "dangerous"
    BLOCKED = "blocked"


@dataclass
class SecurityValidation:
    """Result of security validation"""
    allowed: bool
    security_level: SecurityLevel
    reason: str
    sanitized_args: Optional[Dict[str, Any]] = None
    risk_score: float = 0.0

    def to_dict(self):
        """Convert to dictionary, handling enum."""
        d = asdict(self)
        d['security_level'] = self.security_level.value
        return d


@dataclass
class SecurityContext:
    """Context for security decisions"""
    session_id: str
    user_id: Optional[str] = None
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None
    tool_name: str = ""
    operation_type: str = ""
    correlation_id: Optional[str] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()