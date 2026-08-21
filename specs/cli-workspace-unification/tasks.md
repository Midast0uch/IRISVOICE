# Tasks: Developer Mode CLI, Attached Footer & Visual Workspace Hub

> Each task links to a requirement ID. Grouped into progressive waves for parallel/sequential execution.

---

## Wave 1 — CLI Chassis & Attached Horizontal Footer (Foundation)
- [ ] **T1 (REQ-1)**: Refactor `components/chat-view.tsx` Developer Mode body — render unified chronological message stream with shell output instead of full workspace replacement. — `components/chat-view.tsx` — RIPPLE: Verify personal mode `TaskListCard` remains unaffected.
- [ ] **T2 (REQ-1)**: Remove `TerminalSlideOver` / `TerminalWidget` from the Developer Mode layout ENTIRELY (no slide-over, no `$` input row) — all shell output routes to the unified stream. — `components/terminal/TerminalSlideOver.tsx`, `components/chat-view.tsx` — RIPPLE: Preserves `terminalScrollback.ts` line subscriptions for the scroll bridge; supersedes task-card-v2 REQ-13 for dev mode.
- [ ] **T3 (REQ-2)**: Implement attached horizontal footer toolbar in `components/chat-view.tsx` — sequence `[Web]` $\to$ `[Upload]` $\to$ `|` $\to$ `[Model]` $\to$ `|` $\to$ `[ConversationChips]` $\to$ `[ContextPill: 174px]`, remove `⏎` enter icon, and apply exact $454\text{px}$ inner metric spacing with $32\text{px}$ rounded-full glass buttons. — `components/chat-view.tsx` — RIPPLE: Maintain exact original glassmorphic button styling (`linear-gradient(135deg, rgba(5,5,12,0.9) 0%, rgba(12,12,20,0.85) 100%)`, `border: 1px solid ${fontColor}80`).
- [ ] **T4 (REQ-3)**: Connect `renderBlueprintCellMatrixCLI` in message stream when `isDeveloper` is active — render authentic Unicode box-drawing format (`┌──┐`, `├──┤`, `└──┘`, `┊`, `●`, `◎`, `✦`) with free-form chamber label (`↳ [{branchLabel}]`; never the literal "Sub-Loop" per task-card-v2 CT-9). — `components/chat-view.tsx` — RIPPLE: Verify `CLITaskProgressRenderer.ts` formatting is unbroken.
- [ ] **T4a (REQ-10)**: Mount the branded loading glyph — `components/Xur.tsx` at ~28–36px tinted with brand glow — in the unified scroll between prompt submit and first streamed content; unmount on first block (max one instance, no orphaned rAF loops); carry the glow accent into the matrix `TASK :` header. — `components/chat-view.tsx` — RIPPLE: Reuses `components/Xur.tsx` unchanged.

---

## Wave 2 — Project Folder Bar & Archive Dock in ChatView
- [ ] **T5 (REQ-4)**: Integrate compact 30px Project Folder tab bar at top of Developer Mode ChatView with active folder pill, file tabs, and `+` button triggering `FilePickerModal`. — `components/chat-view.tsx` — RIPPLE: Links to `stores/workspaceStore.ts` tab actions.
- [ ] **T6 (REQ-4)**: Mount `ArchiveDock` directly above input footer in ChatView with 1-click restore functionality and item count badge in top bar. — `components/chat-view.tsx` — RIPPLE: Auto-collapses to 2px glow line when empty.

---

