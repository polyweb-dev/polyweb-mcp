import React from "react"
import { readFileSync, existsSync } from "node:fs"
import path from "node:path"
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import App from "@/App"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { RoutingEngine } from "./RoutingEngine"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  fetchResponseFixture,
  searchResponseFixture,
  type WireProviderStatus,
} from "@/test/backendFixtures"

/**
 * R-Simulator hero/dock + shared ComposerShell (BDD Acceptance, RED phase).
 *
 * User bullet (feedback.md L53): Simulator "Ton of wasted space. Should
 * follow the same strategy as the Search and Fetch Playground, centered and
 * wide like the Google Search page. Once used, it should move to the top
 * like it is now and show the results below, and maybe use a smooth
 * animation. These can be abstracted to reusable components. Same for
 * Search and Fetch." (SEE image yourself:
 * .agents/FEEDBACK/UI/image-22.png — bare top-anchored input with void
 * below; refs the Search Tab pattern.)
 * R1 bottom bar committed — preserve.
 *
 * Plan CONFIRMED (orchestrator rulings: NO Enter-submit change; NO
 * simulator footer; Strategy w-full max-w-none; blessed pg-f1 L802-808
 * guard update; freesearch-ui/ ONLY):
 *   - Simulator hero/dock wrapper (simulator-layout, hasSimulated gate
 *     ONLY, exact search-layout tokens, results after wrapper, same input
 *     node, op-toggle resets hero);
 *   - ComposerShell testIdPrefix=simulator (inputRow icon+input+Simulate,
 *     NO footer; header SegmentedControl stays).
 *
 * AC mapping:
 *   AC-R-SIM-1  Idle hero: simulator-layout data-state=hero with the EXACT
 *               search-layout tokens (transition-all duration-300 ease-out
 *               motion-reduce:transition-none + mx-auto flex min-h-[55vh]
 *               max-w-3xl flex-col justify-center), composer inside, no
 *               pipeline. Top-anchored void is gone.
 *   AC-R-SIM-2  Dock on Simulate: hasSimulated gates data-state docked
 *               (AND ONLY hasSimulated), top-docked replaces hero geometry,
 *               transition kept, ExecutionPipeline renders AFTER (outside)
 *               the wrapper in document order.
 *   AC-R-SIM-3  Same-element transition: hero->docked keeps the SAME input
 *               + composer nodes, value, and focus (no remount).
 *   AC-R-SIM-4  Composer-via-shell: simulator-composer box with the EXACT
 *               Search token strings, borderless input, icon prefix in the
 *               row (never inside the button), text-only "Simulate route"
 *               button, NO divider/footer testids, source wires
 *               testIdPrefix=simulator with no footer prop; the header
 *               SegmentedControl (Simulator operation Search/Fetch) stays.
 *   AC-R-SIM-5  Op-toggle resets hero: switching Search/Fetch clears the
 *               run (hero state, pipeline gone) and swaps the placeholder.
 *   AC-R-SIM-6  Empty-eligible: zero eligible providers shows the empty
 *               message with no pipeline (hero idle); Simulate still only
 *               flips the hasSimulated gate (docked + message, no pipeline).
 *   AC-R-PGF1-1 Blessed churn: pg-f1 L802-808 guard updated to expect the
 *               Simulator shell (toContain ComposerShell/simulator-layout),
 *               stale not-toContain guard gone.
 *   AC-R-REG-1  Regressions GREEN before/after: Search/Fetch layouts +
 *               fetch shell intact, R1 StatusBar intact on both routes, four
 *               routing tabs intact, NO Enter-submit form, NO simulator
 *               footer, simulator/strategy logic untouched.
 *
 * RED expectation: AC-R-SIM-1..S6 FAIL cleanly against the current codebase
 * (zero simulator-layout/simulator-composer testids, zero ComposerShell in
 * the simulator, zero hasSimulated/data-state seams, bare bordered input).
 * AC-R-PGF1-1 + AC-R-REG-1 stay GREEN once the blessed pg-f1 edit lands.
 */

const testDir = import.meta.dirname
const simulatorPath = path.resolve(testDir, "./RouteSimulator.tsx")
const strategyPath = path.resolve(testDir, "./RoutingStrategy.tsx")
const playgroundPath = path.resolve(testDir, "../search/SearchPlayground.tsx")
const appPath = path.resolve(testDir, "../../App.tsx")
const statusBarPath = path.resolve(testDir, "../layout/StatusBar.tsx")
const pgf1Path = path.resolve(testDir, "../search/SearchPlayground.pg-f1.test.tsx")

