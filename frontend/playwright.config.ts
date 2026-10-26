import { defineConfig, devices } from '@playwright/test';

// The e2e run starts its own backend (test-only fake model via backend/tests/fake_server.py, dummy key,
// freshly seeded DB in e2e/.tmp, pay when the Invoice Queue is empty off) on port 8100 and its own `ng serve` on 4300 proxied
// to it, so it never touches your dev data or calls a real LLM.
const BACKEND_PORT = 8100;
const FRONTEND_PORT = 4300;

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1400, height: 900 } } }],
  webServer: [
    {
      command: 'bash e2e/start-backend.sh',
      env: { BACKEND_PORT: String(BACKEND_PORT) },
      url: `http://localhost:${BACKEND_PORT}/api/stats`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npx ng serve --port ${FRONTEND_PORT} --proxy-config e2e/proxy.e2e.json`,
      url: `http://localhost:${FRONTEND_PORT}`,
      reuseExistingServer: false,
      timeout: 240_000,
    },
  ],
});
