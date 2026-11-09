import { describe, expect, it } from "vitest"
import {
  credentialProviderTypes,
  providerTypeName,
  supportedOperationsOf,
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
})
