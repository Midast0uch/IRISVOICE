#!/usr/bin/env node
/**
 * Discord MCP Server
 * 
 * An MCP server that provides Discord access via Discord.js.
 * Communicates over stdio using the Model Context Protocol.
 * 
 * Environment variables:
 * - IRIS_CREDENTIAL: JSON string with Discord bot token
 * - IRIS_INTEGRATION_ID: The integration ID (should be "discord")
 * - IRIS_MCP_VERSION: MCP protocol version
 */

import { Client, GatewayIntentBits, Partials } from 'discord.js';

// MCP Protocol constants
const MCP_VERSION = '2024-11-05';
const SERVER_NAME = 'iris-mcp-discord';
const SERVER_VERSION = '1.0.0';

// Parse credentials from environment
const credentialEnv = process.env.IRIS_CREDENTIAL;
if (!credentialEnv) {
  console.error('Error: IRIS_CREDENTIAL environment variable not set');
  process.exit(1);
}

let credential;
try {
  credential = JSON.parse(credentialEnv);
} catch (e) {
  console.error('Error: Failed to parse IRIS_CREDENTIAL:', e.message);
  process.exit(1);
}

// Initialize Discord client
const token = credential.access_token || credential.bot_token;
if (!token) {
  console.error('Error: No bot token found in credentials');
  process.exit(1);
}

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.MessageContent,
  ],
  partials: [Partials.Channel],
});

// MCP Server State
let initialized = false;
let clientReady = false;

// Tool definitions
const TOOLS = [
  {
    name: 'discord_list_servers',
    description: 'List Discord servers (guilds) the bot is a member of',
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'discord_list_channels',
    description: 'List channels in a server',
    inputSchema: {
      type: 'object',
      properties: {
        serverId: {
          type: 'string',
          description: 'Server (guild) ID',
        },
      },
      required: ['serverId'],
    },
  },
  {
    name: 'discord_read_channel',
    description: 'Read recent messages from a channel',
    inputSchema: {
      type: 'object',
      properties: {
        channelId: {
          type: 'string',
          description: 'Channel ID',
        },
        limit: {
          type: 'number',
          description: 'Number of messages to fetch (default: 20, max: 100)',
          default: 20,
        },
      },
      required: ['channelId'],
    },
  },
  {
    name: 'discord_send_message',
    description: 'Send a message to a channel',
    inputSchema: {
      type: 'object',
      properties: {
        channelId: {
          type: 'string',
          description: 'Channel ID',
        },
        message: {
          type: 'string',
          description: 'Message content',
        },
      },
      required: ['channelId', 'message'],
    },
  },
  {
    name: 'discord_reply',
    description: 'Reply to a specific message',
    inputSchema: {
      type: 'object',
      properties: {
        channelId: {
          type: 'string',
          description: 'Channel ID',
        },
        messageId: {
          type: 'string',
          description: 'Message ID to reply to',
        },
        message: {
          type: 'string',
          description: 'Reply content',
        },
      },
      required: ['channelId', 'messageId', 'message'],
    },
  },
  {
    name: 'discord_react',
    description: 'Add a reaction to a message',
    inputSchema: {
      type: 'object',
      properties: {
        channelId: {
          type: 'string',
          description: 'Channel ID',
        },
        messageId: {
          type: 'string',
          description: 'Message ID',
        },
        emoji: {
          type: 'string',
          description: 'Emoji to react with (Unicode emoji or custom emoji ID)',
        },
      },
      required: ['channelId', 'messageId', 'emoji'],
    },
  },
  {
    name: 'discord_search',
    description: 'Search for messages in a channel (fetches recent messages and filters)',
    inputSchema: {
      type: 'object',
      properties: {
        channelId: {
          type: 'string',
          description: 'Channel ID',
        },
        query: {
          type: 'string',
          description: 'Search query (searches message content)',
        },
        limit: {
          type: 'number',
          description: 'Number of recent messages to search (default: 100)',
          default: 100,
        },
      },
      required: ['channelId', 'query'],
    },
  },
  {
    name: 'discord_get_members',
    description: 'Get members of a server',
    inputSchema: {
      type: 'object',
      properties: {
        serverId: {
          type: 'string',
          description: 'Server (guild) ID',
        },
        limit: {
          type: 'number',
          description: 'Maximum members to fetch (default: 100)',
          default: 100,
        },
      },
      required: ['serverId'],
    },
  },
  {
    name: 'discord_create_thread',
    description: 'Create a thread from a message',
    inputSchema: {
      type: 'object',
      properties: {
        channelId: {
          type: 'string',
          description: 'Channel ID',
        },
        messageId: {
          type: 'string',
          description: 'Message ID to start thread from',
        },
        name: {
          type: 'string',
          description: 'Thread name',
        },
      },
      required: ['channelId', 'messageId', 'name'],
    },
  },
];

