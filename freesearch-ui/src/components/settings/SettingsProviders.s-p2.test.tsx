import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it, afterEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { SettingsView } from "./SettingsView"
import { installFetchStub, ok, err, type FetchStub } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  type WireProviderStatus,
} from "@/test/backendFixtures"

/**
 * S-P2 provider priority values — BDD Acceptance (RED phase).
 *
 * User bullet (verbatim): "These values don't make any sense". BUG image-2.png
 * shows every registry row labelled P100 with the up/down arrows clipped at
 * the card edge. Scout: the live backend returns priority 100 for ALL
 * providers, and the UI renders the raw value (`P{provider.priority}`), so
 * every row reads P100 and the indicator column has no width floor.
 *
 * Plan under test (freesearch-ui/ ONLY, no button restyle/space/merge):
 *   SettingsProviders rank display (P{rank 1..7} from sorted order, never raw
 *   P100) + tooltip dispatch order;
 *   FreeSearchContext moveProviderPriority tied-value branch (equal priorities
 *   -> PATCH distinct rank numbers);
 *   PriorityIndicator fixed min-w/shrink-0 + first-cell px-3 (no clipping,
 *   table + scroller intact).
 *
 * AC mapping:
 *   S-P2-1  all-100 stub renders ranks P1..P7 in row order, never P100
 *           (rank display, not raw priority).
 *   S-P2-2  rank follows sorted order: scrambled backend priorities still
 *           render P1..P7 top-to-bottom with the exact row->rank mapping, plus
 *           an exact `Dispatch order N of 7` tooltip per row.
 *   S-P2-3  clipping guards: PriorityIndicator keeps shrink-0 AND gains a
 *           min-w-* floor (non-zero width proxy — jsdom has no layout engine,
 *           same structural-invariant approach as S-P1-2), first-column cells
 *           keep px-3, and the ui/table scroller (overflow-x-auto + nowrap,
 *           single 7x5 table) stays intact.
 *   S-P2-4  arrows exist for all 7 rows with sorted-order boundaries on ties;
 *           a tie move PATCHes DISTINCT rank numbers (landed guard) AND the
 *           PATCH set must reproduce the EXACT adjacent transposition
 *           (direction-correct: rank-3 down -> rank 4, all other rows stable)
 *           both under (priority, provider_id) replay-sort and in the live
 *           post-move top-to-bottom DOM order — full-tie (all-100) plus a new
 *           partial-tie (some tied, some distinct) case; GET refresh + P1..P7
 *           label-set invariant kept.
 *   S-P2-5  scope guards (GREEN before and after): lucide ArrowUp/ArrowDown
 *           untouched (no button restyle), no ProviderMatrix merge, no
 *           backend/python imports, S-P1 table alignment intact.
 *
 * RED expectation (final review: rank display, tooltip, min-w floor, and
 * tied-value DISTINCT PATCH branch have landed — S-P2-1..S-P2-3 and the S-P2-4
 * PATCH-shape guard are GREEN):
 *   S-P2-4 tie-ORDER (replay-sort + exact post-move DOM order, full-tie and
 *   partial-tie) FAILS cleanly until Developer lands production
 *   normalization — the two-PATCH rank swap cannot reproduce the adjacent
 *   transposition while the untouched rows keep their raw values.
 *   S-P2-5 + boundary/scroller guards stay GREEN throughout.
 */

const testDir = import.meta.dirname
const settingsSource = readFileSync(path.resolve(testDir, "./SettingsProviders.tsx"), "utf8")

const indicatorSource = (() => {
  const start = settingsSource.indexOf("const PriorityIndicator")
  const end = settingsSource.indexOf("const RowPill")
  if (start < 0 || end < 0 || end <= start) {
    throw new Error("PriorityIndicator source block not found — SettingsProviders.tsx refactored?")
  }
  return settingsSource.slice(start, end)
})()

const SEED_PROVIDER_NAMES = [
  "Brave Search",
  "Keenable",
  "Tavily",
  "Exa",
  "Firecrawl",
  "You.com",
  "Parallel",
] as const

