import { defineConfig, devices } from "@playwright/test"

/**
 * Playwright E2E config for voice → chat pipeline tests.
 *
 * Points to the Next.js dev server (expected on localhost:3000).
 * Run with:
 *   npx playwright test --config playwright.e2e.config.ts
 *
 * To start the dev server first:
 *   npx playwright test --config playwright.e2e.config.ts --reporter=list
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 1,
  reporter: [["list"], ["html", { outputFolder: "test-results/e2e-report" }]],
  use: {
    // Base URL for the Next.js app
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Increase timeout for E2E tests (includes web socket wait)
  timeout: 30_000,
})
