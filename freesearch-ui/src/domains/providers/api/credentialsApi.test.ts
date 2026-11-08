import { afterEach, describe, expect, it, vi } from "vitest"
import { installFetchStub, ok } from "@/test/fetchMock"
import { createVaultKey, disconnectVaultOAuth, pollVaultOAuth, rotateVaultKey, startVaultOAuth } from "@/domains/vault"
import { listProjectCredentials } from "./credentialsApi"

const FAKE_SECRET = "fake-provider-key-123"
const SYSTEM_ROW = { id: "c1", provider_type: "tavily", owner_scope: "system", label: "Shared", auth_mode: "api_key", generation: 1, status: "active" }
const PROJECT_ROW = { ...SYSTEM_ROW, owner_scope: "project", permitted_operations: ["search"], can_manage: true }
const VAULT_ROW = { id: "c1", provider_type: "tavily", label: "Shared", auth_mode: "api_key", generation: 1,
  status: "active", created_at: "2026-01-01", capacity: null, overcommit: true, contention_mode: "equal", pool_count: 0 }

describe("credentialsApi", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("creates an API key credential with the secret in the body only", async () => {
    const stub = installFetchStub(() => ok({ ...VAULT_ROW, secret: FAKE_SECRET }, 201))
    const created = await createVaultKey({ provider_type: "tavily", label: "Shared", auth_mode: "api_key", secret: FAKE_SECRET })
    const request = stub.requests[0]
    expect(request?.url).toBe("/api/v1/account/vault/keys")
    expect(request?.method).toBe("POST")
    expect(request?.body).toEqual({ provider_type: "tavily", label: "Shared", auth_mode: "api_key", secret: FAKE_SECRET })
    expect(request?.url).not.toContain(FAKE_SECRET)
    expect(JSON.stringify(created)).not.toContain(FAKE_SECRET)
  })

  it("never sends a secret for an OAuth credential", async () => {
    const stub = installFetchStub(() => ok({ ...VAULT_ROW, provider_type: "parallel", auth_mode: "oauth" }, 201))
    await createVaultKey({ provider_type: "parallel", label: "P", auth_mode: "oauth" })
    expect(stub.requests[0]?.url).toBe("/api/v1/account/vault/keys")
    expect(stub.requests[0]?.body).toEqual({ provider_type: "parallel", label: "P", auth_mode: "oauth" })
  })

  it("rotates at the expected generation", async () => {
    const stub = installFetchStub(() => ok({ ...VAULT_ROW, generation: 2 }))
    await rotateVaultKey("c1", 4, FAKE_SECRET)
    expect(stub.requests[0]?.url).toBe("/api/v1/account/vault/keys/c1/rotate")
    expect(stub.requests[0]?.body).toEqual({ expected_generation: 4, secret: FAKE_SECRET })
  })

  it("lists project credentials and forwards the abort signal", async () => {
    const stub = installFetchStub((req) => {
      if (req.method === "DELETE") return new Response(null, { status: 204 })
      return ok([PROJECT_ROW])
    })
    const controller = new AbortController()
    expect(await listProjectCredentials("proj", controller.signal)).toHaveLength(1)
    expect(stub.requests[0]?.signal).toBe(controller.signal)
    expect(stub.requests.map((r) => `${r.method} ${r.url}`)).toEqual([
      "GET /api/v1/projects/proj/credentials",
    ])
  })

  it("runs the OAuth device flow on the credential base", async () => {
    const stub = installFetchStub((req) => {
      if (req.url.endsWith("/oauth/device")) return ok({ user_code: "ABCD", verification_uri: "https://auth.example.test/d", interval: 5, expires_in: 600 }, 201)
      if (req.url.endsWith("/oauth/poll")) return ok({ credential_id: "c1", status: "pending", interval: 6 })
      return new Response(null, { status: 204 })
    })
    expect((await startVaultOAuth("c1")).user_code).toBe("ABCD")
    expect((await pollVaultOAuth("c1")).interval).toBe(6)
    await disconnectVaultOAuth("c1")
    expect(stub.requests.map((r) => `${r.method} ${r.url}`)).toEqual([
      "POST /api/v1/account/vault/keys/c1/oauth/device",
      "POST /api/v1/account/vault/keys/c1/oauth/poll",
      "DELETE /api/v1/account/vault/keys/c1/oauth",
    ])
  })

})
