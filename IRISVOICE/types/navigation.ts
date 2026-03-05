export type FieldType = "text" | "slider" | "dropdown" | "toggle" | "color" | "custom" | "section" | "button" | "password"

export type FieldValue = string | number | boolean | Record<string, unknown>;

export interface FieldConfig {
  id: string
  type: FieldType
  label: string
  defaultValue?: FieldValue
  // text field props
  placeholder?: string
  // slider props
  min?: number
  max?: number
  step?: number
  unit?: string
  // dropdown props
  options?: string[]
  loadOptions?: () => Promise<{ label: string; value: string }[]>
  // button props
  action?: string
}

export interface Card {
  id: string
  label: string
  icon: string
  fields: FieldConfig[]
}

export type NavigationLevel = 1 | 2 | 3 | 4

export type TransitionStyle =
  | 'radial-spin'
  | 'clockwork'
  | 'slot-machine'
  | 'holographic'
  | 'liquid-morph'
  | 'pure-fade'

export type ExitStyle = 'symmetric' | 'fade-out' | 'fast-rewind'

export type SpeedMultiplier = 0.5 | 0.75 | 1.0 | 1.25 | 1.5 | 2.0

export type StaggerDelay = 0 | 50 | 100 | 150

export interface NavigationConfig {
  entryStyle: TransitionStyle
  exitStyle: ExitStyle
  speedMultiplier: SpeedMultiplier
  staggerDelay: StaggerDelay
}

export interface HistoryEntry {
  level: NavigationLevel
  categoryId: string | null
}

export interface NavState {
  level: NavigationLevel
  history: HistoryEntry[]
  selectedMain: string | null
  selectedSub: string | null
  isTransitioning: boolean
  transitionDirection: 'forward' | 'backward' | null
  // Card stack state (Level 3)
  cardStack: Card[]
  activeCardIndex: number
  cardValues: Record<string, Record<string, FieldValue>> // cardId -> fieldId -> value
  view: string | null // Current view
  mainView: 'navigation' | 'chat' // Main application view
}

export type NavAction =
  | { type: 'SET_VIEW'; payload: { view: string | null } }
  | { type: 'SET_MAIN_VIEW'; payload: { view: 'navigation' | 'chat' } }
  | { type: 'EXPAND_TO_MAIN' }
  | { type: 'SELECT_MAIN'; payload: { categoryId: string; cards?: Card[] } }
  | { type: 'SELECT_SUB'; payload: { sectionId: string; cards: Card[] } }
  | { type: 'GO_BACK' }
  | { type: 'COLLAPSE_TO_IDLE' }
  | { type: 'SET_TRANSITIONING'; payload: boolean }
  | { type: 'RESTORE_STATE'; payload: NavState }
  // Card stack actions
  | { type: 'ROTATE_STACK_FORWARD' }
  | { type: 'ROTATE_STACK_BACKWARD' }
  | { type: 'JUMP_TO_CARD'; payload: { index: number } }
  | { type: 'CONFIRM_CARD'; payload: { id: string; sectionId?: string; values: Record<string, FieldValue> } }
  | { type: 'UPDATE_CARD_VALUE'; payload: { cardId: string; sectionId?: string; fieldId: string; value: FieldValue } }
  | { type: 'CLEAR_CARD_STATE' }

export interface IrisOrbState {
  label: string
  icon: 'home' | 'close' | 'back'
  showBackIndicator: boolean
}

export const LEVEL_NAMES: Record<NavigationLevel, string> = {
  1: 'COLLAPSED',
  2: 'MAIN_EXPANDED',
  3: 'SUB_EXPANDED',
  4: 'DETAIL_VIEW',
}

export const DEFAULT_NAV_CONFIG: NavigationConfig = {
  entryStyle: 'radial-spin',
  exitStyle: 'symmetric',
  speedMultiplier: 1.0,
  staggerDelay: 100,
}

export const STORAGE_KEY = 'iris-nav-state'
export const CONFIG_STORAGE_KEY = 'iris-nav-config'
export const CARD_VALUES_KEY = 'iris-card-values'
