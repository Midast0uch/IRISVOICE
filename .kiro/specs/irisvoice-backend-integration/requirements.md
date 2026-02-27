# Requirements Document: IRISVOICE Backend Integration

## Introduction

This document specifies the requirements for integrating the IRISVOICE backend with the redesigned UI components. The system is a voice-enabled AI assistant with a sophisticated glassmorphic UI featuring voice interaction, text chat, settings management, and tool execution capabilities. The integration must ensure all UI components properly communicate with the backend through WebSocket connections, maintain state consistency across sessions, and provide reliable access to all agent capabilities including the dual-LLM system and MCP tool integration.

### LFM 2.5 Audio Model Architecture

The voice system is powered by the **LFM 2.5 audio model**, an end-to-end audio-to-audio model that handles the complete voice pipeline internally:

- **Audio I/O**: Raw audio capture from microphone and playback to speakers
- **Audio Processing**: Noise reduction, echo cancellation, voice enhancement, automatic gain control
- **Wake Word Detection**: Detects configured wake phrases internally
- **Voice Activity Detection (VAD)**: Detects speech start/end internally
- **Speech-to-Text (STT)**: Transcribes speech internally
- **Conversation**: Understands user intent and generates responses
- **Text-to-Speech (TTS)**: Synthesizes audio responses internally
- **Natural Flow**: Handles turn-taking and interruption

The backend provides only a thin wrapper (AudioEngine) to initialize and manage the LFM 2.5 audio model. There are no separate components for wake word detection, VAD, STT, or TTS - the LFM 2.5 model handles all of this internally.

## Glossary

- **IRIS_System**: The complete IRISVOICE application including frontend (Next.js/Tauri) and backend (FastAPI)
- **IrisOrb**: The central orb UI component that visualizes voice states and handles user interaction
- **DarkGlassDashboard**: The settings dashboard component with 6 main categories and their subnodes
- **ChatView**: The text-based chat interface component for conversing with the agent
- **WebSocket_Manager**: Backend component managing WebSocket connections and message routing
- **Session_Manager**: Backend component managing user sessions and state isolation
- **State_Manager**: Backend component managing application state per session
- **Agent_Kernel**: Backend component orchestrating the dual-LLM system (lfm2-8b reasoning, lfm2.5-1.2b-instruct execution)
- **VPS_Gateway**: Backend component routing model inference to remote VPS or local execution with automatic fallback
- **Tool_Bridge**: Backend component providing access to MCP tools (vision, web, file, system, app)
- **Voice_Pipeline**: Backend orchestrator for the LFM 2.5 audio model (end-to-end audio-to-audio)
- **Navigation_Context**: React context managing navigation state and WebSocket integration
- **Field_Value**: A setting value stored in the backend state (string, number, or boolean)
- **Mini_Node**: A granular settings control within a subnode
- **Voice_State**: Current state of voice interaction (idle, listening, processing_conversation, processing_tool, speaking, error)
- **MCP**: Model Context Protocol for tool integration
- **LFM_Audio_Model**: LFM 2.5 end-to-end audio model that handles all audio processing, wake word detection, VAD, STT, TTS, and conversation flow
- **VPS**: Virtual Private Server - remote server for offloading model inference

## Requirements

### Requirement 1: WebSocket Connection Establishment

**User Story:** As a user, I want the frontend to automatically connect to the backend when the application starts, so that I can interact with IRIS immediately.

#### Acceptance Criteria

1. WHEN the IRIS_System starts, THE WebSocket_Manager SHALL establish a connection to ws://localhost:8000/ws/{client_id}
2. WHEN the connection is established, THE Backend SHALL send an initial_state message containing the complete session state
3. IF the connection fails, THEN THE Frontend SHALL retry with exponential backoff up to 3 attempts
4. WHEN the connection is lost, THE Frontend SHALL display a "Backend offline - running in standalone mode" message
5. THE WebSocket_Manager SHALL send a ping message every 30 seconds to maintain the connection
6. WHEN a ping is received, THE Backend SHALL respond with a pong message within 5 seconds

### Requirement 2: Session Management and State Persistence

**User Story:** As a user, I want my settings and conversation history to persist across application restarts, so that I don't lose my configuration.

#### Acceptance Criteria

