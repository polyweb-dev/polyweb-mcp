import { describe, it, expect } from "vitest"
import { render, screen, within } from "@testing-library/react"
import {
  AUTH_BRAND_CLASSES,
  AUTH_BRAND_NAME_CLASSES,
  AUTH_BRAND_TILE_CLASSES,
  AUTH_FIELD_CLASSES,
  AUTH_FOOTER_CLASSES,
  AUTH_FOOTER_TEXT_CLASSES,
  AUTH_LINK_CLASSES,
  AUTH_SUBMIT_CLASSES,
  AuthPanel,
} from "./AuthPanel"

describe("AuthPanel", () => {
  it("renders a static centered card without an empty subtitle", () => {
    const { container } = render(
      <AuthPanel title="Sign in">
        <button type="submit" className={AUTH_SUBMIT_CLASSES}>
          Sign in
        </button>
      </AuthPanel>
    )

    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument()
    expect(screen.queryByText("Use your FreeSearch account.")).toBeNull()
    const card = screen.getByRole("heading", { name: "Sign in" }).closest("div")?.parentElement
    expect(card?.className).toContain("rounded-xl")
    expect(card?.className).toContain("max-w-sm")
    expect(card?.className).toContain("p-6")
    expect(container.querySelector("[role='dialog']")).toBeNull()
  })

  it("keeps shared control styles with 24px footer spacing and no divider", () => {
    expect(AUTH_SUBMIT_CLASSES).toContain("h-10")
    expect(AUTH_SUBMIT_CLASSES).toContain("text-[13px]")
    expect(AUTH_SUBMIT_CLASSES).toContain("bg-[var(--signal)]")
    expect(AUTH_FOOTER_CLASSES).toContain("mt-6")
    expect(AUTH_FOOTER_CLASSES).not.toContain("border-t")
    expect(AUTH_FOOTER_TEXT_CLASSES).toContain("underline-offset-3")
    expect(AUTH_FOOTER_TEXT_CLASSES).toContain("text-[13px]")
    expect(AUTH_LINK_CLASSES).toContain("focus-visible:ring-2")
    expect(AUTH_FIELD_CLASSES).toContain("rounded")
    expect(AUTH_FIELD_CLASSES).not.toContain("rounded-xl")
  })

  it("uses the 15px title size without a header divider and retains optional subtitles", () => {
    render(
      <AuthPanel title="Create an account" subtitle="Create your FreeSearch account">
        <p>child</p>
      </AuthPanel>
    )

    const title = screen.getByRole("heading", { name: "Create an account" })
    expect(title.className).toContain("text-[15px]")
    expect(title.getAttribute("style")).toContain("font-size: 15px")
    expect(title.parentElement).not.toHaveStyle({ borderBottom: "1px solid var(--border-subtle)" })
    expect(screen.getByText("Create your FreeSearch account")).toBeInTheDocument()
  })

  it("shows the repository brand once above the card", () => {
    render(
      <AuthPanel title="Sign in" subtitle="Use your FreeSearch account.">
        <p>child</p>
      </AuthPanel>
    )

    expect(screen.getByText("FreeSearch", { exact: true })).toBeInTheDocument()
    const logo = document.querySelector('img[src*="freesearch"]')
    expect(logo).not.toBeNull()
    expect(logo?.getAttribute("alt")).toBe("")
    expect(logo?.getAttribute("aria-hidden")).toBe("true")
  })

  it("keeps one page title with the brand outside the heading", () => {
    render(
      <AuthPanel title="Sign in" subtitle="Use your FreeSearch account.">
        <p>child</p>
      </AuthPanel>
    )

    expect(screen.getAllByRole("heading")).toHaveLength(1)
    const brand = screen.getByText("FreeSearch", { exact: true })
    expect(within(brand.closest("div") as HTMLElement).queryAllByRole("heading")).toHaveLength(0)
  })

  it("keeps the brand tile and name classes of the sidebar style", () => {
    expect(AUTH_BRAND_CLASSES).toContain("mb-6")
    expect(AUTH_BRAND_TILE_CLASSES).toContain("size-12")
    expect(AUTH_BRAND_TILE_CLASSES).toContain("rounded-lg")
    expect(AUTH_BRAND_NAME_CLASSES).toContain("text-[22px]")
    expect(AUTH_BRAND_NAME_CLASSES).toContain("font-semibold")
  })
})
