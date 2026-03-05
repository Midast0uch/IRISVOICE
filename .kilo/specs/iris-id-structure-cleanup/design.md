# Design: IRIS ID Structure Cleanup & Alignment

## Overview

This design aligns the frontend UI cards with backend data sections, introduces user-friendly terminology, and creates the missing backend infrastructure. The key architectural decision is to **align backend to frontend** (Option 2) because the frontend already has the desired user experience structure.

Key changes:
- **CREATE** 4 new backend sections: `model_selection`, `inference_mode`, `skills`, `profile`
- **EXPOSE** 2 existing backend sections: `wake`, `speech` (already exist, just need frontend cards)
- **RENAME** `gui` section to `desktop_control` with better field names
- **SPLIT** wake/speech fields out of `input`/`output` sections
- **REMOVE** 6 unused cards and 1 backend section
- **ALIGN** mismatched field IDs across frontend and backend
- **MIGRATE** user data from old section names to new ones
- **ADD** missing fields that only exist on one side

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND LAYER                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  mini-nodes.ts          navigation-constants.ts                  │
│  (Card definitions)     (CARD_TO_SECTION_ID mapping)             │
│       │                         │                                │
│       └──────────┬──────────────┘                                │
│                  │                                               │
│           WheelView.tsx                                          │
│                  │                                               │
│       DarkGlassDashboard.tsx                                     │
│                  │                                               │
│           FieldRow (component)                                   │
│                  │                                               │
│       WebSocket Messages                                         │
│       (update_field, confirm)                                    │
│                  │                                               │
└──────────────────┼───────────────────────────────────────────────┘
                   │
┌──────────────────┼───────────────────────────────────────────────┐
│                  │        BACKEND LAYER                           │
├──────────────────┼───────────────────────────────────────────────┤
│                  │                                               │
│       ws_manager.py (WebSocket handler)                          │
│                  │                                               │
│       models.py (SUBNODE_CONFIGS)                                │
│                  │                                               │
│       state_manager.py (persist to JSON)                         │
│                  │                                               │
│       Session Files                                              │
│       (agent.json, voice.json, etc.)                             │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Components

**Frontend:**
1. **mini-nodes.ts** - Card definitions with fields (modified)
2. **navigation-constants.ts** - CARD_TO_SECTION_ID mapping (modified)
3. **WheelView.tsx** - Navigation wheel (no changes needed)
4. **DarkGlassDashboard.tsx** - Dashboard rendering (no changes needed)
5. **types/navigation.ts** - TypeScript types (add new types)

**Backend:**
1. **models.py** - SUBNODE_CONFIGS with new sections
2. **ws_manager.py** - Handle new section IDs in WebSocket messages
3. **state_manager.py** - Persist new sections to JSON files
4. **config/session_config.py** - Update default session configs

## Data Models

### New Backend Sections (models.py)