const EXPECTED_RANKS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7"] as const

/** Scrambled backend priorities: rank must come from sorted order, not raw. */
const SCRAMBLED_PRIORITIES: Record<string, number> = {
  brave: 30,
  keenable: 10,
  tavily: 50,
  exa: 20,
  firecrawl: 70,
  you: 40,
  parallel: 60,
}

/** Expected row->rank mapping for the scrambled fixture (ascending sort). */
const SCRAMBLED_RANKS: Record<string, string> = {
  Keenable: "P1",
  Exa: "P2",
  "Brave Search": "P3",
  "You.com": "P4",
  Tavily: "P5",
  Parallel: "P6",
  Firecrawl: "P7",
}

function all100Fixture(): WireProviderStatus[] {
  return allProvidersFixture().map((row) => ({ ...row, priority: 100 }))
}

function scrambledFixture(): WireProviderStatus[] {
  return allProvidersFixture().map((row) => ({
    ...row,
    priority: SCRAMBLED_PRIORITIES[row.provider_id] ?? row.priority,
  }))
}

/** Partial tie: brave:1, keenable:2, tavily/exa/firecrawl tied at 5, you:6, parallel:7. */
const PARTIAL_TIE_PRIORITIES: Record<string, number> = {
  brave: 1,
  keenable: 2,
  tavily: 5,
  exa: 5,
  firecrawl: 5,
  you: 6,
  parallel: 7,
}

function partialTieFixture(): WireProviderStatus[] {
  return allProvidersFixture().map((row) => ({
    ...row,
    priority: PARTIAL_TIE_PRIORITIES[row.provider_id] ?? row.priority,
  }))
}

const PARTIAL_TIE_PRE_NAMES = [
  "Brave Search",
  "Keenable",
  "Tavily",
  "Exa",
  "Firecrawl",
  "You.com",
  "Parallel",
] as const

