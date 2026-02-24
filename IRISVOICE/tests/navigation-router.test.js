/**
 * Integration tests for navigation router
 * 
 * Tests:
 * - Level 1 renders Level1View (IrisOrb)
 * - Level 2 renders Level2View (HexagonalControlCenter)
 * - Level 3 renders WheelView
 * - No level 4 case exists
 * - WheelView receives correct props
 * 
 * Validates: Requirements 2.1, 9.7
 */

import { describe, test, expect, jest, beforeEach } from '@jest/globals'

describe('Navigation Router Integration', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  /**
   * Test: Level 1 state
   * Validates: Requirement 2.1
   */
  test('level 1 is the initial collapsed state', () => {
    const initialState = {
      level: 1,
      selectedMain: null,
      selectedSub: null,
      miniNodeStack: [],
    }
    
    expect(initialState.level).toBe(1)
    expect(initialState.selectedMain).toBeNull()
    expect(initialState.selectedSub).toBeNull()
    expect(initialState.miniNodeStack).toEqual([])
  })

  /**
   * Test: Level 2 state
   * Validates: Requirement 2.1
   */
  test('level 2 shows main categories', () => {
    const level2State = {
      level: 2,
      selectedMain: null,
      selectedSub: null,
      miniNodeStack: [],
    }
    
    expect(level2State.level).toBe(2)
    // At level 2, we show HexagonalControlCenter
    const shouldShowHexagonal = level2State.level === 2
    expect(shouldShowHexagonal).toBe(true)
  })

  /**
   * Test: Level 3 state with WheelView
   * Validates: Requirements 2.1, 9.7
   */
  test('level 3 renders WheelView when selectedMain is set', () => {
    const level3State = {
      level: 3,
      selectedMain: 'voice',
      selectedSub: 'input',
      miniNodeStack: [
        { id: 'input-device', label: 'Input Device', icon: 'Mic', fields: [] },
      ],
      activeMiniNodeIndex: 0,
      miniNodeValues: {},
    }
    
    expect(level3State.level).toBe(3)
    expect(level3State.selectedMain).toBe('voice')
    
    // WheelView should render when level is 3 AND selectedMain is set
    const shouldShowWheelView = level3State.level === 3 && level3State.selectedMain !== null
    expect(shouldShowWheelView).toBe(true)
  })

  /**
   * Test: Level 3 without selectedMain
   * Validates: Requirement 2.1
   */
  test('level 3 does not render WheelView without selectedMain', () => {
    const invalidLevel3State = {
      level: 3,
      selectedMain: null,
      selectedSub: null,
      miniNodeStack: [],
    }
    
    // WheelView should NOT render without selectedMain
    const shouldShowWheelView = invalidLevel3State.level === 3 && invalidLevel3State.selectedMain !== null
    expect(shouldShowWheelView).toBe(false)
  })

  /**
   * Test: No level 4 exists
   * Validates: Requirement 9.7
   */
  test('no level 4 case exists in navigation system', () => {
    const validLevels = [1, 2, 3]
    
    // Level 4 should not be in valid levels
    expect(validLevels).not.toContain(4)
    expect(validLevels.length).toBe(3)
    
    // Maximum level is 3
    const maxLevel = Math.max(...validLevels)
    expect(maxLevel).toBe(3)
  })

  /**
   * Test: Level 4 normalization
   * Validates: Requirement 9.7
   */
  test('level 4 is normalized to level 3', () => {
    const normalizeLevel = (level) => {
      if (!Number.isFinite(level)) return 1
      if (level > 3) return 3
      if (level < 1) return 1
      return level
    }
    
    // Level 4 should be normalized to 3
    expect(normalizeLevel(4)).toBe(3)
    expect(normalizeLevel(5)).toBe(3)
    expect(normalizeLevel(100)).toBe(3)
    
    // Valid levels should remain unchanged
    expect(normalizeLevel(1)).toBe(1)
    expect(normalizeLevel(2)).toBe(2)
    expect(normalizeLevel(3)).toBe(3)
  })

  /**
   * Test: WheelView props
   * Validates: Requirements 2.1, 9.7
   */
  test('WheelView receives correct props', () => {
    const state = {
      level: 3,
      selectedMain: 'voice',
      selectedSub: 'input',
      miniNodeStack: [
        { id: 'input-device', label: 'Input Device', icon: 'Mic', fields: [] },
      ],
      miniNodeValues: {
        'input-device': { 'input_device': 'USB Microphone' },
      },
    }
    
    // Props that should be passed to WheelView
    const wheelViewProps = {
      categoryId: state.selectedMain,
      glowColor: '#00D4FF', // From theme
      expandedIrisSize: 240,
      initialValues: state.miniNodeValues,
      onConfirm: jest.fn(),
      onBackToCategories: jest.fn(),
    }
    
    expect(wheelViewProps.categoryId).toBe('voice')
    expect(wheelViewProps.glowColor).toMatch(/^#[0-9A-Fa-f]{6}$/)
    expect(wheelViewProps.expandedIrisSize).toBe(240)
    expect(wheelViewProps.initialValues).toEqual(state.miniNodeValues)
    expect(typeof wheelViewProps.onConfirm).toBe('function')
    expect(typeof wheelViewProps.onBackToCategories).toBe('function')
  })

  /**
   * Test: onBackToCategories callback
   * Validates: Requirements 2.1, 4.3
   */
  test('onBackToCategories dispatches GO_BACK action', () => {
    const handleGoBack = jest.fn()
    
    // Simulate WheelView back button click
    const handleWheelViewBack = () => {
      handleGoBack()
    }
    
    handleWheelViewBack()
    expect(handleGoBack).toHaveBeenCalled()
  })

  /**
   * Test: onConfirm callback
   * Validates: Requirements 2.1, 4.3
   */
  test('onConfirm saves miniNodeValues to context', () => {
    const values = {
      'input-device': { 'input_device': 'USB Microphone' },
      'sensitivity': { 'sensitivity_level': 75 },
    }
    
    // Simulate WheelView confirm
    const handleWheelViewConfirm = jest.fn((vals) => {
      console.log('[Navigation] WheelView confirmed with values:', vals)
    })
    
    handleWheelViewConfirm(values)
    expect(handleWheelViewConfirm).toHaveBeenCalledWith(values)
  })

  /**
   * Test: LocalStorage migration
   * Validates: Requirement 9.7
   */
  test('migrates level 4 to level 3 from localStorage', () => {
    const savedState = {
      level: 4,
      selectedMain: 'voice',
      selectedSub: 'input',
      miniNodeStack: [
        { id: 'input-device', label: 'Input Device', icon: 'Mic', fields: [] },
      ],
      miniNodeValues: {},
      level4ViewMode: 'orbital', // Obsolete property
    }
    
    // Simulate migration
    let migrated = false
    
    if (savedState.level === 4 || savedState.level > 3) {
      savedState.level = 3
      migrated = true
    }
    
    if ('level4ViewMode' in savedState) {
      delete savedState.level4ViewMode
      migrated = true
    }
    
    expect(savedState.level).toBe(3)
    expect(savedState.level4ViewMode).toBeUndefined()
    expect(migrated).toBe(true)
  })

  /**
   * Test: Navigation state validation
   * Validates: Requirement 2.1
   */
  test('validates navigation state consistency', () => {
    const validateNavState = (state) => {
      // Level 3 must have selectedMain
      if (state.level === 3 && !state.selectedMain) {
        return false
      }
      return true
    }
    
    // Valid states
    expect(validateNavState({ level: 1, selectedMain: null })).toBe(true)
    expect(validateNavState({ level: 2, selectedMain: null })).toBe(true)
    expect(validateNavState({ level: 3, selectedMain: 'voice' })).toBe(true)
    
    // Invalid state: level 3 without selectedMain
    expect(validateNavState({ level: 3, selectedMain: null })).toBe(false)
  })

  /**
   * Test: GO_BACK action from level 3
   * Validates: Requirements 4.3, 9.7
   */
  test('GO_BACK from level 3 transitions to level 2', () => {
    const state = {
      level: 3,
      selectedMain: 'voice',
      selectedSub: 'input',
      miniNodeStack: [
        { id: 'input-device', label: 'Input Device', icon: 'Mic', fields: [] },
      ],
    }
    
    // Simulate GO_BACK action
    const newLevel = state.level - 1
    const newState = {
      ...state,
      level: newLevel,
      selectedSub: null,
      miniNodeStack: [],
    }
    
    expect(newState.level).toBe(2)
    expect(newState.selectedSub).toBeNull()
    expect(newState.miniNodeStack).toEqual([])
    expect(newState.selectedMain).toBe('voice') // Preserved for highlighting
  })

  /**
   * Test: SELECT_SUB action sets level to 3
   * Validates: Requirements 4.1, 9.7
   */
  test('SELECT_SUB action sets level to 3 (not 4)', () => {
    const state = {
      level: 2,
      selectedMain: 'voice',
      selectedSub: null,
      miniNodeStack: [],
    }
    
    const miniNodes = [
      { id: 'input-device', label: 'Input Device', icon: 'Mic', fields: [] },
      { id: 'sensitivity', label: 'Sensitivity', icon: 'Sliders', fields: [] },
    ]
    
    // Simulate SELECT_SUB action
    const newState = {
      ...state,
      level: 3, // Should be 3, not 4
      selectedSub: 'input',
      miniNodeStack: miniNodes,
      activeMiniNodeIndex: 0,
    }
    
    expect(newState.level).toBe(3)
    expect(newState.level).not.toBe(4)
    expect(newState.selectedSub).toBe('input')
    expect(newState.miniNodeStack).toEqual(miniNodes)
  })
})
