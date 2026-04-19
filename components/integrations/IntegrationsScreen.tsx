/**
 * IntegrationsScreen Component
 * 
 * Main screen for managing integrations with category grouping.
 * Features glass-morphism design matching wheel-view/dashboard-wing.
 */

'use client';

import React, { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, RefreshCw, Mail, MessageSquare, Shield, AlertCircle } from 'lucide-react';
import { IntegrationCard } from './IntegrationCard';
import { useIntegrations, Integration, IntegrationState } from '@/hooks/useIntegrations';
import { AuthFlowModal } from './AuthFlowModal';

interface IntegrationsScreenProps {
  onClose?: () => void;
}

const categoryConfig: Record<string, { label: string; icon: React.ReactNode; order: number }> = {
  email: { 
    label: 'Email', 
    icon: <Mail className="w-3.5 h-3.5" />, 
    order: 1 
  },
  messaging: { 
    label: 'Messaging', 
    icon: <MessageSquare className="w-3.5 h-3.5" />, 
    order: 2 
  },
  other: { 
    label: 'Other', 
    icon: <Shield className="w-3.5 h-3.5" />, 
    order: 3 
  },
};

export function IntegrationsScreen({ onClose }: IntegrationsScreenProps) {
  const {
    integrations,
    states,
    isLoading,
    error,
    refreshIntegrations,
    enableIntegration,
    disableIntegration,
    pendingAuth,
    clearPendingAuth,
  } = useIntegrations();

  const [selectedIntegration, setSelectedIntegration] = useState<string | null>(null);

  // Group integrations by category
  const groupedIntegrations = React.useMemo(() => {
    const groups: Record<string, typeof integrations> = {};
    
    integrations.forEach(integration => {
      const category = integration.category || 'other';
      if (!groups[category]) {
        groups[category] = [];
      }
      groups[category].push(integration);
    });
    
    // Sort categories by order
    return Object.entries(groups).sort((a, b) => {
      const orderA = categoryConfig[a[0]]?.order || 99;
      const orderB = categoryConfig[b[0]]?.order || 99;
      return orderA - orderB;
    });
  }, [integrations]);

  const handleToggle = useCallback(async (integrationId: string) => {
    const integration = integrations.find(i => i.id === integrationId);
    if (!integration) return;

    if (integration.is_running || integration.status === 'auth_pending') {
      // Disable
      await disableIntegration(integrationId);
    } else {
      // Enable - this may trigger auth flow
      await enableIntegration(integrationId);
    }
  }, [integrations, enableIntegration, disableIntegration]);

  const handleCardClick = useCallback((integrationId: string) => {
    setSelectedIntegration(integrationId);
  }, []);

  const selectedIntegrationData = selectedIntegration 
    ? integrations.find(i => i.id === selectedIntegration)
    : null;

  return (
    <div className="relative w-full h-full overflow-hidden bg-gradient-to-br from-gray-900 via-gray-900 to-black">
      {/* Background ambient effects */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 -left-32 w-64 h-64 bg-blue-500/5 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 -right-32 w-64 h-64 bg-purple-500/5 rounded-full blur-3xl" />
      </div>

      {/* Header */}
      <div className="relative flex items-center justify-between px-5 py-4 border-b border-white/[0.06]">
        <div>
          <h1 className="text-[15px] font-semibold text-white/90 tracking-wide">Integrations</h1>
          <p className="text-[11px] text-white/40 mt-0.5">Manage your connected services</p>
        </div>
        
        <div className="flex items-center gap-2">
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={refreshIntegrations}
            disabled={isLoading}
            className="p-2 rounded-lg bg-white/[0.05] hover:bg-white/[0.08] border border-white/[0.08] transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 text-white/60 ${isLoading ? 'animate-spin' : ''}`} />
          </motion.button>
          
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-white/[0.08] hover:bg-white/[0.12] border border-white/[0.08] transition-colors"
          >
            <Plus className="w-3.5 h-3.5 text-white/70" />
            <span className="text-[11px] font-medium text-white/80">Add</span>
          </motion.button>
        </div>
      </div>

      {/* Content */}
      <div className="relative h-[calc(100%-73px)] overflow-y-auto scrollbar-thin scrollbar-track-transparent scrollbar-thumb-white/10">
        <div className="p-5 space-y-6">
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-[11px]"
            >
              {error}
            </motion.div>
          )}

          <AnimatePresence mode="popLayout">
            {groupedIntegrations.map(([category, items]) => (
              <motion.section
                key={category}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className="space-y-3"
              >
                {/* Category header */}
                <div className="flex items-center gap-2 px-1">
                  <div className="p-1 rounded bg-white/[0.06]">
                    {categoryConfig[category]?.icon || <Shield className="w-3.5 h-3.5 text-white/50" />}
                  </div>
                  <h2 className="text-[11px] font-medium text-white/60 uppercase tracking-wider">
                    {categoryConfig[category]?.label || category}
                  </h2>
                  <div className="flex-1 h-px bg-gradient-to-r from-white/[0.08] to-transparent" />
                </div>

                {/* Integration cards */}
                <div className="space-y-2">
                  {items.map((integration) => (
                    <IntegrationCard
                      key={integration.id}
                      integration={integration}
                      onToggle={handleToggle}
                      onClick={handleCardClick}
                      disabled={isLoading}
                    />
                  ))}
                </div>
              </motion.section>
            ))}
          </AnimatePresence>

          {integrations.length === 0 && !isLoading && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="w-12 h-12 rounded-full bg-white/[0.03] flex items-center justify-center mb-3">
                <Shield className="w-5 h-5 text-white/20" />
              </div>
              <p className="text-[12px] text-white/40">No integrations available</p>
              <p className="text-[10px] text-white/25 mt-1">Check your registry configuration</p>
            </div>
          )}
        </div>
      </div>

      {/* Detail view overlay */}
      <AnimatePresence>
        {selectedIntegration && selectedIntegrationData && (
          <IntegrationDetail
            integration={selectedIntegrationData}
            state={states[selectedIntegration]}
            onClose={() => setSelectedIntegration(null)}
            onToggle={() => handleToggle(selectedIntegration)}
            onDisable={(forget) => disableIntegration(selectedIntegration, forget)}
          />
        )}
      </AnimatePresence>

      {/* Auth flow modal */}
      <AuthFlowModal
        isOpen={pendingAuth !== null}
        onClose={clearPendingAuth}
        authData={pendingAuth}
      />
    </div>
  );
}

