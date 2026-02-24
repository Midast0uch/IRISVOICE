"use client"

import { useState, lazy, Suspense } from "react"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { IrisOrb } from "@/components/iris/IrisOrb"
import { ChatActivationText } from "@/components/chat-activation-text"
import { WheelView } from "@/components/wheel-view/WheelView"
import { WheelViewErrorBoundary } from "@/components/wheel-view/WheelViewErrorBoundary"
import { AnimatePresence } from "framer-motion"

// Lazy load heavy components for faster initial page load
// Note: Using 'any' here due to TypeScript/React.lazy() compatibility issues with Next.js 16/React 19
// A proper fix would require adding explicit type exports to each component
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const LazyChatView = lazy(() => import("@/components/chat-view") as any)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const LazyHexagonalControlCenter = lazy(() => import("@/components/hexagonal-control-center") as any)

export default function Home() {
  const { state, handleExpandToMain, handleGoBack, sendMessage, setMainView, voiceState, orbState, updateMiniNodeValue } = useNavigation()
  const { getThemeConfig } = useBrandColor()
  const [isExpanded, setIsExpanded] = useState(false)

  // Get theme configuration for WheelView
  const theme = getThemeConfig()
  const glowColor = theme.glow.color

  const handleSingleClick = () => {
    if (state.level > 1) {
      handleGoBack()
    } else if (!isExpanded) {
      setIsExpanded(true)
      handleExpandToMain()
    }
  }

  const handleDoubleClick = () => {
    sendMessage("voice_command_start", {})
  }

  const handleChatClick = () => {
    setMainView("chat")
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
    <main className="bg-transparent w-full min-h-screen flex flex-col items-center justify-center relative">
      <div className="flex flex-col items-center justify-center relative">
        <IrisOrb
          onClick={handleSingleClick}
          onDoubleClick={handleDoubleClick}
          isExpanded={isExpanded}
          voiceState={voiceState}
          centerLabel={orbState.label}
          size={175}
          glowColor="#00ffff"
          wakeFlash={false}
          sendMessage={sendMessage}
        />
        <div className="mt-12"> {/* Increased margin top for more spacing */}
          <ChatActivationText
            onChatClick={handleChatClick}
            isExpanded={isExpanded}
            isChatActive={state.mainView === "chat"}
            navigationLevel={state.level}
          />
        </div>
      </div>
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
      <AnimatePresence>
        {state.mainView === "chat" && (
          <Suspense fallback={<div className="text-white">Loading chat...</div>}>
            <LazyChatView
              onClose={() => setMainView("navigation")}
              isActive={true}
              sendMessage={sendMessage}
            />
          </Suspense>
        )}
      </AnimatePresence>
    </main>
  )
}