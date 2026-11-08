import { describe, expect, it } from "vitest"
import { navLinkClass } from "./navLinkClass"

describe("navLinkClass", () => {
  it("marks the active link with the raised surface step and no signal wash or spine", () => {
    const active = navLinkClass(false, true)
    expect(active).toContain("bg-[var(--raised)]")
    expect(active).toContain("font-medium")
    expect(active).toContain("text-[var(--text-strong)]")
    expect(active).not.toContain("bg-[var(--signal-muted)]")
    expect(active).not.toContain("before:bg-[var(--signal)]")
    expect(navLinkClass(false, false)).not.toContain("bg-[var(--raised)] font-medium")
  })

  it("keeps the focus ring and reduced-motion handling in both modes", () => {
    for (const collapsed of [true, false]) {
      const value = navLinkClass(collapsed, false)
      expect(value).toContain("focus-visible:ring-[var(--signal)]")
      expect(value).toContain("motion-reduce:transition-none")
    }
  })

  it("centers the icon on the collapsed rail and keeps the 32px row inset", () => {
    expect(navLinkClass(true, false)).toContain("justify-center")
    expect(navLinkClass(false, false)).toContain("gap-2.5")
    expect(navLinkClass(false, false)).toContain("px-2.5")
    expect(navLinkClass(false, false)).toContain("h-8")
  })
})
