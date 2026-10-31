import { describe, expect, it } from "vitest"
import { navLinkClass } from "./navLinkClass"

describe("navLinkClass", () => {
  it("marks the active link with the signal wash and spine", () => {
    const active = navLinkClass(false, true)
    expect(active).toContain("bg-[var(--signal-muted)]")
    expect(active).toContain("before:bg-[var(--signal)]")
    expect(navLinkClass(false, false)).not.toContain("bg-[var(--signal-muted)]")
  })

  it("keeps the focus ring and reduced-motion handling in both modes", () => {
    for (const collapsed of [true, false]) {
      const value = navLinkClass(collapsed, false)
      expect(value).toContain("focus-visible:ring-[var(--signal)]")
      expect(value).toContain("motion-reduce:transition-none")
    }
  })

  it("centers the icon on the collapsed rail", () => {
    expect(navLinkClass(true, false)).toContain("justify-center")
    expect(navLinkClass(false, false)).toContain("gap-3")
  })
})
