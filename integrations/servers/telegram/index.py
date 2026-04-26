#!/usr/bin/env python3
"""
Telegram MCP Server

An MCP server that provides Telegram access via MTProto protocol using Telethon.
Communicates over stdio using the Model Context Protocol.

Environment variables:
- IRIS_CREDENTIAL: JSON string with MTProto session string
- IRIS_INTEGRATION_ID: The integration ID (should be "telegram")
- IRIS_MCP_VERSION: MCP protocol version
"""

import asyncio
import json
import os
import sys
from io import StringIO
from typing import Any, Dict, List, Optional

from telethon import TelegramClient
from telethon.tl.functions.messages import GetDialogsRequest, SearchRequest
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.tl.types import InputMessagesFilterEmpty, PeerUser, PeerChat, PeerChannel

# MCP Protocol constants
MCP_VERSION = "2024-11-05"
SERVER_NAME = "iris-mcp-telegram"
SERVER_VERSION = "1.0.0"

# Parse credentials from environment
credential_env = os.environ.get("IRIS_CREDENTIAL")
if not credential_env:
    print("Error: IRIS_CREDENTIAL environment variable not set", file=sys.stderr)
    sys.exit(1)

try:
    credential = json.loads(credential_env)
except json.JSONDecodeError as e:
    print(f"Error: Failed to parse IRIS_CREDENTIAL: {e}", file=sys.stderr)
    sys.exit(1)

# Initialize Telegram client with session string
session_string = credential.get("mtproto_session")
api_id = credential.get("api_id")
api_hash = credential.get("api_hash")

if not session_string:
    print("Error: mtproto_session not found in credentials", file=sys.stderr)
    sys.exit(1)

# Create client from session string
client = TelegramClient(
    StringIO(session_string),
    api_id=api_id,
    api_hash=api_hash
)

# MCP Server State
initialized = False

# Tool definitions
TOOLS = [
    {
        "name": "telegram_list_chats",
        "description": "List recent chats (conversations)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "number",
                    "description": "Maximum number of chats to return (default: 20)",
                    "default": 20,
                },
            },
        },
    },
    {
        "name": "telegram_read_chat",
        "description": "Read messages from a specific chat",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "Chat ID (channel username, group ID, or user ID)",
                },
                "limit": {
                    "type": "number",
                    "description": "Maximum number of messages (default: 20)",
                    "default": 20,
                },
            },
            "required": ["chat_id"],
        },
    },
    {
        "name": "telegram_send_message",
        "description": "Send a message to a chat",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "Chat ID to send message to",
                },
                "message": {
                    "type": "string",
                    "description": "Message text",
                },
            },
            "required": ["chat_id", "message"],
        },
    },
    {
        "name": "telegram_reply",
        "description": "Reply to a specific message",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "Chat ID",
                },
                "message_id": {
                    "type": "number",
                    "description": "Message ID to reply to",
                },
                "message": {
                    "type": "string",
                    "description": "Reply text",
                },
            },
            "required": ["chat_id", "message_id", "message"],
        },
    },
    {
        "name": "telegram_search_messages",
        "description": "Search for messages in a chat",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "Chat ID to search in (omit for global search)",
                },
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "limit": {
                    "type": "number",
                    "description": "Maximum results (default: 20)",
                    "default": 20,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "telegram_get_contacts",
        "description": "Get list of contacts",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "telegram_send_file",
        "description": "Send a file to a chat",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "Chat ID to send file to",
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to file",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional caption",
                },
            },
            "required": ["chat_id", "file_path"],
        },
    },
    {
        "name": "telegram_create_group",
        "description": "Create a new group",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Group title",
                },
                "users": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of usernames or user IDs to add",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "telegram_get_chat_members",
        "description": "Get members of a group or channel",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "Chat ID (group or channel)",
                },
                "limit": {
                    "type": "number",
                    "description": "Maximum members to return (default: 100)",
                    "default": 100,
                },
            },
            "required": ["chat_id"],
        },
    },
]


