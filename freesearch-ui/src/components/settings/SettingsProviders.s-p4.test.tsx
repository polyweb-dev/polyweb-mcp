import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, within, waitFor } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { SettingsView } from "./SettingsView"
import { installFetchStub, ok, err, type FetchStub } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

/**
 * S-P4 Providers wasted space — BDD Acceptance (RED phase).
 *
 * User bullet (verbatim): "Wasted space". Read-only:
 * .agents/FEEDBACK/UI/feedback.md L24. SEE image yourself:
 * .agents/FEEDBACK/UI/image-4.png (registry hugs left ~50%, right void).
 *
 * BUG image-4.png shows the Provider registry table hugging the left ~50%
 * of the Settings main column with an empty void on the right — the
 * section is capped at max-w-4xl so it never fills the available width at
 * desktop viewports.
 *
 * Plan under test (ONLY SettingsProviders.tsx, freesearch-ui/ ONLY):
 *   L62 section (max-w-4xl -> w-full max-w-none) +
 *   L70 frame (+w-full max-w-none, KEEP overflow-hidden). No other changes.
 *
 * AC mapping:
 *   S-P4-1  available-width section — <section> carries w-full + max-w-none
 *           and NO capped max-w (no max-w-4xl/3xl/5xl, no other max-w-*
 *           except max-w-none). Source + rendered DOM token assertions.
 *           RED: current L62 is `space-y-4 max-w-4xl` (no w-full, no
 *           max-w-none, capped) so every S-P4-1 assertion FAILS cleanly.
 *   S-P4-2  available-width frame — L70 frame div gains w-full + max-w-none
 *           while KEEPING overflow-hidden (+ rounded-lg + border). Source +
 *           rendered DOM token assertions. RED: current frame is
 *           `overflow-hidden rounded-lg border ...` with no w-full/max-w-none,
 *           so the w-full/max-w-none assertions FAIL cleanly while the
 *           KEEP-overflow-hidden assertions PASS (the keep-guard).
 *   S-P4-3  1440px fills main — at window.innerWidth 1440 the rendered
 *           section + frame still carry w-full max-w-none with no cap, the
 *           single 7-row table with min-w-[880px] is present inside the
 *           w-full scroller. jsdom has no layout engine so the executable
 *           proxy is the width-class invariant at the 1440px viewport (same
 *           structural-invariant approach as S-P1-2/S-P2-3); pixel proof
 *           needs a browser (Playwright). RED: fails on the missing
 *           w-full/max-w-none tokens, exactly like S-P4-1/S-P4-2.
 *   S-P4-4  responsive-scroll preserved (GREEN in Red phase) — the SAME
 *           ui/table table-container scroller (data-slot + overflow-x-auto +
 *           w-full) wraps the table, Table keeps min-w-[880px], all th/td
 *           keep whitespace-nowrap, and the 375px viewport keeps the nowrap
 *           cells inside the horizontal scroller with no flex-wrap. These
 *           MUST pass before and after (the plan adds width, never removes
 *           the scroller).
 *   S-P4-5  regression guards (must stay GREEN before and after):
 *           S-P1 table invariant (single ui/table, exact headers, 7x5,
 *           scroller, nowrap), S-P2 ranks (P1..P7 never P100 + Dispatch
 *           order tooltip + shrink-0/min-w + px-3 + arrow boundaries),
 *           S-P3 Test affordance (ui/button outline sm box, states, one
 *           POST), SettingsView pills (Providers/Keys/Failover pill
 *           variant), Carbon Black tokens, NO ProviderMatrix merge,
 *           sibling sections untouched (KeyVault/Failover keep their caps),
 *           freesearch-ui ONLY (no backend/python imports).
 *
 * RED expectation:
 *   S-P4-1 FAILS cleanly (section capped max-w-4xl, no w-full/max-w-none).
 *   S-P4-2 FAILS cleanly on w-full/max-w-none (overflow-hidden keep PASSES).
 *   S-P4-3 FAILS cleanly (width tokens missing at 1440px).
 *   S-P4-4 + S-P4-5 PASS (scroller + prior bullets intact).
 */

