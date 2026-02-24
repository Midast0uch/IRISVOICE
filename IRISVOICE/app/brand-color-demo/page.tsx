'use client'

import React from 'react'
import { motion } from 'framer-motion'
import { ColorPicker } from '@/components/color-picker'
import { PreviewGenerator } from '@/components/preview-generator'
import { useBrandColor, ThemeType } from '@/contexts/BrandColorContext'
import { 
  generateAetherShimmers, 
  generateEmberGlow, 
  generateAurumMetal 
} from '@/lib/brand-colors'

export default function BrandColorDemo() {
  const { theme, setTheme, brandColor, getHSLString } = useBrandColor()

  const themes: ThemeType[] = ['aether', 'ember', 'aurum']

  // Get theme-specific colors
  const getThemeColors = (t: ThemeType) => {
    switch (t) {
      case 'aether':
        return generateAetherShimmers(brandColor.hue)
      case 'ember':
        return generateEmberGlow(brandColor.hue, brandColor.saturation)
      case 'aurum':
        return generateAurumMetal(brandColor.hue, brandColor.saturation)
    }
  }

  const currentColors = getThemeColors(theme)

  return (
    <div className="min-h-screen p-8 bg-[#0a0a0f]">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-8"
        >
          <h1 className="text-4xl font-bold mb-2" style={{ color: getHSLString() }}>
            ChromaShift Theme Engine
          </h1>
          <p className="text-muted-foreground">
            Brand Color system with Aether, Ember, and Aurum material themes
          </p>
        </motion.div>

        {/* Theme Selector */}
        <div className="mb-8 flex gap-3">
          {themes.map((t) => (
            <button
              key={t}
              onClick={() => setTheme(t)}
              className={`px-4 py-2 rounded-lg capitalize transition-all ${
                theme === t 
                  ? 'ring-2 ring-offset-2 ring-offset-[#0a0a0f]' 
                  : 'bg-secondary hover:bg-secondary/80'
              }`}
              style={{
                backgroundColor: theme === t ? getHSLString() : undefined,
                color: theme === t 
                  ? (brandColor.lightness > 50 ? '#0a0a0f' : '#fff')
                  : undefined,
              }}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Left Column - Color Picker */}
          <div className="space-y-6">
            <ColorPicker />
            <PreviewGenerator />
          </div>

          {/* Right Column - Live Demo */}
          <div className="space-y-6">
            {/* Theme-Specific Demo */}
            <div className="p-6 rounded-2xl glass">
              <h3 className="text-lg font-semibold mb-4 capitalize">
                {theme} Material Demo
              </h3>

              {/* Demo content based on active theme */}
              {theme === 'aether' && (
                <div className="space-y-4">
                  <div 
                    className="h-12 rounded-xl aether-shimmer"
                    style={{ 
                      boxShadow: `0 4px 16px ${(currentColors as any).glow || 'rgba(0,255,136,0.3)'}` 
                    }}
                  />
                  <div 
                    className="p-4 rounded-xl"
                    style={{ 
                      background: 'rgba(255,255,255,0.05)',
                      backdropFilter: 'blur(20px)',
                      border: '1px solid rgba(255,255,255,0.15)'
                    }}
                  >
                    <p className="text-sm text-muted-foreground">
                      Aether: Frosted glass with prismatic shimmer
                    </p>
                  </div>
                </div>
              )}

              {theme === 'ember' && (
                <div className="space-y-4">
                  <div 
                    className="h-12 rounded-2xl ember-edge-glow"
                    style={{ 
                      background: '#1c1c1e',
                      boxShadow: '4px 4px 16px rgba(0,0,0,0.3)'
                    }}
                  />
                  <div className="p-4 rounded-xl bg-[#1c1c1e]">
                    <p className="text-sm" style={{ color: (currentColors as any).edgeGlow }}>
                      Ember: Warm industrial with directional edge glow
                    </p>
                  </div>
                </div>
              )}

              {theme === 'aurum' && (
                <div className="space-y-4">
                  <div className="relative h-16 rounded-[28%] overflow-hidden">
                    <div 
                      className="absolute inset-0 aurum-metal-ring"
                      style={{ borderRadius: '28%' }}
                    />
                    <div 
                      className="absolute inset-2 bg-[#0a0a0a] rounded-[28%] flex items-center justify-center"
                    >
                      <span className="text-sm text-muted-foreground">
                        Liquid Metal Ring
                      </span>
                    </div>
                  </div>
                  <div 
                    className="p-4 rounded-xl"
                    style={{ 
                      background: '#161616',
                      boxShadow: `0 0 20px ${(currentColors as any).ambient || 'rgba(0,255,136,0.15)'}`
                    }}
                  >
                    <p className="text-sm" style={{ color: (currentColors as any).primary }}>
                      Aurum: Liquid metal floating in void space
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* CSS Variables Display */}
            <div className="p-6 rounded-2xl glass">
              <h3 className="text-lg font-semibold mb-4">Active CSS Variables</h3>
              <pre className="text-xs overflow-x-auto p-4 rounded-lg bg-black/50">
                <code className="text-green-400">
{`--brand-hue: ${brandColor.hue};
--brand-saturation: ${brandColor.saturation}%;
--brand-lightness: ${brandColor.lightness}%;
--brand-color: ${getHSLString()};`}
                </code>
              </pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
