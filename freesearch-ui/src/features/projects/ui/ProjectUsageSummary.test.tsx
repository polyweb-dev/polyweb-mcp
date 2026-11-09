import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { installFetchStub, ok } from "@/test/fetchMock"
import { ProjectUsageSummary } from "./ProjectUsageSummary"

describe("ProjectUsageSummary", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("shows zero dollars before the first call", async () => {
    installFetchStub(() => ok({ project_id: "p", totals: [], recent_usage: [], generated_at: "2026-11-08T12:00:00Z" }))
    render(<ProjectUsageSummary accountId="a" projectId="p" />)
    const card = (await screen.findByText("Provider cost")).closest("div")!
    expect(card).toHaveTextContent("$0.00")
  })

  it.each([
    { kinds: ["USD", "CREDIT"], label: "Known provider cost", amount: "$0.035" },
    { kinds: ["USD"], label: "Provider cost", amount: "$0.035" },
    { kinds: ["CREDIT"], label: "Known provider cost", amount: "\u2014" },
    { kinds: ["FREE"], label: "Provider cost", amount: "Free" },
  ])("shows $label as $amount for $kinds", async ({ kinds, label, amount }) => {
    installFetchStub(() => ok({
      project_id: "p",
      totals: kinds.map((kind) => ({
        provider: kind === "CREDIT" ? "tavily" : "exa", operation: "search",
        total_units: kind === "USD" ? "0.035" : "1", event_count: 1, unit_kind: kind,
      })),
      recent_usage: [], generated_at: "2026-11-08T12:00:00Z",
    }))
    render(<ProjectUsageSummary accountId="a" projectId="p" />)

    const card = (await screen.findByText(label)).closest("div")!
    expect(card).toHaveTextContent(amount)
    expect(card).not.toHaveTextContent("Tavily credit")
  })
})
