import { afterEach, expect, it, vi } from "vitest"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import {
  assignKeyPool, copyKeyPool, createKeyPool, createVaultKey, deleteKeyPool, deleteVaultKey,
  disconnectVaultOAuth, getKeyPool, getVaultOAuth, listKeyPools, listVaultKeys, listVaultProjects,
  pollVaultOAuth, rotateVaultKey, startVaultOAuth, unassignKeyPool, updateKeyPool, updateVaultKey,
} from "../index"

const key = {
  id: "k1", provider_type: "brave", label: "Main", auth_mode: "api_key", status: "active",
  generation: 1, created_at: "2026-01-01", capacity: null, overcommit: true, contention_mode: "equal", pool_count: 0,
}
const pool = {
  id: "pool1", credential_id: "k1", provider_type: "brave", project_id: null, label: "Search",
  rate: { limit: 10, window_seconds: 60 }, budget: null, budget_used_usd: 0,
  operations: ["search"], operation_limits: null,
}
afterEach(() => vi.unstubAllGlobals())

it("lists and creates vault keys with the contract fields", async () => {
  const stub = installFetchStub((request) => request.method === "GET" ? ok([key]) : ok(key))
  expect(await listVaultKeys()).toEqual([key])
  await createVaultKey({ provider_type: "brave", label: "Main", auth_mode: "api_key", secret: "secret" })
  expect(stub.requests[1]?.body).toEqual({ provider_type: "brave", label: "Main", auth_mode: "api_key", secret: "secret" })
})

it("sends generation on rotation and propagates missing endpoints", async () => {
  const stub = installFetchStub(() => err(404, null))
  await expect(rotateVaultKey("k1", 2, "secret")).rejects.toMatchObject({ status: 404 })
  expect(stub.requests[0]?.body).toEqual({ expected_generation: 2, secret: "secret" })
})

it("creates a pool beneath its key", async () => {
  const stub = installFetchStub(() => ok(pool))
  expect(await createKeyPool("k1", { label: "Search", rate: pool.rate, budget: null, operations: ["search"] })).toEqual(pool)
  expect(stub.requests[0]?.url).toBe("/api/v1/account/vault/keys/k1/pools")
})

it("rejects malformed key payloads", async () => {
  installFetchStub(() => ok([{ id: "k1" }]))
  await expect(listVaultKeys()).rejects.toMatchObject({ status: 0 })
})

it("does not retain secret fields from vault responses", async () => {
  installFetchStub(() => ok([{ ...key, secret: "must not reach the UI" }]))
  expect(await listVaultKeys()).toEqual([key])
})

it("rejects pool data that omits allowed operations", async () => {
  installFetchStub(() => ok([{ id: "pool1", label: "Search", rate: { limit: null, window_seconds: 60 }, budget: null }]))
  await expect(listKeyPools("k1")).rejects.toMatchObject({ status: 0 })
})

it("drops unknown operations from a pool response", async () => {
  installFetchStub(() => ok([{ ...pool, operations: ["search", "future"], operation_limits: { search: 2, future: 7 } }]))
  expect((await listKeyPools("k1"))[0]).toMatchObject({ operations: ["search"], operation_limits: { search: 2 } })
})

it("updates and deletes a key and manages its OAuth grant", async () => {
  const stub = installFetchStub((request) => {
    if (request.url.endsWith("/oauth/device")) return ok({ user_code: "ABCD", verification_uri: "https://example.com/", interval: 5, expires_in: 60 })
    if (request.url.includes("/oauth")) return ok({ status: "pending", interval: 5 })
    if (request.method === "DELETE") return ok({ deleted_pools: [{ id: "pool1", project_id: "p1" }] })
    return ok(key)
  })
  await updateVaultKey("k1", { label: "New", overcommit: false })
  await startVaultOAuth("k1")
  await pollVaultOAuth("k1")
  await getVaultOAuth("k1")
  await disconnectVaultOAuth("k1")
  expect(await deleteVaultKey("k1")).toEqual({ deleted_pools: [{ id: "pool1", project_id: "p1" }] })
  expect(stub.requests.map(({ method, url }) => `${method} ${url}`)).toEqual([
    "PATCH /api/v1/account/vault/keys/k1", "POST /api/v1/account/vault/keys/k1/oauth/device",
    "POST /api/v1/account/vault/keys/k1/oauth/poll", "GET /api/v1/account/vault/keys/k1/oauth",
    "DELETE /api/v1/account/vault/keys/k1/oauth", "DELETE /api/v1/account/vault/keys/k1",
  ])
  expect(stub.requests[0]?.body).toEqual({ label: "New", overcommit: false })
})

it("reads and updates pools, and assigns or copies them to projects", async () => {
  const stub = installFetchStub((request) => {
    if (request.url.endsWith("/projects")) return ok([{ id: "p1", name: "Project", available_providers: ["brave"] }])
    if (request.url.endsWith("/keys/k1/pools")) return ok([pool])
    return ok(pool)
  })
  expect(await listKeyPools("k1")).toEqual([pool])
  expect(await getKeyPool("pool1")).toEqual(pool)
  const update = { label: "New", project_id: "must-not-be-sent" }
  await updateKeyPool("pool1", update)
  await copyKeyPool("pool1", "p2", "Copy")
  await assignKeyPool("pool1", "p1")
  await unassignKeyPool("pool1")
  await deleteKeyPool("pool1")
  expect(await listVaultProjects()).toEqual([{ id: "p1", name: "Project", available_providers: ["brave"] }])
  expect(stub.requests.map(({ method, url }) => `${method} ${url}`)).toEqual([
    "GET /api/v1/account/vault/keys/k1/pools", "GET /api/v1/account/vault/pools/pool1",
    "PATCH /api/v1/account/vault/pools/pool1", "POST /api/v1/account/vault/pools/pool1/copy",
    "POST /api/v1/account/vault/pools/pool1/assign", "POST /api/v1/account/vault/pools/pool1/unassign",
    "DELETE /api/v1/account/vault/pools/pool1", "GET /api/v1/account/vault/projects",
  ])
  expect(stub.requests[3]?.body).toEqual({ project_id: "p2", label: "Copy" })
  expect(stub.requests[4]?.body).toEqual({ project_id: "p1" })
  expect(stub.requests[2]?.body).toEqual({ label: "New" })
})

it("allows backend defaults in pool creation", async () => {
  const stub = installFetchStub(() => ok(pool))
  await createKeyPool("k1", { label: "Search", budget: { limit: 1.25 } })
  expect(stub.requests[0]?.body).toEqual({ label: "Search", budget: { limit: 1.25 } })
})
