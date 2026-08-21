# Requirements: Developer Mode CLI, Attached Footer & Visual Workspace Hub

## Decisions Locked
- **Single Prompt In Developer Mode**: Exactly one textarea in `chat-view.tsx` handles both conversation requests and shell commands (`>ls`, `/run`). Developer Mode renders NO terminal slide-over at all — `TerminalSlideOver` / `TerminalWidget` are removed from the dev-mode layout entirely and all shell output streams into the unified chronological scroll.
- **Exact ChatView Glass Styling in Attached Footer**: The footer toolbar matches the exact original button specifications from `chat-view.tsx:3840-3995`: `w-[32px] h-[32px] rounded-full` glass buttons, `linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)`, `border: 1px solid ${fontColor}80`, and textarea bottom border glow line.
- **Horizontal Footer Ordering & Symmetrical Spacing**:
  - Sequence: `[🌐 Web (32px)]` `[⤒ Upload (32px)]` `|` `[◈ Model Switcher (116px)]` `|` `[≡ ConversationChips (32px)]` `[● ContextPill (174px)]`.
  - Redundant `⏎` enter icon is removed to maximize `ContextPill` horizontal allocation ($174\text{px}$).
  - `ConversationChips` is positioned immediately to the **LEFT** of `ContextPill`.
  - Total inner width $454\text{px}$ distributed across $486\text{px}$ usable width with balanced $\approx 16\text{px}$ spacing between functional clusters.
- **Unicode Blueprint Matrix**: Task executions in Developer Mode render the architectural box-drawing format (`┌──┐`, `├──┤`, `└──┘`, `┊` dotted rails, `┌┄┄ ↳ [Diving Deeper] ┄┄┐` sub-chambers, `●`/`◎`/`✦` status orbs) inside the unified chronological scroll. The chamber label is FREE-FORM DATA TEXT rendered via `↳ [{branchLabel}]` — the examples here show "Diving Deeper" per task-card-v2 Decision 13 / CT-9, which bans the literal string "Sub-Loop" from every user-facing surface. Internal identifiers (`is_subloop`, `sub_loop_split`, `origin`) are exempt.
- **Project Folder Bar & Archive Dock in ChatView**: Top 30px project bar (`[📁 IRISVOICE]`, `[📄 auth.ts]`, `[+]`) and bottom `ArchiveDock` remain directly accessible in ChatView.
- **Hybrid Navigation Rail (Dual-Mode Switcher + Unified 36px Nodes + Live Telemetry Badges)**:
  - Mode Switcher: Top segmented glass pill `[✦ SURFACES | ⚙ SETTINGS]` collapses into a 2-pip toggle `[✦ | ⚙]`.
  - Surfaces View: Dedicated 36px circular orbs with live ambient telemetry badges:
    - **Workspace Hub**: `[● N Running]` (active agent task counter).
    - **Browser Surface**: `[● Live Web]` (active web search badge).
    - **Marketplace & Models**: `[● N Tools]` (MCP server / tool count).
  - Settings View: 6 uniform 36px circular nodes (`Voice`, `Agent`, `Automate`, `System`, `Customize`, `Monitor`).
- **Interactive Rail Right-Boundary Chevron Seam Stack & Neon Laser Shimmer**:
  - **Single Unified `<nav>` Container**: Clean single element with `overflow-visible` (scroll lists handle content overflow) and right boundary border (`border-r border-white/[0.06]`). No separate adjacent floating handle divs or wrapper splits.
  - **Exact Seam Anchor**: Positioned with explicit inline styles directly on the rail's right border seam at vertical midpoint (`position: 'absolute', right: -8, top: '50%', transform: 'translateY(-50%)'`, width 16px, height 44px).
  - **Single Unified Directional Stack**: Exactly one vertical column of 4 tightly-spaced razor micro-chevrons (`strokeWidth: 1.3`) whose apex tips terminate directly on top of the seam line ($X = 8\text{px}$):
    - **Expanded (160px/180px)**: All 4 chevrons point LEFT (`‹ ‹ ‹ ‹`, $X=12 \to X=8$) to collapse inward.
    - **Collapsed (56px)**: All 4 chevrons point RIGHT (`› › › ›`, $X=4 \to X=8$) to expand outward.
  - **Neon Laser Shimmer On Top of Seam**: Vertical gradient line drawn directly down the seam axis ($X=8\text{px}, Y=3\text{px} \to 37\text{px}$) across the chevron tips, igniting with a glowing cyan-to-white core (`#00d4ff` $\to$ `#ffffff`) and ambient drop-shadow (`drop-shadow(0 0 6px #00d4ff)`) on hover.
