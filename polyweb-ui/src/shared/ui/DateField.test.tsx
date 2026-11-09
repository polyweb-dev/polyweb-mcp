import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { describe, expect, it } from "vitest"
import { DateField } from "./DateField"

function Example() {
  const [date, setDate] = useState("2026-11-01")
  return <DateField id="date" label="Billing start" value={date} onChange={setDate} />
}

describe("DateField", () => {
  it("selects a date in another month and returns an ISO date", async () => {
    const user = userEvent.setup()
    render(<Example />)
    await user.click(screen.getByRole("button", { name: "Choose billing start" }))
    await user.click(screen.getByRole("button", { name: "Next month" }))
    await user.click(screen.getByRole("button", { name: "December 2026 12" }))
    expect(screen.getByLabelText("Billing start")).toHaveValue("2026-12-12")
    expect(screen.queryByRole("button", { name: "Next month" })).toBeNull()
  })
})
