import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import type { ProjectPool } from "@/domains/projects"
import { ProjectPoolCell } from "./ProjectPoolCell"

const pool: ProjectPool = {
  pool_id: "pool", provider_type: "tinyfish", label: "Alpha - Tinyfish", key_label: "Tinyfish key",
  owner: { user_id: "owner", email: "owner@example.com" }, rate: { limit: 60, window_seconds: 60 },
  budget: { limit: 20, period: "month" }, budget_used: 2, operations: ["search", "fetch"],
}

describe("ProjectPoolCell", () => {
  it("uses the common budget phrase and hides dollar budgets for free providers", () => {
    const { rerender } = render(<ProjectPoolCell pool={pool} />)
    expect(screen.getByText(/\$2.00 of \$20.00 this month/)).toBeInTheDocument()
    rerender(<ProjectPoolCell pool={pool} free />)
    expect(screen.queryByText(/\$/)).toBeNull()
    expect(screen.getByText("60 per minute")).toBeInTheDocument()
  })
})