function renderSettingsWith(providers: WireProviderStatus[]): FetchStub {
  const server = providers.map((row) => ({ ...row }))
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(server)
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "PATCH" && req.url.startsWith("/api/v1/providers/")) {
      const backendId = req.url.split("/").at(-1) ?? "unknown"
      const entry = server.find((row) => row.provider_id === backendId)
      if (!entry) return err(404, { detail: `unknown provider '${backendId}'` })
      Object.assign(entry, (req.body as object) ?? {})
      return ok(entry)
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

/**
 * TR-STRICT row lookup (same traversal contract as S-P1: every provider row
 * is a <tr>; throws when rows are still <div>s).
 */
function findProviderRowTr(provider: string): HTMLTableRowElement {
  const nameEl = screen.getByText(provider, { exact: true })
  const tr = nameEl.closest("tr")
  if (!tr) {
    throw new Error(
      `Provider table row <tr> not found for ${provider} — table migration missing`
    )
  }
  return tr as HTMLTableRowElement
}

/** The single P-rank label inside a provider row (works for P1..P7 AND P100). */
function priorityLabelInRow(row: HTMLTableRowElement): HTMLElement {
  const labels = Array.from(row.querySelectorAll("span")).filter((el) =>
    /^P\d+$/.test(el.textContent?.trim() ?? "")
  )
  if (labels.length !== 1) {
    throw new Error(
      `Expected exactly one P-rank label in row, found ${labels.length}: [${labels.map((l) => l.textContent).join(", ")}]`
    )
  }
  return labels[0] as HTMLElement
}

function rankOfRow(provider: string): string {
  return priorityLabelInRow(findProviderRowTr(provider)).textContent?.trim() ?? ""
}

/** Rank labels top-to-bottom in render order. */
function allRankLabelsInRowOrder(): string[] {
  const rows = Array.from(screen.getByRole("table").querySelectorAll("tbody tr"))
  return rows.map((row) => priorityLabelInRow(row as HTMLTableRowElement).textContent?.trim() ?? "")
}

function patchRequests(stub: FetchStub) {
  return stub.requests.filter(
    (r) => r.method === "PATCH" && r.url.startsWith("/api/v1/providers/")
  )
}

/** Provider display names top-to-bottom in render order. */
function providerNamesInRowOrder(): string[] {
  const rows = Array.from(screen.getByRole("table").querySelectorAll("tbody tr"))
  return rows.map((row) => {
    const nameEl = (row as HTMLTableRowElement).querySelector("span.font-medium")
    if (!nameEl) throw new Error("Provider name span.font-medium not found in table row")
    return nameEl.textContent?.trim() ?? ""
  })
}

/**
 * Replay a PATCH set onto a pre-move snapshot, then sort by
 * (priority, provider_id). The result must equal the expected adjacent
 * transposition. The pre-move snapshot is regenerated from the same pure
 * fixture the stub server was seeded with, so values are identical.
 */
function orderFromPatchSet(
  preMove: WireProviderStatus[],
  patches: Array<{ backendId: string; priority: number }>
): string[] {
  const priorityById = new Map(preMove.map((row) => [row.provider_id, row.priority]))
  for (const patch of patches) {
    if (!priorityById.has(patch.backendId)) {
      throw new Error(`PATCH for unknown provider '${patch.backendId}'`)
    }
    priorityById.set(patch.backendId, patch.priority)
  }
  return [...priorityById.entries()]
    .sort((a, b) => a[1] - b[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .map(([id]) => id)
}

function patchIdAndPriority(
  stub: FetchStub
): Array<{ backendId: string; priority: number }> {
  return patchRequests(stub).map((r) => ({
    backendId: r.url.split("/").at(-1) ?? "",
    priority: (r.body as { priority: number }).priority,
  }))
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// S-P2-1: all-100 stub shows P1..P7, never P100
// ---------------------------------------------------------------------------

describe("S-P2-1: all-100 backend renders rank display P1..P7 (never raw P100)", () => {
  it("renders ranks P1..P7 top-to-bottom when every backend priority is 100", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    expect(allRankLabelsInRowOrder()).toEqual([...EXPECTED_RANKS])
  })

  it("shows each rank exactly once with zero P100 labels", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    for (let rank = 1; rank <= 7; rank += 1) {
      expect(screen.queryAllByText(`P${rank}`, { exact: true })).toHaveLength(1)
    }
    expect(screen.queryByText("P100", { exact: true })).toBeNull()
    const multiDigit = allRankLabelsInRowOrder().filter((label) => /^P\d{2,}$/.test(label))
    expect(multiDigit).toEqual([])
  })

  it("never renders the raw priority interpolation", () => {
    expect(settingsSource).not.toContain("P{provider.priority}")
  })
})

// ---------------------------------------------------------------------------
// S-P2-2: rank follows sorted order + tooltip dispatch order
// ---------------------------------------------------------------------------

describe("S-P2-2: rank follows sorted order with dispatch-order tooltip", () => {
  it("maps scrambled backend priorities to ranks by ascending sorted order", async () => {
    renderSettingsWith(scrambledFixture())
    await waitForProviders()
    for (const [name, rank] of Object.entries(SCRAMBLED_RANKS)) {
      expect(rankOfRow(name)).toBe(rank)
    }
  })

  it("shows no raw backend values for the scrambled fixture", async () => {
    renderSettingsWith(scrambledFixture())
    await waitForProviders()
    expect(allRankLabelsInRowOrder()).toEqual([...EXPECTED_RANKS])
    for (const raw of ["P10", "P20", "P30", "P40", "P50", "P60", "P70"]) {
      expect(screen.queryByText(raw, { exact: true })).toBeNull()
    }
  })

  it("exposes an exact dispatch-order tooltip on every rank label", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    for (let rank = 1; rank <= 7; rank += 1) {
      const label = screen.getByText(`P${rank}`, { exact: true })
      expect(label.getAttribute("title")).toBe(`Dispatch order ${rank} of 7`)
    }
  })

  it("declares the dispatch-order tooltip in source", () => {
    expect(settingsSource).toContain("Dispatch order")
  })

  it("derives arrow boundaries from sorted order on scrambled priorities", async () => {
    renderSettingsWith(scrambledFixture())
    await waitForProviders()
    // Sorted first = Keenable (10), sorted last = Firecrawl (70).
    expect(
      screen.getByRole("button", { name: "Move Keenable priority up" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Firecrawl priority down" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Keenable priority down" })
    ).not.toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Firecrawl priority up" })
    ).not.toBeDisabled()
  })
})

