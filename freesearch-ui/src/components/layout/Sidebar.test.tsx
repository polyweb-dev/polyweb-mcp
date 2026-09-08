import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Sidebar } from "./Sidebar"
import type { TabId } from "./Sidebar"

/**
 * C3-REWORK collapsible sidebar — BDD Acceptance (Red phase).
 *
 * User verdict: replace the 2010 topbar with a ChatGPT-inspired collapsible
 * sidebar (prior topbar consensus VOID). Feedback grounding (read-only):
 * .agents/FEEDBACK/UI/feedback.md L12 ("This topbar/navbar feels like 2010").
 * Reference images (seen): ChatGPT EXPANDED rail (brand + labeled nav list)
 * and ChatGPT COLLAPSED rail (w-16 icon-only rail).
 *
 * Plan scope: NEW layout/Sidebar.tsx + App.tsx flex-row shell. Keep
 * PillTabs/views/theme intact; no router/<a>/tab roles. freesearch-ui/ ONLY.
 * Stale suites (Header.c3, C2Contracts top-nav pins) go red by design.
 *
 * AC mapping:
 *   AC-SB-1  Sidebar module contract — TabId verbatim incl "quotas",
 *            navItems 6, SidebarProps (collapsed/defaultCollapsed/
 *            onCollapsedChange), icons from lucide/hugeicons existing deps.
 *   AC-SB-2  Landmark + navigation — <aside> sticky full-height,
 *            <nav aria-label="Primary">, exactly 6 type=button buttons with
 *            exact accessible names, onSelectTab exact TabId, zero tab roles,
 *            no <a>, no router, URL untouched.
 *   AC-SB-3  Active state — exactly one aria-current=page tracking activeTab,
 *            signal wash/spine on the active button.
 *   AC-SB-4  Keyboard + motion — focus-visible signal ring on every nav
 *            button, motion-reduce handling, plain keyboard-focusable buttons.
 *   AC-SB-5  Collapsed rail — collapsed renders w-16 icon rail; every button
 *            keeps exact aria-label + title.
 *   AC-SB-6  Collapse control — "Collapse sidebar"/"Expand sidebar" toggle;
 *            controlled collapsed + onCollapsedChange exact payload;
 *            uncontrolled defaultCollapsed works.
 *   AC-SB-7  Responsive drawer (<md) — overlay drawer (role=dialog) + scrim
 *            (data-testid="sidebar-scrim") + Escape closes + focus returns to
 *            the "Open navigation" opener. Drawer nav is conditionally mounted:
 *            exactly one Primary nav exists while the drawer is closed.
 *   AC-SB-8  Guard — Sidebar introduces zero hex/oklch/gradient literals
 *            (Carbon Black theme tokens only).
 *   AC-SB-9  Persistence — localStorage key freesearch.sidebar.collapsed with
 *            "0"/"1", every access in try/catch; uncontrolled default reads
 *            storage, corrupt storage falls back to defaultCollapsed, toggle
 *            writes best-effort (UI collapses + notifies despite denial),
 *            controlled prop wins, throwing storage never throws.
 *
 * Contract notes for the implementer (asserted below, by accessible name —
 * never icon snapshots):
 *   - Collapse toggle is an aside-level control OUTSIDE the Primary nav
 *     (the nav holds exactly 6 buttons), named "Collapse sidebar" when
 *     expanded and "Expand sidebar" when collapsed.
 *   - Mobile opener is named "Open navigation"; drawer closer is named
 *     "Close navigation"; the drawer container uses role="dialog".
 *   - Escape handling is global (document/window keydown) and closing the
 *     drawer moves focus back to the opener via .focus().
 */

const testDir = import.meta.dirname
const sidebarSource = readFileSync(path.resolve(testDir, "./Sidebar.tsx"), "utf8")
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

const STORAGE_KEY = "freesearch.sidebar.collapsed"

function stubMatchMedia(matches: boolean): void {
  const mql = {
    matches,
    media: "",
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => false),
  }
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue(mql))
}

function renderSidebar(
  props: Partial<React.ComponentProps<typeof Sidebar>> = {}
) {
  const onSelectTab = vi.fn()
  const onCollapsedChange = vi.fn()
  const view = render(
    <Sidebar activeTab="playground" onSelectTab={onSelectTab} {...props} />
  )
  return { onSelectTab, onCollapsedChange, ...view }
}

function asideEl(): HTMLElement {
  const aside = document.querySelector("aside")
  if (aside === null) throw new Error("expected an <aside> element")
  return aside as HTMLElement
}

function primaryNav(): HTMLElement {
  return screen.getByRole("navigation", { name: "Primary" })
}

beforeEach(() => {
  window.localStorage.clear()
  stubMatchMedia(false)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("AC-SB-1: Sidebar module contract", () => {
  it("exports TabId verbatim including 'quotas'", () => {
    expect(sidebarSource).toMatch(/export\s+(type|interface)\s+TabId/)
    for (const id of [
      "playground",
      "providers",
      "routing",
      "quotas",
      "activity",
      "settings",
    ]) {
      expect(sidebarSource).toContain(`"${id}"`)
    }
  })

  it("declares navItems with all six tab ids", () => {
    expect(sidebarSource).toMatch(/navItems/)
    for (const { id } of EXPECTED_NAV) {
      expect(sidebarSource).toContain(`"${id}"`)
    }
  })

  it("declares SidebarProps with collapsed/defaultCollapsed/onCollapsedChange", () => {
    expect(sidebarSource).toMatch(/SidebarProps/)
    expect(sidebarSource).toContain("activeTab")
    expect(sidebarSource).toContain("onSelectTab")
    expect(sidebarSource).toContain("collapsed")
    expect(sidebarSource).toContain("defaultCollapsed")
    expect(sidebarSource).toContain("onCollapsedChange")
  })

  it("imports icons from lucide-react / hugeicons existing deps only", () => {
    expect(sidebarSource).toMatch(
      /from\s+["'](lucide-react|@hugeicons\/react)["']/
    )
    expect(sidebarSource).not.toMatch(/from\s+["']react-icons["']/)
    const allDeps = {
      ...(packageJson.dependencies ?? {}),
      ...(packageJson.devDependencies ?? {}),
    }
    expect(Object.keys(allDeps)).toContain("lucide-react")
    expect(Object.keys(allDeps)).toContain("@hugeicons/react")
  })

  it("renders a vector icon inside every nav button (asserted structurally, never by snapshot)", () => {
    renderSidebar()
    const buttons = within(primaryNav()).getAllByRole("button")
    expect(buttons).toHaveLength(6)
    for (const button of buttons) {
      expect(button.querySelector("svg")).not.toBeNull()
    }
  })
})

describe("AC-SB-2: landmark + six plain buttons, no router", () => {
  it("renders a sticky full-height aside landmark", () => {
    renderSidebar()
    const aside = asideEl()
    expect(aside.tagName).toBe("ASIDE")
    expect(aside.className).toMatch(/sticky/)
    expect(aside.className).toMatch(/h-screen|min-h-screen|h-full/)
  })

  it("exposes one Primary nav inside the aside", () => {
    renderSidebar()
    const nav = primaryNav()
    expect(nav.closest("aside")).not.toBeNull()
    expect(
      screen.getAllByRole("navigation", { name: "Primary" })
    ).toHaveLength(1)
  })

  it("renders exactly six type=button nav buttons in order with exact accessible names", () => {
    renderSidebar()
    const buttons = within(primaryNav()).getAllByRole("button")
    expect(buttons).toHaveLength(6)
    expect(
      buttons.map((b) => b.getAttribute("aria-label") ?? b.textContent?.trim())
    ).toEqual(["Playground", "Providers", "Routing", "Usage", "Activity", "Settings"])
    for (const button of buttons) {
      expect(button.tagName).toBe("BUTTON")
      expect(button.getAttribute("type")).toBe("button")
    }
  })

  it("every nav button is reachable by accessible name (never icon-only query)", () => {
    renderSidebar()
    for (const { label } of EXPECTED_NAV) {
      expect(
        within(primaryNav()).getByRole("button", { name: label, exact: true })
      ).toBeInTheDocument()
    }
  })

  it.each(EXPECTED_NAV)(
    "clicking $label fires onSelectTab with $id exactly once",
    async ({ label, id }) => {
      const user = userEvent.setup()
      const { onSelectTab } = renderSidebar()
      await user.click(
        within(primaryNav()).getByRole("button", { name: label, exact: true })
      )
      expect(onSelectTab).toHaveBeenCalledTimes(1)
      expect(onSelectTab).toHaveBeenCalledWith(id)
    }
  )

  it("exposes zero tab roles — sidebar nav stays plain buttons", () => {
    renderSidebar()
    expect(screen.queryByRole("tab")).not.toBeInTheDocument()
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument()
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument()
  })

  it("renders no anchor navigation inside the aside", () => {
    renderSidebar()
    expect(asideEl().querySelector("a")).toBeNull()
    expect(within(asideEl()).queryByRole("link")).not.toBeInTheDocument()
  })

  it("clicking every nav button never changes the URL", async () => {
    const user = userEvent.setup()
    const { onSelectTab } = renderSidebar()
    const before = window.location.href
    for (const { label } of EXPECTED_NAV) {
      await user.click(
        within(primaryNav()).getByRole("button", { name: label, exact: true })
      )
    }
    expect(window.location.href).toBe(before)
    expect(window.location.pathname).toBe("/")
    expect(onSelectTab).toHaveBeenCalledTimes(6)
    expect(onSelectTab).toHaveBeenNthCalledWith(1, "playground")
    expect(onSelectTab).toHaveBeenNthCalledWith(4, "quotas")
    expect(onSelectTab).toHaveBeenNthCalledWith(6, "settings")
  })

  it("declares no router dependency and imports none in Sidebar source", () => {
    const allDeps = {
      ...(packageJson.dependencies ?? {}),
      ...(packageJson.devDependencies ?? {}),
    }
    expect(
      Object.keys(allDeps).filter((name) => /router|wouter/i.test(name))
    ).toEqual([])
    expect(sidebarSource).not.toMatch(/react-router|wouter/i)
    expect(sidebarSource).not.toMatch(/tanstack.*router/i)
    expect(sidebarSource.includes("<Link")).toBe(false)
    expect(sidebarSource.includes("<NavLink")).toBe(false)
  })
})

describe("AC-SB-3: single active indicator tracks activeTab", () => {
  it("exactly one button carries aria-current=page, on the active tab", () => {
    renderSidebar({ activeTab: "playground" })
    expect(
      within(primaryNav()).getByRole("button", {
        name: "Playground",
        exact: true,
      })
    ).toHaveAttribute("aria-current", "page")
    for (const label of ["Providers", "Routing", "Usage", "Activity", "Settings"]) {
      expect(
        within(primaryNav()).getByRole("button", { name: label, exact: true })
      ).not.toHaveAttribute("aria-current")
    }
    expect(
      document.querySelectorAll('aside [aria-current="page"]')
    ).toHaveLength(1)
  })

  it("aria-current moves when activeTab changes, including the quotas id", () => {
    const { rerender } = render(
      <Sidebar activeTab="playground" onSelectTab={() => {}} />
    )
    expect(
      within(primaryNav()).getByRole("button", {
        name: "Playground",
        exact: true,
      })
    ).toHaveAttribute("aria-current", "page")

    rerender(<Sidebar activeTab="quotas" onSelectTab={() => {}} />)

    expect(
      within(primaryNav()).getByRole("button", { name: "Usage", exact: true })
    ).toHaveAttribute("aria-current", "page")
    expect(
      within(primaryNav()).getByRole("button", {
        name: "Playground",
        exact: true,
      })
    ).not.toHaveAttribute("aria-current")
    expect(
      document.querySelectorAll('aside [aria-current="page"]')
    ).toHaveLength(1)
  })

  it("active button carries the signal wash/spine token", () => {
    renderSidebar({ activeTab: "routing" })
    const active = within(primaryNav()).getByRole("button", {
      name: "Routing",
      exact: true,
    })
    const hay = `${active.className} ${active.innerHTML} ${
      active.getAttribute("style") ?? ""
    }`.toLowerCase()
    expect(hay.includes("signal")).toBe(true)
  })

  it("Sidebar source wires the active state to the signal token", () => {
    expect(sidebarSource.toLowerCase().includes("signal")).toBe(true)
  })
})

describe("AC-SB-4: keyboard focus ring + reduced-motion", () => {
  it("every nav button exposes a signal focus ring", () => {
    renderSidebar()
    const buttons = within(primaryNav()).getAllByRole("button")
    expect(buttons).toHaveLength(6)
    for (const button of buttons) {
      expect(button.className).toMatch(/focus-visible:/)
      expect(button.className.toLowerCase()).toMatch(/signal|ring/)
    }
  })

  it("Sidebar source declares reduced-motion handling", () => {
    expect(sidebarSource).toMatch(/motion-reduce:|prefers-reduced-motion/)
  })

  it("reduced-motion class reaches the rendered sidebar", () => {
    renderSidebar()
    expect(asideEl().outerHTML.includes("motion-reduce:")).toBe(true)
  })

  it("nav buttons stay keyboard-focusable plain buttons", () => {
    renderSidebar()
    const buttons = within(primaryNav()).getAllByRole("button")
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

describe("AC-SB-5: collapsed w-16 icon rail", () => {
  it("collapsed renders the aside as a w-16 icon rail", () => {
    renderSidebar({ collapsed: true, onCollapsedChange: () => {} })
    expect(asideEl().className).toMatch(/w-16/)
  })

  it("expanded aside is not a w-16 rail", () => {
    renderSidebar({ collapsed: false, onCollapsedChange: () => {} })
    expect(asideEl().className).not.toMatch(/w-16/)
  })

  it("collapsed buttons keep exact aria-label + title accessible names", () => {
    renderSidebar({ collapsed: true, onCollapsedChange: () => {} })
    const buttons = within(primaryNav()).getAllByRole("button")
    expect(buttons).toHaveLength(6)
    const seen: string[] = []
    for (const { label } of EXPECTED_NAV) {
      const button = within(primaryNav()).getByRole("button", {
        name: label,
        exact: true,
      })
      expect(button.getAttribute("aria-label")).toBe(label)
      expect(button.getAttribute("title")).toBe(label)
      seen.push(label)
    }
    expect(seen).toEqual([
      "Playground",
      "Providers",
      "Routing",
      "Usage",
      "Activity",
      "Settings",
    ])
  })

  it("collapsed nav selection still fires the exact TabId", async () => {
    const user = userEvent.setup()
    const { onSelectTab } = renderSidebar({
      collapsed: true,
      onCollapsedChange: () => {},
    })
    await user.click(
      within(primaryNav()).getByRole("button", { name: "Usage", exact: true })
    )
    expect(onSelectTab).toHaveBeenCalledTimes(1)
    expect(onSelectTab).toHaveBeenCalledWith("quotas")
  })
})

describe("AC-SB-6: collapse toggle — controlled + uncontrolled", () => {
  it("expanded sidebar offers 'Collapse sidebar' which reports true", async () => {
    const user = userEvent.setup()
    const onCollapsedChange = vi.fn()
    const { rerender } = render(
      <Sidebar
        activeTab="playground"
        onSelectTab={() => {}}
        collapsed={false}
        onCollapsedChange={onCollapsedChange}
      />
    )
    await user.click(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    )
    expect(onCollapsedChange).toHaveBeenCalledTimes(1)
    expect(onCollapsedChange).toHaveBeenCalledWith(true)
    // Controlled: DOM follows the prop, not the click.
    rerender(
      <Sidebar
        activeTab="playground"
        onSelectTab={() => {}}
        collapsed={false}
        onCollapsedChange={onCollapsedChange}
      />
    )
    expect(asideEl().className).not.toMatch(/w-16/)
  })

  it("collapsed sidebar offers 'Expand sidebar' which reports false", async () => {
    const user = userEvent.setup()
    const onCollapsedChange = vi.fn()
    render(
      <Sidebar
        activeTab="playground"
        onSelectTab={() => {}}
        collapsed
        onCollapsedChange={onCollapsedChange}
      />
    )
    await user.click(
      screen.getByRole("button", { name: "Expand sidebar", exact: true })
    )
    expect(onCollapsedChange).toHaveBeenCalledTimes(1)
    expect(onCollapsedChange).toHaveBeenCalledWith(false)
  })

  it("uncontrolled defaultCollapsed starts collapsed and toggles without props", async () => {
    const user = userEvent.setup()
    render(<Sidebar activeTab="playground" onSelectTab={() => {}} defaultCollapsed />)
    expect(asideEl().className).toMatch(/w-16/)

    await user.click(
      screen.getByRole("button", { name: "Expand sidebar", exact: true })
    )
    expect(asideEl().className).not.toMatch(/w-16/)
    expect(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    ).toBeInTheDocument()

    await user.click(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    )
    expect(asideEl().className).toMatch(/w-16/)
  })

  it("omitting defaultCollapsed starts expanded", () => {
    render(<Sidebar activeTab="playground" onSelectTab={() => {}} />)
    expect(asideEl().className).not.toMatch(/w-16/)
    expect(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    ).toBeInTheDocument()
  })
})

describe("AC-SB-7: responsive <md overlay drawer + scrim + Esc + focus return", () => {
  it("Sidebar source wires the md breakpoint, scrim, Escape, and focus return", () => {
    expect(sidebarSource).toMatch(/md:/)
    expect(sidebarSource).toMatch(/Escape/)
    expect(sidebarSource).toMatch(/keydown/)
    expect(sidebarSource).toContain("sidebar-scrim")
    expect(sidebarSource).toMatch(/\.focus\(\)/)
  })

  it("opening navigation shows the scrim and a dialog drawer", async () => {
    const user = userEvent.setup()
    renderSidebar()
    await user.click(
      screen.getByRole("button", { name: "Open navigation", exact: true })
    )
    expect(screen.getByTestId("sidebar-scrim")).toBeInTheDocument()
    expect(screen.getByRole("dialog")).toBeInTheDocument()
  })

  it("selecting a drawer item fires onSelectTab and closes the drawer", async () => {
    const user = userEvent.setup()
    const { onSelectTab } = renderSidebar()
    await user.click(
      screen.getByRole("button", { name: "Open navigation", exact: true })
    )
    const dialog = screen.getByRole("dialog")
    await user.click(
      within(dialog).getByRole("button", { name: "Routing", exact: true })
    )
    expect(onSelectTab).toHaveBeenCalledTimes(1)
    expect(onSelectTab).toHaveBeenCalledWith("routing")
    expect(screen.queryByTestId("sidebar-scrim")).not.toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("Close navigation dismisses the drawer", async () => {
    const user = userEvent.setup()
    renderSidebar()
    await user.click(
      screen.getByRole("button", { name: "Open navigation", exact: true })
    )
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    await user.click(
      screen.getByRole("button", { name: "Close navigation", exact: true })
    )
    expect(screen.queryByTestId("sidebar-scrim")).not.toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("Escape closes the drawer and returns focus to the opener", async () => {
    const user = userEvent.setup()
    renderSidebar()
    const opener = screen.getByRole("button", {
      name: "Open navigation",
      exact: true,
    })
    await user.click(opener)
    expect(screen.getByTestId("sidebar-scrim")).toBeInTheDocument()

    await user.keyboard("{Escape}")

    expect(screen.queryByTestId("sidebar-scrim")).not.toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(document.activeElement).toBe(opener)
  })
})

describe("AC-SB-8 guard: token purity — no new hex/oklch/gradient", () => {
  it("Sidebar introduces zero hex color literals", () => {
    const hexes = sidebarSource.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []
    expect(hexes).toEqual([])
  })

  it("Sidebar contains no oklch()", () => {
    expect(norm(sidebarSource).includes("oklch(")).toBe(false)
  })

  it("Sidebar contains no gradient functions", () => {
    expect(norm(sidebarSource).includes("gradient")).toBe(false)
  })
})

describe("AC-SB-9: persistence in freesearch.sidebar.collapsed", () => {
  it("Sidebar source persists 0/1 under the blessed key inside try/catch", () => {
    expect(sidebarSource).toContain(STORAGE_KEY)
    expect(sidebarSource).toContain("localStorage")
    expect(sidebarSource).toMatch(/try/)
    expect(sidebarSource).toMatch(/catch/)
  })

  it("stored '1' starts the uncontrolled sidebar collapsed", () => {
    window.localStorage.setItem(STORAGE_KEY, "1")
    render(<Sidebar activeTab="playground" onSelectTab={() => {}} />)
    expect(asideEl().className).toMatch(/w-16/)
  })

  it("stored '0' starts the uncontrolled sidebar expanded", () => {
    window.localStorage.setItem(STORAGE_KEY, "0")
    render(<Sidebar activeTab="playground" onSelectTab={() => {}} />)
    expect(asideEl().className).not.toMatch(/w-16/)
  })

  it("a corrupt stored value falls back to expanded without throwing", () => {
    window.localStorage.setItem(STORAGE_KEY, "banana")
    expect(() =>
      render(<Sidebar activeTab="playground" onSelectTab={() => {}} />)
    ).not.toThrow()
    expect(asideEl().className).not.toMatch(/w-16/)
  })

  it("uncontrolled toggle writes '1' then '0' through localStorage", async () => {
    const user = userEvent.setup()
    render(<Sidebar activeTab="playground" onSelectTab={() => {}} />)
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull()

    await user.click(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    )
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("1")

    await user.click(
      screen.getByRole("button", { name: "Expand sidebar", exact: true })
    )
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("0")
  })

  it("a corrupt stored value falls back to defaultCollapsed", () => {
    window.localStorage.setItem(STORAGE_KEY, "banana")
    render(
      <Sidebar
        activeTab="playground"
        onSelectTab={() => {}}
        defaultCollapsed
      />
    )
    expect(asideEl().className).toMatch(/w-16/)
  })

  it("controlled collapsed prop wins over a stored '1'", () => {
    window.localStorage.setItem(STORAGE_KEY, "1")
    render(
      <Sidebar
        activeTab="playground"
        onSelectTab={() => {}}
        collapsed={false}
        onCollapsedChange={() => {}}
      />
    )
    expect(asideEl().className).not.toMatch(/w-16/)
  })

  it("a throwing store never breaks render", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("storage denied")
    })
    expect(() =>
      render(<Sidebar activeTab="playground" onSelectTab={() => {}} />)
    ).not.toThrow()
    expect(asideEl()).toBeInTheDocument()
  })

  it("a throwing store never breaks the collapse toggle", async () => {
    const user = userEvent.setup()
    const onCollapsedChange = vi.fn()
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("storage denied")
    })
    render(
      <Sidebar
        activeTab="playground"
        onSelectTab={() => {}}
        onCollapsedChange={onCollapsedChange}
      />
    )
    await user.click(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    )
    // Best-effort persist: UI state still collapses and notifies despite denial.
    expect(asideEl().className).toMatch(/w-16/)
    expect(onCollapsedChange).toHaveBeenCalledTimes(1)
    expect(onCollapsedChange).toHaveBeenCalledWith(true)
  })
})
