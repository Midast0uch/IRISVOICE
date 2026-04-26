# IRISVOICE Inference Mode Selection Guide

## Overview

IRISVOICE supports three inference modes for AI processing, allowing you to choose the best option based on your hardware, privacy requirements, and budget:

1. **Local Models** - Run AI models on your GPU
2. **VPS Gateway** - Use a remote server for inference
3. **OpenAI API** - Use OpenAI's cloud service

## Important: Model-Agnostic Architecture

**All inference modes provide identical agent capabilities:**
- Conversation memory management
- Personality configuration
- Tool execution (vision, web, file, system, app automation)
- Dual-LLM architecture (reasoning + tool execution)

The only difference is *where* the AI inference happens. Your agent experience remains consistent regardless of which mode you choose.

## Inference Mode Options

### 1. Local Models

**Best for:**
- Users with powerful GPUs (8GB+ VRAM recommended)
- Maximum privacy (no data leaves your machine)
- No internet dependency for AI processing
- Fastest response times (no network latency)

**Requirements:**
- NVIDIA GPU with CUDA support
- Sufficient VRAM for model loading
- Models downloaded to `models/` directory

**How to Enable:**

1. Navigate to **Agent** category in WheelView or DarkGlassDashboard
2. Select **Inference Mode** mini-node/section
3. Choose **"Local Models"** from dropdown
4. Review GPU RAM usage warning
5. Click **Confirm** to load models into GPU memory

**GPU Memory Usage:**
- Models are loaded into GPU RAM when you select Local mode
- Models are automatically unloaded when switching to VPS or OpenAI
- Check available VRAM before enabling: `nvidia-smi` command

**Troubleshooting:**
- If models fail to load, check VRAM availability
- Reduce other GPU-intensive applications
- Consider using VPS or OpenAI mode if GPU is insufficient

### 2. VPS Gateway

**Best for:**
- Users without powerful GPUs
- Remote inference with your own server
- Controlled costs (pay for your VPS only)
- Privacy-conscious users who want to self-host

**Requirements:**
- VPS server running compatible inference service
- VPS URL and API key
- Stable internet connection

**How to Enable:**

1. Navigate to **Agent** category in WheelView or DarkGlassDashboard
2. Select **Inference Mode** mini-node/section
3. Choose **"VPS Gateway"** from dropdown
4. Enter your **VPS URL** (e.g., `https://your-vps.com/api`)
5. Enter your **VPS API Key**
6. Click **Test Connection** to verify
7. Click **Confirm** to save configuration

**Connection Testing:**
- The system will verify your VPS is reachable
- Check that your API key is valid
- Ensure your VPS service is running

**Troubleshooting:**
- Verify VPS URL format (must include `https://`)
- Check API key is correct (no extra spaces)
- Ensure VPS firewall allows connections
- Test VPS health endpoint manually

### 3. OpenAI API

**Best for:**
- Users who want the easiest setup
- Access to latest GPT models
- No hardware requirements
- Pay-as-you-go pricing

**Requirements:**
- OpenAI API key (starts with `sk-`)
- Internet connection
- OpenAI account with credits

**How to Enable:**

1. Navigate to **Agent** category in WheelView or DarkGlassDashboard
2. Select **Inference Mode** mini-node/section
3. Choose **"OpenAI API"** from dropdown
4. Enter your **OpenAI API Key** (format: `sk-...`)
5. Click **Test Connection** to verify
6. Click **Confirm** to save configuration

**API Key Security:**
- Keys are stored encrypted in the backend
- Only last 4 characters are displayed in UI
- Keys are never logged or transmitted insecurely

