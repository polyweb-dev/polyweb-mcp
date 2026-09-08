import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { expect } from "@playwright/test"
import { Given, Then } from "./fixtures"

/**
 * C1 Carbon Black theme — static acceptance steps.
 *
 * These steps assert the VSCode palette migration at the source level
 * (design tokens in src/index.css, backdrop literal in Header.tsx), so no
 * browser page or backend stub is required. The @theme scenarios never touch
 * the network: they read the two theme files from the repository checkout.
 */

const indexCssPath = resolve("src/index.css")
const headerPath = resolve("src/components/layout/Header.tsx")

const norm = (value: string): string => value.toLowerCase().replace(/\s+/g, "")

const readIndexCss = (): string => readFileSync(indexCssPath, "utf8")
const readHeader = (): string => readFileSync(headerPath, "utf8")

const tokenValueNorm = (source: string, name: string): string | null => {
  const match = source.match(new RegExp(`--${name}\\s*:\\s*([^;]+);`))
  return match ? norm(match[1].trim()) : null
}

const VSCODE_DARK_SCALE = ["#1e1e1e", "#252526", "#2d2d30"]

Given("the Carbon Black theme files", async () => {
  await Promise.resolve()
  expect(() => readFileSync(indexCssPath, "utf8")).not.toThrow()
  expect(() => readFileSync(headerPath, "utf8")).not.toThrow()
})

Then("the {string} token should be exactly {string}", async (_, token: string, expected: string) => {
  await Promise.resolve()
  const name = token.replace(/^--/, "")
  expect(tokenValueNorm(readIndexCss(), name)).toBe(norm(expected))
})

Then("index.css should contain no {string} references", async (_, ref: string) => {
  await Promise.resolve()
  expect(norm(readIndexCss()).includes(norm(ref))).toBe(false)
})

Then("index.css should not contain legacy hex {string}", async (_, hex: string) => {
  await Promise.resolve()
  expect(norm(readIndexCss()).includes(norm(hex))).toBe(false)
})

Then(
  "index.css should not reference the legacy signal tint {string}",
  async (_, tint: string) => {
    await Promise.resolve()
    expect(norm(readIndexCss()).includes(norm(tint))).toBe(false)
  }
)

Then("Header.tsx should use {string} as its backdrop", async (_, expected: string) => {
  await Promise.resolve()
  expect(norm(readHeader()).includes(norm(expected))).toBe(true)
})

Then("Header.tsx should not reference the legacy tint {string}", async (_, tint: string) => {
  await Promise.resolve()
  expect(norm(readHeader()).includes(norm(tint))).toBe(false)
})

Then(
  "the shadcn {string} and {string} tokens should be {string}",
  async (_, first: string, second: string, expected: string) => {
    await Promise.resolve()
    const css = readIndexCss()
    expect(tokenValueNorm(css, first.replace(/^--/, ""))).toBe(norm(expected))
    expect(tokenValueNorm(css, second.replace(/^--/, ""))).toBe(norm(expected))
  }
)

Then("the shadcn {string} token should be {string}", async (_, token: string, expected: string) => {
  await Promise.resolve()
  expect(tokenValueNorm(readIndexCss(), token.replace(/^--/, ""))).toBe(norm(expected))
})

Then(
  "the shadcn surface tokens should stay inside the VSCode dark scale",
  async () => {
    await Promise.resolve()
    const css = readIndexCss()
    const surfaceTokens = [
      "card",
      "popover",
      "secondary",
      "muted-bg",
      "accent",
      "sidebar",
      "sidebar-accent",
    ]
    for (const name of surfaceTokens) {
      const value = tokenValueNorm(css, name)
      expect(value, `shadcn --${name} should map into the VSCode dark scale`).not.toBeNull()
      expect(VSCODE_DARK_SCALE).toContain(value)
    }
  }
)

Then("no shadcn token should use {string}", async (_, ref: string) => {
  await Promise.resolve()
  const css = readIndexCss()
  const shadcnBlock = css.slice(css.indexOf("shadcn token mappings"))
  expect(shadcnBlock.length).toBeGreaterThan(0)
  expect(norm(shadcnBlock).includes(norm(ref))).toBe(false)
})
