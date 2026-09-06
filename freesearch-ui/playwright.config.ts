import { defineConfig, devices } from "@playwright/test"
import { defineBddConfig } from "playwright-bdd"

/**
 * Playwright-BDD contract: Gherkin sources in tests/features, typed steps in
 * tests/steps, generated specs in tests/features-gen (never edited by hand).
 */
const testDir = defineBddConfig({
  featuresRoot: "tests/features",
  steps: ["tests/steps/**/*.ts"],
  outputDir: "tests/features-gen",
})

export default defineConfig({
  testDir,
  fullyParallel: false,
  workers: 1,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  snapshotPathTemplate: "tests/snapshots/{projectName}/{testFilePath}/{arg}{ext}",
  webServer: {
    command: "pnpm dev",
    port: 5173,
    reuseExistingServer: true,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
})
