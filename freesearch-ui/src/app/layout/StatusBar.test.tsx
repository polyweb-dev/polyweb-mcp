import React, { act } from "@testing-library/react"
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs"
import path from "node:path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import App from "@/App"
import { deferred, err, installFetchStub, ok } from "@/test/fetchMock"
import { accessResponseFixture, adminAccountFixture, agentAccountFixture } from "@/test/authFixtures"
import { installFakeChannel, installImmediateLocks, removeLocks } from "@/test/browserStubs"
import type { UserAccount } from "@/domains/auth/model/types"
import {
  allProvidersFixture,
  dashboardFixture,
  fetchResponseFixture,
  routingConfigFixture,
  searchResponseFixture,
  type WireProviderStatus,
} from "@/test/backendFixtures"

describe("StatusBar.r1.test.tsx", () => {

/**
 * R1 bottom status bar — BDD Acceptance (RED phase).
 *
 * User bullet NEW (verbatim, feedback.md L47): reusable provider/failover
 * status in a tiny VSCode-like bottom bar (image-29), placed correctly with
 * sidebar + borders (image-33), REMOVE page-level symbols from playground
 * (image-20) + routing (image-19), clickable for detailed info (image-34).
 * Images seen: image-19/20/29/33/34. PG-F1 committed — preserve
 * ComposerShell + layouts.
 *
 * Plan CONFIRMED (orchestrator rulings: NO right-side extras beyond preset;
 * popover display-only, no deep-links):
 *   - NEW layout/StatusBar.tsx (no props, useFreeSearch internally; h-6
 *     text-12px bg-elevated border-t border-subtle muted tnum; provider
 *     "N of M providers" via getEligibleProviders search+preset + Failover
 *     active/inactive unified wording; button trigger aria-expanded/controls
 *     + popover above bar role dialog/status with detail rows from context
 *     only + Esc/outside-close + focus return)
 *   - App.tsx right-column wrapper (outer flex-row intact, bar in-flow
 *     sticky bottom-0, drawer z-50 above)
 *   - DELETE header clusters in SearchPlayground + RoutingEngine (keep
 *     headings/PillTabs/composers/panels/select logic). freesearch-ui/ ONLY.
 *
 * AC mapping:
 *   AC-R1-1  StatusBar module contract (file/exports, no props,
 *            useFreeSearch, getEligibleProviders search+preset +
 *            fallbackConfig, context-only, a11y tokens, no links, no z-50)
 *   AC-R1-2  Bar geometry tokens (testid, h-6, 12px, RESOLVING
 *            bg-[var(--elevated)] / border-[var(--border-subtle)] /
 *            text-[var(--muted)] + tnum; index.css chain #252526/#8B94A7;
 *            in-flow, no fixed/absolute)
 *   AC-R1-3  Bar content (exact "N of M providers" + "Failover
 *            active/inactive"; never "Fallback"/"disabled")
 *   AC-R1-4  Bar on BOTH routes with identical text; single source
 *            (App imports/renders once; exactly one count + one Failover
 *            per route)
 *   AC-R1-5  Placement (outer flex-row intact; bar shares main's parent,
 *            after main, outside aside; sticky bottom-0; border-t;
 *            drawer z-50 above bar)
 *   AC-R1-6  Popover open (single button trigger, aria-expanded/controls,
 *            role dialog/status, id match, above-bar positioning, detail
 *            rows from context only, display-only with zero links, no
 *            metric extras in bar)
 *   AC-R1-7  Popover close (toggle, Esc + focus return, outside mousedown)
 *   AC-R1-8  Removals (no page-level clusters in sources or DOM;
 *            headings/PillTabs/composers/panels/select logic intact)
 *   AC-R1-9  Edge states (loading neutral hides Failover; error muted
 *            hides Failover; 0-of-N exact)
 *   AC-R1-10 Regressions (ComposerShell, search/fetch layouts, live
 *            fetching round-trip, app shell)
 *
 * RED expectation: every AC-R1-* FAILS cleanly against the current codebase
 * (no layout/StatusBar.tsx; App never renders <StatusBar>; page-level
 * "Fallback …" + "N providers" / "Failover …" + "N of M providers eligible"
 * clusters still in SearchPlayground/RoutingEngine). AC-R1-10 stays GREEN.
 */

const testDir = import.meta.dirname
// Slice 4: StatusBar shell in app/layout/StatusBar.tsx, pure summary in
// app/layout/statusSummary.ts, popover siblings alongside; DashboardShell
// owns the Routes table + shell; ComposerShell in shared/ui.
const statusBarPath = path.resolve(testDir, "../../app/layout/StatusBar.tsx")
const statusSummaryPath = path.resolve(testDir, "../../app/layout/statusSummary.ts")
const providerPopoverPath = path.resolve(
  testDir,
  "../../app/layout/ProviderStatusPopover.tsx"
)
const failoverPopoverPath = path.resolve(
  testDir,
  "../../app/layout/FailoverStatusPopover.tsx"
)
const dashboardShellPath = path.resolve(testDir, "../../app/DashboardShell.tsx")
const sharedComposerShellPath = path.resolve(
  testDir,
  "../../shared/ui/ComposerShell.tsx"
)
const sidebarOwnerPath = path.resolve(testDir, "../../app/layout/Sidebar.tsx")
const appPath = path.resolve(testDir, "../../App.tsx")
// Slice 5 moved the playground/routing pages into features/: the routing
// entry point stays as a compat shim while the playground shell was removed
// (CLEANUP 1.1, DashboardShell renders the feature directly). Content asserts
// run against the feature owners (playground page content is split across
// its feature, routing through its workbench shell).
const removedPlaygroundShimPath = path.resolve(testDir, "../../components/search/SearchPlayground.tsx")
const playgroundOwnerDir = path.resolve(testDir, "../../features/playground")
const routingEntryPath = path.resolve(testDir, "../../components/routing/RoutingEngine.tsx")
const routingOwnerPath = path.resolve(
  testDir,
  "../../features/routing/ui/RoutingEngine.tsx"
)
const removedComposerShimPath = path.resolve(testDir, "../../components/common/ComposerShell.tsx")
const sidebarPath = path.resolve(testDir, "../../components/layout/Sidebar.tsx")
const indexCssPath = path.resolve(testDir, "../../index.css")

const appSource = readFileSync(appPath, "utf8")
const dashboardShellSource = readFileSync(dashboardShellPath, "utf8")
const sidebarOwnerSource = readFileSync(sidebarOwnerPath, "utf8")
const sharedComposerShellSource = readFileSync(sharedComposerShellPath, "utf8")

/** Concatenated non-test sources under a feature directory, sorted. */
function readDirSources(dir: string): string {
  const names = readdirSync(dir, { withFileTypes: true })
    .map((entry) => entry.name)
    .sort()
  const parts: string[] = []
  for (const name of names) {
    const full = path.join(dir, name)
    if (statSync(full).isDirectory()) {
      parts.push(readDirSources(full))
    } else if (/\.tsx?$/.test(name) && !/\.test\./.test(name)) {
      parts.push(readFileSync(full, "utf8"))
    }
  }
  return parts.join("\n")
}

const routingShimSource = readFileSync(routingEntryPath, "utf8")
const playgroundSource = readDirSources(playgroundOwnerDir)
const routingSource = readFileSync(routingOwnerPath, "utf8")
const sidebarSource = readFileSync(sidebarPath, "utf8")
const indexCssSource = readFileSync(indexCssPath, "utf8")

function statusBarSource(): string {
  try {
    return readFileSync(statusBarPath, "utf8")
  } catch {
    return ""
  }
}

function statusSummarySource(): string {
  return readFileSync(statusSummaryPath, "utf8")
}

function providerPopoverSource(): string {
  return readFileSync(providerPopoverPath, "utf8")
}

function failoverPopoverSource(): string {
  return readFileSync(failoverPopoverPath, "utf8")
}

function statusSources(): string[] {
  return [
    statusBarSource(),
    statusSummarySource(),
    providerPopoverSource(),
    failoverPopoverSource(),
  ]
}

function stubBackend(opts: {
  providers?: WireProviderStatus[]
  routingHandler?: () => Response
  searchHandler?: () => Response
  fetchHandler?: () => Response
  account?: UserAccount
} = {}) {
  installImmediateLocks()
  installFakeChannel()
  return installFetchStub((req) => {
    if (req.url === "/auth/jwt/refresh" && req.method === "POST") {
      return ok(accessResponseFixture())
    }
    if (req.url === "/users/me" && req.method === "GET") {
      return ok(opts.account ?? adminAccountFixture())
    }
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(opts.providers ?? allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return opts.routingHandler ? opts.routingHandler() : ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url === "/search" && req.method === "POST") {
      return opts.searchHandler ? opts.searchHandler() : ok(searchResponseFixture())
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return opts.fetchHandler ? opts.fetchHandler() : ok(fetchResponseFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
}

async function renderAppAt(route: string) {
  stubBackend()
  const result = render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>
  )
  await screen.findByTestId("status-bar")
  return result
}

/** Mount App and wait until the bar shows live counts + Failover wording. */
async function renderAppReady(route: string): Promise<HTMLElement> {
  await renderAppAt(route)
  await waitFor(() => {
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
  })
  await waitFor(() => {
    expect(screen.getByText(/Failover (active|inactive)/)).toBeInTheDocument()
  })
  await waitFor(() => {
    expect(screen.getByText(/\d+ of \d+ providers/)).toBeInTheDocument()
  })
  return screen.getByTestId("status-bar") as HTMLElement
}

function barEl(): HTMLElement {
  return screen.getByTestId("status-bar") as HTMLElement
}

/** Popover trigger button by accessible name. */
function triggerEl(name: RegExp | string = /providers/i): HTMLElement {
  const bar = barEl()
  if (bar.tagName === "BUTTON") return bar
  return within(bar).getByRole("button", { name }) as HTMLElement
}

beforeEach(() => {
  window.localStorage.clear()
  installImmediateLocks()
  installFakeChannel()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  removeLocks()
})

describe("AC-R1-1: StatusBar module contract", () => {
  it("exists at layout/StatusBar.tsx and exports StatusBar", () => {
    expect(existsSync(statusBarPath)).toBe(true)
    expect(statusBarSource()).toContain("StatusBar")
    expect(statusBarSource()).toMatch(/export\s+(function|const)\s+StatusBar/)
    // Migration complete: the old layout shell is gone (see git history); the app owner above is canonical.
  })

  it("takes no props (prop-less component)", () => {
    expect(existsSync(statusBarPath)).toBe(true)
    const src = statusBarSource()
    expect(src.toLowerCase()).not.toContain("props")
    expect(src).not.toContain("StatusBarProps")
  })

  it("reads live state via useFreeSearch internally", () => {
    expect(statusBarSource()).toContain("useFreeSearch")
    expect(statusBarSource()).toMatch(/from\s+["']@\/context\/useFreeSearch["']/)
  })

  it("derives the count via getEligibleProviders with search + routingPreset", () => {
    // Pure summary helper owns the routing-policy derivation via the routing
    // public API; the bar consumes the helper.
    const src = statusSummarySource()
    expect(src).toContain("getEligibleProviders")
    expect(src).toContain('"search"')
    expect(src).toContain("routingPreset")
    expect(src).toContain("fallbackConfig")
    expect(src).toMatch(/from\s+["']@\/domains\/routing["']/)
    expect(statusBarSource()).toContain("getStatusSummary")
  })

  it("is context-only: never fetches or touches backend routes directly", () => {
    expect(existsSync(statusBarPath)).toBe(true)
    for (const src of statusSources()) {
      expect(src.length).toBeGreaterThan(0)
      expect(src).not.toContain("apiService")
      expect(src).not.toContain("/api/")
      expect(src).not.toContain("127.0.0.1")
      expect(src).not.toContain("http://")
    }
  })

  it("carries the a11y + behavior tokens (aria, Escape, outside, focus, role, above-bar)", () => {
    const src = statusBarSource()
    expect(src).toContain("aria-expanded")
    expect(src).toContain("aria-controls")
    expect(src).toContain("Escape")
    expect(src).toContain(".focus()")
    expect(src.includes("mousedown") || src.includes("pointerdown")).toBe(true)
    // Popover siblings own the dialog role + above-bar positioning.
    const popovers = providerPopoverSource() + failoverPopoverSource()
    expect(popovers).toMatch(/role="(dialog|status)"/)
    expect(popovers).toContain("absolute")
    expect(popovers).toMatch(/bottom-(full|6|7|8)/)
  })

  it("has no deep-links (popover is display-only)", () => {
    expect(existsSync(statusBarPath)).toBe(true)
    for (const src of statusSources()) {
      expect(src.length).toBeGreaterThan(0)
      expect(src).not.toContain("<a")
      expect(src).not.toContain("href")
      expect(src).not.toContain("NavLink")
      expect(src).not.toContain("useNavigate")
    }
  })

  it("stays below the navigation drawer (no z-50 in the bar)", () => {
    expect(sidebarOwnerSource).toContain("z-50")
    // Old sidebar path stays as a compat shim over the app owner.
    expect(sidebarSource).toMatch(/from\s+["']@\/app\/layout\/Sidebar["']/)
    expect(existsSync(statusBarPath)).toBe(true)
    for (const src of statusSources()) {
      expect(src.length).toBeGreaterThan(0)
      expect(src).not.toContain("z-50")
    }
  })
})

describe("AC-R1-2: bar geometry tokens", () => {
  it("renders data-testid=status-bar on the playground route", async () => {
    await renderAppAt("/playground")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
  })

  it("renders data-testid=status-bar on the routing route", async () => {
    await renderAppAt("/routing")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
  })

  it("is a tiny h-6 bar with 12px type", async () => {
    await renderAppAt("/playground")
    const bar = barEl()
    expect(bar.className).toContain("h-6")
    expect(bar.className).toMatch(/text-(\[12px\]|12px)/)
  })

  it("uses the elevated surface, top border, muted text, and tabular numerals", async () => {
    await renderAppAt("/playground")
    const bar = barEl()
    // FINAL REVIEW: resolving arbitrary-value forms ONLY — the bare aliases
    // (bg-elevated / border-subtle / text-muted) never resolve to CSS tokens.
    expect(bar.className).toContain("bg-[var(--elevated)]")
    expect(bar.className).toContain("border-t")
    expect(bar.className).toContain("border-[var(--border-subtle)]")
    expect(bar.className).toContain("text-[var(--muted)]")
    expect(bar.className).toContain("tnum")
  })

  it("resolves tokens to the Carbon Black palette (#252526 elevated, #8B94A7 muted)", () => {
    // Token chain: index.css definitions (deterministic source proof —
    // jsdom never evaluates Tailwind, so no computed-style assert here)
    // plus the bar's resolving class forms that consume them.
    const norm = (value: string): string => value.toLowerCase().replace(/\s+/g, "")
    expect(norm(indexCssSource)).toContain(norm("--elevated: #252526"))
    expect(norm(indexCssSource)).toContain(norm("--muted: #8B94A7"))
    expect(norm(statusBarSource())).toContain(norm("bg-[var(--elevated)]"))
    expect(norm(statusBarSource())).toContain(norm("border-[var(--border-subtle)]"))
    expect(norm(statusBarSource())).toContain(norm("text-[var(--muted)]"))
  })

  it("is in-flow (never fixed/absolute on the bar root)", async () => {
    await renderAppAt("/playground")
    const bar = barEl()
    expect(bar.className).not.toContain("fixed")
    expect(bar.className.split(/\s+/).includes("absolute")).toBe(false)
  })
})

describe("AC-R1-3: bar content (unified wording)", () => {
  it('shows the exact unified count "7 of 7 providers" on playground', async () => {
    await renderAppAt("/playground")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
    await waitFor(() => {
      expect(barEl().textContent).toContain("8 of 8 providers")
    })
  })

  it('shows the unified "Failover active" wording on playground', async () => {
    await renderAppAt("/playground")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
    await waitFor(() => {
      expect(barEl().textContent).toContain("Failover active")
    })
    expect(barEl().textContent).not.toContain("Fallback")
    expect(barEl().textContent).not.toContain("disabled")
  })

  it('shows the same unified content on routing ("7 of 7 providers" + "Failover active")', async () => {
    await renderAppAt("/routing")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
    await waitFor(() => {
      expect(barEl().textContent).toContain("8 of 8 providers")
    })
    await waitFor(() => {
      expect(barEl().textContent).toContain("Failover active")
    })
  })

  it("never shows the legacy playground Fallback wording anywhere", async () => {
    await renderAppAt("/playground")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
    await waitFor(() => {
      expect(barEl().textContent).toContain("8 of 8 providers")
    })
    expect(screen.queryByText(/Fallback/)).toBeNull()
  })
})

describe("AC-R1-4: single source on both routes", () => {
  it("App imports StatusBar from layout and renders it exactly once", () => {
    expect(dashboardShellSource).toMatch(/from\s+["']@\/app\/layout\/StatusBar["']/)
    expect(dashboardShellSource).toContain("<StatusBar")
    expect(dashboardShellSource.match(/<StatusBar/g) ?? []).toHaveLength(1)
    // Thin App shim renders the shell that owns the single StatusBar.
    expect(appSource).toContain("DashboardShell")
  })

  it("playground shows exactly one count and exactly one Failover claim", async () => {
    await renderAppAt("/playground")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText(/\d+ of \d+ providers/)).toBeInTheDocument()
    })
    expect(screen.getAllByText(/\d+ of \d+ providers/)).toHaveLength(1)
    expect(screen.getAllByText(/Failover (active|inactive)/)).toHaveLength(1)
    expect(screen.queryByText(/^\d+ providers$/)).toBeNull()
  })

  it("routing shows exactly one count and exactly one Failover claim", async () => {
    await renderAppAt("/routing")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText(/\d+ of \d+ providers/)).toBeInTheDocument()
    })
    expect(screen.getAllByText(/\d+ of \d+ providers/)).toHaveLength(1)
    expect(screen.getAllByText(/Failover (active|inactive)/)).toHaveLength(1)
  })

  it("both routes render byte-identical bar text (one shared source)", async () => {
    stubBackend()
    const first = render(
      <MemoryRouter initialEntries={["/playground"]}>
        <App />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText("8 of 8 providers")).toBeInTheDocument()
    })
    const playgroundText = screen.getByTestId("status-bar").textContent
    first.unmount()

    render(
      <MemoryRouter initialEntries={["/routing"]}>
        <App />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getByText("8 of 8 providers")).toBeInTheDocument()
    })
    const routingText = screen.getByTestId("status-bar").textContent
    expect(routingText).toBe(playgroundText)
  })
})

describe("AC-R1-5: placement (right column, borders, shell intact)", () => {
  it("App source keeps the outer flex-row shell and adds an in-flow sticky bar", () => {
    expect(dashboardShellSource).toMatch(/flex-row/)
    expect(dashboardShellSource).not.toContain("fixed")
    expect(dashboardShellSource).toContain("sticky")
    expect(dashboardShellSource).toContain("bottom-0")
    // Thin App shim renders the shell that owns the layout.
    expect(appSource).toContain("DashboardShell")
  })

  it("outer shell still lays out horizontally with aside + main", async () => {
    await renderAppAt("/playground")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
    const aside = document.querySelector("aside") as HTMLElement
    const shell = aside.parentElement as HTMLElement
    expect(shell.className).toMatch(/flex/)
    expect(shell.className).toMatch(/flex-row/)
    expect(shell.className).not.toMatch(/flex-col/)
    expect(shell.contains(screen.getByRole("main"))).toBe(true)
  })

  it("bar lives in the right column: same parent as main, after main, outside aside", async () => {
    await renderAppAt("/playground")
    const bar = barEl()
    const main = screen.getByRole("main")
    expect(bar.parentElement).toBe(main.parentElement)
    expect(main.compareDocumentPosition(bar)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    expect((document.querySelector("aside") as HTMLElement).contains(bar)).toBe(false)
  })

  it("bar sticks to the bottom in-flow with a top border", async () => {
    await renderAppAt("/playground")
    const bar = barEl()
    expect(bar.className).toContain("sticky")
    expect(bar.className).toContain("bottom-0")
    expect(bar.className).toContain("border-t")
    // FINAL REVIEW: resolving form only — bare "border-subtle" never resolves.
    expect(bar.className).toContain("border-[var(--border-subtle)]")
  })
})

describe("AC-R1-6: popover opens with context-only detail rows", () => {
  it("exposes two button triggers starting collapsed with aria controls", async () => {
    await renderAppReady("/playground")
    const bar = barEl()
    const inner = within(bar).queryAllByRole("button")
    if (bar.tagName === "BUTTON") {
      expect(inner).toHaveLength(0)
    } else {
      expect(inner).toHaveLength(2)
    }
    const trigger = triggerEl(/providers/i)
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    const controlsId = trigger.getAttribute("aria-controls") ?? ""
    expect(controlsId.length).toBeGreaterThan(0)
    expect(document.getElementById(controlsId)).toBeNull()
    expect(trigger.textContent).toMatch(/providers/)

    const failoverTrigger = triggerEl(/failover/i)
    expect(failoverTrigger.getAttribute("aria-expanded")).toBe("false")
    const failoverControlsId = failoverTrigger.getAttribute("aria-controls") ?? ""
    expect(failoverControlsId.length).toBeGreaterThan(0)
    expect(document.getElementById(failoverControlsId)).toBeNull()
    expect(failoverTrigger.textContent).toMatch(/failover/i)
  })

  it("click opens the popover with matching id and role dialog/status", async () => {
    const user = userEvent.setup()
    await renderAppReady("/playground")
    const trigger = triggerEl(/providers/i)
    const controlsId = trigger.getAttribute("aria-controls") as string

    await user.click(trigger)

    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    const popover = document.getElementById(controlsId) as HTMLElement
    expect(popover).not.toBeNull()
    expect(["dialog", "status"]).toContain(popover.getAttribute("role"))
  })

  it("popover floats above the bar (absolute + bottom offset inside a relative anchor)", async () => {
    const user = userEvent.setup()
    await renderAppReady("/playground")
    const bar = barEl()
    const trigger = triggerEl(/providers/i)
    await user.click(trigger)
    const popover = document.getElementById(
      trigger.getAttribute("aria-controls") as string
    ) as HTMLElement
    expect(popover.className).toContain("absolute")
    expect(popover.className).toMatch(/bottom-(full|6|7|8|10|12)/)
    expect(
      bar.className.includes("relative") ||
        (bar.parentElement as HTMLElement).className.includes("relative")
    ).toBe(true)
  })

  it("popover detail rows come from context (provider names + Failover + counts)", async () => {
    const user = userEvent.setup()
    await renderAppReady("/playground")
    const trigger = triggerEl(/providers/i)
    await user.click(trigger)
    const popover = document.getElementById(
      trigger.getAttribute("aria-controls") as string
    ) as HTMLElement
    expect(popover.textContent).toContain("Brave Search")
    expect(popover.textContent).toContain("Keenable")
    expect(popover.textContent).toContain("8 of 8 providers")

    const failoverTrigger = triggerEl(/failover/i)
    await user.click(failoverTrigger)
    const failoverPopover = document.getElementById(
      failoverTrigger.getAttribute("aria-controls") as string
    ) as HTMLElement
    expect(failoverPopover.textContent).toContain("Failover active")
    expect(failoverPopover.textContent).toContain("Fallback chaining")
  })

  it("popover is display-only: zero links or anchors", async () => {
    const user = userEvent.setup()
    await renderAppReady("/playground")
    const trigger = triggerEl()
    await user.click(trigger)
    const popover = document.getElementById(
      trigger.getAttribute("aria-controls") as string
    ) as HTMLElement
    expect(popover.querySelector("a")).toBeNull()
    expect(within(popover).queryByRole("link")).toBeNull()
  })

  it("bar carries no right-side metric extras beyond the unified status", async () => {
    await renderAppReady("/playground")
    const text = barEl().textContent ?? ""
    expect(text).not.toMatch(/\b(latency|cost|quota|units|hops)\b/i)
    expect(text).not.toMatch(/\d+\s*ms/i)
  })
})

describe("AC-R1-7: popover close (toggle / Esc + focus return / outside)", () => {
  it("toggles closed on a second trigger click", async () => {
    const user = userEvent.setup()
    await renderAppReady("/playground")
    const trigger = triggerEl()
    const controlsId = trigger.getAttribute("aria-controls") as string

    await user.click(trigger)
    expect(document.getElementById(controlsId)).not.toBeNull()

    await user.click(trigger)
    expect(document.getElementById(controlsId)).toBeNull()
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
  })

  it("Escape closes the popover and returns focus to the trigger", async () => {
    const user = userEvent.setup()
    await renderAppReady("/playground")
    const trigger = triggerEl()
    const controlsId = trigger.getAttribute("aria-controls") as string

    await user.click(trigger)
    expect(document.getElementById(controlsId)).not.toBeNull()

    await user.keyboard("{Escape}")

    expect(document.getElementById(controlsId)).toBeNull()
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(document.activeElement).toBe(trigger)
  })

  it("outside mousedown closes the popover", async () => {
    const user = userEvent.setup()
    await renderAppReady("/playground")
    const trigger = triggerEl()
    const controlsId = trigger.getAttribute("aria-controls") as string

    await user.click(trigger)
    expect(document.getElementById(controlsId)).not.toBeNull()

    fireEvent.mouseDown(document.body)
    fireEvent.click(document.body)

    expect(document.getElementById(controlsId)).toBeNull()
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
  })
})

describe("AC-R1-8: page-level clusters removed, views intact", () => {
  it("playground entry is the canonical feature; routing entry stays as compat shim", () => {
    expect(existsSync(removedPlaygroundShimPath)).toBe(false)
    expect(dashboardShellSource).toMatch(/from\s+["']@\/features\/playground/)
    expect(dashboardShellSource).toContain("PlaygroundPage")
    expect(existsSync(routingEntryPath)).toBe(true)
    expect(routingShimSource).toMatch(/from\s+["']@\/features\/routing/)
    expect(routingShimSource).toContain("RoutingEngine")
  })

  it("SearchPlayground source drops its provider/failover cluster", () => {
    expect(playgroundSource).not.toContain("Fallback")
    expect(playgroundSource).not.toContain("fallbackConfig")
    expect(playgroundSource).not.toMatch(/eligibleProviders\.length\}\s*providers/)
  })

  it("SearchPlayground keeps heading, tabs, composers, panels, and select logic", () => {
    expect(playgroundSource).toContain("Search Playground")
    expect(playgroundSource).toContain("PillTabs")
    expect(playgroundSource).toContain('data-testid="search-composer"')
    expect(playgroundSource).toContain('data-testid="search-layout"')
    expect(playgroundSource).toContain('data-testid="fetch-layout"')
    expect(playgroundSource).toContain("eligibleProviders")
    expect(playgroundSource).toContain("Auto arbitration")
    expect(playgroundSource).toContain("ProviderSelect")
    expect(playgroundSource).toContain("ComposerShell")
  })

  it("RoutingEngine source drops its failover/count cluster", () => {
    expect(routingSource).not.toContain("Failover")
    expect(routingSource).not.toContain("providers eligible")
  })

  it("RoutingEngine keeps heading, pill tabs, and all four panels", () => {
    expect(routingSource).toContain("Routing")
    expect(routingSource).toContain("PillTabs")
    for (const panel of ["ProviderRanks", "RouteSimulator", "RoutingStrategy", "ResiliencePolicy"]) {
      expect(routingSource).toContain(panel)
    }
    for (const tab of ["strategy", "simulator", "ranks", "resilience"]) {
      expect(routingSource).toContain(tab)
    }
  })

  it("playground DOM keeps heading, tabs, and composer with no page-level status", async () => {
    await renderAppAt("/playground")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText("8 of 8 providers")).toBeInTheDocument()
    })
    expect(screen.getByRole("heading", { name: "Search Playground" })).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/Search across all providers/i)).toBeInTheDocument()
    expect(screen.queryByText(/Fallback/)).toBeNull()
    expect(screen.getAllByText(/\d+ of \d+ providers/)).toHaveLength(1)
  })

  it("routing DOM keeps heading plus Strategy/Simulator/Ranks/Resilience with no page-level status", async () => {
    await renderAppAt("/routing")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText("8 of 8 providers")).toBeInTheDocument()
    })
    expect(screen.getByRole("heading", { name: "Routing" })).toBeInTheDocument()
    expect(screen.getAllByRole("tab")).toHaveLength(4)
    for (const label of ["Strategy", "Simulator", "Ranks", "Resilience"]) {
      expect(screen.getByRole("tab", { name: new RegExp(`^${label}$`) })).toBeInTheDocument()
    }
    expect(screen.getAllByText(/Failover (active|inactive)/)).toHaveLength(1)
  })
})

