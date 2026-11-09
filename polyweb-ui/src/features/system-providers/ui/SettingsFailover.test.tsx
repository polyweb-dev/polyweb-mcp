import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { PolywebProvider } from "@/context/PolywebContext"
import { ADMIN_ACCOUNT_ID, DEVELOPER_ACCOUNT_ID } from "@/test/authFixtures"
import { SettingsView } from "./SettingsView"
import { installFetchStub, ok, err, type FetchStub } from "@/test/fetchMock"
import {
  allProvidersFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

/**
 * Failover tab: the one place the installation's fallback policy is set.
 *
 * The backend persists and enforces exactly two values (routing config
 * `fallback_policy` chained/first_only and `max_attempts`); execution tries
 * the next ranked route on any provider error up to that many routes. The tab
 * shows only those two controls, with one-line descriptions and no developer
 * notes. The former per-condition switches (429 / timeout / 5xx) were never
 * persisted and are gone, as is the duplicated Resilience policy block.
 */

const testDir = import.meta.dirname
const failoverSource = readFileSync(path.resolve(testDir, "./SettingsFailover.tsx"), "utf8")
const settingsViewSource = readFileSync(path.resolve(testDir, "./SettingsView.tsx"), "utf8")
const providersSource = readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8")
const indexCssSource = readFileSync(path.resolve(testDir, "../../../index.css"), "utf8")

const norm = (value: string): string => value.toLowerCase().replace(/\s+/g, "")

function renderSettings(canEdit = true): FetchStub {
  const policy = { fallback_policy: "chained", max_attempts: 3 }
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(policy)
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "PUT" && req.url === "/api/v1/routing/config") {
      return ok({ ...policy, ...((req.body as object) ?? {}) })
    }
    return err(404, { detail: "unhandled test route" })
  })
  render(
    <MemoryRouter>
      <PolywebProvider
        accountId={canEdit ? ADMIN_ACCOUNT_ID : DEVELOPER_ACCOUNT_ID}
        canReadControls
        canEditControls={canEdit}
      >
        <SettingsView />
      </PolywebProvider>
    </MemoryRouter>
  )
  return stub
}

async function openFailover() {
  // The fallback section sits under the provider table on the Providers view; there is no tab.
  await waitFor(() => {
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
  })
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "When a provider fails" })).toBeInTheDocument()
  })
}

function failoverSection(): HTMLElement {
  const section = screen.getByRole("heading", { name: "When a provider fails" }).closest("section")
  if (!section) throw new Error("Failover <section> not found around the heading")
  return section as HTMLElement
}

function routingConfigPuts(stub: FetchStub) {
  return stub.requests.filter((r) => r.method === "PUT" && r.url === "/api/v1/routing/config")
}

