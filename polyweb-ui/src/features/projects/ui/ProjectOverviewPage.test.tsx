import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectsProvider, ProjectScopeProvider } from "@/domains/projects"
import { ProjectOverviewPage } from "./ProjectOverviewPage"

const PROJECT = { id: "p1", account_id: "a", name: "Alpha", slug: "alpha", status: "active", created_by: "u", created_at: "t", version: 1 }

const ORDER = {
  revision: 1,
  search: {
    strategy: "custom", has_saved_custom: true, not_allowed: ["tavily"],
    providers: [
      { provider: "keenable", name: "Keenable", call_cost_usd: 0, keyless: true },
      { provider: "exa", name: "Exa", call_cost_usd: "0", keyless: false },
      { provider: "brave", name: "Brave Search", call_cost_usd: "0.005", keyless: false },
      { provider: "firecrawl", name: "Firecrawl", call_cost_usd: "0.01", keyless: false },
    ],
  },
  fetch: {
    strategy: "lowest_cost", has_saved_custom: false, not_allowed: [],
    providers: [
      { provider: "exa", name: "Exa", call_cost_usd: 0, keyless: false },
      { provider: "keenable", name: "Keenable", call_cost_usd: null, keyless: true },
    ],
  },
}

const DASHBOARD = {
  project_id: "p1",
  totals: [
    { provider: "tavily", operation: "search", total_units: "2.5", event_count: 2, unit_kind: "CREDIT" },
    { provider: "brave", operation: "search", total_units: "3", event_count: 3, unit_kind: "REQUEST" },
    { provider: "exa", operation: "fetch", total_units: "1", event_count: 1, unit_kind: "REQUEST" },
  ],
  recent_usage: [],
  generated_at: "2026-10-30T10:00:00Z",
}

function providersView(bindingOps: string[] = [], withCredential = true) {
  return {
    project_id: "p1",
    providers: [
      {
        provider_type: "brave",
        capability: ["search"],
        kill_switch: false,
        system_enabled_operations: ["search"],
        available: true,
        enabled: true,
        credentials: withCredential
          ? [
              {
                id: "cred-1",
                label: "Brave key",
                owner_scope: "project",
                auth_mode: "api_key",
                status: "active",
                health_status: "ok",
                granted_operations: ["search"],
                supported_operations: ["search"],
                pools: [],
              },
            ]
          : [],
        bindings:
          bindingOps.length === 0
            ? []
            : [
                {
                  id: "binding-1",
                  credential_id: "cred-1",
                  route_label: "Brave",
                  priority: 1,
                  enabled_operations: bindingOps,
                  effective_operations: bindingOps,
                },
              ],
        effective_operations: bindingOps,
      },
    ],
    allocations: [],
  }
}

function renderPage(
  permissions: string[] = ["project.read", "members.read"],
  providerResponse: Response = ok(providersView(["search"]))
) {
  return installFetchStub((req) => {
    if (req.url === "/api/v1/projects/p1/dashboard") return ok(DASHBOARD)
    if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
    if (req.url === "/api/v1/projects?include_archived=true") return ok([PROJECT])
    if (req.url === "/api/v1/projects/p1/providers") return providerResponse
    if (req.url === "/api/v1/projects/p1/routing/order") return ok(ORDER)
    if (req.url === "/api/v1/projects/p1/access") {
      return ok({ project_id: "p1", permissions, roles: ["project_member", "routing_editor"], policy_revision: 2 })
    }
    return err(404, null)
  })
}

function renderOverview(permissions?: string[], providerResponse?: Response) {
  const stub = renderPage(permissions, providerResponse)
  render(
    <MemoryRouter>
      <ProjectsProvider accountId="acc">
        <ProjectScopeProvider accountId="acc" projectId="p1">
          <ProjectOverviewPage />
        </ProjectScopeProvider>
      </ProjectsProvider>
    </MemoryRouter>
  )
  return stub
}

