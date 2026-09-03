#!/usr/bin/env node
/**
 * Outlook MCP Server
 * 
 * An MCP server that provides Microsoft Outlook / Microsoft 365 access via Microsoft Graph API.
 * Communicates over stdio using the Model Context Protocol.
 * 
 * Environment variables:
 * - IRIS_CREDENTIAL: JSON string with OAuth tokens
 * - IRIS_INTEGRATION_ID: The integration ID (should be "outlook")
 * - IRIS_MCP_VERSION: MCP protocol version
 */

import { Client } from '@azure/msal-node';

// MCP Protocol constants
const MCP_VERSION = '2024-11-05';
const SERVER_NAME = 'iris-mcp-outlook';
const SERVER_VERSION = '1.0.0';

// Microsoft Graph API base URL
const GRAPH_API_BASE = 'https://graph.microsoft.com/v1.0';

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

// MCP Server State
let initialized = false;
let accessToken = credential.access_token;

// Tool definitions
const TOOLS = [
  {
    name: 'outlook_list_inbox',
    description: 'List emails in the inbox, returns message metadata',
    inputSchema: {
      type: 'object',
      properties: {
        maxResults: {
          type: 'number',
          description: 'Maximum number of messages to return (default: 10, max: 50)',
          default: 10,
        },
        skip: {
          type: 'number',
          description: 'Number of messages to skip (for pagination)',
          default: 0,
        },
        filter: {
          type: 'string',
          description: 'OData filter query (e.g., "from/emailAddress/address eq \"user@example.com\"")',
        },
      },
    },
  },
  {
    name: 'outlook_search',
    description: 'Search emails using Microsoft Graph search query',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Search query (e.g., "subject:meeting from:user@example.com")',
        },
        maxResults: {
          type: 'number',
          description: 'Maximum number of results (default: 10)',
          default: 10,
        },
        skip: {
          type: 'number',
          description: 'Number of messages to skip',
          default: 0,
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'outlook_read_message',
    description: 'Read a specific email message by ID',
    inputSchema: {
      type: 'object',
      properties: {
        messageId: {
          type: 'string',
          description: 'The message ID to read',
        },
      },
      required: ['messageId'],
    },
  },
  {
    name: 'outlook_send',
    description: 'Send a new email',
    inputSchema: {
      type: 'object',
      properties: {
        to: {
          type: 'string',
          description: 'Recipient email address',
        },
        subject: {
          type: 'string',
          description: 'Email subject',
        },
        body: {
          type: 'string',
          description: 'Email body (plain text)',
        },
        htmlBody: {
          type: 'string',
          description: 'Email body (HTML, optional)',
        },
        cc: {
          type: 'array',
          items: { type: 'string' },
          description: 'CC recipients email addresses',
        },
        bcc: {
          type: 'array',
          items: { type: 'string' },
          description: 'BCC recipients email addresses',
        },
      },
      required: ['to', 'subject', 'body'],
    },
  },
  {
    name: 'outlook_reply',
    description: 'Reply to an existing email',
    inputSchema: {
      type: 'object',
      properties: {
        messageId: {
          type: 'string',
          description: 'The message ID to reply to',
        },
        body: {
          type: 'string',
          description: 'Reply body (plain text)',
        },
        htmlBody: {
          type: 'string',
          description: 'Reply body (HTML, optional)',
        },
        replyToAll: {
          type: 'boolean',
          description: 'Reply to all recipients (default: false)',
          default: false,
        },
      },
      required: ['messageId', 'body'],
    },
  },
  {
    name: 'outlook_move',
    description: 'Move a message to a different folder',
    inputSchema: {
      type: 'object',
      properties: {
        messageId: {
          type: 'string',
          description: 'The message ID to move',
        },
        folderId: {
          type: 'string',
          description: 'Destination folder ID (e.g., "deleteditems", "drafts", "sentitems")',
        },
      },
      required: ['messageId', 'folderId'],
    },
  },
  {
    name: 'outlook_delete',
    description: 'Delete a message (move to deleted items)',
    inputSchema: {
      type: 'object',
      properties: {
        messageId: {
          type: 'string',
          description: 'The message ID to delete',
        },
        permanent: {
          type: 'boolean',
          description: 'Permanently delete (skip deleted items)',
          default: false,
        },
      },
      required: ['messageId'],
    },
  },
];

// Helper function to send MCP messages
function sendMessage(message) {
  const json = JSON.stringify(message);
  process.stdout.write(json + '\n');
}

