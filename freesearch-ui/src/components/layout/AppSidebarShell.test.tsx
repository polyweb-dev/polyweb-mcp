import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import App from "@/App"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

/**
 * C3-REWORK App shell — BDD Acceptance (Red phase) for AC-SB-8.
 *
 * Plan: App.tsx becomes a flex-row shell (Sidebar + main). Sidebar owns the
 * six workspaces; PillTabs/views/theme stay intact; no router/<a>/tab roles.
 *
 * AC mapping (all AC-SB-8):
 *   AC-SB-8a  App renders a flex-row shell holding <aside> + <main>.
 *   AC-SB-8b  The legacy <header> topbar is gone.
 *   AC-SB-8c  All six sidebar buttons (by accessible name) swap the main view
 *             to its exact heading — views stay intact.
 *   AC-SB-8d  Shell keeps the plain-button contract: no links, no tab roles,
 *             no router dependency, URL never changes.
 *   AC-SB-8e  PillTabs gold standard untouched (Routing + Settings pill tabs).
 *   AC-SB-8f  App source wires the Sidebar into a flex-row shell and exposes
 *             the collapse toggle.
 */

const testDir = import.meta.dirname
const appSource = readFileSync(path.resolve(testDir, "../../App.tsx"), "utf8")
const packageJsonRaw = readFileSync(
  path.resolve(testDir, "../../../package.json"),
  "utf8"
)
const packageJson = JSON.parse(packageJsonRaw) as {
  dependencies?: Record<string, string>
  devDependencies?: Record<string, string>
}

function renderApp() {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    return err(404, { detail: "unhandled test route" })
  })
  return render(<App />)
}

const EXPECTED_VIEWS: Array<{ button: string; heading: string }> = [
  { button: "Playground", heading: "Search Playground" },
  { button: "Providers", heading: "Providers" },
  { button: "Routing", heading: "Routing" },
  { button: "Usage", heading: "Usage" },
  { button: "Activity", heading: "Activity" },
  { button: "Settings", heading: "Settings" },
]

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("AC-SB-8a: App is a flex-row shell with aside + main", () => {
  it("renders the sidebar aside and the main landmark", async () => {
    renderApp()
    expect(document.querySelector("aside")).not.toBeNull()
    expect(screen.getByRole("main")).toBeInTheDocument()
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Search Playground" })
      ).toBeInTheDocument()
    })
  })

  it("shell lays out horizontally (flex-row), not the legacy flex-col stack", () => {
    renderApp()
    const aside = document.querySelector("aside")
    expect(aside).not.toBeNull()
    const shell = aside!.parentElement as HTMLElement
    expect(shell.className).toMatch(/flex/)
    expect(shell.className).toMatch(/flex-row/)
    expect(shell.className).not.toMatch(/flex-col/)
  })

  it("aside and main share the same horizontal shell", () => {
    renderApp()
    const shell = (document.querySelector("aside") as HTMLElement)
      .parentElement as HTMLElement
    expect(shell.className).toMatch(/flex-row/)
    expect(shell.contains(screen.getByRole("main"))).toBe(true)
  })
})

describe("AC-SB-8b: legacy header topbar is gone", () => {
  it("renders no <header> element", () => {
    renderApp()
    expect(document.querySelector("header")).toBeNull()
  })

  it("App source no longer renders the Header topbar", () => {
    expect(appSource.includes("<Header")).toBe(false)
    expect(appSource).not.toMatch(/from\s+["']@\/components\/layout\/Header["']/)
  })
})

describe("AC-SB-8c: six sidebar buttons swap intact views", () => {
  it("sidebar exposes all six workspaces by accessible name", () => {
    renderApp()
    const nav = screen.getByRole("navigation", { name: "Primary" })
    for (const { button } of EXPECTED_VIEWS) {
      expect(
        within(nav).getByRole("button", { name: button, exact: true })
      ).toBeInTheDocument()
    }
  })

  it.each(EXPECTED_VIEWS)(
    "sidebar '$button' shows the '$heading' view",
    async ({ button, heading }) => {
      const user = userEvent.setup()
      renderApp()
      await user.click(
        within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
          "button",
          { name: button, exact: true }
        )
      )
      await waitFor(() => {
        expect(
          within(screen.getByRole("main")).getByRole("heading", {
            name: heading,
          })
        ).toBeInTheDocument()
      })
    }
  )

  it("full click-through visits every view with exactly one active marker", async () => {
    const user = userEvent.setup()
    renderApp()
    for (const { button, heading } of EXPECTED_VIEWS) {
      await user.click(
        within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
          "button",
          { name: button, exact: true }
        )
      )
      await waitFor(() => {
        expect(
          screen.getByRole("heading", { name: heading })
        ).toBeInTheDocument()
      })
      expect(
        document.querySelectorAll('aside [aria-current="page"]')
      ).toHaveLength(1)
    }
  })
})

