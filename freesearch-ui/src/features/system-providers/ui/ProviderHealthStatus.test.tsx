import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { formatDateTime } from "@/shared/lib/formatTime"
import { ProviderHealthStatus } from "./ProviderHealthStatus"

const CHECKED = "2026-11-08T09:00:00Z"
const NOW = Date.parse("2026-11-08T11:00:00Z")
const PROPS = { health: "healthy" as const, checkedAt: CHECKED, now: NOW, testing: false, result: undefined }

describe("ProviderHealthStatus", () => {
  it("shows the latest real call age and exact timestamp", () => {
    render(<ProviderHealthStatus {...PROPS} />)
    expect(screen.getByText("Healthy · 2 h ago")).toBeInTheDocument()
    expect(screen.getByTitle(`Last call: ${formatDateTime(CHECKED)}`)).toBeInTheDocument()
  })

  it("shows a degraded call without treating it as a test", () => {
    render(<ProviderHealthStatus {...PROPS} health="degraded" checkedAt="2026-11-08T10:55:00Z" />)
    expect(screen.getByText("Degraded · 5 min ago")).toBeInTheDocument()
  })

  it("uses a newer session test and identifies its source in the tooltip", () => {
    render(<ProviderHealthStatus {...PROPS} result={{ success: false, message: "Connection failed", latencyMs: 1, checkedAt: NOW - 60_000 }} />)
    expect(screen.getByText("Failing · 1 min ago")).toBeInTheDocument()
    expect(screen.getByTitle(/^Last test:.*Connection failed$/)).toBeInTheDocument()
  })

  it("keeps a call newer than the session test", () => {
    render(<ProviderHealthStatus {...PROPS} result={{ success: false, message: "Old failure", latencyMs: 1, checkedAt: NOW - 10_800_000 }} />)
    expect(screen.getByText("Healthy · 2 h ago")).toBeInTheDocument()
  })

  it("shows a dash only when neither source has a result", () => {
    const { rerender } = render(<ProviderHealthStatus {...PROPS} checkedAt={null} />)
    expect(screen.getByText("—")).toBeInTheDocument()
    rerender(<ProviderHealthStatus {...PROPS} checkedAt={null} result={{ success: true, message: "", latencyMs: 1531, checkedAt: NOW }} />)
    expect(screen.getByText("Healthy · just now")).toBeInTheDocument()
    expect(screen.getByTitle(/1,531 ms$/)).toBeInTheDocument()
  })
})
