#!/usr/bin/env node
/**
 * IMAP/SMTP MCP Server
 * 
 * An MCP server that provides access to generic IMAP/SMTP email accounts.
 * Communicates over stdio using the Model Context Protocol.
 * 
 * Environment variables:
 * - IRIS_CREDENTIAL: JSON string with IMAP/SMTP credentials
 * - IRIS_INTEGRATION_ID: The integration ID (should be "imap_smtp")
 * - IRIS_MCP_VERSION: MCP protocol version
 */

import Imap from 'imap';
import nodemailer from 'nodemailer';
import { simpleParser } from 'mailparser';
import { promisify } from 'util';

// MCP Protocol constants
const MCP_VERSION = '2024-11-05';
const SERVER_NAME = 'iris-mcp-imap';
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

// Validate required fields
const required = ['imap_host', 'imap_port', 'smtp_host', 'smtp_port', 'email', 'password'];
for (const field of required) {
  if (!credential[field]) {
    console.error(`Error: Missing required credential field: ${field}`);
    process.exit(1);
  }
}

// MCP Server State
let initialized = false;

// Tool definitions
const TOOLS = [
  {
    name: 'email_list_inbox',
    description: 'List emails from the inbox folder',
    inputSchema: {
      type: 'object',
      properties: {
        limit: {
          type: 'number',
          description: 'Maximum number of emails to return (default: 20)',
          default: 20,
        },
        folder: {
          type: 'string',
          description: 'Folder to list (default: INBOX)',
          default: 'INBOX',
        },
      },
    },
  },
  {
    name: 'email_search',
    description: 'Search emails in a folder',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Search query (IMAP SEARCH criteria, e.g., "SUBJECT meeting" or "FROM user@example.com")',
        },
        folder: {
          type: 'string',
          description: 'Folder to search (default: INBOX)',
          default: 'INBOX',
        },
        limit: {
          type: 'number',
          description: 'Maximum results (default: 20)',
          default: 20,
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'email_read',
    description: 'Read a specific email by UID',
    inputSchema: {
      type: 'object',
      properties: {
        uid: {
          type: 'string',
          description: 'Email UID',
        },
        folder: {
          type: 'string',
          description: 'Folder containing the email (default: INBOX)',
          default: 'INBOX',
        },
      },
      required: ['uid'],
    },
  },
  {
    name: 'email_send',
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
          description: 'CC recipients',
        },
        bcc: {
          type: 'array',
          items: { type: 'string' },
          description: 'BCC recipients',
        },
      },
      required: ['to', 'subject', 'body'],
    },
  },
  {
    name: 'email_reply',
    description: 'Reply to an existing email',
    inputSchema: {
      type: 'object',
      properties: {
        uid: {
          type: 'string',
          description: 'Original email UID',
        },
        folder: {
          type: 'string',
          description: 'Folder containing original email (default: INBOX)',
          default: 'INBOX',
        },
        body: {
          type: 'string',
          description: 'Reply body',
        },
        replyToAll: {
          type: 'boolean',
          description: 'Reply to all recipients',
          default: false,
        },
      },
      required: ['uid', 'body'],
    },
  },
  {
    name: 'email_move',
    description: 'Move an email to another folder',
    inputSchema: {
      type: 'object',
      properties: {
        uid: {
          type: 'string',
          description: 'Email UID',
        },
        fromFolder: {
          type: 'string',
          description: 'Source folder (default: INBOX)',
          default: 'INBOX',
        },
        toFolder: {
          type: 'string',
          description: 'Destination folder',
        },
      },
      required: ['uid', 'toFolder'],
    },
  },
  {
    name: 'email_delete',
    description: 'Delete an email',
    inputSchema: {
      type: 'object',
      properties: {
        uid: {
          type: 'string',
          description: 'Email UID',
        },
        folder: {
          type: 'string',
          description: 'Folder containing email (default: INBOX)',
          default: 'INBOX',
        },
        permanent: {
          type: 'boolean',
          description: 'Permanently delete (don\'t move to Trash)',
          default: false,
        },
      },
      required: ['uid'],
    },
  },
];

// Helper function to send MCP messages
function sendMessage(message) {
  const json = JSON.stringify(message);
  process.stdout.write(json + '\n');
}

// Create IMAP connection
function createImapConnection() {
  return new Imap({
    user: credential.email,
    password: credential.password,
    host: credential.imap_host,
    port: credential.imap_port,
    tls: credential.imap_tls !== false, // Default to true
    tlsOptions: {
      rejectUnauthorized: false, // Allow self-signed certs
    },
  });
}

// Open mailbox helper
function openBox(imap, folder = 'INBOX', readOnly = false) {
  return new Promise((resolve, reject) => {
    imap.openBox(folder, readOnly, (err, box) => {
      if (err) reject(err);
      else resolve(box);
    });
  });
}

// Search helper
function search(imap, criteria) {
  return new Promise((resolve, reject) => {
    imap.search(criteria, (err, results) => {
      if (err) reject(err);
      else resolve(results);
    });
  });
}

