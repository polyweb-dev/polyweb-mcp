import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { LatencyWaterfall } from "./LatencyWaterfall"
import type { LatencyWaterfallRow } from "./LatencyWaterfall"

/**
 * Domain-neutral timing geometry (PLAN §4): clamped percentage placement,
 * multi-segment rows, an accessible list label, narrow-safe wrapping classes,
 * and a reduced-motion transition. No provider or activity vocabulary here.
 */
describe("LatencyWaterfall", () => {
  it("renders one list item per row under the accessible label", () => {
    render(
      <LatencyWaterfall
        rows={[
          { id: "a", label: "Alpha", segments: [{ offsetMs: 0, durationMs: 50, color: "red" }], value: "50ms" },
          { id: "b", label: "Beta", segments: [{ offsetMs: 50, durationMs: 50, color: "blue" }], value: "50ms" },
        ]}
        totalMs={100}
        ariaLabel="Request latency"
      />
    )

    const list = screen.getByRole("list", { name: "Request latency" })
    expect(within(list).getAllByRole("listitem")).toHaveLength(2)
    expect(list).toHaveTextContent("Alpha")
    expect(list).toHaveTextContent("50ms")
  })

  it("announces the millisecond scale to screen readers", () => {
    render(<LatencyWaterfall rows={[]} totalMs={3381} ariaLabel="Latency" />)

    expect(screen.getByText("Timeline scale 0 to 3381 milliseconds")).toBeInTheDocument()
  })

  it("renders an empty state instead of NaN geometry when the total is zero", () => {
    render(
      <LatencyWaterfall
        rows={[
          { id: "a", label: "Alpha", segments: [{ offsetMs: 0, durationMs: 10, color: "red" }], value: "10ms" },
        ]}
        totalMs={0}
        ariaLabel="Latency"
      />
    )

    const track = screen.getByText("Alpha").closest("li")!
    expect(track.querySelectorAll('span[style*="left"]').length).toBe(0)
  })

  it("clamps offsets and durations into the remaining track room", () => {
    render(
      <LatencyWaterfall
        rows={[
          {
            id: "clamped",
            label: "Clamped",
            segments: [{ offsetMs: -20, durationMs: 500, color: "red" }],
            value: "x",
          },
          {
            id: "past-end",
            label: "Past end",
            segments: [{ offsetMs: 200, durationMs: 50, color: "blue" }],
            value: "y",
          },
        ]}
        totalMs={100}
        ariaLabel="Latency"
      />
    )

    const clamped = screen.getByText("Clamped").closest("li")!
    const bar = clamped.querySelector('span[style*="left"]') as HTMLElement
    expect(bar.style.left).toBe("0%")
    expect(parseFloat(bar.style.width.replace("%", ""))).toBeLessThanOrEqual(100)

    const pastEnd = screen.getByText("Past end").closest("li")!
    expect(pastEnd.querySelectorAll('span[style*="left"]').length).toBe(0)
  })

  it("keeps a visible sliver for sub-half-percent durations", () => {
    render(
      <LatencyWaterfall
        rows={[
          { id: "sliver", label: "Sliver", segments: [{ offsetMs: 0, durationMs: 1, color: "red" }], value: "1ms" },
        ]}
        totalMs={3381}
        ariaLabel="Latency"
      />
    )

    const bar = screen
      .getByText("Sliver")
      .closest("li")!
      .querySelector('span[style*="left"]') as HTMLElement
    expect(parseFloat(bar.style.width.replace("%", ""))).toBeGreaterThanOrEqual(0.5)
  })

  it("supports multiple segments in one row", () => {
    render(
      <LatencyWaterfall
        rows={[
          {
            id: "split",
            label: "Split",
            segments: [
              { offsetMs: 0, durationMs: 20, color: "red" },
              { offsetMs: 60, durationMs: 20, color: "red" },
            ],
            value: "40ms",
          },
        ]}
        totalMs={100}
        ariaLabel="Latency"
      />
    )

    const bars = screen
      .getByText("Split")
      .closest("li")!
      .querySelectorAll('span[style*="left"]')
    expect(bars).toHaveLength(2)
  })

  it("drops non-finite and negative segments without crashing", () => {
    render(
      <LatencyWaterfall
        rows={[
          {
            id: "bad",
            label: "Bad",
            segments: [
              { offsetMs: Number.NaN, durationMs: 10, color: "red" },
              { offsetMs: 0, durationMs: -5, color: "blue" },
              { offsetMs: 0, durationMs: 10, color: "green" },
            ],
            value: "10ms",
          },
        ]}
        totalMs={100}
        ariaLabel="Latency"
      />
    )

    const bars = screen
      .getByText("Bad")
      .closest("li")!
      .querySelectorAll('span[style*="left"]')
    expect(bars).toHaveLength(1)
  })

  it("carries narrow-safe and reduced-motion classes", () => {
    const { container } = render(
      <LatencyWaterfall
        rows={[
          { id: "a", label: "Alpha", segments: [{ offsetMs: 0, durationMs: 10, color: "red" }], value: "10ms" },
        ]}
        totalMs={100}
        ariaLabel="Latency"
      />
    )

    expect(container.querySelector(".min-w-0")).not.toBeNull()
    expect(container.querySelector(".motion-reduce\\:transition-none")).not.toBeNull()
  })
})

