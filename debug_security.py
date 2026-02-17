import asyncio
from backend.security.mcp_security import MCPSecurityManager

async def test_security():
    security_manager = MCPSecurityManager()
    
    # Test dangerous command
    result = await security_manager.validate_tool_operation("system", "exec", {"command": "rm -rf /"})
    print(f"Dangerous command result: allowed={result.allowed}, level={result.security_level}, reason={result.reason}")
    
    # Test valid command
    result = await security_manager.validate_tool_operation("test_tool", "execute", {})
    print(f"Valid command result: allowed={result.allowed}, level={result.security_level}, reason={result.reason}")

if __name__ == "__main__":
    asyncio.run(test_security())