# Model-Agnostic Agent Architecture - Developer Documentation

## Overview

The model-agnostic architecture ensures that agent capabilities (conversation memory, personality, tool execution, dual-LLM coordination) work identically across all inference modes (Local, VPS, OpenAI).

## Core Principle

**The application is model-agnostic and works with any LLM provider.**

Users get the same powerful agent experience regardless of which inference backend they choose. The inference backend is transparent to the agent layer.

## Architecture Layers

### Layer 1: AgentKernel (Agent Orchestration)

**Responsibility:** Provide ALL agent capabilities for ALL inference modes.

**Capabilities:**
- Conversation memory management
- Personality configuration
- Tool execution coordination
- Dual-LLM architecture
- Context management

**Code Location:** `backend/agent/agent_kernel.py`

```python
class AgentKernel:
    """
    Universal agent orchestration layer.
    Works with ALL inference modes (Local/VPS/OpenAI).
    """
    
    def __init__(self, model_router: ModelRouter):
        self.model_router = model_router  # Infrastructure only
        self.conversation_memory = ConversationMemory()
        self.personality_manager = PersonalityManager()
        self.tool_bridge = ToolBridge()
        
    async def process_message(self, message: str) -> str:
        """
        Process user message with full agent capabilities.
        Works identically regardless of inference backend.
        """
        # Add to conversation memory (works for all modes)
        self.conversation_memory.add_user_message(message)
        
        # Get personality context (works for all modes)
        personality = self.personality_manager.get_system_prompt()
        
        # Route to reasoning model via ModelRouter
        response = await self.model_router.route_inference(
            prompt=message,
            context={
                "conversation_history": self.conversation_memory.get_history(),
                "system_prompt": personality,
                "model_role": "reasoning"
            }
        )
        
        # Add to conversation memory (works for all modes)
        self.conversation_memory.add_assistant_message(response)
        
        return response
    
    async def execute_tool(self, tool_name: str, parameters: Dict) -> Any:
        """
        Execute tool with full agent capabilities.
        Works identically regardless of inference backend.
        """
        # Route to tool execution model via ModelRouter
        tool_call = await self.model_router.route_inference(
            prompt=self._format_tool_request(tool_name, parameters),
            context={
                "model_role": "tool_execution",
                "structured_output": True
            }
        )
        
        # Execute tool via ToolBridge (works for all modes)
        result = await self.tool_bridge.execute(tool_name, parameters)
        
        # Add to conversation memory (works for all modes)
        self.conversation_memory.add_tool_result(tool_name, result)
        
        return result
```

### Layer 2: ModelRouter (Infrastructure)

**Responsibility:** Route inference requests to appropriate backend.

**What it does:**
- Routes inference requests based on selected mode
- Manages model loading/unloading for Local mode
- Handles backend-specific API calls
- Implements fallback logic

**What it does NOT do:**
- Does NOT manage conversation memory
- Does NOT handle personality
- Does NOT coordinate tools
- Does NOT provide agent capabilities

**Code Location:** `backend/agent/model_router.py`

```python
class ModelRouter:
    """
    Transparent infrastructure for routing inference requests.
    Does NOT provide agent capabilities - purely infrastructure.
    """
    
    async def route_inference(self, prompt: str, context: Dict[str, Any]) -> str:
        """
        Route inference request to appropriate backend.
        AgentKernel uses this for inference but maintains all orchestration logic.
        """
        if self._inference_mode == InferenceMode.LOCAL:
            return await self._route_to_local(prompt, context)
        elif self._inference_mode == InferenceMode.VPS:
            return await self._route_to_vps(prompt, context)
        elif self._inference_mode == InferenceMode.OPENAI:
            return await self._route_to_openai(prompt, context)
        else:
            raise ValueError("Inference mode not configured")
    
    async def _route_to_local(self, prompt: str, context: Dict[str, Any]) -> str:
        """Route to local models."""
        model_role = context.get("model_role", "reasoning")
        
        if model_role == "reasoning":
            model = self._local_models.conversation_model
        else:
            model = self._local_models.tool_model
        
        # Call local model
        return await model.generate(prompt, context)
    
    async def _route_to_vps(self, prompt: str, context: Dict[str, Any]) -> str:
        """Route to VPS gateway."""
        # Call VPS API
        return await self._vps_gateway.send_inference_request(prompt, context)
    
    async def _route_to_openai(self, prompt: str, context: Dict[str, Any]) -> str:
        """Route to OpenAI API."""
        # Call OpenAI API
        return await self._openai_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            **context
        )
```