describe("ProjectOverviewPage", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("shows the project name and the caller's roles as tags without execution data", async () => {
    renderOverview()
    await screen.findByRole("heading", { name: "Alpha" })
    expect(screen.queryByRole("list", { name: "Your roles" })).not.toBeInTheDocument()
    expect(screen.queryByText("Project member")).not.toBeInTheDocument()
    expect(screen.queryByText("Routing editor")).not.toBeInTheDocument()
    expect(screen.queryByText(/Active project/)).toBeNull()
    expect(screen.queryByText(/Your roles:/)).toBeNull()
    expect(screen.queryByRole("link", { name: "Members" })).toBeNull()
    expect(screen.queryByText(/results|queries/i)).toBeNull()
  })

  it("hides the Members link without members.read", async () => {
    renderOverview(["project.read"])
    await screen.findByRole("heading", { name: "Alpha" })
    expect(screen.queryByRole("link", { name: "Members" })).toBeNull()
  })

  it("summarizes this project's dashboard usage per operation with usage.read", async () => {
    const stub = renderOverview(["project.read", "usage.read"])
    const summary = await screen.findByRole("region", { name: "Usage summary" })
    const searches = (await within(summary).findByText("Searches")).closest("div") as HTMLElement
    const fetches = within(summary).getByText("Fetches").closest("div") as HTMLElement
    const cost = within(summary).getByText("Known provider cost").closest("div") as HTMLElement
    expect(searches).toHaveTextContent("Searches5All time")
    expect(fetches).toHaveTextContent("Fetches1All time")
    // No provider reported dollars; the native credits name their provider.
    expect(cost).toHaveTextContent("Known provider cost\u2014All time")
    expect(cost).not.toHaveTextContent("Tavily credits")
    expect(summary).not.toHaveTextContent("requests")
    expect(within(summary).queryByText("5 events")).toBeNull()
    expect(stub.requestsTo("/api/v1/projects/p1/dashboard")).toHaveLength(1)
  })

  it("shows the dollar cost with named credits and a missing operation as 0", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/projects/p1/dashboard") {
        return ok({
          ...DASHBOARD,
          totals: [
            {
              provider: "tavily",
              operation: "search",
              total_units: "1",
              event_count: 1,
              unit_kind: "CREDIT",
            },
            {
              provider: "exa",
              operation: "search",
              total_units: "0.035",
              event_count: 2,
              unit_kind: "USD",
            },
          ],
        })
      }
      if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
      if (req.url === "/api/v1/projects?include_archived=true") return ok([PROJECT])
      if (req.url === "/api/v1/projects/p1/access") {
        return ok({ project_id: "p1", permissions: ["project.read", "usage.read"], roles: [], policy_revision: 1 })
      }
      return err(404, null)
    })
    render(
      <MemoryRouter>
        <ProjectsProvider accountId="acc">
          <ProjectScopeProvider accountId="acc" projectId="p1">
            <ProjectOverviewPage />
          </ProjectScopeProvider>
        </ProjectsProvider>
      </MemoryRouter>
    )
    const summary = await screen.findByRole("region", { name: "Usage summary" })
    const searches = (await within(summary).findByText("Searches")).closest("div") as HTMLElement
    const fetches = within(summary).getByText("Fetches").closest("div") as HTMLElement
    const cost = within(summary).getByText("Known provider cost").closest("div") as HTMLElement
    expect(searches).toHaveTextContent("Searches3All time")
    expect(fetches).toHaveTextContent("Fetches0All time")
    expect(cost).toHaveTextContent("Known provider cost$0.035All time")
    expect(cost).not.toHaveTextContent("Tavily credit")
    vi.unstubAllGlobals()
  })

  it("shows no usage summary and reads no dashboard without usage.read", async () => {
    const stub = renderOverview(["project.read"])
    await screen.findByRole("heading", { name: "Alpha" })
    expect(screen.queryByRole("region", { name: "Usage summary" })).toBeNull()
    expect(stub.requestsTo("/api/v1/projects/p1/dashboard")).toHaveLength(0)
  })

  it.each([
    ["admin", ["project.read", "providers.read", "providers.configure"]],
    ["developer", ["project.read", "providers.read"]],
  ])("shows the project order for a %s without using legacy bindings", async (_role, permissions) => {
    const stub = renderOverview(permissions, ok(providersView([], false)))
    const search = await screen.findByRole("list", { name: "Search order" })
    const fetch = screen.getByRole("list", { name: "Fetch order" })
    expect(within(search).getAllByRole("listitem").map((row) => row.textContent)).toEqual([
      "Rank 1Keenable", "Rank 2Exa", "Rank 3Brave Search",
    ])
    expect(within(fetch).getAllByRole("listitem").map((row) => row.textContent)).toEqual([
      "Rank 1Exa", "Rank 2Keenable",
    ])
    expect(screen.getByText("+1 more")).toBeInTheDocument()
    expect(within(search).queryByText("Tavily")).not.toBeInTheDocument()
    expect(stub.requestsTo("/api/v1/projects/p1/routing/order")).toHaveLength(1)
  })

  it("shows the order even if the legacy provider view is unavailable", async () => {
    renderOverview(["project.read", "providers.read"], err(403, null))
    expect(await screen.findByRole("list", { name: "Search order" })).toHaveTextContent("Keenable")
    expect(screen.getByRole("list", { name: "Fetch order" })).toHaveTextContent("Exa")
  })

  it("uses the order to show free calls in the usage summary", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/projects/p1/dashboard") return ok({
        ...DASHBOARD, totals: [{ provider: "keenable", operation: "search", total_units: "2", event_count: 2, unit_kind: "REQUEST" }],
      })
      if (req.url === "/api/v1/projects/p1/routing/order") return ok(ORDER)
      if (req.url === "/api/v1/projects/p1/providers") return ok(providersView())
      if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
      if (req.url === "/api/v1/projects?include_archived=true") return ok([PROJECT])
      if (req.url === "/api/v1/projects/p1/access") return ok({
        project_id: "p1", permissions: ["project.read", "usage.read", "providers.read"], roles: [], policy_revision: 1,
      })
      return err(404, null)
    })
    render(<MemoryRouter><ProjectsProvider accountId="acc"><ProjectScopeProvider accountId="acc" projectId="p1">
      <ProjectOverviewPage />
    </ProjectScopeProvider></ProjectsProvider></MemoryRouter>)
    const summary = await screen.findByRole("region", { name: "Usage summary" })
    expect(await within(summary).findByText("Free")).toBeInTheDocument()
    expect(within(summary).queryByText("Not reported")).not.toBeInTheDocument()
  })

  it("shows the setup checklist while no provider can execute", async () => {
    renderOverview(["project.read", "providers.read", "providers.configure"], ok(providersView([], false)))
    expect(
      await screen.findByRole("heading", { name: "Set up this project" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: "Add provider capacity" })
    ).toHaveAttribute("href", "/p/p1/providers")
    expect(
      screen.getByRole("link", { name: "Turn on search or fetch for a provider" })
    ).toHaveAttribute("href", "/p/p1/providers")
    expect(screen.getByRole("link", { name: "Run a first search" })).toHaveAttribute(
      "href",
      "/p/p1/playground"
    )
  })

  it("hides the setup checklist once a provider can execute", async () => {
    renderOverview(
      ["project.read", "providers.read", "providers.configure"],
      ok(providersView(["search"]))
    )
    await screen.findByRole("heading", { name: "Alpha" })
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(screen.queryByRole("heading", { name: "Set up this project" })).toBeNull()
  })

  it("asks a project admin instead of linking actions without providers.configure", async () => {
    renderOverview(["project.read", "providers.read"], ok(providersView([])))
    expect(
      await screen.findByText("Ask a project admin to set up a provider")
    ).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Add provider capacity" })).toBeNull()
  })
})
