import { expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { ActivityPage } from "./ActivityPage"

vi.mock("@/domains/projects", () => ({ useProjectScope: () => ({ projectId: "p" }) }))
vi.mock("../model/useActivityController", () => ({
  useActivityController: () => ({ listStatus: "ready", summaries: [], selection: null, refresh: vi.fn() }),
  selectedTraceState: () => ({ status: "idle", detail: null, error: null }),
}))

it.each([
  ["/", "Run a search or fetch in the Playground to record one"],
  ["/?operation=search", "Choose All to see every trace"],
])("shows concise empty-state copy at %s", (path, description) => {
  render(<MemoryRouter initialEntries={[path]}><ActivityPage /></MemoryRouter>)
  expect(screen.getByText(description, { exact: true })).toBeInTheDocument()
})
