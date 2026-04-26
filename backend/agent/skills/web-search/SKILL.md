---
name: web-search
description: This skill should be used when IRIS needs to look up current information, research a topic, find documentation, or check URLs. Use it for research tasks before implementing, for fact-checking, or when the user asks about recent events.
---

# Web Search

IRIS can search the web and open URLs through the `browser` MCP server.

## Available Tools

| Tool | Description | Required params |
|------|-------------|-----------------|
| `search` | Search Google and open results in browser | `query` |
| `open_url` | Open a specific URL in the default browser | `url` |

## Important Limitation

The `search` tool opens Google in the user's browser — it does NOT return text results to the agent. Use it when:
- The user wants to see search results themselves
- You need to send the user to a specific page
- The task is to launch a search the user will complete

## Research Workflow

For tasks requiring research before implementation:

1. **Identify what you need to know** — specific facts, API docs, code examples
2. **Use `search` to open a query** — the user sees results in their browser
3. **Ask the user to share relevant content** — "I have opened a search for [X]. Can you paste the relevant documentation or answer here?"
4. **Proceed with the information provided**

```python
# Open a search
result = tool_bridge.execute_tool("search", {
    "query": "Python asyncio timeout best practices 2024"
})

# Open a specific URL
result = tool_bridge.execute_tool("open_url", {
    "url": "https://docs.python.org/3/library/asyncio-task.html"
})
```

## When to Use

- User asks: "Look up X" / "Search for Y" / "Find documentation on Z"
- You need current information before implementing something
- You need to send the user to a webpage for credential setup

## When NOT to Use

- For reading local files: use `file-operations` skill instead
- For GitHub: use GitHub MCP if available
- For static reference knowledge you already know: respond directly

## Future Enhancement

A future version will return search result text directly to the agent (using a headless browser or search API). Until then, this skill works best in collaboration with the user.
