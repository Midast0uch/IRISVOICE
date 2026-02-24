"use client"

import { useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import type { MiniNode } from "@/types/navigation"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { useAudioDevices } from "@/hooks/useAudioDevices"
import { MenuWindowSlider } from "./menu-window-slider"
import { ThemeSwitcherCard } from "./theme-switcher-card"
import { CompactAccordion } from "./CompactAccordion"

interface MiniNodeStackProps {
  miniNodes: MiniNode[]
  updateModelConfig?: (config: any) => void
  onUnlock: () => void;
}

export function MiniNodeStack({ miniNodes, updateModelConfig, onUnlock }: MiniNodeStackProps) {
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
      
      // Handle model configuration updates
      if (nodeId === 'audio_model') {
        // Get current model values
        const currentModelValues = miniNodeValues['audio_model'] || {}
        const updatedConfig = {
          ...currentModelValues,
          [fieldId]: value,
        }
        
        updateModelConfig?.(updatedConfig)
      }
    },
    [updateMiniNodeValue, miniNodeValues]
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
        style={{ width: 150 }}
      >
        No settings
      </motion.div>
    )
  }

  // For theme subnode, show the ThemeSwitcherCard instead of accordion cards
  if (isThemeSubnode) {
    return (
      <div style={{ width: 150 }}>
        <ThemeSwitcherCard />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1.5" style={{ width: 150 }}>
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
              <CompactAccordion
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
        className="mt-2 flex justify-center"
        style={{ width: 150 }}
      >
        <MenuWindowSlider 
          onUnlock={onUnlock}
          isOpen={false}
          onClose={() => {}}
        />
      </div>
    </div>
  )
}
