---
name: file-operations
description: This skill should be used when IRIS needs to read, write, create, list, or delete files on the local filesystem. Use it for any task involving files — reading configs, writing output, organizing files, summarizing documents.
---

# File Operations

IRIS has direct access to the local filesystem through the `file_manager` MCP server. Use these tools whenever the task involves files.

## Available Tools

All tools are callable via the DER loop Explorer as `item.tool`:

| Tool | Description | Required params |
|------|-------------|-----------------|
| `read_file` | Read a file's text content | `path` |
| `write_file` | Write text to a file (creates or overwrites) | `path`, `content` |
| `list_directory` | List files in a directory | `path` |
| `create_directory` | Create a directory (including parents) | `path` |
| `delete_file` | Delete a file or directory | `path` |

## Usage in the DER Loop

The Explorer calls these via the tool bridge:

```python
# Read a file
result = tool_bridge.execute_tool("read_file", {"path": "C:/path/to/file.txt"})
content = result.get("content", "")

# Write a file
result = tool_bridge.execute_tool("write_file", {
    "path": "C:/path/to/output.txt",
    "content": "Hello, world!"
})

# List a directory
result = tool_bridge.execute_tool("list_directory", {"path": "C:/path/to/dir"})
items = result.get("items", [])
```

## Guidelines

- Always use absolute paths (e.g., `C:/Users/midas/...`)
- Check `result.get("success")` before using content
- For large files, read in chunks or summarize rather than loading everything
- When writing, confirm the user wants to overwrite if the file already exists
- Do not delete files without explicit user confirmation

## Common Patterns

**Summarize a folder of documents:**
1. `list_directory` — get all files
2. For each .txt/.md: `read_file` — read content
3. Summarize each, combine into report
4. `write_file` — save report

**Edit a config file:**
1. `read_file` — read current content
2. Apply changes in memory
3. `write_file` — write back
