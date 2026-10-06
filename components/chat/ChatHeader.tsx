"use client"

import React, { useCallback, useEffect, useRef, useState } from "react"
import { motion } from "framer-motion"
import { BarChart3, Bell, X, ExternalLink, Maximize2, Minimize2 } from 'lucide-react'
import { invoke } from "@tauri-apps/api/core"
import { Xur } from "@/components/Xur"
import { useBrandPalette } from "@/hooks/useBrandPalette"
import { detachWing, reattachWing } from "@/hooks/useDetachedWing"
import type { ThreadSummary, Strand } from "@/lib/strands/api"
import { ThreadOrbit } from "@/components/chat/header/ThreadOrbit"
import { StrandMap } from "@/components/chat/header/StrandMap"
import { brandVars } from "@/components/chat/header/brandVars"
import { useEscape } from "@/components/chat/header/useEscape"
import { useRunningConversations } from "@/components/chat/header/useRunningConversations"
import { strandLabel, useThreadContext } from "@/components/chat/header/useThreadContext"

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
  // Dashboard / close. (The spotlight aperture is the wing's EdgeLight: header/ChatEdge.)
  isDashboardOpen: boolean
  onDashboardClose?: () => void
  onDashboardClick: () => void
  onClose: () => void
  // Notifications dropdown
  showNotifications: boolean
  openNotifications: () => void
  unreadCount: number
  closeDropdowns: () => void
  // Threads and strands. A strand IS a conversation id.
  activeConversationId: string | null
  /** Title shown until the thread list answers (and for a conversation it does not list). */
  fallbackTitle?: string
  onNewThread: () => void
  onOpenConversation: (conversationId: string) => void
}