const simulatorSource = readFileSync(simulatorPath, "utf8")
const strategySource = readFileSync(strategyPath, "utf8")
const playgroundSource = readFileSync(playgroundPath, "utf8")
const appSource =
  readFileSync(appPath, "utf8") +
  "\n" +
  readFileSync(
    path.resolve(testDir, "../layout/DashboardContent.tsx"),
    "utf8"
  )
const pgf1Source = readFileSync(pgf1Path, "utf8")

function renderRouting(providers: WireProviderStatus[] = allProvidersFixture()) {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(providers)
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
    <FreeSearchProvider>
      <RoutingEngine />
    </FreeSearchProvider>
  )
  return { stub, ...view }
}

async function openSimulator() {
  await waitFor(() => {
    expect(screen.getByRole("tab", { name: /^Simulator$/ })).toBeInTheDocument()
  })
  fireEvent.click(screen.getByRole("tab", { name: /^Simulator$/ }))
  await waitFor(() => {
    expect(
      screen.getByPlaceholderText("Type simulated query...", { exact: true })
    ).toBeInTheDocument()
  })
}

function simulateCurrentInput(value: string) {
  const input = screen.getByPlaceholderText(
    /Type simulated (query|URL)\.\.\./
  ) as HTMLInputElement
  fireEvent.change(input, { target: { value } })
  fireEvent.click(screen.getByRole("button", { name: /^Simulate route$/ }))
  return input
}

const tokens = (className: string): string[] =>
  className.split(/\s+/).filter(Boolean)

function expectTransitionClasses(wrapper: HTMLElement) {
  expect(wrapper.className).toContain("transition-all")
  expect(wrapper.className).toContain("duration-300")
  expect(wrapper.className).toContain("ease-out")
  expect(wrapper.className).toContain("motion-reduce:transition-none")
}

function expectHeroGeometry(wrapper: HTMLElement) {
  expect(wrapper.className).toContain("mx-auto")
  expect(wrapper.className).toContain("flex")
  expect(wrapper.className).toContain("flex-col")
  expect(wrapper.className).toContain("justify-center")
  expect(wrapper.className).toMatch(/min-h-\[(55|60)vh\]/)
  expect(wrapper.className).toContain("max-w-3xl")
  expect(wrapper.className).not.toContain("top-docked")
}

