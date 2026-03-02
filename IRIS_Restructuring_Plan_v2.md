# IRIS — Content & Terminology Restructuring Plan (v2)

**Updated:** Incorporates Part 7 answers, adds MCP Servers / Skills / Workflows management, corrects wake word architecture, removes Agent/Speech section, and locks analytics as display-only.

---

## Part 1 — The Core Idea (unchanged)

The word **"node"** was overloaded. Going forward:

| Term | Meaning | Example |
|------|---------|---------|
| **Node** | One of the 6 hexagonal main categories | Voice, Agent, Automate... |
| **Section** | A grouping tab inside a Node | Voice → Input, Voice → Output |
| **Card** | An individual config unit in the WheelView ring | `microphone-card`, `models-card` |
| **Field** | A single configurable item inside a Card | `input_device`, `tts_voice` |

### ID Format Rules

```
Node IDs     →  single word, lowercase        'voice'  'agent'  'system'
Section IDs  →  snake_case                    'input'  'model_selection'  'inference_mode'
Card IDs     →  kebab-case + -card suffix     'microphone-card'  'speech-card'
Field IDs    →  snake_case                    'input_device'  'tts_voice'
```

The `-card` suffix on all Card IDs is new. It makes it impossible to confuse a Card ID with a Section ID at a glance, even when both are present in the same file.

---

## Part 2 — Answers to Part 7 Questions (now locked in)

**Q1 — TTS voice and speaking rate:** Confirmed moved to **Voice → Output** as `speech-card`. Field IDs `tts_voice` and `speaking_rate` are unchanged. The `speech` section under Agent is removed entirely.

**Q2 — Internet access:** Confirmed in `memory-card` under **Agent → Memory**. Field ID `internet_access` (toggle).

**Q3 — Wake word:** Confirmed single location: **Voice → Input** only. Agent/Wake section is removed. The wake word dropdown populates from `get_wake_words` which calls `WakeWordDiscovery.get_discovered_files()` — this already scans the Picovoice directory and returns both preinstalled keywords and any custom `.ppn` files you trained. Your trained wake word will appear in the same list as "Hey Siri", "Alexa", etc. with its `display_name` shown to the user. No special handling needed — it just works once the event dispatcher (BUG-02) is fixed.

**Q4 — Agent/Speech:** Confirmed removed. No remaining speech fields under Agent.

**Q5 — Monitor/Analytics:** Confirmed display-only. No editable fields — only status indicators and action buttons. Backend can be wired later without changing the UI structure.

---

## Part 3 — MCP Servers, Skills, and Workflows

This is the new content that needs to be planned before writing the data file.

### What Exists in the Backend Right Now

From `tool_bridge.py`, there are exactly **5 built-in MCP servers** that are always present:

| Server Key | What It Does |
|-----------|-------------|
| `browser` | Web browsing, open URLs, search |
| `app_launcher` | Launch apps, open files |
| `system` | System info, lock screen, shutdown, restart |
| `file_manager` | Read/write/list/create/delete files |
| `gui_automation` | Click, type, GUI automation |

There is also a `vision` category (screen capture, element detection, screen analysis) handled separately through `VisionModelClient` and `NativeGUIOperator`.

These are built-in and always available. The user should be able to **see** them and **toggle them on/off** individually, but not add or remove them.

### What Doesn't Exist Yet (Needs Frontend + Backend Planning)

**External MCP Servers** — User-registered MCP servers beyond the 5 built-ins. A user might want to add a custom MCP server (e.g. a home automation server, a database tool, a cloud storage server). Each external server needs: a name, a transport type (stdio or HTTP/SSE), a command or URL, and an enabled/disabled toggle.

**Skills** — Reusable prompt templates or behavior presets that the agent can load. Think of them as personality overlays or task-specific instruction sets (e.g. "Code Review Mode", "Research Assistant", "Email Composer"). Each skill has a name, a description, a prompt file or inline text, and an enabled toggle. Only one skill can be active at a time (or none — default behavior).

