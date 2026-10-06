"use client"

import React from "react"
import { motion } from "framer-motion"
import { BarChart3, Bell, History, X, ExternalLink, Maximize2, Minimize2 } from 'lucide-react'
import { invoke } from "@tauri-apps/api/core"
import { IrisApertureIcon } from "@/components/ui/IrisApertureIcon"
import { detachWing, reattachWing } from "@/hooks/useDetachedWing"

// Launch the separate IRIS Launcher Tauri app (bidirectional launcher⇄widget).
const openIrisLauncher = async () => {
  try {
    await invoke("launch_launcher");
  } catch (e) {
    console.warn("[ChatView] launch_launcher failed:", e);
  }
};

export interface ChatHeaderProps {
  isRemoteView?: boolean
  isDetached: boolean
  glowColor: string
  fontColor: string
  voiceState: "idle" | "listening" | "processing_conversation" | "processing_tool" | "speaking" | "error"
  globalError: boolean
  // Header drag (the ref is owned by the parent: useManualDragWindow attaches to it)
  chatHeaderRef: React.RefObject<HTMLDivElement | null>
  handleHeaderDragStart: (e: React.MouseEvent) => void
  // Dashboard / spotlight / close
  isDashboardOpen: boolean
  onDashboardClose?: () => void
  onDashboardClick: () => void
  onSpotlightToggle?: () => void
  isInChatSpotlight: boolean
  onClose: () => void
  // Dropdown panels
  showNotifications: boolean
  openNotifications: () => void
  unreadCount: number
  showHistory: boolean
  openHistory: () => void
  closeDropdowns: () => void
}

