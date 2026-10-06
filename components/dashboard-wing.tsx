"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X, Bell, MessageSquare, AlertTriangle, Shield, Loader, CheckCircle, Info, AlertCircle, LayoutDashboard, Activity, FileText, Store, Globe, RotateCcw, ArrowLeft, ArrowRight as ArrowRightIcon, Home, ExternalLink, History } from 'lucide-react'
import { DarkGlassDashboard } from "./dark-glass-dashboard"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { SendMessageFunction } from "@/hooks/useIRISWebSocket"
import { EdgeLight } from "@/components/chrome/EdgeLight"
import { EdgeTrail } from "@/components/chrome/EdgeTrail"
import { useBrandPalette } from "@/hooks/useBrandPalette"
import { withAlpha, type Palette } from "@/lib/brandPalette"
import { SpotlightState, UILayoutState } from "@/hooks/useUILayoutState"
import { useLauncherMode } from "@/hooks/useLauncherMode"
import {
  computeFrame,
  dashboardWidth,
  frameLeft,
  TILT_DEG,
  type SpotlightStr,
} from "@/lib/orbWingGeometry"

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
  isBothOpen?: boolean
  initialSubApp?: string | null
  isRemoteView?: boolean
  orbDiameter?: number
  /**
   * This wing is alone in its own detached window (?pane=dashboard). It fills
   * that window flat. Distinct from isRemoteView, which also means "phone".
   */
  isDetached?: boolean
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
  isBothOpen = false,
  initialSubApp,
  isRemoteView = false,
  orbDiameter = 175,
  isDetached = false,
}: DashboardWingProps) {
  const { voiceState } = useNavigation()
  const { getThemeConfig } = useBrandColor()
  const { isDeveloper } = useLauncherMode()

  // Notification system state (mirrors ChatWing)
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);

  // Crawler (web search) live progress is owned by DarkGlassDashboard and
  // rendered as a pill in the CENTRE of its header. It used to live here as a
  // full-width band stacked ABOVE the header, which is the only place this
  // component can put it — the header itself belongs to the dashboard.

  // Window width for responsive both-open layout
  const [windowWidth, setWindowWidth] = useState(1280);
  useEffect(() => {
    setWindowWidth(window.innerWidth);
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Get theme colors from BrandColorContext for real-time updates
  const brandTheme = getThemeConfig()
  const glowColor = brandTheme.glow.color || "#00d4ff"
  const fontColor = brandTheme.text.primary || "#ffffff"
  const palette = useBrandPalette()
  // The concept draws the dashboard edge in the second hue (--b2) and the chat edge in the first.
  const edgePalette: Palette = [palette[1], palette[2], palette[0]]

  // Global error state
  const globalError = voiceState === 'error';

  // Spotlight Mode derived states
  const isInDashboardSpotlight = spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT;
  const isInChatSpotlight = spotlightState === SpotlightState.CHAT_SPOTLIGHT;
  const isBalanced = spotlightState === SpotlightState.BALANCED;

  // Both surfaces that render the wing edge-to-edge with no 3D: the phone
  // layout and a detached window.
  const isFlat = isRemoteView || isDetached;

  // Layout geometry — see lib/orbWingGeometry. The wing no longer computes its
  // own tilt, gap or orb radius; it asks the shared module for the frame and
  // pins itself to the frame's right edge.
  const BOTH_OPEN_TILT = TILT_DEG; // degrees

  const spotlightKey: SpotlightStr = isInChatSpotlight
    ? 'chatSpotlight'
    : isInDashboardSpotlight
      ? 'dashboardSpotlight'
      : 'balanced';
  const frame = computeFrame(
    isBothOpen || isChatOpen ? 'both_open' : 'dashboard_open',
    spotlightKey,
  );

  const getSpotlightWidth = () => (isDetached ? '100vw' : dashboardWidth(spotlightKey));

  // The dashboard wing is the RIGHT part of the frame, so it pins to the
  // frame's right edge in every wing state. In Tauri the window is exactly the
  // frame, so this is 0; in a browser the frame is centred in the viewport.
  //
  // This replaces four special cases (0 / 80 / 252 / a windowWidth-relative
  // formula). The 252 px case is what the user saw as "wings too far apart".
  const getOuterRight = () => {
    if (isFlat) return 0;
    return frameLeft(windowWidth, frame.width);
  };

  const getSpotlightTransform = () => {
    if (isFlat) return 'rotateY(0deg) rotateX(0deg)'; // Flat on mobile and when detached
    if (isInDashboardSpotlight) return 'rotateY(0deg) rotateX(0deg)'; // Flat when spotlighted
    if (isSolo) return 'rotateY(-15deg) rotateX(2deg)'; // Solo balanced: angled
    if (isInChatSpotlight) return 'rotateY(-15deg) rotateX(2deg)';
    if (isBothOpen) return `rotateY(-${BOTH_OPEN_TILT}deg) rotateX(2deg)`; // Both open: tilted divider
    return 'rotateY(-15deg) rotateX(2deg)';
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
          initial={isFlat ? {} : { x: 120, opacity: 0, scale: 0.95 }}
          animate={isFlat ? {} : { 
            x: 0, 
            opacity: getSpotlightOpacity(), 
            scale: 1 
          }}
          exit={isFlat ? {} : { x: 120, opacity: 0, scale: 0.95 }}
          transition={isFlat ? { duration: 0 } : { 
            type: "spring", 
            stiffness: 280, 
            damping: 25,
            mass: 0.8
          }}
          style={{
            left: isFlat ? 0 : undefined,
            right: isFlat ? 0 : getOuterRight(),
            top: isFlat ? 0 : '6vh',
            width: isFlat ? '100vw' : getSpotlightWidth(),
            height: isDetached ? '100vh' : isRemoteView ? '100dvh' : '88vh',
            maxHeight: isDetached ? '100vh' : isRemoteView ? '100dvh' : 'calc(100vh - 24px)',
            // overflow stays clipped on three sides; the top reaches 14 px up so
            // the aperture set into the top edge is whole, not cut in half.
            clipPath: 'inset(-14px 0 0 0)',
            perspective: isFlat ? 'none' : '800px',
            zIndex: getSpotlightZIndex(),
            filter: getSpotlightFilter(),
            pointerEvents: getSpotlightPointerEvents() as any,
            touchAction: 'manipulation',
            willChange: 'auto',
          }}
        >
          {/* HUD Glass Panel Container */}
            <motion.div 
              className="h-full overflow-hidden flex flex-col relative"
              animate={isFlat ? {} : {
                transform: getSpotlightTransform()
              }}
              transition={isFlat ? { duration: 0 } : {
                type: "spring",
                stiffness: 280,
                damping: 25,
                mass: 0.8
              }}
              style={{
                transformOrigin: 'right center',
                transformStyle: isFlat ? 'flat' : 'preserve-3d',
                transform: isFlat ? 'rotateY(0deg) rotateX(0deg)' : undefined,
                // The approved ink ground with a faint brand radial (concept `.dash`).
                background: `radial-gradient(120% 50% at 100% 0%, ${withAlpha(palette[1], 0.07)}, transparent 60%), #04050c`,
                boxShadow: isFlat ? 'none' : `
                  inset 0 -1px 1px rgba(0,0,0,0.5),
                  0 0 0 1px rgba(0,0,0,0.8)
                `,
                borderRadius: isFlat ? '0px' : '12px',
                // The top border is the EdgeLight hairline, so it is transparent here.
                border: isFlat ? 'none' : `1px solid ${withAlpha(palette[1], 0.2)}`,
                borderTopColor: isFlat ? undefined : 'transparent',
                touchAction: 'manipulation',
                willChange: 'auto',
              }}
          >
            {/* Faint particle trail along the inner left edge (concept drawDashEdge) */}
            <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 15 }}>
              <EdgeTrail palette={palette} />
            </div>

            {/* Dashboard Content - Fully delegated to DarkGlassDashboard */}
            <div className="flex-1 overflow-hidden relative z-10 flex flex-col">
              {/* Mobile header with back button */}
              {isRemoteView && onOpenChat && (
                <div className="flex items-center gap-3 px-4 py-3 border-b flex-shrink-0" style={{ borderColor: `${glowColor}15` }}>
                  <button
                    onClick={onClose}
                    className="flex items-center gap-2 min-h-[44px] min-w-[44px] px-3 py-2 rounded-lg transition-all"
                    style={{
                      color: glowColor,
                      backgroundColor: `${glowColor}10`,
                    }}
                  >
                    <ArrowLeft size={20} />
                    <span className="text-sm font-medium">Chat</span>
                  </button>
                  <span className="text-sm font-semibold tracking-wide" style={{ color: fontColor, opacity: 0.7 }}>
                    Dashboard
                  </span>
                </div>
              )}
              <div className="flex-1 overflow-hidden">
                <DarkGlassDashboard
                  fieldValues={fieldValues}
                  updateField={updateField}
                  onClose={onClose}
                  unreadCount={unreadCount}
                  onNotificationsClick={() => setShowNotifications(true)}
                  isNotificationsOpen={showNotifications}
                  isChatOpen={isChatOpen}
                  spotlightState={spotlightState}
                  uiState={uiState}
                  onOpenChat={onOpenChat}
                  initialSubApp={initialSubApp}
                  onRequestSpotlight={onSpotlightToggle}
                  isDetached={isDetached}
                />
              </div>
            </div>
          </motion.div>

          {/* Edge light: the top edge as one hairline with the spotlight aperture set into it,
              centred on the top border. It tilts with the panel (same transform), outside the
              panel's clip so the aperture is whole. */}
          {onSpotlightToggle && !isRemoteView && (
            <motion.div
              className="absolute inset-0 pointer-events-none"
              animate={isFlat ? {} : { transform: getSpotlightTransform() }}
              transition={isFlat ? { duration: 0 } : { type: "spring", stiffness: 280, damping: 25, mass: 0.8 }}
              style={{
                zIndex: 50,
                transformOrigin: 'right center',
                transformStyle: isFlat ? 'flat' : 'preserve-3d',
                transform: isFlat ? 'rotateY(0deg) rotateX(0deg)' : undefined,
              }}
            >
              <EdgeLight
                glowColor={glowColor}
                palette={edgePalette}
                spotlit={isInDashboardSpotlight}
                onAperture={onSpotlightToggle}
                apertureTitle={isInDashboardSpotlight ? "Restore balanced view" : "Maximize dashboard"}
                isActive={isInDashboardSpotlight}
              />
            </motion.div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default DashboardWing