```python
# model_selection section
{
    "id": "model_selection",
    "label": "Model Selection",
    "fields": [
        {"id": "model_provider", "type": "DROPDOWN", "label": "Provider", 
         "options": ["local", "api", "vps"], "value": "local"},
        {"id": "use_same_model", "type": "TOGGLE", "label": "Use Same Model for Both", 
         "value": True},
        {"id": "reasoning_model", "type": "DROPDOWN", "label": "Reasoning Model", 
         "options": [], "value": "", "lazy_load": True},
        {"id": "tool_model", "type": "DROPDOWN", "label": "Tool Model", 
         "options": [], "value": "", "lazy_load": True},
        {"id": "api_key", "type": "TEXT", "label": "API Key", 
         "value": ""},
        {"id": "vps_endpoint", "type": "TEXT", "label": "VPS Endpoint", 
         "value": ""},
    ]
}

# inference_mode section (SIMPLIFIED)
{
    "id": "inference_mode",
    "label": "Inference Mode",
    "fields": [
        {"id": "agent_thinking_style", "type": "DROPDOWN", "label": "Agent Thinking Style",
         "options": ["concise", "balanced", "thorough"], "value": "balanced"},
        {"id": "max_response_length", "type": "DROPDOWN", "label": "Max Response Length",
         "options": ["short", "medium", "long"], "value": "medium"},
        {"id": "reasoning_effort", "type": "DROPDOWN", "label": "Reasoning Effort",
         "options": ["fast", "balanced", "accurate"], "value": "balanced"},
        {"id": "tool_mode", "type": "DROPDOWN", "label": "Tool Mode",
         "options": ["auto", "ask_first", "disabled"], "value": "auto"},
    ]
}

# skills section
{
    "id": "skills",
    "label": "Skills",
    "fields": [
        {"id": "skill_creation_enabled", "type": "TOGGLE", 
         "label": "Allow Agent to Create Skills", "value": True},
        {"id": "skills_list", "type": "DISPLAY", 
         "label": "Learned Skills", "value": []},
    ]
}

# profile section
{
    "id": "profile",
    "label": "Profile",
    "fields": [
        {"id": "user_profile_display", "type": "DISPLAY",
         "label": "Your Profile", "value": {}},
        {"id": "active_mode", "type": "DROPDOWN",
         "label": "Active Mode", "options": [], "value": "default"},
        {"id": "modes_list", "type": "DISPLAY",
         "label": "Your Modes", "value": []},
    ]
}

# desktop_control section (renamed from gui)
{
    "id": "desktop_control",
    "label": "Desktop Control",
    "fields": [
        {"id": "desktop_control_enabled", "type": "TOGGLE",
         "label": "Enable Desktop Control", "value": False},
        {"id": "require_confirmation", "type": "TOGGLE",
         "label": "Ask Before Actions", "value": True},
        {"id": "use_vision_guidance", "type": "TOGGLE",
         "label": "Use Screen Vision", "value": False},
    ]
}

# wake section (new - split from input)
{
    "id": "wake",
    "label": "Wake Word",
    "fields": [
        {"id": "wake_word_enabled", "type": "TOGGLE", "value": True},
        {"id": "wake_phrase", "type": "DROPDOWN",
         "options": ["jarvis", "hey computer", "computer", "custom"], "value": "jarvis"},
        {"id": "detection_sensitivity", "type": "SLIDER", "min": 0, "max": 100, "value": 50},
        {"id": "activation_sound", "type": "TOGGLE", "value": True},
    ]
}

# speech section (new - split from output)
{
    "id": "speech",
    "label": "Speech",
    "fields": [
        {"id": "tts_enabled", "type": "TOGGLE", "value": True},
        {"id": "tts_voice", "type": "DROPDOWN",
         "options": ["Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"], "value": "Nova"},
        {"id": "speaking_rate", "type": "SLIDER", "min": 0.5, "max": 2.0, "step": 0.1, "value": 1.0},
    ]
}
```

### Modified Frontend Cards (mini-nodes.ts)

```typescript
// wake-word-card (moved fields from input)
{
  id: 'wake-word-card',
  label: 'Wake Word',
  section: 'wake',  // Changed from 'input'
  fields: [
    { id: 'wake_word_enabled', type: 'toggle', label: 'Wake Word Enabled' },
    { id: 'wake_phrase', type: 'dropdown', label: 'Wake Phrase', 
      options: ['jarvis', 'hey computer', 'computer', 'custom'] },
    { id: 'detection_sensitivity', type: 'slider', label: 'Sensitivity', min: 0, max: 100 },
    { id: 'activation_sound', type: 'toggle', label: 'Play Sound on Wake' },
  ]
}

// speech-card (moved fields from output)
{
  id: 'speech-card',
  label: 'Speech',
  section: 'speech',  // Changed from 'output'
  fields: [
    { id: 'tts_enabled', type: 'toggle', label: 'Text-to-Speech Enabled' },
    { id: 'tts_voice', type: 'dropdown', label: 'Voice', 
      options: ['Nova', 'Alloy', 'Echo', 'Fable', 'Onyx', 'Shimmer'] },
    { id: 'speaking_rate', type: 'slider', label: 'Speaking Rate', min: 0.5, max: 2.0, step: 0.1 },
  ]
}

// desktop-control-card (renamed from gui-card)
{
  id: 'desktop-control-card',
  label: 'Desktop Control',
  section: 'desktop_control',  // Changed from 'gui'
  fields: [
    { id: 'desktop_control_enabled', type: 'toggle', label: 'Enable Desktop Control' },
    { id: 'require_confirmation', type: 'toggle', label: 'Ask Before Actions' },
    { id: 'use_vision_guidance', type: 'toggle', label: 'Use Screen Vision' },
  ]
}
```

