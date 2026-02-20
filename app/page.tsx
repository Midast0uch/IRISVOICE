"use client"

import { useState, lazy, Suspense } from "react"
import { useNavigation } from "@/contexts/NavigationContext"
import { IrisOrb } from "@/components/iris/IrisOrb"
import { ChatActivationText } from "@/components/chat-activation-text"
import { Level4View } from "@/components/level-4-view"
import HexagonalControlCenter from "@/components/hexagonal-control-center"
import { AnimatePresence } from "framer-motion"

const LazyChatView = lazy(() => import("@/components/chat-view"))

export default function Home() {
  const { state, handleExpandToMain, sendMessage, setMainView, voiceState, updateField, orbState } = useNavigation()
  const [isExpanded, setIsExpanded] = useState(false)

  const handleSingleClick = () => {
    console.log("[DEBUG] Iris orb clicked, current level:", state.level, "isExpanded:", isExpanded)
    if (!isExpanded) {
      setIsExpanded(true)
      handleExpandToMain()
      console.log("[DEBUG] After handleExpandToMain, level should be 2:", state.level)
    }
  }

  const handleDoubleClick = () => {
    sendMessage("voice_command_start", {})
  }

  const handleChatClick = () => {
    setMainView("chat")
  }

  return (
    <main className="bg-transparent w-full min-h-screen flex flex-col items-center justify-center relative">
      <div className="flex flex-col items-center justify-center relative">
        <IrisOrb
          onSingleClick={handleSingleClick}
          onDoubleClick={handleDoubleClick}
          isExpanded={isExpanded}
          voiceState={voiceState}
          centerLabel={orbState.label}
          size={200}
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
      {state.level === 4 && (
        <Level4View
          fieldValues={state.fieldValues}
          updateField={updateField}
          sendMessage={sendMessage}
        />
      )}
      {state.level === 2 && (
        <HexagonalControlCenter
          fieldValues={state.fieldValues}
          updateField={updateField}
          sendMessage={sendMessage}
        />
      )}
      <AnimatePresence>
        {state.mainView === "chat" && (
          <Suspense fallback={<div className="text-white">Loading chat...</div>}>
            <LazyChatView
              onClose={() => setMainView(null)}
              isActive={true}
              sendMessage={sendMessage}
            />
          </Suspense>
        )}
      </AnimatePresence>
    </main>
  )
}