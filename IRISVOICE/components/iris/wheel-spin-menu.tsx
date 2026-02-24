"use client"

import React, { useRef, useState, useEffect, useCallback } from "react"
import { motion, AnimatePresence, useMotionValue, useTransform, animate, type PanInfo } from "framer-motion"
import * as LucideIcons from "lucide-react"
import type { MiniNode } from "@/types/navigation"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { useReducedMotion } from "@/hooks/useReducedMotion"

interface WheelSpinMenuProps {
  miniNodes: MiniNode[]
  activeIndex: number
  onSelect: (index: number) => void
  onItemClick: (miniNode: MiniNode) => void
  values: Record<string, Record<string, any>>
}

// Get icon component from string name
function getIcon(iconName: string) {
  const icons = LucideIcons as unknown as Record<string, React.ComponentType<{ className?: string; style?: React.CSSProperties }>>
  return icons[iconName] || LucideIcons.Circle
}

// Get preview value for a mini node
function getNodePreview(miniNode: MiniNode, nodeValues: Record<string, any>): string {
  const field = miniNode.fields?.[0]
  if (!field) return ""
  
  const value = nodeValues?.[field.id]
  
  switch (field.type) {
    case "toggle":
      return value ? "ON" : "OFF"
    case "dropdown":
      return value || field.defaultValue || field.options?.[0] || "-"
    case "slider":
      const val = value ?? field.defaultValue ?? field.min ?? 0
      return `${Math.round(val)}${field.unit || ""}`
    default:
      return value || field.defaultValue || "-"
  }
}

