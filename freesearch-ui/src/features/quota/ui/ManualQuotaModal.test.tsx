import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { BALANCE_ENTRY, BALANCE_ENTRY_NOTE, CREDIT_MODE_LABEL, SPEND_CAP_NOTE } from "../model/quotaLabels"
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
    expect(screen.getByText("Allowance (USD)")).toBeInTheDocument()
    expect(screen.getByText("Balance remaining (USD)")).toBeInTheDocument()
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
    expect(screen.getByText("Budget limit for Brave")).toBeInTheDocument()
    expect(screen.getByText("grant-body")).toBeInTheDocument()
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
    expect(screen.getByText(SPEND_CAP_NOTE)).toBeInTheDocument()
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
    expect(screen.getByText(BALANCE_ENTRY_NOTE)).toBeInTheDocument()
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
    expect(CREDIT_MODE_LABEL.paid).toBe("Paid balance")
    expect(CREDIT_MODE_LABEL.both).toBe("Free credits and paid balance")
  })

  it("shows the Credit mode combo first with three tier options in a one-column grid", async () => {
    const user = userEvent.setup()
    renderBalanceEntry()
    const combo = screen.getByRole("combobox", { name: "Balance type" })
    expect(combo).toBeInTheDocument()
    expect(combo.tagName).toBe("BUTTON")
    await user.click(combo)
    const options = (await screen.findAllByRole("option")).map((entry) => entry.textContent)
    expect(options).toEqual(["Free balance", "Paid balance", "Free and paid balances"])
    await user.keyboard("{Escape}")
    const grid = document.querySelector("div.grid-cols-1")
    expect(grid?.className ?? "").toContain("grid-cols-1")
    expect(grid?.className ?? "").not.toContain("sm:grid-cols-2")
    const labels = Array.from(document.querySelectorAll("label")).map((entry) => entry.textContent)
    expect(labels).toEqual([
      "Provider",
      "Balance type",
      "Billing start",
      "Billing end",
      "Allowance (USD)",
      "Balance remaining (USD)",
    ])
  })
})

describe("ManualQuotaModal provider balance title", () => {
  function renderEntry(defaults: { billingStart: string; billingEnd: string; allowance: string; used: string } | null) {
    render(
      <ManualQuotaModal
        open
        providerId="brave"
        providerName="Brave"
        unitKind="USD"
        displayUnit="USD"
        defaults={defaults}
        amountMode="balance"
        onClose={() => {}}
        onSave={() => Promise.resolve({})}
      />,
    )
  }

  it("uses the Provider balance title for a new entry with no provider suffix", () => {
    expect(BALANCE_ENTRY).toBe("Provider balance")
    renderEntry(null)
    const heading = within(screen.getByRole("dialog")).getByRole("heading")
    expect(heading.textContent).toBe("Balance for Brave")
    expect(within(heading).getByTestId("provider-logo-brave")).toBeInTheDocument()
    expect(heading.textContent).not.toContain("—")
  })

  it("uses the Update provider balance title for an existing entry with no provider suffix", () => {
    renderEntry({ billingStart: "2026-09-01", billingEnd: "2026-09-30", allowance: "5.00", used: "0.88" })
    const heading = within(screen.getByRole("dialog")).getByRole("heading")
    expect(heading.textContent).toBe("Balance for Brave")
    expect(within(heading).getByTestId("provider-logo-brave")).toBeInTheDocument()
    expect(heading.textContent).not.toContain("—")
  })
})

describe("ManualQuotaModal provider balance width", () => {
  it("uses the md width class", () => {
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
    const dialog = screen.getByRole("dialog")
    expect(dialog.classList.contains("sm:max-w-md")).toBe(true)
    expect(dialog.classList.contains("sm:max-w-2xl")).toBe(false)
  })
})

