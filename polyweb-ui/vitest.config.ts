import path from "node:path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

// POLYWEB_JUNIT_DIR adds a JUnit report (layer 1); POLYWEB_TEST_METRICS=1
// turns on per-test resource metrics in src/test/resource-metrics.ts (layer 2).
const junitDir = process.env.POLYWEB_JUNIT_DIR

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts", "./src/test/resource-metrics.ts"],
    ...(junitDir
      ? {
          reporters: ["default", "junit"],
          outputFile: { junit: path.resolve(junitDir, "vitest.xml") },
        }
      : {}),
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: [
      "node_modules",
      "dist",
      ".stryker-tmp/**",
      "tests/**",
      "test-results/**",
      "playwright-report/**"
    ],
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov", "json"],
      reportsDirectory: "./coverage",
    },
    // worker_threads avoid subprocess pipes, which restricted sandboxes deny
    pool: "threads",
    maxWorkers: 16,
  },
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
})