// Fetch helper
function fetchEmails(imap, sources, options) {
  return new Promise((resolve, reject) => {
    const emails = [];
    const fetch = imap.fetch(sources, options);

    fetch.on('message', (msg, seqno) => {
      let buffer = '';
      msg.on('body', (stream) => {
        stream.on('data', (chunk) => {
          buffer += chunk.toString('utf8');
        });
      });
      msg.once('end', () => {
        emails.push({ seqno, buffer });
      });
    });

    fetch.once('error', reject);
    fetch.once('end', () => resolve(emails));
  });
}

// Tool implementations
async function handleToolCall(toolName, args) {
  switch (toolName) {
    case 'email_list_inbox': {
      const folder = args.folder || 'INBOX';
      const limit = args.limit || 20;

      const imap = createImapConnection();

      return new Promise((resolve, reject) => {
        imap.once('ready', async () => {
          try {
            const box = await openBox(imap, folder, true);
            const total = box.messages.total;
            const start = Math.max(1, total - limit + 1);

            if (start > total) {
              resolve({
                content: [{ type: 'text', text: JSON.stringify({ emails: [], folder, total: 0 }, null, 2) }],
              });
              imap.end();
              return;
            }

            const emails = await fetchEmails(imap, `${start}:${total}`, { bodies: 'HEADER.FIELDS (FROM TO SUBJECT DATE)', struct: false });

            const results = emails.map((email) => {
              const headers = email.buffer.split('\r\n').reduce((acc, line) => {
                const match = line.match(/^([^:]+):\s*(.+)$/);
                if (match) acc[match[1].toLowerCase()] = match[2];
                return acc;
              }, {});

              return {
                seqno: email.seqno,
                subject: headers.subject || '(no subject)',
                from: headers.from || '',
                to: headers.to || '',
                date: headers.date || '',
              };
            });

            resolve({
              content: [{ type: 'text', text: JSON.stringify({ emails: results, folder, total }, null, 2) }],
            });
            imap.end();
          } catch (err) {
            reject(err);
          }
        });

        imap.once('error', reject);
        imap.connect();
      });
    }

    case 'email_search': {
      const folder = args.folder || 'INBOX';
      const limit = args.limit || 20;
      const query = args.query;

      const imap = createImapConnection();

      return new Promise((resolve, reject) => {
        imap.once('ready', async () => {
          try {
            await openBox(imap, folder, true);

            // Parse simple search criteria
            const criteria = ['ALL'];
            if (query.toUpperCase().startsWith('SUBJECT ')) {
              criteria.push(['SUBJECT', query.substring(8)]);
            } else if (query.toUpperCase().startsWith('FROM ')) {
              criteria.push(['FROM', query.substring(5)]);
            } else if (query.toUpperCase().startsWith('TO ')) {
              criteria.push(['TO', query.substring(3)]);
            } else {
              criteria.push(['TEXT', query]);
            }

            const results = await search(imap, criteria);
            const limited = results.slice(-limit);

            if (limited.length === 0) {
              resolve({
                content: [{ type: 'text', text: JSON.stringify({ emails: [], folder, query }, null, 2) }],
              });
              imap.end();
              return;
            }

            const emails = await fetchEmails(imap, limited, { bodies: 'HEADER.FIELDS (FROM TO SUBJECT DATE)' });

            const mapped = emails.map((email) => {
              const headers = email.buffer.split('\r\n').reduce((acc, line) => {
                const match = line.match(/^([^:]+):\s*(.+)$/);
                if (match) acc[match[1].toLowerCase()] = match[2];
                return acc;
              }, {});

              return {
                seqno: email.seqno,
                subject: headers.subject || '(no subject)',
                from: headers.from || '',
                to: headers.to || '',
                date: headers.date || '',
              };
            });

            resolve({
              content: [{ type: 'text', text: JSON.stringify({ emails: mapped, folder, query }, null, 2) }],
            });
            imap.end();
          } catch (err) {
            reject(err);
          }
        });

        imap.once('error', reject);
        imap.connect();
      });
    }

    case 'email_read': {
      const folder = args.folder || 'INBOX';
      const uid = args.uid;

      const imap = createImapConnection();

      return new Promise((resolve, reject) => {
        imap.once('ready', async () => {
          try {
            await openBox(imap, folder, true);

            const emails = await fetchEmails(imap, uid, { bodies: '' });
            if (emails.length === 0) {
              reject(new Error('Email not found'));
              return;
            }

            const parsed = await simpleParser(emails[0].buffer);

            resolve({
              content: [{
                type: 'text',
                text: JSON.stringify({
                  uid,
                  subject: parsed.subject || '(no subject)',
                  from: parsed.from?.text || '',
                  to: parsed.to?.text || '',
                  cc: parsed.cc?.text || '',
                  date: parsed.date?.toISOString() || '',
                  text: parsed.text || '',
                  html: parsed.html || '',
                  attachments: (parsed.attachments || []).map(att => ({
                    filename: att.filename,
                    contentType: att.contentType,
                    size: att.size,
                  })),
                }, null, 2),
              }],
            });
            imap.end();
          } catch (err) {
            reject(err);
          }
        });

        imap.once('error', reject);
        imap.connect();
      });
    }

    case 'email_send': {
      const transporter = nodemailer.createTransport({
        host: credential.smtp_host,
        port: credential.smtp_port,
        secure: credential.smtp_port == 465,
        auth: {
          user: credential.email,
          pass: credential.password,
        },
        tls: {
          rejectUnauthorized: false,
        },
      });

      const info = await transporter.sendMail({
        from: credential.email,
        to: args.to,
        cc: args.cc,
        bcc: args.bcc,
        subject: args.subject,
        text: args.body,
        html: args.htmlBody,
      });

      return {
        content: [{
          type: 'text',
          text: JSON.stringify({
            success: true,
            messageId: info.messageId,
          }, null, 2),
        }],
      };
    }

    case 'email_reply': {
      // First, fetch the original email
      const folder = args.folder || 'INBOX';
      const uid = args.uid;

      const imap = createImapConnection();

      return new Promise((resolve, reject) => {
        imap.once('ready', async () => {
          try {
            await openBox(imap, folder, true);

            const emails = await fetchEmails(imap, uid, { bodies: '' });
            if (emails.length === 0) {
              reject(new Error('Original email not found'));
              return;
            }

            const parsed = await simpleParser(emails[0].buffer);

            // Construct reply
            const transporter = nodemailer.createTransport({
              host: credential.smtp_host,
              port: credential.smtp_port,
              secure: credential.smtp_port == 465,
              auth: {
                user: credential.email,
                pass: credential.password,
              },
              tls: {
                rejectUnauthorized: false,
              },
            });

            const recipients = args.replyToAll
              ? [parsed.from?.text, parsed.to?.text].filter(Boolean).join(', ')
              : parsed.from?.text;

            const info = await transporter.sendMail({
              from: credential.email,
              to: recipients,
              subject: `Re: ${parsed.subject || ''}`,
              text: args.body,
              inReplyTo: parsed.messageId,
              references: parsed.references?.concat([parsed.messageId]) || [parsed.messageId],
            });

            resolve({
              content: [{
                type: 'text',
                text: JSON.stringify({
                  success: true,
                  messageId: info.messageId,
                }, null, 2),
              }],
            });
            imap.end();
          } catch (err) {
            reject(err);
          }
        });

        imap.once('error', reject);
        imap.connect();
      });
    }

    case 'email_move': {
      const fromFolder = args.fromFolder || 'INBOX';
      const toFolder = args.toFolder;
      const uid = args.uid;

      const imap = createImapConnection();

      return new Promise((resolve, reject) => {
        imap.once('ready', async () => {
          try {
            await openBox(imap, fromFolder, false);

            imap.move(uid, toFolder, (err) => {
              if (err) {
                reject(err);
                return;
              }

              resolve({
                content: [{
                  type: 'text',
                  text: JSON.stringify({
                    success: true,
                    uid,
                    fromFolder,
                    toFolder,
                  }, null, 2),
                }],
              });
              imap.end();
            });
          } catch (err) {
            reject(err);
          }
        });

        imap.once('error', reject);
        imap.connect();
      });
    }

    case 'email_delete': {
      const folder = args.folder || 'INBOX';
      const uid = args.uid;
      const permanent = args.permanent || false;

      const imap = createImapConnection();

      return new Promise((resolve, reject) => {
        imap.once('ready', async () => {
          try {
            await openBox(imap, folder, false);

            if (permanent) {
              imap.addFlags(uid, '\\Deleted', (err) => {
                if (err) {
                  reject(err);
                  return;
                }
                imap.expunge((expungeErr) => {
                  if (expungeErr) {
                    reject(expungeErr);
                    return;
                  }
                  resolve({
                    content: [{
                      type: 'text',
                      text: JSON.stringify({
                        success: true,
                        uid,
                        permanentlyDeleted: true,
                      }, null, 2),
                    }],
                  });
                  imap.end();
                });
              });
            } else {
              // Move to Trash
              imap.move(uid, 'Trash', (err) => {
                if (err) {
                  reject(err);
                  return;
                }
                resolve({
                  content: [{
                    type: 'text',
                    text: JSON.stringify({
                      success: true,
                      uid,
                      permanentlyDeleted: false,
                    }, null, 2),
                  }],
                });
                imap.end();
              });
            }
          } catch (err) {
            reject(err);
          }
        });

        imap.once('error', reject);
        imap.connect();
      });
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
console.error(`IMAP/SMTP MCP Server v${SERVER_VERSION} started`);
console.error(`Integration ID: ${process.env.IRIS_INTEGRATION_ID || 'unknown'}`);
console.error(`Email: ${credential.email}`);
console.error(`IMAP: ${credential.imap_host}:${credential.imap_port}`);
console.error(`SMTP: ${credential.smtp_host}:${credential.smtp_port}`);
