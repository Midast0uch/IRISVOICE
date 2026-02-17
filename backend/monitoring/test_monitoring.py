"""
Tests for the monitoring and logging system.

Validates structured logging, session correlation, and security analytics.
"""

import asyncio
import json
import logging
import pytest
from pathlib import Path
from datetime import datetime, timedelta

from backend.monitoring.structured_logger import (StructuredLogger, StructuredFormatter, 
                                                  configure_logging, LogContext)
from backend.monitoring.session_correlation import (SessionAwareLogger, set_session_context, 
                                                    clear_session_context)
from backend.monitoring.security_analytics import (SecurityAnalytics, SecurityEvent, 
                                                     get_security_analytics)


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    """Fixture for a temporary log file."""
    return tmp_path / "test.log"


@pytest.fixture
def structured_logger(log_file: Path) -> StructuredLogger:
    """Fixture for a structured logger instance."""
    return StructuredLogger("test_logger", log_level="DEBUG", log_file=log_file)


class TestStructuredLogger:
    """Tests for the StructuredLogger class."""

    def test_log_file_creation(self, log_file: Path):
        """Test that the log file is created."""
        assert not log_file.exists()
        logger = StructuredLogger("test_file_creation", log_file=log_file)
        logger.info("Test message")
        assert log_file.exists()

    def test_structured_log_format(self, structured_logger: StructuredLogger, log_file: Path):
        """Test that logs are written in structured JSON format."""
        structured_logger.info("Test structured log")
        
        log_content = log_file.read_text()
        log_json = json.loads(log_content)
        
        assert log_json["level"] == "INFO"
        assert log_json["message"] == "Test structured log"
        assert "timestamp" in log_json

    def test_log_context_injection(self, structured_logger: StructuredLogger, log_file: Path):
        """Test that context is correctly injected into logs."""
        structured_logger.set_context(session_id="session123", component="test_component")
        structured_logger.warning("Test context log")
        
        log_json = json.loads(log_file.read_text())
        
        assert log_json["session_id"] == "session123"
        assert log_json["component"] == "test_component"

    def test_security_event_logging(self, structured_logger: StructuredLogger, log_file: Path):
        """Test logging of security events."""
        structured_logger.security_event("test_event", {"detail": "value"})
        
        log_json = json.loads(log_file.read_text())
        
        assert log_json["level"] == "WARNING"
        assert log_json["event_type"] == "test_event"
        assert log_json["security_event"] is True
        assert log_json["details"] == {"detail": "value"}

    def test_performance_metric_logging(self, structured_logger: StructuredLogger, log_file: Path):
        """Test logging of performance metrics."""
        structured_logger.performance_metric("test_metric", 123.4, "ms")
        
        log_json = json.loads(log_file.read_text())
        
        assert log_json["level"] == "INFO"
        assert log_json["metric_name"] == "test_metric"
        assert log_json["metric_value"] == 123.4
        assert log_json["metric_unit"] == "ms"


@pytest.fixture
def session_aware_logger(structured_logger: StructuredLogger) -> SessionAwareLogger:
    """Fixture for a session-aware logger."""
    return SessionAwareLogger(structured_logger)


@pytest.mark.asyncio
class TestSessionAwareLogger:
    """Tests for the SessionAwareLogger class."""

    async def test_automatic_session_context(self, session_aware_logger: SessionAwareLogger, log_file: Path):
        """Test that session context is automatically added to logs."""
        await set_session_context(session_id="auto_session", workspace_id="auto_workspace")
        
        session_aware_logger.info("Test automatic context")
        
        log_json = json.loads(log_file.read_text())
        
        assert log_json["session_id"] == "auto_session"
        assert log_json["workspace_id"] == "auto_workspace"
        
        clear_session_context()

    async def test_context_is_cleared(self, session_aware_logger: SessionAwareLogger, log_file: Path):
        """Test that session context is properly cleared."""
        await set_session_context(session_id="temp_session")
        session_aware_logger.info("Temporary context")
        clear_session_context()
        
        session_aware_logger.info("No context")
        
        logs = log_file.read_text().strip().split("\n")
        log1 = json.loads(logs[0])
        log2 = json.loads(logs[1])
        
        assert "session_id" in log1
        assert "session_id" not in log2


