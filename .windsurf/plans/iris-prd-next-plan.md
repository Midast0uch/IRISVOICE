# IRIS PRD Next Plan

## Objective
Complete remaining PRD gaps by expanding settings window content and refactoring HexagonalControlCenter into smaller components (IrisOrb, Subnode, MiniNode) while preserving current visuals/animations and behavior.

## Scope
- Add placeholder content blocks for all settings categories beyond Appearance.
- Extract UI components from `components/hexagonal-control-center.tsx` into focused files.
- Keep Tauri frameless behavior unchanged.

## Plan

### 1) Settings window category expansion
- Add structured placeholder panels for:
  - Voice & Audio
  - Agent & Memory
  - Automation
  - System Integration
  - Monitoring & Logs
- Include section headers + short descriptive copy (no backend wiring yet).
- Keep the current search bar + bottom bar.

### 2) Component extraction (no behavior change)
Create components folder (if not present): `components/iris/`

- `components/iris/iris-orb.tsx`
  - Extract IrisOrb component as-is.
  - Keep drag + glow animation behavior identical.

- `components/iris/hexagonal-node.tsx`
  - Extract HexagonalNode (main & sub nodes).
  - Preserve spiral animation props and glow logic.

- `components/iris/voice-activity-overlay.tsx`
  - Extract VoiceActivityOverlay for waveform/transcript state display.

- (Optional in same pass if safe)
  - `components/iris/edge-to-edge-line.tsx`
  - `components/iris/settings-window.tsx`

Update `hexagonal-control-center.tsx` imports and ensure no runtime behavior changes.

### 3) Wiring verification
- Confirm line drawing, orb glow overrides, and orbit sizes remain intact.
- Confirm settings open/close, shortcut, and overlay dimming are unaffected.

## Validation
- Open settings window: all categories render without layout break.
- Node expansions still animate correctly.
- Drag to move still works.

## Notes
- Avoid touching any Tauri window configuration code.
- Keep all animation constants exactly aligned with PRD.
