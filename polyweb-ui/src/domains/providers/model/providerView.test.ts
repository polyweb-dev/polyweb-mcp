import { describe, expect, it } from "vitest"
import {
  KEYLESS_AUTH_LABEL,
  KEYLESS_AUTH_MODE,
  authModeNeedsSecret,
  credentialAuthModes,
  credentialProviderTypes,
  keylessProviderTypes,
  providerTypeName,
  supportedOperationsOf,
  supportsKeyless,
  supportsOAuth,
} from "./providerView"

describe("provider catalog helpers", () => {
  it("derives supported operations from the catalog", () => {
    expect(supportedOperationsOf("brave")).toEqual(["search"])
    expect(supportedOperationsOf("tavily")).toEqual(["search", "fetch"])
    expect(supportedOperationsOf("unknown-provider")).toEqual(["search", "fetch"])
  })

  it("allows OAuth only for Parallel", () => {
    expect(supportsOAuth("parallel")).toBe(true)
    expect(supportsOAuth("tavily")).toBe(false)
  })

  it("names wire provider types and lists them", () => {
    expect(providerTypeName("you")).toBe("You.com")
    expect(providerTypeName("mystery")).toBe("mystery")
    expect(credentialProviderTypes()).toContain("parallel")
  })

  it("derives keyless support from the static catalog, never OAuth providers", () => {
    expect(supportsKeyless("keenable")).toBe(true)
    expect(supportsKeyless("tavily")).toBe(true)
    expect(supportsKeyless("exa")).toBe(false)
    expect(supportsKeyless("parallel")).toBe(false)
    expect(supportsKeyless("mystery")).toBe(false)
    expect(keylessProviderTypes()).toEqual(["keenable", "tavily"])
  })

  it("offers keyless first for supported providers and never alongside OAuth", () => {
    expect(credentialAuthModes("keenable")).toEqual([
      { value: KEYLESS_AUTH_MODE, label: KEYLESS_AUTH_LABEL },
      { value: "api_key", label: "API key" },
    ])
    expect(credentialAuthModes("tavily")).toEqual([
      { value: KEYLESS_AUTH_MODE, label: KEYLESS_AUTH_LABEL },
      { value: "api_key", label: "API key" },
    ])
    expect(credentialAuthModes("parallel")).toEqual([
      { value: "api_key", label: "API key" },
      { value: "oauth", label: "OAuth" },
    ])
    expect(credentialAuthModes("exa")).toEqual([{ value: "api_key", label: "API key" }])
    expect(authModeNeedsSecret("api_key")).toBe(true)
    expect(authModeNeedsSecret("oauth")).toBe(false)
    expect(authModeNeedsSecret(KEYLESS_AUTH_MODE)).toBe(false)
  })
})
