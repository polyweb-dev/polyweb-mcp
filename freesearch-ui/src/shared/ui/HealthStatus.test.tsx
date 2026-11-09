import { render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { formatDateTime } from "@/shared/lib/formatTime"
import { HealthStatus } from "./HealthStatus"

afterEach(() => vi.restoreAllMocks())

describe("KeyHealthCell.test.tsx", () => {
  it("shows the real call age and exact timestamp when supplied", () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-11-08T11:00:00Z"))
    const checkedAt = "2026-11-08T09:00:00Z"
    render(<HealthStatus health="healthy" checkedAt={checkedAt} />)
    expect(screen.getByText("Healthy · 2 h ago")).toBeInTheDocument()
    expect(screen.getByTitle(`Last call: ${formatDateTime(checkedAt)}`)).toBeInTheDocument()
  })

  it("keeps known health without inventing an age for legacy responses", () => {
    render(<HealthStatus health="healthy" />)
    expect(screen.getByText("Healthy")).toBeInTheDocument()
  })

  it("keeps an unknown result muted even if a timestamp is present", () => {
    render(<HealthStatus health={null} checkedAt="2026-11-08T09:00:00Z" />)
    expect(screen.getByText("Health not known")).toBeInTheDocument()
    expect(screen.queryByText(/ago/)).toBeNull()
  })

  it("shows unchecked project health as a muted dash", () => {
    render(<HealthStatus health={null} />)
    expect(screen.getByText("—")).toBeInTheDocument()
    expect(screen.getByText("Health not known")).toBeInTheDocument()
  })

  it("shows degraded project health with its age", () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-11-08T11:00:00Z"))
    render(<HealthStatus health="degraded" checkedAt="2026-11-08T09:00:00Z" />)
    expect(screen.getByText("Degraded · 2 h ago")).toBeInTheDocument()
  })
})

const CHECKED = "2026-11-08T09:00:00Z"
const NOW = Date.parse("2026-11-08T11:00:00Z")
const PROPS = { health: "healthy" as const, checkedAt: CHECKED, now: NOW, testing: false, result: undefined }

describe("ProviderHealthStatus.test.tsx", () => {
  it("uses a newer session test and identifies its source in the tooltip", () => {
    render(<HealthStatus {...PROPS} result={{ success: false, message: "Connection failed", latencyMs: 1, checkedAt: NOW - 60_000 }} />)
    expect(screen.getByText("Failing · 1 min ago")).toBeInTheDocument()
    expect(screen.getByTitle(/^Last test:.*Connection failed$/)).toBeInTheDocument()
  })

  it("keeps a call newer than the session test", () => {
    render(<HealthStatus {...PROPS} result={{ success: false, message: "Old failure", latencyMs: 1, checkedAt: NOW - 10_800_000 }} />)
    expect(screen.getByText("Healthy · 2 h ago")).toBeInTheDocument()
  })

  it("shows a dash only when neither source has a result", () => {
    const { rerender } = render(<HealthStatus {...PROPS} health={null} checkedAt={null} />)
    expect(screen.getByText("—")).toBeInTheDocument()
    rerender(<HealthStatus {...PROPS} checkedAt={null} result={{ success: true, message: "", latencyMs: 1531, checkedAt: NOW }} />)
    expect(screen.getByText("Healthy · just now")).toBeInTheDocument()
    expect(screen.getByTitle(/1,531 ms$/)).toBeInTheDocument()
  })
})
