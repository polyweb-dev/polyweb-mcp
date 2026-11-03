import { describe, expect, it } from "vitest"
import {
  decodeAvailableCredential,
  decodeBinding,
  decodeGrant,
  decodeOAuthDevice,
  decodeOAuthStatus,
  decodeProjectCredential,
  decodeProviderTypeView,
  decodeSystemCredential,
} from "./credentialsWire"

const FAKE_SECRET = "fake-provider-key-123"

/** Fields a response must never carry into the client, whatever the server sends. */
const SECRET_LOOKING = {
  secret: FAKE_SECRET,
  api_key: FAKE_SECRET,
  access_token: "fake-access-token",
  refresh_token: "fake-refresh-token",
  device_code: "fake-device-code",
  client_secret: "fake-client-secret",
  fingerprint: "TAV_••••9a1e",
  owner_project_id: "owner-project",
  created_by: "creator",
}

function serialized(value: unknown): string {
  return JSON.stringify(value)
}

describe("decodeSystemCredential", () => {
  it("keeps only the documented metadata", () => {
    const decoded = decodeSystemCredential({
      id: "c1",
      provider_type: "tavily",
      owner_scope: "system",
      label: "Shared Tavily",
      auth_mode: "api_key",
      generation: 3,
      status: "active",
      ...SECRET_LOOKING,
    })
    expect(decoded).toEqual({
      id: "c1",
      providerType: "tavily",
      label: "Shared Tavily",
      authMode: "api_key",
      generation: 3,
      status: "active",
    })
    for (const value of Object.values(SECRET_LOOKING)) expect(serialized(decoded)).not.toContain(value)
  })

  it("drops a row without id or provider type", () => {
    expect(decodeSystemCredential({ label: "x" })).toBeNull()
    expect(decodeSystemCredential("nope")).toBeNull()
  })
})

describe("decodeProjectCredential", () => {
  it("keeps can_manage and generation and nothing secret", () => {
    const decoded = decodeProjectCredential({
      id: "p1",
      provider_type: "parallel",
      owner_scope: "project",
      label: "Team Parallel",
      auth_mode: "oauth",
      status: "active",
      permitted_operations: ["fetch", "search", "crawl"],
      can_manage: true,
      generation: null,
      ...SECRET_LOOKING,
    })
    expect(decoded).toEqual({
      id: "p1",
      providerType: "parallel",
      owner: "project",
      label: "Team Parallel",
      authMode: "oauth",
      status: "active",
      permittedOperations: ["search", "fetch"],
      canManage: true,
      generation: null,
    })
    for (const value of Object.values(SECRET_LOOKING)) expect(serialized(decoded)).not.toContain(value)
  })

  it("rejects an unknown owner scope", () => {
    expect(decodeProjectCredential({ id: "p1", provider_type: "x", owner_scope: "other" })).toBeNull()
  })
})

describe("decodeProviderTypeView", () => {
  it("decodes capability, system state, credentials and bindings", () => {
    const decoded = decodeProviderTypeView({
      provider_type: "tavily",
      capability: ["search", "fetch"],
      kill_switch: true,
      system_enabled_operations: ["search"],
      available: true,
      enabled: false,
      effective_operations: [],
      credentials: [
        {
          id: "c1",
          label: "Shared",
          owner_scope: "system",
          auth_mode: "api_key",
          status: "active",
          health_status: "healthy",
          granted_operations: ["search"],
          supported_operations: ["search", "fetch"],
          pools: [{ operation_scope: "search", pool_id: "pool-1", label: "Tavily account", status: "active", upstream_scope: "account", balance: 99 }],
          ...SECRET_LOOKING,
        },
        { label: "no id" },
      ],
      bindings: [
        { id: "b1", credential_id: "c1", route_label: "primary", priority: 10, enabled_operations: ["search"], effective_operations: [] },
      ],
      secret: FAKE_SECRET,
    })
    expect(decoded?.name).toBe("Tavily")
    expect(decoded?.killSwitch).toBe(true)
    expect(decoded?.credentials).toHaveLength(1)
    expect(decoded?.credentials[0]?.pools).toEqual([{ operation: "search", poolId: "pool-1", label: "Tavily account" }])
    expect(decoded?.bindings[0]).toEqual({
      id: "b1",
      credentialId: "c1",
      routeLabel: "primary",
      priority: 10,
      enabledOperations: ["search"],
      effectiveOperations: [],
    })
    for (const value of Object.values(SECRET_LOOKING)) expect(serialized(decoded)).not.toContain(value)
    expect(serialized(decoded)).not.toContain("balance")
  })

  it("drops a provider without a type", () => {
    expect(decodeProviderTypeView({ capability: [] })).toBeNull()
  })
})

describe("decodeAvailableCredential and decodeBinding", () => {
  it("fall back to safe defaults", () => {
    expect(decodeAvailableCredential({ id: "c", owner_scope: "project" })).toMatchObject({
      label: "c",
      authMode: "api_key",
      health: null,
      pools: [],
    })
    expect(decodeBinding({ id: "b", credential_id: "c", enabled_operations: ["fetch"] })).toMatchObject({
      effectiveOperations: ["fetch"],
      priority: 0,
    })
  })
})

describe("decodeGrant", () => {
  it("keeps the permitted operations and version", () => {
    expect(
      decodeGrant({ credential_id: "c", project_id: "p", permitted_operations: ["search"], version: 2, granted_by: "x" })
    ).toEqual({ credentialId: "c", projectId: "p", permittedOperations: ["search"], version: 2 })
  })
})

describe("decodeOAuthDevice", () => {
  it("keeps the user code, link and timings only", () => {
    const decoded = decodeOAuthDevice({
      user_code: "WDJB-MJHT",
      verification_uri: "https://auth.example.test/device",
      interval: 7,
      expires_in: 900,
      device_code: "fake-device-code",
      client_secret: "fake-client-secret",
    })
    expect(decoded).toEqual({
      userCode: "WDJB-MJHT",
      verificationUri: "https://auth.example.test/device",
      intervalSeconds: 7,
      expiresInSeconds: 900,
    })
    expect(serialized(decoded)).not.toContain("fake-device-code")
  })

  it("rejects a non-http verification link", () => {
    expect(decodeOAuthDevice({ user_code: "A", verification_uri: "javascript:alert(1)", interval: 5, expires_in: 60 })).toBeNull()
  })
})

describe("decodeOAuthStatus", () => {
  it("keeps the status and a pending interval, never token material", () => {
    expect(decodeOAuthStatus({ credential_id: "c", status: "pending", interval: 9, access_token: "t" })).toEqual({
      status: "pending",
      intervalSeconds: 9,
    })
    expect(decodeOAuthStatus({ status: "connected", interval: null })).toEqual({ status: "connected", intervalSeconds: null })
    expect(decodeOAuthStatus({ status: "weird" })).toBeNull()
  })
})
