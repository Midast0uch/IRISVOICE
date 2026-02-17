"use client"

import React, { useState, useCallback, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Mic, MessageSquare } from "lucide-react"
import { getCurrentWindow, PhysicalPosition } from '@tauri-apps/api/window'
import { useIRISWebSocket } from "@/hooks/useIRISWebSocket"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { MiniNodeStack } from "./mini-node-stack"
import { PrismNode } from "./iris/prism-node"
import { MenuWindowSlider } from "./menu-window-slider"
import { DarkGlassDashboard } from "./dark-glass-dashboard"
import { ChatView } from "./chat-view"
import { IrisOrb } from "./iris/IrisOrb"
import { SPIN_CONFIG, SUBMENU_CONFIG, ORBIT_CONFIG, NODE_POSITIONS } from "./iris/config"
import type { ConfirmedMiniNode } from "./iris/types"
import { useIsMobile, getSpiralPosition, startWindowDrag } from "./iris/utils"

const isTauri = typeof window !== "undefined" && (!!(window as any).__TAURI_INTERNALS__ || !!(window as any).__TAURI__)

export default function HexagonalControlCenter() {
  const nav = useNavigation()
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const themeGlowColor = theme.glow.color
  const isMobile = useIsMobile()
  const userNavigatedRef = useRef(false)
  const navLevelRef = useRef(nav.state.level)
  const nodeClickTimestampRef = useRef<number | null>(null)
  const hasUserInteractedRef = useRef(false)

  const [currentView, setCurrentView] = useState<string | null>(null)
  const [pendingView, setPendingView] = useState<string | null>(null)
  const [exitingView, setExitingView] = useState<string | null>(null)
  const [isExpanded, setIsExpanded] = useState(false)
  const [isTransitioning, setIsTransitioning] = useState(false)
  const [activeMiniNodeIndex, setActiveMiniNodeIndex] = useState<number | null>(null)
  const [wakeDetected, setWakeDetected] = useState(false)
  const [dashboardOpen, setDashboardOpen] = useState(false)
  const [wakeFlash, setWakeFlash] = useState(false)
  const [nativeAudioResponse, setNativeAudioResponse] = useState<string | null>(null)
  const [irisCallbacks, setIrisCallbacks] = useState<{ handleWakeDetected: () => void; handleNativeAudioResponse: (payload: any) => void } | null>(null)
  const [isChatActive, setIsChatActive] = useState(false)
  const [hintText, setHintText] = useState<string | React.ReactNode>("Tap IRIS to expand")

  const handleOpenDashboard = useCallback(() => {
    setDashboardOpen(true)
  }, [])

  const handleCloseDashboard = useCallback(() => {
    setDashboardOpen(false)
  }, [])

  const handleToggleChat = useCallback(() => {
    setIsChatActive(prev => !prev)
  }, [])

  const handleCloseChat = useCallback(() => {
    setIsChatActive(false)
  }, [])

  const handleUpdateField = (subnodeId: string, fieldId: string, value: any) => {
    // This is a placeholder for the actual implementation
    console.log(`Updating field: ${subnodeId}.${fieldId} = ${value}`)
  }

  const handleWakeDetected = useCallback(() => {
    console.log("[HexagonalControlCenter] Wake word detected")
    setWakeDetected(true)
    setWakeFlash(true)
    setTimeout(() => setWakeDetected(false), 2000)
    setTimeout(() => setWakeFlash(false), 500)
    
    // Call the IrisOrb callback if available
    if (irisCallbacks?.handleWakeDetected) {
      irisCallbacks.handleWakeDetected()
    }
  }, [irisCallbacks])

  const handleNativeAudioResponse = useCallback((payload: any) => {
    console.log("[HexagonalControlCenter] Native audio response received:", payload)
    if (payload.debug_text) {
      setNativeAudioResponse(payload.debug_text)
      // Clear the response after a few seconds
      setTimeout(() => setNativeAudioResponse(null), 5000)
    }
    
    // Call the IrisOrb callback if available
    if (irisCallbacks?.handleNativeAudioResponse) {
      irisCallbacks.handleNativeAudioResponse(payload)
    }
  }, [irisCallbacks])

  const {
    confirmedNodes: wsConfirmedNodes,
    currentCategory,
    currentSubnode,
    voiceState,
    fieldValues,
    subnodes,
    updateField,
    selectCategory,
    selectSubnode,
    confirmMiniNode,
    sendMessage,
  } = useIRISWebSocket("ws://localhost:8000/ws/iris", true, handleWakeDetected, handleNativeAudioResponse)

  const updateModelConfig = (config: any) => {
    sendMessage(JSON.stringify({
      type: "update_model_config",
      config: config,
    }));
  };

  useEffect(() => {
    navLevelRef.current = nav.state.level
  }, [nav.state.level])

  useEffect(() => {
    const textCycle: (string | React.ReactNode)[] = [
      "Tap iris for menu",
      <span key="mic" className="flex items-center justify-center gap-1.5"><Mic size={12} /> Double-tap for 🎤</span>,
      <span key="chat" className="flex items-center justify-center gap-1.5"><MessageSquare size={12} /> Tap here for 💬</span>
    ];
    let currentIndex = 0;
    const interval = setInterval(() => {
      currentIndex = (currentIndex + 1) % textCycle.length;
      setHintText(textCycle[currentIndex]);
    }, 3000); // Change text every 3 seconds

    return () => clearInterval(interval);
  }, []);

  // Ensure window starts interactive (solid, not click-through) - Tauri only
  useEffect(() => {
    if (!isTauri) return

    const setupWindow = async () => {
      const appWindow = await getCurrentWindow()
      await appWindow.setIgnoreCursorEvents(false)
    }
    setupWindow()
  }, [])

  useEffect(() => {
    // Skip backend sync if user has manually navigated
    if (userNavigatedRef.current) {
      return
    }

    // CRITICAL: Never auto-expand from backend on initial load
    // Only sync backend state after user has explicitly interacted
    if (!hasUserInteractedRef.current) {
      return
    }

    // Skip if category is empty (user just cleared it)
    if (!currentCategory) {
      return
    }

    // CRITICAL: If we are at Level 1 (Idle), DO NOT allow the backend to force an expansion.
    // The user must manually click the Iris orb to enter Level 2.
    if ((nav.state.level as number) === 1) {
      return
    }

    // CRITICAL FIX: Don't auto-navigate to Level 3 on initial load/refresh
    // Only sync the view without advancing navigation level automatically
    // This prevents the "random main node on refresh" issue
    if (!isTransitioning && !pendingView && currentCategory !== currentView && !exitingView) {
      // Only expand to show main nodes (Level 2), don't set currentView to show subnodes
      // This prevents the backend from forcing Level 3 on refresh
      if (!isExpanded && (nav.state.level as number) === 1) {
        setIsExpanded(true)

        nav.expandToMain()
      }
      // Note: We intentionally do NOT call nav.selectMain() or setCurrentView here
      // User must explicitly click a main node to reach Level 3
    }

    if (pendingView && currentCategory === pendingView) {
      setPendingView(null)
    }
  }, [currentCategory, currentView, exitingView, isTransitioning, pendingView, isExpanded, nav])

  const glowColor = themeGlowColor || "#00ff88"

  const activeSubnodeId = currentSubnode
  const centerLabel = isChatActive
    ? "" // Hide center label when chat is active
    : activeSubnodeId
      ? (currentView && subnodes[currentView]?.find(n => n.id === activeSubnodeId)?.label || "IRIS")
      : (currentView ? NODE_POSITIONS.find(n => n.id === currentView)?.label : "IRIS") || "IRIS"

  const confirmedNodes: ConfirmedMiniNode[] = wsConfirmedNodes.map(n => ({
    id: n.id,
    label: n.label,
    icon: n.icon,
    orbitAngle: n.orbit_angle,
    values: n.values
  }))

  const irisSize = isMobile ? 120 : 140
  const nodeSize = isMobile ? 80 : 90
  const mainRadius = isMobile ? 140 : SPIN_CONFIG.radiusExpanded
  const subRadius = isMobile ? 110 : SUBMENU_CONFIG.radius
  const orbitRadius = isMobile ? 160 : ORBIT_CONFIG.radius

  const handleNodeClick = useCallback(
    (nodeId: string, nodeLabel: string, hasSubnodes: boolean) => {
      const currentNavLevel = nav.state.level

      if (isTransitioning) {
        return
      }

      // Navigate if:
      // 1. At Level 2 (main nodes showing) - clicking goes to Level 3
      // 2. At Level 3 but clicking a DIFFERENT main node - switch to that node's subnodes
      const shouldNavigate = currentNavLevel === 2 ||
        (currentNavLevel === 3 && nav.state.selectedMain !== nodeId)

      if (shouldNavigate) {
        if (subnodes[nodeId]?.length > 0) {
          userNavigatedRef.current = true
          setExitingView(currentNavLevel === 3 ? nav.state.selectedMain : "__main__")
          setIsTransitioning(true)
          setActiveMiniNodeIndex(null)
          setPendingView(nodeId)
          setCurrentView(nodeId)

          // If at Level 3, go back first then to new main
          if (currentNavLevel === 3) {
            nav.goBack() // Go from Level 3→2 first
          }

          // Use NavigationContext to advance to Level 3
          nav.selectMain(nodeId)

          setTimeout(() => {
            setExitingView(null)
            setIsTransitioning(false)
            selectCategory(nodeId)
            // Reset userNavigatedRef to allow backend sync again
            userNavigatedRef.current = false
          }, SPIN_CONFIG.spinDuration)
        }
      }
    },
    [isTransitioning, selectCategory, nav, currentView]
  )

  const handleSubnodeClick = useCallback((subnodeId: string) => {
    // Read nav.state.level fresh to avoid stale closure
    const currentNavLevel = nav.state.level

    if (activeSubnodeId === subnodeId) {
      selectSubnode(null)
      nav.goBack()
      setActiveMiniNodeIndex(null)
    } else {
      // Get mini nodes for this subnode and navigate to level 4
      const subnodeData = subnodes[currentView!]?.find(n => n.id === subnodeId)
      // Transform fields into proper MiniNode objects - each field becomes a card in the stack
      const fields = subnodeData?.fields || []
      const miniNodes: import("@/types/navigation").MiniNode[] = fields.map((field: import("@/types/navigation").FieldConfig, index: number) => ({
        id: `${subnodeId}_${field.id}`,
        label: field.label,
        icon: "Settings",
        fields: [field]
      }))

      // CRITICAL: Call nav.selectSub() FIRST to trigger Level 4 navigation
      // This updates the navigation state and sets miniNodeStack
      nav.selectSub(subnodeId, miniNodes)

      // Update backend state
      selectSubnode(subnodeId)
    }
  }, [activeSubnodeId, currentView, nav, selectSubnode])

  const handleIrisClick = useCallback((e?: React.MouseEvent) => {
    // Check if a node was just clicked (within last 300ms) - prevents iris toggle when clicking nodes
    const timeSinceNodeClick = Date.now() - (nodeClickTimestampRef.current || 0)
    if (timeSinceNodeClick < 300) {
      return
    }

    if (isTransitioning) {
      return
    }

    // Use current level from nav state directly
    const level = nav.state.level

    // DEFENSIVE: Check if userNavigatedRef is already true (prevent double navigation)
    if (userNavigatedRef.current) {
      return
    }

    // Mark that user has explicitly interacted - enables backend sync
    hasUserInteractedRef.current = true

    if (level === 4) {
      // Level 4: Mini nodes active -> go back to level 3 (subnodes)
      userNavigatedRef.current = true
      nav.goBack()
      selectSubnode(null)
      setActiveMiniNodeIndex(null)
      setTimeout(() => {
        userNavigatedRef.current = false
      }, SPIN_CONFIG.spinDuration)
    } else if (level === 3) {
      // Level 3: Subnodes showing -> go back to level 2 (main nodes)
      userNavigatedRef.current = true
      nav.goBack()

      // Immediately transition view state to show main nodes
      setExitingView(currentView)
      setCurrentView(null)
      setIsTransitioning(true)

      // Clear backend category
      selectCategory("")

      setTimeout(() => {
        setExitingView(null)
        setIsTransitioning(false)
        userNavigatedRef.current = false
      }, SPIN_CONFIG.spinDuration)
    } else if (level === 2) {
      // Level 2: Main nodes showing -> collapse to level 1 (idle)
      userNavigatedRef.current = true
      nav.collapseToIdle()
      setIsExpanded(false)
      setIsTransitioning(true)

      // Clear backend category to prevent it from restoring on refresh
      selectCategory("")

      setTimeout(() => {
        setIsTransitioning(false)
        userNavigatedRef.current = false
      }, SPIN_CONFIG.spinDuration)
    } else {
      // Level 1: Idle -> expand to level 2 (main nodes)
      userNavigatedRef.current = true
      nav.expandToMain()
      setIsExpanded(true)
      setIsTransitioning(true)

      setTimeout(() => {
        setIsTransitioning(false)
        userNavigatedRef.current = false
      }, SPIN_CONFIG.spinDuration)
    }
  }, [currentView, isExpanded, isTransitioning, activeSubnodeId, selectSubnode, selectCategory, nav])

  const currentNodes = (currentView && subnodes && subnodes[currentView])
    ? subnodes[currentView].map((node: any, idx: number) => ({
      ...node,
      angle: (idx * (360 / subnodes[currentView].length)) - 90,
      index: idx,
    }))
    : NODE_POSITIONS.map((n) => ({ ...n, fields: [] as any[] }))

  const exitingNodes = (exitingView && subnodes && subnodes[exitingView])
    ? subnodes[exitingView].map((node: any, idx: number) => ({
      ...node,
      angle: (idx * (360 / subnodes[exitingView].length)) - 90,
      index: idx,
    }))
    : NODE_POSITIONS.map((n) => ({ ...n, fields: [] as any[] }))


  return (
    <div className="relative w-full h-full">
      <div className="relative w-full h-full overflow-hidden">
        {/* Center IRIS Orb */}
        <motion.div
          className="absolute left-1/2 top-1/2 flex items-center justify-center pointer-events-none z-[150]"
          style={{
            marginLeft: -(irisSize + 120) / 2,
            marginTop: -(irisSize + 120) / 2,
            width: irisSize + 120,
            height: irisSize + 120,
          }}
          animate={{ scale: nav.state.level === 4 ? 0.43 : 1, x: 0 }}
          transition={{ type: "spring", stiffness: 200, damping: 20, duration: 0.5 }}
          onMouseDown={startWindowDrag}
        >
          <div
            className="pointer-events-auto flex items-center justify-center"
            style={{ width: irisSize, height: irisSize }}
            role="button"
            data-no-drag
            data-tauri-drag-region="false"
            aria-label={`IRIS Control Center - ${centerLabel}`}
            aria-live="polite"
          >
            <div className="relative z-50 pointer-events-auto">
              <IrisOrb
                isExpanded={isExpanded}
                onClick={handleIrisClick}
                centerLabel={centerLabel}
                size={irisSize}
                glowColor={glowColor}
                voiceState={voiceState}
                wakeFlash={wakeFlash}
                sendMessage={sendMessage}
                onCallbacksReady={setIrisCallbacks}
              />
            </div>
          </div>
        </motion.div>

        {/* Chat view overlay */}
        <ChatView 
          isActive={isChatActive}
          onClose={handleCloseChat}
          sendMessage={sendMessage}
          fieldValues={confirmedNodes.reduce((acc, node) => ({ ...acc, ...node.values }), {})}
          updateField={handleUpdateField}
        />

        {/* Connecting line between Iris Orb and Mini Stack */}
        <AnimatePresence>
          {nav.state.level === 4 && (() => {
            const activeIndex = nav.state.activeMiniNodeIndex ?? 0
            const targetY = -80 + (activeIndex * 32) + 14
            const lineLength = 80
            const rotation = (Math.atan2(targetY, lineLength) * 180) / Math.PI
            return (
              <motion.div
                className="absolute left-1/2 top-1/2 pointer-events-none z-[55]"
                style={{
                  height: 2, width: lineLength, marginTop: 0, marginLeft: 30,
                  background: `linear-gradient(90deg, rgba(255,255,255,0.8) 0%, rgba(192,192,192,0.9) 20%, rgba(255,255,255,0.95) 40%, rgba(192,192,192,0.9) 60%, rgba(255,255,255,0.8) 80%, rgba(128,128,128,0.6) 100%)`,
                  boxShadow: '0 0 4px rgba(255,255,255,0.5)', transformOrigin: 'left center',
                }}
                initial={{ opacity: 0, scaleX: 0, rotate: 0 }}
                animate={{ opacity: 1, scaleX: 1, rotate: rotation }}
                exit={{ opacity: 0, scaleX: 0 }}
                transition={{ duration: 0.3 }}
              />
            )
          })()}
        </AnimatePresence>

        {/* Mini Node Stack - Level 4 */}
        <AnimatePresence>
          {nav.state.level === 4 && nav.state.miniNodeStack.length > 0 && (
            <motion.div
              className="absolute left-1/2 top-1/2 pointer-events-auto z-[200]"
              style={{ marginLeft: 80, marginTop: -80, width: 160, height: 200 }}
              initial={{ opacity: 0, scale: 0.8, x: -20 }}
              animate={{ opacity: 1, scale: 1, x: 0 }}
              exit={{ opacity: 0, scale: 0.8, x: -20 }}
              transition={{ duration: 0.4 }}
            >
              <MiniNodeStack miniNodes={nav.state.miniNodeStack} onOpenDashboard={handleOpenDashboard} dashboardOpen={dashboardOpen} onCloseDashboard={handleCloseDashboard} updateModelConfig={updateModelConfig} />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Exiting nodes */}
        <AnimatePresence>
          {(nav.state.level === 2 || nav.state.level === 3) && exitingNodes && (
            <>
              {exitingNodes.map((node, idx) => (
                <PrismNode key={`exit-${node.id}`} node={node} angle={node.angle} radius={exitingView ? subRadius : mainRadius} nodeSize={nodeSize} onClick={() => { }} spinRotations={exitingView ? SUBMENU_CONFIG.rotations : SPIN_CONFIG.rotations} spinDuration={exitingView ? SUBMENU_CONFIG.spinDuration : SPIN_CONFIG.spinDuration} staggerIndex={idx} isCollapsing={true} isActive={false} spinConfig={SPIN_CONFIG} />
              ))}
            </>
          )}
        </AnimatePresence>

        {/* Current nodes - INTERACTIVE */}
        <AnimatePresence>
          {(nav.state.level === 2 || nav.state.level === 3) && (
            <>
              {currentNodes
                .filter((node) => !activeSubnodeId || node.id !== activeSubnodeId)
                .map((node, idx) => (
                  <PrismNode
                    key={node.id}
                    node={node}
                    angle={node.angle}
                    radius={currentView ? subRadius : mainRadius}
                    nodeSize={nodeSize}
                    onClick={(e) => {
                      nodeClickTimestampRef.current = Date.now()
                      e?.stopPropagation()
                      currentView ? handleSubnodeClick(node.id) : handleNodeClick(node.id, node.label, (node as any).hasSubnodes)
                    }}
                    spinRotations={currentView ? SUBMENU_CONFIG.rotations : SPIN_CONFIG.rotations}
                    spinDuration={currentView ? SUBMENU_CONFIG.spinDuration : SPIN_CONFIG.spinDuration}
                    staggerIndex={idx}
                    isCollapsing={false}
                    isActive={activeSubnodeId === node.id}
                    spinConfig={SPIN_CONFIG}
                    isChatActive={isChatActive}
                  />
                ))}
            </>
          )}
        </AnimatePresence>

        {/* Cycling hint text */}
        <AnimatePresence>
          {nav.state.level === 1 && (
            <motion.div
              className="absolute bottom-24 left-1/2 -translate-x-1/2 pointer-events-auto"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 10 }}
              transition={{ delay: 0.5, duration: 0.4 }}
            >
              <motion.div
                key={typeof hintText === 'string' ? hintText : 'hint-jsx'}
                onClick={handleToggleChat}
                className="text-xs text-muted-foreground/60 tracking-widest uppercase cursor-pointer"
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ scale: 0.9, opacity: 0 }}
              >
                <motion.span
                  className="flex items-center justify-center gap-1.5"
                  animate={{ opacity: [0.4, 0.8, 0.4] }}
                  transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                >
                  {hintText}
                </motion.span>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {dashboardOpen && <DarkGlassDashboard isOpen={dashboardOpen} onClose={handleCloseDashboard} fieldValues={fieldValues} updateField={handleUpdateField} />}

      <MenuWindowSlider onUnlock={() => console.log('Menu unlocked')} isOpen={false} onClose={() => console.log('Menu closed')} />
    </div>
  )
}
