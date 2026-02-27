# Implementation Plan: IRISVOICE Backend Integration

## Overview

This implementation plan covers the integration of the IRISVOICE backend (FastAPI) with the redesigned glassmorphic UI components (Next.js/Tauri). The system features a dual-LLM architecture (lfm2-8b reasoning + lfm2.5-1.2b-instruct execution), WebSocket-based real-time communication, voice pipeline with LFM 2.5 audio model, MCP tool integration, and persistent session management with multi-client synchronization.

The implementation follows an incremental approach: establish core infrastructure first (WebSocket, sessions, state), then add agent capabilities (dual-LLM, tools), voice features, and finally polish with testing and optimization.

### LFM 2.5 Audio Model Architecture

**CRITICAL**: The LFM 2.5 audio model is an **end-to-end audio-to-audio model** that handles EVERYTHING for voice:

- ✅ Raw audio input capture from microphone
- ✅ Raw audio output playback to speakers
- ✅ ALL audio processing (noise reduction, echo cancellation, voice enhancement, automatic gain)
- ✅ Wake word detection
- ✅ Voice activity detection (VAD)
- ✅ Speech-to-text (STT) transcription
- ✅ User-agent communication (understands user intent, generates responses)
- ✅ Text-to-speech (TTS) synthesis
- ✅ Natural conversation flow (turn-taking, interruption handling)

**What This Means for Implementation**:

1. **AudioEngine** is a thin wrapper (~100 lines) that just initializes and manages the LFM 2.5 audio model
2. **WakeWordDetector** is NOT needed - LFM 2.5 handles wake word detection internally
3. **VoiceActivityDetector** is NOT needed - LFM 2.5 handles VAD internally
4. **LFMAudioManager** is the CORE component - it IS the LFM 2.5 audio model
5. **TTSManager** is NOT needed - LFM 2.5 generates audio responses directly
6. **VoicePipeline** orchestrates the LFM 2.5 audio model, not separate components

The backend just needs to:
- Initialize the LFM 2.5 model
- Stream audio to it
- Receive audio responses
- Manage conversation state

## Tasks

- [x] 1. Set up project structure and core infrastructure
  - Create backend directory structure (backend/core/, backend/agent/, backend/voice/, backend/tools/)
  - Create frontend context structure (contexts/NavigationContext.tsx)
  - Set up WebSocket server endpoint in FastAPI
  - Configure CORS and middleware for Next.js/Tauri integration
  - Set up structured logging configuration
  - _Requirements: 1.1, 2.1_

- [ ] 2. Implement WebSocket connection and session management
  - [x] 2.1 Create WebSocketManager class with connection handling
    - Implement connect() method with client_id and optional session_id
    - Implement disconnect() method with cleanup
    - Implement send_to_client() and broadcast() methods
    - Add ping/pong heartbeat mechanism (30s interval)
    - _Requirements: 1.1, 1.5, 1.6_
  
  - [x] 2.2 Write property test for WebSocket connection initialization
    - **Property 1: WebSocket Connection Initialization**
    - **Validates: Requirements 1.2, 2.1**
  
  - [x] 2.3 Create SessionManager class for session lifecycle
    - Implement create_session() with session_id generation
    - Implement get_session() and associate_client_with_session()
    - Implement session archival after 24 hours of inactivity
    - Add session persistence to backend/sessions/ directory
    - _Requirements: 2.1, 2.4, 2.5_
  
  - [x] 2.4 Write property test for session state isolation
    - **Property 5: Session State Isolation**
    - **Validates: Requirements 2.4**


- [ ] 3. Implement state management and persistence
  - [x] 3.1 Create IRISState and related data models
    - Define IRISState, ColorTheme, SubNode, InputField, ConfirmedNode models
    - Add Pydantic validation for all models
    - _Requirements: 2.2, 10.1_
  
  - [x] 3.2 Create StateManager class for application state
    - Implement get_state(), set_category(), set_subnode() methods
    - Implement update_field() with validation
    - Implement update_theme() and confirm_subnode() methods
    - Add JSON persistence to backend/settings/ directory
    - _Requirements: 2.2, 2.3, 6.1, 6.2, 6.3, 20.1-20.10_
  
  - [x] 3.3 Write property test for field value persistence round-trip
    - **Property 4: Field Value Persistence Round-Trip**
    - **Validates: Requirements 2.2, 2.3, 20.1-20.10**
  
  - [x] 3.4 Write property test for multi-client state synchronization
    - **Property 6: Multi-Client State Synchronization**
    - **Validates: Requirements 2.6, 6.7, 21.1-21.3**
  
  - [x] 3.5 Write property test for field validation
    - **Property 17: Field Validation**
    - **Validates: Requirements 6.2, 6.4, 19.2**

