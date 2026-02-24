# IRISVOICE Navigation Hierarchy Data Export

**Generated:** February 23, 2026  
**Purpose:** Complete navigation structure for frontend agent reference

---

## Overview

This document contains the complete navigation hierarchy for the IRISVOICE application, including:
- 6 Main Categories (Level 2)
- 24 Sub-Nodes (Level 3)
- 52 Mini-Nodes (Level 4)
- 61 Input Fields

All IDs use lowercase-kebab-case format as defined in `navigation-ids.ts`.

---

## Main Categories (Level 2)

### 1. Voice (`voice`)
Audio input/output and processing settings

### 2. Agent (`agent`)
AI agent identity, behavior, and capabilities

### 3. Automate (`automate`)
Automation tools, vision, and workflows

### 4. System (`system`)
System-level settings and controls

### 5. Customize (`customize`)
UI customization and preferences

### 6. Monitor (`monitor`)
Analytics, logs, and diagnostics

---

## Complete Navigation Hierarchy

### VOICE Category

#### Sub-Node: Input (`input`)
**Mini-Nodes:**

1. **Input Device** (`input-device`)
   - Icon: `Mic`
   - Fields:
     - `input_device` (dropdown): Device selection
       - Load Options: Dynamic device list (Default, USB Microphone, Headset, Webcam)
       - Default: 'Default'

2. **Sensitivity** (`input-sensitivity`)
   - Icon: `Volume2`
   - Fields:
     - `input_sensitivity` (slider): Sensitivity level
       - Range: 0-100%
       - Default: 50

3. **Noise Gate** (`noise-gate`)
   - Icon: `Minus`
   - Fields:
     - `noise_gate` (toggle): Enable noise gate
       - Default: false
     - `gate_threshold` (slider): Gate threshold
       - Range: -60 to 0 dB
       - Default: -30

#### Sub-Node: Output (`output`)
**Mini-Nodes:**

4. **Output Device** (`output-device`)
   - Icon: `Speaker`
   - Fields:
     - `output_device` (dropdown): Device selection
       - Load Options: Dynamic device list (Default, Headphones, Speakers, HDMI)
       - Default: 'Default'

5. **Volume** (`output-volume`)
   - Icon: `Volume`
   - Fields:
     - `output_volume` (slider): Volume level
       - Range: 0-100%
       - Default: 75

#### Sub-Node: Processing (`processing`)
**Mini-Nodes:**

6. **Noise Reduction** (`noise-reduction`)
   - Icon: `Minus`
   - Fields:
     - `voice_engine` (toggle): Voice engine
       - Default: false
     - `noise_reduction` (toggle): Enable noise reduction
       - Default: true

7. **Echo Cancellation** (`echo-cancellation`)
   - Icon: `X`
   - Fields:
     - `echo_cancellation` (toggle): Enable echo cancellation
       - Default: true

---

### AGENT Category

#### Sub-Node: Identity (`identity`)
**Mini-Nodes:**

8. **Agent Name** (`agent-name`)
   - Icon: `User`
   - Fields:
     - `agent_name` (text): Agent name
       - Placeholder: 'Enter agent name'
       - Default: 'Iris'

9. **Personality** (`personality-type`)
   - Icon: `Smile`
   - Fields:
     - `personality_type` (dropdown): Personality type
       - Options: Professional, Friendly, Concise, Creative, Technical
       - Default: 'Friendly'

10. **Response Style** (`response-style`)
    - Icon: `MessageCircle`
    - Fields:
      - `response_style` (dropdown): Response style
        - Options: Brief, Balanced, Detailed, Comprehensive
        - Default: 'Balanced'

#### Sub-Node: Wake (`wake`)
**Mini-Nodes:**

11. **Wake Word** (`wake-word`)
    - Icon: `Mic`
    - Fields:
      - `wake_phrase` (dropdown): Wake phrase
        - Options: Hey Computer, Jarvis, Alexa, Hey Mycroft, Hey Jarvis
        - Default: 'Hey Computer'

12. **Voice Trigger** (`voice-trigger`)
    - Icon: `Activity`
    - Fields:
      - `voice_trigger_enabled` (toggle): Enable voice trigger
        - Default: true

#### Sub-Node: Speech (`speech`)
**Mini-Nodes:**

13. **TTS Voice** (`tts-voice`)
    - Icon: `Volume2`
    - Fields:
      - `tts_voice` (dropdown): TTS voice selection
        - Options: Nova, Alloy, Echo, Fable, Onyx, Shimmer
        - Default: 'Nova'

14. **Speed** (`tts-speed`)
    - Icon: `Zap`
    - Fields:
      - `tts_speed` (slider): Speech speed
        - Range: 0.5-2
        - Default: 1

