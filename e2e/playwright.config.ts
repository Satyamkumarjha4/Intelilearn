import { defineConfig, devices } from "@playwright/test";

/**
 * Smoke tests of the whole app in a browser, against the throwaway fake-LLM stack (`make e2e`; docs/testing.md).
 * One worker: the tests share one database and one fake model, and a lesson build is the slow part, not the browser.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:7100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
