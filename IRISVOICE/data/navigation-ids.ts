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
 *    - Data files (cards.ts, etc.)
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
 * Section IDs (Level 3 navigation)
 * Organized by parent category for clarity
 */
export const SECTION_IDS = {
  // Voice category
  VOICE_INPUT: 'input',
  VOICE_OUTPUT: 'output',
  VOICE_WAKE: 'wake',
  VOICE_SPEECH: 'speech',
  
  // Agent category
  AGENT_MODEL_SELECTION: 'model_selection',
  AGENT_INFERENCE_MODE: 'inference_mode',
  AGENT_IDENTITY: 'identity',
  AGENT_MEMORY: 'memory',

  // Automate category
  AUTOMATE_TOOLS: 'tools',
  AUTOMATE_VISION: 'vision',
  AUTOMATE_DESKTOP_CONTROL: 'desktop_control',
  AUTOMATE_SKILLS: 'skills',
  AUTOMATE_PROFILE: 'profile',
  
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

/** @deprecated Use SECTION_IDS instead */
export const SUB_NODE_IDS = SECTION_IDS;

/**
 * Type-safe ID types
 * Use these types in function signatures to ensure type safety
 */
export type MainCategoryId = typeof MAIN_CATEGORY_IDS[keyof typeof MAIN_CATEGORY_IDS];
export type SectionId = typeof SECTION_IDS[keyof typeof SECTION_IDS];
/** @deprecated Use SectionId instead */
export type SubNodeId = SectionId;
export type NavigationId = MainCategoryId | SectionId;

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
  
  // Sections (old uppercase -> new lowercase)
  'INPUT': SECTION_IDS.VOICE_INPUT,
  'OUTPUT': SECTION_IDS.VOICE_OUTPUT,
  'WAKE': SECTION_IDS.VOICE_WAKE,
  'SPEECH': SECTION_IDS.VOICE_SPEECH,
  
  'MODEL_SELECTION': SECTION_IDS.AGENT_MODEL_SELECTION,
  'INFERENCE_MODE': SECTION_IDS.AGENT_INFERENCE_MODE,
  'IDENTITY': SECTION_IDS.AGENT_IDENTITY,
  'MEMORY': SECTION_IDS.AGENT_MEMORY,
  
  'TOOLS': SECTION_IDS.AUTOMATE_TOOLS,
  'VISION': SECTION_IDS.AUTOMATE_VISION,
  'SKILLS': SECTION_IDS.AUTOMATE_SKILLS,
  'PROFILE': SECTION_IDS.AUTOMATE_PROFILE,
  'GUI': SECTION_IDS.AUTOMATE_DESKTOP_CONTROL,
  
  'POWER': SECTION_IDS.SYSTEM_POWER,
  'DISPLAY': SECTION_IDS.SYSTEM_DISPLAY,
  'STORAGE': SECTION_IDS.SYSTEM_STORAGE,
  'NETWORK': SECTION_IDS.SYSTEM_NETWORK,
  
  'THEME': SECTION_IDS.CUSTOMIZE_THEME,
  'STARTUP': SECTION_IDS.CUSTOMIZE_STARTUP,
  'BEHAVIOR': SECTION_IDS.CUSTOMIZE_BEHAVIOR,
  'NOTIFICATIONS': SECTION_IDS.CUSTOMIZE_NOTIFICATIONS,
  
  'ANALYTICS': SECTION_IDS.MONITOR_ANALYTICS,
  'LOGS': SECTION_IDS.MONITOR_LOGS,
  'DIAGNOSTICS': SECTION_IDS.MONITOR_DIAGNOSTICS,
  'UPDATES': SECTION_IDS.MONITOR_UPDATES,
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
 * Checks if an ID is a section
 */
export function isSectionId(id: string): id is SectionId {
  return Object.values(SECTION_IDS).includes(id as SectionId);
}

/** @deprecated Use isSectionId instead */
export function isSubNodeId(id: string): id is SubNodeId {
  return isSectionId(id);
}
