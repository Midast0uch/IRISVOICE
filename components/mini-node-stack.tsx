"use client"

import { useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import type { MiniNode } from "@/types/navigation"
import { MiniNodeCard } from "./mini-node-card"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { ChevronLeft, ChevronRight } from "lucide-react"

interface MiniNodeStackProps {
  miniNodes: MiniNode[]
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

      {/* Navigation Controls */}
      <div 
        className="absolute -bottom-16 left-1/2 -translate-x-1/2 flex items-center gap-4 z-50"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <motion.button
          onClick={(e) => {
            e.stopPropagation()
            rotateStackBackward()
          }}
          onMouseDown={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          whileTap={{ scale: 0.9 }}
          className="w-10 h-10 rounded-full flex items-center justify-center transition-colors pointer-events-auto"
          style={{ 
            backgroundColor: `${glowColor.replace(')', ', 0.1)')}`,
          }}
          whileHover={{ 
            scale: 1.1,
            backgroundColor: `${glowColor.replace(')', ', 0.2)')}`
          }}
        >
          <ChevronLeft className="w-5 h-5" style={{ color: glowColor }} />
        </motion.button>

        <div 
          className="flex items-center gap-2" 
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
        >
          {visibleNodes.map((_, index) => (
            <motion.div
              key={index}
              onClick={(e) => {
                e.stopPropagation()
                handleCardClick(index)
              }}
              onMouseDown={(e) => e.stopPropagation()}
              onPointerDown={(e) => e.stopPropagation()}
              className="w-2 h-2 rounded-full cursor-pointer transition-colors"
              style={{
                backgroundColor: index === activeMiniNodeIndex 
                  ? glowColor 
                  : `${glowColor.replace(')', ', 0.3)')}`
              }}
              whileHover={{ 
                scale: 1.2,
                backgroundColor: index === activeMiniNodeIndex 
                  ? glowColor 
                  : `${glowColor.replace(')', ', 0.5)')}`
              }}
            />
          ))}
        </div>

        <motion.button
          onClick={(e) => {
            e.stopPropagation()
            rotateStackForward()
          }}
          onMouseDown={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          whileTap={{ scale: 0.9 }}
          className="w-10 h-10 rounded-full flex items-center justify-center transition-colors pointer-events-auto"
          style={{ 
            backgroundColor: `${glowColor.replace(')', ', 0.1)')}`,
          }}
          whileHover={{ 
            scale: 1.1,
            backgroundColor: `${glowColor.replace(')', ', 0.2)')}`
          }}
        >
          <ChevronRight className="w-5 h-5" style={{ color: glowColor }} />
        </motion.button>
      </div>

      {/* Card Counter */}
      <div className="absolute -bottom-16 right-0 text-xs" style={{ color: `${glowColor.replace(')', ', 0.4)')}` }}>
        {activeMiniNodeIndex + 1} / {miniNodes.length}
      </div>
    </div>
  )
}
