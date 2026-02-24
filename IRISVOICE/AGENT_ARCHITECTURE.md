# IRIS Agent Architecture

## Overview

This document describes the dual-LLM agent architecture integrating `lfm2-8b` (brain/reasoning) and `lfm2.5-1.2b-instruct` (executor) models.

## Communication Protocol

### Frontend → Backend Messages

| Message Type | Payload | Description |
|--------------|---------|-------------|
| `set_category` | `{ category: string }` | Select main category |
| `set_subnode` | `{ subnode: string }` | Select subnode |
| `go_back` | `{}` | Navigate back |
| `collapse_to_idle` | `{}` | Return to idle state |
| `update_field` | `{ subnode_id, field_id, value }` | Update field value |
| `update_theme` | `{ glow_color, font_color, state_colors }` | Update theme |
| `request_state` | `{}` | Request full state |
| `ping` | `{}` | Health check |
| `expand_to_main` | `{}` | Expand to main view |
| `clear_chat` | `{}` | Clear agent conversation |
| `reload_skills` | `{}` | Reload skills config |
| `text_message` | `{ text }` | Chat message |
| `voice_command` | `{ audio }` | Voice input |
| `agent_status` | `{}` | Get agent kernel status |
| `agent_tools` | `{}` | Get available tools |
| `execute_tool` | `{ tool_name, parameters }` | Execute tool |

### Backend → Frontend Responses

| Response Type | Payload | Description |
|---------------|---------|-------------|
| `category_changed` | `{ category }` | Category updated |
| `subnode_changed` | `{ subnode_id }` | Subnode updated |
| `field_updated` | `{ subnode_id, field_id, value }` | Field updated |
| `theme_updated` | `{ glow, font }` | Theme applied |
| `full_state` | `{ state }` | Complete state |
| `pong` | `{}` | Ping response |
| `category_expanded` | `{}` | Main view expanded |
| `chat_cleared` | `{}` | Conversation cleared |
| `skills_reloaded` | `{ skills }` | Skills loaded |
| `skills_error` | `{ error }` | Skills error |
| `mini_node_confirmed` | `{ subnode_id }` | Mini node confirmed |
| `agent_status` | `{ models, tools, health }` | Agent status |
| `agent_tools` | `{ tools }` | Tool list |
| `tool_result` | `{ result, error }` | Tool execution |
| `text_response` | `{ text, sender }` | Chat response |
| `voice_command_started` | `{}` | Voice processing started |
| `voice_command_ended` | `{}` | Voice processing ended |
| `voice_command_result` | `{ result }` | Voice result |
| `native_audio_response` | `{ audio }` | Audio response |

## Tool Categories

| Category | Description |
|----------|-------------|
| `vision` | Screen capture, OCR, object detection |
| `web` | Browser automation, web scraping |
| `file` | File operations, read/write |
| `system` | System commands, process control |
| `app` | Application control |

## Agent Components

- **AgentKernel**: Central orchestrator
- **InterModelCommunicator**: JSON-based communication
- **ToolBridge**: Connects to MiniCPM, MCP servers
- **SkillsLoader**: Manages user-configurable skills

## Error Codes

- `SUCCESS`: Operation completed
- `FAILURE`: Operation failed
- `PARTIAL`: Partial success
- `TIMEOUT`: Operation timeout
- `INVALID_REQUEST`: Malformed request
