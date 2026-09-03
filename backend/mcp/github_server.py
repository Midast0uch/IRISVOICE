"""GitHub MCP server stub for IRIS backend."""


class GitHubServer:
    """Stub GitHub MCP server — provides minimal GitHub integration."""

    def __init__(self, token: str | None = None):
        self.token = token

    async def start(self):
        pass

    async def stop(self):
        pass

    def get_tools(self) -> list[dict]:
        return []

    async def call_tool(self, name: str, args: dict) -> dict:
        return {"status": "ok", "result": None}
