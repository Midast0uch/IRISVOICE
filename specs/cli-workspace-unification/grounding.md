# Grounding Table — cli-workspace-unification (Phase -1.0, verified 2026-08-21)

| # | symbol/claim | status | evidence (file:line) | notes |
|---|---|---|---|---|
| 1 | chat-view glass button styling `linear-gradient(135deg, rgba(5,5,12,0.9)...)` | EXISTS | components/chat-view.tsx:3847, :3936, :3967 | Spec cited :3840-3995 — correct region |
| 1b | `>` / `/run` prefix routing | EXISTS | chat-view.tsx:1366 (`startsWith('>')`), :1501-1502 (`isDeveloper && (startsWith('>') \|\| startsWith('/run '))`) | Spec cited :1379-1387/:1500-1520 — close |
| 1c | ContextPill render in footer | EXISTS | chat-view.tsx:37 (import), :3988 (render) | |
| 2 | `MAIN_NODES_DATA` 6 category nodes | EXISTS | dark-glass-dashboard.tsx:57 (data), :1317 (filtered render) | Spec cited :1257-1362 — render region correct |
| 2b | sandboxed web search iframe | EXISTS | dark-glass-dashboard.tsx:496, :1744, :1834 | |
| 3 | `FocusPreset` values | EXISTS BUT DIVERGENT | stores/workspaceStore.ts:41 `'full' \| 'work' \| 'chat' \| 'zen'`; cycle logic :288-307 | REAL GAP — exactly what T8 repurposes to full/active/project/compact |
| 4 | useWorkspacePersistence debounced save | EXISTS | hooks/useWorkspacePersistence.ts | |
| 5 | WorkspaceTabBar / ArchiveDock / KanbanCanvas / DeveloperWorkspace / FloatingPanel | EXISTS | components/workspace/*.tsx | TerminalWidget lazy-imported DeveloperWorkspace:18, mounted :86 |
| 6 | FilePickerModal | EXISTS | components/workspace/FilePickerModal.tsx | |
| 7 | CLITaskProgressRenderer.render() → renderBlueprintCellMatrixCLI | EXISTS | lib/cli/CLITaskProgressRenderer.ts:317-321 | File is 321 lines (spec cited :281-344 — minor drift); visibleWidth :110 |
| 8 | app/cli-preview/page.tsx | EXISTS | app/cli-preview/page.tsx | |
| 9 | models scan endpoint | EXISTS BUT WRONG NAME | backend/main.py:1695 `GET /api/models` (not `/api/models/scan`) | T10 wires to the existing route name |
| 9b | `/api/models/hf/search`, `/api/models/hf/download` | DOES NOT EXIST | grep across backend — zero matches | Confirmed NEW — T10 creates both |
| 9c | ModelBrowserPanel w/ VRAM estimation | EXISTS | components/dashboard/ModelBrowserPanel.tsx | LocalModelManager.scan_models() at backend/agent/local_model_manager.py:1198 |
| 10 | `_task_start_payload` incl. card_id/card_relation/conversation_id | EXISTS (LINE DRIFTED) | backend/agent/agent_kernel.py:7697-7739 | Spec cited :7588-7610 (pre-task-card-v2). T9a adds agent_id/project_id HERE. Identity resolution pattern: `_resolve_card_identity` :7755 |
| 10b | agent_id source | EXISTS | agent_kernel.py:13509 `agent_id=self.session_id` | session identity = kernel session_id |
| 10c | backend project-folder scope | DOES NOT EXIST (kernel-level) | grep — project_id only in memory/swarm stores | T9a must derive it (tool_bridge cwd / config active folder) |
| 11 | Xur.tsx props + unconditional rAF | EXISTS | components/Xur.tsx:11 (`size/color/speed`), :81 (rAF loop, no visibility gate) | REQ-10 AC2 unmount-on-first-block is the resource guard |
| 12 | terminal surfaces mounted in dev mode | EXISTS (BOTH) | chat-view.tsx:25,:3771 (TerminalSlideOver); DeveloperWorkspace.tsx:18,:86 (TerminalWidget) | T2 removes both from dev mode; scrollback store preserved |
| 13 | ConversationChips popover + containerRef scrolling | EXISTS | components/chat/ConversationChips.tsx | |
| 15 | test layout | EXISTS | root tests/{contract,behavioral,agent,...}; backend/tests/{contract,behavioral,unit}; frontend __tests__/ | Frontend contract tests belong in __tests__/ (jest), python in tests/ + backend/tests/ |
| 16 | client-side MCP tools-count store | DOES NOT EXIST | grep stores/, hooks/ — zero matches | `[● N Tools]` badge has no client source yet — T7 subscribes to the T10 marketplace surface state (or a backend count endpoint); dimmed fallback per Error Handling |

## BLOCKERS
None blocking Wave 1. Two resolved notes:
- **#3**: FocusPreset divergence is the SPEC'S OWN TARGET (T8), not a blueprint error.
- **#16**: MCP badge source missing — T7 implements the badge shell with dimmed/absent fallback; live count lands with T10's registry state. Error Handling row covers the interim.