const testDir = import.meta.dirname
const settingsSource = readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8")
const indexCssSource = readFileSync(path.resolve(testDir, "../../index.css"), "utf8")
const providerMatrixSource = readFileSync(
  path.resolve(testDir, "../providers/ProviderMatrix.tsx"),
  "utf8"
)
const keyVaultSource = readFileSync(path.resolve(testDir, "./SettingsKeyVault.tsx"), "utf8")
const failoverSource = readFileSync(path.resolve(testDir, "./SettingsFailover.tsx"), "utf8")

const norm = (value: string): string => value.toLowerCase().replace(/\s+/g, "")

const SEED_PROVIDER_NAMES = [
  "Brave Search",
  "Keenable",
  "Tavily",
  "Exa",
  "Firecrawl",
  "You.com",
  "Parallel",
] as const

const EXPECTED_HEADERS = ["Provider", "Global", "Search", "Fetch", "Test"] as const
const EXPECTED_RANKS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7"] as const

const ORIGINAL_INNER_WIDTH = window.innerWidth

function renderSettings(): FetchStub {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "PATCH" && req.url.startsWith("/api/v1/providers/")) {
      const backendId = req.url.split("/").at(-1) ?? "unknown"
      const wire = allProvidersFixture().find((p) => p.provider_id === backendId)
      return ok({ ...(wire ?? allProvidersFixture()[0]), ...((req.body as object) ?? {}) })
    }
    if (req.method === "POST" && req.url.endsWith("/test")) {
      return ok({
        provider: "brave",
        ok: true,
        status: "healthy",
        latency_ms: 142,
        checked_at: "2026-09-06T10:04:00Z",
        detail: null,
      })
    }
    return err(404, { detail: "unhandled test route" })
  })
  render(
    <FreeSearchProvider>
      <SettingsView />
    </FreeSearchProvider>
  )
  return stub
}

async function waitForProviders() {
  await waitFor(() => {
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
  })
}

/** Exact class-token list for an element (Tailwind tokens are whitespace-separated). */
function classTokens(el: Element): string[] {
  return (el.getAttribute("class") ?? "").split(/\s+/).filter(Boolean)
}

/** L62 <section className="..."> token list from source. */
function sectionClassFromSource(): string[] {
  const match = settingsSource.match(/<section\s+className="([^"]*)"/)
  if (!match) throw new Error("<section className> not found in SettingsProviders.tsx (L62 moved?)")
  return match[1].split(/\s+/).filter(Boolean)
}

/** L70 frame <div className="...overflow-hidden..."> token list from source. */
function frameClassFromSource(): string[] {
  const match = settingsSource.match(/<div\s+className="([^"]*overflow-hidden[^"]*)"/)
  if (!match) {
    throw new Error(
      "Frame <div> with overflow-hidden not found in SettingsProviders.tsx (L70 moved?)"
    )
  }
  return match[1].split(/\s+/).filter(Boolean)
}

function providerSection(): HTMLElement {
  const table = screen.getByRole("table")
  const section = table.closest("section")
  if (!section) throw new Error("Provider registry <section> not found around the table")
  return section as HTMLElement
}

function providerFrame(): HTMLElement {
  const table = screen.getByRole("table")
  const container = table.closest('[data-slot="table-container"]')
  if (!container) throw new Error("ui/table container [data-slot=table-container] must wrap the table")
  const frame = container.parentElement
  if (!frame) throw new Error("Frame <div> (table-container parent) not found")
  return frame as HTMLElement
}

function findProviderRowTr(provider: string): HTMLTableRowElement {
  const nameEl = screen.getByText(provider, { exact: true })
  const tr = nameEl.closest("tr")
  if (!tr) {
    throw new Error(
      `Provider table row <tr> not found for ${provider} — S-P1 table migration missing`
    )
  }
  return tr as HTMLTableRowElement
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  ;(window.innerWidth as number) = ORIGINAL_INNER_WIDTH
  window.dispatchEvent(new Event("resize"))
})

// ---------------------------------------------------------------------------
// S-P4-1: section spans the available width (RED)
// ---------------------------------------------------------------------------