describe("ManualQuotaModal provider target", () => {
  it("shows the provider dropdown first with a badge and remounts the form on retarget", async () => {
    const user = userEvent.setup()
    render(
      <ManualQuotaModal
        open
        providerId="brave"
        providerName="Brave"
        unitKind="USD"
        displayUnit="USD"
        defaults={null}
        amountMode="balance"
        providers={[{ id: "brave", name: "Brave" }, { id: "exa", name: "Exa" }] as never}
        observed={{
          brave: { allowance: "5.00", remaining: "4.995" },
          exa: { allowance: "10.00", remaining: "9.00" },
        }}
        onClose={() => {}}
        onSave={() => Promise.resolve({})}
      />,
    )
    const labels = Array.from(document.querySelectorAll("label")).map((entry) => entry.textContent)
    expect(labels[0]).toBe("Provider")
    expect(labels).toEqual([
      "Provider",
      "Balance type",
      "Billing start",
      "Billing end",
      "Allowance (USD)",
      "Balance remaining (USD)",
    ])
    const trigger = screen.getByRole("combobox", { name: "Provider" })
    expect(trigger.getAttribute("data-testid")).toBe("manual-quota-provider")
    expect(trigger.getAttribute("aria-haspopup")).toBe("listbox")
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(screen.queryByRole("option", { name: "Brave" })).toBeNull()
    expect(screen.queryByRole("option", { name: "Exa" })).toBeNull()
    expect(within(trigger as HTMLElement).getByTestId("provider-logo-brave")).toBeInTheDocument()
    expect(screen.getByTestId("manual-quota-allowance")).toHaveValue("5.00")
    expect(screen.getByTestId("manual-quota-usage")).toHaveValue("5.00")
    await user.click(trigger)
    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    const popup = await screen.findByRole("listbox")
    const options = within(popup as HTMLElement).getAllByRole("option")
    expect(options.map((entry) => entry.textContent)).toEqual(["Brave", "Exa"])
    expect(options.map((entry) => entry.getAttribute("aria-selected"))).toEqual(["true", "false"])
    expect(within(options[0] as HTMLElement).getByTestId("provider-logo-brave")).toBeInTheDocument()
    expect(within(options[1] as HTMLElement).getByTestId("provider-logo-exa")).toBeInTheDocument()
    await user.click(screen.getByRole("option", { name: "Exa" }))
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(within(screen.getByRole("heading", { name: "Balance for Exa" })).getByTestId("provider-logo-exa")).toBeInTheDocument()
    expect(screen.getByTestId("manual-quota-allowance")).toHaveValue("10.00")
    expect(screen.getByTestId("manual-quota-usage")).toHaveValue("9.00")
  })

  it("holds the logo inside the trigger with no separate badge beside the combo", () => {
    render(
      <ManualQuotaModal
        open
        providerId="brave"
        providerName="Brave"
        unitKind="USD"
        displayUnit="USD"
        defaults={null}
        amountMode="balance"
        providers={[{ id: "brave", name: "Brave" }, { id: "exa", name: "Exa" }] as never}
        observed={{ brave: { allowance: "5.00", remaining: "4.995" } }}
        onClose={() => {}}
        onSave={() => Promise.resolve({})}
      />,
    )
    const trigger = screen.getByRole("combobox", { name: "Provider" })
    expect(within(trigger as HTMLElement).getByTestId("provider-logo-brave")).toBeInTheDocument()
    expect(trigger.textContent).toContain("Brave")
    const field = trigger.closest("div")
    expect(field?.querySelectorAll('[data-testid^="provider-logo-"]').length).toBe(1)
  })

  it("opens with ArrowDown, moves with arrows, chooses with Enter, closes with Escape", async () => {
    const user = userEvent.setup()
    render(
      <ManualQuotaModal
        open
        providerId="brave"
        providerName="Brave"
        unitKind="USD"
        displayUnit="USD"
        defaults={null}
        amountMode="balance"
        providers={[{ id: "brave", name: "Brave" }, { id: "exa", name: "Exa" }] as never}
        observed={{
          brave: { allowance: "5.00", remaining: "4.995" },
          exa: { allowance: "10.00", remaining: "9.00" },
        }}
        onClose={() => {}}
        onSave={() => Promise.resolve({})}
      />,
    )
    const trigger = screen.getByRole("combobox", { name: "Provider" }) as HTMLElement
    trigger.focus()
    await user.keyboard("{ArrowDown}")
    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    expect(await screen.findByRole("listbox")).toBeInTheDocument()
    expect(trigger.getAttribute("aria-activedescendant")).toContain("-0")
    await user.keyboard("{ArrowDown}")
    expect(trigger.getAttribute("aria-activedescendant")).toContain("-1")
    await user.keyboard("{Escape}")
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(screen.getByTestId("manual-quota-allowance")).toHaveValue("5.00")
    trigger.focus()
    await user.keyboard("{Enter}")
    await user.keyboard("{ArrowDown}")
    await user.keyboard("{Enter}")
    expect(within(screen.getByRole("heading", { name: "Balance for Exa" })).getByTestId("provider-logo-exa")).toBeInTheDocument()
    expect(screen.getByTestId("manual-quota-allowance")).toHaveValue("10.00")
    expect(screen.getByTestId("manual-quota-usage")).toHaveValue("9.00")
  })

  it("closes the open list on a click outside the combo", async () => {
    const user = userEvent.setup()
    render(
      <ManualQuotaModal
        open
        providerId="brave"
        providerName="Brave"
        unitKind="USD"
        displayUnit="USD"
        defaults={null}
        amountMode="balance"
        providers={[{ id: "brave", name: "Brave" }, { id: "exa", name: "Exa" }] as never}
        observed={{ brave: { allowance: "5.00", remaining: "4.995" } }}
        onClose={() => {}}
        onSave={() => Promise.resolve({})}
      />,
    )
    const trigger = screen.getByRole("combobox", { name: "Provider" })
    await user.click(trigger)
    expect(await screen.findByRole("listbox")).toBeInTheDocument()
    await user.click(screen.getByRole("heading", { name: "Balance for Brave" }))
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
  })
})

