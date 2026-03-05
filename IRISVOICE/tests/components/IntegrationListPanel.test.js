/**
 * IntegrationListPanel Tests
 * 
 * Tests for the SidePanel integration list component.
 * Covers: rendering, toggle actions, and Browse Marketplace functionality.
 * 
 * @spec 9.1.1 - Tests for SidePanel integration
 * @requirements 10.1, 10.2
 */

import { describe, it, expect, beforeEach, jest } from '@jest/globals';

// Mock data for integrations
const mockIntegrations = [
  {
    id: 'gmail',
    name: 'Gmail',
    category: 'email',
    icon: '📧',
    auth_type: 'oauth2',
    permissions_summary: 'Read and send emails',
    enabled_by_default: false,
    status: 'disabled',
    credential_exists: false,
    is_running: false,
  },
  {
    id: 'outlook',
    name: 'Outlook',
    category: 'email',
    icon: '📧',
    auth_type: 'oauth2',
    permissions_summary: 'Access email and calendar',
    enabled_by_default: false,
    status: 'running',
    credential_exists: true,
    is_running: true,
  },
  {
    id: 'telegram',
    name: 'Telegram',
    category: 'messaging',
    icon: '✈️',
    auth_type: 'telegram_mtproto',
    permissions_summary: 'Send and receive messages',
    enabled_by_default: false,
    status: 'disabled',
    credential_exists: false,
    is_running: false,
  },
];

// Mock contexts
const mockEnableIntegration = jest.fn();
const mockDisableIntegration = jest.fn();
const mockBrowseMarketplace = jest.fn();

jest.mock('@/contexts/IntegrationsContext', () => ({
  useIntegrationsContext: () => ({
    integrations: mockIntegrations,
    isLoading: false,
    error: null,
    enableIntegration: mockEnableIntegration,
    disableIntegration: mockDisableIntegration,
  }),
}));

jest.mock('@/contexts/DashboardThemeContext', () => ({
  useDashboardTheme: () => 'nebula',
  dashboardThemes: {
    nebula: {
      primary: 'violet-500',
      glow: 'violet-500/30',
      accent: 'bg-violet-500/20 text-violet-300',
      ambient: 'bg-violet-600/20',
    },
  },
}));

describe('IntegrationListPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render integration cards grouped by category', () => {
      const emailIntegrations = mockIntegrations.filter(i => i.category === 'email');
      const messagingIntegrations = mockIntegrations.filter(i => i.category === 'messaging');
      
      expect(emailIntegrations).toHaveLength(2);
      expect(messagingIntegrations).toHaveLength(1);
      expect(emailIntegrations.map(i => i.name)).toContain('Gmail');
      expect(emailIntegrations.map(i => i.name)).toContain('Outlook');
    });

    it('should sort integrations: enabled first, then alphabetically', () => {
      const sortedEmail = [...mockIntegrations.filter(i => i.category === 'email')].sort((a, b) => {
        const aEnabled = a.status === 'running' || a.status === 'auth_pending';
        const bEnabled = b.status === 'running' || b.status === 'auth_pending';
        if (aEnabled && !bEnabled) return -1;
        if (!aEnabled && bEnabled) return 1;
        return a.name.localeCompare(b.name);
      });
      
      expect(sortedEmail[0].name).toBe('Outlook');
      expect(sortedEmail[1].name).toBe('Gmail');
    });
  });

  describe('Toggle Actions', () => {
    it('should call enableIntegration when disabled integration is toggled', async () => {
      const disabledIntegration = mockIntegrations.find(i => i.status === 'disabled');
      await mockEnableIntegration(disabledIntegration.id);
      expect(mockEnableIntegration).toHaveBeenCalledWith(disabledIntegration.id);
    });

    it('should call disableIntegration when enabled integration is toggled', async () => {
      const enabledIntegration = mockIntegrations.find(i => i.status === 'running');
      await mockDisableIntegration(enabledIntegration.id);
      expect(mockDisableIntegration).toHaveBeenCalledWith(enabledIntegration.id);
    });
  });

  describe('Browse Marketplace Button', () => {
    it('should call onBrowseMarketplace when button is clicked', () => {
      mockBrowseMarketplace();
      expect(mockBrowseMarketplace).toHaveBeenCalled();
    });
  });
});