describe("AC-SB-8d: shell keeps the plain-button contract", () => {
  it("sidebar has no links and no tab roles", () => {
    renderApp()
    const aside = document.querySelector("aside") as HTMLElement
    expect(within(aside).queryByRole("link")).not.toBeInTheDocument()
    expect(aside.querySelector("a")).toBeNull()
    expect(within(aside).queryByRole("tab")).not.toBeInTheDocument()
    expect(within(aside).queryByRole("tablist")).not.toBeInTheDocument()
    expect(within(aside).queryByRole("tabpanel")).not.toBeInTheDocument()
  })

  it("switching views never changes the URL and adds no router", async () => {
    const user = userEvent.setup()
    renderApp()
    const before = window.location.href
    for (const { button } of EXPECTED_VIEWS) {
      await user.click(
        within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
          "button",
          { name: button, exact: true }
        )
      )
    }
    expect(window.location.href).toBe(before)
    expect(window.location.pathname).toBe("/")
    const allDeps = {
      ...(packageJson.dependencies ?? {}),
      ...(packageJson.devDependencies ?? {}),
    }
    expect(
      Object.keys(allDeps).filter((name) => /router|wouter/i.test(name))
    ).toEqual([])
    expect(appSource).not.toMatch(/react-router|wouter/i)
  })
})

describe("AC-SB-8e: PillTabs gold standard untouched", () => {
  it("Routing view still exposes Strategy/Simulator/Ranks/Resilience pill tabs", async () => {
    const user = userEvent.setup()
    renderApp()
    await user.click(
      within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
        "button",
        { name: "Routing", exact: true }
      )
    )
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Routing" })
      ).toBeInTheDocument()
    })
    const pillList = document.querySelector(
      '[data-slot="tabs-list"][data-variant="pill"]'
    )
    expect(pillList).not.toBeNull()
    expect(
      within(pillList as HTMLElement)
        .getAllByRole("tab")
        .map((t) => t.textContent)
    ).toEqual(["Strategy", "Simulator", "Ranks", "Resilience"])
  })

  it("Settings view still exposes Providers/Keys/Failover pill tabs", async () => {
    const user = userEvent.setup()
    renderApp()
    await user.click(
      within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
        "button",
        { name: "Settings", exact: true }
      )
    )
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Settings" })
      ).toBeInTheDocument()
    })
    const pillList = document.querySelector(
      '[data-slot="tabs-list"][data-variant="pill"]'
    )
    expect(pillList).not.toBeNull()
    expect(
      within(pillList as HTMLElement)
        .getAllByRole("tab")
        .map((t) => t.textContent)
    ).toEqual(["Providers", "Keys", "Failover"])
  })
})

describe("AC-SB-8f: App source wires Sidebar into the flex-row shell", () => {
  it("App source imports and renders the Sidebar", () => {
    expect(appSource).toMatch(
      /from\s+["']@\/components\/layout\/Sidebar["']/
    )
    expect(appSource.includes("<Sidebar")).toBe(true)
  })

  it("App source declares the horizontal shell", () => {
    expect(appSource).toMatch(/flex-row/)
  })

  it("App exposes the sidebar collapse toggle", async () => {
    const user = userEvent.setup()
    renderApp()
    const toggle = screen.getByRole("button", {
      name: "Collapse sidebar",
      exact: true,
    })
    expect(toggle).toBeInTheDocument()
    await user.click(toggle)
    expect(
      (document.querySelector("aside") as HTMLElement).className
    ).toMatch(/w-16/)
  })
})
