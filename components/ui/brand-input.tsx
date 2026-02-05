'use client'

import React, { useState } from 'react'
import { motion } from 'framer-motion'
import { useBrandColor, ThemeType } from '@/contexts/BrandColorContext'
import { 
  generateAetherShimmers, 
  generateEmberGlow, 
  generateAurumMetal 
} from '@/lib/brand-colors'
import { cn } from '@/lib/utils'

interface BrandInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
}

export function BrandInput({ 
  label, 
  error, 
  className,
  ...props 
}: BrandInputProps) {
  const { theme, brandColor, getHSLString } = useBrandColor()
  const [isFocused, setIsFocused] = useState(false)

  const getThemeStyles = (t: ThemeType) => {
    switch (t) {
      case 'aether':
        const aether = generateAetherShimmers(brandColor.hue)
        return {
          container: {
            background: 'rgba(255, 255, 255, 0.7)',
            backdropFilter: 'blur(20px)',
            border: `1px solid ${isFocused ? aether.start : 'rgba(255,255,255,0.15)'}`,
            boxShadow: isFocused ? `0 0 0 3px ${aether.glow}` : '0 8px 32px rgba(0,0,0,0.1)',
          },
          input: {
            color: '#1c1c1e',
          },
          label: {
            color: '#1c1c1e',
          },
        }
      
      case 'ember':
        const ember = generateEmberGlow(brandColor.hue, brandColor.saturation)
        return {
          container: {
            background: '#1c1c1e',
            border: 'none',
            borderLeft: isFocused ? `3px solid ${ember.edgeGlow}` : '3px solid transparent',
            boxShadow: isFocused 
              ? `inset 3px 0 6px ${ember.edgeSoft}, 0 0 0 1px ${ember.edgeGlow}30`
              : '4px 4px 16px rgba(0,0,0,0.3)',
          },
          input: {
            color: '#f5f5f0',
          },
          label: {
            color: ember.edgeGlow,
          },
        }
      
      case 'aurum':
        const aurum = generateAurumMetal(brandColor.hue, brandColor.saturation)
        return {
          container: {
            background: '#161616',
            border: `1px solid ${isFocused ? aurum.primary : 'transparent'}`,
            borderRadius: '0.5rem',
            boxShadow: isFocused 
              ? `0 0 0 2px ${aurum.ambient}, 0 0 20px ${aurum.ambient}`
              : 'none',
          },
          input: {
            color: '#e5e5e5',
          },
          label: {
            color: aurum.primary,
          },
        }
    }
  }

  const styles = getThemeStyles(theme)

  return (
    <div className="w-full">
      {label && (
        <motion.label 
          className="block text-sm font-medium mb-2"
          style={styles.label}
          animate={{ 
            color: isFocused ? styles.label.color : styles.label.color + '99'
          }}
        >
          {label}
        </motion.label>
      )}
      <motion.div
        className={cn(
          'relative rounded-xl overflow-hidden transition-all duration-200',
          className
        )}
        style={styles.container}
        animate={{
          borderColor: isFocused ? styles.container.border : undefined,
        }}
      >
        <input
          className="w-full bg-transparent px-4 py-3 outline-none placeholder:text-muted-foreground/50"
          style={styles.input}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          {...props}
        />
        {theme === 'aether' && isFocused && (
          <motion.div 
            className="absolute bottom-0 left-0 right-0 h-0.5 aether-shimmer"
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ duration: 0.3 }}
          />
        )}
      </motion.div>
      {error && (
        <motion.p 
          className="mt-1 text-xs text-red-400"
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
        >
          {error}
        </motion.p>
      )}
    </div>
  )
}
