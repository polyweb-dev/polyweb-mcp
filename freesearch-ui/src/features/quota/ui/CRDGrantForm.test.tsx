import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { SPEND_CAP_NOTE } from "../model/quotaLabels"
import { CRDGrantForm } from "./CRDGrantForm"

/**
 * UI7 grant form: search-only for Brave, one-digit rule on changed input,
 * stored fetch preserved when the input stays absent, modal closes only
 * on successful save. Covers UI7-08 and the 4.5 vs 4.500 precision rule.
 */

function grants() {
  return {
    provider: "brave",
    auth_mode: "keyed",
    period_start: "2026-09-01",
    period_end: "2026-09-30",
    version: 3,
    search_granted_crd: "4.500",
    search_consumed_crd: "0",
    search_reserved_crd: "0",
    fetch_granted_crd: "0",
    fetch_consumed_crd: "0",
    fetch_reserved_crd: "0",
  }
}

function renderForm(fetchAvailable: boolean, overrides: Record<string, unknown> = {}) {
  const onSave = vi.fn(() => Promise.resolve(true))
  const onClose = vi.fn()
  const onReload = vi.fn()
  render(
    <CRDGrantForm
      providerName="Brave"
      authMode="keyed"
      grants={grants()}
      fetchAvailable={fetchAvailable}
      saving={false}
      saveError={null}
      staleVersion={false}
      onSave={onSave}
      onClose={onClose}
      onReload={onReload}
      {...overrides}
    />,
  )
  return { onSave, onClose, onReload }
}

describe("CRDGrantForm", () => {
  it("shows search only with no fetch field for Brave (UI7-04, UI7-08)", () => {
    renderForm(false)
    expect(screen.getByLabelText("Search budget (USD)")).not.toBeNull()
    expect(screen.queryByLabelText(/Fetch budget/i)).toBeNull()
    expect(screen.queryByText(/fetch grant/i)).toBeNull()
  })

  it("keeps exact stored 4.500 until the user changes it (precision rule)", () => {
    renderForm(false)
    expect(screen.getByLabelText("Search budget (USD)")).toHaveValue("0.004500")
  })

  it("updates the provider list-price equivalent while editing a CRD budget", async () => {
    renderForm(false)
    const input = screen.getByLabelText("Search budget (USD)")
    const user = userEvent.setup()
    await user.clear(input)
    await user.type(input, "5000")
    expect(input).toHaveValue("5000")
    await user.clear(input)
    await user.type(input, "2500")
    expect(input).toHaveValue("2500")
  })

  it("rejects a changed amount with two decimal digits (UI7-08)", async () => {
    renderForm(false)
    const user = userEvent.setup()
    await user.clear(screen.getByLabelText("Search budget (USD)"))
    await user.type(screen.getByLabelText("Search budget (USD)"), "4.1234567")
    await user.click(screen.getByRole("button", { name: "Save budget limit" }))
    expect(await screen.findByText("Use up to six decimal places")).not.toBeNull()
  })

  it("preserves the stored fetch amount when the input stays absent (UI7-08)", async () => {
    const { onSave } = renderForm(false)
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Save budget limit" }))
    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onSave).toHaveBeenCalledWith({
      auth_mode: "keyed",
      version: 3,
      period_start: "2026-09-01",
      period_end: "2026-09-30",
      search_crd: "4.500",
      fetch_crd: "0",
    })
  })

  it("closes only when saveGrant returns true (UI7-08)", async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(
      <CRDGrantForm
        providerName="Brave"
        authMode="keyed"
        grants={grants()}
        fetchAvailable={false}
        saving={false}
        saveError={null}
        staleVersion={false}
        onSave={() => Promise.resolve(false)}
        onClose={onClose}
        onReload={() => {}}
      />,
    )
    await user.click(screen.getByRole("button", { name: "Save budget limit" }))
    expect(onClose).not.toHaveBeenCalled()
  })

  it("shows the reload action after HTTP 409 and keeps the draft (UI7-08)", () => {
    renderForm(false, { staleVersion: true, saveError: "The server holds a newer version of this record. Reload the limits and try again." })
    expect(screen.getByRole("button", { name: "Reload limits" })).not.toBeNull()
    expect(screen.getByLabelText("Search budget (USD)")).toHaveValue("0.004500")
  })

  it("labels every input explicitly with error descriptions (a11y)", async () => {
    renderForm(false)
    const user = userEvent.setup()
    await user.clear(screen.getByLabelText("Search budget (USD)"))
    await user.click(screen.getByRole("button", { name: "Save budget limit" }))
    expect(await screen.findByText("Enter an amount")).not.toBeNull()
    expect(screen.getByLabelText("Search budget (USD)").getAttribute("aria-invalid")).toBe("true")
  })

  it("uses one column with three full-width rows in amount-period order (final-polish 2)", () => {
    renderForm(false)
    const grid = document.querySelector("div.grid")
    expect(grid).not.toBeNull()
    expect(grid?.className ?? "").toContain("grid-cols-1")
    expect(grid?.className ?? "").not.toContain("sm:grid-cols-2")
    const labels = Array.from(document.querySelectorAll("label")).map((entry) => entry.textContent)
    expect(labels).toEqual(["Search budget (USD)", "Period start", "Period end"])
  })

  it("shows stored facts as a Set, Used, Reserved table without a helper paragraph (CARD-4)", () => {
    renderForm(false)
    const table = screen.getByRole("table", { name: "Current budget limit" })
    expect(Array.from(table.querySelectorAll("th")).map((th) => th.textContent)).toEqual([
      "Operation",
      "Set (USD)",
      "Used (USD)",
      "Reserved (USD)",
    ])
    expect(table.querySelectorAll("tbody tr")).toHaveLength(1)
    expect(screen.queryByText(/Stored budget limit/)).toBe(null)
    expect(screen.queryByText(SPEND_CAP_NOTE)).toBe(null)
  })

  it("puts Cancel before the primary Save on the right and closes on Cancel", async () => {
    const { onClose, onSave } = renderForm(false)
    const user = userEvent.setup()
    const labels = screen.getAllByRole("button").map((button) => button.textContent)
    expect(labels).toEqual(["Cancel", "Save budget limit"])
    await user.click(screen.getByRole("button", { name: "Cancel" }))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onSave).not.toHaveBeenCalled()
  })
})

