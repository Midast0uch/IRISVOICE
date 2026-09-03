# IRIS Whiteboard V2 — Pan/Zoom Artifact Surface Plan

A pan/zoom whiteboard surface where any artifact (web page, image, document, calendar, chart, diagram, 3D model, or sketch) appears as a glass tile arranged in a bento grid or popped out into floating panels. Features an element inspector for same-origin previews, a freeform drawing layer, VL screenshot optimizer, an expanded agent shortcut registry, and an auto-research agent skill for hands-free navigation testing.

---

## What's New in V2

- **Element Inspector** — hover-to-highlight DOM tree on same-origin tiles (localhost, artifact sandbox, html tiles); click a highlighted container to attach a comment with a CSS selector reference the AI can understand.
- **VL Screenshot Optimizer** — model-specific screenshot pipelines that resize, compress, and format captures based on the active vision model's token economics (e.g. Gemini wants 1024x1024, GPT-4o is fine with 1536x any, Claude 3.7 wants under 1568px on the long edge).
- **Expanded Shortcut Registry** — 25+ shortcuts covering zoom, pan, tile operations, focus mode, draw tools, inspector mode, and screenshot. Designed so an agent can "reach" every UI element without a mouse.
- **Collapsible Shelf + Tab Bar** — artifact shelf and tab bar collapse into compact icon-only strips (32px wide) with a hover-expand preview, preserving screen real estate.
- **Xur Loading Overlay** — the existing `Xur.tsx` particle-spiral canvas is reused as a size-adjustable loading overlay for all artifact types.
- **Three.js 3D Viewer Tile** — interactive GLTF/GLB/OBJ rendering with orbit controls inside a tile, for Blender exports and CAD designs.
- **Freeform Drawing Layer** — a full-canvas paint layer on top of the whiteboard plus per-tile sketch overlays; sketches can be saved as new image artifacts.
- **Open Design Gaps Closed** — artifact lint API, template persistence per project, skills-as-files (`SKILL.md` + `DESIGN.md`), and a sidecar-inspired desktop automation protocol for agent screenshot/click/eval.
- **Agent Whiteboard Skill + Auto-Research** — a `SKILL.md` that teaches any CLI agent to navigate the whiteboard, plus a Python auto-research script that iterates until the agent interacts flawlessly.

---

## Visual Mock-Up — Personal Mode

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [≡]  WHITEBOARD HUD                                          [💬] [🔔] [✕] │
├──────┬──────┬───────────────────────────────────────────────────────────────┤
│      │      │                                                               │
│ NAV  │ ART  │         WHITEBOARD SURFACE (pan/zoomable dark void)          │
│ RAIL │ SHELF│                                                               │
│      │(coll)│    ┌─────────┐  ┌─────────────┐  ┌─────────┐                │
│ ◉ Vo │▓▓▓▓▓▓│    │  🌐     │  │    📝       │  │   🖼️    │                │
│ ○ Ag │▓▓▓▓▓▓│    │  Google │  │   Roadmap   │  │  Photo  │                │
│ ○ Au │▓▓▓▓▓▓│    │  (live  │  │   (md)      │  │  (jpg)  │                │
│ ○ Sy │▓▓▓▓▓▓│    │  iframe)│  │             │  │         │                │
│ ○ Cu │▓▓▓▓▓▓│    │  2×2    │  │   2×1       │  │  1×1    │                │
│ ○ Mo │      │    └─────────┘  └─────────────┘  └─────────┘                │
│      │      │                                                               │
│ ● WB │      │    ┌─────────────┐  ┌─────────┐  ┌────────────────────┐    │
│ ● MA │      │    │    📅       │  │   🔗    │  │   🧊 3D Model      │    │
│      │      │    │  Calendar   │  │  Link   │  │   (Three.js)       │    │
│      │      │    │  (embed)    │  │  Card   │  │   GLB, orbit       │    │
│      │      │    │  2×1        │  │  1×1    │  │   controls         │    │
│      │      │    └─────────────┘  └─────────┘  └────────────────────┘    │
│      │      │                                                               │
│      │      │    ┌─────────────────────────────────────────────────────┐   │
│      │      │    │  ✏️ DRAW LAYER (freeform sketches over everything)   │   │
│      │      │    │  a faint red circle drawn around the CTA on the     │   │
│      │      │    │  "Roadmap" tile — saved as sketch artifact          │   │
│      │      │    └─────────────────────────────────────────────────────┘   │
│      │      │                                                               │
│      │      │              ┌────────────────────────┐                     │
│      │      │              │  FLOATING TOOLBAR      │                     │
│      │      │              │  [−][100%][+]│⊞│⊕│📷│⛶│✏️│🔍│⧉│              │
│      │      │              └────────────────────────┘                     │
│      │      │                                                               │
└──────┴──────┴───────────────────────────────────────────────────────────────┘
│  ◉ WS LIVE  ● LFM-2-8B READY  ● SYSTEM IDLE                       [⚙ APPLY] │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Collapsible Artifact Shelf
- **Expanded** (default): 180px wide vertical strip between nav rail and surface. Shows tile thumbnails with labels, type badges, and a close `✕` per item. Like a vertical tab bar for all open artifacts.
- **Collapsed**: 40px wide icon strip. Shows only the artifact type icon and a tiny unread/comment dot. Hovering an icon shows a 120px×80px glass preview tooltip.
- **Toggle**: A small `◀` / `▶` chevron at the top of the shelf.

