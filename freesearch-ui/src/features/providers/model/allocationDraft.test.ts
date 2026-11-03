import { describe, expect, it } from "vitest"
import type { Allocation } from "@/domains/providers"
import {
  MAX_RATE_BELOW_BASE,
  POOL_REQUIRED,
  WEIGHT_TOO_LOW,
  WHOLE_NUMBERS,
  WINDOW_TOO_LOW,
  ZERO_BASE_NEEDS_BEST_EFFORT,
  allocationDraft,
  validateAllocation,
} from "./allocationDraft"

const draft = (overrides: Partial<ReturnType<typeof allocationDraft>> = {}) => ({
  ...allocationDraft(null, "pool-1"),
  ...overrides,
})

describe("allocationDraft", () => {
  it("starts strict with weight 1", () => {
    expect(allocationDraft(null, "pool-1")).toMatchObject({ poolId: "pool-1", borrowEnabled: false, weight: "1", maxRate: "" })
  })

  it("fills from an existing allocation", () => {
    const allocation: Allocation = {
      projectId: "p", poolId: "pool", operation: "fetch", baseRate: 4, windowSeconds: 1, borrowEnabled: true,
      maxRate: 8, effectiveMaxRate: 8, weight: 2, bestEffort: false, maxConcurrency: 3, maxQueuedRequests: null,
      maxQueuedBytes: null, maxQueueWaitMs: 100, version: 1,
    }
    expect(allocationDraft(allocation)).toMatchObject({ operation: "fetch", baseRate: "4", maxRate: "8", maxConcurrency: "3", maxQueuedRequests: "", maxQueueWaitMs: "100" })
  })
})

describe("validateAllocation", () => {
  it("accepts a strict allocation and omits max rate", () => {
    const result = validateAllocation(draft({ maxRate: "999" }))
    expect(result).toEqual({
      ok: true,
      input: {
        baseRate: 10, windowSeconds: 60, borrowEnabled: false, maxRate: null, weight: 1, bestEffort: false,
        maxConcurrency: null, maxQueuedRequests: null, maxQueuedBytes: null, maxQueueWaitMs: null,
      },
    })
  })

  it("requires max rate at least the base with loans", () => {
    expect(validateAllocation(draft({ borrowEnabled: true, maxRate: "5" }))).toEqual({ ok: false, message: MAX_RATE_BELOW_BASE })
    expect(validateAllocation(draft({ borrowEnabled: true, maxRate: "10" })).ok).toBe(true)
    expect(validateAllocation(draft({ borrowEnabled: true, maxRate: "" }))).toEqual({ ok: false, message: WHOLE_NUMBERS })
  })

  it("requires best effort for a zero base", () => {
    expect(validateAllocation(draft({ baseRate: "0" }))).toEqual({ ok: false, message: ZERO_BASE_NEEDS_BEST_EFFORT })
    expect(validateAllocation(draft({ baseRate: "0", bestEffort: true })).ok).toBe(true)
  })

  it("requires weight ≥ 1, window ≥ 1, whole numbers and a pool", () => {
    expect(validateAllocation(draft({ weight: "0" }))).toEqual({ ok: false, message: WEIGHT_TOO_LOW })
    expect(validateAllocation(draft({ windowSeconds: "0" }))).toEqual({ ok: false, message: WINDOW_TOO_LOW })
    expect(validateAllocation(draft({ baseRate: "1.5" }))).toEqual({ ok: false, message: WHOLE_NUMBERS })
    expect(validateAllocation(draft({ maxQueueWaitMs: "-1" }))).toEqual({ ok: false, message: WHOLE_NUMBERS })
    expect(validateAllocation(draft({ poolId: "" }))).toEqual({ ok: false, message: POOL_REQUIRED })
  })

  it("passes optional queue bounds", () => {
    const result = validateAllocation(draft({ maxConcurrency: "2", maxQueuedBytes: "1024" }))
    expect(result.ok && result.input).toMatchObject({ maxConcurrency: 2, maxQueuedBytes: 1024, maxQueuedRequests: null })
  })
})
