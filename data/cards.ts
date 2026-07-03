import type { Card } from "@/types/navigation"

// Card definitions for each section
// Keys must match section IDs from navigation-ids.ts SECTION_IDS

export const CARDS_BY_SECTION: Record<string, Card[]> = {
  // ============================================================================
  // VOICE CATEGORY (6 Cards)
  // ============================================================================

  // input section - microphone-card only
  input: [
    {
      id: 'microphone-card',
      label: 'Input',
      icon: 'Mic',
      fields: [
        {
          id: 'input_device',
          type: 'dropdown',
          label: 'Device',
          options: [],
          defaultValue: ''
        },
         {
           id: 'input_volume',
           type: 'slider',
           label: 'Input Volume',
           min: 0,
           max: 100,
           unit: '%',
           defaultValue: 75
         },
        {
          id: 'vad',
          type: 'toggle',
          label: 'Voice Activity Detection',
          defaultValue: true
        },
        {
          id: 'input_test',
          type: 'button',
          label: 'Test Input',
          action: 'test_input'
        }
      ]
    }
  ],

  // output section - speaker-card only
  output: [
    {
      id: 'speaker-card',
      label: 'Output',
      icon: 'Speaker',
      fields: [
        {
          id: 'output_device',
          type: 'dropdown',
          label: 'Device',
          options: [],
          defaultValue: ''
        },
        {
          id: 'output_volume',
          type: 'slider',
          label: 'Output Volume',
          min: 0,
          max: 100,
          unit: '%',
          defaultValue: 75
        },
        {
          id: 'latency_compensation',
          type: 'slider',
          label: 'Latency Compensation',
          min: 0,
          max: 500,
          unit: 'ms',
          defaultValue: 0
        },
        {
          id: 'output_test',
          type: 'button',
          label: 'Test Output',
          action: 'test_output'
        }
      ]
    }
  ],

  // wake section - wake-word-card
  wake: [
    {
      id: 'wake-word-card',
      label: 'Wake Word',
      icon: 'Sparkles',
      fields: [
        {
          id: 'wake_word_enabled',
          type: 'toggle',
          label: 'Wake Word Enabled',
          defaultValue: true
        },
        {
          id: 'wake_phrase',
          type: 'dropdown',
          label: 'Wake Phrase',
          // Options are populated dynamically from backend (get_wake_words WebSocket message).
          // Built-ins + any custom .ppn files in models/wake_words/ are returned at runtime.
          options: [],
          defaultValue: 'jarvis'
        },
        {
          id: 'wake_word_sensitivity',
          type: 'slider',
          label: 'Sensitivity',
          min: 1,
          max: 10,
          defaultValue: 5
        },
        {
          id: 'voice_profile',
          type: 'dropdown',
          label: 'Voice Profile',
          options: ['Default', 'Personal', 'Professional'],
          defaultValue: 'Default'
        }
      ]
    }
  ],

  // speech section - speech-card
  speech: [
    {
      id: 'speech-card',
      label: 'Speech',
      icon: 'MessageSquare',
      fields: [
        {
          id: 'tts_enabled',
          type: 'toggle',
          label: 'TTS Enabled',
          defaultValue: true
        },
        {
          id: 'tts_voice',
          type: 'dropdown',
          label: 'Voice',
          // Pocket-TTS voices: Cloned Voice (from TOMV2.wav) or built-in catalog voices.
          // "Built-in" forces Piper → pyttsx3 fallback.
          // Catalog voices are downloaded from HF on first use (cached).
          options: [
            'Cloned Voice',
            'alba',
            'marius',
            'javert',
            'jean',
            'fantine',
            'cosette',
            'eponine',
            'azelma',
            'Built-in',
          ],
          defaultValue: 'Cloned Voice'
        },
        {
          id: 'speaking_rate',
          type: 'slider',
          label: 'Speaking Rate',
          min: 0.5,
          max: 2,
          step: 0.1,
          defaultValue: 1
        }
      ]
    }
  ],

  // ============================================================================
  // AGENT CATEGORY

  // model_selection section - models-card
  model_selection: [
    {
      id: 'models-card',
      label: 'Models',
      icon: 'Brain',
      fields: [
        {
          id: 'model_provider',
          type: 'dropdown',
          label: 'Provider',
          options: [
            { label: 'OpenCodeGo', value: 'opencodego' },
            { label: 'Cerebras', value: 'cerebras' },
            { label: 'Chutes AI', value: 'chutes' },
            { label: 'Cohere', value: 'cohere' },
            { label: 'DeepSeek', value: 'deepseek' },
            { label: 'Anthropic', value: 'anthropic' },
            { label: 'LM Studio', value: 'lmstudio' },
          ],
          defaultValue: 'opencodego'
        },
        {
          id: 'api_key',
          type: 'text',
          label: 'API Key',
          placeholder: 'sk-...',
          defaultValue: '',
          showIf: { field: 'model_provider', values: ['opencodego', 'cerebras', 'chutes', 'cohere', 'deepseek', 'anthropic'] }
        },
        {
          id: 'use_same_model',
          type: 'toggle',
          label: 'Use Same Model for Both',
          defaultValue: true,
          showIf: { field: 'model_provider', values: ['opencodego', 'cerebras', 'chutes', 'cohere', 'deepseek', 'anthropic'] }
        },
        {
          id: 'reasoning_model',
          type: 'dropdown',
          label: 'Reasoning Model',
          options: [], // Populated dynamically by available_models event
          defaultValue: '',
          showIf: { field: 'model_provider', values: ['opencodego', 'cerebras', 'chutes', 'cohere', 'deepseek', 'anthropic'] }
        },
        {
          id: 'tool_model',
          type: 'dropdown',
          label: 'Tool Model',
          options: [], // Populated dynamically
          defaultValue: '',
          showIf: { field: 'model_provider', values: ['opencodego', 'cerebras', 'chutes', 'cohere', 'deepseek', 'anthropic'] }
        },
        {
          id: 'lmstudio_endpoint',
          type: 'text',
          label: 'Endpoint',
          placeholder: 'http://localhost:1234',
          defaultValue: 'http://localhost:1234',
          showIf: { field: 'model_provider', values: ['lmstudio'] }
        },
      ]
    }
  ],

  // inference_mode section - inference-card
  inference_mode: [
    {
      id: 'inference-card',
      label: 'Inference',
      icon: 'Cpu',
      fields: [
        {
          id: 'agent_thinking_style',
          type: 'dropdown',
          label: 'Agent Thinking Style',
          options: ['concise', 'balanced', 'thorough'],
          defaultValue: 'balanced'
        },
        {
          id: 'max_response_length',
          type: 'dropdown',
          label: 'Max Response Length',
          options: ['short', 'medium', 'long'],
          defaultValue: 'medium'
        },
        {
          id: 'reasoning_effort',
          type: 'dropdown',
          label: 'Reasoning Effort',
          options: ['fast', 'balanced', 'accurate'],
          defaultValue: 'balanced'
        },
        {
          id: 'tool_mode',
          type: 'dropdown',
          label: 'Tool Mode',
          options: ['auto', 'ask_first', 'disabled'],
          defaultValue: 'auto'
        }
      ]
    }
  ],

  // local_model section — local GGUF model card (mutually exclusive with LM Studio)
  local_model: [
    {
      id: 'local-model-card',
      label: 'Local Model',
      icon: 'HardDrive',
      fields: [
        {
          id: 'local_model_path',
          type: 'dropdown',
          label: 'GGUF Model',
          description: 'Select a loaded GGUF model. Browse & Manage to find more.',
          options: [], // Populated dynamically by available_models / local_models_scanned events
          defaultValue: '',
        },
        {
          id: 'local_model_profile',
          type: 'dropdown',
          label: 'Hardware Profile',
          options: ['eco', 'balanced', 'performance', 'voice_first', 'research', 'custom'],
          defaultValue: 'balanced',
        },
        {
          id: 'local_model_ctx',
          type: 'slider',
          label: 'Context Length',
          min: 1024,
          max: 65536,
          step: 1024,
          defaultValue: 16384,
        },
        {
          id: 'local_model_gpu_layers',
          type: 'slider',
          label: 'GPU Offload (-1 = auto)',
          min: -1,
          max: 128,
          step: 1,
          defaultValue: -1,
        },
        {
          id: 'local_model_status',
          type: 'custom',
          label: 'Model Status',
          defaultValue: 'unloaded',
        },
        {
          id: 'browse_local_models_lm',
          type: 'button',
          label: 'Browse & Manage Models',
          action: 'open_models_screen',
        },
        {
          id: 'load_local_model',
          type: 'button',
          label: 'Load Model',
          action: 'load_local_model',
        },
        {
          id: 'unload_local_model',
          type: 'button',
          label: 'Unload Model',
          action: 'unload_local_model',
        },
      ]
    }
  ],

  // swarm_setup section — multi-agent swarm mode with Director + Workers
  swarm_setup: [
    {
      id: 'swarm-setup-card',
      label: 'Swarm Setup',
      icon: 'Network',
      fields: [
        {
          id: 'swarm_enabled',
          type: 'toggle',
          label: 'Swarm Mode',
          description: 'Enable multi-agent compound collaboration — agents self-join tasks and share context through Mycelium',
          defaultValue: false,
        },
        {
          id: 'swarm_mode',
          type: 'dropdown',
          label: 'Swarm Configuration',
          description: 'Auto-configures Director and Worker models',
          options: ['local_fast', 'api_director', 'quality_director'],
          defaultValue: 'local_fast',
          showIf: { field: 'swarm_enabled', values: [true] }
        },
        {
          id: 'director_source',
          type: 'dropdown',
          label: 'Director Source',
          description: 'Director model source — API provider or local GGUF',
          options: [
            { label: 'API Provider', value: 'api' },
            { label: 'Local GGUF', value: 'local' },
          ],
          defaultValue: 'local_fast',
          showIf: { field: 'swarm_enabled', values: [true] }
        },
        {
          id: 'worker_model',
          type: 'dropdown',
          label: 'Workers Model',
          description: 'GGUF model for swarm workers (populated from scanned GGUFs)',
          options: [],  // Populated dynamically from scanned models
          defaultValue: '',
          showIf: { field: 'swarm_enabled', values: [true] }
        },
        {
          id: 'worker_count',
          type: 'slider',
          label: 'Worker Count',
          description: 'Number of parallel workers (capped by VRAM)',
          min: 1,
          max: 8,
          step: 1,
          defaultValue: 2,
          showIf: { field: 'swarm_enabled', values: [true] }
        },
        {
          id: 'worker_context',
          type: 'slider',
          label: 'Worker Context',
          description: 'Context window per swarm worker (tokens)',
          min: 1024,
          max: 4096,
          step: 1024,
          defaultValue: 2048,
          showIf: { field: 'swarm_enabled', values: [true] }
        },
        {
          id: 'models_directory',
          type: 'text',
          label: 'GGUF Models Directory',
          placeholder: '~/.lmstudio/models',
          defaultValue: '',
          description: 'Directory where GGUF model files are scanned. Defaults to ~/.lmstudio/models from env IRIS_MODELS_DIR.',
          showIf: { field: 'swarm_enabled', values: [true] }
        },
        {
          id: 'browse_swarm_models',
          type: 'button',
          label: 'Browse & Manage Models',
          action: 'open_models_screen',
          showIf: { field: 'swarm_enabled', values: [true] }
        },
        {
          id: 'swarm_status',
          type: 'custom',
          label: 'Swarm Status',
          showIf: { field: 'swarm_enabled', values: [true] }
        },
        {
          id: 'start_swarm',
          type: 'button',
          label: 'Start Swarm',
          action: 'start_swarm',
          showIf: { field: 'swarm_enabled', values: [true] }
        },
        {
          id: 'stop_swarm',
          type: 'button',
          label: 'Stop Swarm',
          action: 'stop_swarm',
          showIf: { field: 'swarm_enabled', values: [true] }
        },
      ]
    }
  ],

  // identity section - personality-card
  identity: [
    {
      id: 'personality-card',
      label: 'Personality',
      icon: 'User',
      fields: [
        {
          id: 'agent_name',
          type: 'text',
          label: 'Agent Name',
          placeholder: 'Enter agent name...',
          defaultValue: 'Iris'
        },
        {
          id: 'persona',
          type: 'dropdown',
          label: 'Persona',
          options: ['Professional', 'Friendly', 'Concise', 'Creative', 'Technical'],
          defaultValue: 'Friendly'
        },
        {
          id: 'greeting_message',
          type: 'text',
          label: 'Greeting Message',
          placeholder: 'Hello! How can I help you?',
          defaultValue: 'Hello! How can I help you?'
        }
      ]
    }
  ],

  // memory section - memory-card
  memory: [
    {
      id: 'memory-card',
      label: 'Memory',
      icon: 'Database',
      fields: [
        {
          id: 'memory_enabled',
          type: 'toggle',
          label: 'Memory Enabled',
          defaultValue: true
        },
        {
          id: 'memory_persistence',
          type: 'toggle',
          label: 'Save Conversations',
          defaultValue: true
        }
      ]
    }
  ],

  // ============================================================================
  // AUTOMATE CATEGORY (8 Cards - added extensions)
  // ============================================================================

  // tools section - tool-permissions-card
  tools: [
    {
      id: 'tool-permissions-card',
      label: 'Tool Permissions',
      icon: 'Tool',
      fields: [
        {
          id: 'allowed_tools',
          type: 'dropdown',
          label: 'Allowed Tools',
          options: ['All', 'None', 'Custom'],
          defaultValue: 'All'
        },
        {
          id: 'tool_confirmations',
          type: 'toggle',
          label: 'Require Confirmations',
          defaultValue: true
        }
      ]
    }
  ],

  // vision section - vision-card
  vision: [
    {
      id: 'vision-card',
      label: 'Vision',
      icon: 'Eye',
      fields: [
        {
          id: 'vision_enabled',
          type: 'toggle',
          label: 'Vision Enabled (LFM2.5-VL)',
          defaultValue: false
        }
      ]
    }
  ],

  // (workflows and shortcuts sections removed - not needed for MVP)

  // desktop_control section - desktop-control-card
  desktop_control: [
    {
      id: 'desktop-control-card',
      label: 'Desktop Control',
      icon: 'Monitor',
      fields: [
        {
          id: 'desktop_control_enabled',
          type: 'toggle',
          label: 'Desktop Control Enabled',
          defaultValue: false
        },
        {
          id: 'ui_tars_provider',
          type: 'dropdown',
          label: 'UI-TARS Provider',
          options: ['cli_npx', 'native_python', 'api_cloud'],
          defaultValue: 'native_python'
        },
        {
          id: 'max_steps',
          type: 'slider',
          label: 'Max Automation Steps',
          min: 5,
          max: 50,
          defaultValue: 25
        },
        {
          id: 'require_confirmation',
          type: 'toggle',
          label: 'Require Confirmation',
          defaultValue: true
        },
        {
          id: 'use_vision_guidance',
          type: 'toggle',
          label: 'Use Vision Guidance',
          defaultValue: true
        }
      ]
    }
  ],

  // skills section - skills-card
  skills: [
    {
      id: 'skills-card',
      label: 'Skills',
      icon: 'Sparkles',
      fields: [
        {
          id: 'skill_creation_enabled',
          type: 'toggle',
          label: 'Allow Agent to Create Skills',
          defaultValue: true
        },
        {
          id: 'skills_list',
          type: 'custom',
          label: 'Learned Skills'
        }
      ]
    }
  ],

  // integrations section - integrations-card
  // Fields array is empty — content is rendered by IntegrationListPanel in SidePanel
  integrations: [
    {
      id: 'integrations-card',
      label: 'Integrations',
      icon: 'Puzzle',
      fields: []
    }
  ],

  // profile section - profile-card
  profile: [
    {
      id: 'profile-card',
      label: 'Profile',
      icon: 'User',
      fields: [
        {
          id: 'user_profile_display',
          type: 'custom',
          label: 'Your Profile'
        },
        {
          id: 'active_mode',
          type: 'dropdown',
          label: 'Active Mode',
          options: ['default', 'work', 'personal', 'focus'],
          defaultValue: 'default'
        },
        {
          id: 'modes_list',
          type: 'custom',
          label: 'Your Modes'
        }
      ]
    }
  ],

  // ============================================================================
  // SYSTEM CATEGORY (4 Cards)
  // ============================================================================

  // power section - power-card
  power: [
    {
      id: 'power-card',
      label: 'Power',
      icon: 'Power',
      fields: [
        {
          id: 'auto_start',
          type: 'toggle',
          label: 'Auto Start on Boot',
          defaultValue: false
        },
        {
          id: 'minimize_to_tray',
          type: 'toggle',
          label: 'Minimize to Tray',
          defaultValue: true
        }
      ]
    }
  ],

  // display section - window-card
  display: [
    {
      id: 'window-card',
      label: 'Window',
      icon: 'Monitor',
      fields: [
        {
          id: 'window_opacity',
          type: 'slider',
          label: 'Window Opacity',
          min: 20,
          max: 100,
          unit: '%',
          defaultValue: 95
        },
        {
          id: 'always_on_top',
          type: 'toggle',
          label: 'Always on Top',
          defaultValue: false
        }
      ]
    }
  ],

  // storage section - storage-card
  storage: [
    {
      id: 'storage-card',
      label: 'Storage',
      icon: 'HardDrive',
      fields: [
        {
          id: 'cache_size',
          type: 'slider',
          label: 'Cache Size',
          min: 100,
          max: 5000,
          unit: 'MB',
          defaultValue: 500
        },
        {
          id: 'log_retention',
          type: 'slider',
          label: 'Log Retention',
          min: 1,
          max: 30,
          unit: 'days',
          defaultValue: 7
        }
      ]
    }
  ],

  // network section - connection-card
  network: [
    {
      id: 'connection-card',
      label: 'Connection',
      icon: 'Wifi',
      fields: [
        {
          id: 'websocket_url',
          type: 'text',
          label: 'WebSocket URL',
          placeholder: 'ws://localhost:8000/ws',
          defaultValue: 'ws://localhost:8000/ws'
        },
        {
          id: 'connection_timeout',
          type: 'slider',
          label: 'Timeout',
          min: 5,
          max: 60,
          unit: 's',
          defaultValue: 30
        }
      ]
    }
  ],

  // ============================================================================
  // CUSTOMIZE CATEGORY (4 Cards)
  // ============================================================================

  // theme section - theme-card (local only)
  theme: [
    {
      id: 'theme-card',
      label: 'Theme',
      icon: 'Palette',
      fields: [
        {
          id: 'theme_mode',
          type: 'dropdown',
          label: 'Theme Mode',
          options: ['Dark', 'Light', 'Auto'],
          defaultValue: 'Dark'
        },
        {
          id: 'font_size',
          type: 'slider',
          label: 'Font Size',
          min: 12,
          max: 24,
          unit: 'px',
          defaultValue: 16
        }
      ]
    }
  ],

  // startup section - startup-card
  startup: [
    {
      id: 'startup-card',
      label: 'Startup',
      icon: 'Rocket',
      fields: [
        {
          id: 'startup_page',
          type: 'dropdown',
          label: 'Startup Page',
          options: ['Dashboard', 'Chat', 'Settings'],
          defaultValue: 'Dashboard'
        },
        {
          id: 'startup_behavior',
          type: 'dropdown',
          label: 'Startup Behavior',
          options: ['Normal', 'Minimized', 'Fullscreen'],
          defaultValue: 'Normal'
        }
      ]
    }
  ],

  // behavior section - behavior-card
  behavior: [
    {
      id: 'behavior-card',
      label: 'Behavior',
      icon: 'Sliders',
      fields: [
        {
          id: 'confirm_exit',
          type: 'toggle',
          label: 'Confirm on Exit',
          defaultValue: true
        },
        {
          id: 'auto_save',
          type: 'toggle',
          label: 'Auto Save',
          defaultValue: true
        }
      ]
    }
  ],

  // notifications section - notifications-card
  notifications: [
    {
      id: 'notifications-card',
      label: 'Notifications',
      icon: 'Bell',
      fields: [
        {
          id: 'notifications_enabled',
          type: 'toggle',
          label: 'Notifications Enabled',
          defaultValue: true
        },
        {
          id: 'sound_effects',
          type: 'toggle',
          label: 'Sound Effects',
          defaultValue: true
        }
      ]
    }
  ],

  // ============================================================================
  // MONITOR CATEGORY (4 Cards)
  // ============================================================================

  // analytics section - analytics-card (live data from backend)
  analytics: [
    {
      id: 'analytics-card',
      label: 'Analytics',
      icon: 'BarChart3',
      fields: [
        {
          id: 'usage_stats',
          type: 'text',
          label: 'Usage Stats',
          placeholder: 'Loading stats...',
          defaultValue: ''
        }
      ]
    }
  ],

  // logs section - logs-card (live data from backend)
  logs: [
    {
      id: 'logs-card',
      label: 'Logs',
      icon: 'FileText',
      fields: [
        {
          id: 'system_logs',
          type: 'text',
          label: 'System Logs',
          placeholder: 'Loading logs...',
          defaultValue: ''
        },
        {
          id: 'error_logs',
          type: 'text',
          label: 'Error Logs',
          placeholder: 'Loading errors...',
          defaultValue: ''
        }
      ]
    }
  ],

  // diagnostics section - diagnostics-card (live data from backend)
  diagnostics: [
    {
      id: 'diagnostics-card',
      label: 'Diagnostics',
      icon: 'Stethoscope',
      fields: [
        {
          id: 'system_health',
          type: 'text',
          label: 'System Health',
          placeholder: 'Running diagnostics...',
          defaultValue: ''
        },
        {
          id: 'troubleshoot',
          type: 'text',
          label: 'Troubleshoot',
          placeholder: 'Issues will appear here...',
          defaultValue: ''
        },
        {
          id: 'debug_info',
          type: 'text',
          label: 'Debug Info',
          placeholder: 'Debug details...',
          defaultValue: ''
        }
      ]
    }
  ],

  // updates section - updates-card (action buttons)
  updates: [
    {
      id: 'updates-card',
      label: 'Updates',
      icon: 'RefreshCw',
      fields: [
        {
          id: 'check_updates',
          type: 'custom',
          label: 'Check for Updates'
        },
        {
          id: 'install_update',
          type: 'custom',
          label: 'Install Update'
        }
      ]
    }
  ]
}

// Flat mapping of all card IDs to their card data
// This allows direct lookup by card ID (e.g., 'microphone-card')
export const CARDS_DATA: Record<string, Card> = Object.entries(CARDS_BY_SECTION).reduce(
  (acc, [, cards]) => {
    cards.forEach((card) => {
      acc[card.id] = card
    })
    return acc
  },
  {} as Record<string, Card>
)

// Helper function to get cards for a section
export function getCardsForSection(sectionId: string): Card[] {
  return CARDS_BY_SECTION[sectionId] || []
}

// Helper function to check if section has cards
export function hasCards(sectionId: string): boolean {
  return sectionId in CARDS_BY_SECTION && CARDS_BY_SECTION[sectionId].length > 0
}

// @deprecated - Backward compatibility aliases
export const SUB_NODES_WITH_MINI = CARDS_BY_SECTION
export const MINI_NODES_DATA = CARDS_DATA
export const getMiniNodesForSubnode = getCardsForSection
export const hasMiniNodes = hasCards