describe("ManualQuotaModal balance prefill", () => {
  it("prefills a new entry from the observed pool with the estimate note", () => {
    render(
      <ManualQuotaModal
        open
        providerId="brave"
        providerName="Brave"
        unitKind="USD"
        displayUnit="USD"
        defaults={null}
        amountMode="balance"
        observed={{ brave: { allowance: "5.00", remaining: "4.995" } }}
        onClose={() => {}}
        onSave={() => Promise.resolve({})}
      />,
    )
    expect(screen.getByTestId("manual-quota-allowance")).toHaveValue("5.00")
    expect(screen.getByTestId("manual-quota-usage")).toHaveValue("5.00")
    expect(screen.queryByTestId("manual-quota-prefill")).toBeNull()
    expect(screen.getByTestId("manual-quota-preview")).toHaveTextContent("100.0% remaining")
  })

  it("lets a saved entry win over the observed pool with no estimate note", () => {
    render(
      <ManualQuotaModal
        open
        providerId="brave"
        providerName="Brave"
        unitKind="USD"
        displayUnit="USD"
        defaults={{ billingStart: "2026-09-01", billingEnd: "2026-09-30", allowance: "5.00", used: "0.88" }}
        amountMode="balance"
        observed={{ brave: { allowance: "9.99", remaining: "9.00" } }}
        onClose={() => {}}
        onSave={() => Promise.resolve({})}
      />,
    )
    expect(screen.getByTestId("manual-quota-allowance")).toHaveValue("5.00")
    expect(screen.getByTestId("manual-quota-usage")).toHaveValue("4.12")
    expect(screen.queryByTestId("manual-quota-prefill")).toBeNull()
  })
})

