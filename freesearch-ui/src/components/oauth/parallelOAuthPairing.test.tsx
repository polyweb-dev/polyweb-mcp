import React, { StrictMode } from "react"
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { useFreeSearch } from "@/context/useFreeSearch"
import { QuotaAnalytics } from "../quota/QuotaAnalytics"
// Relocated to src/components/oauth/ with the developer track per the
// architectural correction; QuotaAnalytics stays in ../quota/.
import { OAuthPairingModal } from "./OAuthPairingModal"
import type {
  BackendOAuthDeviceCode,
  BackendOAuthStatus,
} from "@/domains/providers/api/oauthWire"
import { ApiError } from "@/shared/api/http"
import { quotaDisplay } from "@/domains/dashboard"
import { installFetchStub, ok, err, deferred } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  canonicalQuotasFixture,
  type WireDashboardQuota,
} from "@/test/backendFixtures"

/**
 * ADVERSARIAL suite: Parallel OAuth device pairing.
 *
 * FROZEN CONTRACT under test:
 * - freesearchApi beginOAuthDeviceFlow/getOAuthStatus(404->unpaired)/revokeOAuth
 *   (see ../../services/api/oauthDeviceFlow.test.ts for the wire contract).
 * - Dashboard latest_quota carries the AUTHORITATIVE remaining-only USD row
 *   for a paired parallel; the UI surfaces it with an "authoritative" chip.
 * - UI grammar that must not regress: one signal per row, confidence chips,
 *   dark tokens, quota grid; ManualQuotaModal + QuotaRow manual overlay +
 *   quotaReviewSurfaces RF2/RF4 and QuotaAnalytics.test assertions stay green.
 * - data-testid convention oauth-device-* for every pairing control.
 *
 * SELECTOR POLICY: this suite drives the DEVELOPER's shipped testids so it
 * attacks real behaviour. The developer has converged the modal, dialog
 * wrapper, and disconnect family onto oauth-device-* (verified this round).
 * Finding F-TESTID-01 (row connect button outside oauth-device-*) is now
 * RESOLVED: the developer converged every pairing control, including the
 * row connect button (oauth-device-open-*) and the disconnect family, onto
 * oauth-device-*. Dialogs are selected via role="dialog" (the shipped
 * oauth-device-dialog wrapper is asserted present where relevant).
 *
 * ACTIVATION STRATEGY:
 * - Part A tests pinning ALREADY-SHIPPED behaviour run green today. Tests for
 *   the NEW paired-authoritative headline are describe.skipIf(!hasPairedHeadline)
 *   over the pure quotaDisplay() probe — zero edits to activate.
 * - Part B tests render the real QuotaAnalytics and probe at RUNTIME for the
 *   connect button; ctx.skip() keeps the suite green until the UI lands.
 * - Error mapping: load errors = begin/status failures (B4/B5); there is no
 *   "save" in device flow (begin IS the create); delete errors = revoke (B12).
 */

const T = {
  open: "oauth-device-open-parallel",
  dialog: "oauth-device-dialog",
  userCode: "oauth-device-user-code",
  copy: "oauth-device-copy",
  verifyLink: "oauth-device-open-verification",
  countdown: "oauth-device-countdown",
  error: "oauth-device-error",
  denied: "oauth-device-denied",
  expired: "oauth-device-expired",
  retry: "oauth-device-retry",
  cancel: "oauth-device-cancel",
  paired: "oauth-device-paired",
  unpair: "oauth-device-unpair",
  disconnect: "oauth-device-disconnect",
  confirmDisconnect: "oauth-device-confirm-disconnect",
  disconnectError: "oauth-device-disconnect-error",
} as const

const OAUTH_PATHS = {
  deviceCode: "/api/v1/providers/parallel/oauth/device-code",
  status: "/api/v1/providers/parallel/oauth/status",
  revoke: "/api/v1/providers/parallel/oauth",
} as const

const OBSERVED_AT = "2026-09-06T18:20:00Z"

const DEVICE_CODE_WIRE = {
  provider: "parallel",
  user_code: "ABCD-EFGH",
  verification_uri: "https://parallel.ai/activate",
  verification_uri_complete: "https://parallel.ai/activate?code=ABCD-EFGH",
  expires_in: 300,
  interval: 1,
}

const UNBUDGETED_PARALLEL_ROW: WireDashboardQuota = {
  provider: "parallel",
  source: "estimated",
  observed_at: OBSERVED_AT,
  remaining: null,
  limit: null,
  reset_at: null,
  unit_kind: "USD",
  display_unit: "USD",
}

/** Frozen paired shape: AUTHORITATIVE, remaining-only USD, no limit. */
const PAIRED_PARALLEL_ROW: WireDashboardQuota = {
  provider: "parallel",
  source: "authoritative",
  observed_at: OBSERVED_AT,
  remaining: "3.75",
  limit: null,
  reset_at: null,
  unit_kind: "USD",
  display_unit: "USD",
}

const SEEDED_PARALLEL_ROW: WireDashboardQuota = {
  provider: "parallel",
  source: "estimated",
  observed_at: OBSERVED_AT,
  remaining: "3.75",
  limit: "5.00",
  reset_at: null,
  unit_kind: "USD",
  display_unit: "USD",
}