## API / Interface Changes

### WebSocket Message Handling

**ws_manager.py** needs to handle new section IDs:

```python
# Current handling
VALID_SUBNODE_IDS = {
    'input', 'output', 'processing', 'model',  # VOICE
    'model_selection', 'inference_mode', 'identity', 'memory',  # AGENT (NEW)
    'tools', 'vision', 'workflows', 'shortcuts', 'gui',  # AUTOMATE
    'power', 'display', 'storage', 'network',  # SYSTEM
    'theme', 'startup', 'behavior', 'notifications',  # CUSTOMIZE
    'analytics', 'logs', 'diagnostics', 'updates',  # MONITOR
    # NEW SECTIONS:
    'wake', 'speech', 'skills', 'profile', 'desktop_control',
}
```

### CARD_TO_SECTION_ID Mapping

```typescript
// navigation-constants.ts - Updated mapping
export const CARD_TO_SECTION_ID: Record<string, string> = {
  // Voice (reorganized)
  'microphone-card': 'input',
  'wake-word-card': 'wake',  // Changed from 'input'
  'speaker-card': 'output',
  'speech-card': 'speech',  // Changed from 'output'
  
  // Agent (new cards)
  'models-card': 'model_selection',  // NEW
  'inference-card': 'inference_mode',  // NEW
  'personality-card': 'identity',
  'memory-card': 'memory',
  'skills-card': 'skills',  // NEW
  'profile-card': 'profile',  // NEW
  'tool-permissions-card': 'tools',
  'integrations-card': 'integrations',
  
  // Automate (renamed)
  'vision-card': 'vision',
  'desktop-control-card': 'desktop_control',  // Renamed from 'gui-card'
  
  // System, Customize, Monitor unchanged
  // ...
}
```

## Sequence Diagram

### User Configures Model Selection

```
User                    Frontend                    Backend
 |                         |                            |
 |--Click Models card----->|                            |
 |                         |--Lazy load models--------->|
 |                         |                            |--Query Ollama--|
 |                         |                            |<--Model list---|
 |                         |<--Return models------------|
 |<--Show dropdown---------|                            |
 |                         |                            |
 |--Select model---------->|                            |
 |                         |--WebSocket: update_field-->|
 |                         |  section: model_selection  |
 |                         |  field: reasoning_model    |
 |                         |  value: "lfm2-8b"          |
 |                         |                            |--Update SUBNODE_CONFIGS
 |                         |                            |--Persist to agent.json
 |                         |<--Ack----------------------|
 |<--Show saved indicator--|                            |
```

## Key Design Decisions

### Decision 1: Align Backend to Frontend
**Choice:** Update backend to match frontend structure rather than vice versa
**Rationale:** Frontend already has user-friendly organization; backend should adapt
**Alternatives considered:** Align frontend to backend (rejected - would lose UX improvements)

### Decision 2: Split input/output into input/output/wake/speech
**Choice:** Separate concerns into 4 distinct sections
**Rationale:** Wake word and TTS settings are logically separate from hardware I/O
**Alternatives considered:** Keep consolidated (rejected - confusing for users)