### Collapsible Tab Bar (per tile group/view)
- Inside the whiteboard surface, the tab bar (when multiple artifacts of the same type are grouped) collapses to a 32px floating pill at the top-left of the surface. Hover expands it to show full tab titles.

---

## Visual Mock-Up — Developer Mode

Developer mode uses the **same bento/freeform surface** as personal mode. The whiteboard is always a creative display and viewing area.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [≡]  WHITEBOARD HUD — DEV MODE                               [💬] [🔔] [✕] │
├──────┬──────┬───────────────────────────────────────────────────────────────┤
│      │ ART  │         WHITEBOARD SURFACE (pan/zoomable dark void)          │
│ NAV  │ SHELF│                                                               │
│ RAIL │(coll)│    ┌─────────┐  ┌─────────────┐  ┌────────────────────┐    │
│      │▓▓▓▓▓▓│    │  🌐     │  │    �       │  │   🧊 3D Model      │    │
│ ◉ Vo │▓▓▓▓▓▓│    │  Local  │  │   DESIGN    │  │   (Three.js)       │    │
│ ○ Ag │▓▓▓▓▓▓│    │  host   │  │   .md       │  │   CAD-v2.glb       │    │
│ ○ Au │▓▓▓▓▓▓│    │  (live  │  │   (doc)     │  │   orbit controls   │    │
│ ○ Sy │▓▓▓▓▓▓│    │  iframe)│  │   2×1       │  │   2×2              │    │
│ ○ Cu │▓▓▓▓▓▓│    │  2×2    │  │             │  │                    │    │
│ ○ Mo │      │    └─────────┘  └─────────────┘  └────────────────────┘    │
│      │      │                                                               │
│ ● WB │      │    ┌─────────────┐  ┌─────────┐  ┌─────────────┐            │
│ ● MA │      │    │    🎨       │  │   💻    │  │    📊       │            │
│      │      │    │  Artifact   │  │  Code   │  │   Chart     │            │
│      │      │    │  Preview    │  │  Review │  │  (lint ⚠️)  │            │
│      │      │    │  (sandbox)  │  │  (diff) │  │  2×1        │            │
│      │      │    │  2×2        │  │  1×2    │  │             │            │
│      │      │    └─────────────┘  └─────────┘  └─────────────┘            │
│      │      │                                                               │
│      │      │   ┌──────────────────────────────────────────────────────┐   │
│      │      │   │ 🔍 INSPECTOR MODE (same-origin tiles only)          │   │
│      │      │   │ Hovering over a div in the localhost preview         │   │
│      │      │   │ highlights it with a 2px cyan border + label tooltip  │   │
│      │      │   │ "<nav class='navbar'> — click to comment on element" │   │
│      │      │   └──────────────────────────────────────────────────────┘   │
│      │      │                                                               │
│      │      │              ┌────────────────────────┐                     │
│      │      │              │  [−][90%][+]│⊞│⊕│📷│⛶│✏️│🔍│📋│              │
│      │      │              └────────────────────────┘                     │
│      │      │                                                               │
└──────┴──────┴───────────────────────────────────────────────────────────────┘
│  ◉ WS LIVE  ● LFM-2-8B READY  ● SYSTEM IDLE                       [⚙ APPLY] │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Developer Mode Differences (Additive Only)
- **Inspector mode** (`🔍`) is more commonly available because same-origin tiles (localhost, artifact sandbox, html) are typical in dev mode.
- **Artifact lint badges** — sandboxed preview tiles show inline warning chips (broken tags, stale tokens) from the lint API.
- **Code review tiles** — `code` and `diff` artifacts appear as tiles with syntax highlighting and side-by-side diff views.
- **Artifact Preview tile** — a special tile type that renders a sandboxed iframe for HTML/CSS/JS artifacts generated by the agent. Has a `▶ Live` badge and auto-refresh on file change.
- **Localhost Preview tile** — loads `http://localhost:*` in an iframe. Has a `🔄` refresh button and a `📱` viewport size toggle (desktop/tablet/mobile).
- **Comment pins on previews** — when a comment is placed on an `ArtifactPreview` or `Localhost Preview` tile, the coordinates are relative to the iframe content. The comment overlay uses a transparent `pointer-events: none` div sized to match the tile, with `pointer-events: auto` on the pins.

