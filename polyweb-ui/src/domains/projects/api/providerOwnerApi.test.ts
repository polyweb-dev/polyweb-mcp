import { afterEach, expect, it, vi } from "vitest"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { getProviderOwner, transferProviderOwner } from "./providerOwnerApi"

afterEach(() => vi.unstubAllGlobals())

it("reads an unassigned owner and sends a claim", async () => {
  const stub = installFetchStub((request) => request.method === "GET"
    ? ok(null)
    : ok({ user_id: "u1", unassigned_pools: [] }))
  expect(await getProviderOwner("p1")).toBeNull()
  expect(await transferProviderOwner("p1", "u1")).toEqual({
    user_id: "u1", unassigned_pools: [],
  })
  expect(stub.requests[1]?.body).toEqual({ user_id: "u1" })
})

it("preserves a missing endpoint as a 404", async () => {
  installFetchStub(() => err(404, null))
  await expect(getProviderOwner("p1")).rejects.toMatchObject({ status: 404 })
})

it("decodes named, username-only, legacy, and nullable owner profiles", async () => {
  installFetchStub((request) => request.method === "GET"
    ? ok({ user_id: "u1", username: "ada", first_name: "Ada", last_name: "Lovelace" })
    : ok({ user_id: "u1", username: "ada", first_name: "Ada", last_name: "Lovelace", unassigned_pools: [] }))
  expect(await getProviderOwner("p1")).toEqual({
    user_id: "u1", username: "ada", first_name: "Ada", last_name: "Lovelace",
  })

  installFetchStub(() => ok({ user_id: "u1", username: "ops-lead" }))
  expect(await getProviderOwner("p1")).toEqual({
    user_id: "u1", username: "ops-lead", first_name: null, last_name: null,
  })

  installFetchStub(() => ok({ user_id: "u1" }))
  expect(await getProviderOwner("p1")).toEqual({ user_id: "u1" })

  installFetchStub(() => ok({ user_id: "u1", username: null, first_name: null, last_name: null }))
  expect(await getProviderOwner("p1")).toEqual({
    user_id: "u1", username: null, first_name: null, last_name: null,
  })
})

it("rejects an owner profile field of the wrong type", async () => {
  for (const profile of [{ username: 7 }, { first_name: 7 }, { last_name: 7 }]) {
    installFetchStub(() => ok({ user_id: "u1", ...profile }))
    await expect(getProviderOwner("p1")).rejects.toMatchObject({
      status: 0,
      detail: "The server returned an unexpected provider owner.",
    })
  }
})

it("decodes owners without an email and ignores an email an older server still sends", async () => {
  installFetchStub(() => ok({ user_id: "u1", email: "old@example.com", username: "ada" }))
  const decoded = await getProviderOwner("p1")
  expect(decoded).toEqual({ user_id: "u1", username: "ada", first_name: null, last_name: null })
  expect(decoded).not.toHaveProperty("email")

  installFetchStub(() => ok({ user_id: "u1" }))
  expect(await getProviderOwner("p1")).toEqual({ user_id: "u1" })
})
