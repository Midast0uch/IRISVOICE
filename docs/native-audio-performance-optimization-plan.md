# Native Audio Performance Optimization & Wake Word Visual Feedback Plan

## Problem Statement
IRIS assistant experiences severe performance issues during native audio processing and wake word detection lacks proper visual feedback synchronization.

## Root Cause Analysis

### 1. Wake Word Visual Feedback Issue
**Problem**: Wake word triggers brief flash but doesn't activate full recording UI state (glow effect, "Listening..." message, audio level visualization).

**Root Cause**: Backend broadcasts `wake_detected` but doesn't trigger same UI state as double-click. UI recording state tied to `voice_command_started` message only sent for manual interactions.

**Current Flow**:
- Wake word detected → `wake_detected` broadcast → UI shows brief flash
- Double-click → `voice_command_start` sent → `voice_command_started` broadcast → Full recording UI activated

### 2. Performance Issues (PC Freezing/Lagging)
**Problem**: Severe system lag during audio processing when model processes speech.

**Root Causes** (in priority order):
1. **Synchronous Generation Blocking**: `generate_interleaved()` blocks main thread
2. **GPU Memory Issues**: VRAM fragmentation, no memory limits
3. **CPU Overload**: RQ-Transformer uses 8 decode steps per token, unlimited cores
4. **Memory Leak**: Unlimited conversation history accumulation
5. **Audio Driver Contention**: Simultaneous recording/processing/playback
6. **Power Management**: Windows CPU/GPU throttling

## Implementation Phases

### Phase 1: Wake Word Visual Feedback Fix
**Goal**: Make wake word trigger identical UI state to double-click

**Files to Modify**:
- `backend/main.py`: Modify `on_wake_detected` callback
- `components/hexagonal-control-center.tsx`: Update `handleWakeDetected` function

**Risk Mitigation**:
- Add state validation to prevent overlapping recordings
- Implement proper error handling and cleanup
- Add comprehensive logging for debugging

### Phase 2: Performance Optimization
**Goal**: Eliminate freezing during audio processing

**Priority Order** (highest impact first):
1. **Async Processing**: Move model generation to background thread
2. **GPU Memory Management**: Add memory limits and cleanup
3. **CPU Thread Limiting**: Restrict processing to max 4 cores
4. **Conversation State Limiting**: Cap history to 10 turns
5. **Audio Driver Optimization**: Separate recording/processing threads

**Files to Modify**:
- `backend/audio/model_manager.py`: Add async wrapper and memory management
- `backend/audio/voice_command.py`: Add CPU affinity and thread safety

**Risk Mitigation**:
- Add comprehensive thread safety with RLock
- Implement progressive GPU memory fallback
- Add feature flags for safe deployment
- Include rollback mechanisms

### Phase 3: Integration Testing & Validation
**Goal**: Ensure all changes work together without regressions

**Testing Strategy**:
1. Memory profiling before/after changes
2. Performance benchmarking with timing measurements
3. Stress testing with rapid repeated triggers
4. Cross-platform compatibility testing

## Implementation Checklist

### Before Each Change:
- [ ] Snapshot current working configuration
- [ ] Add comprehensive debug logging
- [ ] Implement error boundaries with graceful degradation
- [ ] Add feature flags for safe deployment

### During Implementation:
- [ ] Follow existing code conventions and patterns
- [ ] Add inline documentation for all modifications
- [ ] Implement thread safety where applicable
- [ ] Add state validation and cleanup

### After Each Phase:
- [ ] Test wake word functionality with visual feedback
- [ ] Measure performance impact with timing logs
- [ ] Check for memory leaks using profiling tools
- [ ] Validate cross-platform compatibility
- [ ] Document any new configuration requirements

## Risk Assessment Matrix

| Risk Category | Severity | Probability | Mitigation Strategy |
|---------------|----------|-------------|---------------------|
| Thread Safety Issues | High | Medium | Comprehensive locking with RLock |
| GPU Memory Failures | Medium | High | Progressive fallback to CPU |
| State Desync | High | Low | State validation and cleanup |
| CPU Affinity Issues | Low | Medium | Graceful degradation on failure |
| Memory Leaks | Medium | Medium | Conversation history limiting |
| Audio Driver Contention | Medium | Low | Separate processing threads |

## Configuration Flags

```python
# Feature flags for safe deployment
ENABLE_ASYNC_PROCESSING = True
ENABLE_GPU_MEMORY_MANAGEMENT = True
ENABLE_CPU_AFFINITY = True
ENABLE_CONVERSATION_LIMITING = True
```

## Rollback Plan

If issues arise:
1. Set feature flags to False to disable new functionality
2. Revert to previous commit if necessary
3. Check logs for specific error patterns
4. Validate audio pipeline integrity

## Success Criteria

### Wake Word Visual Feedback:
- [ ] Wake word triggers same UI state as double-click
- [ ] No overlapping recording sessions
- [ ] Proper error handling and cleanup
- [ ] Visual feedback consistent across platforms

### Performance Optimization:
- [ ] No UI freezing during audio processing
- [ ] Response time under 2 seconds for typical queries
- [ ] Memory usage stable (no continuous growth)
- [ ] CPU usage reasonable (under 50% on 4-core systems)
- [ ] GPU memory usage under 80% of available VRAM

## Monitoring & Logging

Add these log categories:
- `[WakeWordVisual]` - Wake word UI state changes
- `[Performance]` - Timing measurements for each phase
- `[Memory]` - Memory usage before/after processing
- `[ThreadSafety]` - Lock acquisition/release events
- `[Fallback]` - Any fallback to previous behavior

## Reference Files
- Current implementation: `backend/main.py`, `components/hexagonal-control-center.tsx`
- Model processing: `backend/audio/model_manager.py`
- Voice command handling: `backend/audio/voice_command.py`
- WebSocket communication: `hooks/useIRISWebSocket.ts`

---

**Document Version**: 1.0  
**Last Updated**: 2026-02-15  
**Status**: Ready for Implementation  
**Next Review**: After Phase 1 completion