// ---------------------------------------------------------------------------
// S-P2-3: clipping guards (min-w + shrink-0 + px-3, table + scroller intact)
// ---------------------------------------------------------------------------

describe("S-P2-3: priority indicator never clips at the card edge", () => {
  it("indicator keeps shrink-0 and gains a min-w-* floor (non-zero width proxy)", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    for (let rank = 1; rank <= 7; rank += 1) {
      const label = screen.getByText(`P${rank}`, { exact: true })
      const indicator = label.parentElement as HTMLElement | null
      expect(indicator, `P${rank} indicator wrapper must exist`).not.toBeNull()
      // shrink-0 stops flex compression; min-w-* floors the width so the
      // arrows + label cannot collapse to zero at the card edge. jsdom has
      // no layout engine, so the class invariant IS the executable guard
      // (same structural approach as S-P1-2); pixel proof needs a browser.
      expect(indicator!.className).toMatch(/shrink-0/)
      expect(indicator!.className).toMatch(/min-w-/)
    }
  })

  it("declares the min-w floor inside the PriorityIndicator source block", () => {
    expect(indicatorSource).toMatch(/shrink-0/)
    expect(indicatorSource).toMatch(/min-w-/)
  })

  it("first-column (Provider) cells keep px-3 breathing room", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      const row = findProviderRowTr(name)
      const firstCell = row.children[0] as HTMLElement
      expect(firstCell.tagName).toBe("TD")
      expect(firstCell.className).toMatch(/px-3/)
    }
  })

  it("table + scroller stay intact: single 7x9 merged table, overflow-x-auto, nowrap", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    expect(screen.getAllByRole("table")).toHaveLength(1)
    const table = screen.getByRole("table")
    expect(table.querySelectorAll("tbody tr")).toHaveLength(7)
    for (const row of Array.from(table.querySelectorAll("tbody tr"))) {
      expect(row.children).toHaveLength(9)
    }
    const container = table.closest('[data-slot="table-container"]') as HTMLElement | null
    expect(container, "ui/table scroller must wrap the table").not.toBeNull()
    expect(container!.className).toMatch(/overflow-x-auto/)
    const cells = Array.from(table.querySelectorAll("th, td")) as HTMLElement[]
    expect(cells.length).toBe(9 + 7 * 9)
    for (const cell of cells) {
      expect(cell.className).toMatch(/whitespace-nowrap/)
    }
  })
})

// ---------------------------------------------------------------------------
// S-P2-4: arrows + boundaries + PATCH distinct on ties + refresh
// ---------------------------------------------------------------------------

