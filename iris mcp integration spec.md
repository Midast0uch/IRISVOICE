Iris - Local MCP Integration Layer

Specification & Implementation Plan
Network: Torus | Application: Iris | Draft: v1.2 - 2026



1. Overview
Iris manages a suite of locally-running MCP servers, one per external service. Each server is pre-configured in the application backend. The user's only interaction is:
1. Toggle a service ON

2. Complete a one-time auth flow (OAuth, phone code, or API key depending on the service)
3. The agent gains full tool access to that service immediately

 4. Toggle OFF at any time - server stops, token wiped from memory, permissions revoked

No manual configuration. No JSON editing. No port management. The user sees a clean list of services. The infrastructure is invisible.


2. Architecture

+-----------------------------------------------------+
¦	IRIS APPLICATION	¦
¦	¦
¦ +--------------+	+--------------------------+  ¦
¦ ¦ Integration ¦	¦	MCP Host / Router	¦ ¦
¦ ¦	Manager UI ¦----? ¦ (spawns & kills servers)¦ ¦
¦ +--------------+	+--------------------------+  ¦
¦	¦	¦
¦	+---------------------------+--------------+  ¦
¦	?	?	?	? ¦
¦	+----------+	+----------+ +--------+ +--------+¦
¦	¦ Gmail	¦	¦ Telegram ¦ ¦Discord ¦ ¦ IMAP	¦¦
¦	¦MCP Server¦	¦MCP Server¦ ¦ MCP	¦ ¦ MCP	¦¦

¦
¦¦ (stdio) ¦
+----------+¦ (stdio) ¦ ¦(stdio) ¦ ¦(stdio) ¦¦
+----------+ +--------+ +--------+¦+--------+--------------+------------+------------+----+
¦	¦	¦	¦
?	?	?	?
Google API	Telegram	Discord API	Mail Server MTProto

Key Principles
All MCP servers run as child processes on the user's local machine

All servers communicate with the MCP host over stdio - no ports, no network exposure

All OAuth tokens and credentials are encrypted at rest using the OS-native keychain in Phase 1, with a pluggable key provider interface ready for the Torus identity layer in a future upgrade
The Torus network never sees, stores, or routes user credentials or message content

Disabling a connector kills the process and clears the in-memory token immediately

Re-enabling restarts the process and re-uses the stored encrypted credential



3. Integration Registry
The backend ships with a pre-configured registry of all supported integrations. This is the source of truth for what appears in the UI. Users never edit this - they only toggle entries on or off.