**Workflows** — Saved multi-step task sequences the agent can execute on demand. A workflow is a named sequence of actions (tool calls, prompts, conditionals) that the user can trigger by voice or hotkey. Each workflow has a name, a trigger phrase, a definition (JSON or YAML), and an enabled toggle.

### Where These Live in the Navigation

All three belong under **AUTOMATE**, not under Agent. The reasoning: MCP servers are the tool layer, skills modify agent behavior but from a capability perspective, and workflows are automation sequences. These are all automation infrastructure. Agent only owns the AI reasoning configuration (which models, how they reason, memory, personality).

The existing Automate structure gets a new Section: **`extensions`**

This section contains three Cards:

1. `mcp-servers-card` — manage all MCP servers (built-in toggle + external server management)
2. `skills-card` — manage agent skills/presets
3. `workflows-card` — manage saved workflows

---

## Part 4 — Complete Corrected Content Structure

---

### 🎤 VOICE

*Audio input pipeline, wake word detection, audio output, speech synthesis, and audio model.*

**Section: `input`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `microphone-card` | Microphone | `input_device` (dropdown, runtime via `get_audio_devices`), `input_gain` (slider 0–100%), `noise_suppression` (toggle), `echo_cancellation` (toggle) |
| `wake-word-card` | Wake Word | `wake_phrase` (dropdown, runtime via `get_wake_words` — includes Picovoice preinstalled + your trained `.ppn`), `wake_sensitivity` (slider 1–10), `always_listening` (toggle) |

**Section: `output`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `speaker-card` | Speaker | `output_device` (dropdown, runtime), `output_volume` (slider 0–100%) |
| `speech-card` | Voice Synthesis | `tts_voice` (dropdown: Nova/Alloy/Echo/Fable/Onyx/Shimmer), `speaking_rate` (slider 50–200%), `tts_enabled` (toggle) |

**Section: `processing`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `voice-engine-card` | Voice Engine | `voice_engine` (toggle), `vad_threshold` (slider 1–10), `silence_timeout` (slider 500–5000ms), `audio_enhancement` (toggle) |

**Section: `model`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `audio-model-card` | Audio Model | `audio_model_version` (dropdown: LFM 2.5 Audio / LFM 2.5 Audio Lite), `inference_device` (dropdown: Auto / CUDA GPU / CPU), `streaming_mode` (toggle) |

---

### 🤖 AGENT

*Model selection, inference backend, personality, and memory. No voice/speech fields here.*

**Section: `model_selection`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `models-card` | Models | `reasoning_model` (dropdown, runtime), `tool_execution_model` (dropdown, runtime) |

**Section: `inference_mode`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `inference-card` | Inference | `inference_mode` (dropdown: Local Models / VPS Gateway / OpenAI API), then conditional fields: |

Conditional fields shown inside `inference-card` based on `inference_mode`:

- **Local Models selected:** `local_gpu_warning` (info/text: "Requires ~20 GB VRAM")
- **VPS Gateway selected:** `vps_url` (text), `vps_api_key` (text/password), `test_vps_connection` (custom button → sends `test_connection` with `connection_type: "vps"`)
- **OpenAI API selected:** `openai_api_key` (text/password), `test_openai_connection` (custom button → sends `test_connection` with `connection_type: "openai"`)

The `test_connection` message type already exists in `iris_gateway.py` (`_handle_test_connection`). The frontend button just needs to send `{ type: "test_connection", payload: { connection_type: "openai" } }`.

**Section: `identity`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `personality-card` | Personality | `assistant_name` (text, default: IRIS), `personality_style` (dropdown: Professional / Casual / Concise / Detailed / Friendly), `response_length` (dropdown: Brief / Balanced / Detailed), `proactive_suggestions` (toggle) |

**Section: `memory`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `memory-card` | Memory | `memory_enabled` (toggle), `memory_window` (slider 5–50 msgs), `persist_across_sessions` (toggle), `internet_access` (toggle — controls `AgentKernel._internet_access_enabled`), `clear_memory` (custom button) |

---

### ⚡ AUTOMATE

*MCP tool permissions, vision, workflows, shortcuts, GUI automation, and the new extensions system (external MCP servers, skills, saved workflows).*

