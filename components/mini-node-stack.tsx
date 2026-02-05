"use client"

import { useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import * as LucideIcons from "lucide-react"
import type { MiniNode } from "@/types/navigation"
import { MiniNodeCard } from "./mini-node-card"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"

interface MiniNodeStackProps {
  miniNodes: MiniNode[]
}

// Dynamically get Lucide icon
function getIcon(iconName: string) {
  const icons = LucideIcons as unknown as Record<string, React.ComponentType<{ className?: string; style?: React.CSSProperties }>>
  return icons[iconName] || LucideIcons.Circle
}

export function MiniNodeStack({ miniNodes }: MiniNodeStackProps) {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColor = theme.glow.color
  const isVerdant = theme.orbs === null
  
  const {
    state,
    updateMiniNodeValue,
    confirmMiniNode,
    jumpToMiniNode,
    rotateStackForward,
    rotateStackBackward,
  } = useNavigation()

  const { activeMiniNodeIndex, miniNodeValues } = state

  // Only show up to 4 cards
  const visibleNodes = miniNodes.slice(0, 4)

  const handleValueChange = useCallback(
    (nodeId: string, fieldId: string, value: any) => {
      updateMiniNodeValue(nodeId, fieldId, value)
    },
    [updateMiniNodeValue]
  )

  const handleSave = useCallback(
    (nodeId: string) => {
      const values = miniNodeValues[nodeId] || {}
      confirmMiniNode(nodeId, values)
    },
    [confirmMiniNode, miniNodeValues]
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
        className="flex items-center justify-center h-64 text-white/40"
      >
        No settings available
      </motion.div>
    )
  }

  // Cards stacked on top of each other with small vertical offset (like a deck)
  const containerWidth = 220

  return (
    <div className="relative" style={{ width: containerWidth }}>
      <div 
        className="relative flex items-center justify-center"
        style={{ 
          height: 320,
          width: containerWidth,
        }}
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <AnimatePresence mode="popLayout">
          {visibleNodes.map((miniNode, index) => (
            <motion.div
              key={miniNode.id}
              onClick={(e) => {
                e.stopPropagation()
                handleCardClick(index)
              }}
              onMouseDown={(e) => e.stopPropagation()}
              onPointerDown={(e) => e.stopPropagation()}
              className="cursor-pointer absolute"
              style={{ 
                left: 20, // Centered in container
                top: index * 8, // Small vertical stack offset (8px per card)
                zIndex: index === activeMiniNodeIndex ? 30 : 20 - index,
              }}
              initial={{ 
                opacity: 0, 
                scale: 0.5, 
                x: -100, // Start from center (left offset)
                y: 50 
              }}
              animate={{ 
                opacity: 1, 
                scale: index === activeMiniNodeIndex ? 1.05 : 1, 
                x: 0, 
                y: 0 
              }}
              exit={{ 
                opacity: 0, 
                scale: 0.8, 
                x: -50, // Retract toward center
                y: 30,
                transition: { duration: 0.4 } // 400ms exit
              }}
              transition={{ 
                duration: 0.6, // 600ms entry
                delay: index * 0.1, // Stagger cards
                ease: [0.25, 0.46, 0.45, 0.94] // Smooth easing
              }}
            >
              <MiniNodeCard
                miniNode={miniNode}
                isActive={index === activeMiniNodeIndex}
                values={miniNodeValues[miniNode.id] || {}}
                onChange={(fieldId, value) =>
                  handleValueChange(miniNode.id, fieldId, value)
                }
                onSave={() => handleSave(miniNode.id)}
                index={index}
              />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Navigation Controls - Menu Window Style Slider */}
      <div 
        className="absolute -bottom-20 left-1/2 -translate-x-1/2 z-50"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <div 
          className="flex items-center gap-1 px-3 py-2 rounded-2xl"
          style={{ 
            background: `linear-gradient(135deg, ${glowColor.replace(')', ', 0.15)')}, ${glowColor.replace(')', ', 0.05)')})`,
            backdropFilter: 'blur(12px)',
            border: `1px solid ${glowColor.replace(')', ', 0.2)')}`,
            boxShadow: `0 4px 24px ${glowColor.replace(')', ', 0.15)')}`,
          }}
        >
          {visibleNodes.map((miniNode, index) => {
            const IconComponent = getIcon(miniNode.icon)
            const isActive = index === activeMiniNodeIndex
            
            return (
              <motion.button
                key={miniNode.id}
                onClick={(e) => {
                  e.stopPropagation()
                  handleCardClick(index)
                }}
                onMouseDown={(e) => e.stopPropagation()}
                onPointerDown={(e) => e.stopPropagation()}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                className="relative flex flex-col items-center gap-1 px-3 py-2 rounded-xl transition-all duration-200"
                style={{
                  background: isActive 
                    ? `linear-gradient(135deg, ${glowColor.replace(')', ', 0.3)')}, ${glowColor.replace(')', ', 0.1)')})`
                    : 'transparent',
                  border: isActive 
                    ? `1px solid ${glowColor.replace(')', ', 0.5)')}`
                    : '1px solid transparent',
                }}
              >
                <IconComponent 
                  className="w-4 h-4" 
                  style={{ 
                    color: isActive ? '#ffffff' : `${glowColor.replace(')', ', 0.6)')}`,
                    filter: isActive ? 'drop-shadow(0 0 4px ' + glowColor + ')' : 'none'
                  }} 
                />
                <span 
                  className="text-[9px] font-medium uppercase tracking-wider"
                  style={{ 
                    color: isActive ? '#ffffff' : `${glowColor.replace(')', ', 0.5)')}`,
                  }}
                >
                  {miniNode.label.slice(0, 6)}
                </span>
                
                {/* Active indicator bar */}
                {isActive && (
                  <motion.div
                    layoutId="activeIndicator"
                    className="absolute -bottom-1 w-8 h-0.5 rounded-full"
                    style={{ background: glowColor }}
                    transition={{ type: "spring", stiffness: 300, damping: 30 }}
                  />
                )}
              </motion.button>
            )
          })}
        </div>
        
        {/* Card Counter */}
        <div 
          className="text-center mt-2 text-[10px] font-medium tracking-wider"
          style={{ color: `${glowColor.replace(')', ', 0.6)')}` }}
        >
          {activeMiniNodeIndex + 1} / {miniNodes.length}
        </div>
      </div>
    </div>
  )
}
