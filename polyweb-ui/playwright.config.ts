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

/**
 * Worker contract: stubbed scenarios are independent (each Playwright worker
 * is its own process, and the Before hook and the Given steps reset the stub
 * state per scenario), so they run fully parallel. CI sets
 * PLAYWRIGHT_WORKERS to fill the spot worker; local runs default to one
 * worker because the shared dev host is slow. Scenarios tagged `@serial`
 * hold or delay responses on fixed timers, so they run one at a time in
 * their own project.
 */
const configuredWorkers = process.env.PLAYWRIGHT_WORKERS ?? 1
const SERIAL_TAG = /@serial/

export default defineConfig({
  testDir,
  fullyParallel: true,
  workers: Number.isNaN(Number(configuredWorkers)) ? configuredWorkers : Number(configuredWorkers),
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: configuredBaseURL,
    trace: "on-first-retry",
    // A click on a missing control fails in 10 s instead of the 30 s test timeout.
    actionTimeout: 10_000,
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
      grepInvert: SERIAL_TAG,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "chromium-serial",
      grep: SERIAL_TAG,
      fullyParallel: false,
      workers: 1,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
})
