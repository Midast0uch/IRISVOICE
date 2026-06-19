"use client"

import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react"
import { motion } from "framer-motion"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { IrisOrb } from "@/components/iris/IrisOrb"
import { ChatActivationGlitch } from "@/components/iris/radial/ChatActivationGlitch"
import { WheelView } from "@/components/wheel-view/WheelView"
import { WheelViewErrorBoundary } from "@/components/wheel-view/WheelViewErrorBoundary"
import { useUILayoutState, UILayoutState, SpotlightState } from "@/hooks/useUILayoutState"
import { useKeyboardNavigation } from "@/hooks/useKeyboardNavigation"
import { BackdropBlur } from "@/components/backdrop-blur"
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const DashboardWing = lazy(() => import("@/components/dashboard-wing") as any)
import { isTauri } from "@/hooks/useDeepLink"
import { useIsMobile } from "@/hooks/use-mobile"
import { useTailscaleAccess } from "@/hooks/useTailscaleAccess"

// Lazy load heavy components for faster initial page load
// Note: Using 'any' here due to TypeScript/React.lazy() compatibility issues with Next.js 16/React 19
// A proper fix would require adding explicit type exports to each component
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const LazyChatWing = lazy(() => import("@/components/chat-view") as any)

export default function Home() {
  const { state, handleExpandToMain, handleGoBack, handleCollapseToIdle, sendMessage, voiceState, orbState, updateCardValue, startVoiceCommand, endVoiceCommand, cancelVoiceCommand } = useNavigation()
  const { getThemeConfig } = useBrandColor()

  // Initialize UI layout state machine
  const {
    state: uiLayoutState,
    spotlightState,
    openChat,
    openDashboard,
    openDashboardSolo,
    openChatFromDashboard,
    closeAll,
    closeChat,
    closeDashboard,
    toggleChatSpotlight,
    toggleDashboardSpotlight,
    restoreBalanced,
    isChatOpen,
    isDashboardOpen,
    isBothOpen,
    isChatSpotlight,
    isDashboardSpotlight,
    isBalanced,
    activeDashboardTab,
    setActiveDashboardTab,
    browseMarketplace,
    browseTo,
    browserUrl,
  } = useUILayoutState()

  // Track which sub-app to open when the dashboard is triggered from WheelView
  const [pendingSubApp, setPendingSubApp] = useState<string | null>(null);
  const pendingSubAppRef = useRef<string | null>(null);

  // Listen for card action events fired from WheelView (dashboard not yet mounted)
  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent;
      const action = ce.detail?.action;
      const subApp =
        action === 'open_models_screen' ? 'models' :
        action === 'open_inference_console' ? 'inference_console' :
        null;
      if (subApp) {
        pendingSubAppRef.current = subApp;
        setPendingSubApp(subApp);
        if (state.level !== 1) {
          // Exit WheelView first — openDashboardSolo fires in the level-watch effect below
          handleCollapseToIdle();
        } else {
          // Already at level 1: open immediately and consume the ref
          pendingSubAppRef.current = null;
          openDashboardSolo();
        }
      }
    };
    window.addEventListener('iris:card_action', handler);
    return () => window.removeEventListener('iris:card_action', handler);
  }, [state.level, handleCollapseToIdle, openDashboardSolo]);

  // When nav collapses back to level 1 with a pending subapp, open the dashboard
  useEffect(() => {
    if (state.level === 1 && pendingSubAppRef.current) {
      pendingSubAppRef.current = null; // consume so subsequent level-1 navigations don't re-trigger
      openDashboardSolo();
    }
  }, [state.level, openDashboardSolo]);

  // Enable keyboard navigation (Escape key to close wings, or restore balanced in spotlight)
  useKeyboardNavigation({
    closeAll, 
    uiState: uiLayoutState,
    spotlightState,
    restoreBalanced
  })

  // Phase 124: Single source of truth for expansion to prevent stuck states
  const isExpanded = state.level > 1

  // Mobile breakpoint: show only chat on phone
  const isMobile = useIsMobile()

  // Tailscale/mobile network access: show only chat in spotlight
  const isTailscaleAccess = useTailscaleAccess()

  // URL param ?remote=1 (set by Tailscale QR codes) — forces mobile-optimized view.
  // Read via useState+useEffect so there's no hydration mismatch (no use()).
  const [isRemoteView, setIsRemoteView] = useState(false)
  useEffect(() => {
    try {
      const p = new URLSearchParams(window.location.search)
      setIsRemoteView(p.get('remote') === '1')
    } catch {}
  }, [])

  // In Tauri the window dynamically expands to fit wings. The orb must stay
  // centered in the fixed 680px "home" column (to the right of the chat panel).
  // In browser mode the viewport is already wide enough so no offset is needed.
  const chatPanelWidth = (() => {
    if (!isTauri()) return 0
    if (!isChatOpen && !isBothOpen) return 0
    if (isChatSpotlight) return 680
    if (isDashboardSpotlight) return 360
    return 510 // balanced
  })()

  // Get theme configuration for WheelView
  const theme = getThemeConfig()
  const glowColor = theme.glow.color

  const handleSingleClick = useCallback(() => {
    // Single-click always cancels voice immediately
    if (voiceState !== "idle") {
      cancelVoiceCommand()
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
  }, [voiceState, uiLayoutState, state.level, cancelVoiceCommand, closeAll, handleGoBack, handleExpandToMain])

  const handleDoubleClick = useCallback(() => {
    // Phase 121: Double-click to start voice engine if idle
    if (voiceState === "idle") {
      startVoiceCommand()
    }
  }, [voiceState, startVoiceCommand])

  const handleChatClick = () => {
    openChat()
  }

  // WheelView confirm: confirm_card is sent directly inside WheelView.handleConfirm.
  // This callback exists to satisfy the prop type; no additional work needed here.
  const handleWheelViewConfirm = (_values: Record<string, Record<string, any>>) => {
    // confirm_card already dispatched by WheelView to the backend
  }

  const handleWheelViewBack = () => {
    // Dispatch GO_BACK action to return to level 2
    handleGoBack()
  }

  // Mobile / Tailscale / Remote: simplified full-screen chat
  if (isMobile || isTailscaleAccess || isRemoteView) {
    const remoteFlag = isRemoteView || isMobile || isTailscaleAccess
    // On mobile, UI state is IDLE (ChatWing is force-rendered). openDashboard()
    // requires UI_STATE_CHAT_OPEN which never happens, so use openDashboardSolo().
    const handleDashboardClick = uiLayoutState === UILayoutState.UI_STATE_IDLE
      ? openDashboardSolo
      : openDashboard
    const showChat = !isDashboardOpen && !isBothOpen
    const showDashboard = isDashboardOpen || isBothOpen
    return (
      <main suppressHydrationWarning className="bg-transparent w-full h-screen max-h-screen flex flex-col items-center justify-center relative overflow-hidden">
        {showChat && (
          <Suspense fallback={null}>
            <LazyChatWing
              isOpen={true}
              onClose={() => {}}
              onDashboardClick={handleDashboardClick}
              onDashboardClose={closeChat}
              sendMessage={sendMessage}
              spotlightState={isTailscaleAccess ? SpotlightState.CHAT_SPOTLIGHT : spotlightState}
              onSpotlightToggle={toggleChatSpotlight}
              isDashboardOpen={false}
              uiState={uiLayoutState}
              onOpenBrowserUrl={browseTo}
              isRemoteView={remoteFlag}
            />
          </Suspense>
        )}
        {showDashboard && (
          <Suspense fallback={null}>
            <DashboardWing
              isOpen={true}
              onClose={() => {
                setPendingSubApp(null)
                closeDashboard()
              }}
              sendMessage={sendMessage}
              spotlightState={spotlightState}
              onSpotlightToggle={toggleDashboardSpotlight}
              isSolo={true}
              uiState={uiLayoutState}
              onOpenChat={closeDashboard}
              isChatOpen={false}
              initialSubApp={pendingSubApp}
              isRemoteView={remoteFlag}
            />
          </Suspense>
        )}
      </main>
    )
  }

  return (
    <main suppressHydrationWarning className="bg-transparent w-full h-screen max-h-screen flex flex-col items-center justify-center relative overflow-hidden" style={{ perspective: '1200px' }}>
      {/* Backdrop Blur - renders when wings are open */}
      <BackdropBlur uiState={uiLayoutState} />
      
      {(state.level !== 3 || isChatOpen || isBothOpen) && (
        /* Positioning wrapper: in Tauri, pins the orb to the center of its 680px home column */
        <div
          className={chatPanelWidth === 0 ? "absolute inset-0 flex items-center justify-center" : "fixed"}
          style={chatPanelWidth > 0 ? {
            left: chatPanelWidth + 340,
            top: '50%',
            transform: 'translateX(-50%) translateY(-50%)',
            zIndex: (isChatOpen || isBothOpen) ? 5 : 0,
            pointerEvents: (isChatOpen || isBothOpen) ? 'none' : 'auto',
          } : {
            zIndex: (isChatOpen || isBothOpen) ? 5 : 0,
            pointerEvents: (isChatOpen || isBothOpen) ? 'none' : 'auto',
          }}
        >
          <motion.div
            className="flex items-center justify-center"
            animate={{
              scale: uiLayoutState !== UILayoutState.UI_STATE_IDLE ? 0.85 : 1,
              filter: uiLayoutState !== UILayoutState.UI_STATE_IDLE ? 'blur(2px)' : 'blur(0px)',
              opacity: uiLayoutState !== UILayoutState.UI_STATE_IDLE ? 0.6 : 1,
            }}
            transition={{
              duration: 0.4,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <div className="flex flex-col items-center justify-center relative">
              <IrisOrb
                onClick={handleSingleClick}
                onDoubleClick={handleDoubleClick}
                onChatClick={handleChatClick}
                isExpanded={isExpanded}
                centerLabel={orbState.label}
                size={175}
                glowColor={glowColor}
                wakeFlash={false}
              />
              <div className="mt-12">
                <ChatActivationGlitch
                  onClick={handleChatClick}
                  navigationLevel={state.level}
                  uiState={uiLayoutState}
                />
              </div>
            </div>
          </motion.div>
        </div>
      )}
      {state.level === 3 && state.selectedMain && (
        <Suspense fallback={<div className="text-white/50">Loading...</div>}>
          <WheelViewErrorBoundary>
            <WheelView
              categoryId={state.selectedMain}
              glowColor={glowColor}
              expandedIrisSize={240}
              initialValues={state.cardValues}
              onConfirm={handleWheelViewConfirm}
              onBackToCategories={handleWheelViewBack}
              onBrowseMarketplace={browseMarketplace}
            />
          </WheelViewErrorBoundary>
        </Suspense>
      )}
      
      {/* ChatWing - sibling to DashboardWing */}
      <Suspense fallback={null}>
        <LazyChatWing
          isOpen={isChatOpen || isBothOpen}
          onClose={isBothOpen ? closeChat : closeAll}
          onDashboardClick={openDashboard}
          onDashboardClose={closeChat}
          sendMessage={sendMessage}
          spotlightState={spotlightState}
          onSpotlightToggle={toggleChatSpotlight}
          isDashboardOpen={isBothOpen}
          uiState={uiLayoutState}
          onOpenBrowserUrl={browseTo}
        />
      </Suspense>

      {/* DashboardWing - sibling to ChatWing */}
      <Suspense fallback={null}>
        <DashboardWing
          isOpen={isDashboardOpen || isBothOpen}
          onClose={() => {
            setPendingSubApp(null);
            if (isBothOpen) closeDashboard(); else closeAll();
          }}
          sendMessage={sendMessage}
          spotlightState={spotlightState}
          onSpotlightToggle={toggleDashboardSpotlight}
          isSolo={isDashboardOpen}
          uiState={uiLayoutState}
          onOpenChat={isDashboardOpen ? openChatFromDashboard : undefined}
          isChatOpen={isChatOpen || isBothOpen}
          initialSubApp={pendingSubApp}
        />
      </Suspense>
    </main>
  )
}