### Layer 3: Inference Backends

**Responsibility:** Execute inference requests.

**Backends:**
- **LocalModelManager**: Load and run local models
- **VPSGateway**: HTTP client for VPS service
- **OpenAIClient**: OpenAI API client

**Code Locations:**
- `backend/agent/local_model_manager.py`
- `backend/agent/vps_gateway.py`
- `backend/agent/openai_client.py`

## Agent Capabilities Across All Modes

### 1. Conversation Memory

**Implementation:** `backend/agent/conversation_memory.py`

```python
class ConversationMemory:
    """
    Manages conversation history for ALL inference modes.
    Works identically whether using Local/VPS/OpenAI.
    """
    
    def __init__(self):
        self._history: List[Message] = []
        self._max_context_length = 4096
    
    def add_user_message(self, content: str):
        """Add user message to history."""
        self._history.append(Message(role="user", content=content))
        self._trim_history()
    
    def add_assistant_message(self, content: str):
        """Add assistant message to history."""
        self._history.append(Message(role="assistant", content=content))
        self._trim_history()
    
    def get_history(self) -> List[Message]:
        """Get conversation history for context."""
        return self._history.copy()
    
    def _trim_history(self):
        """Trim history to fit context window."""
        # Keep most recent messages within context limit
        while self._estimate_tokens() > self._max_context_length:
            self._history.pop(0)
```

**Usage in AgentKernel:**
```python
# Add to memory (works for all modes)
self.conversation_memory.add_user_message(message)

# Get history for context (works for all modes)
history = self.conversation_memory.get_history()

# Route to inference backend (mode-specific)
response = await self.model_router.route_inference(
    prompt=message,
    context={"conversation_history": history}
)

# Add response to memory (works for all modes)
self.conversation_memory.add_assistant_message(response)
```

### 2. Personality System

**Implementation:** `backend/agent/personality_manager.py`

```python
class PersonalityManager:
    """
    Manages agent personality for ALL inference modes.
    Works identically whether using Local/VPS/OpenAI.
    """
    
    def __init__(self):
        self._personality_config = self._load_default_personality()
    
    def get_system_prompt(self) -> str:
        """Get system prompt with personality."""
        return self._personality_config["system_prompt"]
    
    def set_personality(self, config: Dict[str, Any]):
        """Update personality configuration."""
        self._personality_config.update(config)
        self._persist_personality()
    
    def get_response_style(self) -> Dict[str, Any]:
        """Get response style parameters."""
        return {
            "temperature": self._personality_config.get("temperature", 0.7),
            "tone": self._personality_config.get("tone", "friendly"),
            "verbosity": self._personality_config.get("verbosity", "balanced")
        }
```

**Usage in AgentKernel:**
```python
# Get personality (works for all modes)
personality = self.personality_manager.get_system_prompt()
style = self.personality_manager.get_response_style()

# Route to inference backend with personality (mode-specific)
response = await self.model_router.route_inference(
    prompt=message,
    context={
        "system_prompt": personality,
        "temperature": style["temperature"]
    }
)
```

### 3. Tool Execution

**Implementation:** `backend/agent/tool_bridge.py`

