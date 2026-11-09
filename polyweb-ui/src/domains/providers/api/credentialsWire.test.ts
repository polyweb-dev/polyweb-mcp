import { describe, expect, it } from "vitest"
import {
  decodeAvailableCredential,
  decodeBinding,
  decodeProviderTypeView,
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

describe("decodeProviderTypeView", () => {
  it("derives keyless access from catalog prices rather than a separate flag", () => {
    expect(decodeProviderTypeView({ provider_type: "keenable", keyless: false, keyless_call_cost_usd: { search: "0", fetch: "0" } })?.keyless).toBe(true)
    expect(decodeProviderTypeView({ provider_type: "tavily", keyless: true })?.keyless).toBe(false)
    expect(decodeProviderTypeView({ provider_type: "exa" })?.keyless).toBe(false)
  })

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
    expect(decoded?.credentials[0]).toEqual({ id: "c1", label: "Shared", authMode: "api_key" })
    expect(decoded?.bindings[0]).toEqual({
      credentialId: "c1",
      priority: 10,
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
    })
    expect(decodeBinding({ id: "b", credential_id: "c", enabled_operations: ["fetch"] })).toMatchObject({
      effectiveOperations: ["fetch"],
      priority: 0,
    })
  })

})