def send_message(message: Dict[str, Any]):
    """Send an MCP message to stdout."""
    json_str = json.dumps(message)
    print(json_str, flush=True)


async def get_entity(chat_id: str):
    """Get entity from chat_id string."""
    try:
        # Try as integer ID first
        return await client.get_entity(int(chat_id))
    except ValueError:
        # Try as username or string
        return await client.get_entity(chat_id)


# Tool implementations
async def handle_tool_call(tool_name: str, args: Dict[str, Any]):
    """Handle MCP tool calls."""
    
    if tool_name == "telegram_list_chats":
        limit = args.get("limit", 20)
        
        dialogs = await client(GetDialogsRequest(
            offset_date=None,
            offset_id=0,
            offset_peer=PeerUser(user_id=0),
            limit=limit,
            hash=0
        ))
        
        chats = []
        for dialog in dialogs.dialogs:
            entity = await client.get_entity(dialog.peer)
            chat_info = {
                "id": str(entity.id),
                "title": getattr(entity, "title", None) or getattr(entity, "first_name", "") + " " + getattr(entity, "last_name", ""),
                "type": "channel" if isinstance(dialog.peer, PeerChannel) else "group" if isinstance(dialog.peer, PeerChat) else "user",
            }
            if hasattr(entity, "username"):
                chat_info["username"] = entity.username
            chats.append(chat_info)
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"chats": chats}, indent=2),
                }
            ]
        }
    
    elif tool_name == "telegram_read_chat":
        chat_id = args["chat_id"]
        limit = args.get("limit", 20)
        
        entity = await get_entity(chat_id)
        messages = []
        
        async for message in client.iter_messages(entity, limit=limit):
            msg_data = {
                "id": message.id,
                "date": message.date.isoformat() if message.date else None,
                "text": message.text or "",
                "sender_id": str(message.sender_id) if message.sender_id else None,
            }
            if message.sender:
                msg_data["sender_name"] = getattr(message.sender, "first_name", "") + " " + getattr(message.sender, "last_name", "")
            messages.append(msg_data)
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"messages": messages}, indent=2),
                }
            ]
        }
    
    elif tool_name == "telegram_send_message":
        chat_id = args["chat_id"]
        text = args["message"]
        
        entity = await get_entity(chat_id)
        message = await client.send_message(entity, text)
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "success": True,
                        "message_id": message.id,
                        "date": message.date.isoformat() if message.date else None,
                    }, indent=2),
                }
            ]
        }
    
    elif tool_name == "telegram_reply":
        chat_id = args["chat_id"]
        message_id = args["message_id"]
        text = args["message"]
        
        entity = await get_entity(chat_id)
        message = await client.send_message(entity, text, reply_to=message_id)
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "success": True,
                        "message_id": message.id,
                        "date": message.date.isoformat() if message.date else None,
                    }, indent=2),
                }
            ]
        }
    
    elif tool_name == "telegram_search_messages":
        query = args["query"]
        chat_id = args.get("chat_id")
        limit = args.get("limit", 20)
        
        if chat_id:
            entity = await get_entity(chat_id)
            result = await client(SearchRequest(
                peer=entity,
                q=query,
                filter=InputMessagesFilterEmpty(),
                min_date=None,
                max_date=None,
                offset_id=0,
                add_offset=0,
                limit=limit,
                max_id=0,
                min_id=0,
                hash=0
            ))
            messages = result.messages
        else:
            # Global search - iterate all dialogs
            messages = []
            async for message in client.iter_messages(None, search=query, limit=limit):
                messages.append(message)
        
        results = []
        for msg in messages:
            if msg:
                results.append({
                    "id": msg.id,
                    "chat_id": str(msg.chat_id) if msg.chat_id else None,
                    "date": msg.date.isoformat() if msg.date else None,
                    "text": msg.text or "",
                })
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"messages": results}, indent=2),
                }
            ]
        }
    
    elif tool_name == "telegram_get_contacts":
        contacts = await client(GetContactsRequest(hash=0))
        
        contact_list = []
        for user in contacts.users:
            contact_list.append({
                "id": str(user.id),
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "username": user.username,
                "phone": user.phone,
            })
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"contacts": contact_list}, indent=2),
                }
            ]
        }
    
    elif tool_name == "telegram_send_file":
        chat_id = args["chat_id"]
        file_path = args["file_path"]
        caption = args.get("caption", "")
        
        entity = await get_entity(chat_id)
        message = await client.send_file(entity, file_path, caption=caption)
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "success": True,
                        "message_id": message.id,
                        "date": message.date.isoformat() if message.date else None,
                    }, indent=2),
                }
            ]
        }
    
    elif tool_name == "telegram_create_group":
        title = args["title"]
        users = args.get("users", [])
        
        # Resolve users
        resolved_users = []
        for user in users:
            try:
                entity = await client.get_entity(user)
                resolved_users.append(entity)
            except Exception:
                pass
        
        result = await client(CreateChannelRequest(
            title=title,
            about="",
            megagroup=True  # Supergroup
        )) if not resolved_users else await client(CreateChatRequest(
            title=title,
            users=resolved_users
        ))
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "success": True,
                        "chat_id": str(result.chats[0].id) if result.chats else None,
                        "title": result.chats[0].title if result.chats else None,
                    }, indent=2),
                }
            ]
        }
    
    elif tool_name == "telegram_get_chat_members":
        chat_id = args["chat_id"]
        limit = args.get("limit", 100)
        
        entity = await get_entity(chat_id)
        
        members = []
        async for participant in client.iter_participants(entity, limit=limit):
            members.append({
                "id": str(participant.id),
                "first_name": participant.first_name or "",
                "last_name": participant.last_name or "",
                "username": participant.username,
                "is_bot": participant.bot,
            })
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"members": members}, indent=2),
                }
            ]
        }
    
    else:
        raise ValueError(f"Unknown tool: {tool_name}")


