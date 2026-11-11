import { defineConfig, devices } from "@playwright/test";

import { E2EPhases } from "./support/phases";

/**
 * Smoke tests of the whole app in a browser, against the throwaway fake-LLM stack (`make e2e`; docs/process/testing.md).
 * Two phases (`bun run.ts`, support/phases.ts): the specs that change shared state run alone on one worker, the rest run on
 * several workers, each with a learner of its own. The default here is one worker, for a run of a single spec by hand.
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
  projects: [
    // Opens every page once so `next dev` has compiled them all (tests/warm-up.setup.ts); the specs wait for it.
    { name: "warm-up", testMatch: /.*\.setup\.ts/, use: { ...devices["Desktop Chrome"] } },
    // The specs that change what every learner sees (prices, credit settings, testimonials): run alone, on one worker, first.
    { name: "global", testMatch: E2EPhases.globalPattern(), dependencies: ["warm-up"], use: { ...devices["Desktop Chrome"] } },
    // Every other spec makes its own learner, so several run side by side (`bun run.ts` picks the worker count).
    { name: "learner", testMatch: /.*\.spec\.ts/, testIgnore: E2EPhases.globalPattern(), dependencies: ["warm-up"], use: { ...devices["Desktop Chrome"] } },
  ],
});
