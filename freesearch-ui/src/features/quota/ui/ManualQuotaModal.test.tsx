import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { BALANCE_ENTRY_NOTE, CREDIT_MODE_LABEL, SPEND_CAP_NOTE } from "../model/quotaLabels"
import { ManualQuotaModal } from "./ManualQuotaModal"

/**
 * UI7 modal reuse: manual USD balance entry and the grant shell share one
 * modal composition. Covers UI7-07 and UI7-08.
 */

describe("ManualQuotaModal", () => {
  it("shows USD balance labels in balance mode (UI7-07)", () => {
    render(
      <ManualQuotaModal
        open
        providerId="brave"
        providerName="Brave"
        unitKind="USD"
        displayUnit="USD"
        defaults={null}
        amountMode="balance"
        onClose={() => {}}
        onSave={() => Promise.resolve({})}
      />,
    )
    expect(screen.getByText("Allowance (USD)")).not.toBeNull()
    expect(screen.getByText("Balance remaining (USD)")).not.toBeNull()
  })

  it("reuses the shell for the grant form with a provider title (UI7-08)", () => {
    render(
      <ManualQuotaModal
        mode="grant"
        open
        providerId="brave"
        providerName="Brave"
        onClose={() => {}}
      >
        <p>grant-body</p>
      </ManualQuotaModal>,
    )
    expect(screen.getByText("Budget Limit — Brave")).not.toBeNull()
    expect(screen.getByText("grant-body")).not.toBeNull()
    void vi
  })
})

describe("ManualQuotaModal polish subtitles", () => {
  it("shows the spend cap note in grant shell mode", () => {
    render(
      <ManualQuotaModal
        mode="grant"
        open
        providerId="brave"
        providerName="Brave"
        onClose={() => {}}
      >
        <p>grant-body</p>
      </ManualQuotaModal>,
    )
    expect(screen.getByText(SPEND_CAP_NOTE)).not.toBeNull()
  })

  it("shows the balance entry note in balance mode", () => {
    render(
      <ManualQuotaModal
        open
        providerId="brave"
        providerName="Brave"
        unitKind="USD"
        displayUnit="USD"
        defaults={null}
        amountMode="balance"
        onClose={() => {}}
        onSave={() => Promise.resolve({})}
      />,
    )
    expect(screen.getByText(BALANCE_ENTRY_NOTE)).not.toBeNull()
  })
})

describe("ManualQuotaModal credit mode fields (CARD-4)", () => {
  function renderBalanceEntry() {
    render(
      <ManualQuotaModal
        open
        providerId="brave"
        providerName="Brave"
        unitKind="USD"
        displayUnit="USD"
        defaults={null}
        amountMode="balance"
        onClose={() => {}}
        onSave={() => Promise.resolve({})}
      />,
    )
  }

  it("keeps the credit-tier words exact for the combo and the popover note", () => {
    expect(CREDIT_MODE_LABEL.free).toBe("Free credits")
    expect(CREDIT_MODE_LABEL.paid).toBe("Paid credits")
    expect(CREDIT_MODE_LABEL.both).toBe("Free + Paid")
  })

  it("shows the Credit mode combo first with three tier options in a one-column grid", () => {
    renderBalanceEntry()
    const combo = screen.getByRole("combobox", { name: "Credit mode" })
    expect(combo).not.toBeNull()
    const options = within(combo as HTMLElement).getAllByRole("option").map((entry) => entry.textContent)
    expect(options).toEqual(["Free credits", "Paid credits", "Free + Paid"])
    const grid = document.querySelector("div.grid-cols-1")
    expect(grid?.className ?? "").toContain("grid-cols-1")
    expect(grid?.className ?? "").not.toContain("sm:grid-cols-2")
    const labels = Array.from(document.querySelectorAll("label")).map((entry) => entry.textContent)
    expect(labels).toEqual([
      "Credit mode",
      "Billing start",
      "Billing end",
      "Allowance (USD)",
      "Balance remaining (USD)",
    ])
  })
})
