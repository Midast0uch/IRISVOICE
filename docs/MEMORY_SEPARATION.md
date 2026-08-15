# IRIS Launcher ↔ Widget: Memory Bloat Diagnosis & Process Separation Spec

## Problem Summary

The IRIS system currently runs two separate frontend applications — the **IRIS Launcher** (Vite) and the **IRIS Widget** (Next.js + webpack) — where the Launcher spawns the Widget as a child process. This parent-child process relationship is the primary cause of memory bloat during development and is an architectural anti-pattern that should be eliminated entirely.

-----

## Root Cause Analysis

### 1. Dual Module Graph Accumulation

Both Vite and webpack maintain a full in-memory module graph of every imported file. When running simultaneously:

- **Vite (Launcher)** — builds and holds its own module graph, HMR websocket server, and chokidar file watcher
- **webpack (Widget)** — builds and holds a separate, larger module graph (webpack’s JS-based graph is significantly heavier than Vite’s native ESM approach), its own HMR overlay, and its own chokidar watcher

These two graphs are independent and non-overlapping from a GC perspective, meaning both are fully resident in memory at all times.

### 2. Child Process Memory Inheritance

When the Launcher spawns the Widget via `child_process.spawn()` or similar, the Widget’s Node process **forks from the Launcher’s runtime context**. At fork time, the OS uses copy-on-write semantics, but:

- The IPC channel between parent and child stays open, keeping references alive on both sides
- Node’s garbage collector does not aggressively collect while active IPC handles exist
- Any event listeners or callbacks registered across the IPC boundary prevent GC on both sides

This means the two processes are not memory-isolated — they share reference pressure even though they appear as separate PIDs.

### 3. Overlapping File Watchers

Both chokidar instances will watch overlapping directories (shared `src/`, `components/`, `lib/` folders, and potentially `node_modules`). This causes:

- Duplicate `inotify` handles consuming kernel resources
- Duplicate HMR invalidation events when files change
- Both processes attempting to recompile on every save

### 4. webpack Heap Retention (Widget-Specific)

webpack stores its entire module graph as a JavaScript object tree in the V8 heap. Unlike Turbopack (Rust-based, heap lives outside V8) or Vite (native ESM, no compilation graph), webpack’s graph grows with every incremental build and never fully releases stale module entries during a dev session. Switching from Turbopack back to webpack made this significantly worse.

### 5. Source Maps in Dev Mode

Both processes generate full inline source maps in dev mode. For a project of IRIS’s complexity, this alone can account for 200–500MB of heap per process, and both processes hold their own copy.

-----

## What the Launcher Actually Does

The Launcher is a **point-in-time session bootstrapper**, not a runtime supervisor. Its responsibilities are:

|Responsibility                               |Timing          |
|---------------------------------------------|----------------|
|GitHub OAuth (branch/repo management)        |At startup, once|
|Tailscale connection handshake               |At startup, once|
|Biometric unlock → derive session key        |At startup, once|
|Write encrypted session token to secure store|At startup, once|
|Signal Widget to start                       |Fire-and-forget |

None of these require the Launcher to remain alive or maintain a process relationship with the Widget after handoff. The Launcher’s job ends the moment the session key is in the secure store.

-----

## Required Architecture Change

### Current (Broken)

```
IRIS Launcher (Vite)
  └── spawns → IRIS Widget (Next.js/webpack) [child process]
                    ↑
              IPC channel stays open
              Shared GC pressure
              Overlapping watchers
              Dual module graphs in memory
```

### Target (Correct)

```
IRIS Launcher (Vite)
  → GitHub OAuth          [completes]
  → Tailscale handshake   [completes]
  → Biometric unlock      [completes]
  → Write session token → [OS Keychain / Tauri secure store]
  → Emit start signal     [fire and forget — Tauri event or local socket]
  → EXIT or MINIMIZE      [Launcher is done]

IRIS Widget (Next.js)     [completely independent process]
  → Starts independently
  → Reads session token from secure store
  → Decrypts with derived key
  → Runs with no parent, no IPC, no shared memory
```

