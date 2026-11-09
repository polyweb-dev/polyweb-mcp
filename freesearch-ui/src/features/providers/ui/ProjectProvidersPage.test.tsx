import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { err, ok } from "@/test/fetchMock"
import type { RecordedRequest } from "@/test/fetchMock"
import { PROJECT_ALPHA_ID, PROJECT_MEMBER_PERMISSIONS } from "@/test/accessFixtures"
import { installWorkspaceStub, renderInProject } from "@/test/workspaceHarness"
import { ProjectProvidersPage } from "./ProjectProvidersPage"

vi.mock("@/shared/notifications/useNotifications", () => ({ useNotifications: () => ({ showToast: vi.fn() }) }))

const BASE = `/api/v1/projects/${PROJECT_ALPHA_ID}`

function providerView(
  overrides: { bindings?: unknown[]; allocations?: unknown[]; killSwitch?: boolean; extraProviders?: unknown[]; checkedAt?: string; health?: string } = {}
) {
  return {
    project_id: PROJECT_ALPHA_ID,
    providers: [
      ...(overrides.extraProviders ?? []),
      {
        provider_type: "tavily",
        capability: ["search", "fetch"],
        kill_switch: overrides.killSwitch ?? false,
        system_enabled_operations: ["search", "fetch"],
        available: true,
        enabled: true,
        effective_operations: ["search"],
        health_status: overrides.health ?? (overrides.checkedAt ? "healthy" : null),
        health_checked_at: overrides.checkedAt,
        credentials: [
          { id: "own", label: "Team Tavily", owner_scope: "project", auth_mode: "api_key", status: "active", health_status: "healthy", health_checked_at: overrides.checkedAt, granted_operations: ["search", "fetch"], supported_operations: ["search", "fetch"], pools: [] },
          { id: "shared", label: "Shared Tavily", owner_scope: "system", auth_mode: "api_key", status: "active", health_status: null, granted_operations: ["search"], supported_operations: ["search", "fetch"], pools: [{ operation_scope: "search", pool_id: "pool-1", label: "Tavily account", upstream_scope: "account", status: "active" }] },
        ],
        bindings: overrides.bindings ?? [
          { id: "b1", credential_id: "own", route_label: "primary", priority: 100, enabled_operations: ["search"], effective_operations: ["search"] },
        ],
      },
      {
        provider_type: "parallel",
        capability: ["search", "fetch"],
        kill_switch: false,
        system_enabled_operations: ["search"],
        available: true,
        enabled: false,
        effective_operations: [],
        credentials: [
          { id: "par", label: "Team Parallel", owner_scope: "project", auth_mode: "oauth", status: "active", granted_operations: ["search"], supported_operations: ["search"], pools: [] },
        ],
        bindings: [],
      },
    ],
    allocations: overrides.allocations ?? [],
  }
}

const PROJECT_CREDENTIALS = [
  { id: "own", provider_type: "tavily", owner_scope: "project", label: "Team Tavily", auth_mode: "api_key", status: "active", permitted_operations: ["search", "fetch"], can_manage: true, generation: 2 },
  { id: "shared", provider_type: "tavily", owner_scope: "system", label: "Shared Tavily", auth_mode: "api_key", status: "active", permitted_operations: ["search"], can_manage: false, generation: null },
  { id: "par", provider_type: "parallel", owner_scope: "project", label: "Team Parallel", auth_mode: "oauth", status: "active", permitted_operations: ["search"], can_manage: true, generation: 1 },
]

const BRAVE_ROUTED = {
  provider_type: "brave",
  capability: ["search"],
  kill_switch: false,
  system_enabled_operations: ["search"],
  available: true,
  enabled: true,
  effective_operations: ["search"],
  credentials: [
    { id: "brave-key", label: "dev-brave", owner_scope: "system", auth_mode: "api_key", status: "active", health_status: "unknown", granted_operations: ["search"], supported_operations: ["search"], pools: [] },
  ],
  bindings: [
    { id: "b9", credential_id: "brave-key", route_label: "brave", priority: 200, enabled_operations: ["search"], effective_operations: ["search"] },
  ],
}

