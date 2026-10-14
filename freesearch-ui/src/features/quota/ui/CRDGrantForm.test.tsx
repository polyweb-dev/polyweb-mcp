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
    expect(screen.getByLabelText("Search credit units (CRD)")).not.toBeNull()
    expect(screen.queryByLabelText(/Fetch credit units/i)).toBeNull()
    expect(screen.queryByText(/fetch grant/i)).toBeNull()
  })

  it("keeps exact stored 4.500 until the user changes it (precision rule)", () => {
    renderForm(false)
    expect(screen.getByLabelText("Search credit units (CRD)")).toHaveValue("4.500")
  })

  it("rejects a changed amount with two decimal digits (UI7-08)", async () => {
    renderForm(false)
    const user = userEvent.setup()
    await user.clear(screen.getByLabelText("Search credit units (CRD)"))
    await user.type(screen.getByLabelText("Search credit units (CRD)"), "4.55")
    await user.click(screen.getByRole("button", { name: "Save budget limit" }))
    expect(await screen.findByText("Use at most one decimal digit (for example 3.8).")).not.toBeNull()
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
    expect(screen.getByLabelText("Search credit units (CRD)")).toHaveValue("4.500")
  })

  it("labels every input explicitly with error descriptions (a11y)", async () => {
    renderForm(false)
    const user = userEvent.setup()
    await user.clear(screen.getByLabelText("Search credit units (CRD)"))
    await user.click(screen.getByRole("button", { name: "Save budget limit" }))
    expect(await screen.findByText("Required.")).not.toBeNull()
    expect(screen.getByLabelText("Search credit units (CRD)").getAttribute("aria-invalid")).toBe("true")
  })

  it("uses one column with three full-width rows in amount-period order (final-polish 2)", () => {
    renderForm(false)
    const grid = document.querySelector("div.grid")
    expect(grid).not.toBeNull()
    expect(grid?.className ?? "").toContain("grid-cols-1")
    expect(grid?.className ?? "").not.toContain("sm:grid-cols-2")
    const labels = Array.from(document.querySelectorAll("label")).map((entry) => entry.textContent)
    expect(labels).toEqual(["Search credit units (CRD)", "Period start", "Period end"])
  })

  it("shows stored facts without a helper paragraph (CARD-4)", () => {
    renderForm(false)
    expect(screen.getByText(/Stored budget limit/)).not.toBeNull()
    expect(screen.queryByText(SPEND_CAP_NOTE)).toBe(null)
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
    expect(screen.getByLabelText("Search Credits")).toHaveValue("1")
    expect(screen.getByLabelText("Fetch Credits")).toHaveValue("2")
    expect(screen.getByText(/1 Credit/)).not.toBeNull()
    expect(screen.getByText(/2 Credits/)).not.toBeNull()
    expect(screen.queryByText("8 CRD")).toBeNull()
  })

  it("wires CRD on submit after a typed Credits amount", async () => {
    const { onSave } = renderTavily()
    const user = userEvent.setup()
    await user.clear(screen.getByLabelText("Search Credits"))
    await user.type(screen.getByLabelText("Search Credits"), "3")
    await user.click(screen.getByRole("button", { name: "Save budget limit" }))
    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onSave).toHaveBeenCalledWith({
      auth_mode: "keyed",
      version: 3,
      period_start: "2026-09-01",
      period_end: "2026-09-30",
      search_crd: "24",
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
    expect(screen.getByLabelText("Search credit units (CRD)")).toHaveValue("8")
    expect(screen.getByLabelText("Fetch credit units (CRD)")).toHaveValue("16")
    expect(screen.getByText(/8 CRD/)).not.toBeNull()
  })
})
