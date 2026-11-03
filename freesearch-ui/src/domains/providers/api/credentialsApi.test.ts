import { afterEach, describe, expect, it, vi } from "vitest"
import { installFetchStub, ok } from "@/test/fetchMock"
import {
  createProjectCredential,
  createSystemCredential,
  deleteCredentialGrant,
  deleteProjectCredential,
  deleteSystemCredential,
  disconnectCredentialOAuth,
  listCredentialGrants,
  listProjectCredentials,
  listSystemCredentials,
  pollCredentialOAuth,
  projectCredentialBase,
  putCredentialGrant,
  rotateProjectCredential,
  rotateSystemCredential,
  startCredentialOAuth,
  systemCredentialBase,
} from "./credentialsApi"

const FAKE_SECRET = "fake-provider-key-123"
const SYSTEM_ROW = { id: "c1", provider_type: "tavily", owner_scope: "system", label: "Shared", auth_mode: "api_key", generation: 1, status: "active" }
const PROJECT_ROW = { ...SYSTEM_ROW, owner_scope: "project", permitted_operations: ["search"], can_manage: true }

describe("credentialsApi", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("creates an API key credential with the secret in the body only", async () => {
    const stub = installFetchStub(() => ok({ ...SYSTEM_ROW, secret: FAKE_SECRET }, 201))
    const created = await createSystemCredential({ providerType: "tavily", label: "Shared", authMode: "api_key", secret: FAKE_SECRET })
    const request = stub.requests[0]
    expect(request?.url).toBe("/api/v1/system/credentials")
    expect(request?.method).toBe("POST")
    expect(request?.body).toEqual({ provider_type: "tavily", label: "Shared", auth_mode: "api_key", secret: FAKE_SECRET })
    expect(request?.url).not.toContain(FAKE_SECRET)
    expect(JSON.stringify(created)).not.toContain(FAKE_SECRET)
  })

  it("never sends a secret for an OAuth credential", async () => {
    const stub = installFetchStub(() => ok({ ...PROJECT_ROW, provider_type: "parallel", auth_mode: "oauth" }, 201))
    await createProjectCredential("proj", { providerType: "parallel", label: "P", authMode: "oauth", secret: "ignored" })
    expect(stub.requests[0]?.url).toBe("/api/v1/projects/proj/credentials")
    expect(stub.requests[0]?.body).toEqual({ provider_type: "parallel", label: "P", auth_mode: "oauth" })
  })

  it("rotates at the expected generation", async () => {
    const stub = installFetchStub(() => ok({ ...SYSTEM_ROW, generation: 2 }))
    await rotateSystemCredential("c1", 1, FAKE_SECRET)
    await rotateProjectCredential("proj", "c1", { expectedGeneration: 4, secret: FAKE_SECRET })
    expect(stub.requests[0]?.url).toBe("/api/v1/system/credentials/c1/rotate")
    expect(stub.requests[0]?.body).toEqual({ expected_generation: 1, secret: FAKE_SECRET })
    expect(stub.requests[1]?.url).toBe("/api/v1/projects/proj/credentials/c1/rotate")
    expect(stub.requests[1]?.body).toEqual({ expected_generation: 4, secret: FAKE_SECRET })
  })

  it("lists, deletes and forwards the abort signal", async () => {
    const stub = installFetchStub((req) => {
      if (req.method === "DELETE") return new Response(null, { status: 204 })
      return ok(req.url.includes("/projects/") ? [PROJECT_ROW] : [SYSTEM_ROW])
    })
    const controller = new AbortController()
    expect(await listSystemCredentials(controller.signal)).toHaveLength(1)
    expect(await listProjectCredentials("proj", controller.signal)).toHaveLength(1)
    await deleteSystemCredential("c1")
    await deleteProjectCredential("proj", "c2")
    expect(stub.requests[0]?.signal).toBe(controller.signal)
    expect(stub.requests.map((r) => `${r.method} ${r.url}`)).toEqual([
      "GET /api/v1/system/credentials",
      "GET /api/v1/projects/proj/credentials",
      "DELETE /api/v1/system/credentials/c1",
      "DELETE /api/v1/projects/proj/credentials/c2",
    ])
  })

  it("lists, upserts and removes project grants", async () => {
    const grant = { credential_id: "c1", project_id: "proj", permitted_operations: ["search"], version: 1 }
    const stub = installFetchStub((req) => (req.method === "DELETE" ? new Response(null, { status: 204 }) : ok(req.method === "GET" ? [grant] : grant)))
    expect(await listCredentialGrants("c1")).toHaveLength(1)
    await putCredentialGrant("c1", "proj", ["search", "fetch"])
    await deleteCredentialGrant("c1", "proj")
    expect(stub.requests[1]?.url).toBe("/api/v1/system/credentials/c1/grants/proj")
    expect(stub.requests[1]?.method).toBe("PUT")
    expect(stub.requests[1]?.body).toEqual({ permitted_operations: ["search", "fetch"] })
    expect(stub.requests[2]?.method).toBe("DELETE")
  })

  it("runs the OAuth device flow on the credential base", async () => {
    const stub = installFetchStub((req) => {
      if (req.url.endsWith("/oauth/device")) return ok({ user_code: "ABCD", verification_uri: "https://auth.example.test/d", interval: 5, expires_in: 600 }, 201)
      if (req.url.endsWith("/oauth/poll")) return ok({ credential_id: "c1", status: "pending", interval: 6 })
      return new Response(null, { status: 204 })
    })
    const systemBase = systemCredentialBase("c1")
    const projectBase = projectCredentialBase("proj", "c1")
    expect(systemBase).toBe("/api/v1/system/credentials/c1")
    expect(projectBase).toBe("/api/v1/projects/proj/credentials/c1")
    expect((await startCredentialOAuth(projectBase)).userCode).toBe("ABCD")
    expect((await pollCredentialOAuth(projectBase)).intervalSeconds).toBe(6)
    await disconnectCredentialOAuth(systemBase)
    expect(stub.requests.map((r) => `${r.method} ${r.url}`)).toEqual([
      "POST /api/v1/projects/proj/credentials/c1/oauth/device",
      "POST /api/v1/projects/proj/credentials/c1/oauth/poll",
      "DELETE /api/v1/system/credentials/c1/oauth",
    ])
  })
})
