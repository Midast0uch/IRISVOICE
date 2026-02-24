'use client'

import React, { useState, useCallback, useRef, useEffect } from 'react'
import { motion } from 'framer-motion'
import { useBrandColor, ThemeType } from '@/contexts/BrandColorContext'
import { 
  meetsContrastRequirements, 
  PRESET_COLORS,
  interpolateHue 
} from '@/lib/brand-colors'
import { AlertTriangle, RotateCcw, Palette, Check } from 'lucide-react'

interface ColorPickerProps {
  onClose?: () => void
  showPreview?: boolean
}

export function ColorPicker({ onClose, showPreview = true }: ColorPickerProps) {
  const { 
    brandColor, 
    theme, 
    setHue, 
    setSaturation, 
    setLightness, 
    resetToThemeDefault,
    getHSLString 
  } = useBrandColor()
  
  const [isDragging, setIsDragging] = useState(false)
  const wheelRef = useRef<HTMLDivElement>(null)
  
  // Contrast check
  const contrastCheck = meetsContrastRequirements(
    brandColor.hue,
    brandColor.saturation,
    brandColor.lightness,
    theme === 'aurum' ? 0.05 : 0.95
  )
  
  // Calculate hue from mouse position on wheel
  const handleWheelInteraction = useCallback((e: React.MouseEvent | MouseEvent) => {
    if (!wheelRef.current) return
    
    const rect = wheelRef.current.getBoundingClientRect()
    const centerX = rect.left + rect.width / 2
    const centerY = rect.top + rect.height / 2
    
    const x = e.clientX - centerX
    const y = e.clientY - centerY
    
    let angle = Math.atan2(y, x) * (180 / Math.PI)
    angle = (angle + 90) % 360
    if (angle < 0) angle += 360
    
    setHue(Math.round(angle))
  }, [setHue])
  
  // Drag handlers
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isDragging) handleWheelInteraction(e)
    }
    
    const handleMouseUp = () => setIsDragging(false)
    
    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove)
      window.addEventListener('mouseup', handleMouseUp)
    }
    
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging, handleWheelInteraction])
  
  return (
    <div className="w-full max-w-md p-6 rounded-2xl glass">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Palette className="w-5 h-5" style={{ color: getHSLString() }} />
          <h3 className="text-lg font-semibold">Brand Color</h3>
        </div>
        
        {/* Accessibility Warning */}
        {!contrastCheck.passes && (
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex items-center gap-1.5 text-amber-400 text-sm"
          >
            <AlertTriangle className="w-4 h-4" />
            <span>Low contrast</span>
          </motion.div>
        )}
      </div>
      
      {/* Hue Wheel */}
      <div className="flex justify-center mb-6">
        <div
          ref={wheelRef}
          className="relative w-48 h-48 rounded-full cursor-pointer"
          style={{
            background: `conic-gradient(from 0deg, 
              hsl(0, 100%, 50%), 
              hsl(60, 100%, 50%), 
              hsl(120, 100%, 50%), 
              hsl(180, 100%, 50%), 
              hsl(240, 100%, 50%), 
              hsl(300, 100%, 50%), 
              hsl(360, 100%, 50%))`
          }}
          onMouseDown={(e) => {
            setIsDragging(true)
            handleWheelInteraction(e)
          }}
        >
          {/* Inner hole */}
          <div className="absolute inset-4 rounded-full bg-[#0a0a0f]" />
          
          {/* Selector indicator */}
          <motion.div
            className="absolute w-4 h-4 rounded-full border-2 border-white shadow-lg"
            style={{
              backgroundColor: getHSLString(),
              left: '50%',
              top: '50%',
              marginLeft: '-8px',
              marginTop: '-8px',
            }}
            animate={{
              x: Math.cos((brandColor.hue - 90) * Math.PI / 180) * 80,
              y: Math.sin((brandColor.hue - 90) * Math.PI / 180) * 80,
            }}
            transition={{ type: 'spring', stiffness: 300, damping: 20 }}
          />
        </div>
      </div>
      
      {/* Saturation & Lightness sliders */}
      <div className="space-y-4 mb-6">
        <div>
          <label className="text-sm text-muted-foreground mb-2 block">Saturation</label>
          <input
            type="range"
            min="0"
            max="100"
            value={brandColor.saturation}
            onChange={(e) => setSaturation(Number(e.target.value))}
            className="w-full h-2 rounded-lg appearance-none cursor-pointer"
            style={{
              background: `linear-gradient(to right, hsl(${brandColor.hue}, 0%, 50%), hsl(${brandColor.hue}, 100%, 50%))`
            }}
          />
        </div>
        
        <div>
          <label className="text-sm text-muted-foreground mb-2 block">Lightness</label>
          <input
            type="range"
            min="20"
            max="80"
            value={brandColor.lightness}
            onChange={(e) => setLightness(Number(e.target.value))}
            className="w-full h-2 rounded-lg appearance-none cursor-pointer"
            style={{
              background: `linear-gradient(to right, hsl(${brandColor.hue}, ${brandColor.saturation}%, 20%), hsl(${brandColor.hue}, ${brandColor.saturation}%, 80%))`
            }}
          />
        </div>
      </div>
      
      {/* Preset Swatches */}
      <div className="mb-6">
        <label className="text-sm text-muted-foreground mb-3 block">Presets</label>
        <div className="grid grid-cols-6 gap-2">
          {PRESET_COLORS.map((preset) => (
            <button
              key={preset.name}
              onClick={() => {
                setHue(preset.hue)
                setSaturation(preset.saturation)
                setLightness(preset.lightness)
              }}
              className="relative w-8 h-8 rounded-full transition-transform hover:scale-110 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-[#0a0a0f]"
              style={{ backgroundColor: `hsl(${preset.hue}, ${preset.saturation}%, ${preset.lightness}%)` }}
              title={preset.name}
            >
              {brandColor.hue === preset.hue && 
               Math.abs(brandColor.saturation - preset.saturation) < 5 &&
               Math.abs(brandColor.lightness - preset.lightness) < 5 && (
                <Check className="absolute inset-0 m-auto w-4 h-4 text-white drop-shadow-md" />
              )}
            </button>
          ))}
        </div>
      </div>
      
      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={resetToThemeDefault}
          className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-secondary hover:bg-secondary/80 transition-colors"
        >
          <RotateCcw className="w-4 h-4" />
          <span className="text-sm">Reset to {theme} default</span>
        </button>
        
        {onClose && (
          <button
            onClick={onClose}
            className="px-6 py-2 rounded-lg text-sm font-medium transition-colors"
            style={{ 
              backgroundColor: getHSLString(),
              color: brandColor.lightness > 50 ? '#0a0a0f' : '#fff'
            }}
          >
            Done
          </button>
        )}
      </div>
      
      {/* Contrast suggestion */}
      {!contrastCheck.passes && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="mt-4 text-xs text-amber-400/80 text-center"
        >
          Suggested lightness: {contrastCheck.suggestedLightness}%
        </motion.p>
      )}
    </div>
  )
}
