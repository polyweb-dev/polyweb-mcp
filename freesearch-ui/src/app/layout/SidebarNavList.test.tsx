import { afterEach, describe, expect, it, vi } from "vitest"
import { screen, within } from "@testing-library/react"
import { NavList } from "@/app/layout/SidebarNavList"
import { renderAuthenticated } from "@/test/renderAuthenticated"
import {
  adminAccountFixture,
  agentAccountFixture,
  developerAccountFixture,
} from "@/test/authFixtures"

const ADMIN_LABELS = [
  "Playground",
  "Routing",
  "Usage",
  "Activity",
  "Settings",
  "Account",
  "Admin",
]

const ADMIN_HREFS = [
  "/playground",
  "/routing",
  "/usage",
  "/activity",
  "/settings",
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

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("NavList role filter", () => {
  it("shows all seven links in order with exact hrefs for admin", () => {
    renderAuthenticated(<NavList collapsed={false} />, {
      account: adminAccountFixture(),
    })

    const links = navLinks()
    expect(links).toHaveLength(7)
    expect(ariaLabels(links)).toEqual(ADMIN_LABELS)
    expect(links.map((link) => link.getAttribute("href"))).toEqual(ADMIN_HREFS)
    expect(links[0]?.getAttribute("title")).toBeNull()
  })

  it("shows six links without Admin for developer", () => {
    renderAuthenticated(<NavList collapsed={false} />, {
      account: developerAccountFixture(),
    })

    const links = navLinks()
    expect(links).toHaveLength(6)
    expect(ariaLabels(links)).toEqual([
      "Playground",
      "Routing",
      "Usage",
      "Activity",
      "Settings",
      "Account",
    ])
    expect(
      screen.queryByRole("link", { name: "Admin" })
    ).not.toBeInTheDocument()
  })

  it("shows exactly Playground, Activity, and Account for agent", () => {
    renderAuthenticated(<NavList collapsed={false} />, {
      account: agentAccountFixture(),
    })

    const links = navLinks()
    expect(links).toHaveLength(3)
    expect(ariaLabels(links)).toEqual(["Playground", "Activity", "Account"])
    expect(
      screen.queryByRole("link", { name: "Routing" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("link", { name: "Settings" })
    ).not.toBeInTheDocument()
  })

  it("points the Admin link at /admin/users", () => {
    renderAuthenticated(<NavList collapsed={false} />, {
      account: adminAccountFixture(),
    })

    expect(
      screen.getByRole("link", { name: "Admin" })
    ).toHaveAttribute("href", "/admin/users")
  })
})

describe("NavList collapsed mode", () => {
  it("keeps every aria-label and title without visible text", () => {
    renderAuthenticated(<NavList collapsed />, {
      account: adminAccountFixture(),
    })

    const links = navLinks()
    expect(links).toHaveLength(7)
    for (const label of ADMIN_LABELS) {
      const link = screen.getByRole("link", { name: label })
      expect(link.getAttribute("aria-label")).toBe(label)
      expect(link.getAttribute("title")).toBe(label)
      expect(link.textContent).toBe("")
    }
    expect(ariaLabels(links)).toEqual(ADMIN_LABELS)
  })
})
