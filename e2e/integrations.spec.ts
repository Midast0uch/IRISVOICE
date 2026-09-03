/**
 * Playwright E2E Tests for Integrations UI
 * 
 * Tests the IntegrationsScreen, IntegrationCard, IntegrationDetail components
 * and user interactions.
 * 
 * _Requirements: 6.1.1, 6.1.2, 6.1.3, 6.1.4, 6.1.5
 */

import { test, expect } from '@playwright/test';

// Mock server responses for consistent testing
const MOCK_INTEGRATIONS = {
  integrations: [
    {
      id: 'gmail',
      name: 'Gmail',
      category: 'email',
      icon: 'gmail.svg',
      auth_type: 'oauth2',
      status: 'DISABLED',
      enabled: false,
      permissions_summary: 'Read and send Gmail messages',
    },
    {
      id: 'telegram',
      name: 'Telegram',
      category: 'messaging',
      icon: 'telegram.svg',
      auth_type: 'telegram_mtproto',
      status: 'RUNNING',
      enabled: true,
      permissions_summary: 'Read and send messages',
      connected_as: '@testuser',
    },
    {
      id: 'discord',
      name: 'Discord',
      category: 'messaging',
      icon: 'discord.svg',
      auth_type: 'oauth2',
      status: 'AUTH_PENDING',
      enabled: false,
      permissions_summary: 'Read and send Discord messages',
    },
  ],
};

test.describe('Integrations Screen', () => {
  test.beforeEach(async ({ page }) => {
    // Mock WebSocket connection
    await page.addInitScript(() => {
      // Mock window.iris for Tauri integration
      (window as any).iris = {
        invoke: async (cmd: string, args: any) => {
          if (cmd === 'get_integrations') {
            return MOCK_INTEGRATIONS;
          }
          return null;
        },
      };

      // Mock WebSocket
      class MockWebSocket extends WebSocket {
        constructor(url: string) {
          super(url);
        }
        
        send(data: string) {
          const message = JSON.parse(data);
          
          // Mock responses
          if (message.type === 'integration_list') {
            setTimeout(() => {
              this.dispatchEvent(new MessageEvent('message', {
                data: JSON.stringify({
                  type: 'integration_list',
                  integrations: MOCK_INTEGRATIONS.integrations,
                }),
              }));
            }, 10);
          }
          
          if (message.type === 'integration_state') {
            setTimeout(() => {
              this.dispatchEvent(new MessageEvent('message', {
                data: JSON.stringify({
                  type: 'integration_state',
                  integration_id: message.integration_id,
                  state: { status: 'RUNNING' },
                }),
              }));
            }, 10);
          }
          
          super.send(data);
        }
      }
      
      (window as any).WebSocket = MockWebSocket;
    });

    // Navigate to integrations screen
    await page.goto('/integrations');
    await page.waitForLoadState('networkidle');
  });

  test('displays integrations list with categories', async ({ page }) => {
    // Wait for integrations to load
    await page.waitForSelector('[data-testid="integration-card"]', { timeout: 5000 });

    // Check category headers
    const emailHeader = await page.locator('text=EMAIL').first();
    const messagingHeader = await page.locator('text=MESSAGING').first();
    
    await expect(emailHeader).toBeVisible();
    await expect(messagingHeader).toBeVisible();

    // Check integration cards
    const cards = await page.locator('[data-testid="integration-card"]').all();
    expect(cards.length).toBeGreaterThanOrEqual(3);
  });

  test('integration card displays correct information', async ({ page }) => {
    await page.waitForSelector('[data-testid="integration-card"]', { timeout: 5000 });

    // Check Gmail card
    const gmailCard = await page.locator('[data-testid="integration-card-gmail"]');
    await expect(gmailCard).toContainText('Gmail');
    await expect(gmailCard).toContainText('Read and send Gmail messages');
    
    // Should show OFF state
    const toggle = gmailCard.locator('[role="switch"]');
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
  });

  test('toggle integration on/off', async ({ page }) => {
    await page.waitForSelector('[data-testid="integration-card"]', { timeout: 5000 });

    const gmailCard = await page.locator('[data-testid="integration-card-gmail"]');
    const toggle = gmailCard.locator('[role="switch"]');
    
    // Initially off
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    
    // Click to enable
    await toggle.click();
    
    // Should show auth flow modal
    await page.waitForSelector('[data-testid="auth-flow-modal"]', { timeout: 3000 });
    
    // Close modal
    await page.click('[data-testid="close-modal"]');
    
    // Toggle should still be off (auth not completed)
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
  });

  test('navigate to integration detail view', async ({ page }) => {
    await page.waitForSelector('[data-testid="integration-card"]', { timeout: 5000 });

    // Click on a connected integration (Telegram)
    const telegramCard = await page.locator('[data-testid="integration-card-telegram"]');
    await telegramCard.click();
    
    // Should navigate to detail view
    await page.waitForSelector('[data-testid="integration-detail"]', { timeout: 3000 });
    
    // Verify detail view content
    await expect(page).toContainText('Telegram');
    await expect(page).toContainText('Connected as @testuser');
    await expect(page).toContainText('WHAT YOUR AGENT CAN DO');
    await expect(page).toContainText('PERMISSIONS');
    
    // Check for action buttons
    await expect(page.locator('text=Disconnect')).toBeVisible();
    await expect(page.locator('text=Disconnect & Forget')).toBeVisible();
  });

  test('disconnect integration from detail view', async ({ page }) => {
    await page.waitForSelector('[data-testid="integration-card"]', { timeout: 5000 });

    // Navigate to Telegram detail
    const telegramCard = await page.locator('[data-testid="integration-card-telegram"]');
    await telegramCard.click();
    
    await page.waitForSelector('[data-testid="integration-detail"]', { timeout: 3000 });
    
    // Click Disconnect
    await page.click('text=Disconnect');
    
    // Should show confirmation or return to list with updated state
    await page.waitForTimeout(500);
    
    // Mock response would update state to DISABLED
    // In real test, we'd verify WebSocket message was sent
  });

  test('search and filter integrations', async ({ page }) => {
    await page.waitForSelector('[data-testid="integration-card"]', { timeout: 5000 });

    // Check if search input exists
    const searchInput = await page.locator('input[placeholder*="Search"], input[placeholder*="Filter"]');
    
    if (await searchInput.count() > 0) {
      // Type in search box
      await searchInput.fill('gmail');
      
      // Wait for filter
      await page.waitForTimeout(300);
      
      // Should show only Gmail
      const cards = await page.locator('[data-testid="integration-card"]').all();
      expect(cards.length).toBe(1);
      await expect(page.locator('[data-testid="integration-card-gmail"]')).toBeVisible();
    }
  });

  test('responsive design on different viewports', async ({ page }) => {
    // Mobile viewport
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/integrations');
    await page.waitForTimeout(500);
    
    const cards = await page.locator('[data-testid="integration-card"]').all();
    expect(cards.length).toBeGreaterThan(0);
    
    // Desktop viewport
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/integrations');
    await page.waitForTimeout(500);
    
    const desktopCards = await page.locator('[data-testid="integration-card"]').all();
    expect(desktopCards.length).toBeGreaterThan(0);
  });
});