1. WHEN a new WebSocket connection is established, THE Session_Manager SHALL create or restore a session
2. THE State_Manager SHALL persist all Field_Values to backend storage after each update
3. WHEN the application restarts, THE State_Manager SHALL restore the previous session state
4. THE Session_Manager SHALL maintain state isolation between multiple concurrent sessions
5. WHEN a session is inactive for 24 hours, THE Session_Manager SHALL archive the session data
6. THE State_Manager SHALL synchronize state changes to all connected clients in the same session within 100ms

### Requirement 3: Voice Command Initiation and Processing

**User Story:** As a user, I want to activate voice commands by double-clicking the IrisOrb, so that I can speak to IRIS naturally.

#### Acceptance Criteria

1. WHEN the user double-clicks IrisOrb, THE Frontend SHALL send a voice_command_start message to the Backend
2. WHEN voice_command_start is received, THE LFM_Audio_Model SHALL begin end-to-end audio processing (capture, VAD, wake word detection, STT, conversation, TTS)
3. THE IrisOrb SHALL display Voice_State as "listening" with visual feedback (glow expansion, color change)
4. WHEN the user single-clicks IrisOrb during listening, THE Frontend SHALL send a voice_command_end message
5. WHEN voice_command_end is received, THE LFM_Audio_Model SHALL complete audio processing and generate an audio response
6. THE Backend SHALL send a listening_state message to update Voice_State to "processing_conversation"
7. WHEN audio processing completes, THE LFM_Audio_Model SHALL generate both text and audio responses
8. THE Backend SHALL send a text_response message containing the agent's response text
9. IF audio processing fails, THEN THE Backend SHALL send a voice_command_error message with error details

### Requirement 4: Wake Word Detection

**User Story:** As a user, I want IRIS to activate when I say the wake phrase, so that I can use hands-free voice interaction.

#### Acceptance Criteria

1. WHEN the LFM_Audio_Model detects the configured wake phrase, THE Backend SHALL send a wake_detected message
2. WHEN wake_detected is received, THE IrisOrb SHALL automatically start voice recording
3. THE IrisOrb SHALL display a wake flash animation for 500ms
4. THE LFM_Audio_Model SHALL use the wake phrase configured in agent.wake.wake_phrase field
5. THE LFM_Audio_Model SHALL respect the detection_sensitivity setting (0-100%)
6. WHEN activation_sound is enabled, THE LFM_Audio_Model SHALL play an audio confirmation

### Requirement 4.5: LFM 2.5 Audio Model End-to-End Processing

**User Story:** As a developer, I want the LFM 2.5 audio model to handle all audio processing end-to-end, so that the backend doesn't need to manage separate components for wake word, VAD, STT, and TTS.

#### Acceptance Criteria

1. THE LFM_Audio_Model SHALL capture raw audio input from the configured microphone device
2. THE LFM_Audio_Model SHALL output raw audio to the configured speaker device
3. THE LFM_Audio_Model SHALL perform all audio processing internally (noise reduction, echo cancellation, voice enhancement, automatic gain control)
4. THE LFM_Audio_Model SHALL detect wake words internally without external wake word detection components
5. THE LFM_Audio_Model SHALL perform voice activity detection (VAD) internally without external VAD components
6. THE LFM_Audio_Model SHALL transcribe speech to text internally without external STT components
7. THE LFM_Audio_Model SHALL understand user intent and generate responses internally
8. THE LFM_Audio_Model SHALL synthesize text to speech internally without external TTS components
9. THE LFM_Audio_Model SHALL manage natural conversation flow including turn-taking and interruption handling
10. THE Backend SHALL provide only a thin wrapper (AudioEngine) to initialize and manage the LFM_Audio_Model lifecycle

### Requirement 5: Text Message Processing

**User Story:** As a user, I want to send text messages through ChatView and receive responses, so that I can interact with IRIS without using voice.

#### Acceptance Criteria

1. WHEN the user submits a message in ChatView, THE Frontend SHALL send a text_message with payload.text
2. WHEN text_message is received, THE Agent_Kernel SHALL process the message using the lfm2-8b model
3. THE Backend SHALL send a text_response message with the agent's reply within 10 seconds
4. THE ChatView SHALL display the response message with sender "assistant"
5. THE Agent_Kernel SHALL maintain conversation context for the current session
6. IF the Agent_Kernel is unavailable, THEN THE Backend SHALL send an error message "Agent kernel is not available"
7. THE ChatView SHALL display a typing indicator while waiting for the response

### Requirement 6: Settings Field Synchronization

**User Story:** As a user, I want my settings changes in DarkGlassDashboard to be saved immediately, so that my preferences are always up to date.