// Internal detail view component
interface IntegrationDetailProps {
  integration: Integration;
  state: IntegrationState | undefined;
  onClose: () => void;
  onToggle: () => void;
  onDisable: (forget: boolean) => void;
}

function IntegrationDetail({ integration, state, onClose, onToggle, onDisable }: IntegrationDetailProps) {
  // Format date for display
  const formatDate = (dateStr: string | undefined) => {
    if (!dateStr) return null;
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { 
      month: 'long', 
      day: 'numeric', 
      year: 'numeric' 
    });
  };

  // Get tools list from integration config
  const tools = integration.tools || [];

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.2 }}
      className="absolute inset-0 z-50 bg-gradient-to-br from-gray-900 via-gray-900 to-black"
    >
      {/* Background ambient effects */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 -right-32 w-64 h-64 bg-blue-500/5 rounded-full blur-3xl" />
      </div>

      {/* Header */}
      <div className="relative flex items-center justify-between px-5 py-4 border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-white/[0.05] transition-colors"
          >
            <svg className="w-4 h-4 text-white/60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </motion.button>
          <div>
            <h2 className="text-[15px] font-medium text-white/90">{integration.name}</h2>
            <p className="text-[11px] text-white/40 mt-0.5">
              {integration.is_running 
                ? `Connected` 
                : integration.status === 'auth_pending' 
                  ? 'Authentication Required' 
                  : 'Disconnected'}
            </p>
          </div>
        </div>

        {/* Status indicator */}
        <div className={`px-3 py-1.5 rounded-full text-[11px] font-medium ${
          integration.is_running 
            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' 
            : integration.status === 'error'
              ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
              : 'bg-gray-500/10 text-gray-400 border border-gray-500/20'
        }`}>
          {integration.is_running ? 'Active' : integration.status === 'error' ? 'Error' : 'Inactive'}
        </div>
      </div>

      {/* Content */}
      <div className="relative p-5 space-y-6 overflow-y-auto h-[calc(100%-73px)] scrollbar-thin scrollbar-track-transparent scrollbar-thumb-white/10">
        
        {/* Status card */}
        <div className="p-4 rounded-xl bg-gradient-to-br from-white/[0.08] to-white/[0.02] border border-white/[0.08]">
          <div className="flex items-center justify-between">
            <div className="space-y-1">
              <p className="text-[10px] text-white/40 uppercase tracking-wider">Status</p>
              <p className={`text-[13px] font-medium ${
                integration.is_running ? 'text-emerald-400' : 'text-white/60'
              }`}>
                {integration.is_running 
                  ? 'Connected' 
                  : state?.error_message || 'Disconnected'}
              </p>
              {integration.is_running && state?.connected_since && (
                <p className="text-[11px] text-white/40">
                  Since: {formatDate(state.connected_since)}
                </p>
              )}
            </div>
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={onToggle}
              className={`px-4 py-2.5 rounded-lg text-[11px] font-medium transition-colors ${
                integration.is_running
                  ? 'bg-rose-500/20 text-rose-400 hover:bg-rose-500/30 border border-rose-500/30'
                  : 'bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 border border-emerald-500/30'
              }`}
            >
              {integration.is_running ? 'Disconnect' : 'Connect'}
            </motion.button>
          </div>
        </div>

        {/* What your agent can do */}
        {tools.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-[11px] font-medium text-white/60 uppercase tracking-wider">
              What Your Agent Can Do
            </h3>
            <div className="p-4 rounded-xl bg-gradient-to-br from-white/[0.05] to-white/[0.02] border border-white/[0.06]">
              <ul className="space-y-2">
                {tools.map((tool, index) => (
                  <li key={index} className="flex items-center gap-2 text-[12px] text-white/70">
                    <svg className="w-3.5 h-3.5 text-emerald-400/70" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    {tool}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {/* Permissions summary */}
        <div className="space-y-3">
          <h3 className="text-[11px] font-medium text-white/60 uppercase tracking-wider">
            Permissions
          </h3>
          <p className="text-[12px] text-white/70 leading-relaxed">
            {integration.permissions_summary}
          </p>
        </div>

        {/* Error message if any */}
        {state?.error_message && !integration.is_running && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20"
          >
            <div className="flex items-start gap-2">
              <AlertCircle className="w-4 h-4 text-rose-400 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-[12px] text-rose-400 font-medium">Connection Error</p>
                <p className="text-[11px] text-rose-400/70 mt-1">{state.error_message}</p>
                {state.retry_count > 0 && (
                  <p className="text-[10px] text-rose-400/50 mt-1">
                    Retry attempt {state.retry_count}
                  </p>
                )}
              </div>
            </div>
          </motion.div>
        )}

        {/* Actions */}
        {integration.credential_exists && (
          <div className="pt-4 border-t border-white/[0.06] space-y-2">
            <p className="text-[10px] text-white/40 uppercase tracking-wider mb-3">Actions</p>
            <motion.button
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              onClick={() => onDisable(false)}
              className="w-full py-2.5 rounded-lg bg-white/[0.05] hover:bg-white/[0.08] text-white/70 text-[11px] font-medium transition-colors border border-white/[0.06]"
            >
              Disconnect
            </motion.button>
            <motion.button
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              onClick={() => onDisable(true)}
              className="w-full py-2.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/15 text-rose-400 text-[11px] font-medium transition-colors border border-rose-500/20"
            >
              Disconnect & Forget Credentials
            </motion.button>
          </div>
        )}
      </div>
    </motion.div>
  );
}