- **Repurposed Focus Mode**: Inside the Visual Workspace Hub, Focus Mode controls multi-agent card filtering and board density (`FULL`, `ACTIVE`, `PROJECT`, `COMPACT`).
- **Multi-Agent Kanban Wiring**: Kanban cards subscribe to backend WebSocket task events (`task:start`, `task:progress`, `task:done`) tagged with `(projectId, conversationId, agentId)`.
- **Unified Marketplace & Model Manager Surface**: MCP Tools/Integrations and Model Management are combined into a single unified surface view (`Marketplace & Models`) with sub-tab switching between `[ 🔌 MCP Tools & Integrations ]` and `[ 🧠 Local Models & HF Hub ]`. The local model view scans local weights and connects to Hugging Face Hub search to discover, filter, and stream 1-click downloads directly into the scanned `models/` directory.
- **Multi-Agent Tag Production (Backend)**: The `(projectId, conversationId, agentId)` tags consumed by the Kanban board are emitted by the BACKEND at the kernel's task-event construction point (`agent_kernel._task_start_payload`, the same single point that already carries `card_id` / `card_relation` / `conversation_id`). `agentId` derives from the kernel session identity; `projectId` from the active project folder scope. The frontend never fabricates these tags.
- **Navigation Rail Telemetry Badge Sources**: Badge values come from EXISTING stores — `[● N Running]` from active tasks in `stores/workspaceStore.ts`; `[● Live Web]` from the web-search iframe/browser-surface active state; `[● N Tools]` from the connected MCP server/tool registry count. No new telemetry backend is introduced in this spec.
- **Branded Loading Glyph**: Between prompt submit and the first streamed block (message, shell output, or Blueprint Matrix), the unified scroll renders `components/Xur.tsx` — the existing 92-line canvas particle spiral (`size`/`color`/`speed` props) already used in ChatView — tinted with the brand glow color. It is NON-INTERACTIVE, mounted only while loading, and unmounted on first content so rAF loops do not accumulate in the stream. The Blueprint Matrix `TASK :` header carries the same glow accent color so orb → glyph → matrix read as one continuous brand language.
- **Explicit Exclusions (Deferred to Separate Future Specs)**: Full pan/zoom Whiteboard surface buildout and intricate node-graph MindMap backend architectural diagrams are out of scope.

---

## Requirements

### REQ-1: Single Unified Prompt & Prefix Routing
**User Story:** As a developer, I want a single textarea input in ChatView that handles both natural language requests and shell commands, so that I have a unified CLI interface without redundant input boxes.

**Verified:** `components/chat-view.tsx:3863-3892` & `components/chat-view.tsx:1500-1520`

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide exactly one prompt textarea in ChatView that handles conversation prompts, shell commands starting with `>`, and `/run` tool executions.
- AC2: WHEN a developer enters `> <command>` or `/run <tool>`, THEN THE SYSTEM SHALL route the execution to the shell / CLI tool bridge and stream output directly into the unified scroll.
- AC3: THE SYSTEM SHALL render no terminal slide-over in Developer Mode — `TerminalSlideOver` / `TerminalWidget` SHALL NOT appear in the dev-mode layout, and all shell output SHALL stream into the unified scroll.

---

### REQ-2: Attached Horizontal Footer Toolbar & Spacing Symmetry
**User Story:** As a developer, I want the footer toolbar attached horizontally below the textarea with exact original glass styling and mathematically balanced spacing, so that controls fit within 510px without visual drift.