describe("ManualQuotaModal target units", () => {
  const providers = [{ id: "tinyfish", name: "Tinyfish" }, { id: "exa", name: "Exa" }] as never
  const providerUnits = {
    tinyfish: { unitKind: "REQUEST", displayUnit: "requests", amountMode: "usage" as const },
    exa: { unitKind: "USD", displayUnit: "USD", amountMode: "balance" as const },
  } as const

  it("uses Exa USD inputs and saves exact native-dollar usage after retargeting", async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(() => Promise.resolve())
    render(
      <ManualQuotaModal
        open
        providerId="tinyfish"
        providerName="Tinyfish"
        unitKind="REQUEST"
        displayUnit="requests"
        defaults={null}
        amountMode="usage"
        providers={providers}
        providerUnits={providerUnits}
        onClose={() => {}}
        onSave={onSave}
      />,
    )

    expect(screen.getByText("Allowance (requests)")).toBeInTheDocument()
    await user.click(screen.getByRole("combobox", { name: "Provider" }))
    await user.click(screen.getByRole("option", { name: "Exa" }))
    expect(screen.getByText("Allowance (USD)")).toBeInTheDocument()
    expect(screen.getByText("Balance remaining (USD)")).toBeInTheDocument()
    expect(screen.getByTestId("manual-quota-allowance")).toHaveValue("")
    expect(screen.getByTestId("manual-quota-usage")).toHaveValue("")

    fireEvent.change(screen.getByLabelText("Billing start"), {
      target: { value: "2026-10-01" },
    })
    fireEvent.change(screen.getByLabelText("Billing end"), {
      target: { value: "2026-10-31" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-allowance"), {
      target: { value: "5.00" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-usage"), {
      target: { value: "4.12" },
    })
    await user.click(screen.getByTestId("manual-quota-save"))
    expect(onSave).toHaveBeenCalledWith(
      {
        billing_start: "2026-10-01",
        billing_end: "2026-10-31",
        allowance: "5.00",
        current_usage: "0.88",
      },
      "exa",
    )
  })

  it("switches Exa back to request usage fields and clears its prior draft", async () => {
    const user = userEvent.setup()
    render(
      <ManualQuotaModal
        open
        providerId="exa"
        providerName="Exa"
        unitKind="USD"
        displayUnit="USD"
        defaults={null}
        amountMode="balance"
        providers={providers}
        providerUnits={providerUnits}
        onClose={() => {}}
        onSave={() => Promise.resolve()}
      />,
    )
    fireEvent.change(screen.getByTestId("manual-quota-allowance"), {
      target: { value: "5.00" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-usage"), {
      target: { value: "4.12" },
    })

    await user.click(screen.getByRole("combobox", { name: "Provider" }))
    await user.click(screen.getByRole("option", { name: "Tinyfish" }))
    expect(screen.getByText("Allowance (requests)")).toBeInTheDocument()
    expect(screen.getByText("Balance remaining (requests)")).toBeInTheDocument()
    expect(screen.getByTestId("manual-quota-allowance")).toHaveValue("")
    expect(screen.getByTestId("manual-quota-usage")).toHaveValue("")
  })

  it("uses Exa USD balance fields when no balance or catalog unit metadata is available", () => {
    render(
      <ManualQuotaModal
        open
        providerId="exa"
        providerName="Exa"
        unitKind={null}
        displayUnit={null}
        onClose={() => {}}
        onSave={() => Promise.resolve()}
      />,
    )
    expect(screen.getByText("Allowance (USD)")).toBeInTheDocument()
    expect(screen.getByText("Balance remaining (USD)")).toBeInTheDocument()
  })
})


describe("balance labels by type", () => {
  it("keeps USD labels for a Brave free balance", async () => {
    render(<ManualQuotaModal open providerId="brave" providerName="Brave" unitKind="USD" displayUnit="USD"
      defaults={null} amountMode="balance" onClose={() => {}} onSave={() => Promise.resolve()} />)
    expect(screen.getByLabelText("Allowance (USD)")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("combobox", { name: "Balance type" }))
    await userEvent.click(screen.getByRole("option", { name: "Free balance" }))
    expect(screen.getByLabelText("Allowance (USD)")).toBeInTheDocument()
    expect(screen.getByLabelText("Balance remaining (USD)")).toBeInTheDocument()
  })
})