```python
class ToolBridge:
    """
    Coordinates tool execution for ALL inference modes.
    Works identically whether using Local/VPS/OpenAI.
    """
    
    def __init__(self):
        self._tools = self._discover_tools()
        self._internet_access_enabled = True
    
    async def execute(self, tool_name: str, parameters: Dict) -> Any:
        """Execute tool with parameters."""
        # Check if tool requires internet access
        if self._requires_internet(tool_name) and not self._internet_access_enabled:
            raise PermissionError(f"Tool {tool_name} requires internet access")
        
        # Execute tool
        tool = self._tools[tool_name]
        result = await tool.execute(parameters)
        
        return result
    
    def get_available_tools(self) -> List[str]:
        """Get list of available tools."""
        if not self._internet_access_enabled:
            # Filter out internet-dependent tools
            return [name for name, tool in self._tools.items() 
                    if not self._requires_internet(name)]
        return list(self._tools.keys())
```

**Usage in AgentKernel:**
```python
# Get available tools (works for all modes)
tools = self.tool_bridge.get_available_tools()

# Route to tool execution model (mode-specific)
tool_call = await self.model_router.route_inference(
    prompt=self._format_tool_request(message, tools),
    context={"model_role": "tool_execution"}
)

# Execute tool (works for all modes)
result = await self.tool_bridge.execute(
    tool_call["tool_name"],
    tool_call["parameters"]
)
```

### 4. Dual-LLM Architecture

**Implementation:** Coordinated by AgentKernel

```python
class AgentKernel:
    async def process_message_with_tools(self, message: str) -> str:
        """
        Process message with dual-LLM architecture.
        Works identically for ALL inference modes.
        """
        # Step 1: Reasoning model analyzes message
        analysis = await self.model_router.route_inference(
            prompt=message,
            context={
                "model_role": "reasoning",
                "conversation_history": self.conversation_memory.get_history(),
                "system_prompt": self.personality_manager.get_system_prompt()
            }
        )
        
        # Step 2: Check if tools are needed
        if self._needs_tools(analysis):
            # Step 3: Tool execution model generates tool calls
            tool_calls = await self.model_router.route_inference(
                prompt=self._format_tool_request(analysis),
                context={
                    "model_role": "tool_execution",
                    "structured_output": True,
                    "available_tools": self.tool_bridge.get_available_tools()
                }
            )
            
            # Step 4: Execute tools
            results = []
            for tool_call in tool_calls:
                result = await self.tool_bridge.execute(
                    tool_call["tool_name"],
                    tool_call["parameters"]
                )
                results.append(result)
            
            # Step 5: Reasoning model synthesizes final response
            response = await self.model_router.route_inference(
                prompt=self._format_synthesis_request(analysis, results),
                context={
                    "model_role": "reasoning",
                    "conversation_history": self.conversation_memory.get_history()
                }
            )
        else:
            response = analysis
        
        # Add to conversation memory
        self.conversation_memory.add_assistant_message(response)
        
        return response
```

## Inference Mode Transparency

### Conversation History Persistence

**Scenario:** User switches inference modes mid-conversation.

**Expected Behavior:** Conversation history is preserved.

**Implementation:**
```python
class AgentKernel:
    async def switch_inference_mode(self, new_mode: InferenceMode, config: Dict):
        """
        Switch inference mode while preserving agent state.
        """
        # Conversation memory is independent of inference mode
        # No need to clear or transfer - it just works
        
        # Switch ModelRouter backend
        await self.model_router.set_inference_mode(new_mode, config)
        
        # Agent capabilities remain identical
        # Conversation continues seamlessly
```

**Example Flow:**
1. User starts conversation in Local mode
2. AgentKernel adds messages to ConversationMemory
3. User switches to VPS mode
4. ModelRouter changes backend
5. AgentKernel continues using same ConversationMemory
6. Agent continues conversation with full context

### Personality Persistence

**Scenario:** User configures personality, then switches inference modes.

**Expected Behavior:** Personality settings are preserved.

**Implementation:**
```python
class AgentKernel:
    async def switch_inference_mode(self, new_mode: InferenceMode, config: Dict):
        """
        Switch inference mode while preserving personality.
        """
        # Personality is independent of inference mode
        # PersonalityManager maintains configuration
        
        # Switch ModelRouter backend
        await self.model_router.set_inference_mode(new_mode, config)
        
        # Personality continues to apply to all responses
        # System prompt remains the same
```

### Tool Availability

