import { useState } from "react"
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { PlaygroundController } from "../model/usePlaygroundController"
import { SearchOptions } from "./SearchOptions"

/**
 * TASK-000065 AC#5: the Results input clears and replaces naturally.
 *
 * Real contract under test (SearchOptions.tsx + NumericField type=number):
 * `onChange("")` coerces through `Number("") = 0` and clamps to 1, so the
 * field can never show blank — clearing 6 shows 1, and typing 5 appends to
 * "15" instead of replacing with 5.
 */
function Harness() {
  const [resultCount, setResultCount] = useState(6)
  const controller = {
    setQuery: vi.fn(),
    selectedProviderId: "auto",
    setSelectedProviderId: vi.fn(),
    eligibleProviders: [],
    resultCount,
    setResultCount,
    providersError: false,
    retryProviders: vi.fn(),
  } as unknown as PlaygroundController
  return <SearchOptions controller={controller} />
}

describe("SearchOptions results input (TASK-000065 AC#5)", () => {
  it("clears 6 to blank and replaces it with 5", () => {
    render(<Harness />)
    const input = screen.getByRole("spinbutton", { name: "Number of results" })
    expect(input).toHaveValue(6)
    // Clearing must blank the field instead of coercing to the clamp floor.
    fireEvent.change(input, { target: { value: "" } })
    expect(input).toHaveValue(null)
    // Typing into the blank field must give exactly what was typed.
    fireEvent.change(input, { target: { value: "5" } })
    expect(input).toHaveValue(5)
  })
})
