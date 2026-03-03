"use client"

import React, { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X, Bell, AlertTriangle, Shield, Loader, CheckCircle, Info, AlertCircle } from 'lucide-react'
import { DarkGlassDashboard } from "./dark-glass-dashboard"
import { useNavigation } from "@/contexts/NavigationContext"
import { SendMessageFunction } from "@/hooks/useIRISWebSocket"

// Notification types for the universal notification system
interface Notification {
  id: string;
  type: 'alert' | 'permission' | 'error' | 'task' | 'completion';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
  progress?: number;
}

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

interface DashboardWingProps {
  isOpen: boolean
  onClose: () => void
  sendMessage?: SendMessageFunction
  fieldValues?: Record<string, any>
  updateField?: (subnodeId: string, fieldId: string, value: any) => void
}

export function DashboardWing({ 
  isOpen, 
  onClose, 
  sendMessage, 
  fieldValues, 
  updateField 
}: DashboardWingProps) {
  const { activeTheme, voiceState } = useNavigation()
  
  // Notification system state (mirrors ChatWing)
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  
  // Get theme colors with fallback
  const glowColor = activeTheme?.glow || "#00d4ff"
  const fontColor = activeTheme?.font || "#ffffff"
  
  // Global error state
  const globalError = voiceState === 'error';

  // Keyboard navigation - Escape to close
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        // Close notifications if open, otherwise close dashboard
        if (showNotifications) {
          setShowNotifications(false);
        } else {
          onClose();
        }
      }
    };
    
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [isOpen, showNotifications, onClose]);

  // Calculate unread count when notifications change
  useEffect(() => {
    setUnreadCount(notifications.filter(n => !n.read).length);
  }, [notifications]);

  // Mark all as read when notification panel opens
  useEffect(() => {
    if (showNotifications) {
      setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    }
  }, [showNotifications]);

  // Permission response handlers
  const handlePermissionGrant = (notificationId: string) => {
    sendMessage?.('notification_response', { 
      notification_id: notificationId, 
      action: 'grant' 
    });
    setNotifications(prev => prev.filter(n => n.id !== notificationId));
  };

  const handlePermissionDeny = (notificationId: string) => {
    sendMessage?.('notification_response', { 
      notification_id: notificationId, 
      action: 'deny' 
    });
    setNotifications(prev => prev.filter(n => n.id !== notificationId));
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed z-[10]"
          initial={{ x: 120, opacity: 0, scale: 0.95 }}
          animate={{ x: 0, opacity: 1, scale: 1 }}
          exit={{ x: 120, opacity: 0, scale: 0.95 }}
          transition={{ 
            type: "spring", 
            stiffness: 280, 
            damping: 25,
            mass: 0.8
          }}
          style={{ 
            right: '3%',
            top: '50%',
            width: '280px',
            height: '50vh',
            perspective: '800px',
          }}
        >
          {/* HUD Glass Panel Container */}
          <div 
            className="h-full overflow-hidden flex flex-col relative"
            style={{
              transform: 'translateY(-50%) rotateY(-15deg) rotateX(2deg)',
              transformOrigin: 'right center',
              transformStyle: 'preserve-3d',
              background: 'linear-gradient(225deg, rgba(10,10,20,0.95) 0%, rgba(5,5,10,0.98) 100%)',
              boxShadow: `
                inset 0 1px 1px rgba(255,255,255,0.05),
                inset 0 -1px 1px rgba(0,0,0,0.5),
                0 0 0 1px rgba(0,0,0,0.8),
                -20px 0 60px rgba(0,0,0,0.5)
              `,
              borderRadius: '12px',
              border: `1px solid ${glowColor}20`,
            }}
          >
            {/* HUD Effects Overlay */}
            <div 
              className="absolute inset-0 pointer-events-none z-10"
              style={{
                background: `
                  linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.02) 50%, transparent 100%),
                  repeating-linear-gradient(
                    0deg,
                    transparent,
                    transparent 2px,
                    rgba(0,0,0,0.03) 2px,
                    rgba(0,0,0,0.03) 4px
                  )
                `,
                backgroundSize: '100% 100%, 100% 4px',
              }}
            />
            
            {/* Edge Fresnel Effect */}
            <div 
              className="absolute inset-0 pointer-events-none z-20"
              style={{
                background: `
                  linear-gradient(90deg, ${glowColor}08 0%, transparent 15%, transparent 85%, ${glowColor}08 100%),
                  linear-gradient(0deg, ${glowColor}05 0%, transparent 20%, transparent 80%, ${glowColor}05 100%)
                `,
                borderRadius: '12px',
              }}
            />

            {/* 48px Header */}
            <div 
              className="h-12 px-3 flex items-center justify-between flex-shrink-0 border-b relative z-30"
              style={{ borderColor: `${glowColor}15` }}
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
              
              <div className="flex items-center gap-2">
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
                  Dashboard
                </span>
              </div>
              
              <div className="flex items-center gap-0.5">
                {/* Notifications */}
                <button
                  onClick={() => setShowNotifications(!showNotifications)}
                  className="p-2 rounded-lg transition-all duration-150 relative"
                  style={{ 
                    color: showNotifications ? glowColor : unreadCount > 0 ? glowColor : `${fontColor}60`,
                    backgroundColor: showNotifications ? `${glowColor}15` : 'transparent'
                  }}
                  onMouseEnter={(e) => {
                    if (!showNotifications) e.currentTarget.style.color = unreadCount > 0 ? glowColor : `${fontColor}90`;
                    e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                  }}
                  onMouseLeave={(e) => {
                    if (!showNotifications) e.currentTarget.style.color = unreadCount > 0 ? glowColor : `${fontColor}60`;
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
                
                {/* Close */}
                <button
                  onClick={onClose}
                  className="p-2 rounded-lg transition-all duration-150"
                  style={{ color: `${fontColor}60` }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = `${fontColor}90`;
                    e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = `${fontColor}60`;
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                  title="Close Dashboard"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Notification Dropdown Panel */}
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
                    maxHeight: '50%'
                  }}
                >
                  <div className="p-3 space-y-2 overflow-y-auto">
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

            {/* Dashboard Content */}
            <div className="flex-1 overflow-hidden relative z-10">
              <DarkGlassDashboard 
                fieldValues={fieldValues}
                updateField={updateField}
              />
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default DashboardWing