// Helper function to make Graph API requests
async function graphApiRequest(endpoint, method = 'GET', body = null) {
  const url = `${GRAPH_API_BASE}${endpoint}`;
  const headers = {
    'Authorization': `Bearer ${accessToken}`,
    'Content-Type': 'application/json',
  };

  const options = {
    method,
    headers,
  };

  if (body) {
    options.body = JSON.stringify(body);
  }

  const response = await fetch(url, options);
  
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Graph API error: ${response.status} ${error}`);
  }

  if (response.status === 204) {
    return null;
  }

  return await response.json();
}

// Helper to format email address for Graph API
function formatEmailAddress(email) {
  return {
    emailAddress: {
      address: email,
    },
  };
}

// Tool implementations
async function handleToolCall(toolName, args) {
  switch (toolName) {
    case 'outlook_list_inbox': {
      const params = new URLSearchParams();
      params.append('$top', Math.min(args.maxResults || 10, 50));
      if (args.skip) params.append('$skip', args.skip);
      params.append('$orderby', 'receivedDateTime desc');
      params.append('$select', 'id,subject,from,toRecipients,receivedDateTime,bodyPreview,conversationId');
      if (args.filter) params.append('$filter', args.filter);

      const data = await graphApiRequest(`/me/messages?${params.toString()}`);
      
      const messages = (data.value || []).map(msg => ({
        id: msg.id,
        conversationId: msg.conversationId,
        subject: msg.subject || '(no subject)',
        from: msg.from?.emailAddress?.address || '',
        fromName: msg.from?.emailAddress?.name || '',
        to: (msg.toRecipients || []).map(r => r.emailAddress?.address).filter(Boolean),
        receivedDateTime: msg.receivedDateTime,
        bodyPreview: msg.bodyPreview || '',
      }));

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              messages,
              '@odata.nextLink': data['@odata.nextLink'],
            }, null, 2),
          },
        ],
      };
    }

    case 'outlook_search': {
      // Microsoft Graph uses $search for text search
      const params = new URLSearchParams();
      params.append('$top', Math.min(args.maxResults || 10, 50));
      if (args.skip) params.append('$skip', args.skip);
      params.append('$orderby', 'receivedDateTime desc');
      params.append('$select', 'id,subject,from,toRecipients,receivedDateTime,bodyPreview,conversationId');
      params.append('$search', `"${args.query}"`);

      const data = await graphApiRequest(`/me/messages?${params.toString()}`);
      
      const messages = (data.value || []).map(msg => ({
        id: msg.id,
        conversationId: msg.conversationId,
        subject: msg.subject || '(no subject)',
        from: msg.from?.emailAddress?.address || '',
        fromName: msg.from?.emailAddress?.name || '',
        to: (msg.toRecipients || []).map(r => r.emailAddress?.address).filter(Boolean),
        receivedDateTime: msg.receivedDateTime,
        bodyPreview: msg.bodyPreview || '',
      }));

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              messages,
              '@odata.nextLink': data['@odata.nextLink'],
            }, null, 2),
          },
        ],
      };
    }

    case 'outlook_read_message': {
      const data = await graphApiRequest(`/me/messages/${args.messageId}?$select=id,subject,from,toRecipients,ccRecipients,bccRecipients,receivedDateTime,body,conversationId,internetMessageId`);

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              id: data.id,
              conversationId: data.conversationId,
              internetMessageId: data.internetMessageId,
              subject: data.subject || '(no subject)',
              from: data.from?.emailAddress?.address || '',
              fromName: data.from?.emailAddress?.name || '',
              to: (data.toRecipients || []).map(r => ({
                address: r.emailAddress?.address,
                name: r.emailAddress?.name,
              })),
              cc: (data.ccRecipients || []).map(r => ({
                address: r.emailAddress?.address,
                name: r.emailAddress?.name,
              })),
              bcc: (data.bccRecipients || []).map(r => ({
                address: r.emailAddress?.address,
                name: r.emailAddress?.name,
              })),
              receivedDateTime: data.receivedDateTime,
              body: data.body?.content || '',
              bodyContentType: data.body?.contentType || 'text',
            }, null, 2),
          },
        ],
      };
    }

    case 'outlook_send': {
      const message = {
        subject: args.subject,
        body: {
          contentType: args.htmlBody ? 'html' : 'text',
          content: args.htmlBody || args.body,
        },
        toRecipients: [formatEmailAddress(args.to)],
      };

      if (args.cc && args.cc.length > 0) {
        message.ccRecipients = args.cc.map(formatEmailAddress);
      }

      if (args.bcc && args.bcc.length > 0) {
        message.bccRecipients = args.bcc.map(formatEmailAddress);
      }

      const data = await graphApiRequest('/me/sendMail', 'POST', { message });

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              message: 'Email sent successfully',
            }, null, 2),
          },
        ],
      };
    }

    case 'outlook_reply': {
      const endpoint = args.replyToAll 
        ? `/me/messages/${args.messageId}/replyAll`
        : `/me/messages/${args.messageId}/reply`;

      const body = {
        message: {
          body: {
            contentType: args.htmlBody ? 'html' : 'text',
            content: args.htmlBody || args.body,
          },
        },
      };

      await graphApiRequest(endpoint, 'POST', body);

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              message: 'Reply sent successfully',
            }, null, 2),
          },
        ],
      };
    }

    case 'outlook_move': {
      const data = await graphApiRequest(
        `/me/messages/${args.messageId}/move`,
        'POST',
        { destinationId: args.folderId }
      );

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              messageId: data.id,
              parentFolderId: data.parentFolderId,
            }, null, 2),
          },
        ],
      };
    }

    case 'outlook_delete': {
      if (args.permanently) {
        await graphApiRequest(`/me/messages/${args.messageId}`, 'DELETE');
      } else {
        // Move to deleted items
        await graphApiRequest(
          `/me/messages/${args.messageId}/move`,
          'POST',
          { destinationId: 'deleteditems' }
        );
      }

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              messageId: args.messageId,
              permanentlyDeleted: args.permanently || false,
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
  process.exit(0);
});

process.on('SIGTERM', () => {
  process.exit(0);
});

process.on('SIGINT', () => {
  process.exit(0);
});

// Log startup (to stderr so it doesn't interfere with MCP protocol on stdout)
console.error(`Outlook MCP Server v${SERVER_VERSION} started`);
console.error(`Integration ID: ${process.env.IRIS_INTEGRATION_ID || 'unknown'}`);
