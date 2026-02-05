export type FieldType = 'text' | 'slider' | 'dropdown' | 'toggle' | 'color'

export interface FieldConfig {
  id: string
  type: FieldType
  label: string
  defaultValue?: any
  // text field props
  placeholder?: string
  // slider props
  min?: number
  max?: number
  unit?: string
  // dropdown props
  options?: string[]
}

export interface MiniNode {
  id: string
  label: string
  icon: string
  fields: FieldConfig[]
}

export interface ConfirmedNode {
  id: string
  label: string
  icon: string
  values: Record<string, any>
  orbitAngle: number
  timestamp: number
}

export type NavigationLevel = 1 | 2 | 3 | 4 | 5

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
  nodeId: string | null
}

export interface NavState {
  level: NavigationLevel
  history: HistoryEntry[]
  selectedMain: string | null
  selectedSub: string | null
  selectedMini: string | null
  isTransitioning: boolean
  transitionDirection: 'forward' | 'backward' | null
  // Mini node stack state (Level 4)
  miniNodeStack: MiniNode[]
  activeMiniNodeIndex: number
  confirmedMiniNodes: ConfirmedNode[]
  miniNodeValues: Record<string, Record<string, any>> // nodeId -> fieldId -> value
}

export type NavAction =
  | { type: 'EXPAND_TO_MAIN' }
  | { type: 'SELECT_MAIN'; payload: { nodeId: string } }
  | { type: 'SELECT_SUB'; payload: { subnodeId: string; miniNodes: MiniNode[] } }
  | { type: 'CONFIRM_MINI'; payload: { nodeId: string } }
  | { type: 'GO_BACK' }
  | { type: 'COLLAPSE_TO_IDLE' }
  | { type: 'SET_TRANSITIONING'; payload: boolean }
  | { type: 'RESTORE_STATE'; payload: NavState }
  // Mini node stack actions
  | { type: 'ROTATE_STACK_FORWARD' }
  | { type: 'ROTATE_STACK_BACKWARD' }
  | { type: 'JUMP_TO_MINI_NODE'; payload: { index: number } }
  | { type: 'CONFIRM_MINI_NODE'; payload: { id: string; values: Record<string, any> } }
  | { type: 'RECALL_CONFIRMED_NODE'; payload: { id: string } }
  | { type: 'UPDATE_MINI_NODE_VALUE'; payload: { nodeId: string; fieldId: string; value: any } }
  | { type: 'CLEAR_MINI_NODE_STATE' }

export interface IrisOrbState {
  label: string
  icon: 'home' | 'close' | 'back'
  showBackIndicator: boolean
}

export const LEVEL_NAMES: Record<NavigationLevel, string> = {
  1: 'COLLAPSED',
  2: 'MAIN_EXPANDED',
  3: 'SUB_EXPANDED',
  4: 'MINI_ACTIVE',
  5: 'CONFIRMED_ORBIT',
}

export const DEFAULT_NAV_CONFIG: NavigationConfig = {
  entryStyle: 'radial-spin',
  exitStyle: 'symmetric',
  speedMultiplier: 1.0,
  staggerDelay: 100,
}

export const STORAGE_KEY = 'iris-nav-state'
export const CONFIG_STORAGE_KEY = 'iris-nav-config'
export const MINI_NODE_VALUES_KEY = 'iris-mini-node-values'