# MCP Protocol handlers
async def handle_initialize(params: Dict[str, Any]):
    """Handle initialize request."""
    global initialized
    initialized = True
    return {
        "protocolVersion": MCP_VERSION,
        "capabilities": {
            "tools": {},
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        },
    }


async def handle_tools_list(params: Dict[str, Any]):
    """Handle tools/list request."""
    if not initialized:
        raise RuntimeError("Server not initialized")
    return {"tools": TOOLS}


async def handle_tools_call(params: Dict[str, Any]):
    """Handle tools/call request."""
    if not initialized:
        raise RuntimeError("Server not initialized")
    
    name = params.get("name")
    arguments = params.get("arguments", {})
    
    tool = next((t for t in TOOLS if t["name"] == name), None)
    if not tool:
        raise ValueError(f"Unknown tool: {name}")
    
    return await handle_tool_call(name, arguments)


HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
}


async def process_message(message: Dict[str, Any]):
    """Process a single MCP message."""
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params", {})
    
    if not method:
        return None
    
    handler = HANDLERS.get(method)
    if not handler:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}",
            },
        }
    
    try:
        result = await handler(params)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": result,
        }
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32603,
                "message": str(e),
            },
        }


async def main():
    """Main server loop."""
    # Start Telegram client
    await client.start()
    
    # Log startup
    print(f"Telegram MCP Server v{SERVER_VERSION} started", file=sys.stderr)
    print(f"Integration ID: {os.environ.get('IRIS_INTEGRATION_ID', 'unknown')}", file=sys.stderr)
    
    # Get current user info
    me = await client.get_me()
    print(f"Connected as: {me.first_name} (@{me.username})", file=sys.stderr)
    
    # Process stdin
    buffer = ""
    while True:
        try:
            chunk = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.read, 1)
            if not chunk:
                break
            
            buffer += chunk
            
            # Process complete lines
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip()
                
                if not line:
                    continue
                
                try:
                    message = json.loads(line)
                    response = await process_message(message)
                    if response:
                        send_message(response)
                except json.JSONDecodeError as e:
                    print(f"Error parsing message: {e}", file=sys.stderr)
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
    
    # Cleanup
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
