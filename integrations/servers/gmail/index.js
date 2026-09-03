#!/usr/bin/env node
/**
 * Gmail MCP Server
 * 
 * An MCP server that provides Gmail access via Google APIs.
 * Communicates over stdio using the Model Context Protocol.
 * 
 * Environment variables:
 * - IRIS_CREDENTIAL: JSON string with OAuth tokens
 * - IRIS_INTEGRATION_ID: The integration ID (should be "gmail")
 * - IRIS_MCP_VERSION: MCP protocol version
 */

import { google } from 'googleapis';
import { OAuth2Client } from 'google-auth-library';
import { readFileSync } from 'fs';

// MCP Protocol constants
const MCP_VERSION = '2024-11-05';
const SERVER_NAME = 'iris-mcp-gmail';
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

// Initialize Gmail API client
const oauth2Client = new OAuth2Client();
oauth2Client.setCredentials({
  access_token: credential.access_token,
  refresh_token: credential.refresh_token,
  expiry_date: credential.expires_at ? credential.expires_at * 1000 : null,
});

const gmail = google.gmail({ version: 'v1', auth: oauth2Client });

// MCP Server State
let initialized = false;
let requestId = 0;

// Tool definitions
const TOOLS = [
  {
    name: 'gmail_list_inbox',
    description: 'List emails in the inbox, returns message metadata',
    inputSchema: {
      type: 'object',
      properties: {
        maxResults: {
          type: 'number',
          description: 'Maximum number of messages to return (default: 10, max: 100)',
          default: 10,
        },
        pageToken: {
          type: 'string',
          description: 'Page token for pagination',
        },
        query: {
          type: 'string',
          description: 'Gmail search query (e.g., "from:example@gmail.com")',
        },
      },
    },
  },
  {
    name: 'gmail_search',
    description: 'Search emails using Gmail query syntax',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Gmail search query (e.g., "subject:meeting from:boss")',
        },
        maxResults: {
          type: 'number',
          description: 'Maximum number of results (default: 10)',
          default: 10,
        },
        pageToken: {
          type: 'string',
          description: 'Page token for pagination',
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'gmail_read_message',
    description: 'Read a specific email message by ID',
    inputSchema: {
      type: 'object',
      properties: {
        messageId: {
          type: 'string',
          description: 'The message ID to read',
        },
        format: {
          type: 'string',
          description: 'Format: "full", "metadata", or "minimal"',
          default: 'full',
        },
      },
      required: ['messageId'],
    },
  },
  {
    name: 'gmail_send',
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
          type: 'string',
          description: 'CC recipients (comma-separated)',
        },
        bcc: {
          type: 'string',
          description: 'BCC recipients (comma-separated)',
        },
      },
      required: ['to', 'subject', 'body'],
    },
  },
  {
    name: 'gmail_reply',
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
    name: 'gmail_label',
    description: 'Apply labels to a message',
    inputSchema: {
      type: 'object',
      properties: {
        messageId: {
          type: 'string',
          description: 'The message ID to label',
        },
        addLabels: {
          type: 'array',
          items: { type: 'string' },
          description: 'Label IDs to add',
        },
        removeLabels: {
          type: 'array',
          items: { type: 'string' },
          description: 'Label IDs to remove',
        },
      },
      required: ['messageId'],
    },
  },
  {
    name: 'gmail_delete',
    description: 'Move a message to trash',
    inputSchema: {
      type: 'object',
      properties: {
        messageId: {
          type: 'string',
          description: 'The message ID to delete',
        },
        permanently: {
          type: 'boolean',
          description: 'Permanently delete (skip trash)',
          default: false,
        },
      },
      required: ['messageId'],
    },
  },
  {
    name: 'gmail_create_draft',
    description: 'Create a draft email',
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
          type: 'string',
          description: 'CC recipients',
        },
        bcc: {
          type: 'string',
          description: 'BCC recipients',
        },
      },
      required: ['to', 'subject', 'body'],
    },
  },
];

// Helper function to send MCP messages
function sendMessage(message) {
  const json = JSON.stringify(message);
  process.stdout.write(json + '\n');
}