// integrations/registry.json (bundled with Iris)
{
"integrations": [
{
"id": "gmail",
"name": "Gmail",
"category": "email",
"icon": "gmail.svg", "auth_type": "oauth2", "oauth": {
"provider": "google", "scopes": [
"https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send",

"https://www.googleapis.com/auth/gmail.modify"
],
"client_id_env": "GOOGLE_CLIENT_ID", "redirect_uri": "iris://oauth/callback/gmail"
},
"mcp_server": {
"module": "servers/gmail/index.js", "binary": "iris-mcp-gmail", "tools": [
"gmail_list_inbox", "gmail_search", "gmail_read_message", "gmail_send", "gmail_reply", "gmail_label", "gmail_delete", "gmail_create_draft"
]
},
"permissions_summary": "Read, send, and organize your Gmail", "enabled_by_default": false
},
{
"id": "outlook",
"name": "Outlook / Microsoft 365", "category": "email",
"icon": "outlook.svg", "auth_type": "oauth2", "oauth": {
"provider": "microsoft", "scopes": [
"Mail.Read",
"Mail.Send", "Mail.ReadWrite"
],
"client_id_env": "MICROSOFT_CLIENT_ID", "redirect_uri": "iris://oauth/callback/outlook"
},
"mcp_server": {
"module": "servers/outlook/index.js", "binary": "iris-mcp-outlook", "tools": [
"outlook_list_inbox", "outlook_search", "outlook_read_message", "outlook_send", "outlook_reply",

"outlook_move", "outlook_delete"
]
},
"permissions_summary": "Read, send, and organize your Outlook mail", "enabled_by_default": false
},
{
"id": "telegram",
"name": "Telegram", "category": "messaging", "icon": "telegram.svg",
"auth_type": "telegram_mtproto", "telegram": {
"api_id_env": "TELEGRAM_API_ID", "api_hash_env": "TELEGRAM_API_HASH", "session_storage": "encrypted_local"
},
"mcp_server": {
"module": "servers/telegram/index.py", "binary": "iris-mcp-telegram", "runtime": "python",
"tools": [ "telegram_list_chats", "telegram_read_chat", "telegram_send_message", "telegram_reply", "telegram_search_messages", "telegram_get_contacts", "telegram_send_file", "telegram_create_group", "telegram_get_chat_members"
]
},
"permissions_summary": "Read and send messages, manage chats and contacts", "enabled_by_default": false
},
{
"id": "discord",
"name": "Discord", "category": "messaging", "icon": "discord.svg", "auth_type": "oauth2", "oauth": {
"provider": "discord", "scopes": [
"bot",

"messages.read", "identify", "guilds"
],
"client_id_env": "DISCORD_CLIENT_ID", "redirect_uri": "iris://oauth/callback/discord"
},
"mcp_server": {
"module": "servers/discord/index.js", "binary": "iris-mcp-discord", "tools": [
"discord_list_servers", "discord_list_channels", "discord_read_channel", "discord_send_message", "discord_reply", "discord_react", "discord_search", "discord_get_members", "discord_create_thread"
]
},
"permissions_summary": "Read and send messages across your Discord servers" "enabled_by_default": false
},
{
"id": "imap_smtp",
"name": "Generic Email (IMAP/SMTP)", "category": "email",
"icon": "email.svg", "auth_type": "credentials", "credentials": {
"fields": [
{ "key": "imap_host", "label": "IMAP Host", "type": "text" },
{ "key": "imap_port", "label": "IMAP Port", "type": "number", "default"
{ "key": "smtp_host", "label": "SMTP Host", "type": "text" },
{ "key": "smtp_port", "label": "SMTP Port", "type": "number", "default"
{ "key": "email", "label": "Email Address", "type": "email" },
{ "key": "password", "label": "Password / App Password", "type": "passw
]
},
"mcp_server": {
"module": "servers/imap/index.js", "binary": "iris-mcp-imap", "tools": [
"email_list_inbox", "email_search",

"email_read", "email_send", "email_reply", "email_move", "email_delete"
]
},
"permissions_summary": "Connect any IMAP/SMTP email account", "enabled_by_default": false
}
]
}




4. Credential Storage
All credentials are encrypted before being written to disk. The CredentialStore is the single component responsible for all encryption and decryption. Nothing else in the codebase touches credentials directly - all reads and writes go through this interface.

4.1 CredentialStore Interface
The interface is fixed and will not change when the encryption backend is upgraded. Implement everything else against this contract:
// src/integrations/CredentialStore.js class CredentialStore {
// Store an encrypted credential for an integration async save(integrationId, credentialPayload) { ... }

// Retrieve and decrypt a credential async load(integrationId) { ... }

// Delete a stored credential (Disconnect & Forget) async wipe(integrationId) { ... }

// Check whether a stored credential exists async exists(integrationId) { ... }

// Internal - get the encryption key for a given integration
// THIS IS THE ONLY METHOD THAT CHANGES IN A FUTURE UPGRADE
async _getEncryptionKey(integrationId) { ... }
}

4.2 Phase 1 Implementation - OS Keychain
In Phase 1, _getEncryptionKey derives its key from the OS-native secure storage. On macOS this is Keychain, on Windows it is DPAPI/Credential Store, on Linux it is libsecret/GNOME Keyring. The platform abstraction library keytar handles all three:

// Phase 1 - _getEncryptionKey using OS keychain async _getEncryptionKey(integrationId) {
const SERVICE = 'iris';
const ACCOUNT = `credential-key-${integrationId}`;

// Try to load an existing key for this integration
let keyHex = await keytar.getPassword(SERVICE, ACCOUNT);

if (!keyHex) {
// First use - generate a random 256-bit key and store it const key = crypto.randomBytes(32);
keyHex = key.toString('hex');
await keytar.setPassword(SERVICE, ACCOUNT, keyHex);
}

return Buffer.from(keyHex, 'hex');
}


Encryption at rest uses AES-256-GCM:

async save(integrationId, credentialPayload) {
const key = await this._getEncryptionKey(integrationId); const iv = crypto.randomBytes(12);
const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);

const plaintext = JSON.stringify(credentialPayload);
const encrypted = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final const tag = cipher.getAuthTag();

const stored = { iv: iv.toString('hex'), tag: tag.toString('hex'), data: encryp await fs.writeFile(this._path(integrationId), JSON.stringify(stored));
}

async load(integrationId) {
const key = await this._getEncryptionKey(integrationId);
const stored = JSON.parse(await fs.readFile(this._path(integrationId), 'utf8'))

const decipher = crypto.createDecipheriv( 'aes-256-gcm',
key,

Buffer.from(stored.iv, 'hex')
);
decipher.setAuthTag(Buffer.from(stored.tag, 'hex'));

const decrypted = Buffer.concat([ decipher.update(Buffer.from(stored.data, 'hex')), decipher.final()
]);
return JSON.parse(decrypted.toString('utf8'));
}

async wipe(integrationId) {
await keytar.deletePassword('iris', `credential-key-${integrationId}`); await fs.unlink(this._path(integrationId));
}

_path(integrationId) {
return path.join(os.homedir(), '.iris', 'credentials', `${integrationId}.enc`);
}


4.3 Credential Payload Structure
The payload stored inside the encrypted envelope is the same regardless of which encryption backend is in use:

{
"integration_id": "gmail", "auth_type": "oauth2", "access_token": "ya29.xxx", "refresh_token": "1//xxx", "expires_at": 1700000000,
"scope": "https://www.googleapis.com/auth/gmail.modify", "created_at": 1699990000,
"revocable": true,
"revoke_url": "https://oauth2.googleapis.com/revoke"
}


4.4 Operational Rules
Never stored in plaintext - encrypted at write, decrypted only when the MCP server process starts
Decrypted credential passed to server via environment variable at spawn time - never written to a temp file

On toggle-off - in-memory credential cleared, server process killed, encrypted file retained unless user selects "Disconnect & Forget"
On app close - all server processes killed, all in-memory credentials cleared immediately


4A. Future Upgrade - Torus Identity Layer
This section is for future reference only. Do not implement during Phase 1.

When the Torus Dilithium identity layer is integrated into Iris, the credential encryption backend upgrades by replacing a single method: _getEncryptionKey . Everything else - the interface, the payload format, the file structure, the lifecycle manager, the MCP servers, the UI - stays identical.

// Future Phase - _getEncryptionKey using Dilithium-derived key
// Replaces the keytar implementation above. Interface unchanged.

async _getEncryptionKey(integrationId) {
// Derive a unique AES key per integration from the Dilithium private key
// using HKDF-SHA256. The Dilithium key is the root of trust for the
// entire Torus identity and wallet system.
const dilithiumPrivateKey = await torusIdentity.getPrivateKey(); return await hkdf(
dilithiumPrivateKey,
`iris/credentials/${integrationId}`, 'sha256',
32
);
}


What changes: one method in CredentialStore.js , the keytar dependency is removed.

What does not change: the CredentialStore interface, the credential payload format, the
.enc file structure, LifecycleManager , all MCP servers, all auth flows, all UI components.

Migration path for existing users: on first launch after the upgrade, the app re-encrypts all existing credentials from the OS keychain key to the Dilithium-derived key automatically.
Users see nothing. No re-authentication required.



5. MCP Server Lifecycle Manager

The Integration Manager is the component responsible for spawning, monitoring, and killing MCP server processes. It is not a user-facing component - it runs in the background and is controlled entirely by toggle state.

State Machine Per Integration

DISABLED --[user toggles ON]--? AUTH_PENDING
¦
[auth flow complete]
¦
?
DISABLED ?--[user toggles OFF]-- RUNNING ?--[restart on crash]-- ERROR
¦	¦
[forget credentials]	[credential expires]
¦	¦
?	?
WIPED	REAUTH_PENDING


Process Management (Node.js / Electron)

// src/integrations/LifecycleManager.js class IntegrationLifecycleManager {
constructor(credentialStore, mcpHost) {
this.processes = new Map();	// integration_id -> ChildProcess this.credentialStore = credentialStore;
this.mcpHost = mcpHost;
}

async enable(integrationId) {
const config = registry.get(integrationId);
const credential = await this.credentialStore.decrypt(integrationId);

// Spawn the MCP server as a child process
const proc = spawn(config.mcp_server.binary, [], { stdio: ['pipe', 'pipe', 'pipe'],
env: {
...process.env,
IRIS_CREDENTIAL: JSON.stringify(credential), // passed via env, cleared IRIS_INTEGRATION_ID: integrationId
}
});

// Register with MCP host so the agent can call its tools

await this.mcpHost.registerServer(integrationId, proc); this.processes.set(integrationId, proc);
proc.on('exit', (code) => {
if (code !== 0) this.handleCrash(integrationId);
});

// Clear credential from env after process is running
// (process has already inherited and consumed it) delete proc.spawnargs;
}

async disable(integrationId, forgetCredentials = false) { const proc = this.processes.get(integrationId);

if (proc) {
await this.mcpHost.deregisterServer(integrationId); proc.kill('SIGTERM'); this.processes.delete(integrationId);
}

if (forgetCredentials) {
await this.credentialStore.wipe(integrationId);
}
}

async handleCrash(integrationId) {
// Attempt restart up to 3 times, then set ERROR state
// Notify UI to show reconnect prompt this.mcpHost.deregisterServer(integrationId); this.emitStateChange(integrationId, 'ERROR');
}
}




