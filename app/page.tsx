"use client"

import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react"
import { motion } from "framer-motion"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { IrisOrb } from "@/components/iris/IrisOrb"
import { AmbientCrawlTier } from "@/components/iris/AmbientCrawlTier"
import { WheelView } from "@/components/wheel-view/WheelView"
import { WheelViewErrorBoundary } from "@/components/wheel-view/WheelViewErrorBoundary"
import { useUILayoutState, UILayoutState, SpotlightState } from "@/hooks/useUILayoutState"
import { useKeyboardNavigation } from "@/hooks/useKeyboardNavigation"
import { BackdropBlur } from "@/components/backdrop-blur"
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const DashboardWing = lazy(() => import("@/components/dashboard-wing") as any)
import { useIsMobile } from "@/hooks/use-mobile"
import { useTailscaleAccess } from "@/hooks/useTailscaleAccess"
import { useDetachedPane, useWingReattachListener, detachWing, reattachWing, type PaneName } from "@/hooks/useDetachedWing"
import {
  computeFrame,
  frameLeft,
  orbCenterOffsetX,
  ORB_BOX,
  ORB_BAND,
  type UIStr,
  type SpotlightStr,
} from "@/lib/orbWingGeometry"

// Lazy load heavy components for faster initial page load
// Note: Using 'any' here due to TypeScript/React.lazy() compatibility issues with Next.js 16/React 19
// A proper fix would require adding explicit type exports to each component
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const LazyChatWing = lazy(() => import("@/components/chat-view") as any)