**Scenario:** User switches inference modes.

**Expected Behavior:** Tool availability remains the same (except internet access toggle).

**Implementation:**
```python
class AgentKernel:
    async def switch_inference_mode(self, new_mode: InferenceMode, config: Dict):
        """
        Switch inference mode while preserving tool availability.
        """
        # Tool availability is independent of inference mode
        # ToolBridge maintains tool registry
        
        # Switch ModelRouter backend
        await self.model_router.set_inference_mode(new_mode, config)
        
        # All tools remain available
        # Internet access toggle still applies
```

## User-Configurable Dual-LLM Model Selection

### Model Selection Architecture

**Principle:** Users can select which models handle reasoning and which handle tool execution.

**Implementation:**
```python
class AgentKernel:
    def __init__(self, model_router: ModelRouter):
        self.model_router = model_router
        self._reasoning_model_id = None
        self._tool_execution_model_id = None
    
    def set_model_selection(self, reasoning_model: str, tool_execution_model: str):
        """
        Configure which models handle reasoning and tool execution.
        """
        self._reasoning_model_id = reasoning_model
        self._tool_execution_model_id = tool_execution_model
        
        # Persist selection
        self._persist_model_selection()
    
    async def process_message(self, message: str) -> str:
        """
        Process message using user-selected models.
        """
        # Route to user-selected reasoning model
        response = await self.model_router.route_inference(
            prompt=message,
            context={
                "model_role": "reasoning",
                "model_id": self._reasoning_model_id,  # User selection
                "conversation_history": self.conversation_memory.get_history()
            }
        )
        
        return response
    
    async def execute_tool(self, tool_name: str, parameters: Dict) -> Any:
        """
        Execute tool using user-selected model.
        """
        # Route to user-selected tool execution model
        tool_call = await self.model_router.route_inference(
            prompt=self._format_tool_request(tool_name, parameters),
            context={
                "model_role": "tool_execution",
                "model_id": self._tool_execution_model_id,  # User selection
                "structured_output": True
            }
        )
        
        # Execute tool
        result = await self.tool_bridge.execute(tool_name, parameters)
        
        return result
```

### ModelRouter Model Selection

**Implementation:**
```python
class ModelRouter:
    async def route_inference(self, prompt: str, context: Dict[str, Any]) -> str:
        """
        Route inference to user-selected model.
        """
        model_id = context.get("model_id")
        
        if self._inference_mode == InferenceMode.LOCAL:
            # Use user-selected local model
            model = self._local_models.get_model(model_id)
            return await model.generate(prompt, context)
        
        elif self._inference_mode == InferenceMode.VPS:
            # Use user-selected VPS model
            return await self._vps_gateway.send_inference_request(
                prompt, context, model_id=model_id
            )
        
        elif self._inference_mode == InferenceMode.OPENAI:
            # Use user-selected OpenAI model
            return await self._openai_client.chat.completions.create(
                model=model_id,  # User selection
                messages=[{"role": "user", "content": prompt}],
                **context
            )
    
    async def get_available_models(self) -> List[ModelInfo]:
        """
        Get available models from current inference mode.
        """
        if self._inference_mode == InferenceMode.LOCAL:
            return self._local_models.list_models()
        elif self._inference_mode == InferenceMode.VPS:
            return await self._vps_gateway.list_models()
        elif self._inference_mode == InferenceMode.OPENAI:
            return self._openai_client.list_models()
        else:
            return []
```

## Testing Model-Agnostic Architecture

### Unit Tests

**Test Conversation Memory Across Modes:**
```python
async def test_conversation_memory_across_modes():
    """Verify conversation memory works across all modes."""
    agent = AgentKernel(model_router)
    
    # Start in local mode
    await agent.switch_inference_mode(InferenceMode.LOCAL, {})
    await agent.process_message("Hello")
    
    # Switch to VPS mode
    await agent.switch_inference_mode(InferenceMode.VPS, vps_config)
    await agent.process_message("How are you?")
    
    # Verify conversation history includes both messages
    history = agent.conversation_memory.get_history()
    assert len(history) == 4  # 2 user + 2 assistant
    assert history[0].content == "Hello"
    assert history[2].content == "How are you?"
```

