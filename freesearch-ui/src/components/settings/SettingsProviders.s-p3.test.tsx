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
 * P1-FINAL sweep: per-row Test affordance is now an icon button
 * (ui/button ghost icon-sm, aria-label "{name} test connection") that opens
 * the ProviderTestModal (zero fetch on open). The modal Test button runs the
 * existing handleTest (Test/Testing... + exactly one POST). Table is the
 * merged 10-column registry.
 */

const testDir = import.meta.dirname
const settingsSource = readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8")
const indexCssSource = readFileSync(path.resolve(testDir, "../../index.css"), "utf8")

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

const EXPECTED_HEADERS = [
  "Provider",
  "Endpoint",
  "Global",
  "Search",
  "Fetch",
  "Health",
  "p95",
  "Quota",
  "Breaker",
  "Test",
] as const
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
  return screen.getByRole("button", { name: `${provider} test connection` })
}

/** Icon-only affordance: ui/button ghost icon-sm with an svg icon, never bare text. */
function hasIconAffordance(btn: HTMLElement): boolean {
  const dataSlot = btn.getAttribute("data-slot")
  const cls = btn.className ?? ""
  const text = btn.textContent?.trim() ?? ""
  return (
    dataSlot === "button" &&
    text === "" &&
    btn.querySelector("svg") !== null &&
    /rounded/.test(cls)
  )
}

/** Narrow source window around the icon test aria-label (stays inside the row). */
function testCellWindow(): string {
  const marker = "${provider.name} test connection"
  const idx = settingsSource.indexOf(marker)
  if (idx < 0) throw new Error("Icon test aria-label marker not found in SettingsProviders.tsx")
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
// S-P3-1: affordance — icon test button per row (P1-FINAL)
// ---------------------------------------------------------------------------

describe("S-P3-1: icon test buttons open the ProviderTestModal (affordance)", () => {
  it("every row exposes exactly one icon test button (ui/button, svg, no text)", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const btn = testButtonFor(name)
      expect(
        hasIconAffordance(btn),
        `${name} Test must be an icon-only ui/button: ` +
          `data-slot="button" + svg + empty text; ` +
          `got data-slot=${JSON.stringify(btn.getAttribute("data-slot"))} text=${JSON.stringify(btn.textContent)} class=${JSON.stringify(btn.className)}`
      ).toBe(true)
    }
  })

  it("icon test buttons are ghost icon-sm buttons (never the old outline text box)", async () => {
    renderSettings()
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const btn = testButtonFor(name)
      expect(btn.getAttribute("type")).toBe("button")
      expect(btn).not.toBeDisabled()
      // Icon-only: no visible "Test" text on the row button itself.
      expect(btn.textContent?.trim()).toBe("")
      expect(btn.querySelector("svg")).not.toBeNull()
    }
  })

  it("icon opens the modal with zero fetch (never probes on open)", async () => {
    const user = userEvent.setup()
    const stub = renderSettings()
    await waitForProviders()
    const callsBefore = stub.requests.length
    await user.click(testButtonFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    expect(stub.requests.length).toBe(callsBefore)
    expect(stub.requestsTo("/api/v1/providers/brave/test")).toHaveLength(0)
    expect(dialog.textContent).toContain("Brave Search")
  })

  it("Test cell source uses ghost icon-sm Button wired to onOpenTest; modal Test uses handleTest", () => {
    const window_ = testCellWindow()
    expect(window_).toContain("<Button")
    expect(window_).toMatch(/ghost/)
    expect(window_).toMatch(/icon-sm/)
    expect(window_).toMatch(/onOpenTest/)
    expect(settingsSource).toContain("@/components/ui/button")
    expect(settingsSource).toMatch(/onTest\(provider\.id\)/)
    expect(settingsSource).toContain("handleTest")
  })
})

// ---------------------------------------------------------------------------
// S-P3-2: modal Test states — Testing...+disabled, one POST, last-result
// ---------------------------------------------------------------------------