#### Sub-Node: Memory (`memory`)
**Mini-Nodes:**

15. **Context Window** (`context-window`)
    - Icon: `Layers`
    - Fields:
      - `context_window` (slider): Context window size
        - Range: 5-50 messages
        - Default: 10

16. **Persistence** (`memory-persistence`)
    - Icon: `Save`
    - Fields:
      - `memory_persistence` (toggle): Save conversations
        - Default: true

---

### AUTOMATE Category

#### Sub-Node: Tools (`tools`)
**Mini-Nodes:**

17. **Tool Access** (`tool-access`)
    - Icon: `Tool`
    - Fields:
      - `tool_access` (toggle): Enable tools
        - Default: true

18. **Web Search** (`web-search`)
    - Icon: `Globe`
    - Fields:
      - `web_search` (toggle): Allow web search
        - Default: false

#### Sub-Node: Vision (`vision`)
**Mini-Nodes:**

19. **Vision** (`vision-toggle`)
    - Icon: `Eye`
    - Fields:
      - `vision_enabled` (toggle): Enable vision
        - Default: false

20. **Screen Context** (`screen-context`)
    - Icon: `Monitor`
    - Fields:
      - `screen_context` (toggle): Include in chat
        - Default: true

21. **Proactive Mode** (`proactive-monitor`)
    - Icon: `Activity`
    - Fields:
      - `proactive_monitor` (toggle): Screen monitoring
        - Default: false
      - `monitor_interval` (slider): Monitor interval
        - Range: 5-120 seconds
        - Default: 30

22. **Ollama Endpoint** (`vision-endpoint`)
    - Icon: `Link`
    - Fields:
      - `ollama_endpoint` (text): Endpoint URL
        - Placeholder: 'http://localhost:11434'
        - Default: 'http://localhost:11434'

23. **Vision Model** (`vision-model`)
    - Icon: `Brain`
    - Fields:
      - `vision_model` (dropdown): Vision model selection
        - Options: minicpm-o4.5, llava, bakllava
        - Default: 'minicpm-o4.5'

#### Sub-Node: Workflows (`workflows`)
**Mini-Nodes:**

24. **Auto Start** (`auto-start`)
    - Icon: `Play`
    - Fields:
      - `auto_start` (toggle): Start on boot
        - Default: false

25. **Auto Listen** (`auto-listen`)
    - Icon: `Headphones`
    - Fields:
      - `auto_listen` (toggle): Listen on start
        - Default: true

#### Sub-Node: Favorites (`favorites`)
**Mini-Nodes:**

26. **Favorites** (`favorite-commands`)
    - Icon: `Star`
    - Fields:
      - `favorite_commands` (text): Pinned actions
        - Placeholder: 'View favorites...'
        - Default: ''

#### Sub-Node: Shortcuts (`shortcuts`)
**Mini-Nodes:**

27. **Global Hotkey** (`global-hotkey`)
    - Icon: `Keyboard`
    - Fields:
      - `global_hotkey` (text): Global shortcut
        - Placeholder: 'Ctrl+Space'
        - Default: 'Ctrl+Space'

28. **Toggle Listen** (`toggle-listen`)
    - Icon: `Mic`
    - Fields:
      - `toggle_listen_key` (text): Toggle listen shortcut
        - Placeholder: 'Ctrl+L'
        - Default: 'Ctrl+L'

---

### SYSTEM Category

#### Sub-Node: Power (`power`)
**Mini-Nodes:**

29. **Power Profile** (`power-profile`)
    - Icon: `Battery`
    - Fields:
      - `power_profile` (dropdown): Power profile
        - Options: Balanced, Performance, Battery
        - Default: 'Balanced'

#### Sub-Node: Display (`display`)
**Mini-Nodes:**

30. **Brightness** (`brightness`)
    - Icon: `Sun`
    - Fields:
      - `brightness` (slider): Brightness level
        - Range: 0-100%
        - Default: 80

31. **Theme** (`theme`)
    - Icon: `Palette`
    - Fields:
      - `theme` (dropdown): Color theme
        - Options: Dark, Light, Auto
        - Default: 'Dark'

32. **Accent** (`accent-color`)
    - Icon: `Droplet`
    - Fields:
      - `accent_color` (color): Accent color
        - Default: '#00D4FF'

#### Sub-Node: Storage (`storage`)
**Mini-Nodes:**

33. **Disk Usage** (`disk-usage`)
    - Icon: `Database`
    - Fields:
      - `disk_usage` (text): Storage info
        - Placeholder: 'View usage...'
        - Default: ''