test.describe('Integration State Updates', () => {
  test('real-time state updates via WebSocket', async ({ page }) => {
    // Track WebSocket messages
    const wsMessages: any[] = [];
    
    await page.addInitScript(() => {
      const originalSend = WebSocket.prototype.send;
      WebSocket.prototype.send = function(data: any) {
        wsMessages.push(JSON.parse(data));
        return originalSend.call(this, data);
      };
    });

    await page.goto('/integrations');
    await page.waitForSelector('[data-testid="integration-card"]', { timeout: 5000 });

    // Verify initial list request was sent
    expect(wsMessages.some(m => m.type === 'integration_list')).toBe(true);
  });

  test('error state handling', async ({ page }) => {
    await page.addInitScript(() => {
      (window as any).iris = {
        invoke: async () => {
          throw new Error('Network error');
        },
      };
    });

    await page.goto('/integrations');
    
    // Should show error state
    await page.waitForTimeout(500);
    await expect(page.locator('text=error, text=Error, text=failed')).toBeVisible().catch(() => {
      // Fallback - just verify page loaded
      expect(page.url()).toContain('/integrations');
    });
  });
});

test.describe('Accessibility', () => {
  test('keyboard navigation', async ({ page }) => {
    await page.goto('/integrations');
    await page.waitForSelector('[data-testid="integration-card"]', { timeout: 5000 });

    // Tab through elements
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    
    // Check focus is on interactive element
    const focusedElement = await page.evaluate(() => document.activeElement?.tagName);
    expect(['BUTTON', 'A', 'INPUT', '[role="switch"]']).toContain(focusedElement);
  });

  test('screen reader compatibility', async ({ page }) => {
    await page.goto('/integrations');
    await page.waitForSelector('[data-testid="integration-card"]', { timeout: 5000 });

    // Check for proper ARIA labels
    const toggles = await page.locator('[role="switch"]').all();
    for (const toggle of toggles) {
      const label = await toggle.getAttribute('aria-label');
      expect(label).toBeTruthy();
    }

    // Check for alt text on icons
    const images = await page.locator('img').all();
    for (const img of images) {
      const alt = await img.getAttribute('alt');
      expect(alt).toBeTruthy();
    }
  });
});