**Section: `tools`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `tool-permissions-card` | Tool Access | `tool_browser` (toggle), `tool_file_system` (toggle), `tool_system_commands` (toggle), `tool_app_control` (toggle), `tool_timeout` (slider 5–60s) |

These 5 toggles map directly to the 5 built-in `_mcp_servers` in `AgentToolBridge`. When a toggle is off, the corresponding server's tools are excluded from `get_available_tools()` response.

**Section: `vision`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `vision-card` | Vision | `screen_capture_enabled` (toggle), `vision_model` (dropdown: Auto / GPT-4o Vision / Local), `capture_interval` (slider 1–30s) |

**Section: `workflows`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `workflows-card` | Workflows | `workflow_auto_save` (toggle), `max_workflow_steps` (slider 5–100), `workflow_retry_on_fail` (toggle) |

**Section: `shortcuts`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `shortcuts-card` | Shortcuts | `voice_shortcut_enabled` (toggle), `global_hotkey` (text, default: Ctrl+Shift+Space), `shortcut_feedback` (toggle) |

**Section: `gui`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `gui-card` | GUI Control | `gui_automation_enabled` (toggle), `click_delay` (slider 50–1000ms), `safe_mode` (toggle, default: true) |

**Section: `extensions`** ← NEW

This section is new. It contains three Cards for managing the extensibility layer.

| Card ID | Label | Fields |
|---------|-------|--------|
| `mcp-servers-card` | MCP Servers | See detail below |
| `skills-card` | Skills | See detail below |
| `saved-workflows-card` | Saved Workflows | See detail below |

#### `mcp-servers-card` — MCP Server Management

```
Fields:
  server_browser      (toggle)  — Built-in: Browser
  server_file         (toggle)  — Built-in: File Manager  
  server_system       (toggle)  — Built-in: System
  server_app          (toggle)  — Built-in: App Launcher
  server_gui          (toggle)  — Built-in: GUI Automation

  add_external_server (custom button) → opens inline form or modal:
    external_server_name      (text)     "My Home Server"
    external_server_transport (dropdown) stdio / HTTP+SSE
    external_server_command   (text)     command string (for stdio)
    external_server_url       (text)     endpoint URL (for HTTP)
    external_server_enabled   (toggle)   
    save_external_server      (custom button)

  [Dynamic list of any added external servers, each with a toggle and remove button]
```

**Backend message needed:** `manage_mcp_server` with actions `add`, `remove`, `toggle`. This does not exist yet and needs to be added to `iris_gateway.py`.

#### `skills-card` — Agent Skill/Preset Management

```
Fields:
  active_skill        (dropdown)  None / [list of installed skills]
  skill_description   (text, readonly) — shows description of selected skill

  add_skill           (custom button) → inline form:
    skill_name        (text)     
    skill_description (text)
    skill_prompt      (text, multiline) — the system prompt override
    save_skill        (custom button)

  [Dynamic list of installed skills, each with an activate button and remove button]
```

**Backend message needed:** `manage_skill` with actions `add`, `remove`, `activate`, `deactivate`. This does not exist yet.

Skills are stored as JSON files in a `/skills` directory. The backend `PersonalityManager` (already referenced in `agent_kernel.py`) is the natural home for skill loading — it already manages personality/system prompt behavior.

#### `saved-workflows-card` — Saved Workflow Management

```
Fields:
  import_workflow     (custom button) — import a workflow from a JSON/YAML file
  create_workflow     (custom button) — open workflow builder (future feature)

  [Dynamic list of saved workflows, each with:]
    - Name display
    - Trigger phrase display
    - Enabled toggle
    - Run now button
    - Remove button
```

**Backend message needed:** `manage_workflow` with actions `import`, `remove`, `toggle`, `run`. This does not exist yet.

Workflows are stored as JSON files in a `/workflows` directory. The backend needs a `WorkflowManager` class (does not exist yet) that can load, save, enable/disable, and execute workflow definitions.

