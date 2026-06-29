import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/benchmark',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['line'], ['json', { outputFile: 'test-results/benchmark-results.json' }]],
  use: {
    baseURL: process.env.IRIS_BENCHMARK_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    headless: process.env.IRIS_BENCHMARK_HEADLESS !== 'false',
    viewport: { width: 1280, height: 800 },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