describe("AC-R1-9: edge states (loading neutral, error muted, 0-of-N)", () => {
  it("loading is neutral: bar present with no Failover claim until config resolves", async () => {
    const gate = deferred<Response>()
    installFetchStub((req) => {
      if (req.url === "/auth/jwt/refresh" && req.method === "POST") {
        return ok(accessResponseFixture())
      }
      if (req.url === "/users/me" && req.method === "GET") {
        return ok(adminAccountFixture())
      }
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(allProvidersFixture())
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return gate.promise as unknown as Response
      }
      if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <MemoryRouter initialEntries={["/playground"]}>
        <App />
      </MemoryRouter>
    )

    await screen.findByTestId("status-bar")
    const bar = screen.getByTestId("status-bar") as HTMLElement
    expect(bar.textContent ?? "").not.toMatch(/Failover (active|inactive)/)
    expect((bar.textContent ?? "").length).toBeGreaterThan(0)

    await act(async () => {
      gate.resolve(ok(routingConfigFixture()))
    })
    await waitFor(() => {
      expect(screen.getByText("Failover active")).toBeInTheDocument()
    })
  })

  it("StatusBar source branches on loading and error flags", () => {
    expect(statusBarSource()).toContain("Loading")
    expect(statusBarSource()).toContain("Error")
  })

  it("routing error is muted: counts stay, both Failover claims stay hidden", async () => {
    stubBackend({
      routingHandler: () => err(500, { detail: "routing store down" }),
    })
    render(
      <MemoryRouter initialEntries={["/routing"]}>
        <App />
      </MemoryRouter>
    )

    await screen.findByTestId("status-bar")
    await waitFor(() => {
      expect(screen.getByText("8 of 8 providers")).toBeInTheDocument()
    })
    expect(screen.queryByText("Failover active", { exact: true })).toBeNull()
    expect(screen.queryByText("Failover inactive", { exact: true })).toBeNull()
  })

  it('shows the exact "0 of 7 providers" edge when nothing is eligible', async () => {
    const disabled = allProvidersFixture().map((p) => ({ ...p, enable_mask: 0, enabled: false }))
    stubBackend({ providers: disabled as WireProviderStatus[] })
    render(
      <MemoryRouter initialEntries={["/playground"]}>
        <App />
      </MemoryRouter>
    )

    await screen.findByTestId("status-bar")
    await waitFor(() => {
      expect(barEl().textContent).toContain("0 of 8 providers")
    })
    expect(screen.queryByText(/Fallback/)).toBeNull()
  })
})

