import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { mapTraceDetail } from "@/domains/activity"
import { traceDetailFixture } from "@/test/fixtures/activity"
import { TraceDetailSummary } from "./TraceDetailSummary"

/**
 * TASK-000063 summary-rail attribution: the detail rail carries its own
 * Initiated by cell, so the dialog attribution is covered even when the
 * dialog test targets another scenario.
 */
describe("TraceDetailSummary actor identity", () => {
  function railValues(rail: HTMLElement): (string | null)[] {
    return Array.from(rail.querySelectorAll(":scope > div dd")).map((value) => value.textContent)
  }

  it("renders the attribution rail cell with the display name only, beside the provider", () => {
    const trace = mapTraceDetail(
      traceDetailFixture({
        actor_type: "human",
        first_name: "Ada",
        last_name: "Lovelace",
        username: "ada",
        // An older backend may still send an email; it must never be rendered.
        email: "ada@example.com",
      })
    )
    const { container } = render(<TraceDetailSummary trace={trace} attempt={null} />)

    const rail = screen.getByText("Initiated by").closest("dl")!
    expect(
      Array.from(rail.querySelectorAll(":scope > div dt")).map((term) => term.textContent)
    ).toEqual(["Status", "Provider", "Initiated by", "Total latency", "Results"])
    expect(screen.getByText("Ada Lovelace")).toHaveAttribute("title", "Ada Lovelace")
    expect(railValues(rail)[2]).toBe("Ada Lovelace")
    expect(container.innerHTML).not.toContain("ada@example.com")
    expect(screen.getByText("Keenable")).toBeInTheDocument()
  })

  it("shows the username, else Unknown user, and never an email", () => {
    const named = mapTraceDetail(
      traceDetailFixture({ actor_type: "human", username: "ada", email: "ada@example.com" })
    )
    const { container, unmount } = render(<TraceDetailSummary trace={named} attempt={null} />)
    expect(railValues(screen.getByText("Initiated by").closest("dl")!)[2]).toBe("ada")
    expect(container.innerHTML).not.toContain("ada@example.com")
    unmount()

    const unnamed = mapTraceDetail(
      traceDetailFixture({ actor_type: "human", email: "ghost@example.com" })
    )
    const second = render(<TraceDetailSummary trace={unnamed} attempt={null} />)
    expect(railValues(screen.getByText("Initiated by").closest("dl")!)[2]).toBe("Unknown user")
    expect(second.container.innerHTML).not.toContain("ghost@example.com")
  })

  it("shows the API key name with `API key · prefix` beneath it", () => {
    const trace = mapTraceDetail(
      traceDetailFixture({
        actor_type: "project_api_key",
        api_key_name: "test-key",
        api_key_prefix: "pw_live_ab12",
        username: "ada",
        first_name: "Ada",
        last_name: "Lovelace",
        email: "ada@example.com",
      })
    )
    render(<TraceDetailSummary trace={trace} attempt={null} />)

    const rail = screen.getByText("Initiated by").closest("dl")!
    expect(railValues(rail)[2]).toBe("test-keyAPI key · pw_live_ab12")
    expect(screen.getByText("test-key")).toBeInTheDocument()
    expect(screen.getByText("pw_live_ab12")).toHaveClass("font-mono")
    expect(rail?.textContent).not.toContain("Ada Lovelace")
    expect(rail?.textContent).not.toContain("ada@example.com")
  })

  it("falls back to the plain API key label when the key name is null", () => {
    const trace = mapTraceDetail(
      traceDetailFixture({
        actor_type: "project_api_key",
        api_key_name: null,
        api_key_prefix: null,
      })
    )
    render(<TraceDetailSummary trace={trace} attempt={null} />)

    const rail = screen.getByText("Initiated by").closest("dl")!
    expect(railValues(rail)[2]).toBe("API key")
  })

  it("keeps legacy missing payload rows quiet without naming a project", () => {
    const trace = mapTraceDetail(traceDetailFixture())
    render(<TraceDetailSummary trace={trace} attempt={null} />)

    const rail = screen.getByText("Initiated by").closest("dl")!
    expect(rail).toHaveTextContent("—")
    expect(rail?.textContent).not.toContain("Alpha")
  })
})

describe("TraceDetailSummary total latency of an inconsistent root", () => {
  it("shows the span envelope, not 0 ms, when the root duration is smaller than its children", () => {
    const at = (seconds: string) => `2026-10-01T10:00:${seconds}Z`
    const span = (id: string, parent: string | null, name: string, start: string, end: string, ms: number) => ({
      span_id: id.padEnd(16, "0"),
      parent_span_id: parent === null ? null : parent.padEnd(16, "0"),
      name,
      stage: name,
      kind: "internal",
      started_at: at(start),
      ended_at: at(end),
      duration_ms: ms,
      outcome: "success",
      error: null,
      events: [],
    })
    const trace = mapTraceDetail(
      traceDetailFixture({
        operation: "fetch",
        started_at: at("20.568000"),
        duration_ms: 0,
        spans: [
          span("aa", null, "POST /fetch", "20.568000", "19.352000", 0),
          span("bb", "aa", "polyweb.route", "18.888000", "18.922000", 34),
          span("cc", "aa", "polyweb.provider", "18.923000", "19.318000", 394),
          span("ee", "aa", "polyweb.response", "19.352000", "19.352000", 1),
        ],
      })
    )
    render(<TraceDetailSummary trace={trace} attempt={null} />)

    const cell = screen.getByText("Total latency").closest("div")!
    expect(cell).toHaveTextContent("464 ms")
    expect(cell).not.toHaveTextContent(/^Total latency0 ms$/)
  })
})
