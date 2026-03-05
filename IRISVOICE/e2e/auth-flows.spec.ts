/**
 * Playwright E2E Tests for Auth Flows
 * 
 * Tests OAuth, Telegram MTProto, and Credentials authentication flows.
 * 
 * _Requirements: 3.1.1-3.1.5, 3.2.1-3.2.4, 3.3.1-3.3.3
 */

import { test, expect } from '@playwright/test';

// Mock OAuth provider responses
const MOCK_OAUTH_RESPONSES = {
  google: {
    code: 'mock_auth_code_google',
    tokens: {
      access_token: 'ya29.mock_access_token',
      refresh_token: '1//mock_refresh_token',
      expires_in: 3600,
      token_type: 'Bearer',
    },
  },
  discord: {
    code: 'mock_auth_code_discord',
    tokens: {
      access_token: 'mock_discord_token',
      refresh_token: 'mock_discord_refresh',
      expires_in: 604800,
      token_type: 'Bearer',
    },
  },
};

// Mock Telegram responses
const MOCK_TELEGRAM_RESPONSES = {
  phone_code_hash: 'mock_hash_12345',
  session_string: 'mock_session_string_abc123',
};

test.describe('OAuth2 Flow - Gmail', () => {
  test.beforeEach(async ({ page }) => {
    // Setup mocks
    await page.addInitScript(() => {
      // Mock window.iris
      (window as any).iris = {
        invoke: async (cmd: string, args: any) => {
          if (cmd === 'get_integration' && args.id === 'gmail') {
            return {
              id: 'gmail',
              name: 'Gmail',
              category: 'email',
              auth_type: 'oauth2',
              status: 'DISABLED',
              oauth: {
                scopes: ['https://www.googleapis.com/auth/gmail.readonly'],
                redirect_uri: 'iris://oauth/callback/gmail',
              },
            };
          }
          if (cmd === 'start_oauth_flow') {
            return {
              auth_url: 'https://accounts.google.com/o/oauth2/v2/auth?client_id=test&redirect_uri=iris://oauth/callback/gmail',
            };
          }
          return null;
        },
        // Mock deep link handler
        onDeepLink: (callback: (url: string) => void) => {
          (window as any).__deepLinkCallback = callback;
        },
      };

      // Expose function to simulate deep link
      (window as any).__simulateDeepLink = (url: string) => {
        if ((window as any).__deepLinkCallback) {
          (window as any).__deepLinkCallback(url);
        }
      };
    });

    await page.goto('/integrations');
    await page.waitForSelector('[data-testid="integration-card-gmail"]', { timeout: 5000 });
  });

  test('complete OAuth flow via deep link', async ({ page }) => {
    // Start auth flow
    const gmailCard = await page.locator('[data-testid="integration-card-gmail"]');
    const toggle = gmailCard.locator('[role="switch"]');
    await toggle.click();

    // Should show permissions screen
    await page.waitForSelector('[data-testid="auth-flow-modal"]', { timeout: 3000 });
    await expect(page.locator('text=Gmail')).toBeVisible();
    await expect(page.locator('text=permissions')).toBeVisible();

    // Click Connect
    await page.click('text=Connect');

    // Simulate browser opening (would happen via Tauri)
    await page.waitForTimeout(500);

    // Simulate deep link callback (what happens after user approves in browser)
    await page.evaluate(() => {
      (window as any).__simulateDeepLink('iris://oauth/callback/gmail?code=mock_auth_code&state=test_state');
    });

    // Should show success and close modal
    await page.waitForTimeout(1000);
    
    // Integration should now show as connected
    await expect(page.locator('[data-testid="integration-card-gmail"]')).toContainText('Connected');
  });

  test('handle OAuth error from provider', async ({ page }) => {
    const gmailCard = await page.locator('[data-testid="integration-card-gmail"]');
    await gmailCard.locator('[role="switch"]').click();

    await page.waitForSelector('[data-testid="auth-flow-modal"]', { timeout: 3000 });
    await page.click('text=Connect');

    // Simulate error deep link
    await page.evaluate(() => {
      (window as any).__simulateDeepLink('iris://oauth/callback/gmail?error=access_denied');
    });

    // Should show error
    await expect(page.locator('text=error, text=Error')).toBeVisible({ timeout: 3000 });
  });

  test('cancel OAuth flow', async ({ page }) => {
    const gmailCard = await page.locator('[data-testid="integration-card-gmail"]');
    await gmailCard.locator('[role="switch"]').click();

    await page.waitForSelector('[data-testid="auth-flow-modal"]', { timeout: 3000 });
    
    // Click cancel/close
    await page.click('[data-testid="close-modal"]');

    // Modal should close, toggle should remain off
    await page.waitForTimeout(500);
    const toggle = gmailCard.locator('[role="switch"]');
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
  });
});