function expectComposerBoxClasses(composer: HTMLElement) {
  const cls = composer.className
  const names = tokens(cls)
  expect(cls).toContain("bg-[var(--elevated)]")
  expect(names).toContain("border")
  expect(cls).toContain("border-[var(--border-subtle)]")
  expect(names).toContain("rounded-xl")
  expect(names.some((t) => /^p-\d+$/.test(t))).toBe(true)
  expect(cls).toContain("shadow")
  expect(cls).toContain("focus-within:")
  expect(cls).toContain("signal")
  expect(cls).toContain("motion-reduce:transition-none")
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("R-SIM AC-R-SIM-1: idle Simulator is a centered hero (Search Tab pattern)", () => {
  it("shows the Simulate form with no pipeline in a centered hero simulator-layout", async () => {
    renderRouting()
    await openSimulator()

    expect(
      screen.getByPlaceholderText("Type simulated query...", { exact: true })
    ).toBeInTheDocument()
    expect(screen.queryByText("Client Ingress", { exact: true })).not.toBeInTheDocument()
    expect(screen.queryByText(/Failover cascade/i)).not.toBeInTheDocument()

    const wrapper = screen.getByTestId("simulator-layout")
    expect(wrapper).toHaveAttribute("data-state", "hero")
    expectHeroGeometry(wrapper)
    expectTransitionClasses(wrapper)
    expect(
      wrapper.querySelector('input[placeholder="Type simulated query..."]')
    ).not.toBeNull()
    expect(wrapper.className).not.toContain("top-docked")
  })

  it("uses the EXACT search-layout hero/transition tokens", async () => {
    renderRouting()
    await openSimulator()

    const wrapper = screen.getByTestId("simulator-layout")
    // Exact Search Tab token contract (mirrors search-layout/fetch-layout).
    for (const token of [
      "transition-all",
      "duration-300",
      "ease-out",
      "motion-reduce:transition-none",
      "mx-auto",
      "flex",
      "flex-col",
      "justify-center",
      "max-w-3xl",
    ]) {
      expect(tokens(wrapper.className)).toContain(token)
    }
    expect(wrapper.className).toMatch(/min-h-\[(55|60)vh\]/)
  })

  it("owns the hero wrapper + hasSimulated-only gate in source", () => {
    expect(simulatorSource).toContain("simulator-layout")
    expect(simulatorSource).toContain("hasSimulated")
    expect(simulatorSource).toMatch(
      /hasSimulated\s*\?\s*["']docked["']\s*:\s*["']hero["']/
    )
    expect(simulatorSource).toMatch(/data-state=\{hasSimulated/)
    expect(simulatorSource).toMatch(/min-h-\[(55|60)vh\]/)
    expect(simulatorSource).toContain("max-w-3xl")
    expect(simulatorSource).toContain("top-docked")
  })
})

describe("R-SIM AC-R-SIM-2: Simulate docks the layout, results render after the wrapper", () => {
  it("docks on Simulate and renders the pipeline AFTER (outside) the wrapper", async () => {
    renderRouting()
    await openSimulator()

    expect(screen.getByTestId("simulator-layout")).toHaveAttribute(
      "data-state",
      "hero"
    )

    simulateCurrentInput("distributed systems benchmarks")

    const docked = screen.getByTestId("simulator-layout")
    expect(docked).toHaveAttribute("data-state", "docked")
    expect(docked.className).toContain("top-docked")
    expect(docked.className).not.toMatch(/min-h-\[(55|60)vh\]/)
    expectTransitionClasses(docked)

    const ingress = screen.getByText("Client Ingress", { exact: true })
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
    expect(screen.getByText(/Failover cascade/i)).toBeInTheDocument()

    // Results live below the docked composer, never inside it.
    expect(docked.contains(ingress)).toBe(false)
    const composer = screen.getByTestId("simulator-composer")
     
    expect(composer.compareDocumentPosition(ingress) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe("R-SIM AC-R-SIM-3: smooth same-element transition retains focus and value", () => {
  it("keeps the SAME input + composer nodes, value, and focus across hero->docked", async () => {
    renderRouting()
    await openSimulator()

    const inputBefore = screen.getByPlaceholderText(
      "Type simulated query...",
      { exact: true }
    ) as HTMLInputElement
    const composerBefore = screen.getByTestId("simulator-composer")
    const wrapperBefore = screen.getByTestId("simulator-layout")
    expectTransitionClasses(wrapperBefore)

    fireEvent.change(inputBefore, { target: { value: "keep me docked" } })
    inputBefore.focus()
    expect(inputBefore).toHaveFocus()
    fireEvent.click(screen.getByRole("button", { name: /^Simulate route$/ }))

    await waitFor(() => {
      expect(screen.getByText("Client Ingress", { exact: true })).toBeInTheDocument()
    })

    const inputAfter = screen.getByPlaceholderText(
      "Type simulated query...",
      { exact: true }
    ) as HTMLInputElement
    expect(inputAfter).toBe(inputBefore)
    expect(screen.getByTestId("simulator-composer")).toBe(composerBefore)
    expect(inputAfter).toHaveValue("keep me docked")
    expect(inputAfter).toHaveFocus()

    const wrapperAfter = screen.getByTestId("simulator-layout")
    expect(wrapperAfter).toHaveAttribute("data-state", "docked")
    expectTransitionClasses(wrapperAfter)
  })
})

describe("R-SIM AC-R-SIM-4: Simulate composer via shared ComposerShell (no footer)", () => {
  it("renders the inputRow inside simulator-composer with exact Search tokens and a borderless input", async () => {
    renderRouting()
    await openSimulator()

    const composer = screen.getByTestId("simulator-composer")
    expectComposerBoxClasses(composer)
    expect(composer.className).toContain("rounded-xl")
    expect(composer.className).toContain("bg-[var(--elevated)]")
    expect(composer.className).toContain("border-[var(--border-subtle)]")
    expect(composer.className).toContain("shadow-lg")
    expect(composer.className).toContain("focus-within:border-[var(--signal)]/60")
    expect(composer.className).toContain("motion-reduce:transition-none")

    const input = screen.getByPlaceholderText(
      "Type simulated query...",
      { exact: true }
    ) as HTMLInputElement
    expect(composer.contains(input)).toBe(true)
    expect(input.getAttribute("type")).toBe("text")
    // Box owns the border: the input itself is borderless (no bare underline).
    expect(input.style.borderBottom).toBe("")
    expect((input.getAttribute("style") ?? "").toLowerCase()).not.toContain(
      "border-bottom"
    )
    // Icon prefix lives in the input row inside the box.
    expect(composer.querySelector("svg")).not.toBeNull()
  })

  it("keeps the submit button with search icon inside the composer", async () => {
    renderRouting()
    await openSimulator()

    const composer = screen.getByTestId("simulator-composer")
    const button = screen.getByRole("button", { name: /^Simulate route$/ })
    expect(composer.contains(button)).toBe(true)
    expect(button.textContent?.trim()).toBe("Simulate route")
    expect(button.querySelector("svg")).not.toBeNull()
  })

  it("renders divider and footer inside the Simulator shell", async () => {
    renderRouting()
    await openSimulator()

    expect(screen.getByTestId("simulator-composer")).toBeInTheDocument()
    expect(screen.getByTestId("simulator-composer-divider")).toBeInTheDocument()
    expect(screen.getByTestId("simulator-composer-footer")).toBeInTheDocument()
  })

  it("keeps the SegmentedControl inside the composer footer", async () => {
    renderRouting()
    await openSimulator()

    const group = screen.getByRole("group", { name: "Simulator operation" })
    expect(
      within(group).getByRole("button", { name: "Search", exact: true })
    ).toHaveAttribute("aria-pressed", "true")
    expect(
      within(group).getByRole("button", { name: "Fetch", exact: true })
    ).toHaveAttribute("aria-pressed", "false")
    expect(
      screen.getByRole("heading", { name: "Route simulator" })
    ).toBeInTheDocument()
  })

  it("wires the shell via ComposerShell testIdPrefix=simulator with footer prop (source)", () => {
    expect(simulatorSource).toMatch(
      /from\s+["']@\/components\/common\/ComposerShell["']/
    )
    expect(simulatorSource).toContain("ComposerShell")
    expect(simulatorSource).toMatch(/testIdPrefix\s*=\s*("simulator"|\{"simulator"\})/)
    expect(simulatorSource).toMatch(/footer\s*[=:{]/)
    expect(simulatorSource).toContain("SegmentedControl")
    expect(simulatorSource).toContain("Simulator operation")
  })
})

describe("R-SIM AC-R-SIM-5: operation toggle resets to hero", () => {
  it("switching Search/Fetch clears the run back to hero and swaps the placeholder", async () => {
    const user = userEvent.setup()
    renderRouting()
    await openSimulator()

    simulateCurrentInput("reset me")
    await waitFor(() => {
      expect(screen.getByText("Client Ingress", { exact: true })).toBeInTheDocument()
    })
    expect(screen.getByTestId("simulator-layout")).toHaveAttribute(
      "data-state",
      "docked"
    )

    await user.click(screen.getByRole("button", { name: "Fetch", exact: true }))

    const wrapper = screen.getByTestId("simulator-layout")
    expect(wrapper).toHaveAttribute("data-state", "hero")
    expectHeroGeometry(wrapper)
    expectTransitionClasses(wrapper)
    expect(screen.queryByText("Client Ingress", { exact: true })).not.toBeInTheDocument()
    expect(
      screen.getByPlaceholderText("Type simulated URL...", { exact: true })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Fetch", exact: true })
    ).toHaveAttribute("aria-pressed", "true")

    await user.click(screen.getByRole("button", { name: "Search", exact: true }))
    expect(screen.getByTestId("simulator-layout")).toHaveAttribute(
      "data-state",
      "hero"
    )
    expect(
      screen.getByPlaceholderText("Type simulated query...", { exact: true })
    ).toBeInTheDocument()
  })

  it("resets via hasSimulated=false on operation change (source)", () => {
    expect(simulatorSource).toContain("setHasSimulated(false)")
    expect(simulatorSource).toContain("handleOperationChange")
  })
})

describe("R-SIM AC-R-SIM-6: empty-eligible state", () => {
  it("shows the empty message with no pipeline in hero when nothing is eligible", async () => {
    const disabled = allProvidersFixture().map((p) => ({ ...p, enabled: false }))
    renderRouting(disabled as WireProviderStatus[])
    await openSimulator()

    expect(screen.getByText(/no eligible providers/i)).toBeInTheDocument()
    expect(screen.queryByText("Client Ingress", { exact: true })).not.toBeInTheDocument()
    expect(screen.getByTestId("simulator-layout")).toHaveAttribute(
      "data-state",
      "hero"
    )
  })

  it("Simulate with zero eligible only flips the gate (docked + message, still no pipeline)", async () => {
    const disabled = allProvidersFixture().map((p) => ({ ...p, enabled: false }))
    renderRouting(disabled as WireProviderStatus[])
    await openSimulator()

    fireEvent.click(screen.getByRole("button", { name: /^Simulate route$/ }))

    const wrapper = screen.getByTestId("simulator-layout")
    expect(wrapper).toHaveAttribute("data-state", "docked")
    expect(wrapper.className).toContain("top-docked")
    expect(screen.getByText(/no eligible providers/i)).toBeInTheDocument()
    expect(screen.queryByText("Client Ingress", { exact: true })).not.toBeInTheDocument()
  })
})

describe("R-SIM AC-R-PGF1-1: blessed pg-f1 simulator guard updated (NOT a regression)", () => {
  it("pg-f1 expects the Simulator shell instead of the stale no-shell guard", () => {
    expect(pgf1Source).not.toContain(
      'expect(simulatorSource).not.toContain("ComposerShell")'
    )
    expect(pgf1Source).toContain('expect(simulatorSource).toContain("ComposerShell")')
    expect(pgf1Source).toContain('expect(simulatorSource).toContain("simulator-layout")')
    expect(pgf1Source).toContain(
      'expect(simulatorSource).not.toContain("fetch-composer")'
    )
    expect(pgf1Source).toContain(
      'expect(simulatorSource).not.toContain("search-composer")'
    )
  })
})

describe("R-SIM AC-R-REG-1: regressions stay GREEN (Search/Fetch, bar, tabs, logic)", () => {
  it("Search/Fetch playground seams intact (layouts + fetch shell, search NOT migrated)", () => {
    expect(playgroundSource).toContain('data-testid="search-layout"')
    expect(playgroundSource).toContain('data-testid="fetch-layout"')
    expect(playgroundSource).toContain("hasSearchContent")
    expect(playgroundSource).toContain("hasFetchContent")
    expect(playgroundSource).toContain('data-testid="search-composer"')
    expect(playgroundSource).toMatch(/testIdPrefix\s*=\s*["']fetch["']/)
    expect(playgroundSource).not.toMatch(/testIdPrefix\s*=\s*["']search["']/)
    expect(playgroundSource).not.toMatch(/testIdPrefix\s*=\s*["']simulator["']/)
  })

  it("adds NO Enter-submit form to the simulator", () => {
    expect(simulatorSource).not.toContain("<form")
    expect(simulatorSource).not.toContain("onSubmit")
    expect(simulatorSource).toContain("handleSimulate")
  })

  it("leaves simulator + strategy logic untouched", () => {
    expect(simulatorSource).toContain("submittedOp")
    expect(simulatorSource).toContain("getEligibleProviders")
    expect(simulatorSource).toContain("getProviderReason")
    expect(simulatorSource).toContain("SIMULATOR_OPERATIONS")
    expect(simulatorSource).toContain("Type simulated query...")
    expect(simulatorSource).toContain("Type simulated URL...")
    expect(strategySource).toContain("setRoutingPreset")
    expect(strategySource).toContain("updateCostPreset")
    expect(strategySource).toContain("STRATEGY_CARDS")
  })

  it("R1 StatusBar still owns page status (single source, App renders once)", () => {
    expect(existsSync(statusBarPath)).toBe(true)
    expect(appSource).toMatch(/from\s+["']@\/components\/layout\/StatusBar["']/)
    expect(appSource.match(/<StatusBar/g) ?? []).toHaveLength(1)
  })

  it("routing tabs intact with no page-level status cluster reintroduced", async () => {
    renderRouting()
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /^Routing$/ })).toBeInTheDocument()
    })
    expect(screen.getAllByRole("tab")).toHaveLength(4)
    for (const label of ["Strategy", "Simulator", "Ranks", "Resilience"]) {
      expect(
        screen.getByRole("tab", { name: new RegExp(`^${label}$`) })
      ).toBeInTheDocument()
    }
    expect(screen.queryByText("Failover active", { exact: true })).toBeNull()
    expect(screen.queryByText("Failover inactive", { exact: true })).toBeNull()
    expect(screen.queryByText(/providers eligible/)).toBeNull()
  })

  it("R1 bar renders on the routing route beside the Strategy cards", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(allProvidersFixture())
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(routingConfigFixture())
      }
      if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
      if (req.url === "/search" && req.method === "POST") {
        return ok(searchResponseFixture())
      }
      if (req.url === "/fetch" && req.method === "POST") {
        return ok(fetchResponseFixture())
      }
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <MemoryRouter initialEntries={["/routing"]}>
        <App />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByTestId("status-bar")).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText("7 of 7 providers")).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText(/Failover (active|inactive)/)).toBeInTheDocument()
    })
    expect(screen.getAllByText(/Failover (active|inactive)/)).toHaveLength(1)
    expect(screen.queryByText(/providers eligible/)).toBeNull()
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /^Strict priority/ })
      ).toBeInTheDocument()
    })
  })
})
