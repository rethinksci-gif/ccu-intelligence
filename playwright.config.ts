import { defineConfig, devices } from '@playwright/test';
const base = process.env.BASE_PATH || '/';
export default defineConfig({
  testDir: './tests/browser',
  timeout: 30000,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: `http://127.0.0.1:4322${base}`, trace: 'retain-on-failure' },
  webServer: {
    command: 'npm run preview -- --port 4322 --ignore-lock',
    url: `http://127.0.0.1:4322${base}`,
    reuseExistingServer: !process.env.CI,
    env: { ASTRO_TELEMETRY_DISABLED: '1' },
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
});