- [ ] 4. Implement IRIS Gateway message routing
  - [x] 4.1 Create IRISGateway class for message handling
    - Implement handle_message() dispatcher
    - Implement _handle_navigation() for category/subnode selection
    - Implement _handle_settings() for field updates and theme changes
    - Add message validation and error handling
    - _Requirements: 6.1, 7.1, 7.4, 10.1_
  
  - [x] 4.2 Write property test for category navigation
    - **Property 19: Category Navigation**
    - **Validates: Requirements 7.1, 7.2, 7.3**
  
  - [x] 4.3 Write property test for navigation history round-trip
    - **Property 21: Navigation History Round-Trip**
    - **Validates: Requirements 7.6, 7.7**

- [x] 5. Checkpoint - Ensure core infrastructure tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [ ] 6. Implement dual-LLM agent system
  - [x] 6.1 Create ModelWrapper and ModelRouter classes
    - Implement ModelWrapper for lfm2-8b (reasoning model)
    - Implement ModelWrapper for lfm2.5-1.2b-instruct (execution model)
    - Implement ModelRouter.route_message() with task type detection
    - Add model loading and health checking
    - _Requirements: 23.1, 23.2, 23.3_
  
  - [x] 6.2 Write property test for dual-LLM model routing
    - **Property 54: Dual-LLM Model Routing**
    - **Validates: Requirements 23.1, 23.2, 23.3**
  
  - [x] 6.3 Create ConversationMemory class
    - Implement message storage with configurable limit (default 10)
    - Implement add_message(), get_context(), clear() methods
    - Add persistence to session storage
    - Add conversation archival on session end
    - _Requirements: 5.5, 17.1, 17.2, 17.4, 17.5, 17.6, 17.7_
  
  - [x] 6.4 Write property test for conversation context maintenance
    - **Property 14: Conversation Context Maintenance**
    - **Validates: Requirements 5.5, 17.1, 17.4, 17.5**
  
  - [x] 6.5 Write property test for conversation memory limit
    - **Property 15: Conversation Memory Limit**
    - **Validates: Requirements 17.2**
  
  - [x] 6.4 Create PersonalityManager class
    - Implement personality configuration loading from agent.identity fields
    - Implement system prompt generation with personality
    - Add personality validation against allowed values
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_
  
  - [x] 6.7 Write property test for agent personality configuration
    - **Property 34: Agent Personality Configuration**
    - **Validates: Requirements 13.1, 13.2, 13.3, 13.4**


- [-] 7. Implement AgentKernel orchestration
  - [x] 7.1 Create AgentKernel class
    - Implement process_text_message() with dual-LLM coordination
    - Implement plan_task() using lfm2-8b for reasoning
    - Implement execute_plan() using lfm2.5-1.2b-instruct for execution
    - Add inter-model communication and state management
    - Add model failure fallback to single-model mode
    - _Requirements: 3.7, 3.8, 5.1, 5.2, 5.3, 23.4, 23.5, 23.6_
  
  - [x] 7.2 Write property test for agent response generation
    - **Property 9: Agent Response Generation**
    - **Validates: Requirements 3.7, 3.8, 5.2, 5.3**
  
  - [x] 7.3 Write property test for text message processing
    - **Property 13: Text Message Processing**
    - **Validates: Requirements 5.1, 5.2**
  
  - [x] 7.4 Write property test for inter-model communication
    - **Property 55: Inter-Model Communication**
    - **Validates: Requirements 23.4**
  
  - [x] 7.5 Implement get_status() for agent monitoring
    - Return ready status, models_loaded, total_models, tool_bridge_available
    - Return individual model status for both LLMs
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_
  
  - [x] 7.6 Write property test for agent status information
    - **Property 46: Agent Status Information**
    - **Validates: Requirements 18.1-18.7**
  
  - [x] 7.7 Add _handle_chat() and _handle_status() to IRISGateway
    - Route text_message and clear_chat to AgentKernel
    - Route get_agent_status and get_agent_tools to AgentKernel
    - _Requirements: 5.1, 17.3, 18.1_