> **Implementation note:** The Card field definitions for `mcp-servers-card`, `skills-card`, and `saved-workflows-card` are different from normal Cards. They render dynamic lists, not just static form fields. These Cards will need a custom render path in `SidePanel.tsx` similar to how `theme-mode` gets special treatment. The Card IDs trigger a `case` in the SidePanel renderer that shows the appropriate management UI instead of the standard field list.

---

### 🖥️ SYSTEM

*Application's relationship with the OS: power management, window settings, storage, and connection.*

**Section: `power`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `power-card` | Power | `startup_with_system` (toggle), `background_mode` (toggle), `idle_timeout` (slider 1–60 min), `low_power_mode` (toggle) |

**Section: `display`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `window-card` | Window | `window_opacity` (slider 30–100%), `always_on_top` (toggle), `animations_enabled` (toggle), `reduced_motion` (toggle) |

**Section: `storage`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `storage-card` | Storage | `log_retention_days` (slider 1–90 days), `auto_cleanup` (toggle), `cache_models` (toggle), `run_cleanup` (custom button → sends `execute_cleanup`) |

The `execute_cleanup` message type already exists in `iris_gateway.py` (`_handle_execute_cleanup`). Wire the button directly.

**Section: `network`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `connection-card` | Connection | `backend_host` (text, default: localhost), `backend_port` (text, default: 8000), `websocket_reconnect` (toggle), `check_connection` (custom button → sends `test_connection`) |

---

### 🎨 CUSTOMIZE

*How IRIS looks and behaves as a desktop application.*

**Section: `theme`** — Local only, no backend sync

| Card ID | Label | Fields |
|---------|-------|--------|
| `theme-card` | Theme | `active_theme` (dropdown), `brand_hue` (slider), `brand_saturation` (slider), `brand_lightness` (slider), `base_plate_hue` (slider), `base_plate_saturation` (slider), `base_plate_lightness` (slider), `reset_to_defaults` (custom button) |

This Card is already working correctly. Do not change anything about it or how WheelView handles its real-time sync via BrandColorContext.

**Section: `startup`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `startup-card` | Startup | `startup_view` (dropdown: Navigation / Chat / Minimized), `preload_models` (toggle), `show_splash` (toggle), `auto_connect_ws` (toggle) |

**Section: `behavior`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `behavior-card` | Behavior | `double_click_voice` (toggle), `auto_close_panel` (toggle), `confirm_before_action` (toggle), `click_sound` (toggle) |

**Section: `notifications`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `notifications-card` | Notifications | `notify_task_complete` (toggle), `notify_errors` (toggle), `notify_wake_detected` (toggle), `notification_sound` (toggle) |

---

### 📊 MONITOR

*Status display only. No editable fields. All interactive elements are action buttons. Analytics backend wired later.*

**Section: `analytics`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `analytics-card` | Analytics | `view_session_stats` (custom button), `view_tool_usage` (custom button), `export_report` (custom button) |

No toggles. No dropdowns. No sliders. When the analytics backend exists, these buttons open a data view. Until then they show a "Coming soon" state in the handler.

**Section: `logs`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `logs-card` | Logs | `log_level` (dropdown: DEBUG / INFO / WARNING / ERROR), `log_to_file` (toggle), `clear_logs` (custom button) |

Logs is the one Monitor section that has real functional fields because log level and log-to-file are operational settings, not analytics.

**Section: `diagnostics`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `diagnostics-card` | Diagnostics | `run_diagnostics` (custom button), `check_microphone` (custom button → triggers `get_audio_devices`), `check_backend` (custom button → triggers `test_connection`), `show_gpu_stats` (custom button) |

**Section: `updates`**

| Card ID | Label | Fields |
|---------|-------|--------|
| `updates-card` | Updates | `update_channel` (dropdown: Stable / Beta / Nightly), `check_for_updates` (custom button), `auto_update` (toggle) |

---

## Part 5 — What Changes and What Stays the Same

### Untouched

