# Requirements: Vision System Optimization & Critical Fixes

## Introduction

This spec addresses two major areas: (1) optimizing the MiniCPM vision model for lower memory usage through 4-bit quantization and user-controlled lazy loading, and (2) fixing critical type safety and validation gaps identified in the Agent Kernel and Tool Bridge audit.

## Requirements

### Requirement 1: 4-Bit Quantization for MiniCPM

**User Story:** As a user, I want the vision model to use less VRAM, so that IRIS can run on systems with limited GPU memory.

#### Acceptance Criteria

1. WHEN the vision model is loaded THE SYSTEM SHALL use 4-bit quantization (BitsAndBytesConfig)
2. THE SYSTEM SHALL reduce VRAM usage from 8-12 GB to 3-4 GB
3. IF quantization libraries are not available THE SYSTEM SHALL fall back to standard loading with a warning
4. THE SYSTEM SHALL maintain acceptable inference speed (< 2x slowdown)

### Requirement 2: User-Controlled Lazy Loading

**User Story:** As a user, I want the vision model to only load when I explicitly enable it, so that IRIS doesn't consume resources until needed.

#### Acceptance Criteria

1. THE SYSTEM SHALL provide a "vision_enabled" toggle in the UI
2. WHEN the application starts THE SYSTEM SHALL NOT load the vision model automatically
3. WHEN the user enables vision THE SYSTEM SHALL load the model on-demand (lazy loading)
4. WHEN the user disables vision THE SYSTEM SHALL unload the model and free VRAM
5. THE SYSTEM SHALL display loading progress and estimated wait time to the user

### Requirement 3: Tool Bridge Input Validation

**User Story:** As a developer, I want tool parameters to be validated before execution, so that invalid inputs don't crash the system or cause unexpected behavior.

#### Acceptance Criteria

1. WHEN a tool is called THE SYSTEM SHALL validate parameters against a JSON schema
2. IF parameters are invalid THE SYSTEM SHALL return a typed error response (not Dict[str, Any])
3. THE SYSTEM SHALL sanitize all user inputs before passing to tools
4. THE SYSTEM SHALL log all validation failures with context for debugging

### Requirement 4: Agent Kernel Input Sanitization

**User Story:** As a user, I want my inputs to be sanitized before processing, so that malicious or malformed input doesn't compromise the system.

#### Acceptance Criteria

1. WHEN text is received from the user THE SYSTEM SHALL sanitize HTML/script tags
2. THE SYSTEM SHALL validate session_id format before processing
3. THE SYSTEM SHALL implement rate limiting per session (max 10 requests/minute)
4. WHEN input exceeds 10,000 characters THE SYSTEM SHALL truncate with a warning

### Requirement 5: Type Safety in Tool Interfaces

**User Story:** As a developer, I want type-safe tool interfaces, so that type errors are caught at development time rather than runtime.

#### Acceptance Criteria

1. THE SYSTEM SHALL replace all `Dict[str, Any]` tool parameters with Pydantic models
2. THE SYSTEM SHALL replace all `Dict[str, Any]` return types with typed responses
3. THE SYSTEM SHALL add mypy type checking to the CI pipeline
4. THE SYSTEM SHALL not use `Any` type in any public API

### Requirement 6: Vision System Consolidation

**User Story:** As a maintainer, I want a single vision system instead of four overlapping ones, so that the codebase is easier to maintain.

#### Acceptance Criteria

1. THE SYSTEM SHALL consolidate MiniCPMClient, VisionSystem, VisionModelClient, and GUIToolkit into a single VisionService
2. THE SYSTEM SHALL maintain backward compatibility during migration
3. THE deprecated components SHALL be marked with deprecation warnings
4. THE SYSTEM SHALL remove deprecated components after 2 release cycles

## Critical Issues Summary

| Priority | Issue | Current State | Target State |
|----------|-------|---------------|--------------|
| P0 | MiniCPM Memory Usage | 8-12 GB VRAM | 3-4 GB VRAM |
| P0 | Uncontrolled Model Loading | Auto-load on startup | User-controlled lazy loading |
| P1 | Tool Bridge Validation | No validation | JSON Schema validation |
| P1 | Agent Kernel Sanitization | No sanitization | Input sanitization + rate limiting |
| P2 | Type Safety | Dict[str, Any] | Pydantic models |
| P2 | Vision System Redundancy | 4 implementations | 1 consolidated service |

## References

- `backend/vision/minicpm_client.py` - Current MiniCPM client (Ollama-based)
- `backend/agent/gui_toolkit.py` - Local MiniCPM loader (unused)
- `backend/tools/vision_system.py` - Vision system wrapper
- `backend/agent/tool_bridge.py` - Tool execution (no validation)
- `backend/agent/agent_kernel.py` - Message processing (no sanitization)
