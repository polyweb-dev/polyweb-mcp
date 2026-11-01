import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
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
    <ProjectsContext.Provider value={projectsContextFixture()}>
      <ProjectScopeContext.Provider value={projectScopeValue(projectId)}>
        <ProjectUsagePage />
      </ProjectScopeContext.Provider>
    </ProjectsContext.Provider>
  )
}

describe("ProjectUsagePage", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("shows this project's totals and recent ledger only", async () => {
    installFetchStub((req) =>
      req.url === `/api/v1/projects/${PROJECT_ALPHA_ID}/usage`
        ? ok(usagePayload(PROJECT_ALPHA_ID))
        : err(404, null)
    )
    render(page(PROJECT_ALPHA_ID))

    expect(screen.getByRole("heading", { name: "Usage" })).toBeInTheDocument()
    expect(screen.getByText(/This project's usage only\./)).toBeInTheDocument()
    const totals = await screen.findByRole("table", { name: "Usage totals" })
    expect(within(totals).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Provider",
      "Operation",
      "Units",
      "Events",
    ])
    expect(within(totals).getByText("Tavily")).toBeInTheDocument()
    expect(within(totals).getByText("12 credits")).toBeInTheDocument()
    const recent = screen.getByRole("table", { name: "Recent usage" })
    expect(within(recent).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Time",
      "Provider",
      "Operation",
      "Units",
      "Status",
      "Latency",
    ])
    expect(within(recent).getByText("210 ms")).toBeInTheDocument()
    expect(within(recent).getByText("Success")).toBeInTheDocument()
  })

  it("shows the empty state in both tables", async () => {
    installFetchStub(() =>
      ok({ project_id: PROJECT_ALPHA_ID, totals: [], recent_usage: [], generated_at: "x" })
    )
    render(page(PROJECT_ALPHA_ID))

    expect(await screen.findAllByText("No usage recorded for this project yet.")).toHaveLength(2)
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