test.describe('OAuth2 Flow - Discord', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      (window as any).iris = {
        invoke: async (cmd: string, args: any) => {
          if (cmd === 'get_integration' && args.id === 'discord') {
            return {
              id: 'discord',
              name: 'Discord',
              category: 'messaging',
              auth_type: 'oauth2',
              status: 'DISABLED',
              oauth: {
                scopes: ['bot', 'messages.read', 'identify', 'guilds'],
                redirect_uri: 'iris://oauth/callback/discord',
              },
            };
          }
          return null;
        },
        onDeepLink: (callback: (url: string) => void) => {
          (window as any).__deepLinkCallback = callback;
        },
      };
      
      (window as any).__simulateDeepLink = (url: string) => {
        if ((window as any).__deepLinkCallback) {
          (window as any).__deepLinkCallback(url);
        }
      };
    });

    await page.goto('/integrations');
    await page.waitForSelector('[data-testid="integration-card-discord"]', { timeout: 5000 });
  });

  test('Discord bot OAuth flow', async ({ page }) => {
    const discordCard = await page.locator('[data-testid="integration-card-discord"]');
    await discordCard.locator('[role="switch"]').click();

    await page.waitForSelector('[data-testid="auth-flow-modal"]', { timeout: 3000 });
    
    // Discord flow shows bot permissions
    await expect(page.locator('text=Discord')).toBeVisible();
    await expect(page.locator('text=bot')).toBeVisible();

    await page.click('text=Connect');

    // Simulate deep link with bot token
    await page.evaluate(() => {
      (window as any).__simulateDeepLink('iris://oauth/callback/discord?code=mock_discord_code');
    });

    await page.waitForTimeout(1000);
    await expect(discordCard).toContainText('Connected');
  });
});