describe("AC-R1-10 regressions: ComposerShell, layouts, fetching, shell", () => {
  it("ComposerShell contract untouched (shared shell, exact tokens)", () => {
    expect(existsSync(sharedComposerShellPath)).toBe(true)
    expect(sharedComposerShellSource).toContain("ComposerShell")
    expect(sharedComposerShellSource).toContain("testIdPrefix")
    expect(sharedComposerShellSource).toContain("-composer-divider")
    expect(sharedComposerShellSource).toContain("-composer-footer")
    expect(sharedComposerShellSource).toContain("bg-[var(--elevated)]")
    expect(sharedComposerShellSource).toContain("rounded-xl")
    // Old common path was a compat shim over the shared owner (removed in CLEANUP 1.1).
    expect(existsSync(removedComposerShimPath)).toBe(false)
    expect(playgroundSource).toMatch(/testIdPrefix\s*=\s*["']fetch["']/)
    expect(playgroundSource).not.toMatch(/testIdPrefix\s*=\s*["']search["']/)
  })

  it("search + fetch hero layouts intact with the same docked transition", async () => {
    await renderAppAt("/playground")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
    const searchHero = screen.getByTestId("search-layout")
    expect(searchHero).toHaveAttribute("data-state", "hero")
    expect(searchHero.className).toMatch(/min-h-\[(55|60)vh\]/)
    expect(searchHero.className).toContain("max-w-3xl")

    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
    const fetchHero = screen.getByTestId("fetch-layout")
    expect(fetchHero).toHaveAttribute("data-state", "hero")
    expect(fetchHero.className).toMatch(/min-h-\[(55|60)vh\]/)
    expect(fetchHero.className).toContain("max-w-3xl")
    expect(screen.getByTestId("fetch-composer")).toBeInTheDocument()
  })

  it("live search round-trip still works beside the bar (fetching untouched)", async () => {
    const stub = stubBackend()
    render(
      <MemoryRouter initialEntries={["/playground"]}>
        <App />
      </MemoryRouter>
    )
    await screen.findByTestId("status-bar")
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search across all providers/i)).toBeInTheDocument()
    })

    const input = screen.getByPlaceholderText(
      /Search across all providers/i
    ) as HTMLInputElement
    fireEvent.change(input, { target: { value: "r1 guard query" } })
    fireEvent.submit(input.closest("form")!)

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(stub.requests.filter((r) => r.url === "/search" && r.method === "POST")).toHaveLength(1)
    expect(playgroundSource).toContain("runSearch")
    expect(playgroundSource).toContain("runFetch")
  })

  it("app shell intact: aside + main, five links (P1-FINAL: no providers page), no legacy header", async () => {
    await renderAppAt("/playground")
    expect(screen.getByTestId("status-bar")).toBeInTheDocument()
    expect(document.querySelector("aside")).not.toBeNull()
    expect(screen.getByRole("main")).toBeInTheDocument()
    expect(document.querySelector("header")).toBeNull()
    expect(
      within(screen.getByRole("navigation", { name: "Primary" })).getAllByRole("link")
    ).toHaveLength(7)
  })
})

describe("AC-R1-11: Agent without control reads", () => {
  it("shows Signed in with no provider, failover, or routing disclosures", async () => {
    stubBackend({ account: agentAccountFixture() })
    render(
      <MemoryRouter initialEntries={["/playground"]}>
        <App />
      </MemoryRouter>
    )

    const bar = await screen.findByTestId("status-bar")
    await waitFor(() => {
      expect(screen.getByText("Signed in", { exact: true })).toBeInTheDocument()
    })
    expect(bar.textContent).toContain("Signed in")
    expect(screen.queryByText(/\d+ of \d+ providers/)).toBeNull()
    expect(screen.queryByText(/Failover (active|inactive)/)).toBeNull()
    expect(screen.queryByText("Loading routing status", { exact: true })).toBeNull()
    expect(screen.queryByText("Routing status unavailable", { exact: true })).toBeNull()
  })
})
})