describe("S-P2-4: reorder arrows with tie-safe distinct PATCH + refresh", () => {
  it("renders up/down arrows for all 7 rows with boundaries on the all-100 stub", async () => {
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      expect(
        screen.getByRole("button", { name: `Move ${name} priority up` })
      ).toBeInTheDocument()
      expect(
        screen.getByRole("button", { name: `Move ${name} priority down` })
      ).toBeInTheDocument()
    }
    // Stable sorted order keeps fixture order on ties: Brave first, Parallel last.
    expect(
      screen.getByRole("button", { name: "Move Brave Search priority up" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Parallel priority down" })
    ).toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Tavily priority up" })
    ).not.toBeDisabled()
    expect(
      screen.getByRole("button", { name: "Move Tavily priority down" })
    ).not.toBeDisabled()
  })

  it("a tie move PATCHes DISTINCT rank numbers (1..7, never 100) then refreshes", async () => {
    // Landed guard: the tied-value branch sends rank numbers, not the tied
    // raw value. Deliberately set-agnostic (no count/exact-value pin) so a
    // future full-renormalization (N PATCHes) still satisfies it — exact
    // order is pinned by the transposition tests below.
    const user = userEvent.setup()
    const stub = renderSettingsWith(all100Fixture())
    await waitForProviders()

    // Tavily sits at index 2 (rank 3); moving down swaps with Exa (rank 4).
    await user.click(screen.getByRole("button", { name: "Move Tavily priority down" }))

    await waitFor(() => {
      expect(patchRequests(stub).length).toBeGreaterThanOrEqual(2)
    })
    const values = patchIdAndPriority(stub).map((p) => p.priority)
    expect(values.length).toBeGreaterThan(0)
    for (const value of values) {
      expect(Number.isInteger(value)).toBe(true)
      expect(value).toBeGreaterThanOrEqual(1)
      expect(value).toBeLessThanOrEqual(7)
    }
    expect(new Set(values).size).toBe(values.length)
    expect(values).not.toContain(100)

    // Rank swap is followed by an authoritative GET refresh of the registry.
    await waitFor(() => {
      const gets = stub
        .requestsTo("/api/v1/providers")
        .filter((r) => r.method === "GET")
      expect(gets.length).toBeGreaterThanOrEqual(2)
    })

    // Rank display invariant survives the move: still exactly P1..P7.
    await waitFor(() => {
      expect([...allRankLabelsInRowOrder()].sort()).toEqual([...EXPECTED_RANKS])
    })
  })

  it("tie PATCH set reproduces the adjacent transposition under (priority, provider_id) sort", async () => {
    // Tavily (rank 3) moves down past Exa (rank 4): the ONLY correct
    // end-state is the adjacent transposition
    // [brave, keenable, exa, tavily, firecrawl, you, parallel].
    // Replaying the PATCH set onto the pre-move snapshot and sorting by
    // (priority, provider_id) must yield exactly that order. RED until
    // Developer lands normalization: the two-PATCH rank swap leaves the
    // untouched rows at 100, so the replay sorts the swapped pair first.
    const user = userEvent.setup()
    const stub = renderSettingsWith(all100Fixture())
    await waitForProviders()
    expect(providerNamesInRowOrder()).toEqual([
      "Brave Search",
      "Keenable",
      "Tavily",
      "Exa",
      "Firecrawl",
      "You.com",
      "Parallel",
    ])

    await user.click(screen.getByRole("button", { name: "Move Tavily priority down" }))

    await waitFor(() => {
      expect(patchRequests(stub).length).toBeGreaterThanOrEqual(2)
    })
    const replayed = orderFromPatchSet(all100Fixture(), patchIdAndPriority(stub))
    expect(replayed).toEqual([
      "brave",
      "keenable",
      "exa",
      "tavily",
      "firecrawl",
      "you",
      "parallel",
    ])
  })

  it("tie move yields the exact transposed top-to-bottom order (direction-correct)", async () => {
    // Same move as above, asserted against the LIVE post-refresh DOM:
    // Tavily must read direction-correct at rank 4, Exa at rank 3, every
    // other row stable. RED until Developer lands normalization.
    const user = userEvent.setup()
    const stub = renderSettingsWith(all100Fixture())
    await waitForProviders()
    await user.click(screen.getByRole("button", { name: "Move Tavily priority down" }))

    // Quiescence first: authoritative GET refresh has landed...
    await waitFor(() => {
      const gets = stub
        .requestsTo("/api/v1/providers")
        .filter((r) => r.method === "GET")
      expect(gets.length).toBeGreaterThanOrEqual(2)
    })
    // ...then the registry must read as the adjacent transposition.
    await waitFor(() => {
      expect(providerNamesInRowOrder()).toEqual([
        "Brave Search",
        "Keenable",
        "Exa",
        "Tavily",
        "Firecrawl",
        "You.com",
        "Parallel",
      ])
    })
    expect(rankOfRow("Tavily")).toBe("P4")
    expect(rankOfRow("Exa")).toBe("P3")
  })

  it("partial-tie PATCH set reproduces the adjacent transposition under (priority, provider_id) sort", async () => {
    // Partial tie: brave:1, keenable:2, tavily/exa/firecrawl tied at 5,
    // you:6, parallel:7. Exa (rank 4) moves down past Firecrawl (rank 5):
    // the ONLY correct end-state is
    // [brave, keenable, tavily, firecrawl, exa, you, parallel].
    const user = userEvent.setup()
    const stub = renderSettingsWith(partialTieFixture())
    await waitForProviders()
    expect(providerNamesInRowOrder()).toEqual([...PARTIAL_TIE_PRE_NAMES])
    expect(rankOfRow("Tavily")).toBe("P3")
    expect(rankOfRow("Exa")).toBe("P4")
    expect(rankOfRow("Firecrawl")).toBe("P5")

    await user.click(screen.getByRole("button", { name: "Move Exa priority down" }))

    await waitFor(() => {
      expect(patchRequests(stub).length).toBeGreaterThanOrEqual(2)
    })
    const values = patchIdAndPriority(stub).map((p) => p.priority)
    expect(new Set(values).size).toBe(values.length)
    for (const value of values) {
      expect(Number.isInteger(value)).toBe(true)
      expect(value).toBeGreaterThanOrEqual(1)
      expect(value).toBeLessThanOrEqual(7)
    }
    const replayed = orderFromPatchSet(partialTieFixture(), patchIdAndPriority(stub))
    expect(replayed).toEqual([
      "brave",
      "keenable",
      "tavily",
      "firecrawl",
      "exa",
      "you",
      "parallel",
    ])
  })

  it("partial-tie move yields the exact transposed top-to-bottom order", async () => {
    // Same partial-tie move, asserted against the LIVE post-refresh DOM:
    // Exa must read direction-correct at rank 5, Firecrawl at rank 4,
    // every other row stable. RED until Developer lands normalization.
    const user = userEvent.setup()
    const stub = renderSettingsWith(partialTieFixture())
    await waitForProviders()
    await user.click(screen.getByRole("button", { name: "Move Exa priority down" }))

    await waitFor(() => {
      const gets = stub
        .requestsTo("/api/v1/providers")
        .filter((r) => r.method === "GET")
      expect(gets.length).toBeGreaterThanOrEqual(2)
    })
    await waitFor(() => {
      expect(providerNamesInRowOrder()).toEqual([
        "Brave Search",
        "Keenable",
        "Tavily",
        "Firecrawl",
        "Exa",
        "You.com",
        "Parallel",
      ])
    })
    expect(rankOfRow("Exa")).toBe("P5")
    expect(rankOfRow("Firecrawl")).toBe("P4")
  })
})