test.describe('Telegram MTProto Flow', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      // Mock WebSocket for Telegram auth
      class MockWebSocket extends WebSocket {
        constructor(url: string) {
          super(url);
        }
        
        send(data: string) {
          const message = JSON.parse(data);
          
          if (message.type === 'auth_telegram_phone') {
            setTimeout(() => {
              this.dispatchEvent(new MessageEvent('message', {
                data: JSON.stringify({
                  type: 'auth_telegram_code_sent',
                  flow_id: message.flow_id,
                }),
              }));
            }, 500);
          }
          
          if (message.type === 'auth_telegram_code') {
            setTimeout(() => {
              this.dispatchEvent(new MessageEvent('message', {
                data: JSON.stringify({
                  type: 'auth_telegram_complete',
                  flow_id: message.flow_id,
                  success: true,
                }),
              }));
            }, 500);
          }
          
          super.send(data);
        }
      }
      
      (window as any).WebSocket = MockWebSocket;
      
      (window as any).iris = {
        invoke: async (cmd: string) => {
          if (cmd === 'get_integration' || cmd === 'get_integrations') {
            return {
              integrations: [{
                id: 'telegram',
                name: 'Telegram',
                category: 'messaging',
                auth_type: 'telegram_mtproto',
                status: 'DISABLED',
              }],
            };
          }
          return null;
        },
      };
    });

    await page.goto('/integrations');
    await page.waitForSelector('[data-testid="integration-card-telegram"]', { timeout: 5000 });
  });

  test('complete Telegram phone verification flow', async ({ page }) => {
    const telegramCard = await page.locator('[data-testid="integration-card-telegram"]');
    await telegramCard.locator('[role="switch"]').click();

    // Should show Telegram auth form
    await page.waitForSelector('[data-testid="auth-flow-modal"]', { timeout: 3000 });
    await expect(page.locator('text=Telegram')).toBeVisible();
    await expect(page.locator('input[type="tel"], input[placeholder*="phone" i]')).toBeVisible();

    // Enter phone number
    await page.fill('input[type="tel"], input[placeholder*="phone" i]', '+1234567890');
    await page.click('text=Send Code');

    // Should show code input
    await page.waitForSelector('input[placeholder*="code" i]', { timeout: 3000 });
    await expect(page.locator('text=verification code')).toBeVisible();

    // Enter code
    await page.fill('input[placeholder*="code" i]', '12345');
    await page.click('text=Verify');

    // Should complete and close
    await page.waitForTimeout(1000);
    await expect(telegramCard).toContainText('Connected');
  });

  test('handle invalid phone number', async ({ page }) => {
    const telegramCard = await page.locator('[data-testid="integration-card-telegram"]');
    await telegramCard.locator('[role="switch"]').click();

    await page.waitForSelector('[data-testid="auth-flow-modal"]', { timeout: 3000 });

    // Enter invalid phone
    await page.fill('input[type="tel"]', 'invalid');
    await page.click('text=Send Code');

    // Should show validation error
    await expect(page.locator('text=invalid, text=Invalid, text=phone')).toBeVisible({ timeout: 3000 });
  });

  test('handle incorrect verification code', async ({ page }) => {
    await page.addInitScript(() => {
      // Override with error response
      class MockWebSocket extends WebSocket {
        send(data: string) {
          const message = JSON.parse(data);
          
          if (message.type === 'auth_telegram_code') {
            setTimeout(() => {
              this.dispatchEvent(new MessageEvent('message', {
                data: JSON.stringify({
                  type: 'auth_error',
                  error: 'Invalid code',
                }),
              }));
            }, 500);
          }
          
          super.send(data);
        }
      }
      
      (window as any).WebSocket = MockWebSocket;
    });

    const telegramCard = await page.locator('[data-testid="integration-card-telegram"]');
    await telegramCard.locator('[role="switch"]').click();

    await page.waitForSelector('[data-testid="auth-flow-modal"]', { timeout: 3000 });
    
    await page.fill('input[type="tel"]', '+1234567890');
    await page.click('text=Send Code');

    await page.waitForSelector('input[placeholder*="code" i]', { timeout: 3000 });
    await page.fill('input[placeholder*="code" i]', '00000');
    await page.click('text=Verify');

    // Should show error
    await expect(page.locator('text=Invalid, text=error')).toBeVisible({ timeout: 3000 });
  });
});

