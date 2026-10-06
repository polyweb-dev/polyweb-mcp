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
  it("names the balance entry control with its exact meaning", () => {
    renderActions()
    const manual = screen.getByRole("button", {
      name: "Balance entry for Brave. Records the balance the vendor dashboard shows, as an estimate.",
    })
    expect(manual.getAttribute("data-testid")).toBe("manual-quota-open-brave")
  })

  it("names the spend cap control with its exact meaning", () => {
    renderActions()
    const grant = screen.getByRole("button", {
      name: "Spend cap for Brave. Sets a local credit-unit ceiling that adds no vendor funds.",
    })
    expect(grant.getAttribute("data-testid")).toBe("crd-grant-open-brave")
  })

  it("exposes history and sync controls with stable names", () => {
    renderActions()
    expect(
      screen.getByRole("button", { name: "Balance history for Brave" }).getAttribute("data-testid"),
    ).toBe("limit-history-open-brave")
    expect(screen.getByRole("button", { name: "Sync limits for Brave" })).not.toBeNull()
  })

  it("hides the manual control when the provider is not eligible", () => {
    renderActions({ manualEligible: false })
    expect(screen.queryByTestId("manual-quota-open-brave")).toBeNull()
    expect(screen.getByTestId("crd-grant-open-brave")).not.toBeNull()
    expect(screen.getByTestId("limit-history-open-brave")).not.toBeNull()
  })

  it("disables sync and shows syncing text while syncing", () => {
    renderActions({ syncing: true })
    const sync = screen.getByRole("button", { name: "Sync limits for Brave" })
    expect(sync.hasAttribute("disabled")).toBe(true)
    expect(sync.textContent).toBe("Syncing…")
  })

  it("toggles the detail disclosure with expanded state and panel control", () => {
    const { rerender } = renderActions()
    const collapsed = screen.getByRole("button", { name: "Show detail" })
    expect(collapsed.getAttribute("aria-expanded")).toBe("false")
    expect(collapsed.getAttribute("aria-controls")).toBe("brave-detail")

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
    const expanded = screen.getByRole("button", { name: "Hide detail" })
    expect(expanded.getAttribute("aria-expanded")).toBe("true")
    expect(expanded.getAttribute("aria-controls")).toBe("brave-detail")
  })
})
