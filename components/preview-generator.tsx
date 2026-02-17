'use client'

import React from 'react'
import { motion } from 'framer-motion'
import { useBrandColor, ThemeType } from '@/contexts/BrandColorContext'
import { 
  generateAetherShimmers, 
  generateEmberGlow, 
  generateAurumMetal 
} from '@/lib/brand-colors'

interface ThemePreviewCardProps {
  themeType: ThemeType
  brandHue: number
  brandSat: number
  brandLight: number
  isActive: boolean
}

function ThemePreviewCard({ themeType, brandHue, brandSat, brandLight, isActive }: ThemePreviewCardProps) {
  // Generate theme-specific colors
  const aetherColors = generateAetherShimmers(brandHue)
  const emberColors = generateEmberGlow(brandHue, brandSat)
  const aurumColors = generateAurumMetal(brandHue, brandSat)
  
  const getPreviewStyles = () => {
    switch (themeType) {
      case 'aether':
        return {
          background: '#f8fafc',
          cardBg: 'rgba(255, 255, 255, 0.7)',
          accent: aetherColors.start,
          shimmer: `linear-gradient(90deg, ${aetherColors.start}, ${aetherColors.mid}, ${aetherColors.end})`,
          glowColor: aetherColors.glow,
        }
      case 'ember':
        return {
          background: '#f5f5f0',
          cardBg: '#1c1c1e',
          accent: emberColors.edgeGlow,
          edgeGlow: emberColors.edgeGlow,
          edgeSoft: emberColors.edgeSoft,
        }
      case 'aurum':
        return {
          background: '#0a0a0a',
          cardBg: '#161616',
          accent: aurumColors.primary,
          metalGradient: `conic-gradient(from 0deg, ${aurumColors.primary}, ${aurumColors.highlight}, ${aurumColors.secondary}, ${aurumColors.primary})`,
          ambient: aurumColors.ambient,
        }
      default:
        // Fallback for verdant, nebula, crimson - use aurum as base
        return {
          background: '#0a0a0a',
          cardBg: '#161616',
          accent: aurumColors.primary,
          metalGradient: `conic-gradient(from 0deg, ${aurumColors.primary}, ${aurumColors.highlight}, ${aurumColors.secondary}, ${aurumColors.primary})`,
          ambient: aurumColors.ambient,
        }
    }
  }
  
  const styles = getPreviewStyles()
  
  return (
    <motion.div
      className={`relative rounded-xl overflow-hidden transition-all duration-300 ${
        isActive ? 'ring-2 ring-offset-2' : ''
      }`}
      style={{
        background: styles.background,
        ['--ring-color' as string]: isActive ? (styles as any).accent : undefined,
      }}
      whileHover={{ scale: 1.02 }}
    >
      {/* Theme Label */}
      <div className="absolute top-2 left-2 z-10">
        <span 
          className="text-xs font-semibold px-2 py-1 rounded-full"
          style={{ 
            background: themeType === 'aurum' ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
            color: themeType === 'aurum' ? '#fff' : '#1c1c1e'
          }}
        >
          {themeType.charAt(0).toUpperCase() + themeType.slice(1)}
        </span>
      </div>
      
      {/* Preview Content */}
      <div className="p-4 pt-8">
        {/* Mock Button */}
        <div 
          className="h-6 rounded-lg mb-3 flex items-center justify-center"
          style={{
            background: themeType === 'aether' 
              ? styles.shimmer 
              : themeType === 'aurum'
                ? (styles as any).metalGradient
                : (styles as any).accent,
            boxShadow: themeType === 'aether' 
              ? `0 2px 8px ${(styles as any).glowColor}` 
              : themeType === 'ember'
                ? `inset 2px 0 4px ${(styles as any).edgeSoft}`
                : `0 0 12px ${(styles as any).ambient}`,
          }}
        >
          <span 
            className="text-[8px] font-medium"
            style={{ 
              color: themeType === 'aurum' || themeType === 'ember' ? '#fff' : '#1c1c1e'
            }}
          >
            Button
          </span>
        </div>
        
        {/* Mock Card */}
        <div 
          className="h-12 rounded-lg p-2"
          style={{
            background: styles.cardBg,
            borderLeft: themeType === 'ember' ? `2px solid ${(styles as any).edgeGlow}` : undefined,
            boxShadow: themeType === 'aether' 
              ? `0 2px 8px ${(styles as any).glowColor}` 
              : undefined,
          }}
        >
          <div 
            className="h-1.5 w-3/4 rounded mb-1"
            style={{ background: (styles as any).accent + '40' }}
          />
          <div 
            className="h-1.5 w-1/2 rounded"
            style={{ background: (styles as any).accent + '20' }}
          />
        </div>
      </div>
      
      {/* Active indicator */}
      {isActive && (
        <motion.div
          layoutId="activeIndicator"
          className="absolute inset-0 border-2 rounded-xl pointer-events-none"
          style={{ borderColor: (styles as any).accent }}
        />
      )}
    </motion.div>
  )
}

interface PreviewGeneratorProps {
  compact?: boolean
}

export function PreviewGenerator({ compact = false }: PreviewGeneratorProps) {
  const { brandColor, theme } = useBrandColor()
  const themes: ThemeType[] = ['aether', 'ember', 'aurum']
  
  return (
    <div className={`w-full ${compact ? 'p-4' : 'p-6'} rounded-2xl glass`}>
      {!compact && (
        <div className="mb-4">
          <h4 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            Live Preview
          </h4>
          <p className="text-xs text-muted-foreground/60 mt-1">
            See how your Brand Color appears across all materials
          </p>
        </div>
      )}
      
      <div className={`grid gap-3 ${compact ? 'grid-cols-3' : 'grid-cols-1 sm:grid-cols-3'}`}>
        {themes.map((themeType) => (
          <ThemePreviewCard
            key={themeType}
            themeType={themeType}
            brandHue={brandColor.hue}
            brandSat={brandColor.saturation}
            brandLight={brandColor.lightness}
            isActive={theme === themeType}
          />
        ))}
      </div>
      
      {/* Hue readout */}
      <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
        <span>HSL: {brandColor.hue}°, {brandColor.saturation}%, {brandColor.lightness}%</span>
        <span className="capitalize">Active: {theme}</span>
      </div>
    </div>
  )
}

// Compact inline version for integration in other UI
export function PreviewGeneratorInline() {
  return <PreviewGenerator compact />
}
