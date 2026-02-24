"""
Security event correlation and analytics for IRISVOICE.

Provides security insights by analyzing and correlating security events across sessions.
"""

import json
import asyncio
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter

from backend.monitoring.structured_logger import StructuredLogger, LogContext
from backend.monitoring.session_correlation import SessionAwareLogger, get_session_context


@dataclass
class SecurityEvent:
    """Represents a security event for analysis."""
    timestamp: datetime
    event_type: str
    session_id: str
    workspace_id: Optional[str]
    user_id: Optional[str]
    details: Dict[str, Any]
    severity: str  # "low", "medium", "high", "critical"
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None


@dataclass
class SecurityPattern:
    """Represents a detected security pattern."""
    pattern_id: str
    pattern_type: str
    description: str
    events: List[SecurityEvent]
    first_seen: datetime
    last_seen: datetime
    severity: str
    affected_sessions: Set[str]
    affected_users: Set[str]
    confidence: float  # 0.0 to 1.0


class SecurityEventCollector:
    """Collects and stores security events for analysis."""

    def __init__(self, max_events: int = 10000, retention_hours: int = 24):
        """
        Initialize the security event collector.

        Args:
            max_events: Maximum number of events to keep in memory
            retention_hours: Hours to retain events before cleanup
        """
        self.max_events = max_events
        self.retention_hours = retention_hours
        self.events: List[SecurityEvent] = []
        self.events_by_session: Dict[str, List[SecurityEvent]] = defaultdict(list)
        self.events_by_user: Dict[str, List[SecurityEvent]] = defaultdict(list)
        self.events_by_type: Dict[str, List[SecurityEvent]] = defaultdict(list)

    def add_event(self, event: SecurityEvent) -> None:
        """Add a security event to the collector."""
        self.events.append(event)
        self.events_by_session[event.session_id].append(event)
        if event.user_id:
            self.events_by_user[event.user_id].append(event)
        self.events_by_type[event.event_type].append(event)

        # Maintain size limits
        if len(self.events) > self.max_events:
            self._cleanup_old_events()

    def _cleanup_old_events(self) -> None:
        """Clean up old events based on retention policy."""
        cutoff_time = datetime.utcnow() - timedelta(hours=self.retention_hours)
        
        # Filter events
        self.events = [e for e in self.events if e.timestamp > cutoff_time]
        
        # Rebuild indexes
        self.events_by_session.clear()
        self.events_by_user.clear()
        self.events_by_type.clear()
        
        for event in self.events:
            self.events_by_session[event.session_id].append(event)
            if event.user_id:
                self.events_by_user[event.user_id].append(event)
            self.events_by_type[event.event_type].append(event)

    def get_events(self, session_id: Optional[str] = None, user_id: Optional[str] = None,
                  event_type: Optional[str] = None, severity: Optional[str] = None,
                  time_range: Optional[timedelta] = None) -> List[SecurityEvent]:
        """Get filtered security events."""
        events = self.events
        
        if session_id:
            events = [e for e in events if e.session_id == session_id]
        if user_id:
            events = [e for e in events if e.user_id == user_id]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if severity:
            events = [e for e in events if e.severity == severity]
        if time_range:
            cutoff_time = datetime.utcnow() - time_range
            events = [e for e in events if e.timestamp > cutoff_time]
        
        return events


