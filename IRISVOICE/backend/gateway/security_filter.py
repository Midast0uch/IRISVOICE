"""
Security Filter - Gateway-level security validation and filtering
"""

import logging
import re
from typing import Dict, Any, Optional, List, Set, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .iris_gateway import GatewayMessage, MessageType
from ..security.mcp_security import MCPSecurityManager
from ..security.audit_logger import SecurityAuditLogger
from ..security.security_types import SecurityLevel, SecurityContext, SecurityValidation


@dataclass
class FilterRule:
    """Defines a security filter rule"""
    name: str
    message_types: Set[MessageType]
    conditions: List[Callable[[GatewayMessage], bool]]
    action: str  # "allow", "block", "log", "rate_limit"
    description: str = ""
    priority: int = 0


@dataclass
class FilterResult:
    """Result of applying security filters"""
    allowed: bool
    reason: str
    rule_name: str = ""
    log_level: str = "info"


class SecurityFilter:
    """Gateway-level security filter for message validation"""
    
    def __init__(self, security_manager: Optional[MCPSecurityManager] = None, 
                 audit_logger: Optional[SecurityAuditLogger] = None):
        """Initialize the security filter"""
        self.security_manager = security_manager or MCPSecurityManager()
        self.audit_logger = audit_logger or SecurityAuditLogger()
        self.logger = logging.getLogger(__name__)
        
        self._filter_rules: List[FilterRule] = []
        self._rate_limits: Dict[str, List[datetime]] = {}
        self._blocked_patterns: Dict[str, re.Pattern] = {}
        
        # Initialize default filter rules
        self._initialize_default_rules()
        self._initialize_blocked_patterns()
    
    def _initialize_default_rules(self):
        """Initialize default security filter rules"""
        self._load_default_rules()

    def _load_default_rules(self):
        """Load default security filter rules"""
        # Rule to block dangerous commands
        self.add_rule(
            FilterRule(
                name="block_dangerous_commands",
                description="Block messages containing dangerous command patterns",
                priority=100,
                message_types={MessageType.SYSTEM_COMMAND},
                conditions=[lambda msg: self._contains_dangerous_command(msg.payload.get("command"))],
                action="block"
            )
        )
        
        # Rate limit session creation
        self.add_rule(FilterRule(
            name="rate_limit_session_create",
            message_types={MessageType.SESSION_CREATE},
            conditions=[
                lambda msg: self._check_rate_limit(f"session_create_{msg.client_id}", 5, 60)
            ],
            action="rate_limit",
            description="Rate limit session creation per client",
            priority=90
        ))
        
        # Block automation requests without proper session
        self.add_rule(FilterRule(
            name="block_automation_without_session",
            message_types={MessageType.AUTOMATION_REQUEST},
            conditions=[
                lambda msg: msg.session_id is None
            ],
            action="block",
            description="Block automation requests without session",
            priority=80
        ))
        
        # Log all vision requests
        self.add_rule(FilterRule(
            name="log_vision_requests",
            message_types={MessageType.VISION_REQUEST},
            conditions=[
                lambda msg: True
            ],
            action="log",
            description="Log all vision requests",
            priority=70
        ))
        
        # Block vision requests with suspicious patterns
        self.add_rule(FilterRule(
            name="block_suspicious_vision",
            message_types={MessageType.VISION_REQUEST},
            conditions=[
                lambda msg: self._contains_suspicious_vision(msg.payload.get("vision_request", {}))
            ],
            action="block",
            description="Block suspicious vision requests",
            priority=85
        ))
        
        # Rate limit state updates
        self.add_rule(FilterRule(
            name="rate_limit_state_updates",
            message_types={MessageType.STATE_UPDATE},
            conditions=[
                lambda msg: self._check_rate_limit(f"state_update_{msg.session_id}", 10, 1)
            ],
            action="rate_limit",
            description="Rate limit state updates per session",
            priority=60
        ))
    
    def _initialize_blocked_patterns(self):
        """Initialize blocked patterns for security filtering"""
        # Dangerous command patterns
        self._blocked_patterns["dangerous_commands"] = re.compile(
            r"\b(rm\s+-rf|format|del\s+/q|shutdown|reboot|sudo|administrator)\"",
            re.IGNORECASE
        )
        
        # Suspicious file operations
        self._blocked_patterns["suspicious_files"] = re.compile(
            r"\b(/etc/passwd|/etc/shadow|C:\\\\Windows\\\\System32|\.\.\\|system32)\"",
            re.IGNORECASE
        )
        
        # Network-related patterns
        self._blocked_patterns["network_danger"] = re.compile(
            r"\b(nc\s+-|netcat|telnet|ftp|ssh|rdp)\"",
            re.IGNORECASE
        )

    def _contains_dangerous_command(self, command: Optional[str]) -> bool:
        """Check if a command contains dangerous patterns"""
        if not command:
            return False
        
        return self._blocked_patterns["dangerous_commands"].search(command) is not None

    def _contains_suspicious_vision(self, vision_payload: Dict[str, Any]) -> bool:
        """Check if a vision request contains suspicious patterns"""
        if not vision_payload:
            return False
        
        # Example: check for suspicious keywords in vision requests
        suspicious_keywords = ["password", "credit_card", "ssn"]
        
        for key, value in vision_payload.items():
            if isinstance(value, str):
                for keyword in suspicious_keywords:
                    if keyword in value.lower():
                        return True
        return False
    
    def add_rule(self, rule: FilterRule):
        """Add a filter rule"""
        self._filter_rules.append(rule)
        # Sort by priority (highest first)
        self._filter_rules.sort(key=lambda r: r.priority, reverse=True)
        self.logger.info(f"Added filter rule: {rule.name}")
    
    def remove_rule(self, rule_name: str):
        """Remove a filter rule by name"""
        self._filter_rules = [rule for rule in self._filter_rules if rule.name != rule_name]
        self.logger.info(f"Removed filter rule: {rule_name}")
    
    async def apply_filters(self, message: GatewayMessage) -> FilterResult:
        """Apply all security filters to a message"""
        try:
            self.logger.info(f"Applying filters to message {message.id} of type {message.type.value}")
            
            # Check each filter rule
            for rule in self._filter_rules:
                if message.type in rule.message_types:
                    # Check all conditions for this rule
                    conditions_met = all(condition(message) for condition in rule.conditions)
                    
                    if conditions_met:
                        # Apply the rule action
                        result = await self._apply_rule_action(rule, message)
                        self.logger.info(f"Applied filter rule {rule.name}: {result.allowed}")
                        return result
            
            # No matching rules, allow by default
            return FilterResult(
                allowed=True,
                reason="No matching filter rules",
                log_level="debug"
            )
            
        except Exception as e:
            self.logger.error(f"Error applying filters to message {message.id}: {e}")
            # Block on filter errors for safety
            return FilterResult(
                allowed=False,
                reason=f"Filter error: {str(e)}",
                rule_name="filter_error",
                log_level="error"
            )
    
    async def _apply_rule_action(self, rule: FilterRule, message: GatewayMessage) -> FilterResult:
        """Apply a filter rule action"""
        if rule.action == "allow":
            return FilterResult(
                allowed=True,
                reason=f"Allowed by rule: {rule.name}",
                rule_name=rule.name,
                log_level="info"
            )
        
        elif rule.action == "block":
            # Log the block
            await self.audit_logger.log_tool_operation(
                context=SecurityContext(
                    session_id=message.session_id,
                    user_id=message.client_id,
                    tool_name="gateway_filter",
                    operation_type="block",
                    timestamp=datetime.now()
                ),
                validation=SecurityValidation(
                    allowed=False,
                    level=SecurityLevel.BLOCKED,
                    reason=f"Blocked by filter rule: {rule.description}"
                )
            )
            
            return FilterResult(
                allowed=False,
                reason=f"Blocked by rule: {rule.name}",
                rule_name=rule.name,
                log_level="warning"
            )
        
        elif rule.action == "log":
            # Log but allow
            await self.audit_logger.log_tool_operation(
                context=SecurityContext(
                    session_id=message.session_id,
                    user_id=message.client_id,
                    tool_name="gateway_filter",
                    operation_type="log",
                    timestamp=datetime.now()
                ),
                validation=SecurityValidation(
                    allowed=True,
                    level=SecurityLevel.SAFE,
                    reason=f"Logged by filter rule: {rule.description}"
                )
            )
            
            return FilterResult(
                allowed=True,
                reason=f"Logged by rule: {rule.name}",
                rule_name=rule.name,
                log_level="info"
            )
        
        elif rule.action == "rate_limit":
            # Log the rate limit
            await self.audit_logger.log_tool_operation(
                context=SecurityContext(
                    session_id=message.session_id,
                    user_id=message.client_id,
                    tool_name="gateway_filter",
                    operation_type="rate_limit",
                    timestamp=datetime.now()
                ),
                validation=SecurityValidation(
                    allowed=False,
                    level=SecurityLevel.DANGEROUS,
                    reason=f"Rate limited by rule: {rule.description}"
                )
            )
            
            return FilterResult(
                allowed=False,
                reason=f"Rate limited by rule: {rule.name}",
                rule_name=rule.name,
                log_level="warning"
            )
        
        else:
            # Unknown action, block for safety
            return FilterResult(
                allowed=False,
                reason=f"Unknown filter action: {rule.action}",
                rule_name=rule.name,
                log_level="error"
            )
    
    def _contains_dangerous_command(self, command_payload: Dict[str, Any]) -> bool:
        """Check if command contains dangerous patterns"""
        if not command_payload:
            return False
        
        command_str = str(command_payload)
        
        # Check against blocked patterns
        for pattern_name, pattern in self._blocked_patterns.items():
            if pattern.search(command_str):
                self.logger.warning(f"Found dangerous pattern {pattern_name} in command")
                return True
        
        return False
    
    def _contains_suspicious_vision(self, vision_payload: Dict[str, Any]) -> bool:
        """Check if vision request contains suspicious patterns"""
        if not vision_payload:
            return False
        
        vision_str = str(vision_payload)
        
        # Check for suspicious vision patterns
        suspicious_patterns = [
            r"\b(password|login|credential|secret)\"",
            r"\b(admin|root|sudo)\"",
            r"\b(bank|payment|credit)\""
        ]
        
        for pattern in suspicious_patterns:
            if re.search(pattern, vision_str, re.IGNORECASE):
                self.logger.warning(f"Found suspicious vision pattern: {pattern}")
                return True
        
        return False
    
    def _check_rate_limit(self, key: str, max_requests: int, time_window_seconds: int) -> bool:
        """Check if rate limit is exceeded"""
        now = datetime.now()
        
        # Initialize rate limit tracking for this key
        if key not in self._rate_limits:
            self._rate_limits[key] = []
        
        # Clean up old entries
        cutoff_time = now - timedelta(seconds=time_window_seconds)
        self._rate_limits[key] = [
            timestamp for timestamp in self._rate_limits[key]
            if timestamp > cutoff_time
        ]
        
        # Check if limit exceeded
        if len(self._rate_limits[key]) >= max_requests:
            self.logger.warning(f"Rate limit exceeded for {key}: {len(self._rate_limits[key])} requests in {time_window_seconds}s")
            return True
        
        # Add current request
        self._rate_limits[key].append(now)
        return False
    
    def get_filter_stats(self) -> Dict[str, Any]:
        """Get filter statistics"""
        return {
            "total_rules": len(self._filter_rules),
            "rate_limit_keys": len(self._rate_limits),
            "blocked_patterns": len(self._blocked_patterns),
            "rule_priorities": [rule.priority for rule in self._filter_rules],
            "message_types_covered": list(set(
                mt.value for rule in self._filter_rules for mt in rule.message_types
            ))
        }