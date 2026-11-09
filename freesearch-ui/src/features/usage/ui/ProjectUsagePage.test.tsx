import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { ProjectScopeContext } from "@/domains/projects/state/context"
import { ProjectsContext } from "@/domains/projects/state/context"
import { deferred, err, installFetchStub, ok } from "@/test/fetchMock"
import {
  PROJECT_ALPHA_ID,
  PROJECT_BETA_ID,
  projectScopeValue,
  projectsContextFixture,
} from "@/test/accessFixtures"
import { ProjectUsagePage } from "./ProjectUsagePage"

function usagePayload(projectId: string, provider = "tavily") {
  return {
    project_id: projectId,
    totals: [
      { provider, operation: "search", total_units: "12", event_count: 4, unit_kind: "CREDIT" },
    ],
    recent_usage: [
      {
        provider,
        operation: "search",
        units: "3",
        observed_at: "2026-10-30T10:00:00Z",
        latency_ms: 210,
        status: "success",
        unit_kind: "CREDIT",
      },
    ],
    generated_at: "2026-10-30T10:00:01Z",
  }
}

function page(projectId: string) {
  return (
    <MemoryRouter>
      <ProjectsContext.Provider value={projectsContextFixture()}>
        <ProjectScopeContext.Provider value={projectScopeValue(projectId)}>
          <ProjectUsagePage />
        </ProjectScopeContext.Provider>
      </ProjectsContext.Provider>
    </MemoryRouter>
  )
}

describe("ProjectUsagePage", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("shows this project's totals with each unit kind in its own column", async () => {
    installFetchStub((req) =>
      req.url === `/api/v1/projects/${PROJECT_ALPHA_ID}/usage`
        ? ok(usagePayload(PROJECT_ALPHA_ID))
        : err(404, null)
    )
    render(page(PROJECT_ALPHA_ID))

    expect(screen.getByRole("heading", { name: "Usage" })).toBeInTheDocument()
    expect(screen.getByText("What this project's calls used, per provider")).toBeInTheDocument()
    expect(screen.queryByText(/Provider usage/)).toBeNull()
    const totals = await screen.findByRole("table", { name: "Usage totals" })
    expect(within(totals).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Provider",
      "Operation",
      "Calls",
      "Cost",
      "Provider credits",
    ])
    // Each unit column says what it counts in its header tooltip.
    expect(within(totals).getByRole("columnheader", { name: "Provider credits" })).toHaveAttribute(
      "title",
      "Credits the provider deducted, in its own unit"
    )
    expect(within(totals).getByText("Tavily")).toBeInTheDocument()
    expect(within(totals).getByText("4")).toBeInTheDocument()
    expect(within(totals).getByText("12")).toBeInTheDocument()
    expect(screen.getByText("All time")).toBeInTheDocument()
  })

  it("shows free for zero-priced calls and not reported for unknown prices", async () => {
    const operation = {
      strategy: "lowest_cost", has_saved_custom: false, not_allowed: [],
      providers: [
        { provider: "keenable", name: "Keenable", call_cost_usd: 0, keyless: true },
        { provider: "tavily", name: "Tavily", call_cost_usd: null, keyless: false },
      ],
    }
    installFetchStub((req) => {
      if (req.url.endsWith("/routing/order")) return ok({ revision: 1, search: operation, fetch: operation })
      return ok({
        project_id: PROJECT_ALPHA_ID,
        totals: [
          { provider: "keenable", operation: "search", total_units: 1, event_count: 1, unit_kind: "REQUEST" },
          { provider: "tavily", operation: "search", total_units: 2, event_count: 2, unit_kind: "CREDIT" },
        ],
        recent_usage: [], generated_at: "x",
      })
    })
    render(page(PROJECT_ALPHA_ID))
    const totals = await screen.findByRole("table", { name: "Usage totals" })
    expect(await within(totals).findByText("Free")).toBeInTheDocument()
    const tavily = within(totals).getByText("Tavily").closest("tr")!
    expect(within(tavily).getByText("Not reported")).toBeInTheDocument()
  })

  it("links to Activity from the page header instead of repeating the recent call ledger", async () => {
    installFetchStub(() => ok(usagePayload(PROJECT_ALPHA_ID)))
    render(page(PROJECT_ALPHA_ID))

    await screen.findByRole("table", { name: "Usage totals" })
    const link = screen.getByRole("link", { name: "See every call in Activity" })
    expect(link).toHaveAttribute("href", `/p/${PROJECT_ALPHA_ID}/activity`)
    // A secondary action beside the page title, not a text link in the section.
    expect(link.className).toContain("h-6")
    expect(link.closest("section[aria-labelledby]")).toBeNull()
    expect(screen.queryByRole("table", { name: "Recent usage" })).toBeNull()
    expect(screen.queryByText("210ms")).toBeNull()
  })

  it("adds a total row that sums each unit column on its own", async () => {
    installFetchStub(() =>
      ok({
        project_id: PROJECT_ALPHA_ID,
        totals: [
          { provider: "exa", operation: "search", total_units: "0.035", event_count: 6, unit_kind: "USD" },
          { provider: "brave", operation: "search", total_units: "9", event_count: 9, unit_kind: "REQUEST" },
        ],
        recent_usage: [],
        generated_at: "x",
      })
    )
    render(page(PROJECT_ALPHA_ID))

    const totals = await screen.findByRole("table", { name: "Usage totals" })
    expect(within(totals).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Provider",
      "Operation",
      "Calls",
      "Cost",
    ])
    const totalRow = within(totals).getByText("Total").closest("tr")!
    expect(within(totalRow).queryByText("Known cost")).not.toBeInTheDocument()
    const brave = within(totals).getByText("Brave Search").closest("tr")!
    expect(within(brave).getByText("Not reported")).toHaveClass("text-[var(--muted)]")
    expect(within(totalRow).getByText("15")).toBeInTheDocument()
    expect(within(totalRow).getByText("$0.035")).toBeInTheDocument()
  })

  it("shows the empty state in the totals table", async () => {
    installFetchStub(() =>
      ok({ project_id: PROJECT_ALPHA_ID, totals: [], recent_usage: [], generated_at: "x" })
    )
    render(page(PROJECT_ALPHA_ID))

    expect(await screen.findAllByText("No usage recorded for this project yet")).toHaveLength(1)
  })

  it("aborts the old project's read on a switch and ignores its late result", async () => {
    const alpha = deferred<Response>()
    const stub = installFetchStub((req) =>
      req.url.includes(PROJECT_ALPHA_ID) ? alpha.promise : ok(usagePayload(PROJECT_BETA_ID, "exa"))
    )
    const view = render(page(PROJECT_ALPHA_ID))
    view.rerender(page(PROJECT_BETA_ID))

    expect(stub.requests[0]?.signal?.aborted).toBe(true)
    const totals = await screen.findByRole("table", { name: "Usage totals" })
    expect(within(totals).getByText("Exa")).toBeInTheDocument()

    alpha.resolve(ok(usagePayload(PROJECT_ALPHA_ID)))
    await alpha.promise
    expect(within(totals).queryByText("Tavily")).toBeNull()
  })
})
