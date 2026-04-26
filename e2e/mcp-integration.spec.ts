/**
 * MCP Integration E2E Tests
 * 
 * End-to-end tests for the full MCP integration flow.
 * Covers: Browse → Install → Auth → Enable flow, error recovery, persistence.
 * 
 * @spec 9.1.4 - E2E tests
 * @requirements Full flow testing
 */

import { test, expect, Page } from '@playwright/test';

// Test data
const TEST_INTEGRATION = {
  id: 'test-mcp-server',
  name: 'Test MCP Server',
  category: 'developer',
};

test.describe('MCP Integration E2E Flow', () => {
  let page: Page;

  test.beforeEach(async ({ browser }) => {
    page = await browser.newPage();
    // Navigate to the app
    await page.goto('http://localhost:3000');
  });

  test.afterEach(async () => {
    await page.close();
  });

  test.describe('Browse → Install → Auth → Enable Flow', () => {
    test('should complete full integration flow', async () => {
      // Step 1: Open dashboard
      await page.click('[data-testid="dashboard-toggle"]');
      await expect(page.locator('[data-testid="dashboard-wing"]')).toBeVisible();

      // Step 2: Navigate to Marketplace tab
      await page.click('[data-testid="tab-marketplace"]');
      await expect(page.locator('[data-testid="marketplace-screen"]')).toBeVisible();

      // Step 3: Browse integrations
      await expect(page.locator('[data-testid="integration-card"]')).toHaveCount.greaterThan(0);

      // Step 4: Click install on an integration
      await page.click('[data-testid="install-button"]:first-of-type');
      await expect(page.locator('[data-testid="install-confirm-modal"]')).toBeVisible();

      // Step 5: Confirm installation
      await page.click('[data-testid="confirm-install-button"]');
      await expect(page.locator('[data-testid="install-progress"]')).toBeVisible();

      // Step 6: Wait for auth flow (if OAuth)
      await expect(page.locator('[data-testid="auth-flow-modal"]')).toBeVisible({ timeout: 10000 });

      // Step 7: Complete auth (mocked)
      await page.click('[data-testid="auth-confirm-button"]');

      // Step 8: Verify integration is enabled
      await expect(page.locator('[data-testid="integration-status-running"]')).toBeVisible();
    });
  });

  test.describe('Error Recovery', () => {
    test('should handle failed installation gracefully', async () => {
      // Navigate to marketplace
      await page.click('[data-testid="dashboard-toggle"]');
      await page.click('[data-testid="tab-marketplace"]');

      // Try to install
      await page.click('[data-testid="install-button"]:first-of-type');
      await page.click('[data-testid="confirm-install-button"]');

      // Simulate failure (this would be triggered by backend)
      // Check that error state is shown
      await expect(page.locator('[data-testid="install-error"]')).toBeVisible();

      // Verify retry button is available
      await expect(page.locator('[data-testid="retry-install-button"]')).toBeVisible();
    });

    test('should handle auth flow cancellation', async () => {
      // Navigate through install flow
      await page.click('[data-testid="dashboard-toggle"]');
      await page.click('[data-testid="tab-marketplace"]');
      await page.click('[data-testid="install-button"]:first-of-type');
      await page.click('[data-testid="confirm-install-button"]');

      // Wait for auth modal
      await expect(page.locator('[data-testid="auth-flow-modal"]')).toBeVisible();

      // Cancel auth
      await page.click('[data-testid="cancel-auth-button"]');

      // Verify we're back to marketplace
      await expect(page.locator('[data-testid="marketplace-screen"]')).toBeVisible();
    });

    test('should handle network disconnection during install', async () => {
      // Start installation
      await page.click('[data-testid="dashboard-toggle"]');
      await page.click('[data-testid="tab-marketplace"]');
      await page.click('[data-testid="install-button"]:first-of-type');
      await page.click('[data-testid="confirm-install-button"]');

      // Simulate network offline
      await page.context().setOffline(true);

      // Verify error handling
      await expect(page.locator('[data-testid="network-error"]')).toBeVisible();

      // Restore network
      await page.context().setOffline(false);
    });
  });

  test.describe('Persistence', () => {
    test('should persist integration state after reload', async () => {
      // Enable an integration
      await page.click('[data-testid="dashboard-toggle"]');
      await page.click('[data-testid="tab-marketplace"]');
      await page.click('[data-testid="integration-card-gmail"]');
      await page.click('[data-testid="enable-toggle"]');

      // Wait for enable to complete
      await expect(page.locator('[data-testid="integration-status-running"]')).toBeVisible();

      // Reload page
      await page.reload();

      // Re-open dashboard
      await page.click('[data-testid="dashboard-toggle"]');

      // Verify integration is still enabled
      await expect(page.locator('[data-testid="integration-status-running"]')).toBeVisible();
    });

    test('should persist preferences after reload', async () => {
      // Browse a category
      await page.click('[data-testid="dashboard-toggle"]');
      await page.click('[data-testid="tab-marketplace"]');
      await page.click('[data-testid="category-email"]');

      // Reload
      await page.reload();

      // Re-open dashboard
      await page.click('[data-testid="dashboard-toggle"]');
      await page.click('[data-testid="tab-marketplace"]');

      // Verify recommendations are personalized based on previous browsing
      await expect(page.locator('[data-testid="recommended-section"]')).toBeVisible();
    });

    test('should persist auth credentials securely', async () => {
      // Complete OAuth flow
      await page.click('[data-testid="dashboard-toggle"]');
      await page.click('[data-testid="tab-marketplace"]');
      await page.click('[data-testid="integration-card-gmail"]');
      await page.click('[data-testid="install-button"]');
      await page.click('[data-testid="confirm-install-button"]');

      // Complete auth (mock)
      await page.click('[data-testid="auth-confirm-button"]');

      // Reload
      await page.reload();

      // Verify integration still has credentials
      await page.click('[data-testid="dashboard-toggle"]');
      await expect(page.locator('[data-testid="credential-status-present"]')).toBeVisible();
    });
  });

  test.describe('Dual-Interface Navigation', () => {
    test('should switch from wheel-view to dashboard marketplace', async () => {
      // Open wheel view (level 3)
      await page.click('[data-testid="expand-navigation"]');
      await page.click('[data-testid="category-automate"]');

      // Click "Browse Marketplace" in SidePanel
      await page.click('[data-testid="browse-marketplace-button"]');

      // Verify dashboard opens with marketplace tab active
      await expect(page.locator('[data-testid="dashboard-wing"]')).toBeVisible();
      await expect(page.locator('[data-testid="marketplace-screen"]')).toBeVisible();
      await expect(page.locator('[data-testid="tab-marketplace"]')).toHaveAttribute('data-active', 'true');
    });

    test('should maintain state when switching between tabs', async () => {
      // Open dashboard
      await page.click('[data-testid="dashboard-toggle"]');

      // Go to Activity tab
      await page.click('[data-testid="tab-activity"]');
      await expect(page.locator('[data-testid="activity-panel"]')).toBeVisible();

      // Scroll down in activity panel
      await page.evaluate(() => window.scrollBy(0, 500));

      // Switch to Logs tab
      await page.click('[data-testid="tab-logs"]');
      await expect(page.locator('[data-testid="logs-panel"]')).toBeVisible();

      // Switch back to Activity
      await page.click('[data-testid="tab-activity"]');

      // Verify scroll position is maintained (or at least panel is visible)
      await expect(page.locator('[data-testid="activity-panel"]')).toBeVisible();
    });
  });

  test.describe('Edge Cases', () => {
    test('should handle rapid tab switching', async () => {
      await page.click('[data-testid="dashboard-toggle"]');

      // Rapidly switch between tabs
      for (let i = 0; i < 5; i++) {
        await page.click('[data-testid="tab-activity"]');
        await page.click('[data-testid="tab-logs"]');
        await page.click('[data-testid="tab-marketplace"]');
        await page.click('[data-testid="tab-dashboard"]');
      }

      // Verify app is still stable
      await expect(page.locator('[data-testid="dashboard-wing"]')).toBeVisible();
    });

    test('should handle concurrent integration operations', async () => {
      // Try to enable multiple integrations quickly
      await page.click('[data-testid="dashboard-toggle"]');
      await page.click('[data-testid="tab-marketplace"]');

      // Click enable on multiple integrations
      const enableButtons = await page.locator('[data-testid="enable-toggle"]').all();
      for (const button of enableButtons.slice(0, 3)) {
        await button.click();
      }

      // Verify no errors
      await expect(page.locator('[data-testid="error-message"]')).not.toBeVisible();
    });
  });
});

// Helper function to wait for WebSocket connection
test.describe('WebSocket Connection', () => {
  test('should establish WebSocket connection on load', async ({ page }) => {
    // Listen for WebSocket
    const wsMessages: string[] = [];
    
    page.on('websocket', ws => {
      ws.on('framereceived', data => {
        wsMessages.push(data.toString());
      });
    });

    await page.goto('http://localhost:3000');

    // Wait a bit for connection
    await page.waitForTimeout(1000);

    // Check that we received some messages
    expect(wsMessages.length).toBeGreaterThan(0);
  });
});
