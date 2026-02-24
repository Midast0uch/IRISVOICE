"use client"

import React, { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { useBrandColor, ThemeType, PRISM_THEMES, BrandColorState } from "@/contexts/BrandColorContext"
import { Palette } from "lucide-react"

export function ThemeSwitcherCard() {
  const { theme, setTheme, getThemeConfig, brandColor, setHue, setSaturation, setLightness } = useBrandColor()
  const [isExpanded, setIsExpanded] = useState(false)
  const [isMounted, setIsMounted] = useState(false)
  const [showSpecs, setShowSpecs] = useState(false)

  useEffect(() => {
    setIsMounted(true)
  }, [])

  const currentTheme = getThemeConfig()
  const themes: ThemeType[] = ['aether', 'ember', 'aurum', 'verdant']
  // Use dynamic brandColor for glow color so spec adjustments are reflected in UI
  const glowColor = `hsl(${brandColor.hue}, ${brandColor.saturation}%, ${brandColor.lightness}%)`

  const handleThemeSelect = (t: ThemeType) => {
    setTheme(t)
    setShowSpecs(true)
  }

  const handleClick = () => {
    if (isExpanded) {
      setShowSpecs(false)
    }
    setIsExpanded(!isExpanded)
  }

  if (!isMounted) return null

  return (
    <motion.div
      className="rounded-md overflow-hidden"
      style={{
        width: 140,
        background: isExpanded
          ? `linear-gradient(90deg, ${glowColor.replace(')', ', 0.12)')}, transparent), url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.15' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`
          : 'rgba(255,255,255,0.04)',
        backgroundBlendMode: isExpanded ? 'overlay' : 'normal',
        border: `1px solid ${isExpanded ? glowColor.replace(')', ', 0.25)') : 'rgba(255,255,255,0.08)'}`,
      }}
      animate={{ height: isExpanded ? (showSpecs ? 200 : 110) : 28 }}
      transition={{ type: "spring", stiffness: 400, damping: 35 }}
    >
      {/* Header - matches accordion card styling */}
      <motion.button
        onClick={handleClick}
        className="w-full flex items-center justify-between px-2 h-7"
        whileHover={{ backgroundColor: isExpanded ? 'transparent' : 'rgba(255,255,255,0.06)' }}
        whileTap={{ scale: 0.98 }}
      >
        <div className="flex items-center justify-center gap-1.5 overflow-hidden flex-1">
          <Palette 
            className="w-3 h-3 flex-shrink-0" 
            style={{ color: isExpanded ? glowColor : `${glowColor}aa` }}
          />
          <span 
            className="text-[10px] font-medium tracking-wide truncate"
            style={{ color: isExpanded ? '#fff' : '#ffffffaa' }}
          >
            Theme
          </span>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <span 
            className="text-[9px] tabular-nums"
            style={{ color: '#fff' }}
          >
            {currentTheme.name}
          </span>
        </div>
      </motion.button>

      {/* Expanded Content - 2x2 Theme Grid */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="px-2 pb-2"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="pt-1 border-t border-white/10">
              {/* 2x2 Grid container - white separators like toggle tabs */}
              <div 
                className="grid grid-cols-2 rounded overflow-hidden"
                style={{ 
                  background: 'rgba(255,255,255,0.25)',
                  gap: '1px'
                }}
              >
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
                      className="px-1.5 py-1 text-[7px] leading-tight transition-all text-left flex items-center gap-1.5 font-medium"
                      style={{
                        background: isSelected ? glowColor : 'rgba(0,0,0,0.4)',
                        color: isSelected ? '#000' : '#fff',
                        boxShadow: isSelected ? `inset 0 0 8px ${glowColor}80` : 'none',
                        minHeight: '28px'
                      }}
                      whileTap={{ scale: 0.95 }}
                      title={themeConfig.name}
                    >
                      {/* Color preview dot */}
                      <div
                        className="w-2 h-2 rounded-full flex-shrink-0"
                        style={{
                          background: themeConfig.glow.color,
                          boxShadow: `0 0 4px ${themeConfig.glow.color}`
                        }}
                      />
                      <span className="truncate">{themeConfig.name}</span>
                    </motion.button>
                  )
                })}
              </div>

              {/* Specs Adjuster - shown after theme selection */}
              {showSpecs && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="mt-2 pt-2 border-t border-white/10"
                >
                  <div className="text-[8px] text-white/60 mb-1.5 uppercase tracking-wider">Adjust</div>
                  
                  {/* Hue Slider */}
                  <div className="mb-2">
                    <div className="flex justify-between text-[7px] text-white/80 mb-0.5">
                      <span>Hue</span>
                      <span>{Math.round(brandColor.hue)}°</span>
                    </div>
                    <div
                      className="relative h-1.5 bg-white/20 rounded-full cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation()
                        const rect = e.currentTarget.getBoundingClientRect()
                        const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
                        setHue(pct * 360)
                      }}
                    >
                      <motion.div
                        className="absolute left-0 top-0 h-full rounded-full"
                        style={{ 
                          width: `${(brandColor.hue / 360) * 100}%`, 
                          background: `linear-gradient(90deg, #ff0000, #ffff00, #00ff00, #00ffff, #0000ff, #ff00ff, #ff0000)`
                        }}
                      />
                      <motion.div
                        className="absolute top-1/2 w-2 h-2 rounded-full bg-white border"
                        style={{ 
                          left: `calc(${(brandColor.hue / 360) * 100}% - 4px)`,
                          transform: 'translateY(-50%)',
                          borderColor: glowColor
                        }}
                      />
                    </div>
                  </div>

                  {/* Saturation Slider */}
                  <div className="mb-2">
                    <div className="flex justify-between text-[7px] text-white/80 mb-0.5">
                      <span>Sat</span>
                      <span>{Math.round(brandColor.saturation)}%</span>
                    </div>
                    <div
                      className="relative h-1.5 bg-white/20 rounded-full cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation()
                        const rect = e.currentTarget.getBoundingClientRect()
                        const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
                        setSaturation(pct * 100)
                      }}
                    >
                      <motion.div
                        className="absolute left-0 top-0 h-full rounded-full"
                        style={{ 
                          width: `${brandColor.saturation}%`, 
                          background: `linear-gradient(90deg, gray, ${glowColor})`
                        }}
                      />
                      <motion.div
                        className="absolute top-1/2 w-2 h-2 rounded-full bg-white border"
                        style={{ 
                          left: `calc(${brandColor.saturation}% - 4px)`,
                          transform: 'translateY(-50%)',
                          borderColor: glowColor
                        }}
                      />
                    </div>
                  </div>

                  {/* Lightness Slider */}
                  <div className="mb-1">
                    <div className="flex justify-between text-[7px] text-white/80 mb-0.5">
                      <span>Light</span>
                      <span>{Math.round(brandColor.lightness)}%</span>
                    </div>
                    <div
                      className="relative h-1.5 bg-white/20 rounded-full cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation()
                        const rect = e.currentTarget.getBoundingClientRect()
                        const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
                        setLightness(pct * 100)
                      }}
                    >
                      <motion.div
                        className="absolute left-0 top-0 h-full rounded-full"
                        style={{ 
                          width: `${brandColor.lightness}%`, 
                          background: `linear-gradient(90deg, black, ${glowColor}, white)`
                        }}
                      />
                      <motion.div
                        className="absolute top-1/2 w-2 h-2 rounded-full bg-white border"
                        style={{ 
                          left: `calc(${brandColor.lightness}% - 4px)`,
                          transform: 'translateY(-50%)',
                          borderColor: glowColor
                        }}
                      />
                    </div>
                  </div>

                  {/* Reset Button */}
                  <motion.button
                    onClick={(e) => {
                      e.stopPropagation()
                      const defaults = PRISM_THEMES[theme]
                      setHue(defaults.hue)
                      setSaturation(defaults.saturation)
                      setLightness(defaults.lightness)
                    }}
                    className="w-full mt-2 py-1 text-[7px] text-white/60 hover:text-white transition-colors"
                    whileTap={{ scale: 0.95 }}
                  >
                    Reset to Default
                  </motion.button>
                </motion.div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
