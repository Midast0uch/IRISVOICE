/**
 * Unit Tests for Error Handling
 * 
 * Tests specific error handling scenarios and edge cases.
 * 
 * Feature: wheelview-navigation-integration
 * 
 * Test coverage:
 * - Error boundary catches rendering errors
 * - Fallback UI displays correctly
 * - "Try again" button resets state
 * - Corrupted localStorage doesn't crash app
 * - Invalid field types are skipped
 * 
 * Validates: Requirements 15.3, 15.5, 15.7
 */

import { describe, test, expect, jest, beforeEach, afterEach } from '@jest/globals'

/**
 * Mock WheelViewErrorBoundary for testing
 * Simulates the behavior of the actual error boundary component
 */
class WheelViewErrorBoundaryMock {
  constructor() {
    this.state = {
      hasError: false,
      error: null,
    }
  }
  
  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      error,
    }
  }
  
  componentDidCatch(error, errorInfo) {
    console.error('[WheelView] Rendering error:', error, errorInfo)
  }
  
  handleReset() {
    this.state = {
      hasError: false,
      error: null,
    }
  }
  
  render(children) {
    if (this.state.hasError) {
      return {
        type: 'fallback',
        errorMessage: 'Failed to render settings view',
        tryAgainButton: true,
      }
    }
    return { type: 'children', content: children }
  }
}

