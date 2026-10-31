import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ExpiryChoice } from "../model/expiryChoice"
import { ExpirationRadioGroup } from "./ExpirationRadioGroup"

function renderGroup(choice: ExpiryChoice, handlers: { onChoiceChange?: (c: ExpiryChoice) => void; onCustomDateChange?: (v: string) => void } = {}) {
  return render(
    <ExpirationRadioGroup
      idPrefix="test"
      defaultLabel="90 days (default)"
      choice={choice}
      customDate=""
      disabled={false}
      onChoiceChange={handlers.onChoiceChange ?? (() => {})}
      onCustomDateChange={handlers.onCustomDateChange ?? (() => {})}
    />
  )
}

describe("ExpirationRadioGroup", () => {
  it("names the group Expiration and offers the three choices", () => {
    renderGroup("default")
    const group = screen.getByRole("radiogroup", { name: "Expiration" })
    expect(within(group).getAllByRole("radio").map((radio) => radio.closest("label")?.textContent)).toEqual([
      "90 days (default)",
      "No expiration",
      "Custom date",
    ])
    expect(within(group).getByRole("radio", { name: "90 days (default)" })).toBeChecked()
    expect(screen.queryByLabelText("Expiration date")).toBeNull()
  })

  it("reports a choice change", async () => {
    const onChoiceChange = vi.fn()
    renderGroup("default", { onChoiceChange })
    await userEvent.setup().click(screen.getByRole("radio", { name: "No expiration" }))
    expect(onChoiceChange).toHaveBeenCalledWith("never")
  })

  it("reveals the date input for a custom date, no earlier than today", async () => {
    const onCustomDateChange = vi.fn()
    renderGroup("custom", { onCustomDateChange })
    const date = screen.getByLabelText("Expiration date")
    expect(date).toHaveAttribute("type", "date")
    expect(date.getAttribute("min")).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    await userEvent.setup().type(date, "2099-01-01")
    expect(onCustomDateChange).toHaveBeenCalled()
  })
})