const YOU_BALANCE_ROW: WireDashboardQuota = {
  provider: "you",
  source: "estimated",
  observed_at: OBSERVED_AT,
  remaining: "199.77",
  limit: null,
  reset_at: null,
  unit_kind: "USD",
  display_unit: "USD",
}

const CHIP_TITLES = [
  "Polled directly from the vendor",
  "Observed from vendor response headers or local counters",
  "Estimated locally; not a vendor balance",
]

/** One signal per row: count rendered confidence chips inside a row element. */
function chipCount(root: Element): number {
  return Array.from(root.querySelectorAll("span")).filter((span) =>
    CHIP_TITLES.includes(span.getAttribute("title") ?? "")
  ).length
}

/** Anchor the Parallel quota row via its per-provider headline testid. */
function parallelRow(): Element {
  const marker =
    document.querySelector('[data-testid="quota-remaining-percent-parallel"]') ??
    document.querySelector('[data-testid="manual-quota-estimate-parallel"]')
  expect(marker, "parallel quota row marker must exist").not.toBeNull()
  const row = marker!.closest("tr") ?? marker!.closest("div.grid")
  expect(row, "parallel quota row root must exist").not.toBeNull()
  return row!
}

async function waitForParallelRow(): Promise<Element> {
  await screen.findByTestId("quota-remaining-percent-parallel", undefined, {
    timeout: 10_000,
  })
  return parallelRow()
}

function quotaSection(): HTMLElement {
  return screen.getByText("Provider quota view", { exact: true }).closest("section")!
}

function quotaRows(): Element[] {
  const section = quotaSection()
  const body = section.querySelector('tbody[data-slot="table-body"]') ?? section.querySelector("tbody")
  expect(body, "quota table body must exist").not.toBeNull()
  return Array.from(body!.querySelectorAll("tr"))
}

/** Find the quota row that renders a fixture-controlled native value. */
function rowWithValue(value: string): Element {
  const row = quotaRows().find((candidate) => candidate.textContent?.includes(value))
  expect(row, `expected a quota row rendering "${value}"`).toBeDefined()
  return row!
}

/** Collection-time probe for the NEW paired-authoritative headline. */
function pairedAuthoritativeSupported(): boolean {
  const display = quotaDisplay({
    remaining: "3.75",
    remainingPercent: null,
    limit: null,
    unitKind: "USD",
    displayUnit: "USD",
    confidence: "authoritative",
    resetAt: null,
    providerId: "parallel",
  })
  return display.headline !== "Budget not configured"
}

const hasPairedHeadline = pairedAuthoritativeSupported()

let errSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  errSpy = vi.spyOn(console, "error").mockImplementation(() => {})
})

afterEach(() => {
  errSpy.mockRestore()
  cleanup()
  vi.unstubAllGlobals()
})

function renderUsage(rows: WireDashboardQuota[]) {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture({ latest_quota: rows }))
    if (req.url.endsWith("/manual-quota")) {
      if (req.method === "GET") return err(404, { detail: "no manual quota" })
      return err(500, { detail: "unexpected manual write" })
    }
    return err(404, { detail: `unhandled test route ${req.method} ${req.url}` })
  })
  return render(
    <FreeSearchProvider>
      <QuotaAnalytics />
    </FreeSearchProvider>
  )
}

// ---------------------------------------------------------------------------
// Part A: headline branches — authoritative-balance vs unbudgeted vs seeded
// vs You.com, with no cross-talk in any direction.
// ---------------------------------------------------------------------------

