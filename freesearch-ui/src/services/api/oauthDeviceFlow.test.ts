import { describe, it, expect, afterEach, vi } from "vitest"
import { FreeSearchApiService } from "./freesearchApi"
import { ApiError } from "@/shared/api/http"
import { installFetchStub, ok, err } from "@/test/fetchMock"

/**
 * ADVERSARIAL Phase-1 skeleton: Parallel OAuth device-flow client.
 *
 * FROZEN CONTRACT under test (developer implements in freesearchApi.ts,
 * keeping the class name FreeSearchApiService + singleton apiService):
 * - beginOAuthDeviceFlow(backendId) -> POST /api/v1/providers/{id}/oauth/device-code
 * - getOAuthStatus(backendId)      -> GET  /api/v1/providers/{id}/oauth/status
 *   (404 maps to { provider, status: "unpaired", expires_in: null }, NOT a throw)
 * - revokeOAuth(backendId)         -> DELETE /api/v1/providers/{id}/oauth
 * - Same-origin RELATIVE paths only; shared ApiError mapping for the rest.
 * - Shapes:
 *   device-code { provider, user_code, verification_uri,
 *                 verification_uri_complete | null, expires_in, interval }
 *   status      { provider, status: pending|ready|expired|denied|unpaired,
 *                 expires_in | null }
 *
 * CONTRACT AMBIGUITY (flagged, not papered over): the frozen text
 * "POST/GET/DELETE /api/v1/providers/{id}/oauth[/device-code|/status]" is
 * read here as POST ../oauth/device-code, GET ../oauth/status,
 * DELETE ../oauth. If the backend nests revoke under ../oauth/status, the
 * revoke tests below fail and the reading must be re-frozen explicitly.
 *
 * ACTIVATION: the FreeSearchApiService import is static (the module exists)
 * but the three methods do not yet. Method access goes through an unknown
 * cast, so this file typechecks today; every SUT-dependent block is
 * describe.skipIf(!hasOAuth) and activates with zero test edits once the
 * developer lands the methods.
 */

type OAuthDeviceCode = {
  provider: string
  user_code: string
  verification_uri: string
  verification_uri_complete: string | null
  expires_in: number
  interval: number
}

type OAuthStatusValue = "pending" | "ready" | "expired" | "denied" | "unpaired"

type OAuthStatus = {
  provider: string
  status: OAuthStatusValue
  expires_in: number | null
}

function isDeviceCodeShape(value: unknown): value is OAuthDeviceCode {
  if (!value || typeof value !== "object") return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.provider === "string" &&
    typeof candidate.user_code === "string" &&
    typeof candidate.verification_uri === "string" &&
    (typeof candidate.verification_uri_complete === "string" ||
      candidate.verification_uri_complete === null) &&
    typeof candidate.expires_in === "number" &&
    typeof candidate.interval === "number"
  )
}

function isStatusShape(value: unknown): value is OAuthStatus {
  if (!value || typeof value !== "object") return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.provider === "string" &&
    (candidate.status === "pending" ||
      candidate.status === "ready" ||
      candidate.status === "expired" ||
      candidate.status === "denied" ||
      candidate.status === "unpaired") &&
    (typeof candidate.expires_in === "number" || candidate.expires_in === null)
  )
}

const DEVICE_CODE_WIRE: OAuthDeviceCode = {
  provider: "parallel",
  user_code: "ABCD-EFGH",
  verification_uri: "https://parallel.ai/activate",
  verification_uri_complete: "https://parallel.ai/activate?code=ABCD-EFGH",
  expires_in: 300,
  interval: 2,
}

interface OAuthClient {
  beginOAuthDeviceFlow: (backendId: string) => Promise<OAuthDeviceCode>
  getOAuthStatus: (backendId: string) => Promise<OAuthStatus>
  revokeOAuth: (backendId: string) => Promise<unknown>
}

const OAUTH_METHODS = ["beginOAuthDeviceFlow", "getOAuthStatus", "revokeOAuth"] as const

function requireOAuth(service: FreeSearchApiService): OAuthClient | null {
  const api = service as unknown as Record<string, unknown>
  if (!OAUTH_METHODS.every((method) => typeof api[method] === "function")) return null
  return api as unknown as OAuthClient
}