- [x] 7.5. Implement VPS Gateway for remote model inference
  - [x] 7.5.1 Create VPSGateway class
    - Implement VPSConfig, VPSHealthStatus, VPSInferenceRequest, VPSInferenceResponse models
    - Implement initialize() and shutdown() methods
    - Implement infer() method with routing logic (remote vs local)
    - Implement infer_remote() with HTTP/WebSocket communication
    - Implement infer_local() with ModelRouter integration
    - Add authentication header injection for VPS requests
    - Add request/response serialization and deserialization
    - _Requirements: 26.1, 26.2, 26.3, 26.4, 26.10, 26.11_
  
  - [x] 7.5.2 Write property test for VPS Gateway remote routing
    - **Property 62: VPS Gateway Remote Routing**
    - **Validates: Requirements 26.1**
  
  - [x] 7.5.3 Write property test for VPS Gateway local fallback
    - **Property 63: VPS Gateway Local Fallback**
    - **Validates: Requirements 26.2**
  
  - [x] 7.5.4 Write property test for VPS Gateway authentication
    - **Property 64: VPS Gateway Authentication**
    - **Validates: Requirements 26.4**
  
  - [x] 7.5.5 Implement VPS health monitoring
    - Implement check_vps_health() with ping/health endpoint
    - Add background task for periodic health checks (60s interval)
    - Implement health status tracking per endpoint
    - Add automatic fallback on health check failure
    - Add automatic resume on health check success
    - _Requirements: 26.6, 26.7, 26.8_
  
  - [x] 7.5.6 Write property test for VPS health check recovery
    - **Property 66: VPS Health Check Recovery**
    - **Validates: Requirements 26.7, 26.8**
  
  - [x] 7.5.7 Implement VPS timeout handling
    - Add configurable timeout for VPS requests (default 30s)
    - Implement timeout detection and cancellation
    - Add fallback to local execution on timeout
    - Log timeout events for monitoring
    - _Requirements: 26.5_
  
  - [x] 7.5.8 Write property test for VPS Gateway timeout
    - **Property 65: VPS Gateway Timeout**
    - **Validates: Requirements 26.5**
  
  - [x] 7.5.9 Implement VPS load balancing (optional)
    - Implement select_endpoint() with round-robin or least-loaded strategy
    - Add per-endpoint health tracking
    - Implement automatic removal of failed endpoints from rotation
    - Add endpoint recovery and re-addition to rotation
    - _Requirements: 26.9_
  
  - [x] 7.5.10 Write property test for VPS load balancing
    - **Property 69: VPS Load Balancing**
    - **Validates: Requirements 26.9**
  
  - [x] 7.5.11 Write property test for VPS request serialization round-trip
    - **Property 67: VPS Request Serialization Round-Trip**
    - **Validates: Requirements 26.10, 26.11**
  
  - [x] 7.5.12 Write property test for VPS dual-LLM architecture preservation
    - **Property 68: VPS Dual-LLM Architecture Preservation**
    - **Validates: Requirements 26.12**
  
  - [x] 7.5.13 Integrate VPSGateway with AgentKernel
    - Update AgentKernel to use VPSGateway instead of direct ModelRouter
    - Add VPS status to agent_status response
    - Add VPS configuration fields to settings (agent.vps subnode)
    - Add VPS logging for debugging and monitoring
    - _Requirements: 26.13, 26.14, 26.15, 26.16_
  
  - [x] 7.5.14 Add VPS configuration UI fields to DarkGlassDashboard
    - Add agent.vps subnode with fields: enabled, endpoints, auth_token, timeout, health_check_interval, fallback_to_local, load_balancing, protocol
    - Add VPS status indicator showing current endpoint and health
    - _Requirements: 26.16_

- [ ] 8. Checkpoint - Ensure agent system tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [x] 9. Implement MCP tool integration
  - [x] 9.1 Create MCPClient and ServerManager classes
    - Implement MCP server startup for BrowserServer, AppLauncherServer, SystemServer, FileManagerServer, GUIAutomationServer
    - Implement server health monitoring and automatic restart
    - Add error handling for server startup failures
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8_
  
  - [x] 9.2 Write property test for MCP server startup resilience
    - **Property 42: MCP Server Startup Resilience**
    - **Validates: Requirements 16.7**
  
  - [x] 9.3 Create SecurityFilter class
    - Implement parameter validation against security allowlists
    - Implement destructive operation detection and confirmation
    - Implement rate limiting (max 10 executions per minute)
    - Add input sanitization for all tool parameters
    - _Requirements: 8.7, 24.1, 24.2, 24.4, 24.5, 24.6_
  
  - [x] 9.4 Write property test for security allowlist enforcement
    - **Property 26: Security Allowlist Enforcement**
    - **Validates: Requirements 8.7, 24.1, 24.2**
  
  - [x] 9.5 Write property test for tool execution rate limiting
    - **Property 61: Tool Execution Rate Limiting**
    - **Validates: Requirements 24.6**
  
  - [x] 9.6 Create AuditLogger class
    - Implement tool execution logging with timestamps and parameters
    - Add suspicious activity pattern detection
    - _Requirements: 24.3, 24.7_
  
  - [x] 9.7 Write property test for tool execution audit logging
    - **Property 58: Tool Execution Audit Logging**
    - **Validates: Requirements 24.3**


