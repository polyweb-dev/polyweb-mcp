import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ActivityStream } from "./ActivityStream"

const operationalColumns = ["Time", "Operation", "Provider", "Status", "Latency", "Cost"]

const renderActivity = () =>
  render(
    <FreeSearchProvider>
      <ActivityStream />
    </FreeSearchProvider>
  )

describe("ActivityStream", () => {
  it("renders only the operational telemetry columns", () => {
    renderActivity()

    const table = screen.getByRole("table")
    const headers = screen.getAllByRole("columnheader")
    expect(headers).toHaveLength(operationalColumns.length)
    for (const column of operationalColumns) {
      expect(screen.getByRole("columnheader", { name: new RegExp(`^${column}$`) })).toBeInTheDocument()
    }
    expect(table).toBeInTheDocument()
  })

  it("never renders seeded query or URL targets in the document", () => {
    renderActivity()

    const body = document.body.textContent ?? ""
    expect(body).not.toContain("distributed consensus algorithms")
    expect(body).not.toContain("https://docs.freesearch.dev/getting-started")
    expect(body).not.toContain("http")
  })

  it("does not render a Clear log action", () => {
    renderActivity()

    expect(screen.queryByRole("button", { name: /^Clear log$/ })).not.toBeInTheDocument()
  })
})
