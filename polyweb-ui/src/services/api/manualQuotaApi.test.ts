import { describe, it, expect, afterEach, vi } from "vitest"
import { PolywebApiService } from "./polywebApi"
import { ApiError } from "@/shared/api/http"
import { installFetchStub, ok, err } from "@/test/fetchMock"

/**
 * Manual billing-entry client: GET/PUT/DELETE
 * /api/v1/providers/{id}/manual-quota over same-origin relative paths with
 * the shared ApiError mapping (200 null on GET means "not configured").
 */
describe("PolywebApiService manual quota", () => {
  const service = new PolywebApiService()

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("getManualQuota() GETs the relative manual-quota resource", async () => {
    const wire = {
      provider: "brave",
      billing_start: "2026-09-01",
      billing_end: "2026-09-30",
      allowance: "5.00",
      current_usage: "0.88",
      remaining: "4.12",
      remaining_percent: "82.4",
      source: "estimated",
    }
    const stub = installFetchStub(() => ok(wire))

    const result = await service.getManualQuota("brave")

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0].url).toBe("/api/v1/providers/brave/manual-quota")
    expect(stub.requests[0].method).toBe("GET")
    expect(result).toEqual(wire)
  })

  it("getManualQuota() accepts 200 null without a console error", async () => {
    installFetchStub(() => ok(null))
    const consoleError = vi.spyOn(console, "error")
    await expect(service.getManualQuota("exa")).resolves.toBeNull()
    expect(consoleError).not.toHaveBeenCalled()
    consoleError.mockRestore()
  })

  it.each([403, 404])("getManualQuota() preserves access denial %s", async (status) => {
    installFetchStub(() => err(status, { detail: "Forbidden" }))
    await expect(service.getManualQuota("exa")).rejects.toMatchObject({ status })
  })

  it("getManualQuota() rethrows non-404 failures as ApiError", async () => {
    installFetchStub(() => err(500, { detail: "quota store exploded" }))

    const failure = await service.getManualQuota("brave").then(
      () => null,
      (error: unknown) => error as ApiError
    )
    expect(failure).toBeInstanceOf(ApiError)
    expect(failure!.status).toBe(500)
  })

  it("putManualQuota() PUTs exactly the manual payload", async () => {
    const payload = {
      billing_start: "2026-09-01",
      billing_end: "2026-09-30",
      allowance: "5.00",
      current_usage: "0.88",
    }
    const stub = installFetchStub(() => ok({ provider: "exa", ...payload }))

    const result = await service.putManualQuota("exa", payload as never)

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0].url).toBe("/api/v1/providers/exa/manual-quota")
    expect(stub.requests[0].method).toBe("PUT")
    expect(stub.requests[0].body).toEqual(payload)
    expect(stub.requests[0].headers["content-type"]).toContain("application/json")
    expect(result).toMatchObject({ allowance: "5.00", current_usage: "0.88" })
  })

  it("putManualQuota() surfaces 422 validation detail", async () => {
    installFetchStub(() =>
      err(422, { detail: [{ loc: ["body", "allowance"], msg: "must be positive" }] })
    )

    const failure = await service
      .putManualQuota("brave", {
        billing_start: "2026-09-30",
        billing_end: "2026-09-01",
        allowance: "0",
        current_usage: "0",
      })
      .then(
        () => null,
        (error: unknown) => error as ApiError
      )
    expect(failure).toBeInstanceOf(ApiError)
    expect(failure!.status).toBe(422)
    expect(failure!.detail).toBe("body.allowance: must be positive")
  })

  it("deleteManualQuota() DELETEs the relative resource", async () => {
    const stub = installFetchStub(() => ok({ provider: "brave", deleted: true }))

    await service.deleteManualQuota("brave")

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0].url).toBe("/api/v1/providers/brave/manual-quota")
    expect(stub.requests[0].method).toBe("DELETE")
  })
})
