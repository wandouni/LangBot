import { defineConfig, devices } from '@playwright/test';

const port = process.env.LANGBOT_WIZARD_WEB_PORT;
if (!port || !process.env.LANGBOT_WIZARD_API_URL) {
  throw new Error(
    'Run through tests/e2e/test_wizard_real_stack.py with its isolated backend',
  );
}

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: 'wizard-real-stack.spec.ts',
  workers: 1,
  retries: 0,
  timeout: 180_000,
  reporter: 'list',
  outputDir: process.env.LANGBOT_WIZARD_BROWSER_OUTPUT,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: `node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: { VITE_API_PROXY_TARGET: process.env.LANGBOT_WIZARD_API_URL },
  },
});