// Helper function to send MCP messages
function sendMessage(message) {
  const json = JSON.stringify(message);
  process.stdout.write(json + '\n');
}

// Wait for client to be ready
async function ensureReady() {
  if (clientReady) return;
  await new Promise((resolve) => {
    if (clientReady) resolve();
    else client.once('ready', resolve);
  });
}

// Tool implementations
async function handleToolCall(toolName, args) {
  await ensureReady();

  switch (toolName) {
    case 'discord_list_servers': {
      const guilds = client.guilds.cache.map(guild => ({
        id: guild.id,
        name: guild.name,
        memberCount: guild.memberCount,
        icon: guild.iconURL(),
      }));

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({ servers: guilds }, null, 2),
          },
        ],
      };
    }

    case 'discord_list_channels': {
      const guild = client.guilds.cache.get(args.serverId);
      if (!guild) {
        throw new Error(`Server not found: ${args.serverId}`);
      }

      await guild.channels.fetch();
      const channels = guild.channels.cache
        .filter(ch => ch.isTextBased())
        .map(ch => ({
          id: ch.id,
          name: ch.name,
          type: ch.type.toString(),
          parent: ch.parent?.name || null,
        }));

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({ channels }, null, 2),
          },
        ],
      };
    }

    case 'discord_read_channel': {
      const channel = await client.channels.fetch(args.channelId);
      if (!channel || !channel.isTextBased()) {
        throw new Error(`Channel not found or not a text channel: ${args.channelId}`);
      }

      const limit = Math.min(args.limit || 20, 100);
      const messages = await channel.messages.fetch({ limit });

      const messageList = messages.map(msg => ({
        id: msg.id,
        content: msg.content,
        author: {
          id: msg.author.id,
          username: msg.author.username,
          displayName: msg.author.displayName,
        },
        timestamp: msg.createdAt.toISOString(),
        editedTimestamp: msg.editedAt?.toISOString() || null,
        attachments: msg.attachments.map(att => ({
          id: att.id,
          name: att.name,
          url: att.url,
        })),
        embeds: msg.embeds.length,
        reactions: msg.reactions.cache.map(react => ({
          emoji: react.emoji.name || react.emoji.id,
          count: react.count,
        })),
        threadId: msg.thread?.id || null,
      }));

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({ messages: messageList }, null, 2),
          },
        ],
      };
    }

    case 'discord_send_message': {
      const channel = await client.channels.fetch(args.channelId);
      if (!channel || !channel.isTextBased()) {
        throw new Error(`Channel not found or not a text channel: ${args.channelId}`);
      }

      const message = await channel.send(args.message);

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              messageId: message.id,
              timestamp: message.createdAt.toISOString(),
            }, null, 2),
          },
        ],
      };
    }

    case 'discord_reply': {
      const channel = await client.channels.fetch(args.channelId);
      if (!channel || !channel.isTextBased()) {
        throw new Error(`Channel not found or not a text channel: ${args.channelId}`);
      }

      const message = await channel.messages.fetch(args.messageId);
      if (!message) {
        throw new Error(`Message not found: ${args.messageId}`);
      }

      const reply = await message.reply(args.message);

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              messageId: reply.id,
              timestamp: reply.createdAt.toISOString(),
            }, null, 2),
          },
        ],
      };
    }

    case 'discord_react': {
      const channel = await client.channels.fetch(args.channelId);
      if (!channel || !channel.isTextBased()) {
        throw new Error(`Channel not found or not a text channel: ${args.channelId}`);
      }

      const message = await channel.messages.fetch(args.messageId);
      if (!message) {
        throw new Error(`Message not found: ${args.messageId}`);
      }

      await message.react(args.emoji);

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              messageId: message.id,
              emoji: args.emoji,
            }, null, 2),
          },
        ],
      };
    }

    case 'discord_search': {
      const channel = await client.channels.fetch(args.channelId);
      if (!channel || !channel.isTextBased()) {
        throw new Error(`Channel not found or not a text channel: ${args.channelId}`);
      }

      const limit = Math.min(args.limit || 100, 100);
      const messages = await channel.messages.fetch({ limit });

      const query = args.query.toLowerCase();
      const results = messages
        .filter(msg => msg.content.toLowerCase().includes(query))
        .map(msg => ({
          id: msg.id,
          content: msg.content,
          author: {
            id: msg.author.id,
            username: msg.author.username,
          },
          timestamp: msg.createdAt.toISOString(),
        }));

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({ messages: results }, null, 2),
          },
        ],
      };
    }

    case 'discord_get_members': {
      const guild = client.guilds.cache.get(args.serverId);
      if (!guild) {
        throw new Error(`Server not found: ${args.serverId}`);
      }

      await guild.members.fetch();
      const limit = args.limit || 100;
      const members = guild.members.cache
        .first(limit)
        .map(member => ({
          id: member.id,
          username: member.user.username,
          displayName: member.displayName,
          nickname: member.nickname,
          roles: member.roles.cache.map(r => ({ id: r.id, name: r.name })),
          joinedAt: member.joinedAt?.toISOString(),
        }));

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({ members }, null, 2),
          },
        ],
      };
    }

    case 'discord_create_thread': {
      const channel = await client.channels.fetch(args.channelId);
      if (!channel || !channel.isTextBased()) {
        throw new Error(`Channel not found or not a text channel: ${args.channelId}`);
      }

      const message = await channel.messages.fetch(args.messageId);
      if (!message) {
        throw new Error(`Message not found: ${args.messageId}`);
      }

      const thread = await message.startThread({
        name: args.name,
      });

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              threadId: thread.id,
              name: thread.name,
              createdAt: thread.createdAt?.toISOString(),
            }, null, 2),
          },
        ],
      };
    }

    default:
      throw new Error(`Unknown tool: ${toolName}`);
  }
}

