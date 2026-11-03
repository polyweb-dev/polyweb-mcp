import { afterEach, describe, expect, it, vi } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { err, ok } from "@/test/fetchMock"
import type { RecordedRequest } from "@/test/fetchMock"
import { PROJECT_ALPHA_ID } from "@/test/accessFixtures"
import { installWorkspaceStub, renderInWorkspace } from "@/test/workspaceHarness"
import { CapacityPage } from "./CapacityPage"

const POOL = { id: "pool-1", provider_type: "tavily", upstream_scope: "account", pool_key: "acct-1", label: "Tavily account", constraints: [{ algorithm: "token_bucket", window_seconds: 1, limit: 10 }], max_concurrency: 4, max_queued_requests: null, status: "active", version: 1 }
const LOANS = { project_id: PROJECT_ALPHA_ID, pool_id: "pool-1", operation_scope: "search", base_rate: 5, rate_window_seconds: 60, borrow_enabled: true, max_rate: 20, effective_max_rate: 20, weight: 2, best_effort: false, max_concurrency: null, max_queued_requests: null, max_queued_bytes: null, max_queue_wait_ms: null, version: 1 }
const ALLOCATIONS_URL = `/api/v1/system/projects/${PROJECT_ALPHA_ID}/allocations`

function installCapacityStub(options: { systemPermissions?: readonly string[]; onMutation?: (req: RecordedRequest) => Response | null } = {}) {
  return installWorkspaceStub(
    (req) => {
      if (req.method === "GET" && req.url === "/api/v1/system/pools") return ok([POOL])
      if (req.method === "GET" && req.url === ALLOCATIONS_URL) return ok([LOANS])
      if (req.method === "GET" && req.url === "/api/v1/system/pools/pool-1/links") return ok([])
      if (req.method === "GET" && req.url === "/api/v1/system/credentials") {
        return ok([{ id: "c1", provider_type: "tavily", owner_scope: "system", label: "Shared Tavily", auth_mode: "api_key", generation: 1, status: "active" }])
      }
      const override = options.onMutation?.(req)
      if (override) return override
      if (req.method === "PUT" && req.url.includes("/allocations/")) return ok(LOANS)
      if (req.method === "PUT" && req.url.includes("/links/")) return ok({ credential_id: "c1", pool_id: "pool-1", operation_scope: "fetch", provider_type: "tavily", version: 1 })
      if (req.method === "POST" && req.url === "/api/v1/system/pools") return ok(POOL, 201)
      if (req.method === "DELETE") return new Response(null, { status: 204 })
      return err(404, null)
    },
    options.systemPermissions === undefined ? {} : { systemPermissions: options.systemPermissions }
  )
}

afterEach(() => vi.unstubAllGlobals())

describe("CapacityPage pools", () => {
  it("lists pools with readable limits", async () => {
    installCapacityStub()
    renderInWorkspace(<CapacityPage />)
    expect(await screen.findByRole("heading", { level: 1, name: "Capacity" })).toBeInTheDocument()
    const pools = await screen.findByRole("table", { name: "Pools" })
    expect(within(pools).getByText("Tavily account")).toBeInTheDocument()
    expect(within(pools).getByText("10 per second (token bucket)")).toBeInTheDocument()
    expect(within(pools).getByRole("button", { name: "Edit pool Tavily account" })).toBeInTheDocument()
  })

  it("creates a pool with a limit row", async () => {
    const stub = installCapacityStub()
    const user = userEvent.setup()
    renderInWorkspace(<CapacityPage />)
    await user.click(await screen.findByRole("button", { name: "Add pool" }))
    const dialog = await screen.findByRole("dialog", { name: "Add pool" })
    await user.selectOptions(within(dialog).getByLabelText("Provider"), "tavily")
    await user.type(within(dialog).getByLabelText("Label"), "New pool")
    await user.selectOptions(within(dialog).getByLabelText("Upstream scope"), "credential")
    await user.type(within(dialog).getByLabelText("Pool key"), "key-1")
    await user.click(within(dialog).getByRole("button", { name: "Add limit" }))
    await user.click(within(dialog).getByRole("button", { name: "Save pool" }))
    await waitFor(() => expect(stub.requests.find((req) => req.method === "POST")?.body).toEqual({
      provider_type: "tavily",
      upstream_scope: "credential",
      pool_key: "key-1",
      label: "New pool",
      constraints: [{ algorithm: "token_bucket", window_seconds: 1, limit: 10 }],
      max_concurrency: null,
      max_queued_requests: null,
    }))
  })

  it("links a credential of the same provider", async () => {
    const stub = installCapacityStub()
    const user = userEvent.setup()
    renderInWorkspace(<CapacityPage />)
    await user.click(await screen.findByRole("button", { name: "Links Tavily account" }))
    const dialog = await screen.findByRole("dialog", { name: "Credential links" })
    await within(dialog).findByRole("option", { name: "Shared Tavily" })
    await user.selectOptions(within(dialog).getByLabelText("Operation"), "fetch")
    await user.click(within(dialog).getByRole("button", { name: "Link credential" }))
    await waitFor(() => expect(stub.requests.find((req) => req.method === "PUT")?.url).toBe("/api/v1/system/pools/pool-1/links/c1?operation_scope=fetch"))
  })
})