describe("S-P4-1: registry section spans available width (w-full max-w-none, no cap)", () => {
  it("section source carries w-full", () => {
    expect(
      sectionClassFromSource(),
      `L62 section must carry w-full; got ${JSON.stringify(sectionClassFromSource())}`
    ).toContain("w-full")
  })

  it("section source carries max-w-none", () => {
    expect(
      sectionClassFromSource(),
      `L62 section must carry max-w-none; got ${JSON.stringify(sectionClassFromSource())}`
    ).toContain("max-w-none")
  })

  it("section source has no capped max-w (no max-w-4xl/3xl/5xl, no other max-w-* but max-w-none)", () => {
    const tokens = sectionClassFromSource()
    expect(tokens, "L62 section must not keep max-w-4xl").not.toContain("max-w-4xl")
    expect(tokens, "section must not be capped at max-w-3xl").not.toContain("max-w-3xl")
    expect(tokens, "section must not be capped at max-w-5xl").not.toContain("max-w-5xl")
    const capped = tokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none")
    expect(capped, `section must have no capped max-w-*, got ${JSON.stringify(tokens)}`).toEqual([])
  })

  it("rendered section carries w-full + max-w-none with no capped max-w", async () => {
    renderSettings()
    await waitForProviders()
    const tokens = classTokens(providerSection())
    expect(tokens, `rendered section must carry w-full; got ${JSON.stringify(tokens)}`).toContain(
      "w-full"
    )
    expect(
      tokens,
      `rendered section must carry max-w-none; got ${JSON.stringify(tokens)}`
    ).toContain("max-w-none")
    const capped = tokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none")
    expect(capped, `rendered section must have no capped max-w-*; got ${JSON.stringify(tokens)}`).toEqual(
      []
    )
  })
})

// ---------------------------------------------------------------------------
// S-P4-2: frame spans available width, keeps overflow-hidden (RED on width)
// ---------------------------------------------------------------------------

describe("S-P4-2: table frame spans available width and keeps overflow-hidden", () => {
  it("frame source carries w-full", () => {
    expect(
      frameClassFromSource(),
      `L70 frame must carry w-full; got ${JSON.stringify(frameClassFromSource())}`
    ).toContain("w-full")
  })

  it("frame source carries max-w-none", () => {
    expect(
      frameClassFromSource(),
      `L70 frame must carry max-w-none; got ${JSON.stringify(frameClassFromSource())}`
    ).toContain("max-w-none")
  })

  it("frame source KEEPS overflow-hidden (responsive scroll contract)", () => {
    expect(
      frameClassFromSource(),
      `L70 frame must KEEP overflow-hidden; got ${JSON.stringify(frameClassFromSource())}`
    ).toContain("overflow-hidden")
  })

  it("frame source keeps the rounded bordered card (rounded-lg + border)", () => {
    const tokens = frameClassFromSource()
    expect(tokens, `frame must keep rounded-lg; got ${JSON.stringify(tokens)}`).toContain(
      "rounded-lg"
    )
    expect(tokens.some((t) => t === "border" || t.startsWith("border-"))).toBe(true)
  })

  it("rendered frame carries w-full + max-w-none and keeps overflow-hidden", async () => {
    renderSettings()
    await waitForProviders()
    const tokens = classTokens(providerFrame())
    expect(tokens, `rendered frame must carry w-full; got ${JSON.stringify(tokens)}`).toContain(
      "w-full"
    )
    expect(
      tokens,
      `rendered frame must carry max-w-none; got ${JSON.stringify(tokens)}`
    ).toContain("max-w-none")
    expect(
      tokens,
      `rendered frame must KEEP overflow-hidden; got ${JSON.stringify(tokens)}`
    ).toContain("overflow-hidden")
  })
})

// ---------------------------------------------------------------------------
// S-P4-3: 1440px viewport fills the main column (RED on width)
// ---------------------------------------------------------------------------