- `WheelView.tsx` — structure unchanged
- `DualRingMechanism.tsx` — untouched
- `SidePanel.tsx` — only 5 Card ID string values updated
- `BrandColorContext` — untouched
- `navigation-ids.ts` — Section IDs are already correct
- Both form field sets — both stay, see Part 1 of previous plan for rationale
- `iris_gateway.py` — no changes needed for phase 1 (extensions require new messages in phase 2)

### Files That Change

#### `mini-nodes.ts` — Full replacement

Use the content tables in Part 4. Keep `getMiniNodesForSubnode(sectionId)` as the export function name. The internal type can be renamed from `MiniNode` to `CardDefinition` if desired, but the structural shape must remain identical so NavigationContext doesn't break.

The `extensions` section Cards (`mcp-servers-card`, `skills-card`, `saved-workflows-card`) are defined here like any other Card, but their `fields` arrays are marked with a `renderAs: 'manager'` custom property so SidePanel knows to use the management renderer instead of the standard field renderer.

#### `navigation-constants.ts` — Card ID keys updated

```typescript
// Card ID keys use new -card suffix format
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
```

Note the constant is renamed from `MININODE_TO_SUBNODE_ID` to `CARD_TO_SECTION_ID` to reflect the new terminology.

#### `SidePanel.tsx` — 5 string value updates

```typescript
// Update these Card ID references (string values only, no logic changes):

card.id === 'inference-card'         // was 'inference-mode-config'
card.id === 'microphone-card'        // was 'input-device'
card.id === 'speaker-card'           // was 'output-device'
card.id === 'wake-word-card'         // was 'wake-word'
card.id === 'models-card'            // was 'model-selection-config'
```

Also add a case for the manager Cards:
```typescript
if (['mcp-servers-card', 'skills-card', 'saved-workflows-card'].includes(card.id)) {
  return <ExtensionManagerPanel cardId={card.id} />  // new component, phase 2
}
```

#### `dark-glass-dashboard.tsx` — Remove hardcoded SUB_NODES_DATA

Replace the 175-line hardcoded `SUB_NODES_DATA` constant with a derived structure built from `getMiniNodesForSubnode`. Add a `SECTION_TO_LABEL` and `SECTION_TO_ICON` lookup. This ensures both surfaces always show the same content.

#### `navigation-ids.ts` — Add `extensions` Section ID

```typescript
export const SUB_NODE_IDS = {
  // ...existing...
  AUTOMATE_EXTENSIONS: 'extensions',   // ← add this
} as const
```

Update `CATEGORY_TO_SUBNODES` in `NavigationContext.tsx`:
```typescript
[MAIN_CATEGORY_IDS.AUTOMATE]: [
  SUB_NODE_IDS.AUTOMATE_TOOLS,
  SUB_NODE_IDS.AUTOMATE_VISION,
  SUB_NODE_IDS.AUTOMATE_WORKFLOWS,
  SUB_NODE_IDS.AUTOMATE_SHORTCUTS,
  SUB_NODE_IDS.AUTOMATE_GUI,
  SUB_NODE_IDS.AUTOMATE_EXTENSIONS,   // ← add this
],
```

---

## Part 6 — New Backend Messages Required (Phase 2)

These are not needed to complete the data restructuring. They are needed when you build out the Extensions UI. Document them now so backend work can happen in parallel with frontend.

### MCP Server Management

```python
# iris_gateway.py — add to handle_message routing:
elif msg_type in ["manage_mcp_server", "get_mcp_servers"]:
    await self._handle_mcp_servers(session_id, client_id, message)
```

```python
# _handle_mcp_servers actions:
# action: "list"    → returns built-in servers + registered external servers with status
# action: "toggle"  → enable/disable a server by server_id
# action: "add"     → register a new external MCP server (name, transport, command/url)
# action: "remove"  → remove an external server by server_id
# action: "test"    → test connectivity to an external server
```

### Skills Management

```python
# iris_gateway.py — add to handle_message routing:
elif msg_type in ["manage_skill", "get_skills"]:
    await self._handle_skills(session_id, client_id, message)
```

