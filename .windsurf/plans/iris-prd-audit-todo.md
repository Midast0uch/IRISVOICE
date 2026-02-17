# IRIS PRD Audit TODO

## Current Status: COMPLETED
## Last Reviewed: 2026-02-01

### Completed
- [x] Settings button, settings window overlay, keyboard shortcut, and glow color wiring
- [x] Component extraction: IrisOrb, HexagonalNode, VoiceActivityOverlay, ConfirmedOrbitNode, EdgeToEdgeLine
- [x] Settings window expanded with all 6 categories (Voice & Audio, Agent & Memory, Automation, System Integration, Appearance, Monitoring & Logs)
- [x] Glassmorphic theme applied to all settings panels
- [x] Mini-node stack configuration aligned (180px size, 260px distance)
- [x] Confirmed orbit radius aligned (260px)
- [x] Edge-to-edge animated lines between subnodes and mini-nodes
- [x] State 6 voice-active UI: waveform, transcript placeholder, state-specific colors
- [x] Theme: state color overrides toggle + per-state color pickers + hex input/presets
- [x] Backend: extended ColorTheme model with state color fields
- [x] Backend: state color persistence via theme.json
- [x] WebSocket: theme state sync includes state colors
- [x] Frontend: WebSocket hook receives state colors from backend
- [x] Frontend: Update settings window to send state colors via updateTheme
- [x] Frontend: Update HexagonalControlCenter to use theme.state_colors_enabled

### Notes
- State colors now flow: settings UI → WebSocket → backend → theme.json → frontend on reconnect
- End-to-end persistence verified complete
