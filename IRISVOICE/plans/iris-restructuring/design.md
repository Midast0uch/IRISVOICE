# IRIS Content & Terminology Restructuring - Design

## Architecture Overview

This restructuring modifies the frontend navigation data layer without changing the visual structure or backend API (except for Phase 2 extensions). The key principle is: **centralize definitions in `mini-nodes.ts` and derive all other representations from it**.

---

## File Changes Map

### Files to Modify

| File | Change Type | Description |
|------|-------------|-------------|
| `data/mini-nodes.ts` | Full replacement | Complete Card definitions with new `-card` IDs |
| `data/navigation-ids.ts` | Add/Remove | Add `AUTOMATE_EXTENSIONS`, remove `AGENT_WAKE`, `AGENT_SPEECH` |
| `contexts/NavigationContext.tsx` | Update | Update `CATEGORY_TO_SUBNODES` mapping |
| `components/wheel-view/SidePanel.tsx` | String updates | Update 5 Card ID string references |
| `components/dark-glass-dashboard.tsx` | Refactor | Replace hardcoded `SUB_NODES_DATA` with derived structure |
| `data/navigation-constants.ts` | Create new | Add `CARD_TO_SECTION_ID` mapping constant |

### Files Unchanged

| File | Reason |
|------|--------|
| `wheel-view/WheelView.tsx` | Structure unchanged, only data changes |
| `wheel-view/DualRingMechanism.tsx` | No dependencies on Card IDs |
| `contexts/BrandColorContext.tsx` | Independent of navigation structure |
| `types/navigation.ts` | Type definitions remain compatible |

---

## Data Flow

```
┌─────────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│  mini-nodes.ts  │────▶│  NavigationContext  │────▶│   WheelView     │
│  (source of     │     │  (state management) │     │   (renders UI)  │
│   truth)        │     └─────────────────────┘     └─────────────────┘
└─────────────────┘              │                           ▲
         │                       │                           │
         │                       ▼                           │
         │              ┌─────────────────────┐              │
         │              │ dark-glass-dashboard│              │
         └─────────────▶│ (derives from same  │──────────────┘
                        │  source)            │
                        └─────────────────────┘
```

---

## Card ID Mapping (Old → New)

| Old ID | New ID | Section |
|--------|--------|---------|
| `input-device` | `microphone-card` | input |
| `input-sensitivity` | **REMOVE** | — |
| `noise-gate` | **REMOVE** | — |
| `output-device` | `speaker-card` | output |
| `output-volume` | **MERGE** into speaker-card | — |
| `noise-reduction` | `voice-engine-card` | processing |
| `echo-cancellation` | **MERGE** into voice-engine-card | — |
| `voice-model-config` | `audio-model-card` | model |
| `model-selection-config` | `models-card` | model_selection |
| `inference-mode-config` | `inference-card` | inference_mode |
| `agent-name` | **MERGE** into personality-card | — |
| `personality-type` | **MERGE** into personality-card | — |
| `response-style` | **MERGE** into personality-card | — |
| `wake-word` | `wake-word-card` | input |
| `voice-trigger` | **REMOVE** | — |
| `tts-voice` | `speech-card` | output |
| `tts-speed` | **MERGE** into speech-card | — |
| `context-window` | **MERGE** into memory-card | — |
| `memory-persistence` | **MERGE** into memory-card | — |
| `tool-access` | **RENAME** to tool-permissions-card | tools |
| `web-search` | **REMOVE** (move to memory-card) | — |
| `vision-toggle` | **MERGE** into vision-card | — |
| `screen-context` | **MERGE** into vision-card | — |
| `proactive-monitor` | **MERGE** into vision-card | — |

---

## New Cards to Add

### Voice Category

```typescript
{
  id: 'microphone-card',
  label: 'Microphone',
  icon: 'Mic',
  fields: [
    { id: 'input_device', type: 'dropdown', label: 'Device', loadOptions: loadInputDevices, defaultValue: 'Default' },
    { id: 'input_gain', type: 'slider', label: 'Gain', min: 0, max: 100, unit: '%', defaultValue: 75 },
    { id: 'noise_suppression', type: 'toggle', label: 'Noise Suppression', defaultValue: true },
    { id: 'echo_cancellation', type: 'toggle', label: 'Echo Cancellation', defaultValue: true }
  ]
}
```

```typescript
{
  id: 'wake-word-card',
  label: 'Wake Word',
  icon: 'Mic',
  fields: [
    { id: 'wake_phrase', type: 'dropdown', label: 'Phrase', options: [], defaultValue: '' }, // populated via get_wake_words
    { id: 'wake_sensitivity', type: 'slider', label: 'Sensitivity', min: 1, max: 10, defaultValue: 5 },
    { id: 'always_listening', type: 'toggle', label: 'Always Listening', defaultValue: true }
  ]
}
```