function classTokens(el: Element): string[] {
  return (el.getAttribute("class") ?? "").split(/\s+/).filter(Boolean)
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("SettingsFailover: layout", () => {
  it("section spans the available width with no capped max-w", async () => {
    renderSettings()
    await openFailover()
    const tokens = classTokens(failoverSection())
    expect(tokens).toContain("w-full")
    expect(tokens).toContain("max-w-none")
    expect(tokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none")).toEqual([])
    expect(failoverSource).not.toMatch(/max-w-3xl/)
  })

  it("is the single place for the policy: rendered once under the provider table, no Failover tab", async () => {
    expect(providersSource).not.toMatch(/ResiliencePolicy/)
    expect(providersSource).toContain("<SettingsFailover />")
    expect(settingsViewSource).not.toContain("SettingsFailover")
    expect(failoverSource).not.toMatch(/SettingsProviders|ProviderTestModal/)
    renderSettings()
    await openFailover()
    expect(screen.getAllByRole("heading", { name: "When a provider fails" })).toHaveLength(1)
    expect(screen.queryByRole("tab", { name: "Failover" })).not.toBeInTheDocument()
  })
})

describe("SettingsFailover: only persisted, enforced controls", () => {
  it("shows the Fallback switch and Max attempts with one-line descriptions", async () => {
    renderSettings()
    await openFailover()
    const section = failoverSection()
    const switches = within(section).getAllByRole("switch")
    expect(switches.map((s) => s.getAttribute("aria-label"))).toEqual(["Fallback"])
    expect(switches[0]).toHaveAttribute("aria-checked", "true")
    // The row text does not repeat the section title.
    expect(within(section).getByText("Try the next provider in the project order")).toBeInTheDocument()
    expect(within(section).getByText("Max attempts", { exact: true })).toBeInTheDocument()
    expect(within(section).getByText("Number of providers for each request, first provider included")).toBeInTheDocument()
    expect(within(section).getByText("3", { exact: true })).toBeInTheDocument()
  })

  it("drops the session-only switches, the timeout row and every developer note", async () => {
    renderSettings()
    await openFailover()
    const text = failoverSection().textContent ?? ""
    for (const removed of [
      "Failover on rate limit",
      "Failover on timeout",
      "Failover on server error",
      "Cascade depth",
      "Timeout budget",
      "fallback hops",
      "single-shot",
      "Fallback chaining",
    ]) {
      expect(text).not.toContain(removed)
    }
    expect(text).not.toMatch(/session-only|not enforced|not exposed|persisted|backend/i)
    expect(document.body.textContent).not.toMatch(/3,\s?000\s?ms/)
  })
})

describe("SettingsFailover: writes", () => {
  it("turning Fallback off PUTs first_only, hides Max attempts and says one route is tried", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await openFailover()
    const fallback = screen.getByRole("switch", { name: "Fallback" })

    await user.click(fallback)
    await waitFor(() => expect(fallback).toHaveAttribute("aria-checked", "false"))
    expect(screen.queryByText("Max attempts", { exact: true })).not.toBeInTheDocument()
    expect(within(failoverSection()).getByText("Off: each request tries one provider")).toBeInTheDocument()
    expect(routingConfigPuts(stub).at(-1)?.body).toEqual({
      fallback_policy: "first_only",
      max_attempts: 3,
    })

    await user.click(fallback)
    await waitFor(() => expect(fallback).toHaveAttribute("aria-checked", "true"))
    expect(screen.getByText("Max attempts", { exact: true })).toBeInTheDocument()
    expect(routingConfigPuts(stub).at(-1)?.body).toEqual({
      fallback_policy: "chained",
      max_attempts: 3,
    })
  })

  it("the Max attempts stepper PUTs the new hop limit", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await openFailover()

    await user.click(screen.getByRole("button", { name: "Increase max attempts" }))
    // Scoped to the section: the provider ranks above are bare numbers too.
    await waitFor(() => expect(within(failoverSection()).getByText("4", { exact: true })).toBeInTheDocument())
    expect(routingConfigPuts(stub).at(-1)?.body).toEqual({
      fallback_policy: "chained",
      max_attempts: 4,
    })

    await user.click(screen.getByRole("button", { name: "Decrease max attempts" }))
    await waitFor(() => expect(within(failoverSection()).getByText("3", { exact: true })).toBeInTheDocument())
    expect(routingConfigPuts(stub).at(-1)?.body).toMatchObject({ max_attempts: 3 })
  })

  it("Space on the focused Fallback switch toggles it", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await openFailover()
    const fallback = screen.getByRole("switch", { name: "Fallback" })
    expect(fallback.tagName).toBe("BUTTON")
    ;(fallback as HTMLElement).focus()
    await user.keyboard(" ")
    await waitFor(() => expect(fallback).toHaveAttribute("aria-checked", "false"))
    expect(routingConfigPuts(stub)).toHaveLength(1)
  })
})

describe("SettingsFailover Developer read-only (canReadControls, no edit)", () => {
  it("shows the stored values as text, no switches or steppers, and sends no writes", async () => {
    const stub = renderSettings(false)
    await openFailover()
    const section = failoverSection()
    expect(within(section).getByText("Fallback", { exact: true })).toBeInTheDocument()
    expect(within(section).getByText("On", { exact: true })).toBeInTheDocument()
    expect(within(section).getByText("3", { exact: true })).toBeInTheDocument()
    expect(within(section).queryByRole("switch")).not.toBeInTheDocument()
    expect(within(section).queryByRole("button", { name: /max attempts/i })).not.toBeInTheDocument()
    expect(
      stub.requests.filter((r) => r.method === "PATCH" || r.method === "PUT" || r.method === "POST")
    ).toHaveLength(0)
  })
})

describe("SettingsFailover guards", () => {
  it("Carbon Black theme tokens untouched (#1e1e1e scale + #007acc, no oklch)", () => {
    expect(norm(indexCssSource).includes("#1e1e1e")).toBe(true)
    expect(norm(indexCssSource).includes("#007acc")).toBe(true)
    expect(norm(indexCssSource).includes("oklch(")).toBe(false)
  })

  it("imports no backend/python paths and no absolute backend literals", () => {
    expect(failoverSource).not.toMatch(/\.py["']/)
    expect(failoverSource).not.toMatch(/src\/polyweb/)
    expect(failoverSource).not.toMatch(/127\.0\.0\.1:8001|localhost:8001/)
  })
})
