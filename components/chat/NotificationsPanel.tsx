"use client"

import React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { AlertTriangle, Shield, AlertCircle, Loader, CheckCircle, Info } from 'lucide-react'
import type { Notification } from "@/components/chat-view"

// Helper functions for notification styling
const getNotificationColor = (type: string, glowColor: string): string => {
  switch (type) {
    case 'alert': return '#fbbf24'; // amber
    case 'permission': return '#3b82f6'; // blue
    case 'error': return '#ef4444'; // red
    case 'task': return '#a855f7'; // purple
    case 'completion': return '#22c55e'; // green
    default: return glowColor;
  }
};

const getNotificationIcon = (type: string, glowColor: string) => {
  const iconProps = { size: 10, style: { color: getNotificationColor(type, glowColor) } };
  switch (type) {
    case 'alert': return <AlertTriangle {...iconProps} />;
    case 'permission': return <Shield {...iconProps} />;
    case 'error': return <AlertCircle {...iconProps} />;
    case 'task': return <Loader {...iconProps} className="animate-spin" />;
    case 'completion': return <CheckCircle {...iconProps} />;
    default: return <Info {...iconProps} />;
  }
};

export interface NotificationsPanelProps {
  showNotifications: boolean
  glowColor: string
  notifications: Notification[]
  setNotifications: React.Dispatch<React.SetStateAction<Notification[]>>
  unreadCount: number
  handlePermissionGrant: (notificationId: string) => void
  handlePermissionDeny: (notificationId: string) => void
}

export function NotificationsPanel({
  showNotifications,
  glowColor,
  notifications,
  setNotifications,
  unreadCount,
  handlePermissionGrant,
  handlePermissionDeny,
}: NotificationsPanelProps) {
  return (
      <AnimatePresence>
        {showNotifications && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden border-b flex-shrink-0 z-20"
            style={{
              borderColor: `${glowColor}10`,
              background: 'linear-gradient(180deg, rgba(10,10,20,0.98) 0%, rgba(10,10,20,0.9) 100%)',
              backdropFilter: 'blur(20px)',
              // REQ-3/T5: same latent bug the history dropdown had — a
              // percentage max-height against an indefinite `height:auto`
              // parent never constrains, so the list grows past the panel
              // and the wheel chains to the timeline instead. Viewport
              // unit resolves against the window, which is definite.
              maxHeight: 'min(46vh, 520px)'
            }}
          >
            {/* REQ-4 AC1: trap the wheel so scrolling notifications never
                scrolls the conversation behind it. */}
            <div
              className="p-3 space-y-2 overflow-y-auto"
              style={{ maxHeight: 'inherit', overscrollBehavior: 'contain' }}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-semibold tracking-widest uppercase text-white/50">
                  Notifications
                </span>
                {notifications.length > 0 && (
                  <button
                    onClick={() => setNotifications([])}
                    className="text-[9px] px-2 py-1 rounded transition-colors text-white/40 hover:text-white/70 hover:bg-white/5"
                  >
                    Clear all
                  </button>
                )}
              </div>
              
              {notifications.length === 0 ? (
                <div className="text-center py-6 text-[11px] text-white/40">
                  No notifications
                </div>
              ) : (
                notifications.map((notif) => (
                  <motion.div
                    key={notif.id}
                    initial={{ x: unreadCount > 0 && !notif.read ? -10 : 0, opacity: 0 }}
                    animate={{ x: 0, opacity: 1 }}
                    className="p-2.5 rounded-lg transition-all duration-150 group relative overflow-hidden"
                    style={{
                      backgroundColor: !notif.read ? `${glowColor}08` : 'rgba(255,255,255,0.03)',
                      borderLeft: `2px solid ${getNotificationColor(notif.type, glowColor)}`
                    }}
                  >
                    {/* Type indicator glow */}
                    <div 
                      className="absolute top-0 right-0 w-16 h-16 opacity-10 blur-xl rounded-full -translate-y-1/2 translate-x-1/2"
                      style={{ backgroundColor: getNotificationColor(notif.type, glowColor) }}
                    />
                    
                    <div className="flex items-start justify-between relative">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 mb-1">
                          {getNotificationIcon(notif.type, glowColor)}
                          <span 
                            className="text-[9px] font-semibold tracking-wide uppercase"
                            style={{ color: getNotificationColor(notif.type, glowColor) }}
                          >
                            {notif.type}
                          </span>
                          <span className="text-[8px] text-white/30 tabular-nums ml-auto">
                            {notif.timestamp.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                          </span>
                        </div>
                        <p className="text-[11px] font-medium text-white/90 leading-snug">
                          {notif.title}
                        </p>
                        <p className="text-[10px] text-white/60 mt-0.5 line-clamp-2">
                          {notif.message}
                        </p>
                      </div>
                    </div>
                    
                    {/* Action buttons based on type */}
                    {notif.type === 'permission' && (
                      <div className="flex gap-2 mt-2">
                        <button
                          onClick={() => handlePermissionGrant(notif.id)}
                          className="flex-1 py-1 rounded text-[9px] font-medium transition-colors"
                          style={{ 
                            background: `${glowColor}20`,
                            color: glowColor
                          }}
                        >
                          Allow
                        </button>
                        <button
                          onClick={() => handlePermissionDeny(notif.id)}
                          className="flex-1 py-1 rounded text-[9px] font-medium transition-colors bg-white/10 text-white/70 hover:bg-white/15"
                        >
                          Deny
                        </button>
                      </div>
                    )}
                    
                    {notif.type === 'task' && (
                      <div className="mt-2">
                        <div className="h-1 bg-white/10 rounded-full overflow-hidden">
                          <motion.div 
                            className="h-full rounded-full"
                            style={{ backgroundColor: glowColor }}
                            initial={{ width: 0 }}
                            animate={{ width: `${notif.progress || 0}%` }}
                          />
                        </div>
                        <span className="text-[8px] text-white/40 mt-1 block">
                          {notif.progress || 0}% complete
                        </span>
                      </div>
                    )}
                  </motion.div>
                ))
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
  )
}
