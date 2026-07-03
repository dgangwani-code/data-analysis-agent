import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright config for the Phase 1 golden-path E2E smoke test.
 *
 * The gate command (spec/roadmap.md) starts the real backend (FastAPI,
 * serving the static Next.js export at /app) before running Playwright:
 *
 *   cd frontend && pnpm build && cd .. && \
 *   uv run python -m src & sleep 2 && \
 *   cd frontend && npx playwright test tests/e2e/ --reporter=line
 *
 * So `baseURL` points at the live server — no `webServer` block here, since
 * this config never launches its own server (that is the gate command's
 * job, and the backend is not an npm-managed process).
 */
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'line',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8001',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
