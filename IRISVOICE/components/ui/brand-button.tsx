'use client'

import React from 'react'
import { motion } from 'framer-motion'
import { useBrandColor, ThemeType } from '@/contexts/BrandColorContext'
import { 
  generateAetherShimmers, 
  generateEmberGlow, 
  generateAurumMetal 
} from '@/lib/brand-colors'
import { cn } from '@/lib/utils'

interface BrandButtonProps {
  variant?: 'primary' | 'secondary' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  children: React.ReactNode
  className?: string
  disabled?: boolean
  onClick?: () => void
  type?: 'button' | 'submit' | 'reset'
}

export function BrandButton({ 
  variant = 'primary', 
  size = 'md', 
  children, 
  className,
  disabled,
  onClick,
  type = 'button',
}: BrandButtonProps) {
  const { theme, brandColor, getHSLString } = useBrandColor()

  // Get theme-specific colors
  const getThemeStyles = (t: ThemeType) => {
    const hsl = getHSLString()
    
    switch (t) {
      case 'aether':
        const aether = generateAetherShimmers(brandColor.hue)
        return {
          primary: {
            background: `linear-gradient(90deg, ${aether.start}, ${aether.mid}, ${aether.end})`,
            boxShadow: `0 4px 16px ${aether.glow}`,
            border: 'none',
            color: '#0a0a0f',
          },
          secondary: {
            background: 'rgba(255, 255, 255, 0.1)',
            border: `1px solid ${aether.start}40`,
            color: aether.start,
            boxShadow: 'none',
          },
          ghost: {
            background: 'transparent',
            border: 'none',
            color: aether.start,
            boxShadow: 'none',
          },
        }
      
      case 'ember':
        const ember = generateEmberGlow(brandColor.hue, brandColor.saturation)
        return {
          primary: {
            background: '#1c1c1e',
            borderLeft: `3px solid ${ember.edgeGlow}`,
            boxShadow: `inset 3px 0 6px ${ember.edgeSoft}, 4px 4px 16px rgba(0,0,0,0.3)`,
            color: ember.edgeGlow,
          },
          secondary: {
            background: 'transparent',
            border: `1px solid ${ember.edgeGlow}40`,
            color: ember.edgeGlow,
            boxShadow: 'none',
          },
          ghost: {
            background: 'transparent',
            border: 'none',
            color: ember.edgeGlow,
            boxShadow: 'none',
          },
        }
      
      case 'aurum':
        const aurum = generateAurumMetal(brandColor.hue, brandColor.saturation)
        return {
          primary: {
            background: `conic-gradient(from 0deg, ${aurum.primary}, ${aurum.highlight}, ${aurum.secondary}, ${aurum.primary})`,
            borderRadius: '28%',
            border: 'none',
            color: '#0a0a0f',
            boxShadow: `0 0 20px ${aurum.ambient}`,
          },
          secondary: {
            background: '#161616',
            border: `1px solid ${aurum.primary}60`,
            borderRadius: '28%',
            color: aurum.primary,
            boxShadow: `0 0 8px ${aurum.ambient}`,
          },
          ghost: {
            background: 'transparent',
            border: 'none',
            color: aurum.primary,
            boxShadow: 'none',
          },
        }
      default:
        // Fallback for verdant, nebula, crimson using aurum as base
        const fallbackAurum = generateAurumMetal(brandColor.hue, brandColor.saturation)
        return {
          primary: {
            background: `conic-gradient(from 0deg, ${fallbackAurum.primary}, ${fallbackAurum.highlight}, ${fallbackAurum.secondary}, ${fallbackAurum.primary})`,
            borderRadius: '28%',
            border: 'none',
            color: '#0a0a0f',
            boxShadow: `0 0 20px ${fallbackAurum.ambient}`,
          },
          secondary: {
            background: '#161616',
            border: `1px solid ${fallbackAurum.primary}60`,
            borderRadius: '28%',
            color: fallbackAurum.primary,
            boxShadow: `0 0 8px ${fallbackAurum.ambient}`,
          },
          ghost: {
            background: 'transparent',
            border: 'none',
            color: fallbackAurum.primary,
            boxShadow: 'none',
          },
        }
    }
  }

  const sizeClasses = {
    sm: 'px-3 py-1.5 text-xs',
    md: 'px-4 py-2 text-sm',
    lg: 'px-6 py-3 text-base',
  }

  const styles = getThemeStyles(theme)[variant]

  return (
    <motion.button
      className={cn(
        'relative font-medium transition-all duration-200 flex items-center justify-center gap-2 overflow-hidden',
        sizeClasses[size],
        className
      )}
      style={{
        ...styles,
        borderRadius: theme === 'aurum' && variant === 'primary' ? '28%' : '0.75rem',
      }}
      whileHover={{ 
        scale: 1.02,
        boxShadow: styles.boxShadow?.replace(/\d+px/, (m: string) => String(parseInt(m) * 1.5)),
      }}
      whileTap={{ scale: 0.98 }}
      type={type}
      disabled={disabled}
      onClick={onClick}
    >
      {theme === 'aurum' && variant === 'primary' && (
        <div 
          className="absolute inset-0 aurum-metal-ring opacity-80"
          style={{ borderRadius: '28%' }}
        />
      )}
      <span className="relative z-10">{children}</span>
    </motion.button>
  )
}
