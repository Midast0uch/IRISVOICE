"use client"

import React, { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { useBrandColor, ThemeType, PRISM_THEMES } from "@/contexts/BrandColorContext"
import { Palette, ChevronUp, ChevronDown, Copy } from "lucide-react"

type TestIntensity = "subtle" | "medium" | "strong"

interface IntensityConfig {
  multiplier: number
  label: string
}

const INTENSITY_CONFIG: Record<TestIntensity, IntensityConfig> = {
  subtle: { multiplier: 0.7, label: "Subtle" },
  medium: { multiplier: 1.0, label: "Medium" },
  strong: { multiplier: 1.3, label: "Strong" },
}

export function ThemeTestSwitcher() {
  const { theme, setTheme, getThemeConfig, brandColor, setHue, setSaturation, setLightness } = useBrandColor()

  const [isExpanded, setIsExpanded] = useState(true)
  const [intensity, setIntensity] = useState<TestIntensity>("medium")
  const [isMounted, setIsMounted] = useState(false)
  
  // Color adjustment state
  const [customHue, setCustomHue] = useState(brandColor.hue)
  const [customSat, setCustomSat] = useState(brandColor.saturation)
  const [customLight, setCustomLight] = useState(brandColor.lightness)
  const [showColorAdjust, setShowColorAdjust] = useState(false)

  useEffect(() => {
    setIsMounted(true)
  }, [])
  
  // Sync with brandColor changes
  useEffect(() => {
    setCustomHue(brandColor.hue)
    setCustomSat(brandColor.saturation)
    setCustomLight(brandColor.lightness)
  }, [brandColor])

  const currentTheme = getThemeConfig()
  const themes: ThemeType[] = ['aether', 'ember', 'aurum', 'verdant']

  const handleThemeSelect = (t: ThemeType) => {
    setTheme(t)
    if (t === "ember") setIntensity("strong")
    if (t === "aurum") setIntensity("subtle")
    if (t === "aether") setIntensity("medium")
    if (t === "verdant") setIntensity("medium")
  }
  
  const applyCustomColors = () => {
    setHue(customHue)
    setSaturation(customSat)
    setLightness(customLight)
  }
  
  const copyColorSpecs = () => {
    const specs = `hue: ${Math.round(customHue)}, saturation: ${Math.round(customSat)}, lightness: ${Math.round(customLight)}`
    
    // Try clipboard API first, fallback to console if blocked
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(specs)
          .then(() => alert(`Copied: ${specs}`))
          .catch(() => {
            console.log('[Theme Color Specs]', specs);
            alert(`Color Specs (check console): ${specs}`);
          });
      } else {
        // Fallback for non-secure contexts
        console.log('[Theme Color Specs]', specs);
        alert(`Color Specs: ${specs}\n\n(Check browser console for copy button)`);
      }
    } catch {
      console.log('[Theme Color Specs]', specs);
      alert(`Color Specs: ${specs}`);
    }
  }

  if (!isMounted) return null

  return (
    <motion.div
      className="fixed z-[9999] pointer-events-auto"
      style={{ top: 24, left: 24 }}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      onClick={(e) => {
        e.stopPropagation()
        e.preventDefault()
      }}
      onMouseDown={(e) => {
        e.stopPropagation()
        e.preventDefault()
      }}
      onPointerDown={(e) => {
        e.stopPropagation()
        e.preventDefault()
      }}
    >
      <AnimatePresence mode="wait">
        {!isExpanded ? (
          <motion.button
            key="collapsed"
            onClick={(e) => { 
              e.stopPropagation() 
              setIsExpanded(true) 
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-full backdrop-blur-xl border border-white/10 shadow-2xl"
            style={{ 
              background: `linear-gradient(135deg, ${currentTheme.gradient.from}30, ${currentTheme.gradient.to}20)`,
              borderColor: `${currentTheme.shimmer.primary}40`,
            }}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            exit={{ opacity: 0, scale: 0.9 }}
          >
            <div 
              className="w-3 h-3 rounded-full"
              style={{ 
                background: currentTheme.shimmer.primary,
                boxShadow: `0 0 8px ${currentTheme.shimmer.primary}`,
              }} 
            />
            <span className="text-xs font-medium text-white/90 uppercase tracking-wider">
              {currentTheme.name}
            </span>
            <ChevronUp className="w-3 h-3 text-white/60" />
          </motion.button>
        ) : (
          <motion.div
            key="expanded"
            className="w-72 rounded-2xl backdrop-blur-xl border border-white/10 shadow-2xl overflow-hidden"
            style={{ 
              background: `linear-gradient(180deg, rgba(10,10,15,0.95) 0%, rgba(5,5,10,0.98) 100%)`,
              borderColor: `${currentTheme.shimmer.primary}30`,
            }}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
          >
            {/* Header */}
            <div 
              className="flex items-center justify-between px-4 py-3 border-b"
              style={{ borderColor: `${currentTheme.shimmer.primary}20` }}
            >
              <div className="flex items-center gap-2">
                <Palette className="w-4 h-4" style={{ color: currentTheme.shimmer.primary }} />
                <div>
                  <span className="text-sm font-semibold text-white/90">{currentTheme.name}</span>
                  <p className="text-[10px] text-white/50">{currentTheme.description}</p>
                </div>
              </div>
              <button
                onClick={(e) => { 
                  e.stopPropagation() 
                  setIsExpanded(false) 
                }}
                className="p-1.5 rounded-lg hover:bg-white/10 transition-colors"
              >
                <ChevronDown className="w-4 h-4 text-white/60" />
              </button>
            </div>

            {/* Theme Grid - 2x2 Layout */}
            <div className="p-3 grid grid-cols-2 gap-2">
              {themes.map((t) => {
                const themeConfig = PRISM_THEMES[t]
                const isSelected = theme === t
                
                return (
                  <motion.button
                    key={t}
                    onClick={(e) => { 
                      e.stopPropagation() 
                      handleThemeSelect(t) 
                    }}
                    className={`relative p-3 rounded-xl border transition-all text-left ${
                      isSelected ? 'border-white/30 bg-white/10' : 'border-white/5 hover:border-white/20 hover:bg-white/5'
                    }`}
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                  >
                    {/* Theme Preview - Gradient Background */}
                    <div 
                      className="w-full h-14 rounded-lg mb-2 relative overflow-hidden"
                      style={{
                        background: `linear-gradient(${themeConfig.gradient.angle}deg, ${themeConfig.gradient.from}, ${themeConfig.gradient.to})`,
                        opacity: 0.4,
                      }}
                    >
                      {/* Shimmer preview */}
                      <motion.div
                        className="absolute inset-0 rounded-lg"
                        style={{
                          background: `conic-gradient(from 0deg, transparent 0deg, ${themeConfig.shimmer.secondary}20 60deg, ${themeConfig.shimmer.primary}60 180deg, ${themeConfig.shimmer.secondary}20 300deg, transparent 360deg)`,
                        }}
                        animate={{ rotate: 360 }}
                        transition={{ duration: 8, repeat: Infinity, ease: "linear" }}
                      />
                    </div>
                    
                    {/* Theme Name */}
                    <div className="text-xs font-medium text-white/90 mb-0.5">
                      {themeConfig.name}
                    </div>
                    
                    {/* Mood */}
                    <div className="text-[9px] text-white/50 leading-tight">
                      {themeConfig.mood}
                    </div>

                    {/* Selected Indicator */}
                    {isSelected && (
                      <motion.div
                        layoutId="selectedTheme"
                        className="absolute top-2 right-2 w-2 h-2 rounded-full"
                        style={{ background: themeConfig.shimmer.primary }}
                      />
                    )}
                  </motion.button>
                )
              })}
            </div>

            {/* Intensity Selector */}
            <div className="px-3 pb-2">
              <div className="flex gap-1 bg-white/5 rounded-lg p-1">
                {(['subtle', 'medium', 'strong'] as TestIntensity[]).map((i) => (
                  <button
                    key={i}
                    onClick={(e) => { 
                      e.stopPropagation() 
                      setIntensity(i) 
                    }}
                    className={`flex-1 py-1.5 text-[10px] rounded-md transition-all ${
                      intensity === i ? 'bg-white/20 text-white font-medium' : 'text-white/50 hover:text-white/70'
                    }`}
                  >
                    {INTENSITY_CONFIG[i].label}
                  </button>
                ))}
              </div>
            </div>

            {/* Color Adjustment Toggle */}
            <div className="px-3 pb-2">
              <button
                onClick={(e) => { e.stopPropagation(); setShowColorAdjust(!showColorAdjust) }}
                className="w-full py-2 text-[10px] text-white/70 hover:text-white bg-white/5 rounded-lg transition-colors"
              >
                {showColorAdjust ? 'Hide Color Adjust' : 'Adjust Colors'}
              </button>
            </div>

            {/* Color Adjustment Panel */}
            <AnimatePresence>
              {showColorAdjust && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="px-3 pb-3 space-y-2 overflow-hidden"
                  onClick={(e) => e.stopPropagation()}
                >
                  {/* Hue */}
                  <div className="space-y-1">
                    <div className="flex justify-between text-[10px] text-white/60">
                      <span>Hue</span>
                      <span>{Math.round(customHue)}°</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="360"
                      value={customHue}
                      onChange={(e) => { 
                        e.stopPropagation(); 
                        const val = Number(e.target.value);
                        setCustomHue(val);
                        setHue(val);
                        console.log('[ThemeAdjust] Hue:', val);
                      }}
                      onMouseUp={(e) => { e.stopPropagation(); applyCustomColors() }}
                      onPointerUp={(e) => { e.stopPropagation(); applyCustomColors() }}
                      onMouseDown={(e) => e.stopPropagation()}
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => e.stopPropagation()}
                      className="w-full h-1 bg-white/20 rounded-full appearance-none cursor-pointer"
                      style={{ background: `linear-gradient(to right, hsl(0,100%,50%), hsl(60,100%,50%), hsl(120,100%,50%), hsl(180,100%,50%), hsl(240,100%,50%), hsl(300,100%,50%), hsl(360,100%,50%))` }}
                    />
                  </div>
                  
                  {/* Saturation */}
                  <div className="space-y-1">
                    <div className="flex justify-between text-[10px] text-white/60">
                      <span>Saturation</span>
                      <span>{Math.round(customSat)}%</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="100"
                      value={customSat}
                      onChange={(e) => { 
                        e.stopPropagation(); 
                        const val = Number(e.target.value);
                        setCustomSat(val);
                        setSaturation(val);
                        console.log('[ThemeAdjust] Saturation:', val);
                      }}
                      onMouseUp={(e) => { e.stopPropagation(); applyCustomColors() }}
                      onPointerUp={(e) => { e.stopPropagation(); applyCustomColors() }}
                      onMouseDown={(e) => e.stopPropagation()}
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => e.stopPropagation()}
                      className="w-full h-1 bg-white/20 rounded-full appearance-none cursor-pointer"
                    />
                  </div>
                  
                  {/* Lightness */}
                  <div className="space-y-1">
                    <div className="flex justify-between text-[10px] text-white/60">
                      <span>Lightness</span>
                      <span>{Math.round(customLight)}%</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="100"
                      value={customLight}
                      onChange={(e) => { 
                        e.stopPropagation(); 
                        const val = Number(e.target.value);
                        setCustomLight(val);
                        setLightness(val);
                        console.log('[ThemeAdjust] Lightness:', val);
                      }}
                      onMouseUp={(e) => { e.stopPropagation(); applyCustomColors() }}
                      onPointerUp={(e) => { e.stopPropagation(); applyCustomColors() }}
                      onMouseDown={(e) => e.stopPropagation()}
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => e.stopPropagation()}
                      className="w-full h-1 bg-white/20 rounded-full appearance-none cursor-pointer"
                    />
                  </div>

                  {/* Copy Button */}
                  <button
                    onClick={(e) => { e.stopPropagation(); copyColorSpecs() }}
                    className="w-full mt-2 py-2 flex items-center justify-center gap-2 text-[10px] bg-white/10 hover:bg-white/20 rounded-lg transition-colors text-white/80"
                  >
                    <Copy className="w-3 h-3" />
                    Copy Color Specs
                  </button>
                  
                  {/* Current Values Display */}
                  <div className="text-[9px] text-white/40 font-mono text-center pt-1">
                    hue: {Math.round(customHue)}, sat: {Math.round(customSat)}, light: {Math.round(customLight)}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
