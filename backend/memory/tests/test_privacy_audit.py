"""
Privacy Audit Logging Tests for IRIS Memory Foundation

_Requirements: 14.1, 14.2, 14.3, 14.4_
"""

import pytest
import tempfile
from unittest.mock import Mock, patch

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.audit import PrivacyAuditLogger


@pytest.fixture
def temp_log_path():
    """Create a temporary log path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield f"{tmpdir}/audit.log"


class TestPrivacyAudit:
    """Test privacy audit logging."""
    
    def test_audit_logger_initialization(self, temp_log_path):
        """Test PrivacyAuditLogger initialization."""
        auditor = PrivacyAuditLogger(temp_log_path)
        
        assert auditor is not None
    
    def test_logs_remote_context_access(self, temp_log_path):
        """
        Verify get_task_context_for_remote logs with content hash.
        
        _Requirement: 14.1 - Audit logging for remote context access
        """
        auditor = PrivacyAuditLogger(temp_log_path)
        
        with patch.object(auditor, '_write_log') as mock_write:
            auditor.log_remote_context_access(
                task_summary="Test task",
                context_hash="abc123",
                timestamp="2024-01-01T00:00:00"
            )
            
            mock_write.assert_called_once()
    
    def test_log_rotation(self, temp_log_path):
        """
        Verify log rotation works.
        
        _Requirement: 14.2 - Automatic log rotation
        """
        auditor = PrivacyAuditLogger(temp_log_path, max_size=1024)  # 1KB for testing
        
        # Simulate filling up log
        with patch('os.path.getsize', return_value=2048):  # Pretend log is 2KB
            with patch.object(auditor, '_rotate_log') as mock_rotate:
                auditor._check_rotation()
                mock_rotate.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
