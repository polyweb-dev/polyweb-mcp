import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ExpiryChoice } from "../model/expiryChoice"
import { ExpirationField } from "./ExpirationField"

function renderField(
  choice: ExpiryChoice,
  handlers: { onChoiceChange?: (c: ExpiryChoice) => void; onCustomDateChange?: (v: string) => void } = {},
  error: string | null = null
) {
  return render(
    <ExpirationField
      idPrefix="test"
      defaultLabel="90 days"
      defaultHint="The key stops working 90 days after it is issued"
      choice={choice}
      customDate=""
      disabled={false}
      error={error}
      onChoiceChange={handlers.onChoiceChange ?? (() => {})}
      onCustomDateChange={handlers.onCustomDateChange ?? (() => {})}
    />
  )
}

describe("ExpirationField", () => {
  it("names the group Expiration and offers the three choices with one hint", () => {
    renderField("default")
    const group = screen.getByRole("group", { name: "Expiration" })
    expect(within(group).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "90 days",
      "No expiration",
      "Custom date",
    ])
    expect(within(group).getByRole("button", { name: "90 days" })).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByText("The key stops working 90 days after it is issued")).toBeInTheDocument()
    expect(screen.queryByLabelText("Expiration date")).toBeNull()
    expect(screen.queryByRole("radio")).toBeNull()
  })

  it("reports a choice change", async () => {
    const onChoiceChange = vi.fn()
    renderField("default", { onChoiceChange })
    await userEvent.setup().click(screen.getByRole("button", { name: "No expiration" }))
    expect(onChoiceChange).toHaveBeenCalledWith("never")
  })

  it("describes only the selected option", () => {
    renderField("never")
    expect(screen.getByText("The key works until you revoke it")).toBeInTheDocument()
    expect(screen.queryByText("The key stops working 90 days after it is issued")).toBeNull()
  })

  it("uses a text date field with an explicit format for custom expiration", async () => {
    const onCustomDateChange = vi.fn()
    renderField("custom", { onCustomDateChange })
    const date = screen.getByLabelText("Expiration date")
    expect(date).toHaveAttribute("type", "text")
    expect(screen.getByText("Enter YYYY-MM-DD. The key stops working at the end of this day")).toBeInTheDocument()
    await userEvent.setup().type(date, "2099-01-01")
    expect(onCustomDateChange).toHaveBeenCalled()
  })

  it("shows a date error under the date field", () => {
    renderField("custom", {}, "Choose an expiration date in the future")
    const date = screen.getByLabelText("Expiration date")
    expect(date).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByRole("alert")).toHaveTextContent("Choose an expiration date in the future")
    expect(date.getAttribute("aria-describedby")).toContain("test-expiration-date-error")
  })
})
