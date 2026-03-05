/**
 * IntegrationListPanel Component
 * 
 * Container for integration list in SidePanel.
 * Groups by category, shows "Browse Marketplace" button at bottom.
 * 
 * @spec Group by category, collapsible headers, scrollable list
 */

'use client';

import React, { useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, ChevronRight, Store, Loader2 } from 'lucide-react';
import { Integration } from '@/contexts/IntegrationsContext';
import { useIntegrationsContext } from '@/contexts/IntegrationsContext';
import { useDashboardTheme, dashboardThemes } from '@/contexts/DashboardThemeContext';
import { IntegrationCompactCard } from './IntegrationCompactCard';

type IntegrationCategory = 'email' | 'messaging' | 'productivity' | 'other';

interface IntegrationListPanelProps {
  onBrowseMarketplace?: () => void;
}

const categoryLabels: Record<IntegrationCategory, string> = {
  email: 'Email',
  messaging: 'Messaging',
  productivity: 'Productivity',
  other: 'Other',
};

const categoryOrder: IntegrationCategory[] = ['email', 'messaging', 'productivity', 'other'];

export function IntegrationListPanel({ onBrowseMarketplace }: IntegrationListPanelProps) {
  const themeName = useDashboardTheme();
  const theme = dashboardThemes[themeName];
  const glowColor = theme?.glow || 'cyan-400/30';
  const { 
    integrations, 
    isLoading, 
    error, 
    enableIntegration, 
    disableIntegration 
  } = useIntegrationsContext();

  // Group integrations by category
  const groupedIntegrations = useMemo(() => {
    const groups: Record<string, Integration[]> = {};
    
    integrations.forEach(integration => {
      const category = integration.category || 'other';
      if (!groups[category]) {
        groups[category] = [];
      }
      groups[category].push(integration);
    });

    // Sort within each category: enabled first, then alphabetically
    Object.keys(groups).forEach(category => {
      groups[category].sort((a, b) => {
        const aEnabled = a.status === 'running' || a.status === 'auth_pending';
        const bEnabled = b.status === 'running' || b.status === 'auth_pending';
        if (aEnabled && !bEnabled) return -1;
        if (!aEnabled && bEnabled) return 1;
        return a.name.localeCompare(b.name);
      });
    });

    return groups;
  }, [integrations]);

  // Handle toggle
  const handleToggle = useCallback(async (integrationId: string) => {
    const integration = integrations.find(i => i.id === integrationId);
    if (!integration) return;

    const isEnabled = integration.status === 'running' || integration.status === 'auth_pending';
    
    if (isEnabled) {
      await disableIntegration(integrationId);
    } else {
      await enableIntegration(integrationId);
    }
  }, [integrations, enableIntegration, disableIntegration]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-40 gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-white/50" />
        <span className="text-xs text-white/50">Loading integrations...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-40 px-4 text-center">
        <span className="text-xs text-rose-400 mb-2">Failed to load integrations</span>
        <span className="text-[10px] text-white/40">{error}</span>
      </div>
    );
  }

  if (integrations.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-40 px-4 text-center">
        <Store className="w-8 h-8 text-white/20 mb-2" />
        <span className="text-xs text-white/50 mb-3">No integrations configured</span>
        {onBrowseMarketplace && (
          <button
            onClick={onBrowseMarketplace}
            className="px-3 py-1.5 text-[11px] font-medium rounded-md
              bg-white/10 hover:bg-white/20
              text-white/80 hover:text-white
              transition-colors duration-200
              border border-white/10"
            style={{ boxShadow: `0 0 10px ${glowColor}30` }}
          >
            Browse Marketplace
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Integration list */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-4 scrollbar-thin">
        {categoryOrder.map(category => {
          const categoryIntegrations = groupedIntegrations[category];
          if (!categoryIntegrations || categoryIntegrations.length === 0) return null;

          return (
            <CategorySection
              key={category}
              category={category}
              integrations={categoryIntegrations}
              onToggle={handleToggle}
            />
          );
        })}
      </div>

      {/* Browse Marketplace button */}
      {onBrowseMarketplace && (
        <div className="px-3 py-3 border-t border-white/10">
          <motion.button
            onClick={onBrowseMarketplace}
            className="w-full flex items-center justify-center gap-2 px-3 py-2
              text-[11px] font-medium rounded-lg
              bg-white/10 hover:bg-white/20
              text-white/90 hover:text-white
              transition-all duration-200
              border border-white/10 hover:border-white/20"
            style={{ 
              boxShadow: `0 0 12px ${glowColor}20`,
            }}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
          >
            <Store className="w-3.5 h-3.5" />
            Browse Marketplace
          </motion.button>
        </div>
      )}
    </div>
  );
}

// Category section component
interface CategorySectionProps {
  category: string;
  integrations: Integration[];
  onToggle: (id: string) => void;
}

function CategorySection({ category, integrations, onToggle }: CategorySectionProps) {
  const [isExpanded, setIsExpanded] = React.useState(true);
  const label = categoryLabels[category as IntegrationCategory] || category;

  return (
    <div className="space-y-1.5">
      {/* Category header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-1 py-0.5
          text-[10px] uppercase tracking-wider font-medium
          text-white/40 hover:text-white/60
          transition-colors duration-200"
      >
        <span>{label}</span>
        <span className="flex items-center gap-1">
          <span className="text-white/30">{integrations.length}</span>
          {isExpanded ? (
            <ChevronDown className="w-3 h-3" />
          ) : (
            <ChevronRight className="w-3 h-3" />
          )}
        </span>
      </button>

      {/* Integration cards */}
      <AnimatePresence initial={false}>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="space-y-1.5 overflow-hidden"
          >
            {integrations.map(integration => (
              <IntegrationCompactCard
                key={integration.id}
                integration={integration}
                onToggle={onToggle}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default IntegrationListPanel;