// MCP Protocol handlers
const handlers = {
  initialize: (params) => {
    initialized = true;
    return {
      protocolVersion: MCP_VERSION,
      capabilities: {
        tools: {},
      },
      serverInfo: {
        name: SERVER_NAME,
        version: SERVER_VERSION,
      },
    };
  },

  'tools/list': () => {
    if (!initialized) {
      throw new Error('Server not initialized');
    }
    return {
      tools: TOOLS,
    };
  },

  'tools/call': async (params) => {
    if (!initialized) {
      throw new Error('Server not initialized');
    }

    const { name, arguments: args } = params;
    const tool = TOOLS.find(t => t.name === name);
    if (!tool) {
      throw new Error(`Unknown tool: ${name}`);
    }

    return await handleToolCall(name, args || {});
  },
};

// Start Discord client
client.once('ready', () => {
  clientReady = true;
  console.error(`Discord bot logged in as ${client.user.tag}`);
});

client.login(token).catch(err => {
  console.error('Failed to login to Discord:', err.message);
  process.exit(1);
});

// Read and process incoming messages
let buffer = '';

process.stdin.setEncoding('utf8');

process.stdin.on('data', async (chunk) => {
  buffer += chunk;

  // Process complete lines (MCP messages are newline-delimited JSON)
  let newlineIndex;
  while ((newlineIndex = buffer.indexOf('\n')) !== -1) {
    const line = buffer.slice(0, newlineIndex).trim();
    buffer = buffer.slice(newlineIndex + 1);

    if (!line) continue;

    try {
      const message = JSON.parse(line);
      const { id, method, params } = message;

      if (!method) continue; // Skip notifications without method

      const handler = handlers[method];
      if (!handler) {
        sendMessage({
          jsonrpc: '2.0',
          id,
          error: {
            code: -32601,
            message: `Method not found: ${method}`,
          },
        });
        continue;
      }

      try {
        const result = await handler(params);
        sendMessage({
          jsonrpc: '2.0',
          id,
          result,
        });
      } catch (error) {
        sendMessage({
          jsonrpc: '2.0',
          id,
          error: {
            code: -32603,
            message: error.message,
            data: error.stack,
          },
        });
      }
    } catch (error) {
      console.error('Error processing message:', error);
      // Try to send error response if we can parse the id
      try {
        const msg = JSON.parse(line);
        if (msg.id) {
          sendMessage({
            jsonrpc: '2.0',
            id: msg.id,
            error: {
              code: -32700,
              message: 'Parse error',
            },
          });
        }
      } catch {}
    }
  }
});

process.stdin.on('end', () => {
  client.destroy();
  process.exit(0);
});

process.on('SIGTERM', () => {
  client.destroy();
  process.exit(0);
});

process.on('SIGINT', () => {
  client.destroy();
  process.exit(0);
});

// Log startup (to stderr so it doesn't interfere with MCP protocol on stdout)
console.error(`Discord MCP Server v${SERVER_VERSION} started`);
console.error(`Integration ID: ${process.env.IRIS_INTEGRATION_ID || 'unknown'}`);
