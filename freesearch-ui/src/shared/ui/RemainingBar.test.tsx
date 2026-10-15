import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { RemainingBar, remainingColor } from "./RemainingBar"

/**
 * CR1 shared bar: null and non-finite inputs show no bar, finite inputs
 * clamp to 0 through 100, and the clamped value drives width, color, and
 * aria-valuenow. Colors follow the remaining bands with yellow at 75 and
 * 50 and orange at 25.
 */

describe("remainingColor", () => {
  it("uses green above 75 percent", () => {
    expect(remainingColor(100)).toBe("bg-[var(--status-healthy)]")
    expect(remainingColor(75.1)).toBe("bg-[var(--status-healthy)]")
  })

  it("uses yellow from 50 through 75 percent", () => {
    expect(remainingColor(75)).toBe("bg-[var(--status-warning)]")
    expect(remainingColor(50)).toBe("bg-[var(--status-warning)]")
  })

  it("uses orange from 25 up to 50 percent without 50", () => {
    expect(remainingColor(49.9)).toBe("bg-orange-500")
    expect(remainingColor(25)).toBe("bg-orange-500")
  })

  it("uses red below 25 percent", () => {
    expect(remainingColor(24.9)).toBe("bg-[var(--status-danger)]")
    expect(remainingColor(0)).toBe("bg-[var(--status-danger)]")
  })
})

describe("RemainingBar", () => {
  it("shows 100 percent with green and full width", () => {
    render(<RemainingBar percentRemaining={100} label="Keenable credit units remaining" />)
    const bar = screen.getByRole("progressbar", {
      name: "Keenable credit units remaining",
    })
    expect(bar.getAttribute("aria-valuemin")).toBe("0")
    expect(bar.getAttribute("aria-valuemax")).toBe("100")
    expect(bar.getAttribute("aria-valuenow")).toBe("100")
    expect(bar.getAttribute("class")).toContain("w-full")
    const inner = bar.querySelector("div")
    expect(inner?.getAttribute("class")).toContain("bg-[var(--status-healthy)]")
    expect(inner?.getAttribute("style")).toContain("width: 100%")
  })

  it("shows 75 percent with yellow", () => {
    render(<RemainingBar percentRemaining={75} label="Rate bar" />)
    const bar = screen.getByRole("progressbar", { name: "Rate bar" })
    expect(bar.getAttribute("aria-valuenow")).toBe("75")
    expect(bar.querySelector("div")?.getAttribute("class")).toContain(
      "bg-[var(--status-warning)]",
    )
  })

  it("shows 50 percent with yellow", () => {
    render(<RemainingBar percentRemaining={50} label="Rate bar" />)
    const bar = screen.getByRole("progressbar", { name: "Rate bar" })
    expect(bar.getAttribute("aria-valuenow")).toBe("50")
    expect(bar.querySelector("div")?.getAttribute("class")).toContain(
      "bg-[var(--status-warning)]",
    )
  })

  it("shows 25 percent with orange", () => {
    render(<RemainingBar percentRemaining={25} label="Rate bar" />)
    const bar = screen.getByRole("progressbar", { name: "Rate bar" })
    expect(bar.getAttribute("aria-valuenow")).toBe("25")
    expect(bar.querySelector("div")?.getAttribute("class")).toContain("bg-orange-500")
  })

  it("shows zero percent with red and zero width", () => {
    render(<RemainingBar percentRemaining={0} label="Rate bar" />)
    const bar = screen.getByRole("progressbar", { name: "Rate bar" })
    expect(bar.getAttribute("aria-valuenow")).toBe("0")
    expect(bar.querySelector("div")?.getAttribute("class")).toContain(
      "bg-[var(--status-danger)]",
    )
    expect(bar.querySelector("div")?.getAttribute("style")).toContain("width: 0%")
  })

  it("clamps negative input to zero with red", () => {
    render(<RemainingBar percentRemaining={-5} label="Rate bar" />)
    const bar = screen.getByRole("progressbar", { name: "Rate bar" })
    expect(bar.getAttribute("aria-valuenow")).toBe("0")
    expect(bar.querySelector("div")?.getAttribute("class")).toContain(
      "bg-[var(--status-danger)]",
    )
  })

  it("clamps above-100 input to 100 with green", () => {
    render(<RemainingBar percentRemaining={120} label="Rate bar" />)
    const bar = screen.getByRole("progressbar", { name: "Rate bar" })
    expect(bar.getAttribute("aria-valuenow")).toBe("100")
    expect(bar.querySelector("div")?.getAttribute("class")).toContain(
      "bg-[var(--status-healthy)]",
    )
  })

  it("shows no bar for null percentage", () => {
    const { container } = render(
      <RemainingBar percentRemaining={null} label="Rate bar" />,
    )
    expect(container.textContent).toBe("")
    expect(screen.queryByRole("progressbar")).toBeNull()
  })

  it("shows no bar for NaN percentage", () => {
    const { container } = render(
      <RemainingBar percentRemaining={Number.NaN} label="Rate bar" />,
    )
    expect(container.textContent).toBe("")
    expect(screen.queryByRole("progressbar")).toBeNull()
  })

  it("shows no bar for infinite percentage", () => {
    const { container } = render(
      <RemainingBar percentRemaining={Number.POSITIVE_INFINITY} label="Rate bar" />,
    )
    expect(container.textContent).toBe("")
    expect(screen.queryByRole("progressbar")).toBeNull()
  })

  it("preserves the caller label and the optional value text", () => {
    render(
      <RemainingBar
        percentRemaining={24.9}
        label="Keenable search hourly requests remaining"
        valueText="24.9% remaining, 249 requests left"
      />,
    )
    const bar = screen.getByRole("progressbar", {
      name: "Keenable search hourly requests remaining",
    })
    expect(bar.getAttribute("aria-valuetext")).toBe("24.9% remaining, 249 requests left")
    expect(bar.getAttribute("aria-valuenow")).toBe("24.9")
  })
})