/** Collection-time probe: false until the developer lands the methods. */
const hasOAuth = requireOAuth(new FreeSearchApiService()) !== null

describe("FreeSearchApiService OAuth device flow (frozen contract)", () => {
  const service = new FreeSearchApiService()

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("documents the frozen wire shapes (no SUT required)", () => {
    expect(isDeviceCodeShape(DEVICE_CODE_WIRE)).toBe(true)
    expect(
      isStatusShape({ provider: "parallel", status: "pending", expires_in: 299 })
    ).toBe(true)
    expect(
      isStatusShape({ provider: "parallel", status: "unpaired", expires_in: null })
    ).toBe(true)
    // null-vs-absent: verification_uri_complete must survive as null,
    // never undefined-coerced or dropped by a mapper.
    expect("verification_uri_complete" in DEVICE_CODE_WIRE).toBe(true)
    const nullComplete: OAuthDeviceCode = { ...DEVICE_CODE_WIRE, verification_uri_complete: null }
    expect(isDeviceCodeShape(nullComplete)).toBe(true)
    expect(nullComplete.verification_uri_complete).toBeNull()
    // unpaired synthesis must carry a null expires_in, never undefined.
    const unpaired: OAuthStatus = { provider: "parallel", status: "unpaired", expires_in: null }
    expect("expires_in" in unpaired).toBe(true)
  })

  describe.skipIf(!hasOAuth)("surface", () => {
    it("exposes exactly the frozen OAuth method names", () => {
      const api = service as unknown as Record<string, unknown>
      for (const method of OAUTH_METHODS) {
        expect(typeof api[method], method).toBe("function")
      }
    })
  })

  describe.skipIf(!hasOAuth)("beginOAuthDeviceFlow", () => {
    it("POSTs relative /api/v1/providers/{id}/oauth/device-code with no invented body", async () => {
      const stub = installFetchStub(() => ok(DEVICE_CODE_WIRE))
      const client = requireOAuth(service)!

      const result = await client.beginOAuthDeviceFlow("parallel")

      expect(stub.requests).toHaveLength(1)
      expect(stub.requests[0].url).toBe("/api/v1/providers/parallel/oauth/device-code")
      expect(stub.requests[0].method).toBe("POST")
      expect(stub.requests[0].bodyText).toBeUndefined()
      expect(isDeviceCodeShape(result)).toBe(true)
      expect(result).toEqual(DEVICE_CODE_WIRE)
    })

    it("preserves a null verification_uri_complete verbatim", async () => {
      installFetchStub(() => ok({ ...DEVICE_CODE_WIRE, verification_uri_complete: null }))
      const client = requireOAuth(service)!

      const result = await client.beginOAuthDeviceFlow("parallel")

      expect("verification_uri_complete" in result).toBe(true)
      expect(result.verification_uri_complete).toBeNull()
    })

    it("maps 503/422 failures to ApiError with status and detail", async () => {
      const client = requireOAuth(service)!
      installFetchStub(() => err(503, { detail: "parallel oauth unavailable" }))
      const failure = await client.beginOAuthDeviceFlow("parallel").then(
        () => null,
        (error: unknown) => error as ApiError
      )
      expect(failure).toBeInstanceOf(ApiError)
      expect(failure!.status).toBe(503)
      expect(failure!.detail).toBe("parallel oauth unavailable")
      vi.unstubAllGlobals()

      installFetchStub(() =>
        err(422, { detail: [{ loc: ["body", "provider"], msg: "unsupported provider" }] })
      )
      const invalid = await client.beginOAuthDeviceFlow("parallel").then(
        () => null,
        (error: unknown) => error as ApiError
      )
      expect(invalid).toBeInstanceOf(ApiError)
      expect(invalid!.status).toBe(422)
      expect(invalid!.detail).toBe("body.provider: unsupported provider")
    })

    it("maps a network TypeError to ApiError status 0", async () => {
      installFetchStub(() => {
        throw new TypeError("fetch failed")
      })
      const client = requireOAuth(service)!

      const failure = await client.beginOAuthDeviceFlow("parallel").then(
        () => null,
        (error: unknown) => error as ApiError
      )

      expect(failure).toBeInstanceOf(ApiError)
      expect(failure!.status).toBe(0)
      expect(failure!.detail).toContain("API unreachable")
    })
  })

  describe.skipIf(!hasOAuth)("getOAuthStatus", () => {
    it("GETs relative /api/v1/providers/{id}/oauth/status with no body", async () => {
      const wire: OAuthStatus = { provider: "parallel", status: "pending", expires_in: 299 }
      const stub = installFetchStub(() => ok(wire))
      const client = requireOAuth(service)!

      const result = await client.getOAuthStatus("parallel")

      expect(stub.requests).toHaveLength(1)
      expect(stub.requests[0].url).toBe("/api/v1/providers/parallel/oauth/status")
      expect(stub.requests[0].method).toBe("GET")
      expect(stub.requests[0].bodyText).toBeUndefined()
      expect(result).toEqual(wire)
    })

    it("passes ready/expired/denied through verbatim", async () => {
      const client = requireOAuth(service)!
      for (const status of ["ready", "expired", "denied"] as const) {
        installFetchStub(() => ok({ provider: "parallel", status, expires_in: null }))
        const result = await client.getOAuthStatus("parallel")
        expect(isStatusShape(result)).toBe(true)
        expect(result.status).toBe(status)
        expect(result.provider).toBe("parallel")
        vi.unstubAllGlobals()
      }
    })

    it("maps 404 to synthesized unpaired (no throw, single request)", async () => {
      const stub = installFetchStub(() => err(404, { detail: "no oauth pairing for 'parallel'" }))
      const client = requireOAuth(service)!

      const result = await client.getOAuthStatus("parallel")

      expect(stub.requests).toHaveLength(1)
      expect(result).toEqual({ provider: "parallel", status: "unpaired", expires_in: null })
      expect("expires_in" in result).toBe(true)
    })

    it("rethrows non-404 failures as ApiError (only 404 means unpaired)", async () => {
      const client = requireOAuth(service)!
      for (const status of [500, 503, 422]) {
        installFetchStub(() => err(status, { detail: "oauth store exploded" }))
        const failure = await client.getOAuthStatus("parallel").then(
          () => null,
          (error: unknown) => error as ApiError
        )
        expect(failure, `status ${status} must throw`).toBeInstanceOf(ApiError)
        expect(failure!.status).toBe(status)
        vi.unstubAllGlobals()
      }
    })
  })

  describe.skipIf(!hasOAuth)("revokeOAuth", () => {
    it("DELETEs relative /api/v1/providers/{id}/oauth (collection, not /status)", async () => {
      const stub = installFetchStub(() => ok({ provider: "parallel", deleted: true }))
      const client = requireOAuth(service)!

      await client.revokeOAuth("parallel")

      expect(stub.requests).toHaveLength(1)
      expect(stub.requests[0].url).toBe("/api/v1/providers/parallel/oauth")
      expect(stub.requests[0].method).toBe("DELETE")
    })

    it("surfaces revoke failures as ApiError", async () => {
      installFetchStub(() => err(500, { detail: "revoke exploded" }))
      const client = requireOAuth(service)!

      const failure = await client.revokeOAuth("parallel").then(
        () => null,
        (error: unknown) => error as ApiError
      )

      expect(failure).toBeInstanceOf(ApiError)
      expect(failure!.status).toBe(500)
    })
  })

  describe.skipIf(!hasOAuth)("same-origin discipline", () => {
    it("never calls an absolute backend host literal from any OAuth method", async () => {
      installFetchStub((req) => {
        if (req.url.endsWith("/device-code")) return ok(DEVICE_CODE_WIRE)
        if (req.url.endsWith("/status"))
          return ok({ provider: "parallel", status: "pending", expires_in: 299 })
        return ok({ provider: "parallel", deleted: true })
      })
      const client = requireOAuth(service)!

      await client.beginOAuthDeviceFlow("parallel")
      await client.getOAuthStatus("parallel")
      await client.revokeOAuth("parallel")

      const fetchMock = vi.mocked(globalThis.fetch)
      expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3)
      for (const call of fetchMock.mock.calls) {
        const url = String(call[0])
        expect(url).not.toContain("127.0.0.1")
        expect(url.startsWith("/")).toBe(true)
      }
    })
  })
})