describe("CapacityPage allocations", () => {
  it("shows the selected project's allocations with the loans explanation", async () => {
    installCapacityStub()
    renderInWorkspace(<CapacityPage />)
    const section = await screen.findByRole("region", { name: "Project allocations" })
    const explanation = await within(section).findByTestId("allocation-explanation")
    expect(explanation).toHaveTextContent("Loans enabled")
    expect(explanation).toHaveTextContent(
      "Guaranteed 5 per minute under contention (weight 2). Can borrow up to 20 per minute when the pool is idle. The pool limit always applies."
    )
    expect(within(section).getByRole("button", { name: "Edit allocation Tavily account search" })).toBeInTheDocument()
    expect(within(section).getByRole("button", { name: "Remove allocation Tavily account search" })).toBeInTheDocument()
  })

  it("blocks a zero base without best effort and a max below base", async () => {
    const stub = installCapacityStub()
    const user = userEvent.setup()
    renderInWorkspace(<CapacityPage />)
    await user.click(await screen.findByRole("button", { name: "Add allocation" }))
    const dialog = await screen.findByRole("dialog", { name: "Add allocation" })
    expect(within(dialog).queryByLabelText("Max rate")).toBeNull()
    const base = within(dialog).getByLabelText("Base rate")
    await user.clear(base)
    await user.type(base, "0")
    await user.click(within(dialog).getByRole("button", { name: "Save allocation" }))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("A zero base rate needs best effort.")

    await user.clear(base)
    await user.type(base, "10")
    await user.click(within(dialog).getByRole("radio", { name: "Loans enabled" }))
    await user.type(within(dialog).getByLabelText("Max rate"), "5")
    await user.click(within(dialog).getByRole("button", { name: "Save allocation" }))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Max rate must be at least the base rate.")
    expect(stub.requests.filter((req) => req.method === "PUT")).toHaveLength(0)
  })

  it("explains an infeasible 409 with the server message", async () => {
    installCapacityStub({
      onMutation: (req) =>
        req.method === "PUT" && req.url.includes("/allocations/")
          ? err(409, { detail: { code: "ALLOCATION_INFEASIBLE", message: "Guaranteed rates exceed the pool limit." } })
          : null,
    })
    const user = userEvent.setup()
    renderInWorkspace(<CapacityPage />)
    await user.click(await screen.findByRole("button", { name: "Add allocation" }))
    const dialog = await screen.findByRole("dialog", { name: "Add allocation" })
    await user.click(within(dialog).getByRole("button", { name: "Save allocation" }))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Not feasible: Guaranteed rates exceed the pool limit.")
  })

  it("saves a strict allocation for the selected pool and operation", async () => {
    const stub = installCapacityStub()
    const user = userEvent.setup()
    renderInWorkspace(<CapacityPage />)
    await user.click(await screen.findByRole("button", { name: "Add allocation" }))
    const dialog = await screen.findByRole("dialog", { name: "Add allocation" })
    await user.selectOptions(within(dialog).getByLabelText("Operation"), "fetch")
    await user.click(within(dialog).getByRole("button", { name: "Save allocation" }))
    await waitFor(() => expect(stub.requests.find((req) => req.method === "PUT")?.url).toBe(`${ALLOCATIONS_URL}/pool-1?operation_scope=fetch`))
    expect(stub.requests.find((req) => req.method === "PUT")?.body).toMatchObject({ base_rate: 10, rate_window_seconds: 60, borrow_enabled: false, max_rate: null, weight: 1, best_effort: false })
  })

  it("is read-only without allocation management", async () => {
    installCapacityStub({ systemPermissions: ["system.pools.manage"] })
    renderInWorkspace(<CapacityPage />)
    const section = await screen.findByRole("region", { name: "Project allocations" })
    expect(await within(section).findByTestId("allocation-explanation")).toBeInTheDocument()
    expect(within(section).queryByRole("button", { name: "Add allocation" })).toBeNull()
    expect(within(section).queryByRole("button", { name: /Edit allocation/ })).toBeNull()
  })

  it("hides pool management without pools.manage", async () => {
    const stub = installCapacityStub({ systemPermissions: ["system.allocations.manage"] })
    renderInWorkspace(<CapacityPage />)
    expect(await screen.findByText("Only a pool administrator can view pools.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Add pool" })).toBeNull()
    expect(stub.requestsTo("/api/v1/system/pools")).toHaveLength(0)
  })
})
