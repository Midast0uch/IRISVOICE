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
          id: 'noise_gate',
          type: 'toggle',
          label: 'Noise Gate',
          defaultValue: false
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
          // CosyVoice2 zero-shot voice cloning (uses data/TOMV2.wav) + pyttsx3 fallback
          options: [
            'Cloned Voice',
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
          options: ['lmstudio', 'api', 'vps', 'iris_local'],
          defaultValue: 'lmstudio'
        },
        {
          id: 'use_same_model',
          type: 'toggle',
          label: 'Use Same Model for Both',
          defaultValue: true
        },
        {
          id: 'reasoning_model',
          type: 'dropdown',
          label: 'Reasoning Model',
          options: [], // Populated dynamically
          defaultValue: ''
        },
        {
          id: 'tool_model',
          type: 'dropdown',
          label: 'Tool Model',
          options: [], // Populated dynamically
          defaultValue: ''
        },
        {
          id: 'lmstudio_endpoint',
          type: 'text',
          label: 'Endpoint',
          placeholder: 'http://localhost:1234',
          defaultValue: 'http://localhost:1234',
          showIf: { field: 'model_provider', values: ['lmstudio'] }
        },
        {
          id: 'api_base_url',
          type: 'text',
          label: 'API Base URL',
          placeholder: 'https://api.openai.com/v1',
          defaultValue: 'https://api.openai.com/v1',
          showIf: { field: 'model_provider', values: ['api', 'vps'] }
        },
        {
          id: 'api_key',
          type: 'text',
          label: 'API Key',
          placeholder: 'sk-...',
          defaultValue: '',
          showIf: { field: 'model_provider', values: ['api', 'vps'] }
        },
        // ── iris_local GGUF section ──────────────────────────────────────────
        {
          id: 'iris_local_model_path',
          type: 'text',
          label: 'Active GGUF Model',
          placeholder: '(none — select in Models Browser)',
          defaultValue: '',
          showIf: { field: 'model_provider', values: ['iris_local'] }
        },
        {
          id: 'iris_local_profile',
          type: 'dropdown',
          label: 'Hardware Profile',
          options: ['eco', 'balanced', 'performance', 'voice_first', 'research', 'custom'],
          defaultValue: 'balanced',
          showIf: { field: 'model_provider', values: ['iris_local'] }
        },
        {
          id: 'iris_local_ctx',
          type: 'slider',
          label: 'Context Length',
          min: 1024,
          max: 65536,
          step: 1024,
          defaultValue: 16384,
          showIf: { field: 'model_provider', values: ['iris_local'] }
        },
        {
          id: 'iris_local_gpu_layers',
          type: 'slider',
          label: 'GPU Offload (-1 = auto)',
          min: -1,
          max: 128,
          step: 1,
          defaultValue: -1,
          showIf: { field: 'model_provider', values: ['iris_local'] }
        },
        {
          id: 'browse_local_models',
          type: 'button',
          label: 'Browse & Manage Models',
          action: 'open_models_screen',
          showIf: { field: 'model_provider', values: ['iris_local'] }
        }
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
          id: 'context_window',
          type: 'slider',
          label: 'Context Window',
          min: 5,
          max: 50,
          defaultValue: 10
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

  // analytics section - analytics-card (display-only action buttons)
  analytics: [
    {
      id: 'analytics-card',
      label: 'Analytics',
      icon: 'BarChart3',
      fields: [
        {
          id: 'view_analytics',
          type: 'custom',
          label: 'View Analytics'
        },
        {
          id: 'export_report',
          type: 'custom',
          label: 'Export Report'
        }
      ]
    }
  ],

  // logs section - logs-card (action buttons)
  logs: [
    {
      id: 'logs-card',
      label: 'Logs',
      icon: 'FileText',
      fields: [
        {
          id: 'view_logs',
          type: 'custom',
          label: 'View Logs'
        },
        {
          id: 'clear_logs',
          type: 'custom',
          label: 'Clear Logs'
        }
      ]
    }
  ],

  // diagnostics section - diagnostics-card (action buttons)
  diagnostics: [
    {
      id: 'diagnostics-card',
      label: 'Diagnostics',
      icon: 'Stethoscope',
      fields: [
        {
          id: 'open_inference_console',
          type: 'button',
          label: 'Open Inference Console',
          action: 'open_inference_console'
        },
        {
          id: 'run_diagnostics',
          type: 'custom',
          label: 'Run Diagnostics'
        },
        {
          id: 'system_info',
          type: 'custom',
          label: 'System Info'
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