export function WheelSpinMenu({ 
  miniNodes, 
  activeIndex, 
  onSelect, 
  onItemClick,
  values 
}: WheelSpinMenuProps) {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColor = theme.glow.color
  const prefersReducedMotion = useReducedMotion()
  
  const containerRef = useRef<HTMLDivElement>(null)
  const rotation = useMotionValue(0)
  const prevAngleRef = useRef<number | null>(null)
  
  const itemCount = miniNodes.length
  const angleStep = 360 / Math.max(itemCount, 1)
  const radius = 140 // Distance from center to items
  
  // Compute fractional progress for center arc (0-1 towards next category)
  const fractional = useTransform(rotation, (r) => {
    const normalized = ((r % 360) + 360) % 360
    return (normalized / angleStep) % 1
  })
  
  const arcCircumference = 2 * Math.PI * 50 // For r=50 in SVG
  const arcOffset = useTransform(fractional, (f) => arcCircumference * (1 - f))
  
  // Update active index based on rotation
  useEffect(() => {
    const updateIndex = (latest: number) => {
      const normalized = ((latest % 360) + 360) % 360
      const index = Math.floor(normalized / angleStep) % itemCount
      if (index !== activeIndex) {
        onSelect(index)
      }
    }
    
    updateIndex(rotation.get())
    return rotation.on("change", updateIndex)
  }, [rotation, angleStep, itemCount, activeIndex, onSelect])
  
  // Handle pan start - calculate initial angle
  const handlePanStart = useCallback((_: unknown, info: PanInfo) => {
    if (!containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const centerX = rect.left + rect.width / 2
    const centerY = rect.top + rect.height / 2
    const angle = Math.atan2(info.point.y - centerY, info.point.x - centerX) * (180 / Math.PI)
    prevAngleRef.current = angle
  }, [])
  
  // Handle pan - rotate based on drag
  const handlePan = useCallback((_: unknown, info: PanInfo) => {
    if (!containerRef.current || prevAngleRef.current === null) return
    const rect = containerRef.current.getBoundingClientRect()
    const centerX = rect.left + rect.width / 2
    const centerY = rect.top + rect.height / 2
    const angle = Math.atan2(info.point.y - centerY, info.point.x - centerX) * (180 / Math.PI)
    const delta = angle - prevAngleRef.current
    rotation.set(rotation.get() + delta)
    prevAngleRef.current = angle
  }, [rotation])
  
  // Handle pan end - snap to nearest item
  const handlePanEnd = useCallback(() => {
    prevAngleRef.current = null
    const current = rotation.get()
    const normalized = ((current % 360) + 360) % 360
    const nearest = Math.round(normalized / angleStep) * angleStep
    const target = current - normalized + nearest
    
    if (prefersReducedMotion) {
      rotation.set(target)
    } else {
      animate(rotation, target, { 
        type: "spring", 
        stiffness: 200, 
        damping: 30 
      })
    }
  }, [rotation, angleStep, prefersReducedMotion])
  
  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        e.preventDefault()
        const newIndex = (activeIndex + 1) % itemCount
        const targetRotation = newIndex * angleStep
        if (prefersReducedMotion) {
          rotation.set(targetRotation)
        } else {
          animate(rotation, targetRotation, { 
            type: "spring", 
            stiffness: 200, 
            damping: 30 
          })
        }
        onSelect(newIndex)
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        e.preventDefault()
        const newIndex = activeIndex === 0 ? itemCount - 1 : activeIndex - 1
        const targetRotation = newIndex * angleStep
        if (prefersReducedMotion) {
          rotation.set(targetRotation)
        } else {
          animate(rotation, targetRotation, { 
            type: "spring", 
            stiffness: 200, 
            damping: 30 
          })
        }
        onSelect(newIndex)
      } else if (e.key === "Enter") {
        e.preventDefault()
        onItemClick(miniNodes[activeIndex])
      }
    }
    
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [activeIndex, itemCount, angleStep, miniNodes, onSelect, onItemClick, rotation, prefersReducedMotion])
  
  const currentNode = miniNodes[activeIndex]
  
  // Reduced motion fallback - simple list view
  if (prefersReducedMotion) {
    return (
      <div className="w-96 h-96 flex flex-col items-center justify-center gap-2">
        <div className="text-white/60 text-sm mb-2">Select a setting:</div>
        {miniNodes.map((node, index) => {
          const IconComponent = getIcon(node.icon)
          const isActive = index === activeIndex
          return (
            <button
              key={node.id}
              onClick={() => {
                onSelect(index)
                onItemClick(node)
              }}
              className={`w-48 px-4 py-2 rounded-lg text-left flex items-center gap-2 transition-colors ${
                isActive ? "bg-white/20" : "bg-white/5 hover:bg-white/10"
              }`}
              style={{ border: `1px solid ${isActive ? glowColor : "rgba(255,255,255,0.1)"}` }}
            >
              <IconComponent className="w-4 h-4" style={{ color: isActive ? glowColor : "rgba(255,255,255,0.6)" }} />
              <span className="text-sm text-white">{node.label}</span>
            </button>
          )
        })}
      </div>
    )
  }
  
  return (
    <motion.div
      ref={containerRef}
      className="relative w-96 h-96 cursor-grab active:cursor-grabbing"
      onPanStart={handlePanStart}
      onPan={handlePan}
      onPanEnd={handlePanEnd}
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      exit={{ scale: 0, opacity: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      style={{
        rotate: useTransform(rotation, (r) => `${r}deg`),
      }}
    >
      {/* Center circle with name + progress arc */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="relative">
          <svg width="120" height="120" viewBox="0 0 120 120" className="rotate-[-90deg]">
            {/* Background circle */}
            <circle 
              cx="60" 
              cy="60" 
              r="50" 
              fill="rgba(255,255,255,0.05)" 
              stroke="rgba(255,255,255,0.1)" 
              strokeWidth="4" 
            />
            {/* Progress arc */}
            <motion.circle
              cx="60"
              cy="60"
              r="50"
              fill="none"
              stroke={glowColor}
              strokeWidth="6"
              strokeDasharray={arcCircumference}
              strokeDashoffset={arcOffset}
              strokeLinecap="round"
            />
          </svg>
          {/* Center label */}
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-4">
            <span className="text-white text-lg font-bold truncate max-w-[80px]">
              {currentNode?.label || "Select"}
            </span>
            <span className="text-white/60 text-xs mt-1">
              {getNodePreview(currentNode, values[currentNode?.id] || {})}
            </span>
          </div>
        </div>
      </div>
      
      {/* Radial items */}
      <AnimatePresence mode="wait">
        {miniNodes.map((node, index) => {
          const angle = (index / Math.max(itemCount, 1)) * 360
          const isActive = index === activeIndex
          const IconComponent = getIcon(node.icon)
          
          return (
            <motion.div
              key={node.id}
              className="absolute top-1/2 left-1/2 pointer-events-auto"
              style={{
                rotate: `${angle}deg`,
                translateX: "-50%",
                translateY: "-50%",
              }}
              initial={{ opacity: 0, scale: 0 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0 }}
              transition={{ 
                duration: 0.3, 
                delay: index * 0.04, 
                type: "spring",
                stiffness: 200,
                damping: 20
              }}
            >
              {/* Position the item outward from center */}
              <div
                style={{
                  transform: `translateY(-${radius}px) rotate(-${angle}deg)`,
                }}
              >
                <motion.button
                  onClick={(e) => {
                    e.stopPropagation()
                    // Rotate to this item
                    const targetRotation = index * angleStep
                    animate(rotation, targetRotation, { 
                      type: "spring", 
                      stiffness: 200, 
                      damping: 30 
                    })
                    onSelect(index)
                    onItemClick(node)
                  }}
                  className="flex flex-col items-center gap-1 p-2 rounded-xl transition-all"
                  style={{
                    background: isActive 
                      ? `linear-gradient(135deg, ${glowColor}30, ${glowColor}10)` 
                      : "rgba(255,255,255,0.08)",
                    border: `1px solid ${isActive ? glowColor : "rgba(255,255,255,0.1)"}`,
                    backdropFilter: "blur(12px)",
                    boxShadow: isActive 
                      ? `0 0 20px ${glowColor}40` 
                      : "0 4px 12px rgba(0,0,0,0.2)",
                  }}
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                >
                  <IconComponent 
                    className="w-5 h-5" 
                    style={{ color: isActive ? glowColor : "rgba(255,255,255,0.7)" }} 
                  />
                  <span className="text-[10px] text-white/80 whitespace-nowrap">
                    {node.label}
                  </span>
                </motion.button>
              </div>
            </motion.div>
          )
        })}
      </AnimatePresence>
      
      {/* Drag hint */}
      <motion.div 
        className="absolute bottom-2 left-1/2 -translate-x-1/2 text-white/30 text-xs pointer-events-none"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1 }}
      >
        Drag to spin • Enter to select
      </motion.div>
    </motion.div>
  )
}
