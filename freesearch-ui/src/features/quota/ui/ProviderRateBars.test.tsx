import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import type { RateProgressView } from "@/domains/dashboard"
import { formatDateTime } from "@/shared/lib/formatTime"
import { ProviderRateBars } from "./ProviderRateBars"

/**
 * UI7 rate bars: hour and day only, fetch rows gated by fetchAvailable,
 * unknown limits stay text-only and never render as a zero bar.
 * Replaces the pre-UI7 fetch expectations per UI7-04.
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
        fetchAvailable
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
    expect(screen.getByText("Search")).not.toBeNull()
    expect(screen.getByText("Fetch")).not.toBeNull()
    expect(screen.getAllByRole("progressbar")).toHaveLength(2)
  })

  it("labels request and URL units exactly", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
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
    expect(screen.getByText("5 of 10 requests left this hour")).not.toBeNull()
    expect(screen.getByText("7 of 20 URLs left today")).not.toBeNull()
  })

  it("shows_integer_request_and_url_counts", () => {
    const { unmount: unmountTinyfish } = render(
      <ProviderRateBars
        providerName="Tinyfish"
        fetchAvailable
        progress={[
          makeProgress({
            bucket_id: "tinyfish-fetch-daily",
            operation: "fetch",
            window: "1d",
            unit: "urls",
            remaining: "1000.000000000",
            limit: "1000.000000000",
          }),
          makeProgress({
            bucket_id: "tinyfish-search-hourly",
            operation: "search",
            window: "1h",
            unit: "requests",
            remaining: "498.000000000",
            limit: "500",
          }),
        ]}
      />,
    )
    expect(screen.getByText("1,000 of 1,000 URLs left today")).not.toBeNull()
    expect(screen.getByText("498 of 500 requests left this hour")).not.toBeNull()
    expect(screen.queryByText("1000.000000000 of 1000.000000000 URLs")).toBeNull()
    expect(screen.queryByText("498.000000000 of 500 requests")).toBeNull()
    expect(
      screen
        .getByRole("progressbar", { name: "Tinyfish fetch daily URLs remaining" })
        .getAttribute("aria-valuenow"),
    ).toBe("100")
    expect(
      screen
        .getByRole("progressbar", { name: "Tinyfish search hourly requests remaining" })
        .getAttribute("aria-valuenow"),
    ).toBe("99.6")
    unmountTinyfish()

    const { unmount: unmountNull } = render(
      <ProviderRateBars
        providerName="Synth B"
        fetchAvailable
        progress={[makeProgress({ bucket_id: "synth-null", remaining: "7", limit: null })]}
      />,
    )
    expect(screen.getByText("Limit not reported")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBe(null)
    unmountNull()

    const { unmount: unmountZero } = render(
      <ProviderRateBars
        providerName="Synth C"
        fetchAvailable
        progress={[makeProgress({ bucket_id: "synth-zero", remaining: "5", limit: "0" })]}
      />,
    )
    expect(screen.getByText("Limit not reported")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBe(null)
    unmountZero()
  })

  it("hides fetch rate rows without fetch support (UI7-04)", () => {
    const { container } = render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable={false}
        progress={[
          makeProgress({
            bucket_id: "bucket-day",
            operation: "fetch",
            window: "1d",
            unit: "urls",
          }),
        ]}
      />,
    )
    expect(container.textContent).toBe("")
    expect(screen.queryByText("Fetch daily rate")).toBe(null)
  })

  it("states an estimated confidence in sentence case and no raw enum for a reported one", () => {
    const { unmount } = render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        progress={[makeProgress({ confidence: "estimated" })]}
      />,
    )
    expect(screen.getByText("Estimated")).not.toBeNull()
    unmount()
    render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        progress={[makeProgress({ confidence: "authoritative" })]}
      />,
    )
    expect(screen.queryByText("authoritative")).toBeNull()
  })

  it("shows no note for an unknown confidence", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        progress={[makeProgress({ confidence: "unknown" })]}
      />,
    )
    expect(screen.queryByText("unknown")).toBeNull()
  })

  it("colors a full hourly bar green through the shared bar", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        progress={[makeProgress({ remaining: "10", limit: "10" })]}
      />,
    )
    const bar = screen.getByRole("progressbar", { name: "Synth A search hourly requests remaining" })
    expect(bar.querySelector("div")?.getAttribute("class")).toContain("bg-[var(--status-healthy)]")
    expect(bar.querySelector("div")?.getAttribute("class")).not.toContain("bg-[var(--status-warning)]")
  })

  it("tags a free daily allowance bar", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        progress={[
          makeProgress({ window: "1d", kind: "free_daily_allowance" }),
        ]}
      />,
    )
    expect(screen.getByText("Free daily allowance")).not.toBeNull()
  })

  it("shows the reset time in reader-locale text (polish Item 2)", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        progress={[
          makeProgress({ reset_at: "2026-03-01T00:00:00Z" }),
        ]}
      />,
    )
    const expected = "Resets " + formatDateTime("2026-03-01T00:00:00Z")
    expect(screen.getByText(expected)).not.toBeNull()
    expect(screen.queryByText("Resets 2026-03-01T00:00:00Z")).toBeNull()
  })

  it("exposes an accessible progressbar with provider operation window and unit", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        progress={[makeProgress({ remaining: "5", limit: "10" })]}
      />,
    )
    const bar = screen.getByRole("progressbar", {
      name: "Synth A search hourly requests remaining",
    })
    expect(bar.getAttribute("aria-valuenow")).toBe("50")
    expect(bar.getAttribute("aria-valuemin")).toBe("0")
    expect(bar.getAttribute("aria-valuemax")).toBe("100")
  })

  it("renders an unknown limit as text only with no bar", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        progress={[makeProgress({ remaining: "7", limit: null })]}
      />,
    )
    expect(screen.getByText("Limit not reported")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBe(null)
  })

  it("renders nothing without hour or day progress", () => {
    const { container } = render(
      <ProviderRateBars providerName="Synth A" fetchAvailable progress={[]} />,
    )
    expect(container.textContent).toBe("")
  })
})

describe("ProviderRateBars shared bar", () => {
  it("floors decimal request counts through the shared bar with green", () => {
    render(
      <ProviderRateBars
        providerName="Keenable"
        fetchAvailable
        useSharedBar
        progress={[
          makeProgress({
            bucket_id: "keenable:keyless:requests",
            operation: "search",
            window: "1h",
            unit: "requests",
            remaining: "990.00000000",
            limit: "1000",
            confidence: "observed",
          }),
        ]}
      />,
    )
    // The shared bar holds the title only; the counts sit in the hover popover.
    expect(screen.getByText("990 of 1,000 requests left this hour")).not.toBeNull()
    expect(screen.queryByText("990.00000000")).toBeNull()
    const bar = screen.getByRole("progressbar", {
      name: "Keenable search hourly requests remaining",
    })
    expect(bar.getAttribute("aria-valuenow")).toBe("99")
    expect(bar.querySelector("div")?.getAttribute("class")).toContain(
      "bg-[var(--status-healthy)]",
    )
  })

  it("keeps URL units verbatim on the shared bar path", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        useSharedBar
        progress={[
          makeProgress({
            bucket_id: "bucket-url",
            operation: "fetch",
            window: "1d",
            unit: "urls",
            remaining: "7.5",
            limit: "20",
          }),
        ]}
      />,
    )
    expect(screen.getByText("7.5 of 20 URLs left today")).not.toBeNull()
  })

  it("shows limit-only text without a fabricated remaining amount", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        useSharedBar
        progress={[makeProgress({ remaining: null, limit: "10" })]}
      />,
    )
    // An unknown remaining draws no bar and no hover counts, so the row holds the title only.
    expect(screen.getByText("Search")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBeNull()
    expect(screen.queryByText("0 of 10 requests")).toBeNull()
  })

  it("shows remaining-only text without a fabricated limit amount", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        useSharedBar
        progress={[makeProgress({ remaining: "7", limit: null })]}
      />,
    )
    // An unknown limit draws no bar and no hover counts, so the row holds the title only.
    expect(screen.getByText("Search")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBeNull()
  })

  it("shows zero limit text with no bar and no invented capacity", () => {
    render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        useSharedBar
        progress={[makeProgress({ remaining: "0", limit: "0" })]}
      />,
    )
    // A zero limit draws no bar and no hover counts, so the row holds the title only.
    expect(screen.getByText("Search")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBeNull()
  })

  it("drops a row with invalid amounts instead of a fabricated zero", () => {
    const { container } = render(
      <ProviderRateBars
        providerName="Synth A"
        fetchAvailable
        useSharedBar
        progress={[makeProgress({ remaining: "lots", limit: "lots" })]}
      />,
    )
    expect(container.textContent).toContain("Limit not reported")
    expect(screen.queryByRole("progressbar")).toBeNull()
  })

  it("keeps reset notes after authoritative suppression", () => {
    render(
      <ProviderRateBars
        providerName="Keenable"
        fetchAvailable
        useSharedBar
        hideAuthoritative
        progress={[
          makeProgress({
            bucket_id: "keenable:keyless:requests",
            remaining: "990",
            limit: "1000",
            confidence: "authoritative",
            reset_at: "2026-03-01T00:00:00Z",
          }),
        ]}
      />,
    )
    expect(screen.queryByText("authoritative")).toBeNull()
    expect(screen.getByText(/Resets /)).not.toBeNull()
  })

  it("preserves observed confidence on the shared bar path", () => {
    render(
      <ProviderRateBars
        providerName="Keenable"
        fetchAvailable
        useSharedBar
        progress={[
          makeProgress({
            bucket_id: "keenable:keyless:requests",
            confidence: "observed",
          }),
        ]}
      />,
    )
    expect(screen.getByText("Observed")).not.toBeNull()
  })
})
