import type { MiniNode } from "@/types/navigation"

// Mini node definitions for each subnode
// Keys must match subnode IDs from hexagonal-control-center.tsx SUB_NODES

export const SUB_NODES_WITH_MINI: Record<string, MiniNode[]> = {
  // Voice category subnodes
  input: [
    {
      id: 'input-device',
      label: 'Input Device',
      icon: 'Mic',
      fields: [
        {
          id: 'input_device',
          type: 'dropdown',
          label: 'Device',
          options: ['Default', 'USB Mic', 'Headset', 'Webcam'],
          defaultValue: 'Default'
        }
      ]
    },
    {
      id: 'input-sensitivity',
      label: 'Sensitivity',
      icon: 'Volume2',
      fields: [
        {
          id: 'input_sensitivity',
          type: 'slider',
          label: 'Sensitivity',
          min: 0,
          max: 100,
          unit: '%',
          defaultValue: 50
        }
      ]
    },
    {
      id: 'noise-gate',
      label: 'Noise Gate',
      icon: 'Minus',
      fields: [
        {
          id: 'noise_gate',
          type: 'toggle',
          label: 'Enable',
          defaultValue: false
        },
        {
          id: 'gate_threshold',
          type: 'slider',
          label: 'Threshold',
          min: -60,
          max: 0,
          unit: 'dB',
          defaultValue: -30
        }
      ]
    }
  ],

  output: [
    {
      id: 'output-device',
      label: 'Output Device',
      icon: 'Speaker',
      fields: [
        {
          id: 'output_device',
          type: 'dropdown',
          label: 'Device',
          options: ['Default', 'Speakers', 'Headphones', 'Bluetooth'],
          defaultValue: 'Default'
        }
      ]
    },
    {
      id: 'output-volume',
      label: 'Volume',
      icon: 'Volume',
      fields: [
        {
          id: 'output_volume',
          type: 'slider',
          label: 'Volume',
          min: 0,
          max: 100,
          unit: '%',
          defaultValue: 75
        }
      ]
    }
  ],

  processing: [
    {
      id: 'noise-reduction',
      label: 'Noise Reduction',
      icon: 'Minus',
      fields: [
        {
          id: 'noise_reduction',
          type: 'toggle',
          label: 'Enable',
          defaultValue: true
        }
      ]
    },
    {
      id: 'echo-cancellation',
      label: 'Echo Cancellation',
      icon: 'X',
      fields: [
        {
          id: 'echo_cancellation',
          type: 'toggle',
          label: 'Enable',
          defaultValue: true
        }
      ]
    }
  ],

  // Agent category subnodes
  identity: [
    {
      id: 'agent-name',
      label: 'Agent Name',
      icon: 'User',
      fields: [
        {
          id: 'agent_name',
          type: 'text',
          label: 'Name',
          placeholder: 'Enter agent name',
          defaultValue: 'Iris'
        }
      ]
    },
    {
      id: 'personality-type',
      label: 'Personality',
      icon: 'Smile',
      fields: [
        {
          id: 'personality_type',
          type: 'dropdown',
          label: 'Type',
          options: ['Professional', 'Friendly', 'Casual', 'Technical'],
          defaultValue: 'Friendly'
        }
      ]
    },
    {
      id: 'response-style',
      label: 'Response Style',
      icon: 'MessageCircle',
      fields: [
        {
          id: 'response_style',
          type: 'dropdown',
          label: 'Style',
          options: ['Concise', 'Detailed', 'Balanced'],
          defaultValue: 'Balanced'
        }
      ]
    }
  ],

  wake: [
    {
      id: 'wake-word',
      label: 'Wake Word',
      icon: 'Mic',
      fields: [
        {
          id: 'wake_word',
          type: 'text',
          label: 'Phrase',
          placeholder: 'Hey Iris',
          defaultValue: 'Hey Iris'
        }
      ]
    },
    {
      id: 'voice-trigger',
      label: 'Voice Trigger',
      icon: 'Activity',
      fields: [
        {
          id: 'voice_trigger_enabled',
          type: 'toggle',
          label: 'Enabled',
          defaultValue: true
        }
      ]
    }
  ],

  speech: [
    {
      id: 'tts-voice',
      label: 'TTS Voice',
      icon: 'Volume2',
      fields: [
        {
          id: 'tts_voice',
          type: 'dropdown',
          label: 'Voice',
          options: ['Nova', 'Alloy', 'Echo', 'Fable', 'Onyx', 'Shimmer'],
          defaultValue: 'Nova'
        }
      ]
    },
    {
      id: 'tts-speed',
      label: 'Speed',
      icon: 'Zap',
      fields: [
        {
          id: 'tts_speed',
          type: 'slider',
          label: 'Speed',
          min: 0.5,
          max: 2,
          defaultValue: 1
        }
      ]
    }
  ],

  memory: [
    {
      id: 'context-window',
      label: 'Context Window',
      icon: 'Layers',
      fields: [
        {
          id: 'context_window',
          type: 'slider',
          label: 'Messages',
          min: 5,
          max: 50,
          defaultValue: 10
        }
      ]
    },
    {
      id: 'memory-persistence',
      label: 'Persistence',
      icon: 'Save',
      fields: [
        {
          id: 'memory_persistence',
          type: 'toggle',
          label: 'Save Conversations',
          defaultValue: true
        }
      ]
    }
  ],

  // Automate category subnodes
  tools: [
    {
      id: 'tool-access',
      label: 'Tool Access',
      icon: 'Tool',
      fields: [
        {
          id: 'tool_access',
          type: 'toggle',
          label: 'Enable Tools',
          defaultValue: true
        }
      ]
    },
    {
      id: 'web-search',
      label: 'Web Search',
      icon: 'Globe',
      fields: [
        {
          id: 'web_search',
          type: 'toggle',
          label: 'Allow Web Search',
          defaultValue: false
        }
      ]
    }
  ],

  workflows: [
    {
      id: 'auto-start',
      label: 'Auto Start',
      icon: 'Play',
      fields: [
        {
          id: 'auto_start',
          type: 'toggle',
          label: 'Start on Boot',
          defaultValue: false
        }
      ]
    },
    {
      id: 'auto-listen',
      label: 'Auto Listen',
      icon: 'Headphones',
      fields: [
        {
          id: 'auto_listen',
          type: 'toggle',
          label: 'Listen on Start',
          defaultValue: true
        }
      ]
    }
  ],

  favorites: [
    {
      id: 'favorite-commands',
      label: 'Favorites',
      icon: 'Star',
      fields: [
        {
          id: 'favorite_commands',
          type: 'text',
          label: 'Pinned Actions',
          placeholder: 'View favorites...',
          defaultValue: ''
        }
      ]
    }
  ],

  shortcuts: [
    {
      id: 'global-hotkey',
      label: 'Global Hotkey',
      icon: 'Keyboard',
      fields: [
        {
          id: 'global_hotkey',
          type: 'text',
          label: 'Shortcut',
          placeholder: 'Ctrl+Space',
          defaultValue: 'Ctrl+Space'
        }
      ]
    },
    {
      id: 'toggle-listen',
      label: 'Toggle Listen',
      icon: 'Mic',
      fields: [
        {
          id: 'toggle_listen_key',
          type: 'text',
          label: 'Shortcut',
          placeholder: 'Ctrl+L',
          defaultValue: 'Ctrl+L'
        }
      ]
    }
  ],

  // System category subnodes
  power: [
    {
      id: 'power-profile',
      label: 'Power Profile',
      icon: 'Battery',
      fields: [
        {
          id: 'power_profile',
          type: 'dropdown',
          label: 'Profile',
          options: ['Balanced', 'Performance', 'Battery Saver'],
          defaultValue: 'Balanced'
        }
      ]
    }
  ],

  display: [
    {
      id: 'brightness',
      label: 'Brightness',
      icon: 'Sun',
      fields: [
        {
          id: 'brightness',
          type: 'slider',
          label: 'Level',
          min: 0,
          max: 100,
          unit: '%',
          defaultValue: 80
        }
      ]
    },
    {
      id: 'theme',
      label: 'Theme',
      icon: 'Palette',
      fields: [
        {
          id: 'theme',
          type: 'dropdown',
          label: 'Color Theme',
          options: ['Dark', 'Light', 'Auto'],
          defaultValue: 'Dark'
        }
      ]
    },
    {
      id: 'accent-color',
      label: 'Accent',
      icon: 'Droplet',
      fields: [
        {
          id: 'accent_color',
          type: 'color',
          label: 'Accent Color',
          defaultValue: '#00D4FF'
        }
      ]
    }
  ],

  storage: [
    {
      id: 'disk-usage',
      label: 'Disk Usage',
      icon: 'Database',
      fields: [
        {
          id: 'disk_usage',
          type: 'text',
          label: 'Storage',
          placeholder: 'View usage...',
          defaultValue: ''
        }
      ]
    }
  ],

  network: [
    {
      id: 'wifi-toggle',
      label: 'WiFi',
      icon: 'Wifi',
      fields: [
        {
          id: 'wifi_toggle',
          type: 'toggle',
          label: 'Enabled',
          defaultValue: true
        }
      ]
    }
  ],

  // Customize category subnodes
  theme: [
    {
      id: 'theme-mode',
      label: 'Theme Mode',
      icon: 'Palette',
      fields: [
        {
          id: 'theme_mode',
          type: 'dropdown',
          label: 'Mode',
          options: ['Dark', 'Light', 'Auto'],
          defaultValue: 'Dark'
        }
      ]
    },
    {
      id: 'orb-style',
      label: 'Orb Style',
      icon: 'Circle',
      fields: [
        {
          id: 'orb_style',
          type: 'dropdown',
          label: 'Style',
          options: ['Glass', 'Solid', 'Gradient'],
          defaultValue: 'Glass'
        }
      ]
    }
  ],

  startup: [
    {
      id: 'launch-startup',
      label: 'Launch at Startup',
      icon: 'Power',
      fields: [
        {
          id: 'launch_startup',
          type: 'toggle',
          label: 'Enable',
          defaultValue: true
        }
      ]
    }
  ],

  behavior: [
    {
      id: 'confirm-destructive',
      label: 'Confirm Actions',
      icon: 'Shield',
      fields: [
        {
          id: 'confirm_destructive',
          type: 'toggle',
          label: 'Confirm Destructive',
          defaultValue: true
        }
      ]
    }
  ],

  notifications: [
    {
      id: 'dnd-toggle',
      label: 'Do Not Disturb',
      icon: 'BellOff',
      fields: [
        {
          id: 'dnd_toggle',
          type: 'toggle',
          label: 'Enabled',
          defaultValue: false
        }
      ]
    }
  ],

  // Monitor category subnodes
  analytics: [
    {
      id: 'token-usage',
      label: 'Token Usage',
      icon: 'BarChart',
      fields: [
        {
          id: 'token_usage',
          type: 'text',
          label: 'Usage',
          placeholder: 'View stats...',
          defaultValue: ''
        }
      ]
    },
    {
      id: 'performance-monitor',
      label: 'Performance',
      icon: 'Activity',
      fields: [
        {
          id: 'performance_monitor',
          type: 'toggle',
          label: 'Show FPS',
          defaultValue: false
        }
      ]
    }
  ],

  logs: [
    {
      id: 'log-level',
      label: 'Log Level',
      icon: 'FileText',
      fields: [
        {
          id: 'log_level',
          type: 'dropdown',
          label: 'Level',
          options: ['Debug', 'Info', 'Warning', 'Error'],
          defaultValue: 'Info'
        }
      ]
    },
    {
      id: 'log-retention',
      label: 'Retention',
      icon: 'Clock',
      fields: [
        {
          id: 'log_retention',
          type: 'slider',
          label: 'Days',
          min: 1,
          max: 30,
          defaultValue: 7
        }
      ]
    }
  ],

  diagnostics: [
    {
      id: 'health-check',
      label: 'Health Check',
      icon: 'HeartPulse',
      fields: [
        {
          id: 'health_check',
          type: 'text',
          label: 'Status',
          placeholder: 'Run check...',
          defaultValue: ''
        }
      ]
    }
  ],

  updates: [
    {
      id: 'update-channel',
      label: 'Update Channel',
      icon: 'RefreshCw',
      fields: [
        {
          id: 'update_channel',
          type: 'dropdown',
          label: 'Channel',
          options: ['Stable', 'Beta', 'Nightly'],
          defaultValue: 'Stable'
        }
      ]
    }
  ]
}

// Helper function to get mini nodes for a subnode
export function getMiniNodesForSubnode(subnodeId: string): MiniNode[] {
  return SUB_NODES_WITH_MINI[subnodeId] || []
}

// Helper function to check if subnode has mini nodes
export function hasMiniNodes(subnodeId: string): boolean {
  return subnodeId in SUB_NODES_WITH_MINI && SUB_NODES_WITH_MINI[subnodeId].length > 0
}