describe("S-P4-3: 1440px viewport fills the Settings main column", () => {
  it("at 1440px the section + frame still carry w-full max-w-none with no cap", async () => {
    ;(window.innerWidth as number) = 1440
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    const sectionTokens = classTokens(providerSection())
    const frameTokens = classTokens(providerFrame())
    expect(
      sectionTokens,
      `1440px section must carry w-full; got ${JSON.stringify(sectionTokens)}`
    ).toContain("w-full")
    expect(
      sectionTokens,
      `1440px section must carry max-w-none; got ${JSON.stringify(sectionTokens)}`
    ).toContain("max-w-none")
    expect(
      sectionTokens.filter((t) => /^max-w-/.test(t) && t !== "max-w-none"),
      `1440px section must have no capped max-w-*; got ${JSON.stringify(sectionTokens)}`
    ).toEqual([])
    expect(frameTokens, `1440px frame must carry w-full; got ${JSON.stringify(frameTokens)}`).toContain(
      "w-full"
    )
    expect(
      frameTokens,
      `1440px frame must carry max-w-none; got ${JSON.stringify(frameTokens)}`
    ).toContain("max-w-none")
  })

  it("at 1440px the single 7-row table with min-w-[880px] sits inside the w-full scroller", async () => {
    ;(window.innerWidth as number) = 1440
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("table")).toHaveLength(1)
    const table = screen.getByRole("table")
    expect(table.querySelectorAll("tbody tr")).toHaveLength(7)
    expect(table.className).toMatch(/min-w-\[880px\]/)
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table scroller must wrap the table at 1440px").not.toBeNull()
    expect(container!.className).toMatch(/w-full/)
    expect(container!.className).toMatch(/overflow-x-auto/)
  })
})

// ---------------------------------------------------------------------------
// S-P4-4: responsive scroll preserved (GREEN in Red phase)
// ---------------------------------------------------------------------------

