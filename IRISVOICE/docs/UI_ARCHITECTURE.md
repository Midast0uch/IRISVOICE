# IRISVOICE UI Architecture Reference

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Desktop Widget                           │
│                    (iris-widget.exe - Rust)                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    Tauri WebView                          │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │              Next.js Frontend (React)               │  │  │
│  │  │   ┌─────────┐  ┌─────────┐  ┌─────────────────┐    │  │  │
│  │  │   │Dashboard│  │ Menu    │  │ Chat View      │    │  │  │
│  │  │   │  Page   │  │ Window  │  │ (WebSocket)    │    │  │  │
│  │  │   └─────────┘  └─────────┘  └─────────────────┘    │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ WebSocket
┌─────────────────────────────────────────────────────────────────┐
│                   Python Backend (start-backend.py)             │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐     │
│   │ LLM (LFM2)  │  │  Audio       │  │  Agent System   │     │
│   │ Model       │  │  Processing  │  │  (Tools/MCP)    │     │
│   └──────────────┘  └──────────────┘  └──────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

## Development Commands

| Command | Use Case | Time to Start |
|---------|----------|---------------|
| `npm run dev` | UI/frontend only, no widget | ~1 second |
| `npm run dev:tauri` | Same as above (alias) | ~1 second |
| `npm run dev:tauri:nowatch` | Full widget + frontend, no file watcher | ~3 seconds |
| `npm run dev:backend` | Python backend only (AI models) | ~30 seconds |
| `npx tauri dev` | Full Tauri with file watcher (may trigger rebuilds) | ~3 seconds |

### Recommended Workflows

**Frontend-only development:**
```bash
npm run dev
```

**Full stack testing (2 terminals):**
```bash
# Terminal 1 - Backend
npm run dev:backend

# Terminal 2 - Frontend + Widget
npm run dev:tauri:nowatch
```

## Component Architecture

### Frontend (Next.js + React)
- **Location:** `IRISVOICE/app/`
- **Build:** Turbopack (fast bundler)
- **Styling:** Tailwind CSS v4
- **State:** React Context (BrandColor, Navigation, Transition)

### Desktop Widget (Tauri/Rust)
- **Location:** `IRISVOICE/src-tauri/`
- **Output:** `iris-widget.exe`
- **Purpose:** Desktop window, system tray, native features

### Backend (Python)
- **Location:** `IRISVOICE/backend/`
- **Entry:** `start-backend.py`
- **Models:** LFM2-8B-A1B (LLM), audio processing

## Performance Optimizations

### 1. Incremental Rust Compilation
**File:** `IRISVOICE/src-tauri/.cargo/config.toml`
```toml
[build]
incremental = true
[profile.dev]
incremental = true
```
**Result:** Rust recompiles in ~1-2 seconds (vs 20+ minutes)

### 2. Turbopack (Next.js)
- Enabled by default in Next.js 16
- Fast hot reload
- Filesystem cache for faster subsequent builds

### 3. No-Watch Mode
Use `--no-watch` to prevent Tauri from watching files and triggering rebuilds:
```bash
npm run dev:tauri:nowatch
```

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| 26+ min cache write | Turbopack bug on Windows | Delete `.next/` folder |
| CommonJS/ESM errors | `"type": "commonjs"` in package.json | Change to `"type": "module"` |
| PC freeze during build | Duplicate filesystem cache writes | Use `--no-watch` flag |
| Rust recompiling every time | Incremental disabled | Enable in `.cargo/config.toml` |
| Port 3000 in use | Another Next.js instance running | Kill node processes |

## Key Files

| File | Purpose |
|------|---------|
| `package.json` | NPM config, scripts, dependencies |
| `next.config.mjs` | Next.js/Turbopack configuration |
| `src-tauri/tauri.conf.json` | Tauri widget configuration |
| `src-tauri/.cargo/config.toml` | Rust build settings |
| `backend/main.py` | Python backend entry point |
| `hooks/useIRISWebSocket.ts` | Frontend-backend communication |

## Package.json Type Setting

**IMPORTANT:** Always use `"type": "module"` in package.json

This is required because:
- React/Next.js uses ESM (`import/export`)
- CommonJS (`require/module.exports`) causes format conflicts
- Turbopack will fail with CommonJS errors

---

## Future Simplification (Post-UI Stabilization)

> **Note:** Once the widget UI is finalized, these commands should be simplified for ease of use. Current setup is optimized for development but prone to user error.