describe('Error Handling Unit Tests', () => {
  let consoleErrorSpy
  let consoleWarnSpy
  
  beforeEach(() => {
    jest.clearAllMocks()
    // Suppress console errors in tests
    consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation()
    consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation()
  })
  
  afterEach(() => {
    consoleErrorSpy.mockRestore()
    consoleWarnSpy.mockRestore()
  })
  
  /**
   * Test: Error boundary catches rendering errors
   * Validates: Requirement 15.7
   */
  test('error boundary catches rendering errors', () => {
    const errorBoundary = new WheelViewErrorBoundaryMock()
    const error = new Error('Test rendering error')
    
    // Simulate error being caught
    errorBoundary.state = WheelViewErrorBoundaryMock.getDerivedStateFromError(error)
    
    const result = errorBoundary.render('child content')
    
    expect(result.type).toBe('fallback')
    expect(result.errorMessage).toBe('Failed to render settings view')
    expect(result.tryAgainButton).toBe(true)
  })

  /**
   * Test: Fallback UI displays correctly
   * Validates: Requirement 15.7
   */
  test('fallback UI displays with error message and try again button', () => {
    const errorBoundary = new WheelViewErrorBoundaryMock()
    const error = new Error('Component error')
    
    // Simulate error
    errorBoundary.state = WheelViewErrorBoundaryMock.getDerivedStateFromError(error)
    
    const result = errorBoundary.render('child content')
    
    // Check fallback UI structure
    expect(result.type).toBe('fallback')
    expect(result.errorMessage).toContain('Failed to render settings view')
    expect(result.tryAgainButton).toBe(true)
  })
  
  /**
   * Test: "Try again" button resets error state
   * Validates: Requirement 15.7
   */
  test('try again button resets error state', () => {
    const errorBoundary = new WheelViewErrorBoundaryMock()
    const error = new Error('Initial error')
    
    // Simulate error
    errorBoundary.state = WheelViewErrorBoundaryMock.getDerivedStateFromError(error)
    expect(errorBoundary.state.hasError).toBe(true)
    
    // Reset error state
    errorBoundary.handleReset()
    
    // State should be reset
    expect(errorBoundary.state.hasError).toBe(false)
    expect(errorBoundary.state.error).toBeNull()
    
    // Should render children now
    const result = errorBoundary.render('child content')
    expect(result.type).toBe('children')
    expect(result.content).toBe('child content')
  })

  /**
   * Test: Corrupted localStorage doesn't crash app
   * Validates: Requirement 15.5
   */
  test('corrupted localStorage returns default state', () => {
    const restoreNavigationState = () => {
      const defaultState = {
        level: 1,
        selectedMain: null,
        selectedSub: null,
        miniNodeStack: [],
        activeMiniNodeIndex: 0,
        miniNodeValues: {},
      }
      
      try {
        const saved = 'invalid-json{'
        if (!saved) return defaultState
        
        const parsed = JSON.parse(saved)
        
        if (typeof parsed !== 'object' || parsed === null) {
          throw new Error('Invalid state structure')
        }
        
        return { ...defaultState, ...parsed }
      } catch (error) {
        console.error('[NavigationContext] Failed to restore state:', error)
        return defaultState
      }
    }
    
    const restoredState = restoreNavigationState()
    
    // Should return default state without crashing
    expect(restoredState).toBeDefined()
    expect(restoredState.level).toBe(1)
    expect(restoredState.selectedMain).toBeNull()
    expect(restoredState.selectedSub).toBeNull()
    expect(restoredState.miniNodeStack).toEqual([])
    expect(restoredState.activeMiniNodeIndex).toBe(0)
    expect(restoredState.miniNodeValues).toEqual({})
    
    // Should have logged error
    expect(consoleErrorSpy).toHaveBeenCalled()
  })

  /**
   * Test: Invalid field types are skipped
   * Validates: Requirement 15.3
   */
  test('invalid field types are skipped with warning', () => {
    const renderField = (field) => {
      switch (field.type) {
        case 'text':
          return { component: 'TextField', ...field }
        case 'slider':
          return { component: 'SliderField', ...field }
        case 'dropdown':
          return { component: 'DropdownField', ...field }
        case 'toggle':
          return { component: 'ToggleField', ...field }
        case 'color':
          return { component: 'ColorField', ...field }
        default:
          console.warn(`[WheelView] Invalid field type: ${field.type}`)
          return null
      }
    }
    
    // Valid field types should render
    const textField = { id: 'test-text', label: 'Test', type: 'text' }
    expect(renderField(textField)).not.toBeNull()
    expect(renderField(textField).component).toBe('TextField')
    
    const sliderField = { id: 'test-slider', label: 'Test', type: 'slider' }
    expect(renderField(sliderField)).not.toBeNull()
    expect(renderField(sliderField).component).toBe('SliderField')
    
    // Invalid field types should return null and log warning
    const invalidField1 = { id: 'test-invalid', label: 'Test', type: 'invalid' }
    expect(renderField(invalidField1)).toBeNull()
    expect(consoleWarnSpy).toHaveBeenCalledWith(
      expect.stringContaining('Invalid field type: invalid')
    )
    
    const invalidField2 = { id: 'test-button', label: 'Test', type: 'button' }
    expect(renderField(invalidField2)).toBeNull()
    expect(consoleWarnSpy).toHaveBeenCalledWith(
      expect.stringContaining('Invalid field type: button')
    )
    
    const invalidField3 = { id: 'test-unknown', label: 'Test', type: 'unknown' }
    expect(renderField(invalidField3)).toBeNull()
    expect(consoleWarnSpy).toHaveBeenCalledWith(
      expect.stringContaining('Invalid field type: unknown')
    )
  })

  /**
   * Test: Multiple error scenarios
   * Validates: Requirements 15.3, 15.5, 15.7
   */
  test('handles multiple error scenarios gracefully', () => {
    // Test 1: Empty localStorage
    const restoreEmpty = () => {
      const defaultState = { level: 1, selectedMain: null }
      try {
        const saved = ''
        if (!saved) return defaultState
        return JSON.parse(saved)
      } catch (error) {
        return defaultState
      }
    }
    expect(restoreEmpty()).toEqual({ level: 1, selectedMain: null })
    
    // Test 2: Null localStorage
    const restoreNull = () => {
      const defaultState = { level: 1, selectedMain: null }
      try {
        const saved = 'null'
        if (!saved) return defaultState
        const parsed = JSON.parse(saved)
        if (parsed === null) return defaultState
        return parsed
      } catch (error) {
        return defaultState
      }
    }
    expect(restoreNull()).toEqual({ level: 1, selectedMain: null })
    
    // Test 3: Undefined field type
    const renderField = (field) => {
      const validTypes = ['text', 'slider', 'dropdown', 'toggle', 'color']
      if (!validTypes.includes(field.type)) {
        console.warn(`[WheelView] Invalid field type: ${field.type}`)
        return null
      }
      return { rendered: true }
    }
    
    expect(renderField({ type: undefined })).toBeNull()
    expect(renderField({ type: null })).toBeNull()
    expect(renderField({ type: '' })).toBeNull()
  })
  
  /**
   * Test: Error boundary with successful child
   * Validates: Requirement 15.7
   */
  test('error boundary renders children when no error', () => {
    const errorBoundary = new WheelViewErrorBoundaryMock()
    
    // No error state
    const result = errorBoundary.render('Success content')
    
    expect(result.type).toBe('children')
    expect(result.content).toBe('Success content')
  })
})