export function ChatHeader({
  isRemoteView,
  isDetached,
  glowColor,
  fontColor,
  voiceState,
  globalError,
  chatHeaderRef,
  handleHeaderDragStart,
  isDashboardOpen,
  onDashboardClose,
  onDashboardClick,
  onSpotlightToggle,
  isInChatSpotlight,
  onClose,
  showNotifications,
  openNotifications,
  unreadCount,
  showHistory,
  openHistory,
  closeDropdowns,
}: ChatHeaderProps) {
  return (
      <div 
        ref={chatHeaderRef}
        onMouseDown={handleHeaderDragStart}
        className={isRemoteView ? "h-[60px] px-4 flex items-center flex-shrink-0 border-b relative z-30" : "h-12 px-3 flex items-center flex-shrink-0 border-b relative z-30"}
        style={{ borderColor: `${glowColor}15`, position: 'relative', cursor: isRemoteView ? undefined : 'grab' }}
      >
        {/* Global error line */}
        {globalError && (
          <motion.div
            className="absolute top-0 left-0 right-0 h-[1px] z-40"
            style={{ background: 'rgba(239,68,68,0.8)' }}
            animate={{ opacity: [1, 0.3, 1] }}
            transition={{ duration: 2, repeat: Infinity }}
          />
        )}
        
        {/* Left section: Pulse + Title + Dashboard */}
        <div className="flex items-center gap-2 flex-1">
          <motion.div
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: glowColor }}
            animate={{
              scale: voiceState === 'listening' ? [1, 1.4, 1] : 1,
              opacity: voiceState === 'listening' ? [1, 0.6, 1] : 1
            }}
            transition={{ duration: 1.2, repeat: Infinity }}
          />
          <span
            className="text-[13px] font-semibold tracking-wide"
            style={{ color: fontColor, opacity: 0.9 }}
          >
            IRIS
          </span>
          {/* Dashboard - positioned next to IRIS text - toggles open/close */}
          <button
            onClick={() => {
              if (isDashboardOpen && onDashboardClose) {
                onDashboardClose();
              } else {
                onDashboardClick();
              }
              closeDropdowns();
            }}
            className={isRemoteView ? "p-2.5 rounded-lg transition-all duration-150 min-h-[44px] min-w-[44px] flex items-center justify-center" : "p-1.5 rounded-lg transition-all duration-150"}
            style={{
              color: isDashboardOpen ? glowColor : 'rgba(255,255,255,0.75)',
              backgroundColor: isDashboardOpen ? `${glowColor}15` : 'transparent'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = isDashboardOpen ? glowColor : 'rgba(255,255,255,0.95)';
              e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = isDashboardOpen ? glowColor : 'rgba(255,255,255,0.75)';
              e.currentTarget.style.backgroundColor = isDashboardOpen ? `${glowColor}15` : 'transparent';
            }}
            title={isDashboardOpen ? "Close Dashboard" : "Open Dashboard"}
          >
            <BarChart3 size={isRemoteView ? 20 : 14} />
          </button>
          {/* Detach / reattach. The chat wing becomes its own OS window
              so it can live on a second monitor — the widget window is
              transparent, borderless and always-on-top, and cannot span
              two screens. Detaching closes the wing here so it is never
              drawn twice; closing the detached window puts it back. */}
          {!isRemoteView && (
            <button
              onClick={async () => {
                if (isDetached) {
                  await reattachWing('chat')
                } else if (await detachWing('chat')) {
                  onClose()
                }
              }}
              className="p-1.5 rounded-lg transition-all duration-150"
              style={{ color: 'rgba(255,255,255,0.75)' }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.95)'; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.75)'; e.currentTarget.style.backgroundColor = 'transparent'; }}
              title={isDetached ? "Put chat back in the widget" : "Move chat to its own window"}
              aria-label={isDetached ? "Reattach chat" : "Detach chat"}
            >
              {isDetached ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
          )}
          {/* Open IRIS Launcher — re-open the separate launcher app if closed */}
          <button
            onClick={() => openIrisLauncher()}
            className={isRemoteView ? "p-2.5 rounded-lg transition-all duration-150 min-h-[44px] min-w-[44px] flex items-center justify-center" : "p-1.5 rounded-lg transition-all duration-150"}
            style={{ color: 'rgba(255,255,255,0.75)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.95)'; e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.75)'; e.currentTarget.style.backgroundColor = 'transparent'; }}
            title="Open IRIS Launcher"
          >
            <ExternalLink size={isRemoteView ? 20 : 14} />
          </button>
        </div>

        {/* Center: Spotlight Iris Aperture Button — embedded on top border line */}
        {onSpotlightToggle && (
          <div className="absolute left-1/2 -translate-x-1/2 top-0 -translate-y-1/2 z-40">
            <button
              onClick={() => {
                onSpotlightToggle();
                closeDropdowns();
              }}
              className={isRemoteView ? "p-2.5 rounded-full transition-all duration-150 border min-h-[44px] min-w-[44px] flex items-center justify-center" : "p-1.5 rounded-full transition-all duration-150 border"}
              style={{
                color: isInChatSpotlight ? glowColor : 'rgba(255,255,255,0.7)',
                backgroundColor: isInChatSpotlight ? `${glowColor}20` : 'transparent',
                borderColor: isInChatSpotlight ? `${glowColor}50` : 'rgba(255,255,255,0.2)',
                boxShadow: isInChatSpotlight ? `0 0 8px ${glowColor}40` : 'none',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = glowColor;
                e.currentTarget.style.borderColor = `${glowColor}50`;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = isInChatSpotlight ? glowColor : 'rgba(255,255,255,0.7)';
                e.currentTarget.style.borderColor = isInChatSpotlight ? `${glowColor}50` : 'rgba(255,255,255,0.2)';
              }}
              title={isInChatSpotlight ? "Restore balanced view" : "Maximize chat"}
            >
              <IrisApertureIcon
                isActive={isInChatSpotlight}
                glowColor={glowColor}
                fontColor={fontColor}
                size={isRemoteView ? 18 : 14}
              />
            </button>
          </div>
        )}

        {/* Right section: Notifications + History + Close */}
        <div className="flex items-center gap-1 flex-1 justify-end">
          {/* Notifications */}
          <button
            onClick={() => showNotifications ? closeDropdowns() : openNotifications()}
            className={isRemoteView ? "p-2.5 rounded-lg transition-all duration-150 relative min-h-[44px] min-w-[44px] flex items-center justify-center" : "p-2 rounded-lg transition-all duration-150 relative"}
            style={{
              color: showNotifications ? glowColor : unreadCount > 0 ? glowColor : 'rgba(255,255,255,0.75)',
              backgroundColor: showNotifications ? `${glowColor}15` : 'transparent'
            }}
            onMouseEnter={(e) => {
              if (!showNotifications) e.currentTarget.style.color = unreadCount > 0 ? glowColor : 'rgba(255,255,255,0.95)';
              e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
            }}
            onMouseLeave={(e) => {
              if (!showNotifications) e.currentTarget.style.color = unreadCount > 0 ? glowColor : 'rgba(255,255,255,0.75)';
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
            title="Notifications"
          >
            <Bell size={16} />
            {unreadCount > 0 && (
              <motion.span
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                className="absolute top-1 right-1 w-2 h-2 rounded-full"
                style={{ backgroundColor: glowColor }}
              />
            )}
          </button>

          {/* History */}
          <button
            onClick={() => showHistory ? closeDropdowns() : openHistory()}
            className={isRemoteView ? "p-2.5 rounded-lg transition-all duration-150 min-h-[44px] min-w-[44px] flex items-center justify-center" : "p-2 rounded-lg transition-all duration-150"}
            style={{
              color: showHistory ? glowColor : 'rgba(255,255,255,0.75)',
              backgroundColor: showHistory ? `${glowColor}15` : 'transparent'
            }}
            onMouseEnter={(e) => {
              if (!showHistory) e.currentTarget.style.color = 'rgba(255,255,255,0.95)';
              e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
            }}
            onMouseLeave={(e) => {
              if (!showHistory) e.currentTarget.style.color = 'rgba(255,255,255,0.75)';
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
            title="Conversation History"
          >
            <History size={isRemoteView ? 20 : 16} />
          </button>

          {/* Close */}
          <button
            onClick={() => {
              onClose();
              closeDropdowns();
            }}
            className={isRemoteView ? "p-2.5 rounded-lg transition-all duration-150 min-h-[44px] min-w-[44px] flex items-center justify-center" : "p-2 rounded-lg transition-all duration-150"}
            style={{ color: 'rgba(255,255,255,0.75)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'rgba(255,255,255,0.95)';
              e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'rgba(255,255,255,0.75)';
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
            title="Close Chat"
          >
            <X size={isRemoteView ? 20 : 16} />
          </button>
        </div>
      </div>
  )
}