#### Acceptance Criteria

1. WHEN a field value changes in DarkGlassDashboard, THE Frontend SHALL send an update_field message with subnode_id, field_id, and value
2. THE State_Manager SHALL validate the field value against the field type and constraints
3. IF validation succeeds, THEN THE State_Manager SHALL persist the value and send a field_updated confirmation
4. IF validation fails, THEN THE Backend SHALL send a validation_error message with error details
5. THE DarkGlassDashboard SHALL update the field display optimistically before receiving confirmation
6. WHEN field_updated is received, THE Frontend SHALL confirm the optimistic update
7. THE State_Manager SHALL broadcast field updates to all clients in the same session

### Requirement 7: Category and Subnode Navigation

**User Story:** As a user, I want to navigate through settings categories and subnodes, so that I can access all configuration options.

#### Acceptance Criteria

1. WHEN a main category is selected, THE Frontend SHALL send a select_category message with the category ID
2. WHEN select_category is received, THE State_Manager SHALL update current_category and send a category_changed message
3. THE Backend SHALL send a subnodes message containing all subnodes for the selected category
4. WHEN a subnode is selected, THE Frontend SHALL send a select_subnode message with the subnode_id
5. WHEN select_subnode is received, THE State_Manager SHALL update current_subnode and send a subnode_changed message
6. THE Navigation_Context SHALL maintain navigation history for back navigation
7. WHEN go_back is triggered, THE State_Manager SHALL restore the previous navigation state

### Requirement 8: Agent Tool Access and Execution

**User Story:** As a user, I want the agent to access all available tools, so that it can perform actions on my behalf.

#### Acceptance Criteria

1. WHEN the Frontend requests agent tools, THE Backend SHALL send an agent_tools message listing all available MCP tools
2. THE Tool_Bridge SHALL provide access to vision, web, file, system, and app tools
3. WHEN the Agent_Kernel needs to execute a tool, THE Tool_Bridge SHALL route the request to the appropriate MCP server
4. THE Backend SHALL send tool execution results back to the Agent_Kernel within 30 seconds
5. IF a tool execution fails, THEN THE Tool_Bridge SHALL return an error message with failure details
6. THE Agent_Kernel SHALL include tool results in the conversation context for follow-up responses
7. THE Tool_Bridge SHALL respect security allowlists for all tool executions

### Requirement 9: Voice State Visualization

**User Story:** As a user, I want the IrisOrb to show the current voice state, so that I know when IRIS is listening or processing.

#### Acceptance Criteria

