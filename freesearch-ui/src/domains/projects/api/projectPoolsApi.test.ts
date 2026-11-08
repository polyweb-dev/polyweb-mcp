import { afterEach, expect, it, vi } from "vitest"
import { attachProjectPool, detachProjectPool, listProjectPools } from "../index"
import { installFetchStub, ok } from "@/test/fetchMock"

afterEach(() => vi.unstubAllGlobals())

it("attaches and detaches project capacity", async () => {
  const pool = { pool_id: "pool1", label: "Search", provider_type: "brave", key_label: "Key",
    owner: { user_id: "u1", email: "admin@example.com" }, rate: { limit: 10, window_seconds: 60 },
    budget: null, budget_used: 0, operations: ["search"] }
  const stub = installFetchStub((request) => request.url.endsWith("/unassign") ? ok({
    id: "pool1", credential_id: "k1", provider_type: "brave", project_id: null,
    label: "Search", rate: pool.rate, budget: null, budget_used_usd: 0,
    operations: ["search"], operation_limits: null,
  }) : ok(pool))
  expect(await attachProjectPool("p1", { key_id: "k1", pool: { label: "Search", rate: pool.rate, budget: null } })).toEqual(pool)
  await detachProjectPool("p1", "pool1")
  expect(stub.requests.map(({ method, url }) => `${method} ${url}`)).toEqual([
    "POST /api/v1/projects/p1/pools", "POST /api/v1/account/vault/pools/pool1/unassign",
  ])
})

it("drops unknown operations and excludes private key identifiers", async () => {
  installFetchStub(() => ok([{
    pool_id: "pool1", label: "Search", provider_type: "brave", key_label: "Key",
    owner: { user_id: "u1", email: "admin@example.com" }, rate: { limit: null, window_seconds: 60 },
    budget: null, budget_used: 0, operations: ["search", "future"], key_id: "private",
  }]))
  const pool = (await listProjectPools("p1"))[0]
  expect(pool?.operations).toEqual(["search"])
  expect(pool).not.toHaveProperty("key_id")
})

it("rejects a pool with no recognized operations", async () => {
  installFetchStub(() => ok([{
    pool_id: "pool1", label: "Search", provider_type: "brave", key_label: "Key",
    owner: { user_id: "u1", email: "admin@example.com" }, rate: { limit: null, window_seconds: 60 },
    budget: null, budget_used: 0, operations: [],
  }]))
  await expect(listProjectPools("p1")).rejects.toThrow("unexpected pool")
})