---

## Component Inventory

### New Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `WhiteboardSurface` | `components/whiteboard/WhiteboardSurface.tsx` | Pan/zoom container, wheel/scroll/pinch handling, transform state |
| `BentoGrid` | `components/whiteboard/BentoGrid.tsx` | Responsive auto-layout grid, tile sizing, reflow logic |
| `ArtifactShelf` | `components/whiteboard/ArtifactShelf.tsx` | Collapsible vertical strip listing all open tiles |
| `ArtifactTile` | `components/whiteboard/ArtifactTile.tsx` | Glass card shell with hover header, content routing, comment toggle, inspector hook |
| `ArtifactRenderer` | `components/whiteboard/ArtifactRenderer.tsx` | Content router: iframe, img, markdown, video, chart, calendar, spreadsheet, code, **3D model** |
| `FloatingToolbar` | `components/whiteboard/FloatingToolbar.tsx` | Zoom HUD, snap toggle, add menu, screenshot, focus, **draw toggle, inspector toggle** |
| `CommentPinLayer` | `components/whiteboard/CommentPinLayer.tsx` | Pin rendering, click-to-add, inline editor, **element inspector integration** |
| `DrawLayer` | `components/whiteboard/DrawLayer.tsx` | Freeform canvas overlay on the entire whiteboard; brush, erase, color picker, save-to-artifact |
| `TileSketchOverlay` | `components/whiteboard/TileSketchOverlay.tsx` | Per-tile transparent canvas for sketching on a single artifact |
| `XurLoader` | `components/whiteboard/XurLoader.tsx` | Wraps `Xur.tsx` with configurable size and a dark-glass backdrop for tile/content loading states |
| `Model3DViewer` | `components/whiteboard/Model3DViewer.tsx` | Three.js canvas for GLTF/GLB/OBJ with orbit/zoom/pan controls |
| `InspectorLayer` | `components/whiteboard/InspectorLayer.tsx` | Injects `postMessage`-based inspector into same-origin iframes, handles highlight + selection |
| `MessageContentRenderer` | `components/chat/MessageContentRenderer.tsx` | **Extracted** from `chat-view.tsx` — shared static rendering |
| `VLScreenshotOptimizer` | `lib/vl-screenshot-optimizer.ts` | Model-specific screenshot pipelines (resize, compress, format) |
| `useAppShortcuts` | `hooks/useAppShortcuts.ts` | Global keyboard shortcut registry |
| `useWhiteboardGestures` | `hooks/useWhiteboardGestures.ts` | Pan, zoom, pinch gesture logic |