```typescript
{
  id: 'speech-card',
  label: 'Voice Synthesis',
  icon: 'Volume2',
  fields: [
    { id: 'tts_voice', type: 'dropdown', label: 'Voice', options: ['Nova', 'Alloy', 'Echo', 'Fable', 'Onyx', 'Shimmer'], defaultValue: 'Nova' },
    { id: 'speaking_rate', type: 'slider', label: 'Speaking Rate', min: 50, max: 200, unit: '%', defaultValue: 100 },
    { id: 'tts_enabled', type: 'toggle', label: 'Enabled', defaultValue: true }
  ]
}
```

### Automate Category

```typescript
// In extensions section
{
  id: 'mcp-servers-card',
  label: 'MCP Servers',
  icon: 'Server',
  renderAs: 'manager',
  fields: [
    { id: 'server_browser', type: 'toggle', label: 'Browser', defaultValue: true },
    { id: 'server_file', type: 'toggle', label: 'File Manager', defaultValue: true },
    { id: 'server_system', type: 'toggle', label: 'System', defaultValue: true },
    { id: 'server_app', type: 'toggle', label: 'App Launcher', defaultValue: true },
    { id: 'server_gui', type: 'toggle', label: 'GUI Automation', defaultValue: true },
    { id: 'add_external_server', type: 'custom', label: 'Add External Server' }
  ]
}
```

```typescript
{
  id: 'skills-card',
  label: 'Skills',
  icon: 'Sparkles',
  renderAs: 'manager',
  fields: [
    { id: 'active_skill', type: 'dropdown', label: 'Active Skill', options: ['None'], defaultValue: 'None' },
    { id: 'skill_description', type: 'text', label: 'Description', defaultValue: '' },
    { id: 'add_skill', type: 'custom', label: 'Add Skill' }
  ]
}
```

```typescript
{
  id: 'saved-workflows-card',
  label: 'Saved Workflows',
  icon: 'Workflow',
  renderAs: 'manager',
  fields: [
    { id: 'import_workflow', type: 'custom', label: 'Import Workflow' },
    { id: 'create_workflow', type: 'custom', label: 'Create Workflow' }
  ]
}
```

---

## Navigation Constants

Create `data/navigation-constants.ts`:

```typescript
/**
 * Maps Card IDs to their parent Section IDs
 * This replaces the old MININODE_TO_SUBNODE_ID constant
 */
export const CARD_TO_SECTION_ID: Record<string, string> = {
  // Voice
  'microphone-card':     'input',
  'wake-word-card':      'input',
  'speaker-card':        'output',
  'speech-card':         'output',
  'voice-engine-card':   'processing',
  'audio-model-card':    'model',

  // Agent
  'models-card':         'model_selection',
  'inference-card':      'inference_mode',
  'personality-card':    'identity',
  'memory-card':         'memory',

  // Automate
  'tool-permissions-card': 'tools',
  'vision-card':           'vision',
  'workflows-card':        'workflows',
  'shortcuts-card':        'shortcuts',
  'gui-card':              'gui',
  'mcp-servers-card':      'extensions',
  'skills-card':           'extensions',
  'saved-workflows-card':  'extensions',

  // System
  'power-card':       'power',
  'window-card':      'display',
  'storage-card':     'storage',
  'connection-card':  'network',

  // Customize — theme-card intentionally omitted (local only)
  'startup-card':       'startup',
  'behavior-card':      'behavior',
  'notifications-card': 'notifications',

  // Monitor
  'analytics-card':    'analytics',
  'logs-card':         'logs',
  'diagnostics-card':  'diagnostics',
  'updates-card':      'updates',
}

/**
 * Section labels for display
 */
export const SECTION_TO_LABEL: Record<string, string> = {
  input: 'Input',
  output: 'Output',
  processing: 'Processing',
  model: 'Model',
  model_selection: 'Model Selection',
  inference_mode: 'Inference Mode',
  identity: 'Identity',
  memory: 'Memory',
  tools: 'Tools',
  vision: 'Vision',
  workflows: 'Workflows',
  shortcuts: 'Shortcuts',
  gui: 'GUI',
  extensions: 'Extensions',
  power: 'Power',
  display: 'Display',
  storage: 'Storage',
  network: 'Network',
  theme: 'Theme',
  startup: 'Startup',
  behavior: 'Behavior',
  notifications: 'Notifications',
  analytics: 'Analytics',
  logs: 'Logs',
  diagnostics: 'Diagnostics',
  updates: 'Updates',
}

/**
 * Section icons mapping
 */
export const SECTION_TO_ICON: Record<string, string> = {
  input: 'Mic',
  output: 'Volume2',
  processing: 'Waves',
  model: 'Brain',
  model_selection: 'BrainCircuit',
  inference_mode: 'Cpu',
  identity: 'User',
  memory: 'Database',
  tools: 'Tool',
  vision: 'Eye',
  workflows: 'GitBranch',
  shortcuts: 'Keyboard',
  gui: 'Monitor',
  extensions: 'Puzzle',
  power: 'Power',
  display: 'Monitor',
  storage: 'HardDrive',
  network: 'Wifi',
  theme: 'Palette',
  startup: 'Rocket',
  behavior: 'Sliders',
  notifications: 'Bell',
  analytics: 'BarChart3',
  logs: 'FileText',
  diagnostics: 'Stethoscope',
  updates: 'RefreshCw',
}
```