- [x] 10. Implement AgentToolBridge
  - [x] 10.1 Create VisionSystem class
    - Implement screen monitoring with configurable interval
    - Implement screen capture and analysis using configured vision model
    - Add integration with Ollama endpoint
    - Implement proactive monitoring mode
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6_
  
  - [x] 10.2 Write property test for vision system configuration
    - **Property 39: Vision System Configuration**
    - **Validates: Requirements 15.1, 15.2, 15.3**
  
  - [x] 10.3 Write property test for vision context integration
    - **Property 41: Vision Context Integration**
    - **Validates: Requirements 15.7**
  
  - [x] 10.4 Create AgentToolBridge class
    - Implement initialize() to start all MCP servers
    - Implement get_available_tools() listing all MCP tools
    - Implement execute_tool() with routing to appropriate server
    - Implement execute_mcp_tool(), execute_vision_tool(), execute_gui_tool()
    - Add tool result integration with AgentKernel context
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  
  - [x] 10.5 Write property test for tool availability
    - **Property 22: Tool Availability**
    - **Validates: Requirements 8.1, 8.2**
  
  - [x] 10.6 Write property test for tool execution routing
    - **Property 23: Tool Execution Routing**
    - **Validates: Requirements 8.3, 8.4**
  
  - [x] 10.7 Write property test for tool execution error handling
    - **Property 24: Tool Execution Error Handling**
    - **Validates: Requirements 8.5, 19.3**

- [ ] 11. Checkpoint - Ensure tool system tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [-] 12. Implement voice pipeline infrastructure
  - [x] 12.1 Create AudioEngine class
    - Implement thin wrapper around LFM 2.5 audio model
    - Implement initialize() to load LFM 2.5 audio model
    - Implement start_audio_interaction() and stop_audio_interaction()
    - Implement process_audio() to pass audio to LFM 2.5 model
    - LFM 2.5 handles: device management, audio capture, audio playback, device fallback
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 4.5.1, 4.5.2_
  
  - [x] 12.2 Write property test for audio device configuration
    - **Property 30: Audio Device Configuration**
    - **Validates: Requirements 11.1, 11.2**
  
  - [x] 12.3 Write property test for audio device fallback
    - **Property 31: Audio Device Fallback**
    - **Validates: Requirements 11.5**
  
  - [x] 12.4 Implement audio processing pipeline
    - **NOT NEEDED** - LFM 2.5 audio model handles all audio processing internally
    - LFM 2.5 handles: noise reduction, echo cancellation, voice enhancement, automatic gain control
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 4.5.3_
  
  - [x] 12.5 Write property test for voice processing configuration
    - **Property 32: Voice Processing Configuration**
    - **Validates: Requirements 12.1, 12.2, 12.3, 12.4**
  
  - [x] 12.6 Write property test for voice processing order
    - **Property 33: Voice Processing Order**
    - **Validates: Requirements 12.6**


- [x] 13. Implement LFM 2.5 audio model integration
  - [x] 13.1 Create LFMAudioManager class
    - Implement LFM 2.5 audio model initialization and loading
    - Implement end-to-end audio processing (audio-in to audio-out)
    - LFM 2.5 handles internally: wake word detection, VAD, STT, conversation, TTS
    - Add configuration for wake phrases, sensitivity, voice characteristics, speaking rate
    - _Requirements: 4.1, 4.4, 4.5, 4.6, 4.5.1-4.5.10_
  
  - [x] 13.2 Write property test for wake word detection activation
    - **Property 11: Wake Word Detection Activation**
    - **Validates: Requirements 4.1, 4.2**
  
  - [x] 13.3 Write property test for wake word configuration
    - **Property 12: Wake Word Configuration**
    - **Validates: Requirements 4.4**
  
  - [x] 13.4 Write integration test for LFM 2.5 end-to-end processing
    - Test audio input → wake word → VAD → STT → conversation → TTS → audio output
    - Verify LFM 2.5 handles all processing internally
    - _Requirements: 4.5.1-4.5.10_

