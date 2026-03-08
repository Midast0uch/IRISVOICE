"use client"

import { useCallback, useMemo } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { HexagonalNode } from "@/components/iris/prism-node"
import { useAnimationConfig } from "@/hooks/useAnimationConfig"
import { useReducedMotion } from "@/hooks/useReducedMotion"
import { Mic, Settings, Zap, Shield, Palette, BarChart3 } from "lucide-react"

import { MAIN_CATEGORY_IDS, SECTION_IDS } from "@/data/navigation-ids"
import { getCardsForSection } from "@/data/cards"

// Main node configuration with icons
const MAIN_NODES = [
  { id: MAIN_CATEGORY_IDS.VOICE, label: "Voice", icon: Mic },
  { id: MAIN_CATEGORY_IDS.AGENT, label: "Agent", icon: Settings },
  { id: MAIN_CATEGORY_IDS.AUTOMATE, label: "Automate", icon: Zap },
  { id: MAIN_CATEGORY_IDS.SYSTEM, label: "System", icon: Shield },
  { id: MAIN_CATEGORY_IDS.CUSTOMIZE, label: "Customize", icon: Palette },
  { id: MAIN_CATEGORY_IDS.MONITOR, label: "Monitor", icon: BarChart3 },
]

// Section configurations - using lowercase-kebab-case IDs from navigation-ids.ts
const SECTIONS: Record<string, { id: string; label: string }[]> = {
  [MAIN_CATEGORY_IDS.VOICE]: [
    { id: SECTION_IDS.VOICE_INPUT, label: "Input" },
    { id: SECTION_IDS.VOICE_OUTPUT, label: "Output" },
    { id: SECTION_IDS.VOICE_WAKE, label: "Wake Word" },
    { id: SECTION_IDS.VOICE_SPEECH, label: "Speech" },
  ],
  [MAIN_CATEGORY_IDS.AGENT]: [
    { id: SECTION_IDS.AGENT_MODEL_SELECTION, label: "Models" },
    { id: SECTION_IDS.AGENT_INFERENCE_MODE, label: "Inference" },
    { id: SECTION_IDS.AGENT_IDENTITY, label: "Identity" },
    { id: SECTION_IDS.AGENT_MEMORY, label: "Memory" },
  ],
  [MAIN_CATEGORY_IDS.AUTOMATE]: [
    { id: SECTION_IDS.AUTOMATE_TOOLS, label: "Tools" },
    { id: SECTION_IDS.AUTOMATE_VISION, label: "Vision" },
    { id: SECTION_IDS.AUTOMATE_SKILLS, label: "Skills" },
    { id: SECTION_IDS.AUTOMATE_PROFILE, label: "Profile" },
    { id: SECTION_IDS.AUTOMATE_DESKTOP_CONTROL, label: "Desktop Control" },
  ],
  [MAIN_CATEGORY_IDS.SYSTEM]: [
    { id: SECTION_IDS.SYSTEM_POWER, label: "Power" },
    { id: SECTION_IDS.SYSTEM_DISPLAY, label: "Display" },
    { id: SECTION_IDS.SYSTEM_STORAGE, label: "Storage" },
    { id: SECTION_IDS.SYSTEM_NETWORK, label: "Network" },
  ],
  [MAIN_CATEGORY_IDS.CUSTOMIZE]: [
    { id: SECTION_IDS.CUSTOMIZE_THEME, label: "Theme" },
    { id: SECTION_IDS.CUSTOMIZE_STARTUP, label: "Startup" },
    { id: SECTION_IDS.CUSTOMIZE_BEHAVIOR, label: "Behavior" },
    { id: SECTION_IDS.CUSTOMIZE_NOTIFICATIONS, label: "Notifications" },
  ],
  [MAIN_CATEGORY_IDS.MONITOR]: [
    { id: SECTION_IDS.MONITOR_ANALYTICS, label: "Analytics" },
    { id: SECTION_IDS.MONITOR_LOGS, label: "Logs" },
    { id: SECTION_IDS.MONITOR_DIAGNOSTICS, label: "Diagnostics" },
    { id: SECTION_IDS.MONITOR_UPDATES, label: "Updates" },
  ],
}

// Node positioning angles (6 nodes in a hexagonal pattern)
const MAIN_NODE_ANGLES = [-90, -30, 30, 90, 150, 210]
const SECTION_ANGLES = [-90, 0, 90, 180]

export default function HexagonalControlCenter() {
  const nav = useNavigation()
  const { theme } = useBrandColor()
  const animConfig = useAnimationConfig()
  const reducedMotion = useReducedMotion()

  const handleNodeClick = useCallback((nodeId: string) => {
    if (nav.state.level === 2) {
      nav.handleSelectMain(nodeId)
    } else if (nav.state.level === 3) {
      // Load actual cards for the selected section
      const cards = getCardsForSection(nodeId)
      nav.handleSelectSection(nodeId, cards)
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
      const sections = (nav.sections[nav.state.selectedMain]?.length > 0)
        ? nav.sections[nav.state.selectedMain]
        : (SECTIONS[nav.state.selectedMain] || [])
      return sections.map((node: { id: string; label: string }, index: number) => ({
        ...node,
        icon: Settings, // Default icon for sections
        angle: SECTION_ANGLES[index] || 0,
        isActive: nav.state.selectedSub === node.id,
        isAnchor: false,
      }))
    }
    return []
  }, [nav.state.level, nav.state.selectedMain, nav.state.selectedSub, nav.sections])

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
    </div>
  )
}
