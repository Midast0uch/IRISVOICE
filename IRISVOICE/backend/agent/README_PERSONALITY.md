# PersonalityManager

The PersonalityManager class manages AI assistant personality configuration and generates system prompts that incorporate personality traits.

## Features

- **Configuration Loading**: Load personality settings from agent.identity fields
- **System Prompt Generation**: Generate system prompts that incorporate personality traits
- **Validation**: Validate personality values against allowed options
- **Singleton Pattern**: Ensures consistent personality across the application

## Personality Traits

### Tone
Controls the overall communication style:
- `professional`: Business-appropriate demeanor
- `casual`: Relaxed, informal style
- `friendly`: Warm and approachable (default)
- `formal`: Formal language and structure
- `enthusiastic`: Energetic and positive

### Formality
Controls language formality level:
- `very_formal`: Highly formal, no contractions
- `formal`: Formal with proper grammar
- `neutral`: Balanced approach (default)
- `informal`: Conversational with casual expressions
- `very_informal`: Casual with colloquialisms

### Verbosity
Controls response length:
- `concise`: Brief, 1-2 sentences
- `balanced`: Complete but concise, 2-4 sentences (default)
- `detailed`: Thorough with examples
- `comprehensive`: In-depth, exhaustive responses

### Humor
Controls humor usage:
- `none`: Serious, straightforward
- `subtle`: Light, understated humor (default)
- `moderate`: Natural humor when fitting
- `playful`: Frequent, witty responses

### Empathy
Controls emotional engagement:
- `low`: Focus on facts, minimal emotion
- `moderate`: Understanding and considerate (default)
- `high`: Strong emotional awareness
- `very_high`: Prioritize emotional support

## Usage

### Basic Usage

```python
from backend.agent.personality import get_personality_manager

# Get the singleton instance
manager = get_personality_manager()

# Update personality traits
manager.update_profile(
    assistant_name="CustomBot",
    tone="professional",
    formality="formal",
    verbosity="concise"
)

# Get system prompt
prompt = manager.get_system_prompt()
```

### Loading from Configuration

```python
# Load from agent.identity configuration
config = {
    "identity": {
        "assistant_name": "IRIS",
        "tone": "friendly",
        "formality": "neutral",
        "verbosity": "balanced",
        "humor": "subtle",
        "empathy": "moderate",
        "knowledge": "general"
    }
}

manager.load_from_config(config)
```

### Validation

```python
# Validate configuration before applying
errors = manager.validate_personality_config(config)
if errors:
    print(f"Validation errors: {errors}")
else:
    manager.load_from_config(config)
```

### Getting Current Profile

```python
# Get current personality profile as dictionary
profile = manager.get_profile()
print(f"Current assistant name: {profile['assistant_name']}")
print(f"Current tone: {profile['tone']}")
```

## Integration with Agent System

The PersonalityManager integrates with the agent system to provide consistent personality across conversations:

```python
from backend.agent import get_personality_manager

# In agent initialization
personality = get_personality_manager()

# Load personality from settings
personality.load_from_config(agent_config)

# Use in conversation
system_prompt = personality.get_system_prompt()
# Pass system_prompt to LLM
```

## Error Handling

The PersonalityManager validates all personality values:

```python
try:
    manager.update_profile(tone="invalid_tone")
except ValueError as e:
    print(f"Validation error: {e}")
    # Output: Invalid tone 'invalid_tone'. Allowed values: casual, enthusiastic, formal, friendly, professional
```

## Backward Compatibility

For backward compatibility, the old `PersonalityEngine` name is still available:

```python
from backend.agent.personality import PersonalityEngine, get_personality_engine

# These are aliases to PersonalityManager
engine = get_personality_engine()  # Same as get_personality_manager()
```

## Testing

Comprehensive unit tests are available in `tests/test_personality_manager.py`:

```bash
# Run personality manager tests
python -m pytest tests/test_personality_manager.py -v

# Run with coverage
python -m pytest tests/test_personality_manager.py --cov=backend.agent.personality
```

## Requirements Validation

The PersonalityManager satisfies the following requirements:

- **Requirement 13.1**: Loads assistant_name from agent.identity.assistant_name
- **Requirement 13.2**: Adjusts response tone based on agent.identity.personality
- **Requirement 13.3**: Adjusts domain expertise based on agent.identity.knowledge
- **Requirement 13.4**: Applies personality changes immediately
- **Requirement 13.5**: Maintains personality consistency within conversations
- **Requirement 13.6**: Includes personality in system prompt
- **Requirement 13.7**: Validates personality options against allowed values
