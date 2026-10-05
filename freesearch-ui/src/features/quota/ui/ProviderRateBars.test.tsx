import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import type { RateProgressView } from "@/domains/dashboard"
import { ProviderRateBars } from "./ProviderRateBars"

/**
 * S0 generic rate bars: hour and day only, synthetic providers only, unknown
 * limits stay text-only and never render as a zero bar.
 */

function makeProgress(overrides: Partial<RateProgressView> = {}): RateProgressView {
  return {
    bucket_id: "bucket-synth-1",
    operation: "search",
    window: "1h",
    unit: "requests",
    remaining: "5",
    limit: "10",
    reset_at: null,
    source: "synth-source",
    confidence: "authoritative",
    kind: "rate",
    stale: false,
    enforceable: false,
    ...overrides,
  }
}

describe("ProviderRateBars", () => {
  it("renders hour and day bars and drops second and minute windows", () => {
    const second = {
      ...makeProgress({ bucket_id: "bucket-synth-1s", window: "1h" }),
      window: "1s",
    } as unknown as RateProgressView
    const minute = {
      ...makeProgress({ bucket_id: "bucket-synth-1m", window: "1h" }),
      window: "1m",
    } as unknown as RateProgressView
    render(
      <ProviderRateBars
        providerName="Synth A"
        progress={[
          makeProgress({ bucket_id: "bucket-hour", window: "1h" }),
          makeProgress({
            bucket_id: "bucket-day",
            operation: "fetch",
            window: "1d",
            unit: "urls",
          }),
          second,
          minute,
        ]}
      />,
    )
    expect(screen.getByText("Search hourly rate")).not.toBeNull()
    expect(screen.getByText("Fetch daily rate")).not.toBeNull()
    expect(screen.getAllByRole("progressbar")).toHaveLength(2)
  })

  it("labels request and URL units exactly", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        progress={[
          makeProgress({
            bucket_id: "bucket-hour",
            window: "1h",
            remaining: "5",
            limit: "10",
            unit: "requests",
          }),
          makeProgress({
            bucket_id: "bucket-day",
            operation: "fetch",
            window: "1d",
            remaining: "7",
            limit: "20",
            unit: "urls",
          }),
        ]}
      />,
    )
    expect(screen.getByText("5 of 10 requests")).not.toBeNull()
    expect(screen.getByText("7 of 20 URLs")).not.toBeNull()
  })

  it("shows source confidence text on each bar", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        progress={[makeProgress({ confidence: "authoritative" })]}
      />,
    )
    expect(screen.getByText("authoritative")).not.toBeNull()
  })

  it("shows unknown confidence as plain text", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        progress={[makeProgress({ confidence: "unknown" })]}
      />,
    )
    expect(screen.getByText("unknown")).not.toBeNull()
  })

  it("tags a free daily allowance bar", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        progress={[
          makeProgress({ window: "1d", kind: "free_daily_allowance" }),
        ]}
      />,
    )
    expect(screen.getByText("Free daily allowance")).not.toBeNull()
  })

  it("shows the reset text verbatim", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        progress={[
          makeProgress({ reset_at: "2026-03-01T00:00:00Z" }),
        ]}
      />,
    )
    expect(screen.getByText("Resets 2026-03-01T00:00:00Z")).not.toBeNull()
  })

  it("exposes an accessible progressbar with provider operation window and unit", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        progress={[makeProgress({ remaining: "5", limit: "10" })]}
      />,
    )
    const bar = screen.getByRole("progressbar", {
      name: "Synth A search hourly requests remaining",
    })
    expect(bar.getAttribute("aria-valuenow")).toBe("50")
  })

  it("renders an unknown limit as text only with no bar", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        progress={[makeProgress({ remaining: "7", limit: null })]}
      />,
    )
    expect(screen.getByText("7 left requests")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBe(null)
  })

  it("renders nothing without hour or day progress", () => {
    const { container } = render(
      <ProviderRateBars providerName="Synth A" progress={[]} />,
    )
    expect(container.textContent).toBe("")
  })
})
