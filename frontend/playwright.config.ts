import { defineConfig } from "@playwright/test";

// End-to-end tests drive the real UI, API, worker and database, with the SCRIPTED
// test provider (deterministic, not AI). Results are labelled "mocked provider".
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:8799",
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    // Optional: reuse an already-installed Chromium instead of `npx playwright install chromium`.
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {},
  },
  webServer: {
    command: "bash e2e/test-server.sh",
    url: "http://127.0.0.1:8799/api/health",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
