"use client"

import React, { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import * as LucideIcons from "lucide-react"
import type { MiniNode, FieldConfig } from "@/types/navigation"
import { TextField } from "./fields/TextField"
import { SliderField } from "./fields/SliderField"
import { DropdownField } from "./fields/DropdownField"
import { ToggleField } from "./fields/ToggleField"
import { ColorField } from "./fields/ColorField"
import { useBrandColor } from "@/contexts/BrandColorContext"

interface MiniNodeCardProps {
  miniNode: MiniNode
  isActive: boolean
  values: Record<string, any>
  onChange: (fieldId: string, value: any) => void
  onSave: () => void
  index: number
}

// Dynamically get Lucide icon
function getIcon(iconName: string) {
  const icons = LucideIcons as unknown as Record<string, React.ComponentType<{ className?: string }>>
  return icons[iconName] || LucideIcons.Circle
}

function renderField(
  field: FieldConfig,
  value: any,
  onChange: (value: any) => void,
  glowColor: string,
  theme: any,
  isCleanTheme: boolean
) {
  // Helper for themed backgrounds using hex opacity
  const themedBg = `${theme.shimmer.primary}25`
  const themedBorder = `${theme.shimmer.primary}66`
  const labelColor = '#ffffff'
  
  // Stop propagation wrapper for all field interactions
  const stopProp = (e: React.SyntheticEvent) => e.stopPropagation()

  switch (field.type) {
    case 'text':
      return (
        <div 
          className="p-2 rounded-lg space-y-1" 
          style={{ background: themedBg, border: `1px solid ${themedBorder}` }}
          onClick={stopProp}
        >
          <label className="text-[10px] uppercase tracking-wider" style={{ color: labelColor, fontWeight: 500 }}>
            {field.label}
          </label>
          <TextField
            label=""
            value={value ?? field.defaultValue ?? ""}
            placeholder={field.placeholder}
            onChange={onChange}
          />
        </div>
      )
    case 'slider':
      return (
        <div 
          className="p-2 rounded-lg space-y-1" 
          style={{ background: themedBg, border: `1px solid ${themedBorder}` }}
          onClick={stopProp}
        >
          <label className="text-[10px] uppercase tracking-wider" style={{ color: labelColor, fontWeight: 500 }}>
            {field.label}
          </label>
          <SliderField
            label=""
            value={value ?? field.defaultValue ?? field.min ?? 0}
            min={field.min ?? 0}
            max={field.max ?? 100}
            unit={field.unit}
            onChange={onChange}
          />
        </div>
      )
    case 'dropdown':
      return (
        <div 
          className="p-2 rounded-lg space-y-1" 
          style={{ background: themedBg, border: `1px solid ${themedBorder}` }}
          onClick={stopProp}
        >
          <label className="text-[10px] uppercase tracking-wider" style={{ color: labelColor, fontWeight: 500 }}>
            {field.label}
          </label>
          <DropdownField
            label=""
            value={value ?? field.defaultValue ?? field.options?.[0] ?? ""}
            options={field.options || []}
            onChange={onChange}
          />
        </div>
      )
    case 'toggle':
      return (
        <div 
          className="p-2 rounded-lg flex items-center justify-between" 
          style={{ background: themedBg, border: `1px solid ${themedBorder}` }}
          onClick={stopProp}
        >
          <label className="text-[10px] uppercase tracking-wider" style={{ color: labelColor, fontWeight: 500 }}>
            {field.label}
          </label>
          <ToggleField
            label=""
            value={value ?? field.defaultValue ?? false}
            onChange={onChange}
          />
        </div>
      )
    case 'color':
      return (
        <div 
          className="p-2 rounded-lg space-y-1" 
          style={{ background: themedBg, border: `1px solid ${themedBorder}` }}
          onClick={stopProp}
        >
          <label className="text-[10px] uppercase tracking-wider" style={{ color: labelColor, fontWeight: 500 }}>
            {field.label}
          </label>
          <ColorField
            label=""
            value={value ?? field.defaultValue ?? "#00D4FF"}
            onChange={onChange}
          />
        </div>
      )
    default:
      return null
  }
}

export function MiniNodeCard({
  miniNode,
  isActive,
  values,
  onChange,
  onSave,
  index,
}: MiniNodeCardProps) {
  const [isConfirming, setIsConfirming] = useState(false)
  const IconComponent = getIcon(miniNode.icon)
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColor = theme.glow.color
  const isCleanTheme = theme.name === 'Verdant' || theme.name === 'Aurum'
  
  // Intensity multipliers (same as PrismNode)
  const intensityMultipliers = {
    glowOpacity: isCleanTheme ? 1.5 : 1.0,
    glassOpacity: isCleanTheme ? 1.2 : 1.0,
    shimmerOpacity: 1.0,
  }
  
  // Calculate dynamic opacities
  const glassOpacity = Math.min(theme.glass.opacity * intensityMultipliers.glassOpacity, 0.35)
  const glowOpacity = Math.min(theme.glow.opacity * intensityMultipliers.glowOpacity, 0.5)
  const shimmerOpacity = Math.min(1 * intensityMultipliers.shimmerOpacity, 1)

  // 2x size of regular nodes (90px → 180px)
  const CARD_SIZE = 180

  const handleSave = () => {
    setIsConfirming(true)
    onSave()
    setTimeout(() => setIsConfirming(false), 400)
  }

  // Cards stack vertically with small offset (handled by parent)
  // Active card lifts up slightly
  const verticalLift = isActive ? -20 : 0

  return (
    <motion.div
      layout
      initial={{ scale: 0.8, opacity: 0, y: 20 }}
      animate={{
        scale: isActive ? 1.05 : 1,
        opacity: 1,
        y: verticalLift,
        zIndex: isActive ? 30 : 20 - index,
      }}
      exit={{ scale: 0.8, opacity: 0, y: 20 }}
      transition={{
        type: "spring",
        stiffness: 300,
        damping: 30,
        duration: 0.3,
      }}
      className="relative"
      style={{
        width: CARD_SIZE,
        transformOrigin: "center center",
      }}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
    >
      {/* Animated border ring - Prism Glass shimmer (NOT for clean themes) */}
      {!isCleanTheme && (
        <motion.div
          className="absolute -inset-0.5 pointer-events-none rounded-3xl"
          style={{
            padding: "2px",
            background: `conic-gradient(from 0deg, 
              transparent 0deg, 
              ${theme.shimmer.secondary}${Math.round(30 * shimmerOpacity).toString(16).padStart(2, '0')} 60deg, 
              ${theme.shimmer.primary}${Math.round(isActive ? 255 : 230 * shimmerOpacity).toString(16).padStart(2, '0')} 180deg, 
              ${theme.shimmer.secondary}${Math.round(30 * shimmerOpacity).toString(16).padStart(2, '0')} 300deg, 
              transparent 360deg)`,
            WebkitMask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
            WebkitMaskComposite: "xor",
          }}
          animate={{ rotate: 360 }}
          transition={{ duration: 8, repeat: Infinity, ease: "linear" }}
        />
      )}

      {/* Active glow effect - Prism Glass */}
      {isActive && (
        <motion.div
          className="absolute -inset-2 pointer-events-none rounded-3xl"
          style={{
            background: `radial-gradient(circle, ${theme.glow.color}${Math.round(glowOpacity * 255).toString(16).padStart(2, '0')} 0%, transparent 70%)`,
            filter: `blur(${theme.glow.blur}px)`,
          }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        />
      )}

      {/* Card body - Prism Glass morphism */}
      <div
        className="relative w-full flex flex-col rounded-3xl overflow-hidden pointer-events-auto"
        style={{
          background: `linear-gradient(${theme.gradient.angle}deg, ${theme.gradient.from}${Math.round(glassOpacity * 255).toString(16).padStart(2, '0')}, ${theme.gradient.to}${Math.round(glassOpacity * 255).toString(16).padStart(2, '0')})`,
          backdropFilter: `blur(${theme.glass.blur}px)`,
          WebkitBackdropFilter: `blur(${theme.glass.blur}px)`,
          border: `1px solid ${theme.shimmer.primary}${Math.round(theme.glass.borderOpacity * 255).toString(16).padStart(2, '0')}`,
          boxShadow: `inset 0 1px 1px rgba(255,255,255,0.1), 0 4px 24px rgba(0,0,0,0.2)`,
          minHeight: CARD_SIZE,
        }}
      >
        {/* Themed header background */}
        <div 
          className="absolute top-0 left-0 right-0 h-[52px] pointer-events-none"
          style={{
            background: `linear-gradient(180deg, ${theme.shimmer.primary}40 0%, transparent 100%)`,
          }}
        />

        {/* Header */}
        <div 
          className="relative flex items-center justify-center gap-2 px-3 py-3 border-b"
          style={{ borderColor: `${theme.shimmer.primary}${Math.round(0.35 * 255).toString(16).padStart(2, '0')}` }}
        >
          {React.createElement(IconComponent as React.ComponentType<{ className?: string; style?: React.CSSProperties; strokeWidth?: number }>, {
            className: "w-5 h-5",
            style: { 
              color: '#ffffff',
              filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.7))'
            },
            strokeWidth: 1.5
          })}
          <span className="text-xs font-semibold tracking-wider uppercase" style={{ 
            color: '#ffffff',
            textShadow: '0 1px 2px rgba(0,0,0,0.7), 0 0 2px rgba(0,0,0,0.5)',
            letterSpacing: '0.1em'
          }}>
            {miniNode.label}
          </span>
        </div>

        {/* Fields area */}
        <div className="p-3 space-y-2 flex-1" style={{ background: `radial-gradient(circle at top, ${theme.shimmer.primary}20 0%, transparent 70%)` }}>
          {miniNode.fields?.map((field) => (
            <div key={field.id} className="text-xs">
              {renderField(field, values[field.id], (value) => onChange(field.id, value), glowColor, theme, isCleanTheme)}
            </div>
          ))}
        </div>

        {/* Save Button - only when active */}
        <AnimatePresence>
          {isActive && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="px-3 pb-3"
            >
              <motion.button
                onClick={(e) => {
                  e.stopPropagation()
                  handleSave()
                }}
                disabled={isConfirming}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                animate={isConfirming ? { scale: [1, 1.1, 1] } : {}}
                transition={{ duration: 0.3 }}
                className="w-full py-2 rounded-xl text-xs font-medium transition-all duration-200"
                style={{
                  background: isConfirming 
                    ? "rgba(34, 197, 94, 0.8)"
                    : `linear-gradient(135deg, ${theme.shimmer.primary}cc, ${theme.shimmer.primary}66)`,
                  color: "white",
                  boxShadow: isConfirming
                    ? "0 0 20px rgba(34, 197, 94, 0.4)"
                    : `0 0 15px ${theme.glow.color}4d`,
                }}
              >
                {isConfirming ? "✓ Saved" : "Save"}
              </motion.button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}
