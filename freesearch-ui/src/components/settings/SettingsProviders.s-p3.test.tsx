import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, within, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { SettingsView } from "./SettingsView"
import { installFetchStub, ok, err, deferred, type FetchStub } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

/**
 * S-P3 Test buttons look like actual buttons — BDD Acceptance (RED phase).
 *
 * User bullet (verbatim): "Make these test buttons look like actual buttons."
 * Read-only: .agents/FEEDBACK/UI/feedback.md L22. SEE image yourself:
 * .agents/FEEDBACK/UI/image-3.png (Test plain text, no affordance).
 *
 * BUG image-3.png shows every registry row with a bare muted "Test" text
 * label at the far right — no border, no rounded box, no padding, no
 * data-slot="button". It reads as plain text, not an affordance.
 *
 * Plan under test (ONLY SettingsProviders.tsx Test cell):
 *   bare button -> ui/button outline sm OR Button-like Carbon classes;
 *   states Test/Testing...+disabled, aria-label unchanged, type=button;
 *   no other changes. freesearch-ui/ ONLY.
 *
 * AC mapping:
 *   S-P3-1  affordance — every Test button exposes a real button box:
 *           (ui/button: data-slot="button" + outline border) OR
 *           (Carbon button-like: border + rounded + padding), and is NOT
 *           plain muted text. RED: current Test cell is a bare <button>
 *           with `text-[13px] text-[var(--muted)] hover:text-white ...`
 *           and no border/rounded/padding/data-slot, so all affordance
 *           assertions FAIL cleanly.
 *   S-P3-2  states preserved — initial `Test` + type="button" + exact
 *           aria-label `{name} connection`; click flips to `Testing...` +
 *           disabled with aria-label/type stable; exactly one POST to
 *           /api/v1/providers/{id}/test; flips back to `Test` + enabled
 *           with aria-label stable. GREEN in Red phase (contracts already
 *           hold; the restyle must not break them).
 *   S-P3-3  no-regression (must stay GREEN before and after): S-P1 table
 *           invariant (single ui/table, Provider|Global|Search|Fetch|Test,
 *           7x5, overflow-x-auto scroller, nowrap), S-P2 ranks (P1..P7 never
 *           P100 + Dispatch order tooltip + shrink-0/min-w + px-3 + arrow
 *           boundaries), Carbon Black tokens, NO ProviderMatrix merge,
 *           freesearch-ui ONLY. NOTE: S-P2-5 "no button restyle" covers ONLY
 *           the ArrowUp/ArrowDown arrows — this file MUST NOT assert no
 *           Button in file (Green adds ui/Button to the Test cell).
 *
 * RED expectation:
 *   S-P3-1 FAILS cleanly (no data-slot, no border/rounded/padding on the
 *   Test buttons). S-P3-2 + S-P3-3 PASS (baseline intact).
 */

const testDir = import.meta.dirname
const settingsSource = readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8")
const indexCssSource = readFileSync(path.resolve(testDir, "../../index.css"), "utf8")
const providerMatrixSource = readFileSync(
  path.resolve(testDir, "../providers/ProviderMatrix.tsx"),
  "utf8"
)

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

let testGate: Promise<Response> | null = null

function renderSettings(): FetchStub {
  testGate = null
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
      if (testGate) return testGate
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

function testButtonFor(provider: string): HTMLElement {
  return screen.getByRole("button", { name: `${provider} connection` })
}

/**
 * Button-affordance predicate (accepts EITHER Green implementation):
 *   A) ui/button outline sm -> data-slot="button" + outline border, OR
 *   B) Carbon button-like -> border + rounded + padding.
 * Current bare Test cell has neither (muted text only), so this is false Red.
 */
function hasButtonAffordance(btn: HTMLElement): boolean {
  const dataSlot = btn.getAttribute("data-slot")
  const cls = btn.className ?? ""
  const hasDataSlotButton = dataSlot === "button"
  const hasBorder = /border/.test(cls)
  const hasRounded = /rounded/.test(cls)
  const hasPadding = /px-\d|py-\d/.test(cls)
  const uiButtonOutline = hasDataSlotButton && hasBorder
  const carbonButton = hasBorder && hasRounded && hasPadding
  return uiButtonOutline || carbonButton
}

/** Narrow source window around the Test-cell aria-label (stays inside the row). */
function testCellWindow(): string {
  const marker = "${provider.name} connection"
  const idx = settingsSource.indexOf(marker)
  if (idx < 0) throw new Error("Test cell aria-label marker not found in SettingsProviders.tsx")
  return settingsSource.slice(Math.max(0, idx - 600), idx + 600)
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
})

// ---------------------------------------------------------------------------
// S-P3-1: affordance — Test looks like an actual button (RED)
// ---------------------------------------------------------------------------

