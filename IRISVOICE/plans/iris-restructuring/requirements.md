# IRIS Content & Terminology Restructuring - Requirements

## Overview

Restructure the IRIS navigation system to eliminate terminology confusion and establish clear, consistent naming conventions across the application. The term "node" was overloaded — this restructuring establishes distinct terms: **Node** (main category), **Section** (grouping tab), **Card** (config unit), and **Field** (configurable item).

---

## User Stories

### US-1: Clear Navigation Terminology
**As a** user navigating IRIS settings  
**I want** consistent and clear terminology throughout the interface  
**So that** I can understand where I am and what I'm configuring without confusion

**Acceptance Criteria:**
- [ ] AC-1.1: The hierarchy uses clear terms: Node → Section → Card → Field
- [ ] AC-1.2: All Card IDs use the `-card` suffix (e.g., `microphone-card`, `speech-card`)
- [ ] AC-1.3: Section IDs use `snake_case` format
- [ ] AC-1.4: Field IDs use `snake_case` format
- [ ] AC-1.5: Node IDs use single lowercase word format

### US-2: Voice Settings Consolidation
**As a** user configuring voice settings  
**I want** all voice-related settings in one place  
**So that** I don't have to search across multiple categories

**Acceptance Criteria:**
- [ ] AC-2.1: TTS voice and speaking rate are located in Voice → Output section
- [ ] AC-2.2: Wake word settings are only in Voice → Input section
- [ ] AC-2.3: Agent/Speech section is removed entirely
- [ ] AC-2.4: Field IDs `tts_voice` and `speaking_rate` remain unchanged for backward compatibility

### US-3: Agent Configuration Simplification
**As a** user configuring the AI agent  
**I want** a simplified Agent category without voice/speech confusion  
**So that** I can focus on model selection, inference, personality, and memory

**Acceptance Criteria:**
- [ ] AC-3.1: Agent category has exactly 4 sections: `model_selection`, `inference_mode`, `identity`, `memory`
- [ ] AC-3.2: Agent/Wake section is removed
- [ ] AC-3.3: Agent/Speech section is removed
- [ ] AC-3.4: Internet access toggle is in Agent → Memory section

### US-4: Extensions System
**As a** power user  
**I want** to manage MCP servers, skills, and workflows in one place  
**So that** I can extend IRIS capabilities without cluttering core settings

**Acceptance Criteria:**
- [ ] AC-4.1: New Automate → Extensions section contains 3 Cards: `mcp-servers-card`, `skills-card`, `saved-workflows-card`
- [ ] AC-4.2: Built-in MCP servers (browser, file_manager, system, app_launcher, gui_automation) have toggle controls
- [ ] AC-4.3: External MCP servers can be added with name, transport type, command/URL
- [ ] AC-4.4: Skills can be created with name, description, and prompt override
- [ ] AC-4.5: Workflows can be imported and managed

### US-5: Display-Only Analytics
**As a** user viewing system analytics  
**I want** analytics to be display-only without editable fields  
**So that** I don't accidentally change settings while reviewing data

**Acceptance Criteria:**
- [ ] AC-5.1: Monitor → Analytics Card has only action buttons (no toggles/sliders/dropdowns)
- [ ] AC-5.2: Buttons: `view_session_stats`, `view_tool_usage`, `export_report`
- [ ] AC-5.3: Backend analytics can be wired later without UI changes

### US-6: Consistent Dashboard and Wheel Views
**As a** user switching between dashboard and wheel views  
**I want** both views to show the same content structure  
**So that** my settings are consistent regardless of how I access them

**Acceptance Criteria:**
- [ ] AC-6.1: `dark-glass-dashboard.tsx` derives its structure from `mini-nodes.ts`
- [ ] AC-6.2: Both views use identical Card IDs, field IDs, and default values
- [ ] AC-6.3: No hardcoded data that could drift from the central source

---

## ID Format Rules (Locked)

| Type | Format | Example |
|------|--------|---------|
| Node IDs | single word, lowercase | `voice`, `agent`, `system` |
| Section IDs | snake_case | `input`, `model_selection`, `inference_mode` |
| Card IDs | kebab-case + `-card` suffix | `microphone-card`, `speech-card` |
| Field IDs | snake_case | `input_device`, `tts_voice` |

---

## Content Structure (Locked)

### VOICE Category

**Section: `input`**
- `microphone-card`: Microphone (fields: `input_device`, `input_gain`, `noise_suppression`, `echo_cancellation`)
- `wake-word-card`: Wake Word (fields: `wake_phrase`, `wake_sensitivity`, `always_listening`)

**Section: `output`**
- `speaker-card`: Speaker (fields: `output_device`, `output_volume`)
- `speech-card`: Voice Synthesis (fields: `tts_voice`, `speaking_rate`, `tts_enabled`)

**Section: `processing`**
- `voice-engine-card`: Voice Engine (fields: `voice_engine`, `vad_threshold`, `silence_timeout`, `audio_enhancement`)

**Section: `model`**
- `audio-model-card`: Audio Model (fields: `audio_model_version`, `inference_device`, `streaming_mode`)

### AGENT Category

**Section: `model_selection`**
- `models-card`: Models (fields: `reasoning_model`, `tool_execution_model`)

**Section: `inference_mode`**
- `inference-card`: Inference (fields: `inference_mode`, plus conditional fields)

**Section: `identity`**
- `personality-card`: Personality (fields: `assistant_name`, `personality_style`, `response_length`, `proactive_suggestions`)

**Section: `memory`**
- `memory-card`: Memory (fields: `memory_enabled`, `memory_window`, `persist_across_sessions`, `internet_access`, `clear_memory`)

### AUTOMATE Category

**Section: `tools`**
- `tool-permissions-card`: Tool Access (fields: `tool_browser`, `tool_file_system`, `tool_system_commands`, `tool_app_control`, `tool_timeout`)

**Section: `vision`**
- `vision-card`: Vision (fields: `screen_capture_enabled`, `vision_model`, `capture_interval`)

**Section: `workflows`**
- `workflows-card`: Workflows (fields: `workflow_auto_save`, `max_workflow_steps`, `workflow_retry_on_fail`)

**Section: `shortcuts`**
- `shortcuts-card`: Shortcuts (fields: `voice_shortcut_enabled`, `global_hotkey`, `shortcut_feedback`)

**Section: `gui`**
- `gui-card`: GUI Control (fields: `gui_automation_enabled`, `click_delay`, `safe_mode`)

**Section: `extensions`**
- `mcp-servers-card`: MCP Servers (dynamic fields for built-in and external servers)
- `skills-card`: Skills (dynamic fields for skill management)
- `saved-workflows-card`: Saved Workflows (dynamic fields for workflow management)

### SYSTEM Category

**Section: `power`**
- `power-card`: Power (fields: `startup_with_system`, `background_mode`, `idle_timeout`, `low_power_mode`)

**Section: `display`**
- `window-card`: Window (fields: `window_opacity`, `always_on_top`, `animations_enabled`, `reduced_motion`)

**Section: `storage`**
- `storage-card`: Storage (fields: `log_retention_days`, `auto_cleanup`, `cache_models`, `run_cleanup`)

**Section: `network`**
- `connection-card`: Connection (fields: `backend_host`, `backend_port`, `websocket_reconnect`, `check_connection`)

### CUSTOMIZE Category

**Section: `theme`**
- `theme-card`: Theme (fields: `active_theme`, `brand_hue`, `brand_saturation`, `brand_lightness`, `base_plate_hue`, `base_plate_saturation`, `base_plate_lightness`, `reset_to_defaults`) — local only, no backend sync

**Section: `startup`**
- `startup-card`: Startup (fields: `startup_view`, `preload_models`, `show_splash`, `auto_connect_ws`)

**Section: `behavior`**
- `behavior-card`: Behavior (fields: `double_click_voice`, `auto_close_panel`, `confirm_before_action`, `click_sound`)

**Section: `notifications`**
- `notifications-card`: Notifications (fields: `notify_task_complete`, `notify_errors`, `notify_wake_detected`, `notification_sound`)

### MONITOR Category

**Section: `analytics`**
- `analytics-card`: Analytics (fields: `view_session_stats`, `view_tool_usage`, `export_report`) — buttons only

**Section: `logs`**
- `logs-card`: Logs (fields: `log_level`, `log_to_file`, `clear_logs`)

**Section: `diagnostics`**
- `diagnostics-card`: Diagnostics (fields: `run_diagnostics`, `check_microphone`, `check_backend`, `show_gpu_stats`)

**Section: `updates`**
- `updates-card`: Updates (fields: `update_channel`, `check_for_updates`, `auto_update`)

---

## Out of Scope (Phase 2)

The following backend functionality is documented but NOT implemented in this phase:
- `manage_mcp_server` message handler
- `manage_skill` message handler  
- `manage_workflow` message handler
- Extension manager UI components (`ExtensionManagerPanel`)
- Workflow execution engine

These will be stubbed with "Coming soon" states where applicable.

---

## Verification Criteria

1. All Card IDs end with `-card`
2. No `wake` or `speech` sections under Agent
3. New `extensions` section exists under Automate
4. `dark-glass-dashboard.tsx` uses derived data, not hardcoded
5. `SidePanel.tsx` references updated Card IDs
6. Both form field sets (wheel-view/fields/ and form-fields/) remain functional
