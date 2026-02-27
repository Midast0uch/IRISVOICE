"use client"

import React, { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { useBrandColor, ThemeType, PRISM_THEMES } from "@/contexts/BrandColorContext"
import { Palette } from "lucide-react"

export function ThemeSwitcherCard() {
  const {
    theme, setTheme, getThemeConfig, brandColor, basePlateColor
  } = useBrandColor()
  const [isExpanded, setIsExpanded] = useState(false)
  const [isMounted, setIsMounted] = useState(false)

  useEffect(() => {
    setIsMounted(true)
  }, [])

  const currentTheme = getThemeConfig()
  const themes: ThemeType[] = ['aether', 'ember', 'aurum', 'verdant']

  // Dynamic colors for live feedback
  const glowColor = `hsl(${brandColor.hue}, ${brandColor.saturation}%, ${brandColor.lightness}%)`
  const baseColor = `hsl(${basePlateColor.hue}, ${basePlateColor.saturation}%, ${basePlateColor.lightness}%)`

  const handleThemeSelect = (t: ThemeType) => {
    setTheme(t)
  }

  const handleClick = () => {
    setIsExpanded(!isExpanded)
  }

  if (!isMounted) return null

  return (
    <motion.div
      className="rounded-md overflow-hidden"
      style={{
        width: 140,
        background: isExpanded
          ? `linear-gradient(135deg, ${glowColor.replace(')', ', 0.15)')}, ${baseColor.replace(')', ', 0.3)')}), url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.15' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`
          : 'rgba(255,255,255,0.04)',
        backgroundBlendMode: isExpanded ? 'overlay' : 'normal',
        border: `1px solid ${isExpanded ? glowColor.replace(')', ', 0.3)') : 'rgba(255,255,255,0.08)'}`,
      }}
      animate={{ height: isExpanded ? 110 : 28 }}
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
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