**Verified:** `components/chat-view.tsx:3840-3995` & `app/cli-preview/page.tsx:280-370`

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL attach a 32px horizontal toolbar directly beneath the textarea with a fixed total footer height (~64px).
- AC2: THE SYSTEM SHALL position buttons in the exact sequence: `[Web: 32px]` $\to$ `[Upload: 32px]` $\to$ `Divider` $\to$ `[Model Switcher: 116px]` $\to$ `Divider` $\to$ `[ConversationChips: 32px]` $\to$ `[ContextPill: 174px]`.
- AC3: THE SYSTEM SHALL render `Web Toggle` and `Upload` using exact original `w-[32px] h-[32px] rounded-full` glass styling (`linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)`, `border: 1px solid ${fontColor}80`).
- AC4: THE SYSTEM SHALL eliminate the standalone `⏎` enter icon, allocating the freed horizontal width to `ContextPill`.
- AC5: THE SYSTEM SHALL retain full `ConversationChips` functionality, opening the popover drawer on the left of `ContextPill` and scrolling smoothly to selected turns.

---

### REQ-3: Authentic Unicode Blueprint Matrix Task Progress
**User Story:** As a developer, I want task executions in the CLI to render as authentic Unicode Blueprint Matrix blocks, so that I can clearly see the hierarchical execution tree, thoughts, and memory crystallization.

**Verified:** `temp/task-card-redesign/CLITaskProgressRenderer.ts:281-344`

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL render task progress in Developer Mode using the architectural single-line Unicode box format (`┌──┐`, `├──┤`, `└──┘`, `┊` dotted rails, `┌┄┄ ↳ [{branchLabel}] ┄┄┐` sub-chambers, `●`/`◎`/`✦` status orbs). The chamber label is free-form data text; the literal string "Sub-Loop" SHALL NOT appear in any user-facing surface (task-card-v2 CT-9).
- AC2: WHILE a task is active, THE SYSTEM SHALL display the live `THK` thought stream in the header block and an elapsed running timer (`⏱ MM:SS`).
- AC3: WHEN a task crystallizes, THE SYSTEM SHALL display `✦ CONVERGED` and the memory attribution footer inside the container walls.
- AC4: THE SYSTEM SHALL suppress GUI `TaskListCard` in Developer Mode to prevent dual-renderer duplication.

---

### REQ-4: Integrated Project Folder Bar & Archive Dock in ChatView
**User Story:** As a developer, I want to switch project folders and view archived files directly in ChatView, so that my CLI context remains grounded in the target directory.

**Verified:** `components/workspace/WorkspaceTabBar.tsx:83-148` & `components/workspace/ArchiveDock.tsx:21-137`

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL render a 30px project bar at the top of ChatView displaying the active project folder pill (`[📁 IRISVOICE]`), active file tabs, and a `+` button.
- AC2: WHEN the developer clicks the `+` button, THEN THE SYSTEM SHALL open `FilePickerModal` to switch folders or open files.
- AC3: THE SYSTEM SHALL render an `ArchiveDock` directly above the input footer showing minimized card pills with one-click restoration.

---

### REQ-5: Multi-Agent Kanban Board & Conversation History Wiring
**User Story:** As a developer, I want the Kanban board in the Visual Workspace Hub to wire directly into conversation threads and project folders, so that I can see multiple agents working concurrently across folders and environments.

**Verified:** `components/workspace/KanbanCanvas.tsx:1-45` & `stores/workspaceStore.ts:43-55` & `hooks/useWorkspacePersistence.ts:1-120`

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL wire Kanban cards to backend task events (`task:start`, `task:progress`, `task:done`) tagged with `(projectId, conversationId, agentId)`. The tags SHALL be emitted by the backend at the kernel's task-event construction point (`_task_start_payload`); the frontend SHALL NOT infer or fabricate them.
- AC2: WHEN multiple agents execute tasks in different folders/threads, THEN THE SYSTEM SHALL display distinct Kanban cards with live agent status badges and step counters.
- AC3: WHEN a developer clicks a Kanban card, THEN THE SYSTEM SHALL deep-link or switch to that conversation thread in ChatView.
- AC4: THE SYSTEM SHALL persist the multi-agent Kanban state across sessions via `useWorkspacePersistence`.

---

