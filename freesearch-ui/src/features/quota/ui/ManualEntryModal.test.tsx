import React from "react"
import { describe, it, expect, vi, afterEach } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ManualQuotaModal } from "./ManualQuotaModal"
import { ApiError } from "@/shared/api/http"
import { deferred } from "@/test/fetchMock"

const braveProps = {
  open: true,
  providerId: "brave",
  providerName: "Brave Search",
  unitKind: "USD" as const,
  displayUnit: "USD",
  onClose: () => {},
  onSave: () => Promise.resolve(),
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function fillValidBrave() {
  fireEvent.change(screen.getByLabelText("Billing start"), {
    target: { value: "2026-09-01" },
  })
  fireEvent.change(screen.getByLabelText("Billing end"), {
    target: { value: "2026-09-30" },
  })
  fireEvent.change(screen.getByTestId("manual-quota-allowance"), {
    target: { value: "5.00" },
  })
  fireEvent.change(screen.getByTestId("manual-quota-usage"), {
    target: { value: "0.88" },
  })
}

describe("ManualQuotaModal", () => {
  it.each([
    ["5", "4.9955", "0.0045", "4.9955"],
    ["0.000001", "0", "0.000001", "0.000000"],
  ])("preserves exact USD values on a date-only edit", async (allowance, used, balance, currentUsage) => {
    const onSave = vi.fn(() => Promise.resolve())
    render(<ManualQuotaModal {...braveProps} onSave={onSave}
      defaults={{ billingStart: "2026-09-01", billingEnd: "2026-09-30", allowance, used }} />)
    expect(screen.getByTestId("manual-quota-usage")).toHaveValue(Number(balance))
    fireEvent.change(screen.getByLabelText("Billing end"), { target: { value: "2026-10-01" } })
    await userEvent.click(screen.getByTestId("manual-quota-save"))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      allowance, current_usage: currentUsage,
      billing_end: "2026-10-01",
    }))
  })
  it("selects billing dates from the calendar inside the dialog", async () => {
    const user = userEvent.setup()
    render(<ManualQuotaModal {...braveProps}
      defaults={{ billingStart: "2026-09-01", billingEnd: "2026-09-30", allowance: "5", used: "1" }} />)
    await user.click(screen.getByRole("button", { name: "Choose billing start" }))
    await user.click(screen.getByRole("button", { name: "September 2026 2" }))
    expect(screen.getByLabelText("Billing start")).toHaveValue("2026-09-02")
    expect(screen.getByRole("dialog", { name: "Brave Search balance" })).toBeInTheDocument()
  })

  it("uses USD balance labels for Brave", () => {
    render(<ManualQuotaModal {...braveProps} />)
    expect(screen.getByText("Allowance (USD)")).toBeInTheDocument()
    expect(screen.getByText("Balance remaining (USD)")).toBeInTheDocument()
  })

  it("reuses USD labels for an Exa budget", () => {
    render(
      <ManualQuotaModal
        {...braveProps}
        providerId="exa"
        providerName="Exa"
        unitKind="USD"
        displayUnit="USD"
      />
    )
    expect(screen.getByText("Allowance (USD)")).toBeInTheDocument()
    expect(screen.getByText("Balance remaining (USD)")).toBeInTheDocument()
  })

  it("previews the Brave 0.88/5.00 balance as 17.6% remaining", async () => {
    const user = userEvent.setup()
    render(<ManualQuotaModal {...braveProps} />)
    await user.type(screen.getByTestId("manual-quota-allowance"), "5.00")
    await user.type(screen.getByTestId("manual-quota-usage"), "0.88")
    expect(screen.getByTestId("manual-quota-preview")).toHaveTextContent(
      "17.6% remaining"
    )
  })

  it("previews an Exa USD estimate with the same Decimal-safe math", () => {
    render(
      <ManualQuotaModal
        {...braveProps}
        providerId="exa"
        providerName="Exa"
        unitKind="USD"
        displayUnit="USD"
        defaults={{ billingStart: "2026-09-01", billingEnd: "2026-09-30", allowance: "5.00", used: "3.75" }}
      />
    )
    expect(screen.getByTestId("manual-quota-preview")).toHaveTextContent(
      "25.0% remaining"
    )
  })

  it("blocks save on invalid input without calling onSave", async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(() => Promise.resolve())
    render(<ManualQuotaModal {...braveProps} onSave={onSave} />)
    fillValidBrave()
    fireEvent.change(screen.getByLabelText("Billing end"), {
      target: { value: "2026-09-01" },
    })
    await user.click(screen.getByTestId("manual-quota-save"))
    expect(
      await screen.findByText("Billing end must be after billing start")
    ).toHaveTextContent("Billing end must be after billing start")
    expect(onSave).not.toHaveBeenCalled()
  })

  it("rejects negative and non-decimal amounts", async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(() => Promise.resolve())
    render(<ManualQuotaModal {...braveProps} onSave={onSave} />)
    fireEvent.change(screen.getByLabelText("Billing start"), {
      target: { value: "2026-09-01" },
    })
    fireEvent.change(screen.getByLabelText("Billing end"), {
      target: { value: "2026-09-30" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-allowance"), {
      target: { value: "-2" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-usage"), {
      target: { value: "lots" },
    })
    await user.click(screen.getByTestId("manual-quota-save"))
    expect(screen.getByTestId("manual-quota-allowance")).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByTestId("manual-quota-usage")).toHaveAttribute("aria-invalid", "true")
    expect(onSave).not.toHaveBeenCalled()
  })

  it("disables inputs while saving and closes on success", async () => {
    const user = userEvent.setup()
    const gate = deferred<unknown>()
    const onSave = vi.fn(() => gate.promise)
    const onClose = vi.fn()
    render(<ManualQuotaModal {...braveProps} onSave={onSave} onClose={onClose} />)
    fillValidBrave()
    await user.click(screen.getByTestId("manual-quota-save"))
    await waitFor(() => {
      expect(screen.getByTestId("manual-quota-save")).toHaveTextContent("Saving…")
    })
    expect(screen.getByTestId("manual-quota-allowance")).toBeDisabled()
    expect(screen.getByTestId("manual-quota-cancel")).toBeDisabled()
    expect(onSave).toHaveBeenCalledWith({
      billing_start: "2026-09-01",
      billing_end: "2026-09-30",
      allowance: "5.00",
      current_usage: "4.12",
    })
    gate.resolve(undefined)
    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  it("keeps the modal open and shows the ApiError detail on save failure", async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(() =>
      Promise.reject(new ApiError(422, "body.allowance: must be positive", {}))
    )
    const onClose = vi.fn()
    render(<ManualQuotaModal {...braveProps} onSave={onSave} onClose={onClose} />)
    fillValidBrave()
    await user.click(screen.getByTestId("manual-quota-save"))
    expect(await screen.findByTestId("manual-quota-error")).toHaveTextContent(
      "body.allowance: must be positive"
    )
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByTestId("manual-quota-save")).toHaveTextContent("Save balance")
  })

  it("offers Clear entry when editing and deletes without saving", async () => {
    const user = userEvent.setup()
    const onDelete = vi.fn(() => Promise.resolve())
    const onClose = vi.fn()
    const onSave = vi.fn(() => Promise.resolve())
    render(
      <ManualQuotaModal
        {...braveProps}
        defaults={{ billingStart: "2026-09-01", billingEnd: "2026-09-30", allowance: "5.00", used: "0.88" }}
        onSave={onSave}
        onDelete={onDelete}
        onClose={onClose}
      />
    )
    await user.click(screen.getByTestId("manual-quota-clear"))
    expect(onDelete).not.toHaveBeenCalled()
    const confirm = await screen.findByRole("dialog", { name: "Clear provider balance" })
    await user.click(within(confirm).getByRole("button", { name: "Clear entry" }))
    await waitFor(() => {
      expect(onDelete).toHaveBeenCalledTimes(1)
    })
    expect(onSave).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
