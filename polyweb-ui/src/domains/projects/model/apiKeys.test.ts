import { describe, expect, it } from "vitest"
import { API_KEY_SCOPES, API_KEY_SCOPE_LABELS, isApiKeyScope } from "./apiKeys"

describe("API key scopes", () => {
  it("lists the two execution scopes with their labels", () => {
    expect(API_KEY_SCOPES).toEqual(["search.execute", "fetch.execute"])
    expect(API_KEY_SCOPE_LABELS).toEqual({ "search.execute": "Search", "fetch.execute": "Fetch" })
  })

  it("recognizes only execution scopes", () => {
    expect(isApiKeyScope("search.execute")).toBe(true)
    expect(isApiKeyScope("fetch.execute")).toBe(true)
    expect(isApiKeyScope("tokens.manage")).toBe(false)
    expect(isApiKeyScope(undefined)).toBe(false)
  })
})