describe("S-P4-4: responsive horizontal scroll preserved (no wrap, 375px scrolls)", () => {
  it("table container is the same ui/table scroller (data-slot + overflow-x-auto + w-full)", async () => {
    renderSettings()
    await waitForProviders()
    const table = screen.getByRole("table")
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table container [data-slot=table-container] must wrap the table").not.toBeNull()
    expect(container!.className).toMatch(/overflow-x-auto/)
    expect(container!.className).toMatch(/w-full/)
    expect(table.className).toMatch(/w-full/)
  })

  it("Table keeps min-w-[880px] in source and in the DOM", async () => {
    expect(settingsSource).toMatch(/min-w-\[880px\]/)
    renderSettings()
    await waitForProviders()
    expect(screen.getByRole("table").className).toMatch(/min-w-\[880px\]/)
  })

  it("all header and body cells keep whitespace-nowrap (no wrapping)", async () => {
    renderSettings()
    await waitForProviders()
    const table = screen.getByRole("table")
    const cells = Array.from(table.querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(5 + 7 * 5)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
  })

  it("375px viewport keeps nowrap cells inside the horizontal scroller", async () => {
    ;(window.innerWidth as number) = 375
    window.dispatchEvent(new Event("resize"))
    renderSettings()
    await waitForProviders()
    const table = screen.getByRole("table")
    const container = table.closest('[data-slot="table-container"]') as HTMLElement
    expect(container.className).toMatch(/overflow-x-auto/)
    expect(table.className).toMatch(/min-w-\[880px\]/)
    const cells = Array.from(table.querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(5 + 7 * 5)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
    expect(settingsSource.includes("flex-wrap")).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// S-P4-5: regression guards — S-P1/S-P2/S-P3 + SettingsView stay Green
// ---------------------------------------------------------------------------

describe("S-P4-5: no regression — S-P1 table, S-P2 ranks, S-P3 buttons, SettingsView", () => {
  it("S-P1 table invariant: single table, Provider|Global|Search|Fetch|Test, 7x5, scroller, nowrap", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("table")).toHaveLength(1)
    const table = screen.getByRole("table")
    expect(
      Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent?.trim() ?? "")
    ).toEqual([...EXPECTED_HEADERS])
    const rows = Array.from(table.querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(7)
    for (const row of rows) {
      expect(row.children).toHaveLength(5)
    }
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table scroller must wrap the table").not.toBeNull()
    expect(container!.className).toMatch(/overflow-x-auto/)
    const cells = Array.from(table.querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(5 + 7 * 5)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
  })

  it("S-P2 ranks preserved: P1..P7 never P100 with dispatch-order tooltips", async () => {
    renderSettings()
    await waitForProviders()
    for (let rank = 1; rank <= 7; rank += 1) {
      expect(screen.queryAllByText(`P${rank}`, { exact: true })).toHaveLength(1)
      expect(screen.getByText(`P${rank}`, { exact: true }).getAttribute("title")).toBe(
        `Dispatch order ${rank} of 7`
      )
    }
    expect(screen.queryByText("P100", { exact: true })).toBeNull()
    expect(settingsSource).not.toContain("P{provider.priority}")
    expect(settingsSource).toContain("Dispatch order")
  })

  it("S-P2 indicator + arrows intact: shrink-0/min-w floor, px-3, lucide up/down with boundaries", async () => {
    renderSettings()
    await waitForProviders()
    expect(settingsSource).toContain("lucide-react")
    expect(settingsSource).toContain("ArrowUp")
    expect(settingsSource).toContain("ArrowDown")
    for (let rank = 1; rank <= 7; rank += 1) {
      const label = screen.getByText(`P${rank}`, { exact: true })
      const indicator = label.parentElement as HTMLElement | null
      expect(indicator, `P${rank} indicator wrapper must exist`).not.toBeNull()
      expect(indicator!.className).toMatch(/shrink-0/)
      expect(indicator!.className).toMatch(/min-w-/)
    }
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      expect((row.children[0] as HTMLElement).className).toMatch(/px-3/)
      expect(
        screen.getByRole("button", { name: `Move ${name} priority up` })
      ).toBeInTheDocument()
      expect(
        screen.getByRole("button", { name: `Move ${name} priority down` })
      ).toBeInTheDocument()
    }
    expect(
      screen.getByRole("button", { name: "Move Brave Search priority up" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Parallel priority down" })
    ).toBeDisabled()
    expect(screen.getAllByText([...EXPECTED_RANKS][0], { exact: true })).toHaveLength(1)
  })

  it("S-P3 Test buttons keep the ui/button outline affordance with exact labels", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const btn = screen.getByRole("button", { name: `${name} connection` })
      expect(btn.getAttribute("data-slot")).toBe("button")
      expect(btn.className).toMatch(/border/)
      expect(btn.className).toMatch(/rounded/)
      expect(btn.className).toMatch(/px-\d|py-\d/)
      expect(btn.textContent?.trim()).toBe("Test")
      expect(btn.getAttribute("type")).toBe("button")
      expect(btn.getAttribute("aria-label")).toBe(`${name} connection`)
    }
    expect(settingsSource).toContain("@/components/ui/button")
  })

  it("SettingsView pills stay Providers/Keys/Failover on the pill variant", async () => {
    renderSettings()
    await waitForProviders()
    expect(screen.getAllByRole("tab")).toHaveLength(3)
    for (const label of ["Providers", "Keys", "Failover"]) {
      expect(screen.getByRole("tab", { name: new RegExp(`^${label}$`) })).toBeInTheDocument()
    }
    const pillList = document.querySelector('[data-slot="tabs-list"][data-variant="pill"]')
    expect(pillList, "pill tablist must exist").not.toBeNull()
    expect(
      within(pillList as HTMLElement)
        .getAllByRole("tab")
        .map((t) => t.textContent)
    ).toEqual(["Providers", "Keys", "Failover"])
    expect(
      document.querySelectorAll('[data-slot="tabs-list"][data-variant="line"]')
    ).toHaveLength(0)
  })

  it("Carbon Black theme tokens untouched (#1e1e1e scale + #007acc, no oklch)", () => {
    expect(norm(indexCssSource).includes("#1e1e1e")).toBe(true)
    expect(norm(indexCssSource).includes("#252526")).toBe(true)
    expect(norm(indexCssSource).includes("#3e3e42")).toBe(true)
    expect(norm(indexCssSource).includes("#007acc")).toBe(true)
    expect(norm(indexCssSource).includes("oklch(")).toBe(false)
  })

  it("scope: Keys spans full width (K1) while Failover keeps its cap", () => {
    expect(keyVaultSource).not.toMatch(/max-w-4xl/)
    expect(keyVaultSource).toMatch(/w-full/)
    expect(keyVaultSource).toMatch(/max-w-none/)
    expect(failoverSource).toMatch(/max-w-3xl/)
  })

  it("NO page merge: SettingsProviders never imports ProviderMatrix", () => {
    expect(settingsSource).not.toMatch(/ProviderMatrix/)
    expect(providerMatrixSource).not.toContain("SettingsProviders")
  })

  it("freesearch-ui ONLY: SettingsProviders imports no backend/python paths", () => {
    expect(settingsSource).not.toMatch(/\.py["']/)
    expect(settingsSource).not.toMatch(/src\/freesearch/)
  })
})