- [x] 14. Implement VoicePipeline orchestration
  - [x] 14.1 Create VoicePipeline class
    - Implement start_listening() to activate LFM 2.5 audio model
    - Implement stop_listening() to deactivate LFM 2.5 audio model
    - Implement process_audio() to pass audio to LFM 2.5 model
    - Add get_audio_level() for real-time level monitoring from LFM 2.5
    - Add voice state management (idle, listening, processing_conversation, processing_tool, speaking, error)
    - LFM 2.5 handles: audio capture, wake word, VAD, STT, conversation, TTS, audio playback
    - _Requirements: 3.2, 3.3, 3.5, 3.6, 9.1, 22.1, 22.3, 22.5, 22.7, 4.5.1-4.5.10_
  
  - [x] 14.2 Write property test for voice command state transitions
    - **Property 7: Voice Command State Transitions**
    - **Validates: Requirements 3.2, 3.3**
  
  - [x] 14.3 Write property test for voice command processing
    - **Property 8: Voice Command Processing**
    - **Validates: Requirements 3.5, 3.6**
  
  - [x] 14.4 Write property test for audio level updates
    - **Property 52: Audio Level Updates**
    - **Validates: Requirements 22.1, 22.3**
  
  - [x] 14.5 Add _handle_voice() to IRISGateway
    - Route voice_command_start and voice_command_end to VoicePipeline
    - Send listening_state updates to all clients
    - Send audio_level updates during listening
    - _Requirements: 3.1, 3.4, 9.1, 22.1_


- [x] 15. Implement TTS configuration
  - [x] 15.1 Add TTS configuration to LFMAudioManager
    - Implement voice characteristics configuration (Nova, Alloy, Echo, Fable, Onyx, Shimmer)
    - Implement speaking rate configuration (0.5x to 2.0x)
    - LFM 2.5 handles TTS synthesis internally
    - LFM 2.5 maintains audio quality at all speaking rates
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 4.5.8_
  
  - [x] 15.2 Write property test for TTS voice configuration
    - **Property 37: TTS Voice Configuration**
    - **Validates: Requirements 14.1, 14.2, 14.5**
  
  - [x] 15.3 Write property test for TTS audio output
    - **Property 38: TTS Audio Output**
    - **Validates: Requirements 14.7**
  
  - [x] 15.4 Integrate TTS configuration with AgentKernel
    - Pass TTS configuration to LFM 2.5 audio model
    - Update voice state to "speaking" during audio playback
    - _Requirements: 3.8, 9.1_

- [ ] 16. Checkpoint - Ensure voice system tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [x] 17. Implement frontend NavigationContext
  - [x] 17.1 Create WebSocket client connection logic
    - Implement connection to ws://localhost:8000/ws/{client_id}
    - Add exponential backoff retry (1s, 2s, 4s) up to 3 attempts
    - Add connection loss detection and "Backend offline" message
    - Implement ping/pong heartbeat handling
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6_
  
  - [x] 17.2 Write property test for connection retry with exponential backoff
    - **Property 2: Connection Retry with Exponential Backoff**
    - **Validates: Requirements 1.3**
  
  - [x] 17.3 Write property test for ping-pong heartbeat
    - **Property 3: Ping-Pong Heartbeat**
    - **Validates: Requirements 1.6**
  
  - [x] 17.2 Create NavigationContext with state management
    - Define NavigationContextValue interface with all state and actions
    - Implement WebSocket message handlers for all server messages
    - Add state synchronization with optimistic updates
    - Implement selectCategory(), selectSubnode(), updateField(), updateTheme(), confirmMiniNode(), goBack()
    - Implement startVoiceCommand(), endVoiceCommand()
    - Implement sendMessage(), clearChat()
    - Implement getAgentStatus(), getAgentTools()
    - _Requirements: 1.2, 2.6, 6.1, 6.5, 7.1, 7.4, 7.6, 10.1, 21.3, 21.4_
  
  - [x] 17.3 Write property test for theme update round-trip
    - **Property 28: Theme Update Round-Trip**
    - **Validates: Requirements 10.2, 10.6, 10.7**