6. Auth Flows

6.1 OAuth2 Flow (Gmail, Outlook, Discord)

User toggles ON
¦
?
UI shows permissions summary screen:

"Gmail will be able to: read your inbox, send emails, organize messages. Your credentials never leave your device."
¦
?
User taps "Connect"
¦
?
App opens system browser to provider OAuth URL
(with scopes, client_id, redirect_uri=iris://oauth/callback/gmail)
¦
?
User approves on provider's consent screen
¦
?
Provider redirects to iris://oauth/callback/gmail?code=xxx
¦
?
Iris intercepts deep link, exchanges code for tokens
¦
?
Tokens encrypted and stored to ~/.iris/credentials/gmail.enc
¦
?
Integration status ? RUNNING
MCP server spawned, tools available to agent immediately


6.2 Telegram MTProto Flow

User toggles ON
¦
?
UI shows inline setup (no browser required):
+---------------------------------+

¦Connect Telegram¦¦¦¦Phone number: [+1	]¦¦¦¦[Send Code]¦+---------------------------------+
¦
?
Telegram sends SMS/in-app code
¦
?
+---------------------------------+
¦ Enter code from Telegram:	¦

¦[_ _ _ __]¦¦¦¦[Verify]¦+---------------------------------+
¦
?
Session string generated by Telethon
¦
?
Session encrypted and stored to ~/.iris/credentials/telegram.enc
¦
?
Integration status ? RUNNING
All Telegram tools available to agent


6.3 Credentials Flow (Generic IMAP/SMTP)

User toggles ON
¦
?
UI shows inline form:
+---------------------------------+
¦ Connect Email Account	¦
¦	¦
¦ IMAP Host: [	] ¦
¦ IMAP Port: [993]	¦
¦ SMTP Host: [	] ¦
¦ SMTP Port: [587]	¦
¦ Email:	[	] ¦
¦ Password:	[	] ¦
¦	¦
¦ [Test & Connect]	¦
+---------------------------------+
¦
?
App tests connection
¦
?
Credentials encrypted and stored
¦
?
Integration status ? RUNNING




7. UI Integration Manager

7.1 Integrations Screen Layout

+-----------------------------------------------------+
¦ Integrations	[+ Add New] ¦
+-----------------------------------------------------¦

¦EMAIL¦¦+-----------------------------------------------+¦¦¦ [Gmail icon] Gmail	[?--] ON [?]¦¦¦¦	Connected as user@gmail.com	¦¦¦+-----------------------------------------------+¦¦+-----------------------------------------------+¦¦¦ [Outlook icon] Outlook	[?--] OFF	¦¦¦¦	Tap to connect	¦¦¦+-----------------------------------------------+¦¦+-----------------------------------------------+¦¦¦ [Email icon] Generic Email	[?--] OFF	¦¦¦+-----------------------------------------------+¦¦¦¦MESSAGING¦¦+-----------------------------------------------+¦¦¦ [Tg icon] Telegram	[?--] ON [?]¦¦¦¦	Connected as @username	¦¦¦+-----------------------------------------------+¦¦+-----------------------------------------------+¦¦¦ [Discord icon] Discord	[?--] OFF	¦¦¦+-----------------------------------------------+¦+-----------------------------------------------------+


7.2 Per-Integration Detail View (tap  )

+-----------------------------------------------------+
¦ ? Gmail	¦
+-----------------------------------------------------¦
¦ Status: ? Connected as user@gmail.com	¦
¦ Since:	March 2, 2026	¦
¦	¦
¦ WHAT YOUR AGENT CAN DO	¦
¦ ? Read your inbox and messages	¦
¦ ? Send emails on your behalf	¦
¦ ? Organize, label, and delete messages	¦
¦ ? Create and manage drafts	¦
¦	¦

¦ PERMISSIONS	¦
¦ gmail.readonly gmail.send gmail.modify	¦
¦	¦
¦ [Disconnect]	[Disconnect & Forget]	¦
+-----------------------------------------------------+


Disconnect - stops the server, clears memory, keeps encrypted credential. Re- enabling skips auth.
Disconnect & Forget - stops the server, wipes the encrypted credential file. Re- enabling requires full auth again.


8. Adding New Integrations - The Iris Marketplace
Iris ships with a built-in marketplace that lets users discover, install, and manage MCP servers without ever touching config files or a terminal. The marketplace has two data sources that Iris queries and merges at runtime:
1. The Official MCP Registry - registry.modelcontextprotocol.io - an open-source, community-maintained catalog of thousands of publicly available MCP servers, backed by Anthropic, GitHub, and the broader MCP community. Free to query. No API key required.
2. The Iris Curated List - a hand-vetted subset of the official registry bundled with Iris, covering servers that have been tested for local stdio compatibility and meet Iris's security baseline.
Users in User Mode see the Iris Curated List plus the ability to search the full official registry. Users in Developer Mode get full registry access plus the ability to install from a GitHub URL or a local path directly.


8.1 The Official MCP Registry API
The official MCP Registry is live at registry.modelcontextprotocol.io . It is an open API specification that anyone can implement. It stores metadata about packages - not the package code itself - pointing to npm, PyPI, Docker Hub, or GitHub Releases for the actual installable artifact.
The two endpoints Iris uses:

# Search / list servers

GET https://registry.modelcontextprotocol.io/v0/servers?search=<query>&limit=20

# Get full metadata for a specific server
GET https://registry.modelcontextprotocol.io/v0/servers/<server-name>


Example search response from the live API:


{
"servers": [
{
"server": {
"name": "io.github.somedev/slack-mcp",
"description": "Full Slack integration - read channels, send messages, ma "repository": {
"url": "https://github.com/somedev/slack-mcp", "source": "github"
},
"version": "1.2.0", "packages": [
{
"registryType": "npm", "identifier": "slack-mcp-server", "version": "1.2.0",
"transport": { "type": "stdio" }
}
]
},
"_meta": { "io.modelcontextprotocol.registry/official": {
"status": "active",
"publishedAt": "2025-10-01T00:00:00Z",
"isLatest": true
}
}
}
],
"metadata": {
"nextCursor": "eyJpZCI6MTAwfQ=="
}
}


