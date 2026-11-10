import { useState } from "react"
import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import type { PlaygroundController } from "../model/usePlaygroundController"
import { SearchOptions } from "./SearchOptions"

/**
 * TASK-000065 AC#5: the Results input clears and replaces naturally.
 *
 * Contract: the store always keeps a valid clamped value (1..100). Clearing
 * the field shows blank while editing but commits the floor of 1, so a submit
 * with a blank field still sends a sensible limit; losing focus on a blank
 * field reveals the committed value.
 */
function Harness({ onSubmit }: { onSubmit?: (resultCount: number) => void }) {
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
  return (
    <form onSubmit={(event) => { event.preventDefault(); onSubmit?.(resultCount) }}>
      <SearchOptions controller={controller} />
      <button type="submit">Search</button>
    </form>
  )
}

const resultsInput = () => screen.getByRole("spinbutton", { name: "Number of results" })

describe("SearchOptions results input (TASK-000065 AC#5)", () => {
  it("clears 6 to blank and replaces it with 5", () => {
    render(<Harness />)
    expect(resultsInput()).toHaveValue(6)
    fireEvent.change(resultsInput(), { target: { value: "" } })
    expect(resultsInput()).toHaveValue(null)
    fireEvent.change(resultsInput(), { target: { value: "5" } })
    expect(resultsInput()).toHaveValue(5)
  })

  it("reveals the committed floor of 1 when a blank field loses focus", async () => {
    render(<Harness />)
    await userEvent.clear(resultsInput())
    expect(resultsInput()).toHaveValue(null)
    await userEvent.tab()
    expect(resultsInput()).toHaveValue(1)
  })

  it("clamps 0 up to 1 and 101 down to 100", () => {
    render(<Harness />)
    fireEvent.change(resultsInput(), { target: { value: "0" } })
    expect(resultsInput()).toHaveValue(1)
    fireEvent.change(resultsInput(), { target: { value: "101" } })
    expect(resultsInput()).toHaveValue(100)
  })

  it("submits the committed floor of 1 when Enter is pressed on a blank field", async () => {
    const onSubmit = vi.fn()
    render(<Harness onSubmit={onSubmit} />)
    await userEvent.clear(resultsInput())
    await userEvent.keyboard("{Enter}")
    expect(onSubmit).toHaveBeenCalledWith(1)
  })
})
