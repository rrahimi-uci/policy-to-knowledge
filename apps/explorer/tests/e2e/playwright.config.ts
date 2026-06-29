import { defineConfig, devices } from "@playwright/test";

/**
 * Explorer – Playwright E2E configuration.
 *
 * The tests assume the Flask server is already running on :5001.
 * Start it before running tests:
 *   cd ../.. && PYTHONPATH=. SERVER_PORT=5001 .venv/bin/python src/server.py
 */
export default defineConfig({
  testDir: ".",
  fullyParallel: false,          // tests share server state; run sequentially
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["html", { open: "never" }], ["list"]],
  timeout: 120_000,              // chat LLM calls can be slow

  use: {
    baseURL: process.env.BASE_URL || "http://localhost:5001/app",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 30_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
