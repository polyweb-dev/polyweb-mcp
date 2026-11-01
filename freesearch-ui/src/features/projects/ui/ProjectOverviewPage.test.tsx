import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { ProjectsProvider, ProjectScopeProvider } from "@/domains/projects"
import { ProjectOverviewPage } from "./ProjectOverviewPage"

const PROJECT = { id: "p1", account_id: "a", name: "Alpha", slug: "alpha", status: "active", created_by: "u", created_at: "t", version: 1 }

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

function renderPage(permissions: string[] = ["project.read", "members.read"]) {
  return installFetchStub((req) => {
    if (req.url === "/api/v1/projects/p1/dashboard") return ok(DASHBOARD)
    if (req.url === "/api/v1/system/access") return ok({ rollout_state: "preview", permissions: [] })
    if (req.url === "/api/v1/projects?include_archived=true") return ok([PROJECT])
    if (req.url === "/api/v1/projects/p1/access") {
      return ok({ project_id: "p1", permissions, roles: ["project_member", "routing_editor"], policy_revision: 2 })
    }
    return err(404, null)
  })
}

function renderOverview(permissions?: string[]) {
  const stub = renderPage(permissions)
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

  it("shows the project name, status, and role labels without execution data", async () => {
    renderOverview()
    await screen.findByRole("heading", { name: "Alpha" })
    expect(screen.getByText("Status: Active")).toBeInTheDocument()
    expect(screen.getByText("Project member")).toBeInTheDocument()
    expect(screen.getByText("Routing editor")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Members" })).toBeInTheDocument()
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
    expect(await within(summary).findByText("Search")).toBeInTheDocument()
    expect(within(summary).getByText(/5 events/)).toHaveTextContent(
      "5 events · 2.5 credits · 3 requests"
    )
    expect(within(summary).getByText(/1 event\b/)).toHaveTextContent("1 event · 1 requests")
    expect(stub.requestsTo("/api/v1/projects/p1/dashboard")).toHaveLength(1)
  })

  it("shows no usage summary and reads no dashboard without usage.read", async () => {
    const stub = renderOverview(["project.read"])
    await screen.findByRole("heading", { name: "Alpha" })
    expect(screen.queryByRole("region", { name: "Usage summary" })).toBeNull()
    expect(stub.requestsTo("/api/v1/projects/p1/dashboard")).toHaveLength(0)
  })
})
