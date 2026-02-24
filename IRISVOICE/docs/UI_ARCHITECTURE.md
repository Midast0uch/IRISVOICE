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


## Navigation System Architecture (Feb 23, 2026) - CRITICAL

### Overview

The IRISVOICE navigation system is a 4-level hierarchical interface where nodes orbit around a central IRIS orb. This is the core UI interaction pattern and must remain stable across all future implementations.

### Navigation Levels

```
Level 1: Idle IRIS Orb (collapsed state)
   ↓ Click orb
Level 2: 6 Main Category Nodes (hexagonal orbit)
   ↓ Click category
Level 3: 4 Sub-nodes per category (orbital display)
   ↓ Click sub-node
Level 4: Mini-node stack or wheel view (settings interface)
```

### Core Components

| Component | Location | Purpose |
|-----------|----------|---------|
| NavigationContext | `contexts/NavigationContext.tsx` | State management, WebSocket integration |
| HexagonalControlCenter | `components/hexagonal-control-center.tsx` | Renders nodes at levels 2 & 3 |
| PrismNode (HexagonalNode) | `components/iris/prism-node.tsx` | Individual node rendering & animation |
| Level4View | `components/level-4-view.tsx` | Settings interface at level 4 |
| IrisOrb | `components/iris/IrisOrb.tsx` | Central orb component |

### State Management

**NavState Structure:**
```typescript
{
  level: 1 | 2 | 3 | 4,           // Current navigation level
  selectedMain: string | null,      // Selected category (e.g., "VOICE")
  selectedSub: string | null,       // Selected sub-node (e.g., "INPUT")
  history: HistoryEntry[],          // Navigation history for back button
  transitionDirection: 'forward' | 'backward' | null,
  isTransitioning: boolean,
  miniNodeStack: MiniNode[],        // Level 4 settings
  // ... other state
}
```

**CRITICAL STATE RULES:**

1. **Level 2 → Level 3**: `selectedMain` MUST be set and preserved
2. **Level 3 → Level 2 (backward)**: `selectedMain` MUST remain set (shows which category was selected)
3. **Level 2 → Level 1 (backward)**: Clear all selections
4. **Level 4 → Level 3 (backward)**: Keep `selectedMain` and `selectedSub`, clear mini node stack

### Navigation Actions

| Action | Trigger | State Change |
|--------|---------|--------------|
| `EXPAND_TO_MAIN` | Click IRIS orb at level 1 | level: 1 → 2 |
| `SELECT_MAIN` | Click category node | level: 2 → 3, set selectedMain |
| `SELECT_SUB` | Click sub-node | level: 3 → 4, set selectedSub |
| `GO_BACK` | Click IRIS orb at level > 1 | level: n → n-1, preserve context |
| `COLLAPSE_TO_IDLE` | (Not used for orb clicks) | level: n → 1, clear all |

### Node Rendering Logic

**File:** `components/hexagonal-control-center.tsx`

```typescript
// Level 2: Show 6 main category nodes
if (nav.state.level === 2) {
  return MAIN_NODES.map((node, index) => ({
    ...node,
    angle: MAIN_NODE_ANGLES[index],
    isActive: nav.state.selectedMain === node.id
  }))
}

// Level 3: Show 4 sub-nodes for selected category
else if (nav.state.level === 3 && nav.state.selectedMain) {
  // CRITICAL: Fallback to hardcoded SUB_NODES if WebSocket unavailable
  const subNodes = (nav.subnodes[nav.state.selectedMain]?.length > 0) 
    ? nav.subnodes[nav.state.selectedMain] 
    : (SUB_NODES[nav.state.selectedMain] || [])
  return subNodes.map((node, index) => ({
    ...node,
    angle: SUB_NODE_ANGLES[index],
    isActive: nav.state.selectedSub === node.id
  }))
}
```

### Animation System

**CRITICAL ANIMATION RULE:**
Nodes should ALWAYS animate to their expanded (orbital) positions when rendered, regardless of navigation direction.

```typescript
// CORRECT: Nodes always expand into orbit
<HexagonalNode
  isCollapsing={false}  // ✅ Always false - AnimatePresence handles exit
  // ... other props
/>

// WRONG: Don't use transitionDirection for isCollapsing
<HexagonalNode
  isCollapsing={nav.state.transitionDirection === 'backward'}  // ❌ Breaks backward nav
/>
```

**Why:** AnimatePresence automatically handles exit animations when components unmount. Setting `isCollapsing` based on direction causes nodes to animate to center instead of orbit.