// Helper to decode base64url
function decodeBase64url(data) {
  if (!data) return '';
  // Replace URL-safe chars and add padding
  let str = data.replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  return Buffer.from(str, 'base64').toString('utf8');
}

// Helper to parse email headers
function parseHeaders(headers) {
  const result = {};
  for (const header of headers || []) {
    result[header.name.toLowerCase()] = header.value;
  }
  return result;
}

// Helper to extract body from message parts
function extractBody(parts) {
  if (!parts) return { text: '', html: '' };
  
  let text = '';
  let html = '';
  
  for (const part of parts) {
    if (part.mimeType === 'text/plain' && part.body?.data) {
      text = decodeBase64url(part.body.data);
    } else if (part.mimeType === 'text/html' && part.body?.data) {
      html = decodeBase64url(part.body.data);
    } else if (part.parts) {
      const nested = extractBody(part.parts);
      if (nested.text) text = nested.text;
      if (nested.html) html = nested.html;
    }
  }
  
  return { text, html };
}

// Tool implementations
async function handleToolCall(toolName, args) {
  switch (toolName) {
    case 'gmail_list_inbox': {
      const params = {
        userId: 'me',
        maxResults: args.maxResults || 10,
        labelIds: ['INBOX'],
      };
      if (args.pageToken) params.pageToken = args.pageToken;
      if (args.query) params.q = args.query;
      
      const res = await gmail.users.messages.list(params);
      
      // Get full message details for each
      const messages = [];
      for (const msg of res.data.messages || []) {
        try {
          const fullMsg = await gmail.users.messages.get({
            userId: 'me',
            id: msg.id,
            format: 'metadata',
            metadataHeaders: ['Subject', 'From', 'To', 'Date'],
          });
          
          const headers = parseHeaders(fullMsg.data.payload?.headers);
          messages.push({
            id: msg.id,
            threadId: msg.threadId,
            subject: headers.subject || '(no subject)',
            from: headers.from || '',
            to: headers.to || '',
            date: headers.date || '',
            snippet: fullMsg.data.snippet || '',
            labels: fullMsg.data.labelIds || [],
          });
        } catch (e) {
          messages.push({
            id: msg.id,
            threadId: msg.threadId,
            error: e.message,
          });
        }
      }
      
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              messages,
              nextPageToken: res.data.nextPageToken,
              resultSizeEstimate: res.data.resultSizeEstimate,
            }, null, 2),
          },
        ],
      };
    }
    
    case 'gmail_search': {
      const params = {
        userId: 'me',
        q: args.query,
        maxResults: args.maxResults || 10,
      };
      if (args.pageToken) params.pageToken = args.pageToken;
      
      const res = await gmail.users.messages.list(params);
      
      const messages = [];
      for (const msg of res.data.messages || []) {
        try {
          const fullMsg = await gmail.users.messages.get({
            userId: 'me',
            id: msg.id,
            format: 'metadata',
            metadataHeaders: ['Subject', 'From', 'To', 'Date'],
          });
          
          const headers = parseHeaders(fullMsg.data.payload?.headers);
          messages.push({
            id: msg.id,
            threadId: msg.threadId,
            subject: headers.subject || '(no subject)',
            from: headers.from || '',
            to: headers.to || '',
            date: headers.date || '',
            snippet: fullMsg.data.snippet || '',
            labels: fullMsg.data.labelIds || [],
          });
        } catch (e) {
          messages.push({
            id: msg.id,
            threadId: msg.threadId,
            error: e.message,
          });
        }
      }
      
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              messages,
              nextPageToken: res.data.nextPageToken,
              resultSizeEstimate: res.data.resultSizeEstimate,
            }, null, 2),
          },
        ],
      };
    }
    
    case 'gmail_read_message': {
      const res = await gmail.users.messages.get({
        userId: 'me',
        id: args.messageId,
        format: args.format || 'full',
      });
      
      const msg = res.data;
      const headers = parseHeaders(msg.payload?.headers);
      const body = extractBody(msg.payload?.parts || [msg.payload]);
      
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              id: msg.id,
              threadId: msg.threadId,
              subject: headers.subject || '(no subject)',
              from: headers.from || '',
              to: headers.to || '',
              cc: headers.cc || '',
              bcc: headers.bcc || '',
              date: headers.date || '',
              body: body.text || body.html,
              htmlBody: body.html,
              labels: msg.labelIds || [],
              snippet: msg.snippet || '',
            }, null, 2),
          },
        ],
      };
    }
    
    case 'gmail_send': {
      // Build email content
      const lines = [
        `To: ${args.to}`,
      ];
      if (args.cc) lines.push(`Cc: ${args.cc}`);
      if (args.bcc) lines.push(`Bcc: ${args.bcc}`);
      lines.push(`Subject: ${args.subject}`);
      lines.push('Content-Type: text/plain; charset=utf-8');
      lines.push('');
      lines.push(args.body);
      
      const raw = Buffer.from(lines.join('\r\n'))
        .toString('base64')
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '');
      
      const res = await gmail.users.messages.send({
        userId: 'me',
        requestBody: { raw },
      });
      
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              messageId: res.data.id,
              threadId: res.data.threadId,
            }, null, 2),
          },
        ],
      };
    }
    
    case 'gmail_reply': {
      // Get original message for thread info
      const original = await gmail.users.messages.get({
        userId: 'me',
        id: args.messageId,
        format: 'metadata',
        metadataHeaders: ['Subject', 'From', 'To', 'Cc', 'References', 'Message-ID'],
      });
      
      const headers = parseHeaders(original.data.payload?.headers);
      const subject = headers.subject?.startsWith('Re:') 
        ? headers.subject 
        : `Re: ${headers.subject}`;
      
      const lines = [
        `To: ${headers.from}`,
        `Subject: ${subject}`,
        `In-Reply-To: ${original.data.id}`,
        `References: ${headers.references || original.data.id}`,
        'Content-Type: text/plain; charset=utf-8',
        '',
        args.body,
      ];
      
      if (args.replyToAll && headers.to) {
        lines[0] = `To: ${headers.from}, ${headers.to}`;
      }
      
      const raw = Buffer.from(lines.join('\r\n'))
        .toString('base64')
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '');
      
      const res = await gmail.users.messages.send({
        userId: 'me',
        requestBody: {
          raw,
          threadId: original.data.threadId,
        },
      });
      
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              messageId: res.data.id,
              threadId: res.data.threadId,
            }, null, 2),
          },
        ],
      };
    }
    
    case 'gmail_label': {
      const res = await gmail.users.messages.modify({
        userId: 'me',
        id: args.messageId,
        requestBody: {
          addLabelIds: args.addLabels || [],
          removeLabelIds: args.removeLabels || [],
        },
      });
      
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              messageId: res.data.id,
              labels: res.data.labelIds,
            }, null, 2),
          },
        ],
      };
    }
    
    case 'gmail_delete': {
      if (args.permanently) {
        await gmail.users.messages.delete({
          userId: 'me',
          id: args.messageId,
        });
      } else {
        await gmail.users.messages.trash({
          userId: 'me',
          id: args.messageId,
        });
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
    
    case 'gmail_create_draft': {
      const lines = [
        `To: ${args.to}`,
      ];
      if (args.cc) lines.push(`Cc: ${args.cc}`);
      if (args.bcc) lines.push(`Bcc: ${args.bcc}`);
      lines.push(`Subject: ${args.subject}`);
      lines.push('Content-Type: text/plain; charset=utf-8');
      lines.push('');
      lines.push(args.body);
      
      const raw = Buffer.from(lines.join('\r\n'))
        .toString('base64')
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '');
      
      const res = await gmail.users.drafts.create({
        userId: 'me',
        requestBody: {
          message: { raw },
        },
      });
      
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: true,
              draftId: res.data.id,
              messageId: res.data.message?.id,
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
  
  tools/list: () => {
    if (!initialized) {
      throw new Error('Server not initialized');
    }
    return {
      tools: TOOLS,
    };
  },
  
  tools/call: async (params) => {
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
console.error(`Gmail MCP Server v${SERVER_VERSION} started`);
console.error(`Integration ID: ${process.env.IRIS_INTEGRATION_ID || 'unknown'}`);
