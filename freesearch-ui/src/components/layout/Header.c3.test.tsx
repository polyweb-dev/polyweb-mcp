import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Header, type TabId } from "./Header"

/**
 * C3 modern navbar — BDD Acceptance (Red phase).
 *
 * Feedback grounding (read-only): .agents/FEEDBACK/UI/feedback.md L12
 * ("This topbar/navbar feels like 2010") + image-26.png (FreeSearch brand
 * left, six plain text links right, Playground active with a faint dark wash).
 *
 * Plan scope: ONLY Header.tsx internals/styling change. Preserved contracts
 * (guarded, green before AND after):
 *   - HeaderProps/TabId/navItems, 6 plain buttons
 *   - sticky + backdrop rgba(37,37,38,0.85) verbatim (AC-C1-8 guard)
 *   - zero tab roles + no router (AC-C2-5 guard)
 * Modern deltas (RED before C3, green after):
 *   - inset pill containment, active signal bar/wash, aria-current=page,
 *     signal focus ring, reduced-motion.
 *
 * AC mapping:
 *   C3-1 brand + sticky + backdrop
 *   C3-2 six buttons fire onSelectTab, zero tab roles
 *   C3-3 no URL change / no router dependency
 *   C3-4 single active indicator tracks activeTab (RED)
 *   C3-5 keyboard focus ring + reduced-motion (RED)
 *   C3-6 token purity — no new hex/oklch/gradient (guard)
 */

const testDir = import.meta.dirname
const headerSource = readFileSync(path.resolve(testDir, "./Header.tsx"), "utf8")
const packageJsonRaw = readFileSync(
  path.resolve(testDir, "../../../package.json"),
  "utf8"
)
const packageJson = JSON.parse(packageJsonRaw) as {
  dependencies?: Record<string, string>
  devDependencies?: Record<string, string>
}

const norm = (value: string): string => value.toLowerCase().replace(/\s+/g, "")

const EXPECTED_NAV: Array<{ label: string; id: TabId }> = [
  { label: "Playground", id: "playground" },
  { label: "Providers", id: "providers" },
  { label: "Routing", id: "routing" },
  { label: "Usage", id: "quotas" },
  { label: "Activity", id: "activity" },
  { label: "Settings", id: "settings" },
]

function renderHeader(activeTab: TabId, onSelectTab = vi.fn()) {
  const view = render(<Header activeTab={activeTab} onSelectTab={onSelectTab} />)
  return { onSelectTab, ...view }
}

function headerEl(): HTMLElement {
  const header = document.querySelector("header")
  if (header === null) throw new Error("expected a <header> element")
  return header as HTMLElement
}

function navEl(): HTMLElement {
  const nav = document.querySelector("header nav")
  if (nav === null) throw new Error("expected a <nav> inside <header>")
  return nav as HTMLElement
}

describe("C3-1: brand + sticky + backdrop", () => {
  it("renders the FreeSearch brand inside the header", () => {
    renderHeader("playground")
    const brand = screen.getByText("FreeSearch", { exact: true })
    expect(brand).toBeInTheDocument()
    expect(brand.closest("header")).not.toBeNull()
  })

  it("header is sticky, pinned to the top, with backdrop blur", () => {
    renderHeader("playground")
    const header = headerEl()
    expect(header.className).toMatch(/sticky/)
    expect(header.className).toMatch(/top-0/)
    expect(header.className).toMatch(/backdrop-blur/)
  })

  it("header backdrop is exactly rgba(37, 37, 38, 0.85) verbatim (AC-C1-8 guard)", () => {
    expect(norm(headerSource).includes("rgba(37,37,38,0.85)")).toBe(true)
    renderHeader("playground")
    const header = headerEl()
    expect(norm(header.style.background)).toBe("rgba(37,37,38,0.85)")
  })
})

describe("C3-2: six plain buttons fire onSelectTab, zero tab roles", () => {
  it("renders exactly six navigation buttons in order with exact labels", () => {
    renderHeader("playground")
    const buttons = screen.getAllByRole("button")
    expect(buttons.map((b) => b.textContent)).toEqual([
      "Playground",
      "Providers",
      "Routing",
      "Usage",
      "Activity",
      "Settings",
    ])
    expect(buttons).toHaveLength(6)
    for (const button of buttons) {
      expect(button.tagName).toBe("BUTTON")
    }
  })

  it("exposes zero tab roles — nav stays plain buttons", () => {
    renderHeader("playground")
    expect(screen.queryByRole("tab")).not.toBeInTheDocument()
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument()
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument()
  })

  it.each(EXPECTED_NAV)(
    "clicking $label fires onSelectTab with $id exactly once",
    async ({ label, id }) => {
      const user = userEvent.setup()
      const { onSelectTab } = renderHeader("playground")
      await user.click(screen.getByRole("button", { name: label, exact: true }))
      expect(onSelectTab).toHaveBeenCalledTimes(1)
      expect(onSelectTab).toHaveBeenCalledWith(id)
    }
  )
})

describe("C3-3: no URL change / no router dependency", () => {
  it("clicking every nav button never changes the URL", async () => {
    const user = userEvent.setup()
    const { onSelectTab } = renderHeader("playground")
    const before = window.location.href
    for (const { label } of EXPECTED_NAV) {
      await user.click(screen.getByRole("button", { name: label, exact: true }))
    }
    expect(window.location.href).toBe(before)
    expect(window.location.pathname).toBe("/")
    expect(onSelectTab).toHaveBeenCalledTimes(6)
    expect(onSelectTab).toHaveBeenNthCalledWith(1, "playground")
    expect(onSelectTab).toHaveBeenNthCalledWith(6, "settings")
  })

  it("renders no anchor navigation inside the header", () => {
    renderHeader("playground")
    expect(headerEl().querySelector("a")).toBeNull()
  })

  it("package.json declares no router dependency", () => {
    const allDeps = {
      ...(packageJson.dependencies ?? {}),
      ...(packageJson.devDependencies ?? {}),
    }
    const routerDeps = Object.keys(allDeps).filter((name) =>
      /router|wouter/i.test(name)
    )
    expect(routerDeps).toEqual([])
  })

  it("Header source imports no router and renders no link components", () => {
    expect(headerSource).not.toMatch(/react-router|wouter/i)
    expect(headerSource).not.toMatch(/tanstack.*router/i)
    expect(headerSource).not.toMatch(/from\s+["']next\/(router|navigation|link)["']/i)
    expect(headerSource.includes("<Link")).toBe(false)
    expect(headerSource.includes("<NavLink")).toBe(false)
  })
})

describe("C3-4: single active indicator tracks activeTab (RED)", () => {
  it("exactly one button carries aria-current=page, on the active tab", () => {
    renderHeader("playground")
    expect(
      screen.getByRole("button", { name: "Playground", exact: true })
    ).toHaveAttribute("aria-current", "page")
    for (const label of ["Providers", "Routing", "Usage", "Activity", "Settings"]) {
      expect(
        screen.getByRole("button", { name: label, exact: true })
      ).not.toHaveAttribute("aria-current")
    }
    expect(
      document.querySelectorAll('header [aria-current="page"]')
    ).toHaveLength(1)
  })

  it("aria-current moves when activeTab changes", () => {
    const { rerender } = render(
      <Header activeTab="playground" onSelectTab={() => {}} />
    )
    expect(
      screen.getByRole("button", { name: "Playground", exact: true })
    ).toHaveAttribute("aria-current", "page")

    rerender(<Header activeTab="routing" onSelectTab={() => {}} />)

    expect(
      screen.getByRole("button", { name: "Routing", exact: true })
    ).toHaveAttribute("aria-current", "page")
    expect(
      screen.getByRole("button", { name: "Playground", exact: true })
    ).not.toHaveAttribute("aria-current")
    expect(
      document.querySelectorAll('header [aria-current="page"]')
    ).toHaveLength(1)
  })

  it("nav uses inset pill containment (rounded-full pill)", () => {
    renderHeader("playground")
    const nav = navEl()
    expect(nav.className).toContain("rounded-full")
  })

  it("nav pill containment is token-backed, not a bare transparent row", () => {
    renderHeader("playground")
    const nav = navEl()
    const hay = `${nav.className} ${nav.getAttribute("style") ?? ""}`.toLowerCase()
    const tokenBacked =
      hay.includes("--elevated") ||
      hay.includes("--surface") ||
      hay.includes("--signal") ||
      hay.includes("border-subtle") ||
      hay.includes("border")
    expect(tokenBacked).toBe(true)
    // Pill must also carry shape + inner padding, not the legacy gap-1 text row.
    expect(nav.className).toMatch(/rounded-full/)
    expect(nav.className).toMatch(/p-1|p-\[|padding/)
  })

  it("active button carries the signal wash/bar token", () => {
    renderHeader("playground")
    const active = screen.getByRole("button", {
      name: "Playground",
      exact: true,
    })
    const hay = `${active.className} ${active.innerHTML} ${
      active.getAttribute("style") ?? ""
    }`.toLowerCase()
    expect(hay.includes("signal")).toBe(true)
  })

  it("Header source wires the active state to the signal token", () => {
    expect(headerSource.toLowerCase().includes("signal")).toBe(true)
  })
})

describe("C3-5: keyboard focus ring + reduced-motion (RED)", () => {
  it("every nav button exposes a signal focus ring", () => {
    renderHeader("playground")
    const buttons = screen.getAllByRole("button")
    expect(buttons).toHaveLength(6)
    for (const button of buttons) {
      expect(button.className).toMatch(/focus-visible:/)
      expect(button.className.toLowerCase()).toMatch(/signal|ring/)
    }
  })

  it("Header source declares reduced-motion handling", () => {
    expect(headerSource).toMatch(/motion-reduce:|prefers-reduced-motion/)
  })

  it("reduced-motion class reaches the rendered nav/buttons", () => {
    renderHeader("playground")
    const headerHtml = headerEl().outerHTML
    expect(headerHtml.includes("motion-reduce:")).toBe(true)
  })

  it("nav buttons stay keyboard-focusable plain buttons", () => {
    renderHeader("playground")
    const buttons = screen.getAllByRole("button")
    expect(buttons).toHaveLength(6)
    for (const button of buttons) {
      expect(button.tagName).toBe("BUTTON")
      expect(button.hasAttribute("disabled")).toBe(false)
      expect(button.getAttribute("tabindex")).not.toBe("-1")
    }
    const first = buttons[0] as HTMLButtonElement
    first.focus()
    expect(document.activeElement).toBe(first)
  })
})

describe("C3-6: token purity — no new hex/oklch/gradient (guard)", () => {
  it("Header introduces zero hex color literals", () => {
    const hexes = headerSource.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []
    expect(hexes).toEqual([])
  })

  it("Header contains no oklch()", () => {
    expect(norm(headerSource).includes("oklch(")).toBe(false)
  })

  it("Header contains no gradient functions", () => {
    expect(norm(headerSource).includes("gradient")).toBe(false)
  })

  it("the only rgba literal is the blessed backdrop rgba(37, 37, 38, 0.85)", () => {
    const rgbaLiterals = headerSource.match(/rgba\([^)]*\)/gi) ?? []
    expect(rgbaLiterals).not.toHaveLength(0)
    for (const literal of rgbaLiterals) {
      expect(norm(literal)).toBe("rgba(37,37,38,0.85)")
    }
  })
})