describe("paired-parallel headline branches (no cross-talk)", () => {
  describe.skipIf(!hasPairedHeadline)("authoritative remaining-only USD", () => {
    it("chips authoritative, never claims the budget is unconfigured", async () => {
      renderUsage([PAIRED_PARALLEL_ROW])
      await screen.findAllByText(/3\.75/)

      const row = parallelRow()
      expect(row.textContent).toContain("authoritative")
      expect(row.textContent).toContain("Balance available")
      expect(row.textContent).toContain("Account balance")
      expect(row.textContent).not.toContain("Budget not configured")
      expect(screen.queryByTestId("quota-explainer-parallel")).toBeNull()
      // No invented manual overlay and no percentage without a limit.
      expect(screen.queryByTestId("manual-quota-estimate-parallel")).toBeNull()
      expect(row.querySelector('[role="progressbar"]')).toBeNull()
      expect(chipCount(row)).toBe(1)
    })

    it("leaves Brave/Tavily/You.com rows untouched (no cross-talk either way)", async () => {
      renderUsage([...canonicalQuotasFixture(), PAIRED_PARALLEL_ROW])
      await screen.findAllByText(/3\.75/)

      const braveRow = rowWithValue("950/1000 requests")
      expect(braveRow.textContent).toContain("95% remaining")
      const tavilyRow = rowWithValue("90000.05/100000.10 credits")
      expect(tavilyRow.textContent).toContain("90% remaining")
      const youRow = rowWithValue("4.75")
      expect(youRow.textContent).toContain("Balance available")
      const pairedRow = parallelRow()
      expect(pairedRow.textContent).toContain("authoritative")
      expect(pairedRow.textContent).not.toContain("Budget not configured")
    })
  })

  it("unbudgeted parallel keeps Budget not configured + explainer (no regress)", async () => {
    renderUsage([UNBUDGETED_PARALLEL_ROW])
    const row = await waitForParallelRow()

    expect(row.textContent).toContain("Budget not configured")
    expect(row.textContent).toContain("Monthly")
    expect(screen.getByTestId("quota-explainer-parallel")).toHaveTextContent(
      /no api-key balance endpoint/i
    )
    // The empty snapshot still carries its source signal (estimated).
    expect(chipCount(row)).toBe(1)
    expect(row.textContent).toContain("estimated")
  })

  it("seeded parallel keeps its percent headline, never a balance (no regress)", async () => {
    renderUsage([SEEDED_PARALLEL_ROW])
    await screen.findAllByText(/3\.75/)

    const row = rowWithValue("3.75/5.00 USD")
    expect(row.textContent).toContain("75% remaining")
    expect(row.textContent).toContain("Monthly")
    expect(row.textContent).not.toContain("Balance available")
    expect(screen.queryByTestId("quota-explainer-parallel")).toBeNull()
    expect(chipCount(row)).toBe(1)
  })

  it("You.com remaining USD stays an account balance (no regress)", async () => {
    renderUsage([YOU_BALANCE_ROW])
    await screen.findAllByText(/199\.77/)

    const row = rowWithValue("199.77")
    expect(row.textContent).toContain("Balance available")
    expect(row.textContent).toContain("Account balance")
    expect(row.textContent).not.toContain("Budget not configured")
    expect(chipCount(row)).toBe(1)
  })

  it("every quota row carries at most one confidence signal", async () => {
    renderUsage([...canonicalQuotasFixture(), UNBUDGETED_PARALLEL_ROW])
    await screen.findByText("Provider quota view", { exact: true })
    await waitFor(() => {
      expect(quotaRows().length).toBe(8)
    })

    const rows = quotaRows()
    expect(rows.length).toBe(8)
    let signalled = 0
    for (const row of rows) {
      const count = chipCount(row)
      expect(count, `row "${row.textContent?.slice(0, 40)}" leaks signals`).toBeLessThanOrEqual(1)
      if (count === 1) signalled += 1
    }
    // Tavily + Brave + You.com + Exa snapshots + the unbudgeted Parallel
    // source row; Keenable and Firecrawl rows are "—".
    expect(signalled).toBe(5)
  })
})

// ---------------------------------------------------------------------------
// Part B: pairing state machine. Each test probes for the connect button and
// ctx.skip()s while the developer UI is absent — zero edits to activate.
// ---------------------------------------------------------------------------

type StatusScriptEntry = string | { error: { status: number; body: unknown } }

interface PairingStubOptions {
  dashboardRows?: WireDashboardQuota[]
  /** Row-mount status load (useOAuthStatus): 404 unpaired by default. */
  rowStatus?: { kind: "unpaired404" } | { kind: "status"; status: string }
  /** Shifted per MODAL status GET; the final entry repeats forever. */
  statusScript?: StatusScriptEntry[]
  beginScript?: Array<"ok" | { error: { status: number; body: unknown } }>
  beginGate?: ReturnType<typeof deferred<Response>>
  revokeError?: { status: number; body: unknown }
  deviceCode?: Partial<typeof DEVICE_CODE_WIRE>
  /** Flip the dashboard to the paired row the moment "ready" is served. */
  autoPairOnReady?: boolean
}

