import { afterEach, describe, expect, it, vi } from "vitest"
import { installFetchStub, ok } from "@/test/fetchMock"
import {
  createBinding,
  decodeProjectProviderView,
  deleteBinding,
  getProjectProviderView,
  setBindingOperations,
} from "./providerViewApi"

const BINDING = { id: "b1", project_id: "proj", credential_id: "c1", route_label: "primary", enabled_operations: [], priority: 100, version: 1 }

describe("providerViewApi", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("decodes providers and this project's allocations", () => {
    const view = decodeProjectProviderView({
      project_id: "proj",
      providers: [{ provider_type: "tavily", capability: ["search"] }, { nope: true }],
      allocations: [{ project_id: "proj", pool_id: "pool", operation_scope: "search", base_rate: 1, rate_window_seconds: 1 }],
    })
    expect(view.providers).toHaveLength(1)
    expect(view.allocations).toHaveLength(1)
  })

  it("rejects a payload without providers", () => {
    expect(() => decodeProjectProviderView({})).toThrow()
  })

  it("reads the view with the signal", async () => {
    const stub = installFetchStub(() => ok({ project_id: "proj", providers: [], allocations: [] }))
    const controller = new AbortController()
    await getProjectProviderView("proj", controller.signal)
    expect(stub.requests[0]?.url).toBe("/api/v1/projects/proj/providers")
    expect(stub.requests[0]?.signal).toBe(controller.signal)
  })

  it("creates a binding without enabled operations, then patches and deletes", async () => {
    const stub = installFetchStub((req) => (req.method === "DELETE" ? new Response(null, { status: 204 }) : ok(BINDING, 201)))
    await createBinding("proj", { credentialId: "c1", routeLabel: "primary", priority: 100 })
    await setBindingOperations("proj", "b1", ["search"])
    await deleteBinding("proj", "b1")
    expect(stub.requests[0]?.body).toEqual({ credential_id: "c1", route_label: "primary", priority: 100 })
    expect(stub.requests[1]?.method).toBe("PATCH")
    expect(stub.requests[1]?.url).toBe("/api/v1/projects/proj/bindings/b1")
    expect(stub.requests[1]?.body).toEqual({ enabled_operations: ["search"] })
    expect(stub.requests[2]?.method).toBe("DELETE")
  })
})
