import { expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { OverviewRouteOrder } from "./OverviewRouteOrder"

it("shows a load error instead of an empty order", () => {
  render(<MemoryRouter><OverviewRouteOrder projectId="p" canConfigure={false}
    order={{ status: "error", error: new Error("unavailable") }} /></MemoryRouter>)
  expect(screen.getByRole("alert")).toHaveTextContent("The provider order did not load")
  expect(screen.queryByText("No providers")).not.toBeInTheDocument()
})

it("shows empty search and fetch orders separately", () => {
  const empty = { strategy: "lowest_cost" as const, providers: [], hasSavedCustom: false, notAllowed: [] }
  render(<MemoryRouter><OverviewRouteOrder projectId="p" canConfigure
    order={{ status: "ready", data: { revision: 1, search: empty, fetch: empty } }} /></MemoryRouter>)
  expect(screen.getByRole("heading", { name: "Search order" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "Fetch order" })).toBeInTheDocument()
  expect(screen.getAllByText("No providers")).toHaveLength(2)
})

it("links each remaining provider count to its operation", () => {
  const operation = { strategy: "lowest_cost" as const, hasSavedCustom: false, notAllowed: [],
    providers: ["brave", "exa", "tavily", "keenable"].map((provider) => ({ provider, name: provider, keyless: false, callCostUsd: null })) }
  render(<MemoryRouter><OverviewRouteOrder projectId="p" canConfigure
    order={{ status: "ready", data: { revision: 1, search: operation, fetch: operation } }} /></MemoryRouter>)
  expect(screen.getByRole("link", { name: "View search order" })).toHaveAttribute("href", "/p/p/providers?operation=search")
  expect(screen.getByRole("link", { name: "View fetch order" })).toHaveAttribute("href", "/p/p/providers?operation=fetch")
})