function installPairingStubs(options: PairingStubOptions = {}) {
  const statusScript: StatusScriptEntry[] = [
    ...(options.statusScript ?? ["pending", "pending", "ready"]),
  ]
  let lastStatus: StatusScriptEntry = "pending"
  let statusCalls = 0
  let deviceCodeCalls = 0
  let revoked = false
  const rowStatus = options.rowStatus ?? { kind: "unpaired404" as const }
  const beginScript = [
    ...(options.beginScript ?? (["ok"] as Array<"ok" | { error: { status: number; body: unknown } }>)),
  ]
  let dashboardRows = options.dashboardRows ?? [UNBUDGETED_PARALLEL_ROW]

  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) {
      return ok(dashboardFixture({ latest_quota: dashboardRows }))
    }
    if (req.url.endsWith("/manual-quota")) {
      if (req.method === "GET") return err(404, { detail: "no manual quota" })
      return err(500, { detail: "unexpected manual write" })
    }
    if (req.url === OAUTH_PATHS.deviceCode && req.method === "POST") {
      deviceCodeCalls += 1
      if (options.beginGate) return options.beginGate.promise
      const next = beginScript.length > 0 ? beginScript.shift()! : "ok"
      if (next !== "ok") return err(next.error.status, next.error.body)
      return ok({ ...DEVICE_CODE_WIRE, ...(options.deviceCode ?? {}) })
    }
    if (req.url === OAUTH_PATHS.status && req.method === "GET") {
      statusCalls += 1
      if (revoked) return err(404, { detail: "no oauth pairing for 'parallel'" })
      if (statusCalls === 1) {
        // Row-mount load: deterministic, never consumes the modal script.
        if (rowStatus.kind === "unpaired404") {
          return err(404, { detail: "no oauth pairing for 'parallel'" })
        }
        return ok({ provider: "parallel", status: rowStatus.status, expires_in: null })
      }
      const next = statusScript.length > 0 ? statusScript.shift()! : lastStatus
      lastStatus = next
      if (typeof next === "string") {
        if (next === "ready" && options.autoPairOnReady !== false) {
          dashboardRows = [PAIRED_PARALLEL_ROW]
        }
        return ok({ provider: "parallel", status: next, expires_in: 299 })
      }
      return err(next.error.status, next.error.body)
    }
    if (req.url === OAUTH_PATHS.revoke && req.method === "DELETE") {
      if (options.revokeError) return err(options.revokeError.status, options.revokeError.body)
      // A real revoke flips the next dashboard refresh to the unbudgeted row
      // and all later status loads back to unpaired.
      revoked = true
      dashboardRows = [UNBUDGETED_PARALLEL_ROW]
      return ok({ provider: "parallel", deleted: true })
    }
    return err(404, { detail: `unhandled test route ${req.method} ${req.url}` })
  })

  return {
    stub,
    statusCalls: () => statusCalls,
    deviceCodeCalls: () => deviceCodeCalls,
    dashboardCalls: () => stub.requestsTo(/\/dashboard/).length,
    revokeCalls: () => stub.requestsTo(OAUTH_PATHS.revoke).length,
  }
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

/** Render /usage and return the pairing entry button, or ctx.skip() pre-SUT. */
async function openPairingOrSkip(ctx: { skip: () => never }) {
  await waitForParallelRow()
  const openBtn = screen.queryByTestId(T.open)
  if (!openBtn) {
    errSpy.mockClear()
    ctx.skip()
    throw new Error("unreachable: ctx.skip() always throws")
  }
  errSpy.mockClear()
  fireEvent.click(openBtn)
  const dialog = await screen.findByRole("dialog", undefined, { timeout: 10_000 })
  expect(within(dialog).getByTestId(T.dialog)).toBeInTheDocument()
  return { openBtn, dialog }
}

function dialogByRole(): HTMLElement {
  return within(document.body).getByRole("dialog")
}

const RefreshProbe: React.FC = () => {
  const { refreshDashboard } = useFreeSearch()
  return (
    <button type="button" data-testid="probe-refresh" onClick={() => void refreshDashboard()}>
      probe refresh
    </button>
  )
}

describe("parallel OAuth pairing state machine", () => {
  it("pending poll -> ready auto-closes and refreshes the authoritative balance", async (ctx) => {
    const harness = installPairingStubs({ statusScript: ["pending", "pending", "ready"] })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const { dialog } = await openPairingOrSkip(ctx)

    expect(within(dialog).getByTestId(T.userCode)).toHaveTextContent("ABCD-EFGH")

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), { timeout: 15_000 })
    await waitFor(() => {
      expect(parallelRow().textContent).toContain("authoritative")
    })
    expect(harness.dashboardCalls()).toBeGreaterThanOrEqual(2)

    // Polling stops after the terminal state: no stray intervals.
    const pollsAtClose = harness.statusCalls()
    expect(pollsAtClose).toBeGreaterThanOrEqual(3)
    await sleep(2500)
    expect(harness.statusCalls()).toBe(pollsAtClose)
    expect(errSpy).not.toHaveBeenCalled()
  }, 30_000)

  it("denied stops polling, keeps the dialog open, and retry re-begins to ready", async (ctx) => {
    const harness = installPairingStubs({
      statusScript: ["pending", "denied", "pending", "ready"],
    })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const { dialog } = await openPairingOrSkip(ctx)
    expect(within(dialog).getByTestId(T.userCode)).toHaveTextContent("ABCD-EFGH")

    await within(dialog).findByTestId(T.denied, undefined, { timeout: 10_000 })
    expect(screen.queryByRole("dialog")).toBeInTheDocument()
    const retry = within(dialog).getByTestId(T.retry)
    expect(retry).toBeEnabled()

    // Terminal denial must not spin: the poll count settles.
    const pollsAtDenied = harness.statusCalls()
    await sleep(2500)
    expect(harness.statusCalls()).toBe(pollsAtDenied)

    fireEvent.click(retry)
    expect(harness.deviceCodeCalls()).toBe(2)
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), { timeout: 15_000 })
    expect(errSpy).not.toHaveBeenCalled()
  }, 30_000)

  it("expired offers a retry that re-begins the flow", async (ctx) => {
    const harness = installPairingStubs({ statusScript: ["expired"] })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const { dialog } = await openPairingOrSkip(ctx)

    await within(dialog).findByTestId(T.expired, undefined, { timeout: 10_000 })
    const retry = within(dialog).getByTestId(T.retry)
    expect(retry).toBeEnabled()
    expect(screen.queryByRole("dialog")).toBeInTheDocument()

    fireEvent.click(retry)
    expect(harness.deviceCodeCalls()).toBe(2)
    // The re-begun flow replays the terminal script entry and stays expired.
    await within(dialogByRole()).findByTestId(T.expired, undefined, { timeout: 10_000 })
    expect(errSpy).not.toHaveBeenCalled()
  }, 20_000)

  it("begin failure surfaces the ApiError detail as an alert with no modal polling", async (ctx) => {
    const harness = installPairingStubs({
      beginScript: [
        { error: { status: 503, body: { detail: "parallel oauth unavailable" } } },
        "ok",
      ],
      statusScript: ["pending", "ready"],
    })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const { dialog } = await openPairingOrSkip(ctx)

    const alert = await within(dialog).findByRole("alert", undefined, { timeout: 10_000 })
    expect(alert.textContent).toContain("parallel oauth unavailable")
    expect(within(dialog).getByTestId(T.error)).toBeInTheDocument()
    // Only the row-mount status load happened; the failed begin polls nothing.
    const pollsAfterError = harness.statusCalls()
    await sleep(1500)
    expect(harness.statusCalls()).toBe(pollsAfterError)

    // Retry recovers without reopening: the second begin succeeds.
    fireEvent.click(within(dialog).getByTestId(T.retry))
    expect(harness.deviceCodeCalls()).toBe(2)
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), { timeout: 15_000 })
    expect(errSpy).not.toHaveBeenCalled()
  }, 30_000)

  it("transient status failure never crashes the row", async (ctx) => {
    const harness = installPairingStubs({
      statusScript: [
        "pending",
        { error: { status: 500, body: { detail: "oauth store exploded" } } },
        "ready",
      ],
    })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const { dialog } = await openPairingOrSkip(ctx)
    expect(within(dialog).getByTestId(T.userCode)).toHaveTextContent("ABCD-EFGH")

    // Either the error is surfaced (and polling settles) or the flow rides
    // through to ready — both are defensible, but the row must survive with
    // no unhandled rejection. (CONTRACT GAP: transient poll-failure
    // semantics are unspecified; flagged in the Phase-1 report.)
    await waitFor(
      () => {
        const closed = screen.queryByRole("dialog") === null
        const alerted = screen.queryByTestId(T.error) !== null
        expect(closed || alerted).toBe(true)
      },
      { timeout: 15_000 }
    )
    if (screen.queryByTestId(T.error) !== null) {
      const settled = harness.statusCalls()
      await sleep(2000)
      expect(harness.statusCalls()).toBe(settled)
    }
    expect(harness.statusCalls()).toBeGreaterThanOrEqual(2)
    expect(screen.getByText("Provider quota view")).toBeInTheDocument()
  }, 30_000)

  it("begin pending disables everything and never fires a duplicate request", async (ctx) => {
    const gate = deferred<Response>()
    const harness = installPairingStubs({ beginGate: gate })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    await waitForParallelRow()
    const openBtn = screen.queryByTestId(T.open)
    if (!openBtn) {
      ctx.skip()
      return
    }
    errSpy.mockClear()

    fireEvent.click(openBtn)
    fireEvent.click(openBtn)
    await sleep(300)
    expect(harness.deviceCodeCalls()).toBe(1)

    // While begin is pending, the exit hatch stays enabled (the developer
    // lifted the starting-disable after the Phase-1 round) while retry is
    // absent: nothing to retry before the first attempt settles.
    const dialog = screen.queryByRole("dialog")
    if (dialog) {
      expect(within(dialog).getByTestId(T.cancel)).toBeEnabled()
      expect(within(dialog).queryByTestId(T.retry)).toBeNull()
    }

    gate.resolve(ok(DEVICE_CODE_WIRE))
    await screen.findByTestId(T.userCode, undefined, { timeout: 10_000 })
    expect(screen.getByTestId(T.cancel)).toBeEnabled()
    expect(errSpy).not.toHaveBeenCalled()
  }, 20_000)

  it("unmount during polling stops all polls with no setState-after-unmount noise", async (ctx) => {
    const harness = installPairingStubs({ statusScript: ["pending"] })
    const view = render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    await waitForParallelRow()
    const openBtn = screen.queryByTestId(T.open)
    if (!openBtn) {
      ctx.skip()
      return
    }
    errSpy.mockClear()
    fireEvent.click(openBtn)
    await screen.findByTestId(T.userCode, undefined, { timeout: 10_000 })
    // Row-mount load + begin have fired; the first modal poll lands on the
    // server interval (1s), so only the row call is guaranteed here.
    expect(harness.statusCalls()).toBeGreaterThanOrEqual(1)

    view.unmount()
    const pollsAtUnmount = harness.statusCalls()
    await sleep(2500)
    expect(harness.statusCalls()).toBe(pollsAtUnmount)
    expect(errSpy).not.toHaveBeenCalled()
  }, 20_000)

  it("cancel during polling stops all polls and closes the dialog", async (ctx) => {
    const harness = installPairingStubs({ statusScript: ["pending"] })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const { dialog } = await openPairingOrSkip(ctx)
    await screen.findByTestId(T.userCode, undefined, { timeout: 10_000 })
    expect(harness.statusCalls()).toBeGreaterThanOrEqual(1)

    fireEvent.click(within(dialog).getByTestId(T.cancel))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    const pollsAtCancel = harness.statusCalls()
    await sleep(2500)
    expect(harness.statusCalls()).toBe(pollsAtCancel)
    expect(errSpy).not.toHaveBeenCalled()
  }, 20_000)

  it("countdown ticks down and a short expiry surfaces the expired state", async (ctx) => {
    const harness = installPairingStubs({
      deviceCode: { expires_in: 4, interval: 1 },
      statusScript: ["pending"],
    })
    expect(harness).toBeDefined()
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const { dialog } = await openPairingOrSkip(ctx)

    const countdown = within(dialog).getByTestId(T.countdown)
    expect(countdown.textContent?.trim()).not.toBe("")
    const first = countdown.textContent ?? ""
    // The 1s tick timer fires on wall-clock time outside act(); act-wrap
    // the sleep so only non-act console noise can fail this test below.
    await act(async () => {
      await sleep(2200)
    })
    const second = within(dialogByRole()).getByTestId(T.countdown).textContent ?? ""
    expect(second, "countdown must tick while pending").not.toBe(first)
    // The client must enforce expires_in locally: perpetual "pending" from
    // the server still ends in the expired UI once the window lapses.
    await waitFor(
      () => {
        const terminal =
          screen.queryByTestId(T.expired) ?? screen.queryByTestId(T.error)
        expect(terminal, "expected the expired terminal state").not.toBeNull()
      },
      { timeout: 12_000 }
    )
    expect(screen.getByTestId(T.retry)).toBeEnabled()
    // Wall-clock expiry transitions land outside act() by nature; assert
    // silence only for non-act noise (unmount silence is pinned by B7/B8).
    const nonActNoise = errSpy.mock.calls.filter(
      (args: unknown[]) => !String(args[0]).includes("not wrapped in act")
    )
    expect(nonActNoise).toEqual([])
  }, 30_000)

  it("dialog meets the a11y contract: roles, labels, progressbar, keyboard", async (ctx) => {
    const user = userEvent.setup()
    installPairingStubs({ statusScript: ["pending"] })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const { dialog } = await openPairingOrSkip(ctx)

    // Dialog semantics: role + accessible name.
    const dialogRole = within(document.body).getByRole("dialog")
    expect(dialogRole).toBeInTheDocument()
    expect(
      dialogRole.getAttribute("aria-label") ?? dialogRole.getAttribute("aria-labelledby")
    ).toBeTruthy()

    // User code is labelled; copy and verification link are reachable.
    const code = within(dialog).getByTestId(T.userCode)
    expect(code.textContent?.trim()).not.toBe("")
    expect(code.getAttribute("aria-labelledby")).not.toBeNull()
    const copy = within(dialog).getByTestId(T.copy)
    expect(copy).toBeEnabled()
    const link = within(dialog).getByTestId(T.verifyLink)
    expect(link.getAttribute("href")).toBe(DEVICE_CODE_WIRE.verification_uri_complete)

    // Countdown progressbar carries full range semantics (F-A11Y-01).
    const bars = within(dialog).getAllByRole("progressbar")
    expect(bars.length).toBeGreaterThanOrEqual(1)
    for (const bar of bars) {
      expect(bar.getAttribute("aria-valuemin")).toBe("0")
      expect(bar.getAttribute("aria-valuemax")).not.toBeNull()
      expect(bar.getAttribute("aria-valuenow")).not.toBeNull()
    }

    // Keyboard: Tab reaches copy, verification link, and cancel; Esc closes.
    // The in-dialog cycle also passes the Radix close button and focus-guard
    // sentinels, so walk until every target has been focused (start phase
    // varies with the autofocus + tick timing).
    const seen = new Set<string>()
    const wanted = [T.copy, T.verifyLink, T.cancel]
    for (
      let tab = 0;
      tab < 30 && !wanted.every((id) => seen.has(id));
      tab += 1
    ) {
      await user.tab()
      const active = document.activeElement as HTMLElement | null
      const testid = active?.getAttribute("data-testid") ?? active?.tagName ?? ""
      seen.add(testid)
    }
    expect([...seen].join(" ")).toContain(T.copy)
    expect([...seen].join(" ")).toContain(T.verifyLink)
    expect([...seen].join(" ")).toContain(T.cancel)

    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(errSpy).not.toHaveBeenCalled()
  }, 30_000)

  it("parent re-render while pending never restarts the device flow (F-RESTART-01)", async (ctx) => {
    const harness = installPairingStubs({
      deviceCode: { expires_in: 300, interval: 60 },
      statusScript: ["pending"],
    })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
        <RefreshProbe />
      </FreeSearchProvider>
    )
    const { dialog } = await openPairingOrSkip(ctx)
    await screen.findByTestId(T.userCode, undefined, { timeout: 10_000 })
    expect(harness.deviceCodeCalls()).toBe(1)

    // A dashboard refresh re-renders every row with fresh inline callbacks.
    // act() keeps the refresh state flushes warning-free; a restarted flow
    // still shows up as a second device-code POST.
    await act(async () => {
      fireEvent.click(screen.getByTestId("probe-refresh"))
      await sleep(1000)
    })
    expect(harness.deviceCodeCalls()).toBe(1)
    // The flow was not restarted: no starting spinner, code still showing.
    expect(within(dialogByRole()).getByTestId(T.userCode)).toHaveTextContent("ABCD-EFGH")
    expect(dialog.isConnected).toBe(true)
    expect(errSpy).not.toHaveBeenCalled()
  }, 20_000)

  it("StrictMode effect remount still completes begin (F-STRICT-01, dev-mode guard)", async () => {
    const device: BackendOAuthDeviceCode = { ...DEVICE_CODE_WIRE }
    const beginFlow = vi.fn(async (): Promise<BackendOAuthDeviceCode> => device)
    const checkStatus = vi.fn(
      async (): Promise<BackendOAuthStatus> => ({
        provider: "parallel",
        status: "pending",
        expires_in: 299,
      })
    )
    render(
      <StrictMode>
        <OAuthPairingModal
          open
          providerId="parallel"
          providerName="Parallel"
          onClose={() => {}}
          onPaired={async () => {}}
          beginFlow={beginFlow}
          checkStatus={checkStatus}
          statusPollMs={50}
        />
      </StrictMode>
    )
    const code = await screen.findByTestId(T.userCode, undefined, {
      timeout: 10_000,
    })
    expect(code).toHaveTextContent("ABCD-EFGH")
    expect(errSpy).not.toHaveBeenCalled()
  }, 20_000)

  it("disconnect revokes the pairing and restores the unbudgeted explainer", async (ctx) => {
    const harness = installPairingStubs({
      dashboardRows: [PAIRED_PARALLEL_ROW],
      rowStatus: { kind: "status", status: "ready" },
    })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    await screen.findAllByText(/3\.75/)
    // The row-mount status round-trip lands after the dashboard rows; wait
    // briefly before declaring the UI absent.
    const disconnectBtn = await screen
      .findByTestId(T.disconnect, undefined, { timeout: 5000 })
      .catch(() => null)
    if (!disconnectBtn) {
      ctx.skip()
      return
    }
    errSpy.mockClear()

    fireEvent.click(disconnectBtn)
    const confirm = screen.queryByTestId(T.confirmDisconnect)
    if (confirm) fireEvent.click(confirm)

    await waitFor(() => expect(harness.revokeCalls()).toBe(1), { timeout: 10_000 })
    await waitFor(() =>
      expect(parallelRow().textContent).toContain("Budget not configured")
    )
    expect(screen.getByTestId("quota-explainer-parallel")).toBeInTheDocument()
    // The post-revoke status reload (unpaired) lands a beat after the
    // dashboard refresh; the button hides once it settles.
    await waitFor(() => expect(screen.queryByTestId(T.disconnect)).toBeNull(), {
      timeout: 10_000,
    })
    expect(errSpy).not.toHaveBeenCalled()
  }, 20_000)

  it("revoke failure keeps the pairing and surfaces an alert", async (ctx) => {
    installPairingStubs({
      dashboardRows: [PAIRED_PARALLEL_ROW],
      rowStatus: { kind: "status", status: "ready" },
      revokeError: { status: 500, body: { detail: "revoke exploded" } },
    })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    await screen.findAllByText(/3\.75/)
    // The row-mount status round-trip lands after the dashboard rows; wait
    // briefly before declaring the UI absent.
    const disconnectBtn = await screen
      .findByTestId(T.disconnect, undefined, { timeout: 5000 })
      .catch(() => null)
    if (!disconnectBtn) {
      ctx.skip()
      return
    }
    errSpy.mockClear()

    fireEvent.click(disconnectBtn)
    const confirm = screen.queryByTestId(T.confirmDisconnect)
    if (confirm) fireEvent.click(confirm)

    const alert = await screen.findByRole("alert", undefined, { timeout: 10_000 })
    expect(alert.textContent).toContain("revoke exploded")
    // Still paired: the authoritative row survives the failed revoke.
    expect(parallelRow().textContent).toContain("authoritative")
    expect(errSpy).not.toHaveBeenCalled()
  }, 20_000)
})
describe("409 conflict + in-modal unpair (round 2)", () => {
  it("authoritative snapshot alone offers Disconnect when status is unreachable", async (ctx) => {
    // Row-mount status load 404s; the paired snapshot is pairing evidence.
    installPairingStubs({ dashboardRows: [PAIRED_PARALLEL_ROW] })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    await screen.findAllByText(/3\.75/)
    const disconnectBtn = await screen
      .findByTestId(T.disconnect, undefined, { timeout: 5000 })
      .catch(() => null)
    if (!disconnectBtn) {
      ctx.skip()
      return
    }
    errSpy.mockClear()
    expect(screen.queryByTestId(T.open)).toBeNull()
    expect(parallelRow().textContent).toContain("authoritative")
    expect(errSpy).not.toHaveBeenCalled()
  }, 20_000)

  it("409 surfaces Already-connected-elsewhere; explicit Disconnect unlocks retry, never auto-POSTs", async (ctx) => {
    const harness = installPairingStubs({
      beginScript: [
        { error: { status: 409, body: { detail: "already paired elsewhere" } } },
        "ok",
      ],
      statusScript: ["pending"],
    })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const { dialog } = await openPairingOrSkip(ctx)

    const paired = await within(dialog).findByTestId(T.paired, undefined, {
      timeout: 10_000,
    })
    expect(paired.textContent).toMatch(/already connected elsewhere/i)
    // No retry before an explicit disconnect; no auto-POST loop while paired.
    expect(within(dialog).queryByTestId(T.retry)).toBeNull()
    expect(harness.deviceCodeCalls()).toBe(1)
    await sleep(1500)
    expect(harness.deviceCodeCalls()).toBe(1)

    // In-modal Disconnect (the row provides onRevokePairing) unlocks retry.
    const unpair = within(dialogByRole()).getByTestId(T.unpair)
    expect(unpair).toBeEnabled()
    fireEvent.click(unpair)
    await waitFor(
      () =>
        expect(
          within(dialogByRole()).getByText(/disconnected\. get a new code/i)
        ).toBeInTheDocument(),
      { timeout: 10_000 }
    )
    const retry = within(dialogByRole()).getByTestId(T.retry)
    expect(retry).toBeEnabled()

    fireEvent.click(retry)
    expect(harness.deviceCodeCalls()).toBe(2)
    await screen.findByTestId(T.userCode, undefined, { timeout: 10_000 })
    expect(errSpy).not.toHaveBeenCalled()
  }, 30_000)

  it("409 without onRevokePairing explains manual disconnect and never auto-POSTs", async () => {
    const beginFlow = vi.fn(async (): Promise<BackendOAuthDeviceCode> => {
      throw new ApiError(409, "already paired elsewhere", {})
    })
    const checkStatus = vi.fn(
      async (): Promise<BackendOAuthStatus> => ({
        provider: "parallel",
        status: "pending",
        expires_in: 299,
      })
    )
    render(
      <OAuthPairingModal
        open
        providerId="parallel"
        providerName="Parallel"
        onClose={() => {}}
        onPaired={async () => {}}
        beginFlow={beginFlow}
        checkStatus={checkStatus}
      />
    )
    const paired = await screen.findByTestId(T.paired, undefined, {
      timeout: 10_000,
    })
    expect(paired.textContent).toMatch(/already connected elsewhere/i)
    expect(paired.textContent).toMatch(/disconnect it from the connected session/i)
    expect(screen.queryByTestId(T.unpair)).toBeNull()
    expect(screen.queryByTestId(T.retry)).toBeNull()
    expect(checkStatus).not.toHaveBeenCalled()
    await sleep(1500)
    expect(beginFlow).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole("dialog")).toBeInTheDocument()
    expect(errSpy).not.toHaveBeenCalled()
  }, 20_000)

  it("in-modal Disconnect failure surfaces an alert and stays paired", async (ctx) => {
    const harness = installPairingStubs({
      beginScript: [{ error: { status: 409, body: { detail: "already paired" } } }],
      revokeError: { status: 500, body: { detail: "revoke exploded" } },
    })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const { dialog } = await openPairingOrSkip(ctx)
    await within(dialog).findByTestId(T.paired, undefined, { timeout: 10_000 })

    fireEvent.click(within(dialogByRole()).getByTestId(T.unpair))
    const alert = await within(dialogByRole()).findByRole("alert", undefined, {
      timeout: 10_000,
    })
    expect(alert.textContent).toContain("revoke exploded")
    // Still paired: no retry, unpair still offered, no extra begin.
    expect(within(dialogByRole()).queryByTestId(T.retry)).toBeNull()
    expect(within(dialogByRole()).getByTestId(T.unpair)).toBeEnabled()
    expect(harness.deviceCodeCalls()).toBe(1)
    expect(errSpy).not.toHaveBeenCalled()
  }, 20_000)

  it("RFC 8628: interval/expires_in are seconds — first poll waits out the interval", async (ctx) => {
    const harness = installPairingStubs({
      deviceCode: { expires_in: 300, interval: 3 },
      statusScript: ["pending"],
    })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const { dialog } = await openPairingOrSkip(ctx)
    expect(dialog).toBeInTheDocument()
    await screen.findByTestId(T.userCode, undefined, { timeout: 10_000 })
    // Row-mount load is the only status call so far; a milliseconds reading
    // of interval:3 would already have fired a poll storm.
    expect(harness.statusCalls()).toBe(1)
    await sleep(1500)
    expect(harness.statusCalls()).toBe(1)
    // …while the seconds reading lands the first modal poll at ~3s.
    await waitFor(() => expect(harness.statusCalls()).toBeGreaterThanOrEqual(2), {
      timeout: 10_000,
    })
    expect(screen.queryByRole("dialog")).toBeInTheDocument()
    expect(errSpy).not.toHaveBeenCalled()
  }, 20_000)
})