// ---------------------------------------------------------------------------
// S-P2-5: scope guards — no button restyle/space/merge, freesearch-ui ONLY
// ---------------------------------------------------------------------------

describe("S-P2-5: no restyle, no merge, freesearch-ui only (stays green)", () => {
  it("keeps the lucide ArrowUp/ArrowDown controls with exact aria-labels", async () => {
    expect(settingsSource).toContain("lucide-react")
    expect(settingsSource).toContain("ArrowUp")
    expect(settingsSource).toContain("ArrowDown")
    renderSettingsWith(all100Fixture())
    await waitForProviders()
    for (const name of SEED_PROVIDER_NAMES) {
      expect(
        screen.getByRole("button", { name: `Move ${name} priority up` })
      ).toBeInTheDocument()
      expect(
        screen.getByRole("button", { name: `Move ${name} priority down` })
      ).toBeInTheDocument()
    }
  })

  it("P1-FINAL page merge: fleet telemetry merged into SettingsProviders (ProviderMatrix retired)", () => {
    for (const marker of ["Endpoint", "Health", "Quota", "p95", "ProviderTestModal"]) {
      expect(settingsSource, `merged registry must carry ${marker}`).toContain(marker)
    }
  })

  it("freesearch-ui ONLY: no backend/python import paths", () => {
    expect(settingsSource).not.toMatch(/\.py["']/)
    expect(settingsSource).not.toMatch(/src\/freesearch/)
  })
})
