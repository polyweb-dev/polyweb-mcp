import React from "react"
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { RoutingEngine } from "./RoutingEngine"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import { ADMIN_ACCOUNT_ID, DEVELOPER_ACCOUNT_ID } from "@/test/authFixtures"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/backendFixtures"

describe("RoutingStrategy.r-strat.test.tsx", () => {

/**
 * R-Strategy full-width section (BDD Acceptance, RED phase).
 *
 * User bullet (feedback.md L50): Strategy "Unused space" (SEE image
 * yourself: .agents/FEEDBACK/UI/image-21.png — strategy cards boxed into a
 * narrow left column with a large void on the right).
 * R1 bottom bar committed — preserve (no bar assertions change here).
 *
 * Plan CONFIRMED (orchestrator rulings: Strategy w-full max-w-none;
 * cards/logic untouched; freesearch-ui/ ONLY):
 *   - Strategy section max-w-3xl -> w-full max-w-none (cards + selection
 *     logic byte-identical).
 *
 * AC mapping:
 *   AC-R-STRAT-1  Full-width section: the "Active algorithm" section spans
 *                 the available width (w-full max-w-none), max-w-3xl gone.
 *   AC-R-STRAT-2  Cards/selection intact: all four preset cards render with
 *                 badges + descriptions, radio semantics (aria-pressed)
 *                 toggle on select, cost card PUTs free_first once, the
 *                 selected card previews its Primary provider, and the
 *                 selection logic source is untouched.
 *
 * RED expectation: AC-R-STRAT-1 FAILS cleanly against the current codebase
 * (section is "space-y-3 max-w-3xl"). AC-R-STRAT-2 stays GREEN throughout.
 */

const testDir = import.meta.dirname
// Slice 5 ownership: strategy UI lives in features/routing (shell removed
// at migration completion). Read the joined owner sources.
const strategyOwnerFiles = [
  "./RoutingStrategy.tsx",
  "./StrategyCardButton.tsx",
]
const strategySource = strategyOwnerFiles
  .map((file) => readFileSync(path.resolve(testDir, file), "utf8"))
  .join("\n")
function renderRouting() {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.method === "PUT" && req.url === "/api/v1/routing/config") {
      return ok({ ...routingConfigFixture(), ...((req.body as object) ?? {}) })
    }
    return err(404, { detail: "unhandled test route" })
  })
  const view = render(
    <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
      <RoutingEngine />
    </FreeSearchProvider>
  )
  return { stub, ...view }
}

async function readyForStrategy() {
  await waitFor(() => {
    expect(
      screen.getByRole("button", { name: /^Strict priority/ })
    ).toBeInTheDocument()
  })
}

function strategySection(): HTMLElement {
  const heading = screen.getByRole("heading", { name: "Active algorithm" })
  const section = heading.closest("section")
  expect(section).not.toBeNull()
  return section as HTMLElement
}

describe("R-STRAT AC-R-STRAT-1: strategy section uses the full width", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders the Active algorithm section full-width (w-full max-w-none, no max-w-3xl)", async () => {
    renderRouting()
    await readyForStrategy()

    const section = strategySection()
    expect(section.className).toContain("w-full")
    expect(section.className).toContain("max-w-none")
    expect(section.className).not.toContain("max-w-3xl")
    // Vertical rhythm untouched: only the width constraint changes.
    expect(section.className).toContain("space-y-3")
  })

  it("owns the full-width section in source (w-full max-w-none, max-w-3xl gone)", () => {
    expect(strategySource).toContain("w-full")
    expect(strategySource).toContain("max-w-none")
    expect(strategySource).not.toContain("max-w-3xl")
  })
})

