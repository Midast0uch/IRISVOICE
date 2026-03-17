"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X, Bell, MessageSquare, AlertTriangle, Shield, Loader, CheckCircle, Info, AlertCircle, LayoutDashboard, Activity, FileText, Store, Globe, RotateCcw, ArrowLeft, ArrowRight as ArrowRightIcon, Home, ExternalLink, History } from 'lucide-react'
import { DarkGlassDashboard } from "./dark-glass-dashboard"
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

interface DashboardWingProps {
  isOpen: boolean
  onClose: () => void
  sendMessage?: SendMessageFunction
  fieldValues?: Record<string, any>
  updateField?: (sectionId: string, fieldId: string, value: any) => void
  spotlightState?: SpotlightState
  onSpotlightToggle?: () => void
  isSolo?: boolean
  uiState?: UILayoutState
  onOpenChat?: () => void
  isChatOpen?: boolean
}

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
}: DashboardWingProps) {
  const { voiceState } = useNavigation()
  const { getThemeConfig } = useBrandColor()
  
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
    if (isInDashboardSpotlight) return 760; // Spotlight width (2×)
    if (isSolo) return 560; // Solo balanced width (2×)
    if (isInChatSpotlight) return 360; // Background width when chat is spotlighted (2×)
    return 560; // Balanced width (2×)
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
            right: 252,
            top: '50%',
            width: getSpotlightWidth(),
            height: '88vh',
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
              backdropFilter: 'blur(40px)',
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
              }}
            />

            {/* Spotlight Iris Aperture Button - TOP CENTER (Mirroring ChatView) */}
            <div className="flex items-start justify-center absolute left-1/2 -translate-x-1/2 z-50" style={{ top: '-16px' }}>
              <button
                onClick={onSpotlightToggle}
                className="p-3 rounded-full transition-all duration-150 border shadow-lg"
                style={{ 
                  color: isInDashboardSpotlight ? glowColor : 'rgba(255,255,255,0.4)',
                  backgroundColor: isInDashboardSpotlight ? `${glowColor}25` : 'rgba(10,10,20,0.98)',
                  borderColor: `${glowColor}30`,
                  boxShadow: `0 -2px 10px rgba(0,0,0,0.5), 0 0 20px ${isInDashboardSpotlight ? glowColor : 'transparent'}40`,
                  backdropFilter: 'blur(10px)'
                }}
                onMouseEnter={(e) => {
                  if (!isInDashboardSpotlight) e.currentTarget.style.color = 'white';
                  e.currentTarget.style.backgroundColor = 'rgba(20,20,35,0.98)';
                  e.currentTarget.style.borderColor = `${glowColor}60`;
                }}
                onMouseLeave={(e) => {
                  if (!isInDashboardSpotlight) e.currentTarget.style.color = 'rgba(255,255,255,0.4)';
                  e.currentTarget.style.backgroundColor = isInDashboardSpotlight ? `${glowColor}25` : 'rgba(10,10,20,0.98)';
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
            </div>
            
            {/* Dashboard Content - Fully delegated to DarkGlassDashboard */}
            <div className="flex-1 overflow-hidden relative z-10">
              <DarkGlassDashboard
                fieldValues={fieldValues}
                updateField={updateField}
                onClose={onClose}
                unreadCount={unreadCount}
                onNotificationsClick={() => setShowNotifications(true)}
                spotlightState={spotlightState}
                uiState={uiState}
                onOpenChat={onOpenChat}
              />
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default DashboardWing