Iris reads the packages array to know how to install the server ( npm install , pip install , or direct binary download) and what transport type it uses. Only servers with
 "transport": { "type": "stdio" } are shown in User Mode - remote/SSE servers require Developer Mode.



8.2 Iris Marketplace - User Mode Flow
In User Mode, the user never sees raw JSON, never runs a command, and never configures a path. The entire flow is:

User opens Integrations screen
¦
?
Taps [+ Add New]
¦
?
+-----------------------------------------------------+
¦ Add Integration	[ Search] ¦
+-----------------------------------------------------¦

¦FEATURED¦¦+----------------------+ +----------------------+¦¦¦  Slack	¦ ¦  Notion	¦¦¦¦ Messaging & channels ¦ ¦ Notes & databases	¦¦¦¦ [+ Install]	¦ ¦ [+ Install]	¦¦¦+----------------------+ +----------------------+¦¦¦¦PRODUCTIVITY¦¦+----------------------+ +----------------------+¦¦¦  Google Calendar	¦ ¦  Linear	¦¦¦¦ Events & scheduling ¦ ¦ Issues & projects	¦¦¦¦ [+ Install]	¦ ¦ [+ Install]	¦¦¦+----------------------+ +----------------------+¦¦¦¦[Browse all 200+ integrations ?]¦+-----------------------------------------------------+
¦
User taps [+ Install] on a server
¦
?
+-----------------------------------------------------+
¦ Install Slack	¦
+-----------------------------------------------------¦
¦ Source:	Official MCP Registry ?	¦
¦ Package: slack-mcp-server v1.2.0 (npm)	¦
¦ Size:	~2.4 MB	¦
¦	¦
¦ WHAT THIS WILL BE ABLE TO DO	¦
¦ • Read your Slack messages and channels	¦
¦ • Send messages on your behalf	¦
¦ • Search message history	¦

