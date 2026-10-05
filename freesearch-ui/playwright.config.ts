import { defineConfig, devices } from "@playwright/test"
import { defineBddConfig } from "playwright-bdd"

/**
 * Playwright-BDD contract: Gherkin sources in tests/features, typed steps in
 * tests/steps, generated specs in tests/features-gen (never edited by hand).
 *
 * Port contract: PLAYWRIGHT_PORT and PLAYWRIGHT_BASE_URL override the
 * defaults without changing them (default 5173). Overrides reuse the running
 * dev server (reuseExistingServer) and never hardcode an alternate port.
 */
const configuredPort = Number(process.env.PLAYWRIGHT_PORT ?? process.env.VITE_PORT ?? 5174)
const configuredBaseURL =
  process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${configuredPort}`

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
    baseURL: configuredBaseURL,
    trace: "on-first-retry",
  },
  snapshotPathTemplate: "tests/snapshots/{projectName}/{testFilePath}/{arg}{ext}",
  webServer: {
    command: "pnpm dev",
    port: configuredPort,
    reuseExistingServer: true,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
})
