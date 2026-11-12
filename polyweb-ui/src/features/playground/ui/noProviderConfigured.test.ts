import { describe, expect, it } from "vitest"
import { isNoProviderConfigured } from "./noProviderConfigured"

describe("isNoProviderConfigured", () => {
  it.each([
    "no provider is configured for this project: the project has no assigned pool; create a pool for the selected provider and assign it to this project, then retry",
    "no required provider is configured for this project: keenable has no assigned pool; create a pool for the selected provider and assign it to this project, then retry",
  ])("recognises the backend missing-pool message %#", (message) => {
    expect(isNoProviderConfigured(message)).toBe(true)
  })

  it("is case-insensitive and ignores unrelated or empty errors", () => {
    expect(isNoProviderConfigured("No Required Provider Is Configured for this project")).toBe(true)
    expect(isNoProviderConfigured("no required provider is eligible: tavily")).toBe(false)
    expect(isNoProviderConfigured("Request timed out")).toBe(false)
    expect(isNoProviderConfigured(null)).toBe(false)
  })
})
