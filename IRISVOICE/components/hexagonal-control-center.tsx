"use client"

import { useCallback, useMemo } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { HexagonalNode } from "@/components/iris/prism-node"
import { useAnimationConfig } from "@/hooks/useAnimationConfig"
import { useReducedMotion } from "@/hooks/useReducedMotion"
import { Mic, Settings, Zap, Shield, Palette, BarChart3 } from "lucide-react"

import { MAIN_CATEGORY_IDS, SUB_NODE_IDS } from "@/data/navigation-ids"

// Main node configuration with icons
const MAIN_NODES = [
  { id: MAIN_CATEGORY_IDS.VOICE, label: "Voice", icon: Mic },
  { id: MAIN_CATEGORY_IDS.AGENT, label: "Agent", icon: Settings },
  { id: MAIN_CATEGORY_IDS.AUTOMATE, label: "Automate", icon: Zap },
  { id: MAIN_CATEGORY_IDS.SYSTEM, label: "System", icon: Shield },
  { id: MAIN_CATEGORY_IDS.CUSTOMIZE, label: "Customize", icon: Palette },
  { id: MAIN_CATEGORY_IDS.MONITOR, label: "Monitor", icon: BarChart3 },
]

// Sub-node configurations - using lowercase-kebab-case IDs from navigation-ids.ts
const SUB_NODES: Record<string, { id: string; label: string }[]> = {
  [MAIN_CATEGORY_IDS.VOICE]: [
    { id: SUB_NODE_IDS.VOICE_INPUT, label: "Input" },
    { id: SUB_NODE_IDS.VOICE_OUTPUT, label: "Output" },
    { id: SUB_NODE_IDS.VOICE_PROCESSING, label: "Processing" },
    { id: SUB_NODE_IDS.VOICE_MODEL, label: "Model" },
  ],
  [MAIN_CATEGORY_IDS.AGENT]: [
    { id: SUB_NODE_IDS.AGENT_IDENTITY, label: "Identity" },
    { id: SUB_NODE_IDS.AGENT_WAKE, label: "Wake" },
    { id: SUB_NODE_IDS.AGENT_SPEECH, label: "Speech" },
    { id: SUB_NODE_IDS.AGENT_MEMORY, label: "Memory" },
  ],
  [MAIN_CATEGORY_IDS.AUTOMATE]: [
    { id: SUB_NODE_IDS.AUTOMATE_TOOLS, label: "Tools" },
    { id: SUB_NODE_IDS.AUTOMATE_VISION, label: "Vision" },
    { id: SUB_NODE_IDS.AUTOMATE_WORKFLOWS, label: "Workflows" },
    { id: SUB_NODE_IDS.AUTOMATE_SHORTCUTS, label: "Shortcuts" },
    { id: SUB_NODE_IDS.AUTOMATE_GUI, label: "GUI" },
  ],
  [MAIN_CATEGORY_IDS.SYSTEM]: [
    { id: SUB_NODE_IDS.SYSTEM_POWER, label: "Power" },
    { id: SUB_NODE_IDS.SYSTEM_DISPLAY, label: "Display" },
    { id: SUB_NODE_IDS.SYSTEM_STORAGE, label: "Storage" },
    { id: SUB_NODE_IDS.SYSTEM_NETWORK, label: "Network" },
  ],
  [MAIN_CATEGORY_IDS.CUSTOMIZE]: [
    { id: SUB_NODE_IDS.CUSTOMIZE_THEME, label: "Theme" },
    { id: SUB_NODE_IDS.CUSTOMIZE_STARTUP, label: "Startup" },
    { id: SUB_NODE_IDS.CUSTOMIZE_BEHAVIOR, label: "Behavior" },
    { id: SUB_NODE_IDS.CUSTOMIZE_NOTIFICATIONS, label: "Notifications" },
  ],
  [MAIN_CATEGORY_IDS.MONITOR]: [
    { id: SUB_NODE_IDS.MONITOR_ANALYTICS, label: "Analytics" },
    { id: SUB_NODE_IDS.MONITOR_LOGS, label: "Logs" },
    { id: SUB_NODE_IDS.MONITOR_DIAGNOSTICS, label: "Diagnostics" },
    { id: SUB_NODE_IDS.MONITOR_UPDATES, label: "Updates" },
  ],
}

