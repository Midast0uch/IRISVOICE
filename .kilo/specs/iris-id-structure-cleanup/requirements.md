# Requirements: IRIS ID Structure Cleanup & Alignment

## Introduction

This spec addresses critical misalignments between the frontend UI cards and backend data sections. Currently, many frontend cards have no corresponding backend sections, causing user settings to not persist. Additionally, the terminology and organization need to be cleaned up for better user experience.

Success looks like: All 22 UI cards have corresponding backend sections, data persists correctly, and the UI uses user-friendly terminology (e.g., "Desktop Control" instead of "GUI").

## Requirements

### Requirement 1: Create Missing Backend Sections

**User Story:** As a user, I want my settings to persist when I configure my agent, so that I don't have to reconfigure every time I open the app.

#### Acceptance Criteria

1. WHEN a user configures the Models card THE SYSTEM SHALL persist settings to a `model_selection` backend section
2. WHEN a user configures the Inference card THE SYSTEM SHALL persist settings to an `inference_mode` backend section
3. WHEN a user views the Skills card THE SYSTEM SHALL display data from a `skills` backend section
4. WHEN a user views the Profile card THE SYSTEM SHALL display data from a `profile` backend section
5. THE SYSTEM SHALL support lazy-loaded dropdowns for model selection (populated on demand)

### Requirement 2: Rename GUI to Desktop Control

**User Story:** As a user, I want to understand what "GUI Automation" actually does, so that I can decide whether to enable it.

#### Acceptance Criteria

1. WHEN the UI displays the automation settings THE SYSTEM SHALL show "Desktop Control" instead of "GUI"
2. WHEN the user enables Desktop Control THE SYSTEM SHALL allow voice-controlled desktop automation
3. WHEN Desktop Control is enabled with Vision THE SYSTEM SHALL use MiniCPM for intelligent element detection
4. THE SYSTEM SHALL provide a toggle for "Use Screen Vision" to enable/disable MiniCPM integration

### Requirement 3: Reorganize Field Structure

**User Story:** As a user, I want related settings grouped together logically, so that I can find what I'm looking for easily.

#### Background
- Backend **ALREADY HAS** `wake` and `speech` sections (no frontend cards)
- Frontend currently has wake/TTS fields in `input`/`output` sections
- Need to expose existing backend sections and migrate fields

#### Acceptance Criteria

1. WHEN the user configures wake word settings THE SYSTEM SHALL show them in a dedicated "Wake Word" section
2. WHEN the user configures TTS/voice settings THE SYSTEM SHALL show them in a dedicated "Speech" section
3. WHEN the user configures audio input THE SYSTEM SHALL show input device and volume in the "Input" section
4. WHEN the user configures audio output THE SYSTEM SHALL show output device and volume in the "Output" section
5. THE SYSTEM SHALL create `wake-word-card` that maps to existing backend `wake` section
6. THE SYSTEM SHALL create `speech-card` that maps to existing backend `speech` section
7. THE SYSTEM SHALL remove wake fields from `input` section in frontend
8. THE SYSTEM SHALL remove TTS fields from `output` section in frontend
9. THE SYSTEM SHALL migrate existing user settings from old locations to new sections

### Requirement 4: Simplify Inference Configuration

**User Story:** As a user, I want to configure my agent's behavior without understanding technical parameters like "temperature" and "max_tokens".

#### Acceptance Criteria

1. WHEN the user configures inference mode THE SYSTEM SHALL present user-friendly options:
   - Agent Thinking Style: concise | balanced | thorough
   - Max Response Length: short | medium | long
   - Reasoning Effort: fast | balanced | accurate
   - Tool Mode: auto | ask_first | disabled
2. THE SYSTEM SHALL map these user-friendly options to appropriate technical values internally
3. THE SYSTEM SHALL acknowledge that the two-agent system (Brain + Executor) already exists via Tool Bridge

### Requirement 5: Remove Unused Cards

**User Story:** As a user, I want a clean interface without placeholder cards that don't work.

#### Acceptance Criteria

