"use client"

import React, { useEffect, useCallback, useMemo } from "react"
import { useNavigation } from "@/contexts/NavigationContext"
import { useAnimationConfig } from "@/hooks/useAnimationConfig"
import type { NavigationLevel } from "@/types/navigation"

interface LevelConfig {
  orbRadius: number
  nodeSize: number
  orbLabel: string
  orbIcon: 'home' | 'close' | 'back'
  showBackIndicator: boolean
}

const LEVEL_CONFIGS: Record<NavigationLevel, LevelConfig> = {
  1: {
    orbRadius: 0,
    nodeSize: 0,
    orbLabel: 'IRIS',
    orbIcon: 'home',
    showBackIndicator: false,
  },
  2: {
    orbRadius: 200,
    nodeSize: 90,
    orbLabel: 'CLOSE',
    orbIcon: 'close',
    showBackIndicator: true,
  },
  3: {
    orbRadius: 140,
    nodeSize: 90,
    orbLabel: '', // Dynamic - parent node name
    orbIcon: 'back',
    showBackIndicator: true,
  },
  4: {
    orbRadius: 260,
    nodeSize: 180,
    orbLabel: '', // Dynamic - sub-node name
    orbIcon: 'back',
    showBackIndicator: true,
  },
  5: {
    orbRadius: 260,
    nodeSize: 90,
    orbLabel: 'DONE',
    orbIcon: 'back',
    showBackIndicator: true,
  },
}

const MAIN_NODE_ANGLES = [-90, -30, 30, 90, 150, 210]
const SUB_NODE_ANGLES = [-90, 0, 90, 180]

export interface NavigationControllerProps {
  mainNodes: Array<{ id: string; label: string }>
  subNodes: Record<string, Array<{ id: string; label: string }>>
  onLevelChange?: (level: NavigationLevel, direction: 'forward' | 'backward' | null) => void
  onTransitionStart?: () => void
  onTransitionEnd?: () => void
}

export function useNavigationController({
  mainNodes,
  subNodes,
  onLevelChange,
  onTransitionStart,
  onTransitionEnd,
}: NavigationControllerProps) {
  const nav = useNavigation()
  const animConfig = useAnimationConfig()

  useEffect(() => {
    const mainLabels: Record<string, string> = {}
    mainNodes.forEach(node => {
      mainLabels[node.id] = node.label
    })

    const subLabels: Record<string, string> = {}
    Object.values(subNodes).forEach(nodes => {
      nodes.forEach(node => {
        subLabels[node.id] = node.label
      })
    })

    nav.setNodeLabels(mainLabels, subLabels)
  }, [mainNodes, subNodes, nav])

  useEffect(() => {
    if (onLevelChange) {
      onLevelChange(nav.state.level, nav.state.transitionDirection)
    }
  }, [nav.state.level, nav.state.transitionDirection, onLevelChange])

  useEffect(() => {
    if (nav.state.isTransitioning && onTransitionStart) {
      onTransitionStart()
    } else if (!nav.state.isTransitioning && onTransitionEnd) {
      onTransitionEnd()
    }
  }, [nav.state.isTransitioning, onTransitionStart, onTransitionEnd])

  const handleIrisClick = useCallback(() => {
    if (nav.state.isTransitioning) return

    nav.setTransitioning(true)

    const duration = nav.state.level === 1
      ? animConfig.durations.entry
      : animConfig.durations.exit

    if (nav.state.level === 1) {
      nav.expandToMain()
    } else {
      nav.goBack()
    }

    setTimeout(() => {
      nav.setTransitioning(false)
    }, duration)
  }, [nav, animConfig.durations])

  const handleMainNodeClick = useCallback((nodeId: string) => {
    if (nav.state.isTransitioning || nav.state.level !== 2) return

    nav.setTransitioning(true)
    nav.selectMain(nodeId)

    setTimeout(() => {
      nav.setTransitioning(false)
    }, animConfig.durations.entry)
  }, [nav, animConfig.durations.entry])

  const handleSubNodeClick = useCallback((nodeId: string) => {
    if (nav.state.isTransitioning || nav.state.level !== 3) return

    nav.setTransitioning(true)
    nav.selectSub(nodeId)

    setTimeout(() => {
      nav.setTransitioning(false)
    }, animConfig.durations.entry)
  }, [nav, animConfig.durations.entry])

  const handleMiniConfirm = useCallback((nodeId: string) => {
    if (nav.state.isTransitioning || nav.state.level !== 4) return

    nav.setTransitioning(true)
    nav.confirmMini(nodeId)

    setTimeout(() => {
      nav.setTransitioning(false)
    }, animConfig.durations.entry)
  }, [nav, animConfig.durations.entry])

  const levelConfig = LEVEL_CONFIGS[nav.state.level]

  const currentMainNodes = useMemo(() => {
    if (nav.state.level < 2) return []
    return mainNodes.map((node, index) => ({
      ...node,
      angle: MAIN_NODE_ANGLES[index] || 0,
      isActive: nav.state.selectedMain === node.id,
      isAnchor: nav.state.level >= 3 && nav.state.selectedMain === node.id,
    }))
  }, [mainNodes, nav.state.level, nav.state.selectedMain])

  const currentSubNodes = useMemo(() => {
    if (nav.state.level < 3 || !nav.state.selectedMain) return []
    const nodes = subNodes[nav.state.selectedMain] || []
    return nodes.map((node, index) => ({
      ...node,
      angle: SUB_NODE_ANGLES[index] || 0,
      isActive: nav.state.selectedSub === node.id,
    }))
  }, [subNodes, nav.state.level, nav.state.selectedMain, nav.state.selectedSub])

  const showLiquidLine = nav.state.level === 4 && nav.state.selectedSub !== null
  const isLineRetracting = nav.state.transitionDirection === 'backward' && nav.state.level === 3

  const liquidLineAngle = useMemo(() => {
    if (!nav.state.selectedSub || !nav.state.selectedMain) return 0
    const nodes = subNodes[nav.state.selectedMain] || []
    const index = nodes.findIndex(n => n.id === nav.state.selectedSub)
    return SUB_NODE_ANGLES[index] || 0
  }, [nav.state.selectedSub, nav.state.selectedMain, subNodes])

  return {
    level: nav.state.level,
    isTransitioning: nav.state.isTransitioning,
    transitionDirection: nav.state.transitionDirection,
    selectedMain: nav.state.selectedMain,
    selectedSub: nav.state.selectedSub,
    selectedMini: nav.state.selectedMini,

    levelConfig,
    orbState: nav.orbState,
    animConfig,

    currentMainNodes,
    currentSubNodes,

    showLiquidLine,
    isLineRetracting,
    liquidLineAngle,

    handleIrisClick,
    handleMainNodeClick,
    handleSubNodeClick,
    handleMiniConfirm,

    goBack: nav.goBack,
    collapseToIdle: nav.collapseToIdle,
  }
}

export type NavigationControllerReturn = ReturnType<typeof useNavigationController>
