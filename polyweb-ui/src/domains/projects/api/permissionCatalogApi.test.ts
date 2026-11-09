import { afterEach, expect, it, vi } from "vitest"
import { bulkUpdateProjectMembers, getProjectPermissionCatalog } from "../index"
import { installFetchStub, ok } from "@/test/fetchMock"
import { decodeProjectPermissionCatalog } from "./permissionCatalogApi"

afterEach(() => vi.unstubAllGlobals())

it("reads the catalog and preset bits", async () => {
  const catalog = {
    permissions: [{ key: "search", bit: 1, action: "search.execute", group: "Requests", developer_toggle: true, label: "Run searches", description: "Send search requests in the playground." }],
    presets: [{ key: "standard", label: "Standard", permissions: 15 }],
  }
  installFetchStub(() => ok(catalog))
  expect(await getProjectPermissionCatalog()).toEqual(catalog)
})

it("rejects old preset maps and malformed preset or permission entries", () => {
  expect(() => decodeProjectPermissionCatalog({ permissions: [], presets: { standard: 15 } })).toThrow()
  expect(() => decodeProjectPermissionCatalog({ permissions: [], presets: [{ key: "standard", label: "Standard", permissions: "15" }] })).toThrow()
  expect(() => decodeProjectPermissionCatalog({ permissions: [{ key: "search" }], presets: [] })).toThrow()
})

it("sends atomic member changes with role and permission fields", async () => {
  const stub = installFetchStub(() => ok([]))
  expect(await bulkUpdateProjectMembers("p1", [{ user_id: "u1", role: "developer", permissions: 15 }])).toEqual([])
  expect(stub.requests[0]).toMatchObject({
    method: "PATCH", url: "/api/v1/projects/p1/members/bulk",
    body: { changes: [{ user_id: "u1", role: "developer", permissions: 15 }] },
  })
})
