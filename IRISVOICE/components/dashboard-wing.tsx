"use client"

import React, { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X, Bell, MessageSquare, AlertTriangle, Shield, Loader, CheckCircle, Info, AlertCircle, LayoutDashboard, Activity, FileText, Store } from 'lucide-react'
import { DarkGlassDashboard } from "./dark-glass-dashboard"
import { ActivityPanel } from "./dashboard/ActivityPanel"
import { LogsPanel } from "./dashboard/LogsPanel"
import { MarketplaceScreen } from "./integrations/MarketplaceScreen"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { SendMessageFunction } from "@/hooks/useIRISWebSocket"
import { IrisApertureIcon } from "@/components/ui/IrisApertureIcon"
import { SpotlightState, UILayoutState } from "@/hooks/useUILayoutState"

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

export type DashboardTab = 'dashboard' | 'activity' | 'logs' | 'marketplace';

interface DashboardWingProps {
  isOpen: boolean
  onClose: () => void
  sendMessage?: SendMessageFunction
  fieldValues?: Record<string, any>
  updateField?: (sectionId: string, fieldId: string, value: any) => void
  // Spotlight Mode props
  spotlightState?: SpotlightState
  onSpotlightToggle?: () => void
  // Solo mode props
  isSolo?: boolean
  uiState?: UILayoutState
  // Chat open callback
  onOpenChat?: () => void
  isChatOpen?: boolean
  // Tab navigation
  activeTab?: DashboardTab
  onTabChange?: (tab: DashboardTab) => void
}

const TABS: { id: DashboardTab; label: string; icon: React.ElementType }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'activity', label: 'Activity', icon: Activity },
  { id: 'logs', label: 'Logs', icon: FileText },
  { id: 'marketplace', label: 'Marketplace', icon: Store },
];