**Getting an API Key:**
1. Visit [platform.openai.com](https://platform.openai.com)
2. Sign up or log in
3. Navigate to API Keys section
4. Create a new secret key
5. Copy the key (you won't see it again!)

**Troubleshooting:**
- Verify API key format starts with `sk-`
- Check OpenAI account has available credits
- Ensure API key hasn't been revoked
- Test with a simple request first

## Switching Between Modes

You can switch inference modes at any time:

1. Navigate to **Agent** → **Inference Mode**
2. Select a different mode
3. Configure the new mode (if needed)
4. Click **Confirm**

**What Happens When Switching:**
- **From Local to VPS/OpenAI**: Models are unloaded from GPU RAM
- **From VPS/OpenAI to Local**: Models are loaded into GPU RAM
- **Conversation history is preserved** across all mode switches
- **Agent capabilities remain identical** in all modes

## Model Selection (Dual-LLM Architecture)

IRISVOICE uses two models for optimal performance:
- **Reasoning Model**: Handles conversation and complex reasoning
- **Tool Execution Model**: Handles structured outputs and tool calls

### Configuring Model Selection

1. Navigate to **Agent** → **Model Selection**
2. Select your **Reasoning Model** from available models
3. Select your **Tool Execution Model** from available models
4. Click **Confirm** to save

**Available Models:**
- Models are populated based on your selected inference mode
- Local mode shows models in your `models/` directory
- VPS mode shows models available on your VPS server
- OpenAI mode shows available OpenAI models (GPT-4, GPT-3.5, etc.)

**Best Practices:**
- Use larger models for reasoning (better quality responses)
- Use smaller/faster models for tool execution (faster actions)
- You can use the same model for both roles if desired

**Example Configurations:**

**Local Mode:**
- Reasoning: `lfm2-8b` (larger, better reasoning)
- Tool Execution: `lfm2.5-1.2b-instruct` (smaller, faster tools)

**OpenAI Mode:**
- Reasoning: `gpt-4` (best quality)
- Tool Execution: `gpt-4` (same model for consistency)

**VPS Mode:**
- Reasoning: Your VPS's largest model
- Tool Execution: Your VPS's fastest model

## Performance Comparison

| Feature | Local Models | VPS Gateway | OpenAI API |
|---------|-------------|-------------|------------|
| **Response Time** | Fastest (no network) | Medium (network latency) | Medium (network latency) |
| **Privacy** | Maximum (local only) | High (your server) | Lower (third-party) |
| **Cost** | GPU hardware | VPS hosting | Pay-per-use |
| **Setup Complexity** | High (GPU required) | Medium (VPS setup) | Low (just API key) |
| **Internet Required** | No (for inference) | Yes | Yes |
| **Model Selection** | Your downloaded models | VPS models | OpenAI models |

## Agent Internet Access

**Important:** The "Agent Internet Access" toggle controls whether the AI agent can use web search tools. It does NOT affect:
- Application connectivity to VPS or OpenAI
- Your internet connection
- WebSocket communication with backend

**When to Enable:**
- You want the agent to search the web for information
- You want the agent to access online resources
- You trust the agent to make web requests

**When to Disable:**
- You want to limit agent capabilities to local tools only
- You're concerned about agent making external requests
- You want to test offline functionality

## Troubleshooting

### Models Won't Load (Local Mode)
- Check GPU VRAM: `nvidia-smi`
- Verify models exist in `models/` directory
- Close other GPU-intensive applications
- Try VPS or OpenAI mode instead

### VPS Connection Fails
- Verify VPS URL is correct and includes `https://`
- Check API key has no extra spaces
- Ensure VPS service is running
- Test VPS endpoint manually with curl

### OpenAI API Errors
- Verify API key format starts with `sk-`
- Check OpenAI account has credits
- Ensure API key hasn't been revoked
- Check OpenAI service status

### Conversation History Lost
- This should never happen! Conversation history persists across mode switches
- If you experience this, report it as a bug
- Check backend logs for errors

## FAQ

**Q: Can I use multiple inference modes simultaneously?**
A: No, only one inference mode is active at a time. However, you can switch modes at any time without losing conversation history.

**Q: Do I need to download models for VPS or OpenAI modes?**
A: No, only Local mode requires downloaded models. VPS and OpenAI modes use remote models.

**Q: Will switching modes interrupt my conversation?**
A: No, conversation history is preserved when switching modes. The agent will continue seamlessly.

**Q: Can I use different models for reasoning and tool execution?**
A: Yes! This is recommended for optimal performance. Use a larger model for reasoning and a faster model for tool execution.

**Q: What happens if my VPS or OpenAI connection fails?**
A: The agent will display an error and wait for connection to be restored. You can switch to a different inference mode if needed.

**Q: Is my OpenAI API key secure?**
A: Yes, API keys are encrypted before storage and never logged or transmitted insecurely. Only the last 4 characters are displayed in the UI.

## Next Steps

- [Wake Word Configuration Guide](./USER_GUIDE_WAKE_WORDS.md)
- [Cleanup System Guide](./USER_GUIDE_CLEANUP.md)
- [Agent Architecture Documentation](./AGENT_ARCHITECTURE.md)
