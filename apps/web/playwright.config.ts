import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "node e2e/mock-api.mjs",
      port: 8001,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1",
      port: 3000,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        OPEN_SIGNAL_API_URL: "http://127.0.0.1:8001",
        OPEN_SIGNAL_PUBLICATION_BASE_URL: "",
        OPEN_SIGNAL_REVALIDATE_TOKEN: "e2e-revalidation-token",
      },
    },
  ],
});