export function DashboardWing({
  isOpen,
  onClose,
  sendMessage,
  fieldValues,
  updateField,
  spotlightState = SpotlightState.BALANCED,
  onSpotlightToggle,
  isSolo = false,
  uiState,
  onOpenChat,
  isChatOpen = false,
  activeTab: controlledActiveTab,
  onTabChange,
}: DashboardWingProps) {
  const { voiceState } = useNavigation()
  const { getThemeConfig } = useBrandColor()
  
  // Tab state (controlled or uncontrolled)
  const [internalActiveTab, setInternalActiveTab] = useState<DashboardTab>('dashboard');
  const activeTab = controlledActiveTab ?? internalActiveTab;
  
  const handleTabChange = (tab: DashboardTab) => {
    if (onTabChange) {
      onTabChange(tab);
    } else {
      setInternalActiveTab(tab);
    }
  };
  
  // Notification system state (mirrors ChatWing)
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  
  // Get theme colors from BrandColorContext for real-time updates
  const brandTheme = getThemeConfig()
  const glowColor = brandTheme.glow.color || "#00d4ff"
  const fontColor = brandTheme.text.primary || "#ffffff"
  
  // Global error state
  const globalError = voiceState === 'error';

  // Spotlight Mode derived states
  const isInDashboardSpotlight = spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT;
  const isInChatSpotlight = spotlightState === SpotlightState.CHAT_SPOTLIGHT;
  const isBalanced = spotlightState === SpotlightState.BALANCED;

  // Spotlight dynamic styles
  const getSpotlightWidth = () => {
    if (isInDashboardSpotlight) return 380; // Spotlight width (works in solo and both-open)
    if (isSolo) return 280; // Solo balanced width
    if (isInChatSpotlight) return 180; // Background width when chat is spotlighted
    return 280; // Balanced width
  };

  const getSpotlightTransform = () => {
    if (isInDashboardSpotlight) return 'translateY(-50%) rotateY(0deg) rotateX(0deg)'; // Flat when spotlighted
    if (isSolo) return 'translateY(-50%) rotateY(-15deg) rotateX(2deg)'; // Solo balanced: angled
    if (isInChatSpotlight) return 'translateY(-50%) rotateY(-15deg) rotateX(2deg)';
    return 'translateY(-50%) rotateY(-15deg) rotateX(2deg)';
  };

  const getSpotlightOpacity = () => {
    if (isSolo) return 1.0; // Solo: full opacity
    if (isInChatSpotlight) return 0.3;
    return 1.0;
  };

  const getSpotlightFilter = () => {
    if (isSolo) return 'none'; // Solo: no filter
    if (isInChatSpotlight) return 'saturate(0.6) blur(2px)';
    return 'none';
  };

  const getSpotlightZIndex = () => {
    if (isSolo) return 10; // Solo: normal z-index
    if (isInDashboardSpotlight) return 20;
    if (isInChatSpotlight) return 5;
    return 10;
  };

  const getSpotlightPointerEvents = () => {
    if (isSolo) return 'auto'; // Solo: always interactive
    if (isInChatSpotlight) return 'none';
    return 'auto';
  };

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
          className="fixed"
          initial={{ x: 120, opacity: 0, scale: 0.95 }}
          animate={{ 
            x: 0, 
            opacity: getSpotlightOpacity(), 
            scale: 1 
          }}
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
            width: getSpotlightWidth(),
            height: '50vh',
            perspective: '800px',
            zIndex: getSpotlightZIndex(),
            filter: getSpotlightFilter(),
            pointerEvents: getSpotlightPointerEvents() as any,
          }}
        >
          {/* HUD Glass Panel Container */}
          <motion.div 
            className="h-full overflow-hidden flex flex-col relative"
            animate={{
              transform: getSpotlightTransform()
            }}
            transition={{
              type: "spring",
              stiffness: 280,
              damping: 25,
              mass: 0.8
            }}
            style={{
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
              className="h-12 px-3 flex items-center flex-shrink-0 border-b relative z-30"
              style={{ borderColor: `${glowColor}15`, position: 'relative' }}
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
              
              {/* Left section: Pulse + Title */}
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
                  Dashboard
                </span>
              </div>

              {/* Center section: Spotlight Iris Aperture Button - positioned at top edge */}
              <div className="flex items-start justify-center absolute left-1/2 -translate-x-1/2" style={{ top: '-16px' }}>
                {onSpotlightToggle && (
                  <button
                    onClick={() => {
                      onSpotlightToggle();
                      setShowNotifications(false);
                    }}
                    className="p-3 rounded-full transition-all duration-150 border shadow-lg"
                    style={{ 
                      color: isInDashboardSpotlight ? glowColor : `${fontColor}60`,
                      backgroundColor: isInDashboardSpotlight ? `${glowColor}20` : 'rgba(10,10,20,0.95)',
                      borderColor: `${glowColor}30`,
                      boxShadow: `0 -2px 10px rgba(0,0,0,0.5), 0 0 20px ${isInDashboardSpotlight ? glowColor : 'transparent'}40`,
                      backdropFilter: 'blur(10px)'
                    }}
                    onMouseEnter={(e) => {
                      if (!isInDashboardSpotlight) e.currentTarget.style.color = `${fontColor}90`;
                      e.currentTarget.style.backgroundColor = 'rgba(20,20,35,0.98)';
                      e.currentTarget.style.borderColor = `${glowColor}60`;
                    }}
                    onMouseLeave={(e) => {
                      if (!isInDashboardSpotlight) e.currentTarget.style.color = `${fontColor}60`;
                      e.currentTarget.style.backgroundColor = isInDashboardSpotlight ? `${glowColor}20` : 'rgba(10,10,20,0.95)';
                      e.currentTarget.style.borderColor = `${glowColor}30`;
                    }}
                    title={isInDashboardSpotlight ? "Restore balanced view" : "Maximize dashboard"}
                  >
                    <IrisApertureIcon 
                      isActive={isInDashboardSpotlight} 
                      glowColor={glowColor} 
                      fontColor={fontColor}
                      size={20}
                    />
                  </button>
                )}
              </div>
              
              {/* Right section: Notifications + Close */}
              <div className="flex items-center gap-0.5 flex-1 justify-end">
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
                
                {/* Open Chat - visible in solo mode or when chat is closed */}
                {onOpenChat && !isChatOpen && (
                  <button
                    onClick={() => {
                      onOpenChat();
                      setShowNotifications(false);
                    }}
                    className="p-2 rounded-lg transition-all duration-150"
                    style={{ 
                      color: glowColor,
                      backgroundColor: 'transparent'
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.color = fontColor;
                      e.currentTarget.style.backgroundColor = `${glowColor}20`;
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.color = glowColor;
                      e.currentTarget.style.backgroundColor = 'transparent';
                    }}
                    title="Open Chat"
                  >
                    <MessageSquare size={16} />
                  </button>
                )}
                
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

            {/* Tab Navigation Bar - 32px height */}
            <div
              className="h-8 flex items-center px-2 border-b flex-shrink-0 relative z-30"
              style={{ borderColor: `${glowColor}15` }}
            >
              {TABS.map((tab) => {
                const isActive = activeTab === tab.id;
                const Icon = tab.icon;
                return (
                  <button
                    key={tab.id}
                    onClick={() => handleTabChange(tab.id)}
                    className="relative flex-1 h-full flex items-center justify-center gap-1.5 text-[11px] font-medium transition-all duration-150"
                    style={{
                      color: isActive ? glowColor : `${fontColor}50`,
                    }}
                    onMouseEnter={(e) => {
                      if (!isActive) e.currentTarget.style.color = `${fontColor}80`;
                    }}
                    onMouseLeave={(e) => {
                      if (!isActive) e.currentTarget.style.color = `${fontColor}50`;
                    }}
                  >
                    <Icon size={12} />
                    <span>{tab.label}</span>
                    {isActive && (
                      <motion.div
                        layoutId="activeTab"
                        className="absolute bottom-0 left-1 right-1 h-[2px] rounded-t"
                        style={{
                          background: glowColor,
                          boxShadow: `0 -2px 8px ${glowColor}60`,
                        }}
                        transition={{
                          type: "spring",
                          stiffness: 400,
                          damping: 30,
                        }}
                      />
                    )}
                  </button>
                );
              })}
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

            {/* Dashboard Content - Tab Switching */}
            <div className="flex-1 overflow-hidden relative z-10">
              <AnimatePresence mode="wait">
                {activeTab === 'dashboard' && (
                  <motion.div
                    key="dashboard"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    transition={{ duration: 0.2 }}
                    className="h-full"
                  >
                    <DarkGlassDashboard
                      fieldValues={fieldValues}
                      updateField={updateField}
                    />
                  </motion.div>
                )}
                
                {activeTab === 'activity' && (
                  <motion.div
                    key="activity"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    transition={{ duration: 0.2 }}
                    className="h-full"
                  >
                    <ActivityPanel
                      glowColor={glowColor}
                      fontColor={fontColor}
                    />
                  </motion.div>
                )}
                
                {activeTab === 'logs' && (
                  <motion.div
                    key="logs"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    transition={{ duration: 0.2 }}
                    className="h-full"
                  >
                    <LogsPanel
                      glowColor={glowColor}
                      fontColor={fontColor}
                    />
                  </motion.div>
                )}
                
                {activeTab === 'marketplace' && (
                  <motion.div
                    key="marketplace"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    transition={{ duration: 0.2 }}
                    className="h-full"
                  >
                    <MarketplaceScreen
                      glowColor={glowColor}
                      fontColor={fontColor}
                    />
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default DashboardWing