**Test Personality Across Modes:**
```python
async def test_personality_across_modes():
    """Verify personality persists across mode switches."""
    agent = AgentKernel(model_router)
    
    # Configure personality
    agent.personality_manager.set_personality({
        "tone": "professional",
        "verbosity": "concise"
    })
    
    # Test in local mode
    await agent.switch_inference_mode(InferenceMode.LOCAL, {})
    response1 = await agent.process_message("Hello")
    
    # Switch to OpenAI mode
    await agent.switch_inference_mode(InferenceMode.OPENAI, openai_config)
    response2 = await agent.process_message("Hello")
    
    # Verify personality applies to both responses
    assert agent.personality_manager.get_response_style()["tone"] == "professional"
```

**Test Tool Execution Across Modes:**
```python
async def test_tool_execution_across_modes():
    """Verify tools work across all modes."""
    agent = AgentKernel(model_router)
    
    # Test in local mode
    await agent.switch_inference_mode(InferenceMode.LOCAL, {})
    result1 = await agent.execute_tool("web_search", {"query": "test"})
    
    # Switch to VPS mode
    await agent.switch_inference_mode(InferenceMode.VPS, vps_config)
    result2 = await agent.execute_tool("web_search", {"query": "test"})
    
    # Verify tool execution works in both modes
    assert result1 is not None
    assert result2 is not None
```

### Integration Tests

**Test Complete Agent Flow:**
```python
async def test_complete_agent_flow_across_modes():
    """Test complete agent flow across all inference modes."""
    agent = AgentKernel(model_router)
    
    # Configure personality
    agent.personality_manager.set_personality({"tone": "friendly"})
    
    # Test in local mode
    await agent.switch_inference_mode(InferenceMode.LOCAL, {})
    response1 = await agent.process_message_with_tools("Search for Python tutorials")
    
    # Switch to VPS mode (conversation continues)
    await agent.switch_inference_mode(InferenceMode.VPS, vps_config)
    response2 = await agent.process_message_with_tools("What did you find?")
    
    # Switch to OpenAI mode (conversation continues)
    await agent.switch_inference_mode(InferenceMode.OPENAI, openai_config)
    response3 = await agent.process_message_with_tools("Thanks!")
    
    # Verify conversation history includes all messages
    history = agent.conversation_memory.get_history()
    assert len(history) == 6  # 3 user + 3 assistant
    
    # Verify personality applied throughout
    assert agent.personality_manager.get_response_style()["tone"] == "friendly"
    
    # Verify tools were executed
    assert "Python tutorials" in str(history)
```

## Best Practices

1. **Keep AgentKernel Mode-Agnostic**: Never add mode-specific logic to AgentKernel
2. **Use ModelRouter for Routing Only**: Don't add agent capabilities to ModelRouter
3. **Test All Modes**: Verify agent features work in Local, VPS, and OpenAI modes
4. **Preserve State on Mode Switch**: Ensure conversation, personality, and tools persist
5. **Document Mode Independence**: Clearly document which components are mode-agnostic

## Troubleshooting

### Conversation History Lost on Mode Switch

**Cause:** ConversationMemory being cleared or recreated.

**Solution:** Ensure ConversationMemory is a persistent instance in AgentKernel, not recreated on mode switch.

### Personality Not Applying

**Cause:** System prompt not being passed to ModelRouter.

**Solution:** Verify AgentKernel includes personality in context when calling `route_inference()`.

### Tools Not Working in Specific Mode

**Cause:** Mode-specific tool filtering or ToolBridge not being used.

**Solution:** Ensure ToolBridge is mode-agnostic and tools are executed the same way regardless of mode.

## Next Steps

- [Lazy Loading Architecture](./DEVELOPER_LAZY_LOADING.md)
- [Agent Architecture](./AGENT_ARCHITECTURE.md)
- [User Guide: Inference Mode Selection](./USER_GUIDE_INFERENCE_MODE.md)