class SecurityPatternDetector:
    """Detects security patterns and anomalies."""

    def __init__(self, event_collector: SecurityEventCollector):
        """Initialize the pattern detector."""
        self.event_collector = event_collector
        self.detected_patterns: List[SecurityPattern] = []

    def detect_brute_force_attempts(self, time_window: timedelta = timedelta(minutes=15),
                                   threshold: int = 5) -> List[SecurityPattern]:
        """Detect brute force login attempts."""
        patterns = []
        
        # Get recent failed login events
        failed_logins = self.event_collector.get_events(
            event_type="login_failed",
            time_range=time_window
        )
        
        # Group by source IP
        by_ip = defaultdict(list)
        for event in failed_logins:
            if event.source_ip:
                by_ip[event.source_ip].append(event)
        
        for ip, events in by_ip.items():
            if len(events) >= threshold:
                sessions = set(e.session_id for e in events)
                users = set(e.user_id for e in events if e.user_id)
                
                pattern = SecurityPattern(
                    pattern_id=f"brute_force_{ip}_{datetime.utcnow().isoformat()}",
                    pattern_type="brute_force_attack",
                    description=f"Potential brute force attack from IP {ip}",
                    events=events,
                    first_seen=min(e.timestamp for e in events),
                    last_seen=max(e.timestamp for e in events),
                    severity="high",
                    affected_sessions=sessions,
                    affected_users=users,
                    confidence=min(1.0, len(events) / threshold)
                )
                patterns.append(pattern)
        
        return patterns

    def detect_privilege_escalation(self, time_window: timedelta = timedelta(hours=1)) -> List[SecurityPattern]:
        """Detect potential privilege escalation attempts."""
        patterns = []
        
        # Get permission denied and successful access events
        denied_events = self.event_collector.get_events(
            event_type="permission_denied",
            time_range=time_window
        )
        
        successful_access = self.event_collector.get_events(
            event_type="resource_access",
            time_range=time_window
        )
        
        # Look for users who had permission denied followed by successful access
        by_user = defaultdict(lambda: {"denied": [], "successful": []})
        
        for event in denied_events:
            if event.user_id:
                by_user[event.user_id]["denied"].append(event)
        
        for event in successful_access:
            if event.user_id:
                by_user[event.user_id]["successful"].append(event)
        
        for user_id, events in by_user.items():
            if events["denied"] and events["successful"]:
                # Check if successful access came after denied attempts
                denied_times = [e.timestamp for e in events["denied"]]
                successful_times = [e.timestamp for e in events["successful"]]
                
                if max(denied_times) < max(successful_times):
                    all_events = events["denied"] + events["successful"]
                    sessions = set(e.session_id for e in all_events)
                    
                    pattern = SecurityPattern(
                        pattern_id=f"privilege_escalation_{user_id}_{datetime.utcnow().isoformat()}",
                        pattern_type="privilege_escalation",
                        description=f"Potential privilege escalation by user {user_id}",
                        events=all_events,
                        first_seen=min(e.timestamp for e in all_events),
                        last_seen=max(e.timestamp for e in all_events),
                        severity="critical",
                        affected_sessions=sessions,
                        affected_users={user_id},
                        confidence=0.7  # Medium confidence
                    )
                    patterns.append(pattern)
        
        return patterns

    def detect_unusual_session_activity(self, time_window: timedelta = timedelta(hours=1)) -> List[SecurityPattern]:
        """Detect unusual session activity patterns."""
        patterns = []
        
        # Get events by session
        recent_events = self.event_collector.get_events(time_range=time_window)
        
        by_session = defaultdict(list)
        for event in recent_events:
            by_session[event.session_id].append(event)
        
        for session_id, events in by_session.items():
            if len(events) > 50:  # High activity threshold
                users = set(e.user_id for e in events if e.user_id)
                
                pattern = SecurityPattern(
                    pattern_id=f"high_activity_{session_id}_{datetime.utcnow().isoformat()}",
                    pattern_type="unusual_activity",
                    description=f"Unusually high activity in session {session_id}",
                    events=events,
                    first_seen=min(e.timestamp for e in events),
                    last_seen=max(e.timestamp for e in events),
                    severity="medium",
                    affected_sessions={session_id},
                    affected_users=users,
                    confidence=0.8
                )
                patterns.append(pattern)
        
        return patterns

    def detect_all_patterns(self) -> List[SecurityPattern]:
        """Run all pattern detection algorithms."""
        patterns = []
        
        patterns.extend(self.detect_brute_force_attempts())
        patterns.extend(self.detect_privilege_escalation())
        patterns.extend(self.detect_unusual_session_activity())
        
        return patterns