/**
 * Additive selectable rows for the Activity trajectory (PLAN §6.3 item 9):
 * `selected`/`onSelect` render the row as a keyboard-operable button with
 * `aria-pressed`, while the non-selectable geometry pins stay green.
 */
describe("LatencyWaterfall selectable rows", () => {
  function selectableRow(overrides = {}): LatencyWaterfallRow {
    return {
      id: "selectable",
      label: "Selectable",
      segments: [{ offsetMs: 10, durationMs: 40, color: "red" }],
      value: "40ms",
      selected: false,
      onSelect: () => {},
      ...overrides,
    } as unknown as LatencyWaterfallRow
  }

  it("renders a selectable row as a keyboard-operable button", () => {
    const onSelect = vi.fn()
    render(
      <LatencyWaterfall
        rows={[selectableRow({ onSelect })]}
        totalMs={100}
        ariaLabel="Latency"
      />
    )

    const button = screen.getByRole("button", { name: /selectable.*40ms/i })
    expect(button).toHaveAttribute("aria-pressed", "false")
  })

  it("marks the selected row with aria-pressed and a selected treatment", () => {
    render(
      <LatencyWaterfall
        rows={[selectableRow({ selected: true, onSelect: () => {} })]}
        totalMs={100}
        ariaLabel="Latency"
      />
    )

    const button = screen.getByRole("button", { name: /selectable/i })
    expect(button).toHaveAttribute("aria-pressed", "true")
    expect(button.className + button.innerHTML).toMatch(/selected|accent-cyan|signal/i)
  })

  it("activates selection by click and by keyboard", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(
      <LatencyWaterfall
        rows={[selectableRow({ onSelect })]}
        totalMs={100}
        ariaLabel="Latency"
      />
    )

    const button = screen.getByRole("button", { name: /selectable/i })
    await user.click(button)
    expect(onSelect).toHaveBeenCalledTimes(1)

    button.focus()
    await user.keyboard("{Enter}")
    expect(onSelect).toHaveBeenCalledTimes(2)
  })

  it("keeps non-selectable rows as plain list content", () => {
    render(
      <LatencyWaterfall
        rows={[
          { id: "plain", label: "Plain", segments: [{ offsetMs: 0, durationMs: 10, color: "red" }], value: "10ms" },
        ]}
        totalMs={100}
        ariaLabel="Latency"
      />
    )

    expect(screen.queryByRole("button")).not.toBeInTheDocument()
    expect(screen.getByText("Plain")).toBeInTheDocument()
  })

  it("keeps identical geometry clamps on selectable rows", () => {
    render(
      <LatencyWaterfall
        rows={[selectableRow({ selected: true, onSelect: () => {} })]}
        totalMs={100}
        ariaLabel="Latency"
      />
    )

    const button = screen.getByRole("button", { name: /selectable/i })
    const bar = button.querySelector('span[style*="left"]') as HTMLElement
    expect(bar.style.left).toBe("10%")
    expect(bar.style.width).toBe("40%")
  })
})