interface StubOptions {
  permissions?: readonly string[]
  view?: ReturnType<typeof providerView>
  credentials?: unknown[]
  onMutation?: (req: RecordedRequest) => Response | null
}

function installProvidersStub(options: StubOptions = {}) {
  return installWorkspaceStub(
    (req) => {
      if (req.method === "GET" && req.url === `${BASE}/providers`) return ok(options.view ?? providerView())
      if (req.method === "GET" && req.url === `${BASE}/credentials`) return ok(options.credentials ?? PROJECT_CREDENTIALS)
      const override = options.onMutation?.(req)
      if (override) return override
      if ((req.method === "GET" && req.url === `${BASE}/routing/order`) || (req.method === "PUT" && req.url.startsWith(`${BASE}/routing/order/`))) {
        const providers = (options.view ?? providerView()).providers
          .filter((row): row is typeof BRAVE_ROUTED => typeof row === "object" && row !== null && "bindings" in row && Array.isArray(row.bindings) && row.bindings.length > 0)
          .map((row) => ({ provider: row.provider_type, name: row.provider_type === "brave" ? "Brave Search" : "Tavily", call_cost_usd: null }))
        const order = { strategy: "lowest_cost", providers, has_saved_custom: false, not_allowed: [] }
        return ok({ revision: 1, search: order, fetch: { ...order, providers: providers.filter((row) => row.provider !== "brave") } })
      }
      if (req.method === "GET" && req.url === `${BASE}/provider-owner`) return ok({ user_id: "acc", email: "owner@example.com" })
      if (req.method === "GET" && req.url === `${BASE}/pools`) return ok([{
        pool_id: "pool-1", label: "Team Tavily", provider_type: "tavily", key_label: "Team Tavily",
        owner: { user_id: "acc", email: "owner@example.com" }, rate: { limit: 60, window_seconds: 60 },
        budget: null, budget_used: 0, operations: ["search", "fetch"],
      }])
      if (req.method === "POST" && req.url === `${BASE}/credentials`) {
        const body = req.body as { label: string; provider_type: string; auth_mode: string }
        return ok({ id: "new", provider_type: body.provider_type, owner_scope: "project", label: body.label, auth_mode: body.auth_mode, status: "active", permitted_operations: [], can_manage: true, generation: 1 }, 201)
      }
      if (req.method === "POST" && req.url.endsWith("/rotate")) return ok({ ...PROJECT_CREDENTIALS[0], generation: 3 })
      if (req.method === "POST" && req.url === `${BASE}/bindings`) {
        return ok({ id: "b2", project_id: PROJECT_ALPHA_ID, credential_id: "own", route_label: "backup", enabled_operations: [], priority: 100, version: 1 }, 201)
      }
      if (req.method === "PATCH") return ok({ id: "b1", project_id: PROJECT_ALPHA_ID, credential_id: "own", route_label: "primary", enabled_operations: ["search", "fetch"], priority: 100, version: 2 })
      if (req.method === "DELETE") return new Response(null, { status: 204 })
      return err(404, null)
    },
    { projectPermissions: options.permissions }
  )
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

describe("ProjectProvidersPage view", () => {
  it("shows the age of the last credential result when the provider view supplies it", async () => {
    const checkedAt = new Date(Date.now() - 7_200_000).toISOString()
    installProvidersStub({ view: providerView({ checkedAt }) })
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    expect(await screen.findByText("Healthy · 2 h ago")).toBeInTheDocument()
  })

  it("shows unknown health and no system tag for a search-only provider", async () => {
    installProvidersStub({ view: providerView({ extraProviders: [BRAVE_ROUTED] }), onMutation: (req) => {
      if (req.method === "GET" && req.url === `${BASE}/pools`) return ok([{
        pool_id: "brave-pool", label: "Brave pool", provider_type: "brave", key_label: "Brave key",
        owner: { user_id: "acc", email: "owner@example.com" }, rate: { limit: 10, window_seconds: 60 },
        budget: null, budget_used: 0, operations: ["search"],
      }])
      return null
    } })
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    const table = await screen.findByRole("table", { name: "Search provider order" })
    const row = within(table).getByRole("row", { name: /Brave pool/ })
    expect(within(row).getByText("Health not known")).toBeInTheDocument()
    expect(within(row).queryByText("System")).toBeNull()
    expect(within(row).queryByRole("switch", { name: "Use Brave Search for Fetch" })).toBeNull()
  })

  it("is read-only without providers.configure and credentials.manage_private", async () => {
    installProvidersStub({ permissions: PROJECT_MEMBER_PERMISSIONS })
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    const table = await screen.findByRole("table", { name: "Search provider order" })
    for (const control of within(table).queryAllByRole("switch")) expect(control).toBeDisabled()
    expect(within(table).queryByRole("button", { name: "Actions for Tavily" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Add provider capacity" })).toBeNull()
  })

  it("shows project health as an error for all viewers even when credential health differs", async () => {
    const checkedAt = new Date(Date.now() - 7_200_000).toISOString()
    installProvidersStub({ permissions: PROJECT_MEMBER_PERMISSIONS, view: providerView({ checkedAt, health: "degraded" }) })
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    expect(await screen.findByText("Error · 2 h ago")).toBeInTheDocument()
    expect(screen.queryByText("Healthy · 2 h ago")).toBeNull()
  })



  it("shows the kill switch badge", async () => {
    installProvidersStub({ view: providerView({ killSwitch: true }) })
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    expect((await screen.findAllByText("Disabled by system")).length).toBeGreaterThan(0)
  })



  it("shows no capacity section and no capacity line without allocations", async () => {
    installProvidersStub()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await screen.findByRole("table", { name: "Search provider order" })
    expect(screen.queryByRole("heading", { name: "Capacity allocations" })).toBeNull()
    expect(screen.queryByText(/shared capacity/i)).toBeNull()
  })
})

describe("ProjectProvidersPage routes", () => {


  it("moves a provider up with one custom-order write", async () => {
    const stub = installProvidersStub({
      view: providerView({ extraProviders: [BRAVE_ROUTED] }),
    })
    const user = userEvent.setup()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await user.click(await screen.findByRole("button", { name: "Move Tavily priority up" }))
    await waitFor(() => expect(stub.requests.find((req) => req.method === "PUT")?.body)
      .toEqual({ strategy: "custom", order: ["tavily", "brave"] }))
  })

})

const CAPACITY_POOL = {
  pool_id: "pool-1", label: "Tavily pool", provider_type: "tavily", key_label: "Team Tavily",
  owner: { user_id: "acc", email: "owner@example.com" }, rate: { limit: 60, window_seconds: 60 },
  budget: { limit: 10, period: "month" }, budget_used: 2, operations: ["search"],
}
const VAULT_KEY = {
  id: "par", provider_type: "parallel", label: "Parallel key", auth_mode: "api_key",
  status: "active", generation: 1, created_at: "2026-01-01", capacity: null,
  overcommit: true, contention_mode: "equal", pool_count: 0,
}

function capacityStub(ownerId = "acc", permissions = [...PROJECT_MEMBER_PERMISSIONS, "providers.configure", "providers.supply"]) {
  return installProvidersStub({
    permissions,
    onMutation: (req) => {
      if (req.method === "GET" && req.url === `${BASE}/provider-owner`) return ok({ user_id: ownerId, email: "owner@example.com" })
      if (req.method === "GET" && req.url === `${BASE}/pools`) return ok([CAPACITY_POOL])
      if (req.method === "GET" && req.url === "/api/v1/account/vault/keys") return ok([VAULT_KEY])
      if (req.method === "POST" && req.url === "/api/v1/account/vault/keys/par/pools") return ok({
        id: "pool-2", credential_id: "par", provider_type: "parallel", project_id: PROJECT_ALPHA_ID,
        label: "Alpha - Parallel", rate: { limit: 60, window_seconds: 60 },
        budget: null, budget_used_usd: 0, operations: ["search", "fetch"], operation_limits: null,
      }, 201)
      if (req.method === "POST" && req.url === "/api/v1/account/vault/pools/pool-1/unassign") return ok({
        id: "pool-1", credential_id: "k1", provider_type: "tavily", project_id: null,
        label: "Tavily pool", rate: CAPACITY_POOL.rate, budget: null, budget_used_usd: 0,
        operations: ["search"], operation_limits: null,
      })
      return null
    },
  })
}

describe("ProjectProvidersPage pool capacity", () => {
  function keylessStub(ownerId = "acc", keys: unknown[] = []) {
    const keyless = {
      provider_type: "keenable", capability: ["search", "fetch"], kill_switch: false,
      system_enabled_operations: ["search", "fetch"], available: true, enabled: true, keyless: true,
      call_cost_usd: { search: "0", fetch: "0" }, keyless_call_cost_usd: { search: "0", fetch: "0" },
      effective_operations: ["search", "fetch"], credentials: [], bindings: [],
    }
    return installProvidersStub({
      permissions: [...PROJECT_MEMBER_PERMISSIONS, "providers.configure", "providers.supply"],
      view: providerView({ extraProviders: [keyless] }),
      onMutation: (req) => {
        if (req.url === `${BASE}/provider-owner`) return ok({ user_id: ownerId, email: "owner@example.com" })
        if (req.url === `${BASE}/pools`) return ok([CAPACITY_POOL])
        if (req.url === "/api/v1/account/vault/keys") return ok(keys)
        if (req.url === `${BASE}/routing/order`) {
          const order = { strategy: "lowest_cost", providers: [
            { provider: "keenable", name: "Keenable", call_cost_usd: 0, keyless: true },
            { provider: "tavily", name: "Tavily", call_cost_usd: 0.01, keyless: false },
          ], has_saved_custom: false, not_allowed: [] }
          return ok({ revision: 1, search: order, fetch: order })
        }
        return null
      },
    })
  }

  it("offers a key for a keyless provider without listing it as missing capacity", async () => {
    keylessStub()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    const table = await screen.findByRole("table", { name: "Search provider order" })
    const row = within(table).getByText("Keenable").closest("tr")
    if (!row) throw new Error("Missing Keenable row")
    expect(within(row).getByText("No key needed")).toBeInTheDocument()
    expect(within(row).getAllByRole("cell")[2]).toHaveTextContent("—")
    const pooled = within(table).getByText("Tavily pool").closest("tr")
    if (!pooled) throw new Error("Missing Tavily row")
    expect(within(pooled).queryByText("No key needed")).toBeNull()
    expect(within(pooled).queryByText("No pool needed")).toBeNull()
    expect(within(screen.getByRole("table", { name: "Without capacity" })).queryByText("Keenable")).toBeNull()
    await userEvent.click(within(row).getByRole("button", { name: "Actions for Keenable" }))
    expect(screen.queryByRole("button", { name: "Edit pool" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Unassign" })).toBeNull()
    await userEvent.click(screen.getByRole("button", { name: "Add a key for higher limits" }))
    const dialog = await screen.findByRole("dialog", { name: "Add key" })
    expect(within(dialog).getByLabelText("Label")).toHaveValue("Keenable key")
  })

  it("keeps a keyless provider selected when the owner has multiple keys", async () => {
    keylessStub("acc", [
      { ...VAULT_KEY, id: "k1", provider_type: "keenable", label: "First" },
      { ...VAULT_KEY, id: "k2", provider_type: "keenable", label: "Second" },
    ])
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await userEvent.click(await screen.findByRole("button", { name: "Actions for Keenable" }))
    await userEvent.click(screen.getByRole("button", { name: "Add a key for higher limits" }))
    const dialog = await screen.findByRole("dialog", { name: "Add capacity to Alpha" })
    expect(within(dialog).getByRole("combobox", { name: "Provider" })).toHaveTextContent("Keenable")
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Provider" }))
    expect(within(dialog).getByRole("option", { name: "Keenable" })).toBeInTheDocument()
  })

  it("does not offer keyless actions to a non-owner", async () => {
    keylessStub("another")
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    const table = await screen.findByRole("table", { name: "Search provider order" })
    const row = within(table).getByText("Keenable").closest("tr")
    if (!row) throw new Error("Missing Keenable row")
    expect(within(row).getAllByRole("cell")[2]).toHaveTextContent("—")
    expect(within(table).queryByRole("button", { name: "Actions for Keenable" })).toBeNull()
  })

  it("shows pool details and providers without capacity to the owner", async () => {
    capacityStub()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    expect(await screen.findByText(/Provider owner: owner@example.com/)).toHaveTextContent("(you)")
    expect(await screen.findByText("Tavily pool")).toBeInTheDocument()
    expect(screen.getByText("60/min · $2.00 of $10.00 this month")).toBeInTheDocument()
    const missing = screen.getByRole("table", { name: "Without capacity" })
    expect(within(missing).getByRole("button", { name: "Add capacity for Parallel" })).toBeInTheDocument()
    expect(within(missing).queryByText("Tavily")).toBeNull()
    expect(screen.queryByRole("button", { name: "Add provider capacity" })).toBeNull()
  })

  it("opens capacity with the provider and project preset", async () => {
    const stub = capacityStub()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await userEvent.click(await screen.findByRole("button", { name: "Add capacity for Parallel" }))
    const dialog = await screen.findByRole("dialog", { name: "Create pool from Parallel key" })
    expect(within(dialog).getByRole("combobox", { name: "Project" })).toHaveTextContent("Alpha")
    expect(within(dialog).getByLabelText("Pool name")).toHaveValue("Alpha - Parallel")
    expect(within(dialog).getByRole("checkbox", { name: "Search" })).toBeChecked()
    expect(within(dialog).queryByLabelText("Search requests")).toBeNull()
    await userEvent.click(within(dialog).getByRole("button", { name: "Create pool" }))
    await waitFor(() => expect(stub.requests.find((req) => req.method === "POST" && req.url === "/api/v1/account/vault/keys/par/pools")?.body)
      .toMatchObject({ project_id: PROJECT_ALPHA_ID, operations: ["search", "fetch"] }))
  })

  it("hides capacity controls from other users", async () => {
    const stub = capacityStub("another", [...PROJECT_MEMBER_PERMISSIONS, "providers.supply"])
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    expect(await screen.findByText(/Provider owner: owner@example.com/)).toBeInTheDocument()
    expect(await screen.findByText("The provider owner must add capacity")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Add (provider )?capacity/ })).toBeNull()
    expect(screen.queryByRole("button", { name: "Actions for Tavily" })).toBeNull()
    expect(stub.requests.some((req) => req.url.startsWith("/api/v1/account/vault"))).toBe(false)
  })

  it("confirms before unassigning and never calls retired project writes", async () => {
    const stub = capacityStub()
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Actions for Tavily" }))
    await user.click(await screen.findByRole("button", { name: "Unassign" }))
    expect(stub.requests.some((req) => req.url.endsWith("/unassign"))).toBe(false)
    const dialog = await screen.findByRole("dialog", { name: "Unassign pool" })
    await user.click(within(dialog).getByRole("button", { name: "Unassign" }))
    await waitFor(() => expect(stub.requests.some((req) => req.method === "POST" && req.url === "/api/v1/account/vault/pools/pool-1/unassign")).toBe(true))
    expect(stub.requests.some((req) => req.url.includes("/credentials") || (req.method !== "GET" && req.url.includes("/bindings")) || req.url.includes("/allocations"))).toBe(false)
  })

  it("shows a calm not available state when the pools endpoint is absent", async () => {
    installProvidersStub({ onMutation: (req) => {
      if (req.method === "GET" && req.url === `${BASE}/provider-owner`) return ok(null)
      if (req.method === "GET" && req.url === `${BASE}/pools`) return err(404, null)
      return null
    } })
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    expect(await screen.findByText("Provider capacity is not available yet")).toBeInTheDocument()
    expect(screen.queryByRole("table", { name: "Without capacity" })).toBeNull()
  })
})

describe("ProjectProvidersPage pool operations", () => {
  function stub(operations: string[], owner = "acc") {
    let current = operations
    return installProvidersStub({ permissions: [...PROJECT_MEMBER_PERMISSIONS, "providers.configure", "providers.supply"], onMutation: (req) => {
      if (req.url === `${BASE}/provider-owner`) return ok({ user_id: owner, email: "owner@example.com" })
      if (req.url === `${BASE}/pools`) return ok([{ ...CAPACITY_POOL, operations: current }])
      if (req.method === "GET" && req.url === `${BASE}/routing/order`) {
        const entry = { provider: "tavily", name: "Tavily", call_cost_usd: null }
        const order = (operation: string) => ({ strategy: "lowest_cost", providers: current.includes(operation) ? [entry] : [],
          has_saved_custom: false, not_allowed: current.includes(operation) ? [] : ["tavily"] })
        return ok({ revision: 1, search: order("search"), fetch: order("fetch") })
      }
      if (req.method === "PATCH" && req.url === "/api/v1/account/vault/pools/pool-1") {
        current = (req.body as { operations: string[] }).operations
        return ok({ id: "pool-1", credential_id: "k1", provider_type: "tavily", project_id: PROJECT_ALPHA_ID,
          label: "Tavily pool", rate: CAPACITY_POOL.rate, budget: null, budget_used_usd: 0, operations: current, operation_limits: null })
      }
      return null
    } })
  }

  it("confirms removal and patches the serving pool", async () => {
    const requests = stub(["search", "fetch"])
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await userEvent.click(await screen.findByRole("switch", { name: "Use Tavily for Search" }))
    const dialog = await screen.findByRole("dialog", { name: "Remove Search from Tavily pool" })
    expect(requests.requests.some((req) => req.method === "PATCH")).toBe(false)
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove Search" }))
    await waitFor(() => expect(requests.requests.find((req) => req.method === "PATCH")?.body).toEqual({ operations: ["fetch"] }))
    expect(await screen.findByRole("switch", { name: "Use Tavily for Search" })).not.toBeChecked()
  })

  it("does not change the pool when removal is canceled", async () => {
    const requests = stub(["search", "fetch"])
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await userEvent.click(await screen.findByRole("switch", { name: "Use Tavily for Search" }))
    const dialog = await screen.findByRole("dialog", { name: "Remove Search from Tavily pool" })
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
    expect(requests.requests.some((req) => req.method === "PATCH")).toBe(false)
    expect(screen.getByRole("switch", { name: "Use Tavily for Search" })).toBeChecked()
  })

  it("keeps the Fetch tab selected after its pool changes", async () => {
    const requests = stub(["search", "fetch"])
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await userEvent.click(await screen.findByRole("tab", { name: "Fetch 1" }))
    await userEvent.click(screen.getByRole("switch", { name: "Use Tavily for Fetch" }))
    const dialog = await screen.findByRole("dialog", { name: "Remove Fetch from Tavily pool" })
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove Fetch" }))
    await waitFor(() => expect(requests.requests.find((req) => req.method === "PATCH")?.body).toEqual({ operations: ["search"] }))
    expect(await screen.findByRole("tab", { name: "Fetch 0" })).toHaveAttribute("aria-selected", "true")
  })

  it("refuses to remove the last operation", async () => {
    const requests = stub(["search"])
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await userEvent.click(await screen.findByRole("switch", { name: "Use Tavily for Search" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("A pool must allow at least one operation.")
    expect(requests.requests.some((req) => req.method === "PATCH")).toBe(false)
  })

  it("enables an operation excluded from its order", async () => {
    const requests = stub(["fetch"])
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    await userEvent.click(await screen.findByRole("switch", { name: "Use Tavily for Search" }))
    await waitFor(() => expect(requests.requests.find((req) => req.method === "PATCH")?.body).toEqual({ operations: ["fetch", "search"] }))
    expect(await screen.findByRole("switch", { name: "Use Tavily for Search" })).toBeChecked()
  })

  it("hides the read-only operation column when all providers are on", async () => {
    stub(["search"], "other")
    renderInProject(<ProjectProvidersPage accountId="acc" />)
    const table = await screen.findByRole("table", { name: "Search provider order" })
    expect(within(table).queryByRole("columnheader", { name: "On" })).toBeNull()
    expect(within(table).queryByRole("switch")).toBeNull()
  })
})
