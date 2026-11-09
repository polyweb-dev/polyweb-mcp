/**
 * BDD Acceptance (Red phase) — C1 Carbon Black theme.
 *
 * Executable mirror of tests/features/carbon-black-theme.feature.
 * Reads the theme sources statically and asserts the VSCode palette
 * acceptance criteria with exact values (no truthy theater).
 *
 * AC mapping:
 *   AC-C1-1  --surface is exactly #1e1e1e
 *   AC-C1-2  --elevated is exactly #252526
 *   AC-C1-3  --border-subtle is exactly #3e3e42
 *   AC-C1-4  --signal is exactly #007acc
 *   AC-C1-5  --signal-muted is exactly rgba(0, 122, 204, 0.14)
 *   AC-C1-6  no oklch() remains anywhere in index.css
 *   AC-C1-7  no legacy-palette hexes/tints remain in index.css
 *   AC-C1-8  Header.tsx uses rgba(37, 37, 38, 0.85), legacy 13,16,23 gone
 *   AC-C1-9  shadcn vars map onto the VSCode hexes
 */
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

const testDir = import.meta.dirname
const indexCssSource = readFileSync(path.resolve(testDir, "../index.css"), "utf8")
const headerSource = readFileSync(
  path.resolve(testDir, "../components/layout/Header.tsx"),
  "utf8"
)

/** Lowercase, all whitespace stripped — for exact color-literal comparison. */
const norm = (value: string): string => value.toLowerCase().replace(/\s+/g, "")

/** Raw value of a `--token: <value>;` declaration, or null when absent. */
const tokenValue = (source: string, name: string): string | null => {
  const match = source.match(new RegExp(`--${name}\\s*:\\s*([^;]+);`))
  return match ? match[1].trim() : null
}

const tokenValueNorm = (source: string, name: string): string | null => {
  const value = tokenValue(source, name)
  return value === null ? null : norm(value)
}

/** VSCode Carbon Black dark scale allowed for shadcn surface tokens. */
const VSCODE_DARK_SCALE = ["#1e1e1e", "#252526", "#2d2d30"] as const

describe("Feature: C1 Carbon Black theme", () => {
  describe("Scenario: Core tokens use the VSCode Carbon Black palette", () => {
    it("AC-C1-1: --surface is exactly #1e1e1e", () => {
      expect(tokenValueNorm(indexCssSource, "surface")).toBe("#1e1e1e")
    })

    it("AC-C1-2: --elevated is exactly #252526", () => {
      expect(tokenValueNorm(indexCssSource, "elevated")).toBe("#252526")
    })

    it("AC-C1-3: --border-subtle is exactly #3e3e42", () => {
      expect(tokenValueNorm(indexCssSource, "border-subtle")).toBe("#3e3e42")
    })

    it("AC-C1-4: --signal is exactly #007acc", () => {
      expect(tokenValueNorm(indexCssSource, "signal")).toBe("#007acc")
    })

    it("AC-C1-5: --signal-muted is exactly rgba(0, 122, 204, 0.14)", () => {
      expect(tokenValueNorm(indexCssSource, "signal-muted")).toBe("rgba(0,122,204,0.14)")
    })
  })

  describe("Scenario: No legacy palette leaks in index.css", () => {
    it("AC-C1-6: contains no oklch() references", () => {
      expect(norm(indexCssSource).includes("oklch(")).toBe(false)
    })

    it.each(["#0d1017", "#171c26", "#262e3d", "#3b82f6"])(
      "AC-C1-7: legacy hex %s is gone",
      (legacyHex) => {
        expect(norm(indexCssSource).includes(legacyHex)).toBe(false)
      }
    )

    it("AC-C1-7: legacy signal tint rgb(59, 130, 246) is gone", () => {
      expect(norm(indexCssSource).includes("59,130,246")).toBe(false)
    })
  })

  describe("Scenario: Header backdrop uses the Carbon Black elevated tone", () => {
    it("AC-C1-8: Header uses rgba(37, 37, 38, 0.85) as its backdrop", () => {
      expect(norm(headerSource).includes("rgba(37,37,38,0.85)")).toBe(true)
    })

    it("AC-C1-8: legacy header tint 13, 16, 23 is gone", () => {
      expect(norm(headerSource).includes("13,16,23")).toBe(false)
    })
  })

  describe("Scenario: shadcn tokens map onto the VSCode palette", () => {
    it("AC-C1-9: --primary and --ring map to the VSCode signal #007acc", () => {
      expect(tokenValueNorm(indexCssSource, "primary")).toBe("#007acc")
      expect(tokenValueNorm(indexCssSource, "ring")).toBe("#007acc")
    })

    it("AC-C1-9: --border and --input map to the VSCode chrome #3e3e42", () => {
      expect(tokenValueNorm(indexCssSource, "border")).toBe("#3e3e42")
      expect(tokenValueNorm(indexCssSource, "input")).toBe("#3e3e42")
    })

    it("AC-C1-9: --background maps to the VSCode surface #1e1e1e", () => {
      expect(tokenValueNorm(indexCssSource, "background")).toBe("#1e1e1e")
    })

    it("AC-C1-9: card/popover/secondary/muted/accent/sidebar surfaces stay inside the VSCode dark scale", () => {
      const surfaceTokens = [
        "card",
        "popover",
        "secondary",
        "muted-bg",
        "accent",
        "sidebar",
        "sidebar-accent",
      ]
      expect(surfaceTokens).not.toHaveLength(0)
      for (const name of surfaceTokens) {
        const value = tokenValueNorm(indexCssSource, name)
        expect(
          value,
          `shadcn --${name} should map into the VSCode dark scale`
        ).not.toBeNull()
        expect(VSCODE_DARK_SCALE).toContain(value)
      }
    })

    it("AC-C1-9: no shadcn token declaration uses oklch()", () => {
      const shadcnBlock = indexCssSource.slice(
        indexCssSource.indexOf("shadcn token mappings")
      )
      expect(shadcnBlock.length).toBeGreaterThan(0)
      expect(norm(shadcnBlock).includes("oklch(")).toBe(false)
    })
  })
})