describe("S-P3-1: Test buttons look like actual buttons (affordance)", () => {
  it("every Test button exposes ui/button OR Carbon button box (not plain text)", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const btn = testButtonFor(name)
      expect(
        hasButtonAffordance(btn),
        `${name} Test must look like a button: ` +
          `(data-slot="button" + outline border) OR (border+rounded+padding); ` +
          `got data-slot=${JSON.stringify(btn.getAttribute("data-slot"))} class=${JSON.stringify(btn.className)}`
      ).toBe(true)
    }
  })

  it("Test buttons carry a visible border (not bare muted text)", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const btn = testButtonFor(name)
      expect(
        btn.className,
        `${name} Test class must contain a visible border (got ${JSON.stringify(btn.className)})`
      ).toMatch(/border/)
    }
  })

  it("Test buttons carry a rounded box with padding (not bare text)", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const btn = testButtonFor(name)
      expect(btn.className, `${name} Test must be rounded`).toMatch(/rounded/)
      expect(
        btn.className,
        `${name} Test must carry button padding (got ${JSON.stringify(btn.className)})`
      ).toMatch(/px-\d|py-\d/)
    }
  })

  it("Test cell source uses ui/button outline OR Carbon border+rounded+padding", () => {
    const window_ = testCellWindow()
    const usesUiButton =
      window_.includes("<Button") && settingsSource.includes("@/components/ui/button")
    const hasCarbonBox =
      /border/.test(window_) && /rounded/.test(window_) && /px-/.test(window_)
    expect(
      usesUiButton || hasCarbonBox,
      `Test cell must use <Button> (ui/button outline sm) OR Carbon border+rounded+padding; ` +
        `got window ${JSON.stringify(window_.slice(0, 240))}...`
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// S-P3-2: states preserved — Test/Testing...+disabled, one POST, label stable
// ---------------------------------------------------------------------------

describe("S-P3-2: Test interaction states preserved (Test/Testing... + POST)", () => {
  it("all 7 Test buttons start as Test with type=button and exact aria-label", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const btn = testButtonFor(name)
      expect(btn).toHaveTextContent("Test")
      expect(btn.textContent?.trim()).toBe("Test")
      expect(btn.getAttribute("type")).toBe("button")
      expect(btn.getAttribute("aria-label")).toBe(`${name} connection`)
      expect(btn).not.toBeDisabled()
    }
  })

  it("click flips to Testing... + disabled with aria-label and type stable", async () => {
    const user = userEvent.setup()
    const gate = deferred<Response>()
    renderSettings()
    await waitForProviders()
    testGate = gate.promise

    const before = testButtonFor("Brave Search")
    expect(before).toHaveTextContent("Test")
    expect(before.getAttribute("aria-label")).toBe("Brave Search connection")
    expect(before.getAttribute("type")).toBe("button")

    await user.click(before)

    await waitFor(() => {
      expect(testButtonFor("Brave Search")).toHaveTextContent("Testing...")
    })
    const pending = testButtonFor("Brave Search")
    expect(pending.textContent?.trim()).toBe("Testing...")
    expect(pending).toBeDisabled()
    expect(pending.getAttribute("aria-label")).toBe("Brave Search connection")
    expect(pending.getAttribute("type")).toBe("button")

    gate.resolve(
      ok({
        provider: "brave",
        ok: true,
        status: "healthy",
        latency_ms: 142,
        checked_at: "2026-09-06T10:04:00Z",
        detail: null,
      })
    )
    await waitFor(() => {
      expect(testButtonFor("Brave Search")).toHaveTextContent("Test")
    })
  })

  it("emits exactly one POST to /api/v1/providers/brave/test then flips back enabled", async () => {
    const user = userEvent.setup()
    const gate = deferred<Response>()
    const stub = renderSettings()
    await waitForProviders()
    testGate = gate.promise

    await user.click(testButtonFor("Brave Search"))
    await waitFor(() => {
      expect(testButtonFor("Brave Search")).toHaveTextContent("Testing...")
    })

    gate.resolve(
      ok({
        provider: "brave",
        ok: true,
        status: "healthy",
        latency_ms: 142,
        checked_at: "2026-09-06T10:04:00Z",
        detail: null,
      })
    )
    await waitFor(() => {
      expect(testButtonFor("Brave Search")).toHaveTextContent("Test")
    })
    const done = testButtonFor("Brave Search")
    expect(done.textContent?.trim()).toBe("Test")
    expect(done).not.toBeDisabled()
    expect(done.getAttribute("aria-label")).toBe("Brave Search connection")
    expect(done.getAttribute("type")).toBe("button")

    const tests = stub.requestsTo("/api/v1/providers/brave/test")
    expect(tests).toHaveLength(1)
    expect(tests[0].method).toBe("POST")
  })

  it("Test column keeps 7 labelled buttons inside the Test cells (label stable)", async () => {
    renderSettings()
    await waitForProviders()
    const table = screen.getByRole("table")
    const headers = Array.from(table.querySelectorAll("thead th")).map(
      (th) => th.textContent?.trim() ?? ""
    )
    const testIdx = headers.indexOf("Test")
    expect(testIdx).toBe(4)
    const rows = Array.from(table.querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(7)
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      const cell = row.children[testIdx] as HTMLElement
      const btn = within(cell).getByRole("button", { name: `${name} connection` })
      expect(btn.getAttribute("type")).toBe("button")
      expect(btn.textContent?.trim()).toBe("Test")
    }
  })
})

// ---------------------------------------------------------------------------
// S-P3-3: no-regression — S-P1 table, S-P2 ranks, tokens, no merge
// ---------------------------------------------------------------------------

describe("S-P3-3: no regression — S-P1 table, S-P2 ranks, tokens, no merge", () => {
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
    // S-P2-5 scope: arrows stay lucide ArrowUp/ArrowDown with exact aria-labels.
    // (Deliberately no "no Button in file" assertion — Green adds ui/Button
    // to the Test cell; the restyle guard covers ONLY the arrows.)
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
    expect(
      screen.getAllByText([...EXPECTED_RANKS][0], { exact: true })
    ).toHaveLength(1)
  })

  it("Carbon Black theme tokens untouched (#1e1e1e scale + #007acc, no oklch)", () => {
    expect(norm(indexCssSource).includes("#1e1e1e")).toBe(true)
    expect(norm(indexCssSource).includes("#252526")).toBe(true)
    expect(norm(indexCssSource).includes("#3e3e42")).toBe(true)
    expect(norm(indexCssSource).includes("#007acc")).toBe(true)
    expect(norm(indexCssSource).includes("oklch(")).toBe(false)
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
