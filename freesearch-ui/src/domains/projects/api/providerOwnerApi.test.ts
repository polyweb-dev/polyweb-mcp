import { afterEach, expect, it, vi } from "vitest"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { getProviderOwner, transferProviderOwner } from "./providerOwnerApi"

afterEach(() => vi.unstubAllGlobals())

it("reads an unassigned owner and sends a claim", async () => {
  const stub = installFetchStub((request) => request.method === "GET"
    ? ok(null)
    : ok({ user_id: "u1", email: "admin@example.com", unassigned_pools: [] }))
  expect(await getProviderOwner("p1")).toBeNull()
  expect(await transferProviderOwner("p1", "u1")).toEqual({
    user_id: "u1", email: "admin@example.com", unassigned_pools: [],
  })
  expect(stub.requests[1]?.body).toEqual({ user_id: "u1" })
})

it("preserves a missing endpoint as a 404", async () => {
  installFetchStub(() => err(404, null))
  await expect(getProviderOwner("p1")).rejects.toMatchObject({ status: 404 })
})