@pytest.fixture
def security_analytics(structured_logger: StructuredLogger) -> SecurityAnalytics:
    """Fixture for the security analytics engine."""
    # Reset global instance for clean tests
    from backend.monitoring import security_analytics
    security_analytics._global_analytics = None
    return get_security_analytics(structured_logger)


@pytest.mark.asyncio
class TestSecurityAnalytics:
    """Tests for the SecurityAnalytics engine."""

    async def test_record_and_get_security_events(self, security_analytics: SecurityAnalytics):
        """Test recording and retrieving security events."""
        await security_analytics.record_security_event(
            "test_event", {"detail": "value"}, severity="high", session_id="session1"
        )
        
        events = security_analytics.event_collector.get_events(session_id="session1")
        assert len(events) == 1
        assert events[0].event_type == "test_event"
        assert events[0].severity == "high"

    async def test_brute_force_detection(self, security_analytics: SecurityAnalytics):
        """Test detection of brute force attacks."""
        for i in range(6):
            await security_analytics.record_security_event(
                "login_failed", {"source_ip": "1.2.3.4"}, severity="medium", session_id=f"session_{i}"
            )
        
        patterns = await security_analytics.analyze_security_patterns()
        
        assert len(patterns) == 1
        assert patterns[0].pattern_type == "brute_force_attack"
        assert patterns[0].severity == "high"
        assert "1.2.3.4" in patterns[0].description

    async def test_privilege_escalation_detection(self, security_analytics: SecurityAnalytics):
        """Test detection of privilege escalation attempts."""
        await set_session_context(session_id="session1", user_id="user123")
        
        await security_analytics.record_security_event(
            "permission_denied", {"resource": "/admin"}, severity="high", session_id="session1"
        )
        
        await asyncio.sleep(0.1) # Ensure time difference
        
        await security_analytics.record_security_event(
            "resource_access", {"resource": "/admin"}, severity="low", session_id="session2"
        )
        
        patterns = await security_analytics.analyze_security_patterns()
        
        assert len(patterns) == 1
        assert patterns[0].pattern_type == "privilege_escalation"
        assert patterns[0].severity == "critical"
        assert "user123" in patterns[0].description
        
        clear_session_context()

    async def test_security_summary_generation(self, security_analytics: SecurityAnalytics):
        """Test generation of security summary."""
        await security_analytics.record_security_event("test_event", {}, severity="low")
        await security_analytics.record_security_event("test_event", {}, severity="high")
        
        summary = await security_analytics.get_security_summary()
        
        assert summary["total_events"] == 2
        assert summary["events_by_severity"]["low"] == 1
        assert summary["events_by_severity"]["high"] == 1
        assert summary["events_by_type"]["test_event"] == 2

    async def test_event_cleanup(self, security_analytics: SecurityAnalytics):
        """Test cleanup of old security events."""
        collector = security_analytics.event_collector
        collector.retention_hours = 1 / 3600  # 1 second retention
        
        collector.add_event(SecurityEvent(
            timestamp=datetime.utcnow() - timedelta(seconds=5),
            event_type="old_event", session_id="s1", details={}, severity="low",
            workspace_id=None, user_id=None
        ))
        
        collector.add_event(SecurityEvent(
            timestamp=datetime.utcnow(),
            event_type="new_event", session_id="s2", details={}, severity="low",
            workspace_id=None, user_id=None
        ))
        
        await security_analytics.cleanup_old_events()
        
        events = collector.get_events()
        assert len(events) == 1
        assert events[0].event_type == "new_event"
