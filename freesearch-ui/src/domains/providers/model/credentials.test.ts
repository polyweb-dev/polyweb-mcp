import { describe, expect, it } from "vitest"
import {
  authModeLabel,
  credentialProviderTypes,
  oauthStatusText,
  providerTypeName,

  supportedOperationsOf,
  supportsOAuth,
} from "./credentials"

describe("credential model helpers", () => {
  it("names the OAuth statuses", () => {
    expect(oauthStatusText("pending")).toBe("Waiting for approval…")
    expect(oauthStatusText("connected")).toBe("Connected")
    expect(oauthStatusText("refresh_failed")).toBe("Connection needs attention")
    expect(oauthStatusText("disconnected")).toBe("Not connected")
  })

  it("labels auth modes", () => {
    expect(authModeLabel("oauth")).toBe("OAuth")
    expect(authModeLabel("api_key")).toBe("API key")
  })

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