¦ • Manage channel memberships	¦
¦	¦
¦ ? Community server - not bundled with Iris	¦
¦	Installed locally. Your data stays on device.	¦
¦	¦
¦ [Cancel]	[Install & Connect]	¦
+-----------------------------------------------------+
¦
User taps [Install & Connect]
¦
?
Iris runs install command silently in background (npm install -g slack-mcp-server)
¦
?
Registry entry auto-generated and appended to
~/.iris/user-registry.json
¦
?
Auth flow launches immediately (OAuth, key, etc.)
¦
?
Server appears in Integrations list - status: RUNNING


The user tapped one button. The rest was invisible.



8.3 How Installed Servers Are Stored
Official bundled servers live in integrations/registry.json (shipped with Iris, read-only). User-installed servers are appended to a separate writable file that Iris creates on first use:

~/.iris/user-registry.json


The format is identical to registry.json , with one additional field indicating the source:


{
"integrations": [
{
"id": "slack",
"name": "Slack", "category": "messaging", "source": "mcp-registry",
"registry_name": "io.github.somedev/slack-mcp", "version": "1.2.0",

"installed_at": "2026-03-02T10:00:00Z", "auth_type": "oauth2",
"oauth": {
"provider": "slack",
"scopes": ["channels:read", "chat:write", "users:read"], "client_id_env": "SLACK_CLIENT_ID",
"redirect_uri": "iris://oauth/callback/slack"
},
"mcp_server": {
"binary": "slack-mcp-server",
"install_command": "npm install -g slack-mcp-server", "transport": "stdio",
"tools": []
},
"permissions_summary": "Read and send Slack messages", "enabled_by_default": false
}
]
}


