import { afterEach, describe, expect, it, vi } from "vitest"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { apiKeyFixture } from "@/test/accessFixtures"
import { ApiError } from "@/shared/api/http"
import {
  API_KEY_INACTIVE_MESSAGE,
  PROJECT_ARCHIVED_KEYS_MESSAGE,
  apiKeyMutationMessage,
  issueProjectApiKey,
  listProjectApiKeys,
  revokeProjectApiKey,
  rotateProjectApiKey,
} from "./apiKeysApi"

const PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
const KEY_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
const ONE_TIME_VALUE = "fs_live_test-only-opaque-value"

function issuedBody() {
  return { ...apiKeyFixture(), key: ONE_TIME_VALUE }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("listProjectApiKeys", () => {
  it("reads the project's key metadata", async () => {
    const stub = installFetchStub(() => ok([apiKeyFixture()]))
    const keys = await listProjectApiKeys(PROJECT_ID, new AbortController().signal)
    expect(keys).toEqual([apiKeyFixture()])
    expect(stub.requests[0]).toMatchObject({ url: `/api/v1/projects/${PROJECT_ID}/api-keys`, method: "GET" })
  })
})

describe("issueProjectApiKey", () => {
  it("omits expires_at for the default 90-day lifetime", async () => {
    const stub = installFetchStub(() => ok(issuedBody(), 201))
    const issued = await issueProjectApiKey(PROJECT_ID, {
      label: "CI",
      scopes: ["search.execute", "fetch.execute"],
      expiry: { kind: "default" },
    })
    expect(stub.requests[0]).toMatchObject({ url: `/api/v1/projects/${PROJECT_ID}/api-keys`, method: "POST" })
    expect(stub.requests[0]?.body).toEqual({ label: "CI", scopes: ["search.execute", "fetch.execute"] })
    expect("expires_at" in (stub.requests[0]?.body as object)).toBe(false)
    expect(issued.rawKey).toBe(ONE_TIME_VALUE)
  })

  it("sends an explicit null for No expiration", async () => {
    const stub = installFetchStub(() => ok(issuedBody(), 201))
    await issueProjectApiKey(PROJECT_ID, { label: "CI", scopes: ["search.execute"], expiry: { kind: "never" } })
    expect(stub.requests[0]?.bodyText).toBe('{"label":"CI","scopes":["search.execute"],"expires_at":null}')
  })

  it("sends the custom timestamp", async () => {
    const stub = installFetchStub(() => ok(issuedBody(), 201))
    await issueProjectApiKey(PROJECT_ID, {
      label: "CI",
      scopes: ["fetch.execute"],
      expiry: { kind: "at", isoTimestamp: "2030-01-01T23:59:59.000Z" },
    })
    expect(stub.requests[0]?.body).toEqual({
      label: "CI",
      scopes: ["fetch.execute"],
      expires_at: "2030-01-01T23:59:59.000Z",
    })
  })
})

describe("rotateProjectApiKey", () => {
  it("sends the overlap and omits expires_at to keep the current lifetime", async () => {
    const stub = installFetchStub(() => ok(issuedBody(), 201))
    const issued = await rotateProjectApiKey(PROJECT_ID, KEY_ID, {
      overlapSeconds: 86_400,
      expiry: { kind: "default" },
    })
    expect(stub.requests[0]).toMatchObject({
      url: `/api/v1/projects/${PROJECT_ID}/api-keys/${KEY_ID}/rotate`,
      method: "POST",
    })
    expect(stub.requests[0]?.body).toEqual({ overlap_seconds: 86_400 })
    expect(issued.rawKey).toBe(ONE_TIME_VALUE)
  })

  it("sends an immediate revoke with an explicit null expiry", async () => {
    const stub = installFetchStub(() => ok(issuedBody(), 201))
    await rotateProjectApiKey(PROJECT_ID, KEY_ID, { overlapSeconds: 0, expiry: { kind: "never" } })
    expect(stub.requests[0]?.body).toEqual({ overlap_seconds: 0, expires_at: null })
  })
})

describe("revokeProjectApiKey", () => {
  it("deletes the key and accepts the empty 204", async () => {
    const stub = installFetchStub(() => new Response(null, { status: 204 }))
    await expect(revokeProjectApiKey(PROJECT_ID, KEY_ID)).resolves.toBeUndefined()
    expect(stub.requests[0]).toMatchObject({
      url: `/api/v1/projects/${PROJECT_ID}/api-keys/${KEY_ID}`,
      method: "DELETE",
    })
  })
})

describe("apiKeyMutationMessage", () => {
  async function failure(status: number, body: unknown): Promise<unknown> {
    installFetchStub(() => err(status, body))
    return revokeProjectApiKey(PROJECT_ID, KEY_ID).catch((error: unknown) => error)
  }

  it("maps the inactive-key conflict", async () => {
    const error = await failure(409, { detail: { code: "API_KEY_INACTIVE", message: "x" } })
    expect(apiKeyMutationMessage(error, "fallback")).toBe(API_KEY_INACTIVE_MESSAGE)
    expect(API_KEY_INACTIVE_MESSAGE).toBe("This key is no longer active.")
  })

  it("maps the archived-project conflict", async () => {
    const error = await failure(409, { detail: { code: "PROJECT_ARCHIVED", message: "x" } })
    expect(apiKeyMutationMessage(error, "fallback")).toBe(PROJECT_ARCHIVED_KEYS_MESSAGE)
    expect(PROJECT_ARCHIVED_KEYS_MESSAGE).toBe("An archived project cannot issue or rotate keys.")
  })

  it("maps an empty 403 to the permission-lost copy", async () => {
    const error = await failure(403, null)
    expect(apiKeyMutationMessage(error, "fallback")).toBe("You no longer have permission for this action.")
  })

  it("shows the 422 validation detail", async () => {
    const error = await failure(422, { detail: "expires_at must be in the future" })
    expect(apiKeyMutationMessage(error, "fallback")).toContain("expires_at must be in the future")
  })

  it("falls back for an unknown conflict and a non-API failure", async () => {
    const error = await failure(409, { detail: { code: "SOMETHING_ELSE", message: "x" } })
    expect(apiKeyMutationMessage(error, "fallback")).toBe("fallback")
    expect(apiKeyMutationMessage(new Error("boom"), "fallback")).toBe("fallback")
    expect(apiKeyMutationMessage(new ApiError(500, "", null), "fallback")).toBe("fallback")
  })
})
