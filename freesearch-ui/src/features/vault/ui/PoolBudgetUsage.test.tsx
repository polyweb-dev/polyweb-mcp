import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { KeyPool } from "@/domains/vault"
import { PoolBudgetUsage } from "./PoolBudgetUsage"

vi.mock("../model/useFreeProvider", () => ({ useFreeProvider: (provider: string) => provider === "tinyfish" }))

const pool: KeyPool = {
  id: "pool-1", credential_id: "key-1", provider_type: "tavily", project_id: null, label: "Research",
  rate: { limit: null, window_seconds: 60 }, budget: null, budget_used_usd: 0,
  operations: ["search"], operation_limits: null,
}

describe("PoolBudgetUsage", () => {
  it("hides a stored budget on a free provider", () => {
    render(<PoolBudgetUsage pool={{ ...pool, provider_type: "tinyfish", budget: { limit: 20, period: "month" } }} />)
    expect(screen.getByText("Free")).toBeInTheDocument()
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument()
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument()
  })

  it("shows a neutral label when the pool has no cap", () => {
    render(<PoolBudgetUsage pool={pool} />)
    expect(screen.getByText("No budget cap")).toBeInTheDocument()
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument()
  })

  it("clamps usage above the cap and displays the actual amount", () => {
    render(<PoolBudgetUsage pool={{ ...pool, budget: { limit: 10, period: "day" }, budget_used_usd: 12.345678 }} />)
    expect(screen.getByText("$12.35 of $10.00 today")).toBeInTheDocument()
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100")
  })

  it("treats a zero cap as exhausted", () => {
    render(<PoolBudgetUsage pool={{ ...pool, budget: { limit: 0, period: "month" } }} />)
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100")
  })

  it.each([
    [0, 0, "bg-[var(--muted)]"],
    [7.9, 79, "bg-[var(--muted)]"],
    [8, 80, "bg-[var(--status-warning)]"],
    [10, 100, "bg-[var(--status-danger)]"],
  ])("shows used budget %s with the correct fill", (used, percent, color) => {
    render(<PoolBudgetUsage pool={{ ...pool, budget: { limit: 10, period: "month" }, budget_used_usd: used }} />)
    const bar = screen.getByRole("progressbar", { name: "Budget used for Research" })
    expect(bar).toHaveAttribute("aria-valuenow", String(percent))
    expect(bar.firstElementChild).toHaveStyle({ width: `${percent}%` })
    expect(bar.firstElementChild).toHaveClass(color)
  })
})