- [x] 18. Implement IrisOrb component integration
  - [x] 18.1 Update IrisOrb to consume NavigationContext
    - Connect voiceState from context
    - Connect audioLevel from context
    - Implement onDoubleClick to call startVoiceCommand()
    - Implement onSingleClick during listening to call endVoiceCommand()
    - _Requirements: 3.1, 3.4, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_
  
  - [x] 18.2 Implement voice state visualizations
    - Add idle state: base glow, 1.0x scale
    - Add listening state: 1.15x scale, active glow color, audio level animation
    - Add processing_conversation state: 1.08x scale, purple (#7000ff) glow, pulse animation
    - Add processing_tool state: 1.08x scale, purple (#7000ff) glow, pulse animation
    - Add speaking state: 1.1x scale, active glow color, audio jitter animation
    - Add error state: red glow, shake animation, error message overlay
    - _Requirements: 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_
  
  - [x] 18.3 Implement wake word detection response
    - Add wake flash animation (500ms) on wake_detected message
    - Automatically start voice recording on wake detection
    - _Requirements: 4.2, 4.3_
  
  - [x] 18.4 Implement audio level visualization
    - Display audio levels as glow intensity variations
    - Apply smooth interpolation to prevent jitter
    - Reset audio level to 0 when leaving listening state
    - _Requirements: 22.2, 22.4, 22.7_
  
  - [x] 18.5 Implement theme synchronization
    - Update glow color from activeTheme within 100ms
    - _Requirements: 10.3_


- [x] 19. Implement DarkGlassDashboard component integration
  - [x] 19.1 Update DarkGlassDashboard to consume NavigationContext
    - Connect currentCategory, currentSubnode, subnodes from context
    - Connect fieldValues and activeTheme from context
    - Connect onCategorySelect to selectCategory()
    - Connect onSubnodeSelect to selectSubnode()
    - Connect onFieldUpdate to updateField()
    - Connect onConfirm to confirmMiniNode()
    - _Requirements: 6.1, 6.5, 7.1, 7.4, 10.1_
  
  - [x] 19.2 Implement optimistic field updates
    - Update UI immediately on field change
    - Revert to previous value on validation_error
    - Confirm update on field_updated message
    - _Requirements: 6.5, 6.6_
  
  - [x] 19.3 Implement field validation error display
    - Show error message on validation_error
    - Clear error message on successful update
    - _Requirements: 6.4, 19.2, 19.6_
  
  - [x] 19.4 Implement theme synchronization
    - Update accent colors from activeTheme
    - Apply theme changes within 100ms
    - _Requirements: 10.4_
  
  - [x] 19.5 Implement real-time state synchronization
    - Update field values on field_updated from other clients
    - Handle out-of-order updates using timestamps
    - _Requirements: 21.1, 21.2, 21.3, 21.6, 21.7_


- [x] 20. Implement ChatView component integration
  - [x] 20.1 Update ChatView to consume NavigationContext
    - Connect messages from conversation history
    - Connect isTyping from agent processing state
    - Connect onSendMessage to sendMessage()
    - Connect onClearChat to clearChat()
    - _Requirements: 5.1, 5.4, 5.7, 17.3_
  
  - [x] 20.2 Implement message display
    - Display user and assistant messages with sender identification
    - Add auto-scroll to latest message
    - Show typing indicator while agent is processing
    - _Requirements: 5.4, 5.7_
  
  - [x] 20.3 Implement theme synchronization
    - Update UI elements from activeTheme
    - _Requirements: 10.5_
  
  - [x] 20.4 Implement error message display
    - Show error messages in chat for agent errors
    - Show error messages for voice command errors
    - Display errors in a non-intrusive way
    - _Requirements: 5.6, 19.4, 19.5, 19.6_

- [ ] 21. Checkpoint - Ensure frontend integration tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [x] 22. Implement comprehensive error handling
  - [x] 22.1 Add WebSocket layer error handling
    - Handle connection failures with exponential backoff
    - Handle connection loss with reconnection attempts
    - Handle ping timeout with reconnection
    - Handle parse errors with logging and continuation
    - Handle invalid message format with error response
    - _Requirements: 1.3, 1.4, 19.1_
  
  - [x] 22.2 Write property test for WebSocket message parse error handling
    - **Property 47: WebSocket Message Parse Error Handling**
    - **Validates: Requirements 19.1**
  
  - [x] 22.3 Add state management layer error handling
    - Handle validation errors with validation_error messages
    - Handle persistence errors with retry and error response
    - Handle file corruption with default values and warning
    - _Requirements: 6.2, 6.4, 19.2, 20.10_
  
  - [x] 22.4 Write property test for settings file corruption recovery
    - **Property 50: Settings File Corruption Recovery**
    - **Validates: Requirements 20.10**
  
  - [x] 22.5 Add agent layer error handling
    - Handle model loading failures with error status
    - Handle inference timeout (30s) with error response
    - Handle model crash with restart and fallback
    - Handle tool execution errors with error messages
    - _Requirements: 19.4, 23.6_
  
  - [x] 22.6 Write property test for agent kernel error handling
    - **Property 48: Agent Kernel Error Handling**
    - **Validates: Requirements 19.4**
  
  - [x] 22.7 Add voice pipeline layer error handling
    - Handle device unavailable with fallback to default (LFM 2.5 handles this)
    - Handle capture failure with voice_command_error
    - Handle LFM 2.5 model errors with error messages
    - _Requirements: 3.9, 11.5, 19.5_
  
  - [x] 22.8 Write property test for voice command error handling
    - **Property 10: Voice Command Error Handling**
    - **Validates: Requirements 3.9, 19.5**
  
  - [x] 22.9 Implement structured error logging
    - Log all errors with sufficient context for debugging
    - _Requirements: 19.7_
  
  - [x] 22.10 Write property test for structured error logging
    - **Property 49: Structured Error Logging**
    - **Validates: Requirements 19.7**


- [x] 23. Implement remaining property-based tests
  - [x] 23.1 Write property test for clear chat action
    - **Property 16: Clear Chat Action**
    - **Validates: Requirements 17.3**
  
  - [x] 23.2 Write property test for field update confirmation
    - **Property 18: Field Update Confirmation**
    - **Validates: Requirements 6.3, 6.6**
  
  - [x] 23.3 Write property test for subnode navigation
    - **Property 20: Subnode Navigation**
    - **Validates: Requirements 7.4, 7.5**
  
  - [x] 23.4 Write property test for tool results in context
    - **Property 25: Tool Results in Context**
    - **Validates: Requirements 8.6**
  
  - [x] 23.5 Write property test for voice state broadcasting
    - **Property 27: Voice State Broadcasting**
    - **Validates: Requirements 9.1**
  
  - [x] 23.6 Write property test for theme synchronization
    - **Property 29: Theme Synchronization**
    - **Validates: Requirements 10.1, 10.2**
  
  - [x] 23.7 Write property test for personality consistency
    - **Property 35: Personality Consistency**
    - **Validates: Requirements 13.5**
  
  - [x] 23.8 Write property test for personality validation
    - **Property 36: Personality Validation**
    - **Validates: Requirements 13.7**
  
  - [x] 23.9 Write property test for vision system endpoint configuration
    - **Property 40: Vision System Endpoint Configuration**
    - **Validates: Requirements 15.4, 15.5**
  
  - [x] 23.10 Write property test for MCP server health monitoring
    - **Property 43: MCP Server Health Monitoring**
    - **Validates: Requirements 16.8**
  
  - [x] 23.11 Write property test for conversation persistence
    - **Property 44: Conversation Persistence**
    - **Validates: Requirements 17.6**
  
  - [x] 23.12 Write property test for conversation archival
    - **Property 45: Conversation Archival**
    - **Validates: Requirements 17.7**
  
  - [x] 23.13 Write property test for state update ordering
    - **Property 51: State Update Ordering**
    - **Validates: Requirements 21.6, 21.7**
  
  - [x] 23.14 Write property test for audio level reset
    - **Property 53: Audio Level Reset**
    - **Validates: Requirements 22.7**
  
  - [x] 23.15 Write property test for model fallback
    - **Property 56: Model Fallback**
    - **Validates: Requirements 23.6**
  
  - [x] 23.16 Write property test for tool parameter validation
    - **Property 57: Tool Parameter Validation**
    - **Validates: Requirements 24.1**
  
  - [x] 23.17 Write property test for destructive operation confirmation
    - **Property 59: Destructive Operation Confirmation**
    - **Validates: Requirements 24.4**
  
  - [x] 23.18 Write property test for tool input sanitization
    - **Property 60: Tool Input Sanitization**
    - **Validates: Requirements 24.5**
  
  - [x] 23.19 Write property test for VPS Gateway remote routing (if not already completed in 7.5.2)
    - **Property 62: VPS Gateway Remote Routing**
    - **Validates: Requirements 26.1**
  
  - [x] 23.20 Write property test for VPS Gateway local fallback (if not already completed in 7.5.3)
    - **Property 63: VPS Gateway Local Fallback**
    - **Validates: Requirements 26.2**
  
  - [x] 23.21 Write property test for VPS Gateway authentication (if not already completed in 7.5.4)
    - **Property 64: VPS Gateway Authentication**
    - **Validates: Requirements 26.4**
  
  - [x] 23.22 Write property test for VPS Gateway timeout (if not already completed in 7.5.8)
    - **Property 65: VPS Gateway Timeout**
    - **Validates: Requirements 26.5**
  
  - [x] 23.23 Write property test for VPS health check recovery (if not already completed in 7.5.6)
    - **Property 66: VPS Health Check Recovery**
    - **Validates: Requirements 26.7, 26.8**
  
  - [x] 23.24 Write property test for VPS request serialization round-trip (if not already completed in 7.5.11)
    - **Property 67: VPS Request Serialization Round-Trip**
    - **Validates: Requirements 26.10, 26.11**
  
  - [x] 23.25 Write property test for VPS dual-LLM architecture preservation (if not already completed in 7.5.12)
    - **Property 68: VPS Dual-LLM Architecture Preservation**
    - **Validates: Requirements 26.12**
  
  - [x] 23.26 Write property test for VPS load balancing (if not already completed in 7.5.10)
    - **Property 69: VPS Load Balancing**
    - **Validates: Requirements 26.9**


- [x] 24. Implement performance optimizations
  - [x] 24.1 Optimize WebSocket message delivery
    - Ensure message latency below 50ms (p95)
    - Add message batching for high-frequency updates
    - _Requirements: 25.1_
  
  - [x] 24.2 Optimize agent response time
    - Ensure text responses within 5 seconds for simple queries (p95)
    - Add response streaming for long responses
    - _Requirements: 25.2_
  
  - [x] 24.3 Optimize voice processing
    - Ensure voice command processing within 3 seconds (p95)
    - Optimize audio processing pipeline
    - _Requirements: 25.3_
  
  - [x] 24.4 Optimize state persistence
    - Ensure field updates persist within 100ms
    - Add write batching for multiple rapid updates
    - _Requirements: 25.4_
  
  - [x] 24.5 Optimize frontend rendering
    - Ensure UI updates render within 16ms (60 FPS)
    - Add React.memo and useMemo optimizations
    - _Requirements: 25.5_
  
  - [x] 24.6 Optimize tool execution
    - Ensure tool execution within 10 seconds or timeout
    - Add parallel tool execution where possible
    - _Requirements: 25.6_
  
  - [x] 24.7 Test concurrent connection handling
    - Verify backend handles at least 100 concurrent WebSocket connections
    - _Requirements: 25.7_


- [x] 25. Integration testing and end-to-end flows
  - [x] 25.1 Write integration test for WebSocket connection flow
    - Test connection establishment, initial_state delivery, ping/pong
    - Test connection retry and reconnection
    - _Requirements: 1.1, 1.2, 1.3, 1.6_
  
  - [x] 25.2 Write integration test for voice command flow
    - Test voice_command_start → listening → voice_command_end → processing → response
    - Test wake word detection → automatic recording
    - Test audio level updates during listening
    - _Requirements: 3.1-3.9, 4.1-4.6, 22.1-22.7_
  
  - [x] 25.3 Write integration test for text chat flow
    - Test text_message → agent processing → text_response
    - Test conversation context maintenance
    - Test clear_chat functionality
    - _Requirements: 5.1-5.7, 17.1-17.7_
  
  - [x] 25.4 Write integration test for settings flow
    - Test category navigation → subnode selection → field update → persistence
    - Test theme update → synchronization across components
    - Test multi-client synchronization
    - _Requirements: 6.1-6.7, 7.1-7.7, 10.1-10.7, 20.1-20.10, 21.1-21.7_
  
  - [x] 25.5 Write integration test for tool execution flow
    - Test agent tool request → tool execution → result integration
    - Test security filtering and validation
    - Test audit logging
    - _Requirements: 8.1-8.7, 24.1-24.7_
  
  - [x] 25.6 Write integration test for error recovery scenarios
    - Test connection loss and reconnection
    - Test model failure and fallback
    - Test audio device failure and fallback
    - Test MCP server crash and restart
    - Test VPS failure and fallback to local execution
    - Test VPS recovery and resume to remote execution
    - _Requirements: 19.1-19.7, 26.2, 26.7, 26.8_

- [x] 26. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [x] 27. Documentation and deployment preparation
  - [x] 27.1 Create API documentation
    - Document all WebSocket message types and payloads
    - Document all backend classes and methods
    - Document configuration options
    - _Requirements: All_
  
  - [x] 27.2 Create deployment guide
    - Document backend setup and dependencies
    - Document frontend build and configuration
    - Document MCP server setup
    - Document audio device configuration
    - _Requirements: All_
  
  - [x] 27.3 Create troubleshooting guide
    - Document common error scenarios and solutions
    - Document debugging techniques
    - Document log file locations and formats
    - _Requirements: 19.1-19.7_

## Notes

- Tasks marked with `*` are optional property-based tests and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at major milestones
- Property tests validate universal correctness properties with randomized inputs
- Integration tests validate end-to-end flows across components
- The implementation follows a bottom-up approach: infrastructure → agent → voice → frontend → integration
- All 69 correctness properties from the design document are covered by property-based tests (61 original + 8 VPS Gateway properties)
- All 26 requirements are covered by implementation tasks (25 original + 1 VPS Gateway requirement)
- VPS Gateway is optional and can be disabled via configuration - system works fully in local-only mode

## Test Configuration

Property-based tests use:
- **Backend**: Hypothesis (Python) with minimum 100 iterations per test
- **Frontend**: fast-check (TypeScript) with minimum 100 iterations per test
- **Tagging**: Each property test includes a comment tag: `# Feature: irisvoice-backend-integration, Property N: [Title]`
- **Deterministic**: Fixed random seed for reproducibility
- **Shrinking**: Enabled to find minimal failing examples

## Coverage Goals

- Line coverage: >90%
- Branch coverage: >85%
- Function coverage: >95%
- All 69 correctness properties implemented as property tests (61 original + 8 VPS Gateway)
- All critical paths covered by integration tests
- VPS Gateway fallback and recovery scenarios covered by integration tests