The Widget must be **launchable without the Launcher running**. The Launcher must be **closeable without affecting the Widget**.

-----

## Implementation Steps

### Step 1 — Remove Child Process Spawn

Locate wherever the Launcher calls `spawn()`, `exec()`, `fork()`, or Tauri’s `Command::new()` to start the Widget. Remove it. The Widget will start via an independent mechanism.

### Step 2 — Establish Secure Session Handoff

Use Tauri’s secure store (keytar under the hood, backed by OS keychain) to pass the session token:

```typescript
// Launcher — after biometric unlock and key derivation
import { invoke } from '@tauri-apps/api/core'

await invoke('store_session_token', {
  token: encryptedSessionToken,
  ttl: 3600 // seconds
})
```

```typescript
// Widget — on init, before rendering authenticated content
import { invoke } from '@tauri-apps/api/core'

const token = await invoke('read_session_token')
if (!token) {
  // Redirect to Launcher or show locked state
}
```

The session token should never travel over IPC, env vars, or query strings. OS keychain only.

### Step 3 — Decouple Process Startup

Instead of the Launcher spawning the Widget, use one of:

**Option A — Tauri Shell Plugin (recommended for Tauri v2):**

```rust
// In Launcher's Tauri backend — fire and forget, no handle retained
tauri::async_runtime::spawn(async {
  Command::new("iris-widget")
    .spawn()
    .expect("failed to start widget");
  // Drop the handle immediately — no monitoring
});
```

**Option B — OS-level startup:**
Register the Widget as a separate Tauri application that can be launched via deep link or protocol handler, completely independent of the Launcher process.

**Option C — Development only:**
Run both as independent terminal processes. No programmatic relationship at all during dev:

```bash
# Terminal 1
cd iris-launcher && npm run dev

# Terminal 2  
cd iris-widget && npm run dev
```

### Step 4 — Scope File Watchers

Add explicit ignore rules to both dev configs to prevent overlapping watch:

```javascript
// iris-launcher/vite.config.ts
export default {
  server: {
    watch: {
      ignored: [
        '**/node_modules/**',
        '**/.git/**',
        '../iris-widget/**'  // explicitly exclude Widget directory
      ]
    }
  }
}
```

```javascript
// iris-widget/next.config.js
module.exports = {
  webpack: (config) => {
    config.watchOptions = {
      ignored: [
        '**/node_modules/**',
        '**/.git/**',
        '../iris-launcher/**'  // explicitly exclude Launcher directory
      ]
    }
    return config
  }
}
```

### Step 5 — Suppress Dev Source Maps (Optional but High Impact)

```javascript
// iris-widget/next.config.js
module.exports = {
  productionBrowserSourceMaps: false,
  webpack: (config, { dev }) => {
    if (dev) {
      config.devtool = 'eval'  // fastest, minimal memory — trade: less readable stack traces
      // alternatives: 'eval-cheap-source-map' for slightly better traces
    }
    return config
  }
}
```

-----

## Expected Outcome

|Metric                   |Before                                  |After                                 |
|-------------------------|----------------------------------------|--------------------------------------|
|Node processes in memory |2 (parent-child, shared GC pressure)    |2 (fully independent, isolated GC)    |
|File watcher handles     |Overlapping (2x coverage of shared dirs)|Scoped (each watches only its own dir)|
|IPC overhead             |Active channel, prevents aggressive GC  |None                                  |
|Session key surface area |IPC / env vars / spawn args             |OS keychain only                      |
|Launcher lifecycle       |Must stay alive while Widget runs       |Can exit after handoff                |
|Widget startup dependency|Requires Launcher process               |None — fully independent              |

-----

## Definition of Done

- [ ] Launcher does not call `spawn`, `exec`, `fork`, or any Tauri `Command` to start the Widget
- [ ] Widget starts and runs with Launcher fully closed
- [ ] Session token passes exclusively through OS keychain / Tauri secure store
- [ ] Each app’s `vite.config` / `next.config` explicitly ignores the other app’s directory
- [ ] No IPC channel exists between Launcher and Widget at runtime
- [ ] Memory usage of each process drops to its own baseline with no cross-process accumulation