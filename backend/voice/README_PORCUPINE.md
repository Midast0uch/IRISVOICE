# Porcupine Wake Word Detection

This document describes the Porcupine wake word detection integration in IRISVOICE.

## Overview

IRISVOICE uses [Picovoice's Porcupine](https://picovoice.ai/platform/porcupine/) for wake word detection. Porcupine is a highly accurate, on-device wake word engine that supports both custom-trained wake words and built-in keywords.

## Features

- **Custom Wake Words**: Train your own wake words using Picovoice Console
- **Built-in Keywords**: Use pre-trained keywords (JARVIS, COMPUTER, BUMBLEBEE, PORCUPINE)
- **Multiple Wake Words**: Support multiple wake words simultaneously
- **Configurable Sensitivity**: Adjust detection sensitivity (0.0-1.0) per wake word
- **Low Latency**: On-device processing with minimal latency
- **Cross-Platform**: Works on Windows, macOS, and Linux

## Setup

### 1. Get Picovoice Access Key

1. Sign up at [Picovoice Console](https://console.picovoice.ai/)
2. Navigate to your account settings
3. Copy your Access Key
4. Add it to your `.env` file:

```env
PICOVOICE_ACCESS_KEY=your_access_key_here
```

### 2. Install Dependencies

Porcupine is already included in `requirements.txt`:

```bash
pip install pvporcupine>=3.0.0
```

### 3. Place Wake Word Models

Custom wake word models (`.ppn` files) should be placed in:

```
IRISVOICE/models/wake_words/
```

The default custom wake word is:
- `hey-iris_en_windows_v4_0_0.ppn` - Custom "hey iris" wake word

## Usage

### Basic Configuration

Configure wake word detection in `LFMAudioManager`:

```python
config = {
    "wake_phrase": "hey iris",  # or "jarvis", "computer", "bumblebee", "porcupine"
    "detection_sensitivity": 50,  # 0-100 (converted to 0.0-1.0 internally)
    "activation_sound": True
}

manager = LFMAudioManager(config)
await manager.initialize()
```

### Supported Wake Phrases

1. **"hey iris"** - Custom trained wake word (uses `hey-iris_en_windows_v4_0_0.ppn`)
   - Standalone custom model
2. **"jarvis"** - Built-in Porcupine keyword
3. **"computer"** - Built-in Porcupine keyword
4. **"bumblebee"** - Built-in Porcupine keyword
5. **"porcupine"** - Built-in Porcupine keyword

**Note**: Custom and built-in wake words cannot be mixed in a single Porcupine instance. Each wake phrase uses either a custom model OR a built-in keyword.

### Detection Sensitivity

Sensitivity controls the trade-off between false positives and false negatives:

- **Low sensitivity (0-30)**: More false positives, fewer false negatives
- **Medium sensitivity (40-60)**: Balanced (recommended: 50)
- **High sensitivity (70-100)**: Fewer false positives, more false negatives

```python
# Update sensitivity at runtime
manager.update_wake_config(detection_sensitivity=75)
```

### Direct Porcupine Usage

You can also use `PorcupineWakeWordDetector` directly:

```python
from backend.voice.porcupine_detector import PorcupineWakeWordDetector

# Initialize with custom model and built-in keywords
detector = PorcupineWakeWordDetector(
    custom_model_path="models/wake_words/hey-iris_en_windows_v4_0_0.ppn",
    builtin_keywords=["jarvis", "computer"],
    sensitivities=[0.5, 0.5, 0.5]  # One per wake word
)

# Process audio frames (512 samples at 16kHz)
audio_frame = [...]  # 512 int16 samples
wake_detected, wake_word_name = detector.process_frame(audio_frame)

if wake_detected:
    print(f"Wake word detected: {wake_word_name}")

# Cleanup
detector.cleanup()
```

## Training Custom Wake Words

### Using Picovoice Console

1. **Sign in** to [Picovoice Console](https://console.picovoice.ai/)

2. **Navigate to Porcupine**:
   - Click on "Porcupine" in the left sidebar
   - Click "Train Custom Wake Word"

3. **Configure Wake Word**:
   - **Wake Phrase**: Enter your desired phrase (e.g., "hey iris")
   - **Language**: Select language (e.g., English)
   - **Platform**: Select target platform (Windows, macOS, Linux, etc.)

4. **Train Model**:
   - Click "Train" and wait for processing
   - Download the `.ppn` model file

5. **Deploy Model**:
   - Place the `.ppn` file in `IRISVOICE/models/wake_words/`
   - Update configuration to use the new wake word

### Naming Convention

Wake word model files should follow this naming convention:

```
{wake-phrase}_{language}_{platform}_v{version}.ppn
```

Examples:
- `hey-iris_en_windows_v4_0_0.ppn`
- `ok-iris_en_linux_v4_0_0.ppn`
- `computer_en_mac_v4_0_0.ppn`

## Audio Requirements

Porcupine requires specific audio format:

- **Sample Rate**: 16 kHz
- **Bit Depth**: 16-bit PCM
- **Channels**: Mono (1 channel)
- **Frame Length**: 512 samples (32ms at 16kHz)

The `LFMAudioManager` handles audio preprocessing automatically.

## Architecture

### Integration Flow

```
Audio Input (16kHz, 16-bit PCM)
    ↓
PorcupineWakeWordDetector
    ↓
Process frames (512 samples)
    ↓
Wake word detected?
    ↓ Yes
Trigger callback → Start voice recording
    ↓ No
Continue listening
```

### Components

1. **PorcupineWakeWordDetector** (`porcupine_detector.py`)
   - Wraps Porcupine engine
   - Handles custom and built-in wake words
   - Manages sensitivity configuration

2. **LFMAudioManager** (`lfm_audio_manager.py`)
   - Integrates Porcupine for wake word detection
   - Maintains STT pipeline for transcription (separate from wake word)
   - Coordinates end-to-end audio processing

## Troubleshooting

### "Access key not provided" Error

**Problem**: Porcupine initialization fails with access key error.

**Solution**:
1. Verify `.env` file contains `PICOVOICE_ACCESS_KEY`
2. Ensure `.env` is in the project root
3. Restart the application to reload environment variables

### "Model file not found" Error

**Problem**: Custom wake word model not found.

**Solution**:
1. Verify `.ppn` file is in `IRISVOICE/models/wake_words/`
2. Check file name matches the expected pattern
3. Ensure file permissions allow reading

### Wake Word Not Detected

**Problem**: Wake word is not being detected consistently.

**Solutions**:
1. **Lower sensitivity**: Try `detection_sensitivity=30-40`
2. **Check audio quality**: Ensure clear audio input without background noise
3. **Verify audio format**: Must be 16kHz, 16-bit PCM, mono
4. **Retrain model**: Train a new model with more varied pronunciations

### High False Positive Rate

**Problem**: Wake word triggers on similar-sounding phrases.

**Solutions**:
1. **Increase sensitivity**: Try `detection_sensitivity=60-80`
2. **Retrain model**: Use more specific wake phrase
3. **Add context**: Require confirmation after wake word detection

### Performance Issues

**Problem**: High CPU usage or latency.

**Solutions**:
1. **Use built-in keywords**: They're optimized for performance
2. **Reduce wake word count**: Use fewer simultaneous wake words
3. **Check system resources**: Ensure adequate CPU/memory available

## Best Practices

### Wake Word Selection

1. **Unique phrases**: Choose phrases unlikely to occur in normal conversation
2. **Clear pronunciation**: Avoid ambiguous or hard-to-pronounce words
3. **Appropriate length**: 2-3 syllables work best (e.g., "hey iris")
4. **Avoid common words**: Don't use frequently spoken words alone

### Sensitivity Tuning

1. **Start with default**: Begin with sensitivity=50
2. **Test in environment**: Test in actual usage environment
3. **Iterate**: Adjust based on false positive/negative rates
4. **Document settings**: Record optimal settings for your environment

### Production Deployment

1. **Secure access key**: Never commit access key to version control
2. **Use environment variables**: Store sensitive data in `.env`
3. **Monitor performance**: Track detection accuracy and latency
4. **Update models**: Periodically retrain models for better accuracy
5. **Fallback handling**: Implement graceful degradation if Porcupine fails

## API Reference

### PorcupineWakeWordDetector

```python
class PorcupineWakeWordDetector:
    def __init__(
        self,
        access_key: Optional[str] = None,
        custom_model_path: Optional[str] = None,
        builtin_keywords: Optional[List[str]] = None,
        sensitivities: Optional[List[float]] = None
    )
    
    @property
    def sample_rate(self) -> int
    
    @property
    def frame_length(self) -> int
    
    def process_frame(self, audio_frame: List[int]) -> Tuple[bool, Optional[str]]
    
    def update_sensitivity(self, wake_word_index: int, sensitivity: float)
    
    def update_sensitivity_by_name(self, wake_word_name: str, sensitivity: float)
    
    def cleanup(self)
```

### LFMAudioManager Wake Word Methods

```python
class LFMAudioManager:
    def detect_wake_word(self, audio_data: bytes) -> bool
    
    def update_wake_config(
        self,
        wake_phrase: str = None,
        detection_sensitivity: int = None,
        activation_sound: bool = None
    )
```

## Resources

- [Picovoice Console](https://console.picovoice.ai/) - Train custom wake words
- [Porcupine Documentation](https://picovoice.ai/docs/porcupine/) - Official docs
- [Porcupine GitHub](https://github.com/Picovoice/porcupine) - Source code and examples
- [Wake Word Best Practices](https://picovoice.ai/blog/wake-word-best-practices/) - Design guidelines

## License

Porcupine is licensed by Picovoice. See [Picovoice License](https://picovoice.ai/pricing/) for details.

Free tier includes:
- Unlimited custom wake words
- Up to 3 devices per account
- Community support

For production use, consider Picovoice's commercial licensing options.