### Reused Components

| Component | Source | Usage |
|-----------|--------|-------|
| `FloatingPanel` | `DeveloperWorkspace.tsx` | Popped-out tiles |
| `Xur` | `components/Xur.tsx` | Loading overlay (48px for tiles, 96px for fullscreen, 24px for inline) |
| `@dnd-kit/core` | Deps | Tile reordering and pop-out drag |
| `three` / `@react-three/fiber` | New deps | 3D model viewer |

---

## Data Model Additions

```ts
// types/iris.ts

export type ArtifactType =
  | 'web' | 'localhost' | 'artifact' | 'image' | 'document'
  | 'video' | 'calendar' | 'chart' | 'diagram' | 'spreadsheet'
  | 'code' | 'html' | 'link' | '3d-model' | 'sketch'

export interface WhiteboardTile {
  id: string
  type: ArtifactType
  title: string
  src: string
  content?: string
  gridX: number
  gridY: number
  gridW: 1 | 2
  gridH: 1 | 2
  pinned: boolean
  poppedOut: boolean
  floatX?: number; floatY?: number; floatW?: number; floatH?: number
  comments: TileComment[]
  sketchDataUrl?: string   // per-tile sketch overlay saved as base64 PNG
  createdAt: number
  updatedAt: number
}

export interface TileComment {
  id: string
  x: number       // % within tile (fallback for non-inspector)
  y: number
  elementPath?: string   // CSS selector from inspector (same-origin only)
  elementRect?: { x: number, y: number, w: number, h: number }
  text: string
  resolved: boolean
  author: 'user' | 'agent'
  timestamp: number
}

export interface OpenArtifactMsg {
  type: 'open_artifact'
  artifact_type: ArtifactType
  src: string
  title: string
  content?: string
}

export interface CaptureScreenshotMsg {
  type: 'capture_screenshot'
  target: 'whiteboard' | 'active_tile' | 'full_app'
  optimizeFor?: 'gemini' | 'gpt4o' | 'claude37' | 'default'
}
```

---

## VL Screenshot Optimizer

Not all vision models process screenshots the same way. The optimizer applies a pipeline based on `optimizeFor`:

| Model | Constraints | Pipeline |
|-------|-------------|----------|
| `gemini` | Prefers 1024×1024, < 4MB, JPEG | Crop to square → downscale to 1024px → JPEG quality 85 → base64 |
| `gpt4o` | Accepts up to 1536px long edge, < 20MB, PNG or JPEG | Downscale long edge to 1536px → auto-format (PNG if text-heavy, JPEG if photo) → compress |
| `claude37` | Strict 1568px max long edge, < 5MB, JPEG preferred | Downscale long edge to 1568px → JPEG quality 90 → base64 |
| `default` | Generic WebP | Downscale to 1920px → WebP quality 80 → base64 |

**Implementation:** `lib/vl-screenshot-optimizer.ts` exposes `optimizeScreenshot(canvas, modelType)` → returns `{ dataUrl, mimeType, width, height, tokensEstimate }`.

**Token estimation:** A rough heuristic `tokens ≈ (width × height) / 750` gives the agent a sense of cost before sending.

---

## Shortcut Registry (Agent Cursor)

