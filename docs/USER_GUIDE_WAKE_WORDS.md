# IRISVOICE Wake Word Configuration Guide

## Overview

IRISVOICE uses wake word detection to activate voice commands hands-free. The system automatically discovers all wake word files in your `wake_words/` directory and makes them available for selection.

## Wake Word Discovery System

### Automatic Discovery

The backend automatically scans the `wake_words/` directory on startup and discovers all `.ppn` (Porcupine) wake word files.

**Discovery Process:**
1. Scan `wake_words/` directory for `.ppn` files
2. Parse filename to extract metadata (platform, version)
3. Generate user-friendly display names
4. Populate dropdown in both WheelView and DarkGlassDashboard
5. Verify "Hey Iris" wake word is available

### Supported Platforms

Wake word files are platform-specific:
- **Windows**: `*_windows_*.ppn`
- **Linux**: `*_linux_*.ppn`
- **macOS**: `*_mac_*.ppn`

The system will discover all files regardless of platform, but you should select the file matching your operating system.

## Configuring Wake Words

### WheelView

1. Navigate to **Voice** category
2. Select **Wake Word** mini-node
3. Choose your wake word from the dropdown
4. Click **Confirm** to activate

### DarkGlassDashboard

1. Open **Voice** settings tab
2. Scroll to **Wake Word** section
3. Choose your wake word from the dropdown
4. Selection is saved automatically

## Available Wake Words

### Default Wake Word: "Hey Iris"

The system includes "Hey Iris" as the default wake word:
- File: `hey-iris_en_windows_v4_0_0.ppn` (Windows)
- Display Name: "Hey Iris"
- Language: English
- Version: v4.0.0

### Adding Custom Wake Words

You can add custom wake word files to the `wake_words/` directory:

1. Obtain `.ppn` files from Picovoice Console
2. Place files in `IRISVOICE/models/wake_words/` directory
3. Restart the application
4. New wake words will appear in the dropdown

**Filename Format:**
```
{wake-phrase}_{language}_{platform}_v{version}.ppn
```

**Examples:**
- `hey-iris_en_windows_v4_0_0.ppn`
- `computer_en_linux_v3_0_0.ppn`
- `jarvis_en_mac_v4_0_0.ppn`

## Display Name Formatting

The system automatically formats filenames into user-friendly display names:

| Filename | Display Name |
|----------|--------------|
| `hey-iris_en_windows_v4_0_0.ppn` | Hey Iris |
| `computer_en_windows_v4_0_0.ppn` | Computer |
| `jarvis_en_windows_v4_0_0.ppn` | Jarvis |
| `ok-google_en_windows_v4_0_0.ppn` | Ok Google |

**Formatting Rules:**
1. Remove `.ppn` extension
2. Remove platform suffix (`_en_windows_v4_0_0`)
3. Replace hyphens with spaces
4. Capitalize each word

## Wake Word Sensitivity

You can adjust wake word detection sensitivity:

**Sensitivity Range:** 0.0 (least sensitive) to 1.0 (most sensitive)

**Recommended Values:**
- **0.3**: Very strict (fewer false positives, may miss some activations)
- **0.5**: Balanced (default, good for most environments)
- **0.7**: Sensitive (more activations, may have false positives)

**Adjusting Sensitivity:**
1. Navigate to Voice → Wake Word settings
2. Adjust the **Sensitivity** slider
3. Test with voice commands
4. Fine-tune based on your environment

## Troubleshooting

### No Wake Words Found

**Symptoms:**
- Dropdown shows "No wake word files found"
- Wake word detection doesn't work

**Solutions:**
1. Verify `wake_words/` directory exists
2. Check directory contains `.ppn` files
3. Ensure files have correct naming format
4. Restart the application
5. Check backend logs for discovery errors

### Wake Word Not Detecting

**Symptoms:**
- Wake word doesn't activate voice commands
- No response when saying wake phrase

**Solutions:**
1. Verify correct wake word file is selected
2. Check microphone is working (test in Voice → Input)
3. Adjust sensitivity (try increasing to 0.7)
4. Ensure wake phrase matches selected file
5. Check for background noise interference
6. Verify platform-specific file is selected

### Wrong Platform File

**Symptoms:**
- Wake word detection fails
- Error messages in backend logs

**Solutions:**
1. Check your operating system
2. Select the matching platform file:
   - Windows: `*_windows_*.ppn`
   - Linux: `*_linux_*.ppn`
   - macOS: `*_mac_*.ppn`
3. Download correct platform file if needed

### "Hey Iris" Not Found

**Symptoms:**
- Backend logs warning about missing "Hey Iris"
- Default wake word not available

**Solutions:**
1. Download "Hey Iris" wake word file
2. Place in `wake_words/` directory
3. Ensure filename matches: `hey-iris_en_windows_v4_0_0.ppn`
4. Restart application

## Creating Custom Wake Words

### Using Picovoice Console

1. Visit [Picovoice Console](https://console.picovoice.ai/)
2. Sign up or log in
3. Navigate to "Wake Word" section
4. Create a new wake word:
   - Enter your wake phrase
   - Select language
   - Select target platforms
5. Train the wake word model
6. Download `.ppn` files
7. Place files in `wake_words/` directory

### Best Practices for Custom Wake Words

**Phrase Selection:**
- Use 2-3 word phrases
- Avoid common words (reduces false positives)
- Choose distinct phonetic patterns
- Test in your environment

**Examples of Good Wake Phrases:**
- "Hey Iris" (default)
- "Computer activate"
- "Hello assistant"
- "Wake up system"

**Examples of Poor Wake Phrases:**
- "Hi" (too short, common)
- "The" (too common)
- "System" (single word, common)

## Wake Word Detection Flow

1. **Idle State**: System listens for wake word
2. **Wake Detected**: Wake word recognized
3. **Listening State**: System records voice command
4. **Processing**: Command sent to agent
5. **Response**: Agent responds with text or voice
6. **Return to Idle**: System listens for wake word again

## Performance Considerations

### CPU Usage

Wake word detection runs continuously:
- Low CPU usage (optimized for efficiency)
- Runs on CPU, not GPU
- Minimal impact on system performance

### Latency

Wake word detection is near-instant:
- Detection latency: <100ms
- Activation latency: <200ms
- Total time from wake word to listening: <300ms

### Accuracy

Wake word accuracy depends on:
- Quality of wake word file
- Microphone quality
- Background noise level
- Sensitivity setting
- Distance from microphone

## FAQ

**Q: Can I use multiple wake words simultaneously?**
A: No, only one wake word can be active at a time. You can switch between wake words in settings.

**Q: Do I need internet for wake word detection?**
A: No, wake word detection runs entirely locally on your machine.

**Q: Can I create wake words in other languages?**
A: Yes, Picovoice supports multiple languages. Create wake words in your preferred language using Picovoice Console.

**Q: Why isn't my custom wake word working?**
A: Ensure the file is in the correct format, matches your platform, and is placed in the `wake_words/` directory. Restart the application after adding files.

**Q: Can I adjust how long the system listens after wake word?**
A: Yes, this is configured in Voice → Input settings under "Recording Timeout".

**Q: What happens if I say the wake word during a conversation?**
A: The system ignores wake words while already in listening or processing state to prevent interruptions.

## Next Steps

- [Voice Configuration Guide](./wake-word-frontend-integration-guide.md)
- [Inference Mode Selection Guide](./USER_GUIDE_INFERENCE_MODE.md)
- [System Overview](./SYSTEM_OVERVIEW.md)
