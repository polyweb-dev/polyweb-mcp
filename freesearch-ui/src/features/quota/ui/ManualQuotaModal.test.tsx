import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { BALANCE_ENTRY_NOTE, SPEND_CAP_NOTE } from "../model/quotaLabels"
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
    expect(screen.getByText("Spend cap — Brave")).not.toBeNull()
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
