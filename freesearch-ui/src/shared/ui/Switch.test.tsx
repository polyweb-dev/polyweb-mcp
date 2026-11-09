import React from "react"
import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Switch } from "./Switch"

/**
 * Characterization contract for the shared Switch primitive (CLEANUP.md 2.5).
 * Locks the exact public API + accessible behavior that the Base UI swap
 * must preserve byte-identically: checked/change API, generated label IDs,
 * description wiring (unwired), disabled state, role/name, focus styles,
 * form behavior.
 */
describe("Switch contract", () => {
  it("exposes role=switch with aria-checked reflecting checked", () => {
    const { rerender } = render(<Switch checked={false} onChange={() => {}} ariaLabel="Demo" />)
    const sw = screen.getByRole("switch", { name: "Demo" })
    expect(sw).toHaveAttribute("aria-checked", "false")

    rerender(<Switch checked onChange={() => {}} ariaLabel="Demo" />)
    expect(screen.getByRole("switch", { name: "Demo" })).toHaveAttribute("aria-checked", "true")
  })

  it("calls onChange with the negated value on click (both directions)", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const { rerender } = render(<Switch checked={false} onChange={onChange} ariaLabel="Demo" />)
    await user.click(screen.getByRole("switch", { name: "Demo" }))
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(true)

    onChange.mockClear()
    rerender(<Switch checked onChange={onChange} ariaLabel="Demo" />)
    await user.click(screen.getByRole("switch", { name: "Demo" }))
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(false)
  })

  it("toggles via keyboard Space and Enter", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Switch checked={false} onChange={onChange} ariaLabel="Demo" />)
    const sw = screen.getByRole("switch", { name: "Demo" })
    sw.focus()
    await user.keyboard(" ")
    expect(onChange).toHaveBeenCalledWith(true)

    onChange.mockClear()
    sw.focus()
    await user.keyboard("{Enter}")
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it("prefers ariaLabel over label for the accessible name, falls back to label", () => {
    const { unmount } = render(
      <Switch checked={false} onChange={() => {}} label="Visible" ariaLabel="Explicit" />
    )
    expect(screen.getByRole("switch", { name: "Explicit" })).toBeInTheDocument()
    unmount()

    render(<Switch checked={false} onChange={() => {}} label="Visible" />)
    expect(screen.getByRole("switch", { name: "Visible" })).toBeInTheDocument()
  })

  it("associates the visible label with the switch; clicking label text toggles", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <Switch
        checked={false}
        onChange={onChange}
        label="Fallback chaining"
        description="Moves on when a provider fails."
      />
    )
    const sw = screen.getByRole("switch", { name: "Fallback chaining" })
    const swId = sw.getAttribute("id")
    expect(swId).toBeTruthy()

    const label = screen.getByText("Fallback chaining").closest("label")
    expect(label?.getAttribute("for")).toBe(swId)

    await user.click(screen.getByText("Fallback chaining"))
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it("generates unique ids per instance and honors an explicit id", () => {
    render(
      <>
        <Switch checked={false} onChange={() => {}} label="One" />
        <Switch checked={false} onChange={() => {}} label="Two" />
        <Switch checked={false} onChange={() => {}} label="Three" id="custom-id" />
      </>
    )
    const one = screen.getByRole("switch", { name: "One" })
    const two = screen.getByRole("switch", { name: "Two" })
    const three = screen.getByRole("switch", { name: "Three" })
    expect(one.getAttribute("id")).toBeTruthy()
    expect(two.getAttribute("id")).toBeTruthy()
    expect(one.getAttribute("id")).not.toBe(two.getAttribute("id"))
    expect(three.getAttribute("id")).toBe("custom-id")
  })

  it("renders description text without wiring aria-describedby", () => {
    render(
      <Switch
        checked={false}
        onChange={() => {}}
        label="Fallback chaining"
        description="Moves on when a provider fails."
      />
    )
    expect(screen.getByText("Moves on when a provider fails.")).toBeInTheDocument()
    expect(screen.getByRole("switch", { name: "Fallback chaining" })).not.toHaveAttribute(
      "aria-describedby"
    )
  })

  it("disabled switch is non-interactive via mouse and keyboard", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <>
        <button type="button">before</button>
        <Switch checked onChange={onChange} ariaLabel="Demo" disabled />
      </>
    )
    const sw = screen.getByRole("switch", { name: "Demo" })
    expect(sw).toBeDisabled()

    await user.click(sw)
    expect(onChange).not.toHaveBeenCalled()

    // Browser-true contract: a disabled switch is unreachable via Tab and
    // ignores keyboard activation. (Programmatic .focus() on a disabled
    // control is a jsdom quirk, not a user-observable contract.)
    await user.click(screen.getByRole("button", { name: "before" }))
    await user.tab()
    expect(document.activeElement).not.toBe(sw)
    await user.keyboard(" ")
    await user.keyboard("{Enter}")
    expect(onChange).not.toHaveBeenCalled()
  })

  it("adds no aria-labelledby, so the accessible name comes only from aria-label/label", () => {
    render(<Switch checked={false} onChange={() => {}} label="Fallback chaining" />)
    const sw = screen.getByRole("switch", { name: "Fallback chaining" })
    expect(sw).not.toHaveAttribute("aria-labelledby")
    expect(sw).toHaveAttribute("aria-label", "Fallback chaining")
  })

  it("exposes exactly one switch per instance (no duplicate accessible nodes)", () => {
    render(
      <>
        <Switch checked={false} onChange={() => {}} label="One" />
        <Switch checked onChange={() => {}} label="Two" />
      </>
    )
    expect(screen.getAllByRole("switch")).toHaveLength(2)
  })

  it("is focusable when enabled and carries the signal focus-ring styles", () => {
    render(<Switch checked={false} onChange={() => {}} ariaLabel="Demo" />)
    const sw = screen.getByRole("switch", { name: "Demo" })
    sw.focus()
    expect(document.activeElement).toBe(sw)
    expect(sw.className).toContain("focus-visible:ring-2")
  })

  it("behaves as type=button inside forms (never submits)", async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault())
    const onChange = vi.fn()
    render(
      <form onSubmit={onSubmit}>
        <Switch checked={false} onChange={onChange} ariaLabel="Demo" />
      </form>
    )
    const sw = screen.getByRole("switch", { name: "Demo" })
    expect(sw).toHaveAttribute("type", "button")
    await user.click(sw)
    expect(onChange).toHaveBeenCalledWith(true)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it("reflects checked state on the thumb position", () => {
    const { rerender } = render(<Switch checked={false} onChange={() => {}} ariaLabel="Demo" />)
    const thumb = screen.getByRole("switch", { name: "Demo" }).querySelector("span")
    expect(thumb?.className).not.toContain("translate-x-[14px]")

    rerender(<Switch checked onChange={() => {}} ariaLabel="Demo" />)
    const thumbOn = screen.getByRole("switch", { name: "Demo" }).querySelector("span")
    expect(thumbOn?.className).toContain("translate-x-[14px]")
  })

  it("keeps the on color visible when disabled", () => {
    const { rerender } = render(<Switch checked disabled onChange={() => {}} ariaLabel="Demo" />)
    const sw = screen.getByRole("switch", { name: "Demo" })
    expect(sw).toBeChecked()
    expect(sw).toBeDisabled()
    expect(sw).toHaveClass("bg-[var(--signal)]", "disabled:opacity-70")
    expect(sw.parentElement).not.toHaveClass("opacity-45")
    rerender(<Switch checked={false} disabled onChange={() => {}} ariaLabel="Demo" />)
    expect(sw).not.toBeChecked()
    expect(sw).toHaveClass("bg-transparent", "disabled:opacity-45")
  })
})