## Wave 3 — Dual-Mode Dashboard Navigation Rail & Visual Workspace Hub
- [ ] **T7 (REQ-7)**: Implement Dual-Mode navigation rail in `components/dark-glass-dashboard.tsx` with top mode switcher `[✦ SURFACES | ⚙ SETTINGS]`, 36px circular nodes, live telemetry badges fed from EXISTING stores (`[● N Running]` ← workspaceStore active tasks; `[● Live Web]` ← browser-surface state; `[● N Tools]` ← MCP tool registry count), and precision seam-anchored right-boundary affordance (`position: absolute; right: -8px; top: 50%`, single column of 4 micro-chevrons terminating on seam $X=8$, pointing `‹` when expanded / `›` when collapsed, with localized neon laser shimmer line on the seam that flares on hover) in a unified `<nav overflow-visible>`. — `components/dark-glass-dashboard.tsx` — RIPPLE: Preserves all 6 `MAIN_NODES_DATA` category settings nodes and existing sandboxed web search iframe.
- [ ] **T8 (REQ-6)**: Repurpose Focus Mode in `stores/workspaceStore.ts` and `DeveloperWorkspace.tsx` to control Workspace Hub density and multi-agent filters (`FULL`, `ACTIVE`, `PROJECT`, `COMPACT`). — `stores/workspaceStore.ts` & `components/workspace/DeveloperWorkspace.tsx` — RIPPLE: Replaces legacy terminal collapse configs with multi-agent card filtering.
- [ ] **T9 (REQ-5)**: Wire Multi-Agent Kanban board cards to WebSocket task lifecycle events (`task:start`, `task:progress`, `task:done`) tagged with `(projectId, conversationId, agentId)`. — `components/workspace/KanbanCanvas.tsx` & `stores/workspaceStore.ts` — RIPPLE: Supports deep-linking back to active thread in ChatView.
- [ ] **T9a (REQ-5)**: Emit multi-agent tags from the backend — add `agent_id` (kernel session identity) and `project_id` (active project folder scope) at `agent_kernel._task_start_payload`, the single construction point that already carries `card_id`/`card_relation`/`conversation_id`. Additive only. — `backend/agent/agent_kernel.py` — RIPPLE: Without this, T9 and CT-1 cannot pass; all task:* emit sites inherit the fields.
- [ ] **T10 (REQ-9)**: Build Unified Marketplace & Model Manager surface (`components/integrations/UnifiedMarketplaceModelsSurface.tsx`) combining MCP Tools/Integrations with Local Models (`models/` scan, GGUF/VRAM fit plan, 1-click engine load) and Hugging Face Hub API index search with streamed 1-click downloads to the local folder and auto-rescan. Downloads MUST sanitize remote filenames (no path traversal out of `models/`) and remove partial files on cancel/failure. — `components/integrations/` & `components/dashboard/ModelBrowserPanel.tsx` & `backend/main.py` — RIPPLE: Replaces separate tab split with unified segmented pill view.

---

## Wave 4 — Verification & Standing CDD Harness
- [ ] **T11 (REQ-8)**: Add structured logging for CLI command dispatch, task matrix transitions, and multi-agent card events. — `lib/logger.ts` & `backend/agent/event_bus.py` — RIPPLE: Scoped by active conversation ID.
- [ ] **T12 (REQ-1..REQ-10)**: Build contract tests `tests/contract/test_ws_event_contracts.py` (CT-1 incl. additive `agent_id`/`project_id` tags, CT-2, CT-3 for HF search/download) and behavioral test suite verifying the full CLI, workspace, multi-agent Kanban, unified marketplace/models loop (incl. cancel/fail removes partial `.gguf`), and loading-glyph lifecycle. — `tests/contract/` & `tests/behavioral/` — RIPPLE: Standing CDD validation harness.

---

## Dependency & Parallelization Notes
- **Wave 1 & Wave 2** (ChatView CLI Chassis, Footer, Folder Tabs, Archive Dock) are frontend-only within `chat-view.tsx` and can execute immediately.
- **Wave 3** (Dual-Mode Navigation Rail, Repurposed Focus Mode, Multi-Agent Kanban) touches `dark-glass-dashboard.tsx`, `workspaceStore.ts`, and `KanbanCanvas.tsx`.
- **Whiteboard V2 & Architectural Node-Graph MindMap** are explicitly decoupled from this plan.