```python
# _handle_skills actions:
# action: "list"       → returns all installed skills with name, description, active status
# action: "activate"   → load a skill's system prompt into PersonalityManager
# action: "deactivate" → clear active skill, return to default behavior
# action: "add"        → save new skill JSON to /skills directory
# action: "remove"     → delete skill file
```

### Workflow Management

```python
# iris_gateway.py — add to handle_message routing:
elif msg_type in ["manage_workflow", "get_workflows"]:
    await self._handle_workflows(session_id, client_id, message)
```

```python
# _handle_workflows actions:
# action: "list"    → returns all saved workflows with name, trigger, enabled status
# action: "import"  → save imported workflow JSON/YAML to /workflows directory
# action: "remove"  → delete workflow file
# action: "toggle"  → enable/disable a workflow
# action: "run"     → immediately execute a workflow by ID
```

---

## Part 7 — Implementation Order

### Phase 1 — Data restructuring (do this now, no backend changes needed)

1. Add `AUTOMATE_EXTENSIONS: 'extensions'` to `navigation-ids.ts`
2. Update `CATEGORY_TO_SUBNODES` in `NavigationContext.tsx` to include `extensions`
3. Rewrite `mini-nodes.ts` using Part 4 content tables
4. Rewrite `navigation-constants.ts` with new Card IDs and renamed constant
5. Update 5 Card ID string values in `SidePanel.tsx`
6. Replace hardcoded `SUB_NODES_DATA` in `dark-glass-dashboard.tsx` with derived lookup

Test after each step. Step 3 is the most impactful — after it, the WheelView ring will show correct Card labels and fields for every Section.

### Phase 2 — Extensions UI (after phase 1 is stable)

1. Add `manage_mcp_server`, `manage_skill`, `manage_workflow` message handlers to `iris_gateway.py`
2. Create `ExtensionManagerPanel` component for the 3 manager Cards
3. Wire up the manager Cards in `SidePanel.tsx`
4. Add `WorkflowManager` and `SkillManager` classes to the backend agent module

### Phase 3 — Variable renaming (last, cosmetic only)

Rename `miniNodeStack → cardRing`, `miniNodeValues → cardValues`, etc. in `NavigationContext.tsx` and all consumers. Do this last — it affects the most files and has zero functional impact. Greping for each old name before renaming is essential.

---

## Part 8 — Wake Word Implementation Detail

Since this is a common source of confusion, here is exactly how the wake word flow works end-to-end with the existing backend:

1. `IRISGateway.__init__()` creates a `WakeWordDiscovery` instance and calls `scan_directory()`
2. `scan_directory()` looks in the Picovoice resources directory for `.ppn` files (keywords) and `.pv` files (models)
3. It returns both the preinstalled Picovoice keywords (hey_siri, alexa, etc.) AND any custom `.ppn` files you trained
4. Each entry has a `display_name` — for custom files, this is derived from the filename (e.g. `iris_wakeword_en_mac.ppn` → "Iris Wakeword")
5. Frontend sends `get_wake_words` → backend responds with `wake_words_list` payload containing the full array
6. The `wake-word-card` dropdown shows `display_name` values to the user
7. When user selects one, frontend sends `select_wake_word` with `payload: { filename: "iris_wakeword_en_mac.ppn" }`
8. Backend calls `_handle_select_wake_word` which loads that `.ppn` file into `PorcupineDetector`

The only thing needed on the frontend is making sure the `wake-word-card` dropdown uses `display_name` as the label and `filename` as the value, and that selecting one sends `select_wake_word` instead of `update_field`.

This means `wake_phrase` in `wake-word-card` is a **special field** — it doesn't go through the normal `update_field` path. The SidePanel needs a case:

```typescript
if (card.id === 'wake-word-card' && field.id === 'wake_phrase') {
  sendMessage('select_wake_word', { filename: value })
  // Also update local card value for UI display
  updateCardValue('wake-word-card', 'wake_phrase', value)
  return  // Don't send update_field
}
```

This special case belongs in WheelView's `handleValueChange` and/or in SidePanel's `onValueChange` handler.

---

*Phase 1 can start immediately. Phase 2 can begin in parallel once the backend messages are stubbed out.*
