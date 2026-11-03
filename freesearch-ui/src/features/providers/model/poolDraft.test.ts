import { describe, expect, it } from "vitest"
import type { Pool } from "@/domains/providers"
import { POOL_FIELDS_REQUIRED, POOL_NUMBERS, poolDraft, validatePool } from "./poolDraft"

const POOL: Pool = {
  id: "pool", providerType: "tavily", upstreamScope: "credential", poolKey: "k", label: "L",
  constraints: [{ algorithm: "fixed_window", windowSeconds: 60, limit: 100 }],
  maxConcurrency: null, maxQueuedRequests: 5, status: "disabled", version: 2,
}

describe("poolDraft", () => {
  it("starts empty for a new pool and fills from an existing one", () => {
    expect(poolDraft(null, "brave")).toMatchObject({ providerType: "brave", upstreamScope: "account", constraints: [], status: "active" })
    expect(poolDraft(POOL, "brave")).toMatchObject({
      providerType: "tavily",
      constraints: [{ algorithm: "fixed_window", windowSeconds: "60", limit: "100" }],
      maxConcurrency: "",
      maxQueuedRequests: "5",
      status: "disabled",
    })
  })
})

describe("validatePool", () => {
  it("builds the write body", () => {
    expect(validatePool(poolDraft(POOL, "brave"))).toEqual({
      ok: true,
      input: {
        providerType: "tavily", label: "L", upstreamScope: "credential", poolKey: "k",
        constraints: [{ algorithm: "fixed_window", windowSeconds: 60, limit: 100 }],
        maxConcurrency: null, maxQueuedRequests: 5, status: "disabled",
      },
    })
  })

  it("rejects missing names and bad numbers", () => {
    expect(validatePool({ ...poolDraft(POOL, "x"), label: " " })).toEqual({ ok: false, message: POOL_FIELDS_REQUIRED })
    const bad = poolDraft(POOL, "x")
    expect(validatePool({ ...bad, constraints: [{ algorithm: "token_bucket", windowSeconds: "0", limit: "1" }] })).toEqual({ ok: false, message: POOL_NUMBERS })
    expect(validatePool({ ...bad, maxConcurrency: "a" })).toEqual({ ok: false, message: POOL_NUMBERS })
  })
})