### WebSocket Integration

**Fallback Pattern (CRITICAL):**
```typescript
// Always provide fallback data when WebSocket is unavailable
const subNodes = (nav.subnodes[selectedMain]?.length > 0) 
  ? nav.subnodes[selectedMain]           // Use WebSocket data if available
  : (SUB_NODES[selectedMain] || [])      // Fallback to hardcoded data
```

**Why:** Backend may be offline during development. UI must remain functional with hardcoded fallback data.

### Common Bugs & Fixes (Feb 23, 2026)

#### Bug 1: Nodes Don't Appear at Level 3
**Cause:** Missing fallback to hardcoded SUB_NODES when WebSocket unavailable  
**Fix:** Added fallback logic in HexagonalControlCenter (line 107-109)  
**Test:** `tests/bug-condition-navigation-level3.test.js`

#### Bug 2: Backward Navigation Skips Level 2
**Cause:** `handleIrisClick` called `handleCollapseToIdle()` instead of `handleGoBack()`  
**Fix:** Changed NavigationContext.tsx line 505 to use `handleGoBack()`  
**Impact:** Now navigates 4→3→2→1 instead of jumping to 1

#### Bug 3: Nodes Don't Orbit When Going Backward
**Cause:** `isCollapsing={transitionDirection === 'backward'}` made nodes animate to exit state  
**Fix:** Changed to `isCollapsing={false}` in HexagonalControlCenter line 147  
**Impact:** Nodes now properly orbit when navigating backward

#### Bug 4: selectedMain Cleared When Going Back to Level 2
**Cause:** GO_BACK reducer cleared selectedMain at level 2  
**Fix:** Removed line that cleared selectedMain in NavigationContext.tsx (line 95-100)  
**Impact:** Category remains highlighted when returning to level 2

#### Bug 5: React Reuses Component Between Levels
**Cause:** Same LazyHexagonalControlCenter used for levels 2 & 3 without key prop  
**Fix:** Added `key="level-2"` and `key="level-3"` in page.tsx  
**Impact:** Forces proper re-render when transitioning between levels

### Customization Points (Safe to Modify)

✅ **Safe to customize:**
- Node visual design (colors, glass effects, borders)
- Animation timing and easing functions
- Node icons and labels
- Orbital radius and positioning angles
- Transition effects and styles

❌ **DO NOT modify without careful testing:**
- State management logic in NavigationContext reducer
- `currentNodes` useMemo logic in HexagonalControlCenter
- `isCollapsing` prop value (must always be `false`)
- Fallback data pattern for WebSocket
- Key props on LazyHexagonalControlCenter
- GO_BACK reducer logic for preserving selectedMain

### Testing

**Bug Condition Tests:**
```bash
npm run test:navigation  # Tests level 3 node rendering with offline backend
```

**Preservation Tests:**
```bash
npm run test:navigation:preservation  # Verifies levels 1 & 2 still work
```

### Future-Proofing Guidelines

When making changes to the navigation system:

1. **Always test with backend offline** - Fallback data must work
2. **Test backward navigation** - All levels must render correctly going backward
3. **Verify selectedMain preservation** - Category should stay highlighted at level 2
4. **Check AnimatePresence behavior** - Nodes should always expand into orbit
5. **Add tests for new features** - Follow property-based testing pattern

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    NavigationContext                        │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │   NavState   │  │  WebSocket   │  │  Action         │   │
│  │   Reducer    │←→│  Integration │←→│  Handlers       │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
└────────────┬────────────────────────────────────────────────┘
             │
             ↓ Provides state & actions
┌─────────────────────────────────────────────────────────────┐
│                    page.tsx (Main App)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │   IrisOrb    │  │ Hexagonal    │  │  Level4View     │   │
│  │  (Level 1)   │  │ Control      │  │  (Level 4)      │   │
│  │              │  │ (Levels 2&3) │  │                 │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
└─────────────────────────────────────────────────────────────┘
             │
             ↓ Renders nodes
┌─────────────────────────────────────────────────────────────┐
│              PrismNode (HexagonalNode)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │  Animation   │  │  Glass       │  │  Orbital        │   │
│  │  Variants    │  │  Effects     │  │  Positioning    │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Key Takeaways

1. **Navigation is state-driven** - All UI changes flow from NavState
2. **Fallback data is mandatory** - UI must work without backend
3. **Backward navigation preserves context** - Don't clear state prematurely
4. **Animations are declarative** - Let AnimatePresence handle exits
5. **Test with backend offline** - Most bugs appear in this scenario
