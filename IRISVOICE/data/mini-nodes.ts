import type { MiniNode } from "@/types/navigation"

// Load options functions for audio devices
const loadInputDevices = async () => {
  // This would typically call the backend to get actual devices
  // For now, return a static list as a fallback
  return [
    { label: 'Default', value: 'Default' },
    { label: 'USB Microphone', value: 'USB Microphone' },
    { label: 'Headset', value: 'Headset' },
    { label: 'Webcam', value: 'Webcam' }
  ]
}

const loadOutputDevices = async () => {
  // This would typically call the backend to get actual devices
  // For now, return a static list as a fallback
  return [
    { label: 'Default', value: 'Default' },
    { label: 'Headphones', value: 'Headphones' },
    { label: 'Speakers', value: 'Speakers' },
    { label: 'HDMI', value: 'HDMI' }
  ]
}

// Mini node definitions for each subnode
// Keys must match subnode IDs from navigation-ids.ts SUB_NODE_IDS

export const SUB_NODES_WITH_MINI: Record<string, MiniNode[]> = {
  // ============================================================================
  // VOICE CATEGORY (6 Cards)
  // ============================================================================

  // input section - microphone-card and wake-word-card
  input: [
    {
      id: 'microphone-card',
      label: 'Microphone',
      icon: 'Mic',
      fields: [
        {
          id: 'input_device',
          type: 'dropdown',
          label: 'Device',
          loadOptions: loadInputDevices,
          defaultValue: 'Default'
        },
        {
          id: 'input_volume',
          type: 'slider',
          label: 'Input Volume',
          min: 0,
          max: 100,
          unit: '%',
          defaultValue: 75
        }
      ]
    },
    {
      id: 'wake-word-card',
      label: 'Wake Word',
      icon: 'Mic',
      fields: [
        {
          id: 'wake_word_enabled',
          type: 'toggle',
          label: 'Wake Word Enabled',
          defaultValue: true
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

  // output section - speaker-card and speech-card
  output: [
    {
      id: 'speaker-card',
      label: 'Speaker',
      icon: 'Speaker',
      fields: [
        {
          id: 'output_device',
          type: 'dropdown',
          label: 'Device',
          loadOptions: loadOutputDevices,
          defaultValue: 'Default'
        },
        {
          id: 'output_volume',
          type: 'slider',
          label: 'Output Volume',
          min: 0,
          max: 100,
          unit: '%',
          defaultValue: 75
        }
      ]
    },
    {
      id: 'speech-card',
      label: 'Speech',
      icon: 'Volume2',
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
          options: ['Nova', 'Alloy', 'Echo', 'Fable', 'Onyx', 'Shimmer'],
          defaultValue: 'Nova'
        },
        {
          id: 'tts_speed',
          type: 'slider',
          label: 'Speed',
          min: 0.5,
          max: 2,
          step: 0.1,
          defaultValue: 1
        }
      ]
    }
  ],

  // processing section - voice-engine-card
  processing: [
    {
      id: 'voice-engine-card',
      label: 'Voice Engine',
      icon: 'Waves',
      fields: [
        {
          id: 'stt_engine',
          type: 'dropdown',
          label: 'STT Engine',
          options: ['Whisper', 'Local', 'Cloud'],
          defaultValue: 'Whisper'
        },
        {
          id: 'voice_activity_detection',
          type: 'toggle',
          label: 'Voice Activity Detection',
          defaultValue: true
        },
        {
          id: 'noise_suppression',
          type: 'toggle',
          label: 'Noise Suppression',
          defaultValue: true
        }
      ]
    }
  ],

  // model section - audio-model-card
  model: [
    {
      id: 'audio-model-card',
      label: 'Audio Model',
      icon: 'Brain',
      fields: [
        {
          id: 'audio_model',
          type: 'dropdown',
          label: 'Model',
          options: ['Whisper Tiny', 'Whisper Base', 'Whisper Small', 'Whisper Medium', 'Whisper Large'],
          defaultValue: 'Whisper Base'
        },
        {
          id: 'audio_language',
          type: 'dropdown',
          label: 'Language',
          options: ['English', 'Spanish', 'French', 'German', 'Chinese', 'Japanese', 'Auto-detect'],
          defaultValue: 'English'
        }
      ]
    }
  ],

  // ============================================================================
  // AGENT CATEGORY (4 Cards - removed wake/speech)
  // ============================================================================

  // model_selection section - models-card
  model_selection: [
    {
      id: 'models-card',
      label: 'Models',
      icon: 'BrainCircuit',
      fields: [
        {
          id: 'model_provider',
          type: 'dropdown',
          label: 'Provider',
          options: ['OpenAI', 'Anthropic', 'Local', 'Custom'],
          defaultValue: 'OpenAI'
        },
        {
          id: 'model_name',
          type: 'dropdown',
          label: 'Model',
          options: [], // Will be populated dynamically based on provider
          defaultValue: ''
        },
        {
          id: 'api_key',
          type: 'text',
          label: 'API Key',
          placeholder: 'Enter API key...',
          defaultValue: ''
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
          id: 'mode',
          type: 'dropdown',
          label: 'Mode',
          options: ['Fast', 'Balanced', 'Quality'],
          defaultValue: 'Balanced'
        },
        {
          id: 'temperature',
          type: 'slider',
          label: 'Temperature',
          min: 0,
          max: 2,
          step: 0.1,
          defaultValue: 0.7
        },
        {
          id: 'max_tokens',
          type: 'slider',
          label: 'Max Tokens',
          min: 256,
          max: 8192,
          step: 256,
          defaultValue: 2048
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
          label: 'Vision Enabled',
          defaultValue: false
        },
        {
          id: 'vision_model',
          type: 'dropdown',
          label: 'Vision Model',
          options: ['minicpm-o4.5', 'llava', 'bakllava'],
          defaultValue: 'minicpm-o4.5'
        }
      ]
    }
  ],

  // workflows section - workflows-card (action buttons)
  workflows: [
    {
      id: 'workflows-card',
      label: 'Workflows',
      icon: 'GitBranch',
      fields: [
        {
          id: 'workflow_1',
          type: 'custom',
          label: 'Workflow 1'
        },
        {
          id: 'workflow_2',
          type: 'custom',
          label: 'Workflow 2'
        },
        {
          id: 'workflow_3',
          type: 'custom',
          label: 'Workflow 3'
        }
      ]
    }
  ],

  // shortcuts section - shortcuts-card (action buttons)
  shortcuts: [
    {
      id: 'shortcuts-card',
      label: 'Shortcuts',
      icon: 'Keyboard',
      fields: [
        {
          id: 'shortcut_1',
          type: 'custom',
          label: 'Shortcut 1'
        },
        {
          id: 'shortcut_2',
          type: 'custom',
          label: 'Shortcut 2'
        },
        {
          id: 'shortcut_3',
          type: 'custom',
          label: 'Shortcut 3'
        }
      ]
    }
  ],

  // gui section - gui-card
  gui: [
    {
      id: 'gui-card',
      label: 'GUI',
      icon: 'Monitor',
      fields: [
        {
          id: 'gui_enabled',
          type: 'toggle',
          label: 'GUI Automation Enabled',
          defaultValue: false
        },
        {
          id: 'gui_precision',
          type: 'dropdown',
          label: 'Precision',
          options: ['Low', 'Medium', 'High'],
          defaultValue: 'Medium'
        }
      ]
    }
  ],

  // extensions section - mcp-servers-card, skills-card, saved-workflows-card (Phase 2 stubs)
  extensions: [
    {
      id: 'mcp-servers-card',
      label: 'MCP Servers',
      icon: 'Server',
      fields: [
        {
          id: 'mcp_server_1',
          type: 'custom',
          label: 'MCP Server 1'
        },
        {
          id: 'mcp_server_2',
          type: 'custom',
          label: 'MCP Server 2'
        }
      ]
    },
    {
      id: 'skills-card',
      label: 'Skills',
      icon: 'Sparkles',
      fields: [
        {
          id: 'skill_1',
          type: 'custom',
          label: 'Skill 1'
        },
        {
          id: 'skill_2',
          type: 'custom',
          label: 'Skill 2'
        }
      ]
    },
    {
      id: 'saved-workflows-card',
      label: 'Saved Workflows',
      icon: 'Workflow',
      fields: [
        {
          id: 'saved_workflow_1',
          type: 'custom',
          label: 'Saved Workflow 1'
        },
        {
          id: 'saved_workflow_2',
          type: 'custom',
          label: 'Saved Workflow 2'
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
          id: 'accent_color',
          type: 'color',
          label: 'Accent Color',
          defaultValue: '#00D4FF'
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

// Flat mapping of all card IDs to their mini node data
// This allows direct lookup by card ID (e.g., 'microphone-card')
export const MINI_NODES_DATA: Record<string, MiniNode> = Object.entries(SUB_NODES_WITH_MINI).reduce(
  (acc, [, miniNodes]) => {
    miniNodes.forEach((miniNode) => {
      acc[miniNode.id] = miniNode
    })
    return acc
  },
  {} as Record<string, MiniNode>
)

// Helper function to get mini nodes for a subnode
export function getMiniNodesForSubnode(subnodeId: string): MiniNode[] {
  return SUB_NODES_WITH_MINI[subnodeId] || []
}

// Helper function to check if subnode has mini nodes
export function hasMiniNodes(subnodeId: string): boolean {
  return subnodeId in SUB_NODES_WITH_MINI && SUB_NODES_WITH_MINI[subnodeId].length > 0
}
