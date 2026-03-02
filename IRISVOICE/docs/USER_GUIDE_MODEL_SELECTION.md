# IRISVOICE Dual-LLM Model Selection Guide

## Overview

IRISVOICE uses a dual-LLM architecture to optimize performance:
- **Reasoning Model**: Handles natural conversation and complex reasoning tasks
- **Tool Execution Model**: Handles structured outputs and tool calls

This guide explains how to configure model selection for optimal performance based on your inference mode and available models.

## Why Dual-LLM Architecture?

**Performance Optimization:**
- Larger models excel at reasoning and conversation quality
- Smaller models can execute tools faster with structured outputs
- Separating concerns allows each model to specialize

**Flexibility:**
- Use the same model for both roles (simplicity)
- Use different models for each role (optimization)
- Switch models without changing agent behavior

**Cost Optimization:**
- Use expensive models only for reasoning (fewer calls)
- Use cheaper models for tool execution (more frequent calls)
- Balance quality and cost based on your needs

## Model Selection Interface

### WheelView

1. Navigate to **Agent** category
2. Select **Model Selection** mini-node
3. Choose **Reasoning Model** from dropdown
4. Choose **Tool Execution Model** from dropdown
5. Click **Confirm** to save

### DarkGlassDashboard

1. Open **Agent** settings tab
2. Scroll to **Model Selection** section
3. Choose **Reasoning Model** from dropdown
4. Choose **Tool Execution Model** from dropdown
5. Changes are saved automatically

## Available Models by Inference Mode

### Local Models

Models are populated from your `models/` directory. Common local models:

| Model | Size | Best For | Speed |
|-------|------|----------|-------|
| `lfm2-8b` | 8B params | Reasoning, conversation | Medium |
| `lfm2.5-1.2b-instruct` | 1.2B params | Tool execution, structured output | Fast |

**Recommended Configuration:**
- Reasoning: `lfm2-8b` (better quality)
- Tool Execution: `lfm2.5-1.2b-instruct` (faster execution)

### VPS Gateway

Models are populated from your VPS server. Available models depend on your VPS configuration.

**Recommended Configuration:**
- Reasoning: Your VPS's largest/best model
- Tool Execution: Your VPS's fastest model
- Or use the same model for both if VPS has limited options

### OpenAI API

Models are populated from OpenAI's available models:

| Model | Best For | Cost | Speed |
|-------|----------|------|-------|
| `gpt-4` | Reasoning, complex tasks | High | Slower |
| `gpt-4-turbo` | Reasoning, faster responses | Medium | Medium |
| `gpt-3.5-turbo` | Tool execution, simple tasks | Low | Fast |

**Recommended Configurations:**

**Quality-Focused:**
- Reasoning: `gpt-4`
- Tool Execution: `gpt-4`

**Cost-Optimized:**
- Reasoning: `gpt-4-turbo`
- Tool Execution: `gpt-3.5-turbo`

**Speed-Optimized:**
- Reasoning: `gpt-3.5-turbo`
- Tool Execution: `gpt-3.5-turbo`

## Configuration Strategies

### Strategy 1: Same Model for Both Roles

**When to Use:**
- Simplicity is priority
- Limited model options
- Consistent behavior across all tasks

**Pros:**
- Simpler configuration
- Consistent quality
- Easier troubleshooting

**Cons:**
- May be slower for tool execution
- May be more expensive (if using large model)

**Example:**
```
Reasoning Model: gpt-4
Tool Execution Model: gpt-4
```

### Strategy 2: Optimized Dual Models

**When to Use:**
- Performance optimization is priority
- Cost optimization is important
- Multiple models available

**Pros:**
- Better performance (faster tools)
- Lower costs (cheaper tool model)
- Specialized for each task

**Cons:**
- More complex configuration
- Need to understand model capabilities

**Example:**
```
Reasoning Model: gpt-4 (quality conversations)
Tool Execution Model: gpt-3.5-turbo (fast tools)
```

### Strategy 3: Local + Cloud Hybrid

**When to Use:**
- You have local models but want cloud reasoning
- Cost optimization with local tool execution
- Privacy for tool execution, cloud for reasoning

**Note:** This requires switching inference modes, not dual-model selection. You can only use models from your currently selected inference mode.

## Model Capabilities

### Reasoning Model Capabilities

The reasoning model handles:
- Natural language conversation
- Complex reasoning tasks
- Context understanding
- Response generation
- Personality expression

**What Makes a Good Reasoning Model:**
- Larger parameter count (better understanding)
- Strong language capabilities
- Good context window
- Consistent personality

