import { describe, it, expect, afterEach, vi } from "vitest"
import { FreeSearchApiService } from "./freesearchApi"
import { ApiError } from "@/shared/api/http"
import { installFetchStub, ok, err } from "@/test/fetchMock"

/**
 * OAuth device-flow client: POST device-code / GET status / DELETE revoke
 * over same-origin relative paths with the shared ApiError mapping (a 404
 * on status means "unpaired", every other failure throws).
 */
describe("FreeSearchApiService OAuth pairing", () => {
  const service = new FreeSearchApiService()

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("beginOAuthDeviceFlow() POSTs the relative device-code resource with no body", async () => {
    const wire = {
      provider: "parallel",
      user_code: "ABCD-1234",
      verification_uri: "https://platform.parallel.ai/activate",
      verification_uri_complete: "https://platform.parallel.ai/activate?code=ABCD-1234",
      expires_in: 300,
      interval: 5,
    }
    const stub = installFetchStub(() => ok(wire))

    const result = await service.beginOAuthDeviceFlow("parallel")

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0].url).toBe("/api/v1/providers/parallel/oauth/device-code")
    expect(stub.requests[0].method).toBe("POST")
    expect(stub.requests[0].bodyText).toBeUndefined()
    expect(result).toEqual(wire)
  })

  it("getOAuthStatus() GETs the relative status resource", async () => {
    const wire = { provider: "parallel", status: "pending", expires_in: 295 }
    const stub = installFetchStub(() => ok(wire))

    const result = await service.getOAuthStatus("parallel")

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0].url).toBe("/api/v1/providers/parallel/oauth/status")
    expect(stub.requests[0].method).toBe("GET")
    expect(result).toEqual(wire)
  })

  it("getOAuthStatus() maps 404 to the unpaired honest null-shape", async () => {
    installFetchStub(() => err(404, { detail: "no OAuth pairing for 'parallel'" }))

    await expect(service.getOAuthStatus("parallel")).resolves.toEqual({
      provider: "parallel",
      status: "unpaired",
      expires_in: null,
    })
  })

  it("getOAuthStatus() rethrows non-404 failures as ApiError", async () => {
    installFetchStub(() => err(500, { detail: "oauth store exploded" }))

    const failure = await service.getOAuthStatus("parallel").then(
      () => null,
      (error: unknown) => error as ApiError
    )
    expect(failure).toBeInstanceOf(ApiError)
    expect(failure!.status).toBe(500)
  })

  it("revokeOAuth() DELETEs the relative resource and tolerates an empty 204", async () => {
    const stub = installFetchStub(() => new Response(null, { status: 204 }))

    await expect(service.revokeOAuth("parallel")).resolves.toBeUndefined()

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0].url).toBe("/api/v1/providers/parallel/oauth")
    expect(stub.requests[0].method).toBe("DELETE")
  })
})