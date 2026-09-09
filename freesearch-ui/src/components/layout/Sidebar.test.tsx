import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router"
import { Sidebar } from "./Sidebar"
import type { TabId } from "./Sidebar"

/**
 * C4 URL routing — collapsible sidebar over router links (REWRITTEN, Red phase).
 *
 * Blessed churn (NOT weakening): the C3-REWORK AC-SB-2 no-router/button-only
 * pins are VOID. Sidebar nav items are NavLinks (role=link) bound to the
 * route table; navigation changes the URL; react-router is a dependency.
 *   - `getByRole("button")` -> `getByRole("link")` for the five nav items;
 *   - nav controls (Collapse/Expand/Open/Close) stay plain buttons;
 *   - aria-current=page preserved (exactly one, router-driven);
 *   - drawer closes on navigate; collapse/drawer/persistence untouched.
 *
 * Preserved from C3-REWORK: AC-SB-1 (module contract, TabId verbatim incl
 * "quotas"), AC-SB-3 (single aria-current), AC-SB-4 (focus ring +
 * reduced-motion), AC-SB-5 (collapsed rail), AC-SB-6 (collapse toggle),
 * AC-SB-7 (drawer + scrim + Esc + focus return), AC-SB-8 (token purity),
 * AC-SB-9 (persistence). "TabId unchanged" — quotas still renders at /usage.
 *
 * P1-FINAL (blessed inversion, NOT a regression): the standalone Providers
 * page is retired into the Settings Providers tab. The sidebar exposes FIVE
 * workspace links (Playground/Routing/Usage/Activity/Settings); the
 * "providers" TabId, nav item, TAB_PATHS entry, and /providers href are gone;
 * /providers redirects to /settings (pinned in UrlRouting.test.tsx,
 * UrlRoutingContract.test.ts, AppSidebarShell.test.tsx, and
 * SettingsProviders.p1-final.test.tsx).
 *
 * Route table (App.tsx): / -> /playground, /playground,
 * /routing, /usage (quotas), /activity, /settings, /providers -> /settings
 * redirect, * -> /playground.
 */

const testDir = import.meta.dirname
const sidebarSource =
  readFileSync(path.resolve(testDir, "./Sidebar.tsx"), "utf8") +
  "\n" +
  readFileSync(path.resolve(testDir, "./NavList.tsx"), "utf8") +
  "\n" +
  readFileSync(path.resolve(testDir, "./Brand.tsx"), "utf8")
const packageJsonRaw = readFileSync(
  path.resolve(testDir, "../../../package.json"),
  "utf8"
)
const packageJson = JSON.parse(packageJsonRaw) as {
  dependencies?: Record<string, string>
  devDependencies?: Record<string, string>
}

const norm = (value: string): string => value.toLowerCase().replace(/\s+/g, "")

const EXPECTED_NAV: Array<{ label: string; id: TabId; href: string }> = [
  { label: "Playground", id: "playground", href: "/playground" },
  { label: "Routing", id: "routing", href: "/routing" },
  { label: "Usage", id: "quotas", href: "/usage" },
  { label: "Activity", id: "activity", href: "/activity" },
  { label: "Settings", id: "settings", href: "/settings" },
]

const STORAGE_KEY = "freesearch.sidebar.collapsed"

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="test-location">{location.pathname}</div>
}

function testPath(): string {
  return screen.getByTestId("test-location").textContent ?? ""
}

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
  props: Partial<React.ComponentProps<typeof Sidebar>> = {},
  route = "/playground"
) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Sidebar {...props} />
      <LocationProbe />
    </MemoryRouter>
  )
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
      "routing",
      "quotas",
      "activity",
      "settings",
    ]) {
      expect(sidebarSource).toContain(`"${id}"`)
    }
  })

  it("declares navItems with all five tab ids (P1-FINAL: no providers)", () => {
    expect(sidebarSource).toMatch(/navItems/)
    for (const { id } of EXPECTED_NAV) {
      expect(sidebarSource).toContain(`"${id}"`)
    }
  })

  it("P1-FINAL: drops the providers TabId entirely (page retired)", () => {
    expect(sidebarSource).not.toContain('"providers"')
    expect(sidebarSource).not.toContain('"/providers"')
  })

  it("declares prop-less routing with optional collapse controls", () => {
    expect(sidebarSource).toMatch(/SidebarProps/)
    expect(sidebarSource).not.toContain("activeTab")
    expect(sidebarSource).not.toContain("onSelectTab")
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

  it("renders a vector icon inside every nav link (asserted structurally, never by snapshot)", () => {
    renderSidebar()
    const links = within(primaryNav()).getAllByRole("link")
    expect(links).toHaveLength(5)
    for (const link of links) {
      expect(link.querySelector("svg")).not.toBeNull()
    }
  })
})