### Tool Execution Model Capabilities

The tool execution model handles:
- Structured output generation
- Tool parameter extraction
- Function calling
- JSON formatting
- Quick decisions

**What Makes a Good Tool Execution Model:**
- Fast inference speed
- Reliable structured output
- Good instruction following
- Smaller size (faster)

## Performance Considerations

### Response Time

**Reasoning Model:**
- Called less frequently (only for conversation)
- Can be slower without impacting UX much
- Quality matters more than speed

**Tool Execution Model:**
- Called more frequently (every tool use)
- Speed directly impacts UX
- Fast execution is critical

### Cost Considerations

**Reasoning Model:**
- Fewer calls per session
- Can use expensive model without high cost
- Quality worth the cost

**Tool Execution Model:**
- Many calls per session
- Cost adds up quickly
- Consider cheaper/faster model

### Quality Considerations

**Reasoning Model:**
- Quality directly affects conversation
- Users notice poor reasoning
- Invest in quality here

**Tool Execution Model:**
- Quality affects tool reliability
- Structured output must be correct
- Balance quality and speed

## Model Selection Persistence

**Automatic Saving:**
- Model selection is saved automatically
- Persists across application restarts
- Synced across all connected clients

**Session Isolation:**
- Each session has independent model selection
- Multiple users can use different models
- No interference between sessions

**Broadcast Updates:**
- Model selection changes broadcast to all clients
- All UIs stay synchronized
- Real-time updates

## Troubleshooting

### Models Not Appearing in Dropdown

**Local Mode:**
- Verify models exist in `models/` directory
- Check model files are not corrupted
- Ensure models are compatible format

**VPS Mode:**
- Verify VPS connection is active
- Check VPS API returns model list
- Ensure VPS service is running

**OpenAI Mode:**
- Verify API key is valid
- Check OpenAI service status
- Ensure account has access to models

### Model Selection Not Saving

- Check backend logs for errors
- Verify WebSocket connection is active
- Ensure session is properly initialized
- Try refreshing the page

### Wrong Model Being Used

- Check agent status to verify active models
- Ensure model selection was confirmed
- Verify backend received the update
- Check for model availability errors

### Tool Execution Fails

- Verify tool execution model supports structured output
- Check model is loaded and available
- Ensure model has tool calling capabilities
- Try using a different model

## Best Practices

1. **Start Simple**: Use the same model for both roles initially
2. **Monitor Performance**: Watch response times and quality
3. **Optimize Gradually**: Switch to dual models if needed
4. **Test Thoroughly**: Verify tools work with selected models
5. **Consider Costs**: Balance quality and budget
6. **Update Regularly**: Try new models as they become available

## Example Configurations

### Budget-Conscious (OpenAI)
```
Reasoning Model: gpt-3.5-turbo
Tool Execution Model: gpt-3.5-turbo
Cost: Low
Quality: Good
Speed: Fast
```

### Balanced (OpenAI)
```
Reasoning Model: gpt-4-turbo
Tool Execution Model: gpt-3.5-turbo
Cost: Medium
Quality: Excellent
Speed: Medium
```

### Quality-First (OpenAI)
```
Reasoning Model: gpt-4
Tool Execution Model: gpt-4
Cost: High
Quality: Excellent
Speed: Slower
```

### Local Performance
```
Reasoning Model: lfm2-8b
Tool Execution Model: lfm2.5-1.2b-instruct
Cost: Hardware only
Quality: Good
Speed: Fast (no network)
```

## FAQ

**Q: Can I use models from different inference modes?**
A: No, both models must be from your currently selected inference mode (Local, VPS, or OpenAI).

**Q: What happens if a selected model becomes unavailable?**
A: The system will log a warning and fall back to default behavior. You'll need to select a different model.

**Q: Can I change models mid-conversation?**
A: Yes, model selection can be changed at any time. The conversation history is preserved.

**Q: Do I need different models for reasoning and tool execution?**
A: No, you can use the same model for both roles. Dual models are optional for optimization.

**Q: How do I know which model is best for my use case?**
A: Start with recommended configurations, then adjust based on your priorities (cost, speed, quality).

**Q: Will model selection affect my conversation history?**
A: No, conversation history is independent of model selection. Changing models preserves all history.

## Next Steps

- [Inference Mode Selection Guide](./USER_GUIDE_INFERENCE_MODE.md)
- [Agent Architecture Documentation](./AGENT_ARCHITECTURE.md)
- [Performance Optimization Guide](./OPTIMIZATION_LOG.md)
