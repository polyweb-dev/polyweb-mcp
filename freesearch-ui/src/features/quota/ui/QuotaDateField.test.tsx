import { render, screen, fireEvent } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { QuotaDateField } from "./QuotaDateField"

describe("QuotaDateField", () => {
  it("shows an existing date and converts a typed date to ISO", () => {
    const onChange = vi.fn()
    render(<QuotaDateField id="start" label="Billing start" value="2026-11-01" error={undefined} disabled={false} onChange={onChange} />)
    const field = screen.getByLabelText("Billing start")
    expect(field).toHaveValue("Nov 1, 2026")
    expect(field).toHaveAttribute("type", "text")
    fireEvent.change(field, { target: { value: "Dec 12, 2026" } })
    expect(onChange).toHaveBeenLastCalledWith("2026-12-12")
  })

  it("passes an invalid date through for form validation", () => {
    const onChange = vi.fn()
    render(<QuotaDateField id="end" label="Billing end" value="" error={undefined} disabled={false} onChange={onChange} />)
    fireEvent.change(screen.getByLabelText("Billing end"), { target: { value: "Feb 30, 2026" } })
    expect(onChange).toHaveBeenLastCalledWith("Feb 30, 2026")
  })
})
