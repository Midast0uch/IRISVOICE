/**
 * Navigation Constants
 * 
 * This file provides mapping objects that connect Card IDs to their parent sections,
 * and sections to their display labels and icons.
 * 
 * CRITICAL RULES:
 * 1. All Card IDs MUST end with `-card` suffix
 * 2. Section IDs use snake_case format
 * 3. These mappings must stay in sync with navigation-ids.ts and cards.ts
 */

/**
 * Maps Card IDs to their parent Section IDs
 * This replaces the old legacy card-to-section mapping constants
 */
export const CARD_TO_SECTION_ID: Record<string, string> = {
  // Voice
  'microphone-card': 'input',
  'speaker-card': 'output',
  'wake-word-card': 'wake',
  'speech-card': 'speech',

  // Agent
  'models-card': 'model_selection',
  'inference-card': 'inference_mode',
  'personality-card': 'identity',
  'memory-card': 'memory',

  // Automate
  'tool-permissions-card': 'tools',
  'vision-card': 'vision',
  'desktop-control-card': 'desktop_control',
  'skills-card': 'skills',
  'profile-card': 'profile',

  // System
  'power-card': 'power',
  'window-card': 'display',
  'storage-card': 'storage',
  'connection-card': 'network',

  // Customize — theme-card intentionally omitted (local only)
  'startup-card': 'startup',
  'behavior-card': 'behavior',
  'notifications-card': 'notifications',

  // Monitor
  'analytics-card': 'analytics',
  'logs-card': 'logs',
  'diagnostics-card': 'diagnostics',
  'updates-card': 'updates',
}

/**
 * Section labels for display
 * Maps section IDs to human-readable labels
 */
export const SECTION_TO_LABEL: Record<string, string> = {
  input: 'Input',
  output: 'Output',
  wake: 'Wake Word',
  speech: 'Speech',
  model_selection: 'Model Selection',
  inference_mode: 'Inference Mode',
  identity: 'Identity',
  memory: 'Memory',
  tools: 'Tools',
  vision: 'Vision',
  desktop_control: 'Desktop Control',
  skills: 'Skills',
  profile: 'Profile',
  power: 'Power',
  display: 'Display',
  storage: 'Storage',
  network: 'Network',
  theme: 'Theme',
  startup: 'Startup',
  behavior: 'Behavior',
  notifications: 'Notifications',
  analytics: 'Analytics',
  logs: 'Logs',
  diagnostics: 'Diagnostics',
  updates: 'Updates',
}

/**
 * Section icons mapping
 * Maps section IDs to icon names (using standard icon library names)
 */
export const SECTION_TO_ICON: Record<string, string> = {
  input: 'Mic',
  output: 'Volume2',
  wake: 'Sparkles',
  speech: 'MessageSquare',
  model_selection: 'Brain',
  inference_mode: 'Cpu',
  identity: 'User',
  memory: 'Database',
  tools: 'Tool',
  vision: 'Eye',
  desktop_control: 'Monitor',
  skills: 'Sparkles',
  profile: 'User',
  power: 'Power',
  display: 'Monitor',
  storage: 'HardDrive',
  network: 'Wifi',
  theme: 'Palette',
  startup: 'Rocket',
  behavior: 'Sliders',
  notifications: 'Bell',
  analytics: 'BarChart3',
  logs: 'FileText',
  diagnostics: 'Stethoscope',
  updates: 'RefreshCw',
}