#### Sub-Node: Network (`network`)
**Mini-Nodes:**

34. **WiFi** (`wifi-toggle`)
    - Icon: `Wifi`
    - Fields:
      - `wifi_toggle` (toggle): WiFi enabled
        - Default: true

---

### CUSTOMIZE Category

#### Sub-Node: Theme (`theme`)
**Mini-Nodes:**

35. **Theme Mode** (`theme-mode`)
    - Icon: `Palette`
    - Fields:
      - `theme_mode` (dropdown): Theme mode
        - Options: Dark, Light, Auto
        - Default: 'Dark'

36. **Orb Style** (`orb-style`)
    - Icon: `Circle`
    - Fields:
      - `orb_style` (dropdown): Orb style
        - Options: Glass, Solid, Gradient
        - Default: 'Glass'

#### Sub-Node: Startup (`startup`)
**Mini-Nodes:**

37. **Launch at Startup** (`launch-startup`)
    - Icon: `Power`
    - Fields:
      - `launch_startup` (toggle): Launch at startup
        - Default: false

#### Sub-Node: Behavior (`behavior`)
**Mini-Nodes:**

38. **Confirm Actions** (`confirm-destructive`)
    - Icon: `Shield`
    - Fields:
      - `confirm_destructive` (toggle): Confirm destructive actions
        - Default: true

#### Sub-Node: Notifications (`notifications`)
**Mini-Nodes:**

39. **Do Not Disturb** (`dnd-toggle`)
    - Icon: `BellOff`
    - Fields:
      - `dnd_toggle` (toggle): Do not disturb
        - Default: false

---

### MONITOR Category

#### Sub-Node: Analytics (`analytics`)
**Mini-Nodes:**

40. **Token Usage** (`token-usage`)
    - Icon: `BarChart`
    - Fields:
      - `token_usage` (text): Token usage stats
        - Placeholder: 'View stats...'
        - Default: ''

41. **Performance** (`performance-monitor`)
    - Icon: `Activity`
    - Fields:
      - `performance_monitor` (toggle): Show FPS
        - Default: false

#### Sub-Node: Logs (`logs`)
**Mini-Nodes:**

42. **Log Level** (`log-level`)
    - Icon: `FileText`
    - Fields:
      - `log_level` (dropdown): Log level
        - Options: Debug, Info, Warning, Error
        - Default: 'Info'

43. **Retention** (`log-retention`)
    - Icon: `Clock`
    - Fields:
      - `log_retention` (slider): Log retention
        - Range: 1-30 days
        - Default: 7

#### Sub-Node: Diagnostics (`diagnostics`)
**Mini-Nodes:**

44. **Health Check** (`health-check`)
    - Icon: `HeartPulse`
    - Fields:
      - `health_check` (text): Health status
        - Placeholder: 'Run check...'
        - Default: ''

#### Sub-Node: Updates (`updates`)
**Mini-Nodes:**

45. **Update Channel** (`update-channel`)
    - Icon: `RefreshCw`
    - Fields:
      - `update_channel` (dropdown): Update channel
        - Options: Stable, Beta, Nightly
        - Default: 'Stable'

---

## Summary Statistics

- **Main Categories:** 6
- **Sub-Nodes:** 24
- **Mini-Nodes:** 52
- **Total Input Fields:** 61

### Field Type Distribution
- Toggle: 21 fields
- Slider: 13 fields
- Dropdown: 17 fields
- Text: 9 fields
- Color: 1 field

### Sub-Nodes by Category
- Voice: 3 sub-nodes (7 mini-nodes, 8 fields)
- Agent: 4 sub-nodes (9 mini-nodes, 10 fields)
- Automate: 5 sub-nodes (10 mini-nodes, 13 fields)
- System: 4 sub-nodes (4 mini-nodes, 4 fields)
- Customize: 4 sub-nodes (4 mini-nodes, 4 fields)
- Monitor: 4 sub-nodes (5 mini-nodes, 5 fields)

---

## Notes for Frontend Agent

1. **ID Format:** All IDs use lowercase-kebab-case (e.g., `voice-input`, `agent-name`)
2. **Icon System:** Icons reference Lucide React icon names
3. **Dynamic Options:** Some dropdowns use `loadOptions` functions for dynamic data (audio devices)
4. **Field Types:**
   - `toggle`: Boolean on/off switch
   - `slider`: Numeric range with min/max/unit
   - `dropdown`: Select from predefined options
   - `text`: Free-form text input
   - `color`: Color picker
5. **Default Values:** All fields have sensible defaults defined
6. **Validation:** Field IDs must match backend configuration keys

---

**End of Navigation Data Export**