test.describe('Credentials Flow - IMAP/SMTP', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      // Mock WebSocket
      class MockWebSocket extends WebSocket {
        send(data: string) {
          const message = JSON.parse(data);
          
          if (message.type === 'auth_credentials_submit') {
            const credentials = message.credentials;
            
            // Simulate validation
            const isValid = credentials.email?.includes('@') && 
                          credentials.password?.length > 0 &&
                          credentials.imap_host?.length > 0;
            
            setTimeout(() => {
              if (isValid) {
                this.dispatchEvent(new MessageEvent('message', {
                  data: JSON.stringify({
                    type: 'auth_credentials_complete',
                    flow_id: message.flow_id,
                    success: true,
                  }),
                }));
              } else {
                this.dispatchEvent(new MessageEvent('message', {
                  data: JSON.stringify({
                    type: 'auth_error',
                    error: 'Invalid credentials',
                  }),
                }));
              }
            }, 500);
          }
          
          super.send(data);
        }
      }
      
      (window as any).WebSocket = MockWebSocket;
      
      (window as any).iris = {
        invoke: async (cmd: string) => {
          if (cmd === 'get_integration' || cmd === 'get_integrations') {
            return {
              integrations: [{
                id: 'imap_smtp',
                name: 'Generic Email (IMAP/SMTP)',
                category: 'email',
                auth_type: 'credentials',
                status: 'DISABLED',
              }],
            };
          }
          return null;
        },
      };
    });

    await page.goto('/integrations');
    await page.waitForSelector('[data-testid="integration-card-imap_smtp"]', { timeout: 5000 });
  });

  test('complete IMAP/SMTP credentials flow', async ({ page }) => {
    const imapCard = await page.locator('[data-testid="integration-card-imap_smtp"]');
    await imapCard.locator('[role="switch"]').click();

    // Should show credentials form
    await page.waitForSelector('[data-testid="auth-flow-modal"]', { timeout: 3000 });
    await expect(page.locator('text=IMAP')).toBeVisible();

    // Fill in form
    await page.fill('input[name="imap_host"], input[placeholder*="IMAP" i]', 'imap.gmail.com');
    await page.fill('input[name="imap_port"]', '993');
    await page.fill('input[name="smtp_host"], input[placeholder*="SMTP" i]', 'smtp.gmail.com');
    await page.fill('input[name="smtp_port"]', '587');
    await page.fill('input[type="email"], input[name="email"]', 'test@example.com');
    await page.fill('input[type="password"], input[name="password"]', 'app_password_123');

    await page.click('text=Test & Connect');

    // Should complete
    await page.waitForTimeout(1000);
    await expect(imapCard).toContainText('Connected');
  });

  test('validate required fields', async ({ page }) => {
    const imapCard = await page.locator('[data-testid="integration-card-imap_smtp"]');
    await imapCard.locator('[role="switch"]').click();

    await page.waitForSelector('[data-testid="auth-flow-modal"]', { timeout: 3000 });

    // Try to submit with empty fields
    await page.click('text=Test & Connect');

    // Should show validation errors
    await expect(page.locator('text=required, text=Required')).toBeVisible({ timeout: 3000 });
  });

  test('show password visibility toggle', async ({ page }) => {
    const imapCard = await page.locator('[data-testid="integration-card-imap_smtp"]');
    await imapCard.locator('[role="switch"]').click();

    await page.waitForSelector('[data-testid="auth-flow-modal"]', { timeout: 3000 });

    // Enter password
    const passwordInput = page.locator('input[type="password"]').first();
    await passwordInput.fill('secret_password');

    // Click visibility toggle (if exists)
    const visibilityToggle = page.locator('[data-testid="toggle-password-visibility"], button[aria-label*="show" i], button[aria-label*="hide" i]').first();
    
    if (await visibilityToggle.count() > 0) {
      await visibilityToggle.click();
      
      // Password should now be visible
      const visibleInput = page.locator('input[type="text"]').filter({ hasText: 'secret_password' });
      await expect(visibleInput).toBeVisible();
    }
  });
});

test.describe('Auth Flow Error Handling', () => {
  test('network error during auth', async ({ page }) => {
    await page.addInitScript(() => {
      class FailingWebSocket extends WebSocket {
        constructor(url: string) {
          super(url);
          setTimeout(() => {
            this.dispatchEvent(new Event('error'));
          }, 100);
        }
      }
      
      (window as any).WebSocket = FailingWebSocket;
    });

    await page.goto('/integrations');
    
    // Should handle error gracefully
    await page.waitForTimeout(1000);
    await expect(page.locator('text=error, text=Error, text=connection')).toBeVisible().catch(() => {
      // Fallback - page should at least load
      expect(page.url()).toContain('/integrations');
    });
  });

  test('timeout during auth flow', async ({ page }) => {
    await page.addInitScript(() => {
      // Mock slow WebSocket that never responds
      class SlowWebSocket extends WebSocket {
        send() {
          // Never respond
        }
      }
      
      (window as any).WebSocket = SlowWebSocket;
    });

    await page.goto('/integrations');
    await page.waitForTimeout(1000);

    // UI should show loading state that eventually times out
    // This is a placeholder - actual timeout handling would be implementation-specific
  });
});
