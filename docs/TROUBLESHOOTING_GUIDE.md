# IRISVOICE Troubleshooting Guide

## Table of Contents

1. [Common Error Scenarios](#common-error-scenarios)
2. [Debugging Techniques](#debugging-techniques)
3. [Log Files](#log-files)
4. [Component-Specific Issues](#component-specific-issues)
5. [Performance Issues](#performance-issues)
6. [Quick Fixes](#quick-fixes)

---

## Common Error Scenarios

### 1. Backend Connection Issues

#### Symptom: "Backend offline - running in standalone mode"

**Cause:** The frontend cannot connect to the backend WebSocket server.

**Solutions:**

1. **Check if backend is running:**
   ```bash
   # Windows
   tasklist | findstr python
   
   # macOS/Linux
   ps aux | grep python
   ```

2. **Verify backend is listening on port 8000:**
   ```bash
   # Windows
   netstat -an | findstr 8000
   
   # macOS/Linux
   netstat -an | grep 8000
   ```

3. **Start the backend:**
   ```bash
   cd IRISVOICE
   python start-backend.py
   ```

4. **Check for port conflicts:**
   - Another application may be using port 8000
   - Change the port in `backend/main.py` if needed

5. **Firewall issues:**
   - Ensure Windows Firewall or antivirus isn't blocking port 8000
   - Add an exception for Python or the IRISVOICE application


#### Symptom: WebSocket connection drops frequently

**Cause:** Network instability, backend crashes, or ping/pong timeout.

**Solutions:**

1. **Check backend logs for crashes:**
   ```bash
   tail -f backend/logs/irisvoice.log
   ```

2. **Verify ping/pong heartbeat:**
   - The system sends pings every 30 seconds
   - Check logs for "ping timeout" messages

3. **Increase timeout values:**
   - Edit `backend/ws_manager.py` to increase ping interval
   - Default is 30 seconds, try 60 seconds

4. **Check system resources:**
   - High CPU/memory usage can cause connection drops
   - Monitor with Task Manager (Windows) or `top` (Linux/macOS)

---

### 2. Model Loading Failures

#### Symptom: "Agent kernel is not available" or "Models not loaded"

**Cause:** AI models failed to load due to missing files, insufficient memory, or CUDA errors.

**Solutions:**

1. **Verify models are downloaded:**
   ```bash
   ls -la models/LFM2-8B-A1B/
   ls -la models/LFM2.5-1.2B-Instruct/
   ```

2. **Re-download models:**
   ```bash
   python download_text_model.py
   python download_lfm_audio.py
   ```

3. **Check available RAM:**
   - LFM2-8B requires ~16GB RAM
   - LFM2.5-1.2B-Instruct requires ~4GB RAM
   - Total: ~20GB RAM minimum

4. **CUDA out of memory (GPU users):**
   ```bash
   # Check GPU memory
   nvidia-smi
   
   # Force CPU mode by setting environment variable
   export CUDA_VISIBLE_DEVICES=""
   ```

5. **Check model file integrity:**
   - Corrupted downloads can cause loading failures
   - Delete and re-download if checksums don't match


---

### 3. Voice Command Issues

#### Symptom: Wake word not detected

**Cause:** LFM 2.5 audio model not initialized, incorrect audio device, or sensitivity too low.

**Solutions:**

1. **Check audio device configuration:**
   ```bash
   python check_devices.py
   ```

2. **Verify microphone is working:**
   - Test with Windows Sound Recorder or macOS Voice Memos
   - Check microphone permissions in system settings

3. **Adjust wake word sensitivity:**
   - Open Settings → Voice → Wake → Detection Sensitivity
   - Increase from default (70%) to 80-90%

4. **Check configured wake phrase:**
   - Default phrases: "jarvis", "hey computer", "computer", "bumblebee", "porcupine"
   - Verify in Settings → Agent → Wake → Wake Phrase

5. **LFM 2.5 audio model not loaded:**
   - Check logs: `grep "LFM.*audio" backend/logs/irisvoice.log`
   - Re-download: `python download_lfm_audio.py`

#### Symptom: Voice commands not transcribed correctly

**Cause:** Poor audio quality, background noise, or incorrect audio processing settings.

**Solutions:**

1. **Improve audio quality:**
   - Use a high-quality USB microphone
   - Reduce background noise
   - Speak clearly and at normal volume

2. **Check audio levels:**
   - Open Settings → Voice → Input → Input Volume
   - Adjust to 70-80% for optimal recognition

3. **LFM 2.5 handles audio processing internally:**
   - No manual configuration needed for noise reduction, echo cancellation
   - The model automatically applies optimal processing

4. **Test with double-click activation:**
   - Double-click the IrisOrb to manually start listening
   - This bypasses wake word detection


---

### 4. Settings Not Persisting

#### Symptom: Settings reset after application restart

**Cause:** Settings file corruption, permission issues, or state manager errors.

**Solutions:**

1. **Check settings files exist:**
   ```bash
   ls -la backend/settings/
   ```
   Should contain: `voice.json`, `agent.json`, `automate.json`, `system.json`, `customize.json`, `monitor.json`, `theme.json`

2. **Verify file permissions:**
   ```bash
   # Windows
   icacls backend\settings\*.json
   
   # macOS/Linux
   ls -la backend/settings/*.json
   ```

3. **Check for corruption:**
   - Open each JSON file and verify valid JSON syntax
   - Look for truncated files or invalid characters

4. **Reset to defaults:**
   ```bash
   # Backup current settings
   cp -r backend/settings backend/settings.backup
   
   # Delete corrupted files (they will be recreated with defaults)
   rm backend/settings/*.json
   ```

5. **Check logs for write errors:**
   ```bash
   grep "settings.*error" backend/logs/irisvoice.log
   ```

---

### 5. VPS Gateway Issues

#### Symptom: "VPS unavailable, falling back to local execution"

**Cause:** VPS endpoint unreachable, authentication failure, or network issues.

**Solutions:**

1. **Verify VPS endpoint URL:**
   - Open Settings → Agent → VPS → Endpoints
   - Ensure URL is correct (e.g., `https://vps.example.com:8000`)

2. **Check VPS authentication:**
   - Verify auth token is correct
   - Test with curl:
     ```bash
     curl -H "Authorization: Bearer YOUR_TOKEN" https://vps.example.com:8000/health
     ```

3. **Test network connectivity:**
   ```bash
   ping vps.example.com
   telnet vps.example.com 8000
   ```

4. **Check VPS health status:**
   - Look for health check failures in logs:
     ```bash
     grep "VPS.*health" backend/logs/irisvoice.log
     ```

5. **Increase timeout:**
   - Open Settings → Agent → VPS → Timeout
   - Increase from 30s to 60s for slow connections

6. **Verify VPS server is running:**
   - SSH into VPS and check if the inference service is running
   - Check VPS logs for errors


---

### 6. MCP Tool Execution Failures

#### Symptom: "Tool execution failed" or "Tool not available"

**Cause:** MCP servers not started, security policy violations, or tool errors.

**Solutions:**

1. **Check MCP server status:**
   ```bash
   grep "MCP.*server" backend/logs/irisvoice.log
   ```

2. **Verify all MCP servers started:**
   - BrowserServer (web browsing)
   - AppLauncherServer (application control)
   - SystemServer (system operations)
   - FileManagerServer (file operations)
   - GUIAutomationServer (UI automation)

3. **Restart MCP servers:**
   - Restart the backend to reinitialize all MCP servers
   - Check for startup errors in logs

4. **Security policy violations:**
   - Check if the tool operation is blocked by security filters
   - Look for "Security policy violation" in logs
   - Review allowlists in `backend/security/`

5. **Tool-specific errors:**
   - Vision tools: Verify Ollama endpoint is accessible
   - File tools: Check file permissions
   - System tools: May require elevated privileges

6. **Rate limiting:**
   - Default limit: 10 tool executions per minute
   - Wait 60 seconds or adjust rate limit in `backend/security/security_filter.py`

---

### 7. Session and State Issues

#### Symptom: Multiple windows show different states

**Cause:** State synchronization failure or session isolation issues.

**Solutions:**

1. **Check session ID:**
   - All windows should use the same session ID
   - Look for "session_id" in browser console or logs

2. **Verify WebSocket connections:**
   - Each window should have an active WebSocket connection
   - Check browser console for connection errors

3. **Check state broadcast:**
   ```bash
   grep "broadcast.*state" backend/logs/irisvoice.log
   ```

4. **Clear session data:**
   ```bash
   # Backup sessions
   cp -r backend/sessions backend/sessions.backup
   
   # Delete session data
   rm -rf backend/sessions/*
   ```

5. **Restart all clients:**
   - Close all browser windows/tabs
   - Restart the application


---

## Debugging Techniques

### 1. Enable Debug Logging

**Increase log verbosity to see detailed information:**

```bash
# Set environment variable before starting backend
export IRIS_LOG_LEVEL=DEBUG

# Windows
set IRIS_LOG_LEVEL=DEBUG

# Then start backend
python start-backend.py
```

**What you'll see:**
- All WebSocket messages sent/received
- Model inference details
- State changes and synchronization
- Tool execution parameters and results
- Audio processing events

### 2. Monitor Real-Time Logs

**Tail the log file to see events as they happen:**

```bash
# Linux/macOS
tail -f backend/logs/irisvoice.log

# Windows (PowerShell)
Get-Content backend\logs\irisvoice.log -Wait -Tail 50
```

**Filter for specific components:**

```bash
# WebSocket events
grep "websocket" backend/logs/irisvoice.log

# Agent events
grep "agent" backend/logs/irisvoice.log

# Voice events
grep "voice" backend/logs/irisvoice.log

# Errors only
grep "ERROR" backend/logs/irisvoice.log
```

### 3. Browser Developer Tools

**Open browser console (F12) to see frontend logs:**

1. **Console tab:**
   - WebSocket connection status
   - Message send/receive events
   - React component errors
   - State updates

2. **Network tab:**
   - WebSocket connection details
   - Message payloads
   - Connection timing

3. **Application tab:**
   - LocalStorage data
   - Session storage
   - Cookies

**Useful console commands:**

```javascript
// Check WebSocket connection
console.log(window.ws)

// View current navigation state
console.log(localStorage.getItem('navigationState'))

// Clear local storage
localStorage.clear()
```


### 4. Test Individual Components

**Test backend components in isolation:**

```bash
# Test WebSocket manager
python -m pytest tests/test_websocket_manager.py -v

# Test agent kernel
python -m pytest tests/test_agent_kernel.py -v

# Test state manager
python -m pytest tests/test_state_manager.py -v

# Test VPS gateway
python -m pytest tests/test_vps_gateway.py -v

# Run all integration tests
python -m pytest tests/integration/ -v
```

**Test audio devices:**

```bash
python check_devices.py
```

**Test model loading:**

```bash
python -c "from backend.agent.model_router import ModelRouter; router = ModelRouter(); print('Models loaded successfully')"
```

### 5. Inspect WebSocket Messages

**Use a WebSocket debugging tool:**

1. **Browser extension:** "WebSocket Test Client" or "Simple WebSocket Client"
2. **Connect to:** `ws://localhost:8000/ws/debug-client`
3. **Send test messages:**

```json
{
  "type": "get_agent_status",
  "payload": {}
}
```

**Expected response:**

```json
{
  "type": "agent_status",
  "payload": {
    "ready": true,
    "models_loaded": 2,
    "total_models": 2,
    "tool_bridge_available": true
  }
}
```

### 6. Check System Resources

**Monitor CPU, memory, and GPU usage:**

```bash
# Windows
taskmgr

# Linux
htop
nvidia-smi  # For GPU

# macOS
Activity Monitor (GUI)
top  # Terminal
```

**Python memory profiling:**

```bash
pip install memory_profiler
python -m memory_profiler start-backend.py
```


---

## Log Files

### Log File Locations

**Backend logs:**
- **Main log:** `backend/logs/irisvoice.log`
- **Location:** Relative to IRISVOICE directory
- **Rotation:** Automatically rotates when file exceeds 10MB
- **Retention:** Keeps last 5 log files

**Session data:**
- **Location:** `backend/sessions/{session_id}/`
- **Contents:** Conversation history, session state
- **Archival:** Sessions archived after 24 hours of inactivity

**Settings files:**
- **Location:** `backend/settings/`
- **Files:**
  - `voice.json` - Voice input/output settings
  - `agent.json` - Agent personality and behavior
  - `automate.json` - Tool and automation settings
  - `system.json` - System configuration
  - `customize.json` - UI customization
  - `monitor.json` - Monitoring settings
  - `theme.json` - Theme colors

**Frontend logs:**
- **Browser console:** Press F12 → Console tab
- **Tauri logs (desktop app):** Check application data directory

### Log Format

**Structured JSON logging:**

```json
{
  "timestamp": "2024-02-05T19:30:45.123Z",
  "level": "INFO",
  "component": "websocket",
  "message": "Client connected",
  "client_id": "abc123",
  "session_id": "session-xyz",
  "context": {
    "ip_address": "127.0.0.1"
  }
}
```

**Log levels:**
- `DEBUG`: Detailed diagnostic information
- `INFO`: General informational messages
- `WARNING`: Warning messages (non-critical issues)
- `ERROR`: Error messages (operation failed)
- `CRITICAL`: Critical errors (system failure)

### Reading Logs

**Find specific events:**

```bash
# Connection events
grep "connected\|disconnected" backend/logs/irisvoice.log

# Model inference
grep "inference\|generate" backend/logs/irisvoice.log

# Tool execution
grep "tool.*execute" backend/logs/irisvoice.log

# Errors and warnings
grep -E "ERROR|WARNING" backend/logs/irisvoice.log

# Specific session
grep "session-xyz" backend/logs/irisvoice.log

# Time range (last hour)
grep "2024-02-05T19:" backend/logs/irisvoice.log
```

**Parse JSON logs with jq:**

```bash
# Extract all error messages
cat backend/logs/irisvoice.log | jq 'select(.level == "ERROR") | .message'

# Count errors by component
cat backend/logs/irisvoice.log | jq 'select(.level == "ERROR") | .component' | sort | uniq -c

# Show WebSocket events
cat backend/logs/irisvoice.log | jq 'select(.component == "websocket")'
```


---

## Component-Specific Issues

### WebSocket Manager

**Common issues:**
- Connection refused
- Ping timeout
- Message parse errors

**Debug commands:**

```bash
# Check WebSocket connections
grep "websocket.*connect" backend/logs/irisvoice.log

# Check for timeouts
grep "timeout" backend/logs/irisvoice.log

# Check message errors
grep "parse.*error\|invalid.*message" backend/logs/irisvoice.log
```

**Configuration:**
- Ping interval: 30 seconds (configurable in `backend/ws_manager.py`)
- Max connections: 100 (configurable)
- Message size limit: 1MB

---

### Agent Kernel

**Common issues:**
- Model not loaded
- Inference timeout
- Out of memory

**Debug commands:**

```bash
# Check model status
grep "model.*load\|model.*ready" backend/logs/irisvoice.log

# Check inference timing
grep "inference.*time\|generate.*time" backend/logs/irisvoice.log

# Check memory usage
grep "memory\|OOM" backend/logs/irisvoice.log
```

**Configuration:**
- Inference timeout: 30 seconds
- Max conversation history: 10 messages (configurable in Settings → Agent → Memory)
- Model offloading: Automatic (uses CPU offload for large models)

---

### Voice Pipeline

**Common issues:**
- Audio device not found
- Wake word not detected
- Audio quality issues

**Debug commands:**

```bash
# Check audio device initialization
grep "audio.*device\|audio.*init" backend/logs/irisvoice.log

# Check wake word detection
grep "wake.*detect\|wake.*phrase" backend/logs/irisvoice.log

# Check audio processing
grep "audio.*process\|audio.*level" backend/logs/irisvoice.log
```

**Configuration:**
- Input device: Configurable in Settings → Voice → Input
- Output device: Configurable in Settings → Voice → Output
- Wake phrase: Configurable in Settings → Agent → Wake
- Sensitivity: 0-100% (default 70%)


---

### State Manager

**Common issues:**
- Settings not persisting
- State synchronization failures
- File corruption

**Debug commands:**

```bash
# Check state updates
grep "state.*update\|field.*update" backend/logs/irisvoice.log

# Check persistence errors
grep "persist.*error\|save.*error" backend/logs/irisvoice.log

# Check file operations
grep "file.*write\|file.*read" backend/logs/irisvoice.log
```

**Configuration:**
- Auto-save: Enabled (saves on every field update)
- Backup: Atomic writes with backup
- Validation: Enabled (validates against field schemas)

---

### VPS Gateway

**Common issues:**
- VPS unreachable
- Authentication failure
- Timeout errors

**Debug commands:**

```bash
# Check VPS connection
grep "VPS.*connect\|VPS.*endpoint" backend/logs/irisvoice.log

# Check health checks
grep "VPS.*health" backend/logs/irisvoice.log

# Check fallback events
grep "fallback.*local" backend/logs/irisvoice.log
```

**Configuration:**
- Endpoints: Configurable in Settings → Agent → VPS
- Auth token: Stored securely in settings
- Timeout: 30 seconds (configurable)
- Health check interval: 60 seconds
- Fallback: Enabled by default

---

### Tool Bridge

**Common issues:**
- MCP server not started
- Tool execution timeout
- Security policy violations

**Debug commands:**

```bash
# Check MCP server status
grep "MCP.*server.*start\|MCP.*server.*ready" backend/logs/irisvoice.log

# Check tool execution
grep "tool.*execute\|tool.*result" backend/logs/irisvoice.log

# Check security filters
grep "security.*filter\|security.*violation" backend/logs/irisvoice.log
```

**Configuration:**
- Tool timeout: 10 seconds
- Rate limit: 10 executions per minute
- Security allowlists: Defined in `backend/security/`
- Audit logging: Enabled (logs all tool executions)


---

## Performance Issues

### Slow Response Times

**Symptom:** Agent takes >10 seconds to respond

**Causes and solutions:**

1. **CPU/GPU overload:**
   - Check system resources with Task Manager or `top`
   - Close other applications
   - Consider using VPS Gateway to offload inference

2. **Large conversation history:**
   - Reduce conversation memory limit in Settings → Agent → Memory
   - Default is 10 messages, try 5 messages

3. **Model offloading:**
   - Large models may offload to disk
   - Increase RAM or use smaller models
   - Enable GPU acceleration if available

4. **Network latency (VPS mode):**
   - Check VPS ping time
   - Increase timeout in Settings → Agent → VPS
   - Consider using a closer VPS endpoint

### High Memory Usage

**Symptom:** System uses >20GB RAM

**Causes and solutions:**

1. **Multiple models loaded:**
   - LFM2-8B: ~16GB
   - LFM2.5-1.2B-Instruct: ~4GB
   - Total: ~20GB minimum

2. **Memory leak:**
   - Restart the backend periodically
   - Check for memory growth in logs
   - Report to developers if persistent

3. **Conversation history:**
   - Clear chat history regularly
   - Reduce conversation memory limit

4. **Use VPS Gateway:**
   - Offload models to remote VPS
   - Reduces local memory usage to <2GB

### High CPU Usage

**Symptom:** CPU at 100% constantly

**Causes and solutions:**

1. **Model inference:**
   - Normal during text generation
   - Should drop to <10% when idle

2. **Audio processing:**
   - LFM 2.5 audio model uses CPU for processing
   - Consider GPU acceleration if available

3. **Multiple clients:**
   - Each WebSocket connection uses resources
   - Limit to 2-3 concurrent windows

4. **Background tasks:**
   - Vision system proactive monitoring
   - Disable in Settings → Automate → Vision → Proactive Monitor


### WebSocket Latency

**Symptom:** UI updates lag behind actions

**Causes and solutions:**

1. **Network issues:**
   - Check localhost connectivity
   - Restart network adapter if needed

2. **Message queue backlog:**
   - Check logs for "message queue" warnings
   - Reduce message frequency

3. **Frontend rendering:**
   - Disable animations in Settings → Customize → Behavior
   - Close other browser tabs
   - Use a modern browser (Chrome, Edge, Firefox)

4. **Backend overload:**
   - Check CPU usage
   - Reduce concurrent operations

### Audio Latency

**Symptom:** Delay between speaking and response

**Causes and solutions:**

1. **LFM 2.5 processing time:**
   - Normal latency: 1-3 seconds
   - Includes wake word detection, STT, inference, TTS

2. **Audio device latency:**
   - Use low-latency audio devices
   - Reduce buffer size in audio settings

3. **Model inference time:**
   - Use VPS Gateway for faster inference
   - Reduce conversation history

4. **Network latency (VPS mode):**
   - Check VPS ping time
   - Use a closer VPS endpoint

---

## Quick Fixes

### Reset Everything

**Nuclear option - resets all settings and state:**

```bash
# Backup first
cp -r backend/settings backend/settings.backup
cp -r backend/sessions backend/sessions.backup

# Delete all state
rm -rf backend/settings/*.json
rm -rf backend/sessions/*
rm -rf backend/logs/*.log

# Restart backend
python start-backend.py
```

### Clear Browser Cache

**Frontend issues often resolve with cache clear:**

1. Open browser DevTools (F12)
2. Right-click refresh button
3. Select "Empty Cache and Hard Reload"
4. Or: Settings → Privacy → Clear browsing data

### Restart Services

**Quick restart sequence:**

```bash
# 1. Stop backend (Ctrl+C in terminal)

# 2. Kill any stuck processes
# Windows
taskkill /F /IM python.exe

# Linux/macOS
pkill -9 python

# 3. Clear temporary files
rm -rf backend/__pycache__
rm -rf backend/*/__pycache__

# 4. Restart backend
python start-backend.py

# 5. Refresh frontend (Ctrl+Shift+R)
```


### Verify Installation

**Check all components are installed correctly:**

```bash
# Check Python version
python --version  # Should be 3.10+

# Check Node.js version
node --version  # Should be 18.x+

# Check dependencies
pip list | grep -E "fastapi|torch|transformers"
npm list | grep -E "next|react|framer-motion"

# Check models
ls -la models/LFM2-8B-A1B/
ls -la models/LFM2.5-1.2B-Instruct/

# Run dependency check
python check_phase1_dependencies.py
```

### Update Dependencies

**Ensure all packages are up to date:**

```bash
# Update Python packages
pip install --upgrade -r requirements.txt

# Update Node.js packages
npm update

# Update specific packages
pip install --upgrade fastapi uvicorn
npm update next react react-dom
```

### Check Permissions

**Ensure proper file permissions:**

```bash
# Linux/macOS
chmod -R 755 backend/
chmod -R 644 backend/settings/*.json
chmod -R 644 backend/logs/*.log

# Windows (run as Administrator)
icacls backend /grant Users:F /T
```

### Environment Variables

**Verify environment variables are set:**

```bash
# Check current environment
env | grep IRIS

# Set if missing
export IRIS_LOG_LEVEL=INFO
export IRIS_LOG_DIR=backend/logs

# Windows
set IRIS_LOG_LEVEL=INFO
set IRIS_LOG_DIR=backend\logs
```

---

## Getting Help

### Collect Diagnostic Information

**Before reporting issues, collect:**

1. **System information:**
   ```bash
   # OS version
   uname -a  # Linux/macOS
   systeminfo  # Windows
   
   # Python version
   python --version
   
   # Package versions
   pip list > installed_packages.txt
   ```

2. **Log files:**
   - Last 100 lines: `tail -100 backend/logs/irisvoice.log`
   - Error messages: `grep ERROR backend/logs/irisvoice.log`

3. **Configuration:**
   - Settings files: `backend/settings/*.json`
   - Environment variables: `env | grep IRIS`

4. **Steps to reproduce:**
   - Exact sequence of actions
   - Expected vs actual behavior
   - Screenshots or screen recordings

### Common Solutions Summary

| Issue | Quick Fix |
|-------|-----------|
| Backend offline | `python start-backend.py` |
| Models not loaded | `python download_text_model.py` |
| Wake word not working | Check microphone, increase sensitivity |
| Settings not saving | Check file permissions, delete corrupted JSON |
| VPS unavailable | Verify endpoint URL and auth token |
| Tool execution fails | Check MCP server logs, verify security policies |
| High memory usage | Enable VPS Gateway, reduce conversation history |
| Slow responses | Close other apps, use VPS Gateway |
| WebSocket drops | Check network, increase ping interval |
| Audio quality poor | Use better microphone, reduce background noise |

### Additional Resources

- **API Documentation:** `API_DOCUMENTATION.md`
- **Deployment Guide:** `DEPLOYMENT_GUIDE.md`
- **Design Document:** `.kiro/specs/irisvoice-backend-integration/design.md`
- **Requirements:** `.kiro/specs/irisvoice-backend-integration/requirements.md`

---

**Last Updated:** February 2024  
**Version:** 1.0
