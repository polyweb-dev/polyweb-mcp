import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { ProviderCardActions, type ProviderCardActionsProps } from "./ProviderCardActions"

/**
 * Polish locking suite: named card controls with stable test ids and
 * accessible meanings for the two credit controls.
 */

function renderActions(overrides: Partial<ProviderCardActionsProps> = {}) {
  return render(
    <ProviderCardActions
      providerId="brave"
      providerName="Brave"
      manualEligible
      syncing={false}
      expanded={false}
      panelId="brave-detail"
      onSync={() => {}}
      onOpenModal={() => {}}
      onToggleExpanded={() => {}}
      {...overrides}
    />,
  )
}

describe("ProviderCardActions", () => {
  it("names the provider balance control with its exact meaning", () => {
    renderActions()
    const manual = screen.getByRole("button", {
      name: "Provider Balance for Brave. Records the balance the vendor dashboard shows, as an estimate.",
    })
    expect(manual.getAttribute("data-testid")).toBe("manual-quota-open-brave")
    expect(manual).toHaveTextContent("Provider Balance")
  })

  it("names the budget limit control with its exact meaning", () => {
    renderActions()
    const grant = screen.getByRole("button", {
      name: "Budget Limit for Brave. Sets a local credit-unit ceiling that adds no vendor funds.",
    })
    expect(grant.getAttribute("data-testid")).toBe("crd-grant-open-brave")
    expect(grant).toHaveTextContent("Budget Limit")
  })

  it("exposes history and sync controls with stable names", () => {
    renderActions()
    expect(
      screen.getByRole("button", { name: "Balance history for Brave" }).getAttribute("data-testid"),
    ).toBe("limit-history-open-brave")
    expect(screen.getByRole("button", { name: "Refresh limits for Brave" })).not.toBeNull()
  })

  it("hides the manual control when the provider is not eligible", () => {
    renderActions({ manualEligible: false })
    expect(screen.queryByTestId("manual-quota-open-brave")).toBeNull()
    expect(screen.getByTestId("crd-grant-open-brave")).not.toBeNull()
    expect(screen.getByTestId("limit-history-open-brave")).not.toBeNull()
  })

  it("disables sync and shows syncing text while syncing", () => {
    renderActions({ syncing: true })
    const sync = screen.getByRole("button", { name: "Refresh limits for Brave" })
    expect(sync.hasAttribute("disabled")).toBe(true)
    expect(sync.textContent).toBe("Refreshing…")
  })

  it("mounts no detail disclosure; the info popover owns detail (CARD-3)", () => {
    const { rerender } = renderActions()
    expect(screen.queryByRole("button", { name: "Show detail" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Hide detail" })).toBeNull()
    expect(screen.getByTestId("manual-quota-open-brave")).not.toBeNull()
    expect(screen.getByTestId("crd-grant-open-brave")).not.toBeNull()
    expect(screen.getByTestId("limit-history-open-brave")).not.toBeNull()
    expect(screen.getByRole("button", { name: "Refresh limits for Brave" })).not.toBeNull()

    rerender(
      <ProviderCardActions
        providerId="brave"
        providerName="Brave"
        manualEligible
        syncing={false}
        expanded
        panelId="brave-detail"
        onSync={vi.fn()}
        onOpenModal={vi.fn()}
        onToggleExpanded={vi.fn()}
      />,
    )
    expect(screen.queryByRole("button", { name: "Show detail" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Hide detail" })).toBeNull()
    expect(screen.getByTestId("manual-quota-open-brave")).not.toBeNull()
    expect(screen.getByTestId("crd-grant-open-brave")).not.toBeNull()
    expect(screen.getByTestId("limit-history-open-brave")).not.toBeNull()
  })

  it("locks action order Refresh Limits, Provider Balance, Budget Limit, History (CARD-3)", () => {
    renderActions()
    const labels = screen.getAllByRole("button").map((button) => button.textContent)
    expect(labels).toEqual(["Refresh Limits", "Provider Balance", "Budget Limit", "History"])
  })
})
