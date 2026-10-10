import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, within } from "@testing-library/react"
import { ProviderSelect } from "./ProviderSelect"

/**
 * ProviderSelect: the one provider dropdown. Every entry shows its identity
 * mark and its full name. Routing sentinels show thematic marks, catalog
 * providers show catalog logos, and any other entry shows the account icon.
 * The popup grows to its widest entry, so no label truncates.
 */
const options = [
  { value: "all", label: "All Providers (Ranked Fusion)" },
  { value: "auto", label: "Auto arbitration" },
  { value: "tavily", label: "Tavily" },
  { value: "you", label: "You.com" },
]

function renderPicker(value = "auto") {
  const onValueChange = vi.fn()
  render(
    <ProviderSelect
      id="probe-picker"
      testId="probe-picker"
      value={value}
      options={options}
      onValueChange={onValueChange}
    />
  )
  return { onValueChange }
}

async function openPicker(): Promise<HTMLElement> {
  fireEvent.click(screen.getByTestId("probe-picker"))
  return await screen.findByRole("listbox")
}

describe("ProviderSelect", () => {
  it("shows no option rows while the list is closed", () => {
    renderPicker()

    expect(screen.queryByRole("listbox")).toBeNull()
    expect(screen.queryByRole("option")).toBeNull()
  })

  it("opens a popup sized to its widest entry with a viewport height cap", async () => {
    renderPicker()
    const list = await openPicker()

    expect(list).toHaveClass("w-max")
    expect(list).toHaveClass("min-w-full")
    expect(list).toHaveClass("max-h-[70vh]")
    expect(list.className).not.toContain("max-h-60")
  })

  it("shows every label in full, including the long fusion label", async () => {
    renderPicker()
    await openPicker()

    const rows = screen.getAllByRole("option")
    expect(rows).toHaveLength(4)
    expect(
      screen.getByRole("option", { name: "All Providers (Ranked Fusion)" })
    ).toBeInTheDocument()
    for (const row of rows) {
      expect(row.textContent ?? "").not.toBe("")
    }
  })

  it("marks the All Providers entry with the layers icon and no logo", async () => {
    renderPicker()
    await openPicker()

    const row = screen.getByRole("option", {
      name: "All Providers (Ranked Fusion)",
    })
    const mark = within(row).getByTestId("provider-select-mark")
    expect(mark.tagName).toBe("svg")
    expect(mark.getAttribute("class") ?? "").toContain("lucide-layers")
    expect(row.querySelector("img")).toBeNull()
  })

  it("marks the Auto arbitration entry with the sparkles icon and no logo", async () => {
    renderPicker()
    await openPicker()

    const row = screen.getByRole("option", { name: "Auto arbitration" })
    const mark = within(row).getByTestId("provider-select-mark")
    expect(mark.tagName).toBe("svg")
    expect(mark.getAttribute("class") ?? "").toContain("lucide-sparkles")
    expect(row.querySelector("img")).toBeNull()
  })

  it("marks a catalog provider with its logo image and no mark", async () => {
    renderPicker()
    await openPicker()

    const row = screen.getByRole("option", { name: "Tavily" })
    const logo = row.querySelector('[data-testid="provider-logo-tavily"]')
    expect(logo).not.toBeNull()
    expect(logo?.tagName).toBe("IMG")
    expect(
      within(row).queryByTestId("provider-select-mark")
    ).toBeNull()
  })

  it("marks a provider without a catalog logo with the account icon", async () => {
    renderPicker()
    await openPicker()

    const row = screen.getByRole("option", { name: "You.com" })
    const mark = within(row).getByTestId("provider-select-mark")
    expect(mark.tagName).toBe("svg")
    expect(mark.getAttribute("class") ?? "").toContain(
      "lucide-circle-user-round"
    )
    expect(row.querySelector("img")).toBeNull()
  })

  it("shows the mark of the current value in the trigger", () => {
    renderPicker("auto")

    const trigger = screen.getByTestId("probe-picker")
    const mark = within(trigger).getByTestId("provider-select-mark")
    expect(mark.getAttribute("class") ?? "").toContain("lucide-sparkles")
    expect(trigger.textContent).toContain("Auto arbitration")
  })

  it("chooses a row click value and closes the list", async () => {
    const { onValueChange } = renderPicker()
    await openPicker()

    fireEvent.click(screen.getByRole("option", { name: "Tavily" }))

    expect(onValueChange).toHaveBeenCalledTimes(1)
    expect(onValueChange).toHaveBeenCalledWith("tavily")
    expect(screen.queryByRole("listbox")).toBeNull()
  })

  it("holds no check gutter: no row shows a check mark", async () => {
    renderPicker()
    await openPicker()

    const rows = screen.getAllByRole("option")
    expect(rows.length).toBeGreaterThan(0)
    for (const row of rows) {
      expect(row.querySelector("svg.lucide-check")).toBeNull()
    }
    expect(
      screen.getByRole("listbox").querySelector("svg.lucide-check")
    ).toBeNull()
  })

  it("starts each row with the caller identity row", async () => {
    renderPicker()
    await openPicker()

    for (const row of screen.getAllByRole("option")) {
      expect(row.firstElementChild?.tagName).toBe("SPAN")
    }
  })

  it("marks the shown value row selected with signal background and white text", async () => {
    renderPicker("auto")
    await openPicker()

    const selected = screen.getByRole("option", { name: "Auto arbitration" })
    expect(selected.getAttribute("aria-selected")).toBe("true")
    expect(selected).toHaveClass("bg-[var(--signal)]")
    expect(selected).toHaveClass("text-white")

    const other = screen.getByRole("option", { name: "Tavily" })
    expect(other.getAttribute("aria-selected")).toBe("false")
    expect(other.className).not.toContain("bg-[var(--signal)]")
  })

  it("keeps aria-selected on every row, true only for the shown value", async () => {
    renderPicker("tavily")
    await openPicker()

    for (const row of screen.getAllByRole("option")) {
      expect(row.getAttribute("aria-selected")).not.toBeNull()
    }
    expect(
      screen.getByRole("option", { name: "Tavily" }).getAttribute("aria-selected")
    ).toBe("true")
    expect(
      screen
        .getByRole("option", { name: "Auto arbitration" })
        .getAttribute("aria-selected")
    ).toBe("false")
  })

  it("gives the shown value mark the row white and keeps muted marks elsewhere", async () => {
    renderPicker("auto")
    await openPicker()

    const selectedMark = within(
      screen.getByRole("option", { name: "Auto arbitration" })
    ).getByTestId("provider-select-mark")
    expect(selectedMark.getAttribute("class") ?? "").not.toContain(
      "text-[var(--muted)]"
    )

    const otherMark = within(
      screen.getByRole("option", { name: "All Providers (Ranked Fusion)" })
    ).getByTestId("provider-select-mark")
    expect(otherMark.getAttribute("class") ?? "").toContain(
      "text-[var(--muted)]"
    )
  })

  it("tints the keyboard cursor row with the surface color, with the shown value winning", async () => {
    renderPicker("auto")
    await openPicker()
    const trigger = screen.getByTestId("probe-picker")

    fireEvent.keyDown(trigger, { key: "ArrowDown" })
    const cursor = screen.getByRole("option", { name: "Tavily" })
    expect(cursor.getAttribute("aria-selected")).toBe("false")
    expect(cursor).toHaveClass("bg-[var(--surface)]")

    fireEvent.keyDown(trigger, { key: "ArrowUp" })
    const selected = screen.getByRole("option", { name: "Auto arbitration" })
    expect(selected).toHaveClass("bg-[var(--signal)]")
    expect(selected.className).not.toContain("bg-[var(--surface)]")
  })
})
