import { afterEach, describe, expect, it, vi } from "vitest"
import { screen, within } from "@testing-library/react"
import { NavList } from "@/app/layout/SidebarNavList"
import { renderAuthenticated } from "@/test/renderAuthenticated"
import { adminAccountFixture } from "@/test/authFixtures"
import {
  SETTINGS_READER_PERMISSIONS,
  SYSTEM_ADMIN_PERMISSIONS,
} from "@/test/accessFixtures"

const ADMIN_LABELS = [
  "Routing",
  "Provider usage",
  "Settings",
  "Projects",
  "Account",
  "Admin",
]

const ADMIN_HREFS = [
  "/routing",
  "/usage",
  "/settings",
  "/projects",
  "/account",
  "/admin/users",
]

function navLinks(): HTMLElement[] {
  return within(
    screen.getByRole("navigation", { name: "Primary" })
  ).getAllByRole("link")
}

function ariaLabels(links: HTMLElement[]): Array<string | null> {
  return links.map((link) => link.getAttribute("aria-label"))
}

function renderNav(systemPermissions: readonly string[] | undefined, collapsed = false) {
  return renderAuthenticated(<NavList collapsed={collapsed} />, {
    account: adminAccountFixture(),
    ...(systemPermissions === undefined ? {} : { systemPermissions }),
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("NavList permission filter", () => {
  it("shows all six links in order with exact hrefs for the system administrator", () => {
    renderNav(SYSTEM_ADMIN_PERMISSIONS)

    const links = navLinks()
    expect(links).toHaveLength(6)
    expect(ariaLabels(links)).toEqual(ADMIN_LABELS)
    expect(links.map((link) => link.getAttribute("href"))).toEqual(ADMIN_HREFS)
    expect(links[0]?.getAttribute("title")).toBeNull()
  })

  it("shows five links without Admin with system.settings.read only", () => {
    renderNav(SETTINGS_READER_PERMISSIONS)

    const links = navLinks()
    expect(links).toHaveLength(5)
    expect(ariaLabels(links)).toEqual([
      "Routing",
      "Provider usage",
      "Settings",
      "Projects",
      "Account",
    ])
    expect(
      screen.queryByRole("link", { name: "Admin" })
    ).not.toBeInTheDocument()
  })

  it("shows exactly Projects and Account without system permissions", () => {
    renderNav([])

    const links = navLinks()
    expect(links).toHaveLength(2)
    expect(ariaLabels(links)).toEqual(["Projects", "Account"])
    expect(screen.queryByRole("link", { name: "Playground" })).not.toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Activity" })).not.toBeInTheDocument()
    expect(
      screen.queryByRole("link", { name: "Routing" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("link", { name: "Settings" })
    ).not.toBeInTheDocument()
  })

  it("hides every gated link while the system access is unknown", () => {
    renderNav(undefined)

    expect(ariaLabels(navLinks())).toEqual(["Projects", "Account"])
  })

  it("shows Admin with system.settings.write alone, without the settings links", () => {
    renderNav(["system.settings.write"])

    expect(ariaLabels(navLinks())).toEqual(["Projects", "Account", "Admin"])
  })

  it("points the Admin link at /admin/users", () => {
    renderNav(SYSTEM_ADMIN_PERMISSIONS)

    expect(
      screen.getByRole("link", { name: "Admin" })
    ).toHaveAttribute("href", "/admin/users")
  })
})

describe("NavList collapsed mode", () => {
  it("keeps every aria-label and title without visible text", () => {
    renderNav(SYSTEM_ADMIN_PERMISSIONS, true)

    const links = navLinks()
    expect(links).toHaveLength(6)
    for (const label of ADMIN_LABELS) {
      const link = screen.getByRole("link", { name: label })
      expect(link.getAttribute("aria-label")).toBe(label)
      expect(link.getAttribute("title")).toBe(label)
      expect(link.textContent).toBe("")
    }
    expect(ariaLabels(links)).toEqual(ADMIN_LABELS)
  })
})