### Issues to Address:
1. Multiple cache folders (`.next/`, `dist/`, `tauri-build/`)
2. Multiple build commands with confusing names
3. Need to close widget before rebuild
4. Locked exe file issues on Windows

### Proposed Simplified Flow:
- Single `npm run dev` command that handles everything
- Auto-clean caches when needed
- Graceful handling of locked files
- Clear error messages for common issues

### For Agent Code Editing:
The current process requires manual intervention when:
- Cache becomes corrupted
- Exe file is locked
- Module format conflicts occur

**Recommendation:** Create wrapper scripts that automate these fixes.


## Tauri Dev Freeze Fix (Feb 2026)

Root Causes:
- Rust compile cache + Windows Defender conflict
- Tauri watcher detects 8GB model files

Fixes Applied:
1. Rust target moved to C:\temp\tauri-target
2. Watcher ignores models/, .next/, dist/, node_modules/

Expected: No more 20+ min freezes


## Rust-Analyzer Disable (Feb 2026)

Root Cause:
- rust-analyzer runs cargo check constantly, conflicts with Tauri dev builds

Fixes:
1. Created .vscode/settings.json - disables rust-analyzer for workspace
2. Created src-tauri/rust-analyzer.json - backup config

Alternative: Press Ctrl+Shift+P and type 'disable' to find 'rust-analyzer: Disable Server'


## Tauri Version Mismatch Fix (Feb 23, 2026)

**Problem:**
- Error: "Found version mismatched Tauri packages. Make sure the NPM package and Rust crate versions are on the same major/minor releases: tauri (v2.9.5) : @tauri-apps/api (v2.10.1)"
- Error: "failed to select a version for the requirement `tauri-plugin-shell = "^2.9"`"
- Cargo.toml specified non-existent versions (2.9.x)

**Root Cause:**
- Cargo.toml had `tauri = "2.9"`, `tauri-build = "2.9"`, `tauri-plugin-shell = "2.9"`
- These specific versions don't exist on crates.io (latest is 2.3.5 for plugin)
- NPM packages were on v2.10.x, creating version mismatch

**Fix Applied:**
1. Updated Cargo.toml to use version "2" (gets latest 2.x compatible)
   - `tauri-build = { version = "2", features = [] }`
   - `tauri = { version = "2", features = ["tray-icon"] }`
   - `tauri-plugin-shell = "2"`

2. Updated package.json to compatible versions:
   - `@tauri-apps/api: "^2.0.0"`
   - `@tauri-apps/cli: "^2.0.0"`

3. Cleaned and reinstalled dependencies:
   - Deleted Cargo.lock and ran `cargo update`
   - Ran `npm install` to update node_modules

**Results:**
- NPM: @tauri-apps/api@2.0.0, @tauri-apps/cli@2.0.0
- Cargo: tauri 2.10.2, tauri-build 2.5.5, tauri-plugin-shell 2.3.5
- All version mismatch errors resolved
- Tauri dev now starts without version conflicts

**Prevention:**
Always use major version specifiers (e.g., "2") in Cargo.toml rather than specific minor versions that may not exist.


## Webpack Memory Spike Fix (Feb 23, 2026) - CRITICAL

**Problem:**
- Frontend dev mode caused 7000+ MB memory spike and 16-minute freeze
- Next.js webpack was processing 18+ GB of AI model files during compilation
- Models are only used by Python backend, not frontend

**Root Cause:**
- Webpack file watching included models/ directory by default
- Webpack asset processing scanned large .bin and .safetensors files
- No explicit exclusions in next.config.mjs

**Fix Applied:**
File: `IRISVOICE/next.config.mjs`
```javascript
webpack: (config, { isServer }) => {
  config.watchOptions = {
    ...config.watchOptions,
    ignored: ['**/models/**', '**/node_modules/**', '**/.git/**', '**/.next/**']
  };
  
  config.module.rules.push({
    test: /\.(bin|safetensors)$/,
    type: 'javascript/auto',
    exclude: /models\//,
  });
  
  return config;
}
```

**Results:**
- Compilation: 163s → 2.5s (98.5% faster)
- Memory: 7000+ MB → 5 MB (99.9% reduction)
- No more freezes

**CRITICAL - Prevention:**
NEVER remove the webpack exclusions from next.config.mjs. The memory spike will return immediately if these lines are deleted.

**Testing:**
- `npm run test` - Runs bug condition test
- `npm run test:preservation` - Verifies backend still works
