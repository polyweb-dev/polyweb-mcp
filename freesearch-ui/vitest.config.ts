import path from "node:path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Playwright-BDD emits Playwright specs under tests/features-gen; never run them under vitest.
    exclude: ["node_modules", "dist", "tests/features-gen/**", "test-results/**", "playwright-report/**"],
    // worker_threads avoid subprocess pipes, which restricted sandboxes deny
    pool: "threads",
  },
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
})