The goal: an agent should be able to operate the entire whiteboard without a mouse. Every shortcut emits a `CustomEvent` that `useAppShortcuts` listens for, so agents can also trigger them via `document.dispatchEvent`.

| Shortcut | Action | Event |
|----------|--------|-------|
| `Ctrl/Cmd + Shift + S` | Capture screenshot (whiteboard) | `iris:screenshot` |
| `Ctrl/Cmd + Shift + T` | Capture screenshot (active tile) | `iris:screenshot_tile` |
| `Ctrl/Cmd + Shift + F` | Toggle focus mode on active tile | `iris:focus_mode` |
| `Ctrl/Cmd + Shift + D` | Toggle draw layer | `iris:toggle_draw` |
| `Ctrl/Cmd + Shift + I` | Toggle inspector mode | `iris:toggle_inspector` |
| `Ctrl/Cmd + Shift + R` | Refresh active tile | `iris:refresh_tile` |
| `Ctrl/Cmd + Shift + C` | Collapse/expand artifact shelf | `iris:toggle_shelf` |
| `Ctrl/Cmd + Shift + N` | Add new blank note tile | `iris:new_note` |
| `Ctrl/Cmd + Shift + B` | Add new browser tile | `iris:new_browser` |
| `Ctrl/Cmd + Shift + O` | Open file picker for upload | `iris:open_upload` |
| `Ctrl/Cmd + =` | Zoom in | `iris:zoom_in` |
| `Ctrl/Cmd + -` | Zoom out | `iris:zoom_out` |
| `Ctrl/Cmd + 0` | Reset zoom | `iris:zoom_reset` |
| `Ctrl/Cmd + Shift + ↑` | Pan up | `iris:pan_up` |
| `Ctrl/Cmd + Shift + ↓` | Pan down | `iris:pan_down` |
| `Ctrl/Cmd + Shift + ←` | Pan left | `iris:pan_left` |
| `Ctrl/Cmd + Shift + →` | Pan right | `iris:pan_right` |
| `Ctrl/Cmd + Shift + P` | Pin/unpin active tile | `iris:pin_tile` |
| `Ctrl/Cmd + Shift + X` | Close active tile | `iris:close_tile` |
| `Ctrl/Cmd + Shift + E` | Pop out active tile | `iris:popout_tile` |
| `Ctrl/Cmd + Shift + M` | Maximize/restore active tile | `iris:maximize_tile` |
| `Ctrl/Cmd + Shift + G` | Toggle snap-to-grid | `iris:toggle_snap` |
| `Ctrl/Cmd + Shift + S + V` | Save sketch as artifact | `iris:save_sketch` |
| `Esc` | Exit focus / draw / inspector mode | `iris:exit_mode` |

**Agent invocation:** An agent can call `window.__IRIS_API__.dispatch('iris:zoom_in')` or send a WS message that the frontend translates into the same event. This is the "hands-free cursor."

---

## Open Design Features We're Adopting

After reviewing the repo, these are the capabilities worth integrating:

1. **Artifact Lint API** (`/api/artifacts/lint`) — After the agent generates an HTML/CSS artifact, a lightweight structural check runs (broken tags, missing side files, stale tokens). Findings are shown as inline warnings on the artifact tile.
2. **Template Persistence** — User can "star" a rendered artifact tile; it gets saved to a local templates store. Next time the `⊕ Add` menu opens, "Your Templates" appears as a category.
3. **Skills as Files** — A `SKILL.md` in the project root teaches the agent how to use the whiteboard. A `DESIGN.md` captures the project's visual direction (colors, typography, spacing tokens). Both are plain text — portable, versionable, no plugin system.
4. **Sidecar-Inspired Desktop Automation** — A lightweight IPC protocol so the agent can request: `STATUS` (what's visible), `SCREENSHOT` (optimized), `CLICK(x,y)` (simulate click), `EVAL(js)` (run JS in the whiteboard context), `CONSOLE` (get recent logs). This is exposed via WebSocket messages, not a local socket, to match IRIS's existing architecture.
5. **Tab Persistence per Project** — On app close, serialize `WhiteboardTile[]` to `localStorage` keyed by `projectId`. On reopen, restore the exact layout.

---

## Xur Loading Integration

| Scenario | Size | Color | Backdrop |
|----------|------|-------|----------|
| Full tile loading (iframe src change) | 48px | `glowColor` | Full tile overlay, `bg-black/60 backdrop-blur-sm` |
| Fullscreen whiteboard load | 96px | `glowColor` | Centered on surface, no backdrop (surface is already dark) |
| Inline content load (image, doc) | 24px | `white` | Small inline spinner, no backdrop |
| Agent tool-call in progress | 64px | `glowColor` | Floating toast at bottom-center: "Agent is working..." |

**Implementation:** `XurLoader` wraps `Xur.tsx` and accepts `scenario: 'tile' | 'fullscreen' | 'inline' | 'agent'` to auto-configure size and styling.

---

## Freeform Drawing + Sketch Artifacts

### Global Draw Layer
- A transparent `<canvas>` element absolutely positioned over the entire `WhiteboardSurface`.
- **Tools**: Brush (variable width 1-12px), Eraser, Color picker (palette tied to `glowColor` + 5 derived shades), Undo (Ctrl+Z), Clear.
- **Mode toggle**: `✏️` on the toolbar. When active, pan/zoom gestures are disabled; click-drag draws.
- **Save**: `Ctrl+Shift+S+V` opens a dialog to save the current sketch as a new `sketch` artifact tile. The canvas is exported to `dataUrl` (PNG) and spawned as a new tile.

### Per-Tile Sketch Overlay
- Each `ArtifactTile` has a transparent local canvas overlay.
- **Toggle**: `✏️` button in the tile's hover header (only visible when draw mode is global-off, to allow per-tile sketching).
- **Behavior**: Drawing is constrained to the tile's bounding box. The sketch is saved to `tile.sketchDataUrl` and persisted with the tile.
- **Use case**: Circling a specific element on a website preview, annotating a chart, marking up a document.

---

## 3D Model Viewer (Three.js)

- **New tile type**: `3d-model`.
- **Supported formats**: GLTF, GLB, OBJ (via `three-obj-loader`).
- **Controls**: Orbit (rotate), zoom (scroll), pan (right-click drag) — standard Three.js orbit controls.
- **UI overlay**: A small header inside the tile with `⊕ Wireframe` toggle, `📷 Screenshot` (captures the Three.js canvas), and `ℹ️ Info` (shows vertex/face count).
- **Loading**: `XurLoader` at 48px while the model buffers.
- **Fallback**: If Three.js fails to load or the file is unsupported, show an error card with "Open in External Viewer" link.

---

## Agent Whiteboard Skill + Auto-Research

### `skills/whiteboard/SKILL.md`
A markdown file that teaches any CLI agent how to navigate and interact with the IRIS whiteboard:

```markdown
# Whiteboard Skill

## Navigation
- The whiteboard responds to keyboard shortcuts and CustomEvents.
- To pan: dispatch `iris:pan_{up|down|left|right}`.
- To zoom: dispatch `iris:zoom_{in|out|reset}`.
- To focus a tile: dispatch `iris:focus_mode` when the tile is active.

## Interacting with Tiles
- To open an artifact: send WS message `{ type: 'open_artifact', artifact_type, src, title }`.
- To comment: send WS message `{ type: 'send_message', text: '[Comment on "Title" at x%,y%]: ...' }`.
- To pop out a tile: dispatch `iris:popout_tile` when the tile is active.
- To maximize a tile to full whiteboard view: dispatch `iris:maximize_tile`.

## Inspector Mode (same-origin only)
- Toggle with `iris:toggle_inspector`.
- When active, the agent can request `EVAL` to inject a script that reports DOM element positions.
- Comments can target `elementPath` (CSS selector) instead of raw coordinates.

## Screenshot / Vision
- Request screenshot via `iris:screenshot` or WS `capture_screenshot`.
- The optimizer will return a model-friendly image. Always check `tokensEstimate` before sending to a vision model.
```

### `tools/auto-research-whiteboard.py`
An auto-research script that runs the agent through a test loop:

```python
# Pseudocode
SCENARIOS = [
  "Open a browser tile to google.com, then zoom in 2x.",
  "Drag the calendar tile to a new position on the whiteboard surface.",
  "Add a comment at 45%,22% on the 'Roadmap' tile.",
  "Save the current sketch as a new artifact.",
  "Toggle inspector mode and comment on the navbar element.",
]

for scenario in SCENARIOS:
    agent = spawn_agent_with_skill('whiteboard')
    result = agent.run(scenario)
    if result.success:
        record_success(scenario, agent.actions)
    else:
        record_failure(scenario, result.error, result.screenshot)
        # The failure is fed back as context for the next iteration
        mutate_skill(scenario, result.error)
```

The script iterates until all scenarios pass 3 times consecutively. Passing runs crystallize into permanent landmarks in the coordinate database.

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `components/whiteboard/WhiteboardSurface.tsx` | **Create** |
| `components/whiteboard/BentoGrid.tsx` | **Create** |
| `components/whiteboard/ArtifactTile.tsx` | **Create** |
| `components/whiteboard/ArtifactRenderer.tsx` | **Create** |
| `components/whiteboard/ArtifactShelf.tsx` | **Create** |
| `components/whiteboard/FloatingToolbar.tsx` | **Create** |
| `components/whiteboard/CommentPinLayer.tsx` | **Create** |
| `components/whiteboard/DrawLayer.tsx` | **Create** |
| `components/whiteboard/TileSketchOverlay.tsx` | **Create** |
| `components/whiteboard/XurLoader.tsx` | **Create** |
| `components/whiteboard/Model3DViewer.tsx` | **Create** |
| `components/whiteboard/InspectorLayer.tsx` | **Create** |
| `components/chat/MessageContentRenderer.tsx` | **Extract** from `chat-view.tsx` |
| `lib/vl-screenshot-optimizer.ts` | **Create** |
| `hooks/useAppShortcuts.ts` | **Create** |
| `hooks/useWhiteboardGestures.ts` | **Create** |
| `types/iris.ts` | **Modify** — add new types |
| `components/dark-glass-dashboard.tsx` | **Modify** — replace browser block |
| `components/chat-view.tsx` | **Modify** — add `↗` open button, extract renderer |
| `hooks/useIRISWebSocket.ts` | **Modify** — handle new WS messages |
| `skills/whiteboard/SKILL.md` | **Create** |
| `tools/auto-research-whiteboard.py` | **Create** |
| `package.json` | **Modify** — add `three`, `@react-three/fiber`, `@react-three/drei` |

---

## Suggestions / Unique Ideas

1. **Holographic Pop-Out Shadow**: When a tile is popped out into a floating panel, add a dynamic drop shadow that shifts with the mouse position (simulated light source), giving a physical "lifted glass" feel.
2. **Ambient Sound on Interaction**: Subtle UI sounds for tile open, close, snap, and pop-out. Keep them optional and off by default, but the agent can toggle them for accessibility testing.
3. **Tile Stacking / Decks**: If too many tiles overflow the grid, they can be "stacked" into a deck (like a card stack in the corner) that fans out on hover. This prevents infinite scroll while keeping everything accessible.
4. **Time-Travel Undo**: Since the whiteboard state is lightweight JSON, save a snapshot every 30 seconds. Users can scrub back through states with a small timeline widget at the bottom.
5. **AI Layout Suggestions**: When a new tile is added, the agent can suggest a layout ("Move this next to the calendar?") via a small inline suggestion chip, which the user accepts with a single click or dismisses.