---

## SidePanel.tsx Updates

Update these Card ID references (string values only, no logic changes):

```typescript
// Line ~86: Change this
if (miniNode.id === 'model-selection-config') {
// To this
if (miniNode.id === 'models-card') {

// Line ~107: Change this  
if (miniNode.id === 'input-device' || miniNode.id === 'output-device') {
// To this
if (miniNode.id === 'microphone-card' || miniNode.id === 'speaker-card') {

// Line ~131: Change this
if (miniNode.id === 'wake-word') {
// To this
if (miniNode.id === 'wake-word-card') {

// Line ~161: Change this
if (miniNode.id === 'inference-mode-config') {
// To this
if (miniNode.id === 'inference-card') {

// Line ~181-182: Change this
if (miniNode.id === 'model-selection-config' && (field.id === 'reasoning_model' || field.id === 'tool_execution_model')) {
// To this
if (miniNode.id === 'models-card' && (field.id === 'reasoning_model' || field.id === 'tool_execution_model')) {

// Line ~187: Change this
if (miniNode.id === 'input-device' && field.id === 'input_device') {
// To this
if (miniNode.id === 'microphone-card' && field.id === 'input_device') {

// Line ~192: Change this
if (miniNode.id === 'output-device' && field.id === 'output_device') {
// To this
if (miniNode.id === 'speaker-card' && field.id === 'output_device') {

// Line ~197: Change this
if (miniNode.id === 'wake-word' && field.id === 'wake_phrase') {
// To this
if (miniNode.id === 'wake-word-card' && field.id === 'wake_phrase') {
```

---

## Dark Glass Dashboard Refactor

Replace the hardcoded `SUB_NODES_DATA` with a derived structure:

```typescript
import { getMiniNodesForSubnode } from '@/data/mini-nodes';
import { SECTION_TO_LABEL, SECTION_TO_ICON } from '@/data/navigation-constants';
import { SUB_NODE_IDS } from '@/data/navigation-ids';

// Build SUB_NODES_DATA dynamically from mini-nodes.ts
const SUB_NODES_DATA: Record<string, { id: string; label: string; icon: any; fields: any[] }[]> = {};

// Helper to get icon component from string name
function getIconComponent(iconName: string) {
  const icons: Record<string, any> = {
    Mic, Volume2, Brain, Cpu, Bot, /* ... all icons ... */
  };
  return icons[iconName] || Settings;
}

// Build for each main category
Object.entries(CATEGORY_TO_SUBNODES).forEach(([categoryId, subnodeIds]) => {
  SUB_NODES_DATA[categoryId] = subnodeIds.map(subnodeId => {
    const miniNodes = getMiniNodesForSubnode(subnodeId);
    return {
      id: subnodeId,
      label: SECTION_TO_LABEL[subnodeId] || subnodeId.toUpperCase(),
      icon: getIconComponent(SECTION_TO_ICON[subnodeId] || 'Settings'),
      fields: convertMiniNodeFieldsToDashboardFields(miniNodes)
    };
  });
});
```

---

## Type Definitions

The existing `MiniNode` type in `types/navigation.ts` should work without changes:

```typescript
export interface MiniNode {
  id: string           // Card ID (now with -card suffix)
  label: string        // Display label
  icon: string         // Icon name
  fields: FieldConfig[]
  renderAs?: 'manager' // Optional: for extension manager cards
}
```

---

## Testing Strategy

1. **Visual Regression**: Compare WheelView and Dashboard before/after
2. **State Persistence**: Verify settings save/load correctly
3. **Navigation Flow**: Test all 6 main categories and their sections
4. **Card Selection**: Verify each Card opens correct SidePanel
5. **Field Values**: Confirm defaults and user changes persist

---

## Migration Notes

- User settings with old field IDs will reset to defaults (acceptable for this phase)
- Backend message types remain unchanged
- WebSocket protocol unchanged
- Theme/local settings preserved (separate storage key)
