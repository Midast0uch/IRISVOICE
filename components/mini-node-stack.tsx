"use client"

import { useCallback, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import * as LucideIcons from "lucide-react"
import type { MiniNode, FieldConfig } from "@/types/navigation"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"

interface MiniNodeStackProps {
  miniNodes: MiniNode[]
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

function InlineRow({
  miniNode,
  isActive,
  values,
  onChange,
  onSelect,
  glowColor,
}: {
  miniNode: MiniNode
  isActive: boolean
  values: Record<string, any>
  onChange: (fieldId: string, value: any) => void
  onSelect: () => void
  glowColor: string
}) {
  const IconComponent = getIcon(miniNode.icon)
  const previewField = miniNode.fields?.[0]
  const previewValue = previewField ? getFieldPreview(previewField, values[previewField.id]) : ''

  const handleClick = useCallback(() => {
    onSelect()
  }, [onSelect])

  const getExpandedHeight = () => {
    if (!previewField) return 60
    switch (previewField.type) {
      case 'toggle': return 50
      case 'dropdown': return 70
      case 'slider': return 65
      default: return 60
    }
  }

  return (
    <motion.div
      className="rounded-md overflow-hidden"
      style={{
        background: isActive
          ? `linear-gradient(90deg, ${glowColor.replace(')', ', 0.12)')}, transparent)`
          : 'rgba(255,255,255,0.04)',
        border: `1px solid ${isActive ? glowColor.replace(')', ', 0.25)') : 'rgba(255,255,255,0.08)'}`,
      }}
      animate={{ height: isActive ? getExpandedHeight() : 28 }}
      transition={{ type: "spring", stiffness: 400, damping: 35 }}
    >
      <motion.button
        onClick={handleClick}
        className="w-full flex items-center justify-between px-2 h-7"
        whileHover={{ backgroundColor: isActive ? 'transparent' : 'rgba(255,255,255,0.06)' }}
        whileTap={{ scale: 0.98 }}
      >
        <div className="flex items-center gap-1.5 overflow-hidden">
          <IconComponent 
            className="w-3 h-3 flex-shrink-0" 
            style={{ color: isActive ? glowColor : `${glowColor}aa` }}
          />
          <span 
            className="text-[10px] font-medium tracking-wide truncate"
            style={{ color: isActive ? '#fff' : '#ffffffaa' }}
          >
            {miniNode.label}
          </span>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <span 
            className="text-[9px] tabular-nums"
            style={{ color: `${glowColor}cc` }}
          >
            {previewValue}
          </span>
          <motion.div
            animate={{ rotate: isActive ? 90 : 0 }}
            transition={{ duration: 0.2 }}
          >
            <LucideIcons.ChevronRight 
              className="w-3 h-3"
              style={{ color: `${glowColor}88` }}
            />
          </motion.div>
        </div>
      </motion.button>

      <AnimatePresence>
        {isActive && previewField && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="px-2 pb-2"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="pt-1 border-t border-white/10">
              {renderCompactControl(previewField, values[previewField.id], (v) => onChange(previewField.id, v), glowColor)}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

function renderCompactControl(field: FieldConfig, value: any, onChange: (v: any) => void, glowColor: string) {
  switch (field.type) {
    case 'toggle':
      return (
        <div className="flex items-center justify-between py-1">
          <span className="text-[9px]" style={{ color: '#ffffffaa' }}>{field.label}</span>
          <motion.button
            onClick={(e) => {
              e.stopPropagation()
              onChange(!value)
            }}
            className="relative w-8 h-4 rounded-full"
            style={{ backgroundColor: value ? glowColor : 'rgba(255, 255, 255, 0.15)' }}
            whileTap={{ scale: 0.95 }}
          >
            <motion.span
              className="absolute top-0.5 w-3 h-3 rounded-full bg-white"
              animate={{ left: value ? '17px' : '3px' }}
              transition={{ type: "spring", stiffness: 500, damping: 30 }}
            />
          </motion.button>
        </div>
      )

    case 'dropdown':
      const options = field.options || []
      return (
        <div className="py-1">
          <div className="text-[8px] uppercase tracking-wider mb-1" style={{ color: `${glowColor}aa` }}>
            {field.label}
          </div>
          <div className="flex flex-wrap gap-0.5">
            {options.slice(0, 3).map((option) => {
              const isSelected = option === value
              return (
                <motion.button
                  key={option}
                  onClick={(e) => {
                    e.stopPropagation()
                    onChange(option)
                  }}
                  className="px-1.5 py-0.5 rounded text-[9px] transition-all"
                  style={{
                    background: isSelected ? glowColor : 'rgba(255,255,255,0.08)',
                    color: isSelected ? '#000' : '#ffffffaa',
                    border: `1px solid ${isSelected ? glowColor : 'transparent'}`,
                  }}
                  whileTap={{ scale: 0.95 }}
                >
                  {option.slice(0, 8)}
                </motion.button>
              )
            })}
          </div>
        </div>
      )

    case 'slider':
      const min = field.min ?? 0
      const max = field.max ?? 100
      const currentValue = value ?? min
      const percentage = ((currentValue - min) / (max - min)) * 100
      return (
        <div className="py-1">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[8px] uppercase tracking-wider" style={{ color: `${glowColor}aa` }}>
              {field.label}
            </span>
            <span className="text-[9px] tabular-nums" style={{ color: '#ffffffcc' }}>
              {Math.round(currentValue)}{field.unit || ''}
            </span>
          </div>
          <div
            className="relative h-1 bg-white/10 rounded-full cursor-pointer"
            onClick={(e) => {
              e.stopPropagation()
              const rect = e.currentTarget.getBoundingClientRect()
              const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
              const newValue = min + pct * (max - min)
              onChange(Math.round(newValue))
            }}
          >
            <motion.div
              className="absolute left-0 top-0 h-full rounded-full"
              style={{ width: `${percentage}%`, background: glowColor }}
            />
          </div>
        </div>
      )

    default:
      return null
  }
}

export function MiniNodeStack({ miniNodes }: MiniNodeStackProps) {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColor = theme.glow.color
  
  const {
    state,
    updateMiniNodeValue,
    jumpToMiniNode,
  } = useNavigation()

  const { activeMiniNodeIndex, miniNodeValues } = state
  const visibleNodes = miniNodes.slice(0, 4)

  const handleValueChange = useCallback(
    (nodeId: string, fieldId: string, value: any) => {
      updateMiniNodeValue(nodeId, fieldId, value)
    },
    [updateMiniNodeValue]
  )

  const handleCardClick = useCallback(
    (index: number) => {
      jumpToMiniNode(index)
    },
    [jumpToMiniNode]
  )

  if (miniNodes.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex items-center justify-center h-32 text-white/40 text-xs"
        style={{ width: 140 }}
      >
        No settings
      </motion.div>
    )
  }

  return (
    <div className="flex flex-col gap-1" style={{ width: 140 }}>
      <AnimatePresence mode="popLayout">
        {visibleNodes.map((miniNode, index) => {
          const isActive = index === activeMiniNodeIndex
          return (
            <motion.div
              key={miniNode.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 10 }}
              transition={{ duration: 0.2, delay: index * 0.03 }}
            >
              <InlineRow
                miniNode={miniNode}
                isActive={isActive}
                values={miniNodeValues[miniNode.id] || {}}
                onChange={(fieldId, value) => handleValueChange(miniNode.id, fieldId, value)}
                onSelect={() => handleCardClick(index)}
                glowColor={glowColor}
              />
            </motion.div>
          )
        })}
      </AnimatePresence>

      <div 
        className="text-center mt-1 text-[9px] font-medium tracking-wider"
        style={{ color: `${glowColor.replace(')', ', 0.5)')}` }}
      >
        {activeMiniNodeIndex + 1} / {miniNodes.length}
      </div>
    </div>
  )
}