describe("R-STRAT AC-R-STRAT-2: strategy cards and selection logic intact", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders all four preset cards with badges and descriptions", async () => {
    renderRouting()
    await readyForStrategy()

    const cards: Array<[RegExp, string, string]> = [
      [/^Strict priority/, "Manual ordering", "cascades down user-defined ranks"],
      [/^Cost optimized/, "Zero-cost bias", "free allotments before paid credits"],
      [/^Latency optimized/, "Fastest response", "lowest p95 roundtrip"],
      [/^Quality first/, "Rich extraction", "deep LLM extractors"],
    ]
    for (const [name, badge, description] of cards) {
      const card = screen.getByRole("button", { name })
      expect(within(card).getByText(badge)).toBeInTheDocument()
      expect(card.textContent).toMatch(new RegExp(description))
    }
  })

  it("keeps radio semantics: Strict priority selected by default, selection flips on click", async () => {
    const user = userEvent.setup()
    renderRouting()
    await readyForStrategy()

    const strict = screen.getByRole("button", { name: /^Strict priority/ })
    const latency = screen.getByRole("button", { name: /^Latency optimized/ })
    expect(strict).toHaveAttribute("aria-pressed", "true")
    expect(latency).toHaveAttribute("aria-pressed", "false")

    await user.click(latency)

    expect(latency).toHaveAttribute("aria-pressed", "true")
    expect(strict).toHaveAttribute("aria-pressed", "false")
  })

  it("PUTs free_first once when the cost-optimized card is selected", async () => {
    const user = userEvent.setup()
    const { stub } = renderRouting()
    await readyForStrategy()

    await user.click(screen.getByRole("button", { name: /^Cost optimized/ }))

    expect(
      screen.getByRole("button", { name: /^Cost optimized/ })
    ).toHaveAttribute("aria-pressed", "true")
    await waitFor(() => {
      const puts = stub.requests.filter(
        (r) => r.method === "PUT" && r.url === "/api/v1/routing/config"
      )
      expect(puts).toHaveLength(1)
    })
    const puts = stub.requests.filter(
      (r) => r.method === "PUT" && r.url === "/api/v1/routing/config"
    )
    expect(puts[0].body).toMatchObject({ cost_optimization_preset: "free_first" })
  })

  it("previews the Primary provider on the selected card", async () => {
    renderRouting()
    await readyForStrategy()

    const strict = screen.getByRole("button", { name: /^Strict priority/ })
    // The Primary badge and the arbitrated provider name both arrive with the
    // asynchronous catalog — await the data together, not the static card.
    await waitFor(() => {
      expect(within(strict).getByText("Primary")).toBeInTheDocument()
      expect(within(strict).getByText("Brave Search")).toBeInTheDocument()
    })
    expect(strict.textContent).toMatch(/ms.*p95|p95/)
  })

  it("leaves the selection logic source untouched", () => {
    for (const id of ["priority", "cost_optimized", "latency_optimized", "quality_first"]) {
      expect(strategySource).toContain(id)
    }
    expect(strategySource).toContain("setRoutingPreset")
    expect(strategySource).toContain("updateCostPreset")
    expect(strategySource).toContain("getEligibleProviders")
    expect(strategySource).toContain("free_first")
    expect(strategySource).toContain("balanced")
  })
})
})

describe("RoutingStrategy Developer read-only (canReadControls, no edit)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function renderDeveloperRouting() {
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(allProvidersFixture())
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(routingConfigFixture())
      }
      if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
      return err(404, { detail: "unhandled test route" })
    })
    const view = render(
      <FreeSearchProvider accountId={DEVELOPER_ACCOUNT_ID} canReadControls canEditControls={false}>
        <RoutingEngine />
      </FreeSearchProvider>
    )
    return { stub, ...view }
  }

  async function readyForDeveloperStrategy() {
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Strict priority/ })).toBeInTheDocument()
    })
  }

  it("keeps strategy selection local-only: cost card flips aria-pressed with no backend write", async () => {
    const user = userEvent.setup()
    const { stub } = renderDeveloperRouting()
    await readyForDeveloperStrategy()

    // Read-only markers present: all four preset cards still render.
    for (const name of [/^Strict priority/, /^Cost optimized/, /^Latency optimized/, /^Quality first/]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument()
    }
    const strict = screen.getByRole("button", { name: /^Strict priority/ })
    const cost = screen.getByRole("button", { name: /^Cost optimized/ })
    expect(strict).toHaveAttribute("aria-pressed", "true")
    expect(cost).toHaveAttribute("aria-pressed", "false")

    // Local simulation control still works with no backend write.
    await user.click(cost)
    expect(cost).toHaveAttribute("aria-pressed", "true")
    expect(strict).toHaveAttribute("aria-pressed", "false")
    expect(
      stub.requests.filter((r) => r.method === "PUT" && r.url === "/api/v1/routing/config")
    ).toHaveLength(0)
    expect(
      stub.requests.filter((r) => r.method === "PATCH" || r.method === "PUT" || r.method === "POST")
    ).toHaveLength(0)
  })
})
