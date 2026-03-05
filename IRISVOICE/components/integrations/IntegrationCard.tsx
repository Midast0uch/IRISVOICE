/**
 * IntegrationCard Component
 * 
 * Card displaying an integration with toggle switch and status.
 * Follows glass-morphism design from wheel-view/dashboard-wing.
 */

'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { Power, AlertCircle, CheckCircle2, Mail, MessageSquare, MoreHorizontal } from 'lucide-react';
import { Integration, IntegrationStatus } from '@/hooks/useIntegrations';

interface IntegrationCardProps {
  integration: Integration;
  onToggle: (id: string) => void;
  onClick: (id: string) => void;
  disabled?: boolean;
}

const statusConfig: Record<IntegrationStatus, { color: string; icon: React.ReactNode; label: string }> = {
  disabled: { 
    color: 'text-gray-400', 
    icon: <Power className="w-3 h-3" />, 
    label: 'Disabled' 
  },
  auth_pending: { 
    color: 'text-amber-400', 
    icon: <AlertCircle className="w-3 h-3" />, 
    label: 'Authentication Required' 
  },
  running: { 
    color: 'text-emerald-400', 
    icon: <CheckCircle2 className="w-3 h-3" />, 
    label: 'Connected' 
  },
  error: { 
    color: 'text-rose-400', 
    icon: <AlertCircle className="w-3 h-3" />, 
    label: 'Error' 
  },
  reauth_pending: { 
    color: 'text-amber-400', 
    icon: <AlertCircle className="w-3 h-3" />, 
    label: 'Re-authentication Required' 
  },
  wiped: { 
    color: 'text-gray-400', 
    icon: <Power className="w-3 h-3" />, 
    label: 'Disconnected' 
  },
};

const categoryIcons: Record<string, React.ReactNode> = {
  email: <Mail className="w-4 h-4" />,
  messaging: <MessageSquare className="w-4 h-4" />,
};

export function IntegrationCard({ integration, onToggle, onClick, disabled }: IntegrationCardProps) {
  const status = statusConfig[integration.status];
  const isEnabled = integration.status === 'running' || integration.status === 'auth_pending';
  
  // Glass-morphism card with consistent styling
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      whileHover={{ scale: 1.01 }}
      whileTap={{ scale: 0.99 }}
      onClick={() => onClick(integration.id)}
      className="group relative cursor-pointer"
    >
      {/* Main card container with glass effect */}
      <div className="relative overflow-hidden rounded-lg bg-gradient-to-br from-white/[0.08] to-white/[0.02] backdrop-blur-md border border-white/[0.08] hover:border-white/[0.15] transition-all duration-300">
        
        {/* Edge Fresnel effect - matching dashboard-wing */}
        <div className="absolute inset-y-0 left-0 w-[2px] bg-gradient-to-b from-white/20 via-white/5 to-transparent" />
        <div className="absolute inset-x-0 top-0 h-[1px] bg-gradient-to-r from-white/30 via-white/10 to-transparent" />
        
        {/* Content */}
        <div className="relative flex items-center gap-3 p-4">
          
          {/* Icon container */}
          <div className="relative flex-shrink-0 w-10 h-10 rounded-lg bg-gradient-to-br from-white/10 to-white/5 flex items-center justify-center border border-white/[0.08]">
            {categoryIcons[integration.category] || <MoreHorizontal className="w-4 h-4 text-gray-400" />}
            
            {/* Status indicator dot */}
            <div className={`absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-gray-900 ${
              integration.is_running ? 'bg-emerald-400' : 
              integration.status === 'error' ? 'bg-rose-400' :
              integration.status === 'auth_pending' ? 'bg-amber-400' :
              'bg-gray-500'
            }`} />
          </div>
          
          {/* Text content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-[13px] font-medium text-white/90 truncate tracking-wide">
                {integration.name}
              </h3>
            </div>
            <p className={`text-[10px] ${status.color} flex items-center gap-1 mt-0.5`}>
              {status.icon}
              <span className="uppercase tracking-wider opacity-80">{status.label}</span>
            </p>
          </div>
          
          {/* Toggle switch */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              onToggle(integration.id);
            }}
            disabled={disabled}
            className={`relative w-11 h-6 rounded-full transition-colors duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/30 ${
              isEnabled ? 'bg-emerald-500/30' : 'bg-white/10'
            } ${disabled ? 'opacity-50 cursor-not-allowed' : 'hover:bg-white/15'}`}
          >
            <motion.div
              animate={{ x: isEnabled ? 22 : 2 }}
              transition={{ type: 'spring', stiffness: 500, damping: 30 }}
              className={`absolute top-1 w-4 h-4 rounded-full shadow-lg ${
                isEnabled 
                  ? 'bg-gradient-to-br from-emerald-400 to-emerald-500 shadow-emerald-500/30' 
                  : 'bg-gradient-to-br from-white to-white/80'
              }`}
            />
          </button>
        </div>
        
        {/* Hover overlay glow */}
        <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none">
          <div className="absolute inset-0 bg-gradient-to-r from-white/[0.02] via-transparent to-white/[0.02]" />
        </div>
      </div>
    </motion.div>
  );
}
