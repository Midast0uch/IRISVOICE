# IRIS Vision Integration (MiniCPM-o 4.5)

This integration adds powerful visual capabilities to IRIS using the local **MiniCPM-o 4.5** multimodal model via **Ollama**.

## 🌟 Key Features

1.  **"See & Talk"**: IRIS can now see your screen during conversations.
    *   Ask: *"What am I looking at?"*
    *   Ask: *"Help me with this error message"*
2.  **Local Vision Processing**: All screenshots and analysis happen locally (no cloud API costs).
3.  **Proactive Assistance**: An optional `ScreenMonitor` runs in the background to detect errors or context changes and offer help.
4.  **GUI Automation**: The `GUIAgent` now uses MiniCPM-o to find buttons and text fields for automation tasks.

## 🛠️ Setup Instructions

### 1. Install Dependencies
Update your Python environment with the new vision requirements:
```bash
pip install -r requirements.txt
```

### 2. Install Ollama & Pull Model
You need [Ollama](https://ollama.com/) installed. Then pull the MiniCPM-o 4.5 model:
```bash
ollama pull openbmb/minicpm-o4.5
```

### 3. Verify Installation
Run the included test script to confirm everything is working:
```bash
python tests/test_vision_integration.py
```
If successful, you should see green checkmarks for availability and screen capture.

## 📦 Components Added

| Module | File | Purpose |
|--------|------|---------|
| **Core Client** | `backend/vision/minicpm_client.py` | Handles Ollama API communication for vision. |
| **Capture Utils** | `backend/vision/screen_capture.py` | Efficient screen capture with `mss` + caching. |
| **Conversation** | `backend/agent/omni_conversation.py` | Manages "text + image" prompts for IRIS. |
| **Monitor** | `backend/vision/screen_monitor.py` | Background thread for proactive help. |
| **API** | `backend/main.py` | New endpoints at `/api/vision/*`. |

## 🚀 Usage

### In Conversation
Just speak normally! If `vision_enabled` is ON, IRIS naturally includes a screenshot with your voice query.
*   **User**: "Does this code look correct?"
*   **IRIS**: (Analyzes screen) "Yes, but you're missing a colon on line 14."

### Via API
*   `POST /api/vision/describe`: Get a text description of the current screen.
*   `POST /api/vision/detect?description=Save Button`: Find coordinates of UI elements.
*   `POST /api/vision/monitor/start`: Enable proactive monitoring.

## ⚙️ Configuration
You can configure vision settings via `POST /api/vision/config`:
```json
{
  "vision_enabled": true,
  "screen_context_during_conversation": true,
  "ollama_endpoint": "http://localhost:11434",
  "vision_model": "minicpm-o4.5"
}
```