### Decision 3: Simplify Inference Parameters
**Choice:** Replace technical terms with user-friendly options
**Rationale:** Users shouldn't need to understand "temperature" and "max_tokens"
**Alternatives considered:** Keep technical terms (rejected - poor UX)

### Decision 4: Rename GUI to Desktop Control
**Choice:** Use descriptive, user-friendly terminology
**Rationale:** "GUI" is technical jargon; "Desktop Control" is self-explanatory
**Alternatives considered:** "Screen Automation", "Computer Control" (Desktop Control chosen as clearest)

### Decision 5: Code Terminology Standardization
**Choice:** Rename internal code terminology for consistency
**Rationale:** Current mix of "subnode", "mini-node", "section", "card" is confusing
**Terminology Mapping:**

| Old Term | New Term | Location |
|----------|----------|----------|
| `SUBNODE_CONFIGS` | `SECTION_CONFIGS` | backend/models.py |
| `SubNode` | `Section` | backend/models.py |
| `MiniNode` | `Card` | frontend/types/ |
| `subnode_id` | `section_id` | WebSocket messages |
| `card_id` | `card_id` | already correct |

## Error Handling & Edge Cases

| Scenario | Handling |
|----------|----------|
| Backend receives unknown section ID | Log warning, ignore message |
| Lazy load for models fails | Show "No models available" in dropdown |
| Card maps to missing backend section | Show placeholder: "Configuration unavailable" |
| Frontend has field backend doesn't recognize | Ignore field, log warning |
| User switches model provider | Clear model selection, re-trigger lazy load |
| Vision model unavailable when Desktop Control + Vision enabled | Fall back to coordinate-based clicking |

## Testing Strategy

1. **Unit Tests:**
   - Test new backend section configurations validate correctly
   - Test CARD_TO_SECTION_ID mappings are bijective
   - Test lazy-loaded dropdown population

2. **Integration Tests:**
   - Test WebSocket roundtrip for each new section
   - Test settings persist and reload correctly
   - Test conditional field display (e.g., API key only shown when provider=api)

3. **E2E Tests:**
   - User configures Models → Inference → Voice → Speech
   - Verify settings survive page reload
   - Verify removed cards don't appear in UI

## Data Migration Strategy

### Migration Phases

**Phase 1: Backup**
- Copy all session files to `.backup/migration-YYYY-MM-DD/` before any changes

**Phase 2: Section Renames**
```python
# Migration mappings
SECTION_MIGRATIONS = {
    'gui': 'desktop_control',  # Rename section
}

FIELD_MIGRATIONS = {
    'input': {
        'wake_word_enabled': ('wake', 'wake_word_enabled'),
        'wake_word_sensitivity': ('wake', 'detection_sensitivity'),
    },
    'output': {
        'tts_enabled': ('speech', 'tts_enabled'),
        'tts_voice': ('speech', 'tts_voice'),
        'tts_speed': ('speech', 'speaking_rate'),
    },
    'gui': {
        'gui_enabled': ('desktop_control', 'desktop_control_enabled'),
        'gui_precision': (None, None),  # Remove - not in new design
    }
}
```

**Phase 3: Field Alignment**
- Rename `assistant_name` → `agent_name` in identity section
- Rename `personality` → `persona` in identity section
- Align volume field names (decide on `input_volume` vs `input_sensitivity`)

**Phase 4: Validation**
- Verify all migrations completed successfully
- Log any errors for manual review

### Rollback Plan
1. If migration fails, restore from backup
2. Keep backup for 30 days
3. Log all changes for audit trail

## Security & Performance Considerations

1. **API Key Storage:** Store in backend only, never expose in frontend
2. **Lazy Loading:** Don't fetch model lists until card is opened
3. **Confirmation for Desktop Control:** Always require confirmation for destructive actions
4. **Vision Model Costs:** Warn users if using cloud vision providers
5. **Session Isolation:** New sections respect existing session isolation
6. **Data Migration Safety:** Backup all user data before migration, support rollback
