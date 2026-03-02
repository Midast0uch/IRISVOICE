/**
 * Single Source of Truth for Navigation IDs
 * 
 * CRITICAL RULES:
 * 1. All IDs use lowercase-kebab-case format
 * 2. Frontend and backend MUST use these exact IDs
 * 3. Never create IDs outside this file
 * 4. IDs must match between:
 *    - Navigation state (selectedMain, selectedSub)
 *    - WebSocket messages
 *    - Data files (mini-nodes.ts, etc.)
 *    - Backend API endpoints
 * 
 * Convention: lowercase-kebab-case
 * - Easy to type (no shift key)
 * - URL-safe
 * - Backend compatible (Python/FastAPI standard)
 * - Case-insensitive matching prevents bugs
 * 
 * @example
 * // ✅ CORRECT
 * const id = MAIN_CATEGORY_IDS.VOICE; // 'voice'
 * 
 * // ❌ WRONG - Don't use uppercase or mixed case
 * const id = 'VOICE'; // Will cause mismatches
 */

/**
 * Main category IDs (Level 2 navigation)
 * These are the 6 primary categories in the hexagonal layout
 */
export const MAIN_CATEGORY_IDS = {
  VOICE: 'voice',
  AGENT: 'agent',
  AUTOMATE: 'automate',
  SYSTEM: 'system',
  CUSTOMIZE: 'customize',
  MONITOR: 'monitor',
} as const;

/**
 * Sub-node IDs (Level 3 navigation)
 * Organized by parent category for clarity
 */
export const SUB_NODE_IDS = {
  // Voice category
  VOICE_INPUT: 'input',
  VOICE_OUTPUT: 'output',
  VOICE_PROCESSING: 'processing',
  VOICE_MODEL: 'model',
  
  // Agent category
  AGENT_MODEL_SELECTION: 'model_selection',
  AGENT_INFERENCE_MODE: 'inference_mode',
  AGENT_IDENTITY: 'identity',
  AGENT_MEMORY: 'memory',

  // Automate category
  AUTOMATE_TOOLS: 'tools',
  AUTOMATE_VISION: 'vision',
  AUTOMATE_WORKFLOWS: 'workflows',
  AUTOMATE_SHORTCUTS: 'shortcuts',
  AUTOMATE_GUI: 'gui',
  AUTOMATE_EXTENSIONS: 'extensions',
  
  // System category
  SYSTEM_POWER: 'power',
  SYSTEM_DISPLAY: 'display',
  SYSTEM_STORAGE: 'storage',
  SYSTEM_NETWORK: 'network',
  
  // Customize category
  CUSTOMIZE_THEME: 'theme',
  CUSTOMIZE_STARTUP: 'startup',
  CUSTOMIZE_BEHAVIOR: 'behavior',
  CUSTOMIZE_NOTIFICATIONS: 'notifications',
  
  // Monitor category
  MONITOR_ANALYTICS: 'analytics',
  MONITOR_LOGS: 'logs',
  MONITOR_DIAGNOSTICS: 'diagnostics',
  MONITOR_UPDATES: 'updates',
} as const;

/**
 * Type-safe ID types
 * Use these types in function signatures to ensure type safety
 */
export type MainCategoryId = typeof MAIN_CATEGORY_IDS[keyof typeof MAIN_CATEGORY_IDS];
export type SubNodeId = typeof SUB_NODE_IDS[keyof typeof SUB_NODE_IDS];
export type NavigationId = MainCategoryId | SubNodeId;

/**
 * Validates that an ID matches the expected lowercase-kebab-case format
 * 
 * @param id - ID to validate
 * @returns true if valid, false otherwise
 * 
 * @example
 * isValidNodeId('voice-input') // true
 * isValidNodeId('VOICE_INPUT') // false
 * isValidNodeId('voiceInput') // false
 */
export function isValidNodeId(id: string): boolean {
  // Must be lowercase kebab-case: starts with letter, contains only lowercase letters, numbers, and hyphens
  return /^[a-z][a-z0-9]*(-[a-z0-9]+)*$/.test(id);
}

/**
 * Normalizes an ID to lowercase kebab-case
 * Useful for migrating old uppercase or snake_case IDs
 * 
 * @param id - ID to normalize
 * @returns Normalized ID in lowercase-kebab-case
 * 
 * @example
 * normalizeId('VOICE_INPUT') // 'voice-input'
 * normalizeId('VoiceInput') // 'voice-input'
 * normalizeId('voice_input') // 'voice-input'
 */
