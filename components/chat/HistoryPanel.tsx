"use client"

import React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Plus, Trash2, Pin } from 'lucide-react'
import type { Conversation } from "@/components/chat-view"

export interface HistoryPanelProps {
  showHistory: boolean
  prefersReducedMotion: boolean
  glowColor: string
  fontColor: string
  conversations: Conversation[]
  activeConversationId: string | null
  handleNewConversation: () => void
  handleSelectConversation: (conversationId: string) => void
  handlePinConversation: (e: React.MouseEvent, conversationId: string) => void
  handleDeleteConversation: (e: React.MouseEvent, conversationId: string) => void
}

export function HistoryPanel({
  showHistory,
  prefersReducedMotion,
  glowColor,
  fontColor,
  conversations,
  activeConversationId,
  handleNewConversation,
  handleSelectConversation,
  handlePinConversation,
  handleDeleteConversation,
}: HistoryPanelProps) {
  return (
      <AnimatePresence>
        {showHistory && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: prefersReducedMotion ? 0 : 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden border-b flex-shrink-0 z-20"
            style={{
              borderColor: `${glowColor}10`,
              background: 'linear-gradient(180deg, rgba(10,10,20,0.98) 0%, rgba(10,10,20,0.9) 100%)',
              backdropFilter: 'blur(20px)',
              // Live fix 2026-09-04: maxHeight '50%' never constrained —
              // a percentage resolves against an indefinite flex parent
              // (height animates to auto), so 778 rows grew past the panel,
              // clipped under overflow-hidden ancestors, and the wheel
              // chained to the main timeline. A viewport-relative cap always
              // resolves, so the inner list below can actually scroll.
              maxHeight: 'min(46vh, 520px)',
            }}
          >
            <div
              className="p-3 space-y-2 overflow-y-auto"
              style={{
                // Inherit the panel cap so this box is bounded even when its
                // content is 778 rows tall; containment stops the wheel from
                // scrolling the conversation thread behind the dropdown.
                maxHeight: 'inherit',
                overscrollBehavior: 'contain',
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-semibold tracking-widest uppercase text-white/50">
                  Conversation Threads
                </span>
                <div className="flex items-center gap-2">
                  <span className="text-[9px] text-white/30">
                    {conversations.length} total
                  </span>
                  <button
                    onClick={handleNewConversation}
                    className="p-1.5 rounded transition-all duration-150 flex items-center gap-1"
                    style={{ color: `${fontColor}50` }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.color = glowColor;
                      e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.color = `${fontColor}50`;
                      e.currentTarget.style.backgroundColor = 'transparent';
                    }}
                    title="Start new conversation"
                    aria-label="New conversation"
                  >
                    <Plus size={12} />
                  </button>
                </div>
              </div>
              
              {conversations.length === 0 ? (
                <div className="text-center py-6 text-[11px] text-white/40">
                  No conversations yet
                </div>
              ) : (
                conversations.map((conv) => (
                  <motion.div
                    key={conv.id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    onClick={() => handleSelectConversation(conv.id)}
                    className="group relative p-2.5 rounded-lg cursor-pointer transition-all duration-150 hover:bg-white/5"
                    style={{
                      backgroundColor: activeConversationId === conv.id ? `${glowColor}15` : 'rgba(255,255,255,0.03)',
                      borderLeft: `2px solid ${activeConversationId === conv.id ? glowColor : 'transparent'}`,
                      // 778 rows: skip off-screen row rendering work. The
                      // intrinsic size keeps the scrollbar stable while rows
                      // are skipped; highlight + buttons unaffected.
                      contentVisibility: 'auto',
                      containIntrinsicSize: 'auto 76px',
                    }}
                  >
                    <div className="flex items-center gap-2">
                      {/* Content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 mb-1">
                          {conv.isPinned && (
                            <Pin size={10} style={{ color: glowColor }} className="fill-current flex-shrink-0" />
                          )}
                          <span className="text-[10px] font-medium text-white/90 truncate">
                            {conv.title}
                          </span>
                          <span className="text-[8px] text-white/30 tabular-nums flex-shrink-0">
                            {conv.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                          </span>
                        </div>
                        <p className="text-[9px] text-white/50 truncate leading-snug">
                          {conv.lastMessagePreview}
                          {conv.lastMessagePreview.length >= 60 ? '...' : ''}
                        </p>
                        <span className="text-[8px] text-white/30 mt-1 block">
                          {conv.messages.length} message{conv.messages.length !== 1 ? 's' : ''}
                        </span>
                      </div>
                      
                      {/* Action buttons - centered on right */}
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 self-center">
                        <button
                          onClick={(e) => handlePinConversation(e, conv.id)}
                          className="p-1.5 rounded transition-colors hover:bg-white/10"
                          style={{ color: conv.isPinned ? glowColor : 'rgba(255,255,255,0.5)' }}
                          title={conv.isPinned ? 'Unpin' : 'Pin to top'}
                        >
                          <Pin size={12} className={conv.isPinned ? 'fill-current' : ''} />
                        </button>
                        <button
                          onClick={(e) => handleDeleteConversation(e, conv.id)}
                          className="p-1.5 rounded transition-colors hover:bg-white/10 text-white/50 hover:text-red-400"
                          title="Delete conversation"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                  </motion.div>
                ))
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
  )
}