describe("S-P3-2: modal Test interaction states (Test/Testing... + POST)", () => {
  it("modal opens Not tested with a Test button (type=button, enabled)", async () => {
    const user = userEvent.setup()
    renderSettings()
    await waitForProviders()

    await user.click(testButtonFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).toContain("Not tested")
    const modalTest = within(dialog).getByRole("button", { name: /^Test$/ })
    expect(modalTest.getAttribute("type")).toBe("button")
    expect(modalTest).not.toBeDisabled()
  })

  it("modal Test click flips to Testing... + disabled, then records the last result", async () => {
    const user = userEvent.setup()
    const gate = deferred<Response>()
    renderSettings()
    await waitForProviders()
    testGate = gate.promise

    await user.click(testButtonFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: /^Test$/ }))

    await waitFor(() => {
      expect(
        within(screen.getByRole("dialog")).getByRole("button", { name: /testing/i })
      ).toBeInTheDocument()
    })
    const pending = within(screen.getByRole("dialog")).getByRole("button", {
      name: /testing/i,
    })
    expect(pending.textContent?.trim()).toBe("Testing...")
    expect(pending).toBeDisabled()
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
    // Last result lands in the modal (status + latency of the probe).
    await waitFor(() => {
      expect(screen.getByRole("dialog").textContent).toMatch(/142ms|healthy/)
    })
  })

  it("emits exactly one POST to /api/v1/providers/brave/test via the modal", async () => {
    const user = userEvent.setup()
    const gate = deferred<Response>()
    const stub = renderSettings()
    await waitForProviders()
    testGate = gate.promise

    await user.click(testButtonFor("Brave Search"))
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: /^Test$/ }))
    await waitFor(() => {
      expect(
        within(screen.getByRole("dialog")).getByRole("button", { name: /testing/i })
      ).toBeInTheDocument()
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
      const tests = stub.requestsTo("/api/v1/providers/brave/test")
      expect(tests).toHaveLength(1)
      expect(tests[0].method).toBe("POST")
    })
  })

  it("Test column keeps 7 icon buttons inside the Test cells (label stable)", async () => {
    renderSettings()
    await waitForProviders()
    const table = screen.getByRole("table")
    const headers = Array.from(table.querySelectorAll("thead th")).map(
      (th) => th.textContent?.trim() ?? ""
    )
    const testIdx = headers.indexOf("Test")
    expect(testIdx).toBe(9)
    const rows = Array.from(table.querySelectorAll("tbody tr"))
    expect(rows).toHaveLength(7)
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      const cell = row.children[testIdx] as HTMLElement
      const btn = within(cell).getByRole("button", { name: `${name} test connection` })
      expect(btn.getAttribute("type")).toBe("button")
      expect(btn.textContent?.trim()).toBe("")
    }
  })
})

// ---------------------------------------------------------------------------
// S-P3-3: no-regression — S-P1 table, S-P2 ranks, tokens, no merge
// ---------------------------------------------------------------------------

describe("S-P3-3: no regression — S-P1 table, S-P2 ranks, tokens, merge", () => {
  it("S-P1 table invariant: single merged table, 10 headers, 7x10, scroller, nowrap", async () => {
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
      expect(row.children).toHaveLength(10)
    }
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table scroller must wrap the table").not.toBeNull()
    expect(container!.className).toMatch(/overflow-x-auto/)
    const cells = Array.from(table.querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(10 + 7 * 10)
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

  it("P1-FINAL page merge: fleet telemetry merged into SettingsProviders (ProviderMatrix retired)", () => {
    for (const marker of ["Endpoint", "Health", "Breaker", "Quota", "p95", "ProviderTestModal"]) {
      expect(settingsSource, `merged registry must carry ${marker}`).toContain(marker)
    }
  })

  it("freesearch-ui ONLY: SettingsProviders imports no backend/python paths", () => {
    expect(settingsSource).not.toMatch(/\.py["']/)
    expect(settingsSource).not.toMatch(/src\/freesearch/)
  })
})
