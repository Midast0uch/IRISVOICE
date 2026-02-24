"use client"

import { useState, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import * as LucideIcons from "lucide-react"
import type { MiniNode, FieldConfig, FieldValue } from "@/types/navigation"
import { ToggleRow } from "./fields/ToggleRow"
import { DeviceRow } from "./fields/DeviceRow"
import { CompactSlider } from "./fields/CompactSlider"
import { TextField } from "./fields/TextField"
import { SliderField } from "./fields/SliderField"
import { DropdownField } from "./fields/DropdownField"
import { ToggleField } from "./fields/ToggleField"
import { ColorField } from "./fields/ColorField"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { ThemeSwitcherCard } from "./theme-switcher-card"

interface CompactAccordionProps {
  miniNode: MiniNode
  isActive: boolean
  values: Record<string, FieldValue>
  onChange: (fieldId: string, value: FieldValue) => void
  onSelect: () => void
  glowColor: string
}

function getIcon(iconName: string) {
  const icons = LucideIcons as unknown as Record<string, React.ComponentType<{ className?: string; style?: React.CSSProperties }>>
  return icons[iconName] || LucideIcons.Circle
}

function getFieldPreview(field: FieldConfig, value: FieldValue): string {
  if (field.type === 'toggle') return Boolean(value) ? 'ON' : 'OFF'
  if (field.type === 'dropdown') return String(value || field.defaultValue || field.options?.[0] || '-')
  if (field.type === 'slider') {
    const val = typeof value === 'number' ? value : (typeof field.defaultValue === 'number' ? field.defaultValue : (field.min ?? 0))
    return `${Math.round(val)}${field.unit || ''}`
  }
  return String(value || field.defaultValue || '-')
}

function renderField(
  field: FieldConfig,
  value: FieldValue,
  onChange: (value: FieldValue) => void,
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
    case 'custom':
      return (
        <div onClick={stopProp}>
          <ThemeSwitcherCard />
        </div>
      )
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
            value={String(value ?? field.defaultValue ?? "")}
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
            value={typeof value === 'number' ? value : (typeof field.defaultValue === 'number' ? field.defaultValue : (field.min ?? 0))}
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
            value={String(value ?? field.defaultValue ?? field.options?.[0] ?? "")}
            options={field.options || []}
            loadOptions={field.loadOptions}
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
            value={Boolean(value ?? field.defaultValue ?? false)}
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
            value={String(value ?? field.defaultValue ?? "#00D4FF")}
            onChange={onChange}
          />
        </div>
      )
    default:
      return null
  }
}

export function CompactAccordion({
  miniNode,
  isActive,
  values,
  onChange,
  onSelect,
  glowColor,
}: CompactAccordionProps) {
  const IconComponent = getIcon(miniNode.icon)
  const { getThemeConfig, isCleanTheme } = useBrandColor()
  const theme = getThemeConfig()
  
  // Get preview from first field
  const previewField = miniNode.fields?.[0]
  const previewValue = previewField ? getFieldPreview(previewField, values[previewField.id]) : ''

  const handleHeaderClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    onSelect()
  }, [onSelect])

  return (
    <motion.div
      className="rounded-lg overflow-hidden"
      style={{
        background: isActive 
          ? `linear-gradient(135deg, ${glowColor.replace(')', ', 0.15)')}, ${glowColor.replace(')', ', 0.05)')})`
          : `linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03))`,
        border: `1px solid ${isActive ? glowColor.replace(')', ', 0.3)') : 'rgba(255,255,255,0.1)'}`,
      }}
      animate={{
        height: isActive ? 'auto' : 36,
      }}
      transition={{ type: "spring", stiffness: 400, damping: 30 }}
    >
      {/* Header - Always visible */}
      <motion.button
        onClick={handleHeaderClick}
        className="w-full flex items-center justify-between px-3 h-9"
        whileHover={{ backgroundColor: 'rgba(255,255,255,0.05)' }}
        whileTap={{ scale: 0.98 }}
      >
        <div className="flex items-center gap-2">
          <IconComponent 
            className="w-3.5 h-3.5" 
            style={{ color: isActive ? glowColor : `${glowColor}cc` }}
          />
          <span className="text-[11px] font-medium tracking-wide uppercase" style={{ color: '#ffffff' }}>
            {miniNode.label}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px]" style={{ color: `${glowColor}cc` }}>
            {previewValue}
          </span>
          <motion.div
            animate={{ rotate: isActive ? 90 : 0 }}
            transition={{ duration: 0.2 }}
          >
            <LucideIcons.ChevronRight 
              className="w-3.5 h-3.5"
              style={{ color: `${glowColor}99` }}
            />
          </motion.div>
        </div>
      </motion.button>

      {/* Expanded Content */}
      <AnimatePresence>
        {isActive && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="px-3 pb-3"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="pt-1 border-t border-white/10">
              {miniNode.fields?.map((field) => (
                <div key={field.id}>
                  {renderField(field, values[field.id], (value) => onChange(field.id, value), glowColor, theme, isCleanTheme)}
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
