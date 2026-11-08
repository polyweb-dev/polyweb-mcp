import { render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { formatDateTime } from "@/shared/lib/formatTime"
import { KeyHealthCell } from "./KeyHealthCell"

afterEach(() => vi.restoreAllMocks())

describe("KeyHealthCell", () => {
  it("shows the real call age and exact timestamp when supplied", () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-11-08T11:00:00Z"))
    const checkedAt = "2026-11-08T09:00:00Z"
    render(<KeyHealthCell health="healthy" checkedAt={checkedAt} />)
    expect(screen.getByText("Healthy · 2 h ago")).toBeInTheDocument()
    expect(screen.getByTitle(formatDateTime(checkedAt))).toBeInTheDocument()
  })

  it("keeps known health without inventing an age for legacy responses", () => {
    render(<KeyHealthCell health="healthy" />)
    expect(screen.getByText("Healthy")).toBeInTheDocument()
  })

  it("keeps an unknown result muted even if a timestamp is present", () => {
    render(<KeyHealthCell health="unknown" checkedAt="2026-11-08T09:00:00Z" />)
    expect(screen.getByText("Health not known")).toBeInTheDocument()
    expect(screen.queryByText(/ago/)).toBeNull()
  })

  it("shows unchecked project health as a muted dash", () => {
    render(<KeyHealthCell project health={null} />)
    expect(screen.getByText("—")).toBeInTheDocument()
    expect(screen.getByText("Health not known")).toBeInTheDocument()
  })

  it("shows degraded project health as an error with its age", () => {
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-11-08T11:00:00Z"))
    render(<KeyHealthCell project health="degraded" checkedAt="2026-11-08T09:00:00Z" />)
    expect(screen.getByText("Error · 2 h ago")).toBeInTheDocument()
  })
})