export default function Home() {
  const { state, handleExpandToMain, handleGoBack, handleCollapseToIdle, sendMessage, voiceState, orbState, updateCardValue, startVoiceCommand, endVoiceCommand, cancelVoiceCommand, currentConversationId } = useNavigation()
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

  // Window width for dynamic orb sizing (Tauri widget resizes to fit content)
  const [windowWidth, setWindowWidth] = useState(1920)
  useEffect(() => {
    setWindowWidth(window.innerWidth)
    const handleResize = () => setWindowWidth(window.innerWidth)
    window.addEventListener("resize", handleResize)
    return () => window.removeEventListener("resize", handleResize)
  }, [])

  // Detached wings. `detachedPane` is set only in a window opened by
  // detach_wing; the widget itself always reads null and instead listens for
  // the reattach event so a closed wing comes back inline.
  const detachedPane = useDetachedPane()

  const handleReattach = useCallback((pane: PaneName) => {
    if (pane === 'chat') openChat()
    else openDashboardSolo()
  }, [openChat, openDashboardSolo])
  useWingReattachListener(handleReattach)

  // The frame this page lays out inside — see lib/orbWingGeometry.
  const spotlightKey: SpotlightStr = isChatSpotlight
    ? 'chatSpotlight'
    : isDashboardSpotlight
      ? 'dashboardSpotlight'
      : 'balanced'
  const uiKey: UIStr = isBothOpen
    ? 'both_open'
    : isChatOpen
      ? 'chat_open'
      : isDashboardOpen
        ? 'dashboard_open'
        : 'idle'
  const frame = computeFrame(uiKey, spotlightKey, state.level)
  const frameX = frameLeft(windowWidth, frame.width)

  // Where the swallowed card should sit. It stands in for the orb, so it sits
  // wherever the orb sits: the centre of the orb band, expressed as an offset
  // from the viewport centre. Both wings open -> ~0, between them. One open ->
  // pushed into the empty half.
  const swallowCenterOffsetX = orbCenterOffsetX(frame)

  // Fixed. The orb container used to inflate to fill whatever space the wings
  // left over (60-400 px), but XurOrb caps its canvas at 120 px, so growing
  // the container only spread the labels and pushed the wings further out. The
  // band in orbWingGeometry is sized to this constant.
  const orbDiameter = ORB_BOX

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

  // ── Detached wing window ────────────────────────────────────────────────
  // This window was opened by detach_wing and shows ONE wing filling it. No
  // orb, no second wing, no window resizing: the OS owns this window's size
  // and position, which is the entire point — it can sit on another monitor
  // and stay there.
  //
  // It is the same frontend in the same process as the widget, so it shares
  // the one Rust WebSocket client rather than opening a second connection the
  // backend would evict.
  if (detachedPane) {
    return (
      <main
        suppressHydrationWarning
        className="w-full h-screen max-h-screen overflow-hidden relative"
        style={{ background: '#06070e' }}
      >
        {detachedPane === 'chat' ? (
          <Suspense fallback={null}>
            <LazyChatWing
              isOpen={true}
              /* Closing from inside a detached window means "put it back",
                 which is what closing the window does. */
              onClose={() => { void reattachWing('chat') }}
              onDashboardClick={() => { void detachWing('dashboard') }}
              onDashboardClose={() => {}}
              sendMessage={sendMessage}
              spotlightState={SpotlightState.BALANCED}
              isDashboardOpen={false}
              uiState={uiLayoutState}
              onOpenBrowserUrl={browseTo}
              isDetached
            />
          </Suspense>
        ) : (
          <Suspense fallback={null}>
            <DashboardWing
              isOpen={true}
              onClose={() => { void reattachWing('dashboard') }}
              sendMessage={sendMessage}
              spotlightState={SpotlightState.BALANCED}
              isSolo={true}
              uiState={uiLayoutState}
              isChatOpen={false}
              initialSubApp={pendingSubApp}
              isDetached
            />
          </Suspense>
        )}
      </main>
    )
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
        /* Positioning wrapper — ONE rule for every layout.
           The orb always sits at the centre of the orb band, which is the
           middle third of the frame described in lib/orbWingGeometry. In Tauri
           the native window IS the frame, so frameX is 0 and the band lands
           between two flush-mounted wings. In a browser the same frame is
           centred in the wider viewport.

           This replaces five branches (Tauri home column, browser chat-only,
           browser dashboard-only, both-open chat spotlight, both-open dashboard
           spotlight) that each computed a different orb centre from a different
           set of magic numbers. */
        <div
          className="absolute inset-0"
          style={{
            zIndex: isBothOpen ? 100 : (isChatOpen || isDashboardOpen) ? 5 : 0,
            pointerEvents: 'none',
          }}
        >
        <div
          className="absolute flex items-center justify-center"
          style={{
            left: frameX + frame.orbCenterX,
            top: '50%',
            transform: 'translateX(-50%) translateY(-50%)',
            width: ORB_BAND,
            height: ORB_BAND,
            // The orb itself stays clickable even while the wings are open —
            // a single click on it closes them (handleSingleClick).
            pointerEvents: 'auto',
          }}
        >
          <motion.div
            className="flex items-center justify-center"
            animate={{
              // Held at 1. It used to drop to 0.7 whenever a single wing was
              // open, which left the orb floating in the middle of a band
              // sized for its full width — the gap the user reported.
              scale: 1,
              filter: 'blur(0px)',
              opacity: 1,
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
                size={orbDiameter}
                glowColor={glowColor}
                uiState={uiLayoutState}
              />
            </div>
          </motion.div>
        </div>
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
          orbDiameter={orbDiameter}
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
          isBothOpen={isBothOpen}
          initialSubApp={pendingSubApp}
          orbDiameter={orbDiameter}
        />
      </Suspense>

      {/* REQ-6 (specs/vision-browser-stage, T11): the ambient crawl tier —
          the agent's browsing made visible OUTSIDE the dashboard wing, so a
          voice-driven search is not invisible just because the wing is shut.
          Minimal dot when the panel is actually visible; full status ring
          otherwise. Renders null when no crawl is active. */}
      <Suspense fallback={null}>
        <AmbientCrawlTier
          glowColor={glowColor}
          panelVisible={isDashboardOpen && !isChatSpotlight}
          // REQ-16: a pending question is answerable INLINE in the tier only
          // when ChatView is not on screen. When it IS, QuestionCard owns the
          // question — two live answer surfaces for one question_id would race.
          chatVisible={isChatOpen || isBothOpen}
          // Live diameter so the tier anchors beside the orb at any wing state
          // (it ranges 60-400px) instead of guessing one offset.
          orbDiameter={orbDiameter}
          // REQ-16 AC2/AC3: any open wing during an active run swallows the
          // orb into the tier; the tier then travels out from the orb's centre.
          wingOpen={isChatOpen || isDashboardOpen || isBothOpen}
          centerOffsetX={swallowCenterOffsetX}
          sendMessage={sendMessage}
          // The socket's authoritative thread id. The tier refuses to send an
          // inline ask without it rather than guessing — see submitAsk.
          conversationId={currentConversationId}
        />
      </Suspense>

      {/* Vision Stage Simulator REMOVED (2026-08-25). Built for REQ-12/T13,
          it did its job — 13 scenarios signed off, then Wave 6's counter form,
          swallow and release judged against it — and Wave 6 is now complete.
          ARCHITECTURE.md section 7 preserves the runner contract and the
          scenario list; the source is in git history (see the tasks.md note)
          rather than lost, unlike the first time it was cut. */}
    </main>
  )
}