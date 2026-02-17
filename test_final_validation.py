"""
Final validation test for IRISVOICE system.
This script performs comprehensive integration testing of all system components.
"""

import asyncio
import json
import tempfile
import time
import shutil
from pathlib import Path
from datetime import datetime, timezone

# Import all system components
from backend.security.mcp_security import MCPSecurityManager, SecurityLevel
from backend.security.audit_logger import SecurityAuditLogger
from backend.sessions.session_manager import SessionManager, SessionType
from backend.state_manager import StateManager
from backend.gateway.iris_gateway import IRISGateway, GatewayMessage, MessageType
from backend.vision.action_allowlist import ActionAllowlist
from backend.vision.sandbox_executor import SandboxedExecutor
from backend.vision.action_allowlist import UIAction, ActionType
from backend.config.workspace_manager import WorkspaceManager
from backend.config.config_loader import ConfigurationLoader
from backend.monitoring.structured_logger import StructuredLogger
from backend.monitoring.security_analytics import SecurityEvent
from backend.debug.session_replay import SessionReplay
from backend.debug.state_inspector import StateInspector
from backend.debug.performance_metrics import PerformanceMonitor


class FinalValidationTest:
    """Comprehensive integration test for the entire IRISVOICE system."""
    
    def __init__(self):
        self.test_results = []
        self.start_time = datetime.now(timezone.utc)
        
    async def run_all_tests(self):
        """Run all validation tests."""
        print("🚀 Starting IRISVOICE Final Validation Test")
        print("=" * 60)
        
        # Test security layer
        await self.test_security_layer()
        
        # Test session management
        await self.test_session_management()
        
        # Test gateway system
        await self.test_gateway_system()
        
        # Test vision security
        await self.test_vision_security()
        
        # Test configuration system
        await self.test_configuration_system()
        
        # Test monitoring system
        await self.test_monitoring_system()
        
        # Test debug tools
        await self.test_debug_tools()
        
        # Test end-to-end integration
        await self.test_end_to_end_integration()
        
        # Generate final report
        self.generate_final_report()
        
    async def test_security_layer(self):
        """Test the security layer comprehensively."""
        print("\n🔐 Testing Security Layer...")
        
        # Initialize security components
        security_manager = MCPSecurityManager()
        
        # Test 1: Tool validation
        try:
            # Valid command
            result = await security_manager.validate_tool_operation("test_tool", "execute", {})
            assert result.allowed, f"Valid command should pass validation: {result.reason}"
            assert result.security_level == SecurityLevel.SAFE, "Safe command should have SAFE level"
            
            # Dangerous command
            result = await security_manager.validate_tool_operation("system", "exec", {"command": "rm -rf /"})
            print(f"Dangerous command validation result: {result}")
            assert not result.allowed, f"Dangerous command should be blocked: {result.reason}"
            assert result.security_level == SecurityLevel.DANGEROUS, "Dangerous command should be DANGEROUS, but was {result.security_level}"
            
            print("✅ Tool validation test passed")
            self.test_results.append({"component": "Security", "test": "Tool Validation", "status": "PASS"})
            
        except Exception as e:
            print(f"❌ Tool validation test failed: {e}")
            self.test_results.append({"component": "Security", "test": "Tool Validation", "status": "FAIL", "error": str(e)})
        
    async def test_session_management(self):
        """Test session management system."""
        print("\n📊 Testing Session Management...")
        
        session_manager = SessionManager()
        
        try:
            # Test 1: Session creation
            session_id = await session_manager.create_session()
            session = session_manager.get_session(session_id)
            
            assert session is not None, "Session should be created"
            
            # Test 2: State management via StateManager
            state_manager = StateManager(session_manager)
            await state_manager.update_field(session_id, "test_subnode", "test_field", "test_value")
            state = await state_manager.get_state(session_id)
            
            assert state is not None, "State should be retrievable"
            
            # Test 4: Session cleanup
            await session_manager.remove_session(session_id)
            removed_session = session_manager.get_session(session_id)
            assert removed_session is None, "Session should be removed"
            
            print("✅ Session management test passed")
            self.test_results.append({"component": "Session Management", "test": "Full Lifecycle", "status": "PASS"})
            
        except Exception as e:
            print(f"❌ Session management test failed: {e}")
            self.test_results.append({"component": "Session Management", "test": "Full Lifecycle", "status": "FAIL", "error": str(e)})
        
        await session_manager.shutdown()
        
    async def test_gateway_system(self):
        """Test gateway and routing system."""
        print("\n🚪 Testing Gateway System...")
        
        session_manager = SessionManager()
        gateway = IRISGateway(session_manager)
        
        try:
            # Create a session first
            session_id = await session_manager.create_session()
            
            # Test 1: Message routing
            message = GatewayMessage(
                id="test_message_1",
                type=MessageType.STATE_UPDATE,
                session_id=session_id,
                client_id="test_client",
                payload={
                    "tool": "file_manager",
                    "command": "read",
                    "parameters": {"path": "/test/file.txt"}
                },
                timestamp=datetime.now()
            )
            
            result = await gateway.process_message(message)
            assert result is not None, "Gateway should process message"
            
            # Test 2: Security filtering
            dangerous_message = GatewayMessage(
                id="test_message_2",
                type=MessageType.SYSTEM_COMMAND,
                session_id=session_id,
                client_id="test_client",
                payload={
                    "tool": "system",
                    "command": "exec",
                    "parameters": {"command": "rm -rf /"}
                },
                timestamp=datetime.now()
            )
            
            result = await gateway.process_message(dangerous_message)
            print(f"Dangerous message result: {result}")
            print(f"Security level: {result.security_level}")
            assert result.security_level == "BLOCKED", f"Dangerous message should be blocked, got: {result.security_level}"
            
            print("✅ Gateway system test passed")
            self.test_results.append({"component": "Gateway", "test": "Message Processing", "status": "PASS"})
            
        except Exception as e:
            print(f"❌ Gateway system test failed: {e}")
            self.test_results.append({"component": "Gateway", "test": "Message Processing", "status": "FAIL", "error": str(e)})
        
        await session_manager.shutdown()
        
    async def test_vision_security(self):
        """Test vision security and automation system."""
        print("\n👁️ Testing Vision Security...")
        
        try:
            # Test 1: Action allowlist
            action_allowlist = ActionAllowlist()
            
            # Valid action
            valid_action = UIAction(
                action_type=ActionType.CLICK,
                target_role="button",
                target_name="Save"
            )
            
            result = action_allowlist.validate_action(valid_action)
            assert result["allowed"], f"Valid action should be allowed: {result}"
            

            
            print("✅ Vision security test passed")
            self.test_results.append({"component": "Vision Security", "test": "Action Validation", "status": "PASS"})
            
        except Exception as e:
            print(f"❌ Vision security test failed: {e}")
            self.test_results.append({"component": "Vision Security", "test": "Action Validation", "status": "FAIL", "error": str(e)})
        
    async def test_configuration_system(self):
        """Test configuration and workspace management."""
        print("\n⚙️ Testing Configuration System...")
        
        try:
            # Test 1: Workspace creation
            workspace_manager = WorkspaceManager(Path("./test_workspaces"))
            workspace = await workspace_manager.create_workspace(name="Test Workspace", session_id="test_session", user_id="test_user")
            
            assert workspace is not None, "Workspace should be created"
            assert workspace.name == "Test Workspace", "Workspace name should match"
            
            print("✅ Configuration system test passed")
            self.test_results.append({"component": "Configuration", "test": "Workspace Management", "status": "PASS"})
            
        except Exception as e:
            print(f"❌ Configuration system test failed: {e}")
            self.test_results.append({"component": "Configuration", "test": "Workspace Management", "status": "FAIL", "error": str(e)})
        finally:
            if Path("./test_workspaces").exists():
                shutil.rmtree(Path("./test_workspaces"))

    async def test_monitoring_system(self):
        """Test monitoring and logging system."""
        print("\n📈 Testing Monitoring System...")
        
        try:
            # Test 1: Structured logging
            logger = StructuredLogger("test_component")
            
            logger.info("Test operation completed", extra={
                "operation": "test",
                "duration_ms": 150,
                "success": True
            })
            
            # Test 2: Security event logging
            logger.info("Security event: test_security_check", extra={
                "threat_level": "low",
                "action_taken": "allowed"
            })
            
            print("✅ Monitoring system test passed")
            self.test_results.append({"component": "Monitoring", "test": "Structured Logging", "status": "PASS"})
            
        except Exception as e:
            print(f"❌ Monitoring system test failed: {e}")
            self.test_results.append({"component": "Monitoring", "test": "Structured Logging", "status": "FAIL", "error": str(e)})
        
    async def test_debug_tools(self):
        """Test debug and diagnostic tools."""
        print("\n🔧 Testing Debug Tools...")
        
        try:
            # Test 1: Session replay
            session_replay = SessionReplay("test_session")
            session_replay.start_recording()
            
            # Record some events
            session_replay.add_event("ui_action", {"action": "click", "target": "button"})
            session_replay.add_event("state_change", {"field": "name", "value": "test"})
            
            session_replay.stop_recording()
            
            # Save and load recording
            recording_file = session_replay.save_recording()
            assert recording_file is not None, "Recording should be saved"
            
            loaded_recording = SessionReplay.load_recording(recording_file)
            assert loaded_recording is not None, "Recording should be loadable"
            assert len(loaded_recording["events"]) >= 2, "Recording should have events"
            
            print("✅ Debug tools test passed")
            self.test_results.append({"component": "Debug Tools", "test": "Recording & Monitoring", "status": "PASS"})
            
        except Exception as e:
            print(f"❌ Debug tools test failed: {e}")
            self.test_results.append({"component": "Debug Tools", "test": "Recording & Monitoring", "status": "FAIL", "error": str(e)})
        
    async def test_end_to_end_integration(self):
        """Test complete end-to-end integration scenario."""
        print("\n🔄 Testing End-to-End Integration...")
        
        try:
            # Initialize all components
            session_manager = SessionManager()
            gateway = IRISGateway(session_manager)
            
            # Step 1: Create session
            session_id = await session_manager.create_session()
            
            # Step 2: Process secure message through gateway
            secure_message = GatewayMessage(
                id="test_message_1",
                type=MessageType.SYSTEM_COMMAND,
                session_id=session_id,
                client_id="test_client",
                payload={
                    "tool": "file_manager",
                    "command": "read",
                    "parameters": {"path": "/safe/config.json"}
                },
                timestamp=datetime.now()
            )
            
            gateway_result = await gateway.process_message(secure_message)
            assert gateway_result.security_level == "SAFE", "Secure message should be processed"
            
            # Step 3: Update session state
            state_manager = StateManager(session_manager)
            await state_manager.update_field(session_id, "integration_test", "completed", True)
            state = await state_manager.get_state(session_id)
            assert state is not None, "State should be available"
            
            # Step 6: Clean up
            await session_manager.remove_session(session_id)
            await session_manager.shutdown()
            
            print("✅ End-to-end integration test passed")
            self.test_results.append({"component": "Integration", "test": "End-to-End Flow", "status": "PASS"})
            
        except Exception as e:
            print(f"❌ End-to-end integration test failed: {e}")
            self.test_results.append({"component": "Integration", "test": "End-to-End Flow", "status": "FAIL", "error": str(e)})
        
    def generate_final_report(self):
        """Generate comprehensive final validation report."""
        print("\n" + "=" * 60)
        print("📊 FINAL VALIDATION REPORT")
        print("=" * 60)
        
        end_time = datetime.now(timezone.utc)
        duration = (end_time - self.start_time).total_seconds()
        
        # Calculate statistics
        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results if r["status"] == "PASS")
        failed_tests = sum(1 for r in self.test_results if r["status"] == "FAIL")
        
        # Group by component
        components = {}
        for result in self.test_results:
            component = result["component"]
            if component not in components:
                components[component] = {"passed": 0, "failed": 0}
            
            if result["status"] == "PASS":
                components[component]["passed"] += 1
            else:
                components[component]["failed"] += 1
        
        print(f"\n📈 Test Statistics:")
        print(f"   Total Tests: {total_tests}")
        print(f"   Passed: {passed_tests} ({passed_tests/total_tests*100:.1f}%)")
        print(f"   Failed: {failed_tests} ({failed_tests/total_tests*100:.1f}%)")
        print(f"   Duration: {duration:.2f} seconds")
        
        print(f"\n🔍 Component Breakdown:")
        for component, stats in components.items():
            total = stats["passed"] + stats["failed"]
            pass_rate = stats["passed"] / total * 100 if total > 0 else 0
            status_icon = "✅" if pass_rate == 100 else "❌"
            print(f"   {status_icon} {component}: {stats['passed']}/{total} passed ({pass_rate:.1f}%)")
            
        if failed_tests > 0:
            print("\n❌ Failed Tests:")
            for result in self.test_results:
                if result["status"] == "FAIL":
                    print(f"   - {result['component']}: {result['test']}")
                    print(f"     Error: {result['error']}")
        
        overall_status = "✅ ALL TESTS PASSED" if failed_tests == 0 else "❌ NEEDS ATTENTION"
        print(f"\n🏆 Overall System Status: {overall_status}")
        
        if failed_tests > 0:
            print(f"\n⚠️  The system has {failed_tests} failing tests that need attention before production deployment.")
            
        # Save detailed report to JSON file
        report_data = {
            "summary": {
                "total_tests": total_tests,
                "passed": passed_tests,
                "failed": failed_tests,
                "duration_seconds": duration
            },
            "results": self.test_results
        }
        
        report_file = "validation_report.json"
        with open(report_file, "w") as f:
            json.dump(report_data, f, indent=4)
            
        print(f"\n📄 Detailed report saved to: {report_file}")

if __name__ == "__main__":
    validation_test = FinalValidationTest()
    asyncio.run(validation_test.run_all_tests())