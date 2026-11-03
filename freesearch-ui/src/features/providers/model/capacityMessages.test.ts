import { describe, expect, it } from "vitest"
import { ApiError } from "@/shared/api/http"
import { CAPACITY_FORBIDDEN, NOT_FEASIBLE_FALLBACK, capacityFailureMessage, poolFailureMessage } from "./capacityMessages"

describe("capacityFailureMessage", () => {
  it("prefixes the server's infeasible message", () => {
    const error = new ApiError(409, "", { detail: { code: "ALLOCATION_INFEASIBLE", message: "Guaranteed rates exceed the pool limit." } })
    expect(capacityFailureMessage(error, "x")).toBe("Not feasible: Guaranteed rates exceed the pool limit.")
    expect(capacityFailureMessage(new ApiError(409, "", null), "x")).toBe(`Not feasible: ${NOT_FEASIBLE_FALLBACK}`)
  })

  it("maps 403 and other failures to safe text", () => {
    expect(capacityFailureMessage(new ApiError(403, "", null), "fallback")).toBe(CAPACITY_FORBIDDEN)
    expect(capacityFailureMessage(new ApiError(500, "boom", null), "fallback")).toBe("fallback")
  })
})

describe("poolFailureMessage", () => {
  it("shows a pool conflict message without the prefix", () => {
    expect(poolFailureMessage(new ApiError(409, "", { detail: { code: "C", message: "Pool key taken." } }), "f")).toBe("Pool key taken.")
    expect(poolFailureMessage(new ApiError(500, "", null), "f")).toBe("f")
  })
})