1. THE SYSTEM SHALL remove the `audio-model-card` (confusing overlap with model_selection)
2. THE SYSTEM SHALL remove the `voice-engine-card` (fields don't match backend)
3. THE SYSTEM SHALL remove the `workflows-card` (per product requirements)
4. THE SYSTEM SHALL remove the `shortcuts-card` (not core functionality)
5. THE SYSTEM SHALL remove the `mcp-servers-card` (replaced by integrations-card)
6. THE SYSTEM SHALL remove the `saved-workflows-card` (no backend, not MVP)
7. THE SYSTEM SHALL remove the backend `favorites` section (no frontend card)

### Requirement 6: Align Field IDs

**User Story:** As a developer, I want consistent field IDs between frontend and backend, so that data sync works correctly.

#### Acceptance Criteria

1. THE SYSTEM SHALL use `agent_name` consistently (not `assistant_name`)
2. THE SYSTEM SHALL use `persona` consistently (not `personality`)
3. THE SYSTEM SHALL ensure all Card IDs end with `-card` suffix
4. THE SYSTEM SHALL use lowercase-kebab-case for all IDs
5. THE SYSTEM SHALL update `CARD_TO_SECTION_ID` mappings to match new structure

### Requirement 7: Fix Memory Section

**User Story:** As a user, I want to configure memory settings like window size and persistence, not just view memory statistics.

#### Acceptance Criteria

1. WHEN the user opens the Memory card THE SYSTEM SHALL show configuration fields:
   - Memory Enabled (toggle)
   - Context Window (slider 5-50)
   - Save Conversations (toggle)
2. THE SYSTEM SHALL move display-only fields (visualization, token_count) to a separate view or remove them
3. THE SYSTEM SHALL ensure backend `memory` section fields match frontend expectations

### Requirement 8: Maintain Tool Permissions Security

**User Story:** As a user, I want to be notified when the agent uses tools and have an audit log of actions.

#### Acceptance Criteria

1. THE SYSTEM SHALL keep the `tool-permissions-card` in the AGENT category
2. WHEN a tool is executed THE SYSTEM SHALL log it to the audit system
3. WHEN permission alerts are enabled THE SYSTEM SHALL notify the user of tool usage
4. THE SYSTEM SHALL display recent tool actions in the card

### Requirement 9: Handle Mismatched Fields

**User Story:** As a user, I want all available settings to be accessible, even if they only exist in frontend or backend currently.

#### Background
Fields exist on only one side and need to be aligned:
- Frontend only: `voice_profile`
- Backend only: `noise_gate`, `vad`, `input_test`, `output_test`, `latency_compensation`, `knowledge`, `response_length`

#### Acceptance Criteria

1. THE SYSTEM SHALL add `voice_profile` field to appropriate backend section (wake or identity)
2. THE SYSTEM SHALL add `noise_gate` toggle to frontend input section
3. THE SYSTEM SHALL add `vad` (voice activity detection) toggle to frontend input section
4. THE SYSTEM SHALL add `input_test` button to frontend input section
5. THE SYSTEM SHALL add `output_test` button to frontend output section
6. THE SYSTEM SHALL add `latency_compensation` slider to frontend output section
7. THE SYSTEM SHALL decide whether to add `knowledge` and `response_length` or remove from backend

### Requirement 10: Data Migration Strategy

**User Story:** As a user, I want my existing settings to be preserved when the app structure changes.

#### Acceptance Criteria

1. THE SYSTEM SHALL backup all user session files before migration
2. THE SYSTEM SHALL migrate wake settings from `input` section to `wake` section
3. THE SYSTEM SHALL migrate speech settings from `output` section to `speech` section
4. THE SYSTEM SHALL migrate `gui` section settings to `desktop_control` section
5. THE SYSTEM SHALL handle missing or corrupted session data gracefully
6. THE SYSTEM SHALL provide rollback capability if migration fails
7. THE SYSTEM SHALL log all migration operations for debugging

### Requirement 11: Code Terminology Cleanup

**User Story:** As a developer, I want consistent terminology across the codebase, so that the code is easier to understand and maintain.

#### Acceptance Criteria

1. THE SYSTEM SHALL rename `SUBNODE_CONFIGS` to `SECTION_CONFIGS` in backend/models.py
2. THE SYSTEM SHALL rename `SubNode` type/class to `Section` in backend/models.py
3. THE SYSTEM SHALL rename `MiniNode` type to `Card` in frontend types
4. THE SYSTEM SHALL rename `subnode_id` to `section_id` in all WebSocket messages and handlers
5. THE SYSTEM SHALL update all references to use the new terminology consistently
6. THE SYSTEM SHALL keep `card_id` as-is (already correct)