class SecurityAnalytics:
    """Main security analytics engine."""

    def __init__(self, logger: StructuredLogger):
        """Initialize security analytics."""
        self.logger = logger
        self.event_collector = SecurityEventCollector()
        self.pattern_detector = SecurityPatternDetector(self.event_collector)
        self.analytics_logger = SessionAwareLogger(logger)

    async def record_security_event(self, event_type: str, details: Dict[str, Any],
                                  severity: str = "medium", session_id: Optional[str] = None) -> None:
        """Record a security event for analysis."""
        context = get_session_context()
        
        event = SecurityEvent(
            timestamp=datetime.utcnow(),
            event_type=event_type,
            session_id=session_id or context.get("session_id", "unknown"),
            workspace_id=context.get("workspace_id"),
            user_id=context.get("user_id"),
            details=details,
            severity=severity,
            source_ip=details.get("source_ip"),
            user_agent=details.get("user_agent")
        )
        
        self.event_collector.add_event(event)
        
        # Log the event
        self.analytics_logger.security_event(event_type, details)

    async def analyze_security_patterns(self) -> List[SecurityPattern]:
        """Analyze security patterns and return findings."""
        patterns = self.pattern_detector.detect_all_patterns()
        
        # Log pattern detection results
        if patterns:
            self.analytics_logger.info(f"Detected {len(patterns)} security patterns")
            for pattern in patterns:
                self.analytics_logger.warning(
                    f"Security pattern detected: {pattern.pattern_type}",
                    pattern_id=pattern.pattern_id,
                    severity=pattern.severity,
                    confidence=pattern.confidence,
                    affected_sessions=list(pattern.affected_sessions),
                    affected_users=list(pattern.affected_users)
                )
        
        return patterns

    async def get_security_summary(self, time_range: timedelta = timedelta(hours=24)) -> Dict[str, Any]:
        """Get a security summary for the specified time range."""
        events = self.event_collector.get_events(time_range=time_range)
        
        if not events:
            return {"status": "no_events", "message": "No security events in the specified time range"}
        
        # Basic statistics
        total_events = len(events)
        events_by_severity = Counter(e.severity for e in events)
        events_by_type = Counter(e.event_type for e in events)
        unique_sessions = len(set(e.session_id for e in events))
        unique_users = len(set(e.user_id for e in events if e.user_id))
        
        # Detect patterns
        patterns = await self.analyze_security_patterns()
        
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "time_range_hours": time_range.total_seconds() / 3600,
            "total_events": total_events,
            "events_by_severity": dict(events_by_severity),
            "events_by_type": dict(events_by_type),
            "unique_sessions": unique_sessions,
            "unique_users": unique_users,
            "detected_patterns": len(patterns),
            "patterns": [asdict(p) for p in patterns]
        }
        
        # Log summary
        self.analytics_logger.info("Security summary generated", summary=summary)
        
        return summary

    async def cleanup_old_events(self) -> None:
        """Clean up old security events."""
        self.event_collector._cleanup_old_events()
        self.analytics_logger.info("Cleaned up old security events")


# Global security analytics instance
_global_analytics: Optional[SecurityAnalytics] = None


def get_security_analytics(logger: Optional[StructuredLogger] = None) -> SecurityAnalytics:
    """Get or create the global security analytics instance."""
    global _global_analytics
    if _global_analytics is None:
        if logger is None:
            from backend.monitoring.structured_logger import configure_logging
            logger = configure_logging()
        _global_analytics = SecurityAnalytics(logger)
    return _global_analytics


# Example usage
if __name__ == "__main__":
    from backend.monitoring.structured_logger import configure_logging
    import asyncio

    async def example_usage():
        # Configure logging
        logger = configure_logging(log_level="INFO")
        analytics = get_security_analytics(logger)

        # Record some security events
        await analytics.record_security_event(
            "login_failed",
            {"username": "admin", "source_ip": "192.168.1.100", "reason": "invalid_password"},
            severity="medium"
        )

        await analytics.record_security_event(
            "permission_denied",
            {"resource": "/admin/settings", "required_permission": "admin"},
            severity="high"
        )

        # Analyze patterns
        patterns = await analytics.analyze_security_patterns()
        print(f"Detected {len(patterns)} security patterns")

        # Get security summary
        summary = await analytics.get_security_summary()
        print("Security Summary:", json.dumps(summary, indent=2))

    # Run example
    asyncio.run(example_usage())