import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { ProjectPool } from "@/domains/projects"
import { ProjectPoolCell } from "./ProjectPoolCell"

vi.mock("@/features/vault/model/useFreeProvider", () => ({ useFreeProvider: (provider: string) => provider === "tinyfish" }))

const pool: ProjectPool = {
  pool_id: "pool", provider_type: "tinyfish", label: "Alpha - Tinyfish", key_label: "Tinyfish key",
  owner: { user_id: "owner" }, rate: { limit: 60, window_seconds: 60 },
  budget: { limit: 20, period: "month" }, budget_used: 2, operations: ["search", "fetch"],
}

describe("ProjectPoolCell", () => {
  it("uses the common budget phrase and hides dollar budgets for free providers", () => {
    const { rerender } = render(<ProjectPoolCell pool={{ ...pool, provider_type: "brave" }} operation="search" />)
    expect(screen.getByText(/\$2.00 of \$20.00 this month/)).toBeInTheDocument()
    rerender(<ProjectPoolCell pool={pool} operation="search" />)
    expect(screen.queryByText(/\$/)).toBeNull()
    expect(screen.getByText("60/min")).toBeInTheDocument()
  })

  it("shows a single-operation restriction only in the other operation", () => {
    const brave = { ...pool, provider_type: "brave", operations: ["search"] as const }
    const searchOnly = { ...brave, operations: [...brave.operations] }
    const { rerender } = render(<ProjectPoolCell pool={searchOnly} operation="search" />)
    expect(screen.getByText("60/min · $2.00 of $20.00 this month")).toBeInTheDocument()
    expect(screen.queryByText(/Search only/)).toBeNull()
    rerender(<ProjectPoolCell pool={searchOnly} operation="fetch" />)
    expect(screen.getByText(/Search only/)).toBeInTheDocument()
  })

  it("shows the effective operation rate and its own window", () => {
    const separate = { ...pool, operation_limits: { search: 10, fetch: { rate_limit: 20, rate_window_seconds: 3600 } } }
    const { rerender } = render(<ProjectPoolCell pool={separate} operation="search" />)
    expect(screen.getByText("10/min")).toBeInTheDocument()
    rerender(<ProjectPoolCell pool={separate} operation="fetch" />)
    expect(screen.getByText("20/h")).toBeInTheDocument()
  })

  it("names the pool supplier with the owner display name only", () => {
    const named = { ...pool, owner: { user_id: "owner", username: "ada", first_name: "Ada", last_name: "Lovelace" } }
    const { container } = render(<ProjectPoolCell pool={named} operation="search" />)
    expect(container.firstChild).toHaveAttribute(
      "title",
      "Pool: Alpha - Tinyfish. Key: Tinyfish key. Supplied by Ada Lovelace"
    )
  })

  it("shows Unknown user, never an email, for a pool owner without a name", () => {
    const stray = { ...pool, owner: { user_id: "owner", email: "owner@example.com" } as ProjectPool["owner"] }
    const { container } = render(<ProjectPoolCell pool={stray} operation="search" />)
    expect(container.firstChild).toHaveAttribute(
      "title",
      "Pool: Alpha - Tinyfish. Key: Tinyfish key. Supplied by Unknown user"
    )
    expect(container.innerHTML).not.toContain("owner@example.com")
  })
})
