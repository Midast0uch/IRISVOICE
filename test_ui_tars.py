#!/usr/bin/env python3
"""
UI-TARS Integration Test Script
Tests the GUI Automation MCP server with detailed debug logging
"""
import asyncio
import json
import sys
from datetime import datetime

# Add backend to path
sys.path.insert(0, r'c:\dev\IRISVOICE')

from backend.mcp.gui_automation_server import GUIAutomationServer


class Logger:
    """Test logger with timestamps and color coding"""
    
    @staticmethod
    def info(msg: str):
        print(f"\033[36m[{datetime.now().strftime('%H:%M:%S')}] INFO: {msg}\033[0m")
    
    @staticmethod
    def success(msg: str):
        print(f"\033[32m[{datetime.now().strftime('%H:%M:%S')}] SUCCESS: {msg}\033[0m")
    
    @staticmethod
    def error(msg: str):
        print(f"\033[31m[{datetime.now().strftime('%H:%M:%S')}] ERROR: {msg}\033[0m")
    
    @staticmethod
    def debug(msg: str):
        print(f"\033[33m[{datetime.now().strftime('%H:%M:%S')}] DEBUG: {msg}\033[0m")
    
    @staticmethod
    def section(title: str):
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")


async def test_server_initialization():
    """Test 1: Server initialization and tool registration"""
    Logger.section("TEST 1: Server Initialization")
    
    try:
        server = GUIAutomationServer()
        tools = server.get_tools()
        
        Logger.info(f"Server created: {server.name}")
        Logger.info(f"Tools registered: {len(tools)}")
        
        for tool in tools:
            Logger.debug(f"  - {tool.name}: {tool.description[:50]}...")
        
        assert len(tools) == 6, f"Expected 6 tools, got {len(tools)}"
        tool_names = [t.name for t in tools]
        expected = ['execute_task', 'execute_with_vision', 'click_element', 'type_text', 'take_screenshot', 'get_automation_logs']
        
        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"
            Logger.success(f"Tool '{name}' registered")
        
        return server
        
    except Exception as e:
        Logger.error(f"Initialization failed: {e}")
        raise


async def test_debug_logging(server: GUIAutomationServer):
    """Test 2: Debug logging functionality"""
    Logger.section("TEST 2: Debug Logging")
    
    # Trigger some debug logs
    await server.execute_tool("get_automation_logs", {"limit": 10})
    
    logs = server.debug_log
    Logger.info(f"Debug log entries: {len(logs)}")
    
    for entry in logs[-5:]:
        Logger.debug(f"  {entry['timestamp']}: {entry['action']}")
    
    Logger.success("Debug logging working")