describe("CRDGrantForm Tavily native", () => {
  function tavilyProfile() {
    return {
      reference_usd_per_crd: "0.001",
      native_usd_per_unit: "0.008",
      cost_basis: "paygo_reference",
      price_version: "paygo-reference",
      source: "documented",
      estimated: true,
    }
  }

  function tavilyGrants() {
    return {
      provider: "tavily",
      auth_mode: "keyed",
      period_start: "2026-09-01",
      period_end: "2026-09-30",
      version: 3,
      search_granted_crd: "8",
      search_consumed_crd: "0",
      search_reserved_crd: "0",
      fetch_granted_crd: "16",
      fetch_consumed_crd: "0",
      fetch_reserved_crd: "0",
    }
  }

  function renderTavily(overrides: Record<string, unknown> = {}) {
    const onSave = vi.fn(() => Promise.resolve(true))
    const onClose = vi.fn()
    const onReload = vi.fn()
    render(
      <CRDGrantForm
        providerName="Tavily"
        authMode="keyed"
        grants={tavilyGrants()}
        fetchAvailable
        saving={false}
        saveError={null}
        staleVersion={false}
        nativeDisplay={{ credits: {} as never, profile: tavilyProfile() } as never}
        onSave={onSave}
        onClose={onClose}
        onReload={onReload}
        {...overrides}
      />,
    )
    return { onSave, onClose }
  }

  it("displays native Credits while keeping stored CRD text convertible", () => {
    renderTavily()
    expect(screen.getByLabelText("Search budget (USD)")).toHaveValue("0.008")
    expect(screen.getByLabelText("Fetch budget (USD)")).toHaveValue("0.016")
    expect(screen.queryByText(/1 credit/)).toBeNull()
    expect(screen.queryByText(/2 credits/)).toBeNull()
    expect(screen.queryByText("8 CRD")).toBeNull()
  })

  it("wires CRD on submit after a typed Credits amount", async () => {
    const { onSave } = renderTavily()
    const user = userEvent.setup()
    await user.clear(screen.getByLabelText("Search budget (USD)"))
    await user.type(screen.getByLabelText("Search budget (USD)"), "3")
    await user.click(screen.getByRole("button", { name: "Save budget limit" }))
    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onSave).toHaveBeenCalledWith({
      auth_mode: "keyed",
      version: 3,
      period_start: "2026-09-01",
      period_end: "2026-09-30",
      search_crd: "3000",
      fetch_crd: "16",
    })
  })

  it("disables conversion on an unknown profile and keeps CRD behavior", () => {
    const onSave = vi.fn(() => Promise.resolve(true))
    render(
      <CRDGrantForm
        providerName="Tavily"
        authMode="keyed"
        grants={tavilyGrants()}
        fetchAvailable
        saving={false}
        saveError={null}
        staleVersion={false}
        nativeDisplay={{ credits: {} as never, profile: null } as never}
        onSave={onSave}
        onClose={() => {}}
        onReload={() => {}}
      />,
    )
    expect(screen.getByLabelText("Search budget (USD)")).toHaveValue("0.008")
    expect(screen.getByLabelText("Fetch budget (USD)")).toHaveValue("0.016")
    expect(screen.queryByText(/8 credits/)).toBeNull()
  })
})


describe("USD budget dates and precision", () => {
  it("uses the shared text date fields and sends ISO bounds with exact edited USD", async () => {
    const { onSave } = renderForm(false)
    const user = userEvent.setup()
    expect(screen.getByLabelText("Period start")).toHaveAttribute("type", "text")
    expect(screen.getByLabelText("Period end")).toHaveAttribute("type", "text")
    await user.clear(screen.getByLabelText("Period start"))
    await user.type(screen.getByLabelText("Period start"), "Sep 2, 2026")
    await user.clear(screen.getByLabelText("Search budget (USD)"))
    await user.type(screen.getByLabelText("Search budget (USD)"), "1.234567")
    await user.click(screen.getByRole("button", { name: "Save budget limit" }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ period_start: "2026-09-02", search_crd: "1234.567000" }))
  })
})
