# Hybrid CLI ChatView, Attached Footer & Visual Workspace Hub (Final Architecture Spec)

> **Key Rule**: Single prompt. Single scroll. Exact original ChatView glass styling (`rounded-full` 32x32 buttons, `linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)`).
> **Footer Layout**: `[🌐 Web (32px)]` `[⤒ Upload (32px)]` `|` `[◈ Model (116px)]` `|` `[≡ Turns (32px)]` `[● ContextPill (174px)]`. `⏎` enter icon removed. Symmetrical spacing math.
> **Dual-Mode Navigation Rail**: Mode switch `[✦ SURFACES | ⚙ SETTINGS]`. 36px circular nodes with live telemetry badges (`[● 2 Running]`, `[● Live Web]`, `[● 12 Tools]`). Interactive right-boundary click expansion (56px $\leftrightarrow$ 160px) with subtle glow handle.
> **Full Kiro Spec Suite**: [`specs/cli-workspace-unification/`](file:///c:/dev/IRISVOICE/specs/cli-workspace-unification/)

---

## 1. Dual-Mode Dashboard Navigation Rail Architecture

```
EXPANDED: SURFACES MODE (160px)            EXPANDED: SETTINGS MODE (160px)
┌─────────────────────────┐               ┌─────────────────────────┐
│  IRIS VOICE             │               │  IRIS VOICE             │
├─────────────────────────┤               ├─────────────────────────┤
│ ┌─────────────────────┐ │ Mode Switch   │ ┌─────────────────────┐ │ Mode Switch
│ │ [✦ SURFACES] [⚙ Set]│ │ (Active Left) │ │ [✦ Surf] [⚙ SETTINGS]│ │ (Active Right)
│ └─────────────────────┘ │               │ └─────────────────────┘ │
├─────────────────────────┤               ├─────────────────────────┤
│                         │               │                         │
│  ( 📊 )  Workspace Hub  │               │  ( 🎙 )  Voice Engine    │
│          [● 2 Running]  │ Live badge    │  ( 🤖 )  Agent Settings │
│                         │               │  ( 🕸 )  Automate       │
│  ( 🌐 )  Browser Surface│               │  ( ⚙ )  System         │
│          [● Live Web]   │ Live badge    │  ( 🎨 )  Customize      │
│                         │               │  ( 📈 )  Monitor        │
│  ( 📦 )  Market & Models│               │                         │
│          [● 12 Tools]   │ Live badge    │                         │
├─────────────────────────┤               ├─────────────────────────┤
│  👤 Online · o4-mini    │               │  👤 Online · o4-mini    │
└─────────────────────────┘               └─────────────────────────┘
  ▲                                         ▲
  └─ Right boundary line clickable ─────────┴─ (56px ↔ 160px with subtle glow handle)
```

---

## 2. Layout Breakdown: Developer Mode ChatView

```
┌───────────────────────────────────────────────────────────────────────────┐
│  HEADER           44px   one row, fixed, never scrolls                    │
│  ───────────────────────────────────────────────────────────────────────  │
│  ● IRIS CLI        [Dashboard]                                [Notif][Hist][X]│
├───────────────────────────────────────────────────────────────────────────┤
│  PROJECT & TABS   30px   streamlined folder/tab selector                  │
│  ───────────────────────────────────────────────────────────────────────  │
│  [📁 IRISVOICE]   [📄 auth.ts]   [+]                           [🗄 Dock: 3]│
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  UNIFIED SCROLL   flex-1   ONE overflow-y-auto   ONE bg #0b0c1a           │
│  ───────────────────────────────────────────────────────────────────────  │
│                                                                           │
│  iris@dev > refactor auth middleware with resilient backoff               │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐     │
│  │ TASK : Implement WebSocket Audio Streaming Resilience            │     │
│  │ THK  : Checking FastAPI disconnect lifecycle & backoff params... │     │
│  ├──────────────────────────────────────────────────────────────────┤     │
│  │ ┊ ●  READ    src-tauri/src/ws_client.rs                          │     │
│  │ ┊    └─ Verified tokio reconnect backoff                         │     │
│  │ ┊                                                                │     │
│  │ ┊ ┌┄┄ ↳ [Sub-Loop: Docs] ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐           │     │
│  │ ┊ ┊   ●  SEARCH  FastAPI WebSocket disconnect handlers          │     │
│  │ ┊ ┊   └─ Found 3 connection lifecycle patterns                  │     │
│  │ ┊ └┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘           │     │
│  │ ┊                                                                │     │
│  │ ┊ ◎  EXEC    pytest tests/test_ws_resilience.py                  │     │
│  ├──────────────────────────────────────────────────────────────────┤     │
│  │ ✦ CONVERGED                                                      │     │
│  │ Skill crystallized into data/memory.db (skills)                  │     │
│  │ Retrieved 2 past episodes for WebSocket reconnects               │     │
│  └──────────────────────────────────────────────────────────────────┘     │
│                                                                           │
│  $ pytest tests/test_ws_resilience.py                                     │
│  tests/test_ws_resilience.py::test_reconnect_backoff PASSED               │
│  2 passed in 0.84s                                                        │
│                                                                           │
│  Assistant: Middleware patched with exponential backoff.                  │
│                                                                           │
├───────────────────────────────────────────────────────────────────────────┤
│  ARCHIVE DOCK (Docked above input, click to restore)                      │
│  ───────────────────────────────────────────────────────────────────────  │
│  DOCK: [📄 auth-tokens.ts]  [📄 ws-test.ts]  [📄 middleware.py]           │
├───────────────────────────────────────────────────────────────────────────┤
│  ATTACHED FOOTER COMPONENT (Exact Mathematical Spacing & Glass Aesthetics) │
│  ───────────────────────────────────────────────────────────────────────  │
│                                                                           │
│  [ ▌ Type command, /run, or ask IRIS...                             ]     │
│                                                                           │
│  [ (🌐) Web ] [ ⤒ Upload ] | [◈ o4-mini ▾] | [≡ Turns] [● IDLE 0 / 128k]  │
│                                                                           │
│  — Sequence: Tools (72px) | Model (116px) | Turns (32px) Context (174px)  │
│  — ConversationChips sits immediately to the LEFT of ContextPill.         │
│  — Redundant Enter icon removed; freed width given to ContextPill.        │
│  — Exact w-[32px] h-[32px] rounded-full glass buttons matching chat-view. │
│  — Fits 100% horizontally within 510px fixed width without expansion.    │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Repurposed Focus Mode in the Visual Workspace Hub

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ REPURPOSED FOCUS PRESETS (Inside Visual Workspace Hub)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. FULL    │ Complete pipeline: Backlog, In Progress, Review, Crystallized. │
│            │ Shows all cards across all project folders.                    │
├────────────┼────────────────────────────────────────────────────────────────┤
│ 2. ACTIVE  │ Filtered strictly to active running agent tasks.               │
│            │ Hides idle backlog items to highlight live multi-agent work.  │
├────────────┼────────────────────────────────────────────────────────────────┤
│ 3. PROJECT │ Grouped by project directory (IRISVOICE, backend, etc.).       │
│            │ Ideal for multi-repo or multi-folder projects.                 │
├────────────┼────────────────────────────────────────────────────────────────┤
│ 4. COMPACT │ High-density minimized card strips for quick birds-eye status. │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Canonical Spec Suite Reference

1. **[Requirements](file:///c:/dev/IRISVOICE/specs/cli-workspace-unification/requirements.md)**
2. **[Architecture & Design](file:///c:/dev/IRISVOICE/specs/cli-workspace-unification/design.md)**
3. **[Tasks (Waves 1-4)](file:///c:/dev/IRISVOICE/specs/cli-workspace-unification/tasks.md)**
4. **Live Prototype URL**: `http://localhost:3000/cli-preview`