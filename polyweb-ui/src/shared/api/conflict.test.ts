import { describe, expect, it } from "vitest"
import { ApiError } from "./http"
import { conflictDetail, isConflict, isForbidden } from "./conflict"

describe("conflictDetail", () => {
  it("reads code and message of a 409 body", () => {
    const error = new ApiError(409, "", { detail: { code: "POOL_INFEASIBLE", message: "Base rates exceed the pool." } })
    expect(conflictDetail(error)).toEqual({ code: "POOL_INFEASIBLE", message: "Base rates exceed the pool." })
    expect(isConflict(error)).toBe(true)
  })

  it("returns empty detail for a 409 without a body and null otherwise", () => {
    expect(conflictDetail(new ApiError(409, "", null))).toEqual({ code: null, message: null })
    expect(conflictDetail(new ApiError(403, "", null))).toBeNull()
    expect(conflictDetail(new Error("x"))).toBeNull()
    expect(isForbidden(new ApiError(403, "", null))).toBe(true)
  })
})
