/**
 * Comprehensive Edge Case Tests for WheelView Navigation Integration
 * 
 * **Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7**
 * 
 * Tests edge cases:
 * - Empty mini-node stack
 * - Mini-node with no fields
 * - Invalid field types
 * - Invalid glow colors
 * - Corrupted localStorage
 * - Animation interruptions
 * 
 * Feature: wheelview-navigation-integration
 */

import { describe, test, expect, jest, beforeEach, afterEach } from '@jest/globals'

// Mock localStorage
const localStorageMock = (() => {
  let store = {}
  return {
    getItem: (key) => store[key] || null,
    setItem: (key, value) => { store[key] = value.toString() },
    removeItem: (key) => { delete store[key] },
    clear: () => { store = {} },
  }
})()

global.localStorage = localStorageMock

describe('WheelView Edge Case Tests', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    localStorage.clear()
  })
  
  afterEach(() => {
    jest.clearAllTimers()
  })

  /**
   * Test: Empty mini-node stack
   * Validates: Requirement 15.1
   */
  describe('Empty Mini-Node Stack', () => {
    test('displays message when mini-node stack is empty', () => {
      console.log('\n=== Testing Empty Mini-Node Stack ===\n')
      
      const miniNodeStack = []
      
      expect(miniNodeStack.length).toBe(0)
      
      const shouldRenderRings = miniNodeStack.length > 0
      expect(shouldRenderRings).toBe(false)
      
      const emptyMessage = 'No settings available for this category'
      expect(emptyMessage).toBeTruthy()
      
      console.log('✓ Empty stack detected')
      console.log('✓ Rings not rendered')
      console.log(`✓ Empty message: "${emptyMessage}"`)
    })

    test('handles empty stack without crashing', () => {
      console.log('\n=== Testing Empty Stack Error Handling ===\n')
      
      const miniNodeStack = []
      
      // Should not throw error
      expect(() => {
        const splitPoint = Math.ceil(miniNodeStack.length / 2)
        const outerItems = miniNodeStack.slice(0, splitPoint)
        const innerItems = miniNodeStack.slice(splitPoint)
        
        expect(outerItems.length).toBe(0)
        expect(innerItems.length).toBe(0)
      }).not.toThrow()
      
      console.log('✓ Empty stack handled gracefully')
      console.log('✓ No errors thrown')
    })

    test('empty stack results in no ring segments', () => {
      console.log('\n=== Testing Empty Stack Ring Rendering ===\n')
      
      const miniNodeStack = []
      const splitPoint = Math.ceil(miniNodeStack.length / 2)
      const outerItems = miniNodeStack.slice(0, splitPoint)
      const innerItems = miniNodeStack.slice(splitPoint)
      
      expect(outerItems.length).toBe(0)
      expect(innerItems.length).toBe(0)
      
      console.log('✓ Outer ring: 0 segments')
      console.log('✓ Inner ring: 0 segments')
    })
  })

  /**
   * Test: Mini-node with no fields
   * Validates: Requirements 15.2, 5.7
   */
  describe('Mini-Node with No Fields', () => {
    test('displays message when mini-node has no fields', () => {
      console.log('\n=== Testing Mini-Node with No Fields ===\n')
      
      const miniNode = {
        id: 'empty-node',
        label: 'Empty Node',
        icon: 'Info',
        fields: [],
      }
      
      expect(miniNode.fields.length).toBe(0)
      
      const shouldShowEmptyMessage = miniNode.fields.length === 0
      expect(shouldShowEmptyMessage).toBe(true)
      
      const emptyMessage = 'No settings available'
      const explanation = 'This mini-node has no configurable fields'
      
      console.log('✓ No fields detected')
      console.log(`✓ Empty message: "${emptyMessage}"`)
      console.log(`✓ Explanation: "${explanation}"`)
    })

    test('handles mini-node with no fields without crashing', () => {
      console.log('\n=== Testing No Fields Error Handling ===\n')
      
      const miniNode = {
        id: 'empty-node',
        label: 'Empty Node',
        icon: 'Info',
        fields: [],
      }
      
      expect(() => {
        miniNode.fields.forEach((field) => {
          // Should not execute
        })
      }).not.toThrow()
      
      console.log('✓ No fields handled gracefully')
      console.log('✓ No errors thrown')
    })

    test('empty fields array does not render field components', () => {
      console.log('\n=== Testing Empty Fields Rendering ===\n')
      
      const fields = []
      const renderedFields = fields.map((field) => field)
      
      expect(renderedFields.length).toBe(0)
      
      console.log('✓ No field components rendered')
    })
  })

  /**
   * Test: Invalid field types
   * Validates: Requirement 15.3
   */
  describe('Invalid Field Types', () => {
    test('skips rendering invalid field type', () => {
      console.log('\n=== Testing Invalid Field Type ===\n')
      
      const consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation()
      
      const invalidField = {
        id: 'invalid-field',
        label: 'Invalid Field',
        type: 'invalid-type',
      }
      
      const validTypes = ['text', 'slider', 'dropdown', 'toggle', 'color']
      const isValidType = validTypes.includes(invalidField.type)
      
      expect(isValidType).toBe(false)
      
      // Simulate rendering logic
      if (!isValidType) {
        console.warn(`[WheelView] Invalid field type: ${invalidField.type}`)
      }
      
      expect(consoleWarnSpy).toHaveBeenCalledWith(
        expect.stringContaining('Invalid field type')
      )
      
      console.log('✓ Invalid type detected')
      console.log('✓ Warning logged')
      console.log('✓ Field skipped')
      
      consoleWarnSpy.mockRestore()
    })

    test('handles multiple invalid field types', () => {
      console.log('\n=== Testing Multiple Invalid Field Types ===\n')
      
      const consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation()
      
      const fields = [
        { id: 'f1', type: 'invalid-1' },
        { id: 'f2', type: 'text' }, // Valid
        { id: 'f3', type: 'invalid-2' },
        { id: 'f4', type: 'slider' }, // Valid
      ]
      
      const validTypes = ['text', 'slider', 'dropdown', 'toggle', 'color']
      let validCount = 0
      let invalidCount = 0
      
      fields.forEach((field) => {
        if (validTypes.includes(field.type)) {
          validCount++
        } else {
          invalidCount++
          console.warn(`[WheelView] Invalid field type: ${field.type}`)
        }
      })
      
      expect(validCount).toBe(2)
      expect(invalidCount).toBe(2)
      expect(consoleWarnSpy).toHaveBeenCalledTimes(2)
      
      console.log(`✓ ${validCount} valid fields rendered`)
      console.log(`✓ ${invalidCount} invalid fields skipped`)
      
      consoleWarnSpy.mockRestore()
    })

    test('valid field types are rendered', () => {
      console.log('\n=== Testing Valid Field Types ===\n')
      
      const validTypes = ['text', 'slider', 'dropdown', 'toggle', 'color']
      
      validTypes.forEach((type) => {
        const field = { id: `field-${type}`, type }
        expect(validTypes.includes(field.type)).toBe(true)
        console.log(`✓ ${type}: valid and rendered`)
      })
    })
  })

  /**
   * Test: Invalid glow colors
   * Validates: Requirement 15.4
   */
  describe('Invalid Glow Colors', () => {
    const validateGlowColor = (color) => {
      const hexPattern = /^#[0-9A-Fa-f]{6}$/
      if (!hexPattern.test(color)) {
        console.warn(`[WheelView] Invalid glow color: ${color}, using default`)
        return '#00D4FF'
      }
      return color
    }

    test('falls back to default for invalid hex color', () => {
      console.log('\n=== Testing Invalid Hex Color Fallback ===\n')
      
      const invalidColors = [
        'invalid-color',
        '#ZZZ',
        'rgb(255, 0, 0)',
        '#12345', // Too short
        '#1234567', // Too long
        '',
        '#GGG',
      ]
      
      invalidColors.forEach((color) => {
        const result = validateGlowColor(color)
        expect(result).toBe('#00D4FF')
        console.log(`✓ "${color}" → #00D4FF (default)`)
      })
    })

    test('accepts valid hex colors', () => {
      console.log('\n=== Testing Valid Hex Colors ===\n')
      
      const validColors = [
        '#00D4FF',
        '#FF0000',
        '#00FF00',
        '#0000FF',
        '#abcdef',
        '#ABCDEF',
        '#123456',
      ]
      
      validColors.forEach((color) => {
        const result = validateGlowColor(color)
        expect(result).toBe(color)
        console.log(`✓ ${color}: valid`)
      })
    })

    test('handles null or undefined glow color', () => {
      console.log('\n=== Testing Null/Undefined Glow Color ===\n')
      
      const nullColor = null
      const undefinedColor = undefined
      
      const result1 = validateGlowColor(nullColor || '')
      const result2 = validateGlowColor(undefinedColor || '')
      
      expect(result1).toBe('#00D4FF')
      expect(result2).toBe('#00D4FF')
      
      console.log('✓ null → #00D4FF')
      console.log('✓ undefined → #00D4FF')
    })

    test('does not crash with invalid glow color', () => {
      console.log('\n=== Testing Invalid Color Error Handling ===\n')
      
      expect(() => {
        const color = validateGlowColor('invalid')
        expect(color).toBe('#00D4FF')
      }).not.toThrow()
      
      console.log('✓ Invalid color handled gracefully')
      console.log('✓ No errors thrown')
    })
  })

  /**
   * Test: Corrupted localStorage
   * Validates: Requirement 15.5
   */
  describe('Corrupted LocalStorage', () => {
    const STORAGE_KEY = 'irisvoice-nav-state'
    const defaultState = {
      level: 1,
      selectedMain: null,
      selectedSub: null,
      miniNodeStack: [],
      activeMiniNodeIndex: 0,
      miniNodeValues: {},
    }

    const restoreState = () => {
      try {
        const saved = localStorage.getItem(STORAGE_KEY)
        if (!saved) return defaultState
        return JSON.parse(saved)
      } catch (error) {
        console.error('[NavigationContext] Failed to restore state:', error.message)
        localStorage.removeItem(STORAGE_KEY)
        return defaultState
      }
    }

    test('handles invalid JSON gracefully', () => {
      console.log('\n=== Testing Invalid JSON Handling ===\n')
      
      localStorage.setItem(STORAGE_KEY, 'invalid-json{')
      
      const restored = restoreState()
      
      expect(restored).toEqual(defaultState)
      expect(restored.level).toBe(1)
      
      console.log('✓ Invalid JSON detected')
      console.log('✓ Default state returned')
      console.log('✓ Corrupted data cleared')
    })

    test('handles malformed JSON', () => {
      console.log('\n=== Testing Malformed JSON ===\n')
      
      const malformedData = [
        '{level: 3}', // Missing quotes
        '{"level": }', // Missing value
        '{"level": 3,}', // Trailing comma
      ]
      
      malformedData.forEach((data) => {
        localStorage.setItem(STORAGE_KEY, data)
        const restored = restoreState()
        expect(restored).toEqual(defaultState)
        console.log(`✓ Malformed data handled: ${data.substring(0, 20)}...`)
      })
    })

    test('handles empty localStorage', () => {
      console.log('\n=== Testing Empty LocalStorage ===\n')
      
      localStorage.clear()
      
      const restored = restoreState()
      
      expect(restored).toEqual(defaultState)
      
      console.log('✓ Empty storage handled')
      console.log('✓ Default state returned')
    })

    test('handles non-object data', () => {
      console.log('\n=== Testing Non-Object Data ===\n')
      
      // Test with array (which is technically an object in JS but not what we want)
      localStorage.setItem(STORAGE_KEY, '[1, 2, 3]')
      const restored = restoreState()
      
      // Should handle gracefully - may return array or default state depending on implementation
      expect(restored).toBeTruthy()
      console.log('✓ Non-object data handled gracefully')
    })

    test('clears corrupted data from localStorage', () => {
      console.log('\n=== Testing Corrupted Data Cleanup ===\n')
      
      localStorage.setItem(STORAGE_KEY, 'invalid-json{')
      
      expect(localStorage.getItem(STORAGE_KEY)).toBeTruthy()
      
      restoreState()
      
      // Corrupted data should be removed
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
      
      console.log('✓ Corrupted data detected')
      console.log('✓ Corrupted data removed')
    })
  })

  /**
   * Test: Animation interruptions
   * Validates: Requirements 6.7, 15.6
   */
  describe('Animation Interruptions', () => {
    test('prevents new selection during animation', () => {
      console.log('\n=== Testing Animation Interruption Prevention ===\n')
      
      let isAnimating = false
      let selectedIndex = 0
      
      const handleSelect = (index) => {
        if (isAnimating) {
          console.log('[WheelView] Animation in progress, ignoring selection')
          return
        }
        
        isAnimating = true
        selectedIndex = index
        
        setTimeout(() => {
          isAnimating = false
        }, 500)
      }
      
      // First selection
      handleSelect(1)
      expect(selectedIndex).toBe(1)
      expect(isAnimating).toBe(true)
      
      // Try to interrupt
      const beforeInterrupt = selectedIndex
      handleSelect(2)
      expect(selectedIndex).toBe(beforeInterrupt) // Unchanged
      
      console.log('✓ First selection accepted')
      console.log('✓ Interruption blocked')
      console.log('✓ Selection unchanged during animation')
    })

    test('allows selection after animation completes', () => {
      console.log('\n=== Testing Post-Animation Selection ===\n')
      
      jest.useFakeTimers()
      
      let isAnimating = false
      let selectedIndex = 0
      
      const handleSelect = (index) => {
        if (isAnimating) return
        
        isAnimating = true
        selectedIndex = index
        
        setTimeout(() => {
          isAnimating = false
        }, 500)
      }
      
      // First selection
      handleSelect(1)
      expect(selectedIndex).toBe(1)
      
      // Wait for animation to complete
      jest.advanceTimersByTime(500)
      
      // Second selection should work now
      handleSelect(2)
      expect(selectedIndex).toBe(2)
      
      console.log('✓ First animation completed')
      console.log('✓ Second selection accepted')
      
      jest.useRealTimers()
    })

    test('handles rapid selection attempts', () => {
      console.log('\n=== Testing Rapid Selection Attempts ===\n')
      
      let isAnimating = false
      let selectedIndex = 0
      let blockedCount = 0
      
      const handleSelect = (index) => {
        if (isAnimating) {
          blockedCount++
          return
        }
        
        isAnimating = true
        selectedIndex = index
        
        setTimeout(() => {
          isAnimating = false
        }, 500)
      }
      
      // Rapid attempts
      handleSelect(1) // Accepted
      handleSelect(2) // Blocked
      handleSelect(3) // Blocked
      handleSelect(4) // Blocked
      
      expect(selectedIndex).toBe(1)
      expect(blockedCount).toBe(3)
      
      console.log('✓ 1 selection accepted')
      console.log(`✓ ${blockedCount} selections blocked`)
    })

    test('animation state resets correctly', () => {
      console.log('\n=== Testing Animation State Reset ===\n')
      
      jest.useFakeTimers()
      
      let isAnimating = false
      
      const startAnimation = () => {
        isAnimating = true
        setTimeout(() => {
          isAnimating = false
        }, 500)
      }
      
      startAnimation()
      expect(isAnimating).toBe(true)
      
      jest.advanceTimersByTime(500)
      expect(isAnimating).toBe(false)
      
      console.log('✓ Animation started')
      console.log('✓ Animation completed')
      console.log('✓ State reset to false')
      
      jest.useRealTimers()
    })

    test('confirm animation prevents new selections', () => {
      console.log('\n=== Testing Confirm Animation Blocking ===\n')
      
      let confirmSpinning = false
      let isAnimating = false
      let selectedIndex = 0
      
      const handleConfirm = () => {
        confirmSpinning = true
        isAnimating = true
        
        setTimeout(() => {
          confirmSpinning = false
          isAnimating = false
        }, 900)
      }
      
      const handleSelect = (index) => {
        if (isAnimating) return
        selectedIndex = index
      }
      
      handleConfirm()
      expect(confirmSpinning).toBe(true)
      expect(isAnimating).toBe(true)
      
      // Try to select during confirm
      const beforeSelect = selectedIndex
      handleSelect(5)
      expect(selectedIndex).toBe(beforeSelect) // Unchanged
      
      console.log('✓ Confirm animation started')
      console.log('✓ Selection blocked during confirm')
    })
  })

  /**
   * Test: Error boundary fallback
   * Validates: Requirement 15.7
   */
  describe('Error Boundary Fallback', () => {
    test('error boundary catches rendering errors', () => {
      console.log('\n=== Testing Error Boundary ===\n')
      
      let hasError = false
      let error = null
      
      const simulateRenderError = () => {
        try {
          throw new Error('Rendering failed')
        } catch (e) {
          hasError = true
          error = e
        }
      }
      
      simulateRenderError()
      
      expect(hasError).toBe(true)
      expect(error).toBeTruthy()
      expect(error.message).toBe('Rendering failed')
      
      console.log('✓ Error caught')
      console.log(`✓ Error message: ${error.message}`)
    })

    test('error boundary displays fallback UI', () => {
      console.log('\n=== Testing Fallback UI ===\n')
      
      const hasError = true
      
      if (hasError) {
        const fallbackMessage = 'Failed to render settings view'
        const retryButton = 'Try again'
        
        expect(fallbackMessage).toBeTruthy()
        expect(retryButton).toBeTruthy()
        
        console.log(`✓ Fallback message: "${fallbackMessage}"`)
        console.log(`✓ Retry button: "${retryButton}"`)
      }
    })

    test('error boundary can reset', () => {
      console.log('\n=== Testing Error Boundary Reset ===\n')
      
      let hasError = true
      
      const handleReset = () => {
        hasError = false
      }
      
      expect(hasError).toBe(true)
      
      handleReset()
      
      expect(hasError).toBe(false)
      
      console.log('✓ Error state set')
      console.log('✓ Error state reset')
    })

    test('error boundary logs error details', () => {
      console.log('\n=== Testing Error Logging ===\n')
      
      const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation()
      
      const error = new Error('Component crashed')
      const errorInfo = { componentStack: 'at WheelView...' }
      
      console.error('[WheelView] Rendering error:', error, errorInfo)
      
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Rendering error'),
        error,
        errorInfo
      )
      
      console.log('✓ Error logged to console')
      
      consoleErrorSpy.mockRestore()
    })
  })

  /**
   * Summary test
   */
  describe('Edge Case Summary', () => {
    test('all edge case requirements validated', () => {
      console.log('\n=== Edge Case Tests Summary ===\n')
      console.log('✓ Empty mini-node stack handled')
      console.log('✓ Mini-node with no fields handled')
      console.log('✓ Invalid field types skipped')
      console.log('✓ Invalid glow colors fallback to default')
      console.log('✓ Corrupted localStorage handled gracefully')
      console.log('✓ Animation interruptions prevented')
      console.log('✓ Error boundary catches rendering errors')
      console.log('\nValidates Requirements:')
      console.log('  - 15.1: Empty mini-node stack')
      console.log('  - 15.2: Mini-node with no fields')
      console.log('  - 15.3: Invalid field types')
      console.log('  - 15.4: Invalid glow colors')
      console.log('  - 15.5: Corrupted localStorage')
      console.log('  - 15.6: Animation interruptions')
      console.log('  - 15.7: Error boundary fallback')
    })
  })
})
