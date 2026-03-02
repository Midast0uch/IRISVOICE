# Model Selection Persistence Implementation

## Overview

This document describes the implementation of model selection persistence for the IRISVOICE dual-LLM architecture. This feature allows users to select which models handle reasoning and tool execution tasks, and ensures these selections persist across application restarts.

## Requirements Addressed

- **Requirement 23.5**: Model selection must persist across application restarts
- **Requirement 23.6**: Model selection changes must broadcast to all clients in session

## Implementation Details

### 1. State Model Updates

**File**: `IRISVOICE/backend/core_models.py`

Added two fields to the `IRISState` model:
```python
class IRISState(BaseModel):
    # ... existing fields ...
    
    # Model selection (user-configurable dual-LLM)
    selected_reasoning_model: Optional[str] = None
    selected_tool_execution_model: Optional[str] = None
```

These fields store the user's model selections and are automatically persisted with the rest of the state.

### 2. State Manager Updates

**File**: `IRISVOICE/backend/sessions/state_isolation.py`

#### Field Update Handling

Modified the `update_field` method to handle model selection fields specially:

```python
async def update_field(self, subnode_id: str, field_id: str, value: Any, timestamp: Optional[float] = None):
    # Special handling for model selection fields
    if field_id == "reasoning_model":
        self._state.selected_reasoning_model = value
        # Save state and return
    elif field_id == "tool_execution_model":
        self._state.selected_tool_execution_model = value
        # Save state and return
    
    # ... normal field handling ...
```

Model selection fields are stored as top-level state fields rather than in the `field_values` dictionary, ensuring they're always available and properly persisted.

#### State Copy Updates

Updated `get_state_copy` to include model selections:

```python
async def get_state_copy(self) -> IRISState:
    state_copy = IRISState(
        # ... existing fields ...
        selected_reasoning_model=self._state.selected_reasoning_model,
        selected_tool_execution_model=self._state.selected_tool_execution_model
    )
    return state_copy
```

#### Model Selection Restoration

Added `_restore_model_selections` method to restore model selections to AgentKernel on startup:

```python
async def _restore_model_selections(self):
    """Restore model selections to AgentKernel after loading state"""
    from ..agent.agent_kernel import get_agent_kernel
    
    agent_kernel = get_agent_kernel(self.session_id)
    
    if self._state.selected_reasoning_model or self._state.selected_tool_execution_model:
        success = agent_kernel.set_model_selection(
            reasoning_model=self._state.selected_reasoning_model,
            tool_execution_model=self._state.selected_tool_execution_model
        )
```

This method is called during session initialization after state is loaded from persistence.

### 3. Gateway Updates

**File**: `IRISVOICE/backend/iris_gateway.py`

Added special handling in `_handle_settings` to apply model selections to AgentKernel when they change:

```python
# Apply model selection if reasoning_model or tool_execution_model fields are updated
if field_id in ["reasoning_model", "tool_execution_model"]:
    from .agent.agent_kernel import get_agent_kernel
    
    agent_kernel = get_agent_kernel(session_id)
    state = await self._state_manager.get_state(session_id)
    
    if state:
        # Update the state with the new model selection
        if field_id == "reasoning_model":
            state.selected_reasoning_model = value
        elif field_id == "tool_execution_model":
            state.selected_tool_execution_model = value
        
        # Apply both model selections to AgentKernel
        agent_kernel.set_model_selection(
            reasoning_model=state.selected_reasoning_model,
            tool_execution_model=state.selected_tool_execution_model
        )
```

This ensures that:
1. Model selections are immediately applied to the AgentKernel
2. Changes are persisted to state
3. Updates are broadcast to all clients (via existing field_updated broadcast mechanism)

## Persistence Flow

### On Model Selection Change

1. User selects a model via UI (WheelView or DarkGlassDashboard)
2. UI sends `update_field` message with `field_id` = "reasoning_model" or "tool_execution_model"
3. IRISGateway receives message and calls `StateManager.update_field`
4. IsolatedStateManager updates the top-level state field
5. State is automatically saved to JSON file
6. IRISGateway applies the selection to AgentKernel
7. IRISGateway broadcasts `field_updated` message to all clients in session

### On Application Startup

1. Session is created and initialized
2. IsolatedStateManager loads state from JSON file
3. `_restore_model_selections` is called
4. Model selections are applied to AgentKernel
5. If models are not available, a warning is logged but the application continues

## Testing

**File**: `IRISVOICE/tests/test_model_selection_persistence.py`

Two tests verify the implementation:

1. **test_model_selection_persistence**: Verifies that model selections persist across session restarts
2. **test_model_selection_broadcast**: Verifies that model selection updates work correctly

Both tests pass successfully.

## Broadcast Behavior

Model selection changes are broadcast to all clients in the session using the existing `field_updated` message format:

```json
{
  "type": "field_updated",
  "payload": {
    "subnode_id": "agent.models",
    "field_id": "reasoning_model",
    "value": "gpt-4",
    "valid": true,
    "timestamp": 1234567890.123
  }
}
```

This ensures that all connected clients see the model selection change in real-time.

## Error Handling

- If model selections cannot be restored (e.g., models not available), a warning is logged but the application continues
- If `set_model_selection` fails, the error is logged but the state update still succeeds
- Model selections are validated by AgentKernel before being applied

## Future Enhancements

- Add validation to ensure selected models are available before persisting
- Add UI feedback when model selections are successfully applied
- Add model availability checking on startup
- Consider adding model selection to the initial_state message sent to clients
