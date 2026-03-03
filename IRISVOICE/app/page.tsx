"use client"

import { lazy, Suspense, useCallback } from "react"
import { motion } from "framer-motion"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { IrisOrb } from "@/components/iris/IrisOrb"
import { ChatActivationText } from "@/components/chat-activation-text"
import { WheelView } from "@/components/wheel-view/WheelView"
import { WheelViewErrorBoundary } from "@/components/wheel-view/WheelViewErrorBoundary"
import { useUILayoutState, UILayoutState, SpotlightState } from "@/hooks/useUILayoutState"
import { useKeyboardNavigation } from "@/hooks/useKeyboardNavigation"
import { BackdropBlur } from "@/components/backdrop-blur"
import { DashboardWing } from "@/components/dashboard-wing"

// Lazy load heavy components for faster initial page load
// Note: Using 'any' here due to TypeScript/React.lazy() compatibility issues with Next.js 16/React 19
// A proper fix would require adding explicit type exports to each component
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const LazyChatWing = lazy(() => import("@/components/chat-view") as any)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const LazyHexagonalControlCenter = lazy(() => import("@/components/hexagonal-control-center") as any)

export default function Home() {
  const { state, handleExpandToMain, handleGoBack, sendMessage, voiceState, orbState, updateMiniNodeValue } = useNavigation()
  const { getThemeConfig } = useBrandColor()
  
  // Initialize UI layout state machine
  const { 
    state: uiLayoutState, 
    spotlightState,
    openChat, 
    openDashboard, 
    closeAll, 
    toggleChatSpotlight,
    toggleDashboardSpotlight,
    restoreBalanced,
    isChatOpen, 
    isBothOpen,
    isChatSpotlight,
    isDashboardSpotlight,
    isBalanced
  } = useUILayoutState()

  // Enable keyboard navigation (Escape key to close wings, or restore balanced in spotlight)
  useKeyboardNavigation({ 
    closeAll, 
    uiState: uiLayoutState,
    spotlightState,
    restoreBalanced
  })

  // Phase 124: Single source of truth for expansion to prevent stuck states
  const isExpanded = state.level > 1

  // Get theme configuration for WheelView
  const theme = getThemeConfig()
  const glowColor = theme.glow.color

  const handleSingleClick = useCallback(() => {
    // Phase 121: Single-click to stop voice engine if active
    if (voiceState !== "idle") {
      sendMessage("voice_command_end", {})
      return
    }

    // If wings are open, close them and return to idle
    if (uiLayoutState !== UILayoutState.UI_STATE_IDLE) {
      closeAll()
      return
    }

    // Otherwise, handle navigation as before
    if (state.level > 1) {
      handleGoBack()
    } else {
      handleExpandToMain()
    }
  }, [voiceState, uiLayoutState, state.level, sendMessage, closeAll, handleGoBack, handleExpandToMain])

  const handleDoubleClick = useCallback(() => {
    // Phase 121: Double-click to start voice engine if idle
    if (voiceState === "idle") {
      sendMessage("voice_command_start", {})
    }
  }, [voiceState, sendMessage])

  const handleChatClick = () => {
    openChat()
  }

  // Task 10.2: Wire up WheelView callbacks
  const handleWheelViewConfirm = (values: Record<string, Record<string, any>>) => {
    // Save miniNodeValues to context - already handled by updateMiniNodeValue in WheelView
    // The values are already persisted through the context, so we just need to acknowledge
    console.log("[Navigation] WheelView confirmed with values:", values)
  }

  const handleWheelViewBack = () => {
    // Dispatch GO_BACK action to return to level 2
    handleGoBack()
  }

  return (
    <main className="bg-transparent w-full min-h-screen flex flex-col items-center justify-center relative" style={{ perspective: '1200px' }}>
      {/* Backdrop Blur - renders when wings are open */}
      <BackdropBlur uiState={uiLayoutState} />
      
      {state.level !== 3 && (
        <motion.div 
          className="absolute inset-0 flex items-center justify-center"
          animate={{
            scale: uiLayoutState !== UILayoutState.UI_STATE_IDLE ? 0.85 : 1,
            filter: uiLayoutState !== UILayoutState.UI_STATE_IDLE ? 'blur(2px)' : 'blur(0px)',
            opacity: uiLayoutState !== UILayoutState.UI_STATE_IDLE ? 0.6 : 1,
          }}
          transition={{
            duration: 0.4,
            ease: [0.22, 1, 0.36, 1],
          }}
          style={{ zIndex: 0 }}
        >
          <div className="flex flex-col items-center justify-center relative">
            <IrisOrb
              onClick={handleSingleClick}
              onDoubleClick={handleDoubleClick}
              isExpanded={isExpanded}
              centerLabel={orbState.label}
              size={175}
              glowColor={glowColor}
              wakeFlash={false}
            />
            <div className="mt-12"> {/* Increased margin top for more spacing */}
              <ChatActivationText
                onClick={handleChatClick}
                navigationLevel={state.level}
                uiState={uiLayoutState}
              />
            </div>
          </div>
        </motion.div>
      )}
      {state.level === 2 && (
        <Suspense fallback={<div className="text-white/50">Loading...</div>}>
          <LazyHexagonalControlCenter key="level-2" />
        </Suspense>
      )}
      {state.level === 3 && state.selectedMain && (
        <Suspense fallback={<div className="text-white/50">Loading...</div>}>
          <WheelViewErrorBoundary>
            <WheelView
              categoryId={state.selectedMain}
              glowColor={glowColor}
              expandedIrisSize={240}
              initialValues={state.miniNodeValues}
              onConfirm={handleWheelViewConfirm}
              onBackToCategories={handleWheelViewBack}
            />
          </WheelViewErrorBoundary>
        </Suspense>
      )}
      
      {/* ChatWing - sibling to DashboardWing */}
      <Suspense fallback={null}>
        <LazyChatWing
          isOpen={isChatOpen || isBothOpen}
          onClose={closeAll}
          onDashboardClick={openDashboard}
          sendMessage={sendMessage}
          spotlightState={spotlightState}
          onSpotlightToggle={isBothOpen ? toggleChatSpotlight : undefined}
        />
      </Suspense>
      
      {/* DashboardWing - sibling to ChatWing */}
      <DashboardWing
        isOpen={isBothOpen}
        onClose={closeAll}
        sendMessage={sendMessage}
        spotlightState={spotlightState}
        onSpotlightToggle={isBothOpen ? toggleDashboardSpotlight : undefined}
      />
    </main>
  )
}