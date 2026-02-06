"use client"

import { useCallback, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import * as LucideIcons from "lucide-react"
import type { MiniNode, FieldConfig } from "@/types/navigation"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { useAudioDevices } from "@/hooks/useAudioDevices"
import { MenuWindowSlider } from "./menu-window-slider"
import { ThemeSwitcherCard } from "./theme-switcher-card"

interface MiniNodeStackProps {
  miniNodes: MiniNode[]
}

function getIcon(iconName: string) {
  const icons = LucideIcons as unknown as Record<string, React.ComponentType<{ className?: string; style?: React.CSSProperties }>>
  return icons[iconName] || LucideIcons.Circle
}

function getFieldPreview(field: FieldConfig, value: any, dynamicOptions?: string[]): string {
  if (field.type === 'toggle') return value ? 'ON' : 'OFF'
  if (field.type === 'dropdown') {
    const options = dynamicOptions || field.options || []
    return value || field.defaultValue || options[0] || '-'
  }
  if (field.type === 'slider') {
    const val = value ?? field.defaultValue ?? field.min ?? 0
    return `${Math.round(val)}${field.unit || ''}`
  }
  return value || field.defaultValue || '-'
}

// Dropdown component - now with 2x2 toggle tabs interface
function DropdownControl({
  field,
  value,
  onChange,
  glowColor,
  dynamicOptions,
}: {
  field: FieldConfig
  value: any
  onChange: (v: any) => void
  glowColor: string
  dynamicOptions?: string[]
}) {
  const options = dynamicOptions || field.options || []
  const selectedValue = value ?? field.defaultValue ?? options[0] ?? ''
  const hasMore = options.length > 6
  const visibleOptions = options.slice(0, 6)

  return (
    <div className="py-1">
      {/* 3x2 Grid container - 6 options with white separators */}
      <div 
        className="grid grid-cols-3 rounded overflow-hidden"
        style={{ 
          background: 'rgba(255,255,255,0.25)',
          gap: '1px'
        }}
      >
        {visibleOptions.map((option, idx) => {
          const isSelected = option === selectedValue
          return (
            <motion.button
              key={`${option}-${idx}`}
              onClick={(e) => {
                e.stopPropagation()
                onChange(option)
              }}
              className="px-2 py-1.5 text-[9px] leading-tight transition-all text-left flex items-center font-medium"
              style={{
                background: isSelected ? glowColor : 'rgba(0,0,0,0.4)',
                color: isSelected ? '#000' : '#fff',
                boxShadow: isSelected ? `inset 0 0 8px ${glowColor}80` : 'none',
                minHeight: '32px'
              }}
              whileTap={{ scale: 0.95 }}
              title={option}
            >
              <span className="truncate block w-full">{option}</span>
            </motion.button>
          )
        })}
      </div>
      
      {hasMore && (
        <div className="text-[8px] text-center mt-1.5 font-medium" style={{ color: '#fff' }}>
          +{options.length - 6} more options
        </div>
      )}
    </div>
  )
}

function InlineRow({
  miniNode,
  isActive,
  values,
  onChange,
  onSelect,
  glowColor,
  dynamicOptions,
}: {
  miniNode: MiniNode
  isActive: boolean
  values: Record<string, any>
  onChange: (fieldId: string, value: any) => void
  onSelect: () => void
  glowColor: string
  dynamicOptions?: string[]
}) {
  const IconComponent = getIcon(miniNode.icon)
  const previewField = miniNode.fields?.[0]
  const previewValue = previewField ? getFieldPreview(previewField, values[previewField.id], dynamicOptions) : ''

  const handleClick = useCallback(() => {
    onSelect()
  }, [onSelect])

  const getExpandedHeight = () => {
    if (!previewField) return 70
    switch (previewField.type) {
      case 'toggle': return 60
      case 'dropdown': return 110
      case 'slider': return 80
      default: return 70
    }
  }

  return (
    <motion.div
      className="rounded-md overflow-hidden"
      style={{
        background: isActive
          ? `linear-gradient(90deg, ${glowColor.replace(')', ', 0.12)')}, transparent), url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.15' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`
          : 'rgba(255,255,255,0.04)',
        backgroundBlendMode: isActive ? 'overlay' : 'normal',
        border: `1px solid ${isActive ? glowColor.replace(')', ', 0.25)') : 'rgba(255,255,255,0.08)'}`,
      }}
      animate={{ height: isActive ? getExpandedHeight() : 28 }}
      transition={{ type: "spring", stiffness: 400, damping: 35 }}
    >
      <motion.button
        onClick={handleClick}
        className="w-full flex items-center justify-between px-3 h-8"
        whileHover={{ backgroundColor: isActive ? 'transparent' : 'rgba(255,255,255,0.06)' }}
        whileTap={{ scale: 0.98 }}
      >
        <div className="flex items-center justify-center gap-2 overflow-hidden flex-1">
          <IconComponent 
            className="w-3.5 h-3.5 flex-shrink-0" 
            style={{ color: isActive ? glowColor : `${glowColor}aa` }}
          />
          <span 
            className="text-[11px] font-medium tracking-wide truncate"
            style={{ color: isActive ? '#fff' : '#ffffffaa' }}
          >
            {miniNode.label}
          </span>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <span 
            className="text-[10px] tabular-nums"
            style={{ color: '#fff' }}
          >
            {previewValue}
          </span>
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
              {renderCompactControl(previewField, values[previewField.id], (v) => onChange(previewField.id, v), glowColor, dynamicOptions)}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

function renderCompactControl(field: FieldConfig, value: any, onChange: (v: any) => void, glowColor: string, dynamicOptions?: string[]) {
  switch (field.type) {
    case 'toggle':
      return (
        <div className="flex items-center justify-center py-1">
          <motion.button
            onClick={(e) => {
              e.stopPropagation()
              onChange(!value)
            }}
            className="relative w-10 h-5 rounded-full"
            style={{ backgroundColor: value ? glowColor : 'rgba(255, 255, 255, 0.15)' }}
            whileTap={{ scale: 0.95 }}
          >
            <motion.span
              className="absolute top-0.5 w-4 h-4 rounded-full bg-white"
              animate={{ left: value ? '21px' : '3px' }}
              transition={{ type: "spring", stiffness: 500, damping: 30 }}
            />
          </motion.button>
        </div>
      )

    case 'dropdown':
      return (
        <DropdownControl
          field={field}
          value={value}
          onChange={onChange}
          glowColor={glowColor}
          dynamicOptions={dynamicOptions}
        />
      )

    case 'slider':
      const min = field.min ?? 0
      const max = field.max ?? 100
      const currentValue = value ?? min
      const percentage = ((currentValue - min) / (max - min)) * 100
      return (
        <div className="py-1">
          <div className="flex items-center justify-center mb-2">
            <span className="text-[11px] tabular-nums font-bold px-2 py-0.5 rounded" 
              style={{ 
                color: '#000', 
                background: glowColor,
                boxShadow: `0 0 8px ${glowColor}60`
              }}
            >
              {Math.round(currentValue)}{field.unit || ''}
            </span>
          </div>
          
          {/* Tick marks */}
          <div className="flex justify-between px-1 mb-1">
            {[0, 25, 50, 75, 100].map((tick) => (
              <div 
                key={tick}
                className="w-0.5 h-1 rounded-full"
                style={{ 
                  background: currentValue >= tick ? glowColor : 'rgba(255,255,255,0.3)',
                  opacity: currentValue >= tick ? 1 : 0.5
                }}
              />
            ))}
          </div>
          
          <div
            className="relative h-3 bg-white/30 rounded-full cursor-pointer overflow-visible border border-white/20"
            onClick={(e) => {
              e.stopPropagation()
              const rect = e.currentTarget.getBoundingClientRect()
              const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
              const newValue = min + pct * (max - min)
              onChange(Math.round(newValue))
            }}
          >
            {/* Filled portion with gradient */}
            <motion.div
              className="absolute left-0 top-0 h-full rounded-full"
              style={{ 
                width: `${percentage}%`, 
                background: `linear-gradient(90deg, ${glowColor}88, ${glowColor})`,
                boxShadow: `inset 0 0 10px ${glowColor}40`
              }}
            />
            {/* Handle/knob */}
            <motion.div
              className="absolute top-1/2 w-4 h-4 rounded-full border-2 flex items-center justify-center"
              style={{ 
                left: `calc(${percentage}% - 8px)`,
                transform: 'translateY(-50%)',
                background: '#fff',
                borderColor: glowColor,
                boxShadow: `0 0 12px ${glowColor}, 0 2px 4px rgba(0,0,0,0.3)`
              }}
            >
              <div 
                className="w-1.5 h-1.5 rounded-full" 
                style={{ background: glowColor }}
              />
            </motion.div>
          </div>
          
          {/* Min/Max labels */}
          <div className="flex justify-between mt-1 px-0.5">
            <span className="text-[6px]" style={{ color: 'rgba(255,255,255,0.5)' }}>{min}</span>
            <span className="text-[6px]" style={{ color: 'rgba(255,255,255,0.5)' }}>{max}</span>
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
  
  const { inputDevices, outputDevices, isLoading: devicesLoading } = useAudioDevices()
  
  const {
    state,
    updateMiniNodeValue,
    jumpToMiniNode,
  } = useNavigation()

  const { activeMiniNodeIndex, miniNodeValues } = state
  const visibleNodes = miniNodes.slice(0, 4)

  // Check if we're in the theme subnode
  const isThemeSubnode = state.selectedSub === 'theme'

  const handleValueChange = useCallback(
    (nodeId: string, fieldId: string, value: any) => {
      updateMiniNodeValue(nodeId, fieldId, value)
      
      // Handle voice engine toggle
      if (fieldId === 'voice_engine') {
        const endpoint = value ? '/api/voice/start' : '/api/voice/stop'
        fetch(`http://localhost:8000${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' }
        }).catch(() => {
          // Silently ignore voice API errors - backend may not be running
        })
      }
    },
    [updateMiniNodeValue]
  )

  const handleCardClick = useCallback(
    (index: number) => {
      jumpToMiniNode(index)
    },
    [jumpToMiniNode]
  )
  
  const getDynamicOptions = (miniNode: MiniNode): string[] | undefined => {
    const field = miniNode.fields?.[0]
    if (!field) return undefined
    
    if (field.id === 'input_device' || field.id.includes('input')) {
      return inputDevices.length > 0 ? inputDevices : undefined
    }
    
    if (field.id === 'output_device' || field.id.includes('output')) {
      return outputDevices.length > 0 ? outputDevices : undefined
    }
    
    return undefined
  }

  if (miniNodes.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex items-center justify-center h-32 text-white/40 text-xs"
        style={{ width: 200 }}
      >
        No settings
      </motion.div>
    )
  }

  // For theme subnode, show the ThemeSwitcherCard instead of accordion cards
  if (isThemeSubnode) {
    return (
      <div style={{ width: 200 }}>
        <ThemeSwitcherCard />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2" style={{ width: 200 }}>
      <AnimatePresence mode="popLayout">
        {visibleNodes.map((miniNode, index) => {
          const isActive = index === activeMiniNodeIndex
          const dynamicOptions = getDynamicOptions(miniNode)
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
                dynamicOptions={dynamicOptions}
              />
            </motion.div>
          )
        })}
      </AnimatePresence>

      <div 
        className="mt-3 flex justify-center"
        style={{ width: 200 }}
      >
        <MenuWindowSlider 
          onUnlock={() => window.open('/menu-window', '_blank')}
          isOpen={false}
          onClose={() => {}}
        />
      </div>
    </div>
  )
}