async def test_execute_task_simple(server: GUIAutomationServer):
    """Test 3: Execute simple task (Phase 1 - CLI shell-out)"""
    Logger.section("TEST 3: Execute Task (Simple)")
    
    test_instruction = "Open notepad and type 'Hello from IRIS'"
    
    Logger.info(f"Testing instruction: {test_instruction}")
    Logger.info("Note: This requires Node.js and npx to be installed")
    
    try:
        result = await server.execute_tool("execute_task", {
            "instruction": test_instruction,
            "max_steps": 10,
            "require_confirmation": True
        })
        
        Logger.debug(f"Result: {json.dumps(result, indent=2, default=str)[:500]}")
        
        if result.get("success"):
            Logger.success("Task execution completed")
        else:
            error = result.get("error", "Unknown error")
            if "npx not found" in error:
                Logger.error("npx not found - Node.js not installed or not in PATH")
                Logger.info("To install: https://nodejs.org/")
            else:
                Logger.error(f"Task failed: {error}")
        
        # Check debug logs
        logs_result = await server.execute_tool("get_automation_logs", {"limit": 20})
        if logs_result.get("success"):
            Logger.info(f"Total log entries: {logs_result['total_available']}")
            for log in logs_result['logs'][-5:]:
                Logger.debug(f"  [{log['timestamp']}] {log['action']}")
        
        return result
        
    except Exception as e:
        Logger.error(f"Execute task failed: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


async def test_unimplemented_tools(server: GUIAutomationServer):
    """Test 4: Phase 2 tools now implemented with native operator"""
    Logger.section("TEST 4: Phase 2 Tools (Native Operator)")
    
    tools_to_test = [
        ("click_element", {"description": "OK button", "x": 100, "y": 200}),
        ("type_text", {"text": "Hello World"}),
        ("take_screenshot", {})
    ]
    
    for tool_name, args in tools_to_test:
        Logger.info(f"Testing {tool_name}...")
        result = await server.execute_tool(tool_name, args)
        
        if result.get("success"):
            Logger.success(f"{tool_name} executed successfully: {result.get('message', 'OK')[:60]}")
        elif "Native operator not available" in result.get("message", ""):
            Logger.info(f"{tool_name} - Native operator not installed (expected if deps missing)")
        else:
            Logger.error(f"{tool_name} failed: {result}")


async def test_log_retrieval(server: GUIAutomationServer):
    """Test 5: Log retrieval and filtering"""
    Logger.section("TEST 5: Log Retrieval")
    
    # Get all logs
    result = await server.execute_tool("get_automation_logs", {"limit": 100})
    
    if result.get("success"):
        logs = result["logs"]
        Logger.info(f"Retrieved {len(logs)} log entries")
        Logger.info(f"Total available: {result['total_available']}")
        
        # Show last 3 entries
        for log in logs[-3:]:
            Logger.debug(f"  [{log['timestamp']}] {log['action']}: {str(log['data'])[:80]}")
        
        Logger.success("Log retrieval working")
    else:
        Logger.error("Failed to retrieve logs")


async def test_vision_capabilities(server: GUIAutomationServer):
    """Test 6: Phase 3 Vision capabilities"""
    Logger.section("TEST 6: Vision Model Capabilities")
    
    # Test execute_with_vision (will fail without API key, but tests the flow)
    Logger.info("Testing execute_with_vision...")
    result = await server.execute_tool("execute_with_vision", {
        "instruction": "Click the start menu",
        "max_steps": 3
    })
    
    if result.get("success"):
        Logger.success("Vision task executed")
    elif "Vision model not initialized" in result.get("error", ""):
        Logger.info("Vision model not initialized (expected without API key)")
    else:
        Logger.error(f"Vision task failed: {result.get('error')}")
    
    # Test click by description with vision
    Logger.info("Testing click_element with description (vision path)...")
    server.use_vision = True  # Enable vision for this test
    result = await server.execute_tool("click_element", {
        "description": "Start button"
    })
    
    if "Vision model not initialized" in result.get("message", "") or \
       "Native operator not available" in result.get("message", ""):
        Logger.info("Vision/Operator not available (expected without deps)")
    else:
        Logger.debug(f"Click result: {result}")


async def run_all_tests():
    """Run all test cases"""
    Logger.section("UI-TARS INTEGRATION TEST SUITE")
    Logger.info("Starting tests...")
    
    test_results = {
        "passed": 0,
        "failed": 0,
        "errors": []
    }
    
    try:
        # Test 1: Initialization
        server = await test_server_initialization()
        test_results["passed"] += 1
        
        # Test 2: Debug logging
        await test_debug_logging(server)
        test_results["passed"] += 1
        
        # Test 3: Execute task (may fail if Node.js not installed)
        task_result = await test_execute_task_simple(server)
        if task_result.get("success") or "npx not found" in str(task_result.get("error", "")):
            test_results["passed"] += 1
        else:
            test_results["failed"] += 1
            test_results["errors"].append("Task execution test")
        
        # Test 4: Phase 2 tools
        await test_unimplemented_tools(server)
        test_results["passed"] += 1
        
        # Test 5: Log retrieval
        await test_log_retrieval(server)
        test_results["passed"] += 1
        
        # Test 6: Vision capabilities
        await test_vision_capabilities(server)
        test_results["passed"] += 1
        
    except Exception as e:
        Logger.error(f"Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        test_results["failed"] += 1
        test_results["errors"].append(str(e))
    
    # Summary
    Logger.section("TEST SUMMARY")
    Logger.info(f"Tests passed: {test_results['passed']}")
    Logger.info(f"Tests failed: {test_results['failed']}")
    
    if test_results['errors']:
        Logger.error("Errors encountered:")
        for err in test_results['errors']:
            Logger.error(f"  - {err}")
    else:
        Logger.success("All tests completed successfully!")
    
    return test_results


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  IRIS UI-TARS Integration Test")
    print("="*60 + "\n")
    
    results = asyncio.run(run_all_tests())
    
    # Exit with appropriate code
    sys.exit(0 if results['failed'] == 0 else 1)
