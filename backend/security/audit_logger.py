"""
Security Audit Logger - Comprehensive logging for security events
Provides structured logging for security operations and audit trails
"""
import json
import logging
import os
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, asdict
from enum import Enum

try:
    import aiofiles
except ImportError:
    aiofiles = None

from .security_types import SecurityContext, SecurityValidation, SecurityLevel


class AuditEventType(Enum):
    """Types of security audit events"""
    TOOL_OPERATION = "tool_operation"
    SECURITY_VIOLATION = "security_violation"
    ALLOWLIST_UPDATE = "allowlist_update"
    PATTERN_UPDATE = "pattern_update"
    SESSION_CREATE = "session_create"
    SESSION_DESTROY = "session_destroy"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    CONFIGURATION_CHANGE = "configuration_change"
    EMERGENCY_ACTION = "emergency_action"


class AuditSeverity(Enum):
    """Severity levels for audit events"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    """Represents a security audit event"""
    event_type: AuditEventType
    timestamp: datetime
    session_id: str
    user_id: Optional[str]
    event_data: Dict[str, Any]
    severity: AuditSeverity
    risk_score: float
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None
    correlation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        result['timestamp'] = self.timestamp.isoformat()
        result['event_type'] = self.event_type.value
        result['severity'] = self.severity.value
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AuditEvent':
        """Create from dictionary"""
        return cls(
            event_type=AuditEventType(data['event_type']),
            timestamp=datetime.fromisoformat(data['timestamp']),
            session_id=data['session_id'],
            user_id=data.get('user_id'),
            event_data=data['event_data'],
            severity=AuditSeverity(data['severity']),
            risk_score=data['risk_score'],
            source_ip=data.get('source_ip'),
            user_agent=data.get('user_agent'),
            correlation_id=data.get('correlation_id')
        )


class SecurityAuditLogger:
    """
    Comprehensive security audit logger for IRISVOICE
    Provides structured logging, event correlation, and audit trail management
    """
    
    def __init__(self, log_dir: Optional[Union[str, Path]] = None):
        # Set up log directory
        if log_dir is None:
            base_dir = Path(__file__).parent.parent
            log_dir = base_dir / "logs" / "security"
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize loggers
        self._setup_loggers()
        
        # Event correlation
        self._event_buffer: List[AuditEvent] = []
        self._buffer_size = 1000
        self._correlation_window = 300  # 5 minutes
        
        # Statistics
        self._stats = {
            "events_total": 0,
            "events_by_type": {},
            "events_by_severity": {},
            "unique_sessions": set(),
            "unique_users": set(),
            "risk_score_sum": 0.0,
            "violations_count": 0
        }
        
        # Async lock for thread safety
        self._lock = asyncio.Lock()
    
    def _setup_loggers(self):
        """Set up structured loggers"""
        # Main security audit logger
        self.audit_logger = logging.getLogger("security.audit")
        self.audit_logger.setLevel(logging.INFO)
        
        # Security violations logger
        self.violation_logger = logging.getLogger("security.violations")
        self.violation_logger.setLevel(logging.WARNING)
        
        # Emergency events logger
        self.emergency_logger = logging.getLogger("security.emergency")
        self.emergency_logger.setLevel(logging.CRITICAL)
        
        # Create formatters
        json_formatter = logging.Formatter('%(message)s')  # JSON will be the message
        text_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Audit log file handler
        audit_handler = logging.FileHandler(
            self.log_dir / "security_audit.log",
            encoding='utf-8'
        )
        audit_handler.setFormatter(json_formatter)
        audit_handler.setLevel(logging.INFO)
        self.audit_logger.addHandler(audit_handler)
        
        # Violations log file handler
        violation_handler = logging.FileHandler(
            self.log_dir / "security_violations.log",
            encoding='utf-8'
        )
        violation_handler.setFormatter(json_formatter)
        violation_handler.setLevel(logging.WARNING)
        self.violation_logger.addHandler(violation_handler)
        
        # Emergency log file handler
        emergency_handler = logging.FileHandler(
            self.log_dir / "security_emergency.log",
            encoding='utf-8'
        )
        emergency_handler.setFormatter(json_formatter)
        emergency_handler.setLevel(logging.CRITICAL)
        self.emergency_logger.addHandler(emergency_handler)
        
        # Console handler for critical events
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(text_formatter)
        console_handler.setLevel(logging.CRITICAL)
        self.emergency_logger.addHandler(console_handler)
    
    async def log_tool_operation(
        self,
        tool_name: str,
        operation: str,
        arguments: Dict[str, Any],
        context: SecurityContext,
        result: Any,
        risk_score: float
    ):
        """Log a successful tool operation"""
        
        event = AuditEvent(
            event_type=AuditEventType.TOOL_OPERATION,
            timestamp=datetime.now(),
            session_id=context.session_id if context else "unknown",
            user_id=context.user_id if context else None,
            event_data={
                "tool_name": tool_name,
                "operation": operation,
                "arguments": arguments,
                "result": str(result)  # Keep it concise
            },
            severity=AuditSeverity.INFO,
            risk_score=risk_score,
            source_ip=context.source_ip if context else None,
            user_agent=context.user_agent if context else None,
            correlation_id=context.correlation_id if context else "unknown"
        )
        
        await self._log_event(event)
    
    async def log_allowlist_update(self, tool_name: str, operations: List[str]):
        """Log allowlist configuration changes"""
        event = AuditEvent(
            event_type=AuditEventType.ALLOWLIST_UPDATE,
            timestamp=datetime.now(),
            session_id="system",
            user_id=None,
            event_data={
                "tool_name": tool_name,
                "operations": operations,
                "action": "allowlist_update"
            },
            severity=AuditSeverity.WARNING,
            risk_score=0.3
        )
        
        await self._log_event(event)
    
    async def log_pattern_update(self, name: str, pattern: str, severity: str):
        """Log dangerous pattern configuration changes"""
        event = AuditEvent(
            event_type=AuditEventType.PATTERN_UPDATE,
            timestamp=datetime.now(),
            session_id="system",
            user_id=None,
            event_data={
                "pattern_name": name,
                "pattern": pattern,
                "severity": severity,
                "action": "pattern_update"
            },
            severity=AuditSeverity.WARNING,
            risk_score=0.4
        )
        
        await self._log_event(event)
    
    async def log_session_event(
        self, 
        session_id: str, 
        event_type: str, 
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log session lifecycle events"""
        audit_event_type = (
            AuditEventType.SESSION_CREATE if event_type == "create" else AuditEventType.SESSION_DESTROY
        )
        
        event = AuditEvent(
            event_type=audit_event_type,
            timestamp=datetime.now(),
            session_id=session_id,
            user_id=user_id,
            event_data=metadata or {},
            severity=AuditSeverity.INFO,
            risk_score=0.1,
            correlation_id=session_id
        )
        
        await self._log_event(event)
    
    async def log_emergency_action(self, action: str, reason: str, metadata: Optional[Dict[str, Any]] = None):
        """Log emergency security actions"""
        event = AuditEvent(
            event_type=AuditEventType.EMERGENCY_ACTION,
            timestamp=datetime.now(),
            session_id="system",
            user_id=None,
            event_data={
                "action": action,
                "reason": reason,
                "metadata": metadata or {}
            },
            severity=AuditSeverity.CRITICAL,
            risk_score=1.0
        )
        
        await self._log_event(event)
        
        # Also log to emergency logger
        self.emergency_logger.critical(f"EMERGENCY ACTION: {action} - {reason}")
    
    async def _log_event(self, event: AuditEvent):
        """Internal method to log an event"""
        async with self._lock:
            # Add to buffer
            self._event_buffer.append(event)
            
            # Trim buffer if needed
            if len(self._event_buffer) > self._buffer_size:
                self._event_buffer = self._event_buffer[-self._buffer_size:]
            
            # Update statistics
            self._update_stats(event)
            
            # Write to appropriate log file
            await self._write_event_to_log(event)
    
    async def _write_event_to_log(self, event: AuditEvent):
        """Write event to appropriate log file"""
        event_dict = event.to_dict()
        
        try:
            # Write to main audit log
            self.audit_logger.info(json.dumps(event_dict))
            
            # Write to specific log files based on event type
            if event.event_type == AuditEventType.SECURITY_VIOLATION:
                self.violation_logger.warning(json.dumps(event_dict))
            
            if event.severity == AuditSeverity.CRITICAL:
                self.emergency_logger.critical(json.dumps(event_dict))
            
        except Exception as e:
            # Fallback to error logging if structured logging fails
            logging.error(f"Failed to write security audit event: {e}")
    
    def _update_stats(self, event: AuditEvent):
        """Update statistics"""
        self._stats["events_total"] += 1
        
        # Count by event type
        event_type_str = event.event_type.value
        self._stats["events_by_type"][event_type_str] = (
            self._stats["events_by_type"].get(event_type_str, 0) + 1
        )
        
        # Count by severity
        severity_str = event.severity.value
        self._stats["events_by_severity"][severity_str] = (
            self._stats["events_by_severity"].get(severity_str, 0) + 1
        )
        
        # Track unique sessions and users
        self._stats["unique_sessions"].add(event.session_id)
        if event.user_id:
            self._stats["unique_users"].add(event.user_id)
        
        # Sum risk scores
        self._stats["risk_score_sum"] += event.risk_score
        
        # Count violations
        if event.event_type == AuditEventType.SECURITY_VIOLATION:
            self._stats["violations_count"] += 1
    
    async def get_audit_trail(
        self, 
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        event_type: Optional[AuditEventType] = None,
        severity: Optional[AuditSeverity] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[AuditEvent]:
        """Retrieve audit trail with filtering options"""
        
        async with self._lock:
            events = self._event_buffer.copy()
        
        # Apply filters
        filtered_events = []
        for event in events:
            # Time range filter
            if start_time and event.timestamp < start_time:
                continue
            if end_time and event.timestamp > end_time:
                continue
            
            # Session filter
            if session_id and event.session_id != session_id:
                continue
            
            # User filter
            if user_id and event.user_id != user_id:
                continue
            
            # Event type filter
            if event_type and event.event_type != event_type:
                continue
            
            # Severity filter
            if severity and event.severity != severity:
                continue
            
            filtered_events.append(event)
        
        # Sort by timestamp (newest first) and limit
        filtered_events.sort(key=lambda x: x.timestamp, reverse=True)
        return filtered_events[:limit]
    
    async def get_security_analytics(self) -> Dict[str, Any]:
        """Get security analytics and statistics"""
        async with self._lock:
            total_events = self._stats["events_total"]
            
            if total_events == 0:
                return {
                    "total_events": 0,
                    "violations_rate": 0,
                    "average_risk_score": 0,
                    "unique_sessions": 0,
                    "unique_users": 0
                }
            
            return {
                "total_events": total_events,
                "events_by_type": self._stats["events_by_type"].copy(),
                "events_by_severity": self._stats["events_by_severity"].copy(),
                "violations_rate": (self._stats["violations_count"] / total_events * 100),
                "average_risk_score": (self._stats["risk_score_sum"] / total_events),
                "unique_sessions": len(self._stats["unique_sessions"]),
                "unique_users": len(self._stats["unique_users"]),
                "recent_violations": len([
                    e for e in self._event_buffer[-100:] 
                    if e.event_type == AuditEventType.SECURITY_VIOLATION
                ])
            }
    
    async def detect_anomalies(self) -> List[Dict[str, Any]]:
        """Detect security anomalies in recent events"""
        async with self._lock:
            recent_events = self._event_buffer[-100:]  # Last 100 events
        
        anomalies = []
        
        # Check for violation spikes
        violations_in_window = len([
            e for e in recent_events 
            if e.event_type == AuditEventType.SECURITY_VIOLATION
        ])
        
        if violations_in_window > 10:  # More than 10 violations in last 100 events
            anomalies.append({
                "type": "violation_spike",
                "severity": "high",
                "description": f"High number of security violations: {violations_in_window}/100",
                "recommendation": "Review security policies and investigate potential attacks"
            })
        
        # Check for high-risk events
        high_risk_events = len([
            e for e in recent_events 
            if e.risk_score > 0.8
        ])
        
        if high_risk_events > 5:
            anomalies.append({
                "type": "high_risk_activity",
                "severity": "critical",
                "description": f"Multiple high-risk events detected: {high_risk_events}/100",
                "recommendation": "Immediate security review required"
            })
        
        # Check for unusual session activity
        session_counts = {}
        for event in recent_events:
            session_counts[event.session_id] = session_counts.get(event.session_id, 0) + 1
        
        for session_id, count in session_counts.items():
            if count > 50:  # Session with more than 50 events in window
                anomalies.append({
                    "type": "session_anomaly",
                    "severity": "medium",
                    "description": f"Unusual session activity: {count} events from {session_id}",
                    "recommendation": "Monitor session for potential abuse"
                })
        
        return anomalies
    
    async def export_audit_log(
        self, 
        output_path: Union[str, Path],
        format: str = "json",
        **filter_kwargs
    ) -> bool:
        """Export audit log to file"""
        try:
            events = await self.get_audit_trail(**filter_kwargs)
            
            if format.lower() == "json":
                export_data = {
                    "export_metadata": {
                        "exported_at": datetime.now().isoformat(),
                        "total_events": len(events),
                        "filters": filter_kwargs
                    },
                    "events": [event.to_dict() for event in events]
                }
                
                if aiofiles:
                    async with aiofiles.open(output_path, 'w') as f:
                        await f.write(json.dumps(export_data, indent=2))
                else:
                    with open(output_path, 'w') as f:
                        json.dump(export_data, f, indent=2)
                    
            elif format.lower() == "csv":
                import csv
                
                with open(output_path, 'w', newline='', encoding='utf-8') as f:
                    if events:
                        writer = csv.DictWriter(f, fieldnames=events[0].to_dict().keys())
                        writer.writeheader()
                        for event in events:
                            writer.writerow(event.to_dict())
            
            else:
                raise ValueError(f"Unsupported export format: {format}")
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to export audit log: {e}")
            return False
    
    async def cleanup_old_logs(self, days_to_keep: int = 30) -> int:
        """Clean up audit logs older than specified days"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            cleaned_count = 0
            
            for log_file in self.log_dir.glob("*.log"):
                if log_file.stat().st_mtime < cutoff_date.timestamp():
                    log_file.unlink()
                    cleaned_count += 1
            
            return cleaned_count
            
        except Exception as e:
            logging.error(f"Failed to cleanup old logs: {e}")
            return 0
    
    def get_log_summary(self) -> Dict[str, Any]:
        """Get summary of current log files"""
        try:
            log_files = list(self.log_dir.glob("*.log"))

            return {
                "total_files": len(log_files),
                "total_size": sum(f.stat().st_size for f in log_files),
                "files": [
                    {
                        "name": f.name,
                        "size": f.stat().st_size,
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
                    }
                    for f in log_files
                ]
            }

        except Exception as e:
            logging.error(f"Failed to get log summary: {e}")
            return {"error": str(e)}

    def close(self):
        """Close all file handlers"""
        # Close handlers for each logger
        for logger in [self.audit_logger, self.violation_logger, self.emergency_logger]:
            for handler in logger.handlers[:]:
                try:
                    handler.close()
                    logger.removeHandler(handler)
                except Exception:
                    pass  # Ignore errors during cleanup


    async def log_security_violation(
        self,
        validation_result: SecurityValidation,
        context: SecurityContext,
        tool_name: str,
        operation_type: str,
        sanitized_args: Optional[Dict[str, Any]] = None
    ):
        """Log a security violation"""
        
        event = AuditEvent(
            event_type=AuditEventType.SECURITY_VIOLATION,
            timestamp=datetime.now(),
            session_id=context.session_id if context else "unknown",
            user_id=context.user_id if context else None,
            event_data={
                "tool_name": tool_name,
                "operation_type": operation_type,
                "validation_result": validation_result.to_dict(),
                "sanitized_args": sanitized_args
            },
            severity=AuditSeverity.CRITICAL,
            risk_score=validation_result.risk_score,
            source_ip=context.source_ip if context else None,
            user_agent=context.user_agent if context else None,
            correlation_id=context.correlation_id if context else "unknown"
        )
        
        await self._log_event(event)

# Convenience functions for common logging scenarios
async def log_security_violation(
    session_id: str,
    violation_type: str,
    details: Dict[str, Any],
    risk_score: float = 0.8
):
    """Convenience function to log security violations"""
    logger = SecurityAuditLogger()
    
    event = AuditEvent(
        event_type=AuditEventType.SECURITY_VIOLATION,
        timestamp=datetime.now(),
        session_id=session_id,
        user_id=None,
        event_data={
            "violation_type": violation_type,
            "details": details
        },
        severity=AuditSeverity.CRITICAL,
        risk_score=risk_score
    )
    
    await logger._log_event(event)


async def log_emergency_action(action: str, reason: str):
    """Convenience function to log emergency actions"""
    logger = SecurityAuditLogger()
    await logger.log_emergency_action(action, reason)