/**
 * IntegrationCompactCard Component
 * 
 * Compact card for SidePanel display (48px height, icon, toggle, status).
 * Follows glass-morphism design from wheel-view/dashboard-wing.
 * 
 * @spec 48px height, 24px icon, toggle switch, 9px status text
 */

'use client';

import React, { useCallback } from 'react';
import { motion } from 'framer-motion';
import { Power, AlertCircle, CheckCircle2, Loader2, Mail, MessageSquare, Calendar, MoreHorizontal } from 'lucide-react';
import { Integration, IntegrationStatus } from '@/contexts/IntegrationsContext';
import { useDashboardTheme, dashboardThemes } from '@/contexts/DashboardThemeContext';

interface IntegrationCompactCardProps {
  integration: Integration;
  onToggle: (id: string) => void;
  disabled?: boolean;
}

const statusConfig: Record<IntegrationStatus, { color: string; glowColor: string; label: string }> = {
  disabled: { 
    color: 'text-gray-400', 
    glowColor: 'shadow-gray-500/20',
    label: 'Not configured' 
  },
  auth_pending: { 
    color: 'text-amber-400', 
    glowColor: 'shadow-amber-500/30',
    label: 'Auth required' 
  },
  running: { 
    color: 'text-emerald-400', 
    glowColor: 'shadow-emerald-500/30',
    label: 'Connected' 
  },
  error: { 
    color: 'text-rose-400', 
    glowColor: 'shadow-rose-500/30',
    label: 'Connection error' 
  },
  reauth_pending: { 
    color: 'text-amber-400', 
    glowColor: 'shadow-amber-500/30',
    label: 'Re-auth required' 
  },
  wiped: { 
    color: 'text-gray-400', 
    glowColor: 'shadow-gray-500/20',
    label: 'Disconnected' 
  },
};

const categoryIcons: Record<string, React.ReactNode> = {
  email: <Mail className="w-5 h-5" />,
  messaging: <MessageSquare className="w-5 h-5" />,
  productivity: <Calendar className="w-5 h-5" />,
  other: <MoreHorizontal className="w-5 h-5" />,
};

export function IntegrationCompactCard({ integration, onToggle, disabled }: IntegrationCompactCardProps) {
  const themeName = useDashboardTheme();
  const theme = dashboardThemes[themeName];
  const glowColor = theme?.glow || 'cyan-400/30';
  const status = statusConfig[integration.status];
  const isEnabled = integration.status === 'running' || integration.status === 'auth_pending';
  const isLoading = integration.status === 'auth_pending';

  const handleToggle = useCallback(() => {
    if (!disabled) {
      onToggle(integration.id);
    }
  }, [integration.id, onToggle, disabled]);

  const Icon = categoryIcons[integration.category] || categoryIcons.other;

  return (
    <motion.div
      className={`
        relative flex items-center gap-2 px-2 py-1.5 rounded-lg
        bg-black/30 backdrop-blur-md
        border border-white/10
        ${disabled ? 'opacity-60' : 'hover:bg-white/5'}
        transition-colors duration-200
      `}
      style={{ height: '48px' }}
      whileTap={!disabled ? { scale: 0.98 } : undefined}
    >
      {/* Icon container */}
      <div 
        className={`
          flex items-center justify-center w-6 h-6 rounded-md
          bg-white/5 border border-white/10
          ${status.color}
        `}
        style={{
          boxShadow: isEnabled ? `0 0 8px ${glowColor}40` : undefined
        }}
      >
        {Icon}
      </div>

      {/* Name and status */}
      <div className="flex-1 min-w-0 flex flex-col justify-center">
        <span className="text-[11px] font-medium text-white/90 truncate leading-tight">
          {integration.name}
        </span>
        <span className={`text-[9px] ${status.color} truncate leading-tight`}>
          {status.label}
        </span>
      </div>

      {/* Toggle switch */}
      <button
        onClick={handleToggle}
        disabled={disabled || isLoading}
        className={`
          relative w-9 h-5 rounded-full transition-colors duration-200
          ${isEnabled 
            ? 'bg-emerald-500/80' 
            : 'bg-white/20 hover:bg-white/30'
          }
          ${(disabled || isLoading) ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}
          focus:outline-none focus:ring-2 focus:ring-white/20
        `}
        style={{
          boxShadow: isEnabled ? `0 0 10px ${glowColor}60` : undefined
        }}
        aria-label={`Toggle ${integration.name}`}
      >
        {/* Toggle knob */}
        <motion.div
          className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-md"
          initial={false}
          animate={{ 
            left: isEnabled ? 'calc(100% - 18px)' : '2px',
            scale: isLoading ? 0.9 : 1
          }}
          transition={{ type: 'spring', stiffness: 500, damping: 30 }}
        >
          {isLoading && (
            <Loader2 className="w-3 h-3 text-amber-500 animate-spin absolute top-0.5 left-0.5" />
          )}
        </motion.div>
      </button>

      {/* Active indicator line */}
      {isEnabled && (
        <motion.div
          className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-6 rounded-full"
          style={{ backgroundColor: glowColor }}
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 24 }}
          transition={{ duration: 0.2 }}
        />
      )}
    </motion.div>
  );
}

export default IntegrationCompactCard;