1. WHEN Voice_State changes, THE Backend SHALL send a listening_state message with the new state
2. THE IrisOrb SHALL display "idle" state with base glow and no expansion
3. THE IrisOrb SHALL display "listening" state with 1.15x scale, active glow color, and audio level animation
4. THE IrisOrb SHALL display "processing_conversation" state with 1.08x scale and purple (#7000ff) glow
5. THE IrisOrb SHALL display "processing_tool" state with 1.08x scale and purple (#7000ff) glow
6. THE IrisOrb SHALL display "speaking" state with 1.1x scale, active glow color, and audio jitter animation
7. THE IrisOrb SHALL display "error" state with red glow and error message overlay

### Requirement 10: Theme Synchronization

**User Story:** As a user, I want theme changes to apply across all UI components immediately, so that the interface looks consistent.

#### Acceptance Criteria

1. WHEN brand color changes in DarkGlassDashboard, THE Frontend SHALL send an update_theme message with glow_color
2. WHEN update_theme is received, THE State_Manager SHALL update the active_theme and send a theme_updated message
3. THE IrisOrb SHALL update its glow color to match the new theme within 100ms
4. THE DarkGlassDashboard SHALL update its accent colors to match the new theme
5. THE ChatView SHALL update its UI elements to match the new theme
6. THE State_Manager SHALL persist theme changes to backend storage
7. WHEN the application restarts, THE Frontend SHALL restore the previous theme settings

### Requirement 11: Audio Device Configuration

**User Story:** As a user, I want to select my audio input and output devices, so that IRIS uses the correct microphone and speakers.

#### Acceptance Criteria

1. WHEN the voice.input.input_device field changes, THE LFM_Audio_Model SHALL switch to the selected input device
2. WHEN the voice.output.output_device field changes, THE LFM_Audio_Model SHALL switch to the selected output device
3. THE Backend SHALL enumerate available audio devices and send them to the Frontend
4. THE DarkGlassDashboard SHALL display available devices in dropdown options
5. IF a selected device becomes unavailable, THEN THE LFM_Audio_Model SHALL fall back to the default device
6. THE Backend SHALL send a validation_error if the device switch fails
7. THE LFM_Audio_Model SHALL apply the new device configuration within 2 seconds

### Requirement 12: Voice Processing Configuration

**User Story:** As a user, I want to configure voice processing settings like noise reduction and echo cancellation, so that voice quality is optimized.

#### Acceptance Criteria

1. THE LFM_Audio_Model SHALL apply noise reduction to input audio automatically
2. THE LFM_Audio_Model SHALL apply echo cancellation automatically
3. THE LFM_Audio_Model SHALL apply voice enhancement automatically
4. THE LFM_Audio_Model SHALL apply automatic gain control automatically
5. THE LFM_Audio_Model SHALL handle all audio processing internally without external configuration
6. THE LFM_Audio_Model SHALL apply processing in the optimal order for audio quality
7. THE LFM_Audio_Model SHALL maintain audio latency below 100ms with all processing enabled

### Requirement 13: Agent Personality Configuration

**User Story:** As a user, I want to configure the agent's personality and response style, so that interactions match my preferences.

#### Acceptance Criteria

1. WHEN agent.identity.assistant_name changes, THE Agent_Kernel SHALL use the new name in responses
2. WHEN agent.identity.personality changes, THE Agent_Kernel SHALL adjust response tone accordingly
3. WHEN agent.identity.knowledge changes, THE Agent_Kernel SHALL adjust domain expertise
4. THE Agent_Kernel SHALL apply personality changes to new messages immediately
5. THE Agent_Kernel SHALL maintain personality consistency within a conversation
6. THE Agent_Kernel SHALL include personality configuration in the system prompt
7. THE Agent_Kernel SHALL validate personality options against allowed values

### Requirement 14: TTS Voice Configuration

**User Story:** As a user, I want to select the TTS voice and speaking rate, so that spoken responses sound natural.

#### Acceptance Criteria

1. WHEN agent.speech.tts_voice changes, THE LFM_Audio_Model SHALL adjust voice characteristics for the next response
2. WHEN agent.speech.speaking_rate changes, THE LFM_Audio_Model SHALL adjust the playback speed
3. THE LFM_Audio_Model SHALL support voice characteristics: Nova, Alloy, Echo, Fable, Onyx, Shimmer
4. THE LFM_Audio_Model SHALL support speaking rates from 0.5x to 2.0x
5. THE LFM_Audio_Model SHALL apply voice changes to the next spoken response
6. THE LFM_Audio_Model SHALL maintain audio quality at all speaking rates
7. THE LFM_Audio_Model SHALL generate audio responses directly without external TTS

### Requirement 15: Vision System Integration

**User Story:** As a user, I want to enable vision capabilities so that IRIS can see my screen and provide context-aware assistance.

#### Acceptance Criteria

1. WHEN automate.vision.vision_enabled is true, THE Vision_System SHALL activate screen monitoring
2. WHEN automate.vision.screen_context is true, THE Vision_System SHALL include screen captures in chat context
3. WHEN automate.vision.proactive_monitor is true, THE Vision_System SHALL capture screens at the configured interval
4. THE Vision_System SHALL use the configured automate.vision.ollama_endpoint for vision model inference
5. THE Vision_System SHALL use the configured automate.vision.vision_model (minicpm-o4.5, llava, or bakllava)
6. THE Vision_System SHALL respect the automate.vision.monitor_interval setting (5-120 seconds)
7. THE Vision_System SHALL send screen analysis results to the Agent_Kernel for context

### Requirement 16: MCP Tool Server Management

**User Story:** As a user, I want all MCP tool servers to start automatically, so that the agent has access to all capabilities.

#### Acceptance Criteria

1. WHEN the Backend starts, THE Server_Manager SHALL start all configured MCP servers
2. THE Server_Manager SHALL start BrowserServer for web browsing capabilities
3. THE Server_Manager SHALL start AppLauncherServer for application control
4. THE Server_Manager SHALL start SystemServer for system operations
5. THE Server_Manager SHALL start FileManagerServer for file operations
6. THE Server_Manager SHALL start GUIAutomationServer for UI automation
7. IF a server fails to start, THEN THE Server_Manager SHALL log the error and continue with other servers
8. THE Server_Manager SHALL monitor server health and restart failed servers automatically

### Requirement 17: Conversation Memory Management

**User Story:** As a user, I want the agent to remember our conversation, so that I don't have to repeat context.

#### Acceptance Criteria

1. THE Agent_Kernel SHALL maintain conversation history for the current session
2. THE Conversation_Memory SHALL store the last N messages where N is configurable (default 10)
3. WHEN the user sends clear_chat, THE Agent_Kernel SHALL clear the conversation history
4. THE Conversation_Memory SHALL include both user messages and agent responses
5. THE Conversation_Memory SHALL include tool execution results in the context
6. THE Conversation_Memory SHALL persist conversation history to session storage
7. WHEN the session ends, THE Conversation_Memory SHALL archive the conversation history

### Requirement 18: Agent Status Monitoring

**User Story:** As a user, I want to see the agent's status, so that I know if it's ready to respond.

#### Acceptance Criteria

1. WHEN the Frontend requests agent_status, THE Backend SHALL send current agent state
2. THE agent_status message SHALL include ready status (true/false)
3. THE agent_status message SHALL include models_loaded count
4. THE agent_status message SHALL include total_models count
5. THE agent_status message SHALL include tool_bridge_available status
6. THE agent_status message SHALL include individual model status for lfm2-8b and lfm2.5-1.2b-instruct
7. THE Frontend SHALL display agent status in the UI when requested

### Requirement 19: Error Handling and Recovery

**User Story:** As a user, I want clear error messages when something goes wrong, so that I can understand and resolve issues.

#### Acceptance Criteria

1. WHEN a WebSocket message fails to parse, THE Backend SHALL log the error and continue processing
2. WHEN a field validation fails, THE Backend SHALL send a validation_error with field_id and error message
3. WHEN a tool execution fails, THE Backend SHALL send a tool_result with error details
4. WHEN the Agent_Kernel encounters an error, THE Backend SHALL send a text_response with error explanation
5. WHEN a voice command fails, THE Backend SHALL send a voice_command_error with error details
6. THE Frontend SHALL display error messages to the user in a non-intrusive way
7. THE Backend SHALL log all errors to the structured logger for debugging

### Requirement 20: Settings Persistence and Restoration

**User Story:** As a user, I want all my settings to be saved automatically, so that I don't lose my configuration.

#### Acceptance Criteria

1. THE State_Manager SHALL persist all Field_Values to JSON files in backend/settings/
2. THE State_Manager SHALL save voice settings to backend/settings/voice.json
3. THE State_Manager SHALL save agent settings to backend/settings/agent.json
4. THE State_Manager SHALL save automate settings to backend/settings/automate.json
5. THE State_Manager SHALL save system settings to backend/settings/system.json
6. THE State_Manager SHALL save customize settings to backend/settings/customize.json
7. THE State_Manager SHALL save monitor settings to backend/settings/monitor.json
8. WHEN the Backend starts, THE State_Manager SHALL restore all settings from JSON files
9. THE State_Manager SHALL validate restored settings against field schemas
10. IF a settings file is corrupted, THEN THE State_Manager SHALL use default values and log a warning

### Requirement 21: Real-time State Synchronization

**User Story:** As a user with multiple windows open, I want changes in one window to appear in all windows, so that the interface stays consistent.

#### Acceptance Criteria

1. WHEN a Field_Value changes, THE State_Manager SHALL broadcast the change to all clients in the session
2. THE WebSocket_Manager SHALL deliver state updates within 100ms
3. THE Frontend SHALL update the UI immediately upon receiving state_update messages
4. THE State_Manager SHALL use optimistic updates to minimize perceived latency
5. THE State_Manager SHALL resolve conflicts using last-write-wins strategy
6. THE State_Manager SHALL include a timestamp in all state updates
7. THE Frontend SHALL handle out-of-order state updates gracefully

### Requirement 22: Audio Level Visualization

**User Story:** As a user, I want to see audio levels while speaking, so that I know IRIS is hearing me.

#### Acceptance Criteria

1. WHILE Voice_State is "listening", THE LFM_Audio_Model SHALL send audio level updates every 100ms
2. THE IrisOrb SHALL display audio levels as glow intensity variations
3. THE audio level SHALL be normalized to a range of 0.0 to 1.0
4. THE IrisOrb SHALL animate audio levels smoothly using interpolation
5. THE LFM_Audio_Model SHALL calculate audio levels using RMS (root mean square) of the audio signal
6. THE LFM_Audio_Model SHALL apply a smoothing filter to prevent jittery animations
7. WHEN Voice_State changes from "listening", THE IrisOrb SHALL reset audio level to 0

### Requirement 23: Dual-LLM Model Coordination

**User Story:** As a developer, I want the dual-LLM system to work seamlessly, so that reasoning and execution are properly coordinated.

#### Acceptance Criteria

1. THE Agent_Kernel SHALL use lfm2-8b for reasoning and planning tasks
2. THE Agent_Kernel SHALL use lfm2.5-1.2b-instruct for tool execution and action tasks
3. THE Model_Router SHALL route messages to the appropriate model based on task type
4. THE Agent_Kernel SHALL pass reasoning results from lfm2-8b to lfm2.5-1.2b-instruct for execution
5. THE Agent_Kernel SHALL maintain inter-model communication state
6. THE Agent_Kernel SHALL handle model failures gracefully by falling back to single-model mode
7. THE Agent_Kernel SHALL log all model routing decisions for debugging

### Requirement 24: Security and Validation

**User Story:** As a user, I want my system to be protected from malicious commands, so that IRIS cannot harm my computer.

#### Acceptance Criteria

1. THE Tool_Bridge SHALL validate all tool parameters against security allowlists
2. THE Security_Filter SHALL block tool executions that violate security policies
3. THE Audit_Logger SHALL log all tool executions with timestamps and parameters
4. THE Security_Filter SHALL require user confirmation for destructive operations
5. THE Tool_Bridge SHALL sanitize all user inputs before passing to tools
6. THE Security_Filter SHALL enforce rate limits on tool executions (max 10 per minute)
7. THE Audit_Logger SHALL alert on suspicious activity patterns

### Requirement 25: Performance and Responsiveness

**User Story:** As a user, I want IRIS to respond quickly, so that interactions feel natural and fluid.

#### Acceptance Criteria

1. THE WebSocket_Manager SHALL deliver messages with latency below 50ms
2. THE Agent_Kernel SHALL generate text responses within 5 seconds for simple queries
3. THE Voice_Pipeline SHALL process voice commands within 3 seconds
4. THE State_Manager SHALL persist field updates within 100ms
5. THE Frontend SHALL render UI updates within 16ms (60 FPS)
6. THE Tool_Bridge SHALL execute tools within 10 seconds or timeout
7. THE Backend SHALL handle at least 100 concurrent WebSocket connections

### Requirement 26: VPS Gateway for Remote Model Inference

**User Story:** As a user with limited local compute resources, I want to offload heavy model inference to a remote VPS server, so that I can use IRIS without overwhelming my local machine.

#### Acceptance Criteria

1. WHEN VPS Gateway is configured with an endpoint URL, THE System SHALL route model inference requests to the remote VPS
2. WHEN VPS Gateway is not configured or unavailable, THE System SHALL fall back to local model execution
3. THE VPS_Gateway SHALL support both REST API and WebSocket communication protocols with the remote VPS
4. THE VPS_Gateway SHALL include authentication credentials in all requests to the VPS
5. THE VPS_Gateway SHALL timeout requests after a configurable duration (default 30 seconds)
6. THE VPS_Gateway SHALL perform health checks on the VPS endpoint every 60 seconds
7. WHEN VPS health check fails, THE VPS_Gateway SHALL mark the VPS as unavailable and fall back to local execution
8. WHEN VPS becomes available again, THE VPS_Gateway SHALL automatically resume routing to VPS
9. THE VPS_Gateway SHALL support load balancing across multiple VPS instances when configured
10. THE VPS_Gateway SHALL serialize model inference requests (prompt, context, parameters) for transmission to VPS
11. THE VPS_Gateway SHALL deserialize model inference responses from VPS and return them to the Agent_Kernel
12. THE VPS_Gateway SHALL maintain the same dual-LLM architecture (reasoning + execution) on the VPS
13. THE VPS_Gateway SHALL log all VPS communication for debugging and monitoring
14. THE System SHALL keep lightweight components local: WebSocket_Manager, State_Manager, Session_Manager, UI
15. THE System SHALL offload heavy components to VPS: model loading (lfm2-8b, lfm2.5-1.2b-instruct), model inference, tool execution
16. THE VPS_Gateway configuration SHALL include: endpoint URL, authentication token, timeout duration, health check interval, fallback enabled
17. WHEN tool execution is offloaded to VPS, THE VPS_Gateway SHALL serialize tool parameters and deserialize tool results