export function normalizeId(id: string): string {
  return id
    .toLowerCase()
    .replace(/_/g, '-')
    .replace(/([a-z])([A-Z])/g, '$1-$2')
    .toLowerCase();
}

/**
 * Migration map for old uppercase IDs to new lowercase IDs
 * TEMPORARY: Remove this once all code is migrated
 * 
 * @deprecated Use MAIN_CATEGORY_IDS and SUB_NODE_IDS instead
 */
export const ID_MIGRATION_MAP: Record<string, string> = {
  // Main categories (old uppercase -> new lowercase)
  'VOICE': MAIN_CATEGORY_IDS.VOICE,
  'AGENT': MAIN_CATEGORY_IDS.AGENT,
  'AUTOMATE': MAIN_CATEGORY_IDS.AUTOMATE,
  'SYSTEM': MAIN_CATEGORY_IDS.SYSTEM,
  'CUSTOMIZE': MAIN_CATEGORY_IDS.CUSTOMIZE,
  'MONITOR': MAIN_CATEGORY_IDS.MONITOR,
  
  // Sub-nodes (old uppercase -> new lowercase)
  'INPUT': SUB_NODE_IDS.VOICE_INPUT,
  'OUTPUT': SUB_NODE_IDS.VOICE_OUTPUT,
  'PROCESSING': SUB_NODE_IDS.VOICE_PROCESSING,
  'MODEL': SUB_NODE_IDS.VOICE_MODEL,
  
  'MODEL_SELECTION': SUB_NODE_IDS.AGENT_MODEL_SELECTION,
  'INFERENCE_MODE': SUB_NODE_IDS.AGENT_INFERENCE_MODE,
  'IDENTITY': SUB_NODE_IDS.AGENT_IDENTITY,
  'MEMORY': SUB_NODE_IDS.AGENT_MEMORY,
  
  'TOOLS': SUB_NODE_IDS.AUTOMATE_TOOLS,
  'VISION': SUB_NODE_IDS.AUTOMATE_VISION,
  'WORKFLOWS': SUB_NODE_IDS.AUTOMATE_WORKFLOWS,
  'SHORTCUTS': SUB_NODE_IDS.AUTOMATE_SHORTCUTS,
  'GUI': SUB_NODE_IDS.AUTOMATE_GUI,
  
  'POWER': SUB_NODE_IDS.SYSTEM_POWER,
  'DISPLAY': SUB_NODE_IDS.SYSTEM_DISPLAY,
  'STORAGE': SUB_NODE_IDS.SYSTEM_STORAGE,
  'NETWORK': SUB_NODE_IDS.SYSTEM_NETWORK,
  
  'THEME': SUB_NODE_IDS.CUSTOMIZE_THEME,
  'STARTUP': SUB_NODE_IDS.CUSTOMIZE_STARTUP,
  'BEHAVIOR': SUB_NODE_IDS.CUSTOMIZE_BEHAVIOR,
  'NOTIFICATIONS': SUB_NODE_IDS.CUSTOMIZE_NOTIFICATIONS,
  
  'ANALYTICS': SUB_NODE_IDS.MONITOR_ANALYTICS,
  'LOGS': SUB_NODE_IDS.MONITOR_LOGS,
  'DIAGNOSTICS': SUB_NODE_IDS.MONITOR_DIAGNOSTICS,
  'UPDATES': SUB_NODE_IDS.MONITOR_UPDATES,
};

/**
 * Migrates an old ID to the new format
 * TEMPORARY: Remove this once all code is migrated
 * 
 * @param oldId - Old uppercase or mixed-case ID
 * @returns New lowercase-kebab-case ID
 * 
 * @deprecated Use MAIN_CATEGORY_IDS and SUB_NODE_IDS directly
 */
export function migrateId(oldId: string): string {
  return ID_MIGRATION_MAP[oldId] || normalizeId(oldId);
}

/**
 * Checks if an ID is a main category
 */
export function isMainCategoryId(id: string): id is MainCategoryId {
  return Object.values(MAIN_CATEGORY_IDS).includes(id as MainCategoryId);
}

/**
 * Checks if an ID is a sub-node
 */
export function isSubNodeId(id: string): id is SubNodeId {
  return Object.values(SUB_NODE_IDS).includes(id as SubNodeId);
}