type Overlay = "orbit" | "map" | "menu" | null

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
  onClose,
  showNotifications,
  openNotifications,
  unreadCount,
  closeDropdowns,
  activeConversationId,
  fallbackTitle,
  onNewThread,
  onOpenConversation,
}: ChatHeaderProps) {
  const palette = useBrandPalette()
  const ctx = useThreadContext(activeConversationId)
  const running = useRunningConversations()
  const [overlay, setOverlay] = useState<Overlay>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState("")
  const renameDone = useRef(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const headH = isRemoteView ? 60 : 52
  const touch = isRemoteView ? " touch" : ""

  const closeOverlay = useCallback(() => setOverlay(null), [])
  useEscape(overlay === "menu", closeOverlay)
  const cancelRename = useCallback(() => { renameDone.current = true; setEditing(false) }, [])
  useEscape(editing, cancelRename)

  // Click outside the menu closes it.
  useEffect(() => {
    if (overlay !== "menu") return
    const h = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node) && !(e.target as Element).closest?.("[data-menu-button]")) setOverlay(null)
    }
    document.addEventListener("mousedown", h)
    return () => document.removeEventListener("mousedown", h)
  }, [overlay])

  const toggle = (which: Exclude<Overlay, null>) => {
    closeDropdowns()
    setOverlay((o) => (o === which ? null : which))
  }

  const title = ctx.root?.title ?? fallbackTitle ?? "New thread"
  const canRename = !!ctx.root
  const startRename = () => { if (!canRename) return; renameDone.current = false; setDraft(title); setEditing(true) }
  const saveRename = () => {
    if (renameDone.current) return
    renameDone.current = true
    setEditing(false)
    const next = draft.trim()
    if (next && next !== title) ctx.rename(next).catch((e) => console.warn("[ChatHeader] rename failed:", e))
  }

  const otherStrandWorks = ctx.strands.some((s) => s.id !== activeConversationId && running.has(s.id))
  const rootId = ctx.root?.id ?? null

  const openThread = (t: ThreadSummary) => { setOverlay(null); onOpenConversation(t.id) }
  const newThread = () => { setOverlay(null); onNewThread() }
  const switchStrand = (id: string) => { setOverlay(null); onOpenConversation(id) }
  const strandMade = async (s: Strand) => {
    await ctx.reloadStrands() // the new strand is in the list before it becomes the active one
    switchStrand(s.id)
  }

  const menuItem = (label: string, titleText: string, icon: React.ReactNode, run: () => void | Promise<void>, hint?: React.ReactNode) => (
    <button key={label} type="button" role="menuitem" title={titleText} onClick={() => { setOverlay(null); void run() }}>
      <span style={{ width: 16, display: "grid", placeItems: "center" }}>{icon}</span>
      {label}
      {hint ? <span className="k">{hint}</span> : null}
    </button>
  )

  return (
    <>
      <div
        ref={chatHeaderRef}
        onMouseDown={handleHeaderDragStart}
        className="iris-hd-head"
        style={{ ...brandVars(palette), height: headH, cursor: isRemoteView ? undefined : 'grab' }}
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

        {/* The brand Xur opens the thread orbit. It runs faster while IRIS listens or works. */}
        <button
          type="button"
          className="iris-hd-xbtn"
          title="Your threads"
          aria-label="Open your threads"
          aria-haspopup="dialog"
          aria-expanded={overlay === "orbit"}
          onClick={() => toggle("orbit")}
        >
          <Xur size={40} palette={palette} speed={voiceState === "idle" ? 1 : 1.8} />
        </button>

        <div className="iris-hd-ttl">
          {editing ? (
            <input
              autoFocus
              className="iris-hd-nameinput"
              aria-label="Thread name"
              value={draft}
              maxLength={120}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); saveRename() } }}
              onBlur={saveRename}
              onMouseDown={(e) => e.stopPropagation()}
            />
          ) : (
            <button
              type="button"
              className="iris-hd-name"
              style={{ color: fontColor }}
              title={canRename ? "Click to rename" : title}
              disabled={!canRename}
              onClick={startRename}
            >
              {title}
            </button>
          )}
          {ctx.current && (
            <button type="button" className="iris-hd-strandbtn" title="Strands of this thread" aria-label="Switch strand" onClick={() => toggle("map")}>
              <span style={{ color: palette[1] }}>◆</span>
              <b>{strandLabel(ctx.current, rootId)}</b>
              {ctx.current.tags.map((t) => <span key={t}>· {t}</span>)}
              {ctx.strands.length > 1 && <span>· {ctx.strands.length} strands</span>}
            </button>
          )}
        </div>

        <button
          type="button"
          className={`iris-hd-iconbtn${touch}`}
          title="Strands of this thread"
          aria-label="Strands of this thread"
          aria-haspopup="dialog"
          aria-expanded={overlay === "map"}
          disabled={!rootId}
          onClick={() => toggle("map")}
        >
          ⌖
          {otherStrandWorks && <i className="iris-hd-act" data-testid="strand-activity" role="img" aria-label="Another strand is working" style={{ background: "#f2c14e" }} />}
        </button>
        <button
          type="button"
          className={`iris-hd-iconbtn${touch}`}
          data-menu-button="true"
          title="More"
          aria-label="More"
          aria-haspopup="menu"
          aria-expanded={overlay === "menu"}
          onClick={() => toggle("menu")}
        >
          ◉
          {unreadCount > 0 && <i className="iris-hd-act" role="img" aria-label="Unread alerts" style={{ background: glowColor, animation: "none" }} />}
        </button>
      </div>

      {overlay === "menu" && (
        <div ref={menuRef} className="iris-hd-menu" role="menu" aria-label="Chat controls" style={{ ...brandVars(palette), top: headH }}>
          {menuItem(
            "Dashboard",
            isDashboardOpen ? "Close Dashboard" : "Open Dashboard",
            <BarChart3 size={14} style={{ color: isDashboardOpen ? glowColor : undefined }} />,
            () => {
              if (isDashboardOpen && onDashboardClose) onDashboardClose()
              else onDashboardClick()
              closeDropdowns()
            },
          )}
          {/* Detach / reattach. The chat wing becomes its own OS window so it can
              live on a second monitor — the widget window is transparent,
              borderless and always-on-top, and cannot span two screens.
              Detaching closes the wing here so it is never drawn twice;
              closing the detached window puts it back. */}
          {!isRemoteView && menuItem(
            isDetached ? "Put the chat back" : "Detach the wing",
            isDetached ? "Put chat back in the widget" : "Move chat to its own window",
            isDetached ? <Minimize2 size={14} /> : <Maximize2 size={14} />,
            async () => {
              if (isDetached) await reattachWing('chat')
              else if (await detachWing('chat')) onClose()
            },
          )}
          {menuItem(
            "Alerts",
            "Notifications",
            <Bell size={14} style={{ color: unreadCount > 0 ? glowColor : undefined }} />,
            () => { if (showNotifications) closeDropdowns(); else openNotifications() },
            unreadCount > 0 ? String(unreadCount) : "",
          )}
          {menuItem("Launcher", "Open IRIS Launcher", <ExternalLink size={14} />, () => openIrisLauncher())}
          {menuItem("Close", "Close Chat", <X size={14} />, () => { onClose(); closeDropdowns() }, "Esc")}
        </div>
      )}

      {overlay === "orbit" && (
        <ThreadOrbit palette={palette} activeThreadId={rootId} onOpen={openThread} onNew={newThread} onClose={closeOverlay} />
      )}

      {overlay === "map" && rootId && (
        <StrandMap
          threadId={rootId}
          palette={palette}
          activeId={activeConversationId}
          running={running}
          onSwitch={switchStrand}
          onCreated={strandMade}
          onClose={closeOverlay}
          top={headH}
        />
      )}
    </>
  )
}