At startup, Iris loads both registry.json and user-registry.json and merges them. The UI shows a unified list. The LifecycleManager treats entries from both files identically - same spawn logic, same credential storage, same toggle behavior.


8.4 Removing a User-Installed Server

User opens integration detail (?)
¦
?
Taps [Remove Integration]
¦
?
Confirmation: "This will disconnect Slack, delete its credentials, and uninstall the server package."
¦
User confirms
¦
?
1. Server process killed
2. Credential wiped from CredentialStore
3. npm uninstall -g slack-mcp-server (background)
4. Entry removed from user-registry.json
5. Card disappears from Integrations screen



8.5 Official Updates (Bundled Servers)
Servers bundled with Iris ( registry.json ) update when Iris updates. No separate action needed. If an installed community server has a newer version available in the MCP Registry, Iris shows an "Update available" badge on the integration card and handles the npm install -g slack-mcp-server@latest silently when the user taps Update.


8.6 Developer Mode Extensions
Developer Mode users get two additional install paths not available in User Mode. These are out of scope for this spec but the architecture supports them via the same user- registry.json file:

GitHub URL install - paste a GitHub repo URL, Iris clones and builds it locally

Local path - point to a directory on disk containing a valid MCP server

Both result in the same registry entry format and are managed identically by the LifecycleManager. The only difference is "source": "github" or "source": "local" in the registry entry.


9. Agent Tool Access
Once an integration is running, its tools are available to the agent automatically - no additional configuration. The agent calls tools using standard MCP tool calls:

Agent reasoning:
"The user wants to send an email. Gmail is connected. I will call gmail_send."

Tool call:
{
"tool": "gmail_send", "arguments": {
"to": "recipient@example.com", "subject": "Follow-up",
"body": "Hi, following up on our conversation..."
}
}

MCP host routes call ? Gmail MCP server process ? Google API ? response

The agent never handles raw credentials. It only calls named tools. The MCP server process holds the token and makes the actual API call. This isolation means even if the agent is manipulated into attempting something it shouldn't, it cannot extract the user's credentials
- it can only call the tools it has been given.



10. Security Model

ConcernMitigation
Credential theftEncrypted at rest using AES-256-GCM with OS keychain-derived key (Phase 1). Decrypted only at server spawn time, never written to disk unencrypted. Upgradeable to Torus identity-derived key via Section 4A.Agent credential access
Agent calls tools only. MCP server holds credentials. Agent never sees raw tokens.Rogue MCP serverCommunity integrations require explicit user install approval. Official integrations are signed and bundled.Token leakage on crash
Process exit handler clears in-memory credentials. OS process isolation prevents cross-process access.Unauthorized tool callsPermission summary shown at connect time. Agent operates within approved scopes only. Users can disconnect at any time.Network exposureAll MCP servers run over stdio, not network ports. No integration server is reachable from outside the local process.


11. File Structure

iris/
+-- integrations/
¦	+-- registry.json	# Bundled official integrations (read-only, sh
¦	+-- LifecycleManager.js	# Process spawn/kill/monitor

¦+--CredentialStore.js#OS keychain encryption (Phase 1) - see Secti¦+--AuthFlowManager.js#OAuth2, Telegram MTProto, credentials flows¦+--MarketplaceClient.js#Queries registry.modelcontextprotocol.io API¦+--InstallerService.js#Runs npm/pip install, manages user-registry.
¦+-- RegistryLoader.js#Merges registry.json + ~/.iris/user-registry¦+--servers/#Bundled MCP server implementations (official¦+-- gmail/¦¦	+-- index.js¦+-- outlook/¦¦	+-- index.js¦+-- telegram/¦¦	+-- index.py#Python/Telethon¦+-- discord/¦¦	+-- index.js¦+-- imap/¦+-- index.js¦+--ui/¦+-- IntegrationsScreen.jsx#Unified list (bundled + user-installed) with¦+-- IntegrationDetail.jsx#Per-integration detail, disconnect, remove,¦+-- AuthFlowModal.jsx#OAuth browser, Telegram code entry, IMAP for¦+-- MarketplaceScreen.jsx#Browse/search MCP registry, featured + categ¦+-- InstallConfirmModal.jsx#Permissions summary + install confirmation¦+--mcp/+-- Host.js#MCP host - routes tool calls to correct serv



12. Implementation Sequence
Implement in this order to ship a working integration layer incrementally:

1. CredentialStore - OS keychain key derivation, AES-256-GCM encrypt/decrypt/wipe (interface matches Section 4A for future upgrade)
2. RegistryLoader - load and merge registry.json + ~/.iris/user-registry.json at startup
3. IntegrationsScreen UI - unified list, toggle, status display (no auth yet, just UI)

4. OAuth2 flow - deep link handling, token exchange, store to CredentialStore

5. Gmail MCP server - first end-to-end integration, validates full stack

6. LifecycleManager - process spawn/kill wired to toggle state

7. MCP Host - route tool calls from agent to correct server process

8. Outlook MCP server - second integration, validates OAuth reuse

9. Telegram auth flow + MCP server - validates non-OAuth path

10. Discord MCP server - validates bot OAuth path

11. IMAP/SMTP MCP server - validates credentials path

12. Integration detail view - disconnect, disconnect & forget, status, permissions

13. MarketplaceClient - query registry.modelcontextprotocol.io/v0/servers , search, pagination
14. MarketplaceScreen UI - featured grid, categories, search results, install button

15. InstallConfirmModal - permissions summary, source badge, install confirmation

16. InstallerService - run npm install -g / pip install in background, write to user- registry.json , trigger auth flow on completion
17. Update detection - compare installed version against registry on startup, show update badge
18. Remove integration - uninstall package, wipe credential, remove from user- registry.json
19. Crash recovery and reconnect UI

20. Developer Mode paths (GitHub URL + local path installs) - out of scope for Phase 1



End of Spec - Iris Integration Layer v1.2
