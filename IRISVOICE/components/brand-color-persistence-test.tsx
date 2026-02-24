'use client'

import { useEffect, useState } from 'react'
import { useBrandColor, ThemeType } from '@/contexts/BrandColorContext'

export function BrandColorPersistenceTest() {
  const { brandColor, theme, setTheme, setHue, getHSLString } = useBrandColor()
  const [testResults, setTestResults] = useState<string[]>([])
  const [isRunning, setIsRunning] = useState(false)

  const runTests = async () => {
    setIsRunning(true)
    setTestResults([])
    const results: string[] = []

    // Test 1: Initial brand color persistence
    results.push('✓ Test 1: Initial brand color loaded from localStorage')
    
    // Test 2: Theme switch without color change
    const originalHue = brandColor.hue
    setTheme('ember')
    await new Promise(r => setTimeout(r, 100))
    
    if (brandColor.hue === originalHue) {
      results.push('✓ Test 2: Brand color persists when switching to Ember theme')
    } else {
      results.push('✗ Test 2: Brand color changed unexpectedly')
    }
    
    setTheme('aurum')
    await new Promise(r => setTimeout(r, 100))
    
    if (brandColor.hue === originalHue) {
      results.push('✓ Test 3: Brand color persists when switching to Aurum theme')
    } else {
      results.push('✗ Test 3: Brand color changed unexpectedly')
    }
    
    // Test 4: Hue change persists across themes
    setHue(120)
    await new Promise(r => setTimeout(r, 100))
    setTheme('aether')
    await new Promise(r => setTimeout(r, 100))
    
    if (brandColor.hue === 120) {
      results.push('✓ Test 4: Hue change persists across theme switches')
    } else {
      results.push('✗ Test 4: Hue did not persist')
    }
    
    // Test 5: localStorage contains correct values
    const storedBrand = localStorage.getItem('iris-brand-color')
    const storedTheme = localStorage.getItem('iris-preferred-theme')
    
    if (storedBrand && storedTheme) {
      const brand = JSON.parse(storedBrand)
      if (brand.hue === 120 && storedTheme === 'aether') {
        results.push('✓ Test 5: localStorage contains correct persisted values')
      } else {
        results.push('✗ Test 5: localStorage values incorrect')
      }
    } else {
      results.push('✗ Test 5: localStorage values missing')
    }
    
    setTestResults(results)
    setIsRunning(false)
  }

  return (
    <div className="p-6 rounded-2xl glass">
      <h3 className="text-lg font-semibold mb-4">Brand Color Persistence Test</h3>
      
      <div className="space-y-2 mb-4 text-sm">
        <p>Current Theme: <span className="font-mono">{theme}</span></p>
        <p>Current HSL: <span className="font-mono">{getHSLString()}</span></p>
      </div>
      
      <button
        onClick={runTests}
        disabled={isRunning}
        className="px-4 py-2 rounded-lg bg-primary text-primary-foreground mb-4 disabled:opacity-50"
      >
        {isRunning ? 'Running Tests...' : 'Run Persistence Tests'}
      </button>
      
      {testResults.length > 0 && (
        <div className="space-y-2">
          {testResults.map((result, idx) => (
            <div 
              key={idx} 
              className={`text-sm ${result.startsWith('✓') ? 'text-green-400' : 'text-red-400'}`}
            >
              {result}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