### REQ-6: Repurposed Focus Mode for Visual Workspace Hub
**User Story:** As a developer, I want Focus Mode inside the Visual Workspace Hub to control multi-agent card filtering and board density, so that I can switch between broad multi-project oversight and deep single-task focus.

**Verified:** `stores/workspaceStore.ts:285-308` & `components/workspace/DeveloperWorkspace.tsx:128-160`

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide a Focus Mode toggle in the Visual Workspace Hub cycling through 4 density/filter presets: `FULL`, `ACTIVE`, `PROJECT`, `COMPACT`.
- AC2: WHERE preset is `FULL`, THE SYSTEM SHALL display the complete multi-column pipeline (`BACKLOG`, `IN PROGRESS`, `REVIEW`, `CRYSTALLIZED`) for all project folders.
- AC3: WHERE preset is `ACTIVE`, THE SYSTEM SHALL filter the board to currently executing agent tasks only.
- AC4: WHERE preset is `PROJECT`, THE SYSTEM SHALL group columns by project folder (`IRISVOICE`, `backend`, etc.).
- AC5: WHERE preset is `COMPACT`, THE SYSTEM SHALL render high-density minimized card strips.

---

### REQ-7: Dual-Mode Navigation Rail with Live Telemetry Badges & Seam Chevron Affordance
**User Story:** As a developer, I want a dual-mode navigation rail in the Dashboard Wing with live telemetry badges and a precision seam-anchored chevron toggle with neon laser shimmer, so that I can expand and collapse the rail with clean spatial feedback.

**Verified:** `components/dark-glass-dashboard.tsx:1257-1362` & `app/cli-preview/page.tsx:810-905`

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide a 2-way glass pill switch `[✦ SURFACES | ⚙ SETTINGS]` below branding, collapsing to `[✦ | ⚙]` when rail width is 56px.
- AC2: WHEN in `SURFACES` mode, THE SYSTEM SHALL render 36px circular nodes for **Workspace Hub**, **Browser Surface**, and **Marketplace & Models**, featuring live telemetry sub-badges (`[● N Running]`, `[● Live Web]`, `[● N Tools]`). Badge values derive from existing stores: `N Running` from active tasks in `stores/workspaceStore.ts`; `Live Web` from the browser-surface/web-search active state; `N Tools` from the connected MCP server/tool registry count.
- AC3: WHEN in `SETTINGS` mode, THE SYSTEM SHALL render all 6 `MAIN_NODES_DATA` category nodes (`Voice`, `Agent`, `Automate`, `System`, `Customize`, `Monitor`) as 36px rounded-full buttons.
- AC4: THE SYSTEM SHALL implement the rail collapse/expand affordance within a **single unified `<nav>` container** with `overflow-visible` and `border-r border-white/[0.06]`, without any secondary wrapper divs, floating tabs, or adjacent handle elements.
- AC5: THE SYSTEM SHALL anchor the chevron affordance directly to the **right boundary seam** of the rail at vertical midpoint using explicit inline styles (`position: 'absolute', right: -8, top: '50%', transform: 'translateY(-50%)'`, width 16px, height 44px, z-index 50).
- AC6: THE SYSTEM SHALL render a **single unified vertical column of 4 tightly-spaced razor micro-chevrons** (`strokeWidth: 1.3`, `strokeLinecap: round`, `strokeLinejoin: round`) whose apex tips terminate directly on the center seam axis ($X = 8\text{px}$):
  - **Expanded State (160px/180px)**: All 4 chevrons point in unison to the LEFT (`‹ ‹ ‹ ‹`, paths `M 12 Y1 L 8 Y2 L 12 Y3`) to collapse the rail inward.
  - **Collapsed State (56px)**: All 4 chevrons point in unison to the RIGHT (`› › › ›`, paths `M 4 Y1 L 8 Y2 L 4 Y3`) to expand the rail outward.
- AC7: THE SYSTEM SHALL render a **neon laser shimmer line** directly on top of the seam axis ($X = 8\text{px}$) across the chevron tips ($Y=3\text{px} \to Y=37\text{px}$), which intensifies on hover with a cyan-to-white core (`#00d4ff` $\to$ `#ffffff`) and glowing drop shadow (`drop-shadow(0 0 6px #00d4ff)`).
- AC8: WHEN the developer clicks the seam chevron affordance, THE SYSTEM SHALL smoothly toggle rail width between collapsed (56px) and expanded (160px/180px) with animated width and opacity transitions.