describe("AC-SB-2 (C4, P1-FINAL): landmark + five router links, URL changes on nav", () => {
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

  it("renders exactly five nav links in order with exact accessible names", () => {
    renderSidebar()
    const links = within(primaryNav()).getAllByRole("link")
    expect(links).toHaveLength(5)
    expect(
      links.map((l) => l.getAttribute("aria-label") ?? l.textContent?.trim())
    ).toEqual(["Playground", "Routing", "Usage", "Activity", "Settings"])
    for (const link of links) {
      expect(link.tagName).toBe("A")
      expect(link.getAttribute("href")).toMatch(/^\//)
    }
  })

  it("every nav link carries its exact route href (quotas maps to /usage)", () => {
    renderSidebar()
    for (const { label, href } of EXPECTED_NAV) {
      expect(
        within(primaryNav()).getByRole("link", { name: label, exact: true })
      ).toHaveAttribute("href", href)
    }
    // No legacy /quotas or retired /providers route leaks into the sidebar.
    expect(asideEl().querySelector('a[href="/quotas"]')).toBeNull()
    expect(asideEl().querySelector('a[href="/providers"]')).toBeNull()
  })

  it("every nav link is reachable by accessible name (never icon-only query)", () => {
    renderSidebar()
    for (const { label } of EXPECTED_NAV) {
      expect(
        within(primaryNav()).getByRole("link", { name: label, exact: true })
      ).toBeInTheDocument()
    }
  })

  it.each(EXPECTED_NAV)(
    "clicking $label navigates to $href",
    async ({ label, href }) => {
      const user = userEvent.setup()
      renderSidebar()
      await user.click(
        within(primaryNav()).getByRole("link", { name: label, exact: true })
      )
      expect(testPath()).toBe(href)
    }
  )

  it("exposes zero tab roles — sidebar nav stays plain links", () => {
    renderSidebar()
    expect(screen.queryByRole("tab")).not.toBeInTheDocument()
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument()
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument()
  })

  it("primary nav contains links, not buttons (controls stay buttons)", () => {
    renderSidebar()
    const nav = primaryNav()
    expect(within(nav).getAllByRole("link")).toHaveLength(5)
    expect(within(nav).queryByRole("button")).not.toBeInTheDocument()
    // Aside-level controls remain plain buttons outside the Primary nav.
    expect(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    ).toBeInTheDocument()
  })

  it("clicking every nav link moves the router location through the route table", async () => {
    const user = userEvent.setup()
    renderSidebar({}, "/playground")
    expect(testPath()).toBe("/playground")
    const seen: string[] = []
    for (const { label, href } of EXPECTED_NAV) {
      await user.click(
        within(primaryNav()).getByRole("link", { name: label, exact: true })
      )
      expect(testPath()).toBe(href)
      seen.push(href)
    }
    expect(seen).toEqual([
      "/playground",
      "/routing",
      "/usage",
      "/activity",
      "/settings",
    ])
  })

  it("declares the react-router dependency and renders NavLinks in Sidebar source", () => {
    const allDeps = {
      ...(packageJson.dependencies ?? {}),
      ...(packageJson.devDependencies ?? {}),
    }
    expect(Object.keys(allDeps)).toContain("react-router")
    expect(sidebarSource).toMatch(/react-router/i)
    expect(sidebarSource.includes("<NavLink")).toBe(true)
  })
})

describe("AC-SB-3: single active indicator tracks the router", () => {
  it("exactly one link carries aria-current=page, on the active route", () => {
    renderSidebar()
    expect(
      within(primaryNav()).getByRole("link", {
        name: "Playground",
        exact: true,
      })
    ).toHaveAttribute("aria-current", "page")
    for (const label of ["Routing", "Usage", "Activity", "Settings"]) {
      expect(
        within(primaryNav()).getByRole("link", { name: label, exact: true })
      ).not.toHaveAttribute("aria-current")
    }
    expect(
      document.querySelectorAll('aside [aria-current="page"]')
    ).toHaveLength(1)
  })

  it("aria-current moves when the route changes, including /usage", async () => {
    const user = userEvent.setup()
    renderSidebar()
    expect(
      within(primaryNav()).getByRole("link", {
        name: "Playground",
        exact: true,
      })
    ).toHaveAttribute("aria-current", "page")

    await user.click(
      within(primaryNav()).getByRole("link", { name: "Usage", exact: true })
    )

    expect(
      within(primaryNav()).getByRole("link", { name: "Usage", exact: true })
    ).toHaveAttribute("aria-current", "page")
    expect(
      within(primaryNav()).getByRole("link", {
        name: "Playground",
        exact: true,
      })
    ).not.toHaveAttribute("aria-current")
    expect(
      document.querySelectorAll('aside [aria-current="page"]')
    ).toHaveLength(1)
  })

  it("active link carries the signal wash/spine token", () => {
    renderSidebar({}, "/routing")
    const active = within(primaryNav()).getByRole("link", {
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
  it("every nav link exposes a signal focus ring", () => {
    renderSidebar()
    const links = within(primaryNav()).getAllByRole("link")
    expect(links).toHaveLength(5)
    for (const link of links) {
      expect(link.className).toMatch(/focus-visible:/)
      expect(link.className.toLowerCase()).toMatch(/signal|ring/)
    }
  })

  it("Sidebar source declares reduced-motion handling", () => {
    expect(sidebarSource).toMatch(/motion-reduce:|prefers-reduced-motion/)
  })

  it("reduced-motion class reaches the rendered sidebar", () => {
    renderSidebar()
    expect(asideEl().outerHTML.includes("motion-reduce:")).toBe(true)
  })

  it("nav links stay keyboard-focusable", () => {
    renderSidebar()
    const links = within(primaryNav()).getAllByRole("link")
    expect(links).toHaveLength(5)
    for (const link of links) {
      expect(link.tagName).toBe("A")
      expect(link.hasAttribute("disabled")).toBe(false)
      expect(link.getAttribute("tabindex")).not.toBe("-1")
    }
    const first = links[0] as HTMLAnchorElement
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

  it("collapsed links keep exact aria-label + title accessible names", () => {
    renderSidebar({ collapsed: true, onCollapsedChange: () => {} })
    const links = within(primaryNav()).getAllByRole("link")
    expect(links).toHaveLength(5)
    const seen: string[] = []
    for (const { label } of EXPECTED_NAV) {
      const link = within(primaryNav()).getByRole("link", {
        name: label,
        exact: true,
      })
      expect(link.getAttribute("aria-label")).toBe(label)
      expect(link.getAttribute("title")).toBe(label)
      seen.push(label)
    }
    expect(seen).toEqual([
      "Playground",
      "Routing",
      "Usage",
      "Activity",
      "Settings",
    ])
  })

  it("collapsed nav selection still navigates to the usage route", async () => {
    const user = userEvent.setup()
    renderSidebar({ collapsed: true, onCollapsedChange: () => {} })
    await user.click(
      within(primaryNav()).getByRole("link", { name: "Usage", exact: true })
    )
    expect(testPath()).toBe("/usage")
  })
})

describe("AC-SB-6: collapse toggle — controlled + uncontrolled", () => {
  it("expanded sidebar offers 'Collapse sidebar' which reports true", async () => {
    const user = userEvent.setup()
    const onCollapsedChange = vi.fn()
    const { rerender } = render(
      <MemoryRouter initialEntries={["/playground"]}>
        <Sidebar
          collapsed={false}
          onCollapsedChange={onCollapsedChange}
        />
      </MemoryRouter>
    )
    await user.click(
      screen.getByRole("button", { name: "Collapse sidebar", exact: true })
    )
    expect(onCollapsedChange).toHaveBeenCalledTimes(1)
    expect(onCollapsedChange).toHaveBeenCalledWith(true)
    // Controlled: DOM follows the prop, not the click.
    rerender(
      <MemoryRouter initialEntries={["/playground"]}>
        <Sidebar
          collapsed={false}
          onCollapsedChange={onCollapsedChange}
        />
      </MemoryRouter>
    )
    expect(asideEl().className).not.toMatch(/w-16/)
  })

  it("collapsed sidebar offers 'Expand sidebar' which reports false", async () => {
    const user = userEvent.setup()
    const onCollapsedChange = vi.fn()
    render(
      <MemoryRouter initialEntries={["/playground"]}>
        <Sidebar
          collapsed
          onCollapsedChange={onCollapsedChange}
        />
      </MemoryRouter>
    )
    await user.click(
      screen.getByRole("button", { name: "Expand sidebar", exact: true })
    )
    expect(onCollapsedChange).toHaveBeenCalledTimes(1)
    expect(onCollapsedChange).toHaveBeenCalledWith(false)
  })

  it("uncontrolled defaultCollapsed starts collapsed and toggles without props", async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={["/playground"]}>
        <Sidebar defaultCollapsed />
      </MemoryRouter>
    )
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
    renderSidebar()
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

  it("selecting a drawer item navigates and closes the drawer", async () => {
    const user = userEvent.setup()
    renderSidebar()
    await user.click(
      screen.getByRole("button", { name: "Open navigation", exact: true })
    )
    const dialog = screen.getByRole("dialog")
    await user.click(
      within(dialog).getByRole("link", { name: "Routing", exact: true })
    )
    expect(testPath()).toBe("/routing")
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
    render(
      <MemoryRouter initialEntries={["/playground"]}>
        <Sidebar />
      </MemoryRouter>
    )
    expect(asideEl().className).toMatch(/w-16/)
  })

  it("stored '0' starts the uncontrolled sidebar expanded", () => {
    window.localStorage.setItem(STORAGE_KEY, "0")
    render(
      <MemoryRouter initialEntries={["/playground"]}>
        <Sidebar />
      </MemoryRouter>
    )
    expect(asideEl().className).not.toMatch(/w-16/)
  })

  it("a corrupt stored value falls back to expanded without throwing", () => {
    window.localStorage.setItem(STORAGE_KEY, "banana")
    expect(() =>
      render(
        <MemoryRouter initialEntries={["/playground"]}>
          <Sidebar />
        </MemoryRouter>
      )
    ).not.toThrow()
    expect(asideEl().className).not.toMatch(/w-16/)
  })

  it("uncontrolled toggle writes '1' then '0' through localStorage", async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={["/playground"]}>
        <Sidebar />
      </MemoryRouter>
    )
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
      <MemoryRouter initialEntries={["/playground"]}>
        <Sidebar
          defaultCollapsed
        />
      </MemoryRouter>
    )
    expect(asideEl().className).toMatch(/w-16/)
  })

  it("controlled collapsed prop wins over a stored '1'", () => {
    window.localStorage.setItem(STORAGE_KEY, "1")
    render(
      <MemoryRouter initialEntries={["/playground"]}>
        <Sidebar
          collapsed={false}
          onCollapsedChange={() => {}}
        />
      </MemoryRouter>
    )
    expect(asideEl().className).not.toMatch(/w-16/)
  })

  it("a throwing store never breaks render", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("storage denied")
    })
    expect(() =>
      render(
        <MemoryRouter initialEntries={["/playground"]}>
          <Sidebar />
        </MemoryRouter>
      )
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
      <MemoryRouter initialEntries={["/playground"]}>
        <Sidebar
          onCollapsedChange={onCollapsedChange}
        />
      </MemoryRouter>
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