// Node positioning angles (6 nodes in a hexagonal pattern)
const MAIN_NODE_ANGLES = [-90, -30, 30, 90, 150, 210]
const SUB_NODE_ANGLES = [-90, 0, 90, 180]

export default function HexagonalControlCenter() {
  const nav = useNavigation()
  const { theme } = useBrandColor()
  const animConfig = useAnimationConfig()
  const reducedMotion = useReducedMotion()

  const handleNodeClick = useCallback((nodeId: string) => {
    if (nav.state.level === 2) {
      nav.handleSelectMain(nodeId)
    } else if (nav.state.level === 3) {
      nav.handleSelectSub(nodeId, [])
    }
  }, [nav])

  // Get current level configuration
  const levelConfig = useMemo(() => {
    switch (nav.state.level) {
      case 1:
        return { orbRadius: 0, nodeSize: 0, showNodes: false }
      case 2:
        return { orbRadius: 160, nodeSize: 90, showNodes: true }
      case 3:
        return { orbRadius: 140, nodeSize: 90, showNodes: true }
      case 4:
        return { orbRadius: 260, nodeSize: 180, showNodes: true }
      default:
        return { orbRadius: 0, nodeSize: 0, showNodes: false }
    }
  }, [nav.state.level])

  // Get current nodes to display
  const currentNodes = useMemo(() => {
    if (nav.state.level === 2) {
      return MAIN_NODES.map((node, index) => ({
        ...node,
        angle: MAIN_NODE_ANGLES[index] || 0,
        isActive: nav.state.selectedMain === node.id,
        isAnchor: false,
      }))
    } else if (nav.state.level === 3 && nav.state.selectedMain) {
      const subNodes = (nav.subnodes[nav.state.selectedMain]?.length > 0) 
        ? nav.subnodes[nav.state.selectedMain] 
        : (SUB_NODES[nav.state.selectedMain] || [])
      return subNodes.map((node: { id: string; label: string }, index: number) => ({
        ...node,
        icon: Settings, // Default icon for sub-nodes
        angle: SUB_NODE_ANGLES[index] || 0,
        isActive: nav.state.selectedSub === node.id,
        isAnchor: false,
      }))
    }
    return []
  }, [nav.state.level, nav.state.selectedMain, nav.state.selectedSub, nav.subnodes])

  // Liquid line for level 4
  const showLiquidLine = nav.state.level === 4 && nav.state.selectedSub !== null
  const liquidLineAngle = useMemo(() => {
    if (!nav.state.selectedSub || !nav.state.selectedMain) return 0
    const nodes = nav.subnodes[nav.state.selectedMain] || []
    const index = nodes.findIndex((n: { id: string; label: string }) => n.id === nav.state.selectedSub)
    return SUB_NODE_ANGLES[index] || 0
  }, [nav.state.selectedSub, nav.state.selectedMain, nav.subnodes])

  if (!levelConfig.showNodes) {
    return null
  }

  return (
    <div className="absolute inset-0 pointer-events-none">
      <AnimatePresence>
        {currentNodes.map((node, index) => (
          <HexagonalNode
            key={node.id}
            node={node}
            angle={node.angle}
            radius={levelConfig.orbRadius}
            nodeSize={levelConfig.nodeSize}
            onClick={() => handleNodeClick(node.id)}
            spinRotations={animConfig.rotations}
            spinDuration={animConfig.durations.entry}
            staggerIndex={index}
            isCollapsing={false}
            isActive={node.isActive}
            spinConfig={{ staggerDelay: animConfig.durations.stagger, ease: animConfig.easing }}
            isChatActive={false}
          />
        ))}
      </AnimatePresence>

      {/* Liquid line for level 4 */}
      {showLiquidLine && (
        <motion.div
          className="absolute left-1/2 top-1/2 w-1 bg-gradient-to-b from-transparent via-cyan-400 to-transparent"
          style={{
            height: levelConfig.orbRadius * 2,
            transformOrigin: 'center',
            transform: `translate(-50%, -50%) rotate(${liquidLineAngle}deg)`,
          }}
          initial={{ scaleY: 0 }}
          animate={{ scaleY: 1 }}
          exit={{ scaleY: 0 }}
          transition={{ duration: 0.3 }}
        />
      )}
    </div>
  )
}