"use client"

import { useState, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import * as LucideIcons from "lucide-react"
import type { MiniNode, FieldConfig } from "@/types/navigation"
import { ToggleRow } from "./fields/ToggleRow"
import { DeviceRow } from "./fields/DeviceRow"
import { CompactSlider } from "./fields/CompactSlider"
import { useBrandColor } from "@/contexts/BrandColorContext"

interface CompactAccordionProps {
  miniNode: MiniNode
  isActive: boolean
  values: Record<string, any>
  onChange: (fieldId: string, value: any) => void
  onSelect: () => void
  glowColor: string
}

function getIcon(iconName: string) {
  const icons = LucideIcons as unknown as Record<string, React.ComponentType<{ className?: string; style?: React.CSSProperties }>>
  return icons[iconName] || LucideIcons.Circle
}

function getFieldPreview(field: FieldConfig, value: any): string {
  if (field.type === 'toggle') return value ? 'ON' : 'OFF'
  if (field.type === 'dropdown') return value || field.defaultValue || field.options?.[0] || '-'
  if (field.type === 'slider') {
    const val = value ?? field.defaultValue ?? field.min ?? 0
    return `${Math.round(val)}${field.unit || ''}`
  }
  return value || field.defaultValue || '-'
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
              {miniNode.fields?.map((field) => {
                const value = values[field.id] ?? field.defaultValue
                
                switch (field.type) {
                  case 'toggle':
                    return (
                      <ToggleRow
                        key={field.id}
                        label={field.label}
                        value={value ?? false}
                        onChange={(v) => onChange(field.id, v)}
                        glowColor={glowColor}
                      />
                    )
                  case 'dropdown':
                    return (
                      <DeviceRow
                        key={field.id}
                        label={field.label}
                        options={field.options || []}
                        value={value || field.options?.[0] || ''}
                        onChange={(v) => onChange(field.id, v)}
                        glowColor={glowColor}
                      />
                    )
                  case 'slider':
                    return (
                      <CompactSlider
                        key={field.id}
                        label={field.label}
                        value={value ?? field.min ?? 0}
                        min={field.min ?? 0}
                        max={field.max ?? 100}
                        step={field.step}
                        unit={field.unit}
                        onChange={(v) => onChange(field.id, v)}
                        glowColor={glowColor}
                      />
                    )
                  case 'custom':
                    return null // Handle custom separately
                  default:
                    return null
                }
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