---

### REQ-8: Observability & Telemetry Instrumentation
**User Story:** As a tuner/developer, I want structured logging of CLI dispatches, task matrix transitions, and multi-agent card events, so that system performance and agent trajectories can be verified.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log all CLI command dispatches, Blueprint Matrix transitions, and Kanban card state changes with ISO-8601 timestamps and active conversation IDs.
- AC2: THE SYSTEM SHALL emit structured log entries to `.iris-logs/` without blocking async hot paths.

---

### REQ-9: Unified Marketplace & Model Manager Surface (MCPs + Local Models + Hugging Face Hub)
**User Story:** As a developer, I want a single unified Marketplace & Model Manager surface where I can toggle between MCP tools/integrations and local models, with the ability to search Hugging Face Hub and download new GGUF models directly to my local models folder, so that I have a central control hub for agent capabilities and model weights.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL combine MCP Tools/Integrations and Model Management into a **single unified surface view** (`Marketplace & Models`) accessible via the navigation rail.
- AC2: THE SYSTEM SHALL provide a top segmented pill switcher inside the surface to toggle between:
  - `[ 🔌 MCP Tools & Integrations ]`
  - `[ 🧠 Local Models & HF Hub ]`
- AC3: WHEN the `MCP Tools & Integrations` tab is active, THE SYSTEM SHALL display installed MCP servers, connected tools, and marketplace skills with 1-click connect/disconnect and status badges.
- AC4: WHEN the `Local Models & HF Hub` tab is active, THE SYSTEM SHALL display the scanned local `models/` directory (GGUF weights, file sizes, quantizations, VRAM fit estimates, vision projector attachments, and 1-click load/unload into the inference engine).
- AC5: THE SYSTEM SHALL provide an integrated **Hugging Face Hub Index Search** within the Models view, allowing the developer to query the Hugging Face API (`https://huggingface.co/api/models`) filtered for compatible GGUF/text-generation/voice models.
- AC6: FOR search results from Hugging Face Hub, THE SYSTEM SHALL display repository title, author, likes, downloads, and available quantization files (e.g. Q4_K_M, Q8_0, Q5_K_M) with respective file sizes.
- AC7: WHEN the developer initiates a download from Hugging Face Hub, THE SYSTEM SHALL stream the download directly into the local scanned `models/` folder with live progress percentage, download speed, and cancel capability.
- AC8: UPON download completion, THE SYSTEM SHALL trigger an automatic rescan of the local `models/` folder so the newly downloaded model appears in the local list ready for 1-click loading into the inference engine.

---

### REQ-10: Branded Loading Glyph & Matrix Accent
**User Story:** As a developer, I want IRIS's brand presence visible inside the unified scroll while a prompt is loading, so that the wait between submit and first output feels alive and on-brand rather than dead air.

**Verified:** `components/Xur.tsx` (existing, 92 lines — reused as-is)

**Acceptance Criteria:**
- AC1: WHEN a prompt is submitted and no streamed content has arrived yet, THEN THE SYSTEM SHALL render the `Xur` canvas particle spiral in the unified scroll, tinted with the brand glow color (`BrandColorContext`), non-interactive.
- AC2: WHEN the first content block arrives (message, shell output, or Blueprint Matrix), THEN THE SYSTEM SHALL unmount the glyph — at most one glyph instance lives in the stream at a time, and no rAF loop persists after loading completes.
- AC3: THE SYSTEM SHALL carry the same brand glow accent into the Blueprint Matrix `TASK :` header line, so orb → loading glyph → matrix read as one continuous visual language.

---

## Non-Requirements (Explicitly Out of Scope)
- **Whiteboard Pan/Zoom Surface**: Pan/zoom infinite canvas, freeform drawing layer, and Three.js 3D viewer are out of scope (deferred to dedicated Whiteboard V2 spec).
- **Node-Graph MindMap Architectural Visualizer**: Complex interactive node diagrams of the backend architecture are out of scope (deferred to dedicated Architecture Visualizer spec